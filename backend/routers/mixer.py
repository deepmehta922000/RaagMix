"""
Professional-quality audio mixing engine.

mix_segments() is the upgraded crossfade pipeline used by remix and remix_manual.
It adds beat alignment, phrase boundary snapping, EQ crossfade, energy
matching, and optional vocal ducking on top of the basic volume crossfade.

The original _crossfade_sync in crossfade.py is left unchanged for backward
compatibility with direct /crossfade API calls.
"""

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

import librosa
import numpy as np
from fastapi import HTTPException
from pydub import AudioSegment
from pydub.scipy_effects import high_pass_filter

from utils import UPLOADS_DIR, get_upload_path, pydub_from_file_id

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

BEATS_PER_BAR = 4
PHRASE_BARS = 8                # snap to 8-bar (32-beat) phrase boundaries
PHRASE_SNAP_WINDOW_BARS = 4    # allow snapping within ±4 bars of a boundary
MAX_GAIN_DB = 6.0              # energy-matching gain cap in each direction
EQ_BASS_HARD_HZ = 200          # HP cutoff for first 75 % of crossfade (hard bass cut)
EQ_BASS_SOFT_HZ = 80           # HP cutoff for last 25 % (bass returning)

_BEATS_PER_PHRASE = BEATS_PER_BAR * PHRASE_BARS          # 32
_SNAP_WINDOW_BEATS = BEATS_PER_BAR * PHRASE_SNAP_WINDOW_BARS  # 16


# ── Beat detection ─────────────────────────────────────────────────────────────

def _detect_beats(file_id: str) -> tuple[float, np.ndarray]:
    """Return (bpm, beat_times_seconds) for the audio file at file_id.

    Uses librosa's dynamic-programming beat tracker, which is more robust for
    Bollywood tracks with percussion-heavy intros than the basic autocorrelation.
    sr=None preserves the native sample rate; mono=True is required by the
    beat tracker.
    """
    path = get_upload_path(file_id)
    y, sr = librosa.load(str(path), sr=None, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    return bpm, beat_times


# ── Phrase snapping ────────────────────────────────────────────────────────────

def _snap_to_phrase_boundary(
    desired_ms: int,
    beat_times: np.ndarray,
) -> int:
    """Snap desired_ms to the nearest 8-bar phrase boundary within ±4 bars.

    A phrase boundary is every _BEATS_PER_PHRASE beats (32 beats = 8 bars at 4/4).
    The snap window is ±_SNAP_WINDOW_BEATS (16 beats = 4 bars).

    Returns desired_ms unchanged if no boundary is close enough or beat_times
    is too short to find phrase boundaries.
    """
    if len(beat_times) < _BEATS_PER_PHRASE:
        return desired_ms

    desired_sec = desired_ms / 1000.0

    # Every 32nd beat is a phrase boundary
    phrase_boundaries = beat_times[::_BEATS_PER_PHRASE]  # shape: (n_phrases,)

    diffs = np.abs(phrase_boundaries - desired_sec)
    nearest_idx = int(np.argmin(diffs))
    nearest_sec = float(phrase_boundaries[nearest_idx])

    # Snap window in seconds (use median beat duration to be robust to tempo drift)
    beat_dur_sec = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 0.5
    window_sec = _SNAP_WINDOW_BEATS * beat_dur_sec

    if abs(nearest_sec - desired_sec) > window_sec:
        return desired_ms  # no suitable boundary within the window

    snapped_ms = int(nearest_sec * 1000)
    if snapped_ms != desired_ms:
        logger.info(
            "Phrase snap: %d ms → %d ms (boundary %.2f s, delta %+.2f s)",
            desired_ms,
            snapped_ms,
            nearest_sec,
            nearest_sec - desired_sec,
        )
    return snapped_ms


# ── Beat-phase alignment ───────────────────────────────────────────────────────

def _compute_beat_trim_ms(
    beats_a: np.ndarray,
    beats_b: np.ndarray,
    crossfade_start_ms: int,
) -> int:
    """Milliseconds to trim from Song B's front so its beats align with Song A.

    At the crossfade start, Song A is at a particular phase in its beat grid.
    We find the next beat of Song A inside the crossfade region and compute how
    much to trim from Song B so that a Song B beat lands at exactly the same
    moment.

    The trim is always in [0, one_beat_period_B) so it never exceeds one beat.
    Returns 0 if alignment cannot be computed (too few beats, degenerate data).
    """
    if len(beats_a) < 2 or len(beats_b) < 2:
        return 0

    crossfade_start_sec = crossfade_start_ms / 1000.0
    beat_period_b = float(np.median(np.diff(beats_b)))
    if beat_period_b <= 0:
        return 0

    # Next beat of Song A at or after the crossfade start
    future_a = beats_a[beats_a >= crossfade_start_sec]
    if len(future_a) == 0:
        return 0
    next_a_beat_sec = float(future_a[0])

    # Target: a Song B beat should land this many seconds into Song B's playback
    target_sec = next_a_beat_sec - crossfade_start_sec

    # Song B's first beat sits at beats_b[0] seconds from its own start.
    # We need: beats_b[0] - trim_sec ≡ target_sec  (mod beat_period_b)
    # → trim_sec = (beats_b[0] - target_sec) mod beat_period_b
    trim_sec = (float(beats_b[0]) - target_sec) % beat_period_b
    trim_ms = int(trim_sec * 1000)

    if trim_ms > 0:
        logger.info(
            "Beat alignment: trim %d ms from Song B "
            "(first beat %.3f s → target %.3f s, period %.3f s)",
            trim_ms,
            float(beats_b[0]),
            target_sec,
            beat_period_b,
        )
    return trim_ms


# ── Energy matching ────────────────────────────────────────────────────────────

def _energy_gain_db(seg_a_tail: AudioSegment, seg_b_head: AudioSegment) -> float:
    """Gain in dB to apply to Song B so its RMS matches Song A's tail.

    Capped at ±MAX_GAIN_DB to prevent distortion on extreme mismatches.
    Returns 0.0 if either segment is silent (dBFS = −∞).
    """
    rms_a = seg_a_tail.dBFS
    rms_b = seg_b_head.dBFS
    if not (np.isfinite(rms_a) and np.isfinite(rms_b)):
        return 0.0
    gain = rms_a - rms_b
    return float(np.clip(gain, -MAX_GAIN_DB, MAX_GAIN_DB))


# ── EQ crossfade ──────────────────────────────────────────────────────────────

def _apply_eq_crossfade(seg_b: AudioSegment, crossfade_ms: int) -> AudioSegment:
    """Bass-cut Song B's fade-in region to prevent muddiness during the blend.

    Splits the crossfade region into two sub-zones:
    - First 75 % → hard HP at EQ_BASS_HARD_HZ (200 Hz): both basslines gone,
      preventing the double kick-drum thud that ruins linear crossfades.
    - Last 25 %  → soft HP at EQ_BASS_SOFT_HZ (80 Hz): bass from 80–200 Hz
      returns, creating a "bass drop" feel at the end of the transition.
    - Body (everything after crossfade_ms) → untouched.

    This mirrors the DJ technique of killing the EQ bass during the blend and
    bringing it in on the downbeat.
    """
    if crossfade_ms <= 0 or len(seg_b) <= crossfade_ms:
        return seg_b

    hard_ms = int(crossfade_ms * 0.75)
    soft_ms = crossfade_ms - hard_ms  # remaining 25 %

    hard_region = seg_b[:hard_ms]
    soft_region = seg_b[hard_ms:crossfade_ms]
    body = seg_b[crossfade_ms:]

    hard_eq = high_pass_filter(hard_region, EQ_BASS_HARD_HZ)
    soft_eq = high_pass_filter(soft_region, EQ_BASS_SOFT_HZ)

    return hard_eq + soft_eq + body


# ── Vocal duck ─────────────────────────────────────────────────────────────────

# Module-level cache so the Spleeter model is loaded only once per process.
_spleeter_separator = None


def _get_spleeter_separator():
    global _spleeter_separator
    if _spleeter_separator is None:
        from spleeter.separator import Separator
        _spleeter_separator = Separator("spleeter:2stems")
    return _spleeter_separator


def _duck_vocals_region(seg: AudioSegment) -> AudioSegment:
    """Return the accompaniment-only version of a segment using Spleeter.

    Writes the segment to a temp WAV, runs Spleeter 2-stem separation, reads
    back the accompaniment stem, and resamples to match the original segment's
    sample rate and channel count.

    Falls back to returning the original segment unchanged if Spleeter is not
    installed or if separation fails for any reason.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        tmp_wav = tmp_dir / "input.wav"
        seg.export(str(tmp_wav), format="wav")

        separator = _get_spleeter_separator()
        out_dir = tmp_dir / "stems"
        separator.separate_to_file(str(tmp_wav), str(out_dir))

        acc_path = out_dir / "input" / "accompaniment.wav"
        if not acc_path.exists():
            logger.warning("Spleeter accompaniment output missing; returning original")
            return seg

        acc = AudioSegment.from_wav(str(acc_path))
        # Re-match sample rate and channels to the original segment
        acc = acc.set_frame_rate(seg.frame_rate).set_channels(seg.channels)
        return acc

    except ImportError:
        logger.warning("Spleeter not installed; skipping vocal duck (pip install spleeter)")
        return seg
    except Exception:
        logger.warning("Vocal duck failed; returning original segment", exc_info=True)
        return seg
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Main mixing function ───────────────────────────────────────────────────────

def mix_segments(
    file_id_a: str,
    file_id_b: str,
    crossfade_ms: int,
    fade_type: str,
    align_beats: bool = True,
    eq_crossfade: bool = True,
    vocal_duck: bool = False,
) -> dict:
    """Professional crossfade: beat alignment + EQ + phrase snap + energy match.

    Drop-in replacement for _crossfade_sync — returns the same mandatory keys
    (new_file_id, total_duration_seconds, crossfade_duration_seconds) plus
    diagnostic keys (beat_offset_ms, phrase_snap_ms, gain_db, vocal_duck).

    Processing pipeline (when flags are True):
    1.  Load both files; normalise to the higher sample rate and channel count.
    2.  Beat detection (librosa) on both files.
    3.  Phrase snap: move the crossfade start of Song A to the nearest 8-bar
        phrase boundary (within ±4 bars), trimming A accordingly.
    4.  Beat-phase alignment: trim Song B's intro so its first beat lands on
        Song A's beat grid at the crossfade point.
    4b. Vocal duck: replace A's crossfade tail and B's crossfade head with
        accompaniment-only stems (Spleeter), so only instrumentals overlap.
    5.  Energy matching: apply ±≤6 dB gain to Song B so intro RMS ≈ outro RMS.
    6.  EQ crossfade: high-pass Song B's crossfade region (200 Hz hard cut for
        first 75 %, 80 Hz soft cut for last 25 %).
    7.  Volume crossfade (linear: pydub overlap-add; logarithmic: fade + concat).
    8.  Export to WAV in UPLOADS_DIR.
    """
    # ── 1. Load and normalise ──────────────────────────────────────────────────
    seg_a = pydub_from_file_id(file_id_a)
    seg_b = pydub_from_file_id(file_id_b)

    target_sr = max(seg_a.frame_rate, seg_b.frame_rate)
    target_ch = max(seg_a.channels, seg_b.channels)
    seg_a = seg_a.set_frame_rate(target_sr).set_channels(target_ch)
    seg_b = seg_b.set_frame_rate(target_sr).set_channels(target_ch)

    if crossfade_ms >= len(seg_a) or crossfade_ms >= len(seg_b):
        raise HTTPException(
            status_code=422,
            detail="crossfade_duration must be shorter than both audio tracks",
        )

    beat_offset_ms = 0
    phrase_snap_ms = 0
    gain_db = 0.0

    # ── 2–4. Beat detection, phrase snap, beat alignment ──────────────────────
    if align_beats:
        beats_a: np.ndarray = np.array([])
        beats_b: np.ndarray = np.array([])
        try:
            _, beats_a = _detect_beats(file_id_a)
            _, beats_b = _detect_beats(file_id_b)
        except Exception:
            logger.warning(
                "Beat detection failed for %s / %s; skipping alignment",
                file_id_a, file_id_b,
                exc_info=True,
            )

        # Phrase snap: adjust how much of Song A we keep
        if len(beats_a) >= _BEATS_PER_PHRASE:
            original_start_ms = len(seg_a) - crossfade_ms
            snapped_start_ms = _snap_to_phrase_boundary(original_start_ms, beats_a)

            # Guard: trimmed A must still be long enough to hold the crossfade
            if (
                snapped_start_ms != original_start_ms
                and 0 <= snapped_start_ms
                and snapped_start_ms + crossfade_ms <= len(seg_a)
            ):
                phrase_snap_ms = snapped_start_ms - original_start_ms
                seg_a = seg_a[: snapped_start_ms + crossfade_ms]

        # Beat-phase alignment: trim Song B's front
        if len(beats_b) >= 2:
            crossfade_start_ms = len(seg_a) - crossfade_ms
            beat_offset_ms = _compute_beat_trim_ms(beats_a, beats_b, crossfade_start_ms)
            # Only trim if Song B remains longer than the crossfade after trimming
            if beat_offset_ms > 0 and (len(seg_b) - beat_offset_ms) > crossfade_ms:
                seg_b = seg_b[beat_offset_ms:]

    # ── 4b. Vocal duck ────────────────────────────────────────────────────────
    if vocal_duck:
        try:
            # Replace Song A's crossfade tail with accompaniment only
            cf_start_a = len(seg_a) - crossfade_ms
            if cf_start_a > 0:
                a_tail = _duck_vocals_region(seg_a[cf_start_a:])
                seg_a = seg_a[:cf_start_a] + a_tail

            # Replace Song B's crossfade head with accompaniment only;
            # the body plays on untouched so vocals return after the transition
            if len(seg_b) > crossfade_ms:
                b_head = _duck_vocals_region(seg_b[:crossfade_ms])
                seg_b = b_head + seg_b[crossfade_ms:]

            logger.info("Vocal duck applied to crossfade regions of %s and %s", file_id_a, file_id_b)
        except Exception:
            logger.warning("Vocal duck step failed; continuing without", exc_info=True)

    # ── 5. Energy matching ────────────────────────────────────────────────────
    measure_ms = min(crossfade_ms, len(seg_a), len(seg_b))
    gain_db = _energy_gain_db(seg_a[-measure_ms:], seg_b[:measure_ms])
    if abs(gain_db) > 0.5:  # skip trivial adjustments
        seg_b = seg_b.apply_gain(gain_db)
        logger.info("Energy match: %.1f dB applied to Song B", gain_db)

    # ── 6. EQ crossfade ───────────────────────────────────────────────────────
    if eq_crossfade:
        seg_b = _apply_eq_crossfade(seg_b, crossfade_ms)

    # ── 7. Volume crossfade ───────────────────────────────────────────────────
    if fade_type == "logarithmic":
        # Explicit fade_out / fade_in then hard-concat gives a perceptual
        # equal-loudness curve; pydub's append does linear overlap-add.
        seg_a = seg_a.fade_out(crossfade_ms)
        seg_b = seg_b.fade_in(crossfade_ms)
        combined = seg_a + seg_b
    else:
        combined = seg_a.append(seg_b, crossfade=crossfade_ms)

    # ── 8. Export ─────────────────────────────────────────────────────────────
    new_id = str(uuid.uuid4())
    out_path = UPLOADS_DIR / f"{new_id}.wav"
    combined.export(str(out_path), format="wav")

    logger.info(
        "mix_segments: %s + %s → %s  (%.1f s, beat_offset=%d ms, "
        "phrase_snap=%+d ms, gain=%.1f dB, vocal_duck=%s)",
        file_id_a,
        file_id_b,
        new_id,
        len(combined) / 1000.0,
        beat_offset_ms,
        phrase_snap_ms,
        gain_db,
        vocal_duck,
    )

    return {
        "new_file_id": new_id,
        "total_duration_seconds": round(len(combined) / 1000.0, 3),
        "crossfade_duration_seconds": crossfade_ms / 1000.0,
        "beat_offset_ms": beat_offset_ms,
        "phrase_snap_ms": phrase_snap_ms,
        "gain_db": round(gain_db, 2),
        "vocal_duck": vocal_duck,
    }
