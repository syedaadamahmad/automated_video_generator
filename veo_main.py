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
import os
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

from veo_s3 import VeoS3Client
veo_s3 = VeoS3Client(
    bucket = os.getenv("VEO_S3_BUCKET", ""),
    region = os.getenv("VEO_S3_REGION", "us-east-1"),
)
main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

from veo_orchestrator import VeoOrchestrator
veo_orchestrator = VeoOrchestrator(
    generator     = veo_generator,
    stitcher      = video_stitcher,
    decomposer    = prompt_decomposer,
    clip_duration = config.VEO_CLIP_DURATION_SECONDS,
    s3_client     = veo_s3,
)
main_logger.info("OK VeoOrchestrator initialised")

# ── Job store ─────────────────────────────────────────────────────────────────
jobs: Dict[str, Any] = {}

# ── Live metrics store ────────────────────────────────────────────────────────
# Updated in real-time by generator and decomposer via push.
# Resets on server restart — tracks current session only.
_metrics: Dict[str, Any] = {
    # Veo API
    "veo_submissions":      0,   # total API calls attempted
    "veo_successes":        0,   # successful completions
    "veo_failures":         0,   # all failures (any error)
    "veo_rate_limit_hits":  0,   # 429 errors specifically
    "veo_clips_generated":  0,   # clips that produced a video file
    "veo_generation_time_s": 0.0, # cumulative generation time

    # Bedrock decomposer
    "decomp_nova_calls":       0,
    "decomp_deepseek_calls":   0,
    "decomp_deterministic":    0,
    "decomp_input_tokens":     0,
    "decomp_output_tokens":    0,

    # S3
    "s3_uploads_ok":    0,
    "s3_uploads_fail":  0,

    # Session
    "session_start":    None,   # set on first job
    "jobs_processed":   0,
}

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


@app.get("/api/metrics")
async def get_metrics():
    """Real-time generation metrics for the Streamlit dashboard."""
    import time
    from datetime import datetime, timezone

    # Derived metrics
    total_veo   = _metrics["veo_submissions"]
    rl_rate     = (
        round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
        if total_veo > 0 else 0.0
    )
    avg_clip_s  = (
        round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
        if _metrics["veo_clips_generated"] > 0 else 0.0
    )

    # Estimated cost (clips × 8s × $0.40 for primary model)
    est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
    est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

    return {
        "session_start":        _metrics["session_start"],
        "jobs_processed":       _metrics["jobs_processed"],

        "veo": {
            "submissions":      _metrics["veo_submissions"],
            "successes":        _metrics["veo_successes"],
            "failures":         _metrics["veo_failures"],
            "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
            "rate_limit_pct":   rl_rate,
            "clips_generated":  _metrics["veo_clips_generated"],
            "avg_clip_time_s":  avg_clip_s,
            "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
        },

        "decomposer": {
            "nova_calls":        _metrics["decomp_nova_calls"],
            "deepseek_calls":    _metrics["decomp_deepseek_calls"],
            "deterministic":     _metrics["decomp_deterministic"],
            "input_tokens":      _metrics["decomp_input_tokens"],
            "output_tokens":     _metrics["decomp_output_tokens"],
            "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
        },

        "s3": {
            "uploads_ok":   _metrics["s3_uploads_ok"],
            "uploads_fail": _metrics["s3_uploads_fail"],
        },

        "cost_estimate": {
            "usd": round(est_cost_usd, 4),
            "inr": round(est_cost_inr, 2),
            "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
        },
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


# ── Concurrency config ────────────────────────────────────────────────────────

# Max prompts running simultaneously within one job.
# Veo 3.0 free tier: 2 requests per minute, 50 per day.
# Each prompt with 4 clips = 4 sequential API calls.
# At concurrency=2, clip submissions from two prompts can overlap
# and exceed the 2 RPM limit. Set to 1 for reliable operation
# on the free tier. Increase if you have a paid quota.
_PROMPT_CONCURRENCY = 1


# ── Background generation job ─────────────────────────────────────────────────

async def run_generation_job(job_id: str) -> None:
    """
    Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

    Design:
    - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
    - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
    - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
    - Results are stored by index key str(i) — API schema unchanged.
    - Progress percent is updated after each prompt completes (order-independent).
    """
    generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
    start_time   = time.time()

    # Track session start on first job
    if _metrics["session_start"] is None:
        from datetime import datetime, timezone
        _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
    _metrics["jobs_processed"] += 1
    job          = jobs[job_id]
    prompts_data = job["prompts"]
    total        = len(prompts_data)

    jobs[job_id]["results"]            = {}
    jobs[job_id]["completed_prompts"]  = 0
    jobs[job_id]["failed_prompts"]     = 0
    jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

    semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
    state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

    async def _run_prompt(i: int, prompt_data: dict) -> None:
        """
        Semaphore-gated coroutine for a single prompt.
        Clips within this prompt run sequentially inside generate_for_prompt().
        """
        prompt_text = prompt_data["text"]
        duration    = prompt_data["duration"]

        async with semaphore:
            if job_id not in jobs:
                generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
                return

            generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
            generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
            prompt_start = time.time()

            result = await veo_orchestrator.generate_for_prompt(
                prompt_data  = prompt_data,
                job_id       = job_id,
                prompt_index = i,
            )

            elapsed = time.time() - prompt_start

        # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
        async with state_lock:
            jobs[job_id]["results"][str(i)] = result

            # ── Push result stats into live metrics ───────────────────────────
            _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
            _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
            # Decomposer token tracking
            _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
            _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
            _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
            _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
            _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
            # S3 tracking
            _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
            _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

            if result.get("status") in ("completed", "partial"):
                jobs[job_id]["completed_prompts"] += 1
                _metrics["veo_successes"]       += 1
                _metrics["veo_clips_generated"] += result.get("clips_count", 1)
                _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
                generation_logger.info(
                    f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
                    f"-> {result.get('video_url')} "
                    f"({'stitched' if result.get('stitched') else 'single'}, "
                    f"{result.get('clips_count', 1)} clip(s))"
                )
                progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
            else:
                jobs[job_id]["failed_prompts"] += 1
                _metrics["veo_failures"] += 1
                generation_logger.error(
                    f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
                    f"{result.get('error_message')}"
                )

            done_so_far = (
                jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
            )
            jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
            jobs[job_id]["generation_status"]  = (
                f"Running — {done_so_far}/{total} complete"
            )

    # ── Launch all prompt coroutines; gather waits for all to finish ──────────
    tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # ── Finalise ──────────────────────────────────────────────────────────────
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


# ── Rerun single prompt ───────────────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks):
    """
    Re-run a single prompt within an existing job.

    Flow:
    - Validates job and prompt exist
    - Marks the result as "processing" immediately (UI picks this up on next poll)
    - Schedules a background task that calls the orchestrator for just that one prompt
    - Returns immediately so the UI is never blocked

    Used by: rerun button on each video card in the frontend.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = jobs[job_id]
    prompts_data = job.get("prompts", [])

    if prompt_index < 0 or prompt_index >= len(prompts_data):
        raise HTTPException(
            status_code=400,
            detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
        )

    prompt_data = prompts_data[prompt_index]

    # Mark as processing immediately so frontend shows skeleton
    jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
        "status": "processing",
        "video_url": None,
    }
    # Reset counters to reflect the rerun
    jobs[job_id]["status"] = "processing"

    generation_logger.info(
        f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
        f"'{prompt_data.get('text', '')[:60]}...'"
    )

    async def _rerun():
        try:
            result = await veo_orchestrator.generate_for_prompt(
                prompt_data  = prompt_data,
                job_id       = job_id,
                prompt_index = prompt_index,
            )
            jobs[job_id]["results"][str(prompt_index)] = result

            # Recompute job-level status from all results
            all_results = jobs[job_id].get("results", {})
            total = len(prompts_data)
            completed = sum(
                1 for r in all_results.values()
                if r.get("status") in ("completed", "partial")
            )
            failed = sum(
                1 for r in all_results.values()
                if r.get("status") == "failed"
            )
            processing = sum(
                1 for r in all_results.values()
                if r.get("status") == "processing"
            )

            if processing == 0:
                jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
                jobs[job_id]["completed_prompts"] = completed
                jobs[job_id]["failed_prompts"]    = failed
                jobs[job_id]["progress_percent"]  = 100.0

            generation_logger.info(
                f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
                f"status={result.get('status')}"
            )
        except Exception as e:
            jobs[job_id]["results"][str(prompt_index)] = {
                "status": "failed",
                "error_message": str(e),
            }
            generation_logger.error(
                f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
            )

    # Soft-delete the old S3 video before rerunning
    # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
    if veo_s3.enabled:
        moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
        if moved:
            generation_logger.info(
                f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
            )
        else:
            generation_logger.warning(
                f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
            )

    background_tasks.add_task(_rerun)

    return {
        "status":        "accepted",
        "job_id":        job_id,
        "prompt_index":  prompt_index,
        "message":       f"Rerun started for prompt {prompt_index + 1}",
    }


# ── YouTube upload queue ──────────────────────────────────────────────────────
# In-memory queue: { queue_id: { job_id, prompt_index, title, description,
#                                tags, local_path, s3_url, status, youtube_url } }
# "approved" = waiting to upload, "uploading" = in progress,
# "uploaded" = done, "failed" = error
youtube_queue: Dict[str, Any] = {}


import veo_youtube as _yt


@app.get("/api/youtube/status")
async def youtube_status():
    """Check if YouTube is configured and authenticated."""
    return {
        "configured":    _yt.is_configured(),
        "authenticated": _yt.is_authenticated(),
        "secrets_file":  str(_yt.SECRETS_FILE),
    }


@app.post("/api/youtube/auth")
async def youtube_auth():
    """
    Trigger the OAuth browser flow.
    Opens a browser tab — user logs in, approves, token is saved.
    Returns immediately after auth completes.
    """
    try:
        _yt.get_authenticated_service()
        return {"status": "authenticated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/{job_id}/approve/{prompt_index}")
async def approve_video(job_id: str, prompt_index: int):
    """
    Approve a completed video — adds it to the YouTube upload queue.

    Auto-generates title/description/tags from the prompt.
    User edits these in the UI before triggering upload.

    Returns the queue_id so the frontend can reference this queue entry.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job      = jobs[job_id]
    prompts  = job.get("prompts", [])
    results  = job.get("results", {})

    if prompt_index < 0 or prompt_index >= len(prompts):
        raise HTTPException(status_code=400, detail="prompt_index out of range")

    result = results.get(str(prompt_index), {})
    if result.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Video is not completed yet")

    prompt_text = prompts[prompt_index].get("text", "")
    video_url   = result.get("video_url", "")
    local_path  = result.get("local_video_url") or video_url  # prefer local for upload
    s3_url      = result.get("s3_url", "")

    # Strip /videos/ prefix from local URL if it's a FastAPI-served path
    if local_path and local_path.startswith("/videos/"):
        from pathlib import Path as _Path
        output_dir = _Path(__file__).parent / "outputs" / "videos"
        local_path = str(output_dir / _Path(local_path).name)

    metadata  = _yt.generate_metadata(prompt_text)
    queue_id  = f"q_{job_id}_{prompt_index}"

    youtube_queue[queue_id] = {
        "queue_id":     queue_id,
        "job_id":       job_id,
        "prompt_index": prompt_index,
        "prompt_text":  prompt_text[:120],
        "local_path":   local_path,
        "s3_url":       s3_url,
        "video_url":    video_url,
        "title":        metadata["title"],
        "description":  metadata["description"],
        "tags":         metadata["tags"],
        "status":       "approved",
        "youtube_url":  None,
        "error":        None,
    }

    generation_logger.info(
        f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
    )

    return youtube_queue[queue_id]


@app.get("/api/youtube/queue")
async def get_youtube_queue():
    """Return all items in the upload queue."""
    return {"queue": list(youtube_queue.values())}


@app.patch("/api/youtube/queue/{queue_id}")
async def update_queue_item(queue_id: str, body: dict):
    """
    Update editable metadata for a queued video before upload.
    Accepts: { title, description, tags }
    """
    if queue_id not in youtube_queue:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

    item = youtube_queue[queue_id]
    if item["status"] not in ("approved", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit item with status '{item['status']}'"
        )

    if "title" in body:
        item["title"]       = str(body["title"])[:100]
    if "description" in body:
        item["description"] = str(body["description"])[:5000]
    if "tags" in body and isinstance(body["tags"], list):
        item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

    return item


@app.post("/api/youtube/upload")
async def upload_to_youtube(background_tasks: BackgroundTasks):
    """
    Upload ALL approved queue items to YouTube.

    Runs in background — returns immediately.
    Poll /api/youtube/queue to track per-item status.
    """
    approved = [
        item for item in youtube_queue.values()
        if item["status"] == "approved"
    ]

    if not approved:
        raise HTTPException(status_code=400, detail="No approved videos in queue")

    if not _yt.is_configured():
        raise HTTPException(
            status_code=503,
            detail="YouTube not configured — youtube_client_secrets.json missing"
        )

    async def _upload_all():
        for item in approved:
            qid = item["queue_id"]
            youtube_queue[qid]["status"] = "uploading"
            generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda i=item: _yt.upload_video(
                    local_path  = i["local_path"],
                    title       = i["title"],
                    description = i["description"],
                    tags        = i["tags"],
                    privacy     = "public",
                ),
            )

            if result["status"] == "uploaded":
                youtube_queue[qid]["status"]      = "uploaded"
                youtube_queue[qid]["youtube_url"] = result["youtube_url"]
                youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
                generation_logger.info(
                    f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
                )
            else:
                youtube_queue[qid]["status"] = "failed"
                youtube_queue[qid]["error"]  = result.get("error", "unknown")
                generation_logger.error(
                    f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
                )

    background_tasks.add_task(_upload_all)

    return {
        "status":  "started",
        "count":   len(approved),
        "message": f"Uploading {len(approved)} video(s) to YouTube",
    }


@app.delete("/api/youtube/queue/{queue_id}")
async def remove_from_queue(queue_id: str):
    """Remove an item from the upload queue (before it's uploaded)."""
    if queue_id not in youtube_queue:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
    if youtube_queue[queue_id]["status"] == "uploading":
        raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
    del youtube_queue[queue_id]
    return {"status": "removed", "queue_id": queue_id}


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