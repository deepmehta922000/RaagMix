import asyncio
import logging
from typing import Optional

import librosa
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils import load_audio, save_processed_audio, validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()

MIN_STRETCH_RATIO = 0.5
MAX_STRETCH_RATIO = 2.0
BPM_MATCH_TOLERANCE = 0.5


class TimeStretchRequest(BaseModel):
    file_id: str
    target_bpm: float
    original_bpm: Optional[float] = None  # skip re-detection if caller already knows it


def _time_stretch_sync(
    file_id: str, target_bpm: float, original_bpm: Optional[float]
) -> dict:
    """CPU-bound time-stretch — runs in a thread pool via run_in_executor."""
    y, sr = load_audio(file_id)

    if original_bpm is None:
        detected, _ = librosa.beat.beat_track(y=y, sr=sr)
        original_bpm = float(np.atleast_1d(detected)[0])

    if abs(target_bpm - original_bpm) <= BPM_MATCH_TOLERANCE:
        return {
            "original_file_id": file_id,
            "new_file_id": file_id,
            "original_bpm": round(original_bpm, 2),
            "target_bpm": round(target_bpm, 2),
            "stretch_ratio": 1.0,
            "no_change": True,
        }

    stretch_ratio = target_bpm / original_bpm
    if not (MIN_STRETCH_RATIO <= stretch_ratio <= MAX_STRETCH_RATIO):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Stretch ratio {stretch_ratio:.3f} is outside the supported range "
                f"[{MIN_STRETCH_RATIO}, {MAX_STRETCH_RATIO}]. "
                f"Target BPM must be between "
                f"{original_bpm * MIN_STRETCH_RATIO:.1f} and "
                f"{original_bpm * MAX_STRETCH_RATIO:.1f}."
            ),
        )

    # time_stretch uses a phase vocoder, which preserves pitch while changing tempo.
    # pydub's speed change alters both pitch and tempo — unusable for a remix app
    # where a singer's voice or sitar riff must not shift pitch.
    y_stretched = librosa.effects.time_stretch(y, rate=stretch_ratio)
    new_file_id = save_processed_audio(y_stretched, sr)
    duration = librosa.get_duration(y=y_stretched, sr=sr)

    return {
        "original_file_id": file_id,
        "new_file_id": new_file_id,
        "original_bpm": round(original_bpm, 2),
        "target_bpm": round(target_bpm, 2),
        "stretch_ratio": round(stretch_ratio, 4),
        "duration_seconds": round(duration, 3),
        "no_change": False,
    }


@router.post("/time-stretch")
async def time_stretch(req: TimeStretchRequest) -> dict:
    validate_file_id(req.file_id)
    if req.target_bpm <= 0:
        raise HTTPException(status_code=422, detail="target_bpm must be positive")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, _time_stretch_sync, req.file_id, req.target_bpm, req.original_bpm
    )
    logger.info(
        "Time-stretched %s → %s (%.1f → %.1f BPM, ratio %.3f)",
        req.file_id,
        result["new_file_id"],
        result["original_bpm"],
        result["target_bpm"],
        result["stretch_ratio"],
    )
    return result
