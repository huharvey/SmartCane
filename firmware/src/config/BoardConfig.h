#pragma once

#include <Arduino.h>

/**
 * @file BoardConfig.h
 * @brief 板级固定接线与总线参数。
 *
 * 本文件只随 PCB/开发板接线变化而修改。后续算法同学不应在此调整阈值；
 * 传感器采样周期和业务参数统一放在 UserConfig.h。
 */
namespace Board {

// 经原理图和单模块 Demo 核对的外围接口；I2C 三个设备共用同一总线。
constexpr int PIN_I2C_SDA = 41;   // U3-15
constexpr int PIN_I2C_SCL = 42;   // U3-16
constexpr int PIN_SOS_KEY = 40;   // U3-14，按下为高电平
constexpr int PIN_BUZZER = 1;     // U3-18，MOS 管栅极，高电平响
constexpr int PIN_LIGHT_LED = 14; // U2-19，高电平亮

constexpr int PIN_IMU_RX = 39; // ESP RX <- JY901S TX，U3-13
constexpr int PIN_IMU_TX = 38; // ESP TX -> JY901S RX，U3-12
constexpr int PIN_GPS_RX = 47; // ESP RX <- ATGM336H TX，U3-5
constexpr int PIN_GPS_TX = 21; // ESP TX -> ATGM336H RX，U3-4

// Optional secondary MAX30102 wiring. The current bench profile uses GPIO41/42
// instead because the ultrasonic module is absent and the camera needs the
// second hardware I2C controller for SCCB. A complete build with both 0x57
// sensors requires an I2C multiplexer or a software-I2C bus.
constexpr int PIN_MAX30102_SDA = 2;
constexpr int PIN_MAX30102_SCL = 48;

constexpr uint32_t DEBUG_BAUD = 115200;
constexpr uint32_t IMU_BAUD = 9600;
constexpr uint32_t GPS_BAUD = 9600;
constexpr uint32_t I2C_CLOCK_HZ = 100000;
constexpr uint32_t MAX30102_I2C_CLOCK_HZ = 100000;

// GOOUUU ESP32-S3-CAM + OV2640 固定并行相机总线，不得复用这些 GPIO。
constexpr int CAM_PIN_PWDN = -1;
constexpr int CAM_PIN_RESET = -1;
constexpr int CAM_PIN_XCLK = 15;
constexpr int CAM_PIN_SIOD = 4;
constexpr int CAM_PIN_SIOC = 5;
constexpr int CAM_PIN_D7 = 16; // Y9
constexpr int CAM_PIN_D6 = 17; // Y8
constexpr int CAM_PIN_D5 = 18; // Y7
constexpr int CAM_PIN_D4 = 12; // Y6
constexpr int CAM_PIN_D3 = 10; // Y5
constexpr int CAM_PIN_D2 = 8;  // Y4
constexpr int CAM_PIN_D1 = 9;  // Y3
constexpr int CAM_PIN_D0 = 11; // Y2
constexpr int CAM_PIN_VSYNC = 6;
constexpr int CAM_PIN_HREF = 7;
constexpr int CAM_PIN_PCLK = 13;

static_assert(PIN_I2C_SDA != CAM_PIN_SIOD,
              "外围 I2C 不得复用相机 SCCB 引脚");

} // namespace Board
