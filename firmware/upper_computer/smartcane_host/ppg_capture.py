"""MAX30102 high-rate PPG CSV capture and signal-quality statistics."""

from __future__ import annotations

import csv
import math
import re
import statistics
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .protocol import PPG_FIELDS


PPG_SCENARIOS = (
    ("无手指空载（15 秒）", "no_finger", "NO_FINGER"),
    ("稳定覆盖·静止（60 秒）", "finger_still", "VALID"),
    ("重复放置/移开（6 次）", "finger_reposition", "TRANSITION"),
    ("轻压传感器（30 秒）", "light_pressure", "QUALITY"),
    ("正常按压（60 秒）", "normal_pressure", "VALID"),
    ("重压传感器（30 秒）", "heavy_pressure", "QUALITY"),
    ("手指轻微移动（30 秒）", "finger_motion", "MOTION"),
    ("拐杖轻微晃动（30 秒）", "cane_motion", "MOTION"),
    ("强环境光干扰（30 秒）", "ambient_light", "QUALITY"),
    ("运动后恢复（90 秒）", "post_exercise_recovery", "VALID"),
    ("节律稳定窗口（60 秒）", "rhythm_normal", "NORMAL"),
)

CONTEXT_FIELDS = (
    "rhythm_state", "rhythm_valid", "rhythm_confidence",
    "model_calibrated", "rhythm_ibi_mean_ms", "rhythm_sdnn_ms",
    "rhythm_rmssd_ms", "rhythm_pnn50", "rhythm_beat_count",
    "rhythm_inference_us", "rhythm_inference_count", "rhythm_model_bytes",
    "rhythm_classifier_state_bytes",
    "imu_accel_g", "imu_gyro_dps",
)
CAPTURE_FIELDS = (
    "pc_time", "pc_monotonic_ms", "trial_id", "label", "expected_state",
    "action_marker",
    *PPG_FIELDS, *CONTEXT_FIELDS,
)


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class PpgCaptureSummary:
    path: Path
    samples: int
    dropped: int
    resets: int
    rate_hz: float
    max_gap_ms: float
    fifo_overflow_max: int
    finger_fraction: float
    valid_fraction: float
    clipped_fraction: float
    mean_sqi: float
    mean_hr_bpm: float | None
    mean_spo2_pct: float | None
    trial_id: str
    label: str
    expected_state: str
    action_marked: bool


class PpgCaptureSession:
    """Own one PPG CSV and calculate transport plus signal quality metrics."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self._file: TextIO | None = None
        self._writer: csv.DictWriter | None = None
        self.trial_id = ""
        self.label = ""
        self.expected_state = ""
        self.samples = 0
        self.dropped = 0
        self.resets = 0
        self.fifo_overflow_max = 0
        self._last_seq: int | None = None
        self._last_t_ms: int | None = None
        self._intervals_ms: deque[float] = deque(maxlen=1000)
        self.max_gap_ms = 0.0
        self._finger_samples = 0
        self._valid_samples = 0
        self._clipped_samples = 0
        self._sqi_values: list[float] = []
        self._hr_values: list[float] = []
        self._spo2_values: list[float] = []
        self._action_pending = False
        self._action_marked = False

    @property
    def active(self) -> bool:
        return self._file is not None

    @property
    def rate_hz(self) -> float:
        if not self._intervals_ms:
            return 0.0
        median_ms = statistics.median(self._intervals_ms)
        return 1000.0 / median_ms if median_ms > 0 else 0.0

    @property
    def finger_fraction(self) -> float:
        return self._finger_samples / self.samples if self.samples else 0.0

    @property
    def valid_fraction(self) -> float:
        return self._valid_samples / self.samples if self.samples else 0.0

    @property
    def mean_sqi(self) -> float:
        return statistics.fmean(self._sqi_values) if self._sqi_values else 0.0

    def start(
        self,
        directory: Path,
        trial_id: str,
        label: str,
        expected_state: str,
    ) -> Path:
        if self.active:
            raise RuntimeError("已有 PPG 采集任务正在运行")
        trial_id = trial_id.strip()
        if not trial_id:
            raise ValueError("试验编号不能为空")

        self.__init__()
        self.trial_id = trial_id
        self.label = label
        self.expected_state = expected_state
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        safe_trial = re.sub(r"[^0-9A-Za-z_-]+", "_", trial_id).strip("_") or "trial"
        safe_label = re.sub(r"[^0-9A-Za-z_-]+", "_", label).strip("_") or "scene"
        self.path = directory / f"ppg_{stamp}_{safe_trial}_{safe_label}.csv"
        self._file = self.path.open("w", encoding="utf-8-sig", newline="", buffering=1)
        self._writer = csv.DictWriter(self._file, fieldnames=CAPTURE_FIELDS)
        self._writer.writeheader()
        return self.path

    def mark_action(self) -> None:
        if not self.active:
            raise RuntimeError("请先开始记录")
        if self._action_marked or self._action_pending:
            raise RuntimeError("本次试验已经标记过动作开始")
        self._action_pending = True

    def append(self, sample: dict[str, Any], context: dict[str, Any] | None = None) -> None:
        if not self.active or self._writer is None:
            return
        seq = int(sample["seq"])
        t_ms = int(sample["t_ms"])
        if self._last_seq is not None:
            if seq > self._last_seq:
                self.dropped += max(0, seq - self._last_seq - 1)
            else:
                self.resets += 1
        if self._last_t_ms is not None:
            delta = (t_ms - self._last_t_ms) & 0xFFFFFFFF
            if 0 < delta < 60_000:
                self._intervals_ms.append(float(delta))
                self.max_gap_ms = max(self.max_gap_ms, float(delta))
        self._last_seq = seq
        self._last_t_ms = t_ms

        marker = "ACTION_START" if self._action_pending else ""
        if self._action_pending:
            self._action_pending = False
            self._action_marked = True
        row: dict[str, Any] = {
            "pc_time": datetime.now().isoformat(timespec="milliseconds"),
            "pc_monotonic_ms": int(time.monotonic() * 1000),
            "trial_id": self.trial_id,
            "label": self.label,
            "expected_state": self.expected_state,
            "action_marker": marker,
        }
        row.update({name: sample.get(name, "") for name in PPG_FIELDS})
        context = context or {}
        row.update({name: context.get(name, "") for name in CONTEXT_FIELDS})
        self._writer.writerow(row)
        self.samples += 1

        self._finger_samples += int(bool(sample.get("finger")))
        self._valid_samples += int(bool(sample.get("valid")))
        red, ir = int(sample.get("red", 0)), int(sample.get("ir", 0))
        self._clipped_samples += int(red >= 250_000 or ir >= 250_000)
        self.fifo_overflow_max = max(
            self.fifo_overflow_max, int(sample.get("fifo_overflow", 0))
        )
        if _finite(sample.get("sqi")):
            self._sqi_values.append(float(sample["sqi"]))
        if bool(sample.get("valid")) and _finite(sample.get("hr_bpm")):
            self._hr_values.append(float(sample["hr_bpm"]))
        if bool(sample.get("valid")) and _finite(sample.get("spo2_pct")):
            self._spo2_values.append(float(sample["spo2_pct"]))
        if self.samples % 25 == 0 and self._file is not None:
            self._file.flush()

    def stop(self) -> PpgCaptureSummary | None:
        if not self.active or self.path is None:
            return None
        path = self.path
        if self._file is not None:
            self._file.flush()
            self._file.close()
        mean_hr = statistics.fmean(self._hr_values) if self._hr_values else None
        mean_spo2 = statistics.fmean(self._spo2_values) if self._spo2_values else None
        summary = PpgCaptureSummary(
            path=path,
            samples=self.samples,
            dropped=self.dropped,
            resets=self.resets,
            rate_hz=self.rate_hz,
            max_gap_ms=self.max_gap_ms,
            fifo_overflow_max=self.fifo_overflow_max,
            finger_fraction=self.finger_fraction,
            valid_fraction=self.valid_fraction,
            clipped_fraction=self._clipped_samples / self.samples if self.samples else 0.0,
            mean_sqi=self.mean_sqi,
            mean_hr_bpm=mean_hr,
            mean_spo2_pct=mean_spo2,
            trial_id=self.trial_id,
            label=self.label,
            expected_state=self.expected_state,
            action_marked=self._action_marked,
        )
        self._file = None
        self._writer = None
        self._append_manifest(summary)
        return summary

    @staticmethod
    def _append_manifest(summary: PpgCaptureSummary) -> None:
        manifest = summary.path.parent / "trials.csv"
        fields = tuple(PpgCaptureSummary.__dataclass_fields__.keys())
        exists = manifest.exists() and manifest.stat().st_size > 0
        # Older capture folders may still use the pre-removal reference columns.
        # Append against their existing header so historical data remains intact.
        manifest_fields = fields
        if exists:
            with manifest.open(encoding="utf-8-sig", newline="") as existing:
                reader = csv.reader(existing)
                old_header = next(reader, None)
                if old_header:
                    manifest_fields = tuple(old_header)
        with manifest.open("a", encoding="utf-8-sig", newline="", buffering=1) as handle:
            writer = csv.DictWriter(handle, fieldnames=manifest_fields)
            if not exists:
                writer.writeheader()
            row = {name: getattr(summary, name, "") for name in manifest_fields}
            row["path"] = summary.path.name
            writer.writerow(row)
