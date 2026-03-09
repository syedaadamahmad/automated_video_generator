"""
veo_excel_processor.py — Excel Processor for the Veo Video Generation Platform
════════════════════════════════════════════════════════════════════════════════

Veo generates video + audio natively from text prompts.
This processor is intentionally minimal — only the fields Veo actually uses.

Excel column contract
─────────────────────
REQUIRED:
  prompt     — text prompt sent to Veo (string, non-empty)
  duration   — target video duration in seconds (int, 1–120)

OPTIONAL:
  task_type  — AUTO | TEXT_VIDEO | MULTI_SHOT_AUTOMATED  (default: AUTO)
  priority   — dispatch priority, integer 1–10            (default: 5)

Column aliases (case-insensitive):
  prompt     ← text, video_prompt
  duration   ← duration_s, duration_sec
  task_type  ← tasktype, type
  priority   ← prio, rank

NOT SUPPORTED (Veo handles these natively):
  audio_mode, description, language, image
  — these columns are silently ignored if present
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("VEO_EXCEL")

# ── Column aliases ─────────────────────────────────────────────────────────────
_COL_ALIASES: Dict[str, str] = {
    "prompt":       "prompt",
    "text":         "prompt",
    "video_prompt": "prompt",
    "duration":     "duration",
    "duration_s":   "duration",
    "duration_sec": "duration",
    "task_type":    "task_type",
    "tasktype":     "task_type",
    "type":         "task_type",
    "priority":     "priority",
    "prio":         "priority",
    "rank":         "priority",
}

_VALID_TASK_TYPES = {"AUTO", "TEXT_VIDEO", "MULTI_SHOT_AUTOMATED"}
_DEFAULT_TASK_TYPE = "AUTO"
_DEFAULT_PRIORITY  = 5
_MIN_DURATION      = 1
_MAX_DURATION      = 120
_MIN_PRIORITY      = 1
_MAX_PRIORITY      = 10


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_excel_file(file_path: str) -> Tuple[bool, List[str]]:
    """
    Validate an Excel/CSV file for Veo generation.

    Returns:
        (is_valid: bool, errors: List[str])
    """
    errors: List[str] = []
    path = Path(file_path)

    logger.info("=" * 60)
    logger.info(f"[VEO_EXCEL] Validating: {path.name}")
    logger.info("=" * 60)

    if not path.exists():
        return False, [f"File not found: {file_path}"]

    try:
        df = _load_file(path)
        logger.info(f"   Loaded — {len(df)} rows x {len(df.columns)} columns")
    except Exception as e:
        return False, [f"Could not parse file: {e}"]

    df = _normalise_columns(df)

    # Required columns
    for col in ("prompt", "duration"):
        if col not in df.columns:
            errors.append(f"Missing required column: '{col}'")

    if errors:
        return False, errors

    if df.empty:
        return False, ["File contains no data rows"]

    # Row-level validation
    for idx, row in df.iterrows():
        row_num = idx + 2  # 1-based, header offset

        prompt = str(row.get("prompt", "")).strip()
        if not prompt:
            errors.append(f"Row {row_num}: 'prompt' is empty")

        try:
            dur = int(float(row.get("duration", 0)))
            if not (_MIN_DURATION <= dur <= _MAX_DURATION):
                errors.append(
                    f"Row {row_num}: duration {dur}s out of range "
                    f"({_MIN_DURATION}–{_MAX_DURATION}s)"
                )
        except (ValueError, TypeError):
            errors.append(f"Row {row_num}: 'duration' is not a valid number")

        if "task_type" in df.columns:
            raw_tt = row.get("task_type")
            if raw_tt is not None and str(raw_tt).strip().lower() not in ("nan", "none", ""):
                tt = str(raw_tt).strip().upper()
                if tt not in _VALID_TASK_TYPES:
                    errors.append(
                        f"Row {row_num}: unknown task_type '{tt}' "
                        f"(valid: {', '.join(sorted(_VALID_TASK_TYPES))})"
                    )

    is_valid = len(errors) == 0
    if is_valid:
        logger.info(f"   Validation passed — {len(df)} rows, 0 errors")
    else:
        for e in errors:
            logger.error(f"   ERROR: {e}")

    return is_valid, errors


def create_job_from_excel(
    file_path: str,
    platforms: Optional[List[str]] = None,
    audio_mode: str = "platform_native",   # accepted for API compat, not used
) -> Dict[str, Any]:
    """
    Parse file and build a job dict for the Veo generation pipeline.

    Returns a job dict with:
        job_id, status, total_prompts, completed_prompts, failed_prompts,
        progress_percent, created_at, platforms, prompts, results, metadata

    Each prompt dict contains:
        text, duration, task_type, platforms, priority,
        row_number, original_index
    """
    if platforms is None:
        platforms = ["veo"]

    path = Path(file_path)
    df   = _load_file(path)
    df   = _normalise_columns(df)

    # Drop rows with empty prompts
    df = df.dropna(subset=["prompt"])
    df["prompt"] = df["prompt"].astype(str).str.strip()
    df = df[df["prompt"] != ""]

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    now    = datetime.now(timezone.utc).isoformat()

    logger.info(f"[VEO_EXCEL] Building job {job_id} from {path.name} — {len(df)} rows")

    has_task_col     = "task_type" in df.columns
    has_priority_col = "priority"  in df.columns

    prompts: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        row_num = idx + 2

        prompt_text = str(row.get("prompt", "")).strip()

        try:
            duration = max(
                _MIN_DURATION,
                min(_MAX_DURATION, int(float(row.get("duration", 8)))),
            )
        except (ValueError, TypeError):
            duration = 8
            logger.warning(f"   Row {row_num}: invalid duration — defaulting to 8s")

        # task_type
        task_type = _DEFAULT_TASK_TYPE
        if has_task_col:
            raw_tt = row.get("task_type")
            if raw_tt is not None and str(raw_tt).strip().lower() not in ("nan", "none", ""):
                tt = str(raw_tt).strip().upper()
                task_type = tt if tt in _VALID_TASK_TYPES else _DEFAULT_TASK_TYPE

        # priority
        priority = _DEFAULT_PRIORITY
        if has_priority_col:
            raw_prio = row.get("priority")
            if raw_prio is not None and str(raw_prio).strip().lower() not in ("nan", "none", ""):
                try:
                    priority = max(
                        _MIN_PRIORITY,
                        min(_MAX_PRIORITY, int(float(raw_prio))),
                    )
                except (ValueError, TypeError):
                    pass

        prompts.append({
            "text":           prompt_text,
            "duration":       duration,
            "task_type":      task_type,
            "platforms":      list(platforms),
            "priority":       priority,
            # audio fields — kept for API compat with veo_main.py, never forwarded to Veo
            "audio_mode":     "platform_native",
            "description":    "",
            "language":       "en",
            "has_narration":  False,
            # debug
            "row_number":     row_num,
            "original_index": int(idx),
        })

        logger.info(
            f"   Row {row_num:>3}: {duration:>3}s [{task_type}] priority={priority} "
            f"— \"{prompt_text[:80]}{'...' if len(prompt_text) > 80 else ''}\""
        )

    if not prompts:
        raise ValueError(
            f"No valid prompts found in '{path.name}'. "
            f"Ensure the 'prompt' column is populated."
        )

    return {
        "job_id":             job_id,
        "original_filename":  path.name,
        "status":             "pending",
        "completed_prompts":  0,
        "failed_prompts":     0,
        "progress_percent":   0.0,
        "created_at":         now,
        "updated_at":         now,
        "platforms":          list(platforms),
        "audio_mode":         "platform_native",
        "total_prompts":      len(prompts),
        "prompts":            prompts,
        "results":            {},
        "metadata": {
            "total_duration_seconds": sum(p["duration"] for p in prompts),
            "platforms_used":         sorted(set(platforms)),
            "estimated_clips":        sum(
                -(-p["duration"] // 8) for p in prompts  # ceil(duration/8)
            ),
        },
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lower() for c in df.columns]
    rename_map = {c: _COL_ALIASES[c] for c in df.columns if c in _COL_ALIASES}
    if rename_map:
        logger.debug(f"   Column aliases applied: {rename_map}")
    return df.rename(columns=rename_map)
