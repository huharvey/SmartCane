#pragma once

/**
 * @file DemoConfig.h
 * @brief 十秒抓拍 Demo 的网络、热点、采样周期和图像方向配置。
 */

#include <Arduino.h>
#include "DemoSecrets.h"

namespace DemoConfig {

// 私有路由器凭据位于不提交的 DemoSecrets.h；两项留空则使用独立热点。
constexpr const char *WIFI_SSID = DemoSecrets::WIFI_SSID;
constexpr const char *WIFI_PASSWORD = DemoSecrets::WIFI_PASSWORD;

constexpr char AP_SSID[] = "ESP32-CAM-10S";
constexpr char AP_PASSWORD[] = "12345678";
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 12000;

// 固件按此周期刷新缓存 JPEG；PC 只读取最新缓存，慢客户端不会阻塞采集。
constexpr uint32_t CAPTURE_INTERVAL_MS = 10000;

constexpr bool CAMERA_VFLIP = false;
constexpr bool CAMERA_HMIRROR = false;

} // namespace DemoConfig
