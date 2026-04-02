"""Gemini API wrapper for RaagMix mix plan generation."""

import json
import logging
import re
from typing import Any, Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)

# ── Reference regex ────────────────────────────────────────────────────────────
_REF_RE = re.compile(r"^\$step_(\d+)_output$")

# ── Audio-producing ops (their output can be used as file_id inputs) ───────────
_AUDIO_OPS = {"time_stretch", "crossfade", "extract_loop"}
_ALL_OPS = _AUDIO_OPS | {"analyze"}

# ── Valid BPM / timing bounds (must stay in sync with audio engine) ────────────
_BPM_MIN, _BPM_MAX = 60.0, 180.0
_CROSSFADE_MS_MIN, _CROSSFADE_MS_MAX = 500, 30_000
_LOOP_COUNT_MIN, _LOOP_COUNT_MAX = 1, 32
_LOOP_DURATION_MS_MIN = 500
_STRETCH_RATIO_MIN, _STRETCH_RATIO_MAX = 0.5, 2.0
_MAX_STEPS = 20

# ── Static system prompt sections ─────────────────────────────────────────────

_SECTION_A = """\
You are the remix brain for RaagMix, a professional Bollywood and dance music \
remix tool. Your job is to produce a JSON mix plan that the RaagMix audio \
engine will execute step by step.

IMPORTANT OUTPUT RULES:
- Return ONLY a single JSON object.
- Do NOT include markdown code fences (no ```json or ```).
- Do NOT include any prose, comments, or text before or after the JSON.
- Your response must begin with '{' and end with }'.
"""

_SECTION_B = """\
AVAILABLE OPERATIONS
====================

1. op: "analyze"
   Detects BPM and duration of a track. Does NOT produce audio output — you
   cannot use an analyze output as a file_id in downstream audio steps.
   Use this only for songs whose bpm_confidence is "low" or "unreliable".
   Fields:
     file_id  (string, required): UUID of input audio file OR $step_N_output
              reference to a prior AUDIO-producing step.

2. op: "time_stretch"
   Changes tempo without changing pitch (phase vocoder). Produces a new audio file.
   Fields:
     file_id       (string, required): UUID or $step_N_output (audio only).
     target_bpm    (float,  required): Target tempo. Must be in [{bpm_min}, {bpm_max}].
     original_bpm  (float,  optional): Known source BPM — always supply when known.
   CONSTRAINT: stretch ratio = target_bpm / original_bpm must be in \
[{sr_min}, {sr_max}].
   If the BPMs are within 0.5 of each other, this step is a no-op (returns same file).

3. op: "crossfade"
   Blends the end of track A into the start of track B. Produces a new audio file.
   Fields:
     file_id_a     (string,  required): Outgoing track. UUID or $step_N_output (audio).
     file_id_b     (string,  required): Incoming track. UUID or $step_N_output (audio).
     crossfade_ms  (integer, required): Overlap in milliseconds. \
Range: [{cf_min}, {cf_max}].
     fade_type     (string,  required): "linear" for smooth genres; "logarithmic" for
                   dance/Bollywood (preserves energy at the blend point).
   CONSTRAINT: crossfade_ms must be strictly less than the duration of both tracks.

4. op: "extract_loop"
   Slices a segment and optionally repeats it. Produces a new audio file.
   Fields:
     file_id     (string,  required): UUID or $step_N_output (audio only).
     start_ms    (integer, required): Loop start in milliseconds. Min: 0.
     end_ms      (integer, required): Loop end in milliseconds. Must be > start_ms.
                 Minimum loop duration: {loop_min_ms} ms.
     loop_count  (integer, required): Repetitions. Range: [{lc_min}, {lc_max}].
""".format(
    bpm_min=_BPM_MIN,
    bpm_max=_BPM_MAX,
    sr_min=_STRETCH_RATIO_MIN,
    sr_max=_STRETCH_RATIO_MAX,
    cf_min=_CROSSFADE_MS_MIN,
    cf_max=_CROSSFADE_MS_MAX,
    loop_min_ms=_LOOP_DURATION_MS_MIN,
    lc_min=_LOOP_COUNT_MIN,
    lc_max=_LOOP_COUNT_MAX,
)

_SECTION_C = """\
REQUIRED JSON SCHEMA
====================

Return a single JSON object with these top-level fields:
  "version"     : string, must be "1.0"
  "target_bpm"  : float, the BPM all tracks are mixed to, range [60.0, 180.0]
  "preset"      : string or null
  "description" : string, brief human-readable summary of your plan (max 200 chars)
  "steps"       : array of step objects, 1–20 steps

Each step object must have:
  "step_id" : integer, starting at 1, incrementing by 1
  "op"      : one of "analyze", "time_stretch", "crossfade", "extract_loop"
  "note"    : string (optional), your brief rationale for this step
  ... plus the op-specific fields listed in AVAILABLE OPERATIONS above.

FILE REFERENCE RULES:
  Any field named file_id, file_id_a, or file_id_b must be EITHER:
    (a) A UUID string from the SONG LIST below, OR
    (b) "$step_N_output" where N is the step_id of a PRIOR step (N < current
        step_id) whose op is "time_stretch", "crossfade", or "extract_loop".
  You CANNOT reference the output of an "analyze" step as an audio input.
  You CANNOT use a forward reference (N >= current step_id).

The FINAL step in your plan must be an op that produces audio
("time_stretch", "crossfade", or "extract_loop"). Its output is the finished mix.

CONCRETE EXAMPLE (2 songs, 128 BPM, 4-second crossfade):
{
  "version": "1.0",
  "target_bpm": 128.0,
  "preset": "bollywood_dance",
  "description": "Stretch both tracks to 128 BPM, logarithmic crossfade over 4 seconds",
  "steps": [
    {
      "step_id": 1,
      "op": "time_stretch",
      "file_id": "aaaaaaaa-0000-0000-0000-000000000001",
      "target_bpm": 128.0,
      "original_bpm": 118.5,
      "note": "Bring Song A up to target BPM"
    },
    {
      "step_id": 2,
      "op": "time_stretch",
      "file_id": "bbbbbbbb-0000-0000-0000-000000000002",
      "target_bpm": 128.0,
      "original_bpm": 134.0,
      "note": "Bring Song B down to target BPM"
    },
    {
      "step_id": 3,
      "op": "crossfade",
      "file_id_a": "$step_1_output",
      "file_id_b": "$step_2_output",
      "crossfade_ms": 4000,
      "fade_type": "logarithmic",
      "note": "4-second energy-preserving blend for the dance floor"
    }
  ]
}
"""


# ── Custom exceptions ──────────────────────────────────────────────────────────

class GeminiError(Exception):
    """Base class for all GeminiClient errors."""


class GeminiParseError(GeminiError):
    """Gemini returned a response that could not be parsed as JSON."""
    def __init__(self, message: str, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text


class GeminiValidationError(GeminiError):
    """Gemini returned valid JSON but it failed schema validation."""
    def __init__(self, message: str, plan: dict | None = None) -> None:
        super().__init__(message)
        self.raw_plan_json = json.dumps(plan) if plan else ""


class GeminiAPIError(GeminiError):
    """The Gemini API returned an error."""
    def __init__(self, message: str, retryable: bool = True, status_code: int = 0) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class GeminiMaxRetriesError(GeminiError):
    """All retry attempts failed."""
    def __init__(self, attempts: int, last_error: str) -> None:
        super().__init__(
            f"Gemini failed to produce a valid mix plan after {attempts} attempts. "
            f"Last error: {last_error}"
        )
        self.attempts = attempts
        self.last_error = last_error


# ── GeminiClient ───────────────────────────────────────────────────────────────

class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        max_retries: int = 3,
    ) -> None:
        self.max_retries = max_retries
        self._model_name = model

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name=model,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_mime_type="application/json",
            ),
        )

    # ── Public entry point ─────────────────────────────────────────────────────

    def generate_mix_plan(
        self,
        songs: list[dict],
        preset: Optional[dict],
        user_prompt: str,
    ) -> dict:
        """Build a Gemini prompt, call the API, parse and validate the JSON plan.

        Retries up to max_retries times on recoverable failures, injecting a
        correction block into the prompt that names the specific error.
        """
        input_file_ids = {s["file_id"] for s in songs}
        last_error_msg = ""
        last_raw = ""

        for attempt in range(1, self.max_retries + 1):
            prompt = self._build_prompt(songs, preset, user_prompt)
            if attempt > 1:
                prompt = self._prepend_correction(
                    prompt, last_error_msg, last_raw, attempt
                )

            try:
                raw = self._call_api(prompt)
                plan = self._parse_and_validate(raw, input_file_ids)
                if attempt > 1:
                    logger.info("Gemini succeeded on attempt %d/%d", attempt, self.max_retries)
                return plan

            except GeminiParseError as e:
                last_error_msg = str(e)
                last_raw = e.raw_text
                logger.warning(
                    "Gemini parse error on attempt %d/%d: %s",
                    attempt, self.max_retries, last_error_msg,
                )

            except GeminiValidationError as e:
                last_error_msg = str(e)
                last_raw = e.raw_plan_json
                logger.warning(
                    "Gemini schema validation failed on attempt %d/%d: %s",
                    attempt, self.max_retries, last_error_msg,
                )

            except GeminiAPIError as e:
                if not e.retryable:
                    raise
                last_error_msg = str(e)
                last_raw = ""
                logger.warning(
                    "Retryable Gemini API error on attempt %d/%d: %s",
                    attempt, self.max_retries, last_error_msg,
                )

        raise GeminiMaxRetriesError(self.max_retries, last_error_msg)

    # ── Prompt construction ────────────────────────────────────────────────────

    def _build_prompt(
        self,
        songs: list[dict],
        preset: Optional[dict],
        user_prompt: str,
    ) -> str:
        parts = [_SECTION_A, _SECTION_B, _SECTION_C]
        parts.append(self._build_song_list(songs))
        if preset:
            parts.append(self._build_preset_section(preset))
        parts.append(
            f"USER INSTRUCTIONS: {user_prompt}\n\n"
            "Produce the JSON mix plan now. Begin your response with '{'."
        )
        return "\n\n".join(parts)

    @staticmethod
    def _build_song_list(songs: list[dict]) -> str:
        lines = [
            "SONG LIST (your input files)",
            "============================",
            f"You have {len(songs)} song(s) to work with:\n",
        ]
        for i, song in enumerate(songs, start=1):
            confidence = song.get("bpm_confidence", "ok")
            note = ""
            if confidence in ("low", "unreliable"):
                note = (
                    "  NOTE: BPM confidence is low — add an \"analyze\" step before "
                    "any time_stretch that uses this file, and omit original_bpm.\n"
                )
            lines.append(
                f"Song {i}:\n"
                f"  file_id    : \"{song['file_id']}\"\n"
                f"  filename   : \"{song.get('filename', song['file_id'])}\"\n"
                f"  bpm        : {song.get('bpm', '?')}\n"
                f"  confidence : \"{confidence}\"\n"
                f"  duration   : {song.get('duration_seconds', '?')} seconds\n"
                f"{note}"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_preset_section(preset: dict) -> str:
        bpr = preset["target_bpm_range"]
        return (
            f"STYLE PRESET: {preset['display_name']}\n"
            f"{'=' * (15 + len(preset['display_name']))}\n"
            f"{preset['instructions']}\n\n"
            f"Your plan's target_bpm must be within [{bpr['min']}, {bpr['max']}].\n"
            f"Default crossfade_ms for this preset: {preset['default_crossfade_ms']}.\n"
            f"Default fade_type for this preset: \"{preset['default_fade_type']}\"."
        )

    @staticmethod
    def _prepend_correction(
        base_prompt: str,
        error_msg: str,
        last_raw: str,
        attempt: int,
    ) -> str:
        truncated = (last_raw[:1500] + "…[truncated]") if len(last_raw) > 1500 else last_raw
        correction = (
            f"CORRECTION REQUIRED (attempt {attempt})\n"
            f"{'=' * 40}\n"
            f"Your previous response was rejected for this reason:\n"
            f"  {error_msg}\n\n"
            f"Your previous response was:\n"
            f"  {truncated}\n\n"
            f"Fix the issue and return a corrected JSON plan. "
            f"Remember: return ONLY JSON, beginning with '{{' .\n\n"
        )
        return correction + base_prompt

    # ── API call ───────────────────────────────────────────────────────────────

    def _call_api(self, prompt: str) -> str:
        try:
            response = self._model.generate_content(prompt)
            text = response.text
        except Exception as exc:
            exc_name = type(exc).__name__
            exc_str = str(exc)
            # Classify quota errors as non-retryable
            if "ResourceExhausted" in exc_name or "429" in exc_str or "quota" in exc_str.lower():
                raise GeminiAPIError(exc_str, retryable=False, status_code=429) from exc
            retryable = any(
                x in exc_str for x in ("503", "504", "timeout", "unavailable", "502")
            )
            raise GeminiAPIError(exc_str, retryable=retryable) from exc

        if not text:
            raise GeminiParseError("Gemini returned an empty response", raw_text="")
        return text

    # ── Parsing and validation ─────────────────────────────────────────────────

    def _parse_and_validate(self, raw: str, input_file_ids: set[str]) -> dict:
        """Extract JSON from raw response text and validate against the plan schema."""
        cleaned = raw.strip()

        # Fallback: strip markdown fences if response_mime_type hint was ignored
        if cleaned.startswith("```"):
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1)
            else:
                cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned).rstrip("`").strip()

        try:
            plan = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise GeminiParseError(
                f"Response is not valid JSON: {exc}", raw_text=raw
            ) from exc

        if not isinstance(plan, dict):
            raise GeminiParseError("Response JSON is not an object", raw_text=raw)

        self._validate_schema(plan, input_file_ids)
        return plan

    def _validate_schema(self, plan: dict, input_file_ids: set[str]) -> None:
        """Run all 9 schema checks. Raises GeminiValidationError on first failure."""

        def fail(msg: str) -> None:
            raise GeminiValidationError(msg, plan=plan)

        # 1. version
        if plan.get("version") != "1.0":
            fail(f"\"version\" must be \"1.0\", got {plan.get('version')!r}")

        # 2. target_bpm
        tbpm = plan.get("target_bpm")
        if not isinstance(tbpm, (int, float)) or not (_BPM_MIN <= tbpm <= _BPM_MAX):
            fail(f"\"target_bpm\" must be a float in [{_BPM_MIN}, {_BPM_MAX}], got {tbpm!r}")

        # 3. steps list
        steps = plan.get("steps")
        if not isinstance(steps, list) or len(steps) == 0:
            fail("\"steps\" must be a non-empty array")
        if len(steps) > _MAX_STEPS:
            fail(f"\"steps\" has {len(steps)} items; maximum is {_MAX_STEPS}")

        # 4. step_ids sequential from 1
        for i, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                fail(f"Step at index {i - 1} is not an object")
            sid = step.get("step_id")
            if sid != i:
                fail(f"step_id at position {i - 1} must be {i}, got {sid!r}")
            if step.get("op") not in _ALL_OPS:
                fail(f"Step {sid}: \"op\" must be one of {sorted(_ALL_OPS)}, got {step.get('op')!r}")

        # Build a map of step_id → op for reference resolution checks
        op_by_id: dict[int, str] = {s["step_id"]: s["op"] for s in steps}

        def check_ref(ref: Any, current_step_id: int, field: str) -> None:
            """Check that a file_id field is a valid UUID or a valid $step_N_output ref."""
            if not isinstance(ref, str):
                fail(f"Step {current_step_id}: \"{field}\" must be a string, got {ref!r}")
            m = _REF_RE.match(ref)
            if m:
                n = int(m.group(1))
                if n >= current_step_id:
                    fail(
                        f"Step {current_step_id}: \"{field}\" references $step_{n}_output "
                        f"but that is a forward reference (N must be < {current_step_id})"
                    )
                if op_by_id.get(n) not in _AUDIO_OPS:
                    fail(
                        f"Step {current_step_id}: \"{field}\" references $step_{n}_output "
                        f"but step {n} is op=\"{op_by_id.get(n)}\" which does not produce audio"
                    )
            else:
                # 5. literal UUID must be in the caller's input file list
                if ref not in input_file_ids:
                    fail(
                        f"Step {current_step_id}: \"{field}\" value {ref!r} is not in the "
                        f"provided SONG LIST"
                    )

        for step in steps:
            sid = step["step_id"]
            op = step["op"]

            if op == "analyze":
                if "file_id" not in step:
                    fail(f"Step {sid} (analyze): missing required field \"file_id\"")
                check_ref(step["file_id"], sid, "file_id")

            elif op == "time_stretch":
                for field in ("file_id", "target_bpm"):
                    if field not in step:
                        fail(f"Step {sid} (time_stretch): missing required field \"{field}\"")
                check_ref(step["file_id"], sid, "file_id")
                tbpm_step = step["target_bpm"]
                if not isinstance(tbpm_step, (int, float)) or not (_BPM_MIN <= tbpm_step <= _BPM_MAX):
                    fail(
                        f"Step {sid} (time_stretch): \"target_bpm\" must be in "
                        f"[{_BPM_MIN}, {_BPM_MAX}], got {tbpm_step!r}"
                    )
                # Pre-validate stretch ratio when original_bpm is provided
                orig = step.get("original_bpm")
                if orig is not None and isinstance(orig, (int, float)) and orig > 0:
                    ratio = tbpm_step / orig
                    if not (_STRETCH_RATIO_MIN <= ratio <= _STRETCH_RATIO_MAX):
                        fail(
                            f"Step {sid} (time_stretch): stretch ratio {ratio:.3f} "
                            f"(target {tbpm_step} / original {orig}) is outside "
                            f"[{_STRETCH_RATIO_MIN}, {_STRETCH_RATIO_MAX}]"
                        )

            elif op == "crossfade":
                for field in ("file_id_a", "file_id_b", "crossfade_ms", "fade_type"):
                    if field not in step:
                        fail(f"Step {sid} (crossfade): missing required field \"{field}\"")
                check_ref(step["file_id_a"], sid, "file_id_a")
                check_ref(step["file_id_b"], sid, "file_id_b")
                cf_ms = step["crossfade_ms"]
                if not isinstance(cf_ms, int) or not (_CROSSFADE_MS_MIN <= cf_ms <= _CROSSFADE_MS_MAX):
                    fail(
                        f"Step {sid} (crossfade): \"crossfade_ms\" must be an integer in "
                        f"[{_CROSSFADE_MS_MIN}, {_CROSSFADE_MS_MAX}], got {cf_ms!r}"
                    )
                if step["fade_type"] not in ("linear", "logarithmic"):
                    fail(
                        f"Step {sid} (crossfade): \"fade_type\" must be "
                        f"\"linear\" or \"logarithmic\", got {step['fade_type']!r}"
                    )

            elif op == "extract_loop":
                for field in ("file_id", "start_ms", "end_ms", "loop_count"):
                    if field not in step:
                        fail(f"Step {sid} (extract_loop): missing required field \"{field}\"")
                check_ref(step["file_id"], sid, "file_id")
                start_ms = step["start_ms"]
                end_ms = step["end_ms"]
                lc = step["loop_count"]
                if not isinstance(start_ms, int) or start_ms < 0:
                    fail(f"Step {sid} (extract_loop): \"start_ms\" must be an integer >= 0")
                if not isinstance(end_ms, int) or end_ms <= start_ms:
                    fail(f"Step {sid} (extract_loop): \"end_ms\" must be > \"start_ms\"")
                if (end_ms - start_ms) < _LOOP_DURATION_MS_MIN:
                    fail(
                        f"Step {sid} (extract_loop): loop duration {end_ms - start_ms} ms "
                        f"is below the minimum {_LOOP_DURATION_MS_MIN} ms"
                    )
                if not isinstance(lc, int) or not (_LOOP_COUNT_MIN <= lc <= _LOOP_COUNT_MAX):
                    fail(
                        f"Step {sid} (extract_loop): \"loop_count\" must be an integer in "
                        f"[{_LOOP_COUNT_MIN}, {_LOOP_COUNT_MAX}], got {lc!r}"
                    )

        # 9. Final step must produce audio
        last_op = steps[-1]["op"]
        if last_op not in _AUDIO_OPS:
            fail(
                f"The final step (step_id={steps[-1]['step_id']}) has op=\"{last_op}\" "
                f"which does not produce audio. The last step must be one of: "
                f"{sorted(_AUDIO_OPS)}"
            )
