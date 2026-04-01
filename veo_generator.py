"""
veo_generator.py — Google Veo 3.1 Video Generator
══════════════════════════════════════════════════

Responsibilities:
  - Submit a single text-to-video request to Veo via google-genai SDK
  - Poll the long-running operation to completion
  - Download the resulting video to local storage
  - Return a consistent result dict (same shape as RunwayGenerator)

Stitching contract:
  - generate_video() accepts optional clip_label param
  - When provided, filename encodes it: {job_id}_veo_{clip_label}.mp4
  - Alphabetical sort of filenames = correct stitch order for VideoStitcher

Native audio:
  - Veo 3.1 generates audio (speech, SFX, ambient) natively from the prompt
  - generate_audio flag is kept in instance config for bookkeeping/logging
  - It is NOT passed to GenerateVideosConfig — Gemini API does not support this field
  - When audio_mode = "elevenlabs", caller strips audio after download

Error handling taxonomy:
  [VEO_AUTH_ERR]      - Bad or missing API key
  [VEO_SUBMIT_ERR]    - Generation request rejected by API
  [VEO_POLL_TIMEOUT]  - Operation did not complete within max_attempts
  [VEO_POLL_ERR]      - Polling call failed (network/API error)
  [VEO_NO_VIDEO]      - Operation succeeded but returned no video URI/bytes
  [VEO_DOWNLOAD_ERR]  - Video URI returned but download to disk failed
  [VEO_EXCEPTION]     - Unexpected exception (bubbled from SDK or I/O)
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("VEO_GENERATOR")

# ── SDK import guard ──────────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai.types import GenerateVideosConfig
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False
    logger.warning(
        "⚠️  [VEO_GENERATOR] google-genai not installed. "
        "Run: pip install google-genai"
    )


class VeoGenerator:
    """
    Production-ready Google Veo 3.1 video generator.

    One instance is created at startup and reused across all requests.
    The google-genai client is stateless between calls — safe for concurrent use.
    """

    def __init__(
        self,
        api_key: str,
        output_dir: Path,
        model_primary: str  = "models/veo-3.0-generate-001",
        model_fallback: str = "models/veo-3.0-fast-generate-001",
        clip_duration: int  = 8,
        aspect_ratio: str   = "16:9",
        resolution: str     = "720p",
        generate_audio: bool = True,
        # person_generation: str = "disallow",
        sample_count: int   = 1,
        polling_interval_s: int = 15,
        max_polling_attempts: int = 160,
    ):
        if not _GENAI_AVAILABLE:
            raise ImportError(
                "google-genai is required. Install with: pip install google-genai"
            )
        if not api_key:
            raise ValueError("[VEO_AUTH_ERR] GOOGLE_API_KEY is required but not set.")

        self.api_key              = api_key
        self.output_dir           = Path(output_dir)
        # Normalise model IDs — the v1beta endpoint requires the full
        # "models/" prefix. Strip any existing prefix first to avoid doubling.
        self.model_primary  = self._normalise_model_id(model_primary)
        self.model_fallback = self._normalise_model_id(model_fallback)
        self.clip_duration        = clip_duration
        self.aspect_ratio         = aspect_ratio
        self.resolution           = resolution
        self.generate_audio       = generate_audio   # kept for logging/bookkeeping only
        # self.person_generation    = person_generation
        self.sample_count         = sample_count
        self.polling_interval_s   = polling_interval_s
        self.max_polling_attempts = max_polling_attempts

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialise client once — it holds no mutable call state
        # v1beta is required: Veo 3.x preview models are only available on
        # this API version. Without it the endpoint returns 404 / model-not-found.
        self._client = genai.Client(
            api_key      = self.api_key,
            http_options = {"api_version": "v1beta"},
        )

        logger.info("🎬 [VEO_INIT] VeoGenerator initialised")
        logger.info(f"   🔧 Primary model  : {self.model_primary}")
        logger.info(f"   🔧 Fallback model : {self.model_fallback}")
        logger.info(f"   🎞️  Clip duration  : {self.clip_duration}s (Veo 3.1 hard limit)")
        logger.info(f"   📐 Aspect ratio   : {self.aspect_ratio}")
        logger.info(f"   📺 Resolution     : {self.resolution}")
        logger.info(f"   🔊 Native audio   : {'enabled' if self.generate_audio else 'disabled'} (Veo-native, not passed to API config)")
        # logger.info(f"   👤 Person gen     : {self.person_generation}")
        logger.info(f"   ⏱️  Polling        : every {self.polling_interval_s}s, max {self.max_polling_attempts} attempts")

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_model_id(model_id: str) -> str:
        """
        Ensure model ID carries the required 'models/' prefix.

        The v1beta endpoint treats model IDs as resource names and requires
        the full path. Strip any existing prefix first to avoid 'models/models/'.

        Examples:
            "veo-3.1-generate-preview"       -> "models/veo-3.1-generate-preview"
            "models/veo-3.1-generate-preview" -> "models/veo-3.1-generate-preview"
        """
        model_id = model_id.strip()
        if not model_id.startswith("models/"):
            model_id = f"models/{model_id}"
        return model_id

    # ── Public API ─────────────────────────────────────────────────────────────

    async def generate_video(
        self,
        prompt: str,
        duration: int = 8,
        job_id: str = "job_unknown",
        prompt_index: int = 0,
        clip_label: Optional[str] = None,
        generate_audio: Optional[bool] = None,
        reference_image_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Generate a single Veo video clip.

        Args:
            prompt:               Video description sent to Veo.
            duration:             Requested duration (ignored for Veo — always 8s per clip).
                                  Kept for interface parity with RunwayGenerator.
            job_id:               Job identifier used in output filename.
            prompt_index:         Prompt row index (used in filename if clip_label not set).
            clip_label:           Optional clip sequence label e.g. "p1_clip_001".
                                  When set, filename encodes clip order for VideoStitcher.
            generate_audio:       Per-call override for native audio flag (bookkeeping only).
                                  Does not affect the API request — Veo generates audio
                                  natively and the field is not accepted by GenerateVideosConfig.
            reference_image_path: Optional path to a JPEG/PNG to use as the first-frame
                                  anchor (img2vid). When set, Veo generates the clip
                                  continuing from this image — used for cross-clip continuity.

        Returns:
            {
                status:           "completed" | "failed"
                video_url:        "/videos/{filename}"   (only when completed)
                duration_seconds: int                    (always 8 for Veo 3.1)
                platform:         "veo"
                model_used:       str
                has_native_audio: bool
                clip_label:       str | None
                error_message:    str                    (only when failed)
                error_type:       str                    (only when failed)
            }
        """
        use_audio = generate_audio if generate_audio is not None else self.generate_audio

        logger.info(f"🎬 [VEO] Starting generation — prompt {prompt_index + 1}")
        logger.info(f"   📝 Prompt     : '{prompt[:80]}{'...' if len(prompt) > 80 else ''}'")
        logger.info(f"   🆔 Job ID     : {job_id}")
        logger.info(f"   🏷️  Clip label : {clip_label or '(none)'}")
        logger.info(f"   🔊 Audio      : {'native (Veo-controlled)' if use_audio else 'muted (post-process)'}")
        logger.info(f"   🖼️  Ref image  : {reference_image_path.name if reference_image_path else '(none — text-to-video)' }")

        # Build attempt sequence:
        # 1. Primary   — with reference image (img2vid) if provided
        # 2. Fallback  — with reference image (img2vid) if provided
        # 3. Primary   — text-only (if img2vid failed on both; content policy guard)
        # 4. Fallback  — text-only (last resort)
        #
        # VEO_NO_VIDEO on img2vid = silent content policy block (e.g. minors in frame).
        # Degrading to text-only lets generation continue with narrative continuity
        # preserved by the prompt even when visual chaining is blocked.
        has_image = reference_image_path is not None
        # Metrics counters — accumulated across all attempts and returned in result
        _api_calls_made  = 0
        _rate_limit_hits = 0

        attempts = [
            (self.model_primary,  "PRIMARY",  reference_image_path),
            (self.model_fallback, "FALLBACK", reference_image_path),
        ]
        if has_image:
            # Add text-only fallbacks in case img2vid is blocked
            attempts += [
                (self.model_primary,  "PRIMARY-TEXT",  None),
                (self.model_fallback, "FALLBACK-TEXT", None),
            ]

        for model, label, img_path in attempts:
            is_text_only_retry = has_image and img_path is None
            if is_text_only_retry:
                logger.warning(
                    f"   ⚠️  img2vid blocked (VEO_NO_VIDEO) — retrying [{label}] as text-only"
                )

            _api_calls_made += 1
            result = await self._attempt_generation(
                prompt                = prompt,
                model                 = model,
                model_label           = label,
                job_id                = job_id,
                prompt_index          = prompt_index,
                clip_label            = clip_label,
                use_audio             = use_audio,
                reference_image_path  = img_path,
            )
            if result["status"] == "completed":
                if is_text_only_retry:
                    logger.info(f"   ✅ [{label}] Succeeded as text-only after img2vid block")
                result["api_calls_made"]  = _api_calls_made
                result["rate_limit_hits"] = _rate_limit_hits
                return result

            error_type = result.get("error_type", "")
            error_msg  = result.get("error_message", "")
            logger.warning(
                f"   ⚠️  [{label}] model {model} failed — "
                f"error_type={error_type} | "
                f"msg={error_msg[:80]}"
            )

            # Rate limit (429): wait 60s then retry the SAME attempt once.
            # Do NOT advance to text-only fallbacks — text-only won't fix a rate limit.
            if error_type == "VEO_SUBMIT_ERR" and "429" in error_msg:
                _rate_limit_hits += 1
                if label in ("PRIMARY", "PRIMARY-TEXT"):
                    logger.warning("   ⏳ [RATE_LIMIT] 429 received — waiting 60s before retrying FALLBACK...")
                    await asyncio.sleep(60)
                    logger.info("   🔄 Retrying with FALLBACK model after backoff...")
                    continue   # advance to FALLBACK (or FALLBACK-TEXT)
                else:
                    # FALLBACK also rate-limited — nothing more to try right now
                    logger.error("   ❌ [RATE_LIMIT] Both models rate-limited — aborting this clip")
                    break

            # VEO_NO_VIDEO on img2vid — degrade to text-only
            if has_image and not is_text_only_retry:
                if error_type != "VEO_NO_VIDEO":
                    # Non-img2vid, non-rate-limit error (e.g. VEO_SUBMIT_ERR without 429)
                    # FALLBACK model is tried for PRIMARY failures, then we stop.
                    if label == "PRIMARY":
                        logger.info("   🔄 Retrying with FALLBACK model...")
                        continue
                    else:
                        break   # FALLBACK also failed — stop, text-only won't help
                if label == "PRIMARY":
                    logger.info("   🔄 Retrying with FALLBACK model (VEO_NO_VIDEO)...")
            elif label in ("PRIMARY", "PRIMARY-TEXT"):
                logger.info("   🔄 Retrying with FALLBACK model...")

        # All attempts failed — return the last failure result
        result["error_message"] = (
            f"Both primary ({self.model_primary}) and fallback "
            f"({self.model_fallback}) models failed. "
            f"Last error: {result.get('error_message', 'unknown')}"
        )
        result["api_calls_made"]  = _api_calls_made
        result["rate_limit_hits"] = _rate_limit_hits
        return result

    # ── Internal: single model attempt ────────────────────────────────────────

    async def _attempt_generation(
        self,
        prompt: str,
        model: str,
        model_label: str,
        job_id: str,
        prompt_index: int,
        clip_label: Optional[str],
        use_audio: bool,
        reference_image_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Submit, poll, and download for one specific model."""

        start_time = time.time()
        logger.info(f"   🚀 [{model_label}] Submitting to model: {model}")

        # ── Step 1: Build image anchor (img2vid chaining) ─────────────────────
        ref_image_obj = None
        if reference_image_path and reference_image_path.exists():
            try:
                img_bytes     = reference_image_path.read_bytes()
                suffix        = reference_image_path.suffix.lower()
                mime          = "image/png" if suffix == ".png" else "image/jpeg"
                ref_image_obj = genai.types.Image(image_bytes=img_bytes, mime_type=mime)
                logger.info(
                    f"   🖼️  [{model_label}] Loaded reference image: "
                    f"{reference_image_path.name} ({len(img_bytes) / 1024:.1f} KB)"
                )
            except Exception as e:
                logger.warning(
                    f"   ⚠️  [{model_label}] Could not load reference image "
                    f"{reference_image_path}: {e} — falling back to text-only"
                )
                ref_image_obj = None

        # ── Step 2: Submit ────────────────────────────────────────────────────
        # No pre-submission delay needed at concurrency=1.
        # Sequential clips within a prompt take 70-100s each — naturally
        # under 2 RPM without any artificial wait.
        # 429 backoff (60s) in the attempt loop handles bursts if they occur.
        try:
            def _submit() -> Any:
                kwargs: Dict[str, Any] = dict(
                    model  = model,
                    prompt = prompt,
                    config = GenerateVideosConfig(
                        aspect_ratio     = self.aspect_ratio,
                        resolution       = self.resolution,
                        duration_seconds = self.clip_duration,
                        number_of_videos = self.sample_count,
                        # person_generation intentionally omitted — any value
                        # ("dont_allow" or "allow_adult") causes API errors or
                        # silent VEO_NO_VIDEO failures. Omitting lets Veo use
                        # its own default safely for both text and img2vid calls.
                    ),
                )
                if ref_image_obj is not None:
                    kwargs["image"] = ref_image_obj
                return self._client.models.generate_videos(**kwargs)

            operation = await asyncio.get_event_loop().run_in_executor(None, _submit)
        except Exception as e:
            err = str(e)
            logger.error(f"   ❌ [VEO_SUBMIT_ERR] Submit failed: {err}")
            return {
                "status":        "failed",
                "platform":      "veo",
                "model_used":    model,
                "error_message": err,
                "error_type":    "VEO_SUBMIT_ERR",
            }

        logger.info(f"   ✅ [{model_label}] Submitted — operation ID: {getattr(operation, 'name', 'unknown')}")

        # ── Step 2: Poll ──────────────────────────────────────────────────────
        logger.info(f"   ⏳ [{model_label}] Polling every {self.polling_interval_s}s ...")

        completed_operation = await self._poll_operation(operation, model_label)

        if completed_operation is None:
            return {
                "status":        "failed",
                "platform":      "veo",
                "model_used":    model,
                "error_message": f"Operation timed out after {self.max_polling_attempts} attempts",
                "error_type":    "VEO_POLL_TIMEOUT",
            }

        # ── Step 3: Extract video ─────────────────────────────────────────────
        try:
            generated_videos = (
                completed_operation.response.generated_videos
                if hasattr(completed_operation, "response") and completed_operation.response
                else []
            )
        except Exception as e:
            logger.error(f"   ❌ [VEO_NO_VIDEO] Could not read response: {e}")
            return {
                "status":        "failed",
                "platform":      "veo",
                "model_used":    model,
                "error_message": f"Could not parse operation response: {e}",
                "error_type":    "VEO_NO_VIDEO",
            }

        if not generated_videos:
            logger.error("   ❌ [VEO_NO_VIDEO] Operation completed but returned no videos")
            return {
                "status":        "failed",
                "platform":      "veo",
                "model_used":    model,
                "error_message": "Operation succeeded but no videos were returned",
                "error_type":    "VEO_NO_VIDEO",
            }

        generated_video = generated_videos[0]

        # ── Step 4: Download ──────────────────────────────────────────────────
        local_url = await self._download_video(
            generated_video = generated_video,
            job_id          = job_id,
            prompt_index    = prompt_index,
            clip_label      = clip_label,
        )

        if not local_url:
            return {
                "status":        "failed",
                "platform":      "veo",
                "model_used":    model,
                "error_message": "Generation completed but video download/save failed",
                "error_type":    "VEO_DOWNLOAD_ERR",
            }

        elapsed = time.time() - start_time
        logger.info(f"   ✅ [{model_label}] Done in {elapsed:.1f}s → {local_url}")

        return {
            "status":           "completed",
            "video_url":        local_url,
            "duration_seconds": self.clip_duration,
            "platform":         "veo",
            "model_used":       model,
            "has_native_audio": use_audio,
            "clip_label":       clip_label,
            "generation_time_seconds": round(elapsed, 1),
        }

    # ── Internal: polling ──────────────────────────────────────────────────────

    async def _poll_operation(self, operation: Any, model_label: str) -> Optional[Any]:
        """
        Poll a long-running Veo operation until done or timeout.

        The google-genai SDK exposes operation.done (bool) and
        client.operations.get(operation) to refresh it.

        Returns the completed operation object, or None on timeout/error.
        """
        for attempt in range(1, self.max_polling_attempts + 1):
            try:
                if operation.done:
                    logger.info(f"   ✅ [{model_label}] Completed on poll #{attempt}")
                    return operation

                elapsed_min = (attempt * self.polling_interval_s) / 60
                logger.info(
                    f"   📊 [{model_label}] Poll {attempt}/{self.max_polling_attempts} "
                    f"— not done yet ({elapsed_min:.1f} min elapsed)"
                )

                await asyncio.sleep(self.polling_interval_s)

                # Refresh operation status from API
                operation = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._client.operations.get(operation),
                )

            except Exception as e:
                logger.warning(
                    f"   ⚠️  [{model_label}] [VEO_POLL_ERR] Poll attempt {attempt} failed: {e}"
                )
                # Don't abort on transient network errors — keep polling
                if attempt < self.max_polling_attempts:
                    await asyncio.sleep(self.polling_interval_s)

        logger.error(
            f"   ⏰ [{model_label}] [VEO_POLL_TIMEOUT] "
            f"Timed out after {self.max_polling_attempts} attempts "
            f"({self.max_polling_attempts * self.polling_interval_s / 60:.0f} min)"
        )
        return None

    # ── Internal: download / save ─────────────────────────────────────────────

    async def _download_video(
        self,
        generated_video: Any,
        job_id: str,
        prompt_index: int,
        clip_label: Optional[str],
    ) -> Optional[str]:
        """
        Save a generated video to local disk.

        Veo returns videos as either:
          - video.uri  (GCS URI) — if storageUri was configured
          - video.video_bytes    — raw bytes inline (our path, no GCS needed)

        We always use the bytes path to avoid requiring a GCS bucket.
        Falls back to downloading from URI if bytes are absent.
        """
        logger.info("   📥 [VEO_DOWNLOAD] Saving video to disk...")

        # Filename encodes clip order when clip_label is set
        if clip_label:
            filename = f"{job_id}_veo_{clip_label}.mp4"
        else:
            filename = f"{job_id}_veo_p{prompt_index + 1}.mp4"

        local_path = self.output_dir / filename

        try:
            video_obj = generated_video.video

            # ── Path A: inline bytes (no GCS bucket required) ─────────────────
            video_bytes = getattr(video_obj, "video_bytes", None)
            if video_bytes:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: local_path.write_bytes(video_bytes),
                )
                size_mb = local_path.stat().st_size / (1024 * 1024)
                local_url = f"/videos/{filename}"
                logger.info(f"   ✅ Saved from bytes: {size_mb:.2f} MB → {local_url}")
                return local_url

            # ── Path B: GCS URI — direct HTTP byte download ──────────────
            # The SDK's video_obj.save() / files.download() pattern hangs
            # indefinitely on Veo GCS URIs. Instead, download the bytes
            # directly via httpx using the same API key for auth.
            uri = getattr(video_obj, "uri", None) or getattr(video_obj, "gcs_uri", None)
            if uri:
                logger.info(f"   📎 GCS URI returned: {uri}")

                def _download_bytes(url: str) -> bytes:
                    # Append API key — GCS URIs from Gemini API require it
                    sep = "&" if "?" in url else "?"
                    auth_url = f"{url}{sep}key={self.api_key}"
                    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
                        resp = client.get(auth_url)
                        resp.raise_for_status()
                        return resp.content

                video_bytes_gcs = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _download_bytes(uri),
                )
                if video_bytes_gcs:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: local_path.write_bytes(video_bytes_gcs),
                    )
                    size_mb = local_path.stat().st_size / (1024 * 1024)
                    local_url = f"/videos/{filename}"
                    logger.info(f"   ✅ Saved from GCS: {size_mb:.2f} MB → {local_url}")
                    return local_url

            logger.error("   ❌ [VEO_DOWNLOAD_ERR] No video_bytes or URI in response")
            return None

        except Exception as e:
            logger.error(f"   ❌ [VEO_DOWNLOAD_ERR] {e}")
            return None