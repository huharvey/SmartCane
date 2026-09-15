/**
 * @file SerialTelemetry.cpp
 * @brief SC1 命令白名单、定时 JSON 遥测和 ACK/ERR 应答实现。
 */
#include "SerialTelemetry.h"
#include <ctype.h>
#include <string.h>

namespace {
// 所有上位机控制命令必须使用此前缀，避免误把普通日志当作命令。
constexpr char COMMAND_PREFIX[] = "SC1 CMD ";

bool equalsIgnoreCase(const char *left, const char *right) {
  if (!left || !right) return false;
  while (*left && *right) {
    if (toupper(static_cast<unsigned char>(*left)) !=
        toupper(static_cast<unsigned char>(*right))) return false;
    ++left;
    ++right;
  }
  return *left == '\0' && *right == '\0';
}
} // namespace

void SerialTelemetry::begin(Stream &stream, JsonProvider jsonProvider,
                            CommandHandler commandHandler,
                            uint32_t intervalMs) {
  stream_ = &stream;
  jsonProvider_ = jsonProvider;
  commandHandler_ = commandHandler;
  intervalMs_ = intervalMs < 50 ? 50 : intervalMs; // 防止高频串口输出占满主循环
  lineLength_ = 0;
  lastTelemetryMs_ = millis();
  stream_->println(
      F("SC1 HELLO {\"protocol\":\"smartcane.serial\",\"version\":1,\"baud\":115200}"));
}

void SerialTelemetry::update(uint32_t nowMs) {
  if (!stream_) return;
  while (stream_->available()) {
    consume(static_cast<char>(stream_->read()), nowMs);
  }
  if (nowMs - lastTelemetryMs_ >= intervalMs_) sendTelemetry(nowMs);
}

void SerialTelemetry::consume(char value, uint32_t nowMs) {
  // CR 忽略、LF 结束一帧；缓冲区溢出时清空并返回明确错误。
  if (value == '\n') {
    line_[lineLength_] = '\0';
    handleLine(nowMs);
    lineLength_ = 0;
    return;
  }
  if (value == '\r') return;
  if (lineLength_ < sizeof(line_) - 1) {
    line_[lineLength_++] = value;
  } else {
    lineLength_ = 0;
    sendError("line_too_long");
  }
}

void SerialTelemetry::handleLine(uint32_t nowMs) {
  // 仅接受固定白名单，不解析或执行任意外部字符串。
  if (strncmp(line_, COMMAND_PREFIX, sizeof(COMMAND_PREFIX) - 1) != 0) return;
  const char *command = line_ + sizeof(COMMAND_PREFIX) - 1;

  const auto queueCommand = [this](const char *name, int value) {
    return !commandHandler_ || commandHandler_(name, value);
  };
  if (equalsIgnoreCase(command, "PING")) {
    sendAck("PING");
  } else if (equalsIgnoreCase(command, "GET")) {
    sendTelemetry(nowMs);
    sendAck("GET");
  } else if (equalsIgnoreCase(command, "SOS")) {
    if (queueCommand("sos", 1)) sendAck("SOS");
    else sendError("command_queue_full");
  } else if (equalsIgnoreCase(command, "CANCEL")) {
    if (queueCommand("cancel", 1)) sendAck("CANCEL");
    else sendError("command_queue_full");
  } else if (equalsIgnoreCase(command, "LIGHT AUTO")) {
    if (queueCommand("light", -1)) sendAck("LIGHT AUTO");
    else sendError("command_queue_full");
  } else if (equalsIgnoreCase(command, "LIGHT ON")) {
    if (queueCommand("light", 1)) sendAck("LIGHT ON");
    else sendError("command_queue_full");
  } else if (equalsIgnoreCase(command, "LIGHT OFF")) {
    if (queueCommand("light", 0)) sendAck("LIGHT OFF");
    else sendError("command_queue_full");
  } else if (equalsIgnoreCase(command, "IMU STREAM ON")) {
    if (queueCommand("imu_stream", 1)) sendAck("IMU STREAM ON");
    else sendError("command_queue_full");
  } else if (equalsIgnoreCase(command, "IMU STREAM OFF")) {
    if (queueCommand("imu_stream", 0)) sendAck("IMU STREAM OFF");
    else sendError("command_queue_full");
  } else if (equalsIgnoreCase(command, "PPG STREAM ON")) {
    if (queueCommand("ppg_stream", 1)) sendAck("PPG STREAM ON");
    else sendError("command_queue_full");
  } else if (equalsIgnoreCase(command, "PPG STREAM OFF")) {
    if (queueCommand("ppg_stream", 0)) sendAck("PPG STREAM OFF");
    else sendError("command_queue_full");
  } else {
    sendError("unknown_command");
  }
}

void SerialTelemetry::sendImuHeader() {
  if (!stream_) return;
  stream_->println(F(
      "SC1 IMU HEADER seq,t_ms,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,"
      "roll_deg,pitch_deg,yaw_deg,a_g,g_dps,tilt_deg,fall_phase,"
      "free_fall,impact,tilted_still,alarm,fall_suspected,fall_latched"));
}

void SerialTelemetry::sendImuCsv(const char *csv) {
  if (!stream_ || !csv) return;
  stream_->print(F("SC1 IMU "));
  stream_->println(csv);
}

void SerialTelemetry::sendPpgHeader() {
  if (!stream_) return;
  stream_->println(F(
      "SC1 PPG HEADER seq,t_ms,red,ir,red_dc,ir_dc,red_ac,ir_ac,filtered_ir,"
      "envelope,peak_candidate,beat_accepted,ibi_ms,finger,sqi,hr_bpm,"
      "spo2_pct,valid,fifo_overflow"));
}

void SerialTelemetry::sendPpgCsv(const char *csv) {
  if (!stream_ || !csv) return;
  stream_->print(F("SC1 PPG "));
  stream_->println(csv);
}

void SerialTelemetry::sendTelemetry(uint32_t nowMs) {
  // SC1 TEL 后紧跟单行 JSON，便于 pyserial.readline() 按帧读取。
  if (!stream_ || !jsonProvider_) return;
  const String payload = jsonProvider_();
  stream_->print(F("SC1 TEL "));
  stream_->println(payload);
  lastTelemetryMs_ = nowMs;
}

void SerialTelemetry::sendAck(const char *command) {
  if (!stream_) return;
  stream_->print(F("SC1 ACK "));
  stream_->println(command);
}

void SerialTelemetry::sendError(const char *reason) {
  if (!stream_) return;
  stream_->print(F("SC1 ERR "));
  stream_->println(reason);
}
