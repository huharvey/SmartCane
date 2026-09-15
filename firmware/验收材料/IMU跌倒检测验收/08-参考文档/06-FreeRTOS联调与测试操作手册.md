# 智能拐杖 FreeRTOS 联调与测试操作手册

## 1. 本次交付范围

本工程以 GOOUUU ESP32-S3-CAM + OV2640 为主控，已将已调通的传感器驱动接入以下闭环：

- Core 1：`SensorTask` 采样 IMU、GPS、超声波、BH1750 和 SOS；`DecisionTask` 执行跌倒检测、避障优先级和状态机；`ActuatorTask` 是蜂鸣器、照明 LED 与 OLED 的唯一写入者。
- Core 0：`NetworkTask` 处理 Wi-Fi AP/STA 重连与状态发布；`TelemetryTask` 处理 `SC1` 串口协议。ESP32 的 HTTP 和相机服务由底层任务继续运行。
- `SensorSnapshotQueue`（长度 1、覆盖旧帧）把最新传感器快照交给决策任务；`ControlCommandQueue`（长度 12）接收按键、网页和串口命令；`ActuatorIntentQueue`（长度 1、覆盖旧指令）交给执行任务。
- 跌倒确认采用双路径：2.0 秒窗口内，严格路径要求冲击后倾角至少 55 度、合角速度不高于 45 deg/s 并保持 600 ms；深度低重力（不高于 0.40 g）可在未采到冲击峰值时改用 1200 ms 保持。确认后先进入 `SUSPECTED_FALL`，4 秒未取消再锁存 `FALL`。
- 避障优先级为 `SOS > FALL > DANGER <30 cm > WARNING <50 cm > CAUTION <100 cm > NORMAL`。超声波阈值带 5 cm 回差，避免边界抖动反复响。
- SOS 和跌倒会提高 MJPEG 图传帧率，并在网页/串口状态中标出 `camera_incident: true`。

> 这是课程设计/原型演示逻辑，不是医疗或人身安全认证功能。跌倒阈值必须按本机实测数据复核后再用于展示。

## 2. 当前硬件边界

已配置的引脚见 `src/config/BoardConfig.h`：I2C 为 GPIO41/42，SOS 为 GPIO40，蜂鸣器为 GPIO1，照明 LED 为 GPIO14，JY901S 为 GPIO39/38，ATGM336H 为 GPIO47/21。相机引脚由板卡固定，不可复用。

需求资料中的震动马达和低电量检测目前没有接入到已给出的板卡引脚，因此本版本不会假装控制它们；本地提醒由蜂鸣器和 LED 实现。若后续增加马达，需先补充 MOS 驱动、供电校核、GPIO 定义，再在 `DigitalOutputs` 中扩展输出，不能直接把马达接到 ESP32 GPIO。

## 3. 首次配置与编译

1. 在 VS Code 中打开 `<local-path>\SmartCane`，等待 PlatformIO 识别 `platformio.ini`。
2. 检查开发板已接到正确 COM 口。当前配置为 `COM8`；若设备管理器显示其他端口，在 `platformio.ini` 中同时修改 `upload_port` 和 `monitor_port`。
3. 按需要编辑 `src/config/UserConfig.h`：
   - 想连接路由器时填写 `WIFI_SSID` 和 `WIFI_PASSWORD`；不要提交真实密码。
   - 留空 SSID 时，设备建立热点 `SmartCane-Camera`，密码 `12345678`。
   - 图像颠倒时设置 `CAMERA_VFLIP` 或 `CAMERA_HMIRROR` 为 `true`。
4. 点击 PlatformIO 左侧栏的 **Build**。首次构建会下载 ESP32-S3 框架、编译器和工具包；必须保持网络可用且不要关闭 VS Code。
5. Build 成功后点击 **Upload**。上传失败时，按住板上的 BOOT，短按 RST，开始写入后松开 BOOT。
6. 打开 **Monitor**，波特率设为 `115200`。不接相机时可以先完成传感器和报警测试，再接 OV2640 测图传，便于定位供电问题。

命令行等效命令（在工程目录执行）：

```powershell
<local-path>\.platformio\penv\Scripts\platformio.exe run -e esp32-s3-cam
<local-path>\.platformio\penv\Scripts\platformio.exe run -e esp32-s3-cam -t upload
<local-path>\.platformio\penv\Scripts\platformio.exe device monitor -p COM8 -b 115200
```

## 4. 启动检查

启动后串口应依次出现：

```text
[SmartCane] boot
[I2C] devices: 0x23/0x5C 0x3C 0x57
[BH1750] online
[Sonar] online at 0x57
[OLED] online
[FreeRTOS] Sensor/Decision/Actuator=Core1, Network/Telemetry=Core0
[SmartCane] ready
```

`0x23` 或 `0x5C` 对应 BH1750，`0x3C` 对应 OLED，`0x57` 对应 I2C 超声波。JY901S 和 GPS 走 UART，因此不会出现在 I2C 扫描中；约 2 秒一次的 `[State]` 行中，`imu=ok` 表示 IMU 在更新，`gps=fix` 仅表示已获得室外定位。

若有某一 I2C 地址缺失，先断电检查该模块 3.3 V、GND、SDA/SCL 和上拉，不要先修改算法阈值。

### GPS 波特率诊断

将 `UserConfig.h` 的 `GPS_BAUD_DIAGNOSTIC_ON_BOOT` 临时设为 `true` 后，每次开机都会在 ESP32 的 115200 串口依次测试 `9600、4800、19200、38400、57600、115200`，每个波特率最多等待 2.5 秒。检测到两条校验正确的 NMEA 语句后会输出：

```text
[GPS-NMEA @9600] $GNRMC,...*xx
[GPS-NMEA @9600] $GNGGA,...*xx
[GPS-DIAG] detected 9600 bps
```

这证明 GPS 的 TX、波特率和 NMEA 数据链路正常；即使尚未定位，也应能看到 NMEA。若所有波特率均失败，日志会显示 `no valid NMEA found`，应检查 GPS TX 到 GPIO47、共地、供电和模块是否正常启动。确认结果后，把 `GPS_BAUD_DIAGNOSTIC_ON_BOOT` 改回 `false`，避免每次开机增加最多 15 秒的诊断等待。

## 5. 网络、网页和上位机

### 5.1 浏览器网页

热点模式下，电脑/手机连接 `SmartCane-Camera` 后访问 `http://192.168.4.1/`；路由器模式下查看 OLED 或串口 `[State]` 行中的 IP，再访问 `http://设备IP/`。

- `GET /api/status`：读取完整 JSON 状态。
- `GET /capture`：抓拍一张 JPEG。
- `GET :81/stream`：MJPEG 视频流。
- `POST /api/sos`：触发 SOS。
- `POST /api/cancel`：解除 SOS/FALL 锁存。
- `GET /api/light?mode=on|off|auto`：切换照明模式。

实体 SOS 键采用“按下切换”逻辑：正常状态下按下即触发并保持 SOS；当 SOS 或 FALL 已锁存时，再按一次即本地解除锁存。按住按键不会重复触发，松开按键没有任何动作。解除 SOS/FALL 不会关闭仍然存在的近障提醒，近障状态会依据下一帧距离数据重新判定。

网页/HTTP 回调不会直接读写 GPIO，只会向控制命令队列投递命令；队列满时 HTTP 返回 503，这是预期的保护行为。

### 5.2 串口命令

串口会周期性输出 `SC1 TEL {JSON}`。可在串口监视器一行一条发送下列命令：

```text
SC1 CMD GET
SC1 CMD SOS
SC1 CMD CANCEL
SC1 CMD LIGHT ON
SC1 CMD LIGHT OFF
SC1 CMD LIGHT AUTO
```

成功会返回 `SC1 ACK ...`；命令队列繁忙时返回 `SC1 ERR command_queue_full`。`NORMAL` 仅代表当前没有报警条件，不代表周边环境安全。

## 6. 分项联调步骤

建议按下表顺序测试，并在每一项记录固件版本、阈值版本、环境、结果和异常。

| 顺序 | 操作 | 预期结果 | 不通过时优先检查 |
|---:|---|---|---|
| 1 | 设备平放，保持障碍物大于 120 cm | OLED/网页为 `NORMAL`，蜂鸣器关闭 | 超声波有效性和距离单位 |
| 2 | 把平整障碍物置于 80 cm、40 cm、20 cm 左右 | 分别为 `CAUTION`、`WARNING`、`DANGER`；蜂鸣节奏逐渐变密 | 超声波正前方、反射面、阈值 |
| 3 | 从危险距离逐渐移远 | 超过阈值加 5 cm 后才降级，超过约 105 cm 才恢复正常 | `OBSTACLE_HYSTERESIS_CM` |
| 4 | 遮住 BH1750 | 自动照明 LED 点亮 | I2C 地址、`DARK_LUX_THRESHOLD` |
| 5 | 网页或串口切换 `LIGHT ON/OFF/AUTO` | ON 常亮，OFF 关闭常规照明，AUTO 按光照；紧急闪烁不被 OFF 抑制 | 命令 ACK 与 GPIO14/MOS |
| 6 | 按 SOS 按键，或发 `SC1 CMD SOS` | `SOS` 锁存、蜂鸣/LED 节奏启动、`camera_incident=true` | GPIO40 高电平、按键消抖、命令队列 |
| 7 | 发 `SC1 CMD CANCEL` 或 POST cancel | SOS/FALL 锁存清除；避障仍可在距离过近时继续提示 | 命令格式与串口波特率 |
| 8 | 连接热点后打开网页和视频流，再重复步骤 2、6 | 传感器与报警继续更新，异常时图传更快 | 5 V 供电余量、Wi-Fi 信号、相机排线 |
| 9 | 室外静止 1–2 分钟 | `gps.valid=true`，网页显示经纬度/卫星数 | 天空视野、GPS 天线与 UART 交叉接线 |

## 7. 跌倒检测的安全调试法

不要直接让人跌倒或用真实人身动作“验证”算法。先从传感器数据和受控的拐杖模型开始：

1. 在串口保存至少 10 组场景：静止、正常摆动、放下拐杖、靠墙、轻碰、快速晃动、受控倾倒、受控冲击后倾倒。
2. 每组记录开始/结束时间和标签。观察 JSON 中 `accel_g`、`roll_deg`、`pitch_deg` 和三个 `gyro_*_dps`。
3. 严格路径应依序出现：候选、冲击、`STRICT_HOLD`（或同时满足两路时的 `BOTH_HOLD`），保持 `FALL_TILT_HOLD_MS` 后进入 `SUSPECTED_FALL`。深度低重力旁路应出现 `DEEP_HOLD`，保持 `FALL_DEEP_TILT_HOLD_MS` 后进入 `SUSPECTED_FALL`；4 秒未取消才会令 `fall_latched=true`。
4. 对每个误报，先判断是冲击阈值、倾角阈值、静止阈值还是保持时间造成，再只改一个参数，重刷后用同一数据集复测。
5. 每次调参都在 `UserConfig.h` 注释记录数据集、日期和结论。正常摆动、靠墙和放下拐杖均不应成为“通过一次演示”的漏测项。

初始参数集中在 `src/config/UserConfig.h`，含义如下：

| 参数 | 原型冻结值 | 调整方向 |
|---|---:|---|
| `FALL_FREE_FALL_G` | 0.55 g | 误触发低重力时降低；漏检低重力时提高 |
| `FALL_DEEP_FREE_FALL_G` | 0.40 g | 深度旁路误报时降低；漏掉无冲击峰值跌倒时谨慎提高 |
| `FALL_IMPACT_G` | 2.20 g | 误触发碰撞时提高；模拟跌倒无冲击时降低 |
| `FALL_TILT_DEG` | 55° | 靠墙/放下误报时提高 |
| `FALL_STILL_GYRO_DPS` | 45 deg/s | 运动中误报时降低 |
| `FALL_SEQUENCE_WINDOW_MS` | 2000 ms | 超时漏检时提高；相隔动作被串联时降低 |
| `FALL_TILT_HOLD_MS` | 600 ms | 严格路径短暂倾斜误报时提高 |
| `FALL_DEEP_TILT_HOLD_MS` | 1200 ms | 深度旁路误报时提高；确认过慢时降低 |

## 8. 长时间稳定性与故障定位

完成分项测试后，保持网页视频流与串口上位机同时开启，连续运行至少 30 分钟；正式展示前建议再运行 2 小时。每 10 分钟记录一次：距离刷新、IMU 在线、最少可用堆、Wi-Fi/IP、是否发生重启。

- 相机开启即重启：优先检查 5 V 电源瞬态电流和 USB 线，不要先降低 FreeRTOS 优先级。
- 图传卡但避障仍正常：降低分辨率/改善 Wi-Fi；传感器和本地报警必须继续工作。
- IMU 长期 `offline`：确认 JY901S TX 接 GPIO39、共地、波特率为 9600。
- GPS 一直无定位：室内无 fix 是正常现象；移到开阔天空测试。
- 网页打不开：确认热点/同一局域网与 OLED IP；AP 模式默认 IP 是 `192.168.4.1`。
- 反复出现队列满：不要提高串口发送频率，先检查上位机是否持续发送控制命令或网络回调是否异常重复。

## 9. 验收记录模板

```text
日期/地点：
硬件版本/电源：
固件提交或文件版本：
UserConfig 参数版本：
Wi-Fi 模式（AP/STA）：
避障（80/40/20 cm）：通过 / 失败，备注：
夜间照明与手动灯：通过 / 失败，备注：
SOS 触发与取消：通过 / 失败，备注：
受控跌倒样本编号与结果：
GPS 室外定位：通过 / 失败，备注：
图传与 30 分钟稳定性：通过 / 失败，备注：
待解决问题：
```
