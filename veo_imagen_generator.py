"""
veo_imagen_generator.py — Google Imagen Text-to-Image Generator
════════════════════════════════════════════════════════════════

Uses the same GOOGLE_API_KEY already in veo.env — no Vertex AI,
no service account, no gcloud commands needed.

API endpoint:
  POST https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict

The response contains base64-encoded PNG bytes which are decoded and
saved to disk. No new dependencies — uses only httpx (already installed
for Veo) and base64 (stdlib).

Config (in veo.env / environment):
  GOOGLE_API_KEY=<your-existing-key>   ← same key used for Veo
  IMAGEN_MODEL=imagen-3.0-generate-001  ← optional, this is the default
"""

import base64
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("IMAGEN_GENERATOR")

_BASE_URL    = "https://generativelanguage.googleapis.com/v1beta/models"
_TIMEOUT_S   = 120

# No-text guardrail injected when no_text=True
_NO_TEXT_GUARDRAIL = (
    "No text, captions, titles, watermarks, subtitles, labels, "
    "or written words anywhere in the image."
)

# Aspect ratio → Imagen API string
_AR_MAP = {
    "9:16": "9:16",
    "16:9": "16:9",
    "1:1":  "1:1",
    "4:3":  "4:3",
    "3:4":  "3:4",
}

# Aspect ratio → pixel dimensions for FFmpeg
_AR_PIXELS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1":  (1080, 1080),
    "4:3":  (1440, 1080),
    "3:4":  (1080, 1440),
}


class ImagenGenerator:
    """
    Thin wrapper around the Gemini API Imagen endpoint.

    Uses the same GOOGLE_API_KEY as the Veo generator — no extra
    credentials or SDK needed.
    """

    def __init__(
        self,
        api_key: str,
        model_id: str   = "imagen-3.0-generate-001",
        output_dir: Path = Path("outputs/videos"),
    ):
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY is empty — cannot initialise ImagenGenerator. "
                "Add GOOGLE_API_KEY=<your-key> to veo.env."
            )
        self.api_key    = api_key
        self.model_id   = model_id
        self.output_dir = Path(output_dir)

        logger.info(f"ImagenGenerator ready — model={model_id}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_image(
        self,
        prompt: str,
        output_name: str,
        aspect_ratio: str = "9:16",
        no_text: bool = False,
        seed: Optional[int] = None,
    ) -> dict:
        """
        Generate a single image and save it as PNG.

        Args:
            prompt:       Text prompt.
            output_name:  Filename stem (no extension) for the saved file.
            aspect_ratio: "9:16" | "16:9" | "1:1" | "4:3". Default "9:16".
            no_text:      Append no-text guardrail to the prompt.
            seed:         Optional seed for reproducibility.

        Returns:
            {
                status:     "completed" | "failed"
                image_path: str   absolute path to saved PNG
                image_url:  str   "/images/filename.png"
                prompt_used:str
                model_used: str
                elapsed_s:  float
                error:      str   (only on failure)
            }
        """
        full_prompt = f"{prompt} {_NO_TEXT_GUARDRAIL}" if no_text else prompt
        api_ar      = _AR_MAP.get(aspect_ratio.strip(), "9:16")
        start       = time.time()

        logger.info(f"[IMAGEN] Generating image | ar={api_ar}")
        logger.info(f"   Prompt: '{full_prompt[:100]}...'")

        url     = f"{_BASE_URL}/{self.model_id}:predict?key={self.api_key}"
        payload: dict = {
            "instances": [{"prompt": full_prompt}],
            "parameters": {
                "sampleCount":  1,
                "aspectRatio":  api_ar,
            },
        }
        if seed is not None:
            payload["parameters"]["seed"] = seed

        try:
            with httpx.Client(timeout=_TIMEOUT_S) as client:
                response = client.post(url, json=payload)

            if response.status_code != 200:
                raise RuntimeError(
                    f"Imagen API returned {response.status_code}: "
                    f"{response.text[:300]}"
                )

            data = response.json()
            predictions = data.get("predictions", [])
            if not predictions:
                raise ValueError(
                    "Imagen API returned no predictions — possible content policy block. "
                    f"Response: {data}"
                )

            # Decode base64 PNG
            b64_bytes = predictions[0].get("bytesBase64Encoded", "")
            if not b64_bytes:
                raise ValueError(
                    f"Imagen prediction missing bytesBase64Encoded. "
                    f"Keys present: {list(predictions[0].keys())}"
                )

            image_bytes = base64.b64decode(b64_bytes)

            # Save to disk
            self.output_dir.mkdir(parents=True, exist_ok=True)
            safe_name  = output_name.replace("/", "_").replace("\\", "_")
            image_path = self.output_dir / f"{safe_name}.png"
            image_path.write_bytes(image_bytes)

            elapsed = time.time() - start
            size_kb = len(image_bytes) / 1024

            logger.info(
                f"[IMAGEN] ✅ Saved {image_path.name} "
                f"({size_kb:.0f} KB) in {elapsed:.1f}s"
            )

            return {
                "status":      "completed",
                "image_path":  str(image_path),
                "image_url":   f"/images/{image_path.name}",
                "prompt_used": full_prompt,
                "model_used":  self.model_id,
                "elapsed_s":   round(elapsed, 1),
            }

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"[IMAGEN] ❌ Failed in {elapsed:.1f}s: {e}")
            return {
                "status":    "failed",
                "error":     str(e),
                "elapsed_s": round(elapsed, 1),
            }

    @staticmethod
    def ar_to_pixels(aspect_ratio: str) -> tuple:
        """Return (width, height) in pixels for the given aspect ratio."""
        return _AR_PIXELS.get(aspect_ratio.strip(), (1080, 1920))