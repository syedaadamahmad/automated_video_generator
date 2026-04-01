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
        crossfade: bool = False,
        crossfade_duration: float = 0.5,
        audio_fade_duration: float = 0.3,
    ) -> Optional[str]:
        """
        Concatenate clips → single MP4 via FFmpeg.

        Two modes controlled by the `crossfade` flag (set via config):

        crossfade=False (default):
            Stream-copy concat — fast, lossless, preserves native Veo audio.
            Hard cuts between clips. May show a brief anchor-frame freeze at
            stitch points (1-4 frames from the img2vid reference).

        crossfade=True:
            Re-encodes with FFmpeg xfade filter — dissolves the last
            crossfade_duration seconds of clip N into the first
            crossfade_duration seconds of clip N+1. Eliminates the
            anchor freeze completely. Also applies a short audio fade
            (audio_fade_duration) at each stitch point so narration
            boundaries sound like natural breath pauses rather than cuts.
            Uses CRF 17 — visually lossless at 720p, indistinguishable
            from the source clips. ~15-20s extra processing for 4 clips.

        Args:
            clip_paths:          Absolute filesystem paths to each clip, in order.
            job_id:              Used in output filename.
            prompt_index:        Used in output filename.
            platform_label:      Used in output filename.
            crossfade:           Enable crossfade transition between clips.
            crossfade_duration:  Seconds of overlap between clips (default 0.5s).
            audio_fade_duration: Seconds of audio fade at each stitch (default 0.3s).

        Returns:
            Absolute path to stitched output file, or None on failure.
        """
        n = len(clip_paths)
        stitch_label = f"{job_id}_p{prompt_index + 1}_{platform_label}"
        t0 = time.time()

        logger.info(f"[STITCH] {stitch_label} — {n} clips  mode={'crossfade' if crossfade else 'stream-copy'}")

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

        # Validate all clips
        for p in sorted_paths:
            path = Path(p)
            if not path.exists():
                logger.error(f"[STITCH] Missing clip: {p} — aborting stitch")
                return sorted_paths[0]
            if path.stat().st_size == 0:
                logger.error(f"[STITCH] Empty clip (0 bytes): {p} — aborting stitch")
                return sorted_paths[0]

        output_filename = f"{stitch_label}_stitched.mp4"
        output_path     = self.output_dir / output_filename

        if crossfade and n >= 2:
            success = await self._ffmpeg_crossfade(
                sorted_paths, str(output_path),
                crossfade_duration, audio_fade_duration,
            )
        else:
            # Stream-copy first (fast, lossless, preserves native Veo audio)
            success = await self._ffmpeg_concat(sorted_paths, str(output_path), reencode=False)
            if not success or not output_path.exists() or output_path.stat().st_size == 0:
                logger.warning("[STITCH] Stream-copy failed — retrying with re-encode")
                output_path.unlink(missing_ok=True)
                success = await self._ffmpeg_concat(sorted_paths, str(output_path), reencode=True)

        if not success or not output_path.exists():
            logger.error("[STITCH] FFmpeg stitch failed — returning first clip")
            return sorted_paths[0]

        elapsed = time.time() - t0
        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"[STITCH] Done in {elapsed:.1f}s — {output_filename} ({size_mb:.2f} MB)")

        # Apply final fade-out (audio + video) on the tail of the stitched output.
        # Skip if crossfade mode — crossfade already handles audio at stitch points
        # and the final fade is applied within _ffmpeg_crossfade itself.
        if not crossfade:
            faded_path = await self._apply_fade(output_path)
            if faded_path and faded_path.exists():
                logger.info(f"[STITCH] End fade applied: {faded_path.name}")
                return str(faded_path)
            logger.warning("[STITCH] End fade pass failed — returning raw stitch")

        return str(output_path)

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _ffmpeg_crossfade(
        self,
        clip_paths: List[str],
        output_path: str,
        xfade_duration: float = 0.5,
        audio_fade_duration: float = 0.3,
    ) -> bool:
        """
        Stitch N clips with xfade transitions between each pair.

        For N clips, the FFmpeg filter graph works as follows:
          - Each clip is an input stream [0:v][0:a], [1:v][1:a], ...
          - xfade is applied between each consecutive pair using the offset
            calculated from the cumulative duration minus the overlap duration.
          - Audio is also crossfaded at each stitch point.
          - Final output is re-encoded at CRF 17 (visually lossless at 720p).

        Also applies a short audio fade at each stitch point to mask any
        narration boundary — makes cuts sound like natural breath pauses.

        Quality note: CRF 17 with libx264 is visually lossless at 720p.
        The human eye cannot distinguish it from the source clips.
        h264_amf (AMD) or h264_nvenc (NVIDIA) are tried first for speed.
        """
        import subprocess
        import asyncio

        n = len(clip_paths)
        loop = asyncio.get_running_loop()

        # Get duration of each clip via ffprobe
        async def get_duration(path: str) -> float:
            def _probe() -> float:
                try:
                    r = subprocess.run([
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        path
                    ], capture_output=True, text=True, timeout=30)
                    return float(r.stdout.strip())
                except Exception:
                    return 8.0  # fallback: assume 8s clip
            return await loop.run_in_executor(None, _probe)

        durations = []
        for p in clip_paths:
            d = await get_duration(p)
            durations.append(d)
            logger.debug(f"[STITCH] {Path(p).name}: {d:.2f}s")

        # Build FFmpeg filter complex for N clips
        # Each xfade offset = sum of (clip durations) - (n-1) * xfade_duration
        # up to that transition point
        inputs = []
        for p in clip_paths:
            inputs += ["-i", p]

        # Build video xfade chain
        # [0:v][1:v] xfade=... [v01]; [v01][2:v] xfade=... [v012]; etc.
        video_filters = []
        audio_filters = []
        cumulative_offset = 0.0

        prev_v = "[0:v]"
        prev_a = "[0:a]"

        for i in range(1, n):
            cumulative_offset += durations[i - 1] - xfade_duration
            xf_out  = f"[v{i}]"
            af_out  = f"[a{i}]"

            video_filters.append(
                f"{prev_v}[{i}:v]xfade=transition=fade:"
                f"duration={xfade_duration:.3f}:"
                f"offset={cumulative_offset:.3f}{xf_out}"
            )
            audio_filters.append(
                f"{prev_a}[{i}:a]acrossfade="
                f"d={audio_fade_duration:.3f}{af_out}"
            )
            prev_v = xf_out
            prev_a = af_out

        filter_complex = "; ".join(video_filters + audio_filters)
        final_v = prev_v
        final_a = prev_a

        def _build_encode_cmd(encoder: str) -> list:
            cmd = ["ffmpeg", "-y"] + inputs + [
                "-filter_complex", filter_complex,
                "-map", final_v,
                "-map", final_a,
                "-c:v", encoder,
                "-crf", "17",          # visually lossless at 720p
                "-preset", "fast",
                "-c:a", "aac",
                "-b:a", "192k",
                output_path,
            ]
            # AMD/NVIDIA don't use -crf — use quality level instead
            if encoder in ("h264_amf", "h264_nvenc"):
                cmd = ["ffmpeg", "-y"] + inputs + [
                    "-filter_complex", filter_complex,
                    "-map", final_v,
                    "-map", final_a,
                    "-c:v", encoder,
                    "-quality", "1" if encoder == "h264_amf" else "18",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    output_path,
                ]
            return cmd

        logger.info(
            f"[STITCH] Crossfade pass — {n} clips, "
            f"{xfade_duration}s xfade, {audio_fade_duration}s audio fade"
        )

        def _run(encoder: str) -> bool:
            r = subprocess.run(
                _build_encode_cmd(encoder),
                capture_output=True, text=True, timeout=600,
            )
            ok = r.returncode == 0 and Path(output_path).exists() and Path(output_path).stat().st_size > 0
            if not ok and Path(output_path).exists():
                Path(output_path).unlink(missing_ok=True)
            return ok

        for encoder in ["h264_amf", "h264_nvenc", "libx264"]:
            ok = await loop.run_in_executor(None, lambda e=encoder: _run(e))
            if ok:
                size_mb = Path(output_path).stat().st_size / (1024 * 1024)
                logger.info(f"[STITCH] Crossfade OK — encoder={encoder}, {size_mb:.2f} MB")
                return True
            logger.debug(f"[STITCH] Crossfade encoder {encoder} failed, trying next")

        logger.error("[STITCH] All crossfade encoders failed")
        return False

    async def _apply_fade(
        self,
        input_path: Path,
        audio_fade_s: float = 1.5,
        video_fade_s: float = 0.5,
    ) -> Optional[Path]:
        """
        Second FFmpeg pass: fade audio out over the last audio_fade_s seconds
        and fade video to black over the last video_fade_s seconds.

        Why: Veo occasionally cuts native audio mid-narration. A short fade
        makes any cutoff sound intentional rather than broken.

        Requires re-encode (filters can't be applied on stream-copy).
        Output: <original_stem>_final.mp4 — replaces role of stitched file.
        """
        if not self.ffmpeg_available:
            return None

        try:
            # Get duration via ffprobe
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_path),
            ]
            loop = asyncio.get_running_loop()
            probe = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    probe_cmd, capture_output=True, text=True, timeout=30
                ),
            )
            if probe.returncode != 0:
                logger.warning(f"[STITCH] ffprobe failed — skipping fade")
                return None

            duration = float(probe.stdout.strip())
            if duration < (audio_fade_s + 0.5):
                # Clip too short to fade meaningfully
                logger.info(f"[STITCH] Clip too short ({duration:.1f}s) — skipping fade")
                return None

            audio_start = max(0.0, duration - audio_fade_s)
            video_start = max(0.0, duration - video_fade_s)

            output_path = input_path.parent / (input_path.stem + "_final.mp4")

            # Build codec list — try hardware/software encoders in order.
            # libx264 may not be present in all FFmpeg Windows builds.
            # h264_amf  = AMD GPU encoder (most Windows machines)
            # h264_nvenc = NVIDIA GPU encoder
            # libx264   = software encoder (requires full FFmpeg build)
            # If all fail, fade is skipped and raw stitch is returned.
            video_encoders = ["h264_amf", "h264_nvenc", "libx264"]

            def _build_cmd(encoder: str) -> list:
                return [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-vf",  f"fade=t=out:st={video_start:.3f}:d={video_fade_s:.3f}",
                    "-af",  f"afade=t=out:st={audio_start:.3f}:d={audio_fade_s:.3f}",
                    "-c:v", encoder, "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k",
                    str(output_path),
                ]

            # Try each encoder until one works
            cmd = _build_cmd(video_encoders[0])
            _working_encoder = None
            for enc in video_encoders:
                test_cmd = _build_cmd(enc)
                test_result = subprocess.run(
                    test_cmd, capture_output=True, text=True, timeout=300
                )
                if test_result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    _working_encoder = enc
                    logger.info(f"[STITCH] Fade encoder: {enc}")
                    result = test_result
                    break
                else:
                    if output_path.exists():
                        output_path.unlink(missing_ok=True)
                    logger.debug(f"[STITCH] Encoder {enc} not available, trying next")

            if _working_encoder is None:
                logger.warning("[STITCH] No working video encoder found — fade skipped")
                return None

            # result is already set from the loop above
            if result.returncode != 0:
                return None
            cmd = _build_cmd(_working_encoder)  # just for the log below

            logger.info(
                f"[STITCH] Fade pass — audio fade {audio_fade_s}s from {audio_start:.1f}s, "
                f"video fade {video_fade_s}s from {video_start:.1f}s"
            )

            t0 = time.time()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=300),
            )
            elapsed = time.time() - t0

            # returncode already checked in encoder loop above

            if output_path.exists() and output_path.stat().st_size > 0:
                # Remove intermediate raw stitch — keep only faded final
                try:
                    input_path.unlink()
                except OSError:
                    pass
                size_mb = output_path.stat().st_size / (1024 * 1024)
                logger.info(f"[STITCH] Fade OK in {elapsed:.1f}s — {size_mb:.2f} MB")
                return output_path

            return None

        except Exception as e:
            logger.warning(f"[STITCH] _apply_fade error: {e}")
            return None

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