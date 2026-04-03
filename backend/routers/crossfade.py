import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydub import AudioSegment

from routers.mixer import mix_segments
from utils import UPLOADS_DIR, pydub_from_file_id, validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()


class CrossfadeRequest(BaseModel):
    file_id_a: str
    file_id_b: str
    crossfade_duration: float  # seconds
    fade_type: str = "linear"  # "linear" or "logarithmic"
    normalize_bpm: bool = False  # stub: reserved for v2 BPM-matched crossfade
    align_beats: bool = False   # enable beat alignment + phrase snap + energy match
    eq_crossfade: bool = False  # enable bass-cut EQ during the crossfade region


def _crossfade_sync(
    file_id_a: str,
    file_id_b: str,
    crossfade_ms: int,
    fade_type: str,
) -> dict:
    """CPU-bound crossfade — runs in a thread pool via run_in_executor."""
    seg_a = pydub_from_file_id(file_id_a)
    seg_b = pydub_from_file_id(file_id_b)

    if crossfade_ms >= len(seg_a) or crossfade_ms >= len(seg_b):
        raise HTTPException(
            status_code=422,
            detail="crossfade_duration must be shorter than both audio tracks",
        )

    # Normalize to the higher sample rate and most channels before blending.
    # Without this, pydub silently produces corrupt output when e.g. track A
    # is 44100 Hz stereo and track B is 22050 Hz mono.
    target_sr = max(seg_a.frame_rate, seg_b.frame_rate)
    target_channels = max(seg_a.channels, seg_b.channels)
    seg_a = seg_a.set_frame_rate(target_sr).set_channels(target_channels)
    seg_b = seg_b.set_frame_rate(target_sr).set_channels(target_channels)

    if fade_type == "logarithmic":
        # Apply explicit fade_out / fade_in then hard-concat.
        # This gives a perceptual equal-loudness curve that prevents the
        # energy dip that linear crossfades produce in dance music.
        seg_a = seg_a.fade_out(crossfade_ms)
        seg_b = seg_b.fade_in(crossfade_ms)
        combined = seg_a + seg_b
    else:
        # pydub's append with crossfade applies a built-in equal-power
        # overlap-add blend — the correct level for a standard linear crossfade.
        combined = seg_a.append(seg_b, crossfade=crossfade_ms)

    new_id = str(uuid.uuid4())
    out_path = UPLOADS_DIR / f"{new_id}.wav"
    combined.export(str(out_path), format="wav")

    return {
        "new_file_id": new_id,
        "total_duration_seconds": round(len(combined) / 1000.0, 3),
        "crossfade_duration_seconds": crossfade_ms / 1000.0,
    }


@router.post("/crossfade")
async def crossfade(req: CrossfadeRequest) -> dict:
    validate_file_id(req.file_id_a)
    validate_file_id(req.file_id_b)

    if req.crossfade_duration <= 0:
        raise HTTPException(
            status_code=422, detail="crossfade_duration must be positive"
        )
    if req.fade_type not in {"linear", "logarithmic"}:
        raise HTTPException(
            status_code=422,
            detail="fade_type must be 'linear' or 'logarithmic'",
        )

    crossfade_ms = int(req.crossfade_duration * 1000)

    loop = asyncio.get_running_loop()
    if req.align_beats or req.eq_crossfade:
        result = await loop.run_in_executor(
            None,
            mix_segments,
            req.file_id_a,
            req.file_id_b,
            crossfade_ms,
            req.fade_type,
            req.align_beats,
            req.eq_crossfade,
        )
    else:
        result = await loop.run_in_executor(
            None,
            _crossfade_sync,
            req.file_id_a,
            req.file_id_b,
            crossfade_ms,
            req.fade_type,
        )
    logger.info(
        "Crossfaded %s + %s → %s (%.1fs %s fade, beats=%s eq=%s)",
        req.file_id_a,
        req.file_id_b,
        result["new_file_id"],
        req.crossfade_duration,
        req.fade_type,
        req.align_beats,
        req.eq_crossfade,
    )
    return result
