"""
POST /stems/separate — vocal / accompaniment stem separation via Spleeter.

Separates a file (or a slice of it) into two stems and saves both to UPLOADS_DIR.
The endpoint is used directly by the UI and internally by mix_segments() when
vocal_duck=True is requested on a crossfade.
"""

import asyncio
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydub import AudioSegment

from utils import UPLOADS_DIR, pydub_from_file_id, validate_file_id

logger = logging.getLogger(__name__)
router = APIRouter()


class SeparateRequest(BaseModel):
    file_id: str
    start_ms: int = 0
    end_ms: Optional[int] = None  # None = full file


def _separate_sync(file_id: str, start_ms: int, end_ms: Optional[int]) -> dict:
    """CPU-bound stem separation — runs in a thread pool via run_in_executor."""
    seg = pydub_from_file_id(file_id)

    end = end_ms if end_ms is not None else len(seg)
    end = min(end, len(seg))
    start_ms = max(0, start_ms)

    if start_ms >= end:
        raise HTTPException(
            status_code=422,
            detail="start_ms must be less than end_ms (or file length)",
        )

    region = seg[start_ms:end]

    try:
        from spleeter.separator import Separator
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Spleeter is not installed. Run: pip install spleeter",
        )

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        tmp_wav = tmp_dir / "input.wav"
        region.export(str(tmp_wav), format="wav")

        out_dir = tmp_dir / "stems"
        separator = Separator("spleeter:2stems")
        separator.separate_to_file(str(tmp_wav), str(out_dir))

        # Spleeter writes: out_dir/<stem_name>/{vocals,accompaniment}.wav
        stem_dir = out_dir / "input"
        vocals_path = stem_dir / "vocals.wav"
        acc_path = stem_dir / "accompaniment.wav"

        if not vocals_path.exists() or not acc_path.exists():
            raise HTTPException(
                status_code=500,
                detail="Spleeter did not produce expected output files",
            )

        vocals_id = str(uuid.uuid4())
        acc_id = str(uuid.uuid4())

        AudioSegment.from_wav(str(vocals_path)).export(
            str(UPLOADS_DIR / f"{vocals_id}.wav"), format="wav"
        )
        AudioSegment.from_wav(str(acc_path)).export(
            str(UPLOADS_DIR / f"{acc_id}.wav"), format="wav"
        )

        return {
            "vocals_file_id": vocals_id,
            "accompaniment_file_id": acc_id,
            "duration_seconds": round(len(region) / 1000.0, 3),
            "start_ms": start_ms,
            "end_ms": end,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/stems/separate")
async def separate_stems(req: SeparateRequest) -> dict:
    validate_file_id(req.file_id)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, _separate_sync, req.file_id, req.start_ms, req.end_ms
    )
    logger.info(
        "Stem separation: %s [%d–%s ms] → vocals=%s acc=%s (%.1fs)",
        req.file_id,
        req.start_ms,
        req.end_ms,
        result["vocals_file_id"],
        result["accompaniment_file_id"],
        result["duration_seconds"],
    )
    return result
