"""
veo_app.py — Streamlit Frontend for the Veo Video Generation Platform
═══════════════════════════════════════════════════════════════════════

Run:
  streamlit run veo_app.py

Requires veo_main.py running on http://localhost:8100
  python veo_main.py

Install:
  pip install streamlit pandas openpyxl requests
"""

import io
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE      = "http://localhost:8100"
POLL_INTERVAL = 4   # seconds between status refreshes
CLIP_DURATION = 8   # Veo hard limit per clip

TEMPLATE_PATH = Path(__file__).parent / "veo_template.xlsx"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title = "Veo Studio",
    page_icon  = "🎬",
    layout     = "wide",
)

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Syne:wght@400;600;700;800&display=swap');

:root {
    --bg:        #080c14;
    --surface:   #0d1525;
    --border:    #1a2840;
    --accent:    #00d4ff;
    --accent2:   #7c3aed;
    --text:      #e2e8f0;
    --muted:     #64748b;
    --success:   #10b981;
    --warn:      #f59e0b;
    --error:     #ef4444;
}

html, body, [data-testid="stApp"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Syne', sans-serif;
}

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stToolbar"] { display: none; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] * { color: var(--text) !important; }

/* Main container */
.block-container { padding: 2rem 2.5rem; max-width: 1300px; }

/* Title block */
.veo-title {
    font-size: 3rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: var(--text);
    line-height: 1;
    margin-bottom: 0.25rem;
}
.veo-title span { color: var(--accent); }
.veo-sub {
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    color: var(--muted);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 2rem;
}

/* Drop zone */
.drop-label {
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 0.5rem;
    display: block;
}
[data-testid="stFileUploader"] {
    background: var(--surface) !important;
    border: 2px dashed var(--border) !important;
    border-radius: 12px !important;
    transition: border-color 0.2s;
}
[data-testid="stFileUploader"]:hover {
    border-color: var(--accent) !important;
}
[data-testid="stFileUploadDropzone"] {
    background: transparent !important;
    padding: 2rem !important;
}

/* Stat cards */
.stat-row { display: flex; gap: 1rem; margin: 1.5rem 0; flex-wrap: wrap; }
.stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.5rem;
    flex: 1;
    min-width: 120px;
}
.stat-value {
    font-size: 1.8rem;
    font-weight: 800;
    color: var(--accent);
    line-height: 1;
}
.stat-label {
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    margin-top: 0.3rem;
}

/* Table */
.veo-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
    margin-top: 1rem;
}
.veo-table th {
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--accent);
    padding: 0.6rem 1rem;
    border-bottom: 1px solid var(--border);
    text-align: left;
    background: var(--surface);
}
.veo-table td {
    padding: 0.7rem 1rem;
    border-bottom: 1px solid var(--border);
    color: var(--text);
    vertical-align: top;
    max-width: 420px;
    word-wrap: break-word;
}
.veo-table tr:hover td { background: rgba(0, 212, 255, 0.04); }
.badge {
    display: inline-block;
    font-family: 'Space Mono', monospace;
    font-size: 0.62rem;
    padding: 0.2rem 0.55rem;
    border-radius: 4px;
    letter-spacing: 0.05em;
}
.badge-auto  { background: #1e3a5f; color: #7dd3fc; }
.badge-tv    { background: #1e2a1e; color: #86efac; }
.badge-ms    { background: #2d1b4e; color: #c4b5fd; }
.badge-dur   { background: #1a2840; color: var(--accent); font-weight: 700; }
.clip-note   { font-size: 0.7rem; color: var(--muted); margin-top: 0.2rem; }

/* Submit button */
.stButton > button {
    background: var(--accent) !important;
    color: var(--bg) !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    padding: 0.7rem 2rem !important;
    border-radius: 8px !important;
    border: none !important;
    transition: opacity 0.2s !important;
    width: 100%;
}
.stButton > button:hover { opacity: 0.85 !important; }
.stButton > button:disabled { opacity: 0.4 !important; }

/* Progress */
.stProgress > div > div { background: var(--accent) !important; }

/* Job cards */
.job-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1rem;
}
.job-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
}
.job-id {
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    color: var(--muted);
}
.status-pill {
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    padding: 0.25rem 0.7rem;
    border-radius: 20px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 700;
}
.status-processing { background: rgba(245,158,11,0.15); color: var(--warn); border: 1px solid var(--warn); }
.status-completed  { background: rgba(16,185,129,0.15); color: var(--success); border: 1px solid var(--success); }
.status-partial    { background: rgba(124,58,237,0.15); color: #a78bfa; border: 1px solid #7c3aed; }
.status-failed     { background: rgba(239,68,68,0.15); color: var(--error); border: 1px solid var(--error); }
.status-pending    { background: rgba(100,116,139,0.15); color: var(--muted); border: 1px solid var(--muted); }

/* Result rows */
.result-row {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
}
.result-row:last-child { border-bottom: none; }
.result-prompt {
    flex: 1;
    color: var(--muted);
    font-size: 0.8rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 300px;
}
.result-ok   { color: var(--success); font-family: 'Space Mono', monospace; font-size: 0.7rem; }
.result-fail { color: var(--error);   font-family: 'Space Mono', monospace; font-size: 0.7rem; }
.result-proc { color: var(--warn);    font-family: 'Space Mono', monospace; font-size: 0.7rem; }

/* Download button */
.dl-btn {
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    background: transparent;
    border: 1px solid var(--accent);
    color: var(--accent);
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    text-decoration: none;
    transition: background 0.15s;
}
.dl-btn:hover { background: rgba(0,212,255,0.1); }

/* Divider */
.veo-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 2rem 0;
}

/* Alerts */
.veo-alert {
    border-radius: 8px;
    padding: 0.9rem 1.2rem;
    font-size: 0.88rem;
    margin: 1rem 0;
}
.veo-alert-success { background: rgba(16,185,129,0.1); border-left: 3px solid var(--success); color: #6ee7b7; }
.veo-alert-error   { background: rgba(239,68,68,0.1);  border-left: 3px solid var(--error);   color: #fca5a5; }
.veo-alert-info    { background: rgba(0,212,255,0.08); border-left: 3px solid var(--accent);  color: #7dd3fc; }

/* Inputs */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] select {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 6px !important;
}

/* ── Video grid ──────────────────────────────────────────────────────────── */
.vid-grid-header {
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--accent);
    margin: 2rem 0 1rem;
}
.vid-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.vid-card:hover { border-color: rgba(0,212,255,0.4); }

/* Aspect-ratio container — height is determined by the CSS aspect-ratio    */
/* property set inline per card. Width fills the column.                    */
.vid-ar-box {
    width: 100%;
    position: relative;
    background: var(--border);
    overflow: hidden;
}
.vid-ar-box video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    cursor: pointer;
}

/* Shimmer skeleton for loading state */
.vid-skeleton {
    position: absolute;
    inset: 0;
    background: linear-gradient(
        90deg,
        var(--surface) 0%,
        #1a2840 40%,
        #1f3356 50%,
        #1a2840 60%,
        var(--surface) 100%
    );
    background-size: 250% 100%;
    animation: shimmer 1.8s ease-in-out infinite;
}
@keyframes shimmer {
    0%   { background-position:  200% 0; }
    100% { background-position: -200% 0; }
}
.vid-skeleton-icon {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 2rem;
    opacity: 0.2;
}

/* Card footer */
.vid-footer {
    padding: 0.6rem 0.75rem 0.4rem;
}
.vid-prompt-text {
    font-size: 0.75rem;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-bottom: 0.35rem;
}
.vid-meta {
    font-family: 'Space Mono', monospace;
    font-size: 0.62rem;
    color: var(--muted);
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: wrap;
}
.vid-status-ok   { color: var(--success); }
.vid-status-fail { color: var(--error); }
.vid-status-proc { color: var(--warn); }
.vid-ar-tag {
    background: #1a2840;
    color: var(--accent);
    padding: 0.1rem 0.35rem;
    border-radius: 3px;
    font-size: 0.58rem;
}

/* Rerun button — sits below each video card via st.button */
[data-testid="stButton"] button[kind="secondary"] {
    background: transparent !important;
    border: 1px solid var(--border) !important;
    color: var(--muted) !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 0.65rem !important;
    padding: 0.25rem 0.6rem !important;
    width: 100% !important;
    transition: border-color 0.15s, color 0.15s !important;
}
[data-testid="stButton"] button[kind="secondary"]:hover {
    border-color: var(--warn) !important;
    color: var(--warn) !important;
}

/* ── YouTube queue ───────────────────────────────────────────────────────── */
.yt-queue-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
}
.yt-queue-card.uploaded {
    border-color: var(--success);
}
.yt-queue-card.failed {
    border-color: var(--error);
}
.yt-queue-card.uploading {
    border-color: var(--warn);
}
.yt-video-thumb {
    width: 100%;
    aspect-ratio: 16/9;
    object-fit: cover;
    border-radius: 6px;
    background: var(--border);
}
.yt-link {
    color: #ff0000;
    font-family: Space Mono, monospace;
    font-size: 0.75rem;
    text-decoration: none;
    font-weight: 700;
}
.yt-link:hover { text-decoration: underline; }
.approve-badge {
    display: inline-block;
    background: rgba(16,185,129,0.15);
    color: var(--success);
    border: 1px solid var(--success);
    border-radius: 20px;
    font-family: Space Mono, monospace;
    font-size: 0.62rem;
    padding: 0.2rem 0.6rem;
    letter-spacing: 0.06em;
}
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────
for key, default in [
    ("jobs",           {}),
    ("active_job",     None),
    ("upload_error",   None),
    ("api_ok",         None),
    ("rerun_pending",  set()),   # set of (job_id, prompt_index) currently rerunning
    ("is_generating",     False),   # True while a job is running — blocks duplicate submits
    ("last_completed_job", None),   # job_id of most recently completed job — keeps grid visible
    ("approved_set",   set()),   # set of (job_id, prompt_index) approved for YouTube
    ("yt_queue",       []),      # cached YouTube queue from last fetch

]:
    if key not in st.session_state:
        st.session_state[key] = default


# ── Helpers ───────────────────────────────────────────────────────────────────

def check_api() -> bool:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def upload_file(file_bytes: bytes, filename: str) -> dict:
    r = requests.post(
        f"{API_BASE}/api/upload",
        files={"file": (filename, file_bytes, "application/octet-stream")},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_job(job_id: str) -> dict:
    r = requests.get(f"{API_BASE}/api/jobs/{job_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_all_jobs() -> list:
    try:
        r = requests.get(f"{API_BASE}/api/jobs", timeout=5)
        r.raise_for_status()
        return r.json().get("jobs", [])
    except Exception:
        return []


def approve_video(job_id: str, prompt_index: int) -> Optional[dict]:
    """POST /api/jobs/{job_id}/approve/{prompt_index} — add to YouTube queue."""
    try:
        r = requests.post(
            f"{API_BASE}/api/jobs/{job_id}/approve/{prompt_index}",
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def fetch_youtube_queue() -> list:
    try:
        r = requests.get(f"{API_BASE}/api/youtube/queue", timeout=5)
        r.raise_for_status()
        return r.json().get("queue", [])
    except Exception:
        return []


def update_queue_item(queue_id: str, title: str, description: str, tags: list) -> bool:
    try:
        r = requests.patch(
            f"{API_BASE}/api/youtube/queue/{queue_id}",
            json={"title": title, "description": description, "tags": tags},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def trigger_youtube_upload() -> dict:
    try:
        r = requests.post(f"{API_BASE}/api/youtube/upload", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def remove_from_queue(queue_id: str) -> bool:
    try:
        r = requests.delete(f"{API_BASE}/api/youtube/queue/{queue_id}", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def fetch_youtube_status() -> dict:
    try:
        r = requests.get(f"{API_BASE}/api/youtube/status", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"configured": False, "authenticated": False}


def rerun_prompt(job_id: str, prompt_index: int) -> bool:
    """POST /api/jobs/{job_id}/rerun/{prompt_index}. Returns True on success."""
    try:
        r = requests.post(
            f"{API_BASE}/api/jobs/{job_id}/rerun/{prompt_index}",
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def _ar_to_css(ar: str) -> str:
    """
    Convert aspect ratio string to CSS aspect-ratio value.
    '9:16' → '9/16', '16:9' → '16/9', etc.
    Falls back to '1/1' for unknown values.
    """
    mapping = {
        "9:16": "9/16",
        "16:9": "16/9",
        "1:1":  "1/1",
        "4:3":  "4/3",
        "3:4":  "3/4",
    }
    return mapping.get(str(ar).strip(), "9/16")


def _safe_int(value, default: int = 0, lo: int = None, hi: int = None) -> int:
    """
    Convert any DataFrame cell value to int safely.
    Handles NaN, None, inf, non-numeric strings.
    Clamps to [lo, hi] when provided.
    """
    import math
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        result = int(v)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result


def clip_count(duration: int) -> int:
    return -(-duration // CLIP_DURATION)   # ceil div


def status_pill(status: str) -> str:
    css = {
        "processing": "status-processing",
        "completed":  "status-completed",
        "partial":    "status-partial",
        "failed":     "status-failed",
        "pending":    "status-pending",
    }.get(status, "status-pending")
    return f'<span class="status-pill {css}">{status}</span>'


def badge_task(task_type: str) -> str:
    css = {"TEXT_VIDEO": "badge-tv", "MULTI_SHOT_AUTOMATED": "badge-ms"}.get(task_type, "badge-auto")
    label = {"TEXT_VIDEO": "TEXT", "MULTI_SHOT_AUTOMATED": "MULTI"}.get(task_type, "AUTO")
    return f'<span class="badge {css}">{label}</span>'


def render_preview_table(df: pd.DataFrame):
    rows_html = ""
    for _, row in df.iterrows():
        dur   = _safe_int(row.get("duration", 8), default=8, lo=1, hi=120)
        clips = clip_count(dur)
        tt    = str(row.get("task_type", "AUTO")).upper()
        prio  = _safe_int(row.get("priority", 5), default=5, lo=1, hi=10)
        import html as _html
        prompt = str(row.get("prompt", ""))
        prompt_display = _html.escape(prompt[:90] + "…" if len(prompt) > 90 else prompt)

        clip_note = f'<div class="clip-note">→ {clips} clip{"s" if clips > 1 else ""}</div>' if clips > 1 else ""

        rows_html += f"""
        <tr>
            <td style="color:var(--muted);font-family:Space Mono,monospace;font-size:0.7rem">{int(_) + 1}</td>
            <td>{prompt_display}</td>
            <td>
                <span class="badge badge-dur">{dur}s</span>
                {clip_note}
            </td>
            <td>{badge_task(tt)}</td>
            <td style="font-family:Space Mono,monospace;font-size:0.75rem;color:var(--muted)">{prio}</td>
        </tr>"""

    st.markdown(f"""
    <table class="veo-table">
        <thead><tr>
            <th>#</th><th>Prompt</th><th>Duration</th><th>Task</th><th>Priority</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
    </table>""", unsafe_allow_html=True)


def render_video_grid(job: dict) -> None:
    """
    Render a card grid of all prompts in a job.

    - One card per prompt, laid out in 3 columns.
    - Each card shows a shimmer skeleton while the video is processing.
    - Once completed, shows an HTML5 <video> element (click-to-play).
    - Card height is driven by CSS aspect-ratio matching the prompt's aspect_ratio field.
    - A '↻ Rerun' button below each completed or failed card lets the user re-generate.

    Why HTML5 video not st.video:
        st.video can't be embedded inside column layouts with custom CSS wrappers.
        The API serves videos on /videos/... — direct URL works in <video src>.
    """
    import html as _html

    prompts   = job.get("prompts", [])
    results   = job.get("results", {}) if isinstance(job.get("results"), dict) else {}
    job_id    = job.get("job_id", "")
    job_status = job.get("status", "processing")

    if not prompts:
        return

    st.markdown('<div class="vid-grid-header">🎬 Generated Videos</div>',
                unsafe_allow_html=True)

    # 3-column grid — all prompts rendered, skeletons for pending
    cols = st.columns(3)

    for i, prompt_data in enumerate(prompts):
        col = cols[i % 3]
        result = results.get(str(i), {})
        status = result.get("status", "processing")
        video_url = result.get("video_url")
        prompt_text = prompt_data.get("prompt_text") or prompt_data.get("text", "")
        ar_raw  = prompt_data.get("aspect_ratio", "9:16")
        ar_css  = _ar_to_css(ar_raw)
        clips   = result.get("clips_count", 0)
        dur     = result.get("duration_seconds", 0)
        err     = result.get("error_message", "")
        is_rerunning = (job_id, i) in st.session_state.rerun_pending

        with col:
            # ── Card header (aspect-ratio box) ────────────────────────────────
            if status in ("completed", "partial") and video_url:
                # video_url is either a local FastAPI route (/videos/...)
                # or a full S3 HTTPS URL — handle both
                if video_url.startswith("http"):
                    full_url = video_url          # S3 or external URL — use as-is
                else:
                    full_url = f"{API_BASE}{video_url}"  # local FastAPI route
                safe_url  = _html.escape(full_url)
                st.markdown(f"""
<div class="vid-card">
  <div class="vid-ar-box" style="aspect-ratio:{ar_css}">
    <video controls preload="metadata">
      <source src="{safe_url}" type="video/mp4">
    </video>
  </div>
  <div class="vid-footer">
    <div class="vid-prompt-text" title="{_html.escape(prompt_text[:200])}">{_html.escape(prompt_text[:60])}{'…' if len(prompt_text) > 60 else ''}</div>
    <div class="vid-meta">
      <span class="vid-status-ok">✓ done</span>
      <span class="vid-ar-tag">{ar_raw}</span>
      {f'<span>{clips} clips · {dur}s</span>' if clips > 1 else ''}
    </div>
  </div>
</div>""", unsafe_allow_html=True)

            elif status == "failed":
                st.markdown(f"""
<div class="vid-card">
  <div class="vid-ar-box" style="aspect-ratio:{ar_css}">
    <div class="vid-skeleton"></div>
    <div class="vid-skeleton-icon">✗</div>
  </div>
  <div class="vid-footer">
    <div class="vid-prompt-text">{_html.escape(prompt_text[:60])}{'…' if len(prompt_text) > 60 else ''}</div>
    <div class="vid-meta">
      <span class="vid-status-fail">✗ failed</span>
      <span class="vid-ar-tag">{ar_raw}</span>
    </div>
    {f'<div style="font-size:0.65rem;color:var(--error);margin-top:0.3rem;padding:0 0.75rem 0.5rem">{_html.escape(err[:80])}</div>' if err else ''}
  </div>
</div>""", unsafe_allow_html=True)

            else:
                # Processing / pending — shimmer skeleton
                label = "↻ rerunning…" if is_rerunning else "⋯ generating"
                st.markdown(f"""
<div class="vid-card">
  <div class="vid-ar-box" style="aspect-ratio:{ar_css}">
    <div class="vid-skeleton"></div>
    <div class="vid-skeleton-icon">🎬</div>
  </div>
  <div class="vid-footer">
    <div class="vid-prompt-text">{_html.escape(prompt_text[:60])}{'…' if len(prompt_text) > 60 else ''}</div>
    <div class="vid-meta">
      <span class="vid-status-proc">{label}</span>
      <span class="vid-ar-tag">{ar_raw}</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

            # ── Action buttons (below card) ───────────────────────────────────
            is_approved = (job_id, i) in st.session_state.approved_set

            if status in ("completed", "partial") and not is_rerunning:
                btn_col1, btn_col2 = st.columns(2)

                with btn_col1:
                    if st.button("↻  Rerun", key=f"rerun_{job_id}_{i}", type="secondary"):
                        ok = rerun_prompt(job_id, i)
                        if ok:
                            st.session_state.rerun_pending.add((job_id, i))
                            # Remove from approved if it was queued
                            st.session_state.approved_set.discard((job_id, i))
                            st.rerun()
                        else:
                            st.error("Rerun failed — is the API running?")

                with btn_col2:
                    if is_approved:
                        st.markdown(
                            '<div style="text-align:center;font-family:Space Mono,monospace;'
                            'font-size:0.65rem;color:var(--success);padding:0.3rem 0">✓ Approved</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        if st.button("✓  Approve", key=f"approve_{job_id}_{i}"):
                            item = approve_video(job_id, i)
                            if item:
                                st.session_state.approved_set.add((job_id, i))
                                st.session_state.yt_queue = fetch_youtube_queue()
                                st.rerun()
                            else:
                                st.error("Approve failed — is the API running?")

            elif status == "failed" and not is_rerunning:
                if st.button("↻  Retry", key=f"rerun_{job_id}_{i}", type="secondary"):
                    ok = rerun_prompt(job_id, i)
                    if ok:
                        st.session_state.rerun_pending.add((job_id, i))
                        st.rerun()
                    else:
                        st.error("Retry failed — is the API running?")

            elif is_rerunning:
                if status in ("completed", "failed"):
                    st.session_state.rerun_pending.discard((job_id, i))


def render_job_card(job: dict, live: bool = False):
    job_id   = job.get("job_id", "")
    status   = job.get("status", "pending")
    total    = job.get("total_prompts", 0)
    done     = job.get("completed_prompts", 0)
    failed   = job.get("failed_prompts", 0)
    pct      = job.get("progress_percent", 0.0)
    gen_msg  = job.get("generation_status", "")
    filename = job.get("original_filename", "")
    proc_time = job.get("total_processing_time")

    st.markdown(f"""
    <div class="job-card">
        <div class="job-header">
            <div>
                <div style="font-weight:700;margin-bottom:0.2rem">{filename or job_id}</div>
                <div class="job-id">{job_id}</div>
            </div>
            {status_pill(status)}
        </div>
    </div>""", unsafe_allow_html=True)

    if status in ("processing", "pending") or pct < 100:
        st.progress(pct / 100)
        if gen_msg:
            st.caption(gen_msg)

    col1, col2, col3 = st.columns(3)
    col1.metric("Prompts", total)
    col2.metric("Completed", done)
    col3.metric("Failed", failed)

    if proc_time:
        st.caption(f"Total time: {proc_time}s")

    # Per-prompt results
    prompts = job.get("prompts", [])
    if prompts:
        with st.expander("Results", expanded=(status in ("completed", "partial"))):
            for p in prompts:
                pstatus = p.get("status", "processing")
                text    = p.get("prompt_text", "")[:60] + "…"
                vurl    = p.get("video_url")
                clips   = p.get("clips_count", 0)
                dur     = p.get("duration_seconds")
                err     = p.get("error_message", "")

                col_a, col_b = st.columns([3, 1])
                with col_a:
                    if pstatus == "completed":
                        st.markdown(f'<span style="color:var(--success)">✓</span> {text}', unsafe_allow_html=True)
                        if clips > 1:
                            st.caption(f"Stitched · {clips} clips · {dur}s")
                    elif pstatus == "failed":
                        st.markdown(f'<span style="color:var(--error)">✗</span> {text}', unsafe_allow_html=True)
                        if err:
                            st.caption(err)
                    else:
                        st.markdown(f'<span style="color:var(--warn)">⋯</span> {text}', unsafe_allow_html=True)

                with col_b:
                    if vurl and pstatus in ("completed", "partial"):
                        full_url = vurl if vurl.startswith("http") else f"{API_BASE}{vurl}"
                        st.markdown(
                            f'<a class="dl-btn" href="{full_url}" target="_blank">⬇ Download</a>',
                            unsafe_allow_html=True,
                        )


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙ Settings")

    api_url = st.text_input("API URL", value=API_BASE, key="api_url_input")
    if api_url != API_BASE:
        API_BASE = api_url

    if st.button("Check API"):
        st.session_state.api_ok = check_api()

    if st.session_state.api_ok is True:
        st.markdown('<div class="veo-alert veo-alert-success">API online</div>', unsafe_allow_html=True)
    elif st.session_state.api_ok is False:
        st.markdown('<div class="veo-alert veo-alert-error">API offline — run python veo_main.py</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📥 Template")
    if TEMPLATE_PATH.exists():
        with open(TEMPLATE_PATH, "rb") as f:
            st.download_button(
                label     = "Download veo_template.xlsx",
                data      = f.read(),
                file_name = "veo_template.xlsx",
                mime      = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        st.caption("veo_template.xlsx not found in project folder")

    st.markdown("---")
    st.markdown("### 📋 Column Reference")
    st.markdown("""
**Required**
- `prompt` — video prompt text
- `duration` — seconds (1–120)

**Optional**
- `task_type` — AUTO / TEXT_VIDEO / MULTI_SHOT_AUTOMATED
- `priority` — 1–10 (lower = first)

**Clip rule**
Veo generates 8s clips.
- 8s → 1 clip
- 16s → 2 clips (stitched)
- 24s → 3 clips (stitched)
""")


# ── Main layout ───────────────────────────────────────────────────────────────

st.markdown("""
<div class="veo-title">Veo <span>Studio</span></div>
<div class="veo-sub">Google Veo 3.1 · Batch video generation · Native audio</div>
""", unsafe_allow_html=True)

tab_upload, tab_jobs, tab_metrics, tab_youtube = st.tabs(["🎬 Upload & Generate", "📊 Jobs", "📊 Metrics", "▶ YouTube Queue"])


# ══════════════════════════════════════════════════════════════════════════════
# Tab 1 — Upload
# ══════════════════════════════════════════════════════════════════════════════

with tab_upload:

    st.markdown('<span class="drop-label">Drop your Excel file here</span>', unsafe_allow_html=True)

    uploaded = st.file_uploader(
        label      = "Upload Excel",
        type       = ["xlsx", "xls", "csv"],
        label_visibility = "collapsed",
    )

    if uploaded is not None:
        # ── Parse preview ──────────────────────────────────────────────────────
        try:
            if uploaded.name.lower().endswith(".csv"):
                df_raw = pd.read_csv(uploaded)
            else:
                df_raw = pd.read_excel(uploaded)

            uploaded.seek(0)  # reset for later upload

            # Normalise column names
            df_raw.columns = [str(c).strip().lower() for c in df_raw.columns]
            alias = {"text": "prompt", "video_prompt": "prompt",
                     "duration_s": "duration", "duration_sec": "duration",
                     "tasktype": "task_type", "type": "task_type",
                     "prio": "priority", "rank": "priority"}
            df_raw = df_raw.rename(columns={c: alias[c] for c in df_raw.columns if c in alias})

            has_prompt   = "prompt"   in df_raw.columns
            has_duration = "duration" in df_raw.columns

        except Exception as e:
            st.error(f"Could not read file: {e}")
            st.stop()

        # ── Validation banner ──────────────────────────────────────────────────
        errors = []
        if not has_prompt:
            errors.append("Missing required column: **prompt**")
        if not has_duration:
            errors.append("Missing required column: **duration**")

        if errors:
            for err in errors:
                st.markdown(f'<div class="veo-alert veo-alert-error">✗ {err}</div>', unsafe_allow_html=True)
            st.stop()

        # Drop empties + metadata rows (notes rows have prompt text but no duration)
        df_clean = df_raw.dropna(subset=["prompt"])
        df_clean = df_clean[df_clean["prompt"].astype(str).str.strip() != ""]
        if "duration" in df_clean.columns:
            df_clean = df_clean[df_clean["duration"].apply(
                lambda v: not (v is None or (isinstance(v, float) and __import__("math").isnan(v)))
            )]

        if df_clean.empty:
            st.markdown('<div class="veo-alert veo-alert-error">No non-empty prompts found.</div>', unsafe_allow_html=True)
            st.stop()

        # ── Stats ──────────────────────────────────────────────────────────────
        total_rows  = len(df_clean)
        total_dur   = int(df_clean["duration"].apply(lambda x: _safe_int(x, 8, 1, 120)).sum()) if "duration" in df_clean.columns else 0
        total_clips = int(df_clean["duration"].apply(lambda x: clip_count(_safe_int(x, 8, 1, 120))).sum()) if "duration" in df_clean.columns else 0
        multi_count = int((df_clean["duration"].apply(lambda x: _safe_int(x, 8, 1, 120)) > 8).sum()) if "duration" in df_clean.columns else 0

        st.markdown(f"""
        <div class="stat-row">
            <div class="stat-card">
                <div class="stat-value">{total_rows}</div>
                <div class="stat-label">Prompts</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{total_clips}</div>
                <div class="stat-label">Total Clips</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{total_dur}s</div>
                <div class="stat-label">Total Duration</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{multi_count}</div>
                <div class="stat-label">Multi-clip Rows</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="veo-alert veo-alert-info">Preview — first 20 rows</div>', unsafe_allow_html=True)
        render_preview_table(df_clean.head(20))

        st.markdown("<hr class='veo-divider'>", unsafe_allow_html=True)

        # ── Submit ─────────────────────────────────────────────────────────────
        btn_disabled = not check_api()

        if btn_disabled:
            st.markdown(
                '<div class="veo-alert veo-alert-error">⚠ API offline — start veo_main.py before submitting</div>',
                unsafe_allow_html=True,
            )

        # Disable the button if the API is offline OR a job is already running.
        # This prevents the polling rerun loop from re-firing the upload.
        btn_disabled = btn_disabled or st.session_state.is_generating

        if st.session_state.is_generating:
            st.markdown(
                '<div class="veo-alert veo-alert-info">⏳ Generation in progress — button locked until complete</div>',
                unsafe_allow_html=True,
            )

        if st.button("🚀 Start Veo Generation", disabled=btn_disabled):
            # Lock immediately — before ANY async work — so that any rerun
            # triggered during the upload sees the button as disabled.
            st.session_state.is_generating = True
            with st.spinner("Uploading to Veo service…"):
                try:
                    file_bytes = uploaded.read()
                    result     = upload_file(file_bytes, uploaded.name)

                    job_id = result.get("job_id")
                    st.session_state.jobs[job_id]  = result
                    st.session_state.active_job    = job_id
                    st.session_state.upload_error  = None

                    st.markdown(
                        f'<div class="veo-alert veo-alert-success">✓ Job submitted — ID: <code>{job_id}</code></div>',
                        unsafe_allow_html=True,
                    )

                except requests.exceptions.ConnectionError:
                    st.session_state.upload_error = "Cannot connect to API. Is veo_main.py running on port 8100?"
                    st.session_state.is_generating = False
                except Exception as e:
                    st.session_state.upload_error = str(e)
                    st.session_state.is_generating = False

        if st.session_state.upload_error:
            st.markdown(
                f'<div class="veo-alert veo-alert-error">✗ {st.session_state.upload_error}</div>',
                unsafe_allow_html=True,
            )

        # ── Video grid — appears below upload UI once a job is running ──────────
        if st.session_state.active_job or st.session_state.get("last_completed_job"):
            # Show grid for the active job, or the most recently completed one
            display_job_id = (
                st.session_state.active_job
                or st.session_state.get("last_completed_job")
            )
            if display_job_id:
                try:
                    live_job = fetch_job(display_job_id)
                    display_job = {
                        **live_job.get("summary", {}),
                        "prompts":  live_job.get("prompts", []),
                        "status":   live_job.get("status", "processing"),
                        "results":  {
                            str(i): {
                                "status":    p.get("status"),
                                "video_url": p.get("video_url"),
                                "clips_count": p.get("clips_count", 0),
                                "duration_seconds": p.get("duration_seconds"),
                                "error_message": p.get("error_message", ""),
                            }
                            for i, p in enumerate(live_job.get("prompts", []))
                        },
                        "job_id": display_job_id,
                    }
                    render_video_grid(display_job)

                    # Auto-poll while job is still running.
                    # We use st.rerun() with a small fragment sleep instead of
                    # blocking the main thread with time.sleep() — a blocked
                    # thread queues up browser clicks and causes duplicate submits.
                    if live_job.get("status") in ("processing", "pending"):
                        st.session_state.active_job = display_job_id
                        time.sleep(POLL_INTERVAL)   # sleep is safe here — we're post-render
                        st.rerun()
                    else:
                        # completed, partial, or failed — job is done
                        # Store last_completed_job so grid keeps showing after active_job clears
                        st.session_state.last_completed_job = display_job_id
                        st.session_state.active_job         = None
                        st.session_state.is_generating      = False  # unlock button
                except Exception:
                    pass

    else:
        # Empty state
        st.markdown("""
        <div style="text-align:center;padding:3rem 0;color:var(--muted)">
            <div style="font-size:3rem;margin-bottom:1rem">🎬</div>
            <div style="font-size:1.1rem;font-weight:600;margin-bottom:0.5rem">Drop an Excel file to get started</div>
            <div style="font-family:Space Mono,monospace;font-size:0.75rem">
                Required columns: <span style="color:var(--accent)">prompt</span> · <span style="color:var(--accent)">duration</span>
            </div>
            <div style="margin-top:1rem;font-family:Space Mono,monospace;font-size:0.7rem">
                Download the template from the sidebar →
            </div>
        </div>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — Jobs
# ══════════════════════════════════════════════════════════════════════════════

with tab_jobs:

    col_refresh, col_auto = st.columns([1, 2])
    with col_refresh:
        if st.button("↻ Refresh"):
            pass  # triggers rerun
    with col_auto:
        auto_refresh = st.checkbox("Auto-refresh every 4s", value=bool(st.session_state.active_job))

    # Fetch active job
    if st.session_state.active_job:
        try:
            live_job = fetch_job(st.session_state.active_job)
            st.session_state.jobs[st.session_state.active_job] = {
                **live_job.get("summary", {}),
                "prompts": live_job.get("prompts", []),
                "status":  live_job.get("status", "processing"),
            }
            # Clear active once done
            if live_job.get("status") in ("completed", "partial", "failed"):
                st.session_state.active_job = None
        except Exception:
            pass

    # Merge with server jobs
    server_jobs = {j["job_id"]: j for j in fetch_all_jobs()}
    all_jobs = {**server_jobs, **st.session_state.jobs}

    if not all_jobs:
        st.markdown("""
        <div style="text-align:center;padding:3rem 0;color:var(--muted)">
            <div style="font-size:2rem;margin-bottom:0.75rem">📭</div>
            <div>No jobs yet — upload an Excel file to start</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"**{len(all_jobs)} job{'s' if len(all_jobs) != 1 else ''}**")
        for job_id, job in sorted(all_jobs.items(), reverse=True):
            render_job_card(job, live=(job_id == st.session_state.active_job))

    # Auto-refresh while a job is running
    if auto_refresh and st.session_state.active_job:
        time.sleep(POLL_INTERVAL)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3 — YouTube Queue
# ══════════════════════════════════════════════════════════════════════════════

with tab_metrics:
    st.markdown("### 📊 Live Generation Metrics")
    st.caption("Updates every 5 seconds. Resets when veo_main.py restarts.")

    def fetch_metrics() -> dict:
        try:
            r = requests.get(f"{API_BASE}/api/metrics", timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    m = fetch_metrics()

    if not m:
        st.warning("Cannot reach API — start veo_main.py first.")
    else:
        # ── Session overview ──────────────────────────────────────────────
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Jobs Processed", m.get("jobs_processed", 0))
        with col2:
            st.metric("Clips Generated", m["veo"]["clips_generated"])
        with col3:
            st.metric("Avg Clip Time", f"{m['veo']['avg_clip_time_s']}s")
        with col4:
            est = m.get("cost_estimate", {})
            st.metric("Est. Cost (session)", f"₹{est.get('inr', 0):.2f}")

        st.divider()

        # ── Veo API ──────────────────────────────────────────────────────
        st.markdown("#### 🎬 Veo API")
        v = m["veo"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Submissions",     v["submissions"])
        c2.metric("Successes",       v["successes"])
        c3.metric("Failures",        v["failures"],
                  delta=f"-{v['failures']}" if v["failures"] else None,
                  delta_color="inverse")
        c4.metric("429 Rate Limits", v["rate_limit_hits"],
                  delta=f"{v['rate_limit_pct']}%" if v["rate_limit_hits"] else None,
                  delta_color="inverse")
        c5.metric("Total Gen Time",  f"{v['total_gen_time_s']}s")

        rl_pct = v["rate_limit_pct"]
        if v["submissions"] == 0:
            st.info("No submissions yet this session.")
        elif rl_pct == 0:
            st.success("✅ No rate limit hits this session")
        elif rl_pct < 20:
            st.warning(f"⚠️ {rl_pct}% of submissions hit rate limits")
        else:
            st.error(f"🔴 {rl_pct}% rate limit hit rate — reduce concurrency or upgrade quota")

        st.divider()

        # ── Decomposer ────────────────────────────────────────────────────
        st.markdown("#### 🧠 Prompt Decomposer (AWS Bedrock)")
        d = m["decomposer"]
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Nova 2 Lite Calls",  d["nova_calls"])
        d2.metric("DeepSeek R1 Calls",  d["deepseek_calls"],
                  delta=f"+{d['deepseek_calls']} fallbacks" if d["deepseek_calls"] else None,
                  delta_color="inverse")
        d3.metric("Deterministic",      d["deterministic"],
                  delta=f"+{d['deterministic']} fallbacks" if d["deterministic"] else None,
                  delta_color="inverse")
        d4.metric("Input Tokens",       f"{d['input_tokens']:,}")
        d5.metric("Output Tokens",      f"{d['output_tokens']:,}")

        nova_cost_inr = (d["input_tokens"]  / 1000 * 0.000060 +
                         d["output_tokens"] / 1000 * 0.000240) * 92.5
        ds_cost_inr   = (d["input_tokens"]  / 1000 * 0.00135  +
                         d["output_tokens"] / 1000 * 0.00540)  * 92.5
        st.caption(
            f"Bedrock cost — Nova: ₹{nova_cost_inr:.4f}  |  "
            f"DeepSeek (if called): ₹{ds_cost_inr:.4f}"
        )

        st.divider()

        # ── S3 ────────────────────────────────────────────────────────────
        st.markdown("#### ☁️ S3 Uploads")
        s = m["s3"]
        s1, s2 = st.columns(2)
        s1.metric("Succeeded", s["uploads_ok"])
        s2.metric("Failed",    s["uploads_fail"],
                  delta=f"-{s['uploads_fail']}" if s["uploads_fail"] else None,
                  delta_color="inverse")

        st.divider()

        # ── Cost summary ──────────────────────────────────────────────────
        st.markdown("#### 💰 Session Cost Estimate")
        est = m.get("cost_estimate", {})
        st.info(
            f"**${est.get('usd', 0):.4f} USD  /  ₹{est.get('inr', 0):.2f} INR**  "
            f"(primary model rate · successful clips only)  \n"
            f"_{est.get('note', '')}_"
        )

    # Only auto-refresh metrics while a job is actively running.
    # Unconditional rerun here competes with the generate tab polling loop
    # and causes duplicate card rendering on every cycle.
    if st.session_state.get("active_job") or st.session_state.get("is_generating"):
        time.sleep(5)
        st.rerun()

with tab_youtube:
    import html as _html

    # ── YouTube connection status ─────────────────────────────────────────────
    yt_status = fetch_youtube_status()
    configured    = yt_status.get("configured", False)
    authenticated = yt_status.get("authenticated", False)

    if not configured:
        st.markdown("""
<div class="veo-alert veo-alert-error">
⚠ <code>youtube_client_secrets.json</code> not found in project folder.<br>
Download it from Google Cloud Console → APIs & Services → Credentials.
</div>""", unsafe_allow_html=True)
    elif not authenticated:
        st.markdown("""
<div class="veo-alert veo-alert-info">
YouTube connected but not authenticated yet.<br>
Click the button below to open a browser and approve access (one-time only).
</div>""", unsafe_allow_html=True)
        if st.button("🔐 Authenticate with YouTube"):
            try:
                r = requests.post(f"{API_BASE}/api/youtube/auth", timeout=120)
                if r.status_code == 200:
                    st.markdown('<div class="veo-alert veo-alert-success">✓ Authenticated successfully</div>',
                                unsafe_allow_html=True)
                    st.rerun()
                else:
                    st.error(f"Auth failed: {r.text}")
            except Exception as e:
                st.error(f"Auth error: {e}")
    else:
        st.markdown('<div class="veo-alert veo-alert-success">✓ YouTube connected and authenticated</div>',
                    unsafe_allow_html=True)

    st.markdown("<hr class='veo-divider'>", unsafe_allow_html=True)

    # ── Queue header ──────────────────────────────────────────────────────────
    col_title, col_upload = st.columns([3, 1])
    with col_title:
        st.markdown("### Upload Queue")
        st.caption("Approve videos in the Generate tab → they appear here for review before upload.")

    # Fetch fresh queue
    queue = fetch_youtube_queue()
    st.session_state.yt_queue = queue

    approved_count  = sum(1 for q in queue if q["status"] == "approved")
    uploaded_count  = sum(1 for q in queue if q["status"] == "uploaded")
    uploading_count = sum(1 for q in queue if q["status"] == "uploading")
    failed_count    = sum(1 for q in queue if q["status"] == "failed")

    with col_upload:
        st.markdown("<br>", unsafe_allow_html=True)
        upload_disabled = approved_count == 0 or not authenticated
        if st.button(
            f"▶  Upload {approved_count} to YouTube" if approved_count > 0 else "▶  Upload to YouTube",
            disabled=upload_disabled,
            type="primary",
        ):
            result = trigger_youtube_upload()
            if result.get("status") == "started":
                st.markdown(
                    f'<div class="veo-alert veo-alert-success">✓ Upload started — {result.get("count")} video(s)</div>',
                    unsafe_allow_html=True,
                )
                time.sleep(1)
                st.rerun()
            else:
                st.error(result.get("message", "Upload failed"))

    # ── Stats row ─────────────────────────────────────────────────────────────
    if queue:
        st.markdown(f"""
<div class="stat-row">
    <div class="stat-card"><div class="stat-value">{len(queue)}</div><div class="stat-label">In Queue</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--warn)">{approved_count}</div><div class="stat-label">Approved</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--success)">{uploaded_count}</div><div class="stat-label">Uploaded</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--error)">{failed_count}</div><div class="stat-label">Failed</div></div>
</div>""", unsafe_allow_html=True)

    st.markdown("<hr class='veo-divider'>", unsafe_allow_html=True)

    # ── Queue items ───────────────────────────────────────────────────────────
    if not queue:
        st.markdown("""
<div style="text-align:center;padding:3rem 0;color:var(--muted)">
    <div style="font-size:2rem;margin-bottom:0.75rem">▶</div>
    <div>No videos in the upload queue yet.</div>
    <div style="font-family:Space Mono,monospace;font-size:0.75rem;margin-top:0.5rem">
        Generate videos → click ✓ Approve on any completed video
    </div>
</div>""", unsafe_allow_html=True)
    else:
        for item in queue:
            qid       = item["queue_id"]
            status    = item["status"]
            yt_url    = item.get("youtube_url")
            video_url = item.get("video_url", "")
            err       = item.get("error", "")

            status_colors = {
                "approved":  "var(--warn)",
                "uploading": "var(--accent)",
                "uploaded":  "var(--success)",
                "failed":    "var(--error)",
            }
            status_labels = {
                "approved":  "⏳ Approved — ready to upload",
                "uploading": "⬆ Uploading…",
                "uploaded":  "✓ Uploaded to YouTube",
                "failed":    "✗ Upload failed",
            }
            sc = status_colors.get(status, "var(--muted)")
            sl = status_labels.get(status, status)

            card_class = f"yt-queue-card {status}"
            st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)

            card_col1, card_col2 = st.columns([1, 2])

            with card_col1:
                if video_url:
                    full_url = video_url if video_url.startswith("http") else f"{API_BASE}{video_url}"
                    st.markdown(
                        f'<video class="yt-video-thumb" src="{_html.escape(full_url)}" preload="metadata"></video>',
                        unsafe_allow_html=True,
                    )
                if yt_url:
                    st.markdown(
                        f'<a class="yt-link" href="{yt_url}" target="_blank">▶ Watch on YouTube →</a>',
                        unsafe_allow_html=True,
                    )

            with card_col2:
                st.markdown(
                    f'<div style="font-family:Space Mono,monospace;font-size:0.65rem;color:{sc};margin-bottom:0.5rem">{sl}</div>',
                    unsafe_allow_html=True,
                )
                if err:
                    st.markdown(
                        f'<div style="font-size:0.7rem;color:var(--error);margin-bottom:0.5rem">{_html.escape(err[:120])}</div>',
                        unsafe_allow_html=True,
                    )

                # Editable fields — only shown for approved/failed (not uploaded/uploading)
                if status in ("approved", "failed"):
                    new_title = st.text_input(
                        "Title",
                        value=item.get("title", ""),
                        max_chars=100,
                        key=f"yt_title_{qid}",
                    )
                    new_desc = st.text_area(
                        "Description",
                        value=item.get("description", ""),
                        height=100,
                        key=f"yt_desc_{qid}",
                    )
                    tags_str = st.text_input(
                        "Tags (comma-separated)",
                        value=", ".join(item.get("tags", [])),
                        key=f"yt_tags_{qid}",
                    )
                    new_tags = [t.strip() for t in tags_str.split(",") if t.strip()]

                    btn_c1, btn_c2 = st.columns(2)
                    with btn_c1:
                        if st.button("💾  Save", key=f"yt_save_{qid}", type="secondary"):
                            ok = update_queue_item(qid, new_title, new_desc, new_tags)
                            if ok:
                                st.markdown(
                                    '<div class="veo-alert veo-alert-success" style="padding:0.4rem 0.8rem;font-size:0.8rem">Saved</div>',
                                    unsafe_allow_html=True,
                                )
                                st.rerun()
                    with btn_c2:
                        if st.button("🗑  Remove", key=f"yt_remove_{qid}", type="secondary"):
                            remove_from_queue(qid)
                            st.rerun()
                else:
                    # Read-only view for uploaded/uploading
                    st.markdown(f"**{_html.escape(item.get('title', ''))}**")
                    st.caption(item.get("description", "")[:200])
                    if item.get("tags"):
                        st.caption("Tags: " + ", ".join(item["tags"][:8]))

            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown("")

    # Auto-refresh while uploads are in progress
    if uploading_count > 0:
        time.sleep(3)
        st.rerun()