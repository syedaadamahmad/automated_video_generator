# """
# veo_app.py — Streamlit Frontend for the Veo Video Generation Platform
# ═══════════════════════════════════════════════════════════════════════

# Run:
#   streamlit run veo_app.py

# Requires veo_main.py running on http://localhost:8100
#   python veo_main.py

# Install:
#   pip install streamlit pandas openpyxl requests
# """

# import io
# import time
# from pathlib import Path
# from typing import Optional

# import pandas as pd
# import requests
# import streamlit as st

# # ── Config ────────────────────────────────────────────────────────────────────
# API_BASE      = "http://localhost:8100"
# POLL_INTERVAL = 4   # seconds between status refreshes
# CLIP_DURATION = 8   # Veo hard limit per clip

# TEMPLATE_PATH = Path(__file__).parent / "veo_template.xlsx"

# # ── Page config ───────────────────────────────────────────────────────────────
# st.set_page_config(
#     page_title = "Veo Studio",
#     page_icon  = "🎬",
#     layout     = "wide",
# )

# # ── Styles ────────────────────────────────────────────────────────────────────
# st.markdown("""
# <style>
# @import url('https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Syne:wght@400;600;700;800&display=swap');

# :root {
#     --bg:        #080c14;
#     --surface:   #0d1525;
#     --border:    #1a2840;
#     --accent:    #00d4ff;
#     --accent2:   #7c3aed;
#     --text:      #e2e8f0;
#     --muted:     #64748b;
#     --success:   #10b981;
#     --warn:      #f59e0b;
#     --error:     #ef4444;
# }

# html, body, [data-testid="stApp"] {
#     background-color: var(--bg) !important;
#     color: var(--text) !important;
#     font-family: 'Syne', sans-serif;
# }

# /* Hide Streamlit chrome */
# #MainMenu, footer, header { visibility: hidden; }
# [data-testid="stToolbar"] { display: none; }

# /* Sidebar */
# [data-testid="stSidebar"] {
#     background: var(--surface) !important;
#     border-right: 1px solid var(--border);
# }
# [data-testid="stSidebar"] * { color: var(--text) !important; }

# /* Main container */
# .block-container { padding: 2rem 2.5rem; max-width: 1300px; }

# /* Title block */
# .veo-title {
#     font-size: 3rem;
#     font-weight: 800;
#     letter-spacing: -0.03em;
#     color: var(--text);
#     line-height: 1;
#     margin-bottom: 0.25rem;
# }
# .veo-title span { color: var(--accent); }
# .veo-sub {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.75rem;
#     color: var(--muted);
#     letter-spacing: 0.12em;
#     text-transform: uppercase;
#     margin-bottom: 2rem;
# }

# /* Drop zone */
# .drop-label {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.7rem;
#     letter-spacing: 0.15em;
#     text-transform: uppercase;
#     color: var(--accent);
#     margin-bottom: 0.5rem;
#     display: block;
# }
# [data-testid="stFileUploader"] {
#     background: var(--surface) !important;
#     border: 2px dashed var(--border) !important;
#     border-radius: 12px !important;
#     transition: border-color 0.2s;
# }
# [data-testid="stFileUploader"]:hover {
#     border-color: var(--accent) !important;
# }
# [data-testid="stFileUploadDropzone"] {
#     background: transparent !important;
#     padding: 2rem !important;
# }

# /* Stat cards */
# .stat-row { display: flex; gap: 1rem; margin: 1.5rem 0; flex-wrap: wrap; }
# .stat-card {
#     background: var(--surface);
#     border: 1px solid var(--border);
#     border-radius: 10px;
#     padding: 1rem 1.5rem;
#     flex: 1;
#     min-width: 120px;
# }
# .stat-value {
#     font-size: 1.8rem;
#     font-weight: 800;
#     color: var(--accent);
#     line-height: 1;
# }
# .stat-label {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.65rem;
#     letter-spacing: 0.12em;
#     text-transform: uppercase;
#     color: var(--muted);
#     margin-top: 0.3rem;
# }

# /* Table */
# .veo-table {
#     width: 100%;
#     border-collapse: collapse;
#     font-size: 0.88rem;
#     margin-top: 1rem;
# }
# .veo-table th {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.65rem;
#     letter-spacing: 0.12em;
#     text-transform: uppercase;
#     color: var(--accent);
#     padding: 0.6rem 1rem;
#     border-bottom: 1px solid var(--border);
#     text-align: left;
#     background: var(--surface);
# }
# .veo-table td {
#     padding: 0.7rem 1rem;
#     border-bottom: 1px solid var(--border);
#     color: var(--text);
#     vertical-align: top;
#     max-width: 420px;
#     word-wrap: break-word;
# }
# .veo-table tr:hover td { background: rgba(0, 212, 255, 0.04); }
# .badge {
#     display: inline-block;
#     font-family: 'Space Mono', monospace;
#     font-size: 0.62rem;
#     padding: 0.2rem 0.55rem;
#     border-radius: 4px;
#     letter-spacing: 0.05em;
# }
# .badge-auto  { background: #1e3a5f; color: #7dd3fc; }
# .badge-tv    { background: #1e2a1e; color: #86efac; }
# .badge-ms    { background: #2d1b4e; color: #c4b5fd; }
# .badge-dur   { background: #1a2840; color: var(--accent); font-weight: 700; }
# .clip-note   { font-size: 0.7rem; color: var(--muted); margin-top: 0.2rem; }

# /* Submit button */
# .stButton > button {
#     background: var(--accent) !important;
#     color: var(--bg) !important;
#     font-family: 'Syne', sans-serif !important;
#     font-weight: 700 !important;
#     font-size: 1rem !important;
#     padding: 0.7rem 2rem !important;
#     border-radius: 8px !important;
#     border: none !important;
#     transition: opacity 0.2s !important;
#     width: 100%;
# }
# .stButton > button:hover { opacity: 0.85 !important; }
# .stButton > button:disabled { opacity: 0.4 !important; }

# /* Progress */
# .stProgress > div > div { background: var(--accent) !important; }

# /* Job cards */
# .job-card {
#     background: var(--surface);
#     border: 1px solid var(--border);
#     border-radius: 12px;
#     padding: 1.25rem 1.5rem;
#     margin-bottom: 1rem;
# }
# .job-header {
#     display: flex;
#     justify-content: space-between;
#     align-items: center;
#     margin-bottom: 0.75rem;
# }
# .job-id {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.75rem;
#     color: var(--muted);
# }
# .status-pill {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.65rem;
#     padding: 0.25rem 0.7rem;
#     border-radius: 20px;
#     letter-spacing: 0.08em;
#     text-transform: uppercase;
#     font-weight: 700;
# }
# .status-processing { background: rgba(245,158,11,0.15); color: var(--warn); border: 1px solid var(--warn); }
# .status-completed  { background: rgba(16,185,129,0.15); color: var(--success); border: 1px solid var(--success); }
# .status-partial    { background: rgba(124,58,237,0.15); color: #a78bfa; border: 1px solid #7c3aed; }
# .status-failed     { background: rgba(239,68,68,0.15); color: var(--error); border: 1px solid var(--error); }
# .status-pending    { background: rgba(100,116,139,0.15); color: var(--muted); border: 1px solid var(--muted); }

# /* Result rows */
# .result-row {
#     display: flex;
#     align-items: center;
#     gap: 1rem;
#     padding: 0.5rem 0;
#     border-bottom: 1px solid var(--border);
#     font-size: 0.85rem;
# }
# .result-row:last-child { border-bottom: none; }
# .result-prompt {
#     flex: 1;
#     color: var(--muted);
#     font-size: 0.8rem;
#     white-space: nowrap;
#     overflow: hidden;
#     text-overflow: ellipsis;
#     max-width: 300px;
# }
# .result-ok   { color: var(--success); font-family: 'Space Mono', monospace; font-size: 0.7rem; }
# .result-fail { color: var(--error);   font-family: 'Space Mono', monospace; font-size: 0.7rem; }
# .result-proc { color: var(--warn);    font-family: 'Space Mono', monospace; font-size: 0.7rem; }

# /* Download button */
# .dl-btn {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.65rem;
#     background: transparent;
#     border: 1px solid var(--accent);
#     color: var(--accent);
#     padding: 0.25rem 0.6rem;
#     border-radius: 4px;
#     text-decoration: none;
#     transition: background 0.15s;
# }
# .dl-btn:hover { background: rgba(0,212,255,0.1); }

# /* Divider */
# .veo-divider {
#     border: none;
#     border-top: 1px solid var(--border);
#     margin: 2rem 0;
# }

# /* Alerts */
# .veo-alert {
#     border-radius: 8px;
#     padding: 0.9rem 1.2rem;
#     font-size: 0.88rem;
#     margin: 1rem 0;
# }
# .veo-alert-success { background: rgba(16,185,129,0.1); border-left: 3px solid var(--success); color: #6ee7b7; }
# .veo-alert-error   { background: rgba(239,68,68,0.1);  border-left: 3px solid var(--error);   color: #fca5a5; }
# .veo-alert-info    { background: rgba(0,212,255,0.08); border-left: 3px solid var(--accent);  color: #7dd3fc; }

# /* Inputs */
# [data-testid="stTextInput"] input,
# [data-testid="stNumberInput"] input,
# [data-testid="stSelectbox"] select {
#     background: var(--surface) !important;
#     border: 1px solid var(--border) !important;
#     color: var(--text) !important;
#     border-radius: 6px !important;
# }

# /* ── Video grid ──────────────────────────────────────────────────────────── */
# .vid-grid-header {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.7rem;
#     letter-spacing: 0.12em;
#     text-transform: uppercase;
#     color: var(--accent);
#     margin: 2rem 0 1rem;
# }
# .vid-card {
#     background: var(--surface);
#     border: 1px solid var(--border);
#     border-radius: 12px;
#     overflow: hidden;
#     margin-bottom: 1rem;
#     transition: border-color 0.2s;
# }
# .vid-card:hover { border-color: rgba(0,212,255,0.4); }

# /* Aspect-ratio container — height is determined by the CSS aspect-ratio    */
# /* property set inline per card. Width fills the column.                    */
# .vid-ar-box {
#     width: 100%;
#     position: relative;
#     background: var(--border);
#     overflow: hidden;
# }
# .vid-ar-box video {
#     position: absolute;
#     inset: 0;
#     width: 100%;
#     height: 100%;
#     object-fit: cover;
#     display: block;
#     cursor: pointer;
# }

# /* Shimmer skeleton for loading state */
# .vid-skeleton {
#     position: absolute;
#     inset: 0;
#     background: linear-gradient(
#         90deg,
#         var(--surface) 0%,
#         #1a2840 40%,
#         #1f3356 50%,
#         #1a2840 60%,
#         var(--surface) 100%
#     );
#     background-size: 250% 100%;
#     animation: shimmer 1.8s ease-in-out infinite;
# }
# @keyframes shimmer {
#     0%   { background-position:  200% 0; }
#     100% { background-position: -200% 0; }
# }
# .vid-skeleton-icon {
#     position: absolute;
#     inset: 0;
#     display: flex;
#     align-items: center;
#     justify-content: center;
#     font-size: 2rem;
#     opacity: 0.2;
# }

# /* Card footer */
# .vid-footer {
#     padding: 0.6rem 0.75rem 0.4rem;
# }
# .vid-prompt-text {
#     font-size: 0.75rem;
#     color: var(--muted);
#     white-space: nowrap;
#     overflow: hidden;
#     text-overflow: ellipsis;
#     margin-bottom: 0.35rem;
# }
# .vid-meta {
#     font-family: 'Space Mono', monospace;
#     font-size: 0.62rem;
#     color: var(--muted);
#     display: flex;
#     gap: 0.5rem;
#     align-items: center;
#     flex-wrap: wrap;
# }
# .vid-status-ok   { color: var(--success); }
# .vid-status-fail { color: var(--error); }
# .vid-status-proc { color: var(--warn); }
# .vid-ar-tag {
#     background: #1a2840;
#     color: var(--accent);
#     padding: 0.1rem 0.35rem;
#     border-radius: 3px;
#     font-size: 0.58rem;
# }

# /* Rerun button — sits below each video card via st.button */
# [data-testid="stButton"] button[kind="secondary"] {
#     background: transparent !important;
#     border: 1px solid var(--border) !important;
#     color: var(--muted) !important;
#     font-family: 'Space Mono', monospace !important;
#     font-size: 0.65rem !important;
#     padding: 0.25rem 0.6rem !important;
#     width: 100% !important;
#     transition: border-color 0.15s, color 0.15s !important;
# }
# [data-testid="stButton"] button[kind="secondary"]:hover {
#     border-color: var(--warn) !important;
#     color: var(--warn) !important;
# }

# /* ── YouTube queue ───────────────────────────────────────────────────────── */
# .yt-queue-card {
#     background: var(--surface);
#     border: 1px solid var(--border);
#     border-radius: 12px;
#     padding: 1rem 1.25rem;
#     margin-bottom: 1rem;
# }
# .yt-queue-card.uploaded {
#     border-color: var(--success);
# }
# .yt-queue-card.failed {
#     border-color: var(--error);
# }
# .yt-queue-card.uploading {
#     border-color: var(--warn);
# }
# .yt-video-thumb {
#     width: 100%;
#     aspect-ratio: 16/9;
#     object-fit: cover;
#     border-radius: 6px;
#     background: var(--border);
# }
# .yt-link {
#     color: #ff0000;
#     font-family: Space Mono, monospace;
#     font-size: 0.75rem;
#     text-decoration: none;
#     font-weight: 700;
# }
# .yt-link:hover { text-decoration: underline; }
# .approve-badge {
#     display: inline-block;
#     background: rgba(16,185,129,0.15);
#     color: var(--success);
#     border: 1px solid var(--success);
#     border-radius: 20px;
#     font-family: Space Mono, monospace;
#     font-size: 0.62rem;
#     padding: 0.2rem 0.6rem;
#     letter-spacing: 0.06em;
# }
# </style>
# """, unsafe_allow_html=True)


# # ── Session state ─────────────────────────────────────────────────────────────
# for key, default in [
#     ("jobs",           {}),
#     ("active_job",     None),
#     ("upload_error",   None),
#     ("api_ok",         None),
#     ("rerun_pending",  set()),   # set of (job_id, prompt_index) currently rerunning
#     ("is_generating",     False),   # True while a job is running — blocks duplicate submits
#     ("last_completed_job", None),   # job_id of most recently completed job — keeps grid visible
#     ("approved_set",   set()),   # set of (job_id, prompt_index) approved for YouTube
#     ("yt_queue",       []),      # cached YouTube queue from last fetch

# ]:
#     if key not in st.session_state:
#         st.session_state[key] = default


# # ── Helpers ───────────────────────────────────────────────────────────────────

# def check_api() -> bool:
#     try:
#         r = requests.get(f"{API_BASE}/health", timeout=3)
#         return r.status_code == 200
#     except Exception:
#         return False


# def upload_file(file_bytes: bytes, filename: str) -> dict:
#     r = requests.post(
#         f"{API_BASE}/api/upload",
#         files={"file": (filename, file_bytes, "application/octet-stream")},
#         timeout=30,
#     )
#     r.raise_for_status()
#     return r.json()


# def fetch_job(job_id: str) -> dict:
#     r = requests.get(f"{API_BASE}/api/jobs/{job_id}", timeout=10)
#     r.raise_for_status()
#     return r.json()


# def fetch_all_jobs() -> list:
#     try:
#         r = requests.get(f"{API_BASE}/api/jobs", timeout=5)
#         r.raise_for_status()
#         return r.json().get("jobs", [])
#     except Exception:
#         return []


# def approve_video(job_id: str, prompt_index: int) -> Optional[dict]:
#     """POST /api/jobs/{job_id}/approve/{prompt_index} — add to YouTube queue."""
#     try:
#         r = requests.post(
#             f"{API_BASE}/api/jobs/{job_id}/approve/{prompt_index}",
#             timeout=10,
#         )
#         r.raise_for_status()
#         return r.json()
#     except Exception:
#         return None


# def fetch_youtube_queue() -> list:
#     try:
#         r = requests.get(f"{API_BASE}/api/youtube/queue", timeout=5)
#         r.raise_for_status()
#         return r.json().get("queue", [])
#     except Exception:
#         return []


# def update_queue_item(queue_id: str, title: str, description: str, tags: list) -> bool:
#     try:
#         r = requests.patch(
#             f"{API_BASE}/api/youtube/queue/{queue_id}",
#             json={"title": title, "description": description, "tags": tags},
#             timeout=10,
#         )
#         return r.status_code == 200
#     except Exception:
#         return False


# def trigger_youtube_upload() -> dict:
#     try:
#         r = requests.post(f"{API_BASE}/api/youtube/upload", timeout=10)
#         r.raise_for_status()
#         return r.json()
#     except Exception as e:
#         return {"status": "error", "message": str(e)}


# def remove_from_queue(queue_id: str) -> bool:
#     try:
#         r = requests.delete(f"{API_BASE}/api/youtube/queue/{queue_id}", timeout=5)
#         return r.status_code == 200
#     except Exception:
#         return False


# def fetch_youtube_status() -> dict:
#     try:
#         r = requests.get(f"{API_BASE}/api/youtube/status", timeout=5)
#         r.raise_for_status()
#         return r.json()
#     except Exception:
#         return {"configured": False, "authenticated": False}


# def rerun_prompt(job_id: str, prompt_index: int) -> bool:
#     """POST /api/jobs/{job_id}/rerun/{prompt_index}. Returns True on success."""
#     try:
#         r = requests.post(
#             f"{API_BASE}/api/jobs/{job_id}/rerun/{prompt_index}",
#             timeout=10,
#         )
#         return r.status_code == 200
#     except Exception:
#         return False


# def _ar_to_css(ar: str) -> str:
#     """
#     Convert aspect ratio string to CSS aspect-ratio value.
#     '9:16' → '9/16', '16:9' → '16/9', etc.
#     Falls back to '1/1' for unknown values.
#     """
#     mapping = {
#         "9:16": "9/16",
#         "16:9": "16/9",
#         "1:1":  "1/1",
#         "4:3":  "4/3",
#         "3:4":  "3/4",
#     }
#     return mapping.get(str(ar).strip(), "9/16")


# def _safe_int(value, default: int = 0, lo: int = None, hi: int = None) -> int:
#     """
#     Convert any DataFrame cell value to int safely.
#     Handles NaN, None, inf, non-numeric strings.
#     Clamps to [lo, hi] when provided.
#     """
#     import math
#     try:
#         v = float(value)
#         if math.isnan(v) or math.isinf(v):
#             return default
#         result = int(v)
#     except (TypeError, ValueError):
#         return default
#     if lo is not None:
#         result = max(lo, result)
#     if hi is not None:
#         result = min(hi, result)
#     return result


# def clip_count(duration: int) -> int:
#     return -(-duration // CLIP_DURATION)   # ceil div


# def status_pill(status: str) -> str:
#     css = {
#         "processing": "status-processing",
#         "completed":  "status-completed",
#         "partial":    "status-partial",
#         "failed":     "status-failed",
#         "pending":    "status-pending",
#     }.get(status, "status-pending")
#     return f'<span class="status-pill {css}">{status}</span>'


# def badge_task(task_type: str) -> str:
#     css = {"TEXT_VIDEO": "badge-tv", "MULTI_SHOT_AUTOMATED": "badge-ms"}.get(task_type, "badge-auto")
#     label = {"TEXT_VIDEO": "TEXT", "MULTI_SHOT_AUTOMATED": "MULTI"}.get(task_type, "AUTO")
#     return f'<span class="badge {css}">{label}</span>'


# def render_preview_table(df: pd.DataFrame):
#     rows_html = ""
#     for _, row in df.iterrows():
#         dur   = _safe_int(row.get("duration", 8), default=8, lo=1, hi=120)
#         clips = clip_count(dur)
#         tt    = str(row.get("task_type", "AUTO")).upper()
#         prio  = _safe_int(row.get("priority", 5), default=5, lo=1, hi=10)
#         import html as _html
#         prompt = str(row.get("prompt", ""))
#         prompt_display = _html.escape(prompt[:90] + "…" if len(prompt) > 90 else prompt)

#         clip_note = f'<div class="clip-note">→ {clips} clip{"s" if clips > 1 else ""}</div>' if clips > 1 else ""

#         rows_html += f"""
#         <tr>
#             <td style="color:var(--muted);font-family:Space Mono,monospace;font-size:0.7rem">{int(_) + 1}</td>
#             <td>{prompt_display}</td>
#             <td>
#                 <span class="badge badge-dur">{dur}s</span>
#                 {clip_note}
#             </td>
#             <td>{badge_task(tt)}</td>
#             <td style="font-family:Space Mono,monospace;font-size:0.75rem;color:var(--muted)">{prio}</td>
#         </tr>"""

#     st.markdown(f"""
#     <table class="veo-table">
#         <thead><tr>
#             <th>#</th><th>Prompt</th><th>Duration</th><th>Task</th><th>Priority</th>
#         </tr></thead>
#         <tbody>{rows_html}</tbody>
#     </table>""", unsafe_allow_html=True)


# def render_video_grid(job: dict) -> None:
#     """
#     Render a card grid of all prompts in a job.

#     - One card per prompt, laid out in 3 columns.
#     - Each card shows a shimmer skeleton while the video is processing.
#     - Once completed, shows an HTML5 <video> element (click-to-play).
#     - Card height is driven by CSS aspect-ratio matching the prompt's aspect_ratio field.
#     - A '↻ Rerun' button below each completed or failed card lets the user re-generate.

#     Why HTML5 video not st.video:
#         st.video can't be embedded inside column layouts with custom CSS wrappers.
#         The API serves videos on /videos/... — direct URL works in <video src>.
#     """
#     import html as _html

#     prompts   = job.get("prompts", [])
#     results   = job.get("results", {}) if isinstance(job.get("results"), dict) else {}
#     job_id    = job.get("job_id", "")
#     job_status = job.get("status", "processing")

#     if not prompts:
#         return

#     st.markdown('<div class="vid-grid-header">🎬 Generated Videos</div>',
#                 unsafe_allow_html=True)

#     # 3-column grid — all prompts rendered, skeletons for pending
#     cols = st.columns(3)

#     for i, prompt_data in enumerate(prompts):
#         col = cols[i % 3]
#         result = results.get(str(i), {})
#         status = result.get("status", "processing")
#         video_url = result.get("video_url")
#         prompt_text = prompt_data.get("prompt_text") or prompt_data.get("text", "")
#         ar_raw  = prompt_data.get("aspect_ratio", "9:16")
#         ar_css  = _ar_to_css(ar_raw)
#         clips   = result.get("clips_count", 0)
#         dur     = result.get("duration_seconds", 0)
#         err     = result.get("error_message", "")
#         is_rerunning = (job_id, i) in st.session_state.rerun_pending

#         with col:
#             # ── Card header (aspect-ratio box) ────────────────────────────────
#             if status in ("completed", "partial") and video_url:
#                 # video_url is either a local FastAPI route (/videos/...)
#                 # or a full S3 HTTPS URL — handle both
#                 if video_url.startswith("http"):
#                     full_url = video_url          # S3 or external URL — use as-is
#                 else:
#                     full_url = f"{API_BASE}{video_url}"  # local FastAPI route
#                 safe_url  = _html.escape(full_url)
#                 st.markdown(f"""
# <div class="vid-card">
#   <div class="vid-ar-box" style="aspect-ratio:{ar_css}">
#     <video controls preload="metadata">
#       <source src="{safe_url}" type="video/mp4">
#     </video>
#   </div>
#   <div class="vid-footer">
#     <div class="vid-prompt-text" title="{_html.escape(prompt_text[:200])}">{_html.escape(prompt_text[:60])}{'…' if len(prompt_text) > 60 else ''}</div>
#     <div class="vid-meta">
#       <span class="vid-status-ok">✓ done</span>
#       <span class="vid-ar-tag">{ar_raw}</span>
#       {f'<span>{clips} clips · {dur}s</span>' if clips > 1 else ''}
#     </div>
#   </div>
# </div>""", unsafe_allow_html=True)

#             elif status == "failed":
#                 st.markdown(f"""
# <div class="vid-card">
#   <div class="vid-ar-box" style="aspect-ratio:{ar_css}">
#     <div class="vid-skeleton"></div>
#     <div class="vid-skeleton-icon">✗</div>
#   </div>
#   <div class="vid-footer">
#     <div class="vid-prompt-text">{_html.escape(prompt_text[:60])}{'…' if len(prompt_text) > 60 else ''}</div>
#     <div class="vid-meta">
#       <span class="vid-status-fail">✗ failed</span>
#       <span class="vid-ar-tag">{ar_raw}</span>
#     </div>
#     {f'<div style="font-size:0.65rem;color:var(--error);margin-top:0.3rem;padding:0 0.75rem 0.5rem">{_html.escape(err[:80])}</div>' if err else ''}
#   </div>
# </div>""", unsafe_allow_html=True)

#             else:
#                 # Processing / pending — shimmer skeleton
#                 label = "↻ rerunning…" if is_rerunning else "⋯ generating"
#                 st.markdown(f"""
# <div class="vid-card">
#   <div class="vid-ar-box" style="aspect-ratio:{ar_css}">
#     <div class="vid-skeleton"></div>
#     <div class="vid-skeleton-icon">🎬</div>
#   </div>
#   <div class="vid-footer">
#     <div class="vid-prompt-text">{_html.escape(prompt_text[:60])}{'…' if len(prompt_text) > 60 else ''}</div>
#     <div class="vid-meta">
#       <span class="vid-status-proc">{label}</span>
#       <span class="vid-ar-tag">{ar_raw}</span>
#     </div>
#   </div>
# </div>""", unsafe_allow_html=True)

#             # ── Action buttons (below card) ───────────────────────────────────
#             is_approved = (job_id, i) in st.session_state.approved_set

#             if status in ("completed", "partial") and not is_rerunning:
#                 btn_col1, btn_col2 = st.columns(2)

#                 with btn_col1:
#                     if st.button("↻  Rerun", key=f"rerun_{job_id}_{i}", type="secondary"):
#                         ok = rerun_prompt(job_id, i)
#                         if ok:
#                             st.session_state.rerun_pending.add((job_id, i))
#                             # Remove from approved if it was queued
#                             st.session_state.approved_set.discard((job_id, i))
#                             st.rerun()
#                         else:
#                             st.error("Rerun failed — is the API running?")

#                 with btn_col2:
#                     if is_approved:
#                         st.markdown(
#                             '<div style="text-align:center;font-family:Space Mono,monospace;'
#                             'font-size:0.65rem;color:var(--success);padding:0.3rem 0">✓ Approved</div>',
#                             unsafe_allow_html=True,
#                         )
#                     else:
#                         if st.button("✓  Approve", key=f"approve_{job_id}_{i}"):
#                             item = approve_video(job_id, i)
#                             if item:
#                                 st.session_state.approved_set.add((job_id, i))
#                                 st.session_state.yt_queue = fetch_youtube_queue()
#                                 st.rerun()
#                             else:
#                                 st.error("Approve failed — is the API running?")

#             elif status == "failed" and not is_rerunning:
#                 if st.button("↻  Retry", key=f"rerun_{job_id}_{i}", type="secondary"):
#                     ok = rerun_prompt(job_id, i)
#                     if ok:
#                         st.session_state.rerun_pending.add((job_id, i))
#                         st.rerun()
#                     else:
#                         st.error("Retry failed — is the API running?")

#             elif is_rerunning:
#                 if status in ("completed", "failed"):
#                     st.session_state.rerun_pending.discard((job_id, i))


# def render_job_card(job: dict, live: bool = False):
#     job_id   = job.get("job_id", "")
#     status   = job.get("status", "pending")
#     total    = job.get("total_prompts", 0)
#     done     = job.get("completed_prompts", 0)
#     failed   = job.get("failed_prompts", 0)
#     pct      = job.get("progress_percent", 0.0)
#     gen_msg  = job.get("generation_status", "")
#     filename = job.get("original_filename", "")
#     proc_time = job.get("total_processing_time")

#     st.markdown(f"""
#     <div class="job-card">
#         <div class="job-header">
#             <div>
#                 <div style="font-weight:700;margin-bottom:0.2rem">{filename or job_id}</div>
#                 <div class="job-id">{job_id}</div>
#             </div>
#             {status_pill(status)}
#         </div>
#     </div>""", unsafe_allow_html=True)

#     if status in ("processing", "pending") or pct < 100:
#         st.progress(pct / 100)
#         if gen_msg:
#             st.caption(gen_msg)

#     col1, col2, col3 = st.columns(3)
#     col1.metric("Prompts", total)
#     col2.metric("Completed", done)
#     col3.metric("Failed", failed)

#     if proc_time:
#         st.caption(f"Total time: {proc_time}s")

#     # Per-prompt results
#     prompts = job.get("prompts", [])
#     if prompts:
#         with st.expander("Results", expanded=(status in ("completed", "partial"))):
#             for p in prompts:
#                 pstatus = p.get("status", "processing")
#                 text    = p.get("prompt_text", "")[:60] + "…"
#                 vurl    = p.get("video_url")
#                 clips   = p.get("clips_count", 0)
#                 dur     = p.get("duration_seconds")
#                 err     = p.get("error_message", "")

#                 col_a, col_b = st.columns([3, 1])
#                 with col_a:
#                     if pstatus == "completed":
#                         st.markdown(f'<span style="color:var(--success)">✓</span> {text}', unsafe_allow_html=True)
#                         if clips > 1:
#                             st.caption(f"Stitched · {clips} clips · {dur}s")
#                     elif pstatus == "failed":
#                         st.markdown(f'<span style="color:var(--error)">✗</span> {text}', unsafe_allow_html=True)
#                         if err:
#                             st.caption(err)
#                     else:
#                         st.markdown(f'<span style="color:var(--warn)">⋯</span> {text}', unsafe_allow_html=True)

#                 with col_b:
#                     if vurl and pstatus in ("completed", "partial"):
#                         full_url = vurl if vurl.startswith("http") else f"{API_BASE}{vurl}"
#                         st.markdown(
#                             f'<a class="dl-btn" href="{full_url}" target="_blank">⬇ Download</a>',
#                             unsafe_allow_html=True,
#                         )


# # ── Sidebar ───────────────────────────────────────────────────────────────────

# with st.sidebar:
#     st.markdown("### ⚙ Settings")

#     api_url = st.text_input("API URL", value=API_BASE, key="api_url_input")
#     if api_url != API_BASE:
#         API_BASE = api_url

#     if st.button("Check API"):
#         st.session_state.api_ok = check_api()

#     if st.session_state.api_ok is True:
#         st.markdown('<div class="veo-alert veo-alert-success">API online</div>', unsafe_allow_html=True)
#     elif st.session_state.api_ok is False:
#         st.markdown('<div class="veo-alert veo-alert-error">API offline — run python veo_main.py</div>', unsafe_allow_html=True)

#     st.markdown("---")
#     st.markdown("### 📥 Template")
#     if TEMPLATE_PATH.exists():
#         with open(TEMPLATE_PATH, "rb") as f:
#             st.download_button(
#                 label     = "Download veo_template.xlsx",
#                 data      = f.read(),
#                 file_name = "veo_template.xlsx",
#                 mime      = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#             )
#     else:
#         st.caption("veo_template.xlsx not found in project folder")

#     st.markdown("---")
#     st.markdown("### 📋 Column Reference")
#     st.markdown("""
# **Required**
# - `prompt` — video prompt text
# - `duration` — seconds (1–120)

# **Optional**
# - `task_type` — AUTO / TEXT_VIDEO / MULTI_SHOT_AUTOMATED
# - `priority` — 1–10 (lower = first)

# **Clip rule**
# Veo generates 8s clips.
# - 8s → 1 clip
# - 16s → 2 clips (stitched)
# - 24s → 3 clips (stitched)
# """)


# # ── Main layout ───────────────────────────────────────────────────────────────

# st.markdown("""
# <div class="veo-title">Veo <span>Studio</span></div>
# <div class="veo-sub">Google Veo 3.1 · Batch video generation · Native audio</div>
# """, unsafe_allow_html=True)

# tab_upload, tab_jobs, tab_metrics, tab_youtube = st.tabs(["🎬 Upload & Generate", "📊 Jobs", "📊 Metrics", "▶ YouTube Queue"])


# # ══════════════════════════════════════════════════════════════════════════════
# # Tab 1 — Upload
# # ══════════════════════════════════════════════════════════════════════════════

# with tab_upload:

#     st.markdown('<span class="drop-label">Drop your Excel file here</span>', unsafe_allow_html=True)

#     uploaded = st.file_uploader(
#         label      = "Upload Excel",
#         type       = ["xlsx", "xls", "csv"],
#         label_visibility = "collapsed",
#     )

#     if uploaded is not None:
#         # ── Parse preview ──────────────────────────────────────────────────────
#         try:
#             if uploaded.name.lower().endswith(".csv"):
#                 df_raw = pd.read_csv(uploaded)
#             else:
#                 df_raw = pd.read_excel(uploaded)

#             uploaded.seek(0)  # reset for later upload

#             # Normalise column names
#             df_raw.columns = [str(c).strip().lower() for c in df_raw.columns]
#             alias = {"text": "prompt", "video_prompt": "prompt",
#                      "duration_s": "duration", "duration_sec": "duration",
#                      "tasktype": "task_type", "type": "task_type",
#                      "prio": "priority", "rank": "priority"}
#             df_raw = df_raw.rename(columns={c: alias[c] for c in df_raw.columns if c in alias})

#             has_prompt   = "prompt"   in df_raw.columns
#             has_duration = "duration" in df_raw.columns

#         except Exception as e:
#             st.error(f"Could not read file: {e}")
#             st.stop()

#         # ── Validation banner ──────────────────────────────────────────────────
#         errors = []
#         if not has_prompt:
#             errors.append("Missing required column: **prompt**")
#         if not has_duration:
#             errors.append("Missing required column: **duration**")

#         if errors:
#             for err in errors:
#                 st.markdown(f'<div class="veo-alert veo-alert-error">✗ {err}</div>', unsafe_allow_html=True)
#             st.stop()

#         # Drop empties + metadata rows (notes rows have prompt text but no duration)
#         df_clean = df_raw.dropna(subset=["prompt"])
#         df_clean = df_clean[df_clean["prompt"].astype(str).str.strip() != ""]
#         if "duration" in df_clean.columns:
#             df_clean = df_clean[df_clean["duration"].apply(
#                 lambda v: not (v is None or (isinstance(v, float) and __import__("math").isnan(v)))
#             )]

#         if df_clean.empty:
#             st.markdown('<div class="veo-alert veo-alert-error">No non-empty prompts found.</div>', unsafe_allow_html=True)
#             st.stop()

#         # ── Stats ──────────────────────────────────────────────────────────────
#         total_rows  = len(df_clean)
#         total_dur   = int(df_clean["duration"].apply(lambda x: _safe_int(x, 8, 1, 120)).sum()) if "duration" in df_clean.columns else 0
#         total_clips = int(df_clean["duration"].apply(lambda x: clip_count(_safe_int(x, 8, 1, 120))).sum()) if "duration" in df_clean.columns else 0
#         multi_count = int((df_clean["duration"].apply(lambda x: _safe_int(x, 8, 1, 120)) > 8).sum()) if "duration" in df_clean.columns else 0

#         st.markdown(f"""
#         <div class="stat-row">
#             <div class="stat-card">
#                 <div class="stat-value">{total_rows}</div>
#                 <div class="stat-label">Prompts</div>
#             </div>
#             <div class="stat-card">
#                 <div class="stat-value">{total_clips}</div>
#                 <div class="stat-label">Total Clips</div>
#             </div>
#             <div class="stat-card">
#                 <div class="stat-value">{total_dur}s</div>
#                 <div class="stat-label">Total Duration</div>
#             </div>
#             <div class="stat-card">
#                 <div class="stat-value">{multi_count}</div>
#                 <div class="stat-label">Multi-clip Rows</div>
#             </div>
#         </div>
#         """, unsafe_allow_html=True)

#         st.markdown('<div class="veo-alert veo-alert-info">Preview — first 20 rows</div>', unsafe_allow_html=True)
#         render_preview_table(df_clean.head(20))

#         st.markdown("<hr class='veo-divider'>", unsafe_allow_html=True)

#         # ── Submit ─────────────────────────────────────────────────────────────
#         btn_disabled = not check_api()

#         if btn_disabled:
#             st.markdown(
#                 '<div class="veo-alert veo-alert-error">⚠ API offline — start veo_main.py before submitting</div>',
#                 unsafe_allow_html=True,
#             )

#         # Disable the button if the API is offline OR a job is already running.
#         # This prevents the polling rerun loop from re-firing the upload.
#         btn_disabled = btn_disabled or st.session_state.is_generating

#         if st.session_state.is_generating:
#             st.markdown(
#                 '<div class="veo-alert veo-alert-info">⏳ Generation in progress — button locked until complete</div>',
#                 unsafe_allow_html=True,
#             )

#         if st.button("🚀 Start Veo Generation", disabled=btn_disabled):
#             # Lock immediately — before ANY async work — so that any rerun
#             # triggered during the upload sees the button as disabled.
#             st.session_state.is_generating = True
#             with st.spinner("Uploading to Veo service…"):
#                 try:
#                     file_bytes = uploaded.read()
#                     result     = upload_file(file_bytes, uploaded.name)

#                     job_id = result.get("job_id")
#                     st.session_state.jobs[job_id]  = result
#                     st.session_state.active_job    = job_id
#                     st.session_state.upload_error  = None

#                     st.markdown(
#                         f'<div class="veo-alert veo-alert-success">✓ Job submitted — ID: <code>{job_id}</code></div>',
#                         unsafe_allow_html=True,
#                     )

#                 except requests.exceptions.ConnectionError:
#                     st.session_state.upload_error = "Cannot connect to API. Is veo_main.py running on port 8100?"
#                     st.session_state.is_generating = False
#                 except Exception as e:
#                     st.session_state.upload_error = str(e)
#                     st.session_state.is_generating = False

#         if st.session_state.upload_error:
#             st.markdown(
#                 f'<div class="veo-alert veo-alert-error">✗ {st.session_state.upload_error}</div>',
#                 unsafe_allow_html=True,
#             )

#         # ── Video grid — appears below upload UI once a job is running ──────────
#         if st.session_state.active_job or st.session_state.get("last_completed_job"):
#             # Show grid for the active job, or the most recently completed one
#             display_job_id = (
#                 st.session_state.active_job
#                 or st.session_state.get("last_completed_job")
#             )
#             if display_job_id:
#                 try:
#                     live_job = fetch_job(display_job_id)
#                     display_job = {
#                         **live_job.get("summary", {}),
#                         "prompts":  live_job.get("prompts", []),
#                         "status":   live_job.get("status", "processing"),
#                         "results":  {
#                             str(i): {
#                                 "status":    p.get("status"),
#                                 "video_url": p.get("video_url"),
#                                 "clips_count": p.get("clips_count", 0),
#                                 "duration_seconds": p.get("duration_seconds"),
#                                 "error_message": p.get("error_message", ""),
#                             }
#                             for i, p in enumerate(live_job.get("prompts", []))
#                         },
#                         "job_id": display_job_id,
#                     }
#                     render_video_grid(display_job)

#                     # Auto-poll while job is still running.
#                     # We use st.rerun() with a small fragment sleep instead of
#                     # blocking the main thread with time.sleep() — a blocked
#                     # thread queues up browser clicks and causes duplicate submits.
#                     if live_job.get("status") in ("processing", "pending"):
#                         st.session_state.active_job = display_job_id
#                         time.sleep(POLL_INTERVAL)   # sleep is safe here — we're post-render
#                         st.rerun()
#                     else:
#                         # completed, partial, or failed — job is done
#                         # Store last_completed_job so grid keeps showing after active_job clears
#                         st.session_state.last_completed_job = display_job_id
#                         st.session_state.active_job         = None
#                         st.session_state.is_generating      = False  # unlock button
#                 except Exception:
#                     pass

#     else:
#         # Empty state
#         st.markdown("""
#         <div style="text-align:center;padding:3rem 0;color:var(--muted)">
#             <div style="font-size:3rem;margin-bottom:1rem">🎬</div>
#             <div style="font-size:1.1rem;font-weight:600;margin-bottom:0.5rem">Drop an Excel file to get started</div>
#             <div style="font-family:Space Mono,monospace;font-size:0.75rem">
#                 Required columns: <span style="color:var(--accent)">prompt</span> · <span style="color:var(--accent)">duration</span>
#             </div>
#             <div style="margin-top:1rem;font-family:Space Mono,monospace;font-size:0.7rem">
#                 Download the template from the sidebar →
#             </div>
#         </div>
#         """, unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # Tab 2 — Jobs
# # ══════════════════════════════════════════════════════════════════════════════

# with tab_jobs:

#     col_refresh, col_auto = st.columns([1, 2])
#     with col_refresh:
#         if st.button("↻ Refresh"):
#             pass  # triggers rerun
#     with col_auto:
#         auto_refresh = st.checkbox("Auto-refresh every 4s", value=bool(st.session_state.active_job))

#     # Fetch active job
#     if st.session_state.active_job:
#         try:
#             live_job = fetch_job(st.session_state.active_job)
#             st.session_state.jobs[st.session_state.active_job] = {
#                 **live_job.get("summary", {}),
#                 "prompts": live_job.get("prompts", []),
#                 "status":  live_job.get("status", "processing"),
#             }
#             # Clear active once done
#             if live_job.get("status") in ("completed", "partial", "failed"):
#                 st.session_state.active_job = None
#         except Exception:
#             pass

#     # Merge with server jobs
#     server_jobs = {j["job_id"]: j for j in fetch_all_jobs()}
#     all_jobs = {**server_jobs, **st.session_state.jobs}

#     if not all_jobs:
#         st.markdown("""
#         <div style="text-align:center;padding:3rem 0;color:var(--muted)">
#             <div style="font-size:2rem;margin-bottom:0.75rem">📭</div>
#             <div>No jobs yet — upload an Excel file to start</div>
#         </div>
#         """, unsafe_allow_html=True)
#     else:
#         st.markdown(f"**{len(all_jobs)} job{'s' if len(all_jobs) != 1 else ''}**")
#         for job_id, job in sorted(all_jobs.items(), reverse=True):
#             render_job_card(job, live=(job_id == st.session_state.active_job))

#     # Auto-refresh while a job is running
#     if auto_refresh and st.session_state.active_job:
#         time.sleep(POLL_INTERVAL)
#         st.rerun()


# # ══════════════════════════════════════════════════════════════════════════════
# # Tab 3 — YouTube Queue
# # ══════════════════════════════════════════════════════════════════════════════

# with tab_metrics:
#     st.markdown("### 📊 Live Generation Metrics")
#     st.caption("Updates every 5 seconds. Resets when veo_main.py restarts.")

#     def fetch_metrics() -> dict:
#         try:
#             r = requests.get(f"{API_BASE}/api/metrics", timeout=5)
#             r.raise_for_status()
#             return r.json()
#         except Exception:
#             return {}

#     m = fetch_metrics()

#     if not m:
#         st.warning("Cannot reach API — start veo_main.py first.")
#     else:
#         # ── Session overview ──────────────────────────────────────────────
#         col1, col2, col3, col4 = st.columns(4)
#         with col1:
#             st.metric("Jobs Processed", m.get("jobs_processed", 0))
#         with col2:
#             st.metric("Clips Generated", m["veo"]["clips_generated"])
#         with col3:
#             st.metric("Avg Clip Time", f"{m['veo']['avg_clip_time_s']}s")
#         with col4:
#             est = m.get("cost_estimate", {})
#             st.metric("Est. Cost (session)", f"₹{est.get('inr', 0):.2f}")

#         st.divider()

#         # ── Veo API ──────────────────────────────────────────────────────
#         st.markdown("#### 🎬 Veo API")
#         v = m["veo"]
#         c1, c2, c3, c4, c5 = st.columns(5)
#         c1.metric("Submissions",     v["submissions"])
#         c2.metric("Successes",       v["successes"])
#         c3.metric("Failures",        v["failures"],
#                   delta=f"-{v['failures']}" if v["failures"] else None,
#                   delta_color="inverse")
#         c4.metric("429 Rate Limits", v["rate_limit_hits"],
#                   delta=f"{v['rate_limit_pct']}%" if v["rate_limit_hits"] else None,
#                   delta_color="inverse")
#         c5.metric("Total Gen Time",  f"{v['total_gen_time_s']}s")

#         rl_pct = v["rate_limit_pct"]
#         if v["submissions"] == 0:
#             st.info("No submissions yet this session.")
#         elif rl_pct == 0:
#             st.success("✅ No rate limit hits this session")
#         elif rl_pct < 20:
#             st.warning(f"⚠️ {rl_pct}% of submissions hit rate limits")
#         else:
#             st.error(f"🔴 {rl_pct}% rate limit hit rate — reduce concurrency or upgrade quota")

#         st.divider()

#         # ── Decomposer ────────────────────────────────────────────────────
#         st.markdown("#### 🧠 Prompt Decomposer (AWS Bedrock)")
#         d = m["decomposer"]
#         d1, d2, d3, d4, d5 = st.columns(5)
#         d1.metric("Nova 2 Lite Calls",  d["nova_calls"])
#         d2.metric("DeepSeek R1 Calls",  d["deepseek_calls"],
#                   delta=f"+{d['deepseek_calls']} fallbacks" if d["deepseek_calls"] else None,
#                   delta_color="inverse")
#         d3.metric("Deterministic",      d["deterministic"],
#                   delta=f"+{d['deterministic']} fallbacks" if d["deterministic"] else None,
#                   delta_color="inverse")
#         d4.metric("Input Tokens",       f"{d['input_tokens']:,}")
#         d5.metric("Output Tokens",      f"{d['output_tokens']:,}")

#         nova_cost_inr = (d["input_tokens"]  / 1000 * 0.000060 +
#                          d["output_tokens"] / 1000 * 0.000240) * 92.5
#         ds_cost_inr   = (d["input_tokens"]  / 1000 * 0.00135  +
#                          d["output_tokens"] / 1000 * 0.00540)  * 92.5
#         st.caption(
#             f"Bedrock cost — Nova: ₹{nova_cost_inr:.4f}  |  "
#             f"DeepSeek (if called): ₹{ds_cost_inr:.4f}"
#         )

#         st.divider()

#         # ── S3 ────────────────────────────────────────────────────────────
#         st.markdown("#### ☁️ S3 Uploads")
#         s = m["s3"]
#         s1, s2 = st.columns(2)
#         s1.metric("Succeeded", s["uploads_ok"])
#         s2.metric("Failed",    s["uploads_fail"],
#                   delta=f"-{s['uploads_fail']}" if s["uploads_fail"] else None,
#                   delta_color="inverse")

#         st.divider()

#         # ── Cost summary ──────────────────────────────────────────────────
#         st.markdown("#### 💰 Session Cost Estimate")
#         est = m.get("cost_estimate", {})
#         st.info(
#             f"**${est.get('usd', 0):.4f} USD  /  ₹{est.get('inr', 0):.2f} INR**  "
#             f"(primary model rate · successful clips only)  \n"
#             f"_{est.get('note', '')}_"
#         )

#     # Only auto-refresh metrics while a job is actively running.
#     # Unconditional rerun here competes with the generate tab polling loop
#     # and causes duplicate card rendering on every cycle.
#     if st.session_state.get("active_job") or st.session_state.get("is_generating"):
#         time.sleep(5)
#         st.rerun()

# with tab_youtube:
#     import html as _html

#     # ── YouTube connection status ─────────────────────────────────────────────
#     yt_status = fetch_youtube_status()
#     configured    = yt_status.get("configured", False)
#     authenticated = yt_status.get("authenticated", False)

#     if not configured:
#         st.markdown("""
# <div class="veo-alert veo-alert-error">
# ⚠ <code>youtube_client_secrets.json</code> not found in project folder.<br>
# Download it from Google Cloud Console → APIs & Services → Credentials.
# </div>""", unsafe_allow_html=True)
#     elif not authenticated:
#         st.markdown("""
# <div class="veo-alert veo-alert-info">
# YouTube connected but not authenticated yet.<br>
# Click the button below to open a browser and approve access (one-time only).
# </div>""", unsafe_allow_html=True)
#         if st.button("🔐 Authenticate with YouTube"):
#             try:
#                 r = requests.post(f"{API_BASE}/api/youtube/auth", timeout=120)
#                 if r.status_code == 200:
#                     st.markdown('<div class="veo-alert veo-alert-success">✓ Authenticated successfully</div>',
#                                 unsafe_allow_html=True)
#                     st.rerun()
#                 else:
#                     st.error(f"Auth failed: {r.text}")
#             except Exception as e:
#                 st.error(f"Auth error: {e}")
#     else:
#         st.markdown('<div class="veo-alert veo-alert-success">✓ YouTube connected and authenticated</div>',
#                     unsafe_allow_html=True)

#     st.markdown("<hr class='veo-divider'>", unsafe_allow_html=True)

#     # ── Queue header ──────────────────────────────────────────────────────────
#     col_title, col_upload = st.columns([3, 1])
#     with col_title:
#         st.markdown("### Upload Queue")
#         st.caption("Approve videos in the Generate tab → they appear here for review before upload.")

#     # Fetch fresh queue
#     queue = fetch_youtube_queue()
#     st.session_state.yt_queue = queue

#     approved_count  = sum(1 for q in queue if q["status"] == "approved")
#     uploaded_count  = sum(1 for q in queue if q["status"] == "uploaded")
#     uploading_count = sum(1 for q in queue if q["status"] == "uploading")
#     failed_count    = sum(1 for q in queue if q["status"] == "failed")

#     with col_upload:
#         st.markdown("<br>", unsafe_allow_html=True)
#         upload_disabled = approved_count == 0 or not authenticated
#         if st.button(
#             f"▶  Upload {approved_count} to YouTube" if approved_count > 0 else "▶  Upload to YouTube",
#             disabled=upload_disabled,
#             type="primary",
#         ):
#             result = trigger_youtube_upload()
#             if result.get("status") == "started":
#                 st.markdown(
#                     f'<div class="veo-alert veo-alert-success">✓ Upload started — {result.get("count")} video(s)</div>',
#                     unsafe_allow_html=True,
#                 )
#                 time.sleep(1)
#                 st.rerun()
#             else:
#                 st.error(result.get("message", "Upload failed"))

#     # ── Stats row ─────────────────────────────────────────────────────────────
#     if queue:
#         st.markdown(f"""
# <div class="stat-row">
#     <div class="stat-card"><div class="stat-value">{len(queue)}</div><div class="stat-label">In Queue</div></div>
#     <div class="stat-card"><div class="stat-value" style="color:var(--warn)">{approved_count}</div><div class="stat-label">Approved</div></div>
#     <div class="stat-card"><div class="stat-value" style="color:var(--success)">{uploaded_count}</div><div class="stat-label">Uploaded</div></div>
#     <div class="stat-card"><div class="stat-value" style="color:var(--error)">{failed_count}</div><div class="stat-label">Failed</div></div>
# </div>""", unsafe_allow_html=True)

#     st.markdown("<hr class='veo-divider'>", unsafe_allow_html=True)

#     # ── Queue items ───────────────────────────────────────────────────────────
#     if not queue:
#         st.markdown("""
# <div style="text-align:center;padding:3rem 0;color:var(--muted)">
#     <div style="font-size:2rem;margin-bottom:0.75rem">▶</div>
#     <div>No videos in the upload queue yet.</div>
#     <div style="font-family:Space Mono,monospace;font-size:0.75rem;margin-top:0.5rem">
#         Generate videos → click ✓ Approve on any completed video
#     </div>
# </div>""", unsafe_allow_html=True)
#     else:
#         for item in queue:
#             qid       = item["queue_id"]
#             status    = item["status"]
#             yt_url    = item.get("youtube_url")
#             video_url = item.get("video_url", "")
#             err       = item.get("error", "")

#             status_colors = {
#                 "approved":  "var(--warn)",
#                 "uploading": "var(--accent)",
#                 "uploaded":  "var(--success)",
#                 "failed":    "var(--error)",
#             }
#             status_labels = {
#                 "approved":  "⏳ Approved — ready to upload",
#                 "uploading": "⬆ Uploading…",
#                 "uploaded":  "✓ Uploaded to YouTube",
#                 "failed":    "✗ Upload failed",
#             }
#             sc = status_colors.get(status, "var(--muted)")
#             sl = status_labels.get(status, status)

#             card_class = f"yt-queue-card {status}"
#             st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)

#             card_col1, card_col2 = st.columns([1, 2])

#             with card_col1:
#                 if video_url:
#                     full_url = video_url if video_url.startswith("http") else f"{API_BASE}{video_url}"
#                     st.markdown(
#                         f'<video class="yt-video-thumb" src="{_html.escape(full_url)}" preload="metadata"></video>',
#                         unsafe_allow_html=True,
#                     )
#                 if yt_url:
#                     st.markdown(
#                         f'<a class="yt-link" href="{yt_url}" target="_blank">▶ Watch on YouTube →</a>',
#                         unsafe_allow_html=True,
#                     )

#             with card_col2:
#                 st.markdown(
#                     f'<div style="font-family:Space Mono,monospace;font-size:0.65rem;color:{sc};margin-bottom:0.5rem">{sl}</div>',
#                     unsafe_allow_html=True,
#                 )
#                 if err:
#                     st.markdown(
#                         f'<div style="font-size:0.7rem;color:var(--error);margin-bottom:0.5rem">{_html.escape(err[:120])}</div>',
#                         unsafe_allow_html=True,
#                     )

#                 # Editable fields — only shown for approved/failed (not uploaded/uploading)
#                 if status in ("approved", "failed"):
#                     new_title = st.text_input(
#                         "Title",
#                         value=item.get("title", ""),
#                         max_chars=100,
#                         key=f"yt_title_{qid}",
#                     )
#                     new_desc = st.text_area(
#                         "Description",
#                         value=item.get("description", ""),
#                         height=100,
#                         key=f"yt_desc_{qid}",
#                     )
#                     tags_str = st.text_input(
#                         "Tags (comma-separated)",
#                         value=", ".join(item.get("tags", [])),
#                         key=f"yt_tags_{qid}",
#                     )
#                     new_tags = [t.strip() for t in tags_str.split(",") if t.strip()]

#                     btn_c1, btn_c2 = st.columns(2)
#                     with btn_c1:
#                         if st.button("💾  Save", key=f"yt_save_{qid}", type="secondary"):
#                             ok = update_queue_item(qid, new_title, new_desc, new_tags)
#                             if ok:
#                                 st.markdown(
#                                     '<div class="veo-alert veo-alert-success" style="padding:0.4rem 0.8rem;font-size:0.8rem">Saved</div>',
#                                     unsafe_allow_html=True,
#                                 )
#                                 st.rerun()
#                     with btn_c2:
#                         if st.button("🗑  Remove", key=f"yt_remove_{qid}", type="secondary"):
#                             remove_from_queue(qid)
#                             st.rerun()
#                 else:
#                     # Read-only view for uploaded/uploading
#                     st.markdown(f"**{_html.escape(item.get('title', ''))}**")
#                     st.caption(item.get("description", "")[:200])
#                     if item.get("tags"):
#                         st.caption("Tags: " + ", ".join(item["tags"][:8]))

#             st.markdown('</div>', unsafe_allow_html=True)
#             st.markdown("")

#     # Auto-refresh while uploads are in progress
#     if uploading_count > 0:
#         time.sleep(3)
#         st.rerun()

























"""
veo_app.py — Veo Studio Frontend
══════════════════════════════════
Apple-minimal Streamlit UI. Role-based auth via auth.py.

Run:
    streamlit run veo_app.py
Requires:
    python veo_main.py   (API on port 8100)
    pip install streamlit pandas openpyxl requests
"""

import html as _html
import io
import math
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import streamlit as st

from auth import require_auth, has_permission, get_current_user, logout

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE      = "http://localhost:8100"


def _headers() -> dict:
    """
    Return auth headers for every API request.
    The backend reads X-User-Id and X-User-Role to filter jobs by owner.
    When real JWT auth is added, replace X-User-Id/Role with Authorization: Bearer <token>.
    """
    user = get_current_user() or {}
    return {
        "X-User-Id":   user.get("email", "anonymous"),
        "X-User-Role": user.get("role",  "viewer"),
    }


POLL_INTERVAL = 4
CLIP_DURATION = 8
TEMPLATE_PATH = Path(__file__).parent / "veo_template.xlsx"

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(page_title="Veo Studio", page_icon="🎬", layout="wide")

# ── Auth gate ─────────────────────────────────────────────────────────────────
require_auth()

# ── Design tokens ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
html, body, [data-testid="stApp"] {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                 "SF Pro Text", "Helvetica Neue", Arial, sans-serif !important;
}

/* Light mode tokens */
:root {
    --bg:        #F5F5F7;
    --surface:   #FFFFFF;
    --surface2:  #F5F5F7;
    --border:    #D2D2D7;
    --border2:   #E8E8ED;
    --text:      #1D1D1F;
    --text2:     #6E6E73;
    --text3:     #86868B;
    --accent:    #0071E3;
    --success:   #34C759;
    --warn:      #FF9F0A;
    --error:     #FF3B30;
    --skel:      #E5E5EA;
    --skel2:     #F0F0F5;
}

/* Dark mode tokens */
@media (prefers-color-scheme: dark) {
    :root {
        --bg:        #000000;
        --surface:   #1C1C1E;
        --surface2:  #2C2C2E;
        --border:    #3A3A3C;
        --border2:   #2C2C2E;
        --text:      #F5F5F7;
        --text2:     rgba(235,235,245,.8);
        --text3:     rgba(235,235,245,.6);
        --accent:    #0A84FF;
        --success:   #30D158;
        --warn:      #FF9F0A;
        --error:     #FF453A;
        --skel:      #3A3A3C;
        --skel2:     #48484A;
    }
}

html, body, [data-testid="stApp"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
}
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stToolbar"] { display: none; }
.block-container { padding: 0 2rem 4rem; max-width: 1160px; }

/* ── Navbar ── */
.vs-nav {
    display: flex; align-items: center; justify-content: space-between;
    padding: 1rem 0; border-bottom: 1px solid var(--border); margin-bottom: 2.5rem;
}
.vs-nav-logo { font-size: 1.05rem; font-weight: 600; letter-spacing: -.02em; color: var(--text); }
.vs-nav-logo span { color: var(--text2); font-weight: 400; }
.vs-nav-right { display: flex; align-items: center; gap: .75rem; }
.vs-role { font-size: .7rem; font-weight: 500; padding: .15rem .55rem;
           border-radius: 20px; border: 1px solid var(--border); color: var(--text2);
           text-transform: capitalize; }
.vs-nav-user { font-size: .82rem; color: var(--text2); }

/* ── Tabs ── */
[data-testid="stTabs"] [role="tablist"] {
    gap: 0; border-bottom: 1px solid var(--border);
}
[data-testid="stTabs"] button[role="tab"] {
    font-size: .85rem; font-weight: 500; color: var(--text2) !important;
    padding: .55rem 1rem; border-radius: 0 !important; border: none !important;
    background: none !important; border-bottom: 2px solid transparent !important;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: var(--text) !important; border-bottom: 2px solid var(--text) !important;
}

/* ── File uploader ── */
[data-testid="stFileUploader"] section {
    border: 1.5px dashed var(--border) !important;
    border-radius: 14px !important;
    background: var(--surface) !important;
    padding: 2rem !important;
    transition: border-color .2s;
}
[data-testid="stFileUploader"] section:hover { border-color: var(--accent) !important; }
[data-testid="stFileUploaderDropzoneInstructions"] span { color: var(--text2) !important; }

/* ── Buttons ── */
[data-testid="stButton"] > button {
    border-radius: 980px !important; font-weight: 500 !important;
    font-family: inherit !important; font-size: .85rem !important;
    transition: all .15s !important; border: 1px solid var(--border) !important;
    background: var(--surface) !important; color: var(--text) !important;
    padding: .45rem 1.1rem !important;
}
[data-testid="stButton"] > button:hover {
    background: var(--surface2) !important; border-color: var(--text2) !important;
}
[data-testid="stButton"] > button[kind="primary"] {
    background: var(--text) !important; color: var(--bg) !important;
    border-color: var(--text) !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover { opacity: .85 !important; }
[data-testid="stButton"] > button:disabled { opacity: .35 !important; }
[data-testid="stDownloadButton"] > button {
    border-radius: 980px !important; font-weight: 500 !important;
    font-family: inherit !important; font-size: .85rem !important;
    border: 1px solid var(--border) !important;
    background: var(--surface) !important; color: var(--text) !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    border: 1px solid var(--border2) !important;
    border-radius: 12px !important; background: var(--surface) !important;
}
summary { color: var(--text) !important; font-size: .9rem !important; font-weight: 500 !important; }

/* ── Inputs ── */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background: var(--surface) !important; border: 1px solid var(--border) !important;
    border-radius: 8px !important; color: var(--text) !important; font-family: inherit !important;
}
[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label { color: var(--text2) !important; font-size: .82rem !important; }

/* ── Metric ── */
[data-testid="stMetric"] { background: var(--surface); border: 1px solid var(--border2);
    border-radius: 12px; padding: .85rem 1rem; }
[data-testid="stMetricLabel"] { color: var(--text2) !important; font-size: .75rem !important;
    font-weight: 500 !important; }
[data-testid="stMetricValue"] { color: var(--text) !important; font-size: 1.5rem !important;
    font-weight: 600 !important; letter-spacing: -.03em !important; }

/* ── Table helpers ── */
.vs-table-wrap { background: var(--surface); border-radius: 12px;
    border: 1px solid var(--border2); overflow: hidden; margin-top: 1.25rem; }
.vs-table-cap { font-size: .73rem; font-weight: 600; color: var(--text2);
    letter-spacing: .04em; text-transform: uppercase; padding: .65rem 1.2rem;
    border-bottom: 1px solid var(--border2); background: var(--surface2); }
.vs-tbl { width: 100%; border-collapse: collapse; font-size: .83rem; }
.vs-tbl th { text-align: left; padding: .55rem 1.2rem; font-weight: 500;
    color: var(--text2); font-size: .76rem; background: var(--surface2);
    border-bottom: 1px solid var(--border2); }
.vs-tbl td { padding: .6rem 1.2rem; color: var(--text); border-bottom: 1px solid var(--border2);
    vertical-align: top; }
.vs-tbl tr:last-child td { border-bottom: none; }
.vs-tbl tr:hover td { background: var(--surface2); }
.vs-ellipsis { max-width: 360px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.vs-badge { display: inline-block; font-size: .7rem; font-weight: 500;
    padding: .15rem .5rem; border-radius: 20px; border: 1px solid var(--border); color: var(--text2); }
.vs-badge-blue { border-color: #0071E340; color: var(--accent); background: #0071E310; }

/* ── Status pill ── */
.vs-pill { display: inline-block; font-size: .7rem; font-weight: 500;
    padding: .15rem .55rem; border-radius: 20px; }
.pill-done    { background: #34C75920; color: #34C759; }
.pill-partial { background: #FF9F0A20; color: #FF9F0A; }
.pill-run     { background: #0071E320; color: #0071E3; }
.pill-fail    { background: #FF3B3020; color: #FF3B30; }

/* ── Video card ── */
.vs-card { background: var(--surface); border: 1px solid var(--border2);
    border-radius: 16px; overflow: hidden; }
.vs-card:hover { box-shadow: 0 4px 20px rgba(0,0,0,.07); }
.vs-card-body { padding: .85rem 1rem .75rem; }
.vs-card-prompt { font-size: .8rem; color: var(--text2); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; margin-bottom: .45rem; }
.vs-card-meta { display: flex; align-items: center; gap: .4rem;
    flex-wrap: wrap; margin-bottom: .7rem; }

/* ── Skeleton ── */
@keyframes sk { 0%{background-position:-500px 0} 100%{background-position:500px 0} }
.vs-sk {
    background: linear-gradient(90deg,var(--skel) 25%,var(--skel2) 50%,var(--skel) 75%);
    background-size: 500px 100%; animation: sk 1.4s infinite linear; border-radius: 6px;
}
.vs-sk-video { width:100%; padding-top:177.78%; border-radius:14px 14px 0 0;
    background: linear-gradient(90deg,var(--skel) 25%,var(--skel2) 50%,var(--skel) 75%);
    background-size:500px 100%; animation:sk 1.4s infinite linear; }
.vs-sk-line { height:10px; margin:.35rem 1rem; }
.w60{width:60%} .w40{width:40%}
.vs-sk-btn { height:30px; border-radius:980px; margin:.5rem 1rem; }

/* ── Section headings ── */
.vs-h { font-size:1.35rem; font-weight:600; letter-spacing:-.025em;
    color:var(--text); margin-bottom:.3rem; }
.vs-sub { font-size:.85rem; color:var(--text2); margin-bottom:1.5rem; }

/* ── Alert ── */
.vs-alert { display:flex; align-items:flex-start; gap:.6rem; font-size:.84rem;
    padding:.7rem 1rem; border-radius:10px; margin-bottom:1rem; line-height:1.4; }
.al-info  { background:#0071E312; border:1px solid #0071E330; color:var(--text); }
.al-warn  { background:#FF9F0A12; border:1px solid #FF9F0A30; color:var(--text); }
.al-error { background:#FF3B3012; border:1px solid #FF3B3030; color:var(--text); }

/* ── Divider ── */
hr { border:none; border-top:1px solid var(--border2) !important; margin:1.75rem 0 !important; }
</style>
""", unsafe_allow_html=True)


# ── Session state defaults ────────────────────────────────────────────────────
for _k, _v in [
    ("jobs",               {}),
    ("active_job",         None),
    ("last_completed_job", None),
    ("is_generating",      False),
    ("df_preview",         None),
    ("file_bytes",         None),
    ("file_name",          None),
    ("rejected",           set()),    # set of (job_id, prompt_index)
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ══════════════════════════════════════════════════════════════════════════════
# API helpers
# ══════════════════════════════════════════════════════════════════════════════

def check_api() -> bool:
    try:
        return requests.get(f"{API_BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


def upload_file(file_bytes: bytes, filename: str) -> dict:
    r = requests.post(
        f"{API_BASE}/api/upload",
        files={"file": (filename, file_bytes, "application/octet-stream")},
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_job(job_id: str) -> dict:
    r = requests.get(f"{API_BASE}/api/jobs/{job_id}", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_all_jobs() -> list:
    try:
        return requests.get(f"{API_BASE}/api/jobs", headers=_headers(), timeout=5).json().get("jobs", [])
    except Exception:
        return []


def approve_video(job_id: str, prompt_index: int) -> Optional[dict]:
    try:
        r = requests.post(f"{API_BASE}/api/jobs/{job_id}/approve/{prompt_index}", headers=_headers(), timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def rerun_prompt(job_id: str, prompt_index: int) -> bool:
    try:
        return requests.post(
            f"{API_BASE}/api/jobs/{job_id}/rerun/{prompt_index}",
            headers=_headers(), timeout=10
        ).status_code == 200
    except Exception:
        return False


def fetch_metrics() -> dict:
    try:
        r = requests.get(f"{API_BASE}/api/metrics", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def fetch_youtube_queue() -> list:
    try:
        return requests.get(f"{API_BASE}/api/youtube/queue", timeout=5).json().get("queue", [])
    except Exception:
        return []


def update_queue_item(qid: str, title: str, desc: str, tags: list) -> bool:
    try:
        return requests.patch(
            f"{API_BASE}/api/youtube/queue/{qid}",
            json={"title": title, "description": desc, "tags": tags}, timeout=10
        ).status_code == 200
    except Exception:
        return False


def trigger_youtube_upload() -> dict:
    try:
        r = requests.post(f"{API_BASE}/api/youtube/upload", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def remove_from_queue(qid: str) -> bool:
    try:
        return requests.delete(f"{API_BASE}/api/youtube/queue/{qid}", timeout=5).status_code == 200
    except Exception:
        return False


def fetch_youtube_status() -> dict:
    try:
        return requests.get(f"{API_BASE}/api/youtube/status", timeout=5).json()
    except Exception:
        return {"configured": False, "authenticated": False}


# ══════════════════════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════════════════════

def _safe_int(v, default=0, lo=None, hi=None) -> int:
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        r = int(x)
    except (TypeError, ValueError):
        return default
    if lo is not None: r = max(lo, r)
    if hi is not None: r = min(hi, r)
    return r


def _clips(dur: int) -> int:
    return -(-dur // CLIP_DURATION)


def _ar_css(ar: str) -> str:
    return {"9:16": "9/16", "16:9": "16/9", "1:1": "1/1", "4:3": "4/3"}.get(str(ar).strip(), "9/16")


def _pill(status: str) -> str:
    css = {"completed": "pill-done", "partial": "pill-partial",
           "processing": "pill-run", "pending": "pill-run", "failed": "pill-fail"}
    label = {"completed": "done", "partial": "partial", "processing": "generating",
             "pending": "pending", "failed": "failed"}
    c = css.get(status, "pill-run")
    l = label.get(status, status)
    return f'<span class="vs-pill {c}">{l}</span>'


def _make_sample_xlsx() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "prompts"
    ws.append(["prompt", "duration", "task_type", "priority"])
    ws.append([
        "NARRATOR: warm, Indian-accented female voice, calm and confident. "
        "GROUP ANCHOR: Three Indian school students aged 14-16, blue and white uniforms, silver laptops. "
        "SCENE ANCHOR: Futuristic classroom, blue/purple AI holograms, neon desks, large windows. "
        "Curious students entering a modern futuristic classroom, glowing AI holograms around them. "
        "Indian Accent Narration: \"The future belongs to creators, not just users.\" "
        "Students at glowing desks, building chatbots and AI artwork on laptops, collaborative environment. "
        "Indian Accent Narration: \"Learn Artificial Intelligence and build real projects.\" "
        "Fast montage: AI artwork forming on screen, chatbot interface on phone, website being designed. "
        "Indian Accent Narration: \"Create websites, games, avatars, and intelligent chatbots.\" "
        "Confident student presenting AI project, classmates applauding, scene holds still. "
        "Indian Accent Narration: \"Start your AI journey today.\"",
        32, "AUTO", 1,
    ])
    ws.append([
        "NARRATOR: calm, professional male voice. "
        "Corporate professionals in a boardroom exploring AI tools on laptops. "
        "Indian Accent Narration: \"AI is the skill of this decade.\" "
        "Close-up on screens showing AI dashboards and analytics, confident expressions. "
        "Indian Accent Narration: \"Build the future with your team.\"",
        16, "AUTO", 2,
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# UI Components
# ══════════════════════════════════════════════════════════════════════════════

def render_navbar():
    user = get_current_user() or {}
    name = user.get("name", "")
    role = user.get("role", "viewer")

    st.markdown(f"""
<div class="vs-nav">
  <div class="vs-nav-logo">Veo <span>Studio</span></div>
  <div class="vs-nav-right">
    <span class="vs-role">{role}</span>
    <span class="vs-nav-user">{_html.escape(name)}</span>
  </div>
</div>
""", unsafe_allow_html=True)

    _, col_out = st.columns([12, 1])
    with col_out:
        if st.button("Sign out", key="logout_btn"):
            logout()


def render_preview_table(df: pd.DataFrame):
    rows = ""
    for _, row in df.head(20).iterrows():
        prompt   = str(row.get("prompt", ""))
        duration = _safe_int(row.get("duration", 8), 8, 1, 120)
        task     = str(row.get("task_type", "AUTO")).upper()
        priority = _safe_int(row.get("priority", 5), 5, 1, 10)

        short = (_html.escape(prompt[:110]) + "…") if len(prompt) > 110 else _html.escape(prompt)
        bc    = "vs-badge-blue" if task not in ("TEXT_VIDEO",) else ""
        rows += f"""<tr>
  <td><div class="vs-ellipsis">{short}</div></td>
  <td>{duration}s</td>
  <td>{_clips(duration)}</td>
  <td><span class="vs-badge {bc}">{task}</span></td>
  <td>{priority}</td>
</tr>"""

    st.markdown(f"""
<div class="vs-table-wrap">
  <div class="vs-table-cap">Preview — {min(len(df),20)} of {len(df)} rows</div>
  <table class="vs-tbl">
    <thead><tr><th>Prompt</th><th>Duration</th><th>Clips</th><th>Type</th><th>Priority</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>""", unsafe_allow_html=True)


def render_skeleton():
    st.markdown("""
<div class="vs-card">
  <div class="vs-sk-video"></div>
  <div class="vs-card-body">
    <div class="vs-sk vs-sk-line w60"></div>
    <div class="vs-sk vs-sk-line w40" style="margin-top:.3rem"></div>
    <div class="vs-sk vs-sk-btn" style="margin:.6rem 0 0"></div>
  </div>
</div>""", unsafe_allow_html=True)


def render_video_card(p: dict, job_id: str, idx: int):
    status   = p.get("status", "processing")
    local_u  = p.get("local_video_url")
    dur      = p.get("duration_seconds", 8)
    clips    = p.get("clips_count", 1)
    ar       = p.get("aspect_ratio", "9:16")
    text     = p.get("prompt_text", "")
    short_p  = (_html.escape(text[:75]) + "…") if len(text) > 75 else _html.escape(text)

    # Build player URL — always serve from local FastAPI
    player_url = None
    if local_u:
        if local_u.startswith("http"):
            # Extract filename from any URL and serve locally
            fname = local_u.rstrip("/").split("/")[-1]
            player_url = f"{API_BASE}/videos/{fname}"
        else:
            player_url = f"{API_BASE}{local_u}"

    ar_css = _ar_css(ar)
    video_html = (
        f'<video controls preload="metadata" '
        f'style="width:100%;height:100%;object-fit:cover;display:block;">'
        f'<source src="{_html.escape(player_url)}" type="video/mp4"></video>'
        if player_url else
        '<div style="width:100%;height:100%;background:#111;display:flex;align-items:center;'
        'justify-content:center;color:#555;font-size:.78rem;">No local URL</div>'
    )

    st.markdown(f"""
<div class="vs-card">
  <div style="aspect-ratio:{ar_css};background:#000;overflow:hidden;border-radius:14px 14px 0 0">
    {video_html}
  </div>
  <div class="vs-card-body">
    <div class="vs-card-prompt">{short_p}</div>
    <div class="vs-card-meta">
      {_pill(status)}
      <span class="vs-badge">{ar}</span>
      <span class="vs-badge">{clips} clip{'s' if clips != 1 else ''} · {dur}s</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    # Action row: Approve · Rerun · Reject
    c1, c2, c3 = st.columns(3, gap="small")
    with c1:
        if has_permission("approve"):
            if st.button("✓  Approve", key=f"appr_{job_id}_{idx}", use_container_width=True):
                ok = approve_video(job_id, idx)
                st.toast("Added to YouTube queue" if ok else "Approve failed")
    with c2:
        if has_permission("rerun"):
            if st.button("↺  Rerun", key=f"rerun_{job_id}_{idx}", use_container_width=True):
                ok = rerun_prompt(job_id, idx)
                if ok:
                    st.toast("Rerunning…")
                    st.rerun()
                else:
                    st.toast("Rerun failed")
    with c3:
        if has_permission("reject"):
            if st.button("✕  Reject", key=f"rej_{job_id}_{idx}", use_container_width=True):
                st.session_state.rejected.add((job_id, idx))
                st.rerun()


def render_video_grid(job: dict):
    prompts = job.get("prompts", [])
    if not prompts:
        return

    job_id = job.get("job_id", "")
    n      = len(prompts)

    st.markdown('<div class="vs-h" style="margin-top:2rem">Generated Videos</div>',
                unsafe_allow_html=True)

    cols = st.columns(min(n, 3), gap="medium")
    for i, p in enumerate(prompts):
        if (job_id, i) in st.session_state.rejected:
            continue
        with cols[i % min(n, 3)]:
            status = p.get("status", "processing")
            if status in ("completed", "partial"):
                render_video_card(p, job_id, i)
            else:
                render_skeleton()


# ══════════════════════════════════════════════════════════════════════════════
# Jobs & Metrics (collapsed expanders inside Tab 3)
# ══════════════════════════════════════════════════════════════════════════════

def render_jobs_expander():
    server_jobs = {j["job_id"]: j for j in fetch_all_jobs()}
    all_jobs    = {**server_jobs, **st.session_state.jobs}

    if not all_jobs:
        st.caption("No jobs yet.")
        return

    for job_id, job in sorted(all_jobs.items(), reverse=True):
        status   = job.get("status", "unknown")
        prompts  = job.get("prompts", [])
        n_ok     = sum(1 for p in prompts if p.get("status") in ("completed", "partial"))
        elapsed  = job.get("elapsed_seconds")
        t_str    = f"{int(elapsed)}s" if elapsed else "—"

        rows = ""
        for p in prompts:
            ptxt = (p.get("prompt_text") or "")[:85]
            pst  = p.get("status", "?")
            lu   = p.get("local_video_url")
            link = (f'<a href="{API_BASE}{lu}" target="_blank" '
                    f'style="color:var(--accent);text-decoration:none">↗ Open</a>'
                    if lu and not lu.startswith("http") else
                    (f'<a href="{lu}" target="_blank" style="color:var(--accent);text-decoration:none">↗ S3</a>'
                     if lu else "—"))
            rows += f"<tr><td><div class='vs-ellipsis'>{_html.escape(ptxt)}{'…' if len(p.get('prompt_text',''))>85 else ''}</div></td><td>{_pill(pst)}</td><td>{link}</td></tr>"

        with st.expander(
            f"{job_id}  ·  {n_ok}/{len(prompts)} prompts  ·  {t_str}",
            expanded=False
        ):
            st.markdown(f"""
<table class="vs-tbl" style="font-size:.8rem">
  <thead><tr><th>Prompt</th><th>Status</th><th>Video</th></tr></thead>
  <tbody>{rows}</tbody>
</table>""", unsafe_allow_html=True)


def render_metrics_expander():
    m = fetch_metrics()
    if not m:
        st.caption("Cannot reach API.")
        return

    v   = m.get("veo", {})
    d   = m.get("decomposer", {})
    s   = m.get("s3", {})
    est = m.get("cost_estimate", {})

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Jobs",          m.get("jobs_processed", 0))
    c2.metric("Clips",         v.get("clips_generated", 0))
    c3.metric("Avg clip",      f"{v.get('avg_clip_time_s', 0)}s")
    c4.metric("429 hits",      v.get("rate_limit_hits", 0))
    c5.metric("S3 uploads",    s.get("uploads_ok", 0))
    c6.metric("Cost",          f"₹{est.get('inr', 0):.2f}")

    st.markdown("<br>", unsafe_allow_html=True)

    st.caption("Decomposer")
    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    cc1.metric("Nova 2 Lite",  d.get("nova_calls", 0))
    cc2.metric("DeepSeek R1",  d.get("deepseek_calls", 0))
    cc3.metric("Deterministic",d.get("deterministic", 0))
    cc4.metric("Input tokens", f"{d.get('input_tokens', 0):,}")
    cc5.metric("Output tokens",f"{d.get('output_tokens', 0):,}")

    rl = v.get("rate_limit_pct", 0)
    if v.get("submissions", 0) == 0:
        st.info("No submissions this session.")
    elif rl == 0:
        st.success("✅  No rate limit hits this session.")
    elif rl < 20:
        st.warning(f"⚠️  {rl}% submissions hit rate limits.")
    else:
        st.error(f"🔴  {rl}% rate limit hit rate — consider pacing submissions.")


# ══════════════════════════════════════════════════════════════════════════════
# YouTube tab
# ══════════════════════════════════════════════════════════════════════════════

def render_youtube_tab():
    yt  = fetch_youtube_status()
    if not yt.get("configured"):
        st.markdown('<div class="vs-alert al-warn">⚠️  YouTube not configured — add credentials to <code>veo.env</code>.</div>',
                    unsafe_allow_html=True)
        return

    if not yt.get("authenticated"):
        st.markdown('<div class="vs-alert al-info">ℹ️  Run the OAuth flow once to authenticate YouTube.</div>',
                    unsafe_allow_html=True)

    queue = fetch_youtube_queue()
    if not queue:
        st.markdown('<div style="color:var(--text2);font-size:.88rem">Queue is empty. Approve a video card to add it here.</div>',
                    unsafe_allow_html=True)
        return

    for item in queue:
        qid    = item.get("id", "")
        title  = item.get("title", "")
        desc   = item.get("description", "")
        tags   = item.get("tags", [])
        status = item.get("status", "approved")
        vurl   = item.get("local_path") or item.get("s3_url", "")

        with st.expander(f"{title or '(untitled)'}  ·  {_pill(status)}", expanded=False):
            if vurl:
                player = vurl if vurl.startswith("http") else f"{API_BASE}{vurl}"
                st.video(player)

            ca, cb = st.columns(2)
            with ca:
                new_title = st.text_input("Title", value=title, key=f"yt_t_{qid}")
                new_tags  = st.text_input("Tags (comma-separated)",
                                          value=", ".join(tags), key=f"yt_tg_{qid}")
            with cb:
                new_desc = st.text_area("Description", value=desc, height=100, key=f"yt_d_{qid}")

            cs, cd = st.columns([3, 1])
            with cs:
                if st.button("Save", key=f"yt_sv_{qid}"):
                    ok = update_queue_item(qid, new_title, new_desc,
                                          [t.strip() for t in new_tags.split(",") if t.strip()])
                    st.toast("Saved" if ok else "Save failed")
            with cd:
                if st.button("Remove", key=f"yt_rm_{qid}"):
                    remove_from_queue(qid)
                    st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)

    if has_permission("approve") and yt.get("authenticated"):
        if st.button("⬆  Upload all to YouTube", type="primary"):
            r = trigger_youtube_upload()
            if r.get("status") == "ok":
                st.success(f"Uploaded {r.get('uploaded', 0)} video(s).")
            else:
                st.error(r.get("message", "Upload failed"))


# ══════════════════════════════════════════════════════════════════════════════
# Layout
# ══════════════════════════════════════════════════════════════════════════════

render_navbar()

tab_gen, tab_yt, tab_data = st.tabs(["Generate", "YouTube Queue", "Jobs & Metrics"])

# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Generate
# ─────────────────────────────────────────────────────────────────────────────
with tab_gen:

    if not check_api():
        st.markdown('<div class="vs-alert al-error">✕  API offline — start <code>python veo_main.py</code> first.</div>',
                    unsafe_allow_html=True)

    st.markdown('<div class="vs-h">Upload prompts</div>', unsafe_allow_html=True)
    st.markdown('<div class="vs-sub">Excel file with prompt, duration, task_type and priority columns.</div>',
                unsafe_allow_html=True)

    col_up, col_dl = st.columns([4, 1], gap="medium")
    with col_up:
        uploaded = st.file_uploader(
            "Drop Excel file or click to browse",
            type=["xlsx", "xls"],
            label_visibility="collapsed",
        )
    with col_dl:
        st.markdown("<div style='height:.3rem'></div>", unsafe_allow_html=True)
        st.download_button(
            "↓  Sample",
            data=_make_sample_xlsx(),
            file_name="veo_sample.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    # Parse uploaded file
    if uploaded is not None:
        try:
            df = pd.read_excel(uploaded, engine="openpyxl")
            # Alias normalisation
            aliases = {"duration_s":"duration","duration_sec":"duration",
                       "tasktype":"task_type","type":"task_type","prio":"priority","rank":"priority"}
            df.rename(columns={c: aliases[c.lower()] for c in df.columns if c.lower() in aliases},
                      inplace=True)
            df.columns = [c.lower().strip() for c in df.columns]
            df = df.dropna(subset=["prompt"])
            if "duration" in df.columns:
                df = df[df["duration"].notna()]
            df = df.reset_index(drop=True)
            st.session_state.df_preview = df
            st.session_state.file_bytes = uploaded.getvalue()
            st.session_state.file_name  = uploaded.name
        except Exception as e:
            st.error(f"Could not parse file: {e}")
            st.session_state.df_preview = None

    # Preview table
    if st.session_state.df_preview is not None:
        df = st.session_state.df_preview
        render_preview_table(df)

        st.markdown("<div style='height:1.25rem'></div>", unsafe_allow_html=True)

        if has_permission("generate"):
            n_p   = len(df)
            n_c   = sum(_clips(_safe_int(d, 8, 1, 120)) for d in df.get("duration", pd.Series()))
            busy  = st.session_state.is_generating

            col_btn, col_info = st.columns([2, 4], gap="medium")
            with col_btn:
                if st.button(
                    "Generating…" if busy else f"▶  Generate  ·  {n_p} prompt{'s' if n_p!=1 else ''}",
                    type="primary", disabled=busy, use_container_width=True, key="gen_btn"
                ):
                    st.session_state.is_generating = True
                    try:
                        result = upload_file(st.session_state.file_bytes, st.session_state.file_name)
                        jid = result.get("job_id")
                        if jid:
                            st.session_state.jobs[jid] = result
                            st.session_state.active_job = jid
                            st.session_state.rejected   = set()
                            st.rerun()
                        else:
                            st.error(f"Upload failed: {result}")
                            st.session_state.is_generating = False
                    except Exception as e:
                        st.error(f"Upload error: {e}")
                        st.session_state.is_generating = False

            with col_info:
                t_dur = df["duration"].apply(lambda x: _safe_int(x, 8, 1, 120)).sum() if "duration" in df.columns else 0
                st.markdown(
                    f'<div style="color:var(--text2);font-size:.82rem;padding-top:.65rem">'
                    f'{n_p} prompts · {t_dur}s total · {n_c} clips</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="vs-alert al-warn">⚠️  Your role cannot generate videos.</div>',
                        unsafe_allow_html=True)

    # ── Live video grid ────────────────────────────────────────────────────────
    active = st.session_state.active_job
    display = active or st.session_state.get("last_completed_job")

    if display:
        try:
            live = fetch_job(display)
            st.session_state.jobs[display] = live
            render_video_grid(live)

            jst = live.get("status")
            if jst in ("processing", "pending"):
                st.session_state.active_job = display
                time.sleep(POLL_INTERVAL)
                st.rerun()
            else:
                st.session_state.last_completed_job = display
                st.session_state.active_job         = None
                st.session_state.is_generating      = False
        except Exception as e:
            st.warning(f"Could not fetch job: {e}")
            st.session_state.active_job    = None
            st.session_state.is_generating = False

# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — YouTube Queue
# ─────────────────────────────────────────────────────────────────────────────
with tab_yt:
    st.markdown('<div class="vs-h">YouTube Queue</div>', unsafe_allow_html=True)
    render_youtube_tab()

# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 — Jobs & Metrics (collapsed)
# ─────────────────────────────────────────────────────────────────────────────
with tab_data:
    if has_permission("view_jobs"):
        with st.expander("📋  Jobs", expanded=False):
            render_jobs_expander()

    if has_permission("view_metrics"):
        with st.expander("📊  Metrics", expanded=False):
            render_metrics_expander()