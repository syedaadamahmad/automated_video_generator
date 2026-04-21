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

# ── Static camera directive ──────────────────────────────────────────────────
# Injected into every sub-prompt when the master prompt contains "static".
# Ensures Veo receives an unambiguous locked-camera instruction on every call.
_STATIC_CAMERA_DIRECTIVE = (
    "CAMERA: completely stationary, locked-off tripod frame. "
    "Absolutely no camera movement — no pan, no tilt, no dolly, no zoom, "
    "no handheld shake, no push-in, no pull-back. "
    "The camera does not move for the entire duration of this clip."
)

_STATIC_SYSTEM_ADDENDUM = """
═══ STATIC CAMERA — MANDATORY RULE ═══════════════════════════════════════════
The master prompt specifies a STATIC camera. This overrides all other direction.
- Every clip prompt MUST begin with: "STATIC LOCKED-OFF FRAME. Camera does not move."
- Do NOT suggest any camera motion (no dolly, pan, tilt, zoom, push-in, pull-back).
- The only change between clips is subject action and narrative moment.
- The framing, lens distance, and angle are IDENTICAL across all clips."""

# ── System prompt template ────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are an expert cinematographer decomposing a master video prompt \
into exactly {n} sequential clips that stitch into one seamless video.

═══ STEP 1 — EXTRACT ANCHORS (never change these across clips) ════════════════
SCENE ANCHOR: Extract setting, lighting quality, color palette, time of day.
Keep to 1-2 sentences maximum. Key identifiers only — do NOT write paragraphs.
Bad example: "A modern futuristic classroom filled with glowing AI holograms and machine
  learning neural network graphics floating around. Vibrant colors, high energy..."
Good example: "Futuristic classroom, glowing blue/purple AI holograms, neon-lit desks,
  large windows, daytime."

CHARACTER ANCHOR (only if people are present): Lock gender, approximate age, ethnicity, \
hair style, and ONE key clothing item per person. Maximum 20 words per character. \
Do NOT describe accessories, shoes, build, or posture — these are inferred from context. \
THIS BLOCK IS COPIED VERBATIM INTO EVERY CLIP PROMPT. Keep it SHORT.
Bad example: "Student 1 (foreground): Male, South Indian ethnicity, dark brown hair styled
  in a neat side-part, wearing a crisp light blue button-down shirt, dark blue trousers,
  and black leather shoes; slim build; waist-up, centered frame; standing upright..."
Good example: "Student 1: Indian male ~15, neat dark hair, light blue shirt. Student 2:
  Indian female ~15, black ponytail, turquoise top."

CAMERA ANCHOR: Starting camera position, lens distance (close-up/medium/wide), angle.
One sentence only.

ANCHOR BUDGET: SCENE + CHARACTER + CAMERA anchors combined must be under 150 words.
If you exceed 150 words, cut character descriptions first — remove accessories,
shoes, exact fit details, and posture. Keep gender, age, ethnicity, hair, and
one key clothing item per person.

═══ STEP 2 — DEFINE VISUAL HANDOFFS ══════════════════════════════════════════
For each clip N (except the last), define end_state: a precise single sentence \
describing the LAST VISIBLE FRAME — what the viewer sees as clip N freezes. \
Clip N+1 must open from EXACTLY that visual state.

═══ STEP 3 — WRITE EACH CLIP PROMPT ══════════════════════════════════════════
Rules (strictly enforced):
1. Embed SCENE ANCHOR and CHARACTER ANCHOR verbatim at the start of every prompt.
2. The actual clip action and narration come AFTER the anchors — keep them prominent.
3. Vary ONLY: action progression, camera movement, narrative moment.
4. No new characters. No lighting changes. No setting changes. No costume changes.
5. Clip N+1 opens from clip N's end_state exactly.
6. Each prompt is self-contained and can be sent to a video model independently.
7. Include specific camera movement directions (dolly, pan, tilt, static, push-in, pull-back).

═══ NARRATION RULES (apply when master prompt contains "Narration" text) ═══════
If the master prompt contains narration lines (e.g. Narration "some text"), follow ALL of these:

A. COUNT then DISTRIBUTE. First count the total narration lines in the master prompt.
   Then divide: lines_per_clip = ceil(total_lines / {n}).
   Assign exactly lines_per_clip consecutive lines to each clip in order.
   Example: 4 lines, 2 clips → 2 lines per clip. 4 lines, 4 clips → 1 line per clip.
   3 lines, 2 clips → clip 1 gets lines 1-2, clip 2 gets line 3.
   Do NOT drop any narration lines. Every line must appear in exactly one clip.

B. SELF-CONTAINED narration per clip. Each clip's narration must START and COMPLETE within
   that clip's {clip_duration_str} duration. Never split a sentence across clips.
   A single narration line should fit within 6 seconds of speech (approx 15-20 words max).
   If a narration line is too long for one clip, split it at a natural pause.

C. FINAL CLIP closure. The last clip's prompt MUST signal that the video is ending:
   - The final narration line must be a complete, resolving sentence (not mid-thought).
   - Add to the final clip prompt: "This is the final moment. The narration concludes naturally. Scene and audio resolve to a comfortable close."
   - The visual action in the final clip must reach a resting state (not mid-motion).

D. NON-FINAL CLIPS: Each clip should feel like it could pause naturally — end on a beat, not mid-sentence.

═══ OUTPUT FORMAT ═════════════════════════════════════════════════════════════
Return ONLY a JSON array of exactly {n} objects. No commentary. No markdown fences.
Each object: {{"clip": <int>, "duration_s": <int>, "end_state": "<last frame>", "prompt": "<full self-contained prompt>"}}

Platform: {platform}
Total duration: {total_duration}s | {n} clips | durations: {clip_duration_str}
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

    @staticmethod
    def _extract_narrator(master_prompt: str) -> Optional[str]:
        """
        Extract narrator description from master prompt.

        Matches any of these user-written patterns:
          NARRATOR: calm, warm, Indian-accented female voice
          Indian Accent Narration: ...       (treated as implicit narrator spec)
          NARRATOR VOICE: ...
          VOICE: warm male narrator

        For accent-prefix patterns like "Indian Accent Narration:" we derive
        a narrator description from the prefix itself.
        Returns description string or None if no narrator keyword found.
        """
        import re

        # Explicit NARRATOR: or VOICE: keyword
        m = re.search(
            r'(?:NARRATOR|NARRATOR\s+VOICE|VOICE)\s*:\s*([^\n"]+)',
            master_prompt, re.IGNORECASE
        )
        if m:
            return m.group(1).strip().rstrip('.')

        # Accent-prefix pattern: "X Accent Narration:", "X Accented Voice:", "Indian Voice:"
        # Derive narrator description from the accent prefix
        m = re.search(
            r'([A-Za-z\s]+?(?:Accent|Accented|Voice))\s*(?:Narration|Voice|Narrator)?\s*:',
            master_prompt, re.IGNORECASE
        )
        if m:
            accent = m.group(1).strip()
            return f"{accent} narrator voice, consistent accent and tone throughout"

        return None

    def decompose(
        self,
        master_prompt: str,
        n_clips: int,
        clip_durations: List[int],
        platform: str,
        is_static: bool = False,
        narrator_desc: Optional[str] = None,
    ) -> Tuple[List[str], str, List[dict], dict]:
        """
        Synchronous decomposition. Returns (sub_prompts, model_source, clip_objects, metrics).
        sub_prompts: plain strings for generate_video().
        clip_objects: [{clip, duration_s, end_state, prompt}] for JSON save.
        is_static: when True, every sub-prompt gets a hard camera-lock directive injected.
        narrator: when NARRATOR: keyword found, voice-lock directive injected into every clip.
        Guaranteed to return exactly n_clips strings. Never raises.
        """
        if n_clips == 1:
            logger.info("[DECOMPOSER] Single clip — returning master prompt unchanged")
            prompt = master_prompt
            if is_static:
                prompt = f"STATIC LOCKED-OFF FRAME. Camera does not move. {_STATIC_CAMERA_DIRECTIVE} {prompt}"
                logger.info("[DECOMPOSER] Static camera directive injected into single-clip prompt")
            single_obj = [{"clip": 1, "duration_s": clip_durations[0] if clip_durations else 8, "prompt": prompt, "end_state": ""}]
            return [prompt], "passthrough", single_obj, {
                "input_tokens": 0, "output_tokens": 0,
                "nova_calls": 0, "deepseek_calls": 0, "deterministic": 0,
            }

        logger.info(f"[DECOMPOSER] Decomposing into {n_clips} clips")
        logger.info(f"   Master:   '{master_prompt[:80]}'")
        logger.info(f"   Platform: {platform}")
        logger.info(f"   Durations: {clip_durations}")

        # Track token usage and which models were called
        total_input_tokens  = 0
        total_output_tokens = 0
        nova_calls     = 0
        deepseek_calls = 0
        used_deterministic = 0

        if self._bedrock_client:
            # Primary: Nova 2 Lite
            nova_calls += 1
            result, source, clip_objects = self._try_model(
                model_id=self.model_primary, model_name="Nova 2 Lite",
                master_prompt=master_prompt, n_clips=n_clips,
                clip_durations=clip_durations, platform=platform,
                is_static=is_static,
            )
            total_input_tokens  += self._last_input_tokens
            total_output_tokens += self._last_output_tokens
            if result:
                return result, source, clip_objects, {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "nova_calls": nova_calls,
                    "deepseek_calls": deepseek_calls,
                    "deterministic": 0,
                }

            # Secondary: DeepSeek R1
            deepseek_calls += 1
            result, source, clip_objects = self._try_model(
                model_id=self.model_secondary, model_name="DeepSeek R1",
                master_prompt=master_prompt, n_clips=n_clips,
                clip_durations=clip_durations, platform=platform,
                is_static=is_static,
            )
            total_input_tokens  += self._last_input_tokens
            total_output_tokens += self._last_output_tokens
            if result:
                return result, source, clip_objects, {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "nova_calls": nova_calls,
                    "deepseek_calls": deepseek_calls,
                    "deterministic": 0,
                }
        else:
            logger.warning("[DECOMPOSER] No Bedrock client — skipping LLM path")

        # Tertiary: deterministic
        used_deterministic = 1
        logger.warning("[DECOMPOSER] All LLM paths failed — using deterministic fallback")
        fallback_prompts, fallback_objects = self._phase_fallback(
            master_prompt, n_clips, clip_durations, is_static=is_static
        )
        logger.info(f"[DECOMPOSER] Tertiary (deterministic) complete ({n_clips} clips)")
        for i, sp in enumerate(fallback_prompts):
            logger.info(f"   Clip {i+1}: '{sp[:60]}...'")
        return fallback_prompts, "deterministic", fallback_objects, {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "nova_calls": nova_calls,
            "deepseek_calls": deepseek_calls,
            "deterministic": used_deterministic,
        }

    # ── Model invocation ───────────────────────────────────────────────────────

    def _try_model(
        self,
        model_id: str, model_name: str,
        master_prompt: str, n_clips: int,
        clip_durations: List[int], platform: str,
        is_static: bool = False,
    ) -> Tuple[Optional[List[str]], str, List[dict]]:
        """Attempt decomposition. Returns (sub_prompts, source, clip_objects) or (None, source, [])."""
        logger.info(f"[DECOMPOSER] Trying {model_name} ({model_id})")
        self._last_input_tokens  = 0
        self._last_output_tokens = 0
        try:
            result = self._llm_decompose(
                model_id=model_id, master_prompt=master_prompt,
                n_clips=n_clips, clip_durations=clip_durations, platform=platform,
                is_static=is_static,
            )
            if result is None:
                logger.warning(f"[DECOMPOSER] {model_name} returned None")
                return None, model_name, []

            sub_prompts, clip_objects = result
            if sub_prompts and len(sub_prompts) == n_clips:
                logger.info(f"[DECOMPOSER] {model_name} succeeded ({n_clips} clips)")
                for i, sp in enumerate(sub_prompts):
                    logger.info(f"   Clip {i+1}: '{sp[:60]}...'")
                return sub_prompts, model_name, clip_objects or []

            count = len(sub_prompts) if sub_prompts else 0
            logger.warning(f"[DECOMPOSER] {model_name} returned {count}/{n_clips} clips")
            return None, model_name, []
        except Exception as e:
            logger.error(f"[DECOMPOSER] {model_name} failed: {e}")
            return None, model_name, []

    def _llm_decompose(
        self,
        model_id: str, master_prompt: str,
        n_clips: int, clip_durations: List[int], platform: str,
        is_static: bool = False,
    ) -> Optional[tuple]:
        """Call Bedrock converse(), extract text, parse structured JSON objects."""
        total_duration    = sum(clip_durations)
        clip_duration_str = " + ".join(f"{d}s" for d in clip_durations)

        system_prompt = _SYSTEM_PROMPT
        if is_static:
            system_prompt = _SYSTEM_PROMPT.replace(
                "═══ OUTPUT FORMAT",
                _STATIC_SYSTEM_ADDENDUM + "\n\n═══ OUTPUT FORMAT",
            )
            logger.info("[DECOMPOSER] Static camera addendum injected into system prompt")
        if narrator_desc:
            system_prompt = system_prompt.replace(
                "═══ OUTPUT FORMAT",
                _NARRATOR_SYSTEM_ADDENDUM + "\n\n═══ OUTPUT FORMAT",
            )
            logger.info("[DECOMPOSER] Narrator voice lock addendum injected into system prompt")

        user_content = system_prompt.format(
            n=n_clips, platform=platform, total_duration=total_duration,
            clip_duration_str=clip_duration_str, master_prompt=master_prompt,
        )

        raw_text, in_tok, out_tok = self._converse(model_id, user_content)
        logger.info(f"[DECOMPOSER] Raw response ({model_id}): '{raw_text[:200]}'")
        # Store token counts as instance attr so _try_model can read them
        self._last_input_tokens  = in_tok
        self._last_output_tokens = out_tok

        # Try structured object format first (new prompt returns [{clip, duration_s, end_state, prompt}])
        clip_objects = self._parse_json_objects(raw_text, n_clips)
        if clip_objects:
            sub_prompts = [obj["prompt"] for obj in clip_objects]
            logger.info(f"[DECOMPOSER] Parsed {len(clip_objects)} structured clip objects")
            if len(sub_prompts) != n_clips:
                logger.warning(f"[DECOMPOSER] Count mismatch: expected {n_clips}, got {len(sub_prompts)}")
                sub_prompts, clip_objects = self._repair_count(sub_prompts, n_clips, master_prompt, clip_objects, clip_durations)
            sub_prompts, clip_objects = self._inject_static(sub_prompts, clip_objects, is_static)
            return sub_prompts, clip_objects

        # Fallback: plain string array (defensive — old format)
        sub_prompts = self._parse_json_array(raw_text)
        if sub_prompts is None:
            return None, None

        if len(sub_prompts) != n_clips:
            logger.warning(f"[DECOMPOSER] Count mismatch: expected {n_clips}, got {len(sub_prompts)}")
            sub_prompts, clip_objects = self._repair_count(sub_prompts, n_clips, master_prompt, [], clip_durations)
        else:
            clip_objects = [
                {"clip": i + 1, "duration_s": clip_durations[i], "prompt": sp, "end_state": ""}
                for i, sp in enumerate(sub_prompts)
            ]

        sub_prompts, clip_objects = self._inject_static(sub_prompts, clip_objects, is_static)
        if narrator_desc:
            sub_prompts, clip_objects = self._inject_narrator(sub_prompts, clip_objects, narrator_desc)
        return sub_prompts, clip_objects

    def _converse(self, model_id: str, user_text: str) -> Tuple[str, int, int]:
        """
        Call Bedrock converse() — single unified API for all model families.

        Returns (response_text, input_tokens, output_tokens).
        Token counts come from the Bedrock usage block — used for real-time
        metrics tracking. Returns (text, 0, 0) if usage not present.

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
            inferenceConfig={"maxTokens": 4096, "temperature": 0.7},
        )

        # Extract token usage — Bedrock always returns this in the response
        usage = response.get("usage", {})
        input_tokens  = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        if input_tokens or output_tokens:
            logger.info(
                f"[DECOMPOSER] Tokens — input: {input_tokens}, output: {output_tokens}"
            )

        content_blocks = (
            response.get("output", {})
                    .get("message", {})
                    .get("content", [])
        )
        logger.debug(f"[DECOMPOSER] {model_id}: {len(content_blocks)} content block(s)")
        text = self._extract_text_blocks(content_blocks, model_id)
        return text, input_tokens, output_tokens

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

    def _inject_narrator(
        self,
        sub_prompts: List[str],
        clip_objects: List[dict],
        narrator_desc: str,
    ) -> Tuple[List[str], List[dict]]:
        """
        Prepend narrator voice-lock directive to every sub-prompt.
        Mirrors _inject_static — same pattern, different directive.
        """
        directive = _NARRATOR_DIRECTIVE_TPL.format(narrator_desc=narrator_desc)
        new_prompts = []
        new_objects = []
        for sp, obj in zip(sub_prompts, clip_objects):
            if directive not in sp:
                sp = f"{directive} {sp}"
            new_obj = dict(obj)
            new_obj["prompt"] = sp
            new_prompts.append(sp)
            new_objects.append(new_obj)
        logger.info(
            f"[DECOMPOSER] Narrator voice lock injected into {len(new_prompts)} clip prompts"
        )
        return new_prompts, new_objects

    def _inject_static(
        self,
        sub_prompts: List[str],
        clip_objects: List[dict],
        is_static: bool,
    ) -> Tuple[List[str], List[dict]]:
        """
        Post-processing step: prepend the static camera directive to every
        sub-prompt when is_static=True. Operates on both plain strings and
        clip_objects so both the JSON file and the API call carry the directive.
        """
        if not is_static:
            return sub_prompts, clip_objects

        prefix = f"STATIC LOCKED-OFF FRAME. Camera does not move. {_STATIC_CAMERA_DIRECTIVE} "
        new_prompts = [prefix + p for p in sub_prompts]
        new_objects = []
        for i, obj in enumerate(clip_objects):
            new_objects.append({**obj, "prompt": new_prompts[i]})

        logger.info(f"[DECOMPOSER] Static camera directive injected into {len(new_prompts)} clip prompts")
        return new_prompts, new_objects

    def _parse_json_objects(self, text: str, expected_n: int) -> Optional[List[dict]]:
        """
        Parse a JSON array of clip objects from LLM response.
        Expected shape: [{"clip": int, "duration_s": int, "end_state": str, "prompt": str}, ...]
        Returns list of dicts if valid, None otherwise.
        """
        text  = re.sub(r"```(?:json)?\s*", "", text).strip()
        text  = re.sub(r"```\s*$",         "", text).strip()
        start = text.find("[")
        end   = text.rfind("]")

        if start == -1 or end == -1 or end <= start:
            return None

        try:
            parsed = json.loads(text[start: end + 1])
            if not isinstance(parsed, list):
                return None

            # Must be list of dicts with at least a "prompt" key
            objects = []
            for i, item in enumerate(parsed):
                if not isinstance(item, dict):
                    return None
                if "prompt" not in item:
                    return None
                objects.append({
                    "clip":       item.get("clip", i + 1),
                    "duration_s": item.get("duration_s", 8),
                    "end_state":  item.get("end_state", ""),
                    "prompt":     item["prompt"].strip(),
                })
            return objects if objects else None
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _parse_json_array(self, text: str) -> Optional[List[str]]:
        """Extract JSON array of strings from LLM response, handling markdown fences."""
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
        self,
        sub_prompts: List[str],
        target: int,
        master_prompt: str,
        clip_objects: List[dict],
        clip_durations: List[int],
    ) -> Tuple[List[str], List[dict]]:
        """Truncate if too many; pad with fallback phases if too few."""
        if len(sub_prompts) > target:
            logger.info(f"[DECOMPOSER] Truncating {len(sub_prompts)} -> {target}")
            sub_prompts  = sub_prompts[:target]
            clip_objects = clip_objects[:target] if clip_objects else []

        while len(sub_prompts) < target:
            idx   = len(sub_prompts)
            phase = _PHASE_LABELS[idx % len(_PHASE_LABELS)]
            cue   = _TRANSITION_CUES[idx % len(_TRANSITION_CUES)]
            padded = f"{phase}: {master_prompt.strip()}. {cue}"
            sub_prompts.append(padded)
            clip_objects.append({
                "clip":       idx + 1,
                "duration_s": clip_durations[idx] if idx < len(clip_durations) else 8,
                "end_state":  "",
                "prompt":     padded,
            })
            logger.info(f"[DECOMPOSER] Padded clip {idx + 1} with fallback phase")

        return sub_prompts, clip_objects

    # ── Deterministic tertiary fallback ───────────────────────────────────────

    def _phase_fallback(
        self, master_prompt: str, n_clips: int, clip_durations: List[int],
        is_static: bool = False,
        narrator_desc: Optional[str] = None,
    ) -> Tuple[List[str], List[dict]]:
        """
        Deterministic scene-phase decomposition — no LLM required.

        Three improvements over the naive approach:
        1. Narration lines are extracted and distributed one-per-clip in order.
           The remaining narration lines are stripped from each clip's base text
           so Veo never sees more than one narration line per clip.
        2. Camera movement cues (_TRANSITION_CUES) are suppressed when is_static=True.
        3. end_state is populated from the scene/character anchor so the orchestrator
           has a meaningful description for img2vid reference frame selection.
        """
        import re

        # ── Step 1: Extract narration lines from master prompt ────────────────
        # Parse all Narration "..." lines in order, then strip them from base.
        # Match both straight quotes "..." and curly quotes “...”
        # Also match patterns like: Narration: "..." and Indian Accent Narration: “...”
        narration_pattern = re.compile(
            r'(?:(?:[A-Za-z ]+)?Narration\s*[:\s]+)[\u201c"]([^\u201d"]+)[\u201d"]',
            re.IGNORECASE
        )
        narration_lines   = narration_pattern.findall(master_prompt)
        base = narration_pattern.sub("", master_prompt).strip().rstrip(".")
        # Collapse multiple spaces left by removal
        base = re.sub(r"  +", " ", base).strip()

        # ── Step 2: Distribute narration lines across clips ───────────────────
        # One narration line per clip. If there are fewer lines than clips,
        # later clips get no narration. If more lines than clips, pack extras
        # into the last clip (edge case — prompts should have n_lines == n_clips).
        def _narration_for_clip(i: int) -> str:
            """
            Distribute narration lines proportionally across clips.

            Rule: lines_per_clip = ceil(total_lines / n_clips)
            Clip i gets lines [i*lpc .. (i+1)*lpc - 1].

            Examples:
              4 lines, 4 clips → 1 line each
              4 lines, 2 clips → 2 lines each
              3 lines, 2 clips → clip 0 gets 2 lines, clip 1 gets 1 line
            """
            if not narration_lines:
                return ""
            import math
            lpc = math.ceil(len(narration_lines) / n_clips)  # lines per clip
            start = i * lpc
            end   = min(start + lpc, len(narration_lines))
            clip_lines = narration_lines[start:end]
            if not clip_lines:
                return ""
            combined = " ".join(f'Narration "{l}"' for l in clip_lines)
            if i == n_clips - 1:
                combined += " This is the final moment. Narration concludes naturally. Scene and audio resolve to a comfortable close."
            return f" {combined}"

        # ── Step 3: Derive end_state from base (scene + character anchor) ─────
        # Take up to the first 120 chars of base as the end_state description.
        # This gives the orchestrator a meaningful frame description for img2vid.
        end_state_base = base[:120].rsplit(" ", 1)[0] if len(base) > 120 else base

        # ── Step 4: Choose camera cue (suppressed for static) ─────────────────
        def _cue(i: int) -> str:
            if is_static:
                return ""  # never append movement cues to static prompts
            return " " + _TRANSITION_CUES[i % len(_TRANSITION_CUES)]

        # ── Step 5: Build per-clip prompts ────────────────────────────────────
        def _make(i: int, text: str) -> dict:
            return {
                "clip":       i + 1,
                "duration_s": clip_durations[i] if i < len(clip_durations) else 8,
                "end_state":  end_state_base,
                "prompt":     text,
            }

        sub_prompts = []
        for i in range(n_clips):
            narr = _narration_for_clip(i)
            cue  = _cue(i)

            if i == 0:
                sp = f"Opening — {base}.{narr}{cue}"
            elif i == n_clips - 1:
                sp = f"Closing — {base}.{narr} Final moments, scene resolves naturally."
            else:
                progress = int((i / (n_clips - 1)) * 100)
                sp = f"Scene continuing ({progress}% through) — {base}.{narr}"

            sub_prompts.append(sp.strip())

        objs = [_make(i, t) for i, t in enumerate(sub_prompts)]
        sub_prompts, objs = self._inject_static(sub_prompts, objs, is_static)
        if narrator_desc:
            sub_prompts, objs = self._inject_narrator(sub_prompts, objs, narrator_desc)
        return sub_prompts, objs


# ── Clip math utilities ────────────────────────────────────────────────────────

def compute_veo_clips(total_duration: int) -> List[int]:
    """Veo stitching: N x 8s clips."""
    n_clips = math.ceil(total_duration / 8)
    return [8] * n_clips