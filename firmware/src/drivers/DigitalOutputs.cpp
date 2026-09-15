/**
 * @file DigitalOutputs.cpp
 * @brief 蜂鸣器与照明 GPIO 的安全初始化和逻辑电平写入。
 */
#include "DigitalOutputs.h"

void DigitalOutputs::begin() {
  pinMode(buzzerPin_, OUTPUT);
  pinMode(lightPin_, OUTPUT);
  // 上电默认关闭两个负载，避免 GPIO 浮空造成误响或闪灯。
  setBuzzer(false);
  setLight(false);
}

void DigitalOutputs::write(int pin, bool on) {
  digitalWrite(pin, on == activeHigh_ ? HIGH : LOW);
}

void DigitalOutputs::setBuzzer(bool on) {
  buzzerOn_ = on;
  write(buzzerPin_, on);
}

void DigitalOutputs::setLight(bool on) {
  lightOn_ = on;
  write(lightPin_, on);
}
