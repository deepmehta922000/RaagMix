import asyncio
import json
import logging

import librosa
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from utils import UPLOADS_DIR, load_audio, validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()

MIN_POINTS = 100
MAX_POINTS = 10_000


def _compute_waveform(file_id: str, num_points: int) -> dict:
    """CPU-bound waveform downsampling — runs in a thread pool via run_in_executor.

    Uses peak-based downsampling: for each display point, take max(abs(chunk)).
    Mean-based would cancel positive and negative peaks, producing a flat waveform
    for loud sections. Peak amplitude correctly shows transients, drops, and builds.
    """
    cache_path = UPLOADS_DIR / f"{file_id}.waveform.json"
    cache_key = f"{file_id}:{num_points}"

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("cache_key") == cache_key:
                return cached["data"]
        except (json.JSONDecodeError, KeyError):
            pass  # stale or corrupt cache — recompute

    y, sr = load_audio(file_id)
    duration = librosa.get_duration(y=y, sr=sr)

    actual_points = min(num_points, len(y))
    clamped = actual_points < num_points

    chunks = np.array_split(y, actual_points)
    # .tolist() converts numpy float32 to plain Python float for JSON serialization
    amplitudes = [
        float(np.max(np.abs(chunk))) for chunk in chunks if len(chunk) > 0
    ]

    data = {
        "file_id": file_id,
        "num_points": len(amplitudes),
        "amplitudes": amplitudes,
        "duration_seconds": round(duration, 3),
        "sample_rate": sr,
        "clamped": clamped,
    }

    try:
        cache_path.write_text(json.dumps({"cache_key": cache_key, "data": data}))
    except OSError:
        logger.warning("Failed to write waveform cache for %s", file_id)

    return data


@router.get("/waveform/{file_id}")
async def get_waveform(file_id: str, num_points: int = 1000) -> JSONResponse:
    validate_file_id(file_id)

    if not (MIN_POINTS <= num_points <= MAX_POINTS):
        raise HTTPException(
            status_code=422,
            detail=f"num_points must be between {MIN_POINTS} and {MAX_POINTS}",
        )

    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _compute_waveform, file_id, num_points)

    # Cache-Control: waveform for a given file_id never changes
    return JSONResponse(content=data, headers={"Cache-Control": "max-age=3600"})
