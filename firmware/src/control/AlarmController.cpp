#include "AlarmController.h"
#include "../config/UserConfig.h"

void AlarmController::triggerSos() { sosLatched_ = true; }
void AlarmController::triggerSuspectedFall(uint32_t nowMs) {
  // A real SOS/FALL has priority and must not be replaced by another candidate.
  if (sosLatched_ || fallLatched_ || suspectedFall_) return;
  suspectedFall_ = true;
  suspectedFallAtMs_ = nowMs;
}

void AlarmController::triggerFall() {
  suspectedFall_ = false;
  suspectedFallAtMs_ = 0;
  fallLatched_ = true;
}

void AlarmController::cancelLatchedAlarms() {
  sosLatched_ = false;
  suspectedFall_ = false;
  fallLatched_ = false;
  suspectedFallAtMs_ = 0;
}

void AlarmController::setManualLight(int8_t mode) {
  manualLightMode_ = mode > 0 ? 1 : (mode == 0 ? 0 : -1);
}

AlarmKind AlarmController::obstacleAlarm(const SensorSnapshot &sensors) {
  if (!sensors.distanceValid) {
    obstacleAlarm_ = AlarmKind::None;
    return obstacleAlarm_;
  }

  const float d = sensors.distanceCm;
  // Escalation uses the documented thresholds.  Relaxation uses a small
  // hysteresis margin so a reading around 50 cm does not flicker WARNING.
  switch (obstacleAlarm_) {
  case AlarmKind::ObstacleDanger:
    if (d >= Config::OBSTACLE_DANGER_CM + Config::OBSTACLE_HYSTERESIS_CM)
      obstacleAlarm_ = d < Config::OBSTACLE_WARNING_CM ? AlarmKind::ObstacleWarning :
                       d < Config::OBSTACLE_CAUTION_CM ? AlarmKind::ObstacleCaution :
                                                        AlarmKind::None;
    break;
  case AlarmKind::ObstacleWarning:
    if (d < Config::OBSTACLE_DANGER_CM) obstacleAlarm_ = AlarmKind::ObstacleDanger;
    else if (d >= Config::OBSTACLE_WARNING_CM + Config::OBSTACLE_HYSTERESIS_CM)
      obstacleAlarm_ = d < Config::OBSTACLE_CAUTION_CM ? AlarmKind::ObstacleCaution
                                                        : AlarmKind::None;
    break;
  case AlarmKind::ObstacleCaution:
    if (d < Config::OBSTACLE_DANGER_CM) obstacleAlarm_ = AlarmKind::ObstacleDanger;
    else if (d < Config::OBSTACLE_WARNING_CM) obstacleAlarm_ = AlarmKind::ObstacleWarning;
    else if (d >= Config::OBSTACLE_CAUTION_CM + Config::OBSTACLE_HYSTERESIS_CM)
      obstacleAlarm_ = AlarmKind::None;
    break;
  default:
    if (d < Config::OBSTACLE_DANGER_CM) obstacleAlarm_ = AlarmKind::ObstacleDanger;
    else if (d < Config::OBSTACLE_WARNING_CM) obstacleAlarm_ = AlarmKind::ObstacleWarning;
    else if (d < Config::OBSTACLE_CAUTION_CM) obstacleAlarm_ = AlarmKind::ObstacleCaution;
    break;
  }
  return obstacleAlarm_;
}

bool AlarmController::pulse(uint32_t nowMs, uint32_t periodMs, uint32_t onMs) {
  return periodMs != 0 && nowMs % periodMs < onMs;
}

ActuatorIntent AlarmController::update(const SensorSnapshot &sensors, uint32_t nowMs) {
  if (suspectedFall_ && !sosLatched_ && !fallLatched_ &&
      nowMs - suspectedFallAtMs_ >= Config::SUSPECTED_FALL_CONFIRM_MS) {
    // The user did not cancel the warning during the confirmation window.
    triggerFall();
  }

  if (sosLatched_) activeAlarm_ = AlarmKind::Sos;
  else if (fallLatched_) activeAlarm_ = AlarmKind::Fall;
  else if (suspectedFall_) activeAlarm_ = AlarmKind::SuspectedFall;
  else activeAlarm_ = obstacleAlarm(sensors);

  bool buzzer = false;
  bool alertLight = false;
  switch (activeAlarm_) {
  case AlarmKind::Sos:
    buzzer = pulse(nowMs, 400, 180); alertLight = pulse(nowMs, 400, 200); break;
  case AlarmKind::Fall:
    buzzer = pulse(nowMs, 800, 350); alertLight = pulse(nowMs, 800, 400); break;
  case AlarmKind::SuspectedFall:
    buzzer = pulse(nowMs, 650, 90); alertLight = pulse(nowMs, 650, 120); break;
  case AlarmKind::ObstacleDanger:
    buzzer = pulse(nowMs, 350, 220); alertLight = pulse(nowMs, 350, 175); break;
  case AlarmKind::ObstacleWarning:
    buzzer = pulse(nowMs, 650, 130); break;
  case AlarmKind::ObstacleCaution:
    buzzer = pulse(nowMs, 1100, 80); break;
  default:
    break;
  }
  const bool autoLight = sensors.luxValid && sensors.lux < Config::DARK_LUX_THRESHOLD;
  // Manual OFF disables only the regular night light; it must not suppress a
  // visible fall/SOS/danger indication.
  const bool light = alertLight || manualLightMode_ > 0 ||
                     (manualLightMode_ < 0 && autoLight);
  ActuatorIntent intent;
  intent.sensors = sensors;
  intent.alarm = activeAlarm_;
  intent.buzzerOn = buzzer;
  intent.lightOn = light;
  intent.sosLatched = sosLatched_;
  intent.suspectedFall = suspectedFall_;
  intent.fallLatched = fallLatched_;
  intent.manualLightMode = manualLightMode_;
  // Do not change the existing camera incident behavior until a FALL is
  // confirmed; the short suspected-fall prompt is only a local warning.
  intent.incidentActive = sosLatched_ || fallLatched_;
  return intent;
}
