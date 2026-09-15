/**
 * @file Hcsr04I2c.cpp
 * @brief HC-SR04 I2C 触发/等待/读取状态机实现。
 */
#include "Hcsr04I2c.h"

bool Hcsr04I2c::begin() {
  wire_.beginTransmission(address_);
  online_ = wire_.endTransmission() == 0;
  state_ = State::Idle;
  return online_;
}

bool Hcsr04I2c::startMeasurement(uint32_t nowMs) {
  // Waiting 状态下拒绝重复触发，确保一次命令只对应一次读取。
  if (state_ != State::Idle) return false;

  wire_.beginTransmission(address_);
  wire_.write(static_cast<uint8_t>(0x01));
  if (wire_.endTransmission() != 0) {
    online_ = false;
    return false;
  }

  triggeredAtMs_ = nowMs;
  state_ = State::Waiting;
  online_ = true;
  return true;
}

void Hcsr04I2c::update(uint32_t nowMs) {
  // 到时后再读结果，等待期间主循环可继续处理其他传感器和网络。
  if (state_ == State::Waiting && nowMs - triggeredAtMs_ >= CONVERSION_MS) {
    readResult(nowMs);
    state_ = State::Idle;
  }
}

bool Hcsr04I2c::readResult(uint32_t nowMs) {
  const size_t count = wire_.requestFrom(address_, static_cast<uint8_t>(3));
  if (count != 3) {
    while (wire_.available()) wire_.read();
    online_ = false;
    return false;
  }

  const uint32_t rawUm = (static_cast<uint32_t>(wire_.read()) << 16) |
                         (static_cast<uint32_t>(wire_.read()) << 8) |
                         static_cast<uint32_t>(wire_.read());
  const float cm = rawUm / 10000.0f;

  // 过滤无回波、总线全 1 以及模块有效量程之外的数据。
  if (rawUm == 0 || rawUm == 0xFFFFFF || cm < 2.0f || cm > 500.0f) {
    return false;
  }

  lastDistanceCm_ = cm;
  lastUpdateMs_ = nowMs;
  fresh_ = true;
  online_ = true;
  return true;
}

bool Hcsr04I2c::takeReading(float &distanceCm, uint32_t &updatedAtMs) {
  if (!fresh_) return false;
  distanceCm = lastDistanceCm_;
  updatedAtMs = lastUpdateMs_;
  fresh_ = false;
  return true;
}
