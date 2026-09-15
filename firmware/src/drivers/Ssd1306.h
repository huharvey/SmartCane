#pragma once

/**
 * @file Ssd1306.h
 * @brief SSD1306 128x64 OLED 的轻量帧缓冲驱动。
 *
 * 自带精简英数字体，不依赖第三方库；不支持中文字符。drawText 只修改
 * 内存缓冲，调用 display() 后才真正刷新屏幕。
 */

#include <Arduino.h>
#include <Wire.h>

class Ssd1306 {
public:
  Ssd1306(TwoWire &wire, uint8_t address)
      : wire_(wire), address_(address) {}

  bool begin();
  // 以下绘图接口不会立即访问 I2C，可组合完成一帧后统一 display()。
  void clear();
  void drawText(int16_t x, int16_t y, const char *text, uint8_t scale = 1);
  void display();
  bool online() const { return online_; }

private:
  bool command(uint8_t value);
  void drawChar(int16_t x, int16_t y, char c, uint8_t scale);
  void pixel(int16_t x, int16_t y, bool on);

  TwoWire &wire_;
  uint8_t address_;
  bool online_ = false;
  uint8_t buffer_[128 * 64 / 8]{}; // 128*64/8，全屏 1 bit 帧缓冲
};
