# ESP32-S3-CAM 智能拐杖 Arduino 工程

本目录是仓库中的固件子工程；项目总览见仓库根目录 [README.md](../README.md)。

本工程对应 **GOOUUU ESP32-S3-CAM + OV2640**，并按所给三页原理图配置引脚。传感器、决策、执行器、网络和串口已按 FreeRTOS 多任务运行；相机、Wi-Fi 和 HTTP 服务来自 ESP32 Arduino Core。

## 详细文档

- [工程架构与每个文件的作用](docs/01-工程架构与文件说明.md)
- [ESP32-S3 Arduino 开发与调试指南（零基础）](docs/02-ESP32-Arduino开发与调试指南.md)
- [ESP32-S3-CAM 每 10 秒 Wi-Fi 图传 Demo](demos/wifi_snapshot_10s/README.md)
- [上位机与 SC1 串口通信协议](docs/03-上位机与通信协议.md)
- [硬件现状与下一阶段特色方案](docs/04-硬件现状与下一阶段特色方案.md)
- [FreeRTOS 联调与测试操作手册](docs/06-FreeRTOS联调与测试操作手册.md)
- [跌倒确认与 MAX30102 调试](docs/07-跌倒确认与MAX30102调试.md)
- [TinyML 节律筛查与 MQTT 公网接入](docs/08-TinyML节律筛查与MQTT公网接入.md)
- [MAX30102 与节律筛查调试指南](docs/09-MAX30102与节律筛查调试指南.md)
- [MAX30102 首轮无参考仪器数据分析](docs/10-MAX30102首轮无参考仪器数据分析.md)
- [公网监护网页与部署说明](remote_dashboard/README.md)
- [本轮验收进展与后续任务](验收材料/SmartCane555_本轮代码改动_调试进展与后续任务.md)
- [Windows 上位机使用说明](upper_computer/README.md)

## 本次集成交付边界

已集成并作为本次交付验收项：各传感器原始数据采集、OLED/蜂鸣器/照明硬件接口、CH340 串口 JSON 遥测与命令、Wi-Fi 摄像头服务、上位机传感器显示、MJPEG 图传、GPS 地图和 GeoJSON/GPX/KML 导入。

本次还完成了双核 FreeRTOS 调度、队列/互斥保护、经独立样本验收的双路径跌倒检测、MAX30102 心率/血氧原型、PPG 质量与 baseline 节律筛查，以及 MQTT TLS 公网遥测和独立远程监护网页。跌倒阈值已按本项目样本冻结，但这些结果仍属于课程原型，不能作为医疗或人身安全认证结论。

公网网页曾部署到云主机做课程演示。仓库中的 MQTT / Wi-Fi / 地图密钥已清空，本地复现时请自行填写 `UserConfig.h` 与 `remote_dashboard/.env`。域名和 HTTPS 是后续安全升级项，不是课程演示的硬性前置条件。

## 给后续的阅读入口

1. 先看 `src/model/SystemState.h`：这是统一的传感器数据结构、单位和有效性约定；
2. 再看 `src/app/SmartCaneApp.cpp` 的 `updateSensors()`：这里汇总各驱动的新数据并处理超时；
3. 需要核对原始协议时再进入 `src/drivers/`，不要在算法中直接读 UART/I2C；
4. 算法建议在 `updateSensors()` 之后消费 `sensors_`，输出事件交给控制层；
5. 串口/HTTP 对外字段以 `docs/03-上位机与通信协议.md` 为准。

## 已实现功能

- HC-SR04 2021 UART/IIC 版：I2C 非阻塞测距，默认地址 `0x57`；当前 MAX30102 台架配置因地址冲突暂时停用
- JY901S：解析 `0x55` 帧的加速度、角速度和欧拉角
- ATGM336H：校验并解析 RMC/GGA NMEA 语句
- BH1750 GY-302：自动识别 `0x23`/`0x5C` 地址并读取照度
- SSD1306 128x64：自带轻量显示驱动和英数字体
- SOS 按键、蜂鸣器和照明 LED：分级节奏、锁存、取消及网页/串口控制已实现
- 跌倒检测：严格冲击路径与深度失重补偿路径已实现，并完成独立样本验收
- MAX30102：心率、血氧原型、PPG 质量、IBI/HRV 特征和佩戴状态检测
- 节律筛查：端侧特征提取与 baseline TinyML 推理链已接通；训练模型替换仍待完成
- MQTT 公网通信：通过 TLS 发布 presence、telemetry、vitals、gps、event 五类主题，远程控制默认关闭
- Wi-Fi：优先连接路由器，失败后建立 `SmartCane-Camera` 热点
- OV2640：网页 MJPEG 图传、JPEG 抓拍、JSON 状态和网页控制
- 上位机：串口全量遥测/控制、Wi-Fi 图传、GPS 在线/离线矢量地图、轨迹导入
- 公网监护网页：Python 后端订阅 MQTT，向浏览器提供只读状态、SSE 实时刷新、告警事件和 GPS 地图

> 跌倒检测和 MAX30102/节律筛查均为课程原型。现有验收只能说明在本项目采集样本中通过，不能替代医疗器械验证或真实人身安全认证。

## 引脚表

| 功能 | 模块/信号 | ESP32-S3 GPIO | 板卡排针 | 方向（以 ESP32 为准） |
|---|---|---:|---:|---|
| I2C SDA | 超声波、BH1750、OLED 共用 | 41 | U3-15 | 双向 |
| I2C SCL | 超声波、BH1750、OLED 共用 | 42 | U3-16 | 输出 |
| JY901S TX | IMU 数据到主控 | 39 | U3-13 | RX |
| JY901S RX | 主控命令到 IMU | 38 | U3-12 | TX |
| ATGM336H TX | GPS 数据到主控 | 47 | U3-5 | RX |
| ATGM336H RX | 主控命令到 GPS | 21 | U3-4 | TX |
| SOS | 按下为高电平 | 40 | U3-14 | 输入 |
| 蜂鸣器 | MOS 管栅极，高电平响 | 1 | U3-18 | 输出 |
| LED/照明 | 高电平开 | 14 | U2-19 | 输出 |

相机引脚按板卡原理图固定为：SCCB `GPIO4/5`、VSYNC `6`、HREF `7`、XCLK `15`、PCLK `13`、数据线 `8/9/10/11/12/16/17/18`。这些脚不可再分配给外围模块。

## 工程结构

```text
SmartCane/
├─ SmartCane.ino                 Arduino 入口
├─ platformio.ini                PlatformIO 构建配置
└─ src/
   ├─ app/                       初始化、非阻塞调度和数据发布
   ├─ config/                    板级引脚、Wi-Fi、采样周期
   ├─ control/                   跌倒检测和分级告警状态机
   ├─ drivers/                   每个传感器/执行器的独立驱动
   ├─ model/                     传感器与系统状态模型
   └─ services/                  Wi-Fi、HTTP、摄像头和 MJPEG
```

## 首次配置

编辑 `src/config/UserConfig.h`：

1. 如需连接家中路由器，填写 `WIFI_SSID` 和 `WIFI_PASSWORD`。
2. 留空 `WIFI_SSID` 时，设备直接建立热点：
   - 热点名：`SmartCane-Camera`
   - 密码：`12345678`
   - 默认页面：`http://192.168.4.1/`
3. 图像方向不对时调整 `CAMERA_VFLIP`、`CAMERA_HMIRROR`。
4. MAX30102 与 I2C 超声波模块默认都使用 `0x57`；当前台架只启用 MAX30102。若要同时使用，必须在硬件上分离总线或更换地址/接口，不能只靠软件消除地址冲突。
5. 公网功能应填写 EMQX Broker 地址和 MQTT 设备账号；ESP32 不直接连接 ECS 公网 IP。ECS 只运行远程监护后端。
6. 跌倒、避障和任务周期参数均在同一文件中修改；修改后按操作手册重新测试。

Wi-Fi、MQTT 和地图密钥会以明文进入配置或固件。准备公开代码、答辩归档或上传仓库前，应替换为占位符并重新生成已经暴露的密码。

## 编译和烧录

### PlatformIO（推荐）

用 VS Code/PlatformIO 打开本目录，选择 `esp32-s3-cam` 环境后执行 Build 和 Upload。配置已启用 8 MB Flash、OPI PSRAM 和 `min_spiffs` 分区。实测板使用 CH340 的 UART0（当前 COM8），因此 USB CDC On Boot 必须为 Disabled；COM 号变化时同步修改 `platformio.ini` 或让 PlatformIO 自动选择。

由于 Windows 版 ESP32 链接器对中文构建路径兼容性较差，`platformio.ini` 已把生成文件放到系统临时目录；源码仍保留在当前中文目录，不影响编辑和上传。

### Arduino IDE

1. 安装 Espressif 的 `esp32` 开发板包。
2. 打开 `SmartCane.ino`。
3. 选择 `ESP32S3 Dev Module`。
4. 建议设置：Flash 8MB、PSRAM `OPI PSRAM`、USB CDC On Boot `Disabled`、Partition Scheme `Minimal SPIFFS (Large APPS)`。
5. 上传后打开 115200 波特率串口监视器。

若首次下载失败，按住板上 BOOT，再点一下 RST，开始写入后松开 BOOT。

## 开机自检

串口会先输出 I2C 扫描结果。正常情况下常见地址为：

- `0x23` 或 `0x5C`：BH1750
- `0x3C`：SSD1306
- `0x57`：HC-SR04 IIC

随后应看到各设备的 `online` 状态和周期状态行。OLED 显示告警、距离、照度、GPS 卫星数及网页 IP。

JY901S 和 ATGM336H 没有 I2C 地址，应分别从串口数据判断在线。JY901S 默认按 9600 波特率配置；若模块曾被上位机改为其他波特率，请同步修改 `BoardConfig.h` 中的 `IMU_BAUD`。

## ESP32 本地网页接口

| 地址 | 方法 | 功能 |
|---|---|---|
| `/` | GET | 中文监控和控制页面 |
| `:81/stream` | GET | MJPEG 实时流 |
| `/capture` | GET | 单张 JPEG |
| `/api/status` | GET | 距离、照度、IMU、GPS、告警和网络 JSON |
| `/api/sos` | POST | 通过命令队列触发并锁存 SOS |
| `/api/cancel` | POST | 通过命令队列解除 SOS/FALL 锁存 |
| `/api/light?mode=on/off/auto` | GET | 通过命令队列切换照明模式 |

## 公网监护网页

`remote_dashboard/` 是独立的 Python MQTT 后端和前端，不把 MQTT 密码放进浏览器，也不依赖 ESP32 的局域网 IP。当前公网第一版为只读监护，提供 `/api/status`、`/api/state` 和 SSE `/api/stream`；摄像头仍只支持本地近场访问。部署、Nginx、公网 IP 演示和真实设备验收步骤见 [部署指南](remote_dashboard/DEPLOYMENT.md)。

## 跌倒检测和分级告警

优先级为 `SOS > FALL > DANGER <30 cm > WARNING <50 cm > CAUTION <100 cm > NORMAL`。SOS/FALL 会锁存，需 `CANCEL` 解除；近障在距离有效且离开阈值回差后自动解除。跌倒规则和调参步骤见 [操作手册](docs/06-FreeRTOS联调与测试操作手册.md)。

## 硬件注意事项

- I2C 上拉必须接到 3.3 V；所给原理图中的 4.7 kΩ 上拉符合要求。
- ESP32-S3 GPIO 不耐 5 V。确认 JY901S、GPS 和超声波输出是 3.3 V TTL/I2C；若某模块 TX/SDA/SCL 为 5 V，必须加电平转换。
- 蜂鸣器由原理图中的 MOS 管驱动，不应把蜂鸣器负载直接接到 GPIO。
- 相机启动电流和 Wi-Fi 发射峰值较大，5 V 电源应留有足够余量并保持地线可靠。
- `0x57` 驱动按“写 `0x01`，等待 130 ms（额定转换约 120 ms，留 10 ms 余量），读取 24 位微米值”的 2021 IIC 协议实现。如果你的模块标签/手册给出不同地址或数据单位，只修改 `Hcsr04I2c.cpp` 的命令或换算即可，其他控制逻辑无需改动。

## 建议的实机调试顺序

1. 不装相机，确认 I2C 三个地址、IMU 帧和 GPS NMEA 正常。
2. 遮挡/移开超声波，核对 OLED 距离和三档蜂鸣器节奏。
3. 遮住 BH1750，确认自动照明；再测试网页手动开、关、自动。
4. 室外等待 GPS 定位，检查网页经纬度和卫星数。
5. 最后接相机并测试图传；若此时复位，优先排查 5 V 供电压降。
6. 跌倒阈值已冻结；如更换 IMU、安装方向或拐杖结构，再重新采集正常/跌倒样本并回归。
7. 服务器先用演示模式检查公网登录；智能拐杖在场后关闭演示模式，使用手机 4G/5G 完成一次真实 MQTT 端到端验收。
