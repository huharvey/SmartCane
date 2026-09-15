#!/usr/bin/env python3
"""SmartCane 串口遥测、Wi-Fi 图传和 GPS 地图上位机入口。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtNetwork import QNetworkProxy
from PyQt5.QtWidgets import QApplication

from smartcane_host.main_window import MainWindow


def parse_args() -> argparse.Namespace:
    """解析演示、自动退出和验收截图参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="run without hardware using simulated data")
    parser.add_argument("--duration", type=float, default=0, help="exit automatically after N seconds")
    parser.add_argument("--screenshot", type=Path, help="save a UI screenshot before exiting")
    return parser.parse_args()


def main() -> int:
    """创建 Qt 应用并启动主窗口。"""
    args = parse_args()
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("SmartCane Upper Computer")
    app.setOrganizationName("SmartCane")
    # ESP32 热点地址必须绕过 Clash 等系统代理，否则本地请求会被转发失败。
    QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))
    window = MainWindow(demo=args.demo)
    window.show()
    if args.duration > 0:
        def finish() -> None:
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(args.screenshot), "PNG")
            window.close()
            app.quit()
        QTimer.singleShot(int(args.duration * 1000), finish)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
