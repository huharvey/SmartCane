/**
 * @file SmartCane.ino
 * @brief Arduino IDE 构建入口。
 *
 * 与 src/main.cpp 二选一生效；所有硬件初始化和数据调度均由 SmartCaneApp
 * 负责，入口文件不承载业务逻辑。
 */
#ifndef SMARTCANE_PLATFORMIO
#include "src/app/SmartCaneApp.h"

SmartCaneApp app;

void setup() {
  app.begin();
}

void loop() {
  // update() 为非阻塞轮询接口，应高频调用。
  app.update();
}
#endif
