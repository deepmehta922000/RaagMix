import asyncio
import functools
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from presets import PRESETS, get_preset
from routers.analyze import _analyze_sync
from services.gemini_client import (
    GeminiAPIError,
    GeminiClient,
    GeminiMaxRetriesError,
)
from services.mix_executor import (
    ExecutorStepError,
    ExecutorValidationError,
    MixExecutor,
)
from utils import validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Gemini client singleton ────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _get_gemini_client() -> GeminiClient:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Add it to backend/.env and restart the server."
        )
    return GeminiClient(api_key=api_key)


# ── Request / response models ──────────────────────────────────────────────────

class RemixRequest(BaseModel):
    file_ids: list[str]
    user_prompt: str
    preset: Optional[str] = None
    filenames: Optional[dict[str, str]] = None  # {file_id: display filename}

    @field_validator("file_ids")
    @classmethod
    def validate_file_ids(cls, v: list[str]) -> list[str]:
        if not (2 <= len(v) <= 10):
            raise ValueError("file_ids must contain between 2 and 10 items")
        if len(v) != len(set(v)):
            raise ValueError("file_ids must be unique")
        return v

    @field_validator("user_prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_prompt cannot be empty")
        if len(v) > 500:
            raise ValueError("user_prompt must be 500 characters or fewer")
        return v

    @field_validator("preset")
    @classmethod
    def validate_preset(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PRESETS:
            raise ValueError(
                f"preset must be one of: {', '.join(sorted(PRESETS))} (or null)"
            )
        return v


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/remix")
async def remix(req: RemixRequest) -> dict:
    """Generate a mix plan via Gemini and execute it against the audio engine.

    Flow:
      1. Validate all file_ids exist on disk (collect all missing, not just first).
      2. Pre-analyze all songs in parallel to get BPM/duration for the Gemini prompt.
      3. Call GeminiClient to generate a JSON mix plan (retries on failure).
      4. Execute the plan step-by-step via MixExecutor (direct Python calls).
      5. Return the output file_id and execution metadata.
    """
    event_loop = asyncio.get_running_loop()

    # ── 1. Validate all file_ids upfront ──────────────────────────────────────
    missing: list[str] = []
    for fid in req.file_ids:
        try:
            validate_file_id(fid)
        except HTTPException:
            missing.append(fid)
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"error": "file_not_found", "missing_file_ids": missing},
        )

    # ── 2. Pre-analyze all songs in parallel ──────────────────────────────────
    analyze_tasks = [
        event_loop.run_in_executor(None, _analyze_sync, fid)
        for fid in req.file_ids
    ]
    try:
        songs: list[dict] = list(await asyncio.gather(*analyze_tasks))
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "analysis_failed",
                "detail": f"Could not analyze one or more input files: {exc}",
            },
        ) from exc

    # Attach display filenames for the Gemini prompt
    for song in songs:
        if req.filenames:
            song["filename"] = req.filenames.get(song["file_id"], song["file_id"])
        else:
            song["filename"] = song["file_id"]

    # ── 3. Generate mix plan via Gemini ───────────────────────────────────────
    preset_dict = get_preset(req.preset) if req.preset else None

    try:
        client = _get_gemini_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail={"error": "config_error", "detail": str(exc)})

    try:
        plan: dict = await event_loop.run_in_executor(
            None, client.generate_mix_plan, songs, preset_dict, req.user_prompt
        )
    except GeminiAPIError as exc:
        if exc.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "quota_exceeded",
                    "detail": "Gemini API quota exceeded. Please try again later.",
                },
            ) from exc
        raise HTTPException(
            status_code=502,
            detail={"error": "ai_plan_failed", "detail": str(exc), "retried": 1},
        ) from exc
    except GeminiMaxRetriesError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "ai_plan_failed",
                "detail": str(exc),
                "retried": exc.attempts,
            },
        ) from exc

    logger.info(
        "Gemini plan generated: %d steps, target BPM %.1f",
        len(plan.get("steps", [])),
        plan.get("target_bpm", 0),
    )

    # ── 4. Execute the plan ───────────────────────────────────────────────────
    executor = MixExecutor(input_file_ids=set(req.file_ids), plan=plan)

    try:
        result: dict = await event_loop.run_in_executor(None, executor.run)
    except ExecutorValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "plan_validation_failed",
                "detail": str(exc),
                "plan": plan,
            },
        ) from exc
    except ExecutorStepError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "execution_failed",
                "detail": str(exc),
                "failed_step_id": exc.step_id,
                "completed_steps": exc.completed_steps,
                "plan": plan,
            },
        ) from exc

    logger.info(
        "Remix complete: output=%s, %d/%d steps, BPM=%.1f",
        result["output_file_id"],
        result["steps_completed"],
        len(plan.get("steps", [])),
        result["target_bpm"],
    )

    return {**result, "plan": plan}
