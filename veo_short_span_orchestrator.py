"""
veo_short_span_orchestrator.py — Short Span Clip Generation Pipeline
════════════════════════════════════════════════════════════════════════

Responsibilities:
  1. Accept N prompt rows from Excel — each row = one discrete Veo clip
  2. Generate each clip sequentially via VeoGenerator (NO decomposition)
  3. Chain clips via img2vid last-frame anchoring for visual continuity
  4. Stitch all clips into a single output video via FFmpeg

Design decisions:
  - Completely separate from VeoOrchestrator — no shared state or inheritance
  - Clip duration set globally at job level (2–8s), not per-row
  - Guardrails (no_text, no_speech) injected at generation time
  - Resulting video is one stitched file regardless of clip count

Clip duration:
  - Veo API supports 2–8 seconds per clip (integer values)
  - Total video = number of rows × clip_duration_s
  - No "multiples of 8" constraint on the final output — only per API call

Usage in veo_main.py:
  from veo_short_span_orchestrator import ShortSpanOrchestrator
  ss_orchestrator = ShortSpanOrchestrator(generator, stitcher, s3_client)
  result = await ss_orchestrator.run(prompts, job_id, clip_duration_s=2)
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from veo_s3 import VeoS3Client

logger = logging.getLogger("SHORT_SPAN_ORCH")

# ── Guardrail templates ────────────────────────────────────────────────────────
_NO_TEXT_GUARDRAIL = (
    "NO TEXT OVERLAY: Do not render any text, titles, captions, subtitles, "
    "watermarks, UI labels, or written words anywhere in the video frame."
)
_NO_SPEECH_GUARDRAIL = (
    "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
)


class ShortSpanOrchestrator:
    """
    Generates a short-span clip sequence from discrete per-row prompts.

    Each Excel row → one Veo API call → one clip.
    Clips are chained via img2vid last-frame anchoring, then stitched.
    No prompt decomposition is performed — the user controls each clip directly.
    """

    def __init__(
        self,
        generator,                                    # VeoGenerator instance
        stitcher,                                     # VideoStitcher instance
        s3_client: Optional[VeoS3Client] = None,      # None = local only
    ):
        self.generator = generator
        self.stitcher  = stitcher
        self.s3        = s3_client

        logger.info("ShortSpanOrchestrator initialised")
        logger.info(f"   FFmpeg    : {'available' if stitcher.ffmpeg_available else 'DISABLED'}")
        logger.info(f"   S3 upload : {'enabled' if s3_client and s3_client.enabled else 'local only'}")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(
        self,
        prompts: List[Dict[str, Any]],
        job_id: str,
        clip_duration_s: float = 2.0,
        no_text: bool = False,
        no_speech: bool = False,
        aspect_ratio: str = "9:16",
    ) -> Dict[str, Any]:
        """
        Generate all clips and return a single stitched result dict.

        Args:
            prompts:         List of prompt dicts — one per Excel row.
                             Each dict must have a 'text' key.
            job_id:          Used in output filenames and S3 paths.
            clip_duration_s: Duration of each individual Veo clip (2–8s).
            no_text:         Prepend no-text guardrail to every prompt.
            no_speech:       Prepend no-speech guardrail to every prompt.

        Returns:
            Result dict with status, video_url, local_video_url, s3_url,
            clips_count, duration_seconds, etc. Same shape as VeoOrchestrator
            results for frontend compatibility.
        """
        n        = len(prompts)
        start    = time.time()
        clip_dur = max(2, min(8, int(clip_duration_s)))  # clamp 2–8

        logger.info(
            f"[SHORT_SPAN] {job_id} — {n} clip(s) at {clip_dur}s each | "
            f"no_text={no_text} no_speech={no_speech}"
        )

        clip_paths: List[str] = []
        failed = 0
        # No img2vid chaining — each row is an independent scene.

        # Extract narrator voice lock from the first row (if present)
        # and inject into every clip so the voice stays consistent.
        import re as _re
        _narrator_match = _re.search(
            r'(?:NARRATOR|NARRATOR\s+VOICE|VOICE)\s*:\s*([^\n"]+)',
            (prompts[0].get("text") or "") if prompts else "",
            _re.IGNORECASE,
        )
        narrator_lock = (
            f"NARRATOR VOICE LOCK: {_narrator_match.group(1).strip()} "
            f"— maintain this exact voice throughout."
            if _narrator_match else None
        )
        if narrator_lock:
            logger.info(f"[SHORT_SPAN] Narrator lock detected: '{_narrator_match.group(1).strip()}'")

        for idx, prompt_data in enumerate(prompts):
            raw_text = (prompt_data.get("text") or "").strip()

            # Build prompt: narrator lock + guardrails + scene text
            parts = []
            if narrator_lock and idx > 0:
                # Clip 1 already has the NARRATOR: line in its raw_text.
                # Inject the lock directive into all subsequent clips.
                parts.append(narrator_lock)
            if no_text:   parts.append(_NO_TEXT_GUARDRAIL)
            if no_speech: parts.append(_NO_SPEECH_GUARDRAIL)
            parts.append(raw_text)
            prompt_text = " ".join(parts) if parts[:-1] else raw_text

            clip_label = f"ss_{idx + 1:03d}"
            logger.info(
                f"[SHORT_SPAN] [{idx + 1}/{n}] clip_label={clip_label} | "
                f"'{prompt_text[:80]}...'"
            )

            result = await self.generator.generate_video(
                prompt       = prompt_text,
                duration     = clip_dur,
                job_id       = job_id,
                prompt_index = idx,
                clip_label   = clip_label,
                # No reference_image_path — pure text-to-video, fresh each clip
            )

            if result.get("status") != "completed":
                logger.warning(
                    f"[SHORT_SPAN] Clip {idx + 1} failed "
                    f"({result.get('error_message', 'unknown')}) — skipping"
                )
                failed += 1
                continue

            clip_url        = result["video_url"]
            clip_local_path = Path(self._resolve_path(clip_url))
            clip_paths.append(str(clip_local_path))
            logger.info(f"[SHORT_SPAN] Clip {idx + 1} OK → {clip_url}")

        if not clip_paths:
            logger.error(f"[SHORT_SPAN] {job_id} — all {n} clips failed")
            return {
                "status":        "failed",
                "error_message": f"All {n} short-span clips failed to generate.",
                "clips_count":   0,
            }

        # ── Stitch ────────────────────────────────────────────────────────────
        stitched_path = await self.stitcher.stitch_clips(
            clip_paths     = clip_paths,
            job_id         = job_id,
            prompt_index   = 0,
            platform_label = "ss",
        )

        elapsed = time.time() - start

        if not stitched_path:
            # Stitching failed — return first clip as fallback
            local_url = f"/videos/{Path(clip_paths[0]).name}"
            logger.warning(f"[SHORT_SPAN] Stitch failed — returning first clip")
            return self._result(
                status    = "partial",
                local_url = local_url,
                s3_url    = None,
                clip_paths= clip_paths,
                clip_dur  = clip_dur,
                failed    = failed,
                elapsed   = elapsed,
            )

        # Apply end fade (1.5s audio, 0.5s video to black) — same as full pipeline
        faded_path = await self.stitcher._apply_fade(Path(stitched_path))
        if faded_path and faded_path.exists():
            logger.info(f"[SHORT_SPAN] End fade applied → {faded_path.name}")
            final_stitched = faded_path
        else:
            logger.warning("[SHORT_SPAN] End fade failed — using un-faded stitch")
            final_stitched = Path(stitched_path)

        local_url = f"/videos/{final_stitched.name}"
        resolved  = self._resolve_path(local_url)

        # ── S3 upload ──────────────────────────────────────────────────────────
        s3_url: Optional[str] = None
        if self.s3 and self.s3.enabled:
            s3_url = self.s3.upload_video(
                local_path   = resolved,
                job_id       = job_id,
                prompt_index = 0,
            )
            if s3_url:
                logger.info(f"[SHORT_SPAN] S3 ✅ {s3_url}")
            else:
                logger.warning(f"[SHORT_SPAN] S3 upload failed — local URL used")

        status = "partial" if failed > 0 else "completed"
        logger.info(
            f"[SHORT_SPAN] Done in {elapsed:.1f}s — "
            f"{len(clip_paths)} ok, {failed} failed, status={status}"
        )

        return self._result(
            status    = status,
            local_url = local_url,
            s3_url    = s3_url,
            clip_paths= clip_paths,
            clip_dur  = clip_dur,
            failed    = failed,
            elapsed   = elapsed,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _result(
        self,
        status: str,
        local_url: str,
        s3_url: Optional[str],
        clip_paths: List[str],
        clip_dur: int,
        failed: int,
        elapsed: float,
    ) -> Dict[str, Any]:
        """Build a standardised result dict compatible with the frontend schema."""
        final_url = s3_url or local_url
        return {
            "status":           status,
            "video_url":        final_url,
            "local_video_url":  local_url,
            "s3_url":           s3_url,
            "duration_seconds": round(len(clip_paths) * clip_dur, 1),
            "platform":         "veo",
            "stitched":         True,
            "clips_count":      len(clip_paths),
            "clip_urls":        clip_paths,
            "model_used":       "veo-3.0-generate-001",
            "has_native_audio": True,
            "failed_clips":     failed,
            "generation_time_seconds": round(elapsed, 1),
            # Decomposer not used — zero all token metrics
            "decomp_input_tokens":   0,
            "decomp_output_tokens":  0,
            "decomp_nova_calls":     0,
            "decomp_deepseek_calls": 0,
            "decomp_deterministic":  0,
            "s3_upload_ok":   1 if s3_url else 0,
            "s3_upload_fail": 0 if s3_url else (
                1 if self.s3 and self.s3.enabled else 0
            ),
        }

    def _resolve_path(self, video_url: str) -> str:
        """Convert /videos/filename.mp4 → absolute filesystem path."""
        if not video_url:
            return video_url
        rel = video_url.lstrip("/")
        if rel.startswith("videos/"):
            rel = rel[len("videos/"):]
        return str(self.stitcher.output_dir / rel)

    async def _extract_last_frame(
        self,
        video_url: str,
        clip_label: str,
    ) -> Optional[Path]:
        """
        Extract the frame at -100ms from the end of the clip.
        Used as reference image for img2vid anchoring on the next clip.
        Returns Path to the JPEG frame, or None on failure.
        """
        import subprocess as _sp
        local_path = Path(self._resolve_path(video_url))
        if not local_path.exists():
            logger.warning(f"[SHORT_SPAN] Frame extract: clip not found: {local_path}")
            return None

        frame_path = local_path.parent / f"_frame_{clip_label}.jpg"
        loop = asyncio.get_running_loop()

        def _run():
            r = _sp.run([
                "ffmpeg", "-y",
                "-sseof", "-0.1",
                "-i",     str(local_path),
                "-vframes", "1",
                "-q:v",    "2",
                str(frame_path),
            ], capture_output=True, timeout=30)
            ok = r.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0
            if ok:
                sz = frame_path.stat().st_size / 1024
                logger.info(
                    f"   [FRAME] Extracted {frame_path.name} "
                    f"({sz:.1f} KB) for next clip anchor"
                )
            else:
                logger.warning(f"   [FRAME] Extraction failed for {local_path.name}")
            return frame_path if ok else None

        return await loop.run_in_executor(None, _run)