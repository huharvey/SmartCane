# TinyML 节律筛查与 MQTT 公网接入调试手册

本阶段在原有 MAX30102、跌倒、GPS、相机和局域网网页之上新增两条独立链路：

    MAX30102 → PPG/IBI 特征 → 端侧 TinyML 预筛查 → 网页/串口/MQTT
    ESP32-S3 → 已联网 Wi-Fi/手机热点 → TLS MQTT Broker → 异地电脑或手机

它们不会修改 SOS、疑似跌倒、确认跌倒、避障、照明或相机的控制逻辑。

> 生命体征和节律结果仅用于课程设计演示、趋势观察和“建议复测”的预筛查，不能用于医疗诊断、紧急处置或宣称诊断房颤。

## 1. 已实现的端侧节律筛查

### 1.1 数据处理流程

MAX30102 仍以 100 Hz 采样。现有的去直流、平滑、峰值检测和心率/血氧计算不变；新模块只读取已经计算好的 IBI（相邻心跳间隔）和信号质量，不会直接占用 I2C。

    RED/IR → PPG 预处理 → 峰值 → IBI 历史
                             ├─ 平均 IBI / SDNN / IBI-CV
                             ├─ RMSSD / pNN50 / 最大相邻差
                             └─ 心率 / PPG 信号质量
                                          ↓
                             INT8 六特征 TinyML 基线模型
                                          ↓
                         NORMAL / IRREGULAR / SUSPECTED_AF

模型每 5 秒推理一次，但只有同时满足下列条件时才会输出有效类别：

1. MAX30102 在线，手指持续放在传感器上；
2. PPG 信号质量至少为 0.70；
3. 已稳定采集至少 15 秒，并得到至少 12 个有效 IBI；
4. JY901S 显示拐杖基本静止。移动、抖动或接触松动会显示“请保持静止/信号不足”，不会被误判为异常。

单次较高的 AF-like 结果只显示为“节律不规则”；连续 3 个有效窗口仍为该结果时，才显示“疑似异常节律”并产生 MQTT 事件。它不会自动触发蜂鸣器、SOS、跌倒报警或摄像头事件。

### 1.2 关于 TinyML 的准确表述

当前固件部署的是一个很小的 INT8 六特征分类模型，因此整个“采样 → 特征 → 端侧推理 → 连续确认 → 网页/MQTT”链路可以完整演示，代码没有依赖 TensorFlow Lite Micro 或大型模型。

但当前 RHYTHM_MODEL_CALIBRATED = false，表示附带权重只用于验证系统集成，尚未用同类 MAX30102、同佩戴方式且有 ECG 对照的数据训练和验证。因此答辩时应表述为：

> 基于 PPG 特征的端侧异常节律预筛查基线模型。

不要表述为“已诊断房颤”或“医学级心律失常识别”。后续获得公开标注数据和本机正常 PPG 数据后，只需替换 RhythmClassifier.cpp 中的归一化常量和 INT8 权重，不需要改 MAX30102、FreeRTOS、网页或 MQTT 链路。

### 1.3 网页与串口检查

烧录后，网页会新增“节律筛查”卡片。通常依次看到：

    模块离线 / 请放置手指
    → 采集中
    → 请保持静止（如果拐杖仍在运动）
    → 节律规则

正常使用步骤：

1. 将手指稳定贴在 MAX30102 发光面上，不要大力压住；
2. 让拐杖和手尽量静止；
3. 等待至少 15 到 25 秒；
4. 查看网页卡片和串口 SC1 TEL 中的 vitals.rhythm。

有效 JSON 例子：

~~~json
"rhythm": {
  "state": "NORMAL",
  "model_available": true,
  "model_calibrated": false,
  "valid": true,
  "alert": false,
  "confidence": 0.83,
  "beat_count": 16
}
~~~

MOTION_ARTIFACT、COLLECTING、INCONCLUSIVE 都表示“当前无法可靠判断”，并不代表异常。不要通过刻意制造不规则心跳来测试；没有 ECG 参照时无法安全验证真实异常节律。

可在 UserConfig.h 调整的关键参数：

~~~cpp
RHYTHM_FEATURE_WINDOW_MS
RHYTHM_MIN_IBI_COUNT
RHYTHM_MIN_SIGNAL_QUALITY
RHYTHM_MAX_GYRO_DPS
RHYTHM_ALERT_CONSECUTIVE_WINDOWS
~~~

不要在未保存原始测试结果的情况下随意降低质量门槛或确认次数。

## 2. MQTT 公网远程通信

### 2.1 工作范围

MQTT 解决的是“异地收到状态、GPS、HR、SpO2、FALL/SOS 和节律摘要”，不是把当前 :81/stream MJPEG 视频直接发布到公网：

| 能跨公网实现 | 仍仅限局域网 |
|---|---|
| 设备在线状态、GPS、HR、SpO2、节律筛查 | 当前网页 http://设备IP/ |
| FALL、SOS、疑似跌倒和节律提示事件 | 摄像头 MJPEG :81/stream |
| 经授权的 SOS、解除告警、照明远程命令 | 直接访问 ESP32 的 HTTP 控制接口 |

不要通过端口映射直接暴露 ESP32 网页或摄像头。若后续确实需要公网视频，应单独设计云中转、鉴权和隐私方案。

### 2.2 创建 Broker 后填写配置

请自行在支持 TLS、账号密码和 Topic ACL 的 MQTT 服务中创建一个设备账号，例如 EMQX Cloud。创建账户、接受服务条款和保管密码需要由你本人完成，工程中没有保存真实云端凭据。

编辑 UserConfig.h，按服务商控制台给出的值填写：

~~~cpp
constexpr bool MQTT_ENABLED = true;
constexpr char MQTT_URI[] = "mqtts://你的Broker域名:8883";
constexpr char MQTT_USERNAME[] = "设备账号";
constexpr char MQTT_PASSWORD[] = "设备密码";
constexpr char MQTT_ROOT_CA[] = R"PEM(
-----BEGIN CERTIFICATE-----
粘贴服务商给出的根 CA PEM 全文
-----END CERTIFICATE-----
)PEM";
constexpr char MQTT_TOPIC_ROOT[] = "smartcane";
constexpr char MQTT_DEVICE_ID[] = "device01";

// 先保持 false；确认 ACL 与账号权限正确后才按需要开启。
constexpr bool MQTT_ALLOW_REMOTE_COMMANDS = false;
~~~

要求：

- 正式使用必须采用 mqtts://、端口 8883、根 CA 和账号密码；
- MQTT_ROOT_CA 为空、URI 为空或使用非 TLS URI 时，网页会显示“配置错误”，固件不会偷偷建立不安全连接；
- MQTT_ALLOW_INSECURE_TEST 仅用于隔离的短时实验，公网部署请保持 false；
- Broker ACL 应只允许本账号访问 smartcane/device01/{telemetry,vitals,gps,event,presence,command}；
- 不要把填有真实密码的 UserConfig.h 上传到公开仓库。

设备必须连接能上互联网的路由器或手机热点，即 WIFI_SSID / WIFI_PASSWORD 对应的 STA 网络。回退到 SmartCane-Camera 热点模式后，局域网网页仍能使用，但 MQTT 会自动停止，状态显示为“等待联网”。

TLS 首次联网时固件会先通过 NTP 校时。串口依次可能出现：

~~~text
[MQTT] waiting for NTP time before TLS connection
[MQTT] connecting to mqtts://...
[MQTT] connected
~~~

### 2.3 Topic 与发布频率

以 MQTT_TOPIC_ROOT = smartcane、MQTT_DEVICE_ID = device01 为例：

| Topic | 内容 | 频率/QoS |
|---|---|---|
| smartcane/device01/telemetry | 在线状态、报警、IMU/MAX30102 在线、RSSI | 5 秒，QoS 0 |
| smartcane/device01/vitals | HR、SpO2、信号质量、节律摘要 | 5 秒，QoS 0 |
| smartcane/device01/gps | 实时或最后有效 GPS | 10 秒，QoS 0 |
| smartcane/device01/event | 疑似跌倒、FALL、SOS、连续节律提示 | 立即，QoS 1 |
| smartcane/device01/presence | online / offline | retained，QoS 1 |
| smartcane/device01/command | 远程命令 | 订阅 QoS 1，默认关闭 |

公网不上传原始 RED/IR PPG，也不上传视频。这样可降低隐私、流量和 Broker 负担。

### 2.4 跨网络测试

1. 让 ESP32 连接手机热点 A 或路由器 A，确认该网络能访问互联网；
2. 在另一台电脑/手机连接网络 B；
3. 使用 MQTTX 等客户端，以相同 Broker、TLS CA、账号密码连接；
4. 订阅主题：

~~~text
smartcane/device01/#
~~~

5. 观察 presence 为 online，并每 5 至 10 秒收到三类周期消息；
6. 在本地触发 SOS、疑似跌倒和确认 FALL，确认 event 立即到达；
7. 断开设备热点或路由器，再恢复网络，确认 MQTT 自动恢复并继续上报。

开启远程命令前，先确认 ACL 已限制到设备自己的 command Topic。可发送的纯文本命令只有：

~~~text
sos
cancel
light:on
light:off
light:auto
~~~

命令仍会先进入原有 FreeRTOS 命令队列；MQTT 回调不会直接驱动蜂鸣器、灯或报警状态机。

## 3. 常见状态

| 网页 MQTT 状态 | 含义与处理 |
|---|---|
| 未启用 | MQTT_ENABLED = false，这是默认状态 |
| 配置错误 | URI、设备 ID、Topic 根或 TLS CA 缺失；检查配置 |
| 等待联网 | 当前是 AP 模式或 STA 尚未连上可上网 Wi-Fi |
| TLS 校时中 | 刚联网，等待 NTP 获得正确时间 |
| 连接中 | 正在 DNS/TLS/MQTT 建连，检查 Broker 地址、端口和账号 |
| 已连接 | 公网遥测已工作 |
| 连接错误 | 检查 CA 是否完整、账号密码、ACL、网络是否拦截 8883 |

## 4. 代码位置

- src/control/VitalsProcessor.*：IBI/HRV 特征提取；
- src/control/RhythmClassifier.*：INT8 特征模型、静止门槛和连续确认；
- src/services/MqttRemoteService.*：TLS MQTT、自动重连、Topic、事件和命令白名单；
- src/app/SmartCaneApp.*：将两者接入已有的 Core 1 SensorTask 与 Core 0 NetworkTask；
- src/services/WifiCameraServer.cpp：本地网页的节律和 MQTT 状态卡片。

编译不会上传固件；完成配置后，先 Build，再 Upload，最后以串口和 MQTT 客户端进行跨网络验证。
