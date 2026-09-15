"""SmartCane 三栏监控主窗口：传感器/控制、Wi-Fi 图传、GPS 地图。"""

from __future__ import annotations

import math
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .camera_worker import CameraWorker, normalize_base_url
from .diagnostics import CheckState, DiagnosticsEngine, best_serial_port
from .imu_capture import ImuCaptureSession, SCENARIOS, campaign_metrics
from .imu_plot import ImuPlotWidget
from .map_widget import MapWidget
from .ppg_capture import PpgCaptureSession, PPG_SCENARIOS
from .ppg_plot import PpgPlotWidget
from .serial_worker import SerialWorker
from .track_import import TrackImportError, load_track


# 固件使用稳定英文枚举值传输，界面层只负责映射为中文显示。
ALARM_LABELS = {
    "NORMAL": "正常",
    "CAUTION": "注意障碍",
    "WARNING": "近障警告",
    "DANGER": "危险近障",
    "SUSPECTED_FALL": "疑似跌倒",
    "FALL": "跌倒告警",
    "SOS": "SOS 求救",
}


class MetricCard(QFrame):
    """统一的“名称 + 数值 + 单位”传感器卡片。"""

    def __init__(self, title: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        caption = QLabel(title)
        caption.setObjectName("metricCaption")
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        self.unit = QLabel(unit)
        self.unit.setObjectName("metricUnit")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.value)
        row.addWidget(self.unit)
        row.addStretch(1)
        layout.addWidget(caption)
        layout.addLayout(row)

    def set_value(self, value: str, online: bool = True) -> None:
        self.value.setText(value)
        self.setProperty("online", online)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    """协调串口线程、图传线程和地图组件；不在上位机内执行算法判断。"""

    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self.serial_worker: SerialWorker | None = None
        self._retired_serial_workers: list[SerialWorker] = []
        self.camera_worker: CameraWorker | None = None
        self.current_pixmap = QPixmap()
        self.current_jpeg = b""
        self.last_telemetry_at = 0.0
        self.packet_count = 0
        self.frame_count = 0
        self.frame_started_at = 0.0
        self._camera_address_user_edited = False
        self._demo_phase = 0.0
        self.diagnostics = DiagnosticsEngine()
        self.diagnostic_rows: dict[str, QLabel] = {}
        self.session_log_path: Path | None = None
        self._session_log: TextIO | None = None
        self._auto_connect_after = 0.0
        self._last_auto_candidate = ""
        self.imu_capture = ImuCaptureSession()
        self._demo_imu_sequence = 0
        self.ppg_capture = PpgCaptureSession()
        self._demo_ppg_sequence = 0
        self._latest_ppg_context: dict[str, Any] = {}

        self.setWindowTitle("SmartCane 智能拐杖上位机")
        self.resize(1680, 940)
        self.setMinimumSize(1180, 720)
        self._build_ui()
        self._apply_style()
        self.refresh_ports()

        self.health_timer = QTimer(self)
        self.health_timer.setInterval(1000)
        self.health_timer.timeout.connect(self._check_telemetry_age)
        self.health_timer.start()
        self.port_timer = QTimer(self)
        self.port_timer.setInterval(1500)
        self.port_timer.timeout.connect(self._poll_ports)
        if not demo:
            self.port_timer.start()
        if demo:
            QTimer.singleShot(250, self.start_demo)

    def _build_ui(self) -> None:
        """组装顶部状态、三栏主区域和底部通信日志。"""
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(18, 14, 18, 14)
        root_layout.setSpacing(10)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("SmartCane · 实时监控中心")
        title.setObjectName("title")
        subtitle = QLabel("串口遥测  ·  Wi-Fi 图传  ·  GPS 地图")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch(1)
        self.global_status = QLabel("等待设备连接")
        self.global_status.setObjectName("globalStatus")
        heading.addWidget(self.global_status)
        root_layout.addLayout(heading)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_sensor_panel())
        splitter.addWidget(self._build_camera_panel())
        splitter.addWidget(self._build_map_panel())
        splitter.setSizes([390, 700, 580])
        root_layout.addWidget(splitter, 1)

        log_bar = QHBoxLayout()
        log_title = QLabel("串口原始日志与运行记录")
        log_title.setObjectName("sectionTitle")
        self.log_file_label = QLabel("尚未创建日志文件")
        self.log_file_label.setObjectName("muted")
        self.log_file_label.setToolTip("连接串口后自动创建 UTF-8 日志")
        open_logs = QPushButton("打开日志目录")
        open_logs.clicked.connect(self.open_log_folder)
        export_log = QPushButton("导出本次日志")
        export_log.clicked.connect(self.export_log)
        clear_log = QPushButton("清空显示")
        clear_log.clicked.connect(lambda: self.log.clear())
        log_bar.addWidget(log_title)
        log_bar.addWidget(self.log_file_label, 1)
        log_bar.addWidget(open_logs)
        log_bar.addWidget(export_log)
        log_bar.addWidget(clear_log)
        root_layout.addLayout(log_bar)

        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(1200)
        self.log.setMaximumHeight(190)
        self.log.setPlaceholderText("连接后自动抓取启动日志、SC1 协议消息和错误信息")
        root_layout.addWidget(self.log)
        self.setCentralWidget(root)

    def _build_sensor_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(10)

        connection = self._section("串口连接")
        connection_layout = connection.layout()
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(130)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_ports)
        self.serial_button = QPushButton("连接")
        self.serial_button.setObjectName("primaryButton")
        self.serial_button.clicked.connect(self.toggle_serial)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(refresh)
        port_row.addWidget(self.serial_button)
        self.serial_status = QLabel("未连接 · 115200 bit/s")
        self.serial_status.setObjectName("muted")
        self.auto_connect = QCheckBox("自动发现并连接 USB-TTL（自动排除蓝牙串口）")
        self.auto_connect.setChecked(True)
        connection_layout.addLayout(port_row)
        connection_layout.addWidget(self.serial_status)
        connection_layout.addWidget(self.auto_connect)
        layout.addWidget(connection)

        diagnostics = self._section("自动自检")
        self.diagnostic_overall = QLabel("等待设备连接")
        self.diagnostic_overall.setObjectName("diagnosticOverall")
        self.diagnostic_overall.setProperty("state", CheckState.WAITING.value)
        diagnostics.layout().addWidget(self.diagnostic_overall)
        diagnostics_grid = QGridLayout()
        diagnostics_grid.setHorizontalSpacing(8)
        diagnostics_grid.setVerticalSpacing(4)
        for row, result in enumerate(self.diagnostics.results()):
            name = QLabel(result.label)
            name.setObjectName("fieldName")
            state = QLabel("● 等待")
            state.setObjectName("diagnosticState")
            state.setProperty("state", result.state.value)
            state.setToolTip(result.detail)
            self.diagnostic_rows[result.key] = state
            diagnostics_grid.addWidget(name, row, 0)
            diagnostics_grid.addWidget(state, row, 1)
        diagnostics.layout().addLayout(diagnostics_grid)
        reset_diagnostics = QPushButton("重新开始自检")
        reset_diagnostics.clicked.connect(self.reset_diagnostics)
        diagnostics.layout().addWidget(reset_diagnostics)
        layout.addWidget(diagnostics)

        cards = QGridLayout()
        cards.setSpacing(8)
        self.alarm_card = MetricCard("系统状态")
        self.distance_card = MetricCard("前方距离", "cm")
        self.lux_card = MetricCard("环境光照", "lx")
        self.rssi_card = MetricCard("Wi-Fi 信号", "dBm")
        cards.addWidget(self.alarm_card, 0, 0, 1, 2)
        cards.addWidget(self.distance_card, 1, 0)
        cards.addWidget(self.lux_card, 1, 1)
        cards.addWidget(self.rssi_card, 2, 0)
        self.satellite_card = MetricCard("GPS 卫星", "颗")
        cards.addWidget(self.satellite_card, 2, 1)
        self.heart_rate_card = MetricCard("心率估算", "bpm")
        self.spo2_card = MetricCard("血氧估算", "%")
        self.ppg_quality_card = MetricCard("PPG 质量", "%")
        self.rhythm_card = MetricCard("节律筛查")
        cards.addWidget(self.heart_rate_card, 3, 0)
        cards.addWidget(self.spo2_card, 3, 1)
        cards.addWidget(self.ppg_quality_card, 4, 0)
        cards.addWidget(self.rhythm_card, 4, 1)
        layout.addLayout(cards)

        imu = self._section("JY901S 姿态与惯性")
        imu_grid = QGridLayout()
        self.imu_values: dict[str, QLabel] = {}
        imu_fields = [
            ("ax_g", "AX", "g"), ("ay_g", "AY", "g"), ("az_g", "AZ", "g"),
            ("gyro_x_dps", "GX", "°/s"), ("gyro_y_dps", "GY", "°/s"),
            ("gyro_z_dps", "GZ", "°/s"), ("roll_deg", "横滚", "°"),
            ("pitch_deg", "俯仰", "°"), ("yaw_deg", "航向", "°"),
        ]
        for index, (key, name, unit) in enumerate(imu_fields):
            name_label = QLabel(name)
            name_label.setObjectName("fieldName")
            value = QLabel("—")
            value.setObjectName("fieldValue")
            self.imu_values[key] = value
            cell = QHBoxLayout()
            cell.addWidget(name_label)
            cell.addStretch(1)
            cell.addWidget(value)
            cell.addWidget(QLabel(unit))
            imu_grid.addLayout(cell, index // 3, index % 3)
        imu.layout().addLayout(imu_grid)
        layout.addWidget(imu)

        capture = self._section("跌倒检测 · 高频 IMU 数据采集")
        capture_form = QGridLayout()
        capture_form.addWidget(QLabel("试验编号"), 0, 0)
        self.capture_trial = QLineEdit("T001")
        self.capture_trial.setPlaceholderText("例如 T001")
        capture_form.addWidget(self.capture_trial, 0, 1)
        capture_form.addWidget(QLabel("场景标签"), 1, 0)
        self.capture_scene = QComboBox()
        for display, label, ground_truth in SCENARIOS:
            self.capture_scene.addItem(display, (label, ground_truth))
        capture_form.addWidget(self.capture_scene, 1, 1)
        capture.layout().addLayout(capture_form)

        capture_buttons = QHBoxLayout()
        self.capture_start_button = QPushButton("开始记录")
        self.capture_start_button.setObjectName("primaryButton")
        self.capture_start_button.clicked.connect(self.start_imu_capture)
        self.capture_mark_button = QPushButton("动作开始")
        self.capture_mark_button.clicked.connect(self.mark_imu_action)
        self.capture_mark_button.setEnabled(False)
        self.capture_stop_button = QPushButton("停止并保存")
        self.capture_stop_button.clicked.connect(lambda: self.stop_imu_capture())
        self.capture_stop_button.setEnabled(False)
        capture_buttons.addWidget(self.capture_start_button)
        capture_buttons.addWidget(self.capture_mark_button)
        capture_buttons.addWidget(self.capture_stop_button)
        capture.layout().addLayout(capture_buttons)

        self.capture_status = QLabel("未记录 · CSV 将保存到 imu_captures")
        self.capture_status.setObjectName("muted")
        self.capture_stats = QLabel("样本 0 · 采样率 — Hz · 丢帧 0 · 最大间隔 — ms")
        self.capture_stats.setObjectName("fieldValue")
        self.capture_campaign_stats = QLabel("累计：等待试验数据")
        self.capture_campaign_stats.setObjectName("muted")
        capture.layout().addWidget(self.capture_status)
        capture.layout().addWidget(self.capture_stats)
        capture.layout().addWidget(self.capture_campaign_stats)
        self.imu_plot = ImuPlotWidget()
        capture.layout().addWidget(self.imu_plot)
        plot_note = QLabel("青色 A / 橙色 G / 紫色 Tilt；红色虚线为当前固件阈值")
        plot_note.setObjectName("muted")
        capture.layout().addWidget(plot_note)
        open_captures = QPushButton("打开 CSV 目录")
        open_captures.clicked.connect(self.open_capture_folder)
        capture.layout().addWidget(open_captures)
        layout.addWidget(capture)
        self.refresh_campaign_metrics()

        ppg_capture = self._section("MAX30102 · PPG/血氧数据采集")
        ppg_form = QGridLayout()
        ppg_form.addWidget(QLabel("试验编号"), 0, 0)
        self.ppg_trial = QLineEdit("P001")
        self.ppg_trial.setPlaceholderText("例如 P001")
        ppg_form.addWidget(self.ppg_trial, 0, 1)
        ppg_form.addWidget(QLabel("测试场景"), 1, 0)
        self.ppg_scene = QComboBox()
        for display, label, expected_state in PPG_SCENARIOS:
            self.ppg_scene.addItem(display, (label, expected_state))
        ppg_form.addWidget(self.ppg_scene, 1, 1)
        ppg_capture.layout().addLayout(ppg_form)

        ppg_buttons = QHBoxLayout()
        self.ppg_start_button = QPushButton("开始记录")
        self.ppg_start_button.setObjectName("primaryButton")
        self.ppg_start_button.clicked.connect(self.start_ppg_capture)
        self.ppg_mark_button = QPushButton("动作/放指开始")
        self.ppg_mark_button.clicked.connect(self.mark_ppg_action)
        self.ppg_mark_button.setEnabled(False)
        self.ppg_stop_button = QPushButton("停止并保存")
        self.ppg_stop_button.clicked.connect(lambda: self.stop_ppg_capture())
        self.ppg_stop_button.setEnabled(False)
        ppg_buttons.addWidget(self.ppg_start_button)
        ppg_buttons.addWidget(self.ppg_mark_button)
        ppg_buttons.addWidget(self.ppg_stop_button)
        ppg_capture.layout().addLayout(ppg_buttons)

        self.ppg_capture_status = QLabel("未记录 · CSV 将保存到 ppg_captures")
        self.ppg_capture_status.setObjectName("muted")
        self.ppg_capture_stats = QLabel("样本 0 · 目标 25 Hz · 丢帧 0 · FIFO 溢出 0")
        self.ppg_capture_stats.setObjectName("fieldValue")
        self.ppg_quality_stats = QLabel("手指 — · 有效 — · SQI —")
        self.ppg_quality_stats.setObjectName("muted")
        ppg_capture.layout().addWidget(self.ppg_capture_status)
        ppg_capture.layout().addWidget(self.ppg_capture_stats)
        ppg_capture.layout().addWidget(self.ppg_quality_stats)
        self.ppg_plot = PpgPlotWidget()
        ppg_capture.layout().addWidget(self.ppg_plot)
        ppg_note = QLabel(
            "红/青：RED/IR AC；橙：滤波 IR；白线：接受的脉搏峰；紫：SQI；"
            "硬件 100 SPS 经 4 点平均后 FIFO 实际为 25 Hz"
        )
        ppg_note.setWordWrap(True)
        ppg_note.setObjectName("muted")
        ppg_capture.layout().addWidget(ppg_note)
        open_ppg = QPushButton("打开 PPG CSV 目录")
        open_ppg.clicked.connect(self.open_ppg_capture_folder)
        ppg_capture.layout().addWidget(open_ppg)
        layout.addWidget(ppg_capture)

        controls = self._section("设备控制（串口）")
        control_grid = QGridLayout()
        sos = QPushButton("触发 SOS")
        sos.setObjectName("dangerButton")
        sos.clicked.connect(self._confirm_sos)
        cancel = QPushButton("解除锁存告警")
        cancel.clicked.connect(lambda: self._send("cancel"))
        auto = QPushButton("照明自动")
        auto.clicked.connect(lambda: self._send("light_auto"))
        light_on = QPushButton("照明开启")
        light_on.clicked.connect(lambda: self._send("light_on"))
        light_off = QPushButton("照明关闭")
        light_off.clicked.connect(lambda: self._send("light_off"))
        ping = QPushButton("通信测试")
        ping.clicked.connect(lambda: self._send("ping"))
        control_grid.addWidget(sos, 0, 0)
        control_grid.addWidget(cancel, 0, 1)
        control_grid.addWidget(auto, 1, 0)
        control_grid.addWidget(light_on, 1, 1)
        control_grid.addWidget(light_off, 2, 0)
        control_grid.addWidget(ping, 2, 1)
        controls.layout().addLayout(control_grid)
        layout.addWidget(controls)
        layout.addStretch(1)
        scroll.setWidget(panel)
        return scroll

    def _build_camera_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        heading = QLabel("OV2640 · Wi-Fi 实时图传")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        row = QHBoxLayout()
        self.camera_url = QLineEdit("http://192.168.4.1")
        self.camera_url.setPlaceholderText("http://设备IP")
        self.camera_url.textEdited.connect(lambda: setattr(self, "_camera_address_user_edited", True))
        self.camera_button = QPushButton("连接图传")
        self.camera_button.setObjectName("primaryButton")
        self.camera_button.clicked.connect(self.toggle_camera)
        row.addWidget(self.camera_url, 1)
        row.addWidget(self.camera_button)
        layout.addLayout(row)

        self.image_label = QLabel("等待 Wi-Fi 图像…")
        self.image_label.setObjectName("cameraImage")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(420, 360)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.image_label, 1)
        stats = QHBoxLayout()
        self.camera_status = QLabel("未连接")
        self.camera_status.setObjectName("muted")
        self.camera_stats = QLabel("帧 0  ·  — KiB  ·  — fps")
        self.camera_stats.setObjectName("fieldValue")
        save = QPushButton("保存当前帧")
        save.clicked.connect(self.save_frame)
        stats.addWidget(self.camera_status, 1)
        stats.addWidget(self.camera_stats)
        stats.addWidget(save)
        layout.addLayout(stats)
        return panel

    def _build_map_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        heading = QLabel("ATGM336H · GPS 地图")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        gps_grid = QGridLayout()
        self.gps_values: dict[str, QLabel] = {}
        for index, (key, name) in enumerate(
            [("lat", "纬度"), ("lon", "经度"), ("speed_kmh", "速度 km/h"),
             ("altitude_m", "海拔 m"), ("utc", "UTC"), ("fix", "定位")]
        ):
            gps_grid.addWidget(QLabel(name), index // 2, (index % 2) * 2)
            value = QLabel("—")
            value.setObjectName("fieldValue")
            self.gps_values[key] = value
            gps_grid.addWidget(value, index // 2, (index % 2) * 2 + 1)
        layout.addLayout(gps_grid)
        self.map_widget = MapWidget()
        self.map_widget.setMinimumSize(380, 380)
        layout.addWidget(self.map_widget, 1)
        controls = QHBoxLayout()
        import_button = QPushButton("导入地图/轨迹")
        import_button.clicked.connect(self.import_track)
        clear_button = QPushButton("清除导入")
        clear_button.clicked.connect(self.map_widget.clear_track)
        trail_button = QPushButton("清除实时轨迹")
        trail_button.clicked.connect(self.map_widget.clear_live_trail)
        self.follow_gps = QCheckBox("跟随 GPS")
        self.follow_gps.setChecked(True)
        self.follow_gps.toggled.connect(self.map_widget.set_follow)
        controls.addWidget(import_button)
        controls.addWidget(clear_button)
        controls.addWidget(trail_button)
        controls.addStretch(1)
        controls.addWidget(self.follow_gps)
        layout.addLayout(controls)
        note = QLabel("在线底图：OpenStreetMap；支持 GeoJSON / GPX / KML 导入")
        note.setObjectName("muted")
        layout.addWidget(note)
        return panel

    @staticmethod
    def _section(title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("section")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        layout.addWidget(label)
        return frame

    def refresh_ports(self) -> list[Any]:
        """重新枚举系统串口；data 保存真实 COM 名，文本仅供用户识别。"""
        current = self.port_combo.currentData()
        self.port_combo.clear()
        ports = sorted(list_ports.comports(), key=lambda item: item.device)
        for port in ports:
            label = f"{port.device}  ·  {port.description}"
            self.port_combo.addItem(label, port.device)
        if not ports:
            self.port_combo.addItem("未发现串口", "")
        elif current:
            index = self.port_combo.findData(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        return ports

    def _poll_ports(self) -> None:
        """定时发现 USB-TTL；只对高可信端口执行一次自动连接。"""
        ports = self.refresh_ports()
        if self.serial_worker is not None:
            return
        candidate = best_serial_port(ports)
        if candidate is None:
            self.diagnostics.set_result(
                "serial", CheckState.WAITING,
                "未发现 CH340/CP210x/FTDI；蓝牙串口不会自动连接",
            )
            self._refresh_diagnostics()
            self._last_auto_candidate = ""
            return
        index = self.port_combo.findData(candidate.device)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        if not self.auto_connect.isChecked() or time.monotonic() < self._auto_connect_after:
            return
        if candidate.device != self._last_auto_candidate:
            self.append_log("自动连接", f"发现 USB-TTL：{candidate.device} · {candidate.description}")
            self._last_auto_candidate = candidate.device
        self._start_serial(candidate.device)

    def toggle_serial(self) -> None:
        """连接或请求断开当前选择的 CH340 串口。"""
        if self.serial_worker and self.serial_worker.isRunning():
            self.auto_connect.setChecked(False)
            self.serial_button.setEnabled(False)
            self.serial_worker.stop()
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.information(self, "串口", "未发现可连接串口，请接入设备后刷新。")
            return
        self._start_serial(port)

    def _start_serial(self, port: str) -> None:
        if self.serial_worker is not None:
            return
        self._begin_log_session(port)
        self.diagnostics.reset()
        self.diagnostics.set_result("serial", CheckState.WAITING, f"正在打开 {port}")
        self._refresh_diagnostics()
        self.serial_worker = SerialWorker(port, 115200, self)
        self.serial_worker.telemetry.connect(self.apply_telemetry)
        self.serial_worker.imu_sample.connect(self.handle_imu_sample)
        self.serial_worker.ppg_sample.connect(self.handle_ppg_sample)
        self.serial_worker.connection.connect(self._serial_connection)
        self.serial_worker.message.connect(self._serial_message)
        self.serial_worker.raw_line.connect(self._serial_raw_line)
        self.serial_worker.protocol_event.connect(self._protocol_event)
        self.serial_worker.finished.connect(self._serial_finished)
        self.serial_button.setEnabled(False)
        self.serial_status.setText("正在连接…")
        self.serial_worker.start()

    def toggle_camera(self) -> None:
        """连接或请求断开 Wi-Fi 图传线程。"""
        if self.camera_worker and self.camera_worker.isRunning():
            self.camera_button.setEnabled(False)
            self.camera_worker.stop()
            return
        try:
            url = normalize_base_url(self.camera_url.text())
        except ValueError as exc:
            QMessageBox.warning(self, "设备地址", str(exc))
            return
        self.camera_url.setText(url)
        self.camera_worker = CameraWorker(url, self)
        self.camera_worker.frame.connect(self._camera_frame)
        self.camera_worker.connection.connect(self._camera_connection)
        self.camera_worker.message.connect(lambda message: self.append_log("图传", message))
        self.camera_worker.finished.connect(self._camera_finished)
        self.camera_button.setEnabled(False)
        self.camera_status.setText("正在连接…")
        self.frame_count = 0
        self.frame_started_at = time.monotonic()
        self.camera_worker.start()

    def _send(self, command: str) -> None:
        """向串口线程提交协议白名单中的逻辑命令名。"""
        if self.demo:
            self.append_log("演示", f"模拟发送：{command}")
            return
        if not self.serial_worker or not self.serial_worker.isRunning():
            QMessageBox.information(self, "设备控制", "请先连接串口。")
            return
        self.serial_worker.send(command)

    def _confirm_sos(self) -> None:
        answer = QMessageBox.question(
            self,
            "确认触发 SOS",
            "这会让设备进入锁存 SOS 告警。确认继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._send("sos")

    @property
    def _capture_directory(self) -> Path:
        return Path(__file__).resolve().parents[1] / "imu_captures"

    def start_imu_capture(self) -> None:
        if self.ppg_capture.active:
            QMessageBox.information(self, "IMU 数据采集", "请先停止 PPG 采集。两个高频串口流不能同时开启。")
            return
        if not self.demo and (not self.serial_worker or not self.serial_worker.isRunning()):
            QMessageBox.information(self, "IMU 数据采集", "请先连接 TTL 串口。")
            return
        selected = self.capture_scene.currentData()
        if not isinstance(selected, tuple) or len(selected) != 2:
            QMessageBox.warning(self, "IMU 数据采集", "请选择有效场景。")
            return
        label, ground_truth = selected
        try:
            path = self.imu_capture.start(
                self._capture_directory,
                self.capture_trial.text(),
                str(label),
                str(ground_truth),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "无法开始记录", str(exc))
            return
        self.imu_plot.clear()
        self.capture_start_button.setEnabled(False)
        self.capture_mark_button.setEnabled(True)
        self.capture_stop_button.setEnabled(True)
        self.capture_trial.setEnabled(False)
        self.capture_scene.setEnabled(False)
        self.capture_status.setText(f"正在记录 · {path.name}")
        self.capture_stats.setText("样本 0 · 等待 JY901S 新样本…")
        self._send("imu_stream_on")
        self.append_log("IMU采集", f"开始：{path} · {label} · {ground_truth}")

    def mark_imu_action(self) -> None:
        try:
            self.imu_capture.mark_action()
        except RuntimeError as exc:
            QMessageBox.information(self, "动作标记", str(exc))
            return
        self.capture_mark_button.setEnabled(False)
        self.capture_status.setText("正在记录 · 下一条 IMU 样本将标记 ACTION_START")
        self.append_log("IMU采集", "已标记动作开始")

    def stop_imu_capture(self, show_message: bool = True) -> None:
        if not self.imu_capture.active:
            return
        if self.demo or (self.serial_worker and self.serial_worker.isRunning()):
            self._send("imu_stream_off")
        summary = self.imu_capture.stop()
        self.capture_start_button.setEnabled(True)
        self.capture_mark_button.setEnabled(False)
        self.capture_stop_button.setEnabled(False)
        self.capture_trial.setEnabled(True)
        self.capture_scene.setEnabled(True)
        if summary is None:
            return
        result = (
            f"样本 {summary.samples} · {summary.rate_hz:.1f} Hz · 丢帧 {summary.dropped} "
            f"· 最大间隔 {summary.max_gap_ms:.0f} ms"
        )
        self.capture_status.setText(f"已保存 · {summary.path.name}")
        self.capture_stats.setText(result)
        self.append_log(
            "IMU采集",
            f"完成：{summary.path} · {result} · 判定={summary.classification} "
            f"· 疑似={summary.suspected_seen} · FALL={summary.fall_seen}",
        )
        self._increment_trial_id()
        self.refresh_campaign_metrics()
        if show_message:
            QMessageBox.information(
                self,
                "CSV 已保存",
                f"{summary.path}\n\n{result}\n"
                f"出现疑似跌倒：{'是' if summary.suspected_seen else '否'}\n"
                f"进入 FALL：{'是' if summary.fall_seen else '否'}\n"
                f"本次分类：{summary.classification}",
            )

    def handle_imu_sample(self, sample: dict[str, Any]) -> None:
        self.imu_plot.add_sample(sample)
        if not self.imu_capture.active:
            return
        try:
            self.imu_capture.append(sample)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            self.append_log("IMU采集", f"写入失败：{exc}")
            self.stop_imu_capture(show_message=False)
            QMessageBox.critical(self, "CSV 写入失败", str(exc))
            return
        self.capture_stats.setText(
            f"样本 {self.imu_capture.samples} · {self.imu_capture.rate_hz:.1f} Hz "
            f"· 丢帧 {self.imu_capture.dropped} · 最大间隔 {self.imu_capture.max_gap_ms:.0f} ms"
        )

    def _increment_trial_id(self) -> None:
        self._increment_trial_widget(self.capture_trial)

    @staticmethod
    def _increment_trial_widget(widget: QLineEdit) -> None:
        value = widget.text().strip()
        prefix = value.rstrip("0123456789")
        digits = value[len(prefix):]
        if not digits:
            return
        widget.setText(f"{prefix}{int(digits) + 1:0{len(digits)}d}")

    def open_capture_folder(self) -> None:
        self._capture_directory.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self._capture_directory))  # type: ignore[attr-defined]

    def refresh_campaign_metrics(self) -> None:
        metrics = campaign_metrics(self._capture_directory / "trials.csv")
        recall = metrics["recall"]
        false_positive = metrics["false_positive_rate"]
        recall_text = "—" if recall is None else f"{recall * 100:.1f}%"
        false_text = "—" if false_positive is None else f"{false_positive * 100:.1f}%"
        self.capture_campaign_stats.setText(
            f"累计：跌倒 {metrics['fall_total']} 次 · 正常 {metrics['normal_total']} 次 "
            f"· 召回率 {recall_text} · 误报率 {false_text}"
        )

    @property
    def _ppg_capture_directory(self) -> Path:
        return Path(__file__).resolve().parents[1] / "ppg_captures"

    def start_ppg_capture(self) -> None:
        if self.imu_capture.active:
            QMessageBox.information(self, "PPG 数据采集", "请先停止 IMU 采集。两个高频串口流不能同时开启。")
            return
        if not self.demo and (not self.serial_worker or not self.serial_worker.isRunning()):
            QMessageBox.information(self, "PPG 数据采集", "请先连接 TTL 串口。")
            return
        selected = self.ppg_scene.currentData()
        if not isinstance(selected, tuple) or len(selected) != 2:
            QMessageBox.warning(self, "PPG 数据采集", "请选择有效场景。")
            return
        label, expected_state = selected
        try:
            path = self.ppg_capture.start(
                self._ppg_capture_directory,
                self.ppg_trial.text(),
                str(label),
                str(expected_state),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "无法开始记录", str(exc))
            return
        self.ppg_plot.clear()
        self.ppg_start_button.setEnabled(False)
        self.ppg_mark_button.setEnabled(True)
        self.ppg_stop_button.setEnabled(True)
        for widget in (self.ppg_trial, self.ppg_scene):
            widget.setEnabled(False)
        self.ppg_capture_status.setText(f"正在记录 · {path.name}")
        self.ppg_capture_stats.setText("样本 0 · 等待 MAX30102 FIFO 样本…")
        self.ppg_quality_stats.setText("手指 — · 有效 — · SQI —")
        self._send("ppg_stream_on")
        self.append_log("PPG采集", f"开始：{path} · {label} · {expected_state}")

    def mark_ppg_action(self) -> None:
        try:
            self.ppg_capture.mark_action()
        except RuntimeError as exc:
            QMessageBox.information(self, "动作标记", str(exc))
            return
        self.ppg_mark_button.setEnabled(False)
        self.ppg_capture_status.setText("正在记录 · 下一条 PPG 样本将标记 ACTION_START")
        self.append_log("PPG采集", "已标记动作/放指开始")

    def stop_ppg_capture(self, show_message: bool = True) -> None:
        if not self.ppg_capture.active:
            return
        if self.demo or (self.serial_worker and self.serial_worker.isRunning()):
            self._send("ppg_stream_off")
        summary = self.ppg_capture.stop()
        self.ppg_start_button.setEnabled(True)
        self.ppg_mark_button.setEnabled(False)
        self.ppg_stop_button.setEnabled(False)
        for widget in (self.ppg_trial, self.ppg_scene):
            widget.setEnabled(True)
        if summary is None:
            return
        result = (
            f"样本 {summary.samples} · {summary.rate_hz:.1f} Hz · 丢帧 {summary.dropped} "
            f"· 最大间隔 {summary.max_gap_ms:.0f} ms · FIFO 溢出 {summary.fifo_overflow_max}"
        )
        quality = (
            f"手指 {summary.finger_fraction * 100:.1f}% · 有效 {summary.valid_fraction * 100:.1f}% "
            f"· SQI {summary.mean_sqi * 100:.1f}% · 削顶 {summary.clipped_fraction * 100:.2f}%"
        )
        self.ppg_capture_status.setText(f"已保存 · {summary.path.name}")
        self.ppg_capture_stats.setText(result)
        self.ppg_quality_stats.setText(quality)
        self.append_log("PPG采集", f"完成：{summary.path} · {result} · {quality}")
        self._increment_trial_widget(self.ppg_trial)
        if show_message:
            hr = "—" if summary.mean_hr_bpm is None else f"{summary.mean_hr_bpm:.1f} bpm"
            spo2 = "—" if summary.mean_spo2_pct is None else f"{summary.mean_spo2_pct:.1f}%"
            QMessageBox.information(
                self,
                "PPG CSV 已保存",
                f"{summary.path}\n\n{result}\n{quality}\n"
                f"平均 HR：{hr}\n平均 SpO₂：{spo2}",
            )

    def handle_ppg_sample(self, sample: dict[str, Any]) -> None:
        self.ppg_plot.add_sample(sample)
        if not self.ppg_capture.active:
            return
        try:
            self.ppg_capture.append(sample, self._latest_ppg_context)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            self.append_log("PPG采集", f"写入失败：{exc}")
            self.stop_ppg_capture(show_message=False)
            QMessageBox.critical(self, "PPG CSV 写入失败", str(exc))
            return
        self.ppg_capture_stats.setText(
            f"样本 {self.ppg_capture.samples} · {self.ppg_capture.rate_hz:.1f} Hz "
            f"· 丢帧 {self.ppg_capture.dropped} · 最大间隔 {self.ppg_capture.max_gap_ms:.0f} ms "
            f"· FIFO 溢出 {self.ppg_capture.fifo_overflow_max}"
        )
        self.ppg_quality_stats.setText(
            f"手指 {self.ppg_capture.finger_fraction * 100:.1f}% · "
            f"有效 {self.ppg_capture.valid_fraction * 100:.1f}% · "
            f"SQI {self.ppg_capture.mean_sqi * 100:.1f}%"
        )

    def open_ppg_capture_folder(self) -> None:
        self._ppg_capture_directory.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self._ppg_capture_directory))  # type: ignore[attr-defined]

    def apply_telemetry(self, data: dict[str, Any]) -> None:
        """把一帧 SC1 TEL 数据更新到卡片、GPS字段和地图。

        本函数只显示固件结果：valid=false 或 null 均显示为“—”，不会用 0
        填补缺失数据，也不会在电脑端推断跌倒/告警。
        """
        self.last_telemetry_at = time.monotonic()
        self.packet_count += 1
        self.diagnostics.consume_telemetry(data)
        self._refresh_diagnostics()
        alarm = str(data.get("alarm", "NORMAL"))
        alarm_label = ALARM_LABELS.get(alarm, alarm)
        self.alarm_card.set_value(alarm_label, True)
        self.alarm_card.setProperty("alarm", alarm)
        self.alarm_card.style().unpolish(self.alarm_card)
        self.alarm_card.style().polish(self.alarm_card)
        self.distance_card.set_value(self._number(data.get("distance_cm"), 1), data.get("distance_cm") is not None)
        self.lux_card.set_value(self._number(data.get("lux"), 1), data.get("lux") is not None)
        self.rssi_card.set_value(self._number(data.get("rssi"), 0), bool(data.get("ip")))

        vitals = data.get("vitals") if isinstance(data.get("vitals"), dict) else {}
        vitals_valid = bool(vitals.get("valid"))
        finger_present = bool(vitals.get("finger"))
        self.heart_rate_card.set_value(
            self._number(vitals.get("heart_rate_bpm"), 0), vitals_valid
        )
        self.spo2_card.set_value(
            self._number(vitals.get("spo2_pct"), 0), vitals_valid
        )
        quality = vitals.get("signal_quality")
        quality_text = (f"{float(quality) * 100:.0f}"
                        if self._finite(quality) and finger_present else "—")
        self.ppg_quality_card.set_value(quality_text, finger_present)
        rhythm = vitals.get("rhythm") if isinstance(vitals.get("rhythm"), dict) else {}
        rhythm_names = {
            "DISABLED": "未启用", "NO_SENSOR": "无传感器", "NO_FINGER": "未放手指",
            "COLLECTING": "采集中", "MOTION_ARTIFACT": "运动干扰",
            "INCONCLUSIVE": "无法判断", "NORMAL": "节律规则",
            "IRREGULAR": "节律不规则", "SUSPECTED_AF": "疑似异常",
        }
        rhythm_state = str(rhythm.get("state") or "DISABLED")
        self.rhythm_card.set_value(
            rhythm_names.get(rhythm_state, rhythm_state),
            bool(rhythm.get("valid")) or rhythm_state in {"COLLECTING", "NO_FINGER"},
        )

        imu = data.get("imu") if isinstance(data.get("imu"), dict) else {}
        imu_valid = bool(imu.get("valid"))
        # aliases 兼容早期固件字段，当前协议优先使用带单位后缀的新字段。
        aliases = {"roll_deg": "roll", "pitch_deg": "pitch", "yaw_deg": "yaw"}
        for key, label in self.imu_values.items():
            value = imu.get(key, imu.get(aliases.get(key, "")))
            label.setText(self._number(value, 2) if imu_valid else "—")
        try:
            ax, ay, az = (float(imu.get(name)) for name in ("ax_g", "ay_g", "az_g"))
            gx, gy, gz = (float(imu.get(name)) for name in ("gyro_x_dps", "gyro_y_dps", "gyro_z_dps"))
            imu_accel_g = math.sqrt(ax * ax + ay * ay + az * az)
            imu_gyro_dps = math.sqrt(gx * gx + gy * gy + gz * gz)
        except (TypeError, ValueError):
            imu_accel_g = imu_gyro_dps = math.nan
        self._latest_ppg_context = {
            "rhythm_state": rhythm_state,
            "rhythm_valid": int(bool(rhythm.get("valid"))),
            "rhythm_confidence": rhythm.get("confidence", ""),
            "model_calibrated": int(bool(rhythm.get("model_calibrated"))),
            "rhythm_ibi_mean_ms": rhythm.get("ibi_mean_ms", ""),
            "rhythm_sdnn_ms": rhythm.get("sdnn_ms", ""),
            "rhythm_rmssd_ms": rhythm.get("rmssd_ms", ""),
            "rhythm_pnn50": rhythm.get("pnn50", ""),
            "rhythm_beat_count": rhythm.get("beat_count", ""),
            "rhythm_inference_us": rhythm.get("inference_us", ""),
            "rhythm_inference_count": rhythm.get("inference_count", ""),
            "rhythm_model_bytes": rhythm.get("model_bytes", ""),
            "rhythm_classifier_state_bytes": rhythm.get("classifier_state_bytes", ""),
            "imu_accel_g": imu_accel_g,
            "imu_gyro_dps": imu_gyro_dps,
        }

        gps = data.get("gps") if isinstance(data.get("gps"), dict) else {}
        gps_valid = bool(gps.get("valid"))
        self.satellite_card.set_value(str(gps.get("satellites", 0)), gps_valid)
        self.gps_values["lat"].setText(self._number(gps.get("lat"), 6))
        self.gps_values["lon"].setText(self._number(gps.get("lon"), 6))
        self.gps_values["speed_kmh"].setText(self._number(gps.get("speed_kmh"), 1))
        self.gps_values["altitude_m"].setText(self._number(gps.get("altitude_m"), 1))
        self.gps_values["utc"].setText(str(gps.get("utc") or "—"))
        self.gps_values["fix"].setText("有效" if gps_valid else "未定位")
        if gps_valid and self._finite(gps.get("lat")) and self._finite(gps.get("lon")):
            latitude = float(gps["lat"])
            longitude = float(gps["lon"])
            popup = f"GPS {latitude:.6f}, {longitude:.6f} · {gps.get('satellites', 0)} 星"
            self.map_widget.update_gps(latitude, longitude, popup)

        ip = str(data.get("ip") or "")
        if ip and ip != "0.0.0.0" and not self._camera_address_user_edited:
            self.camera_url.setText(f"http://{ip}")
        self.global_status.setText(f"遥测正常 · {self.packet_count} 帧 · {alarm_label}")
        self.global_status.setProperty("online", True)
        self.global_status.style().unpolish(self.global_status)
        self.global_status.style().polish(self.global_status)

    def import_track(self) -> None:
        """选择并解析 GeoJSON/GPX/KML，然后交给地图组件绘制。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入地图或轨迹",
            "",
            "地图与轨迹 (*.geojson *.json *.gpx *.kml);;GeoJSON (*.geojson *.json);;GPX (*.gpx);;KML (*.kml)",
        )
        if not path:
            return
        try:
            data = load_track(path)
        except TrackImportError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.map_widget.set_track(data, Path(path).stem)
        self.append_log("地图", f"已导入 {Path(path).name}，{len(data.get('features', []))} 个图层对象")

    def save_frame(self) -> None:
        if not self.current_jpeg:
            QMessageBox.information(self, "保存图像", "当前还没有收到图像。")
            return
        default = f"smartcane_{datetime.now():%Y%m%d_%H%M%S}.jpg"
        path, _ = QFileDialog.getSaveFileName(self, "保存当前帧", default, "JPEG (*.jpg *.jpeg)")
        if path:
            Path(path).write_bytes(self.current_jpeg)
            self.append_log("图传", f"图像已保存：{path}")

    def start_demo(self) -> None:
        """启动无硬件演示数据，用于界面验收，不写入任何实机状态。"""
        self.demo_timer = QTimer(self)
        self.demo_timer.setInterval(250)
        self.demo_timer.timeout.connect(self._demo_tick)
        self.demo_timer.start()
        self.serial_status.setText("演示数据 · 115200 bit/s")
        self.camera_status.setText("演示图传")
        self.serial_button.setEnabled(False)
        self.camera_button.setEnabled(False)
        self.auto_connect.setEnabled(False)
        self.diagnostics.set_serial(True, "演示串口")
        self.diagnostics.consume_protocol("hello", {"version": 1})
        self._refresh_diagnostics()
        self.append_log("演示", "已启动无硬件演示模式")

    def _demo_tick(self) -> None:
        self._demo_phase += 0.08
        lat = 30.5728 + math.sin(self._demo_phase) * 0.0012
        lon = 104.0668 + math.cos(self._demo_phase) * 0.0016
        data = {
            "protocol": "smartcane.telemetry", "version": 1,
            "uptime_ms": int(self._demo_phase * 12500), "alarm": "NORMAL",
            "distance_cm": 126.0 + math.sin(self._demo_phase * 2) * 18,
            "lux": 42.0 + math.cos(self._demo_phase) * 12,
            "rssi": -48, "ip": "192.168.4.1", "camera": True,
            "imu": {"valid": True, "ax_g": 0.03, "ay_g": -0.02, "az_g": 0.998,
                    "gyro_x_dps": 0.4, "gyro_y_dps": -0.3, "gyro_z_dps": 0.1,
                    "roll_deg": math.sin(self._demo_phase) * 3.5,
                    "pitch_deg": math.cos(self._demo_phase) * 2.2,
                    "yaw_deg": (self._demo_phase * 8) % 360},
            "gps": {"valid": True, "lat": lat, "lon": lon, "speed_kmh": 3.8,
                     "altitude_m": 503.2, "satellites": 12,
                     "utc": datetime.utcnow().strftime("%H:%M:%S")},
            "vitals": {
                "online": True, "finger": True, "valid": True,
                "signal_quality": 0.88, "heart_rate_bpm": 76.0, "spo2_pct": 98.0,
                "rhythm": {"state": "NORMAL", "valid": True, "alert": False},
            },
            "mqtt": {"enabled": True, "connected": True, "state": "ONLINE"},
        }
        self.apply_telemetry(data)
        if self.imu_capture.active:
            self._demo_imu_sequence += 1
            ax, ay, az = 0.03, -0.02, 0.998
            gx, gy, gz = 0.4, -0.3, 0.1
            roll = math.sin(self._demo_phase) * 3.5
            pitch = math.cos(self._demo_phase) * 2.2
            self.handle_imu_sample({
                "seq": self._demo_imu_sequence,
                "t_ms": int(time.monotonic() * 1000) & 0xFFFFFFFF,
                "ax_g": ax, "ay_g": ay, "az_g": az,
                "gx_dps": gx, "gy_dps": gy, "gz_dps": gz,
                "roll_deg": roll, "pitch_deg": pitch,
                "yaw_deg": (self._demo_phase * 8) % 360,
                "a_g": math.sqrt(ax * ax + ay * ay + az * az),
                "g_dps": math.sqrt(gx * gx + gy * gy + gz * gz),
                "tilt_deg": max(abs(roll), abs(pitch)),
                "fall_phase": "IDLE", "free_fall": False,
                "impact": False, "tilted_still": False,
                "alarm": "NORMAL", "fall_suspected": False,
                "fall_latched": False,
            })
        if self.ppg_capture.active:
            for _ in range(6):
                self._demo_ppg_sequence += 1
                phase = self._demo_ppg_sequence * 2.0 * math.pi * 1.2 / 25.0
                ir_ac = 5200.0 * math.sin(phase)
                red_ac = 3300.0 * math.sin(phase - 0.08)
                self.handle_ppg_sample({
                    "seq": self._demo_ppg_sequence,
                    "t_ms": self._demo_ppg_sequence * 40,
                    "red": int(112000 + red_ac), "ir": int(128000 + ir_ac),
                    "red_dc": 112000.0, "ir_dc": 128000.0,
                    "red_ac": red_ac, "ir_ac": ir_ac,
                    "filtered_ir": ir_ac * 0.82, "envelope": 4200.0,
                    "peak_candidate": math.sin(phase) > 0.96,
                    "beat_accepted": math.sin(phase) > 0.96,
                    "ibi_ms": 833.0 if math.sin(phase) > 0.96 else math.nan,
                    "finger": True, "sqi": 0.88, "hr_bpm": 72.0,
                    "spo2_pct": 98.0, "valid": True, "fifo_overflow": 0,
                })
        if int(self._demo_phase * 10) % 8 == 0:
            self._draw_demo_frame()

    def _draw_demo_frame(self) -> None:
        image = QImage(1280, 720, QImage.Format_RGB32)
        image.fill(QColor("#07101c"))
        painter = QPainter(image)
        painter.fillRect(0, 390, 1280, 330, QColor("#15283a"))
        painter.setPen(QColor("#45e0cd"))
        painter.setFont(QFont("Microsoft YaHei UI", 34, QFont.Bold))
        painter.drawText(56, 86, "SMARTCANE · OV2640")
        painter.setPen(QColor("#dce8f8"))
        painter.setFont(QFont("Microsoft YaHei UI", 22))
        painter.drawText(58, 136, "Wi-Fi 图传演示画面")
        painter.setPen(QColor("#ffb454"))
        painter.drawLine(640, 220, 520, 720)
        painter.drawLine(640, 220, 760, 720)
        painter.setPen(QColor("#91a4c2"))
        painter.setFont(QFont("Consolas", 18))
        painter.drawText(58, 680, datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])
        painter.end()
        self.current_jpeg = b""
        self.current_pixmap = QPixmap.fromImage(image)
        self.frame_count += 1
        self._show_scaled_pixmap()
        self.camera_stats.setText(f"演示帧 {self.frame_count}  ·  1280×720")

    def _serial_connection(self, connected: bool, text: str) -> None:
        self.serial_status.setText(text)
        self.serial_button.setText("断开" if connected else "连接")
        self.serial_button.setEnabled(True)
        self.port_combo.setEnabled(not connected)
        self.diagnostics.set_serial(connected, text)
        self._refresh_diagnostics()
        if not connected:
            if self.imu_capture.active:
                self.stop_imu_capture(show_message=False)
            if self.ppg_capture.active:
                self.stop_ppg_capture(show_message=False)
            self._auto_connect_after = time.monotonic() + 5.0
        self.append_log("串口", text)

    def _serial_message(self, kind: str, message: str) -> None:
        # 普通设备日志已由 raw_line 完整处理，避免界面和日志文件重复两份。
        if kind != "log":
            self.append_log(kind.upper(), message)

    def _serial_raw_line(self, line: str) -> None:
        self._write_session_log("RAW", line)
        self.diagnostics.consume_log(line)
        self._refresh_diagnostics()
        high_rate = line.startswith("SC1 IMU ") or line.startswith("SC1 PPG ")
        if not line.startswith("SC1 TEL ") and not high_rate and "[State]" not in line:
            self.append_log("设备", line, archive=False)

    def _protocol_event(self, kind: str, payload: Any) -> None:
        self.diagnostics.consume_protocol(kind, payload)
        self._refresh_diagnostics()

    def _serial_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, SerialWorker):
            # finished 信号返回主线程时，Qt 仍在完成最后的信号派发；延迟释放
            # Python 包装对象可避免 Windows/PyQt5 下 QThread 被过早析构。
            self._retired_serial_workers.append(worker)
        if self.imu_capture.active:
            self.stop_imu_capture(show_message=False)
        if self.ppg_capture.active:
            self.stop_ppg_capture(show_message=False)
        if self.serial_worker is worker:
            self.serial_worker = None
        self.serial_button.setText("连接")
        self.serial_button.setEnabled(True)
        self.port_combo.setEnabled(True)
        self._close_log_session()
        if isinstance(worker, SerialWorker):
            QTimer.singleShot(1000, lambda saved=worker: self._release_serial_worker(saved))

    def _release_serial_worker(self, worker: SerialWorker) -> None:
        if worker.isRunning():
            return
        if worker in self._retired_serial_workers:
            self._retired_serial_workers.remove(worker)
        worker.deleteLater()

    def _camera_connection(self, connected: bool, text: str) -> None:
        self.camera_status.setText(text)
        self.camera_button.setText("断开图传" if connected else "连接图传")
        self.camera_button.setEnabled(True)
        self.camera_url.setEnabled(not connected)
        self.append_log("图传", text)

    def _camera_finished(self) -> None:
        self.camera_worker = None
        self.camera_button.setText("连接图传")
        self.camera_button.setEnabled(True)
        self.camera_url.setEnabled(True)

    def _camera_frame(self, payload: bytes, latency_ms: float, size: int) -> None:
        # 只有 Qt 能解码的完整 JPEG 才更新当前帧和统计信息。
        pixmap = QPixmap()
        if not pixmap.loadFromData(payload, "JPEG"):
            self.append_log("图传", "收到无效 JPEG，已丢弃")
            return
        self.current_jpeg = payload
        self.current_pixmap = pixmap
        self.frame_count += 1
        elapsed = max(0.01, time.monotonic() - self.frame_started_at)
        fps = self.frame_count / elapsed
        latency = f" · {latency_ms:.0f} ms" if latency_ms else ""
        self.camera_stats.setText(f"帧 {self.frame_count}  ·  {size / 1024:.1f} KiB  ·  {fps:.1f} fps{latency}")
        self._show_scaled_pixmap()

    def _show_scaled_pixmap(self) -> None:
        if self.current_pixmap.isNull():
            return
        self.image_label.setPixmap(
            self.current_pixmap.scaled(
                self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    def _check_telemetry_age(self) -> None:
        if not self.last_telemetry_at:
            return
        age = time.monotonic() - self.last_telemetry_at
        if age > 2.0:
            self.diagnostics.mark_telemetry_stale(age)
            self._refresh_diagnostics()
            self.global_status.setText(f"遥测超时 · {age:.1f} s")
            self.global_status.setProperty("online", False)
            self.global_status.style().unpolish(self.global_status)
            self.global_status.style().polish(self.global_status)

    def _refresh_diagnostics(self) -> None:
        names = {
            CheckState.WAITING: "等待", CheckState.OK: "正常",
            CheckState.WARN: "注意", CheckState.FAIL: "异常",
        }
        for result in self.diagnostics.results():
            label = self.diagnostic_rows.get(result.key)
            if label is None:
                continue
            label.setText(f"● {names[result.state]}")
            label.setToolTip(result.detail)
            label.setProperty("state", result.state.value)
            label.style().unpolish(label)
            label.style().polish(label)
        state, summary = self.diagnostics.overall()
        self.diagnostic_overall.setText(summary)
        self.diagnostic_overall.setProperty("state", state.value)
        self.diagnostic_overall.style().unpolish(self.diagnostic_overall)
        self.diagnostic_overall.style().polish(self.diagnostic_overall)

    def reset_diagnostics(self) -> None:
        self.diagnostics.reset()
        if self.serial_worker and self.serial_worker.isRunning():
            port = self.serial_worker.port
            self.diagnostics.set_serial(True, f"已连接 {port} · 115200")
            self.serial_worker.send("get")
        self.packet_count = 0
        self.last_telemetry_at = 0.0
        self._refresh_diagnostics()
        self.append_log("自检", "已清空判定，等待新日志和遥测")

    @property
    def _log_directory(self) -> Path:
        return Path(__file__).resolve().parents[1] / "logs"

    def _begin_log_session(self, port: str) -> None:
        self._close_log_session()
        self._log_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        safe_port = "".join(character for character in port if character.isalnum() or character in "-_")
        self.session_log_path = self._log_directory / f"smartcane_{timestamp}_{safe_port}.log"
        self._session_log = self.session_log_path.open("a", encoding="utf-8", buffering=1)
        self.log_file_label.setText(self.session_log_path.name)
        self.log_file_label.setToolTip(str(self.session_log_path))
        self._write_session_log("SESSION", f"开始抓取 {port} · 115200 bit/s")

    def _close_log_session(self) -> None:
        if self._session_log is not None:
            self._session_log.flush()
            self._session_log.close()
            self._session_log = None

    def _write_session_log(self, source: str, message: str) -> None:
        if self._session_log is None:
            return
        self._session_log.write(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S.%f}] [{source}] {message}\n"
        )

    def open_log_folder(self) -> None:
        self._log_directory.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self._log_directory))  # type: ignore[attr-defined]

    def export_log(self) -> None:
        if not self.session_log_path or not self.session_log_path.exists():
            QMessageBox.information(self, "导出日志", "当前还没有串口日志。")
            return
        if self._session_log is not None:
            self._session_log.flush()
        default = f"SmartCane调试日志_{datetime.now():%Y%m%d_%H%M%S}.log"
        path, _ = QFileDialog.getSaveFileName(self, "导出本次日志", default, "日志文件 (*.log *.txt)")
        if path:
            target = Path(path)
            if target.resolve() != self.session_log_path.resolve():
                shutil.copy2(self.session_log_path, target)
            self.append_log("日志", f"已导出：{target}")

    def append_log(self, source: str, message: str, archive: bool = True) -> None:
        self.log.append(f"[{datetime.now():%H:%M:%S}] [{source}] {message}")
        if archive:
            self._write_session_log(source, message)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._show_scaled_pixmap()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.port_timer.stop()
        self.health_timer.stop()
        if self.imu_capture.active:
            self.stop_imu_capture(show_message=False)
        if self.ppg_capture.active:
            self.stop_ppg_capture(show_message=False)
        if self.serial_worker and self.serial_worker.isRunning():
            self.serial_worker.stop()
            self.serial_worker.wait(2500)
        if self.camera_worker and self.camera_worker.isRunning():
            self.camera_worker.stop()
            self.camera_worker.wait(3000)
        self._close_log_session()
        event.accept()

    @staticmethod
    def _number(value: Any, decimals: int) -> str:
        if not MainWindow._finite(value):
            return "—"
        return f"{float(value):.{decimals}f}"

    @staticmethod
    def _finite(value: Any) -> bool:
        try:
            return value is not None and math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#08111f; color:#dce8f8; font-family:'Microsoft YaHei UI'; font-size:13px; }
            QLabel#title { font-size:25px; font-weight:700; color:#f6f9ff; }
            QLabel#subtitle, QLabel#muted { color:#8195b2; }
            QLabel#globalStatus { padding:8px 13px; border-radius:9px; background:#17243a; color:#ffbf69; font-weight:700; }
            QLabel#globalStatus[online="true"] { color:#45e0cd; background:#11302f; }
            QLabel#diagnosticOverall { padding:8px 10px; border-radius:7px; background:#17243a; color:#9fb2ce; font-weight:700; }
            QLabel#diagnosticOverall[state="ok"] { color:#45e0cd; background:#11302f; }
            QLabel#diagnosticOverall[state="warn"] { color:#ffbf69; background:#352815; }
            QLabel#diagnosticOverall[state="fail"] { color:#ff7188; background:#351622; }
            QLabel#diagnosticState { font-weight:700; color:#8195b2; }
            QLabel#diagnosticState[state="ok"] { color:#45e0cd; }
            QLabel#diagnosticState[state="warn"] { color:#ffbf69; }
            QLabel#diagnosticState[state="fail"] { color:#ff7188; }
            QFrame#panel, QFrame#section, QFrame#metricCard { background:#0f1b2d; border:1px solid #22334e; border-radius:12px; }
            QFrame#metricCard[online="false"] QLabel#metricValue { color:#687a94; }
            QFrame#metricCard[alarm="SOS"], QFrame#metricCard[alarm="FALL"], QFrame#metricCard[alarm="DANGER"] { border:1px solid #ff667f; background:#2c1724; }
            QLabel#panelTitle { font-size:18px; font-weight:700; color:#f3f7ff; }
            QLabel#sectionTitle { color:#9fb2ce; font-weight:700; }
            QLabel#metricCaption, QLabel#fieldName, QLabel#metricUnit { color:#7f93b1; font-size:12px; }
            QLabel#metricValue { color:#45e0cd; font-size:20px; font-weight:700; }
            QLabel#fieldValue { color:#c8d7ec; font-weight:700; }
            QLabel#cameraImage { background:#02060c; border:1px solid #263954; border-radius:10px; color:#61738e; }
            QLineEdit, QComboBox, QTextEdit { background:#0a1525; border:1px solid #2a3d5a; border-radius:7px; padding:7px; selection-background-color:#2ba899; }
            QComboBox QAbstractItemView { background:#0f1b2d; color:#dce8f8; selection-background-color:#24415e; }
            QTextEdit#log { color:#9fb2ce; font-family:Consolas,'Microsoft YaHei UI'; }
            QPushButton { background:#1a2a41; color:#dce8f8; border:1px solid #304562; border-radius:7px; padding:7px 10px; }
            QPushButton:hover { background:#233a56; }
            QPushButton:disabled { color:#53647d; background:#111c2c; }
            QPushButton#primaryButton { background:#45e0cd; color:#05231f; border:0; font-weight:700; }
            QPushButton#primaryButton:hover { background:#71ebdc; }
            QPushButton#dangerButton { background:#ff667f; color:#330812; border:0; font-weight:700; }
            QCheckBox { color:#9fb2ce; }
            QScrollArea { background:transparent; }
            QSplitter::handle { background:#08111f; width:8px; }
            QScrollBar:vertical { background:#0a1525; width:10px; }
            QScrollBar::handle:vertical { background:#2a3d5a; min-height:26px; border-radius:5px; }
            """
        )
