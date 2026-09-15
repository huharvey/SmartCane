/**
 * @file DebouncedButton.cpp
 * @brief 按键原始电平、稳定状态和一次性事件的消抖实现。
 */
#include "DebouncedButton.h"

void DebouncedButton::begin() {
  pinMode(pin_, activeHigh_ ? INPUT_PULLDOWN : INPUT_PULLUP);
  rawState_ = rawPressed();
  stablePressed_ = rawState_;
  rawChangedAtMs_ = millis();
  if (stablePressed_) pressedAtMs_ = rawChangedAtMs_;
}

bool DebouncedButton::rawPressed() const {
  return digitalRead(pin_) == (activeHigh_ ? HIGH : LOW);
}

void DebouncedButton::update(uint32_t nowMs) {
  // 原始电平改变后需持续稳定 DEBOUNCE_MS 才更新对外状态。
  const bool raw = rawPressed();
  if (raw != rawState_) {
    rawState_ = raw;
    rawChangedAtMs_ = nowMs;
  }
  if (rawState_ == stablePressed_ || nowMs - rawChangedAtMs_ < DEBOUNCE_MS) return;

  stablePressed_ = rawState_;
  if (stablePressed_) {
    pressedAtMs_ = nowMs;
    pressedEvent_ = true;
  } else {
    releasedEvent_ = true;
  }
}

bool DebouncedButton::takePressed() {
  const bool event = pressedEvent_;
  pressedEvent_ = false;
  return event;
}

bool DebouncedButton::takeReleased() {
  const bool event = releasedEvent_;
  releasedEvent_ = false;
  return event;
}

uint32_t DebouncedButton::heldMs(uint32_t nowMs) const {
  return stablePressed_ ? nowMs - pressedAtMs_ : 0;
}
