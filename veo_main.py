#!/usr/bin/env python3
"""
veo_main.py — Veo Video Generation Platform
════════════════════════════════════════════

Standalone FastAPI service. Accepts Excel uploads, generates videos via
Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
via FFmpeg, and serves results as downloadable MP4 files.

Veo 3.1 generates video and audio natively from the text prompt — no
post-processing or external audio service is required.

Endpoints:
  GET  /health                → system status
  POST /api/upload            → accept .xlsx/.csv, start background job
  GET  /api/jobs              → list all jobs
  GET  /api/jobs/{job_id}     → job details + per-prompt results
  GET  /videos/{filename}     → serve generated MP4 files

Run:
  python veo_main.py
  -> http://localhost:8100
  -> http://localhost:8100/docs

Port 8100 avoids collision with the Nova/Runway service on 8000.
"""

import asyncio
import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
main_logger       = logging.getLogger("MAIN")
upload_logger     = logging.getLogger("UPLOAD")
generation_logger = logging.getLogger("GENERATION")
progress_logger   = logging.getLogger("PROGRESS")
job_logger        = logging.getLogger("JOB_MANAGER")
health_logger     = logging.getLogger("HEALTH")

# ── Local imports ─────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

try:
    from veo_config import veo_config as config
    main_logger.info("OK veo_config loaded")
    main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
    main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
    main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
except ImportError as e:
    main_logger.critical(f"[CONFIG_ERROR] {e}")
    sys.exit(1)

try:
    from veo_excel_processor import create_job_from_excel, validate_excel_file
    main_logger.info("OK veo_excel_processor loaded")
except ImportError as e:
    main_logger.critical(f"veo_excel_processor import failed: {e}")
    sys.exit(1)

# Directories
_BASE_DIR  = _HERE
output_dir = _BASE_DIR / config.OUTPUT_DIR
temp_dir   = _BASE_DIR / config.TEMP_DIR
output_dir.mkdir(parents=True, exist_ok=True)
temp_dir.mkdir(parents=True, exist_ok=True)
(output_dir / "decompositions").mkdir(exist_ok=True)

try:
    from video_stitcher import VideoStitcher
    from prompt_decomposer import PromptDecomposer

    video_stitcher = VideoStitcher(
        output_dir            = output_dir,
        aws_access_key_id     = "",
        aws_secret_access_key = "",
        bucket                = "",
        region                = "",
    )
    prompt_decomposer = PromptDecomposer(
        aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
        region                = config.AWS_DEFAULT_REGION,
    )
    main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
    main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
    main_logger.info(
        f"   Decomposer : "
        f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
    )
except ImportError as e:
    main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
    sys.exit(1)

veo_generator = None
try:
    from veo_generator import VeoGenerator
    if config.GOOGLE_API_KEY:
        veo_generator = VeoGenerator(
            api_key              = config.GOOGLE_API_KEY,
            output_dir           = output_dir,
            model_primary        = config.VEO_MODEL_PRIMARY,
            model_fallback       = config.VEO_MODEL_FALLBACK,
            clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
            aspect_ratio         = config.VEO_ASPECT_RATIO,
            resolution           = config.VEO_RESOLUTION,
            generate_audio       = config.VEO_GENERATE_AUDIO,
            sample_count         = config.VEO_SAMPLE_COUNT,
            polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
            max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
        )
        main_logger.info("OK VeoGenerator initialised")
    else:
        main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
except ImportError as e:
    main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

if not veo_generator:
    main_logger.critical("Cannot start without a Veo generator. Exiting.")
    sys.exit(1)

from veo_orchestrator import VeoOrchestrator
veo_orchestrator = VeoOrchestrator(
    generator     = veo_generator,
    stitcher      = video_stitcher,
    decomposer    = prompt_decomposer,
    clip_duration = config.VEO_CLIP_DURATION_SECONDS,
)
main_logger.info("OK VeoOrchestrator initialised")

# ── Job store ─────────────────────────────────────────────────────────────────
jobs: Dict[str, Any] = {}

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "Veo Video Generation Platform",
    description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
    version     = "1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
                         "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    health_logger.info("Health check requested")
    return {
        "status":    "healthy",
        "service":   "veo-video-generation-platform",
        "version":   "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "veo_generator":   True,
            "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
            "decomposer":      True,
        },
        "veo": {
            "primary_model":  config.VEO_MODEL_PRIMARY,
            "fallback_model": config.VEO_MODEL_FALLBACK,
            "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
            "aspect_ratio":   config.VEO_ASPECT_RATIO,
            "resolution":     config.VEO_RESOLUTION,
            "native_audio":   True,  # Veo 3.0 always generates audio natively
        },
        "decomposer_mode": (
            "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
        ),
    }


@app.get("/api/jobs")
async def list_jobs():
    job_logger.info(f"Job list requested — {len(jobs)} total")
    return {
        "jobs": [
            {
                "job_id":            job_id,
                "original_filename": jd.get("original_filename", ""),
                "status":            jd.get("status", "processing"),
                "total_prompts":     jd.get("total_prompts", 0),
                "completed_prompts": jd.get("completed_prompts", 0),
                "failed_prompts":    jd.get("failed_prompts", 0),
                "progress_percent":  jd.get("progress_percent", 0.0),
                "created_at":        jd.get("created_at", ""),
                "generation_status": jd.get("generation_status", "Queued"),
            }
            for job_id, jd in jobs.items()
        ]
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job_data = jobs[job_id]
    results  = job_data.get("results", {})

    prompts_out = []
    for i, prompt_data in enumerate(job_data.get("prompts", [])):
        r = results.get(str(i), {})
        prompts_out.append({
            "prompt_id":       f"prompt_{i + 1}",
            "prompt_text":     prompt_data.get("text", ""),
            "row_number":      i + 1,
            "duration":        prompt_data.get("duration", 8),
            "status":          r.get("status", "processing"),
            "video_url":       r.get("video_url"),
            "duration_seconds": r.get("duration_seconds"),
            "stitched":        r.get("stitched", False),
            "clips_count":     r.get("clips_count", 0),
            "clip_urls":       r.get("clip_urls", []),
            "model_used":      r.get("model_used", ""),
            "has_native_audio": r.get("has_native_audio", False),
            "error_message":   r.get("error_message"),
            "generation_time_seconds": r.get("generation_time_seconds"),
        })

    return {
        "job_id": job_id,
        "status": job_data.get("status", "processing"),
        "summary": {
            "job_id":            job_id,
            "original_filename": job_data.get("original_filename", ""),
            "status":            job_data.get("status", "processing"),
            "total_prompts":     job_data.get("total_prompts", 0),
            "completed_prompts": job_data.get("completed_prompts", 0),
            "failed_prompts":    job_data.get("failed_prompts", 0),
            "progress_percent":  job_data.get("progress_percent", 0.0),
            "total_processing_time": job_data.get("total_processing_time"),
        },
        "prompts": prompts_out,
    }


@app.post("/api/upload")
async def upload_excel(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Accept an Excel/CSV file and start Veo generation as a background job.

    Required Excel columns:  prompt, duration
    Optional Excel columns:  task_type, priority
    """
    upload_id = str(uuid.uuid4())[:8]
    upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
    temp_path.write_bytes(content)

    is_valid, errors = validate_excel_file(str(temp_path))
    if not is_valid:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Excel validation failed: {'; '.join(errors)}",
        )

    job_data = create_job_from_excel(
        file_path  = str(temp_path),
        platforms  = ["veo"],
        audio_mode = "platform_native",   # unused — Veo owns its audio
    )
    job_id = job_data["job_id"]

    jobs[job_id]                      = job_data
    jobs[job_id]["temp_file"]         = str(temp_path)
    jobs[job_id]["upload_id"]         = upload_id
    jobs[job_id]["original_filename"] = file.filename

    upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

    background_tasks.add_task(run_generation_job, job_id)

    return {
        "success":       True,
        "job_id":        job_id,
        "upload_id":     upload_id,
        "prompts_count": job_data["total_prompts"],
        "veo_model":     config.VEO_MODEL_PRIMARY,
        "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
        "native_audio":  True,  # Veo 3.0 always generates audio natively
        "stitching":     video_stitcher.ffmpeg_available,
        "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
    }


# ── Background generation job ─────────────────────────────────────────────────

async def run_generation_job(job_id: str) -> None:
    """
    Process each prompt sequentially. Veo produces video + audio in one API
    call — no mixing, no narration, no post-processing needed.
    """
    generation_logger.info(f"[JOB_{job_id}] Starting")
    start_time   = time.time()
    job          = jobs[job_id]
    prompts_data = job["prompts"]
    total        = len(prompts_data)

    jobs[job_id]["results"] = {}

    for i, prompt_data in enumerate(prompts_data):
        if job_id not in jobs:
            generation_logger.warning(f"[JOB_{job_id}] Job deleted mid-run — stopping")
            break

        prompt_text = prompt_data["text"]
        duration    = prompt_data["duration"]

        jobs[job_id]["generation_status"] = f"Processing prompt {i + 1}/{total}"
        generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s")
        generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")

        prompt_start = time.time()

        result = await veo_orchestrator.generate_for_prompt(
            prompt_data  = prompt_data,
            job_id       = job_id,
            prompt_index = i,
        )

        jobs[job_id]["results"][str(i)] = result
        elapsed = time.time() - prompt_start

        if result.get("status") in ("completed", "partial"):
            jobs[job_id]["completed_prompts"] = jobs[job_id].get("completed_prompts", 0) + 1
            generation_logger.info(
                f"   Done in {elapsed:.1f}s -> {result.get('video_url')} "
                f"({'stitched' if result.get('stitched') else 'single'}, "
                f"{result.get('clips_count', 1)} clip(s))"
            )
            progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
        else:
            jobs[job_id]["failed_prompts"] = jobs[job_id].get("failed_prompts", 0) + 1
            generation_logger.error(f"   Failed after {elapsed:.1f}s: {result.get('error_message')}")

        jobs[job_id]["progress_percent"] = ((i + 1) / total) * 100

    # Finalise
    total_elapsed = time.time() - start_time
    failed_count  = jobs[job_id].get("failed_prompts", 0)

    jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
    jobs[job_id]["generation_status"]     = "All prompts processed"
    jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

    generation_logger.info(
        f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
        f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
    )

    try:
        temp_file = jobs[job_id].get("temp_file")
        if temp_file:
            Path(temp_file).unlink(missing_ok=True)
    except Exception as e:
        generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    s = logging.getLogger("STARTUP")
    s.info("=" * 70)
    s.info("Veo Video Generation Platform v1.0.0")
    s.info("=" * 70)
    s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
    s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
    s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
    s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
    s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
    s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
    s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
    s.info("Endpoints:")
    s.info("   API    : http://localhost:8100")
    s.info("   Docs   : http://localhost:8100/docs")
    s.info("   Health : http://localhost:8100/health")
    s.info("=" * 70)

    uvicorn.run(
        "veo_main:app",
        host      = "0.0.0.0",
        port      = 8100,
        reload    = True,
        log_level = "info",
    )