#pragma once

/**
 * @file Hcsr04I2c.h
 * @brief HC-SR04 2021 UART/IIC 版的非阻塞 I2C 测距驱动。
 *
 * 写 0x01 触发后等待 130 ms，再读取 24 位微米值并换算为 cm。
 */

#include <Arduino.h>
#include <Wire.h>

class Hcsr04I2c {
public:
  Hcsr04I2c(TwoWire &wire, uint8_t address)
      : wire_(wire), address_(address) {}

  bool begin();
  void update(uint32_t nowMs);
  bool startMeasurement(uint32_t nowMs); // 仅发触发命令，不在此等待回波
  // 取走一次新测量；无新数据时返回 false。
  bool takeReading(float &distanceCm, uint32_t &updatedAtMs);
  bool online() const { return online_; }

private:
  enum class State : uint8_t { Idle, Waiting };
  bool readResult(uint32_t nowMs);

  TwoWire &wire_;
  uint8_t address_;
  State state_ = State::Idle;
  uint32_t triggeredAtMs_ = 0;
  float lastDistanceCm_ = NAN;
  uint32_t lastUpdateMs_ = 0;
  bool fresh_ = false;
  bool online_ = false;
  // 单模块 Demo 以 130 ms 读取，为额定约 120 ms 的转换时间留出余量。
  static constexpr uint32_t CONVERSION_MS = 130;
};
