"""Small dependency-free Qt plot for A, G and Tilt during IMU collection."""

from __future__ import annotations

from collections import deque
from typing import Any

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget


class ImuPlotWidget(QWidget):
    COLORS = (QColor("#45e0cd"), QColor("#ffb454"), QColor("#a78bfa"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(210)
        self._samples: deque[tuple[float, float, float]] = deque(maxlen=300)

    def add_sample(self, sample: dict[str, Any]) -> None:
        try:
            self._samples.append(
                (float(sample["a_g"]), float(sample["g_dps"]), float(sample["tilt_deg"]))
            )
        except (KeyError, TypeError, ValueError):
            return
        self.update()

    def clear(self) -> None:
        self._samples.clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#091525"))
        left, right, top, bottom = 42, 8, 8, 8
        width = max(1, self.width() - left - right)
        band_h = max(1, (self.height() - top - bottom) / 3)
        values = list(self._samples)
        definitions = (
            ("A / g", 3.0, (0.55, 2.20)),
            ("G / °s⁻¹", max(100.0, max((v[1] for v in values), default=0.0) * 1.1), (35.0,)),
            ("Tilt / °", 180.0, (55.0,)),
        )
        for band, (label, scale_max, thresholds) in enumerate(definitions):
            y0 = top + band * band_h
            painter.setPen(QPen(QColor("#243650"), 1))
            painter.drawLine(left, int(y0 + band_h), left + width, int(y0 + band_h))
            painter.setPen(QColor("#8297b5"))
            painter.drawText(4, int(y0 + 17), label)
            for threshold in thresholds:
                y = y0 + band_h - min(1.0, threshold / scale_max) * (band_h - 10)
                painter.setPen(QPen(QColor("#ff667f"), 1, Qt.DashLine))
                painter.drawLine(left, int(y), left + width, int(y))
            if len(values) < 2:
                continue
            path = QPainterPath()
            for index, triple in enumerate(values):
                x = left + index * width / max(1, len(values) - 1)
                normalized = max(0.0, min(1.0, triple[band] / scale_max))
                y = y0 + band_h - normalized * (band_h - 10)
                point = QPointF(x, y)
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            painter.setPen(QPen(self.COLORS[band], 1.7))
            painter.drawPath(path)
        painter.end()
