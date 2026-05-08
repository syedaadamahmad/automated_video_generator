"""
veo_short_span_excel_processor.py — Excel Processor for Short Span Clips
═════════════════════════════════════════════════════════════════════════

Short span mode: each Excel row = one discrete clip sent directly to Veo.
No prompt decomposition. No duration column needed (set from the UI slider).

Excel column contract
─────────────────────
REQUIRED:
  prompt       — scene description for this specific clip (string, non-empty)

OPTIONAL:
  aspect_ratio — 9:16 | 16:9 | 1:1 | 4:3  (reference only — set globally in veo.env)

NOT USED (ignored if present):
  duration, task_type, priority
  — these are full-length pipeline fields, meaningless in short span mode.

Column aliases (case-insensitive):
  prompt ← text, video_prompt, clip_prompt, scene
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("SS_EXCEL")

# ── Column aliases ─────────────────────────────────────────────────────────────
_COL_ALIASES: Dict[str, str] = {
    "prompt":       "prompt",
    "text":         "prompt",
    "video_prompt": "prompt",
    "clip_prompt":  "prompt",
    "scene":        "prompt",
    "aspect_ratio": "aspect_ratio",
    "aspect":       "aspect_ratio",
    "ratio":        "aspect_ratio",
    # Silently accept but ignore full-length columns
    "duration":     "duration",
    "duration_s":   "duration",
    "task_type":    "task_type",
    "tasktype":     "task_type",
    "priority":     "priority",
    "prio":         "priority",
}

_VALID_ASPECT_RATIOS = {"9:16", "16:9", "1:1", "4:3", "3:4"}
_DEFAULT_ASPECT_RATIO = "9:16"


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_short_span_excel(file_path: str) -> Tuple[bool, List[str]]:
    """
    Validate an Excel/CSV file for short span clip generation.

    Only requires the 'prompt' column. Everything else is optional or ignored.

    Returns:
        (is_valid: bool, errors: List[str])
    """
    errors: List[str] = []
    path = Path(file_path)

    logger.info("=" * 60)
    logger.info(f"[SS_EXCEL] Validating: {path.name}")
    logger.info("=" * 60)

    if not path.exists():
        return False, [f"File not found: {file_path}"]

    try:
        df = _load_file(path)
        logger.info(f"   Loaded — {len(df)} rows x {len(df.columns)} columns")
    except Exception as e:
        return False, [f"Could not parse file: {e}"]

    df = _normalise_columns(df)

    if "prompt" not in df.columns:
        return False, ["Missing required column: 'prompt'"]

    if df.empty:
        return False, ["File contains no data rows"]

    for idx, row in df.iterrows():
        row_num = idx + 2
        prompt  = str(row.get("prompt", "")).strip()
        if not prompt or prompt.lower() in ("nan", "none", ""):
            continue  # blank row — skip

        # Aspect ratio validation (if column present)
        if "aspect_ratio" in df.columns:
            ar_raw = str(row.get("aspect_ratio", "")).strip()
            if ar_raw and ar_raw.lower() not in ("nan", "none", ""):
                if ar_raw not in _VALID_ASPECT_RATIOS:
                    errors.append(
                        f"Row {row_num}: unknown aspect_ratio '{ar_raw}' "
                        f"(valid: {', '.join(sorted(_VALID_ASPECT_RATIOS))})"
                    )

    is_valid = len(errors) == 0
    if is_valid:
        logger.info(f"   Validation passed — {len(df)} rows, 0 errors")
    else:
        for e in errors:
            logger.error(f"   ERROR: {e}")

    return is_valid, errors


def create_short_span_job(
    file_path: str,
    clip_duration_s: float = 2.0,
    aspect_ratio: str = "9:16",
) -> Dict[str, Any]:
    """
    Parse file and build a job dict for the short span generation pipeline.

    Args:
        file_path:       Path to the Excel/CSV file.
        clip_duration_s: Duration of each clip in seconds (2–8). From UI.
        aspect_ratio:    Default aspect ratio. Overridden per-row if column present.

    Returns job dict with the same shape as create_job_from_excel() for
    compatibility with veo_main.py's job store and get_job response.
    """
    path = Path(file_path)
    df   = _load_file(path)
    df   = _normalise_columns(df)

    # Drop blank prompt rows
    df = df.dropna(subset=["prompt"])
    df["prompt"] = df["prompt"].astype(str).str.strip()
    df = df[df["prompt"].str.lower() != ""]
    df = df[~df["prompt"].str.lower().isin(["nan", "none"])]
    df = df.reset_index(drop=True)

    clip_dur = max(2, min(8, int(clip_duration_s)))
    job_id   = f"job_{uuid.uuid4().hex[:8]}"
    now      = datetime.now(timezone.utc).isoformat()

    has_ar_col = "aspect_ratio" in df.columns

    logger.info(f"[SS_EXCEL] Building short span job {job_id} — {len(df)} clips at {clip_dur}s each")

    prompts: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        row_num     = idx + 2
        prompt_text = str(row.get("prompt", "")).strip()

        # Per-row aspect ratio if provided, else use job-level default
        row_ar = aspect_ratio
        if has_ar_col:
            ar_raw = str(row.get("aspect_ratio", "")).strip()
            if ar_raw and ar_raw not in ("nan", "none", "") \
                    and ar_raw in _VALID_ASPECT_RATIOS:
                row_ar = ar_raw

        prompts.append({
            "text":           prompt_text,
            "duration":       clip_dur,      # used for display/metrics only
            "task_type":      "TEXT_VIDEO",  # each row = one clip, no decomp
            "platforms":      ["veo"],
            "priority":       1,             # all clips equal priority, sequential
            "audio_mode":     "platform_native",
            "description":    "",
            "language":       "en",
            "has_narration":  False,
            "aspect_ratio":   row_ar,
            "row_number":     row_num,
            "original_index": int(idx),
        })

        logger.info(
            f"   Clip {idx + 1:>3}: {clip_dur}s [{row_ar}] "
            f"— \"{prompt_text[:80]}{'...' if len(prompt_text) > 80 else ''}\""
        )

    if not prompts:
        raise ValueError(
            f"No valid prompts found in '{path.name}'. "
            f"Ensure the 'prompt' column is populated."
        )

    total_duration = len(prompts) * clip_dur

    return {
        "job_id":             job_id,
        "original_filename":  path.name,
        "status":             "pending",
        "completed_prompts":  0,
        "failed_prompts":     0,
        "progress_percent":   0.0,
        "created_at":         now,
        "updated_at":         now,
        "platforms":          ["veo"],
        "audio_mode":         "platform_native",
        "total_prompts":      len(prompts),
        "prompts":            prompts,
        "results":            {},
        "metadata": {
            "total_duration_seconds": total_duration,
            "clip_duration_s":        clip_dur,
            "platforms_used":         ["veo"],
            "estimated_clips":        len(prompts),
            "mode":                   "short_span",
        },
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    rename_map = {c: _COL_ALIASES[c] for c in df.columns if c in _COL_ALIASES}
    if rename_map:
        logger.debug(f"   Column aliases: {rename_map}")
    return df.rename(columns=rename_map)