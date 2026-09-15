#pragma once

#include <Arduino.h>

#include "../model/SystemState.h"

// A compact feature classifier for on-device PPG rhythm pre-screening.  It
// consumes only the bounded IBI/quality features emitted by VitalsProcessor;
// it never reads a sensor bus and never controls SOS, FALL, buzzer or camera.
class RhythmClassifier {
public:
  void reset();
  void update(const RhythmFeatures &features, const ImuReading &imu,
              uint32_t nowMs);
  const RhythmScreeningReading &reading() const { return reading_; }

private:
  bool hasMotionArtifact(const ImuReading &imu) const;
  RhythmScreenState infer(const RhythmFeatures &features,
                          float &confidence) const;
  void copyFeatures(const RhythmFeatures &features, uint32_t nowMs);
  void setNonTerminalState(RhythmScreenState state,
                           const RhythmFeatures &features, uint32_t nowMs);
  void clearConsensus();

  RhythmScreeningReading reading_;
  uint32_t lastInferenceAtMs_ = 0;
  uint32_t lastMotionAtMs_ = 0;
  uint8_t consecutiveIrregular_ = 0;
  uint8_t consecutiveSuspectedAf_ = 0;
};
