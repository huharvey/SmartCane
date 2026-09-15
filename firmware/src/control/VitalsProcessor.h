#pragma once

#include <Arduino.h>
#include "../drivers/Max30102.h"
#include "../model/SystemState.h"

// Per-FIFO-sample observability for the local Qt calibration tool.  These
// values never enter MQTT and are emitted only while the explicit PPG debug
// stream is enabled.
struct PpgProcessingDebug {
  float redDc = NAN;
  float irDc = NAN;
  float redAc = NAN;
  float irAc = NAN;
  float filteredIr = NAN;
  float envelope = NAN;
  float ibiMs = NAN;
  bool peakCandidate = false;
  bool beatAccepted = false;
};

// A bounded-memory PPG processor for the MAX30102. It intentionally provides
// monitoring estimates, not a medical diagnosis. All processing is O(1) per
// sample and can run inside the existing SensorTask.
class VitalsProcessor {
public:
  void reset();
  void setSensorOnline(bool online, uint32_t nowMs);
  void update(const Max30102Sample &sample, uint32_t sampleAtMs);
  const VitalsReading &reading() const { return reading_; }
  const PpgProcessingDebug &debugReading() const { return debug_; }
  RhythmFeatures rhythmFeatures(uint32_t nowMs) const;

private:
  static constexpr uint8_t IBI_HISTORY_SIZE = 8;
  // 48 intervals retain the entire 15 s feature window even near the upper
  // configured heart-rate limit, while using less than 400 bytes of RAM.
  static constexpr uint8_t RHYTHM_IBI_HISTORY_SIZE = 48;

  void clearAnalysis();
  void resetIbiHistory();
  void resetSpo2Window(uint32_t red, uint32_t ir, uint32_t nowMs);
  bool registerPeak(uint32_t peakAtMs, float prominence, float envelope);
  void updateHeartRate();
  void updateSpo2(uint32_t sampleAtMs);
  void updateQuality(uint32_t nowMs);
  float ibiMean() const;
  float ibiMedian() const;
  float ibiCoefficientOfVariation() const;
  uint32_t adaptiveRefractoryMs() const;

  VitalsReading reading_;
  PpgProcessingDebug debug_;
  float redDc_ = 0.0f;
  float irDc_ = 0.0f;
  float filteredIr_ = 0.0f;
  float envelope_ = 0.0f;
  float troughSincePeak_ = 0.0f;
  float previousFilteredIr_ = 0.0f;
  float previousPreviousFilteredIr_ = 0.0f;
  uint32_t previousSampleAtMs_ = 0;
  uint32_t lastPeakAtMs_ = 0;
  uint32_t lastValidBeatAtMs_ = 0;
  uint32_t spo2WindowStartedAtMs_ = 0;
  uint32_t redMin_ = 0;
  uint32_t redMax_ = 0;
  uint32_t irMin_ = 0;
  uint32_t irMax_ = 0;
  float lastRelativeAmplitude_ = 0.0f;
  float ibiMs_[IBI_HISTORY_SIZE]{};
  uint8_t ibiCount_ = 0;
  uint8_t ibiWriteIndex_ = 0;
  float rhythmIbiMs_[RHYTHM_IBI_HISTORY_SIZE]{};
  uint32_t rhythmIbiAtMs_[RHYTHM_IBI_HISTORY_SIZE]{};
  uint8_t rhythmIbiCount_ = 0;
  uint8_t rhythmIbiWriteIndex_ = 0;
  uint32_t fingerPlacedAtMs_ = 0;
  bool filterInitialized_ = false;
};
