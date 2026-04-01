import logging
import uuid
from pathlib import Path
from typing import Tuple

import librosa
import numpy as np
import soundfile as sf
from fastapi import HTTPException
from pydub import AudioSegment

logger = logging.getLogger(__name__)

UPLOADS_DIR = Path(__file__).parent / "uploads"
ALLOWED_EXTENSIONS = {".mp3", ".wav"}
ALLOWED_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
}


def get_upload_path(file_id: str) -> Path:
    """Resolve the absolute path for a file_id with path-traversal guard."""
    uploads_resolved = UPLOADS_DIR.resolve()
    matches = [
        p for p in UPLOADS_DIR.glob(f"{file_id}.*") if p.suffix in ALLOWED_EXTENSIONS
    ]
    if not matches:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    path = matches[0].resolve()
    if not path.is_relative_to(uploads_resolved):
        raise HTTPException(status_code=400, detail="Invalid file ID")
    return path


def validate_file_id(file_id: str) -> None:
    """Validate UUID format and confirm the file exists on disk."""
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid file ID format")
    get_upload_path(file_id)


def load_audio(file_id: str) -> Tuple[np.ndarray, int]:
    """Load audio as mono numpy array at native sample rate.

    Always mono=True: BPM detection and time-stretching require a single channel.
    sr=None: preserve native rate rather than silently downsampling to 22050 Hz.
    Only call from a thread pool (librosa.load is blocking).
    """
    path = get_upload_path(file_id)
    y, sr = librosa.load(str(path), sr=None, mono=True)
    return y, sr


def save_processed_audio(y: np.ndarray, sr: int) -> str:
    """Write a processed numpy array to uploads/ as WAV. Returns the new file_id.

    Output is always WAV to avoid generational quality loss on MP3 re-encoding.
    """
    new_id = str(uuid.uuid4())
    out_path = UPLOADS_DIR / f"{new_id}.wav"
    sf.write(str(out_path), y, sr)
    logger.info(
        "Saved processed audio %s.wav (%d samples @ %d Hz)", new_id, len(y), sr
    )
    return new_id


def pydub_from_file_id(file_id: str) -> AudioSegment:
    """Load an audio file as a pydub AudioSegment (format-agnostic)."""
    path = get_upload_path(file_id)
    return AudioSegment.from_file(str(path))
