# 固件构建说明与安全边界

构建环境：PlatformIO `esp32-s3-cam`  
目标板：`esp32-s3-devkitc-1`，8 MB Flash，OPI PSRAM  
已验证的当前整合固件构建时间：2026-08-31 18:09—18:10

| 文件 | 用途 |
|---|---|
| `platformio.ini` | 板型、Flash、PSRAM、串口及构建目录配置 |

交付包没有附带 `firmware.bin`、`bootloader.bin` 和 `partitions.bin`。原因是当前主工程把 MQTT 设备账号和密码作为编译常量写入 `UserConfig.h`，生成的主固件会携带这些凭据；公开归档该二进制并不安全。

需要烧录时，应在受控电脑上使用完整主工程重新构建，再通过 PlatformIO 的 Upload 执行烧录。当前整合固件包含 MQTT 功能以及当天稍后完成的 IMU 阈值调整，它也不是 11:24 MQTT 首次联调版本的逐字节历史快照。

后续建议把设备凭据迁移到不提交版本库的私有配置、NVS 配置区或部署时注入机制，并为每台设备分配独立账号和 Topic ACL。
