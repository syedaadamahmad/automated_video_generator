"""
veo_config.py — Central configuration for the Veo Video Generation Platform
═════════════════════════════════════════════════════════════════════════════

Edit this file to change model selection, generation parameters, and output
paths. Veo 3.0 generates video and audio natively — no external audio service
is needed.

Priority:  .env file  >  environment variables  >  defaults in this file
Restart the server after any changes.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class VeoConfig:

    # ── App ───────────────────────────────────────────────────────────────────
    DEBUG   = os.getenv("DEBUG",   "false").lower() == "true"
    APP_ENV = os.getenv("APP_ENV", "local")   # "local" | "staging" | "production"

    # ── Google / Vertex AI ────────────────────────────────────────────────────
    # API key from console.cloud.google.com -> APIs & Services -> Credentials
    GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "")
    # us-central1 required for Veo models (not us-east-1 like Bedrock)
    GOOGLE_LOCATION   = os.getenv("GOOGLE_LOCATION", "us-central1")

    # ── AWS (used by PromptDecomposer — Bedrock Nova 2 Lite + DeepSeek R1) ───
    # Same credentials as your main project. Bedrock is used ONLY for
    # prompt decomposition — Veo video generation stays on Google's API.
    AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID",     "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_DEFAULT_REGION    = os.getenv("AWS_DEFAULT_REGION",    "us-east-1")

    # ── Veo Model Selection ───────────────────────────────────────────────────
    # Primary model — best quality, native audio+video.
    # models/ prefix is REQUIRED — bare model IDs are rejected by the API.
    # Fallback used on quota exhaustion or primary failure.
    #
    # ┌──────────────────────────────────────────┬─────────┬────────┬───────────────┐
    # │ Model ID                                 │ Speed   │Quality │ Native Audio  │
    # ├──────────────────────────────────────────┼─────────┼────────┼───────────────┤
    # │ models/veo-3.0-generate-001          │ Slower  │ Best   │ ✅ Yes        │
    # │ models/veo-3.0-fast-generate-001     │ Fast    │ High   │ ✅ Yes        │
    # └──────────────────────────────────────────┴─────────┴────────┴───────────────┘
    VEO_MODEL_PRIMARY  = os.getenv("VEO_MODEL_PRIMARY",  "models/veo-3.0-generate-001")
    VEO_MODEL_FALLBACK = os.getenv("VEO_MODEL_FALLBACK", "models/veo-3.0-fast-generate-001")

    # ── Veo Generation Parameters ─────────────────────────────────────────────
    # CLIP_DURATION_SECONDS:
    #   Veo 3.0 generates exactly 8s per clip — platform hard limit.
    #   Prompts longer than 8s are decomposed into N clips and stitched.
    VEO_CLIP_DURATION_SECONDS = int(os.getenv("VEO_CLIP_DURATION_SECONDS", "8"))

    # VEO_ASPECT_RATIO: "16:9" | "9:16" | "1:1" | "4:3" | "3:4"
    #   Note: 9:16 may not work via API (known Studio/API divergence as of 2025).
    #   Default 16:9 is the most reliable choice.
    VEO_ASPECT_RATIO = os.getenv("VEO_ASPECT_RATIO", "9:16")

    # VEO_RESOLUTION: "720p" | "1080p" | "4k"
    #   Veo 3.x only. Higher resolution = significantly longer generation time.
    VEO_RESOLUTION = os.getenv("VEO_RESOLUTION", "720p")

    # Audio and person generation are NOT configurable via env.
    # Veo 3.0 always generates audio natively — no API param exists for it.
    # person_generation is permanently excluded from API calls at the generator level.

    # VEO_GENERATE_AUDIO: kept for bookkeeping/logging in VeoGenerator.
    # NOT passed to GenerateVideosConfig — Veo generates audio natively.
    VEO_GENERATE_AUDIO = os.getenv("VEO_GENERATE_AUDIO", "true").lower() == "true"

    # VEO_SAMPLE_COUNT: 1–4 videos per API request.
    #   Keep at 1 for stitching pipelines (one clip per decomposed sub-prompt).
    VEO_SAMPLE_COUNT = int(os.getenv("VEO_SAMPLE_COUNT", "1"))

    # ── Polling ───────────────────────────────────────────────────────────────
    # Veo jobs are long-running operations — typically 2–5 minutes per clip.
    # Poll every 15s, give up after 40 minutes (160 × 15s).
    VEO_POLLING_INTERVAL_SECONDS = int(os.getenv("VEO_POLLING_INTERVAL_SECONDS", "15"))
    VEO_MAX_POLLING_ATTEMPTS     = int(os.getenv("VEO_MAX_POLLING_ATTEMPTS",     "160"))

    # ── Output Directories ────────────────────────────────────────────────────
    OUTPUT_DIR = os.getenv("VEO_OUTPUT_DIR", "generated_videos")
    TEMP_DIR   = os.getenv("VEO_TEMP_DIR",   "temp_processing")

    # ── Concurrency ───────────────────────────────────────────────────────────
    # Clips for a single prompt are generated sequentially to avoid quota spikes.
    MAX_CONCURRENT_CLIPS = int(os.getenv("VEO_MAX_CONCURRENT_CLIPS", "1"))


# Global singleton
veo_config = VeoConfig()