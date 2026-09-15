"""Offline replay and parameter search for the SmartCane fall detector.

The capture stream contains only fresh JY901S samples (normally 10 Hz), while
the firmware calls FallDetector::update every 20 ms.  Replay therefore holds
the latest recorded sample and evaluates it on a 20 ms decision timeline.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Iterable, Iterator, Sequence


@dataclass(frozen=True)
class ImuSample:
    t_ms: int
    a_g: float
    g_dps: float
    tilt_deg: float


@dataclass(frozen=True)
class Trial:
    trial_id: str
    label: str
    ground_truth: str
    source: Path
    samples: tuple[ImuSample, ...]


@dataclass(frozen=True)
class DetectorConfig:
    free_fall_g: float = 0.55
    impact_g: float = 2.20
    tilt_deg: float = 55.0
    still_gyro_dps: float = 35.0
    sequence_window_ms: int = 1500
    strict_hold_ms: int = 800
    deep_free_fall_g: float | None = None
    deep_hold_ms: int = 1000

    @property
    def mode(self) -> str:
        return "dual" if self.deep_free_fall_g is not None else "strict"


@dataclass(frozen=True)
class ReplayResult:
    detected: bool
    detected_at_ms: int | None
    path: str | None


@dataclass(frozen=True)
class ScanResult:
    config: DetectorConfig
    tp: int
    fn: int
    fp: int
    tn: int
    detections: tuple[ReplayResult, ...]

    @property
    def recall(self) -> float:
        total = self.tp + self.fn
        return self.tp / total if total else 0.0

    @property
    def false_positive_rate(self) -> float:
        total = self.fp + self.tn
        return self.fp / total if total else 0.0


def load_trials(capture_dir: Path) -> list[Trial]:
    trials: list[Trial] = []
    for source in sorted(capture_dir.glob("imu_*.csv")):
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            continue
        samples = tuple(
            ImuSample(
                t_ms=int(row["t_ms"]),
                a_g=float(row["a_g"]),
                g_dps=float(row["g_dps"]),
                tilt_deg=float(row["tilt_deg"]),
            )
            for row in rows
        )
        trials.append(
            Trial(
                trial_id=rows[0]["trial_id"],
                label=rows[0]["label"],
                ground_truth=rows[0]["ground_truth"],
                source=source,
                samples=samples,
            )
        )
    return trials


def replay_trial(
    trial: Trial,
    config: DetectorConfig,
    decision_period_ms: int = 20,
) -> ReplayResult:
    """Replay one recording from an idle detector and return its first event."""

    if not trial.samples:
        return ReplayResult(False, None, None)

    phase_active = False
    candidate_at: int | None = None
    impact_seen = False
    deep_seen = False
    strict_tilt_at: int | None = None
    deep_tilt_at: int | None = None

    sample_index = 0
    sample = trial.samples[0]
    start_ms = sample.t_ms
    end_ms = trial.samples[-1].t_ms

    # The real decision task has an arbitrary phase relative to the sensor.
    # Anchoring the first replay tick to the first captured sample introduces
    # at most one 20 ms tick of timing uncertainty, but preserves all 10 Hz
    # samples and the firmware's held-sample behavior.
    for now_ms in range(start_ms, end_ms + 1, decision_period_ms):
        while (
            sample_index + 1 < len(trial.samples)
            and trial.samples[sample_index + 1].t_ms <= now_ms
        ):
            sample_index += 1
            sample = trial.samples[sample_index]

        free_fall = sample.a_g <= config.free_fall_g
        impact = sample.a_g >= config.impact_g
        deep_free_fall = (
            config.deep_free_fall_g is not None
            and sample.a_g <= config.deep_free_fall_g
        )
        tilted_and_still = (
            sample.tilt_deg >= config.tilt_deg
            and sample.g_dps <= config.still_gyro_dps
        )

        # Match FallDetector.cpp: expiry is checked before the same held input
        # is allowed to begin another candidate.
        if (
            phase_active
            and candidate_at is not None
            and now_ms - candidate_at > config.sequence_window_ms
        ):
            phase_active = False
            candidate_at = None
            impact_seen = False
            deep_seen = False
            strict_tilt_at = None
            deep_tilt_at = None

        if not phase_active and (free_fall or impact or deep_free_fall):
            phase_active = True
            candidate_at = now_ms
            impact_seen = impact
            deep_seen = deep_free_fall
        elif phase_active:
            impact_seen = impact_seen or impact
            deep_seen = deep_seen or deep_free_fall

        if not phase_active:
            continue

        if impact_seen and tilted_and_still:
            if strict_tilt_at is None:
                strict_tilt_at = now_ms
        else:
            strict_tilt_at = None

        if deep_seen and tilted_and_still:
            if deep_tilt_at is None:
                deep_tilt_at = now_ms
        else:
            deep_tilt_at = None

        if (
            strict_tilt_at is not None
            and now_ms - strict_tilt_at >= config.strict_hold_ms
        ):
            return ReplayResult(True, now_ms, "strict")
        if (
            config.deep_free_fall_g is not None
            and deep_tilt_at is not None
            and now_ms - deep_tilt_at >= config.deep_hold_ms
        ):
            return ReplayResult(True, now_ms, "deep")

    return ReplayResult(False, None, None)


def evaluate(trials: Sequence[Trial], config: DetectorConfig) -> ScanResult:
    detections = tuple(replay_trial(trial, config) for trial in trials)
    tp = fn = fp = tn = 0
    for trial, detection in zip(trials, detections):
        is_fall = trial.ground_truth == "fall"
        if is_fall and detection.detected:
            tp += 1
        elif is_fall:
            fn += 1
        elif detection.detected:
            fp += 1
        else:
            tn += 1
    return ScanResult(config, tp, fn, fp, tn, detections)


def strict_grid() -> Iterator[DetectorConfig]:
    """Focused strict-rule grid around the current firmware settings."""

    for values in product(
        (0.45, 0.55, 0.65),
        (1.80, 2.00, 2.20, 2.40),
        (50.0, 55.0, 60.0),
        (25.0, 35.0, 45.0),
        (1500, 2000, 2500),
        (600, 800, 1000),
    ):
        yield DetectorConfig(
            free_fall_g=values[0],
            impact_g=values[1],
            tilt_deg=values[2],
            still_gyro_dps=values[3],
            sequence_window_ms=values[4],
            strict_hold_ms=values[5],
        )


def dual_grid() -> Iterator[DetectorConfig]:
    """Dual-path grid that retains the current strict thresholds."""

    for values in product(
        (50.0, 55.0, 60.0),
        (25.0, 35.0, 45.0),
        (1500, 2000, 2500, 3000),
        (600, 800, 1000),
        (0.25, 0.30, 0.35, 0.40, 0.45),
        (800, 1000, 1200, 1500),
    ):
        yield DetectorConfig(
            tilt_deg=values[0],
            still_gyro_dps=values[1],
            sequence_window_ms=values[2],
            strict_hold_ms=values[3],
            deep_free_fall_g=values[4],
            deep_hold_ms=values[5],
        )


def scan(
    trials: Sequence[Trial], configs: Iterable[DetectorConfig]
) -> list[ScanResult]:
    return [evaluate(trials, config) for config in configs]


CURRENT_CONFIG = DetectorConfig(
    still_gyro_dps=45.0,
    sequence_window_ms=2000,
    strict_hold_ms=600,
    deep_free_fall_g=0.40,
    deep_hold_ms=1200,
)
