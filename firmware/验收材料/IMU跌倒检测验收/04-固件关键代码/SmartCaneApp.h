#pragma once

/**
 * @file SmartCaneApp.h
 * @brief 各硬件驱动与通信服务的集成调度器。
 *
 * 这里负责“采集并搬运数据”，不是最终算法主程序。算法模块可消费 sensors_
 * 或公开的 SensorSnapshot 接口，但不应绕过驱动直接访问 UART/I2C。
 */

#include <Arduino.h>
#include <Wire.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include "../config/BoardConfig.h"
#include "../config/UserConfig.h"
#include "../control/AlarmController.h"
#include "../control/FallDetector.h"
#include "../control/RhythmClassifier.h"
#include "../control/VitalsProcessor.h"
#include "../drivers/Atgm336h.h"
#include "../drivers/Bh1750.h"
#include "../drivers/DebouncedButton.h"
#include "../drivers/DigitalOutputs.h"
#include "../drivers/Hcsr04I2c.h"
#include "../drivers/Jy901s.h"
#include "../drivers/Max30102.h"
#include "../drivers/Ssd1306.h"
#include "../model/SystemState.h"
#include "../services/WifiCameraServer.h"
#include "../services/MqttRemoteService.h"
#include "../services/SerialTelemetry.h"

class SmartCaneApp {
public:
  SmartCaneApp();
  // 初始化 GPIO、I2C、UART、显示、串口协议、Wi-Fi 与摄像头服务。
  void begin();
  // 非阻塞轮询入口；Arduino loop() 必须持续调用。
  void update();

private:
  enum class CommandKind : uint8_t { Sos, Cancel, Light, ImuStream };
  struct ControlCommand {
    CommandKind kind;
    int8_t value;
  };
  struct PublishedState {
    SensorSnapshot sensors;
    AlarmKind alarm = AlarmKind::None;
    bool buzzerOn = false;
    bool lightOn = false;
    bool sosLatched = false;
    bool suspectedFall = false;
    bool fallLatched = false;
    int8_t manualLightMode = -1;
    bool cameraReady = false;
    bool apMode = false;
    int8_t rssi = 0;
    char ip[16] = "0.0.0.0";
    bool mqttEnabled = false;
    bool mqttConnected = false;
    char mqttState[20] = "DISABLED";
    uint32_t mqttLastPublishAtMs = 0;
  };
  struct ImuDebugRecord {
    uint32_t sequence = 0;
    uint32_t sampleAtMs = 0;
    ImuReading imu;
    float accelerationG = NAN;
    float gyroDps = NAN;
    float tiltDeg = NAN;
    FallDetector::Phase phase = FallDetector::Phase::Idle;
    bool freeFall = false;
    bool impact = false;
    bool tiltedAndStill = false;
    AlarmKind alarm = AlarmKind::None;
    bool suspectedFall = false;
    bool fallLatched = false;
  };

  static void sensorTaskThunk(void *context);
  static void decisionTaskThunk(void *context);
  static void actuatorTaskThunk(void *context);
  static void networkTaskThunk(void *context);
  static void telemetryTaskThunk(void *context);
  void sensorTask();
  void decisionTask();
  void actuatorTask();
  void networkTask();
  void telemetryTask();

  void updateSensors(uint32_t nowMs);
  void processButton(uint32_t nowMs);
  void processCommands();
  void updateDisplay(const PublishedState &state, uint32_t nowMs);
  void publishDecision(const ActuatorIntent &intent);
  void publishNetworkState();
  void publishMqttState();
  void queueImuDebugRecord(const SensorSnapshot &current,
                           const ActuatorIntent &intent);
  void updateImuDebugStream();
  PublishedState readPublished() const;
  void logStatus(uint32_t nowMs);
  void scanI2c();
  uint32_t diagnoseGpsBaud();

  String buildJson() const;
  static String jsonThunk();
  static bool commandThunk(const char *command, int value);

  HardwareSerial imuSerial_{1};
  HardwareSerial gpsSerial_{2};
  TwoWire max30102Wire_{1};
  Hcsr04I2c sonar_;
  Bh1750 lightSensor_;
  Jy901s imu_;
  Atgm336h gps_;
  Max30102 max30102_;
  Ssd1306 oled_;
  DebouncedButton sosButton_;
  DigitalOutputs outputs_;
  FallDetector fallDetector_;
  VitalsProcessor vitalsProcessor_;
  RhythmClassifier rhythmClassifier_;
  AlarmController alarmController_;
  SerialTelemetry serialTelemetry_;
  WifiCameraServer network_;
  MqttRemoteService mqttRemote_;
  QueueHandle_t sensorQueue_ = nullptr;
  QueueHandle_t actuatorQueue_ = nullptr;
  QueueHandle_t commandQueue_ = nullptr;
  QueueHandle_t imuDebugQueue_ = nullptr;
  SemaphoreHandle_t i2cMutex_ = nullptr;
  SemaphoreHandle_t stateMutex_ = nullptr;
  TaskHandle_t sensorTaskHandle_ = nullptr;
  TaskHandle_t decisionTaskHandle_ = nullptr;
  TaskHandle_t actuatorTaskHandle_ = nullptr;
  TaskHandle_t networkTaskHandle_ = nullptr;
  TaskHandle_t telemetryTaskHandle_ = nullptr;

  SensorSnapshot sensors_; // 后续算法接入时最重要的统一数据入口
  PublishedState published_;

  uint32_t lastSonarStartMs_ = 0;
  uint32_t lastLightReadMs_ = 0;
  uint32_t lastMax30102ProbeMs_ = 0;
  uint32_t lastDisplayMs_ = 0;
  uint32_t lastLogMs_ = 0;
  uint32_t lastImuDebugSampleAtMs_ = 0;
  uint32_t imuDebugSequence_ = 0;
  volatile bool imuDebugStreamEnabled_ = false;
  bool imuDebugWriterActive_ = false;
  static SmartCaneApp *instance_;
};
