#pragma once

/**
 * @file Bh1750.h
 * @brief BH1750/GY-302 环境照度传感器驱动。
 *
 * 自动探测 0x23/0x5C 地址，使用连续高分辨率模式；输出单位为 lx。
 */

#include <Arduino.h>
#include <Wire.h>

class Bh1750 {
public:
  explicit Bh1750(TwoWire &wire) : wire_(wire) {}
  // 探测地址并启动连续转换，成功后首帧仍需等待约 180 ms。
  bool begin();
  // 读取最近转换值；尚未就绪或通信失败时返回 false。
  bool readLux(float &lux);
  bool online() const { return online_; }
  uint8_t address() const { return address_; }

private:
  bool ping(uint8_t address);
  bool sendCommand(uint8_t command);

  TwoWire &wire_;
  uint8_t address_ = 0x23;
  bool online_ = false;
  uint32_t readyAtMs_ = 0; // 首次高分辨率转换可读取的最早时刻
};
