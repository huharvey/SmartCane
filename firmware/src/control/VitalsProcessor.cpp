#include "VitalsProcessor.h"

#include "../config/UserConfig.h"
#include <math.h>

namespace {
constexpr float DC_ALPHA = 0.02f;
constexpr float FILTER_ALPHA = 0.25f;
constexpr float ENVELOPE_ALPHA = 0.02f;
constexpr float PEAK_ENVELOPE_RATIO = 0.35f;
constexpr float MIN_PEAK_AMPLITUDE = 80.0f;
// A local maximum also needs to rise far enough above the lowest sample since
// the previous accepted peak.  This rejects shoulders/ripples that pass the
// simple amplitude threshold but are not a new pulse wave.
constexpr float PEAK_PROMINENCE_RATIO = 0.35f;
constexpr float MIN_PEAK_PROMINENCE = 80.0f;
// A stable recent rhythm can safely supply a longer refractory period.  A
// highly prominent early peak is still allowed through so genuine ectopy is
// not blindly smoothed out before rhythm classification.
constexpr float ADAPTIVE_REFRACTORY_RATIO = 0.60f;
constexpr float ADAPTIVE_REFRACTORY_MAX_MS = 500.0f;
constexpr float ADAPTIVE_REFRACTORY_MAX_CV = 0.25f;
constexpr float EARLY_PEAK_STRONG_PROMINENCE_RATIO = 0.90f;
constexpr uint8_t ADAPTIVE_REFRACTORY_MIN_IBI_COUNT = 3;
constexpr uint8_t BEAT_STALE_INTERVAL_MULTIPLIER = 2;

float clamp01(float value) {
  return value < 0.0f ? 0.0f : (value > 1.0f ? 1.0f : value);
}
}

void VitalsProcessor::reset() {
  reading_ = VitalsReading{};
  clearAnalysis();
}

void VitalsProcessor::setSensorOnline(bool online, uint32_t nowMs) {
  reading_.sensorOnline = online;
  if (online) return;

  reading_.fingerPresent = false;
  reading_.valid = false;
  reading_.heartRateBpm = NAN;
  reading_.spo2Pct = NAN;
  reading_.signalQuality = 0.0f;
  reading_.updatedAtMs = nowMs;
  clearAnalysis();
}

void VitalsProcessor::clearAnalysis() {
  reading_.heartRateBpm = NAN;
  reading_.spo2Pct = NAN;
  reading_.signalQuality = 0.0f;
  reading_.valid = false;
  redDc_ = 0.0f;
  irDc_ = 0.0f;
  filteredIr_ = 0.0f;
  envelope_ = 0.0f;
  troughSincePeak_ = 0.0f;
  previousFilteredIr_ = 0.0f;
  previousPreviousFilteredIr_ = 0.0f;
  previousSampleAtMs_ = 0;
  lastPeakAtMs_ = 0;
  lastValidBeatAtMs_ = 0;
  spo2WindowStartedAtMs_ = 0;
  redMin_ = redMax_ = irMin_ = irMax_ = 0;
  lastRelativeAmplitude_ = 0.0f;
  fingerPlacedAtMs_ = 0;
  filterInitialized_ = false;
  debug_ = PpgProcessingDebug{};
  resetIbiHistory();
}

void VitalsProcessor::resetIbiHistory() {
  reading_.heartRateBpm = NAN;
  ibiCount_ = 0;
  ibiWriteIndex_ = 0;
  rhythmIbiCount_ = 0;
  rhythmIbiWriteIndex_ = 0;
  lastValidBeatAtMs_ = 0;
  for (float &value : ibiMs_) value = 0.0f;
  for (uint8_t index = 0; index < RHYTHM_IBI_HISTORY_SIZE; ++index) {
    rhythmIbiMs_[index] = 0.0f;
    rhythmIbiAtMs_[index] = 0;
  }
}

void VitalsProcessor::resetSpo2Window(uint32_t red, uint32_t ir, uint32_t nowMs) {
  redMin_ = redMax_ = red;
  irMin_ = irMax_ = ir;
  spo2WindowStartedAtMs_ = nowMs;
}

void VitalsProcessor::update(const Max30102Sample &sample, uint32_t sampleAtMs) {
  debug_.peakCandidate = false;
  debug_.beatAccepted = false;
  debug_.ibiMs = NAN;
  reading_.sensorOnline = true;
  reading_.rawRed = sample.red;
  reading_.rawIr = sample.ir;
  reading_.updatedAtMs = sampleAtMs;

  const bool fingerPresent = sample.ir >= Config::MAX30102_FINGER_IR_THRESHOLD;
  if (!fingerPresent) {
    if (reading_.fingerPresent) clearAnalysis();
    reading_.fingerPresent = false;
    reading_.valid = false;
    reading_.heartRateBpm = NAN;
    reading_.spo2Pct = NAN;
    reading_.signalQuality = 0.0f;
    return;
  }

  if (!reading_.fingerPresent || !filterInitialized_) {
    clearAnalysis();
    reading_.fingerPresent = true;
    redDc_ = static_cast<float>(sample.red);
    irDc_ = static_cast<float>(sample.ir);
    fingerPlacedAtMs_ = sampleAtMs;
    resetSpo2Window(sample.red, sample.ir, sampleAtMs);
    filterInitialized_ = true;
    debug_.redDc = redDc_;
    debug_.irDc = irDc_;
    debug_.redAc = 0.0f;
    debug_.irAc = 0.0f;
    debug_.filteredIr = 0.0f;
    debug_.envelope = 0.0f;
    reading_.valid = false;
    return;
  }

  reading_.fingerPresent = true;
  redDc_ += DC_ALPHA * (static_cast<float>(sample.red) - redDc_);
  irDc_ += DC_ALPHA * (static_cast<float>(sample.ir) - irDc_);
  const float irAc = static_cast<float>(sample.ir) - irDc_;
  filteredIr_ += FILTER_ALPHA * (irAc - filteredIr_);
  envelope_ += ENVELOPE_ALPHA * (fabsf(filteredIr_) - envelope_);
  debug_.redDc = redDc_;
  debug_.irDc = irDc_;
  debug_.redAc = static_cast<float>(sample.red) - redDc_;
  debug_.irAc = irAc;
  debug_.filteredIr = filteredIr_;
  debug_.envelope = envelope_;

  redMin_ = min(redMin_, sample.red);
  redMax_ = max(redMax_, sample.red);
  irMin_ = min(irMin_, sample.ir);
  irMax_ = max(irMax_, sample.ir);

  // A local maximum above an adaptive amplitude threshold is a pulse candidate.
  troughSincePeak_ = fminf(troughSincePeak_, previousFilteredIr_);
  if (previousSampleAtMs_ != 0 &&
      previousFilteredIr_ > previousPreviousFilteredIr_ &&
      previousFilteredIr_ >= filteredIr_ &&
      previousFilteredIr_ >= fmaxf(MIN_PEAK_AMPLITUDE,
                                   envelope_ * PEAK_ENVELOPE_RATIO)) {
    debug_.peakCandidate = true;
    const float prominence = previousFilteredIr_ - troughSincePeak_;
    if (prominence >= fmaxf(MIN_PEAK_PROMINENCE,
                            envelope_ * PEAK_PROMINENCE_RATIO)) {
      const uint32_t previousAnchor = lastPeakAtMs_;
      debug_.beatAccepted = registerPeak(previousSampleAtMs_, prominence,
                                         fmaxf(envelope_, 1.0f));
      // registerPeak also moves the anchor after a long gap.  Reset the trough
      // in both cases, even though a gap itself is not a valid IBI.
      if (lastPeakAtMs_ != previousAnchor) {
        troughSincePeak_ = previousFilteredIr_;
      }
    }
  }
  previousPreviousFilteredIr_ = previousFilteredIr_;
  previousFilteredIr_ = filteredIr_;
  previousSampleAtMs_ = sampleAtMs;

  updateSpo2(sampleAtMs);
  updateQuality(sampleAtMs);
  const uint32_t maxIbi = static_cast<uint32_t>(
      60000.0f / Config::MAX30102_HEART_RATE_MIN_BPM);
  const bool beatFresh = lastValidBeatAtMs_ != 0 &&
                         sampleAtMs - lastValidBeatAtMs_ <=
                             maxIbi * BEAT_STALE_INTERVAL_MULTIPLIER;
  if (!beatFresh) reading_.heartRateBpm = NAN;
  reading_.valid = reading_.fingerPresent && isfinite(reading_.heartRateBpm) &&
                   isfinite(reading_.spo2Pct) &&
                   reading_.signalQuality >= Config::MAX30102_VALID_QUALITY_MIN &&
                   beatFresh;
}

bool VitalsProcessor::registerPeak(uint32_t peakAtMs, float prominence,
                                   float envelope) {
  if (lastPeakAtMs_ == 0) {
    lastPeakAtMs_ = peakAtMs;
    return true;
  }

  const uint32_t ibi = peakAtMs - lastPeakAtMs_;
  const uint32_t minIbi = static_cast<uint32_t>(
      60000.0f / Config::MAX30102_HEART_RATE_MAX_BPM);
  const uint32_t maxIbi = static_cast<uint32_t>(
      60000.0f / Config::MAX30102_HEART_RATE_MIN_BPM);
  if (ibi < minIbi) return false; // likely a noise/secondary peak

  const uint32_t adaptiveMinIbi = adaptiveRefractoryMs();
  const float prominenceRatio = prominence / fmaxf(envelope, 1.0f);
  if (ibi < adaptiveMinIbi &&
      prominenceRatio < EARLY_PEAK_STRONG_PROMINENCE_RATIO) {
    return false;
  }

  lastPeakAtMs_ = peakAtMs;
  if (ibi > maxIbi) {
    // A long gap means the previous HR and rhythm window are no longer a
    // contiguous measurement.  Keep this peak only as the next anchor.
    resetIbiHistory();
    return false;
  }

  debug_.ibiMs = static_cast<float>(ibi);
  lastValidBeatAtMs_ = peakAtMs;

  ibiMs_[ibiWriteIndex_] = static_cast<float>(ibi);
  ibiWriteIndex_ = (ibiWriteIndex_ + 1) % IBI_HISTORY_SIZE;
  if (ibiCount_ < IBI_HISTORY_SIZE) ++ibiCount_;
  rhythmIbiMs_[rhythmIbiWriteIndex_] = static_cast<float>(ibi);
  rhythmIbiAtMs_[rhythmIbiWriteIndex_] = peakAtMs;
  rhythmIbiWriteIndex_ = (rhythmIbiWriteIndex_ + 1) % RHYTHM_IBI_HISTORY_SIZE;
  if (rhythmIbiCount_ < RHYTHM_IBI_HISTORY_SIZE) ++rhythmIbiCount_;
  updateHeartRate();
  return true;
}

void VitalsProcessor::updateHeartRate() {
  if (ibiCount_ < 3) {
    reading_.heartRateBpm = NAN;
    return;
  }
  // Median is robust for the displayed HR while the unmodified IBI sequence
  // remains available to the rhythm feature extractor.
  const float representativeIbi = ibiMedian();
  if (!isfinite(representativeIbi) || representativeIbi <= 0.0f) {
    reading_.heartRateBpm = NAN;
    return;
  }
  const float bpm = 60000.0f / representativeIbi;
  reading_.heartRateBpm =
      bpm >= Config::MAX30102_HEART_RATE_MIN_BPM &&
              bpm <= Config::MAX30102_HEART_RATE_MAX_BPM
          ? bpm
          : NAN;
}

void VitalsProcessor::updateSpo2(uint32_t sampleAtMs) {
  if (spo2WindowStartedAtMs_ == 0 ||
      sampleAtMs - spo2WindowStartedAtMs_ < Config::MAX30102_SPO2_WINDOW_MS) {
    return;
  }

  const float redAc = static_cast<float>(redMax_ - redMin_);
  const float irAc = static_cast<float>(irMax_ - irMin_);
  const float redDc = fmaxf(redDc_, 1.0f);
  const float irDc = fmaxf(irDc_, 1.0f);
  lastRelativeAmplitude_ = irAc / irDc;

  if (redAc > 0.0f && irAc > 0.0f &&
      lastRelativeAmplitude_ >= Config::MAX30102_MIN_RELATIVE_AMPLITUDE) {
    const float ratio = (redAc / redDc) / (irAc / irDc);
    // Widely used classroom/demo approximation. It is intentionally labelled
    // as an estimate in the UI and is suppressed when the signal is poor.
    const float estimated = 110.0f - 25.0f * ratio;
    reading_.spo2Pct = estimated >= 70.0f && estimated <= 100.0f ? estimated : NAN;
  } else {
    reading_.spo2Pct = NAN;
  }
  resetSpo2Window(reading_.rawRed, reading_.rawIr, sampleAtMs);
}

void VitalsProcessor::updateQuality(uint32_t nowMs) {
  const float amplitudeScore = clamp01(
      (lastRelativeAmplitude_ - Config::MAX30102_MIN_RELATIVE_AMPLITUDE) / 0.010f);
  const uint32_t maxIbi = static_cast<uint32_t>(
      60000.0f / Config::MAX30102_HEART_RATE_MIN_BPM);
  const bool beatFresh = lastValidBeatAtMs_ != 0 &&
                         nowMs - lastValidBeatAtMs_ <=
                             maxIbi * BEAT_STALE_INTERVAL_MULTIPLIER;
  const float intervalScore = beatFresh && ibiCount_ >= 3
      ? clamp01(1.0f - ibiCoefficientOfVariation() / 0.35f)
      : 0.0f;
  reading_.signalQuality = 0.70f * amplitudeScore + 0.30f * intervalScore;
}

float VitalsProcessor::ibiMean() const {
  if (ibiCount_ == 0) return NAN;
  float sum = 0.0f;
  for (uint8_t index = 0; index < ibiCount_; ++index) sum += ibiMs_[index];
  return sum / ibiCount_;
}

float VitalsProcessor::ibiMedian() const {
  if (ibiCount_ == 0) return NAN;
  float sorted[IBI_HISTORY_SIZE]{};
  for (uint8_t index = 0; index < ibiCount_; ++index) {
    sorted[index] = ibiMs_[index];
  }
  // The bounded history contains at most eight values; insertion sort avoids
  // dynamic allocation and has negligible sensor-task cost.
  for (uint8_t index = 1; index < ibiCount_; ++index) {
    const float value = sorted[index];
    int8_t position = static_cast<int8_t>(index) - 1;
    while (position >= 0 && sorted[position] > value) {
      sorted[position + 1] = sorted[position];
      --position;
    }
    sorted[position + 1] = value;
  }
  const uint8_t middle = ibiCount_ / 2;
  return ibiCount_ % 2 == 0
             ? 0.5f * (sorted[middle - 1] + sorted[middle])
             : sorted[middle];
}

float VitalsProcessor::ibiCoefficientOfVariation() const {
  if (ibiCount_ < 2) return 1.0f;
  const float mean = ibiMean();
  if (!isfinite(mean) || mean <= 0.0f) return 1.0f;
  float squaredError = 0.0f;
  for (uint8_t index = 0; index < ibiCount_; ++index) {
    const float delta = ibiMs_[index] - mean;
    squaredError += delta * delta;
  }
  return sqrtf(squaredError / ibiCount_) / mean;
}

uint32_t VitalsProcessor::adaptiveRefractoryMs() const {
  const uint32_t fixedMinIbi = static_cast<uint32_t>(
      60000.0f / Config::MAX30102_HEART_RATE_MAX_BPM);
  if (ibiCount_ < ADAPTIVE_REFRACTORY_MIN_IBI_COUNT ||
      ibiCoefficientOfVariation() > ADAPTIVE_REFRACTORY_MAX_CV) {
    return fixedMinIbi;
  }
  const float adaptive = fminf(ADAPTIVE_REFRACTORY_MAX_MS,
                               ibiMedian() * ADAPTIVE_REFRACTORY_RATIO);
  return max(fixedMinIbi, static_cast<uint32_t>(adaptive));
}

RhythmFeatures VitalsProcessor::rhythmFeatures(uint32_t nowMs) const {
  RhythmFeatures features;
  features.sensorOnline = reading_.sensorOnline;
  features.fingerPresent = reading_.fingerPresent;
  features.ppgValid = reading_.valid;
  features.signalQuality = reading_.signalQuality;
  features.heartRateBpm = reading_.heartRateBpm;
  if (!features.sensorOnline || !features.fingerPresent || fingerPlacedAtMs_ == 0) {
    return features;
  }

  features.windowDurationMs = nowMs - fingerPlacedAtMs_;
  if (rhythmIbiCount_ == 0) return features;

  const uint8_t oldestIndex = rhythmIbiCount_ < RHYTHM_IBI_HISTORY_SIZE
                                  ? 0
                                  : rhythmIbiWriteIndex_;
  float sum = 0.0f;
  uint8_t count = 0;
  for (uint8_t offset = 0; offset < rhythmIbiCount_; ++offset) {
    const uint8_t index = (oldestIndex + offset) % RHYTHM_IBI_HISTORY_SIZE;
    if (rhythmIbiAtMs_[index] == 0 ||
        nowMs - rhythmIbiAtMs_[index] > Config::RHYTHM_FEATURE_WINDOW_MS) {
      continue;
    }
    sum += rhythmIbiMs_[index];
    ++count;
  }
  features.beatCount = count;
  if (count < 2) return features;

  const float mean = sum / count;
  float squaredError = 0.0f;
  float adjacentSquaredError = 0.0f;
  float maxAdjacentDifference = 0.0f;
  uint8_t adjacentCount = 0;
  uint8_t pnn50Count = 0;
  float previous = 0.0f;
  bool havePrevious = false;
  for (uint8_t offset = 0; offset < rhythmIbiCount_; ++offset) {
    const uint8_t index = (oldestIndex + offset) % RHYTHM_IBI_HISTORY_SIZE;
    if (rhythmIbiAtMs_[index] == 0 ||
        nowMs - rhythmIbiAtMs_[index] > Config::RHYTHM_FEATURE_WINDOW_MS) {
      continue;
    }
    const float current = rhythmIbiMs_[index];
    const float delta = current - mean;
    squaredError += delta * delta;
    if (havePrevious) {
      const float adjacentDifference = fabsf(current - previous);
      adjacentSquaredError += adjacentDifference * adjacentDifference;
      if (adjacentDifference > maxAdjacentDifference)
        maxAdjacentDifference = adjacentDifference;
      if (adjacentDifference > 50.0f) ++pnn50Count;
      ++adjacentCount;
    }
    previous = current;
    havePrevious = true;
  }

  features.ibiMeanMs = mean;
  features.ibiStdMs = sqrtf(squaredError / count);
  features.ibiCv = mean > 0.0f ? features.ibiStdMs / mean : NAN;
  features.rmssdMs = adjacentCount > 0
      ? sqrtf(adjacentSquaredError / adjacentCount) : NAN;
  features.pnn50 = adjacentCount > 0
      ? static_cast<float>(pnn50Count) / adjacentCount : NAN;
  features.maxAdjacentDiffMs = maxAdjacentDifference;
  features.ready = features.ppgValid &&
                   features.windowDurationMs >= Config::RHYTHM_FEATURE_WINDOW_MS &&
                   count >= Config::RHYTHM_MIN_IBI_COUNT;
  return features;
}
