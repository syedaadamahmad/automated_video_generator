"""
veo_refiner.py — Prompt Refinement Pipeline
════════════════════════════════════════════

Two modes (set REFINER_MODE=1 or 2 in veo.env, default=1):

Mode 1 (default — heavy chain):
  Refine step : Nova 2 Lite → DeepSeek → deterministic
  Outputs     : refined_prompt + structured_fields + warnings
  Decompose   : runs separately on approve via PromptDecomposer

Mode 2 (lightweight single-call):
  Refine+decompose : one model, one LLM call, faster/cheaper
  Outputs          : refined_prompt + structured_fields + clip decomposition
  Approve          : skips decomposer — uses clips from this step directly

Mythology auto-detection:
  Any prompt containing Indian deity/mythology keywords automatically
  receives the INDIAN MYTHOLOGY VISUAL STYLE LOCK injected into the
  refined prompt. User can see and edit it in the structured mythology_notes field.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import boto3

logger = logging.getLogger("VEO_REFINER")

# ── Bedrock model IDs ──────────────────────────────────────────────────────────
_MODEL_NOVA     = os.getenv(
    "NOVA_MODEL_ID",
    "arn:aws:bedrock:us-east-1:148981340030:"
    "inference-profile/us.amazon.nova-2-lite-v1:0"
)
_MODEL_DEEPSEEK = os.getenv("DEEPSEEK_MODEL_ID", "us.deepseek.r1-v1:0")

# ── Mythology detection keywords ───────────────────────────────────────────────
_MYTHOLOGY_KEYWORDS = {
    # Deities
    "vishnu", "shiva", "brahma", "indra", "lakshmi", "saraswati", "durga",
    "ganesha", "krishna", "rama", "hanuman", "arjuna", "kali", "parvati",
    "kartikeya", "ayyappa", "murugan", "surya", "chandra", "varuna", "agni",
    # Mythology terms
    "rahu", "ketu", "asura", "deva", "devata", "rakshasa", "yaksha",
    "apsara", "gandharva", "naga", "garuda", "vahana", "avatar",
    # Events / concepts
    "samudra manthan", "amrit", "amrita", "sudarshan", "chakra", "trishul",
    "mahabharata", "ramayana", "puranas", "vedic", "vedas", "sanskrit",
    # Descriptors
    "hindu", "hinduism", "mythological", "mythology", "ancient india",
    "celestial realm", "svarga", "swarga", "triloka", "brahmaloka",
    "vaikuntha", "kailash", "mandir", "gopuram", "mandapa",
}

# ── Mythology visual style lock ────────────────────────────────────────────────
MYTHOLOGY_STYLE_LOCK = (
    "INDIAN MYTHOLOGY VISUAL STYLE LOCK — mandatory for all clips: "
    "Aesthetic reference: Tanjore painting, Nataraja bronze sculpture, Mughal miniature art, "
    "Mysore painting tradition — NOT Greek, Norse, or European fantasy. "
    "Architecture: carved sandstone temples, gopuram towers, mandapa pillars — "
    "NOT cathedrals, castles, or Middle Earth structures. "
    "Costume: silk dhoti, angavastra, mukut crowns, temple jewellery, chandrahara necklaces — "
    "NOT Roman togas, Western armour, or medieval European clothing. "
    "Divine beings: jewel-toned skin (deep blue, burnished gold, forest green), "
    "multiple arms where appropriate, vahanas (divine mounts) — "
    "NOT glowing white angelic Western figures. "
    "Colour palette: saffron, vermillion, deep teal, burnished gold, lotus pink — "
    "NOT desaturated grey-blue Western epic palette. "
    "Lighting: warm tropical golden light, oil lamp glow, fire torches, "
    "sacred fire (agni) illumination — NOT cold blue moonlight or industrial fog. "
    "Atmosphere: tropical humid haze, monsoon clouds, sacred smoke, marigold pollen — "
    "NOT frost, snow, or temperate forest."
)

# ── Refiner system prompts ─────────────────────────────────────────────────────

_REFINER_MODE1_PROMPT = """You are a Veo video prompt refinement expert. Your job is to improve a raw user video prompt for cinematic quality and extract structured editing fields.

TASK: Given a raw prompt, return ONLY valid JSON — no commentary, no markdown fences.

MYTHOLOGY DETECTION: If the prompt contains any Indian deity, mythology concept, or Sanskrit term, set mythology_detected=true and include the mythology_notes field.

IMPROVEMENTS TO MAKE:
- Add specific camera movement language (dolly, push-in, pull-back, arc shot, static, aerial)
- Add lighting quality (volumetric, HDR, god rays, rim light, practical sources)
- Add texture and atmosphere (film grain, particle effects, fog, depth of field)
- Add emotional specificity (facial expression, body language, environmental storytelling)
- Fix vague language ("beautiful" → "warm golden bokeh", "dramatic" → "slow-motion arc shot with motion blur")
- Keep narration lines EXACTLY as written — do not modify their content
- If mythology detected, add the mythology_notes field with visual style constraints

WARNINGS to generate:
- If narration lines > n_clips: "Narration lines ({count}) exceed clip count ({n_clips}) — some may be truncated"
- If prompt contains character names Veo may not recognise: "Character name '{name}' may render inconsistently — consider visual descriptions"
- If prompt is under 50 words: "Prompt is very short — more visual detail will improve consistency"

OUTPUT JSON shape (return EXACTLY this structure):
{
  "refined_prompt": "<improved full prompt as single string>",
  "mythology_detected": <true|false>,
  "warnings": ["<warning 1>", "..."],
  "structured": {
    "scene": "<scene setting, atmosphere, time of day, colour palette>",
    "characters": "<character descriptions — gender, age, ethnicity, hair, key clothing>",
    "camera": "<camera movements, lens type, depth of field, shot types>",
    "narration_lines": ["<line 1>", "<line 2>", "..."],
    "lighting": "<lighting setup, quality, sources, HDR notes>",
    "mythology_notes": "<Indian mythology visual style constraints if mythology detected, else empty string>"
  }
}"""

_REFINER_MODE2_PROMPT = """You are a Veo video prompt refinement and decomposition expert. In ONE call, you must refine a raw user prompt AND break it into exactly {n} sequential Veo-ready clip prompts.

TASK: Return ONLY valid JSON — no commentary, no markdown fences.

STEP 1 — REFINE:
- Add cinematic camera language, lighting, texture, atmosphere
- Keep narration lines exactly as written
- If mythology detected (Indian deities, Sanskrit terms, Hindu concepts) → inject mythology style lock

STEP 2 — DECOMPOSE into {n} clips:
- Each clip prompt must be fully self-contained (embeds scene + character anchors)
- Distribute narration lines evenly across clips (ceil(total_lines / {n}) lines per clip)
- Each clip opens from the previous clip's end_state
- Final clip must signal visual and audio closure

MYTHOLOGY STYLE LOCK (inject when detected):
"INDIAN MYTHOLOGY VISUAL STYLE LOCK: Tanjore painting aesthetic, sandstone temple architecture, silk dhoti and mukut costume, jewel-toned divine skin, saffron/vermillion/gold palette, tropical warm lighting — NOT Western fantasy."

OUTPUT JSON (exactly this structure):
{
  "refined_prompt": "<improved master prompt>",
  "mythology_detected": <true|false>,
  "warnings": ["..."],
  "structured": {
    "scene": "...",
    "characters": "...",
    "camera": "...",
    "narration_lines": ["..."],
    "lighting": "...",
    "mythology_notes": "..."
  },
  "clips": [
    {
      "clip": 1,
      "duration_s": <int>,
      "start_s": 0,
      "end_s": <duration_s>,
      "end_state": "<last visible frame>",
      "prompt": "<full self-contained Veo prompt for this clip>"
    }
  ]
}

Platform: {platform}
Total duration: {total_duration}s | {n} clips | durations: {clip_duration_str}
Raw user prompt: {master_prompt}"""


class PromptRefiner:
    """
    Refines raw user prompts before decomposition and generation.

    Mode 1: refine only (returns refined prompt + structured fields)
    Mode 2: refine + decompose in one shot (returns clip array too)
    """

    def __init__(
        self,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region: str = "us-east-1",
        mode: int = 1,
        primary_model: str = _MODEL_NOVA,
        secondary_model: str = _MODEL_DEEPSEEK,
    ):
        self.mode             = mode
        self.primary_model    = primary_model
        self.secondary_model  = secondary_model
        self._client: Optional[Any] = None

        if not aws_access_key_id or not aws_secret_access_key:
            logger.warning("[REFINER] No AWS credentials — deterministic fallback only")
            return

        try:
            self._client = boto3.client(
                "bedrock-runtime",
                aws_access_key_id     = aws_access_key_id,
                aws_secret_access_key = aws_secret_access_key,
                region_name           = region,
            )
            logger.info(
                f"[REFINER] Initialised — mode={mode} "
                f"primary={primary_model.split('/')[-1]}"
            )
        except Exception as e:
            logger.error(f"[REFINER] Bedrock client failed: {e}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def refine(
        self,
        raw_prompt:     str,
        n_clips:        int,
        clip_durations: List[int],
        platform:       str = "veo",
    ) -> Dict[str, Any]:
        """
        Refine a single prompt.

        Returns:
          {
            refined_prompt:     str,
            mythology_detected: bool,
            warnings:           List[str],
            structured: {
              scene, characters, camera, narration_lines,
              lighting, mythology_notes
            },
            clips:              List[clip_dict] | []   (Mode 2 only)
          }
        """
        mythology = self._detect_mythology(raw_prompt)
        logger.info(
            f"[REFINER] mode={self.mode} mythology={mythology} "
            f"prompt='{raw_prompt[:60]}...'"
        )

        result = self._call_llm(raw_prompt, n_clips, clip_durations, platform)

        # Inject mythology style lock into refined prompt if detected
        if mythology and MYTHOLOGY_STYLE_LOCK not in result.get("refined_prompt", ""):
            result["refined_prompt"] = (
                MYTHOLOGY_STYLE_LOCK + " " + result.get("refined_prompt", raw_prompt)
            )
            if result.get("structured", {}).get("mythology_notes", "") == "":
                result.setdefault("structured", {})["mythology_notes"] = MYTHOLOGY_STYLE_LOCK

        result["mythology_detected"] = mythology

        # Compute timestamps for overlay display
        result["clips"] = self._build_timestamps(
            result.get("clips", []), clip_durations, n_clips
        )

        return result

    @staticmethod
    def detect_mythology(prompt: str) -> bool:
        return PromptRefiner._detect_mythology_static(prompt)

    # ── Mythology detection ────────────────────────────────────────────────────

    @staticmethod
    def _detect_mythology(prompt: str) -> bool:
        return PromptRefiner._detect_mythology_static(prompt)

    @staticmethod
    def _detect_mythology_static(prompt: str) -> bool:
        lower = prompt.lower()
        return any(kw in lower for kw in _MYTHOLOGY_KEYWORDS)

    # ── LLM calls ─────────────────────────────────────────────────────────────

    def _call_llm(
        self,
        prompt: str,
        n_clips: int,
        clip_durations: List[int],
        platform: str,
    ) -> Dict[str, Any]:
        if self._client is None:
            return self._deterministic_refine(prompt, n_clips, clip_durations)

        total    = sum(clip_durations)
        dur_str  = " + ".join(f"{d}s" for d in clip_durations)

        if self.mode == 2:
            system_text = _REFINER_MODE2_PROMPT.format(
                n               = n_clips,
                platform        = platform,
                total_duration  = total,
                clip_duration_str = dur_str,
                master_prompt   = prompt,
            )
        else:
            system_text = _REFINER_MODE1_PROMPT

        user_text = (
            f"Raw prompt:\n{prompt}"
            if self.mode == 1
            else system_text   # Mode 2: everything in one message
        )
        if self.mode == 1:
            user_text = system_text + f"\n\nRaw prompt to refine:\n{prompt}"

        # Try primary model, then secondary
        for model_id in (self.primary_model, self.secondary_model):
            try:
                raw, _, _ = self._converse(model_id, user_text)
                parsed = self._parse_json(raw)
                if parsed and "refined_prompt" in parsed:
                    logger.info(f"[REFINER] {model_id.split('/')[-1]} succeeded")
                    return self._normalise(parsed, prompt, n_clips, clip_durations)
                logger.warning(f"[REFINER] {model_id.split('/')[-1]} returned unparseable response")
            except Exception as e:
                logger.error(f"[REFINER] {model_id.split('/')[-1]} failed: {e}")

        logger.warning("[REFINER] All LLM paths failed — deterministic fallback")
        return self._deterministic_refine(prompt, n_clips, clip_durations)

    def _converse(self, model_id: str, user_text: str) -> Tuple[str, int, int]:
        response = self._client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.5},
        )
        usage  = response.get("usage", {})
        blocks = (
            response.get("output", {}).get("message", {}).get("content", [])
        )
        text = ""
        for block in blocks:
            if "text" in block:
                text = block["text"].strip()
                break
            if "reasoningContent" in block:
                # DeepSeek R1 CoT fallback
                text = block["reasoningContent"].get("reasoningText", {}).get("text", "")
        return text, usage.get("inputTokens", 0), usage.get("outputTokens", 0)

    # ── Response parsing ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict]:
        text  = re.sub(r"```(?:json)?\s*", "", text).strip()
        text  = re.sub(r"```\s*$",         "", text).strip()
        start = text.find("{")
        end   = text.rfind("}")
        if start == -1 or end == -1:
            return None
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None

    def _normalise(
        self,
        parsed: Dict,
        original: str,
        n_clips: int,
        clip_durations: List[int],
    ) -> Dict[str, Any]:
        """Ensure returned dict has all expected keys with safe defaults."""
        structured = parsed.get("structured", {})
        return {
            "refined_prompt":     parsed.get("refined_prompt", original),
            "mythology_detected": parsed.get("mythology_detected", False),
            "warnings":           parsed.get("warnings", []),
            "structured": {
                "scene":           structured.get("scene", ""),
                "characters":      structured.get("characters", ""),
                "camera":          structured.get("camera", ""),
                "narration_lines": structured.get("narration_lines", []),
                "lighting":        structured.get("lighting", ""),
                "mythology_notes": structured.get("mythology_notes", ""),
            },
            "clips": parsed.get("clips", []),   # populated in Mode 2
        }

    # ── Timestamp builder ──────────────────────────────────────────────────────

    @staticmethod
    def _build_timestamps(
        clips_from_llm: List[Dict],
        clip_durations:  List[int],
        n_clips:         int,
    ) -> List[Dict[str, Any]]:
        """
        Build clip timestamp objects for overlay display.
        If Mode 2 already returned clips, enrich them.
        If Mode 1 (no clips), build from durations.
        """
        result = []
        offset = 0
        for i in range(n_clips):
            dur = clip_durations[i] if i < len(clip_durations) else 8
            if i < len(clips_from_llm):
                clip = dict(clips_from_llm[i])
                clip["start_s"] = offset
                clip["end_s"]   = offset + dur
                clip["duration_s"] = dur
                clip["label"]   = f"Clip {i + 1} · {offset}–{offset + dur}s"
            else:
                clip = {
                    "clip":       i + 1,
                    "duration_s": dur,
                    "start_s":    offset,
                    "end_s":      offset + dur,
                    "end_state":  "",
                    "prompt":     "",
                    "label":      f"Clip {i + 1} · {offset}–{offset + dur}s",
                }
            result.append(clip)
            offset += dur
        return result

    # ── Deterministic fallback ─────────────────────────────────────────────────

    def _deterministic_refine(
        self,
        prompt: str,
        n_clips: int,
        clip_durations: List[int],
    ) -> Dict[str, Any]:
        """No LLM available — extract what we can deterministically."""
        narration_pattern = re.compile(
            r'(?:(?:[A-Za-z ]+)?Narration\s*[:\s]+)?[\u201c"]([^\u201d"]+)[\u201d"]',
            re.IGNORECASE,
        )
        narration_lines = narration_pattern.findall(prompt)

        warnings = []
        if narration_lines and len(narration_lines) > n_clips:
            warnings.append(
                f"Narration lines ({len(narration_lines)}) exceed clip count ({n_clips})"
            )

        mythology = self._detect_mythology(prompt)
        refined = (
            f"{MYTHOLOGY_STYLE_LOCK} {prompt}" if mythology else prompt
        )

        return {
            "refined_prompt":     refined,
            "mythology_detected": mythology,
            "warnings":           warnings,
            "structured": {
                "scene":           "",
                "characters":      "",
                "camera":          "",
                "narration_lines": narration_lines,
                "lighting":        "",
                "mythology_notes": MYTHOLOGY_STYLE_LOCK if mythology else "",
            },
            "clips": [],
        }