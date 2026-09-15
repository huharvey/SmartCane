"""pyserial 后台线程：接收 SC1 遥测、发送白名单命令并转成 Qt 信号。"""

from __future__ import annotations

import queue
import threading
from typing import Any

import serial
from PyQt5.QtCore import QThread, pyqtSignal

from .protocol import ProtocolError, command_line, parse_line


class SerialWorker(QThread):
    """独占一个串口的收发线程，避免阻塞 Qt 界面线程。"""

    # telemetry 只传解析成功的字典；connection/message 用于界面状态和日志。
    telemetry = pyqtSignal(dict)
    imu_sample = pyqtSignal(dict)
    ppg_sample = pyqtSignal(dict)
    connection = pyqtSignal(bool, str)
    message = pyqtSignal(str, str)
    raw_line = pyqtSignal(str)
    protocol_event = pyqtSignal(str, object)

    def __init__(self, port: str, baud: int = 115200, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._stop_event = threading.Event()
        self._outgoing: queue.Queue[bytes] = queue.Queue(maxsize=32)
        self._serial: serial.Serial | None = None

    def run(self) -> None:
        """打开串口并循环处理发送队列与换行分帧数据。"""
        try:
            self._serial = serial.Serial(
                self.port,
                self.baud,
                timeout=0.15,
                write_timeout=0.5,
            )
            # 保留串口缓冲中的启动日志，供上位机完成模块自检和自动归档。
            # 即使第一行是不完整半帧，协议解析器也只会丢弃该行，不影响后续数据。
            self.connection.emit(True, f"已连接 {self.port} · {self.baud}")
            self._outgoing.put_nowait(command_line("get"))
            while not self._stop_event.is_set():
                self._flush_commands()
                raw = self._serial.readline()
                if not raw:
                    continue
                self._handle_line(raw)
        except (serial.SerialException, OSError, ValueError) as exc:
            if not self._stop_event.is_set():
                self.message.emit("error", f"串口异常：{exc}")
        finally:
            if self._serial is not None:
                try:
                    self._serial.close()
                except serial.SerialException:
                    pass
                self._serial = None
            self.connection.emit(False, "串口未连接")

    def send(self, name: str) -> bool:
        """把已验证命令放入有界队列；队列满时返回 false。"""
        try:
            payload = command_line(name)
            self._outgoing.put_nowait(payload)
            return True
        except (ProtocolError, queue.Full) as exc:
            self.message.emit("error", str(exc) or "命令队列已满")
            return False

    def stop(self) -> None:
        """请求线程安全退出；实际关闭串口在 run() 的 finally 中完成。"""
        self._stop_event.set()

    def _flush_commands(self) -> None:
        if self._serial is None:
            return
        while True:
            try:
                payload = self._outgoing.get_nowait()
            except queue.Empty:
                return
            self._serial.write(payload)
            self._serial.flush()
            self.message.emit("tx", payload.decode("ascii").strip())

    def _handle_line(self, raw: bytes) -> None:
        # 协议错误只丢弃当前行，不终止后续遥测接收。
        text = raw.decode("utf-8", "replace").rstrip("\r\n")
        if text:
            self.raw_line.emit(text)
        try:
            frame = parse_line(raw)
        except ProtocolError as exc:
            self.message.emit("error", f"协议帧已丢弃：{exc}")
            return
        if frame.kind == "telemetry":
            self.protocol_event.emit(frame.kind, frame.payload)
            self.telemetry.emit(frame.payload)
        elif frame.kind == "imu":
            self.protocol_event.emit(frame.kind, frame.payload)
            self.imu_sample.emit(frame.payload)
        elif frame.kind == "imu_header":
            self.protocol_event.emit(frame.kind, frame.payload)
            self.message.emit("rx", "设备已开启高频 IMU 数据流")
        elif frame.kind == "ppg":
            self.protocol_event.emit(frame.kind, frame.payload)
            self.ppg_sample.emit(frame.payload)
        elif frame.kind == "ppg_header":
            self.protocol_event.emit(frame.kind, frame.payload)
            self.message.emit("rx", "设备已开启高频 PPG 数据流")
        elif frame.kind == "hello":
            self.protocol_event.emit(frame.kind, frame.payload)
            self.message.emit("rx", f"设备握手：{frame.payload}")
        elif frame.kind == "ack":
            self.message.emit("ack", f"设备确认：{frame.payload}")
        elif frame.kind == "error":
            self.protocol_event.emit(frame.kind, frame.payload)
            self.message.emit("error", f"设备拒绝：{frame.payload}")
        elif frame.payload:
            self.message.emit("log", str(frame.payload))
