"""High-rate IMU CSV capture and sampling-quality statistics."""

from __future__ import annotations

import csv
import re
import statistics
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .protocol import IMU_FIELDS


SCENARIOS = (
    ("静止直立", "static_upright", "normal"),
    ("正常行走", "normal_walk", "normal"),
    ("快速行走", "fast_walk", "normal"),
    ("大幅摆杖", "cane_swing", "normal"),
    ("左转", "turn_left", "normal"),
    ("右转", "turn_right", "normal"),
    ("上台阶", "stairs_up", "normal"),
    ("下台阶", "stairs_down", "normal"),
    ("靠墙放置", "lean_wall", "normal"),
    ("正常放下", "put_down", "normal"),
    ("正常拿起", "pick_up", "normal"),
    ("杖尖碰撞", "tip_collision", "normal"),
    ("受控向前倾倒", "fall_forward", "fall"),
    ("受控向后倾倒", "fall_backward", "fall"),
    ("受控向左倾倒", "fall_left", "fall"),
    ("受控向右倾倒", "fall_right", "fall"),
)

CAPTURE_FIELDS = (
    "pc_time", "pc_monotonic_ms", "trial_id", "label", "ground_truth",
    "action_marker", *IMU_FIELDS,
)


def campaign_metrics(manifest: Path) -> dict[str, Any]:
    counts = {"TP": 0, "FN": 0, "FP": 0, "TN": 0}
    if manifest.exists():
        with manifest.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name = str(row.get("classification", "")).upper()
                if name in counts:
                    counts[name] += 1
    fall_total = counts["TP"] + counts["FN"]
    normal_total = counts["FP"] + counts["TN"]
    return {
        **counts,
        "fall_total": fall_total,
        "normal_total": normal_total,
        "recall": counts["TP"] / fall_total if fall_total else None,
        "false_positive_rate": counts["FP"] / normal_total if normal_total else None,
    }


@dataclass(frozen=True)
class CaptureSummary:
    path: Path
    samples: int
    dropped: int
    resets: int
    rate_hz: float
    max_gap_ms: float
    suspected_seen: bool
    fall_seen: bool
    cancel_seen: bool
    trial_id: str
    label: str
    ground_truth: str
    action_marked: bool
    classification: str


class ImuCaptureSession:
    """Own one CSV file and derive quality metrics from device timestamps."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self._file: TextIO | None = None
        self._writer: csv.DictWriter | None = None
        self.trial_id = ""
        self.label = ""
        self.ground_truth = ""
        self.samples = 0
        self.dropped = 0
        self.resets = 0
        self._last_seq: int | None = None
        self._last_t_ms: int | None = None
        self._intervals_ms: deque[float] = deque(maxlen=500)
        self.max_gap_ms = 0.0
        self.suspected_seen = False
        self.fall_seen = False
        self.cancel_seen = False
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

    def start(
        self, directory: Path, trial_id: str, label: str, ground_truth: str
    ) -> Path:
        if self.active:
            raise RuntimeError("已有采集任务正在运行")
        trial_id = trial_id.strip()
        if not trial_id:
            raise ValueError("试验编号不能为空")
        if ground_truth not in {"normal", "fall"}:
            raise ValueError("真实标签必须是 normal 或 fall")

        self.__init__()
        self.trial_id = trial_id
        self.label = label
        self.ground_truth = ground_truth
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        safe_trial = re.sub(r"[^0-9A-Za-z_-]+", "_", trial_id).strip("_") or "trial"
        safe_label = re.sub(r"[^0-9A-Za-z_-]+", "_", label).strip("_") or "scene"
        self.path = directory / f"imu_{stamp}_{safe_trial}_{safe_label}.csv"
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

    def append(self, sample: dict[str, Any]) -> None:
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
            "ground_truth": self.ground_truth,
            "action_marker": marker,
        }
        row.update({name: sample.get(name, "") for name in IMU_FIELDS})
        self._writer.writerow(row)
        self.samples += 1
        alert_seen_before = self.suspected_seen or self.fall_seen
        self.suspected_seen |= bool(sample.get("fall_suspected")) or sample.get("alarm") == "SUSPECTED_FALL"
        self.fall_seen |= bool(sample.get("fall_latched")) or sample.get("alarm") == "FALL"
        self.cancel_seen |= bool(
            alert_seen_before
            and sample.get("alarm") == "NORMAL"
            and not sample.get("fall_suspected")
            and not sample.get("fall_latched")
        )
        if self.samples % 10 == 0 and self._file is not None:
            self._file.flush()

    def stop(self) -> CaptureSummary | None:
        if not self.active or self.path is None:
            return None
        path = self.path
        if self._file is not None:
            self._file.flush()
            self._file.close()
        detected = self.suspected_seen or self.fall_seen
        classification = (
            "TP" if self.ground_truth == "fall" and detected else
            "FN" if self.ground_truth == "fall" else
            "FP" if detected else "TN"
        )
        summary = CaptureSummary(
            path=path,
            samples=self.samples,
            dropped=self.dropped,
            resets=self.resets,
            rate_hz=self.rate_hz,
            max_gap_ms=self.max_gap_ms,
            suspected_seen=self.suspected_seen,
            fall_seen=self.fall_seen,
            cancel_seen=self.cancel_seen,
            trial_id=self.trial_id,
            label=self.label,
            ground_truth=self.ground_truth,
            action_marked=self._action_marked,
            classification=classification,
        )
        self._file = None
        self._writer = None
        self._append_manifest(summary)
        return summary

    @staticmethod
    def _append_manifest(summary: CaptureSummary) -> None:
        manifest = summary.path.parent / "trials.csv"
        fields = (
            "recorded_at", "trial_id", "label", "ground_truth", "classification",
            "suspected_seen", "fall_seen", "cancel_seen", "action_marked",
            "samples", "rate_hz", "dropped", "resets", "max_gap_ms", "file",
        )
        exists = manifest.exists() and manifest.stat().st_size > 0
        with manifest.open("a", encoding="utf-8-sig", newline="", buffering=1) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow({
                "recorded_at": datetime.now().isoformat(timespec="seconds"),
                "trial_id": summary.trial_id,
                "label": summary.label,
                "ground_truth": summary.ground_truth,
                "classification": summary.classification,
                "suspected_seen": int(summary.suspected_seen),
                "fall_seen": int(summary.fall_seen),
                "cancel_seen": int(summary.cancel_seen),
                "action_marked": int(summary.action_marked),
                "samples": summary.samples,
                "rate_hz": f"{summary.rate_hz:.3f}",
                "dropped": summary.dropped,
                "resets": summary.resets,
                "max_gap_ms": f"{summary.max_gap_ms:.1f}",
                "file": summary.path.name,
            })
