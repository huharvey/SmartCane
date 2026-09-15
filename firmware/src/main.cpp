/**
 * @file main.cpp
 * @brief PlatformIO 构建入口。
 *
 * 本文件只负责把 Arduino 的 setup/loop 转交给 SmartCaneApp，禁止在这里
 * 添加传感器解析或算法逻辑，避免与 Arduino IDE 入口 SmartCane.ino 分叉。
 */
#ifdef SMARTCANE_PLATFORMIO
#include "app/SmartCaneApp.h"

SmartCaneApp app;

void setup() {
  app.begin();
}

void loop() {
  app.update();
}
#endif
