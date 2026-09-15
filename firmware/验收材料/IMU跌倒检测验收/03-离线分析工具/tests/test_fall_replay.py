from pathlib import Path

from smartcane_host.fall_replay import (
    CURRENT_CONFIG,
    DetectorConfig,
    ImuSample,
    Trial,
    replay_trial,
)


def _trial(samples, ground_truth="fall"):
    return Trial("T", "synthetic", ground_truth, Path("synthetic.csv"), tuple(samples))


def test_strict_path_requires_impact():
    trial = _trial(
        [
            ImuSample(0, 0.30, 100.0, 10.0),
            ImuSample(100, 1.00, 5.0, 70.0),
            ImuSample(1300, 1.00, 5.0, 70.0),
        ]
    )
    assert not replay_trial(trial, DetectorConfig(sequence_window_ms=2000)).detected


def test_deep_path_can_bridge_missed_impact():
    trial = _trial(
        [
            ImuSample(0, 0.30, 100.0, 10.0),
            ImuSample(100, 1.00, 5.0, 70.0),
            ImuSample(1300, 1.00, 5.0, 70.0),
        ]
    )
    result = replay_trial(
        trial,
        DetectorConfig(
            sequence_window_ms=2000,
            deep_free_fall_g=0.35,
            deep_hold_ms=1000,
        ),
    )
    assert result.detected
    assert result.path == "deep"


def test_deep_path_rejects_low_g_above_threshold():
    trial = _trial(
        [
            ImuSample(0, 0.47, 100.0, 10.0),
            ImuSample(100, 1.00, 5.0, 70.0),
            ImuSample(1300, 1.00, 5.0, 70.0),
        ],
        ground_truth="normal",
    )
    result = replay_trial(
        trial,
        DetectorConfig(
            sequence_window_ms=2000,
            deep_free_fall_g=0.35,
            deep_hold_ms=1000,
        ),
    )
    assert not result.detected


def test_frozen_profile_accepts_observed_03823_g_deep_entry():
    trial = _trial(
        [
            ImuSample(0, 0.3823, 100.0, 10.0),
            ImuSample(100, 1.00, 5.0, 70.0),
            ImuSample(1500, 1.00, 5.0, 70.0),
        ]
    )
    result = replay_trial(trial, CURRENT_CONFIG)
    assert result.detected
    assert result.path == "deep"
