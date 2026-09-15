"""Run the SmartCane fall-detector grid search against recorded IMU trials."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from smartcane_host.fall_replay import (
    CURRENT_CONFIG,
    DetectorConfig,
    ScanResult,
    dual_grid,
    evaluate,
    load_trials,
    scan,
    strict_grid,
)


def _result_dict(result: ScanResult, trials) -> dict:
    missed = [
        trial.trial_id
        for trial, detection in zip(trials, result.detections)
        if trial.ground_truth == "fall" and not detection.detected
    ]
    false_alarms = [
        trial.trial_id
        for trial, detection in zip(trials, result.detections)
        if trial.ground_truth == "normal" and detection.detected
    ]
    paths = {
        trial.trial_id: detection.path
        for trial, detection in zip(trials, result.detections)
        if detection.detected
    }
    return {
        "config": asdict(result.config),
        "tp": result.tp,
        "fn": result.fn,
        "fp": result.fp,
        "tn": result.tn,
        "recall": round(result.recall, 6),
        "false_positive_rate": round(result.false_positive_rate, 6),
        "missed": missed,
        "false_alarms": false_alarms,
        "paths": paths,
    }


def _rank_key(result: ScanResult) -> tuple:
    config = result.config
    deep_margin = (
        -config.deep_free_fall_g
        if config.deep_free_fall_g is not None
        else -1.0
    )
    return (
        result.fp,
        -result.tp,
        0 if config.mode == "strict" else 1,
        deep_margin,
        -config.impact_g,
        -config.tilt_deg,
        config.sequence_window_ms,
        config.strict_hold_ms,
        config.deep_hold_ms,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "imu_captures",
    )
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()

    trials = load_trials(args.capture_dir)
    if not trials:
        raise SystemExit(f"No imu_*.csv files found in {args.capture_dir}")

    baseline = evaluate(trials, CURRENT_CONFIG)
    strict_results = scan(trials, strict_grid())
    dual_results = scan(trials, dual_grid())
    all_results = strict_results + dual_results
    perfect = [result for result in all_results if result.fn == 0 and result.fp == 0]

    # Named candidates are deliberately interpretable and close to the current
    # firmware; the broad ranking is still included for auditability.
    named_configs = {
        "A_balanced_dual": DetectorConfig(
            still_gyro_dps=45.0,
            sequence_window_ms=2000,
            strict_hold_ms=600,
            deep_free_fall_g=0.40,
            deep_hold_ms=1200,
        ),
        "B_conservative_dual": DetectorConfig(
            tilt_deg=60.0,
            still_gyro_dps=45.0,
            sequence_window_ms=2000,
            strict_hold_ms=600,
            deep_free_fall_g=0.25,
            deep_hold_ms=1500,
        ),
        "C_strict_low_impact": DetectorConfig(
            impact_g=1.80,
            tilt_deg=60.0,
            still_gyro_dps=45.0,
            sequence_window_ms=2000,
            strict_hold_ms=600,
        ),
    }

    normal_min_a = min(
        sample.a_g
        for trial in trials
        if trial.ground_truth == "normal"
        for sample in trial.samples
    )
    normal_max_a = max(
        sample.a_g
        for trial in trials
        if trial.ground_truth == "normal"
        for sample in trial.samples
    )
    fall_min_a = min(
        sample.a_g
        for trial in trials
        if trial.ground_truth == "fall"
        for sample in trial.samples
    )

    payload = {
        "dataset": {
            "trials": len(trials),
            "fall_trials": sum(t.ground_truth == "fall" for t in trials),
            "normal_trials": sum(t.ground_truth == "normal" for t in trials),
            "normal_min_a_g": normal_min_a,
            "normal_max_a_g": normal_max_a,
            "fall_min_a_g": fall_min_a,
        },
        "search": {
            "strict_configs": len(strict_results),
            "dual_configs": len(dual_results),
            "perfect_configs": len(perfect),
        },
        "baseline": _result_dict(baseline, trials),
        "candidates": {
            name: _result_dict(evaluate(trials, config), trials)
            for name, config in named_configs.items()
        },
        "top_ranked": [
            _result_dict(result, trials)
            for result in sorted(all_results, key=_rank_key)[: args.top]
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
