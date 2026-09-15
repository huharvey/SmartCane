#pragma once

/**
 * @file SerialTelemetry.h
 * @brief 上位机 SC1 行协议的串口收发服务。
 *
 * 人工启动日志可与协议共用 UART；只有以“SC1 ”开头的行属于机器协议，
 * 上位机因此可以安全忽略其他日志。协议字段见 docs/03-上位机与通信协议.md。
 */

#include <Arduino.h>

class SerialTelemetry {
public:
  using JsonProvider = String (*)();
  using CommandHandler = bool (*)(const char *command, int value);

  // intervalMs 为遥测发布周期；过小值会被限制为至少 50 ms。
  void begin(Stream &stream, JsonProvider jsonProvider,
             CommandHandler commandHandler, uint32_t intervalMs);
  void update(uint32_t nowMs);
  // High-rate IMU records are already formatted as compact CSV by the app.
  // Keeping the actual write here preserves a single owner of the debug UART.
  void sendImuHeader();
  void sendImuCsv(const char *csv);

private:
  void consume(char value, uint32_t nowMs);
  void handleLine(uint32_t nowMs);
  void sendTelemetry(uint32_t nowMs);
  void sendAck(const char *command);
  void sendError(const char *reason);

  Stream *stream_ = nullptr;
  JsonProvider jsonProvider_ = nullptr;
  CommandHandler commandHandler_ = nullptr;
  uint32_t intervalMs_ = 200;
  uint32_t lastTelemetryMs_ = 0;
  char line_[96]{}; // 上位机命令行缓存，超长命令直接丢弃
  size_t lineLength_ = 0;
};
