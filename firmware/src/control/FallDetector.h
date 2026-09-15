#pragma once

#include <Arduino.h>
#include "../model/SystemState.h"

// Combined IMU fall-event detector.  The strict path requires impact; the deep
// low-g path uses a longer quiet-inclination hold to tolerate a missed impact
// peak in the 10 Hz JY901S stream.
class FallDetector {
public:
  enum class Phase : uint8_t {
    Idle,
    Candidate,
    StrictHolding,
    DeepHolding,
    BothHolding,
  };

  struct Diagnostics {
    Phase phase = Phase::Idle;
    bool valid = false;
    float accelerationG = NAN;
    float gyroDps = NAN;
    float tiltDeg = NAN;
    bool freeFall = false;
    bool deepFreeFall = false;
    bool impact = false;
    bool tiltedAndStill = false;
  };

  void update(const ImuReading &imu, uint32_t nowMs);
  bool takeDetected();
  void reset();
  // Called after a user cancels a suspected/FALL alarm.  It clears any stale
  // candidate and prevents the same physical event from immediately rearming.
  void cancelAndCooldown(uint32_t nowMs);
  const Diagnostics &diagnostics() const { return diagnostics_; }
  static const char *phaseName(Phase phase);

private:
  bool isTilted(const ImuReading &imu) const;
  void clearCandidate();

  Phase phase_ = Phase::Idle;
  bool impactSeen_ = false;
  bool deepFreeFallSeen_ = false;
  bool detected_ = false;
  uint32_t candidateAtMs_ = 0;
  uint32_t strictTiltAtMs_ = 0;
  uint32_t deepTiltAtMs_ = 0;
  uint32_t lastDetectionAtMs_ = 0;
  Diagnostics diagnostics_;
};
