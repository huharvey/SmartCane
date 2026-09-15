# ESP32-S3-CAM 每 10 秒 Wi-Fi 图传 Demo

## 1. 功能

本 Demo 是“定时快照图传”，不是连续视频流：

1. ESP32-S3-CAM 每 10 秒采集一张 JPEG 并缓存在 PSRAM；
2. Qt 上位机每 10 秒通过 HTTP 获取最新缓存帧；
3. 上位机显示帧号、大小、网络耗时、设备采集时刻和下次请求倒计时；
4. JPEG 可自动保存到电脑；
5. 固件内置浏览器页面，不打开 Qt 也能看图；
6. 附带本地模拟相机，无开发板时也能测试 Qt 上位机。

采用“ESP 定时采集 + PC 定时拉取”而不是 UDP 裸数据，是因为 JPEG/HTTP 更容易调试，丢包后下一周期可自动恢复，并且浏览器、Qt、Python 都能直接访问。

## 2. 目录

```text
wifi_snapshot_10s/
├─ firmware/
│  ├─ platformio.ini
│  ├─ include/
│  │  ├─ CameraPins.h
│  │  └─ DemoConfig.h
│  └─ src/main.cpp
├─ pc/
│  ├─ qt_receiver.py
│  ├─ mock_camera_server.py
│  ├─ requirements.txt
│  └─ run_mock_demo.ps1
└─ artifacts/
```

## 3. 默认联网方式

`DemoConfig.h` 默认不连接路由器，而是由开发板建立热点：

| 项目 | 默认值 |
|---|---|
| 热点名 | `ESP32-CAM-10S` |
| 密码 | `12345678` |
| 设备地址 | `http://192.168.4.1` |
| 采集周期 | 10000 ms |

电脑连接该热点后，可访问：

| 地址 | 功能 |
|---|---|
| `http://192.168.4.1/` | 内置浏览器上位机 |
| `http://192.168.4.1/capture` | 最新 JPEG |
| `http://192.168.4.1/api/status` | 帧号、大小、采集时刻和间隔 JSON |

如果希望开发板连接现有路由器，在 `firmware/include/DemoConfig.h` 填写 `WIFI_SSID` 和 `WIFI_PASSWORD`。真实密码不要提交到公开仓库。

## 4. 编译与烧录

用 VS Code 单独打开 `firmware` 文件夹，选择环境 `esp32-s3-cam-demo`：

```powershell
pio run -e esp32-s3-cam-demo
pio run -e esp32-s3-cam-demo -t upload
pio device monitor -b 115200
```

当前 Demo 针对带 CH340 的板卡，让 `Serial` 走 UART0。若上传一直停在 `Connecting...`：

1. 按住 BOOT；
2. 短按并松开 RST；
3. 松开 BOOT；
4. 重新上传。

正常日志示例：

```text
[Demo] ESP32-S3-CAM 10-second snapshot server
[Camera] ready, psram=yes
[WiFi] AP ESP32-CAM-10S, password 12345678, IP 192.168.4.1
[Frame] id=1 size=... capturedAt=...ms
[HTTP] open http://192.168.4.1/
```

之后每 10 秒帧号增加一次。

## 5. 运行 Qt 上位机

本机已有 PyQt5 时：

```powershell
cd pc
python qt_receiver.py --url http://192.168.4.1 --interval 10
```

缺少依赖时：

```powershell
python -m pip install -r requirements.txt
```

点击“开始接收”后会立即取第一张图，之后每 10 秒更新。勾选“自动保存 JPEG”时，图像写入 `pc/captures/`。

## 6. 无硬件模拟运行

`run_mock_demo.ps1` 会启动本地模拟相机、运行 Qt 12 秒、接收至少两轮定时帧，并保存窗口截图：

```powershell
powershell -ExecutionPolicy Bypass -File .\pc\run_mock_demo.ps1
```

也可分两个终端运行：

```powershell
python pc/mock_camera_server.py --port 8765 --interval 10
python pc/qt_receiver.py --url http://127.0.0.1:8765 --interval 10
```

## 7. 修改采集周期

ESP32 固件的真实采集周期在 `DemoConfig.h`：

```cpp
constexpr uint32_t CAPTURE_INTERVAL_MS = 10000;
```

Qt 请求周期由 `--interval` 设置。两者建议保持一致。若 Qt 更快，它会重复收到同一个 `X-Frame-Id`；若 Qt 更慢，它只会收到当前最新帧。

## 8. 常见问题

| 现象 | 处理 |
|---|---|
| Qt 显示连接失败 | 确认电脑连接 `ESP32-CAM-10S`，地址为 `192.168.4.1` |
| 能开网页但没有图 | 先访问 `/api/status`，再检查相机排线、引脚和供电 |
| 帧号不增加 | 查看串口是否每 10 秒出现 `[Frame]` |
| 图像颠倒 | 修改 `CAMERA_VFLIP` 或 `CAMERA_HMIRROR` |
| 相机初始化失败 | 断电重插排线，确认 OPI PSRAM 和稳定 5 V 供电 |
| 开相机后复位 | 换短数据线或更强电源，断开其他大电流负载 |
| Qt 无法启动 | 执行 `python -c "import PyQt5"` 并按 requirements 安装依赖 |

