"""串口自动发现和 SmartCane 模块自检规则。

本模块只判断“通信链路与模块是否可用于调试”，不在电脑端复制跌倒、
生命体征或告警算法。所有业务结论仍以固件遥测字段为准。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class CheckState(str, Enum):
    WAITING = "waiting"
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    state: CheckState
    detail: str


CHECK_LABELS = {
    "serial": "USB-TTL 串口",
    "protocol": "SC1 协议",
    "telemetry": "实时遥测",
    "freertos": "FreeRTOS 任务",
    "i2c": "主 I²C 总线",
    "oled": "SSD1306 OLED",
    "sonar": "超声波测距",
    "light": "BH1750 光照",
    "imu": "JY901S IMU",
    "gps": "ATGM336H GPS",
    "max30102": "MAX30102 PPG",
    "camera": "OV2640 相机",
    "mqtt": "公网 MQTT",
}


def serial_port_score(port: Any) -> int:
    """给 pyserial 端口打分；蓝牙串口永不参与自动连接。"""
    fields = [
        getattr(port, "device", ""),
        getattr(port, "description", ""),
        getattr(port, "manufacturer", ""),
        getattr(port, "hwid", ""),
    ]
    text = " ".join(str(value or "") for value in fields).lower()
    if "bluetooth" in text or "蓝牙" in text or "bthenum" in text:
        return -100

    score = 0
    keywords = {
        "ch340": 80,
        "ch341": 80,
        "wch": 60,
        "cp210": 70,
        "ftdi": 70,
        "usb-serial": 55,
        "usb serial": 55,
        "usb uart": 55,
        "uart bridge": 45,
    }
    for keyword, points in keywords.items():
        if keyword in text:
            score = max(score, points)
    if getattr(port, "vid", None) is not None:
        score += 20
    if getattr(port, "pid", None) is not None:
        score += 10
    return score


def best_serial_port(ports: Iterable[Any]) -> Any | None:
    """返回最可信的 USB-TTL 端口；没有可靠候选时返回 None。"""
    ranked = sorted(((serial_port_score(port), port) for port in ports),
                    key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] > 0 else None


class DiagnosticsEngine:
    """融合启动日志和 SC1 遥测，生成可解释的调试健康状态。"""

    CRITICAL_KEYS = ("serial", "protocol", "telemetry", "freertos", "imu")

    def __init__(self) -> None:
        self._results: dict[str, CheckResult] = {}
        self.reset()

    def reset(self) -> None:
        self._results = {
            key: CheckResult(key, label, CheckState.WAITING, "等待检测")
            for key, label in CHECK_LABELS.items()
        }

    def set_result(self, key: str, state: CheckState, detail: str) -> None:
        label = CHECK_LABELS[key]
        self._results[key] = CheckResult(key, label, state, detail)

    def set_serial(self, connected: bool, detail: str = "") -> None:
        self.set_result(
            "serial",
            CheckState.OK if connected else CheckState.FAIL,
            detail or ("串口已打开" if connected else "串口未连接"),
        )

    def consume_protocol(self, kind: str, payload: Any = None) -> None:
        if kind == "hello":
            version = payload.get("version") if isinstance(payload, dict) else None
            if version == 1:
                self.set_result("protocol", CheckState.OK, "设备握手成功，协议版本 1")
            else:
                self.set_result("protocol", CheckState.WARN, f"握手成功，未知版本 {version}")
        elif kind == "telemetry":
            self.set_result("protocol", CheckState.OK, "SC1 TEL JSON 解析正常")
        elif kind == "error":
            self.set_result("protocol", CheckState.WARN, str(payload or "设备返回协议错误"))

    def consume_log(self, line: str) -> None:
        text = line.strip()
        lower = text.lower()
        if not text:
            return

        if "[freertos] allocation failed" in lower or "task creation failed" in lower:
            self.set_result("freertos", CheckState.FAIL, text)
        elif "[freertos] sensor/decision/actuator" in lower:
            self.set_result("freertos", CheckState.OK, "五个任务已创建并完成双核分工")

        if text.startswith("[I2C] devices:"):
            devices = text.split(":", 1)[1].strip()
            state = CheckState.WARN if devices == "none" else CheckState.OK
            self.set_result("i2c", state, f"扫描结果：{devices}")

        self._consume_online_log(text, lower, "[oled]", "oled")
        self._consume_online_log(text, lower, "[sonar]", "sonar")
        self._consume_online_log(text, lower, "[bh1750]", "light")

        if lower.startswith("[max30102]"):
            if "online" in lower:
                self.set_result("max30102", CheckState.OK, text)
            elif "not found" in lower or "offline" in lower:
                self.set_result("max30102", CheckState.WARN, text)

        if "[gps] parser started" in lower or "[gps-diag] detected" in lower:
            self.set_result("gps", CheckState.WAITING, "串口解析器已启动，等待卫星定位")

        if "[camera] init failed" in lower:
            self.set_result("camera", CheckState.WARN, text)
        elif "[camera] psram=" in lower:
            self.set_result("camera", CheckState.WAITING, "相机正在初始化")

        if "[mqtt] connected" in lower:
            self.set_result("mqtt", CheckState.OK, "TLS MQTT 已连接")
        elif "[mqtt] transport or broker error" in lower:
            self.set_result("mqtt", CheckState.FAIL, text)
        elif "[mqtt] disconnected" in lower:
            self.set_result("mqtt", CheckState.WARN, "连接断开，等待自动重连")
        elif "[mqtt] waiting" in lower or "[mqtt] connecting" in lower:
            self.set_result("mqtt", CheckState.WAITING, text)

    def _consume_online_log(self, text: str, lower: str, prefix: str, key: str) -> None:
        if not lower.startswith(prefix):
            return
        if "online" in lower:
            self.set_result(key, CheckState.OK, text)
        elif "not found" in lower or "offline" in lower:
            self.set_result(key, CheckState.WARN, text)

    def consume_telemetry(self, data: dict[str, Any]) -> None:
        protocol = data.get("protocol")
        version = data.get("version")
        if protocol == "smartcane.telemetry" and version == 1:
            self.set_result("protocol", CheckState.OK, "SC1 TEL JSON 解析正常")
        else:
            self.set_result("protocol", CheckState.WARN,
                            f"遥测协议字段异常：{protocol!r} v{version!r}")
        self.set_result("telemetry", CheckState.OK, "持续收到有效遥测")
        self.set_result("freertos", CheckState.OK, "任务正在运行，遥测链路活跃")

        imu = data.get("imu") if isinstance(data.get("imu"), dict) else {}
        self.set_result(
            "imu",
            CheckState.OK if imu.get("valid") else CheckState.WARN,
            "姿态、加速度和角速度有效" if imu.get("valid") else "IMU 数据无效或已超时",
        )

        distance = data.get("distance_cm")
        self.set_result(
            "sonar", CheckState.OK if distance is not None else CheckState.WARN,
            f"距离 {distance} cm" if distance is not None else "未收到有效距离",
        )
        lux = data.get("lux")
        self.set_result(
            "light", CheckState.OK if lux is not None else CheckState.WARN,
            f"照度 {lux} lx" if lux is not None else "未收到有效照度",
        )

        gps = data.get("gps") if isinstance(data.get("gps"), dict) else {}
        if gps.get("valid"):
            self.set_result("gps", CheckState.OK,
                            f"定位有效，卫星 {gps.get('satellites', 0)} 颗")
        else:
            self.set_result("gps", CheckState.WAITING,
                            f"尚未定位，卫星 {gps.get('satellites', 0)} 颗")

        vitals = data.get("vitals") if isinstance(data.get("vitals"), dict) else {}
        if vitals.get("online"):
            detail = "模块在线"
            if vitals.get("finger"):
                detail += f"，信号质量 {float(vitals.get('signal_quality') or 0) * 100:.0f}%"
            else:
                detail += "，等待放置手指"
            self.set_result("max30102", CheckState.OK, detail)
        else:
            self.set_result("max30102", CheckState.WARN, "模块离线或未接入")

        camera = bool(data.get("camera"))
        self.set_result("camera", CheckState.OK if camera else CheckState.WARN,
                        "相机初始化完成" if camera else "相机不可用或未接入")

        mqtt = data.get("mqtt") if isinstance(data.get("mqtt"), dict) else {}
        if not mqtt.get("enabled"):
            self.set_result("mqtt", CheckState.WARN, "MQTT 未启用")
        elif mqtt.get("connected") or mqtt.get("state") == "ONLINE":
            self.set_result("mqtt", CheckState.OK, "公网 MQTT 已连接")
        elif mqtt.get("state") in {"ERROR", "CONFIG_ERROR"}:
            self.set_result("mqtt", CheckState.FAIL,
                            f"MQTT 状态：{mqtt.get('state')}")
        else:
            self.set_result("mqtt", CheckState.WAITING,
                            f"MQTT 状态：{mqtt.get('state', '等待连接')}")

    def mark_telemetry_stale(self, age_seconds: float) -> None:
        self.set_result("telemetry", CheckState.FAIL,
                        f"超过 {age_seconds:.1f} 秒未收到遥测")

    def results(self) -> list[CheckResult]:
        return [self._results[key] for key in CHECK_LABELS]

    def overall(self) -> tuple[CheckState, str]:
        critical = [self._results[key] for key in self.CRITICAL_KEYS]
        if any(result.state == CheckState.FAIL for result in critical):
            return CheckState.FAIL, "核心链路异常"
        if any(result.state == CheckState.WAITING for result in critical):
            return CheckState.WAITING, "等待核心链路完成自检"
        if any(result.state in {CheckState.WARN, CheckState.FAIL}
               for result in self._results.values()):
            return CheckState.WARN, "核心链路正常，部分模块待检查"
        # GPS 等待首次定位属于正常场景；I²C/OLED 若仍为等待，通常意味着连接
        # 上位机时启动日志已经过去，需要复位板子重新抓取，不能直接显示全绿。
        if any(self._results[key].state == CheckState.WAITING for key in ("i2c", "oled")):
            return CheckState.WARN, "核心链路正常，请复位板子补抓启动自检"
        return CheckState.OK, "核心链路与已确认模块正常"
