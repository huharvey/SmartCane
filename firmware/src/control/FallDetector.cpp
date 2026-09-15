#include "FallDetector.h"
#include "../config/UserConfig.h"
#include <math.h>

void FallDetector::reset() {
  phase_ = Phase::Idle;
  impactSeen_ = false;
  deepFreeFallSeen_ = false;
  detected_ = false;
  candidateAtMs_ = 0;
  strictTiltAtMs_ = 0;
  deepTiltAtMs_ = 0;
  lastDetectionAtMs_ = 0;
  diagnostics_ = Diagnostics{};
}

void FallDetector::cancelAndCooldown(uint32_t nowMs) {
  clearCandidate();
  detected_ = false;
  lastDetectionAtMs_ = nowMs;
  diagnostics_.phase = Phase::Idle;
}

const char *FallDetector::phaseName(Phase phase) {
  switch (phase) {
  case Phase::Candidate: return "CANDIDATE";
  case Phase::StrictHolding: return "STRICT_HOLD";
  case Phase::DeepHolding: return "DEEP_HOLD";
  case Phase::BothHolding: return "BOTH_HOLD";
  default: return "IDLE";
  }
}

bool FallDetector::isTilted(const ImuReading &imu) const {
  return fabsf(imu.rollDeg) >= Config::FALL_TILT_DEG ||
         fabsf(imu.pitchDeg) >= Config::FALL_TILT_DEG;
}

void FallDetector::clearCandidate() {
  phase_ = Phase::Idle;
  impactSeen_ = false;
  deepFreeFallSeen_ = false;
  candidateAtMs_ = 0;
  strictTiltAtMs_ = 0;
  deepTiltAtMs_ = 0;
}

void FallDetector::update(const ImuReading &imu, uint32_t nowMs) {
  diagnostics_ = Diagnostics{};
  if (!imu.valid || !isfinite(imu.axG) || !isfinite(imu.ayG) ||
      !isfinite(imu.azG) || !isfinite(imu.rollDeg) ||
      !isfinite(imu.pitchDeg) || !isfinite(imu.gyroX) ||
      !isfinite(imu.gyroY) || !isfinite(imu.gyroZ)) {
    clearCandidate();
    return;
  }

  const float accelerationG = imu.accelerationMagnitudeG();
  const float gyroDps = sqrtf(imu.gyroX * imu.gyroX + imu.gyroY * imu.gyroY +
                              imu.gyroZ * imu.gyroZ);
  const float tiltDeg = fmaxf(fabsf(imu.rollDeg), fabsf(imu.pitchDeg));
  const bool freeFall = accelerationG <= Config::FALL_FREE_FALL_G;
  const bool deepFreeFall = accelerationG <= Config::FALL_DEEP_FREE_FALL_G;
  const bool impact = accelerationG >= Config::FALL_IMPACT_G;
  const bool tiltedAndStill = isTilted(imu) && gyroDps <= Config::FALL_STILL_GYRO_DPS;
  diagnostics_.valid = true;
  diagnostics_.accelerationG = accelerationG;
  diagnostics_.gyroDps = gyroDps;
  diagnostics_.tiltDeg = tiltDeg;
  diagnostics_.freeFall = freeFall;
  diagnostics_.deepFreeFall = deepFreeFall;
  diagnostics_.impact = impact;
  diagnostics_.tiltedAndStill = tiltedAndStill;

  // A cancelled event must not be immediately re-detected from the same
  // movement.  Sampling continues; only new fall candidates are suppressed.
  if (lastDetectionAtMs_ != 0 &&
      nowMs - lastDetectionAtMs_ < Config::FALL_CANCEL_COOLDOWN_MS) {
    clearCandidate();
    diagnostics_.phase = phase_;
    return;
  }

  if (phase_ != Phase::Idle &&
      nowMs - candidateAtMs_ > Config::FALL_SEQUENCE_WINDOW_MS) clearCandidate();

  if (phase_ == Phase::Idle && (freeFall || impact)) {
    phase_ = Phase::Candidate;
    candidateAtMs_ = nowMs;
    impactSeen_ = impact;
    deepFreeFallSeen_ = deepFreeFall;
  } else if (phase_ != Phase::Idle) {
    impactSeen_ = impactSeen_ || impact;
    deepFreeFallSeen_ = deepFreeFallSeen_ || deepFreeFall;
  }

  if (phase_ != Phase::Idle) {
    if (impactSeen_ && tiltedAndStill) {
      if (strictTiltAtMs_ == 0) strictTiltAtMs_ = nowMs;
    } else {
      strictTiltAtMs_ = 0;
    }
    if (deepFreeFallSeen_ && tiltedAndStill) {
      if (deepTiltAtMs_ == 0) deepTiltAtMs_ = nowMs;
    } else {
      deepTiltAtMs_ = 0;
    }

    if (strictTiltAtMs_ != 0 && deepTiltAtMs_ != 0) {
      phase_ = Phase::BothHolding;
    } else if (strictTiltAtMs_ != 0) {
      phase_ = Phase::StrictHolding;
    } else if (deepTiltAtMs_ != 0) {
      phase_ = Phase::DeepHolding;
    } else {
      phase_ = Phase::Candidate;
    }
  }

  const bool strictConfirmed =
      strictTiltAtMs_ != 0 &&
      nowMs - strictTiltAtMs_ >= Config::FALL_TILT_HOLD_MS;
  const bool deepConfirmed =
      deepTiltAtMs_ != 0 &&
      nowMs - deepTiltAtMs_ >= Config::FALL_DEEP_TILT_HOLD_MS;
  if ((strictConfirmed || deepConfirmed) &&
      (lastDetectionAtMs_ == 0 ||
       nowMs - lastDetectionAtMs_ >= Config::FALL_COOLDOWN_MS)) {
    detected_ = true;
    lastDetectionAtMs_ = nowMs;
    clearCandidate();
  }
  diagnostics_.phase = phase_;
}

bool FallDetector::takeDetected() {
  const bool detected = detected_;
  detected_ = false;
  return detected;
}
