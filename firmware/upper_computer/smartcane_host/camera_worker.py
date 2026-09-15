"""Wi-Fi 图传线程：优先接收 MJPEG，失败时自动降级到 HTTP 抓拍。"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit, urlunsplit

import requests
from PyQt5.QtCore import QThread, pyqtSignal


def normalize_base_url(value: str) -> str:
    """把用户输入规范化为不带路径和末尾斜杠的设备根地址。"""
    value = value.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    parsed = urlsplit(value)
    if not parsed.hostname:
        raise ValueError("设备地址无效")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def stream_url(base_url: str) -> str:
    """根据设备根地址生成固件约定的 81 端口 MJPEG 地址。"""
    parsed = urlsplit(normalize_base_url(base_url))
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port
    stream_port = 81 if port in (None, 80) else port
    return urlunsplit((parsed.scheme, f"{host}:{stream_port}", "/stream", "", ""))


def extract_jpeg_frames(buffer: bytearray) -> list[bytes]:
    """从跨网络分块缓冲中取出所有完整 JPEG，并保留未完成尾部。"""
    frames: list[bytes] = []
    while True:
        start = buffer.find(b"\xff\xd8")
        if start < 0:
            if len(buffer) > 1:
                del buffer[:-1]
            return frames
        end = buffer.find(b"\xff\xd9", start + 2)
        if end < 0:
            if start > 0:
                del buffer[:start]
            return frames
        frames.append(bytes(buffer[start : end + 2]))
        del buffer[: end + 2]


class CameraWorker(QThread):
    """在后台接收图像，避免网络读超时冻结主界面。"""
    frame = pyqtSignal(bytes, float, int)
    connection = pyqtSignal(bool, str)
    message = pyqtSignal(str)

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self.base_url = normalize_base_url(base_url)
        self._stop_event = threading.Event()
        self._response: requests.Response | None = None

    def run(self) -> None:
        """关闭系统代理继承，依次尝试实时流和抓拍链路。"""
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": "SmartCaneUpperComputer/1.0"})
        try:
            self._run_mjpeg(session)
        except (requests.RequestException, ValueError) as exc:
            if self._stop_event.is_set():
                return
            self.message.emit(f"MJPEG 不可用，切换抓拍模式：{exc}")
            self._run_snapshots(session)
        finally:
            self.connection.emit(False, "图传未连接")
            session.close()

    def stop(self) -> None:
        self._stop_event.set()
        response = self._response
        if response is not None:
            response.close()

    def _run_mjpeg(self, session: requests.Session) -> None:
        # 不依赖 multipart 边界完整落在同一个 TCP 分块，直接按 JPEG 标志重组。
        url = stream_url(self.base_url)
        self._response = session.get(url, stream=True, timeout=(3.0, 8.0))
        self._response.raise_for_status()
        self.connection.emit(True, f"MJPEG 实时流 · {url}")
        buffer = bytearray()
        for chunk in self._response.iter_content(chunk_size=8192):
            if self._stop_event.is_set():
                return
            if not chunk:
                continue
            buffer.extend(chunk)
            self._extract_frames(buffer)
            if len(buffer) > 4 * 1024 * 1024:
                del buffer[:-2]
        if not self._stop_event.is_set():
            raise requests.ConnectionError("视频流已关闭")

    def _run_snapshots(self, session: requests.Session) -> None:
        # 抓拍模式限制请求频率，适合 MJPEG 长连接不可用时继续联调。
        url = self.base_url + "/capture"
        self.connection.emit(True, f"HTTP 抓拍 · {url}")
        while not self._stop_event.is_set():
            started = time.perf_counter()
            try:
                response = session.get(url, timeout=(3.0, 5.0))
                response.raise_for_status()
                payload = response.content
                if payload[:2] == b"\xff\xd8" and payload[-2:] == b"\xff\xd9":
                    self.frame.emit(payload, (time.perf_counter() - started) * 1000, len(payload))
                else:
                    self.message.emit("抓拍接口返回的不是 JPEG")
            except requests.RequestException as exc:
                self.message.emit(f"抓拍失败：{exc}")
                self._stop_event.wait(1.5)
                continue
            self._stop_event.wait(0.35)

    def _extract_frames(self, buffer: bytearray) -> None:
        for payload in extract_jpeg_frames(buffer):
            self.frame.emit(payload, 0.0, len(payload))
