import csv
import tempfile
import unittest
from pathlib import Path

from smartcane_host.imu_capture import ImuCaptureSession, campaign_metrics


def sample(seq: int, t_ms: int, **overrides):
    value = {
        "seq": seq, "t_ms": t_ms,
        "ax_g": 0.0, "ay_g": 0.0, "az_g": 1.0,
        "gx_dps": 0.0, "gy_dps": 0.0, "gz_dps": 0.0,
        "roll_deg": 0.0, "pitch_deg": 0.0, "yaw_deg": 0.0,
        "a_g": 1.0, "g_dps": 0.0, "tilt_deg": 0.0,
        "fall_phase": "IDLE", "free_fall": False, "impact": False,
        "tilted_still": False, "alarm": "NORMAL",
        "fall_suspected": False, "fall_latched": False,
    }
    value.update(overrides)
    return value


class ImuCaptureTests(unittest.TestCase):
    def test_csv_metadata_marker_rate_and_drop_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = ImuCaptureSession()
            path = capture.start(Path(directory), "T001", "fall_left", "fall")
            capture.append(sample(1, 1000))
            capture.mark_action()
            capture.append(sample(2, 1050, alarm="SUSPECTED_FALL", fall_suspected=True))
            capture.append(sample(4, 1100, alarm="FALL", fall_latched=True))
            summary = capture.stop()

            self.assertIsNotNone(summary)
            assert summary is not None
            self.assertEqual(summary.samples, 3)
            self.assertEqual(summary.dropped, 1)
            self.assertAlmostEqual(summary.rate_hz, 20.0)
            self.assertTrue(summary.suspected_seen)
            self.assertTrue(summary.fall_seen)
            self.assertEqual(summary.classification, "TP")
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[1]["action_marker"], "ACTION_START")
            self.assertEqual(rows[1]["trial_id"], "T001")
            self.assertEqual(rows[1]["ground_truth"], "fall")
            with (Path(directory) / "trials.csv").open(encoding="utf-8-sig", newline="") as handle:
                trials = list(csv.DictReader(handle))
            self.assertEqual(trials[0]["classification"], "TP")
            metrics = campaign_metrics(Path(directory) / "trials.csv")
            self.assertEqual(metrics["TP"], 1)
            self.assertEqual(metrics["recall"], 1.0)
            self.assertIsNone(metrics["false_positive_rate"])

    def test_action_can_only_be_marked_once(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = ImuCaptureSession()
            capture.start(Path(directory), "T002", "normal_walk", "normal")
            capture.mark_action()
            with self.assertRaises(RuntimeError):
                capture.mark_action()
            capture.stop()


if __name__ == "__main__":
    unittest.main()
