#pragma once

#include <Arduino.h>
#include <math.h>

/**
 * @file SystemState.h
 * @brief 驱动层、控制层、通信层之间共享的原始数据契约。
 *
 * 后续算法优先读取 SensorSnapshot：数值单位已统一，valid 表示当前可用，
 * updatedAtMs 用于判断数据新鲜度。无效浮点字段保持 NAN，禁止当作 0 使用。
 */
struct ImuReading {
  float axG = NAN;      // X 轴加速度，单位 g
  float ayG = NAN;
  float azG = NAN;
  float gyroX = NAN;    // X 轴角速度，单位 °/s
  float gyroY = NAN;
  float gyroZ = NAN;
  float rollDeg = NAN;  // 欧拉角，单位 °
  float pitchDeg = NAN;
  float yawDeg = NAN;
  uint32_t updatedAtMs = 0; // 最近一组完整数据的 millis() 时间戳
  bool valid = false;       // true 仅表示驱动已得到当前有效帧

  float accelerationMagnitudeG() const {
    return sqrtf(axG * axG + ayG * ayG + azG * azG);
  }
};

struct GpsReading {
  double latitude = NAN;  // WGS-84 纬度，北纬为正
  double longitude = NAN;
  float speedKmh = NAN;   // 地速，km/h
  float altitudeM = NAN;  // 海拔，m
  uint8_t satellites = 0;
  char utc[11] = "--:--:--";
  uint32_t updatedAtMs = 0;
  bool valid = false;
};

// The PPG rhythm result is deliberately a screening result, never a medical
// diagnosis.  The three terminal classes are generated only after a stable
// signal window and a consecutive-window confirmation policy.
enum class RhythmScreenState : uint8_t {
  Disabled,
  NoSensor,
  NoFinger,
  Collecting,
  MotionArtifact,
  Inconclusive,
  Normal,
  Irregular,
  SuspectedAf
};

inline const char *rhythmScreenName(RhythmScreenState state) {
  switch (state) {
  case RhythmScreenState::Disabled: return "DISABLED";
  case RhythmScreenState::NoSensor: return "NO_SENSOR";
  case RhythmScreenState::NoFinger: return "NO_FINGER";
  case RhythmScreenState::Collecting: return "COLLECTING";
  case RhythmScreenState::MotionArtifact: return "MOTION_ARTIFACT";
  case RhythmScreenState::Inconclusive: return "INCONCLUSIVE";
  case RhythmScreenState::Normal: return "NORMAL";
  case RhythmScreenState::Irregular: return "IRREGULAR";
  case RhythmScreenState::SuspectedAf: return "SUSPECTED_AF";
  default: return "INCONCLUSIVE";
  }
}

// The bounded feature vector shared by VitalsProcessor and RhythmClassifier.
// It carries no raw PPG samples, which keeps both the classifier and public
// telemetry small and avoids exporting an unnecessary biometric waveform.
struct RhythmFeatures {
  float heartRateBpm = NAN;
  float ibiMeanMs = NAN;
  float ibiStdMs = NAN;       // SDNN for the rolling IBI window
  float ibiCv = NAN;
  float rmssdMs = NAN;
  float pnn50 = NAN;          // 0.0 ~ 1.0
  float maxAdjacentDiffMs = NAN;
  float signalQuality = 0.0f;
  uint32_t windowDurationMs = 0;
  uint8_t beatCount = 0;
  bool sensorOnline = false;
  bool fingerPresent = false;
  bool ppgValid = false;
  bool ready = false;
};

struct RhythmScreeningReading {
  RhythmScreenState state = RhythmScreenState::Disabled;
  float confidence = 0.0f;       // probability-like model confidence, 0~1
  float ibiMeanMs = NAN;
  float sdnnMs = NAN;
  float rmssdMs = NAN;
  float pnn50 = NAN;
  uint32_t updatedAtMs = 0;
  uint32_t inferenceUs = 0;
  uint32_t inferenceCount = 0;
  uint16_t modelBytes = 0;
  uint16_t classifierStateBytes = 0;
  uint8_t beatCount = 0;
  bool modelAvailable = false;
  // false for the bundled integration baseline.  It becomes true only after
  // its weights have been replaced with an ECG-referenced, validated model.
  bool modelCalibrated = false;
  bool valid = false;
  bool alertActive = false;
};

// MAX30102 PPG-derived, non-medical vital-sign snapshot. `valid` requires a
// stable finger signal, a usable waveform and plausible calculated values.
struct VitalsReading {
  float heartRateBpm = NAN;
  float spo2Pct = NAN;
  float signalQuality = 0.0f; // 0.0 ~ 1.0
  uint32_t rawRed = 0;
  uint32_t rawIr = 0;
  uint32_t updatedAtMs = 0;
  bool sensorOnline = false;
  bool fingerPresent = false;
  bool valid = false;
  RhythmScreeningReading rhythm;
};

struct SensorSnapshot {
  float distanceCm = NAN; // 前向距离，cm
  uint32_t distanceUpdatedAtMs = 0;
  bool sonarOnline = false;
  bool distanceValid = false;

  float lux = NAN;        // 环境照度，lx
  uint32_t luxUpdatedAtMs = 0;
  bool lightSensorOnline = false;
  bool luxValid = false;

  ImuReading imu;
  GpsReading gps;          // 当前 GNSS 状态；失星后 valid 会变为 false。
  GpsReading lastValidGps; // 本次上电以来最后一次有效定位，供断星回退显示。
  bool lastValidGpsAvailable = false;
  VitalsReading vitals;
};

enum class AlarmKind : uint8_t {
  None,
  ObstacleCaution,
  ObstacleWarning,
  ObstacleDanger,
  SuspectedFall,
  Fall,
  Sos
};

// A decision-task output.  It is intentionally a value object so it can cross
// a FreeRTOS queue without sharing mutable controller state with the task that
// owns the GPIOs.
struct ActuatorIntent {
  SensorSnapshot sensors;
  AlarmKind alarm = AlarmKind::None;
  bool buzzerOn = false;
  bool lightOn = false;
  bool sosLatched = false;
  bool suspectedFall = false;
  bool fallLatched = false;
  int8_t manualLightMode = -1; // -1 auto, 0 off, 1 on
  bool incidentActive = false;
};

inline const char *alarmName(AlarmKind alarm) {
  switch (alarm) {
  case AlarmKind::ObstacleCaution: return "CAUTION";
  case AlarmKind::ObstacleWarning: return "WARNING";
  case AlarmKind::ObstacleDanger: return "DANGER";
  case AlarmKind::SuspectedFall: return "SUSPECTED_FALL";
  case AlarmKind::Fall: return "FALL";
  case AlarmKind::Sos: return "SOS";
  default: return "NORMAL";
  }
}
