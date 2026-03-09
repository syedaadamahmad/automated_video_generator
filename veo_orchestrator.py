"""
veo_orchestrator.py — Prompt Decomposition + Clip Generation + Stitching
═════════════════════════════════════════════════════════════════════════

Responsibilities:
  1. Decompose long prompts into N x 8s sub-prompts (Veo hard clip limit)
  2. Generate each clip sequentially via VeoGenerator
  3. Stitch clips into a single output video via FFmpeg

Veo 3.1 generates video and audio natively in one API call.
No audio stripping, mixing, or post-processing is needed here.

Decomposition strategy:
  - duration <= 8s  -> 1 clip, prompt used verbatim
  - duration >  8s  -> n_clips = ceil(duration / 8), sub-prompts from decomposer

Result shape (returned by generate_for_prompt):
  {
    status:           "completed" | "partial" | "failed"
    video_url:        "/videos/{filename}"
    duration_seconds: int
    platform:         "veo"
    stitched:         bool
    clips_count:      int
    clip_urls:        List[str]
    model_used:       str
    has_native_audio: bool
    error_message:    str   (only on failure)
    error_type:       str   (only on failure)
  }
"""

import asyncio
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("VEO_ORCHESTRATOR")


class VeoOrchestrator:
    """
    Orchestrates multi-clip Veo generation for a single prompt row.
    One instance created at startup, reused across all requests.
    """

    def __init__(
        self,
        generator,          # VeoGenerator instance
        stitcher,           # VideoStitcher instance
        decomposer,         # PromptDecomposer instance
        clip_duration: int = 8,
    ):
        self.generator     = generator
        self.stitcher      = stitcher
        self.decomposer    = decomposer
        self.clip_duration = clip_duration

        logger.info("VeoOrchestrator initialised")
        logger.info(f"   Clip duration : {self.clip_duration}s")
        logger.info(f"   FFmpeg        : {'available' if stitcher.ffmpeg_available else 'DISABLED'}")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def generate_for_prompt(
        self,
        prompt_data: Dict[str, Any],
        job_id: str,
        prompt_index: int,
    ) -> Dict[str, Any]:
        """
        Full pipeline for one Excel row: decompose -> generate -> stitch.

        Args:
            prompt_data:   Dict from excel_processor (text, duration, task_type, etc.)
            job_id:        Used for output filenames.
            prompt_index:  Row index used in filenames.
        """
        prompt_text = prompt_data["text"]
        duration    = prompt_data["duration"]
        n_clips     = math.ceil(duration / self.clip_duration)
        start_time  = time.time()

        logger.info(f"[VEO_ORCH] Prompt {prompt_index + 1} | {duration}s -> {n_clips} clip(s)")

        if n_clips == 1:
            return await self._generate_single_clip(
                prompt_text  = prompt_text,
                duration     = duration,
                job_id       = job_id,
                prompt_index = prompt_index,
                start_time   = start_time,
            )

        return await self._generate_multi_clip(
            prompt_text  = prompt_text,
            duration     = duration,
            n_clips      = n_clips,
            job_id       = job_id,
            prompt_index = prompt_index,
            start_time   = start_time,
        )

    # ── Single-clip path ───────────────────────────────────────────────────────

    async def _generate_single_clip(
        self,
        prompt_text: str,
        duration: int,
        job_id: str,
        prompt_index: int,
        start_time: float,
    ) -> Dict[str, Any]:
        logger.info("   Single-clip path")

        result = await self.generator.generate_video(
            prompt       = prompt_text,
            duration     = duration,
            job_id       = job_id,
            prompt_index = prompt_index,
        )

        elapsed = time.time() - start_time

        if result["status"] != "completed":
            return {
                **result,
                "stitched":    False,
                "clips_count": 0,
                "clip_urls":   [],
            }

        logger.info(f"   Done in {elapsed:.1f}s -> {result['video_url']}")

        return {
            "status":           "completed",
            "video_url":        result["video_url"],
            "duration_seconds": self.clip_duration,
            "platform":         "veo",
            "stitched":         False,
            "clips_count":      1,
            "clip_urls":        [result["video_url"]],
            "model_used":       result.get("model_used", ""),
            "has_native_audio": result.get("has_native_audio", True),
            "generation_time_seconds": round(elapsed, 1),
        }

    # ── Multi-clip path ────────────────────────────────────────────────────────

    async def _generate_multi_clip(
        self,
        prompt_text: str,
        duration: int,
        n_clips: int,
        job_id: str,
        prompt_index: int,
        start_time: float,
    ) -> Dict[str, Any]:
        logger.info(f"   Multi-clip path — decomposing into {n_clips} sub-prompts")

        sub_prompts = await self._decompose(
            prompt_text  = prompt_text,
            n_clips      = n_clips,
            duration     = duration,
            job_id       = job_id,
            prompt_index = prompt_index,
        )

        logger.info(f"   Sub-prompts ({len(sub_prompts)}):")
        for idx, sp in enumerate(sub_prompts, 1):
            logger.info(f"     [{idx}] {sp[:80]}{'...' if len(sp) > 80 else ''}")

        # ── Save decomposition JSON ────────────────────────────────────────────
        try:
            decomp_dir = self.stitcher.output_dir.parent / "decompositions"
            decomp_dir.mkdir(parents=True, exist_ok=True)
            decomp_file = decomp_dir / f"{job_id}_p{prompt_index + 1}_decomposition.json"
            decomp_data = {
                "job_id":        job_id,
                "prompt_index":  prompt_index + 1,
                "master_prompt": prompt_text,
                "duration_s":    duration,
                "n_clips":       n_clips,
                "sub_prompts":   sub_prompts,
                "created_at":    datetime.now(timezone.utc).isoformat(),
            }
            decomp_file.write_text(
                json.dumps(decomp_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"   💾 Decomposition saved: {decomp_file.name}")
        except Exception as e:
            logger.warning(f"   [DECOMP_SAVE_ERR] Could not save decomposition JSON: {e}")

        # Generate clips sequentially — Veo quota is per-project
        clip_urls: List[str] = []
        failed_clips: int    = 0
        model_used: str      = ""

        for clip_idx, sub_prompt in enumerate(sub_prompts):
            clip_num   = clip_idx + 1
            clip_label = f"p{prompt_index + 1}_clip_{clip_num:03d}"

            logger.info(f"   Clip {clip_num}/{n_clips} — {clip_label}")

            clip_result = await self.generator.generate_video(
                prompt       = sub_prompt,
                duration     = self.clip_duration,
                job_id       = job_id,
                prompt_index = prompt_index,
                clip_label   = clip_label,
            )

            if clip_result["status"] == "completed":
                clip_urls.append(clip_result["video_url"])
                model_used = clip_result.get("model_used", model_used)
                logger.info(f"     Clip {clip_num} -> {clip_result['video_url']}")
            else:
                failed_clips += 1
                logger.error(
                    f"     Clip {clip_num} failed: "
                    f"{clip_result.get('error_message', 'unknown')}"
                )

        if not clip_urls:
            return {
                "status":        "failed",
                "platform":      "veo",
                "stitched":      False,
                "clips_count":   0,
                "clip_urls":     [],
                "error_message": f"All {n_clips} clips failed",
                "error_type":    "VEO_ALL_CLIPS_FAILED",
                "generation_time_seconds": round(time.time() - start_time, 1),
            }

        # Stitch if more than one clip succeeded
        stitched_url = clip_urls[0]  # fallback: first clip
        did_stitch   = False

        if len(clip_urls) > 1 and self.stitcher.ffmpeg_available:
            logger.info(f"   Stitching {len(clip_urls)} clips...")
            local_paths   = self._resolve_local_paths(clip_urls)
            stitched_path = await self.stitcher.stitch_clips(
                clip_paths     = local_paths,
                job_id         = job_id,
                prompt_index   = prompt_index,
                platform_label = "veo",
            )
            if stitched_path:
                stitched_url = f"/videos/{Path(stitched_path).name}"
                did_stitch   = True
                logger.info(f"   Stitched -> {stitched_url}")
            else:
                logger.warning("   Stitching failed — using first clip as fallback")

        elapsed      = time.time() - start_time
        final_status = "partial" if failed_clips > 0 else "completed"

        return {
            "status":           final_status,
            "video_url":        stitched_url,
            "duration_seconds": len(clip_urls) * self.clip_duration,
            "platform":         "veo",
            "stitched":         did_stitch,
            "clips_count":      len(clip_urls),
            "clip_urls":        clip_urls,
            "model_used":       model_used,
            "has_native_audio": True,
            "failed_clips":     failed_clips,
            "generation_time_seconds": round(elapsed, 1),
        }

    # ── Decompose ──────────────────────────────────────────────────────────────

    async def _decompose(
        self,
        prompt_text: str,
        n_clips: int,
        duration: int,
        job_id: str,
        prompt_index: int,
    ) -> List[str]:
        """
        Generate N sub-prompts via PromptDecomposer (Bedrock backend).

        decompose() is synchronous (boto3 blocking call). Run it in the default
        thread executor so the event loop stays free during the Bedrock round-trip.

        Bedrock contract:
            decompose(master_prompt, n_clips, clip_durations, platform)
            -> (List[str], str)   # (sub_prompts, model_source)

        clip_durations: list of per-clip durations e.g. [8, 8, 8] for 3×8s clips.
        All Veo clips are exactly self.clip_duration seconds (default 8).
        """
        clip_durations = [self.clip_duration] * n_clips  # [8, 8, 8, ...]

        try:
            loop = asyncio.get_running_loop()
            sub_prompts, source = await loop.run_in_executor(
                None,
                lambda: self.decomposer.decompose(
                    master_prompt  = prompt_text,
                    n_clips        = n_clips,
                    clip_durations = clip_durations,
                    platform       = "veo",
                ),
            )
            logger.info(f"   Decomposer source: {source}")

            if sub_prompts and len(sub_prompts) == n_clips:
                return sub_prompts

            logger.warning(
                f"   Decomposer returned {len(sub_prompts) if sub_prompts else 0} "
                f"sub-prompts, expected {n_clips} — using fallback"
            )
        except Exception as e:
            logger.warning(f"   Decomposer error: {type(e).__name__}: {e} — using fallback")

        # Safety net: repeat the original prompt for each clip
        logger.info("   Falling back to repeated master prompt")
        return [prompt_text] * n_clips

    # ── Path resolution ────────────────────────────────────────────────────────

    def _resolve_local_paths(self, video_urls: List[str]) -> List[str]:
        """Convert /videos/{filename} URLs to absolute local paths for FFmpeg."""
        local_paths = []
        output_dir  = self.stitcher.output_dir

        for url in video_urls:
            filename  = url.split("/")[-1]
            full_path = output_dir / filename
            if full_path.exists():
                local_paths.append(str(full_path))
            else:
                logger.warning(f"   Clip file not found for stitching: {full_path}")

        return local_paths