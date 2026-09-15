# MQTT 调试复现与验收步骤

## 1. 准备条件

- ESP32 连接可访问互联网的 STA Wi-Fi，不能停留在 `SmartCane-Camera` 热点模式；
- Broker 支持 TLS 8883、用户名密码和 Topic ACL；
- MQTTX 使用单独的只读订阅账号；
- 设备端只允许发布自身 Topic；
- 远程命令保持关闭。

## 2. MQTTX 配置

1. 新建连接，协议选择 `mqtts://`；
2. Host 填 Broker 域名，不要带 `mqtts://` 前缀；
3. Port 填 `8883`；
4. 填写只读订阅账号和密码；
5. 开启 SSL/TLS 和证书校验；
6. MQTT Version 选择 3.1.1；
7. 开启 Auto Reconnect，Keep Alive 可设 60 秒；
8. 连接后订阅 `smartcane/device01/#`，订阅 QoS 设 1。

验收截图参考 `01-验收截图/01-MQTTX-TLS连接配置.png`。

## 3. 周期上报验收

保持设备静止在线至少 30 秒，记录各 Topic 到达时间：

- `presence`：出现 retained `online`；
- `telemetry`：约 5 秒一条；
- `vitals`：约 5 秒一条；
- `gps`：约 10 秒一条；
- telemetry 中 `imu_online`、`max30102_online` 和 `rssi` 与实际状态一致。

血氧传感器没有有效手指时，HR/SpO2 为 `null` 属于正常保护逻辑；GPS 未定位时坐标为 `null`，不能当作 `(0,0)`。

## 4. SOS 验收

1. 在安全状态下触发设备 SOS；
2. 观察本地蜂鸣器和状态变化；
3. MQTTX 应立即收到 `smartcane/device01/event`；
4. 确认 `event` 为 `SOS`，QoS 为 1；
5. 网页顶部状态应切换为“SOS 求助”；
6. 解除告警后，下一条 telemetry 应恢复 `alarm=NORMAL`。

本次实测证据见 `03-MQTTX-SOS事件-QoS1.png` 和 `05-远程监护网页-SOS状态.png`。

## 5. 运行远程网页

在 `02-远程监护网页源码` 目录打开 PowerShell：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填写 Broker 和只读 MQTT 账号。首次运行：

```powershell
.\run.ps1 -Install
.\run.ps1
```

浏览器打开 `http://127.0.0.1:8080`。只看界面、不连接 Broker 时可运行：

```powershell
.\run.ps1 -Demo
```

## 6. 网页自动测试

```powershell
python -m unittest discover -s tests -v
```

本次共运行 7 项，全部通过，覆盖：在线判定、生命体征/GPS 解包、SOS 时间线、无效 JSON、网页鉴权、健康检查和安全响应头。

## 7. 生产发布前补测

1. 设备和电脑分别使用手机热点与另一条网络，验证真正跨网络通信；
2. 运行中关闭设备 Wi-Fi，再恢复，记录自动重连时间；
3. 设备突然断电，确认 `presence=offline` 遗嘱被 Broker 保留；
4. 分别触发 `SUSPECTED_FALL`、`FALL`、`SOS` 和节律提醒；
5. 连续运行 8—24 小时，统计丢包、重连次数和内存稳定性；
6. 记录本地事件发生时间与远端收到时间，统计端到端延迟；
7. 使用 Broker ACL 实测禁止跨设备 Topic、禁止网页账号发布命令。

