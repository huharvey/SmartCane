# ESP32-S3 Arduino 开发与调试指南（零基础）

## 1. 这份指南解决什么问题

本文以本工程的 ESP32-S3-CAM 为对象，带你完成从“能看懂工程”到“能编译、烧录、看日志、定位故障和安全修改功能”的完整流程。

不要求读者提前掌握单片机、Arduino、C++ 或 PlatformIO。建议第一次严格按顺序操作，不要一开始就同时连接所有传感器。

工程内部设计和逐文件职责见 [01-工程架构与文件说明.md](./01-工程架构与文件说明.md)。

## 2. 先理解 10 个基本概念

| 概念 | 通俗解释 |
|---|---|
| ESP32-S3 | 一颗带 Wi-Fi、蓝牙、USB、多个串口和丰富 GPIO 的微控制器。 |
| 开发板 | 把 ESP32-S3、Flash、PSRAM、USB、电源和排针做在一起的板卡。 |
| Arduino 框架 | 用 `setup()`、`loop()` 和常用库简化嵌入式开发的软件框架。 |
| PlatformIO | 负责下载编译器和框架、管理开发板、编译、上传和串口监视。 |
| 固件 | 编译后写入 ESP32-S3 Flash 的程序，本工程产物为 `firmware.bin`。 |
| GPIO | 可作为输入或输出的引脚；ESP32-S3 只能承受 3.3 V 逻辑。 |
| I2C | 两根信号线连接多个低速设备的总线，设备靠地址区分。 |
| UART | TX/RX 两根数据线组成的串口，常用于 GPS、IMU 和调试。 |
| 串口监视器 | 在电脑上查看 ESP32 输出日志的窗口，是零基础调试最重要的工具。 |
| BOOT/RST | BOOT 用于进入下载模式，RST/EN 用于复位芯片。 |

## 3. 本机已配置的开发环境

当前工程采用以下组合：

- VS Code；
- PlatformIO IDE 扩展；
- PlatformIO Core；
- Espressif32 开发平台；
- Arduino for ESP32 框架；
- Xtensa ESP32-S3 编译器；
- `esptool` 烧录工具。

PlatformIO IDE 自带 PlatformIO Core，不需要另外安装 Arduino IDE 才能编译本工程。官方操作说明可参考：

- [PlatformIO IDE for VS Code](https://docs.platformio.org/en/latest/integration/ide/vscode.html)
- [Arduino ESP32 官方文档](https://docs.espressif.com/projects/arduino-esp32/en/latest/)
- [ESP32-S3 USB CDC 烧录说明](https://docs.espressif.com/projects/arduino-esp32/en/latest/tutorials/cdc_dfu_flash.html)

## 4. 硬件准备与安全底线

### 4.1 最小开发组合

第一次上电只准备：

- ESP32-S3-CAM 主板；
- 一根确认可以传数据的 USB 线；
- 稳定的 USB 口或 5 V 电源；
- 电脑上的 VS Code。

先不要连接摄像头和所有传感器。确认主板能识别、能烧录、能输出串口后，再逐项增加外设。

### 4.2 必须遵守

- ESP32-S3 GPIO 不耐 5 V，外设 TX、SDA、SCL 若输出 5 V，必须加电平转换；
- I2C 上拉电阻接 3.3 V，不能上拉到 5 V；
- 蜂鸣器负载通过 MOS 管驱动，不能直接由 GPIO 带大电流；
- 所有模块必须共地；
- 接线和拔插模块前先断电；
- 摄像头和 Wi-Fi 同时工作时电流峰值较大，反复复位首先排查供电和 USB 线；
- 跌倒检测、分级告警和双核 FreeRTOS 当前只保留 TODO 空接口。

## 5. 在 VS Code 中正确打开工程

不要只打开单个 `.ino` 文件，也不要只打开最外层资料目录。应在 VS Code 中选择：

```text
文件 → 打开文件夹 → D:\桌面\拐杖example\代码\SmartCane
```

正确打开后，资源管理器顶层应直接看到：

```text
platformio.ini
SmartCane.ino
src/
```

底部状态栏会出现 PlatformIO 按钮，左侧活动栏会出现蚂蚁图标。首次打开时 PlatformIO 可能需要数十秒建立代码索引。

### 5.1 常用按钮

| 图标/命令 | 作用 | 快捷键 |
|---|---|---|
| `✓` Build | 只编译，不写入开发板 | `Ctrl+Alt+B` |
| `→` Upload | 编译并烧录 | `Ctrl+Alt+U` |
| 插头 Monitor | 打开串口监视器 | `Ctrl+Alt+S` |
| 垃圾桶 Clean | 清理构建缓存 | 无固定键 |
| PlatformIO Home | 管理开发板、库和项目 | 状态栏 Home |

## 6. 认识本工程的入口

Arduino 程序通常由两个函数组成：

```cpp
void setup() {
  // 上电或复位后只执行一次
}

void loop() {
  // setup 完成后不断重复执行
}
```

本工程把真正逻辑放在 `SmartCaneApp` 中：

```cpp
void setup() { app.begin(); }
void loop()  { app.update(); }
```

- `begin()` 初始化串口、I2C、传感器、OLED、Wi-Fi 和摄像头；
- `update()` 快速轮询所有模块，不用长时间等待某一个传感器。

PlatformIO 使用 `src/main.cpp`，Arduino IDE 使用 `SmartCane.ino`。不要删除其中一个，也不要把两者同时加入同一次构建。

## 7. 第一次编译

### 7.1 图形界面方法

1. 确认 VS Code 打开的是 `SmartCane` 文件夹；
2. 查看状态栏环境是否为 `esp32-s3-cam`；
3. 点击 `✓` Build；
4. 第一次需要下载 ESP32-S3 工具链和 Arduino 框架，时间明显长于后续编译；
5. 终端最后出现 `[SUCCESS]` 表示编译通过。

### 7.2 命令行方法

在 PlatformIO 的 Core CLI 终端中执行：

```powershell
pio run -e esp32-s3-cam
```

普通 PowerShell 如果提示找不到 `pio`，应从 PlatformIO 左侧面板打开它自带的终端，或直接使用图形按钮。

### 7.3 如何看编译结果

成功末尾通常包含：

```text
RAM:   [==        ] ...
Flash: [====      ] ...
========================= [SUCCESS] =========================
```

- RAM 是运行时内存，不应长期逼近 100%；
- Flash 是程序存储占用；
- `firmware.bin` 是可烧录固件；
- `firmware.elf` 包含符号，供断点调试和崩溃定位使用。

本工程把产物放在：

```text
%TEMP%\smartcane-platformio-build\esp32-s3-cam\
```

这是为了避开中文路径导致的 ESP32 链接问题，不是文件丢失。

## 8. 连接开发板并识别串口

### 8.1 插入 USB 后检查

在 VS Code 中执行：

```text
PlatformIO → Devices
```

或在 PlatformIO Core CLI 中执行：

```powershell
pio device list
```

Windows 设备管理器的“端口（COM 和 LPT）”中也应出现新设备，常见名称包括：

- Espressif USB JTAG/Serial；
- USB Serial Device；
- CP210x；
- CH340/CH341；
- FTDI。

### 8.2 没有新串口

按顺序排查：

1. 换一根确定支持数据的 USB 线；
2. 换电脑 USB 口，不使用无供电扩展坞；
3. 确认插的是板上正确的 USB/下载接口；
4. 打开设备管理器查看是否有黄色叹号；
5. 若板上使用 CP210x/CH340，安装对应芯片驱动；
6. 按住 BOOT，短按 RST，再观察是否出现下载端口；
7. 断开外围模块，排除外设占用启动脚或造成电源压降。

ESP32-S3 支持原生 USB CDC，但前提是板卡确实把芯片 USB 引脚接到了该 USB 口。当前实测板通过 CH340 暴露 UART0（当前为 COM8），因此本工程定义 `ARDUINO_USB_CDC_ON_BOOT=0`；上位机和串口监视器均连接这个 CH340 端口。

## 9. 烧录固件

### 9.1 正常上传

1. 关闭正在占用端口的其他串口工具；
2. 点击 PlatformIO 的 Upload；
3. 等待终端显示擦除、写入和校验进度；
4. 看到 `[SUCCESS]` 后按一次 RST（若板卡没有自动复位）；
5. 打开 115200 波特率串口监视器。

命令行等价操作：

```powershell
pio run -e esp32-s3-cam -t upload
```

### 9.2 手动进入下载模式

遇到 `Timed out waiting for packet header` 或一直显示 `Connecting...` 时：

1. 按住 BOOT 不松；
2. 短按并松开 RST/EN；
3. 松开 BOOT；
4. 重新选择新出现的端口并点击 Upload；
5. 如果仍失败，可在出现 `Connecting...` 后再按上述顺序操作。

不同厂商板卡的自动下载电路不同，第一次使用原生 USB 时手动进入下载模式是正常现象。

### 9.3 多个串口时固定端口

通常让 PlatformIO 自动识别即可。如果电脑同时连接多个开发板，可在 `platformio.ini` 的环境中临时加入：

```ini
upload_port = COM7
monitor_port = COM7
```

把 `COM7` 替换为实际端口。换 USB 口后 COM 号可能变化，因此不建议把个人端口配置提交给其他人。

## 10. 串口监视与开机自检

### 10.1 打开方式

- 点击底部串口监视图标；
- 或执行：

```powershell
pio device monitor -b 115200
```

`platformio.ini` 已设置 `monitor_speed = 115200`，通常不需要手动指定。

### 10.2 预期日志

复位后重点查看：

```text
[SmartCane] boot
[I2C] devices: ...
[BH1750] online / not found
[Sonar] online / not found at 0x57
[OLED] online / not found
[SmartCane] ready
[State] ...
```

I2C 设备通常为：

| 地址 | 模块 |
|---|---|
| `0x23` 或 `0x5C` | BH1750 |
| `0x3C` | SSD1306 OLED |
| `0x57` | HC-SR04 IIC |

JY901S 和 GPS 使用 UART，不会出现在 I2C 扫描中。

### 10.3 日志乱码

检查两件事：

- 串口波特率必须为 115200；
- VS Code 终端使用 UTF-8。

开机 ROM 日志与应用串口配置可能短暂不同，但应用进入 `[SmartCane] boot` 后应清晰可读。

## 11. 推荐的分阶段硬件调试方法

不要一次接满所有模块后再找问题。每增加一个模块，都应重复“接线 → 上电 → 看日志 → 验证数据”。

### 阶段 1：只测主板

目标：能编译、上传和看到 `[SmartCane] boot`。

允许传感器显示 `not found`，此时只确认主控、USB、Flash 和串口正常。

### 阶段 2：测试 I2C 总线

按顺序连接 OLED、BH1750、超声波：

1. 全部共用 GPIO41 SDA、GPIO42 SCL；
2. 确认 3.3 V 上拉和共地；
3. 每接一个模块，看 I2C 地址是否新增；
4. 如果接入某个模块后全部地址消失，重点检查 SDA/SCL 接反、短路或 5 V 上拉。

### 阶段 3：测试 JY901S

接线方向：

```text
JY901S TX → ESP32 GPIO39（RX）
JY901S RX ← ESP32 GPIO38（TX）
GND       ↔ GND
```

默认 9600 bit/s。网页状态中的 `imu.valid` 应变为 `true`，转动模块时 roll/pitch 应变化。

若始终离线：

- 检查 TX/RX 是否交叉；
- 确认模块没有被上位机改成其他波特率；
- 检查输出是否确实是 `0x55` 开头的维特协议帧；
- 确认电平为 3.3 V。

### 阶段 4：测试 GPS

接线方向：

```text
ATGM336H TX → ESP32 GPIO47（RX）
ATGM336H RX ← ESP32 GPIO21（TX）
GND         ↔ GND
```

在室外开阔位置等待定位。能接收 NMEA 不等于已经定位：

- `online` 含义：最近收到合法 RMC/GGA 语句；
- `valid` 含义：RMC 状态有效或 GGA 定位质量大于 0；
- 室内长期显示未定位通常不是代码错误。

### 阶段 5：测试告警和照明

1. 遮挡并移开超声波，确认距离变化；
2. 检查蜂鸣器和照明 LED 的硬件接口是否通过 MOS 驱动；
3. 当前不执行分级告警、SOS 锁存或自动照明逻辑，相关验证待 TODO 完成后进行。

### 阶段 6：最后连接摄像头

摄像头最容易暴露供电、排线和 PSRAM 问题，因此最后测试：

1. 断电后插紧 OV2640 排线并确认方向；
2. 上电查看是否反复重启；
3. 打开网页 `/capture` 测单张图；
4. 再打开 `:81/stream` 测视频；
5. 图像颠倒时修改 `CAMERA_VFLIP` 或 `CAMERA_HMIRROR`。

## 12. Wi-Fi 和网页调试

### 12.1 热点模式（最容易验证）

保持 `UserConfig.h` 中 `WIFI_SSID` 为空：

1. 手机或电脑连接 `SmartCane-Camera`；
2. 密码为 `12345678`；
3. 浏览器打开 `http://192.168.4.1/`；
4. 页面应显示距离、照度、GPS、IMU 和视频。

### 12.2 路由器模式

在 `UserConfig.h` 填写：

```cpp
constexpr char WIFI_SSID[] = "你的Wi-Fi名称";
constexpr char WIFI_PASSWORD[] = "你的Wi-Fi密码";
```

重新编译和上传后，从 OLED 或串口 `[State]` 行查看 IP。电脑/手机必须与设备处于可互访的同一局域网。

不要把真实密码上传到公开代码仓库。修改前先备份，演示或提交时恢复为空。

### 12.3 单独测试 API

在 PowerShell 中把 IP 替换为设备地址：

```powershell
Invoke-RestMethod http://192.168.4.1/api/status
Invoke-WebRequest -Method Post http://192.168.4.1/api/sos
Invoke-WebRequest -Method Post http://192.168.4.1/api/cancel
Invoke-RestMethod 'http://192.168.4.1/api/light?mode=auto'
```

浏览器可直接测试：

```text
http://192.168.4.1/capture
http://192.168.4.1:81/stream
```

## 13. 零基础 C++/Arduino 阅读要点

### 13.1 `.h` 和 `.cpp`

- `.h` 通常声明“这个模块能做什么”；
- `.cpp` 实现“具体怎么做”；
- 例如 `Bh1750.h` 声明 `readLux()`，`Bh1750.cpp` 负责 I2C 命令和换算。

### 13.2 类和对象

```cpp
Bh1750 lightSensor_(Wire);
```

`Bh1750` 是类，相当于设计图；`lightSensor_` 是对象，相当于按设计图制造出的一个实例；`Wire` 告诉它使用哪条 I2C 总线。

### 13.3 `constexpr`

```cpp
// TODO：后续补充照明和告警参数。
```

表示编译期常量。修改后必须重新编译和上传，设备运行时不会自动变化。

### 13.4 `millis()` 与非阻塞

错误的长阻塞写法：

```cpp
delay(5000); // 这 5 秒里网页、GPS、按键都无法及时处理
```

本工程使用：

```cpp
if (nowMs - lastReadMs >= intervalMs) {
  // 到时间才执行一次
}
```

这种写法让多个任务在一个主循环中并行推进。

### 13.5 `valid` 和更新时间

传感器读数不是永远可信。工程为每类数据保存：

- 数值；
- `valid` 有效标志；
- `updatedAtMs` 最近更新时间。

新增控制逻辑时必须先判断数据有效和是否过期，不能只判断数值。

## 14. 如何安全修改工程

### 14.1 只调参数

修改 `src/config/UserConfig.h`，一次只改一类参数：

- 跌倒、分级告警和照明参数：当前尚未定义，待 TODO 完成后补充；
- 采样速度：`*_INTERVAL_MS`；
- Wi-Fi、热点和图像方向。

修改后执行：编译 → 上传 → 重复原测试 → 记录结果。

### 14.2 改接线

修改 `BoardConfig.h`。先对照原理图确认新 GPIO：

- 没被摄像头占用；
- 不是启动绑带脚，或已正确处理上拉/下拉；
- 支持目标外设；
- RX/TX 方向正确。

### 14.3 新增传感器

推荐流程：

1. 在 `src/drivers/` 新建 `NewSensor.h/.cpp`；
2. 先只实现 `begin()` 和读取函数；
3. 在 `SmartCaneApp.h` 增加对象；
4. 在 `begin()` 初始化；
5. 在 `updateSensors()` 非阻塞读取；
6. 在 `SystemState.h` 增加需要共享的数据；
7. 最后再接入 OLED、告警和网页。

不要先在 `SmartCaneApp.cpp` 里写大量设备协议代码，否则后续很难维护。

### 14.4 修改网页

网页 HTML/CSS/JavaScript 位于 `WifiCameraServer.cpp` 的 `INDEX_HTML` 原始字符串中。修改后需要重新编译和上传，网页不是独立存放在文件系统中的。

## 15. 调试方法：从简单到高级

### 15.1 第一级：编译器报错

双击 VS Code“问题”面板中的错误，先处理最上面的第一条。后续几十条常常是第一条引起的连锁错误。

常见类型：

| 错误关键词 | 含义 |
|---|---|
| `No such file or directory` | 头文件路径或库不存在 |
| `was not declared in this scope` | 名字拼错、缺少声明或作用域不对 |
| `multiple definition of setup/loop` | 两个入口被同时编译 |
| `undefined reference` | 声明了函数但没有实现，或实现未加入构建 |
| `expected ';'` | 前一行或当前行缺少分号/括号 |

### 15.2 第二级：串口日志

这是本工程首选调试方法。新增日志示例：

```cpp
Serial.printf("[Sonar] valid=%d distance=%.1f\n",
              sensors_.distanceValid, sensors_.distanceCm);
```

建议每条日志带模块前缀，如 `[GPS]`、`[IMU]`、`[Camera]`，避免输出无法归属。

不要在高速主循环每次都打印。使用时间间隔，否则串口输出本身会改变系统时序。

### 15.3 第三级：最小化故障

当系统异常时：

1. 断开所有可选外设；
2. 回到最近一次能工作的固件；
3. 每次只恢复一个模块；
4. 每一步记录电压、日志和现象；
5. 区分“编译问题、烧录问题、硬件问题、协议问题、业务逻辑问题”。

### 15.4 第四级：异常解码

若串口出现 Guru Meditation 和回溯地址，可临时在 `platformio.ini` 的环境中加入：

```ini
monitor_filters = esp32_exception_decoder
```

重新打开 PlatformIO 串口监视器后，回溯更容易映射到源文件和行号。排查完成后可保留该过滤器，也可删除。

### 15.5 第五级：断点/JTAG

VS Code 左侧“运行和调试”中已有 PlatformIO 自动生成的 `PIO Debug` 配置。真正断点调试需要：

- 板卡暴露 ESP32-S3 原生 USB-JTAG，或连接兼容 JTAG 调试器；
- 正确的 USB 模式、驱动和调试连接；
- Debug 构建和可用的 `firmware.elf`。

串口能输出不代表 JTAG 一定可用。零基础阶段先掌握日志和最小化测试，再使用断点调试。

## 16. 常见问题速查

| 现象 | 优先原因 | 处理方法 |
|---|---|---|
| VS Code 显示 `failed to fetch` | 代理端口、Clash 模式或当前节点错误 | 确认 Clash 规则模式、7897 端口和 VS Code `http.proxy`，再重启 VS Code |
| PlatformIO 下载开发板/库失败 | Core 没继承代理 | 检查 `HTTP_PROXY/HTTPS_PROXY`，确认 Clash 正常，再重试 |
| 编译找不到头文件 | 工程打开层级错误或索引未生成 | 直接打开 `SmartCane` 文件夹，执行 Build/Rebuild IntelliSense |
| 链接器在中文路径报错 | ESP32 工具链路径兼容性 | 保留当前 `build_dir=${sysenv.TEMP}/...` 配置 |
| 没有 COM 口 | USB 线只供电、驱动缺失、接口错误 | 换数据线/USB 口，查设备管理器，尝试 BOOT+RST |
| `Timed out waiting for packet header` | 没进入下载模式或端口被占用 | 关闭串口工具，手动 BOOT+RST，重新选端口 |
| 上传成功但无日志 | 端口/波特率错误或 USB CDC 模式不匹配 | 选新出现的端口，115200，按 RST；核对原生 USB 与 USB-UART 接口 |
| I2C 显示 `none` | SDA/SCL 接反、未共地、上拉/电压错误 | 断电逐线检查，先只接一个 I2C 模块 |
| 只有某个 I2C 地址缺失 | 设备地址、供电或模块协议不符 | 查模块标签/手册，BH1750 检查 `0x23/0x5C` |
| IMU 始终离线 | TX/RX、波特率或协议错误 | 交叉 RX/TX，核对 9600 和 `0x55` 帧 |
| GPS 有数据但未定位 | 室内无卫星或天线条件差 | 到室外开阔处等待，观察卫星数和定位质量 |
| 距离一直无效 | 超声波版本/协议不同 | 确认是 2021 IIC 版、地址 `0x57`、命令 `0x01` 和 24 位微米数据 |
| 相机初始化失败 | 排线、引脚、供电或 PSRAM 配置 | 断电重插排线，核对板型和 OPI PSRAM，使用稳定 5 V 电源 |
| 相机开启后反复重启 | Brownout 或 PSRAM/Flash 模式不匹配 | 换短 USB 线/强电源，断开大负载，核对 `qio_opi` 配置 |
| 网页能开但无视频 | 相机未就绪或 81 端口不可达 | 先测 `/capture`，再测 `IP:81/stream`，查看供电和相机状态 |
| 网页命令偶尔无响应 | 网络丢包或短时间命令过密 | 等待状态刷新，降低点击频率，检查信号强度 |
| 拐杖靠墙触发跌倒 | 持续倾斜分支的预期限制 | 调大确认时间/角度，或加入握持/压力条件后再启用该分支 |

## 17. 跌倒算法的正确调试方法

不要直接拿设备做危险跌倒实验。建议：

1. 先把 JY901S 固定到与最终产品一致的位置；
2. 记录正常行走、转弯、坐下、放下拐杖、靠墙和乘车数据；
3. 在软垫和有人保护的条件下做模拟跌落；
4. 分析加速度模长、roll、pitch 和时间顺序；
5. 调整阈值后，重新回放所有正常行为；
6. 统计漏报与误报，不要只验证一次成功案例；
7. 最终产品应增加握持、压力或其他上下文信息。

参数意义：

| 参数 | 含义 | 调大后的大致效果 |
|---|---|---|
| `FREE_FALL_G` | 自由落体判定上限 | 更容易进入自由落体状态 |
| `IMPACT_G` | 撞击判定下限 | 更不容易确认撞击 |
| `TILT_ANGLE_DEG` | 倾倒角度 | 更不容易判为倾倒 |
| `IMPACT_WINDOW_MS` | 自由落体后等待撞击窗口 | 接受更晚的撞击 |
| `POST_IMPACT_CONFIRM_MS` | 撞击后姿态确认等待 | 给设备更多稳定时间 |
| `TILT_CONFIRM_MS` | 缓慢倾倒持续时间 | 降低短时倾斜误报 |

## 18. 每次修改后的回归检查

完成任何代码修改后，至少确认：

- [ ] PlatformIO 编译为 `[SUCCESS]`；
- [ ] Flash/RAM 占用没有异常暴涨；
- [ ] 能正常烧录和重启；
- [ ] I2C 地址完整；
- [ ] IMU、GPS 在线状态符合实际；
- [ ] 超声波距离与实际变化一致；
- [ ] 三档障碍告警节奏正确；
- [ ] SOS 能触发，实体按键再次按下和网页均能取消；
- [ ] 自动、手动开灯和关闭都正常；
- [ ] 热点/路由器模式可以访问网页；
- [ ] `/api/status` JSON 合法；
- [ ] 单张抓拍和视频流正常；
- [ ] 连续运行一段时间没有重启、卡死或明显内存异常；
- [ ] 正常放置、靠墙和移动不会产生不可接受的跌倒误报。

## 19. 推荐学习顺序

### 第 1 阶段：能操作

- 会打开正确工程目录；
- 会 Build、Upload、Monitor；
- 会用 BOOT/RST；
- 会读 I2C 地址和 `online/not found`。

### 第 2 阶段：会调参数

- 理解 `UserConfig.h`；
- 修改距离、照度和采样周期；
- 每次修改后做回归测试。

### 第 3 阶段：能读代码

- 理解 `setup()/loop()`；
- 理解 `.h/.cpp`、类、对象和 `constexpr`；
- 理解 `millis()` 非阻塞调度；
- 能从 `SmartCaneApp` 跟踪一条传感器数据流。

### 第 4 阶段：能扩展

- 独立增加一个驱动；
- 把数据加入 `SensorSnapshot`；
- 在 OLED 或网页展示；
- 在控制层增加规则而不破坏驱动层。

### 第 5 阶段：能系统调试

- 会最小化故障；
- 会分析供电、总线、协议和软件状态；
- 会解码异常回溯；
- 有条件时使用 USB-JTAG/JTAG 断点调试。
