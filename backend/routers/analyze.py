import asyncio
import logging

import librosa
import numpy as np
from fastapi import APIRouter

from utils import load_audio, validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()


def _analyze_sync(file_id: str) -> dict:
    """CPU-bound analysis — runs in a thread pool via run_in_executor."""
    y, sr = load_audio(file_id)
    duration = librosa.get_duration(y=y, sr=sr)

    # beat_track uses dynamic-programming beat tracking, which is more robust
    # for Bollywood tracks with percussion-heavy intros or subtle tempo drift
    # than librosa.beat.tempo(), which just picks the raw histogram peak.
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])

    bpm_confidence = "ok"
    if duration < 10.0:
        bpm_confidence = "low"
    elif not (40.0 <= bpm <= 220.0):
        bpm_confidence = "unreliable"

    return {
        "file_id": file_id,
        "bpm": round(bpm, 2),
        "bpm_confidence": bpm_confidence,
        "duration_seconds": round(duration, 3),
        "sample_rate": sr,
        "num_samples": len(y),
    }


@router.post("/analyze/{file_id}")
async def analyze_audio(file_id: str) -> dict:
    validate_file_id(file_id)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _analyze_sync, file_id)
    logger.info(
        "Analyzed %s: %.1f BPM (%s), %.1fs",
        file_id,
        result["bpm"],
        result["bpm_confidence"],
        result["duration_seconds"],
    )
    return result
