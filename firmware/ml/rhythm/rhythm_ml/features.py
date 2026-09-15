from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

import numpy as np


TARGET_SAMPLE_HZ = 25
WINDOW_SECONDS = 15.0
STEP_SECONDS = 5.0
MIN_IBI_COUNT = 12

FEATURE_NAMES = (
    "ibi_cv",
    "rmssd_ratio",
    "pnn50",
    "max_jump_ratio",
    "signal_quality",
    "hr_out_of_range",
)

# Keep these constants synchronized with VitalsProcessor.cpp.
DC_ALPHA = 0.02
FILTER_ALPHA = 0.25
ENVELOPE_ALPHA = 0.02
PEAK_ENVELOPE_RATIO = 0.35
MIN_PEAK_AMPLITUDE = 80.0
PEAK_PROMINENCE_RATIO = 0.35
MIN_PEAK_PROMINENCE = 80.0
ADAPTIVE_REFRACTORY_RATIO = 0.60
ADAPTIVE_REFRACTORY_MAX_MS = 500.0
ADAPTIVE_REFRACTORY_MAX_CV = 0.25
EARLY_PEAK_STRONG_PROMINENCE_RATIO = 0.90
ADAPTIVE_REFRACTORY_MIN_IBI_COUNT = 3
MIN_HEART_RATE_BPM = 40.0
MAX_HEART_RATE_BPM = 180.0


@dataclass(frozen=True)
class BeatSeries:
    peak_ms: np.ndarray
    ibi_ms: np.ndarray
    orientation: int


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def heart_rate_out_of_range(bpm: float) -> float:
    if not np.isfinite(bpm):
        return 1.0
    if bpm < 50.0:
        return _clamp01((50.0 - bpm) / 30.0)
    if bpm > 110.0:
        return _clamp01((bpm - 110.0) / 70.0)
    return 0.0


def feature_vector(
    ibi_ms: Iterable[float], signal_quality: float = 1.0
) -> np.ndarray:
    ibi = np.asarray(tuple(ibi_ms), dtype=np.float64)
    if ibi.size < 2 or not np.all(np.isfinite(ibi)):
        raise ValueError("at least two finite IBI values are required")
    mean = float(np.mean(ibi))
    if mean <= 0.0:
        raise ValueError("mean IBI must be positive")
    adjacent = np.abs(np.diff(ibi))
    std = float(np.sqrt(np.mean(np.square(ibi - mean))))
    rmssd = float(np.sqrt(np.mean(np.square(adjacent))))
    pnn50 = float(np.mean(adjacent > 50.0))
    max_jump = float(np.max(adjacent))
    representative_ibi = float(np.median(ibi[-8:]))
    bpm = 60000.0 / representative_ibi
    return np.asarray(
        (
            std / mean,
            rmssd / mean,
            pnn50,
            max_jump / mean,
            _clamp01(signal_quality),
            heart_rate_out_of_range(bpm),
        ),
        dtype=np.float64,
    )


def quantize_features(values: Iterable[float]) -> np.ndarray:
    """Mirror RhythmClassifier.cpp quantize01() and feature transforms."""
    v = np.asarray(tuple(values), dtype=np.float64)
    if v.shape != (6,):
        raise ValueError(f"expected six features, got shape {v.shape}")
    normalized = np.asarray(
        (
            (v[0] - 0.015) / 0.285,
            (v[1] - 0.015) / 0.285,
            v[2],
            (v[3] - 0.04) / 0.76,
            v[4],
            v[5],
        ),
        dtype=np.float64,
    )
    normalized = np.clip(normalized, 0.0, 1.0)
    # C++ lroundf is half-away-from-zero. Inputs are non-negative.
    return np.floor(normalized * 127.0 + 0.5).astype(np.uint8)


def estimate_sample_rate(time_seconds: np.ndarray) -> float:
    t = np.asarray(time_seconds, dtype=np.float64)
    differences = np.diff(t)
    differences = differences[np.isfinite(differences) & (differences > 0.0)]
    if differences.size == 0:
        raise ValueError("recording has no increasing timestamps")
    return float(1.0 / np.median(differences))


def resample_ppg(
    ppg: np.ndarray, source_hz: float, target_hz: int = TARGET_SAMPLE_HZ
) -> np.ndarray:
    """Anti-aliased rational resampling; 125 Hz input becomes exactly 25 Hz."""
    from scipy.signal import resample_poly

    values = np.asarray(ppg, dtype=np.float64)
    finite = np.isfinite(values)
    if finite.mean() < 0.90:
        raise ValueError("more than 10% of PPG samples are missing")
    if not np.all(finite):
        indices = np.arange(values.size)
        values = np.interp(indices, indices[finite], values[finite])
    ratio = Fraction(target_hz / source_hz).limit_denominator(1000)
    return np.asarray(resample_poly(values, ratio.numerator, ratio.denominator))


def _pseudo_ir(ppg: np.ndarray, orientation: int) -> np.ndarray:
    values = np.asarray(ppg, dtype=np.float64) * float(orientation)
    low, high = np.percentile(values, (5.0, 95.0))
    span = float(high - low)
    if not np.isfinite(span) or span <= 1e-9:
        raise ValueError("PPG recording is flat")
    centered = (values - float(np.median(values))) / span
    # Public PPG units differ from MAX30102 ADC counts. A fixed pseudo-ADC
    # mapping preserves waveform timing while satisfying the firmware's
    # absolute minimum prominence. SQI remains an external gate and receives
    # zero model weight during training.
    return 100000.0 + np.clip(centered, -3.0, 3.0) * 20000.0


def _history_cv(history: list[float]) -> float:
    if len(history) < 2:
        return 1.0
    mean = float(np.mean(history))
    return float(np.std(history) / mean) if mean > 0.0 else 1.0


def _detect_one_orientation(ppg_25hz: np.ndarray, orientation: int) -> BeatSeries:
    samples = _pseudo_ir(ppg_25hz, orientation)
    red_dc = ir_dc = filtered = envelope = 0.0
    trough = previous = previous_previous = 0.0
    previous_at_ms = 0
    last_peak_ms = 0
    initialized = False
    recent_ibi: list[float] = []
    peak_times: list[float] = []
    intervals: list[float] = []

    min_ibi = int(60000.0 / MAX_HEART_RATE_BPM)
    max_ibi = int(60000.0 / MIN_HEART_RATE_BPM)

    for index, raw in enumerate(samples):
        now_ms = int(round(index * 1000.0 / TARGET_SAMPLE_HZ))
        if not initialized:
            red_dc = ir_dc = float(raw)
            initialized = True
            continue

        red_dc += DC_ALPHA * (float(raw) - red_dc)
        ir_dc += DC_ALPHA * (float(raw) - ir_dc)
        ir_ac = float(raw) - ir_dc
        filtered += FILTER_ALPHA * (ir_ac - filtered)
        envelope += ENVELOPE_ALPHA * (abs(filtered) - envelope)
        trough = min(trough, previous)

        candidate = (
            previous_at_ms != 0
            and previous > previous_previous
            and previous >= filtered
            and previous >= max(MIN_PEAK_AMPLITUDE, envelope * PEAK_ENVELOPE_RATIO)
        )
        if candidate:
            prominence = previous - trough
            if prominence >= max(
                MIN_PEAK_PROMINENCE, envelope * PEAK_PROMINENCE_RATIO
            ):
                changed_anchor = False
                if last_peak_ms == 0:
                    last_peak_ms = previous_at_ms
                    changed_anchor = True
                else:
                    ibi = previous_at_ms - last_peak_ms
                    if ibi >= min_ibi:
                        adaptive_min = min_ibi
                        if (
                            len(recent_ibi) >= ADAPTIVE_REFRACTORY_MIN_IBI_COUNT
                            and _history_cv(recent_ibi) <= ADAPTIVE_REFRACTORY_MAX_CV
                        ):
                            adaptive_min = max(
                                min_ibi,
                                int(
                                    min(
                                        ADAPTIVE_REFRACTORY_MAX_MS,
                                        np.median(recent_ibi)
                                        * ADAPTIVE_REFRACTORY_RATIO,
                                    )
                                ),
                            )
                        prominence_ratio = prominence / max(envelope, 1.0)
                        if not (
                            ibi < adaptive_min
                            and prominence_ratio
                            < EARLY_PEAK_STRONG_PROMINENCE_RATIO
                        ):
                            last_peak_ms = previous_at_ms
                            changed_anchor = True
                            if ibi > max_ibi:
                                recent_ibi.clear()
                            else:
                                recent_ibi.append(float(ibi))
                                recent_ibi = recent_ibi[-8:]
                                peak_times.append(float(previous_at_ms))
                                intervals.append(float(ibi))
                if changed_anchor:
                    trough = previous

        previous_previous = previous
        previous = filtered
        previous_at_ms = now_ms

    return BeatSeries(
        peak_ms=np.asarray(peak_times, dtype=np.float64),
        ibi_ms=np.asarray(intervals, dtype=np.float64),
        orientation=orientation,
    )


def detect_firmware_beats(ppg_25hz: np.ndarray) -> BeatSeries:
    """Run both PPG polarities and keep the one yielding more usable beats."""
    positive = _detect_one_orientation(ppg_25hz, 1)
    negative = _detect_one_orientation(ppg_25hz, -1)
    return positive if positive.ibi_ms.size >= negative.ibi_ms.size else negative


def window_rows(
    beats: BeatSeries,
    duration_seconds: float,
    subject_id: str,
    label: int,
) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    if beats.ibi_ms.size == 0:
        return rows
    for end_seconds in np.arange(
        WINDOW_SECONDS, duration_seconds + 1e-6, STEP_SECONDS
    ):
        end_ms = end_seconds * 1000.0
        start_ms = end_ms - WINDOW_SECONDS * 1000.0
        mask = (beats.peak_ms > start_ms) & (beats.peak_ms <= end_ms)
        ibi = beats.ibi_ms[mask]
        peak_ms = beats.peak_ms[mask]
        if ibi.size < MIN_IBI_COUNT:
            continue
        if peak_ms.size == 0 or end_ms - peak_ms[-1] > 3000.0:
            continue
        features = feature_vector(ibi, signal_quality=1.0)
        quantized = quantize_features(features)
        row: dict[str, float | int | str] = {
            "subject_id": subject_id,
            "label": int(label),
            "window_end_s": float(end_seconds),
            "beat_count": int(ibi.size),
            "orientation": int(beats.orientation),
        }
        row.update({name: float(value) for name, value in zip(FEATURE_NAMES, features)})
        row.update({f"q_{name}": int(value) for name, value in zip(FEATURE_NAMES, quantized)})
        rows.append(row)
    return rows

