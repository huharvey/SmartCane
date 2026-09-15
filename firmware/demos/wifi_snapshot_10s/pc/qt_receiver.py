#!/usr/bin/env python3
"""ESP32 十秒抓拍 Demo 的 PyQt5 接收、显示和自动保存客户端。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtNetwork import (
    QNetworkAccessManager,
    QNetworkProxy,
    QNetworkReply,
    QNetworkRequest,
)
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SnapshotWindow(QMainWindow):
    """用 Qt 异步网络接口取图，避免 HTTP 请求阻塞界面。"""
    def __init__(self, base_url: str, interval_seconds: int, capture_dir: Path):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.interval_seconds = max(1, interval_seconds)
        self.capture_dir = capture_dir
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.manager = QNetworkAccessManager(self)
        self.manager.finished.connect(self._reply_finished)
        self.running = False
        self.request_started = 0.0
        self.next_due = 0.0
        self.current_pixmap = QPixmap()

        self.setWindowTitle("ESP32-S3-CAM Wi-Fi 定时图传上位机")
        self.resize(1040, 760)
        self._build_ui()

        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(self.interval_seconds * 1000)
        self.capture_timer.timeout.connect(self.request_frame)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(200)
        self.countdown_timer.timeout.connect(self._update_countdown)
        self.countdown_timer.start()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        title = QLabel("ESP32-S3-CAM · 10 秒定时图传")
        title.setObjectName("title")
        title.setFont(QFont("Microsoft YaHei UI", 20, QFont.Bold))
        subtitle = QLabel("HTTP/JPEG over Wi-Fi · Qt 异步接收 · 自动保存")
        subtitle.setObjectName("subtitle")

        connection = QHBoxLayout()
        connection.addWidget(QLabel("设备地址"))
        self.url_edit = QLineEdit(self.base_url)
        self.url_edit.setPlaceholderText("http://192.168.4.1")
        connection.addWidget(self.url_edit, 1)
        self.start_button = QPushButton("开始接收")
        self.start_button.clicked.connect(self.toggle_running)
        connection.addWidget(self.start_button)
        self.now_button = QPushButton("立即取图")
        self.now_button.clicked.connect(self.request_frame)
        connection.addWidget(self.now_button)

        self.image = QLabel("等待图像…")
        self.image.setObjectName("image")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(760, 430)
        self.image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        stats = QGridLayout()
        self.frame_value = QLabel("—")
        self.bytes_value = QLabel("—")
        self.latency_value = QLabel("—")
        self.source_time_value = QLabel("—")
        self.countdown_value = QLabel(f"{self.interval_seconds:.1f} s")
        labels = [
            ("最新帧", self.frame_value),
            ("JPEG 大小", self.bytes_value),
            ("网络耗时", self.latency_value),
            ("设备采集时刻", self.source_time_value),
            ("下次请求", self.countdown_value),
        ]
        for column, (name, value) in enumerate(labels):
            name_label = QLabel(name)
            name_label.setObjectName("statName")
            value.setObjectName("statValue")
            stats.addWidget(name_label, 0, column)
            stats.addWidget(value, 1, column)

        options = QHBoxLayout()
        self.auto_save = QCheckBox("自动保存 JPEG")
        self.auto_save.setChecked(True)
        options.addWidget(self.auto_save)
        self.connection_value = QLabel("未连接")
        self.connection_value.setObjectName("connection")
        options.addStretch(1)
        options.addWidget(self.connection_value)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        self.log.setPlaceholderText("运行日志")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(connection)
        layout.addWidget(self.image, 1)
        layout.addLayout(stats)
        layout.addLayout(options)
        layout.addWidget(self.log)
        self.setCentralWidget(root)

        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#0b1220; color:#e5edf9; font-family:'Microsoft YaHei UI'; }
            QLabel#title { color:#f8fbff; }
            QLabel#subtitle, QLabel#statName { color:#91a4c2; }
            QLabel#image { background:#03070d; border:1px solid #2b3b58; border-radius:14px; color:#7183a0; }
            QLabel#statValue { color:#55d6be; font-size:17px; font-weight:700; }
            QLabel#connection { color:#fbbf24; font-weight:700; }
            QLineEdit, QTextEdit { background:#121c2e; border:1px solid #2b3b58; border-radius:8px; padding:8px; }
            QPushButton { background:#38bdf8; color:#082f49; border:0; border-radius:8px; padding:9px 16px; font-weight:700; }
            QPushButton:hover { background:#7dd3fc; }
            QCheckBox { spacing:8px; }
            """
        )

    def toggle_running(self) -> None:
        if self.running:
            self.running = False
            self.capture_timer.stop()
            self.start_button.setText("开始接收")
            self.connection_value.setText("已暂停")
            self._append_log("定时接收已暂停")
            return

        self.base_url = self.url_edit.text().strip().rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            self.base_url = "http://" + self.base_url
            self.url_edit.setText(self.base_url)
        self.running = True
        self.start_button.setText("暂停接收")
        self.capture_timer.start()
        self.next_due = time.monotonic() + self.interval_seconds
        self._append_log(f"开始接收：{self.base_url}，周期 {self.interval_seconds} 秒")
        self.request_frame()

    def request_frame(self) -> None:
        # 时间戳查询参数用于绕过中间缓存，设备端仍返回最新缓存帧。
        if not self.base_url:
            return
        self.request_started = time.perf_counter()
        url = QUrl(f"{self.base_url}/capture?t={int(time.time() * 1000)}")
        request = QNetworkRequest(url)
        request.setRawHeader(b"Cache-Control", b"no-cache")
        reply = self.manager.get(request)
        reply.setProperty("kind", "frame")
        reply.setProperty("started", self.request_started)
        self.connection_value.setText("正在接收…")
        self.next_due = time.monotonic() + self.interval_seconds

    def request_status(self) -> None:
        request = QNetworkRequest(QUrl(f"{self.base_url}/api/status?t={int(time.time() * 1000)}"))
        reply = self.manager.get(request)
        reply.setProperty("kind", "status")

    def _reply_finished(self, reply: QNetworkReply) -> None:
        # status 与 JPEG 共用同一个 manager，通过 kind 属性区分响应。
        kind = reply.property("kind")
        payload = bytes(reply.readAll())
        if reply.error() != QNetworkReply.NoError:
            self.connection_value.setText("连接失败")
            self._append_log(f"请求失败：{reply.errorString()}")
            reply.deleteLater()
            return

        if kind == "status":
            try:
                status = json.loads(payload.decode("utf-8"))
                self.source_time_value.setText(f"{status.get('captured_at_ms', 0)} ms")
            except (ValueError, UnicodeDecodeError):
                pass
            reply.deleteLater()
            return

        pixmap = QPixmap()
        if not pixmap.loadFromData(payload, "JPEG"):
            self.connection_value.setText("图像无效")
            self._append_log(f"返回内容不是有效 JPEG（{len(payload)} 字节）")
            reply.deleteLater()
            return

        self.current_pixmap = pixmap
        self._show_scaled_pixmap()
        frame_id = bytes(reply.rawHeader(b"X-Frame-Id")).decode("ascii", "replace") or "?"
        captured_at = bytes(reply.rawHeader(b"X-Captured-At-Ms")).decode("ascii", "replace") or "?"
        started = float(reply.property("started") or time.perf_counter())
        latency_ms = (time.perf_counter() - started) * 1000.0
        self.frame_value.setText(f"#{frame_id}")
        self.bytes_value.setText(f"{len(payload) / 1024:.1f} KiB")
        self.latency_value.setText(f"{latency_ms:.0f} ms")
        self.source_time_value.setText(f"{captured_at} ms")
        self.connection_value.setText("接收正常")
        self.connection_value.setStyleSheet("color:#55d6be;font-weight:700")
        self._append_log(
            f"收到帧 #{frame_id}，{len(payload)} 字节，网络耗时 {latency_ms:.0f} ms"
        )
        if self.auto_save.isChecked():
            path = self.capture_dir / f"frame_{frame_id}_{datetime.now():%Y%m%d_%H%M%S}.jpg"
            path.write_bytes(payload)
        self.request_status()
        reply.deleteLater()

    def _show_scaled_pixmap(self) -> None:
        if self.current_pixmap.isNull():
            return
        self.image.setPixmap(
            self.current_pixmap.scaled(
                self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        self._show_scaled_pixmap()

    def _update_countdown(self) -> None:
        if not self.running:
            self.countdown_value.setText("已暂停")
            return
        remaining = max(0.0, self.next_due - time.monotonic())
        self.countdown_value.setText(f"{remaining:.1f} s")

    def _append_log(self, message: str) -> None:
        self.log.append(f"[{datetime.now():%H:%M:%S}] {message}")

    def save_window_and_quit(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.grab().save(str(path), "PNG")
        self._append_log(f"运行截图已保存：{path}")
        QApplication.instance().quit()


def parse_args() -> argparse.Namespace:
    """解析设备地址、抓拍周期、保存目录和自动验收参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://192.168.4.1", help="ESP32 base URL")
    parser.add_argument("--interval", type=int, default=10, help="fetch interval in seconds")
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "captures",
        help="directory used by auto-save",
    )
    parser.add_argument("--screenshot", type=Path, help="save a PNG screenshot before exit")
    parser.add_argument("--duration", type=float, default=0, help="auto-exit after N seconds")
    return parser.parse_args()


def main() -> int:
    """启动十秒抓拍 Demo 窗口。"""
    args = parse_args()
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    # 相机位于本地 Wi-Fi，必须绕过 Clash 等代理，避免 192.168.4.1 被转发。
    QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))
    window = SnapshotWindow(args.url, args.interval, args.capture_dir)
    window.show()
    QTimer.singleShot(250, window.toggle_running)
    if args.duration > 0:
        if args.screenshot:
            QTimer.singleShot(
                int(args.duration * 1000),
                lambda: window.save_window_and_quit(args.screenshot),
            )
        else:
            QTimer.singleShot(int(args.duration * 1000), app.quit)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
