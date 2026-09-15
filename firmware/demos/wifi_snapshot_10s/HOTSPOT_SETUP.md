# 手机热点联网说明

本 Demo 支持两种工作方式：

1. 手机热点 / 路由器模式（推荐）：ESP32 和电脑都连接同一个 2.4GHz 网络。电脑保持互联网，Qt 使用 ESP32 串口打印出的局域网 IP 收图。
2. 独立热点模式：ESP32 建立 `ESP32-CAM-10S`，电脑直连 `192.168.4.1`。此模式没有互联网出口，Windows 显示“无 Internet”是正常的。

## 配置手机热点

本机私有热点配置位于 `firmware/include/DemoSecrets.h`，该文件已被 `firmware/.gitignore` 排除，不能提交到代码仓库。

```cpp
namespace DemoSecrets {
constexpr char WIFI_SSID[] = "你的热点名称";
constexpr char WIFI_PASSWORD[] = "你的热点密码";
}
```

手机热点必须启用 **2.4GHz**。ESP32-S3 不能使用纯 5GHz 热点。

## 烧录和运行

烧录后，以 115200 波特率打开串口。连接成功时会出现：

```text
[WiFi] router connected: 192.168.x.x
[HTTP] open http://192.168.x.x/
```

将这个 IP 填给 Qt 上位机：

```powershell
python pc/qt_receiver.py --url http://192.168.x.x --interval 10
```

若 12 秒内连接失败，固件会自动回退到独立热点模式，串口会打印回退提示和 `192.168.4.1`。
