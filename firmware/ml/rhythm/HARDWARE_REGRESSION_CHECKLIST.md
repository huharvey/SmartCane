# 候选节律模型：最后的实机短程回归

## 已完成的部分

- 候选模型已写入 `src/control/RhythmModel.generated.h` 并接入 `RhythmClassifier.cpp`。
- `RHYTHM_MODEL_CALIBRATED` 仍为 `false`，这是当前正确状态。
- PlatformIO `esp32-s3-cam` 编译已通过。
- 本次完整固件 RAM：`55308 / 327680 bytes（16.9%）`。
- 本次完整固件 Flash：`1012797 / 1966080 bytes（51.5%）`。
- 候选模型常量：`18 bytes`（不含分类器运行状态）。

## 拿到实机后按顺序操作

1. 在设备管理器或 PlatformIO Devices 中确认开发板当前 COM 口。
2. 将 `platformio.ini` 的 `upload_port` 和 `monitor_port` 改为该端口；不要照抄旧电脑的 COM8。
3. 关闭占用串口的串口监视器、Qt 上位机或其他程序。
4. 在 VS Code 的 PlatformIO 页面点击 Upload，或运行 `pio run -e esp32-s3-cam -t upload`。
5. 烧录结束后再打开串口监视器，确认启动日志无崩溃，MAX30102 在线。
6. 启动现有 Qt 上位机。若 PowerShell 禁止脚本，可在 `upper_computer` 中运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\run.ps1 -Install
   powershell -ExecutionPolicy Bypass -File .\run.ps1
   ```

7. 在“MAX30102 · PPG/血氧数据采集”中采 `P044`、`P045`、`P046` 三组 `rhythm_normal`：每组 45～60 秒，手指稳定覆盖，拐杖和手臂尽量静止；三组之间重新放置一次手指。
8. 正常现象：开始约 15 秒为 `COLLECTING`，之后允许短暂 `INCONCLUSIVE`，每组最后一次有效推理应为 `NORMAL`；全程不能出现 `SUSPECTED_AF`。
9. 用下列命令自动统计模型字节数、最终状态以及推理耗时平均值/P95/最大值：

   ```powershell
   Set-Location "<local-path>\SmartCane_实机调试\SmartCane\ml\rhythm"
   .\.venv\Scripts\python.exe .\check_hardware_regression.py `
     --captures "<local-path>\SmartCane_实机调试\SmartCane\upper_computer\ppg_captures" `
     --trials P044 P045 P046 `
     --output ".\artifacts\latest\HARDWARE_RESULT.md"
   ```

10. 打开 `artifacts/latest/HARDWARE_RESULT.md`。只有总体结论为“通过”，人工检查 CSV 也无异常后，才将 `src/config/UserConfig.h` 中的 `RHYTHM_MODEL_CALIBRATED` 改成 `true`，然后重新编译烧录。

## 状态含义

- 模型直接输出两类：`NORMAL` 或 AF-like。
- 第 1、2 个连续 AF-like 窗口只显示 `IRREGULAR`。
- 第 3 个连续 AF-like 窗口才显示 `SUSPECTED_AF` 并形成远程事件。
- 它不会自动触发 SOS、跌倒告警、蜂鸣器或摄像头。
- “通过”只说明课程原型的软件与短程实机回归完成，不等于医学诊断或医疗器械认证。
