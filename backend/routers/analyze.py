import asyncio
import logging

import librosa
import numpy as np
from fastapi import APIRouter

from utils import load_audio, validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()

# Krumhansl-Schmuckler key profiles (major and minor)
# Indices 0–11 map to C, C#, D, D#, E, F, F#, G, G#, A, A#, B
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                       2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                       2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]


def _detect_key(y: np.ndarray, sr: int) -> tuple[str, float]:
    """Return (key_string, confidence) using Krumhansl-Schmuckler profiles.

    key_string is e.g. "A major" or "F# minor".
    confidence is the Pearson correlation of the best match (0–1).
    """
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    mean_chroma = chroma.mean(axis=1)  # shape (12,)

    best_score = -np.inf
    best_key = "C major"

    for root in range(12):
        # Rotate profiles to match this root note
        major_profile = np.roll(_KS_MAJOR, root)
        minor_profile = np.roll(_KS_MINOR, root)

        score_major = float(np.corrcoef(mean_chroma, major_profile)[0, 1])
        score_minor = float(np.corrcoef(mean_chroma, minor_profile)[0, 1])

        if score_major > best_score:
            best_score = score_major
            best_key = f"{_NOTE_NAMES[root]} major"
        if score_minor > best_score:
            best_score = score_minor
            best_key = f"{_NOTE_NAMES[root]} minor"

    confidence = round(float(np.clip(best_score, 0.0, 1.0)), 3)
    return best_key, confidence


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

    key, key_confidence = _detect_key(y, sr)

    return {
        "file_id": file_id,
        "bpm": round(bpm, 2),
        "bpm_confidence": bpm_confidence,
        "duration_seconds": round(duration, 3),
        "sample_rate": sr,
        "num_samples": len(y),
        "key": key,
        "key_confidence": key_confidence,
    }


@router.post("/analyze/{file_id}")
async def analyze_audio(file_id: str) -> dict:
    validate_file_id(file_id)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _analyze_sync, file_id)
    logger.info(
        "Analyzed %s: %.1f BPM (%s), key=%s (%.2f), %.1fs",
        file_id,
        result["bpm"],
        result["bpm_confidence"],
        result["key"],
        result["key_confidence"],
        result["duration_seconds"],
    )
    return result
