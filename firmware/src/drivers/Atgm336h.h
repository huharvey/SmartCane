#pragma once

/**
 * @file Atgm336h.h
 * @brief ATGM336H GNSS 的 NMEA 串口接收与定位数据接口。
 *
 * 驱动校验并解析 RMC/GGA，输出 WGS-84 坐标。室内无定位时串口仍可能
 * online，但 GpsReading::valid 为 false；算法必须以 valid 为准。
 */

#include <Arduino.h>
#include "../model/SystemState.h"

class Atgm336h {
public:
  // 启动指定硬件串口；rxPin 接模块 TX，txPin 接模块 RX。
  void begin(HardwareSerial &serial, uint32_t baud, int rxPin, int txPin);
  // 消费当前已到达的 NMEA 字节，不阻塞等待新数据。
  void update(uint32_t nowMs);
  // 取走一份新解析结果；返回 false 表示本轮没有新语句。
  bool takeReading(GpsReading &reading);
  // 仅判断近期是否收到校验正确的 NMEA 语句，不等同于已经定位。
  bool online(uint32_t nowMs, uint32_t staleMs) const;

private:
  void parseLine(char *line, uint32_t nowMs);
  void parseRmc(char **fields, size_t count, uint32_t nowMs);
  void parseGga(char **fields, size_t count, uint32_t nowMs);
  static bool validChecksum(const char *line);
  static double parseCoordinate(const char *value, const char *hemisphere);
  static void formatUtc(const char *nmeaTime, char out[11]);

  HardwareSerial *serial_ = nullptr;
  char line_[128]{}; // 单条 NMEA 语句缓存（不含 CR/LF）
  size_t length_ = 0;
  GpsReading reading_;
  uint32_t lastSentenceMs_ = 0;
  bool fresh_ = false;
};
