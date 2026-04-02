"""
POST /remix/manual — timestamp-based manual remix.

The user specifies exact start/end times for each segment, an optional
target BPM, crossfade duration, and per-segment flags for skipping stretch
or replacing a crossfade with a hard cut. No AI is involved.
"""

import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from pydub import AudioSegment as _AudioSegment

from routers.analyze import _analyze_sync
from routers.crossfade import _crossfade_sync
from routers.loops import _extract_loop_sync
from routers.transform import _time_stretch_sync
from utils import UPLOADS_DIR, pydub_from_file_id, validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_SEGMENTS = 20


# ── Models ─────────────────────────────────────────────────────────────────────

class ManualSegment(BaseModel):
    file_id: str
    start_time: int          # milliseconds, >= 0
    end_time: int            # milliseconds, > start_time
    order: int               # >= 1, must form a contiguous sequence across all segments
    crossfade_with_next: bool = True
    # skip_stretch=True: exclude this segment from time-stretching even when
    # target_bpm is set. Use for dialogue clips, voiceovers, sound effects.
    skip_stretch: bool = False

    @field_validator("file_id")
    @classmethod
    def check_file_id(cls, v: str) -> str:
        try:
            validate_file_id(v)
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc
        return v

    @field_validator("order")
    @classmethod
    def check_order(cls, v: int) -> int:
        if v < 1:
            raise ValueError("order must be >= 1")
        return v

    @model_validator(mode="after")
    def check_time_range(self) -> "ManualSegment":
        if self.start_time < 0:
            raise ValueError("start_time must be >= 0")
        if self.end_time <= 0:
            raise ValueError("end_time must be > 0")
        if self.end_time <= self.start_time:
            raise ValueError(
                f"end_time ({self.end_time} ms) must be greater than "
                f"start_time ({self.start_time} ms)"
            )
        return self


class ManualRemixRequest(BaseModel):
    segments: list[ManualSegment]
    target_bpm: Optional[float] = None
    crossfade_seconds: float = 2.0
    fade_type: str = "linear"

    @field_validator("segments")
    @classmethod
    def check_segment_count(cls, v: list) -> list:
        if len(v) < 1:
            raise ValueError("At least 1 segment is required")
        if len(v) > _MAX_SEGMENTS:
            raise ValueError(f"Maximum {_MAX_SEGMENTS} segments allowed, got {len(v)}")
        return v

    @field_validator("target_bpm")
    @classmethod
    def check_target_bpm(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (20.0 < v < 300.0):
            raise ValueError("target_bpm must be between 20 and 300")
        return v

    @field_validator("crossfade_seconds")
    @classmethod
    def check_crossfade(cls, v: float) -> float:
        if v <= 0 or v > 30.0:
            raise ValueError("crossfade_seconds must be > 0 and <= 30")
        return v

    @field_validator("fade_type")
    @classmethod
    def check_fade_type(cls, v: str) -> str:
        if v not in ("linear", "logarithmic"):
            raise ValueError("fade_type must be 'linear' or 'logarithmic'")
        return v

    @model_validator(mode="after")
    def check_order_sequence(self) -> "ManualRemixRequest":
        orders = [s.order for s in self.segments]
        # Duplicate check
        seen, dupes = set(), set()
        for o in orders:
            (dupes if o in seen else seen).add(o)
        if dupes:
            raise ValueError(f"Duplicate order values: {sorted(dupes)}")
        # Contiguous-from-1 check
        sorted_orders = sorted(orders)
        expected = list(range(1, len(orders) + 1))
        if sorted_orders != expected:
            raise ValueError(
                f"order values must be contiguous starting from 1. "
                f"Got: {sorted_orders}, expected: {expected}"
            )
        return self


# ── Audio helpers ──────────────────────────────────────────────────────────────

def _hard_concat_sync(file_id_a: str, file_id_b: str) -> dict:
    """Concatenate two audio files with a hard cut (no overlap).

    Normalizes sample rate and channel count before joining so pydub does not
    silently produce corrupt output when the two files differ in format.
    """
    seg_a = pydub_from_file_id(file_id_a)
    seg_b = pydub_from_file_id(file_id_b)

    target_sr = max(seg_a.frame_rate, seg_b.frame_rate)
    target_ch = max(seg_a.channels, seg_b.channels)
    seg_a = seg_a.set_frame_rate(target_sr).set_channels(target_ch)
    seg_b = seg_b.set_frame_rate(target_sr).set_channels(target_ch)

    combined = seg_a + seg_b
    new_id = str(uuid.uuid4())
    out_path = UPLOADS_DIR / f"{new_id}.wav"
    combined.export(str(out_path), format="wav")

    return {
        "new_file_id": new_id,
        "total_duration_seconds": round(len(combined) / 1000.0, 3),
    }


def _cleanup(file_ids: set[str]) -> None:
    """Delete a set of intermediate files from UPLOADS_DIR."""
    for fid in file_ids:
        try:
            for path in UPLOADS_DIR.glob(f"{fid}.*"):
                path.unlink(missing_ok=True)
                logger.info("Cleaned up intermediate file %s", path.name)
        except Exception:
            logger.warning("Failed to clean up %s", fid, exc_info=True)


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/remix/manual")
async def remix_manual(req: ManualRemixRequest) -> dict:
    """
    Extract specific time ranges from one or more songs, optionally stretch them
    to a target BPM, and chain them together with crossfades or hard cuts.

    - 1 segment: returns the extracted (and optionally stretched) clip directly.
    - N segments: folds them together left-to-right using per-segment
      crossfade_with_next flags to choose between a crossfade and a hard cut at
      each join point.
    - skip_stretch=True on a segment excludes it from time-stretching even when
      target_bpm is set (for dialogue, voiceovers, short sound effects).
    """
    event_loop = asyncio.get_running_loop()
    sorted_segs = sorted(req.segments, key=lambda s: s.order)
    crossfade_ms = int(req.crossfade_seconds * 1000)

    # ── Pre-check: crossfade feasibility against expected durations ───────────
    # This fast check (no audio loaded) catches obvious misconfigurations.
    # _crossfade_sync also validates at execution time using real durations.
    if len(sorted_segs) > 1:
        for i, seg in enumerate(sorted_segs[:-1]):
            if not seg.crossfade_with_next:
                continue
            next_seg = sorted_segs[i + 1]
            seg_dur_ms = seg.end_time - seg.start_time
            next_dur_ms = next_seg.end_time - next_seg.start_time
            # For the very first crossfade both sides must be long enough.
            # For subsequent crossfades the accumulator grows, so only check
            # the incoming segment.
            if i == 0 and seg_dur_ms <= crossfade_ms:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "crossfade_exceeds_segment",
                        "detail": (
                            f"Segment order={seg.order} is {seg_dur_ms} ms but "
                            f"crossfade is {crossfade_ms} ms"
                        ),
                        "segment_order": seg.order,
                        "segment_duration_ms": seg_dur_ms,
                        "crossfade_ms": crossfade_ms,
                    },
                )
            if next_dur_ms <= crossfade_ms:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "crossfade_exceeds_segment",
                        "detail": (
                            f"Segment order={next_seg.order} is {next_dur_ms} ms but "
                            f"crossfade is {crossfade_ms} ms"
                        ),
                        "segment_order": next_seg.order,
                        "segment_duration_ms": next_dur_ms,
                        "crossfade_ms": crossfade_ms,
                    },
                )

    # All new file IDs created during this request. The final output file_id is
    # discarded from this set before cleanup so it is never deleted.
    intermediates: set[str] = set()

    try:
        # ── Step 1: Extract each segment ─────────────────────────────────────
        extracted: list[dict] = []
        for seg in sorted_segs:
            try:
                ext = await event_loop.run_in_executor(
                    None, _extract_loop_sync,
                    seg.file_id, seg.start_time, seg.end_time, 1,
                )
            except HTTPException as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "extraction_failed",
                        "segment_order": seg.order,
                        "file_id": seg.file_id,
                        "detail": str(exc.detail),
                    },
                ) from exc
            intermediates.add(ext["new_file_id"])
            extracted.append(ext)
            logger.info(
                "Extracted segment order=%d from %s [%dms–%dms] → %s",
                seg.order, seg.file_id, seg.start_time, seg.end_time,
                ext["new_file_id"],
            )

        # ── Step 2: Post-extract crossfade feasibility check (ground truth) ──
        if len(sorted_segs) > 1:
            for i, seg in enumerate(sorted_segs[:-1]):
                if not seg.crossfade_with_next:
                    continue
                next_ext = extracted[i + 1]
                actual_ms = int(next_ext["loop_duration_seconds"] * 1000)
                if actual_ms <= crossfade_ms:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "error": "crossfade_exceeds_segment",
                            "detail": (
                                f"Segment order={sorted_segs[i + 1].order} is only "
                                f"{next_ext['loop_duration_seconds']:.2f}s after extraction, "
                                f"shorter than the {req.crossfade_seconds}s crossfade."
                            ),
                            "segment_order": sorted_segs[i + 1].order,
                            "extracted_duration_seconds": next_ext["loop_duration_seconds"],
                            "crossfade_seconds": req.crossfade_seconds,
                        },
                    )

        # ── Step 3: Analyze parent BPMs in parallel, then stretch ─────────────
        # Use the parent file's BPM — the extracted clip is a time window of the
        # parent and has the same tempo. Analyzing the clip would add latency for
        # no accuracy gain on constant-tempo tracks.
        processed_ids: list[str] = []
        segment_meta: list[dict] = []

        if req.target_bpm is not None:
            segs_to_analyze = [
                (i, seg) for i, seg in enumerate(sorted_segs)
                if not seg.skip_stretch
            ]
            if segs_to_analyze:
                analyses = await asyncio.gather(*[
                    event_loop.run_in_executor(None, _analyze_sync, seg.file_id)
                    for _, seg in segs_to_analyze
                ])
                bpm_by_idx: dict[int, float] = {
                    idx: a["bpm"] for (idx, _), a in zip(segs_to_analyze, analyses)
                }
            else:
                bpm_by_idx = {}

            for i, (seg, ext) in enumerate(zip(sorted_segs, extracted)):
                if seg.skip_stretch:
                    processed_ids.append(ext["new_file_id"])
                    segment_meta.append(_seg_meta(
                        seg, ext,
                        stretched=False,
                        skip_stretch=True,
                        original_bpm=None,
                        stretch_ratio=None,
                        stretched_file_id=None,
                    ))
                else:
                    orig_bpm = bpm_by_idx[i]
                    try:
                        sr = await event_loop.run_in_executor(
                            None, _time_stretch_sync,
                            ext["new_file_id"], req.target_bpm, orig_bpm,
                        )
                    except HTTPException as exc:
                        raise HTTPException(
                            status_code=422,
                            detail={
                                "error": "stretch_ratio_out_of_range",
                                "segment_order": seg.order,
                                "original_bpm": orig_bpm,
                                "target_bpm": req.target_bpm,
                                "detail": str(exc.detail),
                            },
                        ) from exc

                    new_fid = sr["new_file_id"]
                    actually_stretched = not sr["no_change"]
                    if actually_stretched:
                        intermediates.add(new_fid)
                    processed_ids.append(new_fid)
                    segment_meta.append(_seg_meta(
                        seg, ext,
                        stretched=actually_stretched,
                        skip_stretch=False,
                        original_bpm=sr["original_bpm"],
                        stretch_ratio=sr["stretch_ratio"] if actually_stretched else None,
                        stretched_file_id=new_fid if actually_stretched else None,
                    ))
        else:
            for seg, ext in zip(sorted_segs, extracted):
                processed_ids.append(ext["new_file_id"])
                segment_meta.append(_seg_meta(
                    seg, ext,
                    stretched=False,
                    skip_stretch=seg.skip_stretch,
                    original_bpm=None,
                    stretch_ratio=None,
                    stretched_file_id=None,
                ))

        # ── Step 4: Chain segments ────────────────────────────────────────────
        if len(processed_ids) == 1:
            final_file_id = processed_ids[0]
            total_duration = extracted[0]["loop_duration_seconds"]
        else:
            accumulator = processed_ids[0]
            last_chain_result: dict = {}

            for i in range(len(processed_ids) - 1):
                seg = sorted_segs[i]
                next_file = processed_ids[i + 1]

                if seg.crossfade_with_next:
                    try:
                        chain_result = await event_loop.run_in_executor(
                            None, _crossfade_sync,
                            accumulator, next_file, crossfade_ms, req.fade_type,
                        )
                    except HTTPException as exc:
                        raise HTTPException(
                            status_code=422,
                            detail={
                                "error": "crossfade_failed",
                                "segment_order": seg.order,
                                "detail": str(exc.detail),
                            },
                        ) from exc
                else:
                    chain_result = await event_loop.run_in_executor(
                        None, _hard_concat_sync, accumulator, next_file,
                    )

                new_acc = chain_result["new_file_id"]
                # The previous accumulator (not the initial segment) is now
                # consumed — it is a pure intermediate.
                if i > 0:
                    intermediates.add(accumulator)
                accumulator = new_acc
                last_chain_result = chain_result

            final_file_id = accumulator
            total_duration = last_chain_result["total_duration_seconds"]

        # ── Step 5: Clean up intermediates, protect the output ───────────────
        intermediates.discard(final_file_id)
        _cleanup(intermediates)

        logger.info(
            "Manual remix complete: %d segment(s), output=%s, duration=%.1fs",
            len(sorted_segs), final_file_id, total_duration,
        )

        return {
            "final_file_id": final_file_id,
            "total_duration_seconds": round(total_duration, 3),
            "target_bpm": req.target_bpm,
            "crossfade_seconds": req.crossfade_seconds,
            "fade_type": req.fade_type,
            "segments": segment_meta,
        }

    except HTTPException:
        intermediates.discard(final_file_id if "final_file_id" in dir() else "")
        _cleanup(intermediates)
        raise
    except Exception as exc:
        _cleanup(intermediates)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "detail": str(exc)},
        ) from exc


# ── Private helper ─────────────────────────────────────────────────────────────

def _seg_meta(
    seg: ManualSegment,
    ext: dict,
    stretched: bool,
    skip_stretch: bool,
    original_bpm: Optional[float],
    stretch_ratio: Optional[float],
    stretched_file_id: Optional[str],
) -> dict:
    return {
        "order": seg.order,
        "original_file_id": seg.file_id,
        "start_time": seg.start_time,
        "end_time": seg.end_time,
        "extracted_file_id": ext["new_file_id"],
        "extracted_duration_seconds": ext["loop_duration_seconds"],
        "crossfade_with_next": seg.crossfade_with_next,
        "stretched": stretched,
        "skip_stretch": skip_stretch,
        "original_bpm": original_bpm,
        "stretch_ratio": stretch_ratio,
        "stretched_file_id": stretched_file_id,
    }
