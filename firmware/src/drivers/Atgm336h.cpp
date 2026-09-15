/**
 * @file Atgm336h.cpp
 * @brief ATGM336H NMEA 字节流、校验和、RMC/GGA 解析实现。
 */
#include "Atgm336h.h"
#include <stdlib.h>
#include <string.h>

void Atgm336h::begin(HardwareSerial &serial, uint32_t baud, int rxPin, int txPin) {
  serial_ = &serial;
  serial_->begin(baud, SERIAL_8N1, rxPin, txPin);
}

void Atgm336h::update(uint32_t nowMs) {
  // 逐字节拼成一行；溢出时丢弃当前行，避免越界或解析半截语句。
  if (!serial_) return;
  while (serial_->available()) {
    const char c = static_cast<char>(serial_->read());
    if (c == '\n') {
      line_[length_] = '\0';
      if (length_ > 6) parseLine(line_, nowMs);
      length_ = 0;
    } else if (c != '\r') {
      if (length_ < sizeof(line_) - 1) line_[length_++] = c;
      else length_ = 0;
    }
  }
}

bool Atgm336h::validChecksum(const char *line) {
  // NMEA 校验为 '$' 与 '*' 之间全部字符逐字节异或。
  if (!line || line[0] != '$') return false;
  const char *star = strchr(line, '*');
  if (!star || strlen(star) < 3) return false;

  uint8_t checksum = 0;
  for (const char *p = line + 1; p < star; ++p) checksum ^= *p;
  return checksum == static_cast<uint8_t>(strtoul(star + 1, nullptr, 16));
}

void Atgm336h::parseLine(char *line, uint32_t nowMs) {
  if (!validChecksum(line)) return;
  char *star = strchr(line, '*');
  if (star) *star = '\0';

  // 原地把逗号替换为 '\0'，得到字段指针数组，不产生动态内存分配。
  char *fields[20]{};
  size_t count = 0;
  char *cursor = line;
  while (cursor && count < 20) {
    fields[count++] = cursor;
    char *comma = strchr(cursor, ',');
    if (!comma) break;
    *comma = '\0';
    cursor = comma + 1;
  }
  if (count == 0) return;

  const size_t typeLen = strlen(fields[0]);
  if (typeLen >= 3 && strcmp(fields[0] + typeLen - 3, "RMC") == 0) {
    parseRmc(fields, count, nowMs);
  } else if (typeLen >= 3 && strcmp(fields[0] + typeLen - 3, "GGA") == 0) {
    parseGga(fields, count, nowMs);
  }
  lastSentenceMs_ = nowMs;
}

double Atgm336h::parseCoordinate(const char *value, const char *hemisphere) {
  // NMEA 坐标格式为 ddmm.mmmm/dddmm.mmmm，需要换算为十进制度。
  if (!value || !*value || !hemisphere || !*hemisphere) return NAN;
  const double raw = atof(value);
  const int degrees = static_cast<int>(raw / 100.0);
  double coordinate = degrees + (raw - degrees * 100.0) / 60.0;
  if (*hemisphere == 'S' || *hemisphere == 'W') coordinate = -coordinate;
  return coordinate;
}

void Atgm336h::formatUtc(const char *nmeaTime, char out[11]) {
  if (!nmeaTime || strlen(nmeaTime) < 6) {
    strcpy(out, "--:--:--");
    return;
  }
  snprintf(out, 11, "%.2s:%.2s:%.2s", nmeaTime, nmeaTime + 2, nmeaTime + 4);
}

void Atgm336h::parseRmc(char **f, size_t count, uint32_t nowMs) {
  // RMC 提供定位有效性、经纬度和节速；节乘 1.852 得到 km/h。
  if (count < 8) return;
  formatUtc(f[1], reading_.utc);
  reading_.valid = f[2] && f[2][0] == 'A';
  if (reading_.valid) {
    reading_.latitude = parseCoordinate(f[3], f[4]);
    reading_.longitude = parseCoordinate(f[5], f[6]);
    reading_.speedKmh = f[7] && *f[7] ? atof(f[7]) * 1.852f : 0.0f;
    reading_.updatedAtMs = nowMs;
  }
  fresh_ = true;
}

void Atgm336h::parseGga(char **f, size_t count, uint32_t nowMs) {
  // GGA 补充定位质量、卫星数和海拔；quality=0 表示本句无有效定位。
  if (count < 10) return;
  formatUtc(f[1], reading_.utc);
  const int quality = f[6] && *f[6] ? atoi(f[6]) : 0;
  reading_.satellites = f[7] && *f[7] ? static_cast<uint8_t>(atoi(f[7])) : 0;
  reading_.altitudeM = f[9] && *f[9] ? atof(f[9]) : NAN;
  if (quality > 0) {
    reading_.latitude = parseCoordinate(f[2], f[3]);
    reading_.longitude = parseCoordinate(f[4], f[5]);
    reading_.valid = true;
    reading_.updatedAtMs = nowMs;
  }
  fresh_ = true;
}

bool Atgm336h::takeReading(GpsReading &reading) {
  if (!fresh_) return false;
  reading = reading_;
  fresh_ = false;
  return true;
}

bool Atgm336h::online(uint32_t nowMs, uint32_t staleMs) const {
  return lastSentenceMs_ != 0 && nowMs - lastSentenceMs_ <= staleMs;
}
