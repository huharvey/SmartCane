#pragma once

/**
 * @file CameraPins.h
 * @brief 图传 Demo 使用的 GOOUUU ESP32-S3-CAM + OV2640 固定引脚表。
 */
namespace CameraPins {

constexpr int PWDN = -1;
constexpr int RESET = -1;
constexpr int XCLK = 15;
constexpr int SIOD = 4;
constexpr int SIOC = 5;
constexpr int D7 = 16;
constexpr int D6 = 17;
constexpr int D5 = 18;
constexpr int D4 = 12;
constexpr int D3 = 10;
constexpr int D2 = 8;
constexpr int D1 = 9;
constexpr int D0 = 11;
constexpr int VSYNC = 6;
constexpr int HREF = 7;
constexpr int PCLK = 13;

} // namespace CameraPins
