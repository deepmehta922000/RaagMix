import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils import UPLOADS_DIR, pydub_from_file_id, validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()

MIN_LOOP_DURATION = 0.5  # seconds
MAX_LOOP_COUNT = 32


class ExtractLoopRequest(BaseModel):
    file_id: str
    start_time: float  # seconds
    end_time: float  # seconds
    loop_count: int = 1
    snap_to_beat: bool = False  # stub: reserved for v2 beat-snapping via librosa


def _extract_loop_sync(
    file_id: str,
    start_ms: int,
    end_ms: int,
    loop_count: int,
) -> dict:
    """CPU-bound loop extraction — runs in a thread pool via run_in_executor."""
    seg = pydub_from_file_id(file_id)

    if end_ms > len(seg):
        raise HTTPException(
            status_code=422,
            detail=(
                f"end_time ({end_ms / 1000:.2f}s) exceeds "
                f"track duration ({len(seg) / 1000:.2f}s)"
            ),
        )

    # pydub slicing [start_ms:end_ms] works at the clip level and handles
    # frame alignment automatically — preferred over librosa sample slicing
    # which would require manual index math and format conversion.
    loop_segment = seg[start_ms:end_ms]
    if loop_count > 1:
        loop_segment = loop_segment * loop_count

    new_id = str(uuid.uuid4())
    out_path = UPLOADS_DIR / f"{new_id}.wav"
    loop_segment.export(str(out_path), format="wav")

    loop_duration = (end_ms - start_ms) / 1000.0
    return {
        "new_file_id": new_id,
        "start_time": start_ms / 1000.0,
        "end_time": end_ms / 1000.0,
        "loop_duration_seconds": round(loop_duration, 3),
        "total_duration_seconds": round(loop_duration * loop_count, 3),
    }


@router.post("/extract-loop")
async def extract_loop(req: ExtractLoopRequest) -> dict:
    validate_file_id(req.file_id)

    if req.start_time < 0:
        raise HTTPException(status_code=422, detail="start_time must be >= 0")
    if req.end_time <= req.start_time:
        raise HTTPException(
            status_code=422, detail="end_time must be greater than start_time"
        )
    if (req.end_time - req.start_time) < MIN_LOOP_DURATION:
        raise HTTPException(
            status_code=422,
            detail=f"Loop must be at least {MIN_LOOP_DURATION}s long",
        )
    if not (1 <= req.loop_count <= MAX_LOOP_COUNT):
        raise HTTPException(
            status_code=422,
            detail=f"loop_count must be between 1 and {MAX_LOOP_COUNT}",
        )

    start_ms = int(req.start_time * 1000)
    end_ms = int(req.end_time * 1000)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, _extract_loop_sync, req.file_id, start_ms, end_ms, req.loop_count
    )
    logger.info(
        "Extracted loop from %s [%.2fs–%.2fs] × %d → %s",
        req.file_id,
        req.start_time,
        req.end_time,
        req.loop_count,
        result["new_file_id"],
    )
    return result
