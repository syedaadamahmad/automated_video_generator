"""
video_stitcher.py — Veo-specific FFmpeg video stitcher
══════════════════════════════════════════════════════

Responsibilities:
  1. Receive a list of local clip paths (already on disk from VeoGenerator)
  2. Sort by filename (clip NNN suffix = generation order)
  3. FFmpeg concat demuxer → single stitched .mp4
  4. Return absolute path of stitched file

No S3. No boto3. No audio mixing.
Veo clips already contain native audio — stream-copy preserves it end-to-end.

Called by VeoOrchestrator as:
    stitched_path = await stitcher.stitch_clips(
        clip_paths     = ["/abs/path/clip1.mp4", ...],
        job_id         = "job_abc",
        prompt_index   = 0,
        platform_label = "veo",
    )
Returns: absolute path string on success, None on failure.
"""

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("VEO_STITCHER")


class VideoStitcher:
    """FFmpeg-based clip stitcher. No S3, no audio mixing — Veo native audio is preserved."""

    def __init__(
        self,
        output_dir: Path,
        # Accept (and ignore) legacy S3 kwargs so veo_main.py needs no changes
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        bucket: str = "",
        region: str = "",
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ffmpeg_available = self._check_ffmpeg()

        logger.info("=" * 55)
        logger.info("[VEO_STITCHER] Initialising")
        logger.info(f"   Output dir : {self.output_dir}")
        logger.info(f"   FFmpeg     : {'available' if self.ffmpeg_available else 'NOT FOUND — stitching disabled'}")
        if not self.ffmpeg_available:
            logger.error("   Install FFmpeg and ensure it is on PATH")
        logger.info("=" * 55)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def stitch_clips(
        self,
        clip_paths: List[str],
        job_id: str,
        prompt_index: int,
        platform_label: str = "veo",
    ) -> Optional[str]:
        """
        Concatenate clips → single MP4 via FFmpeg concat demuxer.

        Args:
            clip_paths:     Absolute filesystem paths to each clip, in order.
            job_id:         Used in output filename.
            prompt_index:   Used in output filename.
            platform_label: Used in output filename.

        Returns:
            Absolute path to stitched output file, or None on failure.
        """
        n = len(clip_paths)
        stitch_label = f"{job_id}_p{prompt_index + 1}_{platform_label}"
        t0 = time.time()

        logger.info(f"[STITCH] {stitch_label} — {n} clips")

        if not self.ffmpeg_available:
            logger.error("[STITCH] FFmpeg not available — returning first clip as fallback")
            return clip_paths[0] if clip_paths else None

        if not clip_paths:
            logger.error("[STITCH] No clip paths provided")
            return None

        if n == 1:
            logger.info("[STITCH] Single clip — no stitching needed, returning as-is")
            return clip_paths[0]

        # Sort by filename — clip_001, clip_002, ... guarantees order
        sorted_paths = sorted(clip_paths, key=lambda p: Path(p).name)
        logger.info("[STITCH] Clip order:")
        for i, p in enumerate(sorted_paths):
            exists  = Path(p).exists()
            size_mb = Path(p).stat().st_size / (1024 * 1024) if exists else 0
            logger.info(f"   [{i+1}] {Path(p).name}  ({'%.2f MB' % size_mb if exists else 'MISSING'})")
            if not exists:
                logger.error(f"   [STITCH_ERR] Clip not found on disk: {p}")

        # Validate all clips exist and are non-empty
        for p in sorted_paths:
            path = Path(p)
            if not path.exists():
                logger.error(f"[STITCH] Missing clip: {p} — aborting stitch")
                return sorted_paths[0]  # first available clip as fallback
            if path.stat().st_size == 0:
                logger.error(f"[STITCH] Empty clip (0 bytes): {p} — aborting stitch")
                return sorted_paths[0]

        output_filename = f"{stitch_label}_stitched.mp4"
        output_path     = self.output_dir / output_filename

        # Stream-copy first (fast, lossless, preserves native Veo audio)
        # Falls back to libx264 re-encode if stream-copy fails (codec mismatch)
        success = await self._ffmpeg_concat(sorted_paths, str(output_path), reencode=False)

        if not success or not output_path.exists() or output_path.stat().st_size == 0:
            logger.warning("[STITCH] Stream-copy failed — retrying with libx264 re-encode")
            output_path.unlink(missing_ok=True)
            success = await self._ffmpeg_concat(sorted_paths, str(output_path), reencode=True)

        if not success or not output_path.exists():
            logger.error("[STITCH] Both FFmpeg attempts failed — returning first clip")
            return sorted_paths[0]

        elapsed = time.time() - t0
        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"[STITCH] Done in {elapsed:.1f}s — {output_filename} ({size_mb:.2f} MB)")

        return str(output_path)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _check_ffmpeg(self) -> bool:
        try:
            r = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                timeout=5,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def _ffmpeg_concat(
        self,
        clip_paths: List[str],
        output_path: str,
        reencode: bool,
    ) -> bool:
        """
        Write FFmpeg concat list file, run concat demuxer.

        concat demuxer requires:
          - 'safe 0' because absolute paths are used
          - Each path wrapped in single quotes
          - Paths written to a temp .txt file (not passed on command line)

        Stream-copy (-c copy):
          Preserves Veo native audio and video without transcoding.
          All clips must have identical codec/resolution/fps — Veo guarantees this.

        Re-encode fallback (-c:v libx264 -c:a aac):
          Used when Veo returns clips with minor container differences.
        """
        abs_paths = [str(Path(p).resolve()) for p in clip_paths]
        concat_content = "\n".join(f"file '{p}'" for p in abs_paths)
        tmp_concat = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(concat_content)
                tmp_concat = f.name

            logger.info(f"[STITCH] Concat list ({tmp_concat}):")
            for line in concat_content.splitlines():
                logger.info(f"   {line}")

            if reencode:
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0", "-i", tmp_concat,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k",
                    output_path,
                ]
                logger.info("[STITCH] Mode: re-encode (libx264 + AAC)")
            else:
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0", "-i", tmp_concat,
                    "-c", "copy",
                    output_path,
                ]
                logger.info("[STITCH] Mode: stream-copy (lossless, preserves native audio)")

            logger.info(f"[STITCH] CMD: {' '.join(cmd)}")

            loop   = asyncio.get_running_loop()
            t0     = time.time()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=300),
            )
            elapsed = time.time() - t0

            if result.returncode == 0:
                out_mb = Path(output_path).stat().st_size / (1024*1024) if Path(output_path).exists() else 0
                logger.info(f"[STITCH] FFmpeg OK in {elapsed:.1f}s — {out_mb:.2f} MB")
                return True

            logger.error(f"[STITCH] FFmpeg exit {result.returncode} after {elapsed:.1f}s")
            # Log last 10 meaningful stderr lines
            stderr_lines = [
                l for l in (result.stderr or "").strip().splitlines()
                if l.strip() and not l.startswith("ffmpeg version")
            ]
            for line in stderr_lines[-10:]:
                logger.error(f"   STDERR: {line}")
            return False

        except subprocess.TimeoutExpired:
            logger.error("[STITCH] FFmpeg timed out after 300s")
            return False
        except Exception as e:
            logger.error(f"[STITCH] Unexpected error: {type(e).__name__}: {e}")
            return False
        finally:
            if tmp_concat and os.path.exists(tmp_concat):
                try:
                    os.unlink(tmp_concat)
                except Exception:
                    pass
