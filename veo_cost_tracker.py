#!/usr/bin/env python3
"""
veo_cost_tracker.py
════════════════════
Reads completed Veo job results from the running API and calculates
exact cost per clip, per prompt, and per job in USD and INR.

Usage:
    python veo_cost_tracker.py                     # all jobs
    python veo_cost_tracker.py --job job_5b60b470  # one job
    python veo_cost_tracker.py --rate 92.5         # override INR rate

Pricing (Google official, September 2025):
    veo-3.0-generate-001      = $0.40 / second  (with audio)
    veo-3.0-fast-generate-001 = $0.15 / second  (with audio)

INR rate is fetched live from exchangerate-api.com.
Falls back to --rate argument or 92.5 if fetch fails.

# All jobs from disk
python veo_cost_tracker.py --offline

# One specific job from disk
python veo_cost_tracker.py --offline --job job_5b60b470

# Override INR rate
python veo_cost_tracker.py --offline --rate 92.5

# JSON output for Excel
python veo_cost_tracker.py --offline --json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional
import requests

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE     = "http://localhost:8100"
FALLBACK_INR = 92.5  # used if live rate fetch fails

# Google official per-second rates (September 2025)
MODEL_RATES: dict[str, float] = {
    "veo-3.0-generate-001":       0.40,
    "veo-3.0-generate-preview":   0.40,
    "veo-3.0-fast-generate-001":  0.15,
    "veo-3.0-fast-generate-preview": 0.15,
}
DEFAULT_RATE = 0.40  # fallback if model string not matched

# AWS Bedrock decomposer pricing (per 1,000 tokens)
# Nova 2 Lite — primary decomposer
NOVA_INPUT_PER_1K   = 0.000060
NOVA_OUTPUT_PER_1K  = 0.000240
# DeepSeek R1 — fallback decomposer
DEEPSEEK_INPUT_PER_1K  = 0.00135
DEEPSEEK_OUTPUT_PER_1K = 0.00540
# Approximate tokens per decomposition call (850 input, 450 output)
DECOMP_INPUT_TOKENS  = 850
DECOMP_OUTPUT_TOKENS = 450


# ── Live INR rate ─────────────────────────────────────────────────────────────
def get_inr_rate(override: Optional[float] = None) -> tuple[float, str]:
    """Return (rate, source_label)."""
    if override:
        return override, f"manual override"
    try:
        r = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=5
        )
        rate = r.json()["rates"]["INR"]
        return rate, "live (exchangerate-api.com)"
    except Exception:
        pass
    try:
        r = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=5
        )
        rate = r.json()["rates"]["INR"]
        return rate, "live (open.er-api.com)"
    except Exception:
        pass
    return FALLBACK_INR, f"fallback hardcoded (fetch failed)"


# ── Rate lookup ───────────────────────────────────────────────────────────────
def usd_per_second(model_used: str) -> float:
    """Return per-second USD rate for a model string."""
    model_used = (model_used or "").strip()
    for key, rate in MODEL_RATES.items():
        if key in model_used:
            return rate
    return DEFAULT_RATE


# ── Offline mode: read from local disk ────────────────────────────────────────
def find_outputs_dir() -> Optional[Path]:
    """
    Locate the outputs/videos directory relative to this script.
    Searches: script dir, parent, grandparent.
    """
    from pathlib import Path
    candidates = [
        Path(__file__).parent / "outputs" / "videos",
        Path(__file__).parent / "outputs",
        Path(__file__).parent,
    ]
    for c in candidates:
        if c.exists() and any(c.glob("*.mp4")):
            return c
    return None


def find_decompositions_dir() -> Optional[Path]:
    from pathlib import Path
    candidates = [
        Path(__file__).parent / "outputs" / "decompositions",
        Path(__file__).parent / "decompositions",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_offline_jobs() -> list[dict]:
    """
    Build job summaries from local decomposition JSONs + video files.

    Strategy:
    - Read every *_decomposition.json in outputs/decompositions/
    - Group by job_id
    - For each prompt, check whether a video file exists in outputs/videos/
    - Infer model_used from decomposition source field
    - Infer clips_count from n_clips in decomposition JSON
    """
    import re
    from pathlib import Path

    decomp_dir = find_decompositions_dir()
    video_dir  = find_outputs_dir()

    if not decomp_dir:
        print("[OFFLINE] No decompositions directory found.")
        print("  Expected: outputs/decompositions/ next to this script.")
        return []

    decomp_files = sorted(decomp_dir.glob("*_decomposition.json"))
    if not decomp_files:
        print(f"[OFFLINE] No decomposition files found in {decomp_dir}")
        return []

    # Group decompositions by job_id
    jobs_map: dict[str, list[dict]] = {}
    for f in decomp_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            job_id = data.get("job_id", "unknown")
            if job_id not in jobs_map:
                jobs_map[job_id] = []
            jobs_map[job_id].append(data)
        except Exception as e:
            print(f"[OFFLINE] Could not read {f.name}: {e}")

    if not jobs_map:
        return []

    # Build job dicts compatible with analyse_job()
    result = []
    for job_id, decomps in jobs_map.items():
        # Sort prompts by prompt_index
        decomps.sort(key=lambda d: d.get("prompt_index", 0))

        prompts = []
        for d in decomps:
            prompt_idx  = d.get("prompt_index", 1)
            n_clips     = d.get("n_clips", 1)
            duration_s  = d.get("duration_s", 8)
            decomp_src  = d.get("model_used", "deterministic")

            # Infer model_used for cost: decomp_source tells us LLM used,
            # not Veo model. Check for video file to confirm generation succeeded.
            video_found = False
            model_used  = "models/veo-3.0-generate-001"  # default primary
            if video_dir:
                # Look for any mp4 matching this job + prompt index
                patterns = [
                    f"{job_id}_veo_p{prompt_idx}.mp4",           # single clip
                    f"{job_id}_p{prompt_idx}_veo_stitched*.mp4",  # stitched
                ]
                for pat in patterns:
                    matches = list(video_dir.glob(pat))
                    if matches:
                        video_found = True
                        # Check filename for fast model hint
                        # (not directly inferrable from filename — use primary as default)
                        break

            # Also check for _final.mp4 (fade applied)
            if video_dir and not video_found:
                finals = list(video_dir.glob(f"{job_id}_p{prompt_idx}_veo_stitched_final.mp4"))
                if finals:
                    video_found = True

            status = "completed" if video_found else "failed"

            prompts.append({
                "status":           status,
                "model_used":       model_used,
                "duration_seconds": duration_s,
                "clips_count":      n_clips,
                "stitched":         n_clips > 1,
                "decomp_source":    decomp_src,
                "video_url":        f"/videos/{job_id}_p{prompt_idx}" if video_found else None,
            })

        result.append({
            "job_id":   job_id,
            "summary":  {
                "job_id":            job_id,
                "original_filename": "",
                "status":            "completed" if any(p["status"] == "completed" for p in prompts) else "failed",
            },
            "prompts":  prompts,
        })

    return result


# ── Cost calculation ──────────────────────────────────────────────────────────
def calc_clip_cost(model_used: str, duration_s: int) -> float:
    return usd_per_second(model_used) * duration_s


def analyse_job(job_data: dict, inr_rate: float) -> dict:
    """
    Parse a job result dict from GET /api/jobs/{job_id}.
    Returns structured cost breakdown.
    """
    job_id   = job_data.get("job_id", "unknown")
    prompts  = job_data.get("prompts", [])
    summary  = job_data.get("summary", {})
    filename = summary.get("original_filename", "")

    prompt_breakdowns = []
    job_usd_total     = 0.0

    for i, p in enumerate(prompts):
        status      = p.get("status", "unknown")
        model_used  = p.get("model_used", "")
        duration_s  = p.get("duration_seconds") or p.get("duration", 8)
        clips_count = p.get("clips_count", 1)
        stitched    = p.get("stitched", False)

        if status not in ("completed", "partial"):
            prompt_breakdowns.append({
                "prompt_index": i + 1,
                "status":       status,
                "cost_usd":     0.0,
                "cost_inr":     0.0,
                "note":         "failed — not billed",
            })
            continue

        # Cost = per-second rate × total seconds generated
        # For stitched clips: billed per clip (each 8s), not per stitched total
        clip_duration_s = 8  # Veo always generates 8s clips
        cost_usd = calc_clip_cost(model_used, clip_duration_s) * clips_count
        cost_inr = cost_usd * inr_rate
        job_usd_total += cost_usd

        prompt_breakdowns.append({
            "prompt_index": i + 1,
            "status":       status,
            "model":        model_used or "unknown",
            "duration_s":   duration_s,
            "clips":        clips_count,
            "stitched":     stitched,
            "rate_usd_s":   usd_per_second(model_used),
            "cost_usd":     round(cost_usd, 4),
            "cost_inr":     round(cost_inr, 2),
        })

    # ── Decomposer cost (Nova 2 Lite + DeepSeek R1 if fallback) ─────────────────
    # Each multi-clip prompt (n_clips > 1) calls Nova 2 Lite once.
    # If Nova fails, DeepSeek R1 is called as well.
    # Approximate: count prompts with clips_count > 1 as needing decomposition.
    decomp_prompts = sum(
        1 for p in prompt_breakdowns
        if p.get("clips", 1) > 1
    )
    nova_cost_usd     = decomp_prompts * (
        (DECOMP_INPUT_TOKENS  / 1000 * NOVA_INPUT_PER_1K) +
        (DECOMP_OUTPUT_TOKENS / 1000 * NOVA_OUTPUT_PER_1K)
    )
    # Conservative: assume DeepSeek was NOT called unless job used deterministic
    # fallback (we can't tell from the API response, so show as a separate line)
    deepseek_cost_usd = decomp_prompts * (
        (DECOMP_INPUT_TOKENS  / 1000 * DEEPSEEK_INPUT_PER_1K) +
        (DECOMP_OUTPUT_TOKENS / 1000 * DEEPSEEK_OUTPUT_PER_1K)
    )

    grand_usd = job_usd_total + nova_cost_usd
    return {
        "job_id":                   job_id,
        "filename":                 filename,
        "status":                   summary.get("status", "unknown"),
        "total_prompts":            len(prompts),
        "prompts":                  prompt_breakdowns,
        "veo_cost_usd":             round(job_usd_total, 4),
        "veo_cost_inr":             round(job_usd_total * inr_rate, 2),
        "nova_decomp_cost_usd":     round(nova_cost_usd, 6),
        "nova_decomp_cost_inr":     round(nova_cost_usd * inr_rate, 4),
        "deepseek_decomp_cost_usd": round(deepseek_cost_usd, 6),
        "deepseek_decomp_cost_inr": round(deepseek_cost_usd * inr_rate, 4),
        "total_cost_usd":           round(grand_usd, 4),
        "total_cost_inr":           round(grand_usd * inr_rate, 2),
        "note": "DeepSeek cost shown separately — only billed if Nova 2 Lite failed",
    }


# ── Fetch from API ────────────────────────────────────────────────────────────
def fetch_all_jobs() -> list[dict]:
    try:
        r = requests.get(f"{API_BASE}/api/jobs", timeout=10)
        r.raise_for_status()
        return r.json().get("jobs", [])
    except Exception as e:
        print(f"[ERROR] Cannot reach API at {API_BASE}: {e}")
        sys.exit(1)


def fetch_job(job_id: str) -> dict:
    try:
        r = requests.get(f"{API_BASE}/api/jobs/{job_id}", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[ERROR] Cannot fetch job {job_id}: {e}")
        sys.exit(1)


# ── Display ───────────────────────────────────────────────────────────────────
def print_job_report(breakdown: dict, inr_rate: float, rate_source: str):
    sep = "─" * 72
    print(f"\n{'═' * 72}")
    print(f"  JOB: {breakdown['job_id']}")
    print(f"  File: {breakdown['filename'] or '(no file)'}")
    print(f"  Status: {breakdown['status']}")
    print(f"  INR rate: ₹{inr_rate:.2f} / USD  [{rate_source}]")
    print(sep)

    for p in breakdown["prompts"]:
        idx = p["prompt_index"]
        if p["status"] not in ("completed", "partial"):
            print(f"  Prompt {idx:>2}  ✗ {p['status']:<12}  — not billed")
            continue

        clips   = p["clips"]
        model   = p.get("model", "")
        model_s = "primary" if "fast" not in model else "fast"
        rate    = p.get("rate_usd_s", DEFAULT_RATE)
        stitch  = "stitched" if p.get("stitched") else "single"

        print(
            f"  Prompt {idx:>2}  ✓ {stitch:<8}  "
            f"{clips} clip(s) × 8s × ${rate}/s  "
            f"= ${p['cost_usd']:.2f}  /  ₹{p['cost_inr']:.0f}  "
            f"[{model_s}]"
        )

    print(sep)
    veo_usd   = breakdown["veo_cost_usd"]
    nova_usd  = breakdown["nova_decomp_cost_usd"]
    ds_usd    = breakdown["deepseek_decomp_cost_usd"]
    tot_usd   = breakdown["total_cost_usd"]
    inr_r     = inr_rate
    print(f"  Veo generation        ${veo_usd:.4f}   /   ₹{veo_usd * inr_r:.2f}")
    print(f"  Nova 2 Lite (decomp)  ${nova_usd:.6f} /   ₹{nova_usd * inr_r:.4f}")
    print(f"  DeepSeek R1 (if used) ${ds_usd:.6f} /   ₹{ds_usd * inr_r:.4f}  ← only if Nova failed")
    print(sep)
    print(
        f"  TOTAL (Veo + Nova)  {breakdown['total_prompts']} prompts   "
        f"${tot_usd:.4f}   /   "
        f"₹{breakdown['total_cost_inr']:.2f}"
    )
    print(f"{'═' * 72}\n")


def print_summary(breakdowns: list[dict], inr_rate: float, rate_source: str):
    grand_usd = sum(b["total_cost_usd"] for b in breakdowns)
    grand_inr = sum(b["total_cost_inr"] for b in breakdowns)
    clips_total = sum(
        sum(p.get("clips", 0) for p in b["prompts"] if p["status"] in ("completed","partial"))
        for b in breakdowns
    )
    print(f"{'═' * 72}")
    print(f"  GRAND TOTAL — {len(breakdowns)} job(s)")
    print(f"  INR rate: ₹{inr_rate:.2f} / USD  [{rate_source}]")
    print(f"  Total clips generated: {clips_total}")
    print(f"  Total cost: ${grand_usd:.4f}  /  ₹{grand_inr:.2f}")
    print(f"{'═' * 72}\n")

    print("  Cost reference table (at current rate):")
    print(f"  {'Item':<40} {'USD':>8}  {'INR':>10}")
    print(f"  {'─'*40} {'─'*8}  {'─'*10}")
    rows = [
        ("1 clip × 8s  (Veo 3.0 primary)",       0.40 * 8,  0.40 * 8 * inr_rate),
        ("1 clip × 8s  (Veo 3.0 Fast fallback)",  0.15 * 8,  0.15 * 8 * inr_rate),
        ("1 ad × 32s   (4 clips, all primary)",   0.40 * 32, 0.40 * 32 * inr_rate),
        ("1 ad × 32s   (4 clips, all fast)",       0.15 * 32, 0.15 * 32 * inr_rate),
        ("5 ads × 32s  (all primary)",             0.40 * 160, 0.40 * 160 * inr_rate),
        ("5 ads × 32s  (all fast)",                0.15 * 160, 0.15 * 160 * inr_rate),
    ]
    for label, usd, inr in rows:
        print(f"  {label:<40} ${usd:>7.2f}  ₹{inr:>9.2f}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Veo cost tracker")
    parser.add_argument("--job",     help="Specific job ID to analyse")
    parser.add_argument("--rate",    type=float, help="Override INR rate (e.g. 92.5)")
    parser.add_argument("--json",    action="store_true", help="Output raw JSON")
    parser.add_argument("--offline", action="store_true",
                        help="Read from local decomposition JSONs (no API needed)")
    args = parser.parse_args()

    inr_rate, rate_source = get_inr_rate(args.rate)

    # ── Offline mode: read from local decomposition JSONs ─────────────────────
    if args.offline:
        print("[OFFLINE] Reading from local decomposition files — no API needed")
        offline_jobs = load_offline_jobs()
        if not offline_jobs:
            print("[OFFLINE] No job data found on disk.")
            print("  Run at least one generation job first.")
            return
        breakdowns = []
        for job_data in offline_jobs:
            if args.job and job_data["job_id"] != args.job:
                continue
            breakdown = analyse_job(job_data, inr_rate)
            if args.json:
                pass
            else:
                print_job_report(breakdown, inr_rate, rate_source)
            breakdowns.append(breakdown)
        if args.json:
            print(json.dumps(breakdowns, indent=2))
        else:
            print_summary(breakdowns, inr_rate, rate_source)
        return

    # ── Online mode: read from live API ───────────────────────────────────────
    if args.job:
        job_data  = fetch_job(args.job)
        breakdown = analyse_job(job_data, inr_rate)
        if args.json:
            print(json.dumps(breakdown, indent=2))
        else:
            print_job_report(breakdown, inr_rate, rate_source)
            print_summary([breakdown], inr_rate, rate_source)
    else:
        jobs_list  = fetch_all_jobs()
        if not jobs_list:
            print("No jobs found.")
            return
        breakdowns = []
        for j in jobs_list:
            job_data  = fetch_job(j["job_id"])
            breakdown = analyse_job(job_data, inr_rate)
            if args.json:
                pass
            else:
                print_job_report(breakdown, inr_rate, rate_source)
            breakdowns.append(breakdown)
        if args.json:
            print(json.dumps(breakdowns, indent=2))
        else:
            print_summary(breakdowns, inr_rate, rate_source)


if __name__ == "__main__":
    main()
