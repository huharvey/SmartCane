#!/usr/bin/env python3
"""本地 HTTP 相机模拟器：无硬件时验证 Qt 抓拍接收端。"""

from __future__ import annotations

import argparse
import io
import json
import math
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw, ImageFont


class FrameSource:
    """按固定周期生成并缓存一张带状态文字的测试 JPEG。"""
    def __init__(self, interval_seconds: int):
        self.interval_seconds = max(1, interval_seconds)
        self.lock = threading.Lock()
        self.frame_id = 0
        self.captured_at = 0.0
        self.jpeg = b""

    def latest(self) -> tuple[bytes, int, int]:
        with self.lock:
            now = time.monotonic()
            if not self.jpeg or now - self.captured_at >= self.interval_seconds:
                self.frame_id += 1
                self.captured_at = now
                self.jpeg = self._render(self.frame_id)
            return self.jpeg, self.frame_id, int(self.captured_at * 1000)

    @staticmethod
    def _render(frame_id: int) -> bytes:
        width, height = 960, 540
        image = Image.new("RGB", (width, height), "#08111f")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for y in range(height):
            shade = int(18 + 38 * y / height)
            draw.line((0, y, width, y), fill=(8, shade, 46 + shade // 2))
        for x in range(0, width, 80):
            draw.line((x, 0, x, height), fill="#1f3853", width=1)
        for y in range(0, height, 60):
            draw.line((0, y, width, y), fill="#1f3853", width=1)

        angle = frame_id * 0.65
        center_x = int(width / 2 + math.sin(angle) * 240)
        center_y = int(height / 2 + math.cos(angle) * 105)
        draw.ellipse(
            (center_x - 58, center_y - 58, center_x + 58, center_y + 58),
            fill="#38bdf8",
            outline="#bae6fd",
            width=5,
        )
        draw.rectangle((36, 34, 550, 145), fill="#101c2f", outline="#3b82f6", width=3)
        draw.text((58, 55), "ESP32-S3-CAM 10 SECOND SNAPSHOT DEMO", font=font, fill="white")
        draw.text((58, 82), f"FRAME ID: {frame_id}", font=font, fill="#67e8f9")
        draw.text((58, 109), datetime.now().strftime("CAPTURED: %Y-%m-%d %H:%M:%S"), font=font, fill="#cbd5e1")
        draw.text((36, height - 45), "Local mock source - replace URL with http://192.168.4.1 for ESP32", font=font, fill="#94a3b8")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88)
        return output.getvalue()


def make_handler(source: FrameSource):
    """创建共享同一个 FrameSource 的 HTTP 请求处理类。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - HTTP API name
            path = self.path.split("?", 1)[0]
            if path == "/capture":
                jpeg, frame_id, captured_at = source.latest()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Id", str(frame_id))
                self.send_header("X-Captured-At-Ms", str(captured_at))
                self.end_headers()
                self.wfile.write(jpeg)
                return
            if path == "/api/status":
                jpeg, frame_id, captured_at = source.latest()
                payload = json.dumps(
                    {
                        "ok": True,
                        "frame_id": frame_id,
                        "captured_at_ms": captured_at,
                        "size": len(jpeg),
                        "interval_ms": source.interval_seconds * 1000,
                        "ap_mode": False,
                        "ip": self.server.server_address[0],
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if path == "/":
                payload = b"ESP32-CAM mock server: use /capture or /api/status\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_error(404)

        def log_message(self, fmt, *args):
            print(f"[{datetime.now():%H:%M:%S}] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def main() -> int:
    """解析监听参数并启动本地调试服务器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()
    source = FrameSource(args.interval)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(source))
    print(f"Mock camera listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
