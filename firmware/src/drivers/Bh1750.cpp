/**
 * @file Bh1750.cpp
 * @brief BH1750 地址探测、连续高分辨率模式和照度换算实现。
 */
#include "Bh1750.h"

namespace {
// BH1750 数据手册命令：上电后进入连续高分辨率模式。
constexpr uint8_t POWER_ON = 0x01;
constexpr uint8_t CONTINUOUS_HIGH_RES_MODE = 0x10;
}

bool Bh1750::ping(uint8_t address) {
  wire_.beginTransmission(address);
  return wire_.endTransmission() == 0;
}

bool Bh1750::sendCommand(uint8_t command) {
  wire_.beginTransmission(address_);
  wire_.write(command);
  return wire_.endTransmission() == 0;
}

bool Bh1750::begin() {
  if (ping(0x23)) {
    address_ = 0x23;
  } else if (ping(0x5C)) {
    address_ = 0x5C;
  } else {
    online_ = false;
    return false;
  }

  online_ = sendCommand(POWER_ON) && sendCommand(CONTINUOUS_HIGH_RES_MODE);
  if (online_) readyAtMs_ = millis() + 180;
  return online_;
}

bool Bh1750::readLux(float &lux) {
  if (!online_ && !begin()) return false;
  // 实测 Demo 中首次高分辨率转换需要 120～180 ms，未到时直接返回。
  if (static_cast<int32_t>(millis() - readyAtMs_) < 0) return false;

  const size_t received = wire_.requestFrom(address_, static_cast<uint8_t>(2));
  if (received != 2) {
    online_ = false;
    return false;
  }

  const uint16_t raw = (static_cast<uint16_t>(wire_.read()) << 8) |
                       static_cast<uint16_t>(wire_.read());
  // 默认 MTreg=69 时，高分辨率模式换算系数为 1.2。
  lux = raw / 1.2f;
  online_ = true;
  return true;
}
