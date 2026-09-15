"""Dependency-free MAX30102 waveform, filter and SQI plot."""

from __future__ import annotations

import math
from collections import deque
from typing import Any

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget


class PpgPlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(260)
        self._samples: deque[tuple[float, float, float, float, bool]] = deque(maxlen=300)

    def add_sample(self, sample: dict[str, Any]) -> None:
        try:
            values = (
                float(sample["red_ac"]), float(sample["ir_ac"]),
                float(sample["filtered_ir"]), float(sample["sqi"]),
                bool(sample["beat_accepted"]),
            )
        except (KeyError, TypeError, ValueError):
            return
        self._samples.append(values)
        self.update()

    def clear(self) -> None:
        self._samples.clear()
        self.update()

    @staticmethod
    def _path(values: list[float], left: float, width: float, y_mid: float,
              amplitude: float, band_h: float) -> QPainterPath:
        path = QPainterPath()
        for index, value in enumerate(values):
            x = left + index * width / max(1, len(values) - 1)
            if not math.isfinite(value):
                value = 0.0
            normalized = max(-1.0, min(1.0, value / amplitude))
            point = QPointF(x, y_mid - normalized * (band_h * 0.40))
            path.moveTo(point) if index == 0 else path.lineTo(point)
        return path

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#091525"))
        left, right, top, bottom = 48, 8, 8, 8
        width = max(1, self.width() - left - right)
        band_h = max(1, (self.height() - top - bottom) / 3)
        samples = list(self._samples)
        for band, label in enumerate(("RED / IR AC", "滤波 IR / 峰值", "SQI / 0~1")):
            y0 = top + band * band_h
            painter.setPen(QPen(QColor("#243650"), 1))
            painter.drawLine(left, int(y0 + band_h), left + width, int(y0 + band_h))
            painter.setPen(QColor("#8297b5"))
            painter.drawText(4, int(y0 + 17), label)
        if len(samples) >= 2:
            red = [row[0] for row in samples if math.isfinite(row[0])]
            ir = [row[1] for row in samples if math.isfinite(row[1])]
            ac_scale = max(100.0, max((abs(v) for v in red + ir), default=100.0))
            y_mid = top + band_h * 0.55
            painter.setPen(QPen(QColor("#ff667f"), 1.3))
            painter.drawPath(self._path([row[0] for row in samples], left, width, y_mid, ac_scale, band_h))
            painter.setPen(QPen(QColor("#45e0cd"), 1.5))
            painter.drawPath(self._path([row[1] for row in samples], left, width, y_mid, ac_scale, band_h))

            filtered = [row[2] for row in samples if math.isfinite(row[2])]
            filter_scale = max(80.0, max((abs(v) for v in filtered), default=80.0))
            filter_mid = top + band_h + band_h * 0.55
            painter.setPen(QPen(QColor("#ffb454"), 1.7))
            painter.drawPath(self._path([row[2] for row in samples], left, width, filter_mid, filter_scale, band_h))
            painter.setPen(QPen(QColor("#f6f9ff"), 1))
            for index, row in enumerate(samples):
                if not row[4]:
                    continue
                x = left + index * width / max(1, len(samples) - 1)
                painter.drawLine(int(x), int(top + band_h + 7), int(x), int(top + 2 * band_h - 5))

            sqi_y0 = top + 2 * band_h
            threshold_y = sqi_y0 + band_h - 0.45 * (band_h - 12)
            painter.setPen(QPen(QColor("#ff667f"), 1, Qt.DashLine))
            painter.drawLine(left, int(threshold_y), left + width, int(threshold_y))
            sqi_path = QPainterPath()
            for index, row in enumerate(samples):
                x = left + index * width / max(1, len(samples) - 1)
                value = max(0.0, min(1.0, row[3])) if math.isfinite(row[3]) else 0.0
                point = QPointF(x, sqi_y0 + band_h - value * (band_h - 12))
                sqi_path.moveTo(point) if index == 0 else sqi_path.lineTo(point)
            painter.setPen(QPen(QColor("#a78bfa"), 1.7))
            painter.drawPath(sqi_path)
        painter.end()
