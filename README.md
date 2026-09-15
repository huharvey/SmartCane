# SmartCane

基于 **ESP32-S3-CAM** 的智能拐杖课程原型：近障提示、跌倒告警、心率/血氧采集、Wi-Fi 图传、GPS 定位，以及 MQTT 远程监护网页。

本仓库是结题归档版本。固件对应实机调试最终代码；电路对应嘉立创工程 `智能拐杖电路设计_1.eprj2`；结构对应 `结构` 目录完整文件。跌倒检测与 MAX30102/节律筛查仅为课程演示，**不能作为医疗或人身安全认证结论**。

## 仓库结构

```text
SmartCane/
├─ firmware/          ESP32 固件、上位机、远程网页、验收材料
├─ hardware/          嘉立创电路工程、Gerber、原理图 PDF
├─ mechanical/        SolidWorks 零件/装配体、STEP、打印文件
├─ docs/              开题答辩、中期进展、结题报告（已去标识）
└─ media/             结构照片、调试截图、功能演示视频
```

| 路径 | 说明 |
|---|---|
| `firmware/` | PlatformIO / Arduino 主工程。详细说明见 [firmware/README.md](firmware/README.md) |
| `firmware/src/` | 驱动、FreeRTOS 任务、跌倒检测、MQTT、摄像头服务 |
| `firmware/upper_computer/` | Windows PyQt 上位机（串口遥测、图传、地图） |
| `firmware/remote_dashboard/` | MQTT 远程监护网页（Python） |
| `firmware/ml/rhythm/` | 节律筛查离线训练脚本（公开 MIMIC 数据包需自行下载） |
| `hardware/智能拐杖电路设计.eprj2` | 最终电路 PCB 工程 |
| `hardware/Gerber_PCB.zip` | 制板 Gerber |
| `mechanical/` | 壳体、装配体及厂商库模型（按结题结构目录原样归档） |
| `docs/` | 课程报告与答辩材料 |
| `media/videos/` | 心率血氧、跌倒告警、超声测距、实时图传 |

## 功能概览

- HC-SR04（I2C）、JY901S、ATGM336H、BH1750、SSD1306、SOS 按键、蜂鸣器、照明
- OV2640 MJPEG 图传与本地网页控制
- 双路径跌倒检测（冲击路径 + 深度失重补偿），SOS/跌倒锁存
- MAX30102 心率/血氧原型与端侧节律筛查（非医疗）
- MQTT TLS 公网遥测 + 独立远程监护网页
- 上位机：串口 JSON、图传、GPS 地图、轨迹导入

当前台架配置中，MAX30102 与超声波模块共用 I2C 地址 `0x57`，固件默认关闭超声波和 OLED，只启用 MAX30102。若要同时使用，必须在硬件上分离总线。

## 快速开始（固件）

1. 用 VS Code / PlatformIO 打开 `firmware/`。
2. 编辑 `firmware/src/config/UserConfig.h`：填写 Wi-Fi、高德静态地图 Key、MQTT Broker（仓库内均为空占位符）。
3. 选择 `esp32-s3-cam`，Build / Upload。板型为 GOOUUU ESP32-S3-CAM（8 MB Flash + OPI PSRAM），USB CDC On Boot 需关闭。
4. 串口 115200。上位机见 `firmware/upper_computer/README.md`。

热点回退（SSID 留空时）：

- SSID：`SmartCane-Camera`
- 密码：`12345678`
- 页面：`http://192.168.4.1/`

## 硬件要点

- 主控：ESP32-S3-CAM + OV2640
- I2C：SDA GPIO41、SCL GPIO42（3.3 V 上拉）
- IMU：GPIO39/38；GPS：GPIO47/21；SOS：GPIO40；蜂鸣器：GPIO1；照明：GPIO14
- 原理图 PDF 与 Gerber 在 `hardware/`；结构件在 `mechanical/`

## 归档说明

- 已移除学号、姓名等课程标识；报告正文中的姓名已替换为成员 A/B/C。
- Wi-Fi 密码、高德 Key、EMQX 账号已换成空占位符；MQTT 默认关闭。本地烧录前请自行填写。
- 运行日志、原始 MIMIC zip、含密钥的 `.bin` 固件未入库。
- 结题答辩 PPT 因体积超过 GitHub 单文件限制未放入仓库；开题/中期 PPT 与结题报告在 `docs/`。

## 许可与声明

课程项目归档，仅供学习交流。传感器告警、跌倒检测和生理信号结果均未经医疗器械验证。
