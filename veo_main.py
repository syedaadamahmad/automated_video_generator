# # #!/usr/bin/env python3
# # """
# # veo_main.py — Veo Video Generation Platform
# # ════════════════════════════════════════════

# # Standalone FastAPI service. Accepts Excel uploads, generates videos via
# # Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# # via FFmpeg, and serves results as downloadable MP4 files.

# # Veo 3.1 generates video and audio natively from the text prompt — no
# # post-processing or external audio service is required.

# # Endpoints:
# #   GET  /health                → system status
# #   POST /api/upload            → accept .xlsx/.csv, start background job
# #   GET  /api/jobs              → list all jobs
# #   GET  /api/jobs/{job_id}     → job details + per-prompt results
# #   GET  /videos/{filename}     → serve generated MP4 files

# # Run:
# #   python veo_main.py
# #   -> http://localhost:8100
# #   -> http://localhost:8100/docs

# # Port 8100 avoids collision with the Nova/Runway service on 8000.
# # """

# # import asyncio
# # import logging
# # import os
# # import sys
# # import time
# # import uuid
# # from datetime import datetime
# # from pathlib import Path
# # from typing import Any, Dict

# # import uvicorn
# # from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
# # from fastapi.middleware.cors import CORSMiddleware
# # from fastapi.staticfiles import StaticFiles

# # # ── Logging ───────────────────────────────────────────────────────────────────
# # logging.basicConfig(
# #     level   = logging.INFO,
# #     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
# #     datefmt = "%Y-%m-%d %H:%M:%S",
# # )
# # main_logger       = logging.getLogger("MAIN")
# # upload_logger     = logging.getLogger("UPLOAD")
# # generation_logger = logging.getLogger("GENERATION")
# # progress_logger   = logging.getLogger("PROGRESS")
# # job_logger        = logging.getLogger("JOB_MANAGER")
# # health_logger     = logging.getLogger("HEALTH")

# # # ── Local imports ─────────────────────────────────────────────────────────────
# # _HERE = Path(__file__).resolve().parent
# # sys.path.insert(0, str(_HERE))

# # try:
# #     from veo_config import veo_config as config
# #     main_logger.info("OK veo_config loaded")
# #     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
# #     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
# #     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# # except ImportError as e:
# #     main_logger.critical(f"[CONFIG_ERROR] {e}")
# #     sys.exit(1)

# # try:
# #     from veo_excel_processor import create_job_from_excel, validate_excel_file
# #     main_logger.info("OK veo_excel_processor loaded")
# # except ImportError as e:
# #     main_logger.critical(f"veo_excel_processor import failed: {e}")
# #     sys.exit(1)

# # # Directories
# # _BASE_DIR  = _HERE
# # output_dir = _BASE_DIR / config.OUTPUT_DIR
# # temp_dir   = _BASE_DIR / config.TEMP_DIR
# # output_dir.mkdir(parents=True, exist_ok=True)
# # temp_dir.mkdir(parents=True, exist_ok=True)
# # (output_dir / "decompositions").mkdir(exist_ok=True)

# # try:
# #     from video_stitcher import VideoStitcher
# #     from prompt_decomposer import PromptDecomposer

# #     video_stitcher = VideoStitcher(
# #         output_dir            = output_dir,
# #         aws_access_key_id     = "",
# #         aws_secret_access_key = "",
# #         bucket                = "",
# #         region                = "",
# #     )
# #     prompt_decomposer = PromptDecomposer(
# #         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
# #         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
# #         region                = config.AWS_DEFAULT_REGION,
# #     )
# #     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
# #     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
# #     main_logger.info(
# #         f"   Decomposer : "
# #         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
# #     )
# # except ImportError as e:
# #     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
# #     sys.exit(1)

# # veo_generator = None
# # try:
# #     from veo_generator import VeoGenerator
# #     if config.GOOGLE_API_KEY:
# #         veo_generator = VeoGenerator(
# #             api_key              = config.GOOGLE_API_KEY,
# #             output_dir           = output_dir,
# #             model_primary        = config.VEO_MODEL_PRIMARY,
# #             model_fallback       = config.VEO_MODEL_FALLBACK,
# #             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
# #             aspect_ratio         = config.VEO_ASPECT_RATIO,
# #             resolution           = config.VEO_RESOLUTION,
# #             generate_audio       = config.VEO_GENERATE_AUDIO,
# #             sample_count         = config.VEO_SAMPLE_COUNT,
# #             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
# #             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
# #         )
# #         main_logger.info("OK VeoGenerator initialised")
# #     else:
# #         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# # except ImportError as e:
# #     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# # if not veo_generator:
# #     main_logger.critical("Cannot start without a Veo generator. Exiting.")
# #     sys.exit(1)

# # from veo_s3 import VeoS3Client
# # veo_s3 = VeoS3Client(
# #     bucket = os.getenv("VEO_S3_BUCKET", ""),
# #     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# # )
# # main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# # from veo_orchestrator import VeoOrchestrator
# # veo_orchestrator = VeoOrchestrator(
# #     generator     = veo_generator,
# #     stitcher      = video_stitcher,
# #     decomposer    = prompt_decomposer,
# #     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
# #     s3_client     = veo_s3,
# # )
# # main_logger.info("OK VeoOrchestrator initialised")

# # # ── Job store ─────────────────────────────────────────────────────────────────
# # jobs: Dict[str, Any] = {}

# # # ── Live metrics store ────────────────────────────────────────────────────────
# # # Updated in real-time by generator and decomposer via push.
# # # Resets on server restart — tracks current session only.
# # _metrics: Dict[str, Any] = {
# #     # Veo API
# #     "veo_submissions":      0,   # total API calls attempted
# #     "veo_successes":        0,   # successful completions
# #     "veo_failures":         0,   # all failures (any error)
# #     "veo_rate_limit_hits":  0,   # 429 errors specifically
# #     "veo_clips_generated":  0,   # clips that produced a video file
# #     "veo_generation_time_s": 0.0, # cumulative generation time

# #     # Bedrock decomposer
# #     "decomp_nova_calls":       0,
# #     "decomp_deepseek_calls":   0,
# #     "decomp_deterministic":    0,
# #     "decomp_input_tokens":     0,
# #     "decomp_output_tokens":    0,

# #     # S3
# #     "s3_uploads_ok":    0,
# #     "s3_uploads_fail":  0,

# #     # Session
# #     "session_start":    None,   # set on first job
# #     "jobs_processed":   0,
# # }

# # # ── FastAPI ───────────────────────────────────────────────────────────────────
# # app = FastAPI(
# #     title       = "Veo Video Generation Platform",
# #     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
# #     version     = "1.0.0",
# # )

# # app.add_middleware(
# #     CORSMiddleware,
# #     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
# #                          "http://localhost:3000", "http://127.0.0.1:3000"],
# #     allow_credentials = True,
# #     allow_methods     = ["*"],
# #     allow_headers     = ["*"],
# # )

# # app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # # ── Routes ────────────────────────────────────────────────────────────────────

# # @app.get("/health")
# # async def health_check():
# #     health_logger.info("Health check requested")
# #     return {
# #         "status":    "healthy",
# #         "service":   "veo-video-generation-platform",
# #         "version":   "1.0.0",
# #         "timestamp": datetime.now().isoformat(),
# #         "components": {
# #             "veo_generator":   True,
# #             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
# #             "decomposer":      True,
# #         },
# #         "veo": {
# #             "primary_model":  config.VEO_MODEL_PRIMARY,
# #             "fallback_model": config.VEO_MODEL_FALLBACK,
# #             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
# #             "aspect_ratio":   config.VEO_ASPECT_RATIO,
# #             "resolution":     config.VEO_RESOLUTION,
# #             "native_audio":   True,  # Veo 3.0 always generates audio natively
# #         },
# #         "decomposer_mode": (
# #             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
# #         ),
# #     }


# # @app.get("/api/metrics")
# # async def get_metrics():
# #     """Real-time generation metrics for the Streamlit dashboard."""
# #     import time
# #     from datetime import datetime, timezone

# #     # Derived metrics
# #     total_veo   = _metrics["veo_submissions"]
# #     rl_rate     = (
# #         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
# #         if total_veo > 0 else 0.0
# #     )
# #     avg_clip_s  = (
# #         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
# #         if _metrics["veo_clips_generated"] > 0 else 0.0
# #     )

# #     # Estimated cost (clips × 8s × $0.40 for primary model)
# #     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
# #     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

# #     return {
# #         "session_start":        _metrics["session_start"],
# #         "jobs_processed":       _metrics["jobs_processed"],

# #         "veo": {
# #             "submissions":      _metrics["veo_submissions"],
# #             "successes":        _metrics["veo_successes"],
# #             "failures":         _metrics["veo_failures"],
# #             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
# #             "rate_limit_pct":   rl_rate,
# #             "clips_generated":  _metrics["veo_clips_generated"],
# #             "avg_clip_time_s":  avg_clip_s,
# #             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
# #         },

# #         "decomposer": {
# #             "nova_calls":        _metrics["decomp_nova_calls"],
# #             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
# #             "deterministic":     _metrics["decomp_deterministic"],
# #             "input_tokens":      _metrics["decomp_input_tokens"],
# #             "output_tokens":     _metrics["decomp_output_tokens"],
# #             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
# #         },

# #         "s3": {
# #             "uploads_ok":   _metrics["s3_uploads_ok"],
# #             "uploads_fail": _metrics["s3_uploads_fail"],
# #         },

# #         "cost_estimate": {
# #             "usd": round(est_cost_usd, 4),
# #             "inr": round(est_cost_inr, 2),
# #             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
# #         },
# #     }


# # @app.get("/api/jobs")
# # async def list_jobs():
# #     job_logger.info(f"Job list requested — {len(jobs)} total")
# #     return {
# #         "jobs": [
# #             {
# #                 "job_id":            job_id,
# #                 "original_filename": jd.get("original_filename", ""),
# #                 "status":            jd.get("status", "processing"),
# #                 "total_prompts":     jd.get("total_prompts", 0),
# #                 "completed_prompts": jd.get("completed_prompts", 0),
# #                 "failed_prompts":    jd.get("failed_prompts", 0),
# #                 "progress_percent":  jd.get("progress_percent", 0.0),
# #                 "created_at":        jd.get("created_at", ""),
# #                 "generation_status": jd.get("generation_status", "Queued"),
# #             }
# #             for job_id, jd in jobs.items()
# #         ]
# #     }


# # @app.get("/api/jobs/{job_id}")
# # async def get_job(job_id: str):
# #     if job_id not in jobs:
# #         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

# #     job_data = jobs[job_id]
# #     results  = job_data.get("results", {})

# #     prompts_out = []
# #     for i, prompt_data in enumerate(job_data.get("prompts", [])):
# #         r = results.get(str(i), {})
# #         prompts_out.append({
# #             "prompt_id":       f"prompt_{i + 1}",
# #             "prompt_text":     prompt_data.get("text", ""),
# #             "row_number":      i + 1,
# #             "duration":        prompt_data.get("duration", 8),
# #             "status":          r.get("status", "processing"),
# #             "video_url":       r.get("video_url"),
# #             "duration_seconds": r.get("duration_seconds"),
# #             "stitched":        r.get("stitched", False),
# #             "clips_count":     r.get("clips_count", 0),
# #             "clip_urls":       r.get("clip_urls", []),
# #             "model_used":      r.get("model_used", ""),
# #             "has_native_audio": r.get("has_native_audio", False),
# #             "error_message":   r.get("error_message"),
# #             "generation_time_seconds": r.get("generation_time_seconds"),
# #         })

# #     return {
# #         "job_id": job_id,
# #         "status": job_data.get("status", "processing"),
# #         "summary": {
# #             "job_id":            job_id,
# #             "original_filename": job_data.get("original_filename", ""),
# #             "status":            job_data.get("status", "processing"),
# #             "total_prompts":     job_data.get("total_prompts", 0),
# #             "completed_prompts": job_data.get("completed_prompts", 0),
# #             "failed_prompts":    job_data.get("failed_prompts", 0),
# #             "progress_percent":  job_data.get("progress_percent", 0.0),
# #             "total_processing_time": job_data.get("total_processing_time"),
# #         },
# #         "prompts": prompts_out,
# #     }


# # @app.post("/api/upload")
# # async def upload_excel(
# #     background_tasks: BackgroundTasks,
# #     file: UploadFile = File(...),
# # ):
# #     """
# #     Accept an Excel/CSV file and start Veo generation as a background job.

# #     Required Excel columns:  prompt, duration
# #     Optional Excel columns:  task_type, priority
# #     """
# #     upload_id = str(uuid.uuid4())[:8]
# #     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

# #     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
# #         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

# #     content = await file.read()
# #     if len(content) > 10 * 1024 * 1024:
# #         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

# #     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
# #     temp_path.write_bytes(content)

# #     is_valid, errors = validate_excel_file(str(temp_path))
# #     if not is_valid:
# #         temp_path.unlink(missing_ok=True)
# #         raise HTTPException(
# #             status_code=400,
# #             detail=f"Excel validation failed: {'; '.join(errors)}",
# #         )

# #     job_data = create_job_from_excel(
# #         file_path  = str(temp_path),
# #         platforms  = ["veo"],
# #         audio_mode = "platform_native",   # unused — Veo owns its audio
# #     )
# #     job_id = job_data["job_id"]

# #     jobs[job_id]                      = job_data
# #     jobs[job_id]["temp_file"]         = str(temp_path)
# #     jobs[job_id]["upload_id"]         = upload_id
# #     jobs[job_id]["original_filename"] = file.filename

# #     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

# #     background_tasks.add_task(run_generation_job, job_id)

# #     return {
# #         "success":       True,
# #         "job_id":        job_id,
# #         "upload_id":     upload_id,
# #         "prompts_count": job_data["total_prompts"],
# #         "veo_model":     config.VEO_MODEL_PRIMARY,
# #         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
# #         "native_audio":  True,  # Veo 3.0 always generates audio natively
# #         "stitching":     video_stitcher.ffmpeg_available,
# #         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
# #     }


# # # ── Concurrency config ────────────────────────────────────────────────────────

# # # Max prompts running simultaneously within one job.
# # # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # # Each prompt with 4 clips = 4 sequential API calls.
# # # At concurrency=2, clip submissions from two prompts can overlap
# # # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # # on the free tier. Increase if you have a paid quota.
# # _PROMPT_CONCURRENCY = 1


# # # ── Background generation job ─────────────────────────────────────────────────

# # async def run_generation_job(job_id: str) -> None:
# #     """
# #     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

# #     Design:
# #     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
# #     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
# #     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
# #     - Results are stored by index key str(i) — API schema unchanged.
# #     - Progress percent is updated after each prompt completes (order-independent).
# #     """
# #     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
# #     start_time   = time.time()

# #     # Track session start on first job
# #     if _metrics["session_start"] is None:
# #         from datetime import datetime, timezone
# #         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
# #     _metrics["jobs_processed"] += 1
# #     job          = jobs[job_id]
# #     prompts_data = job["prompts"]
# #     total        = len(prompts_data)

# #     jobs[job_id]["results"]            = {}
# #     jobs[job_id]["completed_prompts"]  = 0
# #     jobs[job_id]["failed_prompts"]     = 0
# #     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

# #     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
# #     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

# #     async def _run_prompt(i: int, prompt_data: dict) -> None:
# #         """
# #         Semaphore-gated coroutine for a single prompt.
# #         Clips within this prompt run sequentially inside generate_for_prompt().
# #         """
# #         prompt_text = prompt_data["text"]
# #         duration    = prompt_data["duration"]

# #         async with semaphore:
# #             if job_id not in jobs:
# #                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
# #                 return

# #             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
# #             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
# #             prompt_start = time.time()

# #             result = await veo_orchestrator.generate_for_prompt(
# #                 prompt_data  = prompt_data,
# #                 job_id       = job_id,
# #                 prompt_index = i,
# #             )

# #             elapsed = time.time() - prompt_start

# #         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
# #         async with state_lock:
# #             jobs[job_id]["results"][str(i)] = result

# #             # ── Push result stats into live metrics ───────────────────────────
# #             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
# #             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
# #             # Decomposer token tracking
# #             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
# #             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
# #             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
# #             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
# #             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
# #             # S3 tracking
# #             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
# #             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

# #             if result.get("status") in ("completed", "partial"):
# #                 jobs[job_id]["completed_prompts"] += 1
# #                 _metrics["veo_successes"]       += 1
# #                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
# #                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
# #                 generation_logger.info(
# #                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
# #                     f"-> {result.get('video_url')} "
# #                     f"({'stitched' if result.get('stitched') else 'single'}, "
# #                     f"{result.get('clips_count', 1)} clip(s))"
# #                 )
# #                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
# #             else:
# #                 jobs[job_id]["failed_prompts"] += 1
# #                 _metrics["veo_failures"] += 1
# #                 generation_logger.error(
# #                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
# #                     f"{result.get('error_message')}"
# #                 )

# #             done_so_far = (
# #                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
# #             )
# #             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
# #             jobs[job_id]["generation_status"]  = (
# #                 f"Running — {done_so_far}/{total} complete"
# #             )

# #     # ── Launch all prompt coroutines; gather waits for all to finish ──────────
# #     tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
# #     await asyncio.gather(*tasks, return_exceptions=True)

# #     # ── Finalise ──────────────────────────────────────────────────────────────
# #     total_elapsed = time.time() - start_time
# #     failed_count  = jobs[job_id].get("failed_prompts", 0)

# #     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
# #     jobs[job_id]["generation_status"]     = "All prompts processed"
# #     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

# #     generation_logger.info(
# #         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
# #         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
# #     )

# #     try:
# #         temp_file = jobs[job_id].get("temp_file")
# #         if temp_file:
# #             Path(temp_file).unlink(missing_ok=True)
# #     except Exception as e:
# #         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # # ── Rerun single prompt ───────────────────────────────────────────────────────

# # @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# # async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks):
# #     """
# #     Re-run a single prompt within an existing job.

# #     Flow:
# #     - Validates job and prompt exist
# #     - Marks the result as "processing" immediately (UI picks this up on next poll)
# #     - Schedules a background task that calls the orchestrator for just that one prompt
# #     - Returns immediately so the UI is never blocked

# #     Used by: rerun button on each video card in the frontend.
# #     """
# #     if job_id not in jobs:
# #         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

# #     job = jobs[job_id]
# #     prompts_data = job.get("prompts", [])

# #     if prompt_index < 0 or prompt_index >= len(prompts_data):
# #         raise HTTPException(
# #             status_code=400,
# #             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
# #         )

# #     prompt_data = prompts_data[prompt_index]

# #     # Mark as processing immediately so frontend shows skeleton
# #     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
# #         "status": "processing",
# #         "video_url": None,
# #     }
# #     # Reset counters to reflect the rerun
# #     jobs[job_id]["status"] = "processing"

# #     generation_logger.info(
# #         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
# #         f"'{prompt_data.get('text', '')[:60]}...'"
# #     )

# #     async def _rerun():
# #         try:
# #             result = await veo_orchestrator.generate_for_prompt(
# #                 prompt_data  = prompt_data,
# #                 job_id       = job_id,
# #                 prompt_index = prompt_index,
# #             )
# #             jobs[job_id]["results"][str(prompt_index)] = result

# #             # Recompute job-level status from all results
# #             all_results = jobs[job_id].get("results", {})
# #             total = len(prompts_data)
# #             completed = sum(
# #                 1 for r in all_results.values()
# #                 if r.get("status") in ("completed", "partial")
# #             )
# #             failed = sum(
# #                 1 for r in all_results.values()
# #                 if r.get("status") == "failed"
# #             )
# #             processing = sum(
# #                 1 for r in all_results.values()
# #                 if r.get("status") == "processing"
# #             )

# #             if processing == 0:
# #                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
# #                 jobs[job_id]["completed_prompts"] = completed
# #                 jobs[job_id]["failed_prompts"]    = failed
# #                 jobs[job_id]["progress_percent"]  = 100.0

# #             generation_logger.info(
# #                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
# #                 f"status={result.get('status')}"
# #             )
# #         except Exception as e:
# #             jobs[job_id]["results"][str(prompt_index)] = {
# #                 "status": "failed",
# #                 "error_message": str(e),
# #             }
# #             generation_logger.error(
# #                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
# #             )

# #     # Soft-delete the old S3 video before rerunning
# #     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
# #     if veo_s3.enabled:
# #         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
# #         if moved:
# #             generation_logger.info(
# #                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
# #             )
# #         else:
# #             generation_logger.warning(
# #                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
# #             )

# #     background_tasks.add_task(_rerun)

# #     return {
# #         "status":        "accepted",
# #         "job_id":        job_id,
# #         "prompt_index":  prompt_index,
# #         "message":       f"Rerun started for prompt {prompt_index + 1}",
# #     }


# # # ── YouTube upload queue ──────────────────────────────────────────────────────
# # # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# # #                                tags, local_path, s3_url, status, youtube_url } }
# # # "approved" = waiting to upload, "uploading" = in progress,
# # # "uploaded" = done, "failed" = error
# # youtube_queue: Dict[str, Any] = {}


# # import veo_youtube as _yt


# # @app.get("/api/youtube/status")
# # async def youtube_status():
# #     """Check if YouTube is configured and authenticated."""
# #     return {
# #         "configured":    _yt.is_configured(),
# #         "authenticated": _yt.is_authenticated(),
# #         "secrets_file":  str(_yt.SECRETS_FILE),
# #     }


# # @app.post("/api/youtube/auth")
# # async def youtube_auth():
# #     """
# #     Trigger the OAuth browser flow.
# #     Opens a browser tab — user logs in, approves, token is saved.
# #     Returns immediately after auth completes.
# #     """
# #     try:
# #         _yt.get_authenticated_service()
# #         return {"status": "authenticated"}
# #     except Exception as e:
# #         raise HTTPException(status_code=500, detail=str(e))


# # @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# # async def approve_video(job_id: str, prompt_index: int):
# #     """
# #     Approve a completed video — adds it to the YouTube upload queue.

# #     Auto-generates title/description/tags from the prompt.
# #     User edits these in the UI before triggering upload.

# #     Returns the queue_id so the frontend can reference this queue entry.
# #     """
# #     if job_id not in jobs:
# #         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

# #     job      = jobs[job_id]
# #     prompts  = job.get("prompts", [])
# #     results  = job.get("results", {})

# #     if prompt_index < 0 or prompt_index >= len(prompts):
# #         raise HTTPException(status_code=400, detail="prompt_index out of range")

# #     result = results.get(str(prompt_index), {})
# #     if result.get("status") != "completed":
# #         raise HTTPException(status_code=400, detail="Video is not completed yet")

# #     prompt_text = prompts[prompt_index].get("text", "")
# #     video_url   = result.get("video_url", "")
# #     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
# #     s3_url      = result.get("s3_url", "")

# #     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
# #     if local_path and local_path.startswith("/videos/"):
# #         from pathlib import Path as _Path
# #         output_dir = _Path(__file__).parent / "outputs" / "videos"
# #         local_path = str(output_dir / _Path(local_path).name)

# #     metadata  = _yt.generate_metadata(prompt_text)
# #     queue_id  = f"q_{job_id}_{prompt_index}"

# #     youtube_queue[queue_id] = {
# #         "queue_id":     queue_id,
# #         "job_id":       job_id,
# #         "prompt_index": prompt_index,
# #         "prompt_text":  prompt_text[:120],
# #         "local_path":   local_path,
# #         "s3_url":       s3_url,
# #         "video_url":    video_url,
# #         "title":        metadata["title"],
# #         "description":  metadata["description"],
# #         "tags":         metadata["tags"],
# #         "status":       "approved",
# #         "youtube_url":  None,
# #         "error":        None,
# #     }

# #     generation_logger.info(
# #         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
# #     )

# #     return youtube_queue[queue_id]


# # @app.get("/api/youtube/queue")
# # async def get_youtube_queue():
# #     """Return all items in the upload queue."""
# #     return {"queue": list(youtube_queue.values())}


# # @app.patch("/api/youtube/queue/{queue_id}")
# # async def update_queue_item(queue_id: str, body: dict):
# #     """
# #     Update editable metadata for a queued video before upload.
# #     Accepts: { title, description, tags }
# #     """
# #     if queue_id not in youtube_queue:
# #         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

# #     item = youtube_queue[queue_id]
# #     if item["status"] not in ("approved", "failed"):
# #         raise HTTPException(
# #             status_code=400,
# #             detail=f"Cannot edit item with status '{item['status']}'"
# #         )

# #     if "title" in body:
# #         item["title"]       = str(body["title"])[:100]
# #     if "description" in body:
# #         item["description"] = str(body["description"])[:5000]
# #     if "tags" in body and isinstance(body["tags"], list):
# #         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

# #     return item


# # @app.post("/api/youtube/upload")
# # async def upload_to_youtube(background_tasks: BackgroundTasks):
# #     """
# #     Upload ALL approved queue items to YouTube.

# #     Runs in background — returns immediately.
# #     Poll /api/youtube/queue to track per-item status.
# #     """
# #     approved = [
# #         item for item in youtube_queue.values()
# #         if item["status"] == "approved"
# #     ]

# #     if not approved:
# #         raise HTTPException(status_code=400, detail="No approved videos in queue")

# #     if not _yt.is_configured():
# #         raise HTTPException(
# #             status_code=503,
# #             detail="YouTube not configured — youtube_client_secrets.json missing"
# #         )

# #     async def _upload_all():
# #         for item in approved:
# #             qid = item["queue_id"]
# #             youtube_queue[qid]["status"] = "uploading"
# #             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

# #             result = await asyncio.get_event_loop().run_in_executor(
# #                 None,
# #                 lambda i=item: _yt.upload_video(
# #                     local_path  = i["local_path"],
# #                     title       = i["title"],
# #                     description = i["description"],
# #                     tags        = i["tags"],
# #                     privacy     = "public",
# #                 ),
# #             )

# #             if result["status"] == "uploaded":
# #                 youtube_queue[qid]["status"]      = "uploaded"
# #                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
# #                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
# #                 generation_logger.info(
# #                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
# #                 )
# #             else:
# #                 youtube_queue[qid]["status"] = "failed"
# #                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
# #                 generation_logger.error(
# #                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
# #                 )

# #     background_tasks.add_task(_upload_all)

# #     return {
# #         "status":  "started",
# #         "count":   len(approved),
# #         "message": f"Uploading {len(approved)} video(s) to YouTube",
# #     }


# # @app.delete("/api/youtube/queue/{queue_id}")
# # async def remove_from_queue(queue_id: str):
# #     """Remove an item from the upload queue (before it's uploaded)."""
# #     if queue_id not in youtube_queue:
# #         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
# #     if youtube_queue[queue_id]["status"] == "uploading":
# #         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
# #     del youtube_queue[queue_id]
# #     return {"status": "removed", "queue_id": queue_id}


# # # ── Entry point ───────────────────────────────────────────────────────────────

# # if __name__ == "__main__":
# #     s = logging.getLogger("STARTUP")
# #     s.info("=" * 70)
# #     s.info("Veo Video Generation Platform v1.0.0")
# #     s.info("=" * 70)
# #     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
# #     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
# #     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
# #     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
# #     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
# #     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# #     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
# #     s.info("Endpoints:")
# #     s.info("   API    : http://localhost:8100")
# #     s.info("   Docs   : http://localhost:8100/docs")
# #     s.info("   Health : http://localhost:8100/health")
# #     s.info("=" * 70)

# #     uvicorn.run(
# #         "veo_main:app",
# #         host      = "0.0.0.0",
# #         port      = 8100,
# #         reload    = True,
# #         log_level = "info",
# #     )















# #!/usr/bin/env python3
# """
# veo_main.py — Veo Video Generation Platform
# ════════════════════════════════════════════

# Standalone FastAPI service. Accepts Excel uploads, generates videos via
# Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# via FFmpeg, and serves results as downloadable MP4 files.

# Veo 3.1 generates video and audio natively from the text prompt — no
# post-processing or external audio service is required.

# Endpoints:
#   GET  /health                → system status
#   POST /api/upload            → accept .xlsx/.csv, start background job
#   GET  /api/jobs              → list all jobs
#   GET  /api/jobs/{job_id}     → job details + per-prompt results
#   GET  /videos/{filename}     → serve generated MP4 files

# Run:
#   python veo_main.py
#   -> http://localhost:8100
#   -> http://localhost:8100/docs

# Port 8100 avoids collision with the Nova/Runway service on 8000.
# """

# import asyncio
# import logging
# import os
# import sys
# import time
# import uuid
# from datetime import datetime
# from pathlib import Path
# from typing import Any, Dict

# import uvicorn
# from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level   = logging.INFO,
#     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
#     datefmt = "%Y-%m-%d %H:%M:%S",
# )
# main_logger       = logging.getLogger("MAIN")
# upload_logger     = logging.getLogger("UPLOAD")
# generation_logger = logging.getLogger("GENERATION")
# progress_logger   = logging.getLogger("PROGRESS")
# job_logger        = logging.getLogger("JOB_MANAGER")
# health_logger     = logging.getLogger("HEALTH")

# # ── Local imports ─────────────────────────────────────────────────────────────
# _HERE = Path(__file__).resolve().parent
# sys.path.insert(0, str(_HERE))

# try:
#     from veo_config import veo_config as config
#     main_logger.info("OK veo_config loaded")
#     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# except ImportError as e:
#     main_logger.critical(f"[CONFIG_ERROR] {e}")
#     sys.exit(1)

# try:
#     from veo_excel_processor import create_job_from_excel, validate_excel_file
#     main_logger.info("OK veo_excel_processor loaded")
# except ImportError as e:
#     main_logger.critical(f"veo_excel_processor import failed: {e}")
#     sys.exit(1)

# # Directories
# _BASE_DIR  = _HERE
# output_dir = _BASE_DIR / config.OUTPUT_DIR
# temp_dir   = _BASE_DIR / config.TEMP_DIR
# output_dir.mkdir(parents=True, exist_ok=True)
# temp_dir.mkdir(parents=True, exist_ok=True)
# (output_dir / "decompositions").mkdir(exist_ok=True)

# try:
#     from video_stitcher import VideoStitcher
#     from prompt_decomposer import PromptDecomposer

#     video_stitcher = VideoStitcher(
#         output_dir            = output_dir,
#         aws_access_key_id     = "",
#         aws_secret_access_key = "",
#         bucket                = "",
#         region                = "",
#     )
#     prompt_decomposer = PromptDecomposer(
#         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#         region                = config.AWS_DEFAULT_REGION,
#     )
#     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
#     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     main_logger.info(
#         f"   Decomposer : "
#         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
#     )
# except ImportError as e:
#     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
#     sys.exit(1)

# veo_generator = None
# try:
#     from veo_generator import VeoGenerator
#     if config.GOOGLE_API_KEY:
#         veo_generator = VeoGenerator(
#             api_key              = config.GOOGLE_API_KEY,
#             output_dir           = output_dir,
#             model_primary        = config.VEO_MODEL_PRIMARY,
#             model_fallback       = config.VEO_MODEL_FALLBACK,
#             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
#             aspect_ratio         = config.VEO_ASPECT_RATIO,
#             resolution           = config.VEO_RESOLUTION,
#             generate_audio       = config.VEO_GENERATE_AUDIO,
#             sample_count         = config.VEO_SAMPLE_COUNT,
#             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
#             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
#         )
#         main_logger.info("OK VeoGenerator initialised")
#     else:
#         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# except ImportError as e:
#     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# if not veo_generator:
#     main_logger.critical("Cannot start without a Veo generator. Exiting.")
#     sys.exit(1)

# from veo_s3 import VeoS3Client
# veo_s3 = VeoS3Client(
#     bucket = os.getenv("VEO_S3_BUCKET", ""),
#     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# )
# main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# from veo_orchestrator import VeoOrchestrator
# veo_orchestrator = VeoOrchestrator(
#     generator     = veo_generator,
#     stitcher      = video_stitcher,
#     decomposer    = prompt_decomposer,
#     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
#     s3_client     = veo_s3,
# )
# main_logger.info("OK VeoOrchestrator initialised")

# # ── Job store ─────────────────────────────────────────────────────────────────
# jobs: Dict[str, Any] = {}

# # ── Per-request user identity ─────────────────────────────────────────────────
# def _request_user(request: Request) -> tuple:
#     """
#     Return (user_id, user_role) from request headers.
#     X-User-Id   — authenticated user email (set by frontend _headers())
#     X-User-Role — role string: admin / editor / viewer
#     Defaults to ("anonymous","viewer") so curl/API docs still work.
#     PRODUCTION: replace with JWT decode.
#     """
#     uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
#     role = request.headers.get("X-User-Role", "viewer").strip().lower()
#     return uid, role

# def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
#     """Admins see all jobs. Others see only their own."""
#     if user_role == "admin":
#         return True
#     return job_data.get("user_id", "anonymous") == user_id

# # ── Live metrics store ────────────────────────────────────────────────────────
# # Updated in real-time by generator and decomposer via push.
# # Resets on server restart — tracks current session only.
# _metrics: Dict[str, Any] = {
#     # Veo API
#     "veo_submissions":      0,   # total API calls attempted
#     "veo_successes":        0,   # successful completions
#     "veo_failures":         0,   # all failures (any error)
#     "veo_rate_limit_hits":  0,   # 429 errors specifically
#     "veo_clips_generated":  0,   # clips that produced a video file
#     "veo_generation_time_s": 0.0, # cumulative generation time

#     # Bedrock decomposer
#     "decomp_nova_calls":       0,
#     "decomp_deepseek_calls":   0,
#     "decomp_deterministic":    0,
#     "decomp_input_tokens":     0,
#     "decomp_output_tokens":    0,

#     # S3
#     "s3_uploads_ok":    0,
#     "s3_uploads_fail":  0,

#     # Session
#     "session_start":    None,   # set on first job
#     "jobs_processed":   0,
# }

# # ── FastAPI ───────────────────────────────────────────────────────────────────
# app = FastAPI(
#     title       = "Veo Video Generation Platform",
#     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
#     version     = "1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
#                          "http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials = True,
#     allow_methods     = ["*"],
#     allow_headers     = ["*"],
# )

# app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # ── Routes ────────────────────────────────────────────────────────────────────

# @app.get("/health")
# async def health_check():
#     health_logger.info("Health check requested")
#     return {
#         "status":    "healthy",
#         "service":   "veo-video-generation-platform",
#         "version":   "1.0.0",
#         "timestamp": datetime.now().isoformat(),
#         "components": {
#             "veo_generator":   True,
#             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
#             "decomposer":      True,
#         },
#         "veo": {
#             "primary_model":  config.VEO_MODEL_PRIMARY,
#             "fallback_model": config.VEO_MODEL_FALLBACK,
#             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
#             "aspect_ratio":   config.VEO_ASPECT_RATIO,
#             "resolution":     config.VEO_RESOLUTION,
#             "native_audio":   True,  # Veo 3.0 always generates audio natively
#         },
#         "decomposer_mode": (
#             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
#         ),
#     }


# @app.get("/api/metrics")
# async def get_metrics():
#     """Real-time generation metrics for the Streamlit dashboard."""
#     import time
#     from datetime import datetime, timezone

#     # Derived metrics
#     total_veo   = _metrics["veo_submissions"]
#     rl_rate     = (
#         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
#         if total_veo > 0 else 0.0
#     )
#     avg_clip_s  = (
#         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
#         if _metrics["veo_clips_generated"] > 0 else 0.0
#     )

#     # Estimated cost (clips × 8s × $0.40 for primary model)
#     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
#     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

#     return {
#         "session_start":        _metrics["session_start"],
#         "jobs_processed":       _metrics["jobs_processed"],

#         "veo": {
#             "submissions":      _metrics["veo_submissions"],
#             "successes":        _metrics["veo_successes"],
#             "failures":         _metrics["veo_failures"],
#             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
#             "rate_limit_pct":   rl_rate,
#             "clips_generated":  _metrics["veo_clips_generated"],
#             "avg_clip_time_s":  avg_clip_s,
#             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
#         },

#         "decomposer": {
#             "nova_calls":        _metrics["decomp_nova_calls"],
#             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
#             "deterministic":     _metrics["decomp_deterministic"],
#             "input_tokens":      _metrics["decomp_input_tokens"],
#             "output_tokens":     _metrics["decomp_output_tokens"],
#             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
#         },

#         "s3": {
#             "uploads_ok":   _metrics["s3_uploads_ok"],
#             "uploads_fail": _metrics["s3_uploads_fail"],
#         },

#         "cost_estimate": {
#             "usd": round(est_cost_usd, 4),
#             "inr": round(est_cost_inr, 2),
#             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
#         },
#     }


# @app.get("/api/jobs")
# async def list_jobs(request: Request):
#     user_id, user_role = _request_user(request)
#     visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
#     job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
#     return {
#         "jobs": [
#             {
#                 "job_id":            job_id,
#                 "original_filename": jd.get("original_filename", ""),
#                 "status":            jd.get("status", "processing"),
#                 "total_prompts":     jd.get("total_prompts", 0),
#                 "completed_prompts": jd.get("completed_prompts", 0),
#                 "failed_prompts":    jd.get("failed_prompts", 0),
#                 "progress_percent":  jd.get("progress_percent", 0.0),
#                 "created_at":        jd.get("created_at", ""),
#                 "generation_status": jd.get("generation_status", "Queued"),
#                 "user_id":           jd.get("user_id", "anonymous"),
#             }
#             for job_id, jd in visible.items()
#         ]
#     }


# @app.get("/api/jobs/{job_id}")
# async def get_job(job_id: str, request: Request):
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     user_id, user_role = _request_user(request)
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied")

#     job_data = jobs[job_id]
#     results  = job_data.get("results", {})

#     prompts_out = []
#     for i, prompt_data in enumerate(job_data.get("prompts", [])):
#         r = results.get(str(i), {})
#         # video_url: may be S3 URL after upload (for distribution)
#         # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
#         raw_video_url = r.get("video_url")
#         raw_local_url = r.get("local_video_url")
#         # Ensure local_video_url is a proper /videos/ route, not an absolute path
#         if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
#             from pathlib import Path as _Path
#             raw_local_url = f"/videos/{_Path(raw_local_url).name}"
#         # If no local URL stored but video_url is already a local route, use it
#         if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
#             raw_local_url = raw_video_url
#         prompts_out.append({
#             "prompt_id":        f"prompt_{i + 1}",
#             "prompt_text":      prompt_data.get("text", ""),
#             "row_number":       i + 1,
#             "duration":         prompt_data.get("duration", 8),
#             "status":           r.get("status", "processing"),
#             "video_url":        raw_video_url,    # S3 or local route
#             "local_video_url":  raw_local_url,    # always /videos/... for player
#             "duration_seconds": r.get("duration_seconds"),
#             "stitched":         r.get("stitched", False),
#             "clips_count":      r.get("clips_count", 0),
#             "clip_urls":        r.get("clip_urls", []),
#             "model_used":       r.get("model_used", ""),
#             "has_native_audio": r.get("has_native_audio", False),
#             "error_message":    r.get("error_message"),
#             "generation_time_seconds": r.get("generation_time_seconds"),
#         })

#     return {
#         "job_id": job_id,
#         "status": job_data.get("status", "processing"),
#         "summary": {
#             "job_id":            job_id,
#             "original_filename": job_data.get("original_filename", ""),
#             "status":            job_data.get("status", "processing"),
#             "total_prompts":     job_data.get("total_prompts", 0),
#             "completed_prompts": job_data.get("completed_prompts", 0),
#             "failed_prompts":    job_data.get("failed_prompts", 0),
#             "progress_percent":  job_data.get("progress_percent", 0.0),
#             "total_processing_time": job_data.get("total_processing_time"),
#         },
#         "prompts": prompts_out,
#     }


# @app.post("/api/upload")
# async def upload_excel(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(...),
# ):
#     """
#     Accept an Excel/CSV file and start Veo generation as a background job.

#     Required Excel columns:  prompt, duration
#     Optional Excel columns:  task_type, priority
#     """
#     upload_id = str(uuid.uuid4())[:8]
#     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

#     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     is_valid, errors = validate_excel_file(str(temp_path))
#     if not is_valid:
#         temp_path.unlink(missing_ok=True)
#         raise HTTPException(
#             status_code=400,
#             detail=f"Excel validation failed: {'; '.join(errors)}",
#         )

#     job_data = create_job_from_excel(
#         file_path  = str(temp_path),
#         platforms  = ["veo"],
#         audio_mode = "platform_native",   # unused — Veo owns its audio
#     )
#     job_id = job_data["job_id"]

#     user_id, user_role = _request_user(request)

#     jobs[job_id]                      = job_data
#     jobs[job_id]["temp_file"]         = str(temp_path)
#     jobs[job_id]["upload_id"]         = upload_id
#     jobs[job_id]["original_filename"] = file.filename
#     jobs[job_id]["user_id"]           = user_id

#     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

#     background_tasks.add_task(run_generation_job, job_id)

#     return {
#         "success":       True,
#         "job_id":        job_id,
#         "upload_id":     upload_id,
#         "prompts_count": job_data["total_prompts"],
#         "veo_model":     config.VEO_MODEL_PRIMARY,
#         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
#         "native_audio":  True,  # Veo 3.0 always generates audio natively
#         "stitching":     video_stitcher.ffmpeg_available,
#         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
#     }


# # ── Concurrency config ────────────────────────────────────────────────────────

# # Max prompts running simultaneously within one job.
# # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # Each prompt with 4 clips = 4 sequential API calls.
# # At concurrency=2, clip submissions from two prompts can overlap
# # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # on the free tier. Increase if you have a paid quota.
# _PROMPT_CONCURRENCY = 1


# # ── Background generation job ─────────────────────────────────────────────────

# async def run_generation_job(job_id: str) -> None:
#     """
#     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

#     Design:
#     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
#     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
#     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
#     - Results are stored by index key str(i) — API schema unchanged.
#     - Progress percent is updated after each prompt completes (order-independent).
#     """
#     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
#     start_time   = time.time()

#     # Track session start on first job
#     if _metrics["session_start"] is None:
#         from datetime import datetime, timezone
#         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
#     _metrics["jobs_processed"] += 1
#     job          = jobs[job_id]
#     prompts_data = job["prompts"]
#     total        = len(prompts_data)

#     jobs[job_id]["results"]            = {}
#     jobs[job_id]["completed_prompts"]  = 0
#     jobs[job_id]["failed_prompts"]     = 0
#     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

#     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
#     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

#     async def _run_prompt(i: int, prompt_data: dict) -> None:
#         """
#         Semaphore-gated coroutine for a single prompt.
#         Clips within this prompt run sequentially inside generate_for_prompt().
#         """
#         prompt_text = prompt_data["text"]
#         duration    = prompt_data["duration"]

#         async with semaphore:
#             if job_id not in jobs:
#                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
#                 return

#             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
#             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
#             prompt_start = time.time()

#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = i,
#             )

#             elapsed = time.time() - prompt_start

#         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
#         async with state_lock:
#             jobs[job_id]["results"][str(i)] = result

#             # ── Push result stats into live metrics ───────────────────────────
#             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
#             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
#             # Decomposer token tracking
#             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
#             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
#             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
#             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
#             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
#             # S3 tracking
#             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
#             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

#             if result.get("status") in ("completed", "partial"):
#                 jobs[job_id]["completed_prompts"] += 1
#                 _metrics["veo_successes"]       += 1
#                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
#                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
#                 generation_logger.info(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
#                     f"-> {result.get('video_url')} "
#                     f"({'stitched' if result.get('stitched') else 'single'}, "
#                     f"{result.get('clips_count', 1)} clip(s))"
#                 )
#                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
#             else:
#                 jobs[job_id]["failed_prompts"] += 1
#                 _metrics["veo_failures"] += 1
#                 generation_logger.error(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
#                     f"{result.get('error_message')}"
#                 )

#             done_so_far = (
#                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
#             )
#             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
#             jobs[job_id]["generation_status"]  = (
#                 f"Running — {done_so_far}/{total} complete"
#             )

#     # ── Launch all prompt coroutines; gather waits for all to finish ──────────
#     tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
#     await asyncio.gather(*tasks, return_exceptions=True)

#     # ── Finalise ──────────────────────────────────────────────────────────────
#     total_elapsed = time.time() - start_time
#     failed_count  = jobs[job_id].get("failed_prompts", 0)

#     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
#     jobs[job_id]["generation_status"]     = "All prompts processed"
#     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

#     generation_logger.info(
#         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
#         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
#     )

#     try:
#         temp_file = jobs[job_id].get("temp_file")
#         if temp_file:
#             Path(temp_file).unlink(missing_ok=True)
#     except Exception as e:
#         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # ── Rerun single prompt ───────────────────────────────────────────────────────

# @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
#     """
#     Re-run a single prompt within an existing job.

#     Flow:
#     - Validates job and prompt exist
#     - Marks the result as "processing" immediately (UI picks this up on next poll)
#     - Schedules a background task that calls the orchestrator for just that one prompt
#     - Returns immediately so the UI is never blocked

#     Used by: rerun button on each video card in the frontend.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job = jobs[job_id]
#     prompts_data = job.get("prompts", [])

#     if prompt_index < 0 or prompt_index >= len(prompts_data):
#         raise HTTPException(
#             status_code=400,
#             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
#         )

#     prompt_data = prompts_data[prompt_index]

#     # Mark as processing immediately so frontend shows skeleton
#     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
#         "status": "processing",
#         "video_url": None,
#     }
#     # Reset counters to reflect the rerun
#     jobs[job_id]["status"] = "processing"

#     generation_logger.info(
#         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
#         f"'{prompt_data.get('text', '')[:60]}...'"
#     )

#     async def _rerun():
#         try:
#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = prompt_index,
#             )
#             jobs[job_id]["results"][str(prompt_index)] = result

#             # Recompute job-level status from all results
#             all_results = jobs[job_id].get("results", {})
#             total = len(prompts_data)
#             completed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") in ("completed", "partial")
#             )
#             failed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "failed"
#             )
#             processing = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "processing"
#             )

#             if processing == 0:
#                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
#                 jobs[job_id]["completed_prompts"] = completed
#                 jobs[job_id]["failed_prompts"]    = failed
#                 jobs[job_id]["progress_percent"]  = 100.0

#             generation_logger.info(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
#                 f"status={result.get('status')}"
#             )
#         except Exception as e:
#             jobs[job_id]["results"][str(prompt_index)] = {
#                 "status": "failed",
#                 "error_message": str(e),
#             }
#             generation_logger.error(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
#             )

#     # Soft-delete the old S3 video before rerunning
#     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
#     if veo_s3.enabled:
#         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
#         if moved:
#             generation_logger.info(
#                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
#             )
#         else:
#             generation_logger.warning(
#                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
#             )

#     background_tasks.add_task(_rerun)

#     return {
#         "status":        "accepted",
#         "job_id":        job_id,
#         "prompt_index":  prompt_index,
#         "message":       f"Rerun started for prompt {prompt_index + 1}",
#     }


# # ── YouTube upload queue ──────────────────────────────────────────────────────
# # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# #                                tags, local_path, s3_url, status, youtube_url } }
# # "approved" = waiting to upload, "uploading" = in progress,
# # "uploaded" = done, "failed" = error
# youtube_queue: Dict[str, Any] = {}


# import veo_youtube as _yt


# @app.get("/api/youtube/status")
# async def youtube_status():
#     """Check if YouTube is configured and authenticated."""
#     return {
#         "configured":    _yt.is_configured(),
#         "authenticated": _yt.is_authenticated(),
#         "secrets_file":  str(_yt.SECRETS_FILE),
#     }


# @app.post("/api/youtube/auth")
# async def youtube_auth():
#     """
#     Trigger the OAuth browser flow.
#     Opens a browser tab — user logs in, approves, token is saved.
#     Returns immediately after auth completes.
#     """
#     try:
#         _yt.get_authenticated_service()
#         return {"status": "authenticated"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# async def approve_video(job_id: str, prompt_index: int, request: Request):
#     """
#     Approve a completed video — adds it to the YouTube upload queue.

#     Auto-generates title/description/tags from the prompt.
#     User edits these in the UI before triggering upload.

#     Returns the queue_id so the frontend can reference this queue entry.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job      = jobs[job_id]
#     prompts  = job.get("prompts", [])
#     results  = job.get("results", {})

#     if prompt_index < 0 or prompt_index >= len(prompts):
#         raise HTTPException(status_code=400, detail="prompt_index out of range")

#     result = results.get(str(prompt_index), {})
#     if result.get("status") != "completed":
#         raise HTTPException(status_code=400, detail="Video is not completed yet")

#     prompt_text = prompts[prompt_index].get("text", "")
#     video_url   = result.get("video_url", "")
#     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
#     s3_url      = result.get("s3_url", "")

#     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
#     if local_path and local_path.startswith("/videos/"):
#         from pathlib import Path as _Path
#         output_dir = _Path(__file__).parent / "outputs" / "videos"
#         local_path = str(output_dir / _Path(local_path).name)

#     metadata  = _yt.generate_metadata(prompt_text)
#     queue_id  = f"q_{job_id}_{prompt_index}"

#     youtube_queue[queue_id] = {
#         "queue_id":     queue_id,
#         "job_id":       job_id,
#         "prompt_index": prompt_index,
#         "prompt_text":  prompt_text[:120],
#         "local_path":   local_path,
#         "s3_url":       s3_url,
#         "video_url":    video_url,
#         "title":        metadata["title"],
#         "description":  metadata["description"],
#         "tags":         metadata["tags"],
#         "status":       "approved",
#         "youtube_url":  None,
#         "error":        None,
#     }

#     generation_logger.info(
#         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
#     )

#     return youtube_queue[queue_id]


# @app.get("/api/youtube/queue")
# async def get_youtube_queue():
#     """Return all items in the upload queue."""
#     return {"queue": list(youtube_queue.values())}


# @app.patch("/api/youtube/queue/{queue_id}")
# async def update_queue_item(queue_id: str, body: dict):
#     """
#     Update editable metadata for a queued video before upload.
#     Accepts: { title, description, tags }
#     """
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

#     item = youtube_queue[queue_id]
#     if item["status"] not in ("approved", "failed"):
#         raise HTTPException(
#             status_code=400,
#             detail=f"Cannot edit item with status '{item['status']}'"
#         )

#     if "title" in body:
#         item["title"]       = str(body["title"])[:100]
#     if "description" in body:
#         item["description"] = str(body["description"])[:5000]
#     if "tags" in body and isinstance(body["tags"], list):
#         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

#     return item


# @app.post("/api/youtube/upload")
# async def upload_to_youtube(background_tasks: BackgroundTasks):
#     """
#     Upload ALL approved queue items to YouTube.

#     Runs in background — returns immediately.
#     Poll /api/youtube/queue to track per-item status.
#     """
#     approved = [
#         item for item in youtube_queue.values()
#         if item["status"] == "approved"
#     ]

#     if not approved:
#         raise HTTPException(status_code=400, detail="No approved videos in queue")

#     if not _yt.is_configured():
#         raise HTTPException(
#             status_code=503,
#             detail="YouTube not configured — youtube_client_secrets.json missing"
#         )

#     async def _upload_all():
#         for item in approved:
#             qid = item["queue_id"]
#             youtube_queue[qid]["status"] = "uploading"
#             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

#             result = await asyncio.get_event_loop().run_in_executor(
#                 None,
#                 lambda i=item: _yt.upload_video(
#                     local_path  = i["local_path"],
#                     title       = i["title"],
#                     description = i["description"],
#                     tags        = i["tags"],
#                     privacy     = "public",
#                 ),
#             )

#             if result["status"] == "uploaded":
#                 youtube_queue[qid]["status"]      = "uploaded"
#                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
#                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
#                 generation_logger.info(
#                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
#                 )
#             else:
#                 youtube_queue[qid]["status"] = "failed"
#                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
#                 generation_logger.error(
#                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
#                 )

#     background_tasks.add_task(_upload_all)

#     return {
#         "status":  "started",
#         "count":   len(approved),
#         "message": f"Uploading {len(approved)} video(s) to YouTube",
#     }


# @app.delete("/api/youtube/queue/{queue_id}")
# async def remove_from_queue(queue_id: str):
#     """Remove an item from the upload queue (before it's uploaded)."""
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
#     if youtube_queue[queue_id]["status"] == "uploading":
#         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
#     del youtube_queue[queue_id]
#     return {"status": "removed", "queue_id": queue_id}


# # ── Entry point ───────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     s = logging.getLogger("STARTUP")
#     s.info("=" * 70)
#     s.info("Veo Video Generation Platform v1.0.0")
#     s.info("=" * 70)
#     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
#     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
#     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
#     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
#     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     s.info("Endpoints:")
#     s.info("   API    : http://localhost:8100")
#     s.info("   Docs   : http://localhost:8100/docs")
#     s.info("   Health : http://localhost:8100/health")
#     s.info("=" * 70)

#     uvicorn.run(
#         "veo_main:app",
#         host      = "0.0.0.0",
#         port      = 8100,
#         reload    = True,
#         log_level = "info",
#     )



















# #!/usr/bin/env python3
# """
# veo_main.py — Veo Video Generation Platform
# ════════════════════════════════════════════

# Standalone FastAPI service. Accepts Excel uploads, generates videos via
# Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# via FFmpeg, and serves results as downloadable MP4 files.

# Veo 3.1 generates video and audio natively from the text prompt — no
# post-processing or external audio service is required.

# Endpoints:
#   GET  /health                → system status
#   POST /api/upload            → accept .xlsx/.csv, start background job
#   GET  /api/jobs              → list all jobs
#   GET  /api/jobs/{job_id}     → job details + per-prompt results
#   GET  /videos/{filename}     → serve generated MP4 files

# Run:
#   python veo_main.py
#   -> http://localhost:8100
#   -> http://localhost:8100/docs

# Port 8100 avoids collision with the Nova/Runway service on 8000.
# """

# import asyncio
# import logging
# import os
# import sys
# import time
# import uuid
# from datetime import datetime
# from pathlib import Path
# from typing import Any, Dict

# import uvicorn
# from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level   = logging.INFO,
#     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
#     datefmt = "%Y-%m-%d %H:%M:%S",
# )
# main_logger       = logging.getLogger("MAIN")
# upload_logger     = logging.getLogger("UPLOAD")
# generation_logger = logging.getLogger("GENERATION")
# progress_logger   = logging.getLogger("PROGRESS")
# job_logger        = logging.getLogger("JOB_MANAGER")
# health_logger     = logging.getLogger("HEALTH")

# # ── Local imports ─────────────────────────────────────────────────────────────
# _HERE = Path(__file__).resolve().parent
# sys.path.insert(0, str(_HERE))

# try:
#     from veo_config import veo_config as config
#     main_logger.info("OK veo_config loaded")
#     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# except ImportError as e:
#     main_logger.critical(f"[CONFIG_ERROR] {e}")
#     sys.exit(1)

# try:
#     from veo_excel_processor import create_job_from_excel, validate_excel_file
#     main_logger.info("OK veo_excel_processor loaded")
# except ImportError as e:
#     main_logger.critical(f"veo_excel_processor import failed: {e}")
#     sys.exit(1)

# # Directories
# _BASE_DIR  = _HERE
# output_dir = _BASE_DIR / config.OUTPUT_DIR
# temp_dir   = _BASE_DIR / config.TEMP_DIR
# output_dir.mkdir(parents=True, exist_ok=True)
# temp_dir.mkdir(parents=True, exist_ok=True)
# (output_dir / "decompositions").mkdir(exist_ok=True)

# try:
#     from video_stitcher import VideoStitcher
#     from prompt_decomposer import PromptDecomposer

#     video_stitcher = VideoStitcher(
#         output_dir            = output_dir,
#         aws_access_key_id     = "",
#         aws_secret_access_key = "",
#         bucket                = "",
#         region                = "",
#     )
#     prompt_decomposer = PromptDecomposer(
#         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#         region                = config.AWS_DEFAULT_REGION,
#     )
#     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
#     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     main_logger.info(
#         f"   Decomposer : "
#         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
#     )
# except ImportError as e:
#     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
#     sys.exit(1)

# veo_generator = None
# try:
#     from veo_generator import VeoGenerator
#     if config.GOOGLE_API_KEY:
#         veo_generator = VeoGenerator(
#             api_key              = config.GOOGLE_API_KEY,
#             output_dir           = output_dir,
#             model_primary        = config.VEO_MODEL_PRIMARY,
#             model_fallback       = config.VEO_MODEL_FALLBACK,
#             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
#             aspect_ratio         = config.VEO_ASPECT_RATIO,
#             resolution           = config.VEO_RESOLUTION,
#             generate_audio       = config.VEO_GENERATE_AUDIO,
#             sample_count         = config.VEO_SAMPLE_COUNT,
#             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
#             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
#         )
#         main_logger.info("OK VeoGenerator initialised")
#     else:
#         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# except ImportError as e:
#     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# if not veo_generator:
#     main_logger.critical("Cannot start without a Veo generator. Exiting.")
#     sys.exit(1)

# from veo_s3 import VeoS3Client
# veo_s3 = VeoS3Client(
#     bucket = os.getenv("VEO_S3_BUCKET", ""),
#     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# )
# main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# from veo_orchestrator import VeoOrchestrator
# veo_orchestrator = VeoOrchestrator(
#     generator     = veo_generator,
#     stitcher      = video_stitcher,
#     decomposer    = prompt_decomposer,
#     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
#     s3_client     = veo_s3,
# )
# main_logger.info("OK VeoOrchestrator initialised")

# # ── Job store ─────────────────────────────────────────────────────────────────
# jobs: Dict[str, Any] = {}

# # ── Per-request user identity ─────────────────────────────────────────────────
# def _request_user(request: Request) -> tuple:
#     """
#     Return (user_id, user_role) from request headers.
#     X-User-Id   — authenticated user email (set by frontend _headers())
#     X-User-Role — role string: admin / editor / viewer
#     Defaults to ("anonymous","viewer") so curl/API docs still work.
#     PRODUCTION: replace with JWT decode.
#     """
#     uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
#     role = request.headers.get("X-User-Role", "viewer").strip().lower()
#     return uid, role

# def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
#     """Admins see all jobs. Others see only their own."""
#     if user_role == "admin":
#         return True
#     return job_data.get("user_id", "anonymous") == user_id

# # ── Live metrics store ────────────────────────────────────────────────────────
# # Updated in real-time by generator and decomposer via push.
# # Resets on server restart — tracks current session only.
# _metrics: Dict[str, Any] = {
#     # Veo API
#     "veo_submissions":      0,   # total API calls attempted
#     "veo_successes":        0,   # successful completions
#     "veo_failures":         0,   # all failures (any error)
#     "veo_rate_limit_hits":  0,   # 429 errors specifically
#     "veo_clips_generated":  0,   # clips that produced a video file
#     "veo_generation_time_s": 0.0, # cumulative generation time

#     # Bedrock decomposer
#     "decomp_nova_calls":       0,
#     "decomp_deepseek_calls":   0,
#     "decomp_deterministic":    0,
#     "decomp_input_tokens":     0,
#     "decomp_output_tokens":    0,

#     # S3
#     "s3_uploads_ok":    0,
#     "s3_uploads_fail":  0,

#     # Session
#     "session_start":    None,   # set on first job
#     "jobs_processed":   0,
# }

# # ── FastAPI ───────────────────────────────────────────────────────────────────
# app = FastAPI(
#     title       = "Veo Video Generation Platform",
#     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
#     version     = "1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
#                          "http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials = True,
#     allow_methods     = ["*"],
#     allow_headers     = ["*"],
# )

# app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # ── Routes ────────────────────────────────────────────────────────────────────

# @app.get("/health")
# async def health_check():
#     health_logger.info("Health check requested")
#     return {
#         "status":    "healthy",
#         "service":   "veo-video-generation-platform",
#         "version":   "1.0.0",
#         "timestamp": datetime.now().isoformat(),
#         "components": {
#             "veo_generator":   True,
#             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
#             "decomposer":      True,
#         },
#         "veo": {
#             "primary_model":  config.VEO_MODEL_PRIMARY,
#             "fallback_model": config.VEO_MODEL_FALLBACK,
#             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
#             "aspect_ratio":   config.VEO_ASPECT_RATIO,
#             "resolution":     config.VEO_RESOLUTION,
#             "native_audio":   True,  # Veo 3.0 always generates audio natively
#         },
#         "decomposer_mode": (
#             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
#         ),
#     }


# @app.get("/api/metrics")
# async def get_metrics():
#     """Real-time generation metrics for the Streamlit dashboard."""
#     import time
#     from datetime import datetime, timezone

#     # Derived metrics
#     total_veo   = _metrics["veo_submissions"]
#     rl_rate     = (
#         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
#         if total_veo > 0 else 0.0
#     )
#     avg_clip_s  = (
#         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
#         if _metrics["veo_clips_generated"] > 0 else 0.0
#     )

#     # Estimated cost (clips × 8s × $0.40 for primary model)
#     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
#     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

#     return {
#         "session_start":        _metrics["session_start"],
#         "jobs_processed":       _metrics["jobs_processed"],

#         "veo": {
#             "submissions":      _metrics["veo_submissions"],
#             "successes":        _metrics["veo_successes"],
#             "failures":         _metrics["veo_failures"],
#             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
#             "rate_limit_pct":   rl_rate,
#             "clips_generated":  _metrics["veo_clips_generated"],
#             "avg_clip_time_s":  avg_clip_s,
#             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
#         },

#         "decomposer": {
#             "nova_calls":        _metrics["decomp_nova_calls"],
#             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
#             "deterministic":     _metrics["decomp_deterministic"],
#             "input_tokens":      _metrics["decomp_input_tokens"],
#             "output_tokens":     _metrics["decomp_output_tokens"],
#             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
#         },

#         "s3": {
#             "uploads_ok":   _metrics["s3_uploads_ok"],
#             "uploads_fail": _metrics["s3_uploads_fail"],
#         },

#         "cost_estimate": {
#             "usd": round(est_cost_usd, 4),
#             "inr": round(est_cost_inr, 2),
#             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
#         },
#     }


# @app.get("/api/jobs")
# async def list_jobs(request: Request):
#     user_id, user_role = _request_user(request)
#     visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
#     job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
#     return {
#         "jobs": [
#             {
#                 "job_id":            job_id,
#                 "original_filename": jd.get("original_filename", ""),
#                 "status":            jd.get("status", "processing"),
#                 "total_prompts":     jd.get("total_prompts", 0),
#                 "completed_prompts": jd.get("completed_prompts", 0),
#                 "failed_prompts":    jd.get("failed_prompts", 0),
#                 "progress_percent":  jd.get("progress_percent", 0.0),
#                 "created_at":        jd.get("created_at", ""),
#                 "generation_status": jd.get("generation_status", "Queued"),
#                 "user_id":           jd.get("user_id", "anonymous"),
#             }
#             for job_id, jd in visible.items()
#         ]
#     }


# @app.get("/api/jobs/{job_id}")
# async def get_job(job_id: str, request: Request):
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     user_id, user_role = _request_user(request)
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied")

#     job_data = jobs[job_id]
#     results  = job_data.get("results", {})

#     prompts_out = []
#     for i, prompt_data in enumerate(job_data.get("prompts", [])):
#         r = results.get(str(i), {})
#         # video_url: may be S3 URL after upload (for distribution)
#         # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
#         raw_video_url = r.get("video_url")
#         raw_local_url = r.get("local_video_url")
#         # Ensure local_video_url is a proper /videos/ route, not an absolute path
#         if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
#             from pathlib import Path as _Path
#             raw_local_url = f"/videos/{_Path(raw_local_url).name}"
#         # If no local URL stored but video_url is already a local route, use it
#         if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
#             raw_local_url = raw_video_url
#         prompts_out.append({
#             "prompt_id":        f"prompt_{i + 1}",
#             "prompt_text":      prompt_data.get("text", ""),
#             "row_number":       i + 1,
#             "duration":         prompt_data.get("duration", 8),
#             "status":           r.get("status", "processing"),
#             "video_url":        raw_video_url,    # S3 or local route
#             "local_video_url":  raw_local_url,    # always /videos/... for player
#             "duration_seconds": r.get("duration_seconds"),
#             "stitched":         r.get("stitched", False),
#             "clips_count":      r.get("clips_count", 0),
#             "clip_urls":        r.get("clip_urls", []),
#             "model_used":       r.get("model_used", ""),
#             "has_native_audio": r.get("has_native_audio", False),
#             "error_message":    r.get("error_message"),
#             "generation_time_seconds": r.get("generation_time_seconds"),
#         })

#     return {
#         "job_id": job_id,
#         "status": job_data.get("status", "processing"),
#         "summary": {
#             "job_id":            job_id,
#             "original_filename": job_data.get("original_filename", ""),
#             "status":            job_data.get("status", "processing"),
#             "total_prompts":     job_data.get("total_prompts", 0),
#             "completed_prompts": job_data.get("completed_prompts", 0),
#             "failed_prompts":    job_data.get("failed_prompts", 0),
#             "progress_percent":  job_data.get("progress_percent", 0.0),
#             "total_processing_time": job_data.get("total_processing_time"),
#         },
#         "prompts": prompts_out,
#     }


# @app.post("/api/upload")
# async def upload_excel(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(...),
# ):
#     """
#     Accept an Excel/CSV file and start Veo generation as a background job.

#     Required Excel columns:  prompt, duration
#     Optional Excel columns:  task_type, priority
#     """
#     upload_id = str(uuid.uuid4())[:8]
#     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

#     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     is_valid, errors = validate_excel_file(str(temp_path))
#     if not is_valid:
#         temp_path.unlink(missing_ok=True)
#         raise HTTPException(
#             status_code=400,
#             detail=f"Excel validation failed: {'; '.join(errors)}",
#         )

#     job_data = create_job_from_excel(
#         file_path  = str(temp_path),
#         platforms  = ["veo"],
#         audio_mode = "platform_native",   # unused — Veo owns its audio
#     )
#     job_id = job_data["job_id"]

#     user_id, user_role = _request_user(request)

#     jobs[job_id]                      = job_data
#     jobs[job_id]["temp_file"]         = str(temp_path)
#     jobs[job_id]["upload_id"]         = upload_id
#     jobs[job_id]["original_filename"] = file.filename
#     jobs[job_id]["user_id"]           = user_id
#     jobs[job_id]["mode"]              = mode
#     jobs[job_id]["clip_duration"]     = clip_duration
#     jobs[job_id]["no_text"]           = no_text
#     jobs[job_id]["no_speech"]         = no_speech

#     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

#     background_tasks.add_task(run_generation_job, job_id)

#     return {
#         "success":       True,
#         "job_id":        job_id,
#         "upload_id":     upload_id,
#         "prompts_count": job_data["total_prompts"],
#         "veo_model":     config.VEO_MODEL_PRIMARY,
#         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
#         "native_audio":  True,  # Veo 3.0 always generates audio natively
#         "stitching":     video_stitcher.ffmpeg_available,
#         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
#     }


# # ── Concurrency config ────────────────────────────────────────────────────────

# # Max prompts running simultaneously within one job.
# # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # Each prompt with 4 clips = 4 sequential API calls.
# # At concurrency=2, clip submissions from two prompts can overlap
# # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # on the free tier. Increase if you have a paid quota.
# _PROMPT_CONCURRENCY = 1


# # ── Background generation job ─────────────────────────────────────────────────

# async def run_generation_job(job_id: str) -> None:
#     """
#     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

#     Design:
#     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
#     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
#     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
#     - Results are stored by index key str(i) — API schema unchanged.
#     - Progress percent is updated after each prompt completes (order-independent).
#     """
#     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
#     start_time   = time.time()

#     # Track session start on first job
#     if _metrics["session_start"] is None:
#         from datetime import datetime, timezone
#         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
#     _metrics["jobs_processed"] += 1
#     job          = jobs[job_id]
#     prompts_data = job["prompts"]
#     total        = len(prompts_data)

#     jobs[job_id]["results"]            = {}
#     jobs[job_id]["completed_prompts"]  = 0
#     jobs[job_id]["failed_prompts"]     = 0
#     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

#     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
#     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

#     async def _run_prompt(i: int, prompt_data: dict) -> None:
#         """
#         Semaphore-gated coroutine for a single prompt.
#         Clips within this prompt run sequentially inside generate_for_prompt().
#         """
#         prompt_text = prompt_data["text"]
#         duration    = prompt_data["duration"]

#         async with semaphore:
#             if job_id not in jobs:
#                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
#                 return

#             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
#             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
#             prompt_start = time.time()

#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = i,
#             )

#             elapsed = time.time() - prompt_start

#         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
#         async with state_lock:
#             jobs[job_id]["results"][str(i)] = result

#             # ── Push result stats into live metrics ───────────────────────────
#             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
#             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
#             # Decomposer token tracking
#             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
#             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
#             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
#             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
#             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
#             # S3 tracking
#             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
#             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

#             if result.get("status") in ("completed", "partial"):
#                 jobs[job_id]["completed_prompts"] += 1
#                 _metrics["veo_successes"]       += 1
#                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
#                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
#                 generation_logger.info(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
#                     f"-> {result.get('video_url')} "
#                     f"({'stitched' if result.get('stitched') else 'single'}, "
#                     f"{result.get('clips_count', 1)} clip(s))"
#                 )
#                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
#             else:
#                 jobs[job_id]["failed_prompts"] += 1
#                 _metrics["veo_failures"] += 1
#                 generation_logger.error(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
#                     f"{result.get('error_message')}"
#                 )

#             done_so_far = (
#                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
#             )
#             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
#             jobs[job_id]["generation_status"]  = (
#                 f"Running — {done_so_far}/{total} complete"
#             )

#     # ── Launch based on mode ──────────────────────────────────────────────────
#     mode         = job.get("mode", "full")
#     no_text      = job.get("no_text", False)
#     no_speech    = job.get("no_speech", False)
#     clip_dur     = job.get("clip_duration", 2.0)

#     if mode == "short_span":
#         # ── Short Span Clips: all rows = one sequence, no decomposition ───────
#         # Inject guardrails into prompt text before passing to orchestrator
#         _NO_TEXT_G = (
#             "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#             "subtitles, watermarks, or UI labels anywhere in the frame."
#         )
#         _NO_SPEECH_G = (
#             "NO SPEECH: No person should be speaking or moving their lips. "
#             "No narration or dialogue. Ambient background sound only."
#         )
#         enriched = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:   parts.append(_NO_TEXT_G)
#             if no_speech: parts.append(_NO_SPEECH_G)
#             parts.append(pd.get("text", ""))
#             enriched.append({**pd, "text": " ".join(parts)})

#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN mode — {len(enriched)} clip(s) "
#             f"at {clip_dur}s each, no_text={no_text}, no_speech={no_speech}"
#         )
#         result = await veo_orchestrator.generate_short_span_sequence(
#             prompts         = enriched,
#             job_id          = job_id,
#             clip_duration_s = clip_dur,
#             no_text         = False,   # already injected above
#             no_speech       = False,
#         )
#         # Store as single result at index 0 and mark job done
#         async with state_lock:
#             jobs[job_id]["results"]["0"]          = result
#             jobs[job_id]["completed_prompts"]     = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]        = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]      = 100.0
#             jobs[job_id]["generation_status"]     = "All prompts processed"
#             _metrics["veo_clips_generated"]      += result.get("clips_count", 0)
#             _metrics["veo_generation_time_s"]    += result.get("generation_time_seconds", 0) or 0
#             if result.get("status") in ("completed", "partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"] += 1

#     else:
#         # ── Full Length Videos (existing pipeline) ────────────────────────────
#         # Inject no_text/no_speech guardrails into prompt text if requested
#         if no_text or no_speech:
#             _NO_TEXT_G = (
#                 "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#                 "subtitles, watermarks, or UI labels anywhere in the frame."
#             )
#             _NO_SPEECH_G = (
#                 "NO SPEECH: No person should be speaking or moving their lips. "
#                 "No narration or dialogue. Ambient background sound only."
#             )
#             for pd in prompts_data:
#                 parts = []
#                 if no_text:   parts.append(_NO_TEXT_G)
#                 if no_speech: parts.append(_NO_SPEECH_G)
#                 parts.append(pd.get("text", ""))
#                 pd["text"] = " ".join(parts)

#         tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
#         await asyncio.gather(*tasks, return_exceptions=True)

#     # ── Finalise ──────────────────────────────────────────────────────────────
#     total_elapsed = time.time() - start_time
#     failed_count  = jobs[job_id].get("failed_prompts", 0)

#     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
#     jobs[job_id]["generation_status"]     = "All prompts processed"
#     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

#     generation_logger.info(
#         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
#         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
#     )

#     try:
#         temp_file = jobs[job_id].get("temp_file")
#         if temp_file:
#             Path(temp_file).unlink(missing_ok=True)
#     except Exception as e:
#         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # ── Rerun single prompt ───────────────────────────────────────────────────────

# @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
#     """
#     Re-run a single prompt within an existing job.

#     Flow:
#     - Validates job and prompt exist
#     - Marks the result as "processing" immediately (UI picks this up on next poll)
#     - Schedules a background task that calls the orchestrator for just that one prompt
#     - Returns immediately so the UI is never blocked

#     Used by: rerun button on each video card in the frontend.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job = jobs[job_id]
#     prompts_data = job.get("prompts", [])

#     if prompt_index < 0 or prompt_index >= len(prompts_data):
#         raise HTTPException(
#             status_code=400,
#             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
#         )

#     prompt_data = prompts_data[prompt_index]

#     # Mark as processing immediately so frontend shows skeleton
#     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
#         "status": "processing",
#         "video_url": None,
#     }
#     # Reset counters to reflect the rerun
#     jobs[job_id]["status"] = "processing"

#     generation_logger.info(
#         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
#         f"'{prompt_data.get('text', '')[:60]}...'"
#     )

#     async def _rerun():
#         try:
#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = prompt_index,
#             )
#             jobs[job_id]["results"][str(prompt_index)] = result

#             # Recompute job-level status from all results
#             all_results = jobs[job_id].get("results", {})
#             total = len(prompts_data)
#             completed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") in ("completed", "partial")
#             )
#             failed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "failed"
#             )
#             processing = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "processing"
#             )

#             if processing == 0:
#                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
#                 jobs[job_id]["completed_prompts"] = completed
#                 jobs[job_id]["failed_prompts"]    = failed
#                 jobs[job_id]["progress_percent"]  = 100.0

#             generation_logger.info(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
#                 f"status={result.get('status')}"
#             )
#         except Exception as e:
#             jobs[job_id]["results"][str(prompt_index)] = {
#                 "status": "failed",
#                 "error_message": str(e),
#             }
#             generation_logger.error(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
#             )

#     # Soft-delete the old S3 video before rerunning
#     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
#     if veo_s3.enabled:
#         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
#         if moved:
#             generation_logger.info(
#                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
#             )
#         else:
#             generation_logger.warning(
#                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
#             )

#     background_tasks.add_task(_rerun)

#     return {
#         "status":        "accepted",
#         "job_id":        job_id,
#         "prompt_index":  prompt_index,
#         "message":       f"Rerun started for prompt {prompt_index + 1}",
#     }


# # ── YouTube upload queue ──────────────────────────────────────────────────────
# # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# #                                tags, local_path, s3_url, status, youtube_url } }
# # "approved" = waiting to upload, "uploading" = in progress,
# # "uploaded" = done, "failed" = error
# youtube_queue: Dict[str, Any] = {}


# import veo_youtube as _yt


# @app.get("/api/youtube/status")
# async def youtube_status():
#     """Check if YouTube is configured and authenticated."""
#     return {
#         "configured":    _yt.is_configured(),
#         "authenticated": _yt.is_authenticated(),
#         "secrets_file":  str(_yt.SECRETS_FILE),
#     }


# @app.post("/api/youtube/auth")
# async def youtube_auth():
#     """
#     Trigger the OAuth browser flow.
#     Opens a browser tab — user logs in, approves, token is saved.
#     Returns immediately after auth completes.
#     """
#     try:
#         _yt.get_authenticated_service()
#         return {"status": "authenticated"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# async def approve_video(job_id: str, prompt_index: int, request: Request):
#     """
#     Approve a completed video — adds it to the YouTube upload queue.

#     Auto-generates title/description/tags from the prompt.
#     User edits these in the UI before triggering upload.

#     Returns the queue_id so the frontend can reference this queue entry.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job      = jobs[job_id]
#     prompts  = job.get("prompts", [])
#     results  = job.get("results", {})

#     if prompt_index < 0 or prompt_index >= len(prompts):
#         raise HTTPException(status_code=400, detail="prompt_index out of range")

#     result = results.get(str(prompt_index), {})
#     if result.get("status") != "completed":
#         raise HTTPException(status_code=400, detail="Video is not completed yet")

#     prompt_text = prompts[prompt_index].get("text", "")
#     video_url   = result.get("video_url", "")
#     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
#     s3_url      = result.get("s3_url", "")

#     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
#     if local_path and local_path.startswith("/videos/"):
#         from pathlib import Path as _Path
#         output_dir = _Path(__file__).parent / "outputs" / "videos"
#         local_path = str(output_dir / _Path(local_path).name)

#     metadata  = _yt.generate_metadata(prompt_text)
#     queue_id  = f"q_{job_id}_{prompt_index}"

#     youtube_queue[queue_id] = {
#         "queue_id":     queue_id,
#         "job_id":       job_id,
#         "prompt_index": prompt_index,
#         "prompt_text":  prompt_text[:120],
#         "local_path":   local_path,
#         "s3_url":       s3_url,
#         "video_url":    video_url,
#         "title":        metadata["title"],
#         "description":  metadata["description"],
#         "tags":         metadata["tags"],
#         "status":       "approved",
#         "youtube_url":  None,
#         "error":        None,
#     }

#     generation_logger.info(
#         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
#     )

#     return youtube_queue[queue_id]


# @app.get("/api/youtube/queue")
# async def get_youtube_queue():
#     """Return all items in the upload queue."""
#     return {"queue": list(youtube_queue.values())}


# @app.patch("/api/youtube/queue/{queue_id}")
# async def update_queue_item(queue_id: str, body: dict):
#     """
#     Update editable metadata for a queued video before upload.
#     Accepts: { title, description, tags }
#     """
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

#     item = youtube_queue[queue_id]
#     if item["status"] not in ("approved", "failed"):
#         raise HTTPException(
#             status_code=400,
#             detail=f"Cannot edit item with status '{item['status']}'"
#         )

#     if "title" in body:
#         item["title"]       = str(body["title"])[:100]
#     if "description" in body:
#         item["description"] = str(body["description"])[:5000]
#     if "tags" in body and isinstance(body["tags"], list):
#         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

#     return item


# @app.post("/api/youtube/upload")
# async def upload_to_youtube(background_tasks: BackgroundTasks):
#     """
#     Upload ALL approved queue items to YouTube.

#     Runs in background — returns immediately.
#     Poll /api/youtube/queue to track per-item status.
#     """
#     approved = [
#         item for item in youtube_queue.values()
#         if item["status"] == "approved"
#     ]

#     if not approved:
#         raise HTTPException(status_code=400, detail="No approved videos in queue")

#     if not _yt.is_configured():
#         raise HTTPException(
#             status_code=503,
#             detail="YouTube not configured — youtube_client_secrets.json missing"
#         )

#     async def _upload_all():
#         for item in approved:
#             qid = item["queue_id"]
#             youtube_queue[qid]["status"] = "uploading"
#             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

#             result = await asyncio.get_event_loop().run_in_executor(
#                 None,
#                 lambda i=item: _yt.upload_video(
#                     local_path  = i["local_path"],
#                     title       = i["title"],
#                     description = i["description"],
#                     tags        = i["tags"],
#                     privacy     = "public",
#                 ),
#             )

#             if result["status"] == "uploaded":
#                 youtube_queue[qid]["status"]      = "uploaded"
#                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
#                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
#                 generation_logger.info(
#                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
#                 )
#             else:
#                 youtube_queue[qid]["status"] = "failed"
#                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
#                 generation_logger.error(
#                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
#                 )

#     background_tasks.add_task(_upload_all)

#     return {
#         "status":  "started",
#         "count":   len(approved),
#         "message": f"Uploading {len(approved)} video(s) to YouTube",
#     }


# @app.delete("/api/youtube/queue/{queue_id}")
# async def remove_from_queue(queue_id: str):
#     """Remove an item from the upload queue (before it's uploaded)."""
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
#     if youtube_queue[queue_id]["status"] == "uploading":
#         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
#     del youtube_queue[queue_id]
#     return {"status": "removed", "queue_id": queue_id}


# # ── Entry point ───────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     s = logging.getLogger("STARTUP")
#     s.info("=" * 70)
#     s.info("Veo Video Generation Platform v1.0.0")
#     s.info("=" * 70)
#     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
#     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
#     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
#     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
#     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     s.info("Endpoints:")
#     s.info("   API    : http://localhost:8100")
#     s.info("   Docs   : http://localhost:8100/docs")
#     s.info("   Health : http://localhost:8100/health")
#     s.info("=" * 70)

#     uvicorn.run(
#         "veo_main:app",
#         host      = "0.0.0.0",
#         port      = 8100,
#         reload    = True,
#         log_level = "info",
#     )


























# #!/usr/bin/env python3
# """
# veo_main.py — Veo Video Generation Platform
# ════════════════════════════════════════════

# Standalone FastAPI service. Accepts Excel uploads, generates videos via
# Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# via FFmpeg, and serves results as downloadable MP4 files.

# Veo 3.1 generates video and audio natively from the text prompt — no
# post-processing or external audio service is required.

# Endpoints:
#   GET  /health                → system status
#   POST /api/upload            → accept .xlsx/.csv, start background job
#   GET  /api/jobs              → list all jobs
#   GET  /api/jobs/{job_id}     → job details + per-prompt results
#   GET  /videos/{filename}     → serve generated MP4 files

# Run:
#   python veo_main.py
#   -> http://localhost:8100
#   -> http://localhost:8100/docs

# Port 8100 avoids collision with the Nova/Runway service on 8000.
# """

# import asyncio
# import logging
# import os
# import sys
# import time
# import uuid
# from datetime import datetime
# from pathlib import Path
# from typing import Any, Dict

# import uvicorn
# from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level   = logging.INFO,
#     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
#     datefmt = "%Y-%m-%d %H:%M:%S",
# )
# main_logger       = logging.getLogger("MAIN")
# upload_logger     = logging.getLogger("UPLOAD")
# generation_logger = logging.getLogger("GENERATION")
# progress_logger   = logging.getLogger("PROGRESS")
# job_logger        = logging.getLogger("JOB_MANAGER")
# health_logger     = logging.getLogger("HEALTH")

# # ── Local imports ─────────────────────────────────────────────────────────────
# _HERE = Path(__file__).resolve().parent
# sys.path.insert(0, str(_HERE))

# try:
#     from veo_config import veo_config as config
#     main_logger.info("OK veo_config loaded")
#     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# except ImportError as e:
#     main_logger.critical(f"[CONFIG_ERROR] {e}")
#     sys.exit(1)

# try:
#     from veo_excel_processor import create_job_from_excel, validate_excel_file
#     main_logger.info("OK veo_excel_processor loaded")
# except ImportError as e:
#     main_logger.critical(f"veo_excel_processor import failed: {e}")
#     sys.exit(1)

# # Directories
# _BASE_DIR  = _HERE
# output_dir = _BASE_DIR / config.OUTPUT_DIR
# temp_dir   = _BASE_DIR / config.TEMP_DIR
# output_dir.mkdir(parents=True, exist_ok=True)
# temp_dir.mkdir(parents=True, exist_ok=True)
# (output_dir / "decompositions").mkdir(exist_ok=True)

# try:
#     from video_stitcher import VideoStitcher
#     from prompt_decomposer import PromptDecomposer

#     video_stitcher = VideoStitcher(
#         output_dir            = output_dir,
#         aws_access_key_id     = "",
#         aws_secret_access_key = "",
#         bucket                = "",
#         region                = "",
#     )
#     prompt_decomposer = PromptDecomposer(
#         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#         region                = config.AWS_DEFAULT_REGION,
#     )
#     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
#     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     main_logger.info(
#         f"   Decomposer : "
#         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
#     )
# except ImportError as e:
#     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
#     sys.exit(1)

# veo_generator = None
# try:
#     from veo_generator import VeoGenerator
#     if config.GOOGLE_API_KEY:
#         veo_generator = VeoGenerator(
#             api_key              = config.GOOGLE_API_KEY,
#             output_dir           = output_dir,
#             model_primary        = config.VEO_MODEL_PRIMARY,
#             model_fallback       = config.VEO_MODEL_FALLBACK,
#             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
#             aspect_ratio         = config.VEO_ASPECT_RATIO,
#             resolution           = config.VEO_RESOLUTION,
#             generate_audio       = config.VEO_GENERATE_AUDIO,
#             sample_count         = config.VEO_SAMPLE_COUNT,
#             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
#             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
#         )
#         main_logger.info("OK VeoGenerator initialised")
#     else:
#         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# except ImportError as e:
#     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# if not veo_generator:
#     main_logger.critical("Cannot start without a Veo generator. Exiting.")
#     sys.exit(1)

# from veo_s3 import VeoS3Client
# veo_s3 = VeoS3Client(
#     bucket = os.getenv("VEO_S3_BUCKET", ""),
#     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# )
# main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# from veo_orchestrator import VeoOrchestrator
# from veo_short_span_orchestrator import ShortSpanOrchestrator
# veo_orchestrator = VeoOrchestrator(
#     generator     = veo_generator,
#     stitcher      = video_stitcher,
#     decomposer    = prompt_decomposer,
#     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
#     s3_client     = veo_s3,
# )
# main_logger.info("OK VeoOrchestrator initialised")

# ss_orchestrator = ShortSpanOrchestrator(
#     generator  = veo_generator,
#     stitcher   = video_stitcher,
#     s3_client  = veo_s3,
# )
# main_logger.info("OK ShortSpanOrchestrator initialised")

# # ── Job store ─────────────────────────────────────────────────────────────────
# jobs: Dict[str, Any] = {}

# # ── Per-request user identity ─────────────────────────────────────────────────
# def _request_user(request: Request) -> tuple:
#     """
#     Return (user_id, user_role) from request headers.
#     X-User-Id   — authenticated user email (set by frontend _headers())
#     X-User-Role — role string: admin / editor / viewer
#     Defaults to ("anonymous","viewer") so curl/API docs still work.
#     PRODUCTION: replace with JWT decode.
#     """
#     uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
#     role = request.headers.get("X-User-Role", "viewer").strip().lower()
#     return uid, role

# def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
#     """Admins see all jobs. Others see only their own."""
#     if user_role == "admin":
#         return True
#     return job_data.get("user_id", "anonymous") == user_id

# # ── Live metrics store ────────────────────────────────────────────────────────
# # Updated in real-time by generator and decomposer via push.
# # Resets on server restart — tracks current session only.
# _metrics: Dict[str, Any] = {
#     # Veo API
#     "veo_submissions":      0,   # total API calls attempted
#     "veo_successes":        0,   # successful completions
#     "veo_failures":         0,   # all failures (any error)
#     "veo_rate_limit_hits":  0,   # 429 errors specifically
#     "veo_clips_generated":  0,   # clips that produced a video file
#     "veo_generation_time_s": 0.0, # cumulative generation time

#     # Bedrock decomposer
#     "decomp_nova_calls":       0,
#     "decomp_deepseek_calls":   0,
#     "decomp_deterministic":    0,
#     "decomp_input_tokens":     0,
#     "decomp_output_tokens":    0,

#     # S3
#     "s3_uploads_ok":    0,
#     "s3_uploads_fail":  0,

#     # Session
#     "session_start":    None,   # set on first job
#     "jobs_processed":   0,
# }

# # ── FastAPI ───────────────────────────────────────────────────────────────────
# app = FastAPI(
#     title       = "Veo Video Generation Platform",
#     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
#     version     = "1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
#                          "http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials = True,
#     allow_methods     = ["*"],
#     allow_headers     = ["*"],
# )

# app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # ── Routes ────────────────────────────────────────────────────────────────────

# @app.get("/health")
# async def health_check():
#     health_logger.info("Health check requested")
#     return {
#         "status":    "healthy",
#         "service":   "veo-video-generation-platform",
#         "version":   "1.0.0",
#         "timestamp": datetime.now().isoformat(),
#         "components": {
#             "veo_generator":   True,
#             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
#             "decomposer":      True,
#         },
#         "veo": {
#             "primary_model":  config.VEO_MODEL_PRIMARY,
#             "fallback_model": config.VEO_MODEL_FALLBACK,
#             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
#             "aspect_ratio":   config.VEO_ASPECT_RATIO,
#             "resolution":     config.VEO_RESOLUTION,
#             "native_audio":   True,  # Veo 3.0 always generates audio natively
#         },
#         "decomposer_mode": (
#             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
#         ),
#     }


# @app.get("/api/metrics")
# async def get_metrics():
#     """Real-time generation metrics for the Streamlit dashboard."""
#     import time
#     from datetime import datetime, timezone

#     # Derived metrics
#     total_veo   = _metrics["veo_submissions"]
#     rl_rate     = (
#         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
#         if total_veo > 0 else 0.0
#     )
#     avg_clip_s  = (
#         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
#         if _metrics["veo_clips_generated"] > 0 else 0.0
#     )

#     # Estimated cost (clips × 8s × $0.40 for primary model)
#     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
#     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

#     return {
#         "session_start":        _metrics["session_start"],
#         "jobs_processed":       _metrics["jobs_processed"],

#         "veo": {
#             "submissions":      _metrics["veo_submissions"],
#             "successes":        _metrics["veo_successes"],
#             "failures":         _metrics["veo_failures"],
#             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
#             "rate_limit_pct":   rl_rate,
#             "clips_generated":  _metrics["veo_clips_generated"],
#             "avg_clip_time_s":  avg_clip_s,
#             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
#         },

#         "decomposer": {
#             "nova_calls":        _metrics["decomp_nova_calls"],
#             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
#             "deterministic":     _metrics["decomp_deterministic"],
#             "input_tokens":      _metrics["decomp_input_tokens"],
#             "output_tokens":     _metrics["decomp_output_tokens"],
#             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
#         },

#         "s3": {
#             "uploads_ok":   _metrics["s3_uploads_ok"],
#             "uploads_fail": _metrics["s3_uploads_fail"],
#         },

#         "cost_estimate": {
#             "usd": round(est_cost_usd, 4),
#             "inr": round(est_cost_inr, 2),
#             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
#         },
#     }


# @app.get("/api/jobs")
# async def list_jobs(request: Request):
#     user_id, user_role = _request_user(request)
#     visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
#     job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
#     return {
#         "jobs": [
#             {
#                 "job_id":            job_id,
#                 "original_filename": jd.get("original_filename", ""),
#                 "status":            jd.get("status", "processing"),
#                 "total_prompts":     jd.get("total_prompts", 0),
#                 "completed_prompts": jd.get("completed_prompts", 0),
#                 "failed_prompts":    jd.get("failed_prompts", 0),
#                 "progress_percent":  jd.get("progress_percent", 0.0),
#                 "created_at":        jd.get("created_at", ""),
#                 "generation_status": jd.get("generation_status", "Queued"),
#                 "user_id":           jd.get("user_id", "anonymous"),
#             }
#             for job_id, jd in visible.items()
#         ]
#     }


# @app.get("/api/jobs/{job_id}")
# async def get_job(job_id: str, request: Request):
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     user_id, user_role = _request_user(request)
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied")

#     job_data = jobs[job_id]
#     results  = job_data.get("results", {})

#     prompts_out = []
#     for i, prompt_data in enumerate(job_data.get("prompts", [])):
#         r = results.get(str(i), {})
#         # video_url: may be S3 URL after upload (for distribution)
#         # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
#         raw_video_url = r.get("video_url")
#         raw_local_url = r.get("local_video_url")
#         # Ensure local_video_url is a proper /videos/ route, not an absolute path
#         if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
#             from pathlib import Path as _Path
#             raw_local_url = f"/videos/{_Path(raw_local_url).name}"
#         # If no local URL stored but video_url is already a local route, use it
#         if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
#             raw_local_url = raw_video_url
#         prompts_out.append({
#             "prompt_id":        f"prompt_{i + 1}",
#             "prompt_text":      prompt_data.get("text", ""),
#             "row_number":       i + 1,
#             "duration":         prompt_data.get("duration", 8),
#             "status":           r.get("status", "processing"),
#             "video_url":        raw_video_url,    # S3 or local route
#             "local_video_url":  raw_local_url,    # always /videos/... for player
#             "duration_seconds": r.get("duration_seconds"),
#             "stitched":         r.get("stitched", False),
#             "clips_count":      r.get("clips_count", 0),
#             "clip_urls":        r.get("clip_urls", []),
#             "model_used":       r.get("model_used", ""),
#             "has_native_audio": r.get("has_native_audio", False),
#             "error_message":    r.get("error_message"),
#             "generation_time_seconds": r.get("generation_time_seconds"),
#         })

#     return {
#         "job_id":       job_id,
#         "status":       job_data.get("status", "processing"),
#         "mode":         job_data.get("mode", "full"),
#         "clip_duration":job_data.get("clip_duration", 8),
#         "no_text":      job_data.get("no_text", False),
#         "no_speech":    job_data.get("no_speech", False),
#         "summary": {
#             "job_id":            job_id,
#             "original_filename": job_data.get("original_filename", ""),
#             "status":            job_data.get("status", "processing"),
#             "total_prompts":     job_data.get("total_prompts", 0),
#             "completed_prompts": job_data.get("completed_prompts", 0),
#             "failed_prompts":    job_data.get("failed_prompts", 0),
#             "progress_percent":  job_data.get("progress_percent", 0.0),
#             "total_processing_time": job_data.get("total_processing_time"),
#         },
#         "prompts": prompts_out,
#     }


# @app.post("/api/upload")
# async def upload_excel(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(...),
# ):
#     """
#     Accept an Excel/CSV file and start Veo generation as a background job.

#     Required Excel columns:  prompt, duration
#     Optional Excel columns:  task_type, priority
#     """
#     upload_id = str(uuid.uuid4())[:8]
#     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

#     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     is_valid, errors = validate_excel_file(str(temp_path))
#     if not is_valid:
#         temp_path.unlink(missing_ok=True)
#         raise HTTPException(
#             status_code=400,
#             detail=f"Excel validation failed: {'; '.join(errors)}",
#         )

#     job_data = create_job_from_excel(
#         file_path  = str(temp_path),
#         platforms  = ["veo"],
#         audio_mode = "platform_native",   # unused — Veo owns its audio
#     )
#     job_id = job_data["job_id"]

#     user_id, user_role = _request_user(request)

#     jobs[job_id]                      = job_data
#     jobs[job_id]["temp_file"]         = str(temp_path)
#     jobs[job_id]["upload_id"]         = upload_id
#     jobs[job_id]["original_filename"] = file.filename
#     jobs[job_id]["user_id"]           = user_id
#     jobs[job_id]["mode"]              = mode
#     jobs[job_id]["clip_duration"]     = clip_duration
#     jobs[job_id]["no_text"]           = no_text
#     jobs[job_id]["no_speech"]         = no_speech

#     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

#     background_tasks.add_task(run_generation_job, job_id)

#     return {
#         "success":       True,
#         "job_id":        job_id,
#         "upload_id":     upload_id,
#         "prompts_count": job_data["total_prompts"],
#         "veo_model":     config.VEO_MODEL_PRIMARY,
#         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
#         "native_audio":  True,  # Veo 3.0 always generates audio natively
#         "stitching":     video_stitcher.ffmpeg_available,
#         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
#     }


# # ── Concurrency config ────────────────────────────────────────────────────────

# # Max prompts running simultaneously within one job.
# # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # Each prompt with 4 clips = 4 sequential API calls.
# # At concurrency=2, clip submissions from two prompts can overlap
# # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # on the free tier. Increase if you have a paid quota.
# _PROMPT_CONCURRENCY = 1


# # ── Background generation job ─────────────────────────────────────────────────

# async def run_generation_job(job_id: str) -> None:
#     """
#     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

#     Design:
#     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
#     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
#     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
#     - Results are stored by index key str(i) — API schema unchanged.
#     - Progress percent is updated after each prompt completes (order-independent).
#     """
#     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
#     start_time   = time.time()

#     # Track session start on first job
#     if _metrics["session_start"] is None:
#         from datetime import datetime, timezone
#         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
#     _metrics["jobs_processed"] += 1
#     job          = jobs[job_id]
#     prompts_data = job["prompts"]
#     total        = len(prompts_data)

#     jobs[job_id]["results"]            = {}
#     jobs[job_id]["completed_prompts"]  = 0
#     jobs[job_id]["failed_prompts"]     = 0
#     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

#     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
#     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

#     async def _run_prompt(i: int, prompt_data: dict) -> None:
#         """
#         Semaphore-gated coroutine for a single prompt.
#         Clips within this prompt run sequentially inside generate_for_prompt().
#         """
#         prompt_text = prompt_data["text"]
#         duration    = prompt_data["duration"]

#         async with semaphore:
#             if job_id not in jobs:
#                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
#                 return

#             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
#             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
#             prompt_start = time.time()

#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = i,
#             )

#             elapsed = time.time() - prompt_start

#         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
#         async with state_lock:
#             jobs[job_id]["results"][str(i)] = result

#             # ── Push result stats into live metrics ───────────────────────────
#             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
#             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
#             # Decomposer token tracking
#             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
#             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
#             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
#             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
#             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
#             # S3 tracking
#             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
#             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

#             if result.get("status") in ("completed", "partial"):
#                 jobs[job_id]["completed_prompts"] += 1
#                 _metrics["veo_successes"]       += 1
#                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
#                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
#                 generation_logger.info(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
#                     f"-> {result.get('video_url')} "
#                     f"({'stitched' if result.get('stitched') else 'single'}, "
#                     f"{result.get('clips_count', 1)} clip(s))"
#                 )
#                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
#             else:
#                 jobs[job_id]["failed_prompts"] += 1
#                 _metrics["veo_failures"] += 1
#                 generation_logger.error(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
#                     f"{result.get('error_message')}"
#                 )

#             done_so_far = (
#                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
#             )
#             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
#             jobs[job_id]["generation_status"]  = (
#                 f"Running — {done_so_far}/{total} complete"
#             )

#     # ── Launch based on mode ──────────────────────────────────────────────────
#     mode         = job.get("mode", "full")
#     no_text      = job.get("no_text", False)
#     no_speech    = job.get("no_speech", False)
#     clip_dur     = job.get("clip_duration", 2.0)

#     if mode == "short_span":
#         # ── Short Span Clips: all rows = one sequence, no decomposition ───────
#         # Inject guardrails into prompt text before passing to orchestrator
#         _NO_TEXT_G = (
#             "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#             "subtitles, watermarks, or UI labels anywhere in the frame."
#         )
#         _NO_SPEECH_G = (
#             "NO SPEECH: No person should be speaking or moving their lips. "
#             "No narration or dialogue. Ambient background sound only."
#         )
#         enriched = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:   parts.append(_NO_TEXT_G)
#             if no_speech: parts.append(_NO_SPEECH_G)
#             parts.append(pd.get("text", ""))
#             enriched.append({**pd, "text": " ".join(parts)})

#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN mode — {len(enriched)} clip(s) "
#             f"at {clip_dur}s each, no_text={no_text}, no_speech={no_speech}"
#         )
#         result = await ss_orchestrator.run(
#             prompts         = enriched,
#             job_id          = job_id,
#             clip_duration_s = clip_dur,
#             no_text         = False,
#             no_speech       = False,
#         )
#         # Store as single result at index 0 and mark job done
#         async with state_lock:
#             jobs[job_id]["results"]["0"]          = result
#             jobs[job_id]["completed_prompts"]     = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]        = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]      = 100.0
#             jobs[job_id]["generation_status"]     = "All prompts processed"
#             _metrics["veo_clips_generated"]      += result.get("clips_count", 0)
#             _metrics["veo_generation_time_s"]    += result.get("generation_time_seconds", 0) or 0
#             if result.get("status") in ("completed", "partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"] += 1

#     else:
#         # ── Full Length Videos (existing pipeline) ────────────────────────────
#         # Inject no_text/no_speech guardrails into prompt text if requested
#         if no_text or no_speech:
#             _NO_TEXT_G = (
#                 "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#                 "subtitles, watermarks, or UI labels anywhere in the frame."
#             )
#             _NO_SPEECH_G = (
#                 "NO SPEECH: No person should be speaking or moving their lips. "
#                 "No narration or dialogue. Ambient background sound only."
#             )
#             for pd in prompts_data:
#                 parts = []
#                 if no_text:   parts.append(_NO_TEXT_G)
#                 if no_speech: parts.append(_NO_SPEECH_G)
#                 parts.append(pd.get("text", ""))
#                 pd["text"] = " ".join(parts)

#         tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
#         await asyncio.gather(*tasks, return_exceptions=True)

#     # ── Finalise ──────────────────────────────────────────────────────────────
#     total_elapsed = time.time() - start_time
#     failed_count  = jobs[job_id].get("failed_prompts", 0)

#     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
#     jobs[job_id]["generation_status"]     = "All prompts processed"
#     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

#     generation_logger.info(
#         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
#         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
#     )

#     try:
#         temp_file = jobs[job_id].get("temp_file")
#         if temp_file:
#             Path(temp_file).unlink(missing_ok=True)
#     except Exception as e:
#         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # ── Rerun single prompt ───────────────────────────────────────────────────────

# @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
#     """
#     Re-run a single prompt within an existing job.

#     Flow:
#     - Validates job and prompt exist
#     - Marks the result as "processing" immediately (UI picks this up on next poll)
#     - Schedules a background task that calls the orchestrator for just that one prompt
#     - Returns immediately so the UI is never blocked

#     Used by: rerun button on each video card in the frontend.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job = jobs[job_id]
#     prompts_data = job.get("prompts", [])

#     if prompt_index < 0 or prompt_index >= len(prompts_data):
#         raise HTTPException(
#             status_code=400,
#             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
#         )

#     prompt_data = prompts_data[prompt_index]

#     # Mark as processing immediately so frontend shows skeleton
#     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
#         "status": "processing",
#         "video_url": None,
#     }
#     # Reset counters to reflect the rerun
#     jobs[job_id]["status"] = "processing"

#     generation_logger.info(
#         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
#         f"'{prompt_data.get('text', '')[:60]}...'"
#     )

#     async def _rerun():
#         try:
#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = prompt_index,
#             )
#             jobs[job_id]["results"][str(prompt_index)] = result

#             # Recompute job-level status from all results
#             all_results = jobs[job_id].get("results", {})
#             total = len(prompts_data)
#             completed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") in ("completed", "partial")
#             )
#             failed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "failed"
#             )
#             processing = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "processing"
#             )

#             if processing == 0:
#                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
#                 jobs[job_id]["completed_prompts"] = completed
#                 jobs[job_id]["failed_prompts"]    = failed
#                 jobs[job_id]["progress_percent"]  = 100.0

#             generation_logger.info(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
#                 f"status={result.get('status')}"
#             )
#         except Exception as e:
#             jobs[job_id]["results"][str(prompt_index)] = {
#                 "status": "failed",
#                 "error_message": str(e),
#             }
#             generation_logger.error(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
#             )

#     # Soft-delete the old S3 video before rerunning
#     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
#     if veo_s3.enabled:
#         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
#         if moved:
#             generation_logger.info(
#                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
#             )
#         else:
#             generation_logger.warning(
#                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
#             )

#     background_tasks.add_task(_rerun)

#     return {
#         "status":        "accepted",
#         "job_id":        job_id,
#         "prompt_index":  prompt_index,
#         "message":       f"Rerun started for prompt {prompt_index + 1}",
#     }


# # ── YouTube upload queue ──────────────────────────────────────────────────────
# # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# #                                tags, local_path, s3_url, status, youtube_url } }
# # "approved" = waiting to upload, "uploading" = in progress,
# # "uploaded" = done, "failed" = error
# youtube_queue: Dict[str, Any] = {}


# import veo_youtube as _yt


# @app.get("/api/youtube/status")
# async def youtube_status():
#     """Check if YouTube is configured and authenticated."""
#     return {
#         "configured":    _yt.is_configured(),
#         "authenticated": _yt.is_authenticated(),
#         "secrets_file":  str(_yt.SECRETS_FILE),
#     }


# @app.post("/api/youtube/auth")
# async def youtube_auth():
#     """
#     Trigger the OAuth browser flow.
#     Opens a browser tab — user logs in, approves, token is saved.
#     Returns immediately after auth completes.
#     """
#     try:
#         _yt.get_authenticated_service()
#         return {"status": "authenticated"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# async def approve_video(job_id: str, prompt_index: int, request: Request):
#     """
#     Approve a completed video — adds it to the YouTube upload queue.

#     Auto-generates title/description/tags from the prompt.
#     User edits these in the UI before triggering upload.

#     Returns the queue_id so the frontend can reference this queue entry.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job      = jobs[job_id]
#     prompts  = job.get("prompts", [])
#     results  = job.get("results", {})

#     if prompt_index < 0 or prompt_index >= len(prompts):
#         raise HTTPException(status_code=400, detail="prompt_index out of range")

#     result = results.get(str(prompt_index), {})
#     if result.get("status") != "completed":
#         raise HTTPException(status_code=400, detail="Video is not completed yet")

#     prompt_text = prompts[prompt_index].get("text", "")
#     video_url   = result.get("video_url", "")
#     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
#     s3_url      = result.get("s3_url", "")

#     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
#     if local_path and local_path.startswith("/videos/"):
#         from pathlib import Path as _Path
#         output_dir = _Path(__file__).parent / "outputs" / "videos"
#         local_path = str(output_dir / _Path(local_path).name)

#     metadata  = _yt.generate_metadata(prompt_text)
#     queue_id  = f"q_{job_id}_{prompt_index}"

#     youtube_queue[queue_id] = {
#         "queue_id":     queue_id,
#         "job_id":       job_id,
#         "prompt_index": prompt_index,
#         "prompt_text":  prompt_text[:120],
#         "local_path":   local_path,
#         "s3_url":       s3_url,
#         "video_url":    video_url,
#         "title":        metadata["title"],
#         "description":  metadata["description"],
#         "tags":         metadata["tags"],
#         "status":       "approved",
#         "youtube_url":  None,
#         "error":        None,
#     }

#     generation_logger.info(
#         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
#     )

#     return youtube_queue[queue_id]


# @app.get("/api/youtube/queue")
# async def get_youtube_queue():
#     """Return all items in the upload queue."""
#     return {"queue": list(youtube_queue.values())}


# @app.patch("/api/youtube/queue/{queue_id}")
# async def update_queue_item(queue_id: str, body: dict):
#     """
#     Update editable metadata for a queued video before upload.
#     Accepts: { title, description, tags }
#     """
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

#     item = youtube_queue[queue_id]
#     if item["status"] not in ("approved", "failed"):
#         raise HTTPException(
#             status_code=400,
#             detail=f"Cannot edit item with status '{item['status']}'"
#         )

#     if "title" in body:
#         item["title"]       = str(body["title"])[:100]
#     if "description" in body:
#         item["description"] = str(body["description"])[:5000]
#     if "tags" in body and isinstance(body["tags"], list):
#         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

#     return item


# @app.post("/api/youtube/upload")
# async def upload_to_youtube(background_tasks: BackgroundTasks):
#     """
#     Upload ALL approved queue items to YouTube.

#     Runs in background — returns immediately.
#     Poll /api/youtube/queue to track per-item status.
#     """
#     approved = [
#         item for item in youtube_queue.values()
#         if item["status"] == "approved"
#     ]

#     if not approved:
#         raise HTTPException(status_code=400, detail="No approved videos in queue")

#     if not _yt.is_configured():
#         raise HTTPException(
#             status_code=503,
#             detail="YouTube not configured — youtube_client_secrets.json missing"
#         )

#     async def _upload_all():
#         for item in approved:
#             qid = item["queue_id"]
#             youtube_queue[qid]["status"] = "uploading"
#             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

#             result = await asyncio.get_event_loop().run_in_executor(
#                 None,
#                 lambda i=item: _yt.upload_video(
#                     local_path  = i["local_path"],
#                     title       = i["title"],
#                     description = i["description"],
#                     tags        = i["tags"],
#                     privacy     = "public",
#                 ),
#             )

#             if result["status"] == "uploaded":
#                 youtube_queue[qid]["status"]      = "uploaded"
#                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
#                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
#                 generation_logger.info(
#                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
#                 )
#             else:
#                 youtube_queue[qid]["status"] = "failed"
#                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
#                 generation_logger.error(
#                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
#                 )

#     background_tasks.add_task(_upload_all)

#     return {
#         "status":  "started",
#         "count":   len(approved),
#         "message": f"Uploading {len(approved)} video(s) to YouTube",
#     }


# @app.delete("/api/youtube/queue/{queue_id}")
# async def remove_from_queue(queue_id: str):
#     """Remove an item from the upload queue (before it's uploaded)."""
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
#     if youtube_queue[queue_id]["status"] == "uploading":
#         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
#     del youtube_queue[queue_id]
#     return {"status": "removed", "queue_id": queue_id}


# # ── Entry point ───────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     s = logging.getLogger("STARTUP")
#     s.info("=" * 70)
#     s.info("Veo Video Generation Platform v1.0.0")
#     s.info("=" * 70)
#     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
#     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
#     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
#     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
#     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     s.info("Endpoints:")
#     s.info("   API    : http://localhost:8100")
#     s.info("   Docs   : http://localhost:8100/docs")
#     s.info("   Health : http://localhost:8100/health")
#     s.info("=" * 70)

#     uvicorn.run(
#         "veo_main:app",
#         host      = "0.0.0.0",
#         port      = 8100,
#         reload    = True,
#         log_level = "info",
#     )























# #!/usr/bin/env python3
# """
# veo_main.py — Veo Video Generation Platform
# ════════════════════════════════════════════

# Standalone FastAPI service. Accepts Excel uploads, generates videos via
# Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# via FFmpeg, and serves results as downloadable MP4 files.

# Veo 3.1 generates video and audio natively from the text prompt — no
# post-processing or external audio service is required.

# Endpoints:
#   GET  /health                → system status
#   POST /api/upload            → accept .xlsx/.csv, start background job
#   GET  /api/jobs              → list all jobs
#   GET  /api/jobs/{job_id}     → job details + per-prompt results
#   GET  /videos/{filename}     → serve generated MP4 files

# Run:
#   python veo_main.py
#   -> http://localhost:8100
#   -> http://localhost:8100/docs

# Port 8100 avoids collision with the Nova/Runway service on 8000.
# """

# import asyncio
# import logging
# import os
# import sys
# import time
# import uuid
# from datetime import datetime
# from pathlib import Path
# from typing import Any, Dict

# import uvicorn
# from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level   = logging.INFO,
#     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
#     datefmt = "%Y-%m-%d %H:%M:%S",
# )
# main_logger       = logging.getLogger("MAIN")
# upload_logger     = logging.getLogger("UPLOAD")
# generation_logger = logging.getLogger("GENERATION")
# progress_logger   = logging.getLogger("PROGRESS")
# job_logger        = logging.getLogger("JOB_MANAGER")
# health_logger     = logging.getLogger("HEALTH")

# # ── Local imports ─────────────────────────────────────────────────────────────
# _HERE = Path(__file__).resolve().parent
# sys.path.insert(0, str(_HERE))

# try:
#     from veo_config import veo_config as config
#     main_logger.info("OK veo_config loaded")
#     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# except ImportError as e:
#     main_logger.critical(f"[CONFIG_ERROR] {e}")
#     sys.exit(1)

# try:
#     from veo_excel_processor import create_job_from_excel, validate_excel_file
#     main_logger.info("OK veo_excel_processor loaded")
# except ImportError as e:
#     main_logger.critical(f"veo_excel_processor import failed: {e}")
#     sys.exit(1)

# # Directories
# _BASE_DIR  = _HERE
# output_dir = _BASE_DIR / config.OUTPUT_DIR
# temp_dir   = _BASE_DIR / config.TEMP_DIR
# output_dir.mkdir(parents=True, exist_ok=True)
# temp_dir.mkdir(parents=True, exist_ok=True)
# (output_dir / "decompositions").mkdir(exist_ok=True)

# try:
#     from video_stitcher import VideoStitcher
#     from prompt_decomposer import PromptDecomposer

#     video_stitcher = VideoStitcher(
#         output_dir            = output_dir,
#         aws_access_key_id     = "",
#         aws_secret_access_key = "",
#         bucket                = "",
#         region                = "",
#     )
#     prompt_decomposer = PromptDecomposer(
#         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#         region                = config.AWS_DEFAULT_REGION,
#     )
#     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
#     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     main_logger.info(
#         f"   Decomposer : "
#         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
#     )
# except ImportError as e:
#     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
#     sys.exit(1)

# veo_generator = None
# try:
#     from veo_generator import VeoGenerator
#     if config.GOOGLE_API_KEY:
#         veo_generator = VeoGenerator(
#             api_key              = config.GOOGLE_API_KEY,
#             output_dir           = output_dir,
#             model_primary        = config.VEO_MODEL_PRIMARY,
#             model_fallback       = config.VEO_MODEL_FALLBACK,
#             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
#             aspect_ratio         = config.VEO_ASPECT_RATIO,
#             resolution           = config.VEO_RESOLUTION,
#             generate_audio       = config.VEO_GENERATE_AUDIO,
#             sample_count         = config.VEO_SAMPLE_COUNT,
#             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
#             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
#         )
#         main_logger.info("OK VeoGenerator initialised")
#     else:
#         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# except ImportError as e:
#     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# if not veo_generator:
#     main_logger.critical("Cannot start without a Veo generator. Exiting.")
#     sys.exit(1)

# from veo_s3 import VeoS3Client
# veo_s3 = VeoS3Client(
#     bucket = os.getenv("VEO_S3_BUCKET", ""),
#     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# )
# main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# from veo_orchestrator import VeoOrchestrator
# from veo_short_span_orchestrator import ShortSpanOrchestrator
# from veo_short_span_image_orchestrator import ShortSpanImageOrchestrator
# from veo_imagen_generator import ImagenGenerator
# veo_orchestrator = VeoOrchestrator(
#     generator     = veo_generator,
#     stitcher      = video_stitcher,
#     decomposer    = prompt_decomposer,
#     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
#     s3_client     = veo_s3,
# )
# main_logger.info("OK VeoOrchestrator initialised")

# ss_orchestrator = ShortSpanOrchestrator(
#     generator  = veo_generator,
#     stitcher   = video_stitcher,
#     s3_client  = veo_s3,
# )
# main_logger.info("OK ShortSpanOrchestrator initialised")

# # ── Short Span Image orchestrator — same GOOGLE_API_KEY as Veo ───────────────
# _imagen_model = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-001")
# if config.GOOGLE_API_KEY:
#     imagen_generator = ImagenGenerator(
#         api_key    = config.GOOGLE_API_KEY,
#         model_id   = _imagen_model,
#         output_dir = config.VEO_OUTPUT_DIR,
#     )
#     img_orchestrator = ShortSpanImageOrchestrator(
#         imagen_generator = imagen_generator,
#         stitcher         = video_stitcher,
#         s3_client        = veo_s3,
#     )
#     main_logger.info(f"OK ShortSpanImageOrchestrator initialised (model={_imagen_model})")
# else:
#     imagen_generator = None
#     img_orchestrator = None
#     main_logger.warning("GOOGLE_API_KEY not set — Short Span Images disabled")

# # ── Job store ─────────────────────────────────────────────────────────────────
# jobs: Dict[str, Any] = {}

# # ── Per-request user identity ─────────────────────────────────────────────────
# def _request_user(request: Request) -> tuple:
#     """
#     Return (user_id, user_role) from request headers.
#     X-User-Id   — authenticated user email (set by frontend _headers())
#     X-User-Role — role string: admin / editor / viewer
#     Defaults to ("anonymous","viewer") so curl/API docs still work.
#     PRODUCTION: replace with JWT decode.
#     """
#     uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
#     role = request.headers.get("X-User-Role", "viewer").strip().lower()
#     return uid, role

# def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
#     """Admins see all jobs. Others see only their own."""
#     if user_role == "admin":
#         return True
#     return job_data.get("user_id", "anonymous") == user_id

# # ── Live metrics store ────────────────────────────────────────────────────────
# # Updated in real-time by generator and decomposer via push.
# # Resets on server restart — tracks current session only.
# _metrics: Dict[str, Any] = {
#     # Veo API
#     "veo_submissions":      0,   # total API calls attempted
#     "veo_successes":        0,   # successful completions
#     "veo_failures":         0,   # all failures (any error)
#     "veo_rate_limit_hits":  0,   # 429 errors specifically
#     "veo_clips_generated":  0,   # clips that produced a video file
#     "veo_generation_time_s": 0.0, # cumulative generation time

#     # Bedrock decomposer
#     "decomp_nova_calls":       0,
#     "decomp_deepseek_calls":   0,
#     "decomp_deterministic":    0,
#     "decomp_input_tokens":     0,
#     "decomp_output_tokens":    0,

#     # S3
#     "s3_uploads_ok":    0,
#     "s3_uploads_fail":  0,

#     # Session
#     "session_start":    None,   # set on first job
#     "jobs_processed":   0,
# }

# # ── FastAPI ───────────────────────────────────────────────────────────────────
# app = FastAPI(
#     title       = "Veo Video Generation Platform",
#     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
#     version     = "1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
#                          "http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials = True,
#     allow_methods     = ["*"],
#     allow_headers     = ["*"],
# )

# app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # ── Routes ────────────────────────────────────────────────────────────────────

# @app.get("/health")
# async def health_check():
#     health_logger.info("Health check requested")
#     return {
#         "status":    "healthy",
#         "service":   "veo-video-generation-platform",
#         "version":   "1.0.0",
#         "timestamp": datetime.now().isoformat(),
#         "components": {
#             "veo_generator":   True,
#             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
#             "decomposer":      True,
#         },
#         "veo": {
#             "primary_model":  config.VEO_MODEL_PRIMARY,
#             "fallback_model": config.VEO_MODEL_FALLBACK,
#             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
#             "aspect_ratio":   config.VEO_ASPECT_RATIO,
#             "resolution":     config.VEO_RESOLUTION,
#             "native_audio":   True,  # Veo 3.0 always generates audio natively
#         },
#         "decomposer_mode": (
#             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
#         ),
#     }


# @app.get("/api/metrics")
# async def get_metrics():
#     """Real-time generation metrics for the Streamlit dashboard."""
#     import time
#     from datetime import datetime, timezone

#     # Derived metrics
#     total_veo   = _metrics["veo_submissions"]
#     rl_rate     = (
#         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
#         if total_veo > 0 else 0.0
#     )
#     avg_clip_s  = (
#         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
#         if _metrics["veo_clips_generated"] > 0 else 0.0
#     )

#     # Estimated cost (clips × 8s × $0.40 for primary model)
#     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
#     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

#     return {
#         "session_start":        _metrics["session_start"],
#         "jobs_processed":       _metrics["jobs_processed"],

#         "veo": {
#             "submissions":      _metrics["veo_submissions"],
#             "successes":        _metrics["veo_successes"],
#             "failures":         _metrics["veo_failures"],
#             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
#             "rate_limit_pct":   rl_rate,
#             "clips_generated":  _metrics["veo_clips_generated"],
#             "avg_clip_time_s":  avg_clip_s,
#             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
#         },

#         "decomposer": {
#             "nova_calls":        _metrics["decomp_nova_calls"],
#             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
#             "deterministic":     _metrics["decomp_deterministic"],
#             "input_tokens":      _metrics["decomp_input_tokens"],
#             "output_tokens":     _metrics["decomp_output_tokens"],
#             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
#         },

#         "s3": {
#             "uploads_ok":   _metrics["s3_uploads_ok"],
#             "uploads_fail": _metrics["s3_uploads_fail"],
#         },

#         "cost_estimate": {
#             "usd": round(est_cost_usd, 4),
#             "inr": round(est_cost_inr, 2),
#             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
#         },
#     }


# @app.get("/api/jobs")
# async def list_jobs(request: Request):
#     user_id, user_role = _request_user(request)
#     visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
#     job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
#     return {
#         "jobs": [
#             {
#                 "job_id":            job_id,
#                 "original_filename": jd.get("original_filename", ""),
#                 "status":            jd.get("status", "processing"),
#                 "total_prompts":     jd.get("total_prompts", 0),
#                 "completed_prompts": jd.get("completed_prompts", 0),
#                 "failed_prompts":    jd.get("failed_prompts", 0),
#                 "progress_percent":  jd.get("progress_percent", 0.0),
#                 "created_at":        jd.get("created_at", ""),
#                 "generation_status": jd.get("generation_status", "Queued"),
#                 "user_id":           jd.get("user_id", "anonymous"),
#             }
#             for job_id, jd in visible.items()
#         ]
#     }


# @app.get("/api/jobs/{job_id}")
# async def get_job(job_id: str, request: Request):
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     user_id, user_role = _request_user(request)
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied")

#     job_data = jobs[job_id]
#     results  = job_data.get("results", {})

#     prompts_out = []
#     for i, prompt_data in enumerate(job_data.get("prompts", [])):
#         r = results.get(str(i), {})
#         # video_url: may be S3 URL after upload (for distribution)
#         # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
#         raw_video_url = r.get("video_url")
#         raw_local_url = r.get("local_video_url")
#         # Ensure local_video_url is a proper /videos/ route, not an absolute path
#         if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
#             from pathlib import Path as _Path
#             raw_local_url = f"/videos/{_Path(raw_local_url).name}"
#         # If no local URL stored but video_url is already a local route, use it
#         if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
#             raw_local_url = raw_video_url
#         prompts_out.append({
#             "prompt_id":        f"prompt_{i + 1}",
#             "prompt_text":      prompt_data.get("text", ""),
#             "row_number":       i + 1,
#             "duration":         prompt_data.get("duration", 8),
#             "status":           r.get("status", "processing"),
#             "video_url":        raw_video_url,    # S3 or local route
#             "local_video_url":  raw_local_url,    # always /videos/... for player
#             "duration_seconds": r.get("duration_seconds"),
#             "stitched":         r.get("stitched", False),
#             "clips_count":      r.get("clips_count", 0),
#             "clip_urls":        r.get("clip_urls", []),
#             "model_used":       r.get("model_used", ""),
#             "has_native_audio": r.get("has_native_audio", False),
#             "error_message":    r.get("error_message"),
#             "generation_time_seconds": r.get("generation_time_seconds"),
#         })

#     return {
#         "job_id":       job_id,
#         "status":       job_data.get("status", "processing"),
#         "mode":         job_data.get("mode", "full"),
#         "hold_duration":job_data.get("hold_duration", 5.0),
#         "clip_duration":job_data.get("clip_duration", 8),
#         "no_text":      job_data.get("no_text", False),
#         "no_speech":    job_data.get("no_speech", False),
#         "summary": {
#             "job_id":            job_id,
#             "original_filename": job_data.get("original_filename", ""),
#             "status":            job_data.get("status", "processing"),
#             "total_prompts":     job_data.get("total_prompts", 0),
#             "completed_prompts": job_data.get("completed_prompts", 0),
#             "failed_prompts":    job_data.get("failed_prompts", 0),
#             "progress_percent":  job_data.get("progress_percent", 0.0),
#             "total_processing_time": job_data.get("total_processing_time"),
#         },
#         "prompts": prompts_out,
#     }


# @app.post("/api/upload")
# async def upload_excel(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(...),
#     mode: str = "full",           # "full" | "short_span" | "short_span_image"
#     clip_duration: float = 2.0,   # short_span only: seconds per clip (2–8)
#     hold_duration: float = 5.0,   # short_span_image only: seconds per image (2 or 5)
#     no_text: bool = False,        # inject no-text guardrail into all prompts
#     no_speech: bool = False,      # inject no-speech guardrail into all prompts
# ):
#     """
#     Accept an Excel/CSV file and start Veo generation as a background job.

#     Required Excel columns:  prompt, duration
#     Optional Excel columns:  task_type, priority
#     """
#     upload_id = str(uuid.uuid4())[:8]
#     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

#     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     is_valid, errors = validate_excel_file(str(temp_path))
#     if not is_valid:
#         temp_path.unlink(missing_ok=True)
#         raise HTTPException(
#             status_code=400,
#             detail=f"Excel validation failed: {'; '.join(errors)}",
#         )

#     job_data = create_job_from_excel(
#         file_path  = str(temp_path),
#         platforms  = ["veo"],
#         audio_mode = "platform_native",   # unused — Veo owns its audio
#     )
#     job_id = job_data["job_id"]

#     user_id, user_role = _request_user(request)

#     jobs[job_id]                      = job_data
#     jobs[job_id]["temp_file"]         = str(temp_path)
#     jobs[job_id]["upload_id"]         = upload_id
#     jobs[job_id]["original_filename"] = file.filename
#     jobs[job_id]["user_id"]           = user_id
#     jobs[job_id]["mode"]              = mode
#     jobs[job_id]["clip_duration"]     = clip_duration
#     jobs[job_id]["hold_duration"]     = hold_duration
#     jobs[job_id]["no_text"]           = no_text
#     jobs[job_id]["no_speech"]         = no_speech

#     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

#     background_tasks.add_task(run_generation_job, job_id)

#     return {
#         "success":       True,
#         "job_id":        job_id,
#         "upload_id":     upload_id,
#         "prompts_count": job_data["total_prompts"],
#         "veo_model":     config.VEO_MODEL_PRIMARY,
#         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
#         "native_audio":  True,  # Veo 3.0 always generates audio natively
#         "stitching":     video_stitcher.ffmpeg_available,
#         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
#     }


# # ── Concurrency config ────────────────────────────────────────────────────────

# # Max prompts running simultaneously within one job.
# # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # Each prompt with 4 clips = 4 sequential API calls.
# # At concurrency=2, clip submissions from two prompts can overlap
# # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # on the free tier. Increase if you have a paid quota.
# _PROMPT_CONCURRENCY = 1


# # ── Background generation job ─────────────────────────────────────────────────

# async def run_generation_job(job_id: str) -> None:
#     """
#     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

#     Design:
#     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
#     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
#     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
#     - Results are stored by index key str(i) — API schema unchanged.
#     - Progress percent is updated after each prompt completes (order-independent).
#     """
#     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
#     start_time   = time.time()

#     # Track session start on first job
#     if _metrics["session_start"] is None:
#         from datetime import datetime, timezone
#         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
#     _metrics["jobs_processed"] += 1
#     job          = jobs[job_id]
#     prompts_data = job["prompts"]
#     total        = len(prompts_data)

#     jobs[job_id]["results"]            = {}
#     jobs[job_id]["completed_prompts"]  = 0
#     jobs[job_id]["failed_prompts"]     = 0
#     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

#     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
#     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

#     async def _run_prompt(i: int, prompt_data: dict) -> None:
#         """
#         Semaphore-gated coroutine for a single prompt.
#         Clips within this prompt run sequentially inside generate_for_prompt().
#         """
#         prompt_text = prompt_data["text"]
#         duration    = prompt_data["duration"]

#         async with semaphore:
#             if job_id not in jobs:
#                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
#                 return

#             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
#             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
#             prompt_start = time.time()

#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = i,
#             )

#             elapsed = time.time() - prompt_start

#         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
#         async with state_lock:
#             jobs[job_id]["results"][str(i)] = result

#             # ── Push result stats into live metrics ───────────────────────────
#             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
#             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
#             # Decomposer token tracking
#             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
#             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
#             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
#             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
#             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
#             # S3 tracking
#             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
#             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

#             if result.get("status") in ("completed", "partial"):
#                 jobs[job_id]["completed_prompts"] += 1
#                 _metrics["veo_successes"]       += 1
#                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
#                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
#                 generation_logger.info(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
#                     f"-> {result.get('video_url')} "
#                     f"({'stitched' if result.get('stitched') else 'single'}, "
#                     f"{result.get('clips_count', 1)} clip(s))"
#                 )
#                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
#             else:
#                 jobs[job_id]["failed_prompts"] += 1
#                 _metrics["veo_failures"] += 1
#                 generation_logger.error(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
#                     f"{result.get('error_message')}"
#                 )

#             done_so_far = (
#                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
#             )
#             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
#             jobs[job_id]["generation_status"]  = (
#                 f"Running — {done_so_far}/{total} complete"
#             )

#     # ── Launch based on mode ──────────────────────────────────────────────────
#     mode         = job.get("mode", "full")
#     no_text      = job.get("no_text", False)
#     no_speech    = job.get("no_speech", False)
#     clip_dur     = job.get("clip_duration", 2.0)

#     if mode == "short_span":
#         # ── Short Span Clips: all rows = one sequence, no decomposition ───────
#         # Inject guardrails into prompt text before passing to orchestrator
#         _NO_TEXT_G = (
#             "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#             "subtitles, watermarks, or UI labels anywhere in the frame."
#         )
#         _NO_SPEECH_G = (
#             "NO SPEECH: No person should be speaking or moving their lips. "
#             "No narration or dialogue. Ambient background sound only."
#         )
#         enriched = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:   parts.append(_NO_TEXT_G)
#             if no_speech: parts.append(_NO_SPEECH_G)
#             parts.append(pd.get("text", ""))
#             enriched.append({**pd, "text": " ".join(parts)})

#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN mode — {len(enriched)} clip(s) "
#             f"at {clip_dur}s each, no_text={no_text}, no_speech={no_speech}"
#         )
#         result = await ss_orchestrator.run(
#             prompts         = enriched,
#             job_id          = job_id,
#             clip_duration_s = clip_dur,
#             no_text         = False,
#             no_speech       = False,
#         )
#         # Store as single result at index 0 and mark job done
#         async with state_lock:
#             jobs[job_id]["results"]["0"]          = result
#             jobs[job_id]["completed_prompts"]     = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]        = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]      = 100.0
#             jobs[job_id]["generation_status"]     = "All prompts processed"
#             _metrics["veo_clips_generated"]      += result.get("clips_count", 0)
#             _metrics["veo_generation_time_s"]    += result.get("generation_time_seconds", 0) or 0
#             if result.get("status") in ("completed", "partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"] += 1

#     elif mode == "short_span_image":
#         if img_orchestrator is None:
#             generation_logger.error(f"[JOB_{job_id}] Short Span Images: GOOGLE_API_KEY not set")
#             async with state_lock:
#                 jobs[job_id]["status"] = "failed"
#                 jobs[job_id]["generation_status"] = "GOOGLE_API_KEY missing"
#                 jobs[job_id]["progress_percent"] = 100.0
#             return
#         hold_dur     = job.get("hold_duration", 5.0)
#         aspect_ratio = job.get("aspect_ratio", "9:16")
#         enriched_imgs = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:
#                 parts.append("No text, captions, titles, watermarks, or labels in the image.")
#             parts.append(pd.get("text", ""))
#             enriched_imgs.append({**pd, "text": " ".join(parts)})
#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN_IMAGE — {len(enriched_imgs)} images at {hold_dur}s"
#         )
#         result = await img_orchestrator.run(
#             prompts         = enriched_imgs,
#             job_id          = job_id,
#             hold_duration_s = hold_dur,
#             aspect_ratio    = aspect_ratio,
#             no_text         = False,
#         )
#         async with state_lock:
#             jobs[job_id]["results"]["0"]      = result
#             jobs[job_id]["completed_prompts"] = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]    = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]  = 100.0
#             jobs[job_id]["generation_status"] = "All images processed"
#             if result.get("status") in ("completed","partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"]  += 1

#     else:
#         # ── Full Length Videos (existing pipeline) ────────────────────────────
#         # Inject no_text/no_speech guardrails into prompt text if requested
#         if no_text or no_speech:
#             _NO_TEXT_G = (
#                 "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#                 "subtitles, watermarks, or UI labels anywhere in the frame."
#             )
#             _NO_SPEECH_G = (
#                 "NO SPEECH: No person should be speaking or moving their lips. "
#                 "No narration or dialogue. Ambient background sound only."
#             )
#             for pd in prompts_data:
#                 parts = []
#                 if no_text:   parts.append(_NO_TEXT_G)
#                 if no_speech: parts.append(_NO_SPEECH_G)
#                 parts.append(pd.get("text", ""))
#                 pd["text"] = " ".join(parts)

#         tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
#         await asyncio.gather(*tasks, return_exceptions=True)

#     # ── Finalise ──────────────────────────────────────────────────────────────
#     total_elapsed = time.time() - start_time
#     failed_count  = jobs[job_id].get("failed_prompts", 0)

#     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
#     jobs[job_id]["generation_status"]     = "All prompts processed"
#     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

#     generation_logger.info(
#         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
#         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
#     )

#     try:
#         temp_file = jobs[job_id].get("temp_file")
#         if temp_file:
#             Path(temp_file).unlink(missing_ok=True)
#     except Exception as e:
#         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # ── Rerun single prompt ───────────────────────────────────────────────────────

# @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
#     """
#     Re-run a single prompt within an existing job.

#     Flow:
#     - Validates job and prompt exist
#     - Marks the result as "processing" immediately (UI picks this up on next poll)
#     - Schedules a background task that calls the orchestrator for just that one prompt
#     - Returns immediately so the UI is never blocked

#     Used by: rerun button on each video card in the frontend.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job = jobs[job_id]
#     prompts_data = job.get("prompts", [])

#     if prompt_index < 0 or prompt_index >= len(prompts_data):
#         raise HTTPException(
#             status_code=400,
#             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
#         )

#     prompt_data = prompts_data[prompt_index]

#     # Mark as processing immediately so frontend shows skeleton
#     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
#         "status": "processing",
#         "video_url": None,
#     }
#     # Reset counters to reflect the rerun
#     jobs[job_id]["status"] = "processing"

#     generation_logger.info(
#         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
#         f"'{prompt_data.get('text', '')[:60]}...'"
#     )

#     async def _rerun():
#         try:
#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = prompt_index,
#             )
#             jobs[job_id]["results"][str(prompt_index)] = result

#             # Recompute job-level status from all results
#             all_results = jobs[job_id].get("results", {})
#             total = len(prompts_data)
#             completed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") in ("completed", "partial")
#             )
#             failed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "failed"
#             )
#             processing = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "processing"
#             )

#             if processing == 0:
#                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
#                 jobs[job_id]["completed_prompts"] = completed
#                 jobs[job_id]["failed_prompts"]    = failed
#                 jobs[job_id]["progress_percent"]  = 100.0

#             generation_logger.info(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
#                 f"status={result.get('status')}"
#             )
#         except Exception as e:
#             jobs[job_id]["results"][str(prompt_index)] = {
#                 "status": "failed",
#                 "error_message": str(e),
#             }
#             generation_logger.error(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
#             )

#     # Soft-delete the old S3 video before rerunning
#     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
#     if veo_s3.enabled:
#         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
#         if moved:
#             generation_logger.info(
#                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
#             )
#         else:
#             generation_logger.warning(
#                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
#             )

#     background_tasks.add_task(_rerun)

#     return {
#         "status":        "accepted",
#         "job_id":        job_id,
#         "prompt_index":  prompt_index,
#         "message":       f"Rerun started for prompt {prompt_index + 1}",
#     }


# # ── YouTube upload queue ──────────────────────────────────────────────────────
# # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# #                                tags, local_path, s3_url, status, youtube_url } }
# # "approved" = waiting to upload, "uploading" = in progress,
# # "uploaded" = done, "failed" = error
# youtube_queue: Dict[str, Any] = {}


# import veo_youtube as _yt


# @app.get("/api/youtube/status")
# async def youtube_status():
#     """Check if YouTube is configured and authenticated."""
#     return {
#         "configured":    _yt.is_configured(),
#         "authenticated": _yt.is_authenticated(),
#         "secrets_file":  str(_yt.SECRETS_FILE),
#     }


# @app.post("/api/youtube/auth")
# async def youtube_auth():
#     """
#     Trigger the OAuth browser flow.
#     Opens a browser tab — user logs in, approves, token is saved.
#     Returns immediately after auth completes.
#     """
#     try:
#         _yt.get_authenticated_service()
#         return {"status": "authenticated"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# async def approve_video(job_id: str, prompt_index: int, request: Request):
#     """
#     Approve a completed video — adds it to the YouTube upload queue.

#     Auto-generates title/description/tags from the prompt.
#     User edits these in the UI before triggering upload.

#     Returns the queue_id so the frontend can reference this queue entry.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job      = jobs[job_id]
#     prompts  = job.get("prompts", [])
#     results  = job.get("results", {})

#     if prompt_index < 0 or prompt_index >= len(prompts):
#         raise HTTPException(status_code=400, detail="prompt_index out of range")

#     result = results.get(str(prompt_index), {})
#     if result.get("status") != "completed":
#         raise HTTPException(status_code=400, detail="Video is not completed yet")

#     prompt_text = prompts[prompt_index].get("text", "")
#     video_url   = result.get("video_url", "")
#     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
#     s3_url      = result.get("s3_url", "")

#     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
#     if local_path and local_path.startswith("/videos/"):
#         from pathlib import Path as _Path
#         output_dir = _Path(__file__).parent / "outputs" / "videos"
#         local_path = str(output_dir / _Path(local_path).name)

#     metadata  = _yt.generate_metadata(prompt_text)
#     queue_id  = f"q_{job_id}_{prompt_index}"

#     youtube_queue[queue_id] = {
#         "queue_id":     queue_id,
#         "job_id":       job_id,
#         "prompt_index": prompt_index,
#         "prompt_text":  prompt_text[:120],
#         "local_path":   local_path,
#         "s3_url":       s3_url,
#         "video_url":    video_url,
#         "title":        metadata["title"],
#         "description":  metadata["description"],
#         "tags":         metadata["tags"],
#         "status":       "approved",
#         "youtube_url":  None,
#         "error":        None,
#     }

#     generation_logger.info(
#         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
#     )

#     return youtube_queue[queue_id]


# @app.get("/api/youtube/queue")
# async def get_youtube_queue():
#     """Return all items in the upload queue."""
#     return {"queue": list(youtube_queue.values())}


# @app.patch("/api/youtube/queue/{queue_id}")
# async def update_queue_item(queue_id: str, body: dict):
#     """
#     Update editable metadata for a queued video before upload.
#     Accepts: { title, description, tags }
#     """
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

#     item = youtube_queue[queue_id]
#     if item["status"] not in ("approved", "failed"):
#         raise HTTPException(
#             status_code=400,
#             detail=f"Cannot edit item with status '{item['status']}'"
#         )

#     if "title" in body:
#         item["title"]       = str(body["title"])[:100]
#     if "description" in body:
#         item["description"] = str(body["description"])[:5000]
#     if "tags" in body and isinstance(body["tags"], list):
#         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

#     return item


# @app.post("/api/youtube/upload")
# async def upload_to_youtube(background_tasks: BackgroundTasks):
#     """
#     Upload ALL approved queue items to YouTube.

#     Runs in background — returns immediately.
#     Poll /api/youtube/queue to track per-item status.
#     """
#     approved = [
#         item for item in youtube_queue.values()
#         if item["status"] == "approved"
#     ]

#     if not approved:
#         raise HTTPException(status_code=400, detail="No approved videos in queue")

#     if not _yt.is_configured():
#         raise HTTPException(
#             status_code=503,
#             detail="YouTube not configured — youtube_client_secrets.json missing"
#         )

#     async def _upload_all():
#         for item in approved:
#             qid = item["queue_id"]
#             youtube_queue[qid]["status"] = "uploading"
#             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

#             result = await asyncio.get_event_loop().run_in_executor(
#                 None,
#                 lambda i=item: _yt.upload_video(
#                     local_path  = i["local_path"],
#                     title       = i["title"],
#                     description = i["description"],
#                     tags        = i["tags"],
#                     privacy     = "public",
#                 ),
#             )

#             if result["status"] == "uploaded":
#                 youtube_queue[qid]["status"]      = "uploaded"
#                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
#                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
#                 generation_logger.info(
#                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
#                 )
#             else:
#                 youtube_queue[qid]["status"] = "failed"
#                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
#                 generation_logger.error(
#                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
#                 )

#     background_tasks.add_task(_upload_all)

#     return {
#         "status":  "started",
#         "count":   len(approved),
#         "message": f"Uploading {len(approved)} video(s) to YouTube",
#     }


# @app.delete("/api/youtube/queue/{queue_id}")
# async def remove_from_queue(queue_id: str):
#     """Remove an item from the upload queue (before it's uploaded)."""
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
#     if youtube_queue[queue_id]["status"] == "uploading":
#         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
#     del youtube_queue[queue_id]
#     return {"status": "removed", "queue_id": queue_id}


# # ── Entry point ───────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     s = logging.getLogger("STARTUP")
#     s.info("=" * 70)
#     s.info("Veo Video Generation Platform v1.0.0")
#     s.info("=" * 70)
#     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
#     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
#     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
#     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
#     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     s.info("Endpoints:")
#     s.info("   API    : http://localhost:8100")
#     s.info("   Docs   : http://localhost:8100/docs")
#     s.info("   Health : http://localhost:8100/health")
#     s.info("=" * 70)

#     uvicorn.run(
#         "veo_main:app",
#         host      = "0.0.0.0",
#         port      = 8100,
#         reload    = True,
#         log_level = "info",
#     )














# #!/usr/bin/env python3
# """
# veo_main.py — Veo Video Generation Platform
# ════════════════════════════════════════════

# Standalone FastAPI service. Accepts Excel uploads, generates videos via
# Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# via FFmpeg, and serves results as downloadable MP4 files.

# Veo 3.1 generates video and audio natively from the text prompt — no
# post-processing or external audio service is required.

# Endpoints:
#   GET  /health                → system status
#   POST /api/upload            → accept .xlsx/.csv, start background job
#   GET  /api/jobs              → list all jobs
#   GET  /api/jobs/{job_id}     → job details + per-prompt results
#   GET  /videos/{filename}     → serve generated MP4 files

# Run:
#   python veo_main.py
#   -> http://localhost:8100
#   -> http://localhost:8100/docs

# Port 8100 avoids collision with the Nova/Runway service on 8000.
# """

# import asyncio
# import logging
# import os
# import sys
# import time
# import uuid
# from datetime import datetime
# from pathlib import Path
# from typing import Any, Dict

# import uvicorn
# from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level   = logging.INFO,
#     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
#     datefmt = "%Y-%m-%d %H:%M:%S",
# )
# main_logger       = logging.getLogger("MAIN")
# upload_logger     = logging.getLogger("UPLOAD")
# generation_logger = logging.getLogger("GENERATION")
# progress_logger   = logging.getLogger("PROGRESS")
# job_logger        = logging.getLogger("JOB_MANAGER")
# health_logger     = logging.getLogger("HEALTH")

# # ── Local imports ─────────────────────────────────────────────────────────────
# _HERE = Path(__file__).resolve().parent
# sys.path.insert(0, str(_HERE))

# try:
#     from veo_config import veo_config as config
#     main_logger.info("OK veo_config loaded")
#     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# except ImportError as e:
#     main_logger.critical(f"[CONFIG_ERROR] {e}")
#     sys.exit(1)

# try:
#     from veo_excel_processor import create_job_from_excel, validate_excel_file
#     main_logger.info("OK veo_excel_processor loaded")
# except ImportError as e:
#     main_logger.critical(f"veo_excel_processor import failed: {e}")
#     sys.exit(1)

# # Directories
# _BASE_DIR  = _HERE
# output_dir = _BASE_DIR / config.OUTPUT_DIR
# temp_dir   = _BASE_DIR / config.TEMP_DIR
# output_dir.mkdir(parents=True, exist_ok=True)
# temp_dir.mkdir(parents=True, exist_ok=True)
# (output_dir / "decompositions").mkdir(exist_ok=True)

# try:
#     from video_stitcher import VideoStitcher
#     from prompt_decomposer import PromptDecomposer

#     video_stitcher = VideoStitcher(
#         output_dir            = output_dir,
#         aws_access_key_id     = "",
#         aws_secret_access_key = "",
#         bucket                = "",
#         region                = "",
#     )
#     prompt_decomposer = PromptDecomposer(
#         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#         region                = config.AWS_DEFAULT_REGION,
#     )
#     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
#     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     main_logger.info(
#         f"   Decomposer : "
#         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
#     )
# except ImportError as e:
#     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
#     sys.exit(1)

# veo_generator = None
# try:
#     from veo_generator import VeoGenerator
#     if config.GOOGLE_API_KEY:
#         veo_generator = VeoGenerator(
#             api_key              = config.GOOGLE_API_KEY,
#             output_dir           = output_dir,
#             model_primary        = config.VEO_MODEL_PRIMARY,
#             model_fallback       = config.VEO_MODEL_FALLBACK,
#             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
#             aspect_ratio         = config.VEO_ASPECT_RATIO,
#             resolution           = config.VEO_RESOLUTION,
#             generate_audio       = config.VEO_GENERATE_AUDIO,
#             sample_count         = config.VEO_SAMPLE_COUNT,
#             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
#             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
#         )
#         main_logger.info("OK VeoGenerator initialised")
#     else:
#         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# except ImportError as e:
#     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# if not veo_generator:
#     main_logger.critical("Cannot start without a Veo generator. Exiting.")
#     sys.exit(1)

# from veo_s3 import VeoS3Client
# veo_s3 = VeoS3Client(
#     bucket = os.getenv("VEO_S3_BUCKET", ""),
#     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# )
# main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# from veo_orchestrator import VeoOrchestrator
# from veo_short_span_orchestrator import ShortSpanOrchestrator
# try:
#     from veo_short_span_image_orchestrator import ShortSpanImageOrchestrator
#     from veo_imagen_generator import ImagenGenerator
#     _IMAGEN_AVAILABLE = True
# except ImportError:
#     ShortSpanImageOrchestrator = None  # type: ignore
#     ImagenGenerator = None             # type: ignore
#     _IMAGEN_AVAILABLE = False
# veo_orchestrator = VeoOrchestrator(
#     generator     = veo_generator,
#     stitcher      = video_stitcher,
#     decomposer    = prompt_decomposer,
#     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
#     s3_client     = veo_s3,
# )
# main_logger.info("OK VeoOrchestrator initialised")

# ss_orchestrator = ShortSpanOrchestrator(
#     generator  = veo_generator,
#     stitcher   = video_stitcher,
#     s3_client  = veo_s3,
# )
# main_logger.info("OK ShortSpanOrchestrator initialised")

# # ── Short Span Image orchestrator — same GOOGLE_API_KEY as Veo ───────────────
# _imagen_model = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-001")
# if _IMAGEN_AVAILABLE and config.GOOGLE_API_KEY:
#     imagen_generator = ImagenGenerator(
#         api_key    = config.GOOGLE_API_KEY,
#         model_id   = _imagen_model,
#         output_dir = config.OUTPUT_DIR,
#     )
#     img_orchestrator = ShortSpanImageOrchestrator(
#         imagen_generator = imagen_generator,
#         stitcher         = video_stitcher,
#         s3_client        = veo_s3,
#     )
#     main_logger.info(f"OK ShortSpanImageOrchestrator initialised (model={_imagen_model})")
# else:
#     imagen_generator = None
#     img_orchestrator = None
#     if not _IMAGEN_AVAILABLE:
#         main_logger.warning(
#             "veo_imagen_generator / veo_short_span_image_orchestrator not found — "
#             "Short Span Images disabled. Copy both files to the veo/ folder to enable."
#         )
#     else:
#         main_logger.warning("GOOGLE_API_KEY not set — Short Span Images disabled")

# # ── Job store ─────────────────────────────────────────────────────────────────
# jobs: Dict[str, Any] = {}

# # ── Per-request user identity ─────────────────────────────────────────────────
# def _request_user(request: Request) -> tuple:
#     """
#     Return (user_id, user_role) from request headers.
#     X-User-Id   — authenticated user email (set by frontend _headers())
#     X-User-Role — role string: admin / editor / viewer
#     Defaults to ("anonymous","viewer") so curl/API docs still work.
#     PRODUCTION: replace with JWT decode.
#     """
#     uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
#     role = request.headers.get("X-User-Role", "viewer").strip().lower()
#     return uid, role

# def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
#     """Admins see all jobs. Others see only their own."""
#     if user_role == "admin":
#         return True
#     return job_data.get("user_id", "anonymous") == user_id

# # ── Live metrics store ────────────────────────────────────────────────────────
# # Updated in real-time by generator and decomposer via push.
# # Resets on server restart — tracks current session only.
# _metrics: Dict[str, Any] = {
#     # Veo API
#     "veo_submissions":      0,   # total API calls attempted
#     "veo_successes":        0,   # successful completions
#     "veo_failures":         0,   # all failures (any error)
#     "veo_rate_limit_hits":  0,   # 429 errors specifically
#     "veo_clips_generated":  0,   # clips that produced a video file
#     "veo_generation_time_s": 0.0, # cumulative generation time

#     # Bedrock decomposer
#     "decomp_nova_calls":       0,
#     "decomp_deepseek_calls":   0,
#     "decomp_deterministic":    0,
#     "decomp_input_tokens":     0,
#     "decomp_output_tokens":    0,

#     # S3
#     "s3_uploads_ok":    0,
#     "s3_uploads_fail":  0,

#     # Session
#     "session_start":    None,   # set on first job
#     "jobs_processed":   0,
# }

# # ── FastAPI ───────────────────────────────────────────────────────────────────
# app = FastAPI(
#     title       = "Veo Video Generation Platform",
#     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
#     version     = "1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
#                          "http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials = True,
#     allow_methods     = ["*"],
#     allow_headers     = ["*"],
# )

# app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # ── Routes ────────────────────────────────────────────────────────────────────

# @app.get("/health")
# async def health_check():
#     health_logger.info("Health check requested")
#     return {
#         "status":    "healthy",
#         "service":   "veo-video-generation-platform",
#         "version":   "1.0.0",
#         "timestamp": datetime.now().isoformat(),
#         "components": {
#             "veo_generator":   True,
#             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
#             "decomposer":      True,
#         },
#         "veo": {
#             "primary_model":  config.VEO_MODEL_PRIMARY,
#             "fallback_model": config.VEO_MODEL_FALLBACK,
#             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
#             "aspect_ratio":   config.VEO_ASPECT_RATIO,
#             "resolution":     config.VEO_RESOLUTION,
#             "native_audio":   True,  # Veo 3.0 always generates audio natively
#         },
#         "decomposer_mode": (
#             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
#         ),
#     }


# @app.get("/api/metrics")
# async def get_metrics():
#     """Real-time generation metrics for the Streamlit dashboard."""
#     import time
#     from datetime import datetime, timezone

#     # Derived metrics
#     total_veo   = _metrics["veo_submissions"]
#     rl_rate     = (
#         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
#         if total_veo > 0 else 0.0
#     )
#     avg_clip_s  = (
#         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
#         if _metrics["veo_clips_generated"] > 0 else 0.0
#     )

#     # Estimated cost (clips × 8s × $0.40 for primary model)
#     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
#     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

#     return {
#         "session_start":        _metrics["session_start"],
#         "jobs_processed":       _metrics["jobs_processed"],

#         "veo": {
#             "submissions":      _metrics["veo_submissions"],
#             "successes":        _metrics["veo_successes"],
#             "failures":         _metrics["veo_failures"],
#             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
#             "rate_limit_pct":   rl_rate,
#             "clips_generated":  _metrics["veo_clips_generated"],
#             "avg_clip_time_s":  avg_clip_s,
#             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
#         },

#         "decomposer": {
#             "nova_calls":        _metrics["decomp_nova_calls"],
#             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
#             "deterministic":     _metrics["decomp_deterministic"],
#             "input_tokens":      _metrics["decomp_input_tokens"],
#             "output_tokens":     _metrics["decomp_output_tokens"],
#             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
#         },

#         "s3": {
#             "uploads_ok":   _metrics["s3_uploads_ok"],
#             "uploads_fail": _metrics["s3_uploads_fail"],
#         },

#         "cost_estimate": {
#             "usd": round(est_cost_usd, 4),
#             "inr": round(est_cost_inr, 2),
#             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
#         },
#     }


# @app.get("/api/jobs")
# async def list_jobs(request: Request):
#     user_id, user_role = _request_user(request)
#     visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
#     job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
#     return {
#         "jobs": [
#             {
#                 "job_id":            job_id,
#                 "original_filename": jd.get("original_filename", ""),
#                 "status":            jd.get("status", "processing"),
#                 "total_prompts":     jd.get("total_prompts", 0),
#                 "completed_prompts": jd.get("completed_prompts", 0),
#                 "failed_prompts":    jd.get("failed_prompts", 0),
#                 "progress_percent":  jd.get("progress_percent", 0.0),
#                 "created_at":        jd.get("created_at", ""),
#                 "generation_status": jd.get("generation_status", "Queued"),
#                 "user_id":           jd.get("user_id", "anonymous"),
#             }
#             for job_id, jd in visible.items()
#         ]
#     }


# @app.get("/api/jobs/{job_id}")
# async def get_job(job_id: str, request: Request):
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     user_id, user_role = _request_user(request)
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied")

#     job_data = jobs[job_id]
#     results  = job_data.get("results", {})

#     prompts_out = []
#     for i, prompt_data in enumerate(job_data.get("prompts", [])):
#         r = results.get(str(i), {})
#         # video_url: may be S3 URL after upload (for distribution)
#         # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
#         raw_video_url = r.get("video_url")
#         raw_local_url = r.get("local_video_url")
#         # Ensure local_video_url is a proper /videos/ route, not an absolute path
#         if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
#             from pathlib import Path as _Path
#             raw_local_url = f"/videos/{_Path(raw_local_url).name}"
#         # If no local URL stored but video_url is already a local route, use it
#         if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
#             raw_local_url = raw_video_url
#         prompts_out.append({
#             "prompt_id":        f"prompt_{i + 1}",
#             "prompt_text":      prompt_data.get("text", ""),
#             "row_number":       i + 1,
#             "duration":         prompt_data.get("duration", 8),
#             "status":           r.get("status", "processing"),
#             "video_url":        raw_video_url,    # S3 or local route
#             "local_video_url":  raw_local_url,    # always /videos/... for player
#             "duration_seconds": r.get("duration_seconds"),
#             "stitched":         r.get("stitched", False),
#             "clips_count":      r.get("clips_count", 0),
#             "clip_urls":        r.get("clip_urls", []),
#             "model_used":       r.get("model_used", ""),
#             "has_native_audio": r.get("has_native_audio", False),
#             "error_message":    r.get("error_message"),
#             "generation_time_seconds": r.get("generation_time_seconds"),
#         })

#     return {
#         "job_id":       job_id,
#         "status":       job_data.get("status", "processing"),
#         "mode":         job_data.get("mode", "full"),
#         "hold_duration":job_data.get("hold_duration", 5.0),
#         "clip_duration":job_data.get("clip_duration", 8),
#         "no_text":      job_data.get("no_text", False),
#         "no_speech":    job_data.get("no_speech", False),
#         "summary": {
#             "job_id":            job_id,
#             "original_filename": job_data.get("original_filename", ""),
#             "status":            job_data.get("status", "processing"),
#             "total_prompts":     job_data.get("total_prompts", 0),
#             "completed_prompts": job_data.get("completed_prompts", 0),
#             "failed_prompts":    job_data.get("failed_prompts", 0),
#             "progress_percent":  job_data.get("progress_percent", 0.0),
#             "total_processing_time": job_data.get("total_processing_time"),
#         },
#         "prompts": prompts_out,
#     }


# @app.post("/api/upload")
# async def upload_excel(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(...),
#     mode: str = "full",           # "full" | "short_span" | "short_span_image"
#     clip_duration: float = 2.0,   # short_span only: seconds per clip (2–8)
#     hold_duration: float = 5.0,   # short_span_image only: seconds per image (2 or 5)
#     no_text: bool = False,        # inject no-text guardrail into all prompts
#     no_speech: bool = False,      # inject no-speech guardrail into all prompts
# ):
#     """
#     Accept an Excel/CSV file and start Veo generation as a background job.

#     Required Excel columns:  prompt, duration
#     Optional Excel columns:  task_type, priority
#     """
#     upload_id = str(uuid.uuid4())[:8]
#     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

#     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     is_valid, errors = validate_excel_file(str(temp_path))
#     if not is_valid:
#         temp_path.unlink(missing_ok=True)
#         raise HTTPException(
#             status_code=400,
#             detail=f"Excel validation failed: {'; '.join(errors)}",
#         )

#     job_data = create_job_from_excel(
#         file_path  = str(temp_path),
#         platforms  = ["veo"],
#         audio_mode = "platform_native",   # unused — Veo owns its audio
#     )
#     job_id = job_data["job_id"]

#     user_id, user_role = _request_user(request)

#     jobs[job_id]                      = job_data
#     jobs[job_id]["temp_file"]         = str(temp_path)
#     jobs[job_id]["upload_id"]         = upload_id
#     jobs[job_id]["original_filename"] = file.filename
#     jobs[job_id]["user_id"]           = user_id
#     jobs[job_id]["mode"]              = mode
#     jobs[job_id]["clip_duration"]     = clip_duration
#     jobs[job_id]["hold_duration"]     = hold_duration
#     jobs[job_id]["no_text"]           = no_text
#     jobs[job_id]["no_speech"]         = no_speech

#     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

#     background_tasks.add_task(run_generation_job, job_id)

#     return {
#         "success":       True,
#         "job_id":        job_id,
#         "upload_id":     upload_id,
#         "prompts_count": job_data["total_prompts"],
#         "veo_model":     config.VEO_MODEL_PRIMARY,
#         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
#         "native_audio":  True,  # Veo 3.0 always generates audio natively
#         "stitching":     video_stitcher.ffmpeg_available,
#         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
#     }


# # ── Concurrency config ────────────────────────────────────────────────────────

# # Max prompts running simultaneously within one job.
# # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # Each prompt with 4 clips = 4 sequential API calls.
# # At concurrency=2, clip submissions from two prompts can overlap
# # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # on the free tier. Increase if you have a paid quota.
# _PROMPT_CONCURRENCY = 1


# # ── Background generation job ─────────────────────────────────────────────────

# async def run_generation_job(job_id: str) -> None:
#     """
#     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

#     Design:
#     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
#     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
#     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
#     - Results are stored by index key str(i) — API schema unchanged.
#     - Progress percent is updated after each prompt completes (order-independent).
#     """
#     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
#     start_time   = time.time()

#     # Track session start on first job
#     if _metrics["session_start"] is None:
#         from datetime import datetime, timezone
#         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
#     _metrics["jobs_processed"] += 1
#     job          = jobs[job_id]
#     prompts_data = job["prompts"]
#     total        = len(prompts_data)

#     jobs[job_id]["results"]            = {}
#     jobs[job_id]["completed_prompts"]  = 0
#     jobs[job_id]["failed_prompts"]     = 0
#     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

#     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
#     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

#     async def _run_prompt(i: int, prompt_data: dict) -> None:
#         """
#         Semaphore-gated coroutine for a single prompt.
#         Clips within this prompt run sequentially inside generate_for_prompt().
#         """
#         prompt_text = prompt_data["text"]
#         duration    = prompt_data["duration"]

#         async with semaphore:
#             if job_id not in jobs:
#                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
#                 return

#             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
#             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
#             prompt_start = time.time()

#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = i,
#             )

#             elapsed = time.time() - prompt_start

#         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
#         async with state_lock:
#             jobs[job_id]["results"][str(i)] = result

#             # ── Push result stats into live metrics ───────────────────────────
#             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
#             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
#             # Decomposer token tracking
#             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
#             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
#             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
#             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
#             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
#             # S3 tracking
#             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
#             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

#             if result.get("status") in ("completed", "partial"):
#                 jobs[job_id]["completed_prompts"] += 1
#                 _metrics["veo_successes"]       += 1
#                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
#                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
#                 generation_logger.info(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
#                     f"-> {result.get('video_url')} "
#                     f"({'stitched' if result.get('stitched') else 'single'}, "
#                     f"{result.get('clips_count', 1)} clip(s))"
#                 )
#                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
#             else:
#                 jobs[job_id]["failed_prompts"] += 1
#                 _metrics["veo_failures"] += 1
#                 generation_logger.error(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
#                     f"{result.get('error_message')}"
#                 )

#             done_so_far = (
#                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
#             )
#             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
#             jobs[job_id]["generation_status"]  = (
#                 f"Running — {done_so_far}/{total} complete"
#             )

#     # ── Launch based on mode ──────────────────────────────────────────────────
#     mode         = job.get("mode", "full")
#     no_text      = job.get("no_text", False)
#     no_speech    = job.get("no_speech", False)
#     clip_dur     = job.get("clip_duration", 2.0)

#     if mode == "short_span":
#         # ── Short Span Clips: all rows = one sequence, no decomposition ───────
#         # Inject guardrails into prompt text before passing to orchestrator
#         _NO_TEXT_G = (
#             "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#             "subtitles, watermarks, or UI labels anywhere in the frame."
#         )
#         _NO_SPEECH_G = (
#             "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
#         )
#         enriched = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:   parts.append(_NO_TEXT_G)
#             if no_speech: parts.append(_NO_SPEECH_G)
#             parts.append(pd.get("text", ""))
#             enriched.append({**pd, "text": " ".join(parts)})

#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN mode — {len(enriched)} clip(s) "
#             f"at {clip_dur}s each, no_text={no_text}, no_speech={no_speech}"
#         )
#         result = await ss_orchestrator.run(
#             prompts         = enriched,
#             job_id          = job_id,
#             clip_duration_s = clip_dur,
#             no_text         = False,   # guardrails already injected into enriched
#             no_speech       = False,
#             aspect_ratio    = job.get("aspect_ratio", "9:16"),
#         )
#         # Store as single result at index 0 and mark job done
#         async with state_lock:
#             jobs[job_id]["results"]["0"]          = result
#             jobs[job_id]["completed_prompts"]     = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]        = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]      = 100.0
#             jobs[job_id]["generation_status"]     = "All prompts processed"
#             _metrics["veo_clips_generated"]      += result.get("clips_count", 0)
#             _metrics["veo_generation_time_s"]    += result.get("generation_time_seconds", 0) or 0
#             if result.get("status") in ("completed", "partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"] += 1

#     elif mode == "short_span_image":
#         if img_orchestrator is None:
#             generation_logger.error(f"[JOB_{job_id}] Short Span Images: GOOGLE_API_KEY not set")
#             async with state_lock:
#                 jobs[job_id]["status"] = "failed"
#                 jobs[job_id]["generation_status"] = "GOOGLE_API_KEY missing"
#                 jobs[job_id]["progress_percent"] = 100.0
#             return
#         hold_dur     = job.get("hold_duration", 5.0)
#         aspect_ratio = job.get("aspect_ratio", "9:16")
#         enriched_imgs = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:
#                 parts.append("No text, captions, titles, watermarks, or labels in the image.")
#             parts.append(pd.get("text", ""))
#             enriched_imgs.append({**pd, "text": " ".join(parts)})
#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN_IMAGE — {len(enriched_imgs)} images at {hold_dur}s"
#         )
#         result = await img_orchestrator.run(
#             prompts         = enriched_imgs,
#             job_id          = job_id,
#             hold_duration_s = hold_dur,
#             aspect_ratio    = aspect_ratio,
#             no_text         = False,
#         )
#         async with state_lock:
#             jobs[job_id]["results"]["0"]      = result
#             jobs[job_id]["completed_prompts"] = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]    = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]  = 100.0
#             jobs[job_id]["generation_status"] = "All images processed"
#             if result.get("status") in ("completed","partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"]  += 1

#     else:
#         # ── Full Length Videos (existing pipeline) ────────────────────────────
#         # Inject no_text/no_speech guardrails into prompt text if requested
#         if no_text or no_speech:
#             _NO_TEXT_G = (
#                 "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#                 "subtitles, watermarks, or UI labels anywhere in the frame."
#             )
#             _NO_SPEECH_G = (
#                 "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
#             )
#             for pd in prompts_data:
#                 parts = []
#                 if no_text:   parts.append(_NO_TEXT_G)
#                 if no_speech: parts.append(_NO_SPEECH_G)
#                 parts.append(pd.get("text", ""))
#                 pd["text"] = " ".join(parts)

#         tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
#         await asyncio.gather(*tasks, return_exceptions=True)

#     # ── Finalise ──────────────────────────────────────────────────────────────
#     total_elapsed = time.time() - start_time
#     failed_count  = jobs[job_id].get("failed_prompts", 0)

#     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
#     jobs[job_id]["generation_status"]     = "All prompts processed"
#     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

#     generation_logger.info(
#         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
#         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
#     )

#     try:
#         temp_file = jobs[job_id].get("temp_file")
#         if temp_file:
#             Path(temp_file).unlink(missing_ok=True)
#     except Exception as e:
#         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # ── Rerun single prompt ───────────────────────────────────────────────────────

# @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
#     """
#     Re-run a single prompt within an existing job.

#     Flow:
#     - Validates job and prompt exist
#     - Marks the result as "processing" immediately (UI picks this up on next poll)
#     - Schedules a background task that calls the orchestrator for just that one prompt
#     - Returns immediately so the UI is never blocked

#     Used by: rerun button on each video card in the frontend.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job = jobs[job_id]
#     prompts_data = job.get("prompts", [])

#     if prompt_index < 0 or prompt_index >= len(prompts_data):
#         raise HTTPException(
#             status_code=400,
#             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
#         )

#     prompt_data = prompts_data[prompt_index]

#     # Mark as processing immediately so frontend shows skeleton
#     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
#         "status": "processing",
#         "video_url": None,
#     }
#     # Reset counters to reflect the rerun
#     jobs[job_id]["status"] = "processing"

#     generation_logger.info(
#         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
#         f"'{prompt_data.get('text', '')[:60]}...'"
#     )

#     async def _rerun():
#         try:
#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = prompt_index,
#             )
#             jobs[job_id]["results"][str(prompt_index)] = result

#             # Recompute job-level status from all results
#             all_results = jobs[job_id].get("results", {})
#             total = len(prompts_data)
#             completed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") in ("completed", "partial")
#             )
#             failed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "failed"
#             )
#             processing = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "processing"
#             )

#             if processing == 0:
#                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
#                 jobs[job_id]["completed_prompts"] = completed
#                 jobs[job_id]["failed_prompts"]    = failed
#                 jobs[job_id]["progress_percent"]  = 100.0

#             generation_logger.info(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
#                 f"status={result.get('status')}"
#             )
#         except Exception as e:
#             jobs[job_id]["results"][str(prompt_index)] = {
#                 "status": "failed",
#                 "error_message": str(e),
#             }
#             generation_logger.error(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
#             )

#     # Soft-delete the old S3 video before rerunning
#     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
#     if veo_s3.enabled:
#         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
#         if moved:
#             generation_logger.info(
#                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
#             )
#         else:
#             generation_logger.warning(
#                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
#             )

#     background_tasks.add_task(_rerun)

#     return {
#         "status":        "accepted",
#         "job_id":        job_id,
#         "prompt_index":  prompt_index,
#         "message":       f"Rerun started for prompt {prompt_index + 1}",
#     }


# # ── YouTube upload queue ──────────────────────────────────────────────────────
# # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# #                                tags, local_path, s3_url, status, youtube_url } }
# # "approved" = waiting to upload, "uploading" = in progress,
# # "uploaded" = done, "failed" = error
# youtube_queue: Dict[str, Any] = {}


# import veo_youtube as _yt


# @app.get("/api/youtube/status")
# async def youtube_status():
#     """Check if YouTube is configured and authenticated."""
#     return {
#         "configured":    _yt.is_configured(),
#         "authenticated": _yt.is_authenticated(),
#         "secrets_file":  str(_yt.SECRETS_FILE),
#     }


# @app.post("/api/youtube/auth")
# async def youtube_auth():
#     """
#     Trigger the OAuth browser flow.
#     Opens a browser tab — user logs in, approves, token is saved.
#     Returns immediately after auth completes.
#     """
#     try:
#         _yt.get_authenticated_service()
#         return {"status": "authenticated"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# async def approve_video(job_id: str, prompt_index: int, request: Request):
#     """
#     Approve a completed video — adds it to the YouTube upload queue.

#     Auto-generates title/description/tags from the prompt.
#     User edits these in the UI before triggering upload.

#     Returns the queue_id so the frontend can reference this queue entry.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job      = jobs[job_id]
#     prompts  = job.get("prompts", [])
#     results  = job.get("results", {})

#     if prompt_index < 0 or prompt_index >= len(prompts):
#         raise HTTPException(status_code=400, detail="prompt_index out of range")

#     result = results.get(str(prompt_index), {})
#     if result.get("status") != "completed":
#         raise HTTPException(status_code=400, detail="Video is not completed yet")

#     prompt_text = prompts[prompt_index].get("text", "")
#     video_url   = result.get("video_url", "")
#     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
#     s3_url      = result.get("s3_url", "")

#     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
#     if local_path and local_path.startswith("/videos/"):
#         from pathlib import Path as _Path
#         output_dir = _Path(__file__).parent / "outputs" / "videos"
#         local_path = str(output_dir / _Path(local_path).name)

#     metadata  = _yt.generate_metadata(prompt_text)
#     queue_id  = f"q_{job_id}_{prompt_index}"

#     youtube_queue[queue_id] = {
#         "queue_id":     queue_id,
#         "job_id":       job_id,
#         "prompt_index": prompt_index,
#         "prompt_text":  prompt_text[:120],
#         "local_path":   local_path,
#         "s3_url":       s3_url,
#         "video_url":    video_url,
#         "title":        metadata["title"],
#         "description":  metadata["description"],
#         "tags":         metadata["tags"],
#         "status":       "approved",
#         "youtube_url":  None,
#         "error":        None,
#     }

#     generation_logger.info(
#         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
#     )

#     return youtube_queue[queue_id]


# @app.get("/api/youtube/queue")
# async def get_youtube_queue():
#     """Return all items in the upload queue."""
#     return {"queue": list(youtube_queue.values())}


# @app.patch("/api/youtube/queue/{queue_id}")
# async def update_queue_item(queue_id: str, body: dict):
#     """
#     Update editable metadata for a queued video before upload.
#     Accepts: { title, description, tags }
#     """
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

#     item = youtube_queue[queue_id]
#     if item["status"] not in ("approved", "failed"):
#         raise HTTPException(
#             status_code=400,
#             detail=f"Cannot edit item with status '{item['status']}'"
#         )

#     if "title" in body:
#         item["title"]       = str(body["title"])[:100]
#     if "description" in body:
#         item["description"] = str(body["description"])[:5000]
#     if "tags" in body and isinstance(body["tags"], list):
#         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

#     return item


# @app.post("/api/youtube/upload")
# async def upload_to_youtube(background_tasks: BackgroundTasks):
#     """
#     Upload ALL approved queue items to YouTube.

#     Runs in background — returns immediately.
#     Poll /api/youtube/queue to track per-item status.
#     """
#     approved = [
#         item for item in youtube_queue.values()
#         if item["status"] == "approved"
#     ]

#     if not approved:
#         raise HTTPException(status_code=400, detail="No approved videos in queue")

#     if not _yt.is_configured():
#         raise HTTPException(
#             status_code=503,
#             detail="YouTube not configured — youtube_client_secrets.json missing"
#         )

#     async def _upload_all():
#         for item in approved:
#             qid = item["queue_id"]
#             youtube_queue[qid]["status"] = "uploading"
#             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

#             result = await asyncio.get_event_loop().run_in_executor(
#                 None,
#                 lambda i=item: _yt.upload_video(
#                     local_path  = i["local_path"],
#                     title       = i["title"],
#                     description = i["description"],
#                     tags        = i["tags"],
#                     privacy     = "public",
#                 ),
#             )

#             if result["status"] == "uploaded":
#                 youtube_queue[qid]["status"]      = "uploaded"
#                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
#                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
#                 generation_logger.info(
#                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
#                 )
#             else:
#                 youtube_queue[qid]["status"] = "failed"
#                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
#                 generation_logger.error(
#                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
#                 )

#     background_tasks.add_task(_upload_all)

#     return {
#         "status":  "started",
#         "count":   len(approved),
#         "message": f"Uploading {len(approved)} video(s) to YouTube",
#     }


# @app.delete("/api/youtube/queue/{queue_id}")
# async def remove_from_queue(queue_id: str):
#     """Remove an item from the upload queue (before it's uploaded)."""
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
#     if youtube_queue[queue_id]["status"] == "uploading":
#         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
#     del youtube_queue[queue_id]
#     return {"status": "removed", "queue_id": queue_id}


# # ── Entry point ───────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     s = logging.getLogger("STARTUP")
#     s.info("=" * 70)
#     s.info("Veo Video Generation Platform v1.0.0")
#     s.info("=" * 70)
#     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
#     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
#     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
#     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
#     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     s.info("Endpoints:")
#     s.info("   API    : http://localhost:8100")
#     s.info("   Docs   : http://localhost:8100/docs")
#     s.info("   Health : http://localhost:8100/health")
#     s.info("=" * 70)

#     uvicorn.run(
#         "veo_main:app",
#         host      = "0.0.0.0",
#         port      = 8100,
#         reload    = True,
#         log_level = "info",
#     )




















# #!/usr/bin/env python3
# """
# veo_main.py — Veo Video Generation Platform
# ════════════════════════════════════════════

# Standalone FastAPI service. Accepts Excel uploads, generates videos via
# Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# via FFmpeg, and serves results as downloadable MP4 files.

# Veo 3.1 generates video and audio natively from the text prompt — no
# post-processing or external audio service is required.

# Endpoints:
#   GET  /health                → system status
#   POST /api/upload            → accept .xlsx/.csv, start background job
#   GET  /api/jobs              → list all jobs
#   GET  /api/jobs/{job_id}     → job details + per-prompt results
#   GET  /videos/{filename}     → serve generated MP4 files

# Run:
#   python veo_main.py
#   -> http://localhost:8100
#   -> http://localhost:8100/docs

# Port 8100 avoids collision with the Nova/Runway service on 8000.
# """

# import asyncio
# import logging
# import os
# import sys
# import time
# import uuid
# from datetime import datetime
# from pathlib import Path
# from typing import Any, Dict

# import uvicorn
# from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level   = logging.INFO,
#     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
#     datefmt = "%Y-%m-%d %H:%M:%S",
# )
# main_logger       = logging.getLogger("MAIN")
# upload_logger     = logging.getLogger("UPLOAD")
# generation_logger = logging.getLogger("GENERATION")
# progress_logger   = logging.getLogger("PROGRESS")
# job_logger        = logging.getLogger("JOB_MANAGER")
# health_logger     = logging.getLogger("HEALTH")

# # ── Local imports ─────────────────────────────────────────────────────────────
# _HERE = Path(__file__).resolve().parent
# sys.path.insert(0, str(_HERE))

# try:
#     from veo_config import veo_config as config
#     main_logger.info("OK veo_config loaded")
#     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# except ImportError as e:
#     main_logger.critical(f"[CONFIG_ERROR] {e}")
#     sys.exit(1)

# try:
#     from veo_excel_processor import create_job_from_excel, validate_excel_file
#     from veo_short_span_excel_processor import validate_short_span_excel, create_short_span_job
#     main_logger.info("OK veo_excel_processor + veo_short_span_excel_processor loaded")
# except ImportError as e:
#     main_logger.critical(f"veo_excel_processor import failed: {e}")
#     sys.exit(1)

# # Directories
# _BASE_DIR  = _HERE
# output_dir = _BASE_DIR / config.OUTPUT_DIR
# temp_dir   = _BASE_DIR / config.TEMP_DIR
# output_dir.mkdir(parents=True, exist_ok=True)
# temp_dir.mkdir(parents=True, exist_ok=True)
# (output_dir / "decompositions").mkdir(exist_ok=True)

# try:
#     from video_stitcher import VideoStitcher
#     from prompt_decomposer import PromptDecomposer

#     video_stitcher = VideoStitcher(
#         output_dir            = output_dir,
#         aws_access_key_id     = "",
#         aws_secret_access_key = "",
#         bucket                = "",
#         region                = "",
#     )
#     prompt_decomposer = PromptDecomposer(
#         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#         region                = config.AWS_DEFAULT_REGION,
#     )
#     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
#     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     main_logger.info(
#         f"   Decomposer : "
#         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
#     )
# except ImportError as e:
#     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
#     sys.exit(1)

# veo_generator = None
# try:
#     from veo_generator import VeoGenerator
#     if config.GOOGLE_API_KEY:
#         veo_generator = VeoGenerator(
#             api_key              = config.GOOGLE_API_KEY,
#             output_dir           = output_dir,
#             model_primary        = config.VEO_MODEL_PRIMARY,
#             model_fallback       = config.VEO_MODEL_FALLBACK,
#             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
#             aspect_ratio         = config.VEO_ASPECT_RATIO,
#             resolution           = config.VEO_RESOLUTION,
#             generate_audio       = config.VEO_GENERATE_AUDIO,
#             sample_count         = config.VEO_SAMPLE_COUNT,
#             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
#             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
#         )
#         main_logger.info("OK VeoGenerator initialised")
#     else:
#         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# except ImportError as e:
#     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# if not veo_generator:
#     main_logger.critical("Cannot start without a Veo generator. Exiting.")
#     sys.exit(1)

# from veo_s3 import VeoS3Client
# veo_s3 = VeoS3Client(
#     bucket = os.getenv("VEO_S3_BUCKET", ""),
#     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# )
# main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# from veo_orchestrator import VeoOrchestrator
# from veo_short_span_orchestrator import ShortSpanOrchestrator
# try:
#     from veo_short_span_image_orchestrator import ShortSpanImageOrchestrator
#     from veo_imagen_generator import ImagenGenerator
#     _IMAGEN_AVAILABLE = True
# except ImportError:
#     ShortSpanImageOrchestrator = None  # type: ignore
#     ImagenGenerator = None             # type: ignore
#     _IMAGEN_AVAILABLE = False
# veo_orchestrator = VeoOrchestrator(
#     generator     = veo_generator,
#     stitcher      = video_stitcher,
#     decomposer    = prompt_decomposer,
#     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
#     s3_client     = veo_s3,
# )
# main_logger.info("OK VeoOrchestrator initialised")

# ss_orchestrator = ShortSpanOrchestrator(
#     generator  = veo_generator,
#     stitcher   = video_stitcher,
#     s3_client  = veo_s3,
# )
# main_logger.info("OK ShortSpanOrchestrator initialised")

# # ── Short Span Image orchestrator — same GOOGLE_API_KEY as Veo ───────────────
# _imagen_model = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-001")
# if _IMAGEN_AVAILABLE and config.GOOGLE_API_KEY:
#     imagen_generator = ImagenGenerator(
#         api_key    = config.GOOGLE_API_KEY,
#         model_id   = _imagen_model,
#         output_dir = config.OUTPUT_DIR,
#     )
#     img_orchestrator = ShortSpanImageOrchestrator(
#         imagen_generator = imagen_generator,
#         stitcher         = video_stitcher,
#         s3_client        = veo_s3,
#     )
#     main_logger.info(f"OK ShortSpanImageOrchestrator initialised (model={_imagen_model})")
# else:
#     imagen_generator = None
#     img_orchestrator = None
#     if not _IMAGEN_AVAILABLE:
#         main_logger.warning(
#             "veo_imagen_generator / veo_short_span_image_orchestrator not found — "
#             "Short Span Images disabled. Copy both files to the veo/ folder to enable."
#         )
#     else:
#         main_logger.warning("GOOGLE_API_KEY not set — Short Span Images disabled")

# # ── Job store ─────────────────────────────────────────────────────────────────
# jobs: Dict[str, Any] = {}

# # ── Per-request user identity ─────────────────────────────────────────────────
# def _request_user(request: Request) -> tuple:
#     """
#     Return (user_id, user_role) from request headers.
#     X-User-Id   — authenticated user email (set by frontend _headers())
#     X-User-Role — role string: admin / editor / viewer
#     Defaults to ("anonymous","viewer") so curl/API docs still work.
#     PRODUCTION: replace with JWT decode.
#     """
#     uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
#     role = request.headers.get("X-User-Role", "viewer").strip().lower()
#     return uid, role

# def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
#     """Admins see all jobs. Others see only their own."""
#     if user_role == "admin":
#         return True
#     return job_data.get("user_id", "anonymous") == user_id

# # ── Live metrics store ────────────────────────────────────────────────────────
# # Updated in real-time by generator and decomposer via push.
# # Resets on server restart — tracks current session only.
# _metrics: Dict[str, Any] = {
#     # Veo API
#     "veo_submissions":      0,   # total API calls attempted
#     "veo_successes":        0,   # successful completions
#     "veo_failures":         0,   # all failures (any error)
#     "veo_rate_limit_hits":  0,   # 429 errors specifically
#     "veo_clips_generated":  0,   # clips that produced a video file
#     "veo_generation_time_s": 0.0, # cumulative generation time

#     # Bedrock decomposer
#     "decomp_nova_calls":       0,
#     "decomp_deepseek_calls":   0,
#     "decomp_deterministic":    0,
#     "decomp_input_tokens":     0,
#     "decomp_output_tokens":    0,

#     # S3
#     "s3_uploads_ok":    0,
#     "s3_uploads_fail":  0,

#     # Session
#     "session_start":    None,   # set on first job
#     "jobs_processed":   0,
# }

# # ── FastAPI ───────────────────────────────────────────────────────────────────
# app = FastAPI(
#     title       = "Veo Video Generation Platform",
#     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
#     version     = "1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
#                          "http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials = True,
#     allow_methods     = ["*"],
#     allow_headers     = ["*"],
# )

# app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # ── Routes ────────────────────────────────────────────────────────────────────

# @app.get("/health")
# async def health_check():
#     health_logger.info("Health check requested")
#     return {
#         "status":    "healthy",
#         "service":   "veo-video-generation-platform",
#         "version":   "1.0.0",
#         "timestamp": datetime.now().isoformat(),
#         "components": {
#             "veo_generator":   True,
#             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
#             "decomposer":      True,
#         },
#         "veo": {
#             "primary_model":  config.VEO_MODEL_PRIMARY,
#             "fallback_model": config.VEO_MODEL_FALLBACK,
#             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
#             "aspect_ratio":   config.VEO_ASPECT_RATIO,
#             "resolution":     config.VEO_RESOLUTION,
#             "native_audio":   True,  # Veo 3.0 always generates audio natively
#         },
#         "decomposer_mode": (
#             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
#         ),
#     }


# @app.get("/api/metrics")
# async def get_metrics():
#     """Real-time generation metrics for the Streamlit dashboard."""
#     import time
#     from datetime import datetime, timezone

#     # Derived metrics
#     total_veo   = _metrics["veo_submissions"]
#     rl_rate     = (
#         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
#         if total_veo > 0 else 0.0
#     )
#     avg_clip_s  = (
#         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
#         if _metrics["veo_clips_generated"] > 0 else 0.0
#     )

#     # Estimated cost (clips × 8s × $0.40 for primary model)
#     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
#     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

#     return {
#         "session_start":        _metrics["session_start"],
#         "jobs_processed":       _metrics["jobs_processed"],

#         "veo": {
#             "submissions":      _metrics["veo_submissions"],
#             "successes":        _metrics["veo_successes"],
#             "failures":         _metrics["veo_failures"],
#             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
#             "rate_limit_pct":   rl_rate,
#             "clips_generated":  _metrics["veo_clips_generated"],
#             "avg_clip_time_s":  avg_clip_s,
#             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
#         },

#         "decomposer": {
#             "nova_calls":        _metrics["decomp_nova_calls"],
#             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
#             "deterministic":     _metrics["decomp_deterministic"],
#             "input_tokens":      _metrics["decomp_input_tokens"],
#             "output_tokens":     _metrics["decomp_output_tokens"],
#             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
#         },

#         "s3": {
#             "uploads_ok":   _metrics["s3_uploads_ok"],
#             "uploads_fail": _metrics["s3_uploads_fail"],
#         },

#         "cost_estimate": {
#             "usd": round(est_cost_usd, 4),
#             "inr": round(est_cost_inr, 2),
#             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
#         },
#     }


# @app.get("/api/jobs")
# async def list_jobs(request: Request):
#     user_id, user_role = _request_user(request)
#     visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
#     job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
#     return {
#         "jobs": [
#             {
#                 "job_id":            job_id,
#                 "original_filename": jd.get("original_filename", ""),
#                 "status":            jd.get("status", "processing"),
#                 "total_prompts":     jd.get("total_prompts", 0),
#                 "completed_prompts": jd.get("completed_prompts", 0),
#                 "failed_prompts":    jd.get("failed_prompts", 0),
#                 "progress_percent":  jd.get("progress_percent", 0.0),
#                 "created_at":        jd.get("created_at", ""),
#                 "generation_status": jd.get("generation_status", "Queued"),
#                 "user_id":           jd.get("user_id", "anonymous"),
#             }
#             for job_id, jd in visible.items()
#         ]
#     }


# @app.get("/api/jobs/{job_id}")
# async def get_job(job_id: str, request: Request):
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     user_id, user_role = _request_user(request)
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied")

#     job_data = jobs[job_id]
#     results  = job_data.get("results", {})

#     prompts_out = []
#     for i, prompt_data in enumerate(job_data.get("prompts", [])):
#         r = results.get(str(i), {})
#         # video_url: may be S3 URL after upload (for distribution)
#         # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
#         raw_video_url = r.get("video_url")
#         raw_local_url = r.get("local_video_url")
#         # Ensure local_video_url is a proper /videos/ route, not an absolute path
#         if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
#             from pathlib import Path as _Path
#             raw_local_url = f"/videos/{_Path(raw_local_url).name}"
#         # If no local URL stored but video_url is already a local route, use it
#         if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
#             raw_local_url = raw_video_url
#         prompts_out.append({
#             "prompt_id":        f"prompt_{i + 1}",
#             "prompt_text":      prompt_data.get("text", ""),
#             "row_number":       i + 1,
#             "duration":         prompt_data.get("duration", 8),
#             "status":           r.get("status", "processing"),
#             "video_url":        raw_video_url,    # S3 or local route
#             "local_video_url":  raw_local_url,    # always /videos/... for player
#             "duration_seconds": r.get("duration_seconds"),
#             "stitched":         r.get("stitched", False),
#             "clips_count":      r.get("clips_count", 0),
#             "clip_urls":        r.get("clip_urls", []),
#             "model_used":       r.get("model_used", ""),
#             "has_native_audio": r.get("has_native_audio", False),
#             "error_message":    r.get("error_message"),
#             "generation_time_seconds": r.get("generation_time_seconds"),
#         })

#     return {
#         "job_id":       job_id,
#         "status":       job_data.get("status", "processing"),
#         "mode":         job_data.get("mode", "full"),
#         "hold_duration":job_data.get("hold_duration", 5.0),
#         "clip_duration":job_data.get("clip_duration", 8),
#         "no_text":      job_data.get("no_text", False),
#         "no_speech":    job_data.get("no_speech", False),
#         "summary": {
#             "job_id":            job_id,
#             "original_filename": job_data.get("original_filename", ""),
#             "status":            job_data.get("status", "processing"),
#             "total_prompts":     job_data.get("total_prompts", 0),
#             "completed_prompts": job_data.get("completed_prompts", 0),
#             "failed_prompts":    job_data.get("failed_prompts", 0),
#             "progress_percent":  job_data.get("progress_percent", 0.0),
#             "total_processing_time": job_data.get("total_processing_time"),
#         },
#         "prompts": prompts_out,
#     }


# @app.post("/api/upload")
# async def upload_excel(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(...),
#     mode: str = "full",           # "full" | "short_span" | "short_span_image"
#     clip_duration: float = 2.0,   # short_span only: seconds per clip (2–8)
#     hold_duration: float = 5.0,   # short_span_image only: seconds per image (2 or 5)
#     no_text: bool = False,        # inject no-text guardrail into all prompts
#     no_speech: bool = False,      # inject no-speech guardrail into all prompts
# ):
#     """
#     Accept an Excel/CSV file and start Veo generation as a background job.

#     Required Excel columns:  prompt, duration
#     Optional Excel columns:  task_type, priority
#     """
#     upload_id = str(uuid.uuid4())[:8]
#     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

#     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     _is_short_span = mode in ("short_span", "short_span_image")

#     if _is_short_span:
#         is_valid, errors = validate_short_span_excel(str(temp_path))
#     else:
#         is_valid, errors = validate_excel_file(str(temp_path))

#     if not is_valid:
#         temp_path.unlink(missing_ok=True)
#         raise HTTPException(
#             status_code=400,
#             detail=f"Excel validation failed: {'; '.join(errors)}",
#         )

#     if _is_short_span:
#         job_data = create_short_span_job(
#             file_path       = str(temp_path),
#             clip_duration_s = clip_duration,
#             aspect_ratio    = "9:16",
#         )
#     else:
#         job_data = create_job_from_excel(
#             file_path  = str(temp_path),
#             platforms  = ["veo"],
#             audio_mode = "platform_native",
#         )
#     job_id = job_data["job_id"]

#     user_id, user_role = _request_user(request)

#     jobs[job_id]                      = job_data
#     jobs[job_id]["temp_file"]         = str(temp_path)
#     jobs[job_id]["upload_id"]         = upload_id
#     jobs[job_id]["original_filename"] = file.filename
#     jobs[job_id]["user_id"]           = user_id
#     jobs[job_id]["mode"]              = mode
#     jobs[job_id]["clip_duration"]     = clip_duration
#     jobs[job_id]["hold_duration"]     = hold_duration
#     jobs[job_id]["no_text"]           = no_text
#     jobs[job_id]["no_speech"]         = no_speech

#     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

#     background_tasks.add_task(run_generation_job, job_id)

#     return {
#         "success":       True,
#         "job_id":        job_id,
#         "upload_id":     upload_id,
#         "prompts_count": job_data["total_prompts"],
#         "veo_model":     config.VEO_MODEL_PRIMARY,
#         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
#         "native_audio":  True,  # Veo 3.0 always generates audio natively
#         "stitching":     video_stitcher.ffmpeg_available,
#         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
#     }


# # ── Concurrency config ────────────────────────────────────────────────────────

# # Max prompts running simultaneously within one job.
# # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # Each prompt with 4 clips = 4 sequential API calls.
# # At concurrency=2, clip submissions from two prompts can overlap
# # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # on the free tier. Increase if you have a paid quota.
# _PROMPT_CONCURRENCY = 1


# # ── Background generation job ─────────────────────────────────────────────────

# async def run_generation_job(job_id: str) -> None:
#     """
#     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

#     Design:
#     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
#     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
#     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
#     - Results are stored by index key str(i) — API schema unchanged.
#     - Progress percent is updated after each prompt completes (order-independent).
#     """
#     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
#     start_time   = time.time()

#     # Track session start on first job
#     if _metrics["session_start"] is None:
#         from datetime import datetime, timezone
#         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
#     _metrics["jobs_processed"] += 1
#     job          = jobs[job_id]
#     prompts_data = job["prompts"]
#     total        = len(prompts_data)

#     jobs[job_id]["results"]            = {}
#     jobs[job_id]["completed_prompts"]  = 0
#     jobs[job_id]["failed_prompts"]     = 0
#     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

#     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
#     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

#     async def _run_prompt(i: int, prompt_data: dict) -> None:
#         """
#         Semaphore-gated coroutine for a single prompt.
#         Clips within this prompt run sequentially inside generate_for_prompt().
#         """
#         prompt_text = prompt_data["text"]
#         duration    = prompt_data["duration"]

#         async with semaphore:
#             if job_id not in jobs:
#                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
#                 return

#             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
#             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
#             prompt_start = time.time()

#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = i,
#             )

#             elapsed = time.time() - prompt_start

#         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
#         async with state_lock:
#             jobs[job_id]["results"][str(i)] = result

#             # ── Push result stats into live metrics ───────────────────────────
#             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
#             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
#             # Decomposer token tracking
#             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
#             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
#             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
#             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
#             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
#             # S3 tracking
#             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
#             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

#             if result.get("status") in ("completed", "partial"):
#                 jobs[job_id]["completed_prompts"] += 1
#                 _metrics["veo_successes"]       += 1
#                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
#                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
#                 generation_logger.info(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
#                     f"-> {result.get('video_url')} "
#                     f"({'stitched' if result.get('stitched') else 'single'}, "
#                     f"{result.get('clips_count', 1)} clip(s))"
#                 )
#                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
#             else:
#                 jobs[job_id]["failed_prompts"] += 1
#                 _metrics["veo_failures"] += 1
#                 generation_logger.error(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
#                     f"{result.get('error_message')}"
#                 )

#             done_so_far = (
#                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
#             )
#             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
#             jobs[job_id]["generation_status"]  = (
#                 f"Running — {done_so_far}/{total} complete"
#             )

#     # ── Launch based on mode ──────────────────────────────────────────────────
#     mode         = job.get("mode", "full")
#     no_text      = job.get("no_text", False)
#     no_speech    = job.get("no_speech", False)
#     clip_dur     = job.get("clip_duration", 2.0)

#     if mode == "short_span":
#         # ── Short Span Clips: all rows = one sequence, no decomposition ───────
#         # Inject guardrails into prompt text before passing to orchestrator
#         _NO_TEXT_G = (
#             "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#             "subtitles, watermarks, or UI labels anywhere in the frame."
#         )
#         _NO_SPEECH_G = (
#             "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
#         )
#         enriched = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:   parts.append(_NO_TEXT_G)
#             if no_speech: parts.append(_NO_SPEECH_G)
#             parts.append(pd.get("text", ""))
#             enriched.append({**pd, "text": " ".join(parts)})

#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN mode — {len(enriched)} clip(s) "
#             f"at {clip_dur}s each, no_text={no_text}, no_speech={no_speech}"
#         )
#         result = await ss_orchestrator.run(
#             prompts         = enriched,
#             job_id          = job_id,
#             clip_duration_s = clip_dur,
#             no_text         = False,   # guardrails already injected into enriched
#             no_speech       = False,
#             aspect_ratio    = job.get("aspect_ratio", "9:16"),
#         )
#         # Store as single result at index 0 and mark job done
#         async with state_lock:
#             jobs[job_id]["results"]["0"]          = result
#             jobs[job_id]["completed_prompts"]     = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]        = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]      = 100.0
#             jobs[job_id]["generation_status"]     = "All prompts processed"
#             _metrics["veo_clips_generated"]      += result.get("clips_count", 0)
#             _metrics["veo_generation_time_s"]    += result.get("generation_time_seconds", 0) or 0
#             if result.get("status") in ("completed", "partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"] += 1

#     elif mode == "short_span_image":
#         if img_orchestrator is None:
#             generation_logger.error(f"[JOB_{job_id}] Short Span Images: GOOGLE_API_KEY not set")
#             async with state_lock:
#                 jobs[job_id]["status"] = "failed"
#                 jobs[job_id]["generation_status"] = "GOOGLE_API_KEY missing"
#                 jobs[job_id]["progress_percent"] = 100.0
#             return
#         hold_dur     = job.get("hold_duration", 5.0)
#         aspect_ratio = job.get("aspect_ratio", "9:16")
#         enriched_imgs = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:
#                 parts.append("No text, captions, titles, watermarks, or labels in the image.")
#             parts.append(pd.get("text", ""))
#             enriched_imgs.append({**pd, "text": " ".join(parts)})
#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN_IMAGE — {len(enriched_imgs)} images at {hold_dur}s"
#         )
#         result = await img_orchestrator.run(
#             prompts         = enriched_imgs,
#             job_id          = job_id,
#             hold_duration_s = hold_dur,
#             aspect_ratio    = aspect_ratio,
#             no_text         = False,
#         )
#         async with state_lock:
#             jobs[job_id]["results"]["0"]      = result
#             jobs[job_id]["completed_prompts"] = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]    = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]  = 100.0
#             jobs[job_id]["generation_status"] = "All images processed"
#             if result.get("status") in ("completed","partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"]  += 1

#     else:
#         # ── Full Length Videos (existing pipeline) ────────────────────────────
#         # Inject no_text/no_speech guardrails into prompt text if requested
#         if no_text or no_speech:
#             _NO_TEXT_G = (
#                 "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#                 "subtitles, watermarks, or UI labels anywhere in the frame."
#             )
#             _NO_SPEECH_G = (
#                 "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
#             )
#             for pd in prompts_data:
#                 parts = []
#                 if no_text:   parts.append(_NO_TEXT_G)
#                 if no_speech: parts.append(_NO_SPEECH_G)
#                 parts.append(pd.get("text", ""))
#                 pd["text"] = " ".join(parts)

#         tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
#         await asyncio.gather(*tasks, return_exceptions=True)

#     # ── Finalise ──────────────────────────────────────────────────────────────
#     total_elapsed = time.time() - start_time
#     failed_count  = jobs[job_id].get("failed_prompts", 0)

#     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
#     jobs[job_id]["generation_status"]     = "All prompts processed"
#     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

#     generation_logger.info(
#         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
#         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
#     )

#     try:
#         temp_file = jobs[job_id].get("temp_file")
#         if temp_file:
#             Path(temp_file).unlink(missing_ok=True)
#     except Exception as e:
#         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # ── Rerun single prompt ───────────────────────────────────────────────────────

# @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
#     """
#     Re-run a single prompt within an existing job.

#     Flow:
#     - Validates job and prompt exist
#     - Marks the result as "processing" immediately (UI picks this up on next poll)
#     - Schedules a background task that calls the orchestrator for just that one prompt
#     - Returns immediately so the UI is never blocked

#     Used by: rerun button on each video card in the frontend.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job = jobs[job_id]
#     prompts_data = job.get("prompts", [])

#     if prompt_index < 0 or prompt_index >= len(prompts_data):
#         raise HTTPException(
#             status_code=400,
#             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
#         )

#     prompt_data = prompts_data[prompt_index]

#     # Mark as processing immediately so frontend shows skeleton
#     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
#         "status": "processing",
#         "video_url": None,
#     }
#     # Reset counters to reflect the rerun
#     jobs[job_id]["status"] = "processing"

#     generation_logger.info(
#         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
#         f"'{prompt_data.get('text', '')[:60]}...'"
#     )

#     async def _rerun():
#         try:
#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = prompt_index,
#             )
#             jobs[job_id]["results"][str(prompt_index)] = result

#             # Recompute job-level status from all results
#             all_results = jobs[job_id].get("results", {})
#             total = len(prompts_data)
#             completed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") in ("completed", "partial")
#             )
#             failed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "failed"
#             )
#             processing = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "processing"
#             )

#             if processing == 0:
#                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
#                 jobs[job_id]["completed_prompts"] = completed
#                 jobs[job_id]["failed_prompts"]    = failed
#                 jobs[job_id]["progress_percent"]  = 100.0

#             generation_logger.info(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
#                 f"status={result.get('status')}"
#             )
#         except Exception as e:
#             jobs[job_id]["results"][str(prompt_index)] = {
#                 "status": "failed",
#                 "error_message": str(e),
#             }
#             generation_logger.error(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
#             )

#     # Soft-delete the old S3 video before rerunning
#     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
#     if veo_s3.enabled:
#         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
#         if moved:
#             generation_logger.info(
#                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
#             )
#         else:
#             generation_logger.warning(
#                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
#             )

#     background_tasks.add_task(_rerun)

#     return {
#         "status":        "accepted",
#         "job_id":        job_id,
#         "prompt_index":  prompt_index,
#         "message":       f"Rerun started for prompt {prompt_index + 1}",
#     }


# # ── YouTube upload queue ──────────────────────────────────────────────────────
# # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# #                                tags, local_path, s3_url, status, youtube_url } }
# # "approved" = waiting to upload, "uploading" = in progress,
# # "uploaded" = done, "failed" = error
# youtube_queue: Dict[str, Any] = {}


# import veo_youtube as _yt


# @app.get("/api/youtube/status")
# async def youtube_status():
#     """Check if YouTube is configured and authenticated."""
#     return {
#         "configured":    _yt.is_configured(),
#         "authenticated": _yt.is_authenticated(),
#         "secrets_file":  str(_yt.SECRETS_FILE),
#     }


# @app.post("/api/youtube/auth")
# async def youtube_auth():
#     """
#     Trigger the OAuth browser flow.
#     Opens a browser tab — user logs in, approves, token is saved.
#     Returns immediately after auth completes.
#     """
#     try:
#         _yt.get_authenticated_service()
#         return {"status": "authenticated"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# async def approve_video(job_id: str, prompt_index: int, request: Request):
#     """
#     Approve a completed video — adds it to the YouTube upload queue.

#     Auto-generates title/description/tags from the prompt.
#     User edits these in the UI before triggering upload.

#     Returns the queue_id so the frontend can reference this queue entry.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job      = jobs[job_id]
#     prompts  = job.get("prompts", [])
#     results  = job.get("results", {})

#     if prompt_index < 0 or prompt_index >= len(prompts):
#         raise HTTPException(status_code=400, detail="prompt_index out of range")

#     result = results.get(str(prompt_index), {})
#     if result.get("status") != "completed":
#         raise HTTPException(status_code=400, detail="Video is not completed yet")

#     prompt_text = prompts[prompt_index].get("text", "")
#     video_url   = result.get("video_url", "")
#     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
#     s3_url      = result.get("s3_url", "")

#     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
#     if local_path and local_path.startswith("/videos/"):
#         from pathlib import Path as _Path
#         output_dir = _Path(__file__).parent / "outputs" / "videos"
#         local_path = str(output_dir / _Path(local_path).name)

#     metadata  = _yt.generate_metadata(prompt_text)
#     queue_id  = f"q_{job_id}_{prompt_index}"

#     youtube_queue[queue_id] = {
#         "queue_id":     queue_id,
#         "job_id":       job_id,
#         "prompt_index": prompt_index,
#         "prompt_text":  prompt_text[:120],
#         "local_path":   local_path,
#         "s3_url":       s3_url,
#         "video_url":    video_url,
#         "title":        metadata["title"],
#         "description":  metadata["description"],
#         "tags":         metadata["tags"],
#         "status":       "approved",
#         "youtube_url":  None,
#         "error":        None,
#     }

#     generation_logger.info(
#         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
#     )

#     return youtube_queue[queue_id]


# @app.get("/api/youtube/queue")
# async def get_youtube_queue():
#     """Return all items in the upload queue."""
#     return {"queue": list(youtube_queue.values())}


# @app.patch("/api/youtube/queue/{queue_id}")
# async def update_queue_item(queue_id: str, body: dict):
#     """
#     Update editable metadata for a queued video before upload.
#     Accepts: { title, description, tags }
#     """
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

#     item = youtube_queue[queue_id]
#     if item["status"] not in ("approved", "failed"):
#         raise HTTPException(
#             status_code=400,
#             detail=f"Cannot edit item with status '{item['status']}'"
#         )

#     if "title" in body:
#         item["title"]       = str(body["title"])[:100]
#     if "description" in body:
#         item["description"] = str(body["description"])[:5000]
#     if "tags" in body and isinstance(body["tags"], list):
#         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

#     return item


# @app.post("/api/youtube/upload")
# async def upload_to_youtube(background_tasks: BackgroundTasks):
#     """
#     Upload ALL approved queue items to YouTube.

#     Runs in background — returns immediately.
#     Poll /api/youtube/queue to track per-item status.
#     """
#     approved = [
#         item for item in youtube_queue.values()
#         if item["status"] == "approved"
#     ]

#     if not approved:
#         raise HTTPException(status_code=400, detail="No approved videos in queue")

#     if not _yt.is_configured():
#         raise HTTPException(
#             status_code=503,
#             detail="YouTube not configured — youtube_client_secrets.json missing"
#         )

#     async def _upload_all():
#         for item in approved:
#             qid = item["queue_id"]
#             youtube_queue[qid]["status"] = "uploading"
#             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

#             result = await asyncio.get_event_loop().run_in_executor(
#                 None,
#                 lambda i=item: _yt.upload_video(
#                     local_path  = i["local_path"],
#                     title       = i["title"],
#                     description = i["description"],
#                     tags        = i["tags"],
#                     privacy     = "public",
#                 ),
#             )

#             if result["status"] == "uploaded":
#                 youtube_queue[qid]["status"]      = "uploaded"
#                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
#                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
#                 generation_logger.info(
#                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
#                 )
#             else:
#                 youtube_queue[qid]["status"] = "failed"
#                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
#                 generation_logger.error(
#                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
#                 )

#     background_tasks.add_task(_upload_all)

#     return {
#         "status":  "started",
#         "count":   len(approved),
#         "message": f"Uploading {len(approved)} video(s) to YouTube",
#     }


# @app.delete("/api/youtube/queue/{queue_id}")
# async def remove_from_queue(queue_id: str):
#     """Remove an item from the upload queue (before it's uploaded)."""
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
#     if youtube_queue[queue_id]["status"] == "uploading":
#         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
#     del youtube_queue[queue_id]
#     return {"status": "removed", "queue_id": queue_id}


# # ── Entry point ───────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     s = logging.getLogger("STARTUP")
#     s.info("=" * 70)
#     s.info("Veo Video Generation Platform v1.0.0")
#     s.info("=" * 70)
#     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
#     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
#     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
#     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
#     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     s.info("Endpoints:")
#     s.info("   API    : http://localhost:8100")
#     s.info("   Docs   : http://localhost:8100/docs")
#     s.info("   Health : http://localhost:8100/health")
#     s.info("=" * 70)

#     uvicorn.run(
#         "veo_main:app",
#         host      = "0.0.0.0",
#         port      = 8100,
#         reload    = True,
#         log_level = "info",
#     )





















# #!/usr/bin/env python3
# """
# veo_main.py — Veo Video Generation Platform
# ════════════════════════════════════════════

# Standalone FastAPI service. Accepts Excel uploads, generates videos via
# Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# via FFmpeg, and serves results as downloadable MP4 files.

# Veo 3.1 generates video and audio natively from the text prompt — no
# post-processing or external audio service is required.

# Endpoints:
#   GET  /health                → system status
#   POST /api/upload            → accept .xlsx/.csv, start background job
#   GET  /api/jobs              → list all jobs
#   GET  /api/jobs/{job_id}     → job details + per-prompt results
#   GET  /videos/{filename}     → serve generated MP4 files

# Run:
#   python veo_main.py
#   -> http://localhost:8100
#   -> http://localhost:8100/docs

# Port 8100 avoids collision with the Nova/Runway service on 8000.
# """

# import asyncio
# import logging
# import os
# import sys
# import time
# import uuid
# from datetime import datetime
# from pathlib import Path
# from typing import Any, Dict

# import uvicorn
# from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.responses import JSONResponse
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level   = logging.INFO,
#     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
#     datefmt = "%Y-%m-%d %H:%M:%S",
# )
# main_logger       = logging.getLogger("MAIN")
# upload_logger     = logging.getLogger("UPLOAD")
# generation_logger = logging.getLogger("GENERATION")
# progress_logger   = logging.getLogger("PROGRESS")
# job_logger        = logging.getLogger("JOB_MANAGER")
# health_logger     = logging.getLogger("HEALTH")

# # ── Local imports ─────────────────────────────────────────────────────────────
# _HERE = Path(__file__).resolve().parent
# sys.path.insert(0, str(_HERE))

# try:
#     from veo_config import veo_config as config
#     main_logger.info("OK veo_config loaded")
#     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# except ImportError as e:
#     main_logger.critical(f"[CONFIG_ERROR] {e}")
#     sys.exit(1)

# try:
#     from veo_excel_processor import create_job_from_excel, validate_excel_file
#     from veo_short_span_excel_processor import validate_short_span_excel, create_short_span_job
#     from veo_users import UserStore
#     main_logger.info("OK veo_excel_processor + veo_short_span_excel_processor loaded")
# except ImportError as e:
#     main_logger.critical(f"veo_excel_processor import failed: {e}")
#     sys.exit(1)

# # Directories
# _BASE_DIR  = _HERE
# output_dir = _BASE_DIR / config.OUTPUT_DIR
# temp_dir   = _BASE_DIR / config.TEMP_DIR
# output_dir.mkdir(parents=True, exist_ok=True)
# temp_dir.mkdir(parents=True, exist_ok=True)
# (output_dir / "decompositions").mkdir(exist_ok=True)

# try:
#     from video_stitcher import VideoStitcher
#     from prompt_decomposer import PromptDecomposer

#     video_stitcher = VideoStitcher(
#         output_dir            = output_dir,
#         aws_access_key_id     = "",
#         aws_secret_access_key = "",
#         bucket                = "",
#         region                = "",
#     )
#     prompt_decomposer = PromptDecomposer(
#         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#         region                = config.AWS_DEFAULT_REGION,
#     )
#     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
#     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     main_logger.info(
#         f"   Decomposer : "
#         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
#     )
# except ImportError as e:
#     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
#     sys.exit(1)

# veo_generator = None
# try:
#     from veo_generator import VeoGenerator
#     if config.GOOGLE_API_KEY:
#         veo_generator = VeoGenerator(
#             api_key              = config.GOOGLE_API_KEY,
#             output_dir           = output_dir,
#             model_primary        = config.VEO_MODEL_PRIMARY,
#             model_fallback       = config.VEO_MODEL_FALLBACK,
#             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
#             aspect_ratio         = config.VEO_ASPECT_RATIO,
#             resolution           = config.VEO_RESOLUTION,
#             generate_audio       = config.VEO_GENERATE_AUDIO,
#             sample_count         = config.VEO_SAMPLE_COUNT,
#             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
#             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
#         )
#         main_logger.info("OK VeoGenerator initialised")
#     else:
#         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# except ImportError as e:
#     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# if not veo_generator:
#     main_logger.critical("Cannot start without a Veo generator. Exiting.")
#     sys.exit(1)

# from veo_s3 import VeoS3Client
# veo_s3 = VeoS3Client(
#     bucket = os.getenv("VEO_S3_BUCKET", ""),
#     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# )
# main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# from veo_orchestrator import VeoOrchestrator
# from veo_short_span_orchestrator import ShortSpanOrchestrator
# try:
#     from veo_short_span_image_orchestrator import ShortSpanImageOrchestrator
#     from veo_imagen_generator import ImagenGenerator
#     _IMAGEN_AVAILABLE = True
# except ImportError:
#     ShortSpanImageOrchestrator = None  # type: ignore
#     ImagenGenerator = None             # type: ignore
#     _IMAGEN_AVAILABLE = False
# veo_orchestrator = VeoOrchestrator(
#     generator     = veo_generator,
#     stitcher      = video_stitcher,
#     decomposer    = prompt_decomposer,
#     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
#     s3_client     = veo_s3,
# )
# main_logger.info("OK VeoOrchestrator initialised")

# # ── User store ────────────────────────────────────────────────────────────────
# user_store = UserStore()
# user_store.init()
# main_logger.info(f"OK UserStore — {user_store.count()} user(s)")

# ss_orchestrator = ShortSpanOrchestrator(
#     generator  = veo_generator,
#     stitcher   = video_stitcher,
#     s3_client  = veo_s3,
# )
# main_logger.info("OK ShortSpanOrchestrator initialised")

# # ── Short Span Image orchestrator — same GOOGLE_API_KEY as Veo ───────────────
# _imagen_model = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-001")
# if _IMAGEN_AVAILABLE and config.GOOGLE_API_KEY:
#     imagen_generator = ImagenGenerator(
#         api_key    = config.GOOGLE_API_KEY,
#         model_id   = _imagen_model,
#         output_dir = config.OUTPUT_DIR,
#     )
#     img_orchestrator = ShortSpanImageOrchestrator(
#         imagen_generator = imagen_generator,
#         stitcher         = video_stitcher,
#         s3_client        = veo_s3,
#     )
#     main_logger.info(f"OK ShortSpanImageOrchestrator initialised (model={_imagen_model})")
# else:
#     imagen_generator = None
#     img_orchestrator = None
#     if not _IMAGEN_AVAILABLE:
#         main_logger.warning(
#             "veo_imagen_generator / veo_short_span_image_orchestrator not found — "
#             "Short Span Images disabled. Copy both files to the veo/ folder to enable."
#         )
#     else:
#         main_logger.warning("GOOGLE_API_KEY not set — Short Span Images disabled")

# # ── Job store ─────────────────────────────────────────────────────────────────
# jobs: Dict[str, Any] = {}

# # ── Per-request user identity ─────────────────────────────────────────────────
# def _request_user(request: Request) -> tuple:
#     """
#     Return (user_id, user_role) from request headers.
#     X-User-Id   — authenticated user email (set by frontend _headers())
#     X-User-Role — role string: admin / editor / viewer
#     Defaults to ("anonymous","viewer") so curl/API docs still work.
#     PRODUCTION: replace with JWT decode.
#     """
#     uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
#     role = request.headers.get("X-User-Role", "viewer").strip().lower()
#     return uid, role

# def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
#     """Admins see all jobs. Others see only their own."""
#     if user_role == "admin":
#         return True
#     return job_data.get("user_id", "anonymous") == user_id

# # ── Live metrics store ────────────────────────────────────────────────────────
# # Updated in real-time by generator and decomposer via push.
# # Resets on server restart — tracks current session only.
# _metrics: Dict[str, Any] = {
#     # Veo API
#     "veo_submissions":      0,   # total API calls attempted
#     "veo_successes":        0,   # successful completions
#     "veo_failures":         0,   # all failures (any error)
#     "veo_rate_limit_hits":  0,   # 429 errors specifically
#     "veo_clips_generated":  0,   # clips that produced a video file
#     "veo_generation_time_s": 0.0, # cumulative generation time

#     # Bedrock decomposer
#     "decomp_nova_calls":       0,
#     "decomp_deepseek_calls":   0,
#     "decomp_deterministic":    0,
#     "decomp_input_tokens":     0,
#     "decomp_output_tokens":    0,

#     # S3
#     "s3_uploads_ok":    0,
#     "s3_uploads_fail":  0,

#     # Session
#     "session_start":    None,   # set on first job
#     "jobs_processed":   0,
# }

# # ── FastAPI ───────────────────────────────────────────────────────────────────
# app = FastAPI(
#     title       = "Veo Video Generation Platform",
#     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
#     version     = "1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
#                          "http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials = True,
#     allow_methods     = ["*"],
#     allow_headers     = ["*"],
# )

# app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # ── Routes ────────────────────────────────────────────────────────────────────

# # ── Authentication endpoint (called by NextAuth authorize) ────────────────────
# @app.post("/api/auth/verify")
# async def verify_credentials(body: dict):
#     email    = body.get("email", "")
#     password = body.get("password", "")
#     user     = user_store.verify(email, password)
#     if not user:
#         raise HTTPException(status_code=401, detail="Invalid email or password")
#     return user


# # ── User management (admin only) ──────────────────────────────────────────────
# @app.get("/api/users")
# async def list_users(request: Request):
#     _, role = _request_user(request)
#     if role != "admin":
#         raise HTTPException(status_code=403, detail="Admin access required")
#     return {"users": user_store.list_users()}


# @app.post("/api/users")
# async def create_user(request: Request, body: dict):
#     _, role = _request_user(request)
#     if role != "admin":
#         raise HTTPException(status_code=403, detail="Admin access required")
#     email    = body.get("email", "").strip()
#     password = body.get("password", "").strip()
#     name     = body.get("name", "").strip()
#     user_role= body.get("role", "editor").strip()
#     if not email or not password or not name:
#         raise HTTPException(status_code=400, detail="email, password, and name required")
#     try:
#         return {"success": True, "user": user_store.create(email, password, name, user_role)}
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @app.patch("/api/users/{email:path}")
# async def update_user(email: str, request: Request, body: dict):
#     caller_email, caller_role = _request_user(request)
#     if caller_role != "admin" and caller_email != email.lower():
#         raise HTTPException(status_code=403, detail="Admin access required")
#     if body.get("role") and caller_role != "admin":
#         raise HTTPException(status_code=403, detail="Only admins can change roles")
#     try:
#         return {"success": True, "user": user_store.update(
#             email        = email,
#             name         = body.get("name"),
#             role         = body.get("role"),
#             new_password = body.get("password"),
#         )}
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @app.delete("/api/users/{email:path}")
# async def delete_user(email: str, request: Request):
#     caller_email, caller_role = _request_user(request)
#     if caller_role != "admin":
#         raise HTTPException(status_code=403, detail="Admin access required")
#     if caller_email == email.lower():
#         raise HTTPException(status_code=400, detail="Cannot delete your own account")
#     if not user_store.delete(email):
#         raise HTTPException(status_code=404, detail=f"User '{email}' not found")
#     return {"success": True}


# # ── Internal secret middleware ────────────────────────────────────────────────
# # Rejects any request missing the correct X-Internal-Secret header.
# # This prevents direct access to the API bypassing the Next.js proxy.
# # The secret must match INTERNAL_SECRET in both veo.env and Vercel env vars.
# #
# # Exceptions (no secret required):
# #   GET  /health   — uptime monitoring
# #   POST /api/auth/verify — NextAuth calls this with the secret already

# _INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")

# @app.middleware("http")
# async def require_internal_secret(request: Request, call_next):
#     """
#     Reject requests that don't carry the correct X-Internal-Secret header.
#     Public paths: /health (monitoring), docs (local dev only).
#     """
#     path = request.url.path

#     # Always allow health check and local Swagger docs
#     public_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
#     if path in public_paths:
#         return await call_next(request)

#     # Skip secret check if INTERNAL_SECRET is not configured
#     # (local development without the secret set)
#     if not _INTERNAL_SECRET:
#         return await call_next(request)

#     incoming = request.headers.get("X-Internal-Secret", "")
#     if incoming != _INTERNAL_SECRET:
#         return JSONResponse(
#             status_code=401,
#             content={"detail": "Missing or invalid X-Internal-Secret header"},
#         )

#     return await call_next(request)


# @app.get("/health")
# async def health_check():
#     health_logger.info("Health check requested")
#     return {
#         "status":    "healthy",
#         "service":   "veo-video-generation-platform",
#         "version":   "1.0.0",
#         "timestamp": datetime.now().isoformat(),
#         "components": {
#             "veo_generator":   True,
#             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
#             "decomposer":      True,
#         },
#         "veo": {
#             "primary_model":  config.VEO_MODEL_PRIMARY,
#             "fallback_model": config.VEO_MODEL_FALLBACK,
#             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
#             "aspect_ratio":   config.VEO_ASPECT_RATIO,
#             "resolution":     config.VEO_RESOLUTION,
#             "native_audio":   True,  # Veo 3.0 always generates audio natively
#         },
#         "decomposer_mode": (
#             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
#         ),
#     }


# @app.get("/api/metrics")
# async def get_metrics():
#     """Real-time generation metrics for the Streamlit dashboard."""
#     import time
#     from datetime import datetime, timezone

#     # Derived metrics
#     total_veo   = _metrics["veo_submissions"]
#     rl_rate     = (
#         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
#         if total_veo > 0 else 0.0
#     )
#     avg_clip_s  = (
#         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
#         if _metrics["veo_clips_generated"] > 0 else 0.0
#     )

#     # Estimated cost (clips × 8s × $0.40 for primary model)
#     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
#     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

#     return {
#         "session_start":        _metrics["session_start"],
#         "jobs_processed":       _metrics["jobs_processed"],

#         "veo": {
#             "submissions":      _metrics["veo_submissions"],
#             "successes":        _metrics["veo_successes"],
#             "failures":         _metrics["veo_failures"],
#             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
#             "rate_limit_pct":   rl_rate,
#             "clips_generated":  _metrics["veo_clips_generated"],
#             "avg_clip_time_s":  avg_clip_s,
#             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
#         },

#         "decomposer": {
#             "nova_calls":        _metrics["decomp_nova_calls"],
#             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
#             "deterministic":     _metrics["decomp_deterministic"],
#             "input_tokens":      _metrics["decomp_input_tokens"],
#             "output_tokens":     _metrics["decomp_output_tokens"],
#             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
#         },

#         "s3": {
#             "uploads_ok":   _metrics["s3_uploads_ok"],
#             "uploads_fail": _metrics["s3_uploads_fail"],
#         },

#         "cost_estimate": {
#             "usd": round(est_cost_usd, 4),
#             "inr": round(est_cost_inr, 2),
#             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
#         },
#     }


# @app.get("/api/jobs")
# async def list_jobs(request: Request):
#     user_id, user_role = _request_user(request)
#     visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
#     job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
#     return {
#         "jobs": [
#             {
#                 "job_id":            job_id,
#                 "original_filename": jd.get("original_filename", ""),
#                 "status":            jd.get("status", "processing"),
#                 "total_prompts":     jd.get("total_prompts", 0),
#                 "completed_prompts": jd.get("completed_prompts", 0),
#                 "failed_prompts":    jd.get("failed_prompts", 0),
#                 "progress_percent":  jd.get("progress_percent", 0.0),
#                 "created_at":        jd.get("created_at", ""),
#                 "generation_status": jd.get("generation_status", "Queued"),
#                 "user_id":           jd.get("user_id", "anonymous"),
#             }
#             for job_id, jd in visible.items()
#         ]
#     }


# @app.get("/api/jobs/{job_id}")
# async def get_job(job_id: str, request: Request):
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     user_id, user_role = _request_user(request)
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied")

#     job_data = jobs[job_id]
#     results  = job_data.get("results", {})

#     prompts_out = []
#     for i, prompt_data in enumerate(job_data.get("prompts", [])):
#         r = results.get(str(i), {})
#         # video_url: may be S3 URL after upload (for distribution)
#         # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
#         raw_video_url = r.get("video_url")
#         raw_local_url = r.get("local_video_url")
#         # Ensure local_video_url is a proper /videos/ route, not an absolute path
#         if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
#             from pathlib import Path as _Path
#             raw_local_url = f"/videos/{_Path(raw_local_url).name}"
#         # If no local URL stored but video_url is already a local route, use it
#         if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
#             raw_local_url = raw_video_url
#         prompts_out.append({
#             "prompt_id":        f"prompt_{i + 1}",
#             "prompt_text":      prompt_data.get("text", ""),
#             "row_number":       i + 1,
#             "duration":         prompt_data.get("duration", 8),
#             "status":           r.get("status", "processing"),
#             "video_url":        raw_video_url,    # S3 or local route
#             "local_video_url":  raw_local_url,    # always /videos/... for player
#             "duration_seconds": r.get("duration_seconds"),
#             "stitched":         r.get("stitched", False),
#             "clips_count":      r.get("clips_count", 0),
#             "clip_urls":        r.get("clip_urls", []),
#             "model_used":       r.get("model_used", ""),
#             "has_native_audio": r.get("has_native_audio", False),
#             "error_message":    r.get("error_message"),
#             "generation_time_seconds": r.get("generation_time_seconds"),
#         })

#     return {
#         "job_id":       job_id,
#         "status":       job_data.get("status", "processing"),
#         "mode":         job_data.get("mode", "full"),
#         "hold_duration":job_data.get("hold_duration", 5.0),
#         "clip_duration":job_data.get("clip_duration", 8),
#         "no_text":      job_data.get("no_text", False),
#         "no_speech":    job_data.get("no_speech", False),
#         "summary": {
#             "job_id":            job_id,
#             "original_filename": job_data.get("original_filename", ""),
#             "status":            job_data.get("status", "processing"),
#             "total_prompts":     job_data.get("total_prompts", 0),
#             "completed_prompts": job_data.get("completed_prompts", 0),
#             "failed_prompts":    job_data.get("failed_prompts", 0),
#             "progress_percent":  job_data.get("progress_percent", 0.0),
#             "total_processing_time": job_data.get("total_processing_time"),
#         },
#         "prompts": prompts_out,
#     }


# @app.post("/api/upload")
# async def upload_excel(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(...),
#     mode: str = "full",           # "full" | "short_span" | "short_span_image"
#     clip_duration: float = 2.0,   # short_span only: seconds per clip (2–8)
#     hold_duration: float = 5.0,   # short_span_image only: seconds per image (2 or 5)
#     no_text: bool = False,        # inject no-text guardrail into all prompts
#     no_speech: bool = False,      # inject no-speech guardrail into all prompts
# ):
#     """
#     Accept an Excel/CSV file and start Veo generation as a background job.

#     Required Excel columns:  prompt, duration
#     Optional Excel columns:  task_type, priority
#     """
#     upload_id = str(uuid.uuid4())[:8]
#     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

#     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     _is_short_span = mode in ("short_span", "short_span_image")

#     if _is_short_span:
#         is_valid, errors = validate_short_span_excel(str(temp_path))
#     else:
#         is_valid, errors = validate_excel_file(str(temp_path))

#     if not is_valid:
#         temp_path.unlink(missing_ok=True)
#         raise HTTPException(
#             status_code=400,
#             detail=f"Excel validation failed: {'; '.join(errors)}",
#         )

#     if _is_short_span:
#         job_data = create_short_span_job(
#             file_path       = str(temp_path),
#             clip_duration_s = clip_duration,
#             aspect_ratio    = "9:16",
#         )
#     else:
#         job_data = create_job_from_excel(
#             file_path  = str(temp_path),
#             platforms  = ["veo"],
#             audio_mode = "platform_native",
#         )
#     job_id = job_data["job_id"]

#     user_id, user_role = _request_user(request)

#     jobs[job_id]                      = job_data
#     jobs[job_id]["temp_file"]         = str(temp_path)
#     jobs[job_id]["upload_id"]         = upload_id
#     jobs[job_id]["original_filename"] = file.filename
#     jobs[job_id]["user_id"]           = user_id
#     jobs[job_id]["mode"]              = mode
#     jobs[job_id]["clip_duration"]     = clip_duration
#     jobs[job_id]["hold_duration"]     = hold_duration
#     jobs[job_id]["no_text"]           = no_text
#     jobs[job_id]["no_speech"]         = no_speech

#     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

#     background_tasks.add_task(run_generation_job, job_id)

#     return {
#         "success":       True,
#         "job_id":        job_id,
#         "upload_id":     upload_id,
#         "prompts_count": job_data["total_prompts"],
#         "veo_model":     config.VEO_MODEL_PRIMARY,
#         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
#         "native_audio":  True,  # Veo 3.0 always generates audio natively
#         "stitching":     video_stitcher.ffmpeg_available,
#         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
#     }


# # ── Concurrency config ────────────────────────────────────────────────────────

# # Max prompts running simultaneously within one job.
# # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # Each prompt with 4 clips = 4 sequential API calls.
# # At concurrency=2, clip submissions from two prompts can overlap
# # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # on the free tier. Increase if you have a paid quota.
# _PROMPT_CONCURRENCY = 1


# # ── Background generation job ─────────────────────────────────────────────────

# async def run_generation_job(job_id: str) -> None:
#     """
#     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

#     Design:
#     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
#     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
#     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
#     - Results are stored by index key str(i) — API schema unchanged.
#     - Progress percent is updated after each prompt completes (order-independent).
#     """
#     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
#     start_time   = time.time()

#     # Track session start on first job
#     if _metrics["session_start"] is None:
#         from datetime import datetime, timezone
#         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
#     _metrics["jobs_processed"] += 1
#     job          = jobs[job_id]
#     prompts_data = job["prompts"]
#     total        = len(prompts_data)

#     jobs[job_id]["results"]            = {}
#     jobs[job_id]["completed_prompts"]  = 0
#     jobs[job_id]["failed_prompts"]     = 0
#     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

#     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
#     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

#     async def _run_prompt(i: int, prompt_data: dict) -> None:
#         """
#         Semaphore-gated coroutine for a single prompt.
#         Clips within this prompt run sequentially inside generate_for_prompt().
#         """
#         prompt_text = prompt_data["text"]
#         duration    = prompt_data["duration"]

#         async with semaphore:
#             if job_id not in jobs:
#                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
#                 return

#             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
#             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
#             prompt_start = time.time()

#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = i,
#             )

#             elapsed = time.time() - prompt_start

#         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
#         async with state_lock:
#             jobs[job_id]["results"][str(i)] = result

#             # ── Push result stats into live metrics ───────────────────────────
#             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
#             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
#             # Decomposer token tracking
#             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
#             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
#             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
#             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
#             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
#             # S3 tracking
#             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
#             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

#             if result.get("status") in ("completed", "partial"):
#                 jobs[job_id]["completed_prompts"] += 1
#                 _metrics["veo_successes"]       += 1
#                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
#                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
#                 generation_logger.info(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
#                     f"-> {result.get('video_url')} "
#                     f"({'stitched' if result.get('stitched') else 'single'}, "
#                     f"{result.get('clips_count', 1)} clip(s))"
#                 )
#                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
#             else:
#                 jobs[job_id]["failed_prompts"] += 1
#                 _metrics["veo_failures"] += 1
#                 generation_logger.error(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
#                     f"{result.get('error_message')}"
#                 )

#             done_so_far = (
#                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
#             )
#             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
#             jobs[job_id]["generation_status"]  = (
#                 f"Running — {done_so_far}/{total} complete"
#             )

#     # ── Launch based on mode ──────────────────────────────────────────────────
#     mode         = job.get("mode", "full")
#     no_text      = job.get("no_text", False)
#     no_speech    = job.get("no_speech", False)
#     clip_dur     = job.get("clip_duration", 2.0)

#     if mode == "short_span":
#         # ── Short Span Clips: all rows = one sequence, no decomposition ───────
#         # Inject guardrails into prompt text before passing to orchestrator
#         _NO_TEXT_G = (
#             "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#             "subtitles, watermarks, or UI labels anywhere in the frame."
#         )
#         _NO_SPEECH_G = (
#             "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
#         )
#         enriched = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:   parts.append(_NO_TEXT_G)
#             if no_speech: parts.append(_NO_SPEECH_G)
#             parts.append(pd.get("text", ""))
#             enriched.append({**pd, "text": " ".join(parts)})

#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN mode — {len(enriched)} clip(s) "
#             f"at {clip_dur}s each, no_text={no_text}, no_speech={no_speech}"
#         )
#         result = await ss_orchestrator.run(
#             prompts         = enriched,
#             job_id          = job_id,
#             clip_duration_s = clip_dur,
#             no_text         = False,   # guardrails already injected into enriched
#             no_speech       = False,
#             aspect_ratio    = job.get("aspect_ratio", "9:16"),
#         )
#         # Store as single result at index 0 and mark job done
#         async with state_lock:
#             jobs[job_id]["results"]["0"]          = result
#             jobs[job_id]["completed_prompts"]     = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]        = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]      = 100.0
#             jobs[job_id]["generation_status"]     = "All prompts processed"
#             _metrics["veo_clips_generated"]      += result.get("clips_count", 0)
#             _metrics["veo_generation_time_s"]    += result.get("generation_time_seconds", 0) or 0
#             if result.get("status") in ("completed", "partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"] += 1

#     elif mode == "short_span_image":
#         if img_orchestrator is None:
#             generation_logger.error(f"[JOB_{job_id}] Short Span Images: GOOGLE_API_KEY not set")
#             async with state_lock:
#                 jobs[job_id]["status"] = "failed"
#                 jobs[job_id]["generation_status"] = "GOOGLE_API_KEY missing"
#                 jobs[job_id]["progress_percent"] = 100.0
#             return
#         hold_dur     = job.get("hold_duration", 5.0)
#         aspect_ratio = job.get("aspect_ratio", "9:16")
#         enriched_imgs = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:
#                 parts.append("No text, captions, titles, watermarks, or labels in the image.")
#             parts.append(pd.get("text", ""))
#             enriched_imgs.append({**pd, "text": " ".join(parts)})
#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN_IMAGE — {len(enriched_imgs)} images at {hold_dur}s"
#         )
#         result = await img_orchestrator.run(
#             prompts         = enriched_imgs,
#             job_id          = job_id,
#             hold_duration_s = hold_dur,
#             aspect_ratio    = aspect_ratio,
#             no_text         = False,
#         )
#         async with state_lock:
#             jobs[job_id]["results"]["0"]      = result
#             jobs[job_id]["completed_prompts"] = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]    = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]  = 100.0
#             jobs[job_id]["generation_status"] = "All images processed"
#             if result.get("status") in ("completed","partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"]  += 1

#     else:
#         # ── Full Length Videos (existing pipeline) ────────────────────────────
#         # Inject no_text/no_speech guardrails into prompt text if requested
#         if no_text or no_speech:
#             _NO_TEXT_G = (
#                 "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#                 "subtitles, watermarks, or UI labels anywhere in the frame."
#             )
#             _NO_SPEECH_G = (
#                 "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
#             )
#             for pd in prompts_data:
#                 parts = []
#                 if no_text:   parts.append(_NO_TEXT_G)
#                 if no_speech: parts.append(_NO_SPEECH_G)
#                 parts.append(pd.get("text", ""))
#                 pd["text"] = " ".join(parts)

#         tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
#         await asyncio.gather(*tasks, return_exceptions=True)

#     # ── Finalise ──────────────────────────────────────────────────────────────
#     total_elapsed = time.time() - start_time
#     failed_count  = jobs[job_id].get("failed_prompts", 0)

#     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
#     jobs[job_id]["generation_status"]     = "All prompts processed"
#     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

#     generation_logger.info(
#         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
#         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
#     )

#     try:
#         temp_file = jobs[job_id].get("temp_file")
#         if temp_file:
#             Path(temp_file).unlink(missing_ok=True)
#     except Exception as e:
#         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # ── Rerun single prompt ───────────────────────────────────────────────────────

# @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
#     """
#     Re-run a single prompt within an existing job.

#     Flow:
#     - Validates job and prompt exist
#     - Marks the result as "processing" immediately (UI picks this up on next poll)
#     - Schedules a background task that calls the orchestrator for just that one prompt
#     - Returns immediately so the UI is never blocked

#     Used by: rerun button on each video card in the frontend.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job = jobs[job_id]
#     prompts_data = job.get("prompts", [])

#     if prompt_index < 0 or prompt_index >= len(prompts_data):
#         raise HTTPException(
#             status_code=400,
#             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
#         )

#     prompt_data = prompts_data[prompt_index]

#     # Mark as processing immediately so frontend shows skeleton
#     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
#         "status": "processing",
#         "video_url": None,
#     }
#     # Reset counters to reflect the rerun
#     jobs[job_id]["status"] = "processing"

#     generation_logger.info(
#         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
#         f"'{prompt_data.get('text', '')[:60]}...'"
#     )

#     async def _rerun():
#         try:
#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = prompt_index,
#             )
#             jobs[job_id]["results"][str(prompt_index)] = result

#             # Recompute job-level status from all results
#             all_results = jobs[job_id].get("results", {})
#             total = len(prompts_data)
#             completed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") in ("completed", "partial")
#             )
#             failed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "failed"
#             )
#             processing = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "processing"
#             )

#             if processing == 0:
#                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
#                 jobs[job_id]["completed_prompts"] = completed
#                 jobs[job_id]["failed_prompts"]    = failed
#                 jobs[job_id]["progress_percent"]  = 100.0

#             generation_logger.info(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
#                 f"status={result.get('status')}"
#             )
#         except Exception as e:
#             jobs[job_id]["results"][str(prompt_index)] = {
#                 "status": "failed",
#                 "error_message": str(e),
#             }
#             generation_logger.error(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
#             )

#     # Soft-delete the old S3 video before rerunning
#     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
#     if veo_s3.enabled:
#         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
#         if moved:
#             generation_logger.info(
#                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
#             )
#         else:
#             generation_logger.warning(
#                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
#             )

#     background_tasks.add_task(_rerun)

#     return {
#         "status":        "accepted",
#         "job_id":        job_id,
#         "prompt_index":  prompt_index,
#         "message":       f"Rerun started for prompt {prompt_index + 1}",
#     }


# # ── YouTube upload queue ──────────────────────────────────────────────────────
# # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# #                                tags, local_path, s3_url, status, youtube_url } }
# # "approved" = waiting to upload, "uploading" = in progress,
# # "uploaded" = done, "failed" = error
# youtube_queue: Dict[str, Any] = {}


# import veo_youtube as _yt


# @app.get("/api/youtube/status")
# async def youtube_status():
#     """Check if YouTube is configured and authenticated."""
#     return {
#         "configured":    _yt.is_configured(),
#         "authenticated": _yt.is_authenticated(),
#         "secrets_file":  str(_yt.SECRETS_FILE),
#     }


# @app.post("/api/youtube/auth")
# async def youtube_auth():
#     """
#     Trigger the OAuth browser flow.
#     Opens a browser tab — user logs in, approves, token is saved.
#     Returns immediately after auth completes.
#     """
#     try:
#         _yt.get_authenticated_service()
#         return {"status": "authenticated"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# async def approve_video(job_id: str, prompt_index: int, request: Request):
#     """
#     Approve a completed video — adds it to the YouTube upload queue.

#     Auto-generates title/description/tags from the prompt.
#     User edits these in the UI before triggering upload.

#     Returns the queue_id so the frontend can reference this queue entry.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job      = jobs[job_id]
#     prompts  = job.get("prompts", [])
#     results  = job.get("results", {})

#     if prompt_index < 0 or prompt_index >= len(prompts):
#         raise HTTPException(status_code=400, detail="prompt_index out of range")

#     result = results.get(str(prompt_index), {})
#     if result.get("status") != "completed":
#         raise HTTPException(status_code=400, detail="Video is not completed yet")

#     prompt_text = prompts[prompt_index].get("text", "")
#     video_url   = result.get("video_url", "")
#     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
#     s3_url      = result.get("s3_url", "")

#     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
#     if local_path and local_path.startswith("/videos/"):
#         from pathlib import Path as _Path
#         output_dir = _Path(__file__).parent / "outputs" / "videos"
#         local_path = str(output_dir / _Path(local_path).name)

#     metadata  = _yt.generate_metadata(prompt_text)
#     queue_id  = f"q_{job_id}_{prompt_index}"

#     youtube_queue[queue_id] = {
#         "queue_id":     queue_id,
#         "job_id":       job_id,
#         "prompt_index": prompt_index,
#         "prompt_text":  prompt_text[:120],
#         "local_path":   local_path,
#         "s3_url":       s3_url,
#         "video_url":    video_url,
#         "title":        metadata["title"],
#         "description":  metadata["description"],
#         "tags":         metadata["tags"],
#         "status":       "approved",
#         "youtube_url":  None,
#         "error":        None,
#     }

#     generation_logger.info(
#         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
#     )

#     return youtube_queue[queue_id]


# @app.get("/api/youtube/queue")
# async def get_youtube_queue():
#     """Return all items in the upload queue."""
#     return {"queue": list(youtube_queue.values())}


# @app.patch("/api/youtube/queue/{queue_id}")
# async def update_queue_item(queue_id: str, body: dict):
#     """
#     Update editable metadata for a queued video before upload.
#     Accepts: { title, description, tags }
#     """
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

#     item = youtube_queue[queue_id]
#     if item["status"] not in ("approved", "failed"):
#         raise HTTPException(
#             status_code=400,
#             detail=f"Cannot edit item with status '{item['status']}'"
#         )

#     if "title" in body:
#         item["title"]       = str(body["title"])[:100]
#     if "description" in body:
#         item["description"] = str(body["description"])[:5000]
#     if "tags" in body and isinstance(body["tags"], list):
#         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

#     return item


# @app.post("/api/youtube/upload")
# async def upload_to_youtube(background_tasks: BackgroundTasks):
#     """
#     Upload ALL approved queue items to YouTube.

#     Runs in background — returns immediately.
#     Poll /api/youtube/queue to track per-item status.
#     """
#     approved = [
#         item for item in youtube_queue.values()
#         if item["status"] == "approved"
#     ]

#     if not approved:
#         raise HTTPException(status_code=400, detail="No approved videos in queue")

#     if not _yt.is_configured():
#         raise HTTPException(
#             status_code=503,
#             detail="YouTube not configured — youtube_client_secrets.json missing"
#         )

#     async def _upload_all():
#         for item in approved:
#             qid = item["queue_id"]
#             youtube_queue[qid]["status"] = "uploading"
#             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

#             result = await asyncio.get_event_loop().run_in_executor(
#                 None,
#                 lambda i=item: _yt.upload_video(
#                     local_path  = i["local_path"],
#                     title       = i["title"],
#                     description = i["description"],
#                     tags        = i["tags"],
#                     privacy     = "public",
#                 ),
#             )

#             if result["status"] == "uploaded":
#                 youtube_queue[qid]["status"]      = "uploaded"
#                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
#                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
#                 generation_logger.info(
#                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
#                 )
#             else:
#                 youtube_queue[qid]["status"] = "failed"
#                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
#                 generation_logger.error(
#                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
#                 )

#     background_tasks.add_task(_upload_all)

#     return {
#         "status":  "started",
#         "count":   len(approved),
#         "message": f"Uploading {len(approved)} video(s) to YouTube",
#     }


# @app.delete("/api/youtube/queue/{queue_id}")
# async def remove_from_queue(queue_id: str):
#     """Remove an item from the upload queue (before it's uploaded)."""
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
#     if youtube_queue[queue_id]["status"] == "uploading":
#         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
#     del youtube_queue[queue_id]
#     return {"status": "removed", "queue_id": queue_id}


# # ── Entry point ───────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     s = logging.getLogger("STARTUP")
#     s.info("=" * 70)
#     s.info("Veo Video Generation Platform v1.0.0")
#     s.info("=" * 70)
#     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
#     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
#     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
#     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
#     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     s.info("Endpoints:")
#     s.info("   API    : http://localhost:8100")
#     s.info("   Docs   : http://localhost:8100/docs")
#     s.info("   Health : http://localhost:8100/health")
#     s.info("=" * 70)

#     uvicorn.run(
#         "veo_main:app",
#         host      = "0.0.0.0",
#         port      = 8100,
#         reload    = True,
#         log_level = "info",
#     )

















# #!/usr/bin/env python3
# """
# veo_main.py — Veo Video Generation Platform
# ════════════════════════════════════════════

# Standalone FastAPI service. Accepts Excel uploads, generates videos via
# Google Veo 3.1 (video + audio in one pass), stitches multi-clip outputs
# via FFmpeg, and serves results as downloadable MP4 files.

# Veo 3.1 generates video and audio natively from the text prompt — no
# post-processing or external audio service is required.

# Endpoints:
#   GET  /health                → system status
#   POST /api/upload            → accept .xlsx/.csv, start background job
#   GET  /api/jobs              → list all jobs
#   GET  /api/jobs/{job_id}     → job details + per-prompt results
#   GET  /videos/{filename}     → serve generated MP4 files

# Run:
#   python veo_main.py
#   -> http://localhost:8100
#   -> http://localhost:8100/docs

# Port 8100 avoids collision with the Nova/Runway service on 8000.
# """

# import asyncio
# import logging
# import os
# import sys
# import time
# import json
# import uuid
# from datetime import datetime, timezone
# from pathlib import Path
# from typing import Any, Dict, List, Optional, Tuple

# import uvicorn
# from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.responses import JSONResponse
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level   = logging.INFO,
#     format  = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
#     datefmt = "%Y-%m-%d %H:%M:%S",
# )
# main_logger       = logging.getLogger("MAIN")
# upload_logger     = logging.getLogger("UPLOAD")
# generation_logger = logging.getLogger("GENERATION")
# progress_logger   = logging.getLogger("PROGRESS")
# job_logger        = logging.getLogger("JOB_MANAGER")
# health_logger     = logging.getLogger("HEALTH")

# # ── Local imports ─────────────────────────────────────────────────────────────
# _HERE = Path(__file__).resolve().parent
# sys.path.insert(0, str(_HERE))

# try:
#     from veo_config import veo_config as config
#     main_logger.info("OK veo_config loaded")
#     main_logger.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     main_logger.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     main_logger.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
# except ImportError as e:
#     main_logger.critical(f"[CONFIG_ERROR] {e}")
#     sys.exit(1)

# try:
#     from veo_excel_processor import create_job_from_excel, validate_excel_file
#     from veo_short_span_excel_processor import validate_short_span_excel, create_short_span_job
#     from veo_users import UserStore
#     from veo_refiner import PromptRefiner
#     main_logger.info("OK veo_excel_processor + veo_short_span_excel_processor loaded")
# except ImportError as e:
#     main_logger.critical(f"veo_excel_processor import failed: {e}")
#     sys.exit(1)

# # Directories
# _BASE_DIR  = _HERE
# output_dir = _BASE_DIR / config.OUTPUT_DIR
# temp_dir   = _BASE_DIR / config.TEMP_DIR
# output_dir.mkdir(parents=True, exist_ok=True)
# temp_dir.mkdir(parents=True, exist_ok=True)
# (output_dir / "decompositions").mkdir(exist_ok=True)

# try:
#     from video_stitcher import VideoStitcher
#     from prompt_decomposer import PromptDecomposer

#     video_stitcher = VideoStitcher(
#         output_dir            = output_dir,
#         aws_access_key_id     = "",
#         aws_secret_access_key = "",
#         bucket                = "",
#         region                = "",
#     )
#     prompt_decomposer = PromptDecomposer(
#         aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#         region                = config.AWS_DEFAULT_REGION,
#     )
#     main_logger.info("OK VideoStitcher + PromptDecomposer loaded")
#     main_logger.info(f"   FFmpeg stitching : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     main_logger.info(
#         f"   Decomposer : "
#         f"{'Bedrock (Nova 2 Lite -> DeepSeek R1)' if prompt_decomposer._bedrock_client else 'deterministic fallback (no AWS creds)'}"
#     )
# except ImportError as e:
#     main_logger.critical(f"VideoStitcher/PromptDecomposer import failed: {e}")
#     sys.exit(1)

# veo_generator = None
# try:
#     from veo_generator import VeoGenerator
#     if config.GOOGLE_API_KEY:
#         veo_generator = VeoGenerator(
#             api_key              = config.GOOGLE_API_KEY,
#             output_dir           = output_dir,
#             model_primary        = config.VEO_MODEL_PRIMARY,
#             model_fallback       = config.VEO_MODEL_FALLBACK,
#             clip_duration        = config.VEO_CLIP_DURATION_SECONDS,
#             aspect_ratio         = config.VEO_ASPECT_RATIO,
#             resolution           = config.VEO_RESOLUTION,
#             generate_audio       = config.VEO_GENERATE_AUDIO,
#             sample_count         = config.VEO_SAMPLE_COUNT,
#             polling_interval_s   = config.VEO_POLLING_INTERVAL_SECONDS,
#             max_polling_attempts = config.VEO_MAX_POLLING_ATTEMPTS,
#         )
#         main_logger.info("OK VeoGenerator initialised")
#     else:
#         main_logger.critical("GOOGLE_API_KEY not set — add it to .env")
# except ImportError as e:
#     main_logger.critical(f"VeoGenerator import failed: {e} — run: pip install google-genai")

# if not veo_generator:
#     main_logger.critical("Cannot start without a Veo generator. Exiting.")
#     sys.exit(1)

# from veo_s3 import VeoS3Client
# veo_s3 = VeoS3Client(
#     bucket = os.getenv("VEO_S3_BUCKET", ""),
#     region = os.getenv("VEO_S3_REGION", "us-east-1"),
# )
# main_logger.info(f"OK VeoS3Client — {'enabled' if veo_s3.enabled else 'disabled (local only)'}")

# from veo_orchestrator import VeoOrchestrator
# from veo_short_span_orchestrator import ShortSpanOrchestrator
# try:
#     from veo_short_span_image_orchestrator import ShortSpanImageOrchestrator
#     from veo_imagen_generator import ImagenGenerator
#     _IMAGEN_AVAILABLE = True
# except ImportError:
#     ShortSpanImageOrchestrator = None  # type: ignore
#     ImagenGenerator = None             # type: ignore
#     _IMAGEN_AVAILABLE = False
# veo_orchestrator = VeoOrchestrator(
#     generator     = veo_generator,
#     stitcher      = video_stitcher,
#     decomposer    = prompt_decomposer,
#     clip_duration = config.VEO_CLIP_DURATION_SECONDS,
#     s3_client     = veo_s3,
# )
# main_logger.info("OK VeoOrchestrator initialised")

# # ── User store ────────────────────────────────────────────────────────────────
# user_store = UserStore()
# user_store.init()
# main_logger.info(f"OK UserStore — {user_store.count()} user(s)")

# # ── Prompt refiner ────────────────────────────────────────────────────────────
# _refiner_mode = int(os.getenv("REFINER_MODE", "1"))
# prompt_refiner = PromptRefiner(
#     aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#     aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#     region                = config.AWS_DEFAULT_REGION,
#     mode                  = _refiner_mode,
# )
# main_logger.info(f"OK PromptRefiner — mode={_refiner_mode}")

# ss_orchestrator = ShortSpanOrchestrator(
#     generator  = veo_generator,
#     stitcher   = video_stitcher,
#     s3_client  = veo_s3,
# )
# main_logger.info("OK ShortSpanOrchestrator initialised")

# # ── Short Span Image orchestrator — same GOOGLE_API_KEY as Veo ───────────────
# _imagen_model = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-001")
# if _IMAGEN_AVAILABLE and config.GOOGLE_API_KEY:
#     imagen_generator = ImagenGenerator(
#         api_key    = config.GOOGLE_API_KEY,
#         model_id   = _imagen_model,
#         output_dir = config.OUTPUT_DIR,
#     )
#     img_orchestrator = ShortSpanImageOrchestrator(
#         imagen_generator = imagen_generator,
#         stitcher         = video_stitcher,
#         s3_client        = veo_s3,
#     )
#     main_logger.info(f"OK ShortSpanImageOrchestrator initialised (model={_imagen_model})")
# else:
#     imagen_generator = None
#     img_orchestrator = None
#     if not _IMAGEN_AVAILABLE:
#         main_logger.warning(
#             "veo_imagen_generator / veo_short_span_image_orchestrator not found — "
#             "Short Span Images disabled. Copy both files to the veo/ folder to enable."
#         )
#     else:
#         main_logger.warning("GOOGLE_API_KEY not set — Short Span Images disabled")

# # ── Job store ─────────────────────────────────────────────────────────────────
# jobs: Dict[str, Any] = {}

# # ── Per-request user identity ─────────────────────────────────────────────────
# def _request_user(request: Request) -> tuple:
#     """
#     Return (user_id, user_role) from request headers.
#     X-User-Id   — authenticated user email (set by frontend _headers())
#     X-User-Role — role string: admin / editor / viewer
#     Defaults to ("anonymous","viewer") so curl/API docs still work.
#     PRODUCTION: replace with JWT decode.
#     """
#     uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
#     role = request.headers.get("X-User-Role", "viewer").strip().lower()
#     return uid, role

# def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
#     """Admins see all jobs. Others see only their own."""
#     if user_role == "admin":
#         return True
#     return job_data.get("user_id", "anonymous") == user_id

# # ── Live metrics store ────────────────────────────────────────────────────────
# # Updated in real-time by generator and decomposer via push.
# # Resets on server restart — tracks current session only.
# _metrics: Dict[str, Any] = {
#     # Veo API
#     "veo_submissions":      0,   # total API calls attempted
#     "veo_successes":        0,   # successful completions
#     "veo_failures":         0,   # all failures (any error)
#     "veo_rate_limit_hits":  0,   # 429 errors specifically
#     "veo_clips_generated":  0,   # clips that produced a video file
#     "veo_generation_time_s": 0.0, # cumulative generation time

#     # Bedrock decomposer
#     "decomp_nova_calls":       0,
#     "decomp_deepseek_calls":   0,
#     "decomp_deterministic":    0,
#     "decomp_input_tokens":     0,
#     "decomp_output_tokens":    0,

#     # S3
#     "s3_uploads_ok":    0,
#     "s3_uploads_fail":  0,

#     # Session
#     "session_start":    None,   # set on first job
#     "jobs_processed":   0,
# }

# # ── FastAPI ───────────────────────────────────────────────────────────────────
# app = FastAPI(
#     title       = "Veo Video Generation Platform",
#     description = "Google Veo 3.1 — text prompt to video+audio via Excel batch upload",
#     version     = "1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins     = ["http://localhost:8501", "http://127.0.0.1:8501",
#                          "http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials = True,
#     allow_methods     = ["*"],
#     allow_headers     = ["*"],
# )

# app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


# # ── Routes ────────────────────────────────────────────────────────────────────

# # ── Prompt refinement ────────────────────────────────────────────────────────────
# @app.post("/api/refine")
# async def refine_prompts(
#     request:          Request,
#     file:             UploadFile = File(...),
#     mode:             str   = "full",
#     clip_duration:    float = 8.0,
#     hold_duration:    float = 5.0,
#     no_text:          bool  = False,
#     no_speech:        bool  = False,
#     refiner_mode_override: Optional[int] = None,   # 1 or 2 — overrides REFINER_MODE env
# ):
#     """
#     Step 1 of the two-step generation flow.
#     Runs LLM refinement on all Excel rows, returns structured preview.
#     Does NOT start generation — waits for /api/jobs/{id}/approve.
#     """
#     user_id, _ = _request_user(request)
#     upload_id  = str(uuid.uuid4())[:8]

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(400, "Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(413, "File too large (max 10 MB)")

#     temp_path = temp_dir / f"refine_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     _is_short_span = mode in ("short_span", "short_span_image")

#     try:
#         if _is_short_span:
#             is_valid, errors = validate_short_span_excel(str(temp_path))
#         else:
#             is_valid, errors = validate_excel_file(str(temp_path))
#         if not is_valid:
#             temp_path.unlink(missing_ok=True)
#             raise HTTPException(400, f"Excel validation failed: {'; '.join(errors)}")

#         if _is_short_span:
#             job_data = create_short_span_job(str(temp_path), clip_duration, "9:16")
#         else:
#             job_data = create_job_from_excel(str(temp_path), platforms=["veo"], audio_mode="platform_native")
#     finally:
#         temp_path.unlink(missing_ok=True)

#     # Determine clips per row from job_data
#     job_id   = job_data["job_id"]
#     prompts  = job_data.get("prompts", [])
#     now      = datetime.now(timezone.utc).isoformat()

#     # Store job in awaiting_approval state
#     jobs[job_id] = {
#         **job_data,
#         "status":             "awaiting_approval",
#         "mode":               mode,
#         "clip_duration":      clip_duration,
#         "hold_duration":      hold_duration,
#         "no_text":            no_text,
#         "no_speech":          no_speech,
#         "user_id":            user_id,
#         "created_at":         now,
#         "generation_status":  "Awaiting approval",
#         "progress_percent":   0.0,
#         "completed_prompts":  0,
#         "failed_prompts":     0,
#         "results":            {},
#         "refined_rows":       [],   # populated below
#     }

#     # Run refinement per row
#     active_mode = refiner_mode_override or _refiner_mode
#     refined_rows = []

#     for idx, prompt_data in enumerate(prompts):
#         raw_text   = (prompt_data.get("text") or "").strip()
#         row_dur    = int(prompt_data.get("duration", clip_duration))
#         n_clips_row = max(1, row_dur // 8) if mode == "full" else 1
#         clip_durs  = [8] * n_clips_row if mode == "full" else [int(clip_duration)]

#         try:
#             # Use override mode if specified (per-request)
#             if refiner_mode_override and refiner_mode_override != _refiner_mode:
#                 from veo_refiner import PromptRefiner as _PR
#                 override_refiner = _PR(
#                     aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
#                     aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
#                     region                = config.AWS_DEFAULT_REGION,
#                     mode                  = refiner_mode_override,
#                 )
#                 refined = override_refiner.refine(raw_text, n_clips_row, clip_durs)
#             else:
#                 refined = prompt_refiner.refine(raw_text, n_clips_row, clip_durs)
#         except Exception as e:
#             main_logger.error(f"[REFINE] Row {idx + 1} failed: {e}")
#             refined = {
#                 "refined_prompt":     raw_text,
#                 "mythology_detected": False,
#                 "warnings":           [f"Refinement failed: {str(e)}"],
#                 "structured":         {"scene":"","characters":"","camera":"","narration_lines":[],"lighting":"","mythology_notes":""},
#                 "clips":              [],
#             }

#         refined_rows.append({
#             "row_index":         idx,
#             "original_prompt":   raw_text,
#             "refined_prompt":    refined["refined_prompt"],
#             "mythology_detected":refined["mythology_detected"],
#             "warnings":          refined["warnings"],
#             "structured":        refined["structured"],
#             "clips":             refined["clips"],
#             "row_number":        prompt_data.get("row_number", idx + 2),
#             "duration":          row_dur,
#             "n_clips":           n_clips_row,
#             # Mode 2 flag: clips are already decomposed, skip decomposer on approve
#             "clips_ready":       len(refined["clips"]) == n_clips_row and active_mode == 2,
#         })

#     jobs[job_id]["refined_rows"] = refined_rows
#     main_logger.info(f"[REFINE] job={job_id} rows={len(refined_rows)} mode={active_mode}")

#     return {
#         "job_id":       job_id,
#         "total_rows":   len(refined_rows),
#         "mode":         mode,
#         "refiner_mode": active_mode,
#         "rows":         refined_rows,
#     }


# @app.post("/api/jobs/{job_id}/approve")
# async def approve_job(
#     job_id: str,
#     request: Request,
#     background_tasks: BackgroundTasks,
#     body: dict = Body(default={}),
# ):
#     """
#     Step 2 of the two-step flow. User has reviewed and approved prompts.
#     Accepts final (possibly edited) prompt per row, then starts generation.
#     """
#     user_id, _ = _request_user(request)

#     if job_id not in jobs:
#         raise HTTPException(404, f"Job '{job_id}' not found")

#     job = jobs[job_id]
#     if job.get("status") != "awaiting_approval":
#         raise HTTPException(400, f"Job is not awaiting approval (status={job.get('status')})")

#     # Apply any user edits from the overlay
#     approved_rows: List[Dict] = body.get("approved_rows", [])
#     for row in approved_rows:
#         idx = row.get("row_index")
#         final_prompt = row.get("final_prompt", "").strip()
#         if final_prompt and idx is not None:
#             # Update the prompt in job prompts list
#             if idx < len(job.get("prompts", [])):
#                 jobs[job_id]["prompts"][idx]["text"] = final_prompt
#             # Update refined_rows record
#             for rr in jobs[job_id].get("refined_rows", []):
#                 if rr.get("row_index") == idx:
#                     rr["approved_prompt"] = final_prompt
#                     break

#     # Transition to pending and start generation
#     now = datetime.now(timezone.utc).isoformat()
#     jobs[job_id]["status"]            = "pending"
#     jobs[job_id]["generation_status"] = "Queued"
#     jobs[job_id]["approved_at"]       = now

#     background_tasks.add_task(run_generation_job, job_id)

#     main_logger.info(f"[APPROVE] job={job_id} approved by {user_id}")
#     return {"success": True, "job_id": job_id, "status": "pending"}


# @app.post("/api/jobs/{job_id}/reject")
# async def reject_job(job_id: str, request: Request):
#     """
#     User rejected the refinement — clean up the awaiting_approval job.
#     Frontend returns to the upload screen.
#     """
#     if job_id not in jobs:
#         raise HTTPException(404, f"Job '{job_id}' not found")

#     if jobs[job_id].get("status") == "awaiting_approval":
#         del jobs[job_id]
#         main_logger.info(f"[REJECT] job={job_id} rejected and removed")
#         return {"success": True}

#     raise HTTPException(400, f"Job is not in awaiting_approval state")


# @app.post("/api/jobs/{job_id}/refine-row/{row_index}")
# async def refine_row_again(
#     job_id:    str,
#     row_index: int,
#     request:   Request,
#     body:      dict = {},
# ):
#     """
#     Re-run refinement for a single row — preserves all other rows.
#     Uses original prompt (not edited version) for reproducibility.
#     """
#     if job_id not in jobs:
#         raise HTTPException(404, f"Job '{job_id}' not found")

#     job = jobs[job_id]
#     refined_rows = job.get("refined_rows", [])

#     if row_index >= len(refined_rows):
#         raise HTTPException(400, f"Row index {row_index} out of range")

#     row         = refined_rows[row_index]
#     raw_text    = row["original_prompt"]
#     n_clips_row = row.get("n_clips", 1)
#     clip_durs   = [int(job.get("clip_duration", 8))] * n_clips_row

#     try:
#         refined = prompt_refiner.refine(raw_text, n_clips_row, clip_durs)
#     except Exception as e:
#         raise HTTPException(500, f"Refinement failed: {e}")

#     jobs[job_id]["refined_rows"][row_index] = {
#         **row,
#         "refined_prompt":    refined["refined_prompt"],
#         "mythology_detected":refined["mythology_detected"],
#         "warnings":          refined["warnings"],
#         "structured":        refined["structured"],
#         "clips":             refined["clips"],
#         "clips_ready":       len(refined["clips"]) == n_clips_row and _refiner_mode == 2,
#     }

#     return {
#         "success":   True,
#         "row_index": row_index,
#         "row":       jobs[job_id]["refined_rows"][row_index],
#     }


# # ── Authentication endpoint (called by NextAuth authorize) ────────────────────
# @app.post("/api/auth/verify")
# async def verify_credentials(body: dict = Body(default={})):
#     email    = body.get("email", "")
#     password = body.get("password", "")
#     user     = user_store.verify(email, password)
#     if not user:
#         raise HTTPException(status_code=401, detail="Invalid email or password")
#     return user


# # ── User management (admin only) ──────────────────────────────────────────────
# @app.get("/api/users")
# async def list_users(request: Request):
#     _, role = _request_user(request)
#     if role != "admin":
#         raise HTTPException(status_code=403, detail="Admin access required")
#     return {"users": user_store.list_users()}


# @app.post("/api/users")
# async def create_user(request: Request, body: dict = Body(default={})):
#     _, role = _request_user(request)
#     if role != "admin":
#         raise HTTPException(status_code=403, detail="Admin access required")
#     email    = body.get("email", "").strip()
#     password = body.get("password", "").strip()
#     name     = body.get("name", "").strip()
#     user_role= body.get("role", "editor").strip()
#     if not email or not password or not name:
#         raise HTTPException(status_code=400, detail="email, password, and name required")
#     try:
#         return {"success": True, "user": user_store.create(email, password, name, user_role)}
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @app.patch("/api/users/{email:path}")
# async def update_user(email: str, request: Request, body: dict = Body(default={})):
#     caller_email, caller_role = _request_user(request)
#     if caller_role != "admin" and caller_email != email.lower():
#         raise HTTPException(status_code=403, detail="Admin access required")
#     if body.get("role") and caller_role != "admin":
#         raise HTTPException(status_code=403, detail="Only admins can change roles")
#     try:
#         return {"success": True, "user": user_store.update(
#             email        = email,
#             name         = body.get("name"),
#             role         = body.get("role"),
#             new_password = body.get("password"),
#         )}
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @app.delete("/api/users/{email:path}")
# async def delete_user(email: str, request: Request):
#     caller_email, caller_role = _request_user(request)
#     if caller_role != "admin":
#         raise HTTPException(status_code=403, detail="Admin access required")
#     if caller_email == email.lower():
#         raise HTTPException(status_code=400, detail="Cannot delete your own account")
#     if not user_store.delete(email):
#         raise HTTPException(status_code=404, detail=f"User '{email}' not found")
#     return {"success": True}


# # ── Internal secret middleware ────────────────────────────────────────────────
# # Rejects any request missing the correct X-Internal-Secret header.
# # This prevents direct access to the API bypassing the Next.js proxy.
# # The secret must match INTERNAL_SECRET in both veo.env and Vercel env vars.
# #
# # Exceptions (no secret required):
# #   GET  /health   — uptime monitoring
# #   POST /api/auth/verify — NextAuth calls this with the secret already

# _INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")

# @app.middleware("http")
# async def require_internal_secret(request: Request, call_next):
#     """
#     Reject requests that don't carry the correct X-Internal-Secret header.
#     Public paths: /health (monitoring), docs (local dev only).
#     """
#     path = request.url.path

#     # Always allow health check and local Swagger docs
#     public_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
#     if path in public_paths:
#         return await call_next(request)

#     # Skip secret check if INTERNAL_SECRET is not configured
#     # (local development without the secret set)
#     if not _INTERNAL_SECRET:
#         return await call_next(request)

#     incoming = request.headers.get("X-Internal-Secret", "")
#     if incoming != _INTERNAL_SECRET:
#         return JSONResponse(
#             status_code=401,
#             content={"detail": "Missing or invalid X-Internal-Secret header"},
#         )

#     return await call_next(request)


# @app.get("/health")
# async def health_check():
#     health_logger.info("Health check requested")
#     return {
#         "status":    "healthy",
#         "service":   "veo-video-generation-platform",
#         "version":   "1.0.0",
#         "timestamp": datetime.now().isoformat(),
#         "components": {
#             "veo_generator":   True,
#             "ffmpeg_stitcher": video_stitcher.ffmpeg_available,
#             "decomposer":      True,
#         },
#         "veo": {
#             "primary_model":  config.VEO_MODEL_PRIMARY,
#             "fallback_model": config.VEO_MODEL_FALLBACK,
#             "clip_duration":  f"{config.VEO_CLIP_DURATION_SECONDS}s (hard limit)",
#             "aspect_ratio":   config.VEO_ASPECT_RATIO,
#             "resolution":     config.VEO_RESOLUTION,
#             "native_audio":   True,  # Veo 3.0 always generates audio natively
#         },
#         "decomposer_mode": (
#             "bedrock_nova_deepseek" if prompt_decomposer._bedrock_client else "deterministic_fallback"
#         ),
#     }


# @app.get("/api/metrics")
# async def get_metrics():
#     """Real-time generation metrics for the Streamlit dashboard."""
#     import time
#     from datetime import datetime, timezone, timezone

#     # Derived metrics
#     total_veo   = _metrics["veo_submissions"]
#     rl_rate     = (
#         round(_metrics["veo_rate_limit_hits"] / total_veo * 100, 1)
#         if total_veo > 0 else 0.0
#     )
#     avg_clip_s  = (
#         round(_metrics["veo_generation_time_s"] / _metrics["veo_clips_generated"], 1)
#         if _metrics["veo_clips_generated"] > 0 else 0.0
#     )

#     # Estimated cost (clips × 8s × $0.40 for primary model)
#     est_cost_usd = _metrics["veo_clips_generated"] * 8 * 0.40
#     est_cost_inr = est_cost_usd * 92.5  # approximate; live rate not fetched here

#     return {
#         "session_start":        _metrics["session_start"],
#         "jobs_processed":       _metrics["jobs_processed"],

#         "veo": {
#             "submissions":      _metrics["veo_submissions"],
#             "successes":        _metrics["veo_successes"],
#             "failures":         _metrics["veo_failures"],
#             "rate_limit_hits":  _metrics["veo_rate_limit_hits"],
#             "rate_limit_pct":   rl_rate,
#             "clips_generated":  _metrics["veo_clips_generated"],
#             "avg_clip_time_s":  avg_clip_s,
#             "total_gen_time_s": round(_metrics["veo_generation_time_s"], 1),
#         },

#         "decomposer": {
#             "nova_calls":        _metrics["decomp_nova_calls"],
#             "deepseek_calls":    _metrics["decomp_deepseek_calls"],
#             "deterministic":     _metrics["decomp_deterministic"],
#             "input_tokens":      _metrics["decomp_input_tokens"],
#             "output_tokens":     _metrics["decomp_output_tokens"],
#             "total_tokens":      _metrics["decomp_input_tokens"] + _metrics["decomp_output_tokens"],
#         },

#         "s3": {
#             "uploads_ok":   _metrics["s3_uploads_ok"],
#             "uploads_fail": _metrics["s3_uploads_fail"],
#         },

#         "cost_estimate": {
#             "usd": round(est_cost_usd, 4),
#             "inr": round(est_cost_inr, 2),
#             "note": "Primary model rate ($0.40/s). Check GCP console for exact billing.",
#         },
#     }


# @app.get("/api/jobs")
# async def list_jobs(request: Request):
#     user_id, user_role = _request_user(request)
#     visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
#     job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
#     return {
#         "jobs": [
#             {
#                 "job_id":            job_id,
#                 "original_filename": jd.get("original_filename", ""),
#                 "status":            jd.get("status", "processing"),
#                 "total_prompts":     jd.get("total_prompts", 0),
#                 "completed_prompts": jd.get("completed_prompts", 0),
#                 "failed_prompts":    jd.get("failed_prompts", 0),
#                 "progress_percent":  jd.get("progress_percent", 0.0),
#                 "created_at":        jd.get("created_at", ""),
#                 "generation_status": jd.get("generation_status", "Queued"),
#                 "user_id":           jd.get("user_id", "anonymous"),
#             }
#             for job_id, jd in visible.items()
#         ]
#     }


# @app.get("/api/jobs/{job_id}")
# async def get_job(job_id: str, request: Request):
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     user_id, user_role = _request_user(request)
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied")

#     job_data = jobs[job_id]
#     results  = job_data.get("results", {})

#     prompts_out = []
#     for i, prompt_data in enumerate(job_data.get("prompts", [])):
#         r = results.get(str(i), {})
#         # video_url: may be S3 URL after upload (for distribution)
#         # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
#         raw_video_url = r.get("video_url")
#         raw_local_url = r.get("local_video_url")
#         # Ensure local_video_url is a proper /videos/ route, not an absolute path
#         if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
#             from pathlib import Path as _Path
#             raw_local_url = f"/videos/{_Path(raw_local_url).name}"
#         # If no local URL stored but video_url is already a local route, use it
#         if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
#             raw_local_url = raw_video_url
#         prompts_out.append({
#             "prompt_id":        f"prompt_{i + 1}",
#             "prompt_text":      prompt_data.get("text", ""),
#             "row_number":       i + 1,
#             "duration":         prompt_data.get("duration", 8),
#             "status":           r.get("status", "processing"),
#             "video_url":        raw_video_url,    # S3 or local route
#             "local_video_url":  raw_local_url,    # always /videos/... for player
#             "duration_seconds": r.get("duration_seconds"),
#             "stitched":         r.get("stitched", False),
#             "clips_count":      r.get("clips_count", 0),
#             "clip_urls":        r.get("clip_urls", []),
#             "model_used":       r.get("model_used", ""),
#             "has_native_audio": r.get("has_native_audio", False),
#             "error_message":    r.get("error_message"),
#             "generation_time_seconds": r.get("generation_time_seconds"),
#         })

#     return {
#         "job_id":       job_id,
#         "status":       job_data.get("status", "processing"),
#         "mode":         job_data.get("mode", "full"),
#         "hold_duration":job_data.get("hold_duration", 5.0),
#         "clip_duration":job_data.get("clip_duration", 8),
#         "no_text":      job_data.get("no_text", False),
#         "no_speech":    job_data.get("no_speech", False),
#         "summary": {
#             "job_id":            job_id,
#             "original_filename": job_data.get("original_filename", ""),
#             "status":            job_data.get("status", "processing"),
#             "total_prompts":     job_data.get("total_prompts", 0),
#             "completed_prompts": job_data.get("completed_prompts", 0),
#             "failed_prompts":    job_data.get("failed_prompts", 0),
#             "progress_percent":  job_data.get("progress_percent", 0.0),
#             "total_processing_time": job_data.get("total_processing_time"),
#         },
#         "prompts": prompts_out,
#     }


# @app.post("/api/upload")
# async def upload_excel(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(...),
#     mode: str = "full",           # "full" | "short_span" | "short_span_image"
#     clip_duration: float = 2.0,   # short_span only: seconds per clip (2–8)
#     hold_duration: float = 5.0,   # short_span_image only: seconds per image (2 or 5)
#     no_text: bool = False,        # inject no-text guardrail into all prompts
#     no_speech: bool = False,      # inject no-speech guardrail into all prompts
# ):
#     """
#     Accept an Excel/CSV file and start Veo generation as a background job.

#     Required Excel columns:  prompt, duration
#     Optional Excel columns:  task_type, priority
#     """
#     upload_id = str(uuid.uuid4())[:8]
#     upload_logger.info(f"[UPLOAD_{upload_id}] {file.filename}")

#     if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
#         raise HTTPException(status_code=400, detail="Upload must be .xlsx, .xls, or .csv")

#     content = await file.read()
#     if len(content) > 10 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

#     temp_path = temp_dir / f"upload_{upload_id}_{file.filename}"
#     temp_path.write_bytes(content)

#     _is_short_span = mode in ("short_span", "short_span_image")

#     if _is_short_span:
#         is_valid, errors = validate_short_span_excel(str(temp_path))
#     else:
#         is_valid, errors = validate_excel_file(str(temp_path))

#     if not is_valid:
#         temp_path.unlink(missing_ok=True)
#         raise HTTPException(
#             status_code=400,
#             detail=f"Excel validation failed: {'; '.join(errors)}",
#         )

#     if _is_short_span:
#         job_data = create_short_span_job(
#             file_path       = str(temp_path),
#             clip_duration_s = clip_duration,
#             aspect_ratio    = "9:16",
#         )
#     else:
#         job_data = create_job_from_excel(
#             file_path  = str(temp_path),
#             platforms  = ["veo"],
#             audio_mode = "platform_native",
#         )
#     job_id = job_data["job_id"]

#     user_id, user_role = _request_user(request)

#     jobs[job_id]                      = job_data
#     jobs[job_id]["temp_file"]         = str(temp_path)
#     jobs[job_id]["upload_id"]         = upload_id
#     jobs[job_id]["original_filename"] = file.filename
#     jobs[job_id]["user_id"]           = user_id
#     jobs[job_id]["mode"]              = mode
#     jobs[job_id]["clip_duration"]     = clip_duration
#     jobs[job_id]["hold_duration"]     = hold_duration
#     jobs[job_id]["no_text"]           = no_text
#     jobs[job_id]["no_speech"]         = no_speech

#     upload_logger.info(f"[UPLOAD_{upload_id}] Job {job_id} — {job_data['total_prompts']} prompt(s)")

#     background_tasks.add_task(run_generation_job, job_id)

#     return {
#         "success":       True,
#         "job_id":        job_id,
#         "upload_id":     upload_id,
#         "prompts_count": job_data["total_prompts"],
#         "veo_model":     config.VEO_MODEL_PRIMARY,
#         "clip_duration": f"{config.VEO_CLIP_DURATION_SECONDS}s",
#         "native_audio":  True,  # Veo 3.0 always generates audio natively
#         "stitching":     video_stitcher.ffmpeg_available,
#         "message":       "Veo generation started. Poll /api/jobs/{job_id} for status.",
#     }


# # ── Concurrency config ────────────────────────────────────────────────────────

# # Max prompts running simultaneously within one job.
# # Veo 3.0 free tier: 2 requests per minute, 50 per day.
# # Each prompt with 4 clips = 4 sequential API calls.
# # At concurrency=2, clip submissions from two prompts can overlap
# # and exceed the 2 RPM limit. Set to 1 for reliable operation
# # on the free tier. Increase if you have a paid quota.
# _PROMPT_CONCURRENCY = 1


# # ── Background generation job ─────────────────────────────────────────────────

# async def run_generation_job(job_id: str) -> None:
#     """
#     Process prompts concurrently (up to _PROMPT_CONCURRENCY at once).

#     Design:
#     - asyncio.Semaphore gates concurrent access — at most 5 prompts call Veo simultaneously.
#     - asyncio.Lock protects writes to the shared jobs[job_id] dict (completed/failed counters).
#     - Within each prompt, clips are sequential — clip N+1 waits for clip N's last frame.
#     - Results are stored by index key str(i) — API schema unchanged.
#     - Progress percent is updated after each prompt completes (order-independent).
#     """
#     generation_logger.info(f"[JOB_{job_id}] Starting — {_PROMPT_CONCURRENCY} concurrent")
#     start_time   = time.time()

#     # Track session start on first job
#     if _metrics["session_start"] is None:
#         from datetime import datetime, timezone, timezone
#         _metrics["session_start"] = datetime.now(timezone.utc).isoformat()
#     _metrics["jobs_processed"] += 1
#     job          = jobs[job_id]
#     prompts_data = job["prompts"]
#     total        = len(prompts_data)

#     jobs[job_id]["results"]            = {}
#     jobs[job_id]["completed_prompts"]  = 0
#     jobs[job_id]["failed_prompts"]     = 0
#     jobs[job_id]["generation_status"]  = f"Running — 0/{total} complete"

#     semaphore  = asyncio.Semaphore(_PROMPT_CONCURRENCY)
#     state_lock = asyncio.Lock()   # guards counter/status writes on jobs[job_id]

#     async def _run_prompt(i: int, prompt_data: dict) -> None:
#         """
#         Semaphore-gated coroutine for a single prompt.
#         Clips within this prompt run sequentially inside generate_for_prompt().
#         """
#         prompt_text = prompt_data["text"]
#         duration    = prompt_data["duration"]

#         async with semaphore:
#             if job_id not in jobs:
#                 generation_logger.warning(f"[JOB_{job_id}] Job deleted — skipping prompt {i + 1}")
#                 return

#             generation_logger.info(f"[JOB_{job_id}] Prompt {i + 1}/{total} | {duration}s [START]")
#             generation_logger.info(f"   '{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}'")
#             prompt_start = time.time()

#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = i,
#             )

#             elapsed = time.time() - prompt_start

#         # ── Update shared state (outside semaphore — IO-free, lock-protected) ──
#         async with state_lock:
#             jobs[job_id]["results"][str(i)] = result

#             # ── Push result stats into live metrics ───────────────────────────
#             _metrics["veo_submissions"]     += result.get("api_calls_made", 1)
#             _metrics["veo_rate_limit_hits"] += result.get("rate_limit_hits", 0)
#             # Decomposer token tracking
#             _metrics["decomp_input_tokens"]   += result.get("decomp_input_tokens", 0)
#             _metrics["decomp_output_tokens"]  += result.get("decomp_output_tokens", 0)
#             _metrics["decomp_nova_calls"]     += result.get("decomp_nova_calls", 0)
#             _metrics["decomp_deepseek_calls"] += result.get("decomp_deepseek_calls", 0)
#             _metrics["decomp_deterministic"]  += result.get("decomp_deterministic", 0)
#             # S3 tracking
#             _metrics["s3_uploads_ok"]   += result.get("s3_upload_ok", 0)
#             _metrics["s3_uploads_fail"] += result.get("s3_upload_fail", 0)

#             if result.get("status") in ("completed", "partial"):
#                 jobs[job_id]["completed_prompts"] += 1
#                 _metrics["veo_successes"]       += 1
#                 _metrics["veo_clips_generated"] += result.get("clips_count", 1)
#                 _metrics["veo_generation_time_s"] += result.get("generation_time_seconds", 0) or 0
#                 generation_logger.info(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} done in {elapsed:.1f}s "
#                     f"-> {result.get('video_url')} "
#                     f"({'stitched' if result.get('stitched') else 'single'}, "
#                     f"{result.get('clips_count', 1)} clip(s))"
#                 )
#                 progress_logger.info(f"[{i + 1}/{total}] {result.get('video_url')}")
#             else:
#                 jobs[job_id]["failed_prompts"] += 1
#                 _metrics["veo_failures"] += 1
#                 generation_logger.error(
#                     f"[JOB_{job_id}] Prompt {i + 1}/{total} failed after {elapsed:.1f}s: "
#                     f"{result.get('error_message')}"
#                 )

#             done_so_far = (
#                 jobs[job_id]["completed_prompts"] + jobs[job_id]["failed_prompts"]
#             )
#             jobs[job_id]["progress_percent"]   = (done_so_far / total) * 100
#             jobs[job_id]["generation_status"]  = (
#                 f"Running — {done_so_far}/{total} complete"
#             )

#     # ── Launch based on mode ──────────────────────────────────────────────────
#     mode         = job.get("mode", "full")
#     no_text      = job.get("no_text", False)
#     no_speech    = job.get("no_speech", False)
#     clip_dur     = job.get("clip_duration", 2.0)

#     if mode == "short_span":
#         # ── Short Span Clips: all rows = one sequence, no decomposition ───────
#         # Inject guardrails into prompt text before passing to orchestrator
#         _NO_TEXT_G = (
#             "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#             "subtitles, watermarks, or UI labels anywhere in the frame."
#         )
#         _NO_SPEECH_G = (
#             "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
#         )
#         enriched = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:   parts.append(_NO_TEXT_G)
#             if no_speech: parts.append(_NO_SPEECH_G)
#             parts.append(pd.get("text", ""))
#             enriched.append({**pd, "text": " ".join(parts)})

#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN mode — {len(enriched)} clip(s) "
#             f"at {clip_dur}s each, no_text={no_text}, no_speech={no_speech}"
#         )
#         result = await ss_orchestrator.run(
#             prompts         = enriched,
#             job_id          = job_id,
#             clip_duration_s = clip_dur,
#             no_text         = False,   # guardrails already injected into enriched
#             no_speech       = False,
#             aspect_ratio    = job.get("aspect_ratio", "9:16"),
#         )
#         # Store as single result at index 0 and mark job done
#         async with state_lock:
#             jobs[job_id]["results"]["0"]          = result
#             jobs[job_id]["completed_prompts"]     = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]        = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]      = 100.0
#             jobs[job_id]["generation_status"]     = "All prompts processed"
#             _metrics["veo_clips_generated"]      += result.get("clips_count", 0)
#             _metrics["veo_generation_time_s"]    += result.get("generation_time_seconds", 0) or 0
#             if result.get("status") in ("completed", "partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"] += 1

#     elif mode == "short_span_image":
#         if img_orchestrator is None:
#             generation_logger.error(f"[JOB_{job_id}] Short Span Images: GOOGLE_API_KEY not set")
#             async with state_lock:
#                 jobs[job_id]["status"] = "failed"
#                 jobs[job_id]["generation_status"] = "GOOGLE_API_KEY missing"
#                 jobs[job_id]["progress_percent"] = 100.0
#             return
#         hold_dur     = job.get("hold_duration", 5.0)
#         aspect_ratio = job.get("aspect_ratio", "9:16")
#         enriched_imgs = []
#         for pd in prompts_data:
#             parts = []
#             if no_text:
#                 parts.append("No text, captions, titles, watermarks, or labels in the image.")
#             parts.append(pd.get("text", ""))
#             enriched_imgs.append({**pd, "text": " ".join(parts)})
#         generation_logger.info(
#             f"[JOB_{job_id}] SHORT_SPAN_IMAGE — {len(enriched_imgs)} images at {hold_dur}s"
#         )
#         result = await img_orchestrator.run(
#             prompts         = enriched_imgs,
#             job_id          = job_id,
#             hold_duration_s = hold_dur,
#             aspect_ratio    = aspect_ratio,
#             no_text         = False,
#         )
#         async with state_lock:
#             jobs[job_id]["results"]["0"]      = result
#             jobs[job_id]["completed_prompts"] = 1 if result.get("status") in ("completed","partial") else 0
#             jobs[job_id]["failed_prompts"]    = 0 if result.get("status") in ("completed","partial") else 1
#             jobs[job_id]["progress_percent"]  = 100.0
#             jobs[job_id]["generation_status"] = "All images processed"
#             if result.get("status") in ("completed","partial"):
#                 _metrics["veo_successes"] += 1
#                 _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
#             else:
#                 _metrics["veo_failures"]  += 1

#     else:
#         # ── Full Length Videos (existing pipeline) ────────────────────────────
#         # Inject no_text/no_speech guardrails into prompt text if requested
#         if no_text or no_speech:
#             _NO_TEXT_G = (
#                 "NO TEXT OVERLAY: Do not render any text, titles, captions, "
#                 "subtitles, watermarks, or UI labels anywhere in the frame."
#             )
#             _NO_SPEECH_G = (
#                 "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
#             )
#             for pd in prompts_data:
#                 parts = []
#                 if no_text:   parts.append(_NO_TEXT_G)
#                 if no_speech: parts.append(_NO_SPEECH_G)
#                 parts.append(pd.get("text", ""))
#                 pd["text"] = " ".join(parts)

#         tasks = [_run_prompt(i, pd) for i, pd in enumerate(prompts_data)]
#         await asyncio.gather(*tasks, return_exceptions=True)

#     # ── Finalise ──────────────────────────────────────────────────────────────
#     total_elapsed = time.time() - start_time
#     failed_count  = jobs[job_id].get("failed_prompts", 0)

#     jobs[job_id]["status"]                = "completed" if failed_count == 0 else "partial"
#     jobs[job_id]["generation_status"]     = "All prompts processed"
#     jobs[job_id]["total_processing_time"] = round(total_elapsed, 1)

#     generation_logger.info(
#         f"[JOB_{job_id}] Done in {total_elapsed:.1f}s — "
#         f"{jobs[job_id].get('completed_prompts', 0)} ok, {failed_count} failed"
#     )

#     try:
#         temp_file = jobs[job_id].get("temp_file")
#         if temp_file:
#             Path(temp_file).unlink(missing_ok=True)
#     except Exception as e:
#         generation_logger.warning(f"[JOB_{job_id}] Could not delete temp file: {e}")


# # ── Rerun single prompt ───────────────────────────────────────────────────────

# @app.post("/api/jobs/{job_id}/rerun/{prompt_index}")
# async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
#     """
#     Re-run a single prompt within an existing job.

#     Flow:
#     - Validates job and prompt exist
#     - Marks the result as "processing" immediately (UI picks this up on next poll)
#     - Schedules a background task that calls the orchestrator for just that one prompt
#     - Returns immediately so the UI is never blocked

#     Used by: rerun button on each video card in the frontend.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job = jobs[job_id]
#     prompts_data = job.get("prompts", [])

#     if prompt_index < 0 or prompt_index >= len(prompts_data):
#         raise HTTPException(
#             status_code=400,
#             detail=f"prompt_index {prompt_index} out of range (job has {len(prompts_data)} prompts)"
#         )

#     prompt_data = prompts_data[prompt_index]

#     # Mark as processing immediately so frontend shows skeleton
#     jobs[job_id].setdefault("results", {})[str(prompt_index)] = {
#         "status": "processing",
#         "video_url": None,
#     }
#     # Reset counters to reflect the rerun
#     jobs[job_id]["status"] = "processing"

#     generation_logger.info(
#         f"[JOB_{job_id}] Rerun requested — prompt {prompt_index + 1} "
#         f"'{prompt_data.get('text', '')[:60]}...'"
#     )

#     async def _rerun():
#         try:
#             result = await veo_orchestrator.generate_for_prompt(
#                 prompt_data  = prompt_data,
#                 job_id       = job_id,
#                 prompt_index = prompt_index,
#             )
#             jobs[job_id]["results"][str(prompt_index)] = result

#             # Recompute job-level status from all results
#             all_results = jobs[job_id].get("results", {})
#             total = len(prompts_data)
#             completed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") in ("completed", "partial")
#             )
#             failed = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "failed"
#             )
#             processing = sum(
#                 1 for r in all_results.values()
#                 if r.get("status") == "processing"
#             )

#             if processing == 0:
#                 jobs[job_id]["status"] = "completed" if failed == 0 else "partial"
#                 jobs[job_id]["completed_prompts"] = completed
#                 jobs[job_id]["failed_prompts"]    = failed
#                 jobs[job_id]["progress_percent"]  = 100.0

#             generation_logger.info(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} done — "
#                 f"status={result.get('status')}"
#             )
#         except Exception as e:
#             jobs[job_id]["results"][str(prompt_index)] = {
#                 "status": "failed",
#                 "error_message": str(e),
#             }
#             generation_logger.error(
#                 f"[JOB_{job_id}] Rerun prompt {prompt_index + 1} error: {e}"
#             )

#     # Soft-delete the old S3 video before rerunning
#     # (moves to rejected/{job_id}/prompt_{N}/ — not hard deleted)
#     if veo_s3.enabled:
#         moved = veo_s3.soft_delete_video(job_id=job_id, prompt_index=prompt_index)
#         if moved:
#             generation_logger.info(
#                 f"[JOB_{job_id}] S3 soft-delete OK — prompt {prompt_index + 1} moved to rejected/"
#             )
#         else:
#             generation_logger.warning(
#                 f"[JOB_{job_id}] S3 soft-delete skipped — no existing object or S3 error"
#             )

#     background_tasks.add_task(_rerun)

#     return {
#         "status":        "accepted",
#         "job_id":        job_id,
#         "prompt_index":  prompt_index,
#         "message":       f"Rerun started for prompt {prompt_index + 1}",
#     }


# # ── YouTube upload queue ──────────────────────────────────────────────────────
# # In-memory queue: { queue_id: { job_id, prompt_index, title, description,
# #                                tags, local_path, s3_url, status, youtube_url } }
# # "approved" = waiting to upload, "uploading" = in progress,
# # "uploaded" = done, "failed" = error
# youtube_queue: Dict[str, Any] = {}


# import veo_youtube as _yt


# @app.get("/api/youtube/status")
# async def youtube_status():
#     """Check if YouTube is configured and authenticated."""
#     return {
#         "configured":    _yt.is_configured(),
#         "authenticated": _yt.is_authenticated(),
#         "secrets_file":  str(_yt.SECRETS_FILE),
#     }


# @app.post("/api/youtube/auth")
# async def youtube_auth():
#     """
#     Trigger the OAuth browser flow.
#     Opens a browser tab — user logs in, approves, token is saved.
#     Returns immediately after auth completes.
#     """
#     try:
#         _yt.get_authenticated_service()
#         return {"status": "authenticated"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/api/jobs/{job_id}/approve/{prompt_index}")
# async def approve_video(job_id: str, prompt_index: int, request: Request):
#     """
#     Approve a completed video — adds it to the YouTube upload queue.

#     Auto-generates title/description/tags from the prompt.
#     User edits these in the UI before triggering upload.

#     Returns the queue_id so the frontend can reference this queue entry.
#     """
#     user_id, user_role = _request_user(request)
#     if job_id not in jobs:
#         raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
#     if not _owns_job(jobs[job_id], user_id, user_role):
#         raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

#     job      = jobs[job_id]
#     prompts  = job.get("prompts", [])
#     results  = job.get("results", {})

#     if prompt_index < 0 or prompt_index >= len(prompts):
#         raise HTTPException(status_code=400, detail="prompt_index out of range")

#     result = results.get(str(prompt_index), {})
#     if result.get("status") != "completed":
#         raise HTTPException(status_code=400, detail="Video is not completed yet")

#     prompt_text = prompts[prompt_index].get("text", "")
#     video_url   = result.get("video_url", "")
#     local_path  = result.get("local_video_url") or video_url  # prefer local for upload
#     s3_url      = result.get("s3_url", "")

#     # Strip /videos/ prefix from local URL if it's a FastAPI-served path
#     if local_path and local_path.startswith("/videos/"):
#         from pathlib import Path as _Path
#         output_dir = _Path(__file__).parent / "outputs" / "videos"
#         local_path = str(output_dir / _Path(local_path).name)

#     metadata  = _yt.generate_metadata(prompt_text)
#     queue_id  = f"q_{job_id}_{prompt_index}"

#     youtube_queue[queue_id] = {
#         "queue_id":     queue_id,
#         "job_id":       job_id,
#         "prompt_index": prompt_index,
#         "prompt_text":  prompt_text[:120],
#         "local_path":   local_path,
#         "s3_url":       s3_url,
#         "video_url":    video_url,
#         "title":        metadata["title"],
#         "description":  metadata["description"],
#         "tags":         metadata["tags"],
#         "status":       "approved",
#         "youtube_url":  None,
#         "error":        None,
#     }

#     generation_logger.info(
#         f"[YOUTUBE] Queued for upload: {queue_id} — '{metadata['title'][:60]}'"
#     )

#     return youtube_queue[queue_id]


# @app.get("/api/youtube/queue")
# async def get_youtube_queue():
#     """Return all items in the upload queue."""
#     return {"queue": list(youtube_queue.values())}


# @app.patch("/api/youtube/queue/{queue_id}")
# async def update_queue_item(queue_id: str, body: dict = Body(default={})):
#     """
#     Update editable metadata for a queued video before upload.
#     Accepts: { title, description, tags }
#     """
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

#     item = youtube_queue[queue_id]
#     if item["status"] not in ("approved", "failed"):
#         raise HTTPException(
#             status_code=400,
#             detail=f"Cannot edit item with status '{item['status']}'"
#         )

#     if "title" in body:
#         item["title"]       = str(body["title"])[:100]
#     if "description" in body:
#         item["description"] = str(body["description"])[:5000]
#     if "tags" in body and isinstance(body["tags"], list):
#         item["tags"]        = [str(t).strip() for t in body["tags"] if str(t).strip()]

#     return item


# @app.post("/api/youtube/upload")
# async def upload_to_youtube(background_tasks: BackgroundTasks):
#     """
#     Upload ALL approved queue items to YouTube.

#     Runs in background — returns immediately.
#     Poll /api/youtube/queue to track per-item status.
#     """
#     approved = [
#         item for item in youtube_queue.values()
#         if item["status"] == "approved"
#     ]

#     if not approved:
#         raise HTTPException(status_code=400, detail="No approved videos in queue")

#     if not _yt.is_configured():
#         raise HTTPException(
#             status_code=503,
#             detail="YouTube not configured — youtube_client_secrets.json missing"
#         )

#     async def _upload_all():
#         for item in approved:
#             qid = item["queue_id"]
#             youtube_queue[qid]["status"] = "uploading"
#             generation_logger.info(f"[YOUTUBE] Uploading {qid} — '{item['title'][:60]}'")

#             result = await asyncio.get_event_loop().run_in_executor(
#                 None,
#                 lambda i=item: _yt.upload_video(
#                     local_path  = i["local_path"],
#                     title       = i["title"],
#                     description = i["description"],
#                     tags        = i["tags"],
#                     privacy     = "public",
#                 ),
#             )

#             if result["status"] == "uploaded":
#                 youtube_queue[qid]["status"]      = "uploaded"
#                 youtube_queue[qid]["youtube_url"] = result["youtube_url"]
#                 youtube_queue[qid]["youtube_id"]  = result["youtube_id"]
#                 generation_logger.info(
#                     f"[YOUTUBE] ✅ {qid} uploaded → {result['youtube_url']}"
#                 )
#             else:
#                 youtube_queue[qid]["status"] = "failed"
#                 youtube_queue[qid]["error"]  = result.get("error", "unknown")
#                 generation_logger.error(
#                     f"[YOUTUBE] ❌ {qid} failed: {result.get('error')}"
#                 )

#     background_tasks.add_task(_upload_all)

#     return {
#         "status":  "started",
#         "count":   len(approved),
#         "message": f"Uploading {len(approved)} video(s) to YouTube",
#     }


# @app.delete("/api/youtube/queue/{queue_id}")
# async def remove_from_queue(queue_id: str):
#     """Remove an item from the upload queue (before it's uploaded)."""
#     if queue_id not in youtube_queue:
#         raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
#     if youtube_queue[queue_id]["status"] == "uploading":
#         raise HTTPException(status_code=400, detail="Cannot remove item currently uploading")
#     del youtube_queue[queue_id]
#     return {"status": "removed", "queue_id": queue_id}


# # ── Entry point ───────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     s = logging.getLogger("STARTUP")
#     s.info("=" * 70)
#     s.info("Veo Video Generation Platform v1.0.0")
#     s.info("=" * 70)
#     s.info(f"   Primary model  : {config.VEO_MODEL_PRIMARY}")
#     s.info(f"   Fallback model : {config.VEO_MODEL_FALLBACK}")
#     s.info(f"   Clip duration  : {config.VEO_CLIP_DURATION_SECONDS}s")
#     s.info(f"   Aspect ratio   : {config.VEO_ASPECT_RATIO}")
#     s.info(f"   Resolution     : {config.VEO_RESOLUTION}")
#     s.info(f"   Native audio   : enabled (Veo 3.0 — always on)")
#     s.info(f"   FFmpeg stitch  : {'enabled' if video_stitcher.ffmpeg_available else 'DISABLED'}")
#     s.info("Endpoints:")
#     s.info("   API    : http://localhost:8100")
#     s.info("   Docs   : http://localhost:8100/docs")
#     s.info("   Health : http://localhost:8100/health")
#     s.info("=" * 70)

#     uvicorn.run(
#         "veo_main:app",
#         host      = "0.0.0.0",
#         port      = 8100,
#         reload    = True,
#         log_level = "info",
#     )


















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
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
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
    from veo_short_span_excel_processor import validate_short_span_excel, create_short_span_job
    from veo_users import UserStore
    from veo_refiner import PromptRefiner
    main_logger.info("OK veo_excel_processor + veo_short_span_excel_processor loaded")
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
        google_api_key        = config.GOOGLE_API_KEY,
        gemini_model          = os.getenv("GEMINI_DECOMPOSER_MODEL", "gemini-2.5-flash"),
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
from veo_short_span_orchestrator import ShortSpanOrchestrator
try:
    from veo_short_span_image_orchestrator import ShortSpanImageOrchestrator
    from veo_imagen_generator import ImagenGenerator
    _IMAGEN_AVAILABLE = True
except ImportError:
    ShortSpanImageOrchestrator = None  # type: ignore
    ImagenGenerator = None             # type: ignore
    _IMAGEN_AVAILABLE = False
veo_orchestrator = VeoOrchestrator(
    generator     = veo_generator,
    stitcher      = video_stitcher,
    decomposer    = prompt_decomposer,
    clip_duration = config.VEO_CLIP_DURATION_SECONDS,
    s3_client     = veo_s3,
)
main_logger.info("OK VeoOrchestrator initialised")

# ── User store ────────────────────────────────────────────────────────────────
user_store = UserStore()
user_store.init()
main_logger.info(f"OK UserStore — {user_store.count()} user(s)")

# ── Prompt refiner ────────────────────────────────────────────────────────────
_refiner_mode = int(os.getenv("REFINER_MODE", "1"))
prompt_refiner = PromptRefiner(
    aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
    aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
    region                = config.AWS_DEFAULT_REGION,
    mode                  = _refiner_mode,
)
main_logger.info(f"OK PromptRefiner — mode={_refiner_mode}")

ss_orchestrator = ShortSpanOrchestrator(
    generator  = veo_generator,
    stitcher   = video_stitcher,
    s3_client  = veo_s3,
)
main_logger.info("OK ShortSpanOrchestrator initialised")

# ── Short Span Image orchestrator — same GOOGLE_API_KEY as Veo ───────────────
_imagen_model = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-001")
if _IMAGEN_AVAILABLE and config.GOOGLE_API_KEY:
    imagen_generator = ImagenGenerator(
        api_key    = config.GOOGLE_API_KEY,
        model_id   = _imagen_model,
        output_dir = config.OUTPUT_DIR,
    )
    img_orchestrator = ShortSpanImageOrchestrator(
        imagen_generator = imagen_generator,
        stitcher         = video_stitcher,
        s3_client        = veo_s3,
    )
    main_logger.info(f"OK ShortSpanImageOrchestrator initialised (model={_imagen_model})")
else:
    imagen_generator = None
    img_orchestrator = None
    if not _IMAGEN_AVAILABLE:
        main_logger.warning(
            "veo_imagen_generator / veo_short_span_image_orchestrator not found — "
            "Short Span Images disabled. Copy both files to the veo/ folder to enable."
        )
    else:
        main_logger.warning("GOOGLE_API_KEY not set — Short Span Images disabled")

# ── Job store ─────────────────────────────────────────────────────────────────
jobs: Dict[str, Any] = {}

# ── Per-request user identity ─────────────────────────────────────────────────
def _request_user(request: Request) -> tuple:
    """
    Return (user_id, user_role) from request headers.
    X-User-Id   — authenticated user email (set by frontend _headers())
    X-User-Role — role string: admin / editor / viewer
    Defaults to ("anonymous","viewer") so curl/API docs still work.
    PRODUCTION: replace with JWT decode.
    """
    uid  = request.headers.get("X-User-Id",   "anonymous").strip().lower()
    role = request.headers.get("X-User-Role", "viewer").strip().lower()
    return uid, role

def _owns_job(job_data: dict, user_id: str, user_role: str) -> bool:
    """Admins see all jobs. Others see only their own."""
    if user_role == "admin":
        return True
    return job_data.get("user_id", "anonymous") == user_id

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

# ── Prompt refinement ────────────────────────────────────────────────────────────
@app.post("/api/refine")
async def refine_prompts(
    request:          Request,
    file:             UploadFile = File(...),
    mode:             str   = "full",
    clip_duration:    float = 8.0,
    hold_duration:    float = 5.0,
    no_text:          bool  = False,
    no_speech:        bool  = False,
    refiner_mode_override: Optional[int] = None,   # 1 or 2 — overrides REFINER_MODE env
):
    """
    Step 1 of the two-step generation flow.
    Runs LLM refinement on all Excel rows, returns structured preview.
    Does NOT start generation — waits for /api/jobs/{id}/approve.
    """
    user_id, _ = _request_user(request)
    upload_id  = str(uuid.uuid4())[:8]

    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "Upload must be .xlsx, .xls, or .csv")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 10 MB)")

    temp_path = temp_dir / f"refine_{upload_id}_{file.filename}"
    temp_path.write_bytes(content)

    _is_short_span = mode in ("short_span", "short_span_image")

    try:
        if _is_short_span:
            is_valid, errors = validate_short_span_excel(str(temp_path))
        else:
            is_valid, errors = validate_excel_file(str(temp_path))
        if not is_valid:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(400, f"Excel validation failed: {'; '.join(errors)}")

        if _is_short_span:
            job_data = create_short_span_job(str(temp_path), clip_duration, "9:16")
        else:
            job_data = create_job_from_excel(str(temp_path), platforms=["veo"], audio_mode="platform_native")
    finally:
        temp_path.unlink(missing_ok=True)

    # Determine clips per row from job_data
    job_id   = job_data["job_id"]
    prompts  = job_data.get("prompts", [])
    now      = datetime.now(timezone.utc).isoformat()

    # Store job in awaiting_approval state
    jobs[job_id] = {
        **job_data,
        "status":             "awaiting_approval",
        "mode":               mode,
        "clip_duration":      clip_duration,
        "hold_duration":      hold_duration,
        "no_text":            no_text,
        "no_speech":          no_speech,
        "user_id":            user_id,
        "created_at":         now,
        "generation_status":  "Awaiting approval",
        "progress_percent":   0.0,
        "completed_prompts":  0,
        "failed_prompts":     0,
        "results":            {},
        "refined_rows":       [],   # populated below
    }

    # Run refinement per row
    active_mode = refiner_mode_override or _refiner_mode
    refined_rows = []

    for idx, prompt_data in enumerate(prompts):
        raw_text   = (prompt_data.get("text") or "").strip()
        row_dur    = int(prompt_data.get("duration", clip_duration))
        n_clips_row = max(1, row_dur // 8) if mode == "full" else 1
        clip_durs  = [8] * n_clips_row if mode == "full" else [int(clip_duration)]

        try:
            # Use override mode if specified (per-request)
            if refiner_mode_override and refiner_mode_override != _refiner_mode:
                from veo_refiner import PromptRefiner as _PR
                override_refiner = _PR(
                    aws_access_key_id     = config.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key = config.AWS_SECRET_ACCESS_KEY,
                    region                = config.AWS_DEFAULT_REGION,
                    mode                  = refiner_mode_override,
                )
                refined = override_refiner.refine(raw_text, n_clips_row, clip_durs)
            else:
                refined = prompt_refiner.refine(raw_text, n_clips_row, clip_durs)
        except Exception as e:
            main_logger.error(f"[REFINE] Row {idx + 1} failed: {e}")
            refined = {
                "refined_prompt":     raw_text,
                "mythology_detected": False,
                "warnings":           [f"Refinement failed: {str(e)}"],
                "structured":         {"scene":"","characters":"","camera":"","narration_lines":[],"lighting":"","mythology_notes":""},
                "clips":              [],
            }

        refined_rows.append({
            "row_index":         idx,
            "original_prompt":   raw_text,
            "refined_prompt":    refined["refined_prompt"],
            "mythology_detected":refined["mythology_detected"],
            "warnings":          refined["warnings"],
            "structured":        refined["structured"],
            "clips":             refined["clips"],
            "row_number":        prompt_data.get("row_number", idx + 2),
            "duration":          row_dur,
            "n_clips":           n_clips_row,
            # Mode 2 flag: clips are already decomposed, skip decomposer on approve
            "clips_ready":       len(refined["clips"]) == n_clips_row and active_mode == 2,
        })

    jobs[job_id]["refined_rows"] = refined_rows
    main_logger.info(f"[REFINE] job={job_id} rows={len(refined_rows)} mode={active_mode}")

    return {
        "job_id":       job_id,
        "total_rows":   len(refined_rows),
        "mode":         mode,
        "refiner_mode": active_mode,
        "rows":         refined_rows,
    }


@app.post("/api/jobs/{job_id}/approve")
async def approve_job(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    body: dict = Body(default={}),
):
    """
    Step 2 of the two-step flow. User has reviewed and approved prompts.
    Accepts final (possibly edited) prompt per row, then starts generation.
    """
    user_id, _ = _request_user(request)

    if job_id not in jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")

    job = jobs[job_id]
    if job.get("status") != "awaiting_approval":
        raise HTTPException(400, f"Job is not awaiting approval (status={job.get('status')})")

    # Apply any user edits from the overlay
    approved_rows: List[Dict] = body.get("approved_rows", [])
    for row in approved_rows:
        idx = row.get("row_index")
        final_prompt = row.get("final_prompt", "").strip()
        if final_prompt and idx is not None:
            # Update the prompt in job prompts list
            if idx < len(job.get("prompts", [])):
                jobs[job_id]["prompts"][idx]["text"] = final_prompt
            # Update refined_rows record
            for rr in jobs[job_id].get("refined_rows", []):
                if rr.get("row_index") == idx:
                    rr["approved_prompt"] = final_prompt
                    break

    # Transition to pending and start generation
    now = datetime.now(timezone.utc).isoformat()
    jobs[job_id]["status"]            = "pending"
    jobs[job_id]["generation_status"] = "Queued"
    jobs[job_id]["approved_at"]       = now

    background_tasks.add_task(run_generation_job, job_id)

    main_logger.info(f"[APPROVE] job={job_id} approved by {user_id}")
    return {"success": True, "job_id": job_id, "status": "pending"}


@app.post("/api/jobs/{job_id}/reject")
async def reject_job(job_id: str, request: Request):
    """
    User rejected the refinement — clean up the awaiting_approval job.
    Frontend returns to the upload screen.
    """
    if job_id not in jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")

    if jobs[job_id].get("status") == "awaiting_approval":
        del jobs[job_id]
        main_logger.info(f"[REJECT] job={job_id} rejected and removed")
        return {"success": True}

    raise HTTPException(400, f"Job is not in awaiting_approval state")


@app.post("/api/jobs/{job_id}/refine-row/{row_index}")
async def refine_row_again(
    job_id:    str,
    row_index: int,
    request:   Request,
    body:      dict = {},
):
    """
    Re-run refinement for a single row — preserves all other rows.
    Uses original prompt (not edited version) for reproducibility.
    """
    if job_id not in jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")

    job = jobs[job_id]
    refined_rows = job.get("refined_rows", [])

    if row_index >= len(refined_rows):
        raise HTTPException(400, f"Row index {row_index} out of range")

    row         = refined_rows[row_index]
    raw_text    = row["original_prompt"]
    n_clips_row = row.get("n_clips", 1)
    clip_durs   = [int(job.get("clip_duration", 8))] * n_clips_row

    try:
        refined = prompt_refiner.refine(raw_text, n_clips_row, clip_durs)
    except Exception as e:
        raise HTTPException(500, f"Refinement failed: {e}")

    jobs[job_id]["refined_rows"][row_index] = {
        **row,
        "refined_prompt":    refined["refined_prompt"],
        "mythology_detected":refined["mythology_detected"],
        "warnings":          refined["warnings"],
        "structured":        refined["structured"],
        "clips":             refined["clips"],
        "clips_ready":       len(refined["clips"]) == n_clips_row and _refiner_mode == 2,
    }

    return {
        "success":   True,
        "row_index": row_index,
        "row":       jobs[job_id]["refined_rows"][row_index],
    }


# ── Authentication endpoint (called by NextAuth authorize) ────────────────────
@app.post("/api/auth/verify")
async def verify_credentials(body: dict = Body(default={})):
    email    = body.get("email", "")
    password = body.get("password", "")
    user     = user_store.verify(email, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user


# ── User management (admin only) ──────────────────────────────────────────────
@app.get("/api/users")
async def list_users(request: Request):
    _, role = _request_user(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return {"users": user_store.list_users()}


@app.post("/api/users")
async def create_user(request: Request, body: dict = Body(default={})):
    _, role = _request_user(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    email    = body.get("email", "").strip()
    password = body.get("password", "").strip()
    name     = body.get("name", "").strip()
    user_role= body.get("role", "editor").strip()
    if not email or not password or not name:
        raise HTTPException(status_code=400, detail="email, password, and name required")
    try:
        return {"success": True, "user": user_store.create(email, password, name, user_role)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/users/{email:path}")
async def update_user(email: str, request: Request, body: dict = Body(default={})):
    caller_email, caller_role = _request_user(request)
    if caller_role != "admin" and caller_email != email.lower():
        raise HTTPException(status_code=403, detail="Admin access required")
    if body.get("role") and caller_role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can change roles")
    try:
        return {"success": True, "user": user_store.update(
            email        = email,
            name         = body.get("name"),
            role         = body.get("role"),
            new_password = body.get("password"),
        )}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/users/{email:path}")
async def delete_user(email: str, request: Request):
    caller_email, caller_role = _request_user(request)
    if caller_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if caller_email == email.lower():
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if not user_store.delete(email):
        raise HTTPException(status_code=404, detail=f"User '{email}' not found")
    return {"success": True}


# ── Internal secret middleware ────────────────────────────────────────────────
# Rejects any request missing the correct X-Internal-Secret header.
# This prevents direct access to the API bypassing the Next.js proxy.
# The secret must match INTERNAL_SECRET in both veo.env and Vercel env vars.
#
# Exceptions (no secret required):
#   GET  /health   — uptime monitoring
#   POST /api/auth/verify — NextAuth calls this with the secret already

_INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")

@app.middleware("http")
async def require_internal_secret(request: Request, call_next):
    """
    Reject requests that don't carry the correct X-Internal-Secret header.
    Public paths: /health (monitoring), docs (local dev only).
    """
    path = request.url.path

    # Always allow health check and local Swagger docs
    public_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
    if path in public_paths:
        return await call_next(request)

    # Skip secret check if INTERNAL_SECRET is not configured
    # (local development without the secret set)
    if not _INTERNAL_SECRET:
        return await call_next(request)

    incoming = request.headers.get("X-Internal-Secret", "")
    if incoming != _INTERNAL_SECRET:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid X-Internal-Secret header"},
        )

    return await call_next(request)


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
    from datetime import datetime, timezone, timezone

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
async def list_jobs(request: Request):
    user_id, user_role = _request_user(request)
    visible = {jid: jd for jid, jd in jobs.items() if _owns_job(jd, user_id, user_role)}
    job_logger.info(f"Job list — {len(visible)}/{len(jobs)} visible to {user_id} ({user_role})")
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
                "user_id":           jd.get("user_id", "anonymous"),
            }
            for job_id, jd in visible.items()
        ]
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    user_id, user_role = _request_user(request)
    if not _owns_job(jobs[job_id], user_id, user_role):
        raise HTTPException(status_code=403, detail="Access denied")

    job_data = jobs[job_id]
    results  = job_data.get("results", {})

    prompts_out = []
    for i, prompt_data in enumerate(job_data.get("prompts", [])):
        r = results.get(str(i), {})
        # video_url: may be S3 URL after upload (for distribution)
        # local_video_url: always /videos/filename.mp4 (for in-browser playback via FastAPI)
        raw_video_url = r.get("video_url")
        raw_local_url = r.get("local_video_url")
        # Ensure local_video_url is a proper /videos/ route, not an absolute path
        if raw_local_url and len(raw_local_url) > 1 and raw_local_url[1] == ":":
            from pathlib import Path as _Path
            raw_local_url = f"/videos/{_Path(raw_local_url).name}"
        # If no local URL stored but video_url is already a local route, use it
        if not raw_local_url and raw_video_url and not raw_video_url.startswith("http"):
            raw_local_url = raw_video_url
        prompts_out.append({
            "prompt_id":        f"prompt_{i + 1}",
            "prompt_text":      prompt_data.get("text", ""),
            "row_number":       i + 1,
            "duration":         prompt_data.get("duration", 8),
            "status":           r.get("status", "processing"),
            "video_url":        raw_video_url,    # S3 or local route
            "local_video_url":  raw_local_url,    # always /videos/... for player
            "duration_seconds": r.get("duration_seconds"),
            "stitched":         r.get("stitched", False),
            "clips_count":      r.get("clips_count", 0),
            "clip_urls":        r.get("clip_urls", []),
            "model_used":       r.get("model_used", ""),
            "has_native_audio": r.get("has_native_audio", False),
            "error_message":    r.get("error_message"),
            "generation_time_seconds": r.get("generation_time_seconds"),
        })

    return {
        "job_id":       job_id,
        "status":       job_data.get("status", "processing"),
        "mode":         job_data.get("mode", "full"),
        "hold_duration":job_data.get("hold_duration", 5.0),
        "clip_duration":job_data.get("clip_duration", 8),
        "no_text":      job_data.get("no_text", False),
        "no_speech":    job_data.get("no_speech", False),
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
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = "full",           # "full" | "short_span" | "short_span_image"
    clip_duration: float = 2.0,   # short_span only: seconds per clip (2–8)
    hold_duration: float = 5.0,   # short_span_image only: seconds per image (2 or 5)
    no_text: bool = False,        # inject no-text guardrail into all prompts
    no_speech: bool = False,      # inject no-speech guardrail into all prompts
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

    _is_short_span = mode in ("short_span", "short_span_image")

    if _is_short_span:
        is_valid, errors = validate_short_span_excel(str(temp_path))
    else:
        is_valid, errors = validate_excel_file(str(temp_path))

    if not is_valid:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Excel validation failed: {'; '.join(errors)}",
        )

    if _is_short_span:
        job_data = create_short_span_job(
            file_path       = str(temp_path),
            clip_duration_s = clip_duration,
            aspect_ratio    = "9:16",
        )
    else:
        job_data = create_job_from_excel(
            file_path  = str(temp_path),
            platforms  = ["veo"],
            audio_mode = "platform_native",
        )
    job_id = job_data["job_id"]

    user_id, user_role = _request_user(request)

    jobs[job_id]                      = job_data
    jobs[job_id]["temp_file"]         = str(temp_path)
    jobs[job_id]["upload_id"]         = upload_id
    jobs[job_id]["original_filename"] = file.filename
    jobs[job_id]["user_id"]           = user_id
    jobs[job_id]["mode"]              = mode
    jobs[job_id]["clip_duration"]     = clip_duration
    jobs[job_id]["hold_duration"]     = hold_duration
    jobs[job_id]["no_text"]           = no_text
    jobs[job_id]["no_speech"]         = no_speech

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
        from datetime import datetime, timezone, timezone
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

    # ── Launch based on mode ──────────────────────────────────────────────────
    mode         = job.get("mode", "full")
    no_text      = job.get("no_text", False)
    no_speech    = job.get("no_speech", False)
    clip_dur     = job.get("clip_duration", 2.0)

    if mode == "short_span":
        # ── Short Span Clips: all rows = one sequence, no decomposition ───────
        # Inject guardrails into prompt text before passing to orchestrator
        _NO_TEXT_G = (
            "NO TEXT OVERLAY: Do not render any text, titles, captions, "
            "subtitles, watermarks, or UI labels anywhere in the frame."
        )
        _NO_SPEECH_G = (
            "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
        )
        enriched = []
        for pd in prompts_data:
            parts = []
            if no_text:   parts.append(_NO_TEXT_G)
            if no_speech: parts.append(_NO_SPEECH_G)
            parts.append(pd.get("text", ""))
            enriched.append({**pd, "text": " ".join(parts)})

        generation_logger.info(
            f"[JOB_{job_id}] SHORT_SPAN mode — {len(enriched)} clip(s) "
            f"at {clip_dur}s each, no_text={no_text}, no_speech={no_speech}"
        )
        result = await ss_orchestrator.run(
            prompts         = enriched,
            job_id          = job_id,
            clip_duration_s = clip_dur,
            no_text         = False,   # guardrails already injected into enriched
            no_speech       = False,
            aspect_ratio    = job.get("aspect_ratio", "9:16"),
        )
        # Store as single result at index 0 and mark job done
        async with state_lock:
            jobs[job_id]["results"]["0"]          = result
            jobs[job_id]["completed_prompts"]     = 1 if result.get("status") in ("completed","partial") else 0
            jobs[job_id]["failed_prompts"]        = 0 if result.get("status") in ("completed","partial") else 1
            jobs[job_id]["progress_percent"]      = 100.0
            jobs[job_id]["generation_status"]     = "All prompts processed"
            _metrics["veo_clips_generated"]      += result.get("clips_count", 0)
            _metrics["veo_generation_time_s"]    += result.get("generation_time_seconds", 0) or 0
            if result.get("status") in ("completed", "partial"):
                _metrics["veo_successes"] += 1
                _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
            else:
                _metrics["veo_failures"] += 1

    elif mode == "short_span_image":
        if img_orchestrator is None:
            generation_logger.error(f"[JOB_{job_id}] Short Span Images: GOOGLE_API_KEY not set")
            async with state_lock:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["generation_status"] = "GOOGLE_API_KEY missing"
                jobs[job_id]["progress_percent"] = 100.0
            return
        hold_dur     = job.get("hold_duration", 5.0)
        aspect_ratio = job.get("aspect_ratio", "9:16")
        enriched_imgs = []
        for pd in prompts_data:
            parts = []
            if no_text:
                parts.append("No text, captions, titles, watermarks, or labels in the image.")
            parts.append(pd.get("text", ""))
            enriched_imgs.append({**pd, "text": " ".join(parts)})
        generation_logger.info(
            f"[JOB_{job_id}] SHORT_SPAN_IMAGE — {len(enriched_imgs)} images at {hold_dur}s"
        )
        result = await img_orchestrator.run(
            prompts         = enriched_imgs,
            job_id          = job_id,
            hold_duration_s = hold_dur,
            aspect_ratio    = aspect_ratio,
            no_text         = False,
        )
        async with state_lock:
            jobs[job_id]["results"]["0"]      = result
            jobs[job_id]["completed_prompts"] = 1 if result.get("status") in ("completed","partial") else 0
            jobs[job_id]["failed_prompts"]    = 0 if result.get("status") in ("completed","partial") else 1
            jobs[job_id]["progress_percent"]  = 100.0
            jobs[job_id]["generation_status"] = "All images processed"
            if result.get("status") in ("completed","partial"):
                _metrics["veo_successes"] += 1
                _metrics["s3_uploads_ok"] += result.get("s3_upload_ok", 0)
            else:
                _metrics["veo_failures"]  += 1

    else:
        # ── Full Length Videos (existing pipeline) ────────────────────────────
        # Inject no_text/no_speech guardrails into prompt text if requested
        if no_text or no_speech:
            _NO_TEXT_G = (
                "NO TEXT OVERLAY: Do not render any text, titles, captions, "
                "subtitles, watermarks, or UI labels anywhere in the frame."
            )
            _NO_SPEECH_G = (
                "NO CHARACTER DIALOGUE: Characters should not speak, mouth words, or lip-sync. No dialogue between characters. The scene plays as natural action with narrator voiceover in the background."
            )
            for pd in prompts_data:
                parts = []
                if no_text:   parts.append(_NO_TEXT_G)
                if no_speech: parts.append(_NO_SPEECH_G)
                parts.append(pd.get("text", ""))
                pd["text"] = " ".join(parts)

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
async def rerun_prompt(job_id: str, prompt_index: int, background_tasks: BackgroundTasks, request: Request):
    """
    Re-run a single prompt within an existing job.

    Flow:
    - Validates job and prompt exist
    - Marks the result as "processing" immediately (UI picks this up on next poll)
    - Schedules a background task that calls the orchestrator for just that one prompt
    - Returns immediately so the UI is never blocked

    Used by: rerun button on each video card in the frontend.
    """
    user_id, user_role = _request_user(request)
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if not _owns_job(jobs[job_id], user_id, user_role):
        raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

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
async def approve_video(job_id: str, prompt_index: int, request: Request):
    """
    Approve a completed video — adds it to the YouTube upload queue.

    Auto-generates title/description/tags from the prompt.
    User edits these in the UI before triggering upload.

    Returns the queue_id so the frontend can reference this queue entry.
    """
    user_id, user_role = _request_user(request)
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if not _owns_job(jobs[job_id], user_id, user_role):
        raise HTTPException(status_code=403, detail="Access denied — job belongs to another user")

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
async def update_queue_item(queue_id: str, body: dict = Body(default={})):
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