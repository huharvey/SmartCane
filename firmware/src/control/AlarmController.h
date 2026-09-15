#pragma once

#include <Arduino.h>
#include "../model/SystemState.h"

class AlarmController {
public:
  void triggerSos();
  void triggerSuspectedFall(uint32_t nowMs);
  void triggerFall();
  void cancelLatchedAlarms();
  void setManualLight(int8_t mode); // -1 auto, 0 off, 1 on
  // Runs only in DecisionTask.  It does not access GPIO; ActuatorTask applies
  // the returned intent, which keeps hardware ownership single-tasked.
  ActuatorIntent update(const SensorSnapshot &sensors, uint32_t nowMs);

  AlarmKind activeAlarm() const { return activeAlarm_; }
  bool sosLatched() const { return sosLatched_; }
  bool suspectedFall() const { return suspectedFall_; }
  bool fallLatched() const { return fallLatched_; }
  int8_t manualLightMode() const { return manualLightMode_; }

private:
  AlarmKind obstacleAlarm(const SensorSnapshot &sensors);
  static bool pulse(uint32_t nowMs, uint32_t periodMs, uint32_t onMs);

  AlarmKind activeAlarm_ = AlarmKind::None;
  AlarmKind obstacleAlarm_ = AlarmKind::None;
  bool sosLatched_ = false;
  bool suspectedFall_ = false;
  bool fallLatched_ = false;
  uint32_t suspectedFallAtMs_ = 0;
  int8_t manualLightMode_ = -1;
};
