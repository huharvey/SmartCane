# SmartCane 上位机

该程序同时完成三条数据链路：

- CH340 串口（115200 bit/s）：接收 5 Hz JSON 传感器遥测，保留设备控制命令入口；
- Wi-Fi HTTP/MJPEG：连接 ESP32-S3-CAM 的 81 端口实时流，断流时自动降级到 `/capture` 抓拍；
- GPS 地图：显示实时位置和轨迹，支持导入 GeoJSON、GPX、KML。

调试版还提供：自动识别 CH340/CP210x/FTDI 串口（排除蓝牙 COM）、自动保存
完整原始串口日志、启动自检解析、遥测超时告警，以及 IMU、MAX30102、摄像头、
MQTT 等模块的可视化健康判定。

地图底图使用按需加载的 OpenStreetMap 瓦片，并使用磁盘缓存；不会预下载地图。没有互联网时，底图变为暗色网格，但 GPS 点、实时轨迹和导入轨迹仍可正常显示。

## 1. 安装与启动

在本目录打开 PowerShell：

```powershell
.\run.ps1 -Install
.\run.ps1
```

只需安装一次依赖。也可以手动执行：

```powershell
python -m pip install -r requirements.txt
python main.py
```

无硬件验收界面：

```powershell
.\run.ps1 -Demo
```

## 2. 实机连接顺序

1. 给拐杖上电，将 CH340 USB 串口接到电脑。
2. 电脑连接设备热点 `SmartCane-Camera`，密码 `12345678`；若固件配置为路由器模式，则电脑和设备接入同一局域网。
3. 启动上位机，在左侧选择 COM 口并点击“连接”。当前实测板通常是 COM8，程序会自动列出所有端口。
4. 串口遥测中的 IP 会自动填入图传地址；点击“连接图传”。热点模式默认地址为 `http://192.168.4.1`。
5. GPS 室外定位后，右侧地图出现实时位置。可点击“导入地图/轨迹”加载 `.geojson`、`.gpx` 或 `.kml`。

默认勾选“自动发现并连接 USB-TTL”。插入设备后，上位机会忽略 Windows 的蓝牙
串口，优先选择 CH340、CP210x 或 FTDI；连接成功后在 `upper_computer/logs/`
自动创建 UTF-8 日志。若自动自检中的主 I²C/OLED 仍显示“等待”，按一次板上 RST，
让上位机重新抓取完整启动日志即可。状态说明：

- 绿色“正常”：日志或遥测已经确认该链路可用；
- 灰色“等待”：仍在启动、定位、联网或等待放置手指；
- 黄色“注意”：模块未接、数据无效或功能未启用，但核心串口仍可调试；
- 红色“异常”：核心链路超时、任务创建失败或 MQTT 配置/连接错误。

日志区右上角可打开日志目录、另存本次日志或清空当前屏幕显示；清空显示不会删除
磁盘中的原始日志。

串口或图传被其他监视器占用时，应先关闭原程序再连接。若 Windows 把本地地址交给代理软件，上位机的数据通道会主动绕过系统代理。

## 3. 控制入口

- 通信测试、立即遥测；
- SOS、解除告警和照明控制按钮仍保留，但当前主固件对应逻辑是 TODO 空实现；
- 保存当前 JPEG；
- 导入/清除地图轨迹、清除实时 GPS 轨迹、跟随 GPS。

## 4. 跌倒检测高频数据采集

左侧向下滚动到“跌倒检测 · 高频 IMU 数据采集”：

1. 填写唯一试验编号并选择场景；场景已经绑定 `normal/fall` 真实标签。
2. 点击“开始记录”，上位机发送 `SC1 CMD IMU STREAM ON`。
3. 保持直立基线约 5 秒后点击“动作开始”，下一条样本写入 `ACTION_START`。
4. 完成动作并保留约 5 秒尾段，点击“停止并保存”。

单次原始记录保存在 `upper_computer/imu_captures/imu_*.csv`，总试验索引保存在
`imu_captures/trials.csv`。界面自动显示真实采样率、源序号丢帧、最大采样间隔、
召回率和误报率。正常动作只要出现 `SUSPECTED_FALL` 即按 FP 统计；模拟跌倒
出现 `SUSPECTED_FALL` 或 `FALL` 即按 TP 统计。

曲线中的 A、G、Tilt 来自设备同一条新 IMU 样本，红色虚线对应当前固件阈值。
现有 5 Hz `SC1 TEL` 继续用于普通状态卡片，不用于冲击峰值标定。

## 5. 文件结构

```text
upper_computer/
├─ main.py                         程序入口和演示参数
├─ requirements.txt               Python 依赖
├─ run.ps1                         Windows 启动脚本
├─ smartcane_host/
│  ├─ protocol.py                 SC1 串口协议解析与命令白名单
│  ├─ serial_worker.py            串口后台线程
│  ├─ imu_capture.py              CSV、试验索引、召回率和误报率统计
│  ├─ imu_plot.py                 A/G/Tilt 实时曲线与阈值线
│  ├─ camera_worker.py            MJPEG 接收与抓拍降级
│  ├─ track_import.py             GeoJSON/GPX/KML 解析
│  ├─ map_widget.py               在线瓦片、缓存、离线矢量地图
│  └─ main_window.py              三栏监控界面
├─ samples/demo_track.geojson      导入测试文件
└─ tests/                           协议与轨迹解析测试
```

## 6. 交付边界

上位机只展示固件发来的原始/当前快照，不在电脑端实现跌倒判断、传感器融合或业务状态机。界面的告警字段直接显示固件结果。FreeRTOS任务划分、跌倒检测算法、传感器进一步处理和最终主状态机不在本次验收范围。
