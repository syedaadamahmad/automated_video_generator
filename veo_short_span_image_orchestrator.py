"""
veo_short_span_image_orchestrator.py — Short Span Image Slideshow Pipeline
═══════════════════════════════════════════════════════════════════════════

Pipeline:
  1. Each Excel row → one Imagen API call → one PNG
  2. Each PNG → FFmpeg Ken Burns clip (slow zoom in/out, N seconds)
  3. All Ken Burns clips → FFmpeg xfade crossfade concat → final MP4
  4. Final MP4 → S3 upload

Ken Burns effect:
  - Even-indexed images: slow zoom in  (scale 1.0 → 1.25 over duration)
  - Odd-indexed images:  slow zoom out (scale 1.25 → 1.0 over duration)
  - This alternation creates natural visual rhythm across the sequence.
  - Pan direction also alternates (centre → top-left → centre → top-right...).

Audio:
  - Silent. Images have no Veo audio pipeline.
  - Add an audio track in post using your own narration or music.

Usage in veo_main.py:
  from veo_short_span_image_orchestrator import ShortSpanImageOrchestrator
  img_orch = ShortSpanImageOrchestrator(imagen_generator, stitcher, s3_client)
  result   = await img_orch.run(prompts, job_id, hold_duration_s=5)
"""

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from veo_s3 import VeoS3Client

logger = logging.getLogger("SS_IMAGE_ORCH")

# ── FFmpeg Ken Burns constants ─────────────────────────────────────────────────
_FPS          = 24
_CROSSFADE_S  = 0.5    # seconds of xfade crossfade between consecutive images
_MAX_ZOOM     = 1.25   # zoom range: 1.0 ↔ 1.25


class ShortSpanImageOrchestrator:
    """
    Generates a slideshow from per-row text-to-image prompts.
    Each image gets a Ken Burns effect, then all are crossfaded into one MP4.
    """

    def __init__(
        self,
        imagen_generator,                          # ImagenGenerator instance
        stitcher,                                  # VideoStitcher (for output_dir + ffmpeg path)
        s3_client: Optional[VeoS3Client] = None,
    ):
        self.imagen  = imagen_generator
        self.stitcher= stitcher
        self.s3      = s3_client

        logger.info("ShortSpanImageOrchestrator initialised")
        logger.info(f"   FFmpeg    : {'available' if stitcher.ffmpeg_available else 'DISABLED'}")
        logger.info(f"   S3 upload : {'enabled' if s3_client and s3_client.enabled else 'local only'}")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(
        self,
        prompts: List[Dict[str, Any]],
        job_id: str,
        hold_duration_s: float = 5.0,
        aspect_ratio: str = "9:16",
        no_text: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate all images and return a stitched Ken Burns slideshow.

        Args:
            prompts:         List of prompt dicts — one per Excel row.
            job_id:          Used in filenames and S3 paths.
            hold_duration_s: How long each image is held (2.0 or 5.0).
            aspect_ratio:    "9:16" | "16:9" | "1:1". Applies to all images.
            no_text:         Prepend no-text guardrail to every prompt.

        Returns:
            Result dict — same shape as ShortSpanOrchestrator for frontend compat.
        """
        n        = len(prompts)
        start    = time.time()
        hold_dur = max(2.0, min(5.0, float(hold_duration_s)))

        logger.info(
            f"[SS_IMAGE] {job_id} — {n} image(s), {hold_dur}s each, "
            f"ar={aspect_ratio}, no_text={no_text}"
        )

        image_paths: List[Path] = []
        kb_clip_paths: List[str] = []
        failed = 0

        # ── Step 1: Generate images ────────────────────────────────────────────
        for idx, prompt_data in enumerate(prompts):
            raw_text    = (prompt_data.get("text") or "").strip()
            output_name = f"{job_id}_img_{idx + 1:03d}"

            logger.info(f"[SS_IMAGE] [{idx + 1}/{n}] '{raw_text[:80]}...'")

            result = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda p=raw_text, n=output_name: self.imagen.generate_image(
                    prompt       = p,
                    output_name  = n,
                    aspect_ratio = aspect_ratio,
                    no_text      = no_text,
                )
            )

            if result["status"] != "completed":
                logger.warning(
                    f"[SS_IMAGE] Image {idx + 1} failed: {result.get('error')} — skipping"
                )
                failed += 1
                continue

            image_paths.append(Path(result["image_path"]))
            logger.info(f"[SS_IMAGE] Image {idx + 1} OK → {result['image_path']}")

        if not image_paths:
            return {
                "status":        "failed",
                "error_message": f"All {n} image generations failed.",
                "clips_count":   0,
            }

        # ── Step 2: Apply Ken Burns to each image → short video clip ──────────
        w, h = self.imagen.ar_to_pixels(aspect_ratio)

        for img_idx, img_path in enumerate(image_paths):
            kb_path = await self._apply_ken_burns(
                image_path = img_path,
                output_dir = self.stitcher.output_dir,
                duration_s = hold_dur,
                width      = w,
                height     = h,
                zoom_in    = (img_idx % 2 == 0),   # alternate zoom direction
                img_index  = img_idx,
            )
            if kb_path:
                kb_clip_paths.append(str(kb_path))
                logger.info(f"[SS_IMAGE] Ken Burns clip {img_idx + 1} → {kb_path.name}")
            else:
                logger.warning(f"[SS_IMAGE] Ken Burns failed for image {img_idx + 1}")
                failed += 1

        if not kb_clip_paths:
            return {
                "status":        "failed",
                "error_message": "Ken Burns conversion failed for all images.",
                "clips_count":   0,
            }

        # ── Step 3: Crossfade concat all Ken Burns clips ───────────────────────
        stitched_path = await self._crossfade_concat(
            clip_paths = kb_clip_paths,
            job_id     = job_id,
            width      = w,
            height     = h,
        )

        elapsed = time.time() - start

        if not stitched_path:
            # Fallback to first clip
            local_url = f"/videos/{Path(kb_clip_paths[0]).name}"
            logger.warning("[SS_IMAGE] Crossfade concat failed — returning first clip")
            return self._result(
                status    = "partial",
                local_url = local_url,
                s3_url    = None,
                n_images  = len(kb_clip_paths),
                hold_dur  = hold_dur,
                failed    = failed,
                elapsed   = elapsed,
            )

        # ── Step 4: S3 upload ──────────────────────────────────────────────────
        local_url = f"/videos/{stitched_path.name}"
        s3_url: Optional[str] = None
        if self.s3 and self.s3.enabled:
            s3_url = self.s3.upload_video(
                local_path   = str(stitched_path),
                job_id       = job_id,
                prompt_index = 0,
            )
            if s3_url:
                logger.info(f"[SS_IMAGE] S3 ✅ {s3_url}")
            else:
                logger.warning("[SS_IMAGE] S3 upload failed — local URL used")

        status = "partial" if failed > 0 else "completed"
        logger.info(
            f"[SS_IMAGE] Done in {elapsed:.1f}s — "
            f"{len(kb_clip_paths)} images ok, {failed} failed"
        )

        return self._result(
            status   = status,
            local_url= local_url,
            s3_url   = s3_url,
            n_images = len(kb_clip_paths),
            hold_dur = hold_dur,
            failed   = failed,
            elapsed  = elapsed,
        )

    # ── Ken Burns ──────────────────────────────────────────────────────────────

    async def _apply_ken_burns(
        self,
        image_path: Path,
        output_dir: Path,
        duration_s: float,
        width:  int,
        height: int,
        zoom_in: bool = True,
        img_index: int = 0,
    ) -> Optional[Path]:
        """
        Apply Ken Burns effect to a static image and produce an MP4 clip.

        Alternates direction per image:
          zoom_in=True  → scale 1.0 → 1.25 (gentle zoom toward center)
          zoom_in=False → scale 1.25 → 1.0 (gentle zoom out from center)

        Pan also varies:
          img_index % 4 == 0 → centre
          img_index % 4 == 1 → top-left
          img_index % 4 == 2 → centre
          img_index % 4 == 3 → top-right
        """
        frames     = int(duration_s * _FPS)
        zoom_speed = (_MAX_ZOOM - 1.0) / frames   # per-frame zoom increment

        if zoom_in:
            # Zoom from 1.0 to MAX_ZOOM — z starts at 1, increments up
            zoom_expr = f"min(zoom+{zoom_speed:.6f},{_MAX_ZOOM})"
        else:
            # Zoom from MAX_ZOOM to 1.0 — z starts at MAX_ZOOM, decrements
            zoom_speed_neg = (_MAX_ZOOM - 1.0) / frames
            zoom_expr = f"max(zoom-{zoom_speed_neg:.6f},1.0)"
            # Note: zoompan starts at z=1 by default; for zoom-out we initialise
            # via a reversed approach — actually we can't set start z in zoompan.
            # Use a workaround: reverse time using setpts trick.
            # Simplest correct approach: compute z as fn of frame number.
            # Use: z='if(eq(on,1),{MAX_ZOOM},{MAX_ZOOM}-{speed}*on)'
            zoom_expr = (
                f"if(eq(on,1),{_MAX_ZOOM},"
                f"max({_MAX_ZOOM}-{zoom_speed_neg:.6f}*(on-1),1.0))"
            )

        # Pan: vary x/y anchor based on img_index for subtle movement
        pan_style = img_index % 4
        if pan_style == 0:
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"
        elif pan_style == 1:
            x_expr = "iw*0.1"
            y_expr = "ih*0.1"
        elif pan_style == 2:
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih*0.2"
        else:
            x_expr = "iw*0.6-(iw/zoom/2)"
            y_expr = "ih*0.1"

        out_path = output_dir / f"{image_path.stem}_kb.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i",    str(image_path),
            "-vf",   (
                f"zoompan="
                f"z='{zoom_expr}':"
                f"x='{x_expr}':"
                f"y='{y_expr}':"
                f"d={frames}:"
                f"s={width}x{height}:"
                f"fps={_FPS},"
                f"scale={width}:{height},"
                f"setsar=1"
            ),
            "-t",    str(duration_s),
            "-c:v",  "libx264",
            "-pix_fmt", "yuv420p",
            "-an",   # no audio — silent clip
        ]
        # Hardware encoder fallback chain
        for encoder in ["h264_amf", "h264_nvenc", "libx264"]:
            test_cmd = cmd.copy()
            # Replace encoder
            enc_idx = test_cmd.index("-c:v") + 1
            test_cmd[enc_idx] = encoder
            test_cmd.extend([str(out_path)])

            loop = asyncio.get_running_loop()
            def _run(c=test_cmd):
                r = subprocess.run(c, capture_output=True, timeout=120)
                return r.returncode == 0 and Path(c[-1]).exists()

            try:
                ok = await loop.run_in_executor(None, _run)
                if ok:
                    return out_path
            except Exception as e:
                logger.warning(f"[KB] Encoder {encoder} failed: {e}")
                continue

        logger.error(f"[KB] All encoders failed for {image_path.name}")
        return None

    # ── Crossfade concat ───────────────────────────────────────────────────────

    async def _crossfade_concat(
        self,
        clip_paths: List[str],
        job_id: str,
        width: int,
        height: int,
    ) -> Optional[Path]:
        """
        Concatenate Ken Burns clips with xfade crossfade transitions.

        For N clips of duration D seconds each, with crossfade C seconds:
          - Clip i starts at offset: i * (D - C)
          - Total duration ≈ N*D - (N-1)*C

        The FFmpeg xfade filter chain is built programmatically.
        """
        n = len(clip_paths)
        if n == 1:
            # Single image — just return as-is
            return Path(clip_paths[0])

        out_path   = self.stitcher.output_dir / f"{job_id}_ss_img_stitched.mp4"
        cf_dur     = _CROSSFADE_S

        # Probe clip duration
        loop = asyncio.get_running_loop()
        def _probe_dur(path):
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=10,
            )
            try:
                return float(r.stdout.strip())
            except ValueError:
                return 5.0

        clip_dur = await loop.run_in_executor(None, lambda: _probe_dur(clip_paths[0]))

        # Build xfade filter chain
        # Input streams: [0][1][2]...[N-1]
        # Chain: [0][1]xfade=...[v01]; [v01][2]xfade=...[v012]; ...
        inputs = []
        for cp in clip_paths:
            inputs += ["-i", cp]

        filters = []
        prev_label = "0:v"   # first input video stream

        for i in range(1, n):
            offset    = round(i * (clip_dur - cf_dur), 3)
            out_label = f"v{i}"
            filters.append(
                f"[{prev_label}][{i}:v]"
                f"xfade=transition=fade:duration={cf_dur}:offset={offset}"
                f"[{out_label}]"
            )
            prev_label = out_label

        filter_str = ";".join(filters)

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + [
                "-filter_complex", filter_str,
                "-map",   f"[{prev_label}]",
                "-c:v",   "libx264",
                "-pix_fmt", "yuv420p",
                "-an",    # silent
                str(out_path),
            ]
        )

        def _run():
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            if r.returncode != 0:
                logger.error(f"[SS_IMAGE] xfade concat stderr: {r.stderr.decode()[-500:]}")
            return r.returncode == 0 and out_path.exists()

        ok = await loop.run_in_executor(None, _run)
        return out_path if ok else None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _result(
        self,
        status: str,
        local_url: str,
        s3_url: Optional[str],
        n_images: int,
        hold_dur: float,
        failed: int,
        elapsed: float,
    ) -> Dict[str, Any]:
        """Standardised result dict — same shape as ShortSpanOrchestrator."""
        final_url = s3_url or local_url
        return {
            "status":           status,
            "video_url":        final_url,
            "local_video_url":  local_url,
            "s3_url":           s3_url,
            "duration_seconds": round(n_images * hold_dur, 1),
            "platform":         "imagen",
            "stitched":         True,
            "clips_count":      n_images,
            "clip_urls":        [],
            "model_used":       "imagen-3.0-generate-001",
            "has_native_audio": False,    # silent — add audio in post
            "failed_clips":     failed,
            "generation_time_seconds": round(elapsed, 1),
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