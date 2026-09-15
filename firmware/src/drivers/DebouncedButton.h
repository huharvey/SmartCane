#pragma once

/**
 * @file DebouncedButton.h
 * @brief 非阻塞式机械按键消抖与按下/释放事件封装。
 *
 * takePressed/takeReleased 为“取走事件”语义，读取一次后自动清除。
 */

#include <Arduino.h>

class DebouncedButton {
public:
  DebouncedButton(int pin, bool activeHigh) : pin_(pin), activeHigh_(activeHigh) {}
  void begin();
  // 每轮主循环调用，内部以 millis() 判断稳定时间。
  void update(uint32_t nowMs);
  bool takePressed();
  bool takeReleased();
  bool pressed() const { return stablePressed_; }
  uint32_t heldMs(uint32_t nowMs) const;

private:
  bool rawPressed() const;
  int pin_;
  bool activeHigh_;
  bool rawState_ = false;
  bool stablePressed_ = false;
  bool pressedEvent_ = false;
  bool releasedEvent_ = false;
  uint32_t rawChangedAtMs_ = 0;
  uint32_t pressedAtMs_ = 0;
  static constexpr uint32_t DEBOUNCE_MS = 30; // 电平持续稳定后才确认状态变化
};
