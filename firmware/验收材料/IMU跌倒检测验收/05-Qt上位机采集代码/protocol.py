"""上位机与固件共用的 SC1 串口行协议解析和命令白名单。"""

from __future__ import annotations

import json
import csv
from dataclasses import dataclass
from typing import Any, Literal

# 普通启动日志没有此前缀，解析器可在同一串口中安全区分机器协议。
PROTOCOL_PREFIX = "SC1 "
# 上位机只能通过此表发送已知命令，禁止把界面输入直接拼入串口。
COMMANDS = {
    "ping": "SC1 CMD PING\n",
    "get": "SC1 CMD GET\n",
    "sos": "SC1 CMD SOS\n",
    "cancel": "SC1 CMD CANCEL\n",
    "light_auto": "SC1 CMD LIGHT AUTO\n",
    "light_on": "SC1 CMD LIGHT ON\n",
    "light_off": "SC1 CMD LIGHT OFF\n",
    "imu_stream_on": "SC1 CMD IMU STREAM ON\n",
    "imu_stream_off": "SC1 CMD IMU STREAM OFF\n",
}

IMU_FIELDS = (
    "seq", "t_ms", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps",
    "roll_deg", "pitch_deg", "yaw_deg", "a_g", "g_dps", "tilt_deg",
    "fall_phase", "free_fall", "impact", "tilted_still", "alarm",
    "fall_suspected", "fall_latched",
)
IMU_FLOAT_FIELDS = {
    "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps", "roll_deg",
    "pitch_deg", "yaw_deg", "a_g", "g_dps", "tilt_deg",
}
IMU_BOOL_FIELDS = {
    "free_fall", "impact", "tilted_still", "fall_suspected", "fall_latched",
}


@dataclass(frozen=True)
class ParsedLine:
    """一行串口输入的分类结果；raw 保留原文便于调试。"""
    kind: Literal["telemetry", "imu", "imu_header", "hello", "ack", "error", "log"]
    payload: Any
    raw: str


class ProtocolError(ValueError):
    """SC1 帧类型或 JSON 载荷不符合约定。"""


def parse_line(raw: bytes | str) -> ParsedLine:
    """解析一行 UART 数据；非协议启动日志按 log 返回而不是报错。"""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", "replace").strip()
    else:
        text = raw.strip()
    if not text.startswith(PROTOCOL_PREFIX):
        return ParsedLine("log", text, text)

    if text.startswith("SC1 TEL "):
        return ParsedLine("telemetry", _json_payload(text[8:]), text)
    if text.startswith("SC1 IMU HEADER "):
        fields = tuple(item.strip() for item in text[15:].split(","))
        if fields != IMU_FIELDS:
            raise ProtocolError("IMU CSV 表头与上位机协议不一致")
        return ParsedLine("imu_header", fields, text)
    if text.startswith("SC1 IMU "):
        return ParsedLine("imu", _imu_payload(text[8:]), text)
    if text.startswith("SC1 HELLO "):
        return ParsedLine("hello", _json_payload(text[10:]), text)
    if text.startswith("SC1 ACK "):
        return ParsedLine("ack", text[8:], text)
    if text.startswith("SC1 ERR "):
        return ParsedLine("error", text[8:], text)
    raise ProtocolError(f"未知 SC1 帧类型：{text[:32]}")


def _json_payload(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"JSON 格式错误：{exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("JSON 载荷必须是对象")
    return payload


def _imu_payload(value: str) -> dict[str, Any]:
    try:
        columns = next(csv.reader([value]))
    except (csv.Error, StopIteration) as exc:
        raise ProtocolError(f"IMU CSV 格式错误：{exc}") from exc
    if len(columns) != len(IMU_FIELDS):
        raise ProtocolError(
            f"IMU CSV 字段数错误：收到 {len(columns)}，需要 {len(IMU_FIELDS)}"
        )
    payload: dict[str, Any] = dict(zip(IMU_FIELDS, columns))
    try:
        payload["seq"] = int(payload["seq"])
        payload["t_ms"] = int(payload["t_ms"])
        for name in IMU_FLOAT_FIELDS:
            payload[name] = float(payload[name])
        for name in IMU_BOOL_FIELDS:
            if payload[name] not in {"0", "1"}:
                raise ValueError(f"{name} 不是 0/1")
            payload[name] = payload[name] == "1"
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"IMU CSV 数值错误：{exc}") from exc
    return payload


def command_line(name: str) -> bytes:
    """按白名单生成 ASCII 命令，绝不向设备发送任意文本。"""
    try:
        return COMMANDS[name].encode("ascii")
    except KeyError as exc:
        raise ProtocolError(f"不支持的命令：{name}") from exc
