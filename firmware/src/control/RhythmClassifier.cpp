#include "RhythmClassifier.h"

#include "../config/UserConfig.h"
#include "RhythmModel.generated.h"
#include <math.h>

namespace {
float clamp01(float value) {
  return value < 0.0f ? 0.0f : (value > 1.0f ? 1.0f : value);
}

uint8_t quantize01(float value) {
  return static_cast<uint8_t>(lroundf(clamp01(value) * 127.0f));
}

float heartRateOutOfRange(float bpm) {
  if (!isfinite(bpm)) return 1.0f;
  if (bpm < 50.0f) return clamp01((50.0f - bpm) / 30.0f);
  if (bpm > 110.0f) return clamp01((bpm - 110.0f) / 70.0f);
  return 0.0f;
}

} // namespace

void RhythmClassifier::reset() {
  reading_ = RhythmScreeningReading{};
  reading_.state = RhythmScreenState::Disabled;
  lastInferenceAtMs_ = 0;
  lastMotionAtMs_ = 0;
  clearConsensus();
}

void RhythmClassifier::clearConsensus() {
  consecutiveIrregular_ = 0;
  consecutiveSuspectedAf_ = 0;
}

void RhythmClassifier::copyFeatures(const RhythmFeatures &features,
                                    uint32_t nowMs) {
  reading_.ibiMeanMs = features.ibiMeanMs;
  reading_.sdnnMs = features.ibiStdMs;
  reading_.rmssdMs = features.rmssdMs;
  reading_.pnn50 = features.pnn50;
  reading_.beatCount = features.beatCount;
  reading_.updatedAtMs = nowMs;
  reading_.modelAvailable = Config::RHYTHM_BASELINE_MODEL_ENABLED;
  reading_.modelCalibrated = Config::RHYTHM_MODEL_CALIBRATED;
  reading_.modelBytes = RhythmModel::MODEL_BYTES;
  reading_.classifierStateBytes = sizeof(RhythmClassifier);
}

void RhythmClassifier::setNonTerminalState(RhythmScreenState state,
                                            const RhythmFeatures &features,
                                            uint32_t nowMs) {
  copyFeatures(features, nowMs);
  reading_.state = state;
  reading_.confidence = 0.0f;
  reading_.valid = false;
  reading_.alertActive = false;
}

bool RhythmClassifier::hasMotionArtifact(const ImuReading &imu) const {
  if (!Config::RHYTHM_REQUIRE_STILL_IMU || !imu.valid) return false;
  const float gyroMagnitude = sqrtf(imu.gyroX * imu.gyroX +
                                    imu.gyroY * imu.gyroY +
                                    imu.gyroZ * imu.gyroZ);
  const float accelerationMagnitude = imu.accelerationMagnitudeG();
  return !isfinite(gyroMagnitude) || !isfinite(accelerationMagnitude) ||
         gyroMagnitude > Config::RHYTHM_MAX_GYRO_DPS ||
         fabsf(accelerationMagnitude - 1.0f) > Config::RHYTHM_MAX_ACCEL_DELTA_G;
}

RhythmScreenState RhythmClassifier::infer(const RhythmFeatures &features,
                                          float &confidence) const {
  // Subject-independent, ECG-referenced, binary INT8 candidate.  A positive
  // raw result is still required in three consecutive windows by update(), so
  // the public-data model cannot directly raise an SOS/FALL alarm.
  // Input order: IBI CV, RMSSD/mean IBI, pNN50, max IBI jump/mean IBI,
  // signal quality, and out-of-range heart-rate score.
  const float meanIbi = fmaxf(features.ibiMeanMs, 1.0f);
  const uint8_t input[] = {
      quantize01((features.ibiCv - 0.015f) / 0.285f),
      quantize01((features.rmssdMs / meanIbi - 0.015f) / 0.285f),
      quantize01(features.pnn50),
      quantize01((features.maxAdjacentDiffMs / meanIbi - 0.04f) / 0.76f),
      quantize01(features.signalQuality),
      quantize01(heartRateOutOfRange(features.heartRateBpm))};
  int32_t score = RhythmModel::BIAS;
  for (uint8_t feature = 0; feature < RhythmModel::FEATURE_COUNT; ++feature) {
    score += static_cast<int32_t>(RhythmModel::WEIGHTS[feature]) *
             static_cast<int32_t>(input[feature]);
  }
  const float logit = static_cast<float>(score) / RhythmModel::SCORE_SCALE;
  const float probabilityAf = 1.0f / (1.0f + expf(-logit));
  const bool afLike = probabilityAf >= RhythmModel::AF_THRESHOLD;
  confidence = afLike ? probabilityAf : 1.0f - probabilityAf;
  return afLike ? RhythmScreenState::SuspectedAf
                : RhythmScreenState::Normal;
}

void RhythmClassifier::update(const RhythmFeatures &features,
                              const ImuReading &imu, uint32_t nowMs) {
  if (!Config::RHYTHM_SCREENING_ENABLED) {
    setNonTerminalState(RhythmScreenState::Disabled, features, nowMs);
    reading_.modelAvailable = false;
    clearConsensus();
    return;
  }
  if (!features.sensorOnline) {
    setNonTerminalState(RhythmScreenState::NoSensor, features, nowMs);
    clearConsensus();
    return;
  }
  if (!features.fingerPresent) {
    setNonTerminalState(RhythmScreenState::NoFinger, features, nowMs);
    clearConsensus();
    lastInferenceAtMs_ = 0;
    return;
  }
  if (hasMotionArtifact(imu)) {
    lastMotionAtMs_ = nowMs;
    lastInferenceAtMs_ = 0;
    clearConsensus();
    setNonTerminalState(RhythmScreenState::MotionArtifact, features, nowMs);
    return;
  }
  if (lastMotionAtMs_ != 0 &&
      nowMs - lastMotionAtMs_ < Config::RHYTHM_SETTLE_AFTER_MOTION_MS) {
    setNonTerminalState(RhythmScreenState::MotionArtifact, features, nowMs);
    return;
  }
  if (!features.ready) {
    setNonTerminalState(RhythmScreenState::Collecting, features, nowMs);
    clearConsensus();
    return;
  }
  if (features.signalQuality < Config::RHYTHM_MIN_SIGNAL_QUALITY) {
    setNonTerminalState(RhythmScreenState::Inconclusive, features, nowMs);
    clearConsensus();
    return;
  }
  if (!Config::RHYTHM_BASELINE_MODEL_ENABLED) {
    setNonTerminalState(RhythmScreenState::Inconclusive, features, nowMs);
    reading_.modelAvailable = false;
    clearConsensus();
    return;
  }
  if (lastInferenceAtMs_ != 0 &&
      nowMs - lastInferenceAtMs_ < Config::RHYTHM_INFERENCE_INTERVAL_MS) {
    return;
  }

  lastInferenceAtMs_ = nowMs;
  float confidence = 0.0f;
  const uint32_t inferenceStartedUs = micros();
  const RhythmScreenState rawResult = infer(features, confidence);
  const uint32_t inferenceUs = micros() - inferenceStartedUs;
  copyFeatures(features, nowMs);
  reading_.inferenceUs = inferenceUs;
  if (reading_.inferenceCount < UINT32_MAX) ++reading_.inferenceCount;
  reading_.confidence = confidence;
  reading_.valid = confidence >= Config::RHYTHM_MIN_MODEL_CONFIDENCE;
  reading_.alertActive = false;
  if (!reading_.valid) {
    reading_.state = RhythmScreenState::Inconclusive;
    clearConsensus();
    return;
  }

  switch (rawResult) {
  case RhythmScreenState::Normal:
    reading_.state = RhythmScreenState::Normal;
    clearConsensus();
    break;
  case RhythmScreenState::Irregular:
    reading_.state = RhythmScreenState::Irregular;
    ++consecutiveIrregular_;
    consecutiveSuspectedAf_ = 0;
    break;
  case RhythmScreenState::SuspectedAf:
    consecutiveIrregular_ = 0;
    if (consecutiveSuspectedAf_ < 255) ++consecutiveSuspectedAf_;
    // A single noisy/atypical window must not be shown as a serious alert.
    // Until it repeats, expose only the lower-severity irregular state.
    if (consecutiveSuspectedAf_ >= Config::RHYTHM_ALERT_CONSECUTIVE_WINDOWS) {
      reading_.state = RhythmScreenState::SuspectedAf;
      reading_.alertActive = true;
    } else {
      reading_.state = RhythmScreenState::Irregular;
    }
    break;
  default:
    reading_.state = RhythmScreenState::Inconclusive;
    clearConsensus();
    break;
  }
}
