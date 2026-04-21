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
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from veo_s3 import VeoS3Client  # noqa: E402 — imported after path setup in veo_main

logger = logging.getLogger("VEO_ORCHESTRATOR")


class VeoOrchestrator:
    """
    Orchestrates multi-clip Veo generation for a single prompt row.
    One instance created at startup, reused across all requests.
    """

    def __init__(
        self,
        generator,                          # VeoGenerator instance
        stitcher,                           # VideoStitcher instance
        decomposer,                         # PromptDecomposer instance
        clip_duration: int = 8,
        s3_client: Optional[VeoS3Client] = None,  # None = local-only mode
    ):
        self.generator     = generator
        self.stitcher      = stitcher
        self.decomposer    = decomposer
        self.clip_duration = clip_duration
        self.s3            = s3_client      # VeoS3Client or None

        logger.info("VeoOrchestrator initialised")
        logger.info(f"   Clip duration : {self.clip_duration}s")
        logger.info(f"   FFmpeg        : {'available' if stitcher.ffmpeg_available else 'DISABLED'}")
        logger.info(f"   S3 upload     : {'enabled' if s3_client and s3_client.enabled else 'disabled (local only)'}")

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

        # ── S3 upload (non-blocking — local file already saved) ────────────────
        local_video_url = result["video_url"]
        # video_url is a FastAPI route like /videos/filename.mp4 — resolve to
        # the actual filesystem path before passing to S3.
        resolved_local = self._resolve_video_path(local_video_url)
        s3_url = None
        if self.s3 and self.s3.enabled:
            s3_url = self.s3.upload_video(
                local_path   = resolved_local,
                job_id       = job_id,
                prompt_index = prompt_index,
            )

        final_url = s3_url or local_video_url

        return {
            "status":           "completed",
            "video_url":        final_url,
            "local_video_url":  local_video_url,
            "s3_url":           s3_url,
            "duration_seconds": self.clip_duration,
            "platform":         "veo",
            "stitched":         False,
            "clips_count":      1,
            "clip_urls":        [final_url],
            "model_used":       result.get("model_used", ""),
            "has_native_audio": result.get("has_native_audio", True),
            "generation_time_seconds": round(elapsed, 1),
            # Metrics
            "api_calls_made":       result.get("api_calls_made", 1),
            "rate_limit_hits":      result.get("rate_limit_hits", 0),
            "decomp_input_tokens":  decomp_metrics.get("input_tokens", 0),
            "decomp_output_tokens": decomp_metrics.get("output_tokens", 0),
            "decomp_nova_calls":    decomp_metrics.get("nova_calls", 0),
            "decomp_deepseek_calls":decomp_metrics.get("deepseek_calls", 0),
            "decomp_deterministic": decomp_metrics.get("deterministic", 0),
            "s3_upload_ok":         1 if s3_url else 0,
            "s3_upload_fail":       0 if s3_url else (1 if self.s3 and self.s3.enabled else 0),
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
        # Detect static camera mode — user signals this with "static" in the prompt.
        # When active: decomposer injects a hard camera-lock directive into every
        # sub-prompt, and img2vid chaining further enforces positional continuity.
        is_static = "static" in prompt_text.lower()
        if is_static:
            logger.info("   📷 Static camera mode detected — camera-lock directive will be injected into all sub-prompts")

        # Detect narrator voice lock — user signals this with "NARRATOR:" in the prompt.
        # When active: decomposer injects a voice-lock directive into every sub-prompt
        # to keep accent, tone, and pacing consistent across all clips.
        narrator_desc = self.decomposer._extract_narrator(prompt_text)
        if narrator_desc:
            logger.info(f"   🎙️ Narrator voice lock detected: '{narrator_desc}' — injecting into all sub-prompts")

        logger.info(f"   Multi-clip path — decomposing into {n_clips} sub-prompts")

        sub_prompts, decomp_source, clip_objects, decomp_metrics = await self._decompose(
            prompt_text   = prompt_text,
            n_clips       = n_clips,
            duration      = duration,
            job_id        = job_id,
            prompt_index  = prompt_index,
            is_static     = is_static,
            narrator_desc = narrator_desc,
        )

        logger.info(f"   Sub-prompts ({len(sub_prompts)}) via {decomp_source}:")
        for idx, sp in enumerate(sub_prompts, 1):
            logger.info(f"     [{idx}] {sp[:80]}{'...' if len(sp) > 80 else ''}")

        # ── Save decomposition JSON (rich format) ──────────────────────────────
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
                "model_used":    decomp_source,
                "is_static":     is_static,
                "clip_objects":  clip_objects,
                "sub_prompts":   sub_prompts,  # plain strings — kept for readability
                "saved_at":      datetime.now(timezone.utc).isoformat(),
            }
            decomp_file.write_text(
                json.dumps(decomp_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"   💾 Decomposition saved: {decomp_file.name}")
        except Exception as e:
            logger.warning(f"   [DECOMP_SAVE_ERR] Could not save decomposition JSON: {e}")

        # Generate clips sequentially with img2vid chaining for continuity.
        # After each successful clip, extract its last frame and pass as the
        # first-frame anchor to the next clip. This enforces visual continuity
        # across independent Veo generations (character, setting, lighting).
        clip_urls:    List[str]        = []
        clip_results: List[dict]       = []   # per-clip result dicts for metric aggregation
        temp_frames:  List[Path]       = []   # collected for cleanup after stitch
        failed_clips: int              = 0
        model_used: str             = ""
        reference_image: Optional[Path] = None   # last frame of previous clip

        for clip_idx, sub_prompt in enumerate(sub_prompts):
            clip_num   = clip_idx + 1
            clip_label = f"p{prompt_index + 1}_clip_{clip_num:03d}"

            logger.info(
                f"   Clip {clip_num}/{n_clips} — {clip_label}"
                + (f" [img2vid anchor: {reference_image.name}]" if reference_image else " [text-to-video]")
            )

            clip_result = await self.generator.generate_video(
                prompt               = sub_prompt,
                duration             = self.clip_duration,
                job_id               = job_id,
                prompt_index         = prompt_index,
                clip_label           = clip_label,
                reference_image_path = reference_image,
            )

            if clip_result["status"] == "completed":
                clip_urls.append(clip_result["video_url"])
                clip_results.append(clip_result)
                model_used = clip_result.get("model_used", model_used)
                logger.info(f"     ✅ Clip {clip_num} -> {clip_result['video_url']}")

                # Extract last frame for next clip's anchor (skip on final clip)
                if clip_num < n_clips:
                    frame = await self._extract_last_frame(
                        video_url  = clip_result["video_url"],
                        clip_label = clip_label,
                    )
                    if frame:
                        reference_image = frame
                        temp_frames.append(frame)
                    else:
                        reference_image = None  # degrade gracefully — next clip is text-only
                        logger.warning(
                            f"     ⚠️  Frame extraction failed for clip {clip_num} "
                            f"— clip {clip_num + 1} will use text-only generation"
                        )
            else:
                failed_clips += 1
                clip_results.append(clip_result)   # track for metric aggregation
                reference_image = None  # broken clip — no frame to chain from
                logger.error(
                    f"     ❌ Clip {clip_num} failed: "
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
            # Read crossfade settings from config — off by default
            from veo_config import veo_config as _cfg
            stitched_path = await self.stitcher.stitch_clips(
                clip_paths          = local_paths,
                job_id              = job_id,
                prompt_index        = prompt_index,
                platform_label      = "veo",
                crossfade           = _cfg.STITCH_CROSSFADE,
                crossfade_duration  = _cfg.STITCH_CROSSFADE_DURATION,
                audio_fade_duration = _cfg.STITCH_AUDIO_FADE,
            )
            if stitched_path:
                stitched_url = f"/videos/{Path(stitched_path).name}"
                did_stitch   = True
                logger.info(f"   Stitched -> {stitched_url}")
            else:
                logger.warning("   Stitching failed — using first clip as fallback")

        # Clean up temporary frame files used for img2vid chaining
        for frame_path in temp_frames:
            try:
                if frame_path.exists():
                    frame_path.unlink()
            except Exception:
                pass

        elapsed      = time.time() - start_time
        # partial = some clips failed but at least one succeeded — video exists
        # completed = all clips succeeded
        # failed = no clips succeeded at all (handled above with early return)
        final_status = "partial" if failed_clips > 0 else "completed"

        # ── S3 upload of stitched output ───────────────────────────────────────
        local_stitched_url = stitched_url
        # stitched_url is a FastAPI route — resolve to actual filesystem path.
        resolved_stitched = self._resolve_video_path(stitched_url) if stitched_url else None
        s3_url = None
        if self.s3 and self.s3.enabled and resolved_stitched:
            s3_url = self.s3.upload_video(
                local_path   = resolved_stitched,
                job_id       = job_id,
                prompt_index = prompt_index,
            )

        final_url = s3_url or stitched_url
        total_api_calls = sum(r.get("api_calls_made", 1) for r in clip_results if r)
        total_rl_hits   = sum(r.get("rate_limit_hits", 0) for r in clip_results if r)

        return {
            "status":           final_status,
            "video_url":        final_url,
            "local_video_url":  local_stitched_url,
            "s3_url":           s3_url,
            "duration_seconds": len(clip_urls) * self.clip_duration,
            "platform":         "veo",
            "stitched":         did_stitch,
            "clips_count":      len(clip_urls),
            "clip_urls":        clip_urls,
            "model_used":       model_used,
            "has_native_audio": True,
            "failed_clips":     failed_clips,
            "generation_time_seconds": round(elapsed, 1),
            # Metrics
            "api_calls_made":       total_api_calls,
            "rate_limit_hits":      total_rl_hits,
            "decomp_input_tokens":  decomp_metrics.get("input_tokens", 0),
            "decomp_output_tokens": decomp_metrics.get("output_tokens", 0),
            "decomp_nova_calls":    decomp_metrics.get("nova_calls", 0),
            "decomp_deepseek_calls":decomp_metrics.get("deepseek_calls", 0),
            "decomp_deterministic": decomp_metrics.get("deterministic", 0),
            "s3_upload_ok":         1 if s3_url else 0,
            "s3_upload_fail":       0 if s3_url else (1 if self.s3 and self.s3.enabled else 0),
        }

    # ── Last-frame extraction (img2vid chaining) ──────────────────────────────

    async def _extract_last_frame(
        self,
        video_url: str,
        clip_label: str,
    ) -> Optional[Path]:
        """
        Extract the last frame of a generated clip as a JPEG.

        Used for img2vid chaining: the last frame of clip N becomes the first-frame
        anchor for clip N+1, enforcing visual continuity across generations.

        Args:
            video_url:  /videos/{filename} URL of the completed clip.
            clip_label: Used to name the temp frame file.

        Returns:
            Path to the extracted JPEG, or None if extraction fails.
        """
        if not self.stitcher.ffmpeg_available:
            logger.warning("   [FRAME_EXTRACT] FFmpeg not available — skipping last-frame extraction")
            return None

        try:
            filename   = video_url.split("/")[-1]
            local_path = self.stitcher.output_dir / filename

            if not local_path.exists():
                logger.warning(f"   [FRAME_EXTRACT] Source clip not found: {local_path}")
                return None

            # Write to a temp file alongside the videos
            frame_path = self.stitcher.output_dir / f"_frame_{clip_label}.jpg"

            cmd = [
                "ffmpeg", "-y",
                "-sseof", "-0.1",          # seek 100ms from end — last meaningful frame,
                                           # close enough to avoid blank tail, far enough
                                           # from the very last duplicate frame
                "-i", str(local_path),
                "-vframes", "1",
                "-q:v", "2",               # high quality JPEG
                "-f", "image2",
                str(frame_path),
            ]

            def _run() -> bool:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                return result.returncode == 0 and frame_path.exists()

            success = await asyncio.get_event_loop().run_in_executor(None, _run)

            if success:
                size_kb = frame_path.stat().st_size / 1024
                logger.info(
                    f"   🖼️  [FRAME_EXTRACT] Extracted last frame: "
                    f"{frame_path.name} ({size_kb:.1f} KB)"
                )
                return frame_path
            else:
                logger.warning(
                    f"   [FRAME_EXTRACT] FFmpeg extraction failed for {filename}"
                )
                return None

        except Exception as e:
            logger.warning(f"   [FRAME_EXTRACT] Error: {e}")
            return None

    # ── Decompose ──────────────────────────────────────────────────────────────

    async def _decompose(
        self,
        prompt_text: str,
        n_clips: int,
        duration: int,
        job_id: str,
        prompt_index: int,
        is_static: bool = False,
        narrator_desc: Optional[str] = None,
    ) -> Tuple[List[str], str, List[dict], dict]:
        """
        Generate N sub-prompts via PromptDecomposer (Bedrock backend).

        decompose() is synchronous (boto3 blocking call). Run it in the default
        thread executor so the event loop stays free during the Bedrock round-trip.

        is_static: propagated from master prompt detection — injects camera-lock
        directive into every sub-prompt via the decomposer.

        clip_durations: list of per-clip durations e.g. [8, 8, 8] for 3×8s clips.
        All Veo clips are exactly self.clip_duration seconds (default 8).
        """
        clip_durations = [self.clip_duration] * n_clips  # [8, 8, 8, ...]

        try:
            loop = asyncio.get_running_loop()
            sub_prompts, source, clip_objects, decomp_metrics = await loop.run_in_executor(
                None,
                lambda: self.decomposer.decompose(
                    master_prompt  = prompt_text,
                    n_clips        = n_clips,
                    clip_durations = clip_durations,
                    platform       = "veo",
                    is_static      = is_static,
                    narrator_desc  = narrator_desc,
                ),
            )
            logger.info(f"   Decomposer source: {source}")

            if sub_prompts and len(sub_prompts) == n_clips:
                return sub_prompts, source, clip_objects, decomp_metrics

            logger.warning(
                f"   Decomposer returned {len(sub_prompts) if sub_prompts else 0} "
                f"sub-prompts, expected {n_clips} — using fallback"
            )
        except Exception as e:
            import traceback
            logger.error(
                f"   [DECOMPOSE_ERR] {type(e).__name__}: {e}\n"
                f"{traceback.format_exc()}"
            )

        # Safety net: repeat the original prompt for each clip
        logger.info("   Falling back to repeated master prompt")
        fallback_objects = [
            {"clip": i+1, "duration_s": clip_durations[i] if i < len(clip_durations) else 8,
             "end_state": "", "prompt": prompt_text}
            for i in range(n_clips)
        ]
        empty_metrics = {"input_tokens": 0, "output_tokens": 0,
                         "nova_calls": 0, "deepseek_calls": 0, "deterministic": 1}
        return [prompt_text] * n_clips, "repeated_master", fallback_objects, empty_metrics

    # ── Path resolution ────────────────────────────────────────────────────────

    def _resolve_video_path(self, video_url: str) -> str:
        """
        Convert a FastAPI route (/videos/filename.mp4) to an absolute
        filesystem path that S3 and FFmpeg can actually open.

        veo_main.py mounts the videos folder at /videos/ via StaticFiles.
        The route is just a URL prefix — the actual file is in output_dir.
        """
        if not video_url:
            return video_url
        filename = Path(video_url).name   # strip /videos/ prefix
        return str(self.stitcher.output_dir / filename)

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