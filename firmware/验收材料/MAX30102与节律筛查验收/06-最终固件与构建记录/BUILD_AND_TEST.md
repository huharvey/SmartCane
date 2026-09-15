# 最终固件构建与测试记录

## 构建环境

- PlatformIO 环境：`esp32-s3-cam`；
- Platform：Espressif32 7.0.1；
- Framework：Arduino ESP32 3.20017；
- Board：ESP32-S3-DevKitC-1-N8；
- 构建模式：release。

## 构建命令

```powershell
platformio run -e esp32-s3-cam
```

## 最终资源占用

```text
RAM  : 55308 / 327680 bytes（16.9%）
Flash: 1012877 / 1966080 bytes（51.5%）
```

构建成功并生成 `SmartCane-MAX30102-final.bin`。该二进制包含峰值突出度、自适应不应期、
IBI 中位数 HR、长间隔历史清空和心搏新鲜度保护。

## Qt回归测试

```powershell
python -m unittest discover -s tests -v
```

结果：21 项测试全部通过，覆盖串口选择、自检诊断、IMU/PPG CSV、协议解析、摄像头分块和
地图轨迹解析。

## 实机最终验证

固件烧录后采集 P041～P043。三组均保持 25 Hz、零丢帧、零 FIFO 溢出；243 个有效
IBI 中没有小于 500 ms 或大于 1200 ms 的间隔；29 次端侧推理全部输出 `NORMAL`。

## 安全说明

完整 `UserConfig.h` 可能包含网络和 MQTT 配置，因此没有进入验收包。包内
`03-固件关键代码/UserConfig_MAX30102节选.h` 仅保留与本模块有关的脱敏参数。

