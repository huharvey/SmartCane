#pragma once

/**
 * @file DigitalOutputs.h
 * @brief 蜂鸣器与照明 LED 的统一数字输出接口。
 *
 * 该类只负责安全写 GPIO 并保存当前电平，不包含告警或照明决策。
 */

#include <Arduino.h>

class DigitalOutputs {
public:
  DigitalOutputs(int buzzerPin, int lightPin, bool activeHigh = true)
      : buzzerPin_(buzzerPin), lightPin_(lightPin), activeHigh_(activeHigh) {}
  void begin();
  // 参数表示逻辑开关状态，内部自动换算高/低有效电平。
  void setBuzzer(bool on);
  void setLight(bool on);
  bool buzzerOn() const { return buzzerOn_; }
  bool lightOn() const { return lightOn_; }

private:
  void write(int pin, bool on);
  int buzzerPin_;
  int lightPin_;
  bool activeHigh_;
  bool buzzerOn_ = false;
  bool lightOn_ = false;
};
