import csv
import tempfile
import unittest
from pathlib import Path

from smartcane_host.ppg_capture import PpgCaptureSession


def sample(seq: int, t_ms: int, **overrides):
    value = {
        "seq": seq, "t_ms": t_ms, "red": 112000, "ir": 128000,
        "red_dc": 111900.0, "ir_dc": 127800.0,
        "red_ac": 100.0, "ir_ac": 200.0, "filtered_ir": 160.0,
        "envelope": 90.0, "peak_candidate": False, "beat_accepted": False,
        "ibi_ms": float("nan"), "finger": True, "sqi": 0.8,
        "hr_bpm": 72.0, "spo2_pct": 98.0, "valid": True,
        "fifo_overflow": 0,
    }
    value.update(overrides)
    return value


class PpgCaptureTests(unittest.TestCase):
    def test_csv_marker_rate_drop_and_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = PpgCaptureSession()
            path = capture.start(
                Path(directory), "P001", "finger_still", "VALID",
            )
            capture.append(sample(1, 1000))
            capture.mark_action()
            capture.append(sample(2, 1040, beat_accepted=True, ibi_ms=833.0))
            capture.append(sample(4, 1080, fifo_overflow=2))
            summary = capture.stop()

            self.assertIsNotNone(summary)
            assert summary is not None
            self.assertEqual(summary.samples, 3)
            self.assertEqual(summary.dropped, 1)
            self.assertAlmostEqual(summary.rate_hz, 25.0)
            self.assertEqual(summary.fifo_overflow_max, 2)
            self.assertAlmostEqual(summary.finger_fraction, 1.0)
            self.assertAlmostEqual(summary.valid_fraction, 1.0)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[1]["action_marker"], "ACTION_START")
            self.assertNotIn("reference_hr_bpm", rows[0])
            self.assertNotIn("reference_spo2_pct", rows[0])
            with (Path(directory) / "trials.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                trials = list(csv.DictReader(handle))
            self.assertEqual(trials[0]["label"], "finger_still")

    def test_legacy_manifest_header_remains_appendable(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "trials.csv"
            manifest.write_text(
                "path,samples,hr_mae,spo2_mae,trial_id,label\n"
                "old.csv,10,1.0,1.0,OLD,reference_compare\n",
                encoding="utf-8-sig",
            )
            capture = PpgCaptureSession()
            capture.start(Path(directory), "P002", "finger_still", "VALID")
            capture.append(sample(1, 1000))
            capture.stop()
            with manifest.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["trial_id"], "P002")
            self.assertEqual(rows[1]["hr_mae"], "")


if __name__ == "__main__":
    unittest.main()
