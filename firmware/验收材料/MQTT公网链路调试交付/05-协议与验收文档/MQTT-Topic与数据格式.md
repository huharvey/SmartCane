# MQTT Topic 与数据格式

## 1. 基本约定

- 协议：MQTT 3.1.1；
- 传输：MQTT over TLS；
- 端口：8883；
- Topic 根路径：`smartcane/device01`；
- 订阅全部上行消息：`smartcane/device01/#`；
- JSON 数值无效时使用 `null`，不伪造传感器数据。

## 2. Topic 表

| Topic | 方向 | 内容 | 周期 / QoS | Retain |
|---|---|---|---|---|
| `smartcane/device01/presence` | 设备→云端 | `online` / `offline` | 连接状态变化，QoS 1 | 是 |
| `smartcane/device01/telemetry` | 设备→云端 | 报警、传感器在线、RSSI、运行时间 | 约 5 秒，QoS 0 | 否 |
| `smartcane/device01/vitals` | 设备→云端 | 心率、血氧、PPG 质量、节律摘要 | 约 5 秒，QoS 0 | 否 |
| `smartcane/device01/gps` | 设备→云端 | 定位来源、经纬度、卫星数 | 约 10 秒，QoS 0 | 否 |
| `smartcane/device01/event` | 设备→云端 | SOS、疑似跌倒、跌倒、节律提醒 | 状态变化立即发送，QoS 1 | 否 |
| `smartcane/device01/command` | 云端→设备 | 远程命令 | QoS 1 | 否 |

`command` 在本次交付中默认关闭，设备不会订阅该 Topic。

## 3. Payload 示例

### presence

```text
online
```

### telemetry

```json
{
  "protocol": "smartcane.mqtt",
  "version": 1,
  "online": true,
  "uptime_ms": 276994,
  "alarm": "NORMAL",
  "imu_online": true,
  "max30102_online": true,
  "rssi": -28
}
```

### vitals

```json
{
  "uptime_ms": 276994,
  "vitals": {
    "online": true,
    "finger": true,
    "valid": true,
    "signal_quality": 0.96,
    "heart_rate_bpm": 78.0,
    "spo2_pct": 99.0,
    "rhythm": {
      "state": "INSUFFICIENT_SIGNAL",
      "valid": false,
      "alert": false,
      "model_calibrated": false,
      "confidence": null
    }
  }
}
```

### gps

```json
{
  "uptime_ms": 276994,
  "gps": {
    "source": "none",
    "valid": false,
    "lat": null,
    "lon": null,
    "satellites": 0
  }
}
```

### event

```json
{
  "event": "SOS",
  "event_uptime_ms": 427034,
  "vitals": {},
  "gps": {
    "source": "none",
    "valid": false,
    "lat": null,
    "lon": null,
    "satellites": 0
  }
}
```

事件类型包括：`SUSPECTED_FALL`、`FALL`、`SOS`、`RHYTHM_SCREENING_ALERT`。

## 4. 在线判定

远程网页同时满足以下条件才显示“设备在线”：

1. Broker 已连接；
2. retained `presence` 为 `online`；
3. 最近一条 `telemetry.online` 为 `true`；
4. telemetry 距当前时间不超过 15 秒。

这种判定可避免 Broker 在线但设备已失联时仍显示正常。

