"""Executes a validated Gemini mix plan by calling audio engine functions directly."""

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException

from routers.analyze import _analyze_sync
from routers.loops import _extract_loop_sync
from routers.mixer import mix_segments
from routers.transform import _time_stretch_sync, MAX_STRETCH_RATIO, MIN_STRETCH_RATIO
from utils import UPLOADS_DIR, get_upload_path

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"^\$step_(\d+)_output$")
_AUDIO_OPS = {"time_stretch", "crossfade", "extract_loop"}


# ── Custom exceptions ──────────────────────────────────────────────────────────

class ExecutorError(Exception):
    """Base class for MixExecutor errors."""


class ExecutorValidationError(ExecutorError):
    """Plan failed pre-execution validation (no audio was touched)."""


class ExecutorStepError(ExecutorError):
    """An audio engine step failed during execution."""
    def __init__(
        self,
        step_id: int,
        op: str,
        message: str,
        completed_steps: list[int],
    ) -> None:
        super().__init__(
            f"Step {step_id} ({op}) failed: {message}"
        )
        self.step_id = step_id
        self.op = op
        self.completed_steps = completed_steps


# ── MixExecutor ────────────────────────────────────────────────────────────────

class MixExecutor:
    """Executes a schema-validated mix plan produced by GeminiClient.

    Calls the sync audio engine functions directly (not via HTTP), so this
    class itself must be run in a thread pool via asyncio.run_in_executor.
    """

    def __init__(self, input_file_ids: set[str], plan: dict) -> None:
        self._input_file_ids = input_file_ids
        self._plan = plan

    def run(self) -> dict:
        """Validate and execute the plan. Returns the result dict on success."""
        self._prevalidate()
        return self._execute()

    # ── Pre-execution validation ───────────────────────────────────────────────

    def _prevalidate(self) -> None:
        """Run runtime checks before touching any audio file.

        These complement the schema checks already done by GeminiClient:
        - All literal UUIDs must actually exist on disk.
        - time_stretch steps with known original_bpm must have a valid ratio.
        """
        missing: list[str] = []
        for fid in self._input_file_ids:
            try:
                get_upload_path(fid)
            except HTTPException:
                missing.append(fid)
        if missing:
            raise ExecutorValidationError(
                f"The following input file(s) no longer exist on disk: {missing}"
            )

        for step in self._plan["steps"]:
            if step["op"] != "time_stretch":
                continue
            orig = step.get("original_bpm")
            target = step.get("target_bpm")
            if orig is not None and isinstance(orig, (int, float)) and orig > 0:
                ratio = target / orig
                if not (MIN_STRETCH_RATIO <= ratio <= MAX_STRETCH_RATIO):
                    raise ExecutorValidationError(
                        f"Step {step['step_id']} (time_stretch): stretch ratio {ratio:.3f} "
                        f"({target} / {orig}) is outside [{MIN_STRETCH_RATIO}, {MAX_STRETCH_RATIO}]. "
                        f"target_bpm must be between {orig * MIN_STRETCH_RATIO:.1f} and "
                        f"{orig * MAX_STRETCH_RATIO:.1f}."
                    )

    # ── Execution loop ─────────────────────────────────────────────────────────

    def _execute(self) -> dict:
        step_outputs: dict[int, str] = {}    # step_id → new audio file_id
        step_analyses: dict[int, dict] = {}  # step_id → analysis result dict
        intermediate_file_ids: list[str] = []
        step_results: list[dict] = []
        completed_steps: list[int] = []

        for step in self._plan["steps"]:
            sid = step["step_id"]
            op = step["op"]
            logger.info("Executing step %d (%s)", sid, op)

            try:
                result = self._execute_step(step, step_outputs, step_analyses)
            except (ExecutorStepError, ExecutorValidationError):
                raise
            except HTTPException as exc:
                self._cleanup(intermediate_file_ids)
                raise ExecutorStepError(
                    step_id=sid,
                    op=op,
                    message=str(exc.detail),
                    completed_steps=completed_steps,
                ) from exc
            except Exception as exc:
                self._cleanup(intermediate_file_ids)
                raise ExecutorStepError(
                    step_id=sid,
                    op=op,
                    message=str(exc),
                    completed_steps=completed_steps,
                ) from exc

            if op == "analyze":
                step_analyses[sid] = result
            else:
                new_fid = result["new_file_id"]
                step_outputs[sid] = new_fid
                # Only track genuinely new files — time_stretch no-ops return the original
                if new_fid not in self._input_file_ids:
                    intermediate_file_ids.append(new_fid)

            step_results.append({"step_id": sid, "op": op, "result": result})
            completed_steps.append(sid)
            logger.info("Step %d (%s) completed", sid, op)

        final_step = self._plan["steps"][-1]
        output_file_id = step_outputs[final_step["step_id"]]

        return {
            "output_file_id": output_file_id,
            "target_bpm": self._plan["target_bpm"],
            "steps_completed": len(completed_steps),
            "step_results": step_results,
            "intermediate_file_ids": intermediate_file_ids,
        }

    # ── Per-step dispatch ──────────────────────────────────────────────────────

    def _execute_step(
        self,
        step: dict,
        step_outputs: dict[int, str],
        step_analyses: dict[int, dict],
    ) -> dict:
        op = step["op"]
        sid = step["step_id"]

        if op == "analyze":
            file_id = self._resolve(step["file_id"], step_outputs)
            return _analyze_sync(file_id)

        if op == "time_stretch":
            file_id = self._resolve(step["file_id"], step_outputs)
            return _time_stretch_sync(
                file_id,
                float(step["target_bpm"]),
                float(step["original_bpm"]) if step.get("original_bpm") is not None else None,
            )

        if op == "crossfade":
            file_id_a = self._resolve(step["file_id_a"], step_outputs)
            file_id_b = self._resolve(step["file_id_b"], step_outputs)
            return mix_segments(
                file_id_a,
                file_id_b,
                int(step["crossfade_ms"]),
                str(step["fade_type"]),
                align_beats=True,
                eq_crossfade=True,
            )

        if op == "extract_loop":
            file_id = self._resolve(step["file_id"], step_outputs)
            return _extract_loop_sync(
                file_id,
                int(step["start_ms"]),
                int(step["end_ms"]),
                int(step["loop_count"]),
            )

        raise ExecutorValidationError(f"Step {sid}: unknown op {op!r}")

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve(ref: str, step_outputs: dict[int, str]) -> str:
        """Resolve a $step_N_output reference to its actual file_id, or return as-is."""
        m = _REF_RE.match(ref)
        if m:
            n = int(m.group(1))
            if n not in step_outputs:
                raise ExecutorValidationError(
                    f"Cannot resolve {ref!r}: step {n} has not produced output yet "
                    f"(available: {sorted(step_outputs)})"
                )
            return step_outputs[n]
        return ref

    @staticmethod
    def _cleanup(file_ids: list[str]) -> None:
        """Delete intermediate files produced by completed steps before the failure."""
        for fid in file_ids:
            try:
                # Search both .wav and .mp3 since save_processed_audio always writes .wav
                for path in UPLOADS_DIR.glob(f"{fid}.*"):
                    path.unlink(missing_ok=True)
                    logger.info("Cleaned up intermediate file %s", path.name)
            except Exception:
                logger.warning("Failed to clean up intermediate file %s", fid, exc_info=True)
