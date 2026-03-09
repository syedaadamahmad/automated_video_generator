"""
Prompt Decomposer
Splits a master video prompt into N distinct, sequentially flowing sub-prompts
for multi-clip stitching.

Fallback chain (in order):
  1. Amazon Nova 2 Lite via Bedrock  (primary — cross-region inference profile)
  2. DeepSeek R1 via Bedrock         (secondary — system-defined cross-region profile)
  3. Deterministic phase templates   (tertiary — always succeeds)

Uses the Bedrock CONVERSE API for all models.

Why converse() over invoke_model():
  invoke_model() requires a different request body schema per model family
  (Nova, Anthropic, DeepSeek all differ). converse() is AWS's unified API —
  one schema, one response shape, works for all Bedrock models including
  cross-region inference profiles. Eliminates per-family branching entirely.
"""

import json
import logging
import math
import re
from typing import List, Optional, Tuple

import boto3

logger = logging.getLogger("DECOMPOSER")

# ── Bedrock model / inference profile IDs ─────────────────────────────────────
MODEL_NOVA_LITE = (
    "arn:aws:bedrock:us-east-1:148981340030:"
    "inference-profile/us.amazon.nova-2-lite-v1:0"
)
MODEL_DEEPSEEK = "us.deepseek.r1-v1:0"
MODEL_HAIKU    = MODEL_NOVA_LITE  # backwards-compat alias

# ── Scene phase templates (deterministic fallback) ────────────────────────────
_PHASE_LABELS = [
    "Opening establishing shot",
    "Rising action",
    "Mid-scene development",
    "Climactic moment",
    "Resolution",
    "Closing wide shot",
    "Epilogue sequence",
    "Final frame",
]

_TRANSITION_CUES = [
    "Camera slowly pushes in.",
    "Camera pulls back to reveal.",
    "Angle shifts to a lateral tracking shot.",
    "Cut to close-up detail.",
    "Wide aerial view.",
    "Low ground-level perspective.",
    "Slow motion drift.",
    "Static locked-off frame.",
]

# ── System prompt template ────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are a professional video director and cinematographer.
Your task is to split a master video prompt into exactly {n} sequential sub-prompts
that, when generated as separate video clips and stitched together, produce one
seamless, flowing video of the intended scene.

Rules (strictly enforced):
1. Each sub-prompt must describe a VISUALLY DISTINCT phase of the scene.
2. Sub-prompts must flow CONTINUOUSLY — clip N+1 picks up where clip N ends.
3. Maintain CONSISTENT: subject identity, lighting, color palette, style, mood.
4. NEVER repeat the same scene, angle, or action from a previous clip.
5. Each sub-prompt is self-contained.
6. Include implicit camera direction to guide visual continuity.
7. Return ONLY a valid JSON array of exactly {n} strings. No commentary. No markdown.
   Example: ["clip 1 description", "clip 2 description"]

Platform: {platform}
Total duration: {total_duration}s across {n} clips ({clip_duration_str})
Master prompt: {master_prompt}"""


class PromptDecomposer:
    """
    Decomposes a master video prompt into N distinct sub-prompts.

    Uses the Bedrock converse() API — one interface for all models.

    Fallback chain:
      Primary:   Amazon Nova 2 Lite (account inference profile ARN)
      Secondary: DeepSeek R1        (system cross-region profile: us.deepseek.r1-v1:0)
      Tertiary:  Deterministic phase-based decomposition (always succeeds)
    """

    def __init__(
        self,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region: str = "us-east-1",
        model_primary: str = MODEL_NOVA_LITE,
        model_secondary: str = MODEL_DEEPSEEK,
    ):
        self.region          = region
        self.model_primary   = model_primary
        self.model_secondary = model_secondary
        self._bedrock_client: Optional[boto3.client] = None

        if not aws_access_key_id or not aws_secret_access_key:
            logger.warning("[DECOMPOSER] No AWS credentials — deterministic fallback only")
            return

        try:
            self._bedrock_client = boto3.client(
                "bedrock-runtime",
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=region,
            )
            logger.info("[DECOMPOSER] Bedrock client initialized (converse API)")
            logger.info(f"   Primary:   {model_primary}")
            logger.info(f"   Secondary: {model_secondary}")
            logger.info(f"   Tertiary:  deterministic phase templates")
        except Exception as e:
            logger.error(f"[DECOMPOSER] Bedrock client failed: {e} — deterministic fallback only")
            self._bedrock_client = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def decompose(
        self,
        master_prompt: str,
        n_clips: int,
        clip_durations: List[int],
        platform: str,
    ) -> Tuple[List[str], str]:
        """
        Synchronous decomposition. Returns (sub_prompts, model_source).
        Guaranteed to return exactly n_clips strings. Never raises.
        """
        if n_clips == 1:
            logger.info("[DECOMPOSER] Single clip — returning master prompt unchanged")
            return [master_prompt], "passthrough"

        logger.info(f"[DECOMPOSER] Decomposing into {n_clips} clips")
        logger.info(f"   Master:   '{master_prompt[:80]}'")
        logger.info(f"   Platform: {platform}")
        logger.info(f"   Durations: {clip_durations}")

        if self._bedrock_client:
            # Primary: Nova 2 Lite
            result, source = self._try_model(
                model_id=self.model_primary, model_name="Nova 2 Lite",
                master_prompt=master_prompt, n_clips=n_clips,
                clip_durations=clip_durations, platform=platform,
            )
            if result:
                return result, source

            # Secondary: DeepSeek R1
            result, source = self._try_model(
                model_id=self.model_secondary, model_name="DeepSeek R1",
                master_prompt=master_prompt, n_clips=n_clips,
                clip_durations=clip_durations, platform=platform,
            )
            if result:
                return result, source
        else:
            logger.warning("[DECOMPOSER] No Bedrock client — skipping LLM path")

        # Tertiary: deterministic
        logger.warning("[DECOMPOSER] All LLM paths failed — using deterministic fallback")
        fallback = self._phase_fallback(master_prompt, n_clips, clip_durations)
        logger.info(f"[DECOMPOSER] Tertiary (deterministic) complete ({n_clips} clips)")
        for i, sp in enumerate(fallback):
            logger.info(f"   Clip {i+1}: '{sp[:60]}...'")
        return fallback, "deterministic"

    # ── Model invocation ───────────────────────────────────────────────────────

    def _try_model(
        self,
        model_id: str, model_name: str,
        master_prompt: str, n_clips: int,
        clip_durations: List[int], platform: str,
    ) -> Tuple[Optional[List[str]], str]:
        """Attempt decomposition. Returns (sub_prompts, source) or (None, source)."""
        logger.info(f"[DECOMPOSER] Trying {model_name} ({model_id})")
        try:
            sub_prompts = self._llm_decompose(
                model_id=model_id, master_prompt=master_prompt,
                n_clips=n_clips, clip_durations=clip_durations, platform=platform,
            )
            if sub_prompts and len(sub_prompts) == n_clips:
                logger.info(f"[DECOMPOSER] {model_name} succeeded ({n_clips} clips)")
                for i, sp in enumerate(sub_prompts):
                    logger.info(f"   Clip {i+1}: '{sp[:60]}...'")
                return sub_prompts, model_name

            count = len(sub_prompts) if sub_prompts else 0
            logger.warning(f"[DECOMPOSER] {model_name} returned {count}/{n_clips} clips")
            return None, model_name
        except Exception as e:
            logger.error(f"[DECOMPOSER] {model_name} failed: {e}")
            return None, model_name

    def _llm_decompose(
        self,
        model_id: str, master_prompt: str,
        n_clips: int, clip_durations: List[int], platform: str,
    ) -> Optional[List[str]]:
        """Call Bedrock converse(), extract text, parse JSON array."""
        total_duration    = sum(clip_durations)
        clip_duration_str = " + ".join(f"{d}s" for d in clip_durations)

        user_content = _SYSTEM_PROMPT.format(
            n=n_clips, platform=platform, total_duration=total_duration,
            clip_duration_str=clip_duration_str, master_prompt=master_prompt,
        )

        raw_text = self._converse(model_id, user_content)
        logger.info(f"[DECOMPOSER] Raw response ({model_id}): '{raw_text[:200]}'")

        sub_prompts = self._parse_json_array(raw_text)
        if sub_prompts is None:
            return None

        if len(sub_prompts) != n_clips:
            logger.warning(
                f"[DECOMPOSER] Count mismatch: expected {n_clips}, got {len(sub_prompts)}"
            )
            sub_prompts = self._repair_count(sub_prompts, n_clips, master_prompt)

        return sub_prompts

    def _converse(self, model_id: str, user_text: str) -> str:
        """
        Call Bedrock converse() — single unified API for all model families.

        Response content block layout varies by model:
          Nova / Claude:  content = [{"text": "<answer>"}]
          DeepSeek R1:    content = [
                            {"reasoningContent": {"reasoningText": {"text": "<CoT>"}}},
                            {"text": "<answer>"}
                          ]

        Must iterate content blocks — content[0]["text"] silently fails for
        DeepSeek R1 because block 0 is chain-of-thought, not the answer.
        """
        logger.info(f"[DECOMPOSER] converse() -> {model_id}")
        response = self._bedrock_client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.7},
        )

        content_blocks = (
            response.get("output", {})
                    .get("message", {})
                    .get("content", [])
        )
        logger.debug(f"[DECOMPOSER] {model_id}: {len(content_blocks)} content block(s)")
        return self._extract_text_blocks(content_blocks, model_id)

    def _extract_text_blocks(self, content_blocks: list, model_id: str) -> str:
        """
        Iterate converse() content blocks and return the first direct "text" value.

        Normal layout:
          Nova / Claude : [{"text": "<answer>"}]
          DeepSeek R1   : [{"reasoningContent": ...}, {"text": "<answer>"}]

        Edge case — CoT-only response (DeepSeek R1 with low maxTokens):
          DeepSeek R1 is a reasoning model. It allocates its token budget to
          chain-of-thought first. When maxTokens is too small it exhausts the
          budget during CoT and never emits the answer block, leaving only:
            [{"reasoningContent": {"reasoningText": {"text": "<CoT>"}}}]

          In production this is avoided by using maxTokens=1024. As a safety
          net, if no text block is found, fall back to the last reasoningText
          content — DeepSeek's CoT typically ends with the intended answer.
        """
        cot_fallback = ""

        for i, block in enumerate(content_blocks):
            if "text" in block:
                text = block["text"].strip()
                logger.debug(f"[DECOMPOSER] Text at block {i}: {repr(text[:60])}")
                return text

            if "reasoningContent" in block:
                cot_text = (
                    block.get("reasoningContent", {})
                         .get("reasoningText", {})
                         .get("text", "")
                )
                cot_fallback = cot_text  # keep last CoT seen
                logger.debug(
                    f"[DECOMPOSER] Block {i} is reasoningContent "
                    f"({len(cot_text)} chars) — skipping (stored as fallback)"
                )
                continue

            logger.debug(
                f"[DECOMPOSER] Block {i} has unknown keys {list(block.keys())} — skipping"
            )

        # No dedicated text block found — CoT-only response (token budget exhausted)
        if cot_fallback:
            logger.warning(
                f"[DECOMPOSER] No text block in {len(content_blocks)} block(s) for "
                f"{model_id} — using reasoningContent as fallback "
                f"(increase maxTokens if this happens in production)"
            )
            return cot_fallback.strip()

        logger.warning(
            f"[DECOMPOSER] No text or reasoning content in "
            f"{len(content_blocks)} block(s) for {model_id}"
        )
        return ""

    # ── Response parsing ───────────────────────────────────────────────────────

    def _parse_json_array(self, text: str) -> Optional[List[str]]:
        """Extract JSON array from LLM response, handling markdown fences."""
        text  = re.sub(r"```(?:json)?\s*", "", text).strip()
        text  = re.sub(r"```\s*$",         "", text).strip()
        start = text.find("[")
        end   = text.rfind("]")

        if start == -1 or end == -1 or end <= start:
            logger.warning(f"[DECOMPOSER] No JSON array found in: '{text[:100]}'")
            return None

        try:
            parsed = json.loads(text[start: end + 1])
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                return [s.strip() for s in parsed if s.strip()]
            logger.warning("[DECOMPOSER] Parsed JSON is not a list of strings")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"[DECOMPOSER] JSON parse error: {e}")
            return None

    def _repair_count(
        self, sub_prompts: List[str], target: int, master_prompt: str
    ) -> List[str]:
        """Truncate if too many; pad with fallback phases if too few."""
        if len(sub_prompts) > target:
            logger.info(f"[DECOMPOSER] Truncating {len(sub_prompts)} -> {target}")
            return sub_prompts[:target]

        while len(sub_prompts) < target:
            idx   = len(sub_prompts)
            phase = _PHASE_LABELS[idx % len(_PHASE_LABELS)]
            cue   = _TRANSITION_CUES[idx % len(_TRANSITION_CUES)]
            sub_prompts.append(f"{phase}: {master_prompt.strip()}. {cue}")
            logger.info(f"[DECOMPOSER] Padded clip {idx + 1} with fallback phase")

        return sub_prompts

    # ── Deterministic tertiary fallback ───────────────────────────────────────

    def _phase_fallback(
        self, master_prompt: str, n_clips: int, clip_durations: List[int],
    ) -> List[str]:
        """Deterministic scene-phase decomposition — no LLM required."""
        base = master_prompt.strip().rstrip(".")

        if n_clips == 2:
            return [
                f"Opening shot: {base}. Wide establishing angle, scene beginning.",
                f"Closing shot: {base}. Scene reaches conclusion, camera pulls back to reveal full scope.",
            ]

        if n_clips == 3:
            return [
                f"Opening: {base}. Wide establishing shot, scene begins.",
                f"Mid-scene: {base}. Camera moves closer, action develops, dynamic angle.",
                f"Closing: {base}. Final moments, scene resolves, slow pull-back.",
            ]

        sub_prompts = []
        for i in range(n_clips):
            phase = _PHASE_LABELS[i % len(_PHASE_LABELS)]
            cue   = _TRANSITION_CUES[i % len(_TRANSITION_CUES)]
            if i == 0:
                sp = f"Opening -- {base}. Wide establishing angle, scene begins. {cue}"
            elif i == n_clips - 1:
                sp = f"Closing -- {base}. Final moments, scene resolves. {cue}"
            else:
                progress = int((i / (n_clips - 1)) * 100)
                sp = (
                    f"Sequence {i+1}/{n_clips} ({progress}% through) -- {base}. "
                    f"Scene progresses, visual evolution continues. {cue}"
                )
            sub_prompts.append(sp)

        return sub_prompts


# ── Clip math utilities ────────────────────────────────────────────────────────

def compute_veo_clips(total_duration: int) -> List[int]:
    """Veo stitching: N x 8s clips."""
    n_clips = math.ceil(total_duration / 8)
    return [8] * n_clips