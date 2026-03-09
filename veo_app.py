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
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────
for key, default in [
    ("jobs",         {}),
    ("active_job",   None),
    ("upload_error", None),
    ("api_ok",       None),
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
        dur   = int(row.get("duration", 8))
        clips = clip_count(dur)
        tt    = str(row.get("task_type", "AUTO")).upper()
        prio  = row.get("priority", 5)
        prompt = str(row.get("prompt", ""))
        prompt_display = prompt[:90] + "…" if len(prompt) > 90 else prompt

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
            <td style="font-family:Space Mono,monospace;font-size:0.75rem;color:var(--muted)">{int(prio)}</td>
        </tr>"""

    st.markdown(f"""
    <table class="veo-table">
        <thead><tr>
            <th>#</th><th>Prompt</th><th>Duration</th><th>Task</th><th>Priority</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
    </table>""", unsafe_allow_html=True)


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
                    if vurl and pstatus == "completed":
                        full_url = f"{API_BASE}{vurl}"
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

tab_upload, tab_jobs = st.tabs(["🎬 Upload & Generate", "📊 Jobs"])


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

        # Drop empties
        df_clean = df_raw.dropna(subset=["prompt"])
        df_clean = df_clean[df_clean["prompt"].astype(str).str.strip() != ""]

        if df_clean.empty:
            st.markdown('<div class="veo-alert veo-alert-error">No non-empty prompts found.</div>', unsafe_allow_html=True)
            st.stop()

        # ── Stats ──────────────────────────────────────────────────────────────
        total_rows  = len(df_clean)
        total_dur   = int(df_clean["duration"].apply(lambda x: max(1, min(120, int(float(x))))).sum()) if "duration" in df_clean.columns else 0
        total_clips = int(df_clean["duration"].apply(lambda x: -(-max(1, min(120, int(float(x)))) // 8)).sum()) if "duration" in df_clean.columns else 0
        multi_count = int((df_clean["duration"].apply(lambda x: int(float(x))) > 8).sum()) if "duration" in df_clean.columns else 0

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

        if st.button("🚀 Start Veo Generation", disabled=btn_disabled):
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
                except Exception as e:
                    st.session_state.upload_error = str(e)

        if st.session_state.upload_error:
            st.markdown(
                f'<div class="veo-alert veo-alert-error">✗ {st.session_state.upload_error}</div>',
                unsafe_allow_html=True,
            )

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
