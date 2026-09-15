/**
 * @file Jy901s.cpp
 * @brief JY901S 固定 11 字节帧同步、校验和物理量换算实现。
 */
#include "Jy901s.h"

void Jy901s::begin(HardwareSerial &serial, uint32_t baud, int rxPin, int txPin) {
  serial_ = &serial;
  serial_->begin(baud, SERIAL_8N1, rxPin, txPin);
  index_ = 0;
}

void Jy901s::update(uint32_t nowMs) {
  if (!serial_) return;
  while (serial_->available()) consume(static_cast<uint8_t>(serial_->read()), nowMs);
}

void Jy901s::consume(uint8_t value, uint32_t nowMs) {
  // 只在 0x55 帧头开始收集；第 11 字节为前 10 字节累加和低 8 位。
  if (index_ == 0 && value != 0x55) return;
  frame_[index_++] = value;
  if (index_ < sizeof(frame_)) return;

  uint8_t checksum = 0;
  for (uint8_t i = 0; i < 10; ++i) checksum += frame_[i];
  if (checksum == frame_[10]) decodeFrame(nowMs);
  index_ = 0;
}

int16_t Jy901s::signed16(const uint8_t *p) {
  return static_cast<int16_t>(static_cast<uint16_t>(p[0]) |
                              (static_cast<uint16_t>(p[1]) << 8));
}

void Jy901s::decodeFrame(uint32_t nowMs) {
  // 换算比例来自 JY901S 协议：±16 g、±2000 °/s、±180°。
  switch (frame_[1]) {
  case 0x51:
    reading_.axG = signed16(&frame_[2]) / 32768.0f * 16.0f;
    reading_.ayG = signed16(&frame_[4]) / 32768.0f * 16.0f;
    reading_.azG = signed16(&frame_[6]) / 32768.0f * 16.0f;
    break;
  case 0x52:
    reading_.gyroX = signed16(&frame_[2]) / 32768.0f * 2000.0f;
    reading_.gyroY = signed16(&frame_[4]) / 32768.0f * 2000.0f;
    reading_.gyroZ = signed16(&frame_[6]) / 32768.0f * 2000.0f;
    break;
  case 0x53:
    reading_.rollDeg = signed16(&frame_[2]) / 32768.0f * 180.0f;
    reading_.pitchDeg = signed16(&frame_[4]) / 32768.0f * 180.0f;
    reading_.yawDeg = signed16(&frame_[6]) / 32768.0f * 180.0f;
    reading_.updatedAtMs = nowMs;
    // 以姿态帧作为一组 IMU 数据的发布边界；至少需先收到加速度帧。
    reading_.valid = !isnan(reading_.axG);
    fresh_ = reading_.valid;
    break;
  default:
    break;
  }
  lastFrameMs_ = nowMs;
}

bool Jy901s::takeReading(ImuReading &reading) {
  if (!fresh_) return false;
  reading = reading_;
  fresh_ = false;
  return true;
}

bool Jy901s::online(uint32_t nowMs, uint32_t staleMs) const {
  return lastFrameMs_ != 0 && nowMs - lastFrameMs_ <= staleMs;
}
