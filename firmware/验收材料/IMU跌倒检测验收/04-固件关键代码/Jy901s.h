#pragma once

/**
 * @file Jy901s.h
 * @brief JY901S IMU 的 0x55 二进制帧解析接口。
 *
 * 0x51/0x52/0x53 分别提供加速度、角速度和欧拉角。驱动收到姿态帧后
 * 发布当前组合数据，单位统一写入 ImuReading。
 */

#include <Arduino.h>
#include "../model/SystemState.h"

class Jy901s {
public:
  // rxPin 接 JY901S TX；默认实测波特率为 9600。
  void begin(HardwareSerial &serial, uint32_t baud, int rxPin, int txPin);
  // 尽快消费串口缓冲区中的现有字节，不主动等待完整帧。
  void update(uint32_t nowMs);
  // 取走一组新数据；一次新数据只会被返回一次。
  bool takeReading(ImuReading &reading);
  // 判断近期是否收到校验正确的 JY901S 帧。
  bool online(uint32_t nowMs, uint32_t staleMs) const;

private:
  void consume(uint8_t value, uint32_t nowMs);
  void decodeFrame(uint32_t nowMs);
  static int16_t signed16(const uint8_t *p);

  HardwareSerial *serial_ = nullptr;
  uint8_t frame_[11]{}; // JY901S 固定 11 字节帧
  uint8_t index_ = 0;
  ImuReading reading_;
  uint32_t lastFrameMs_ = 0;
  bool fresh_ = false;
};
