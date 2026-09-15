#pragma once

#include <Arduino.h>
#include <Wire.h>

// One RED/IR pair from the MAX30102 FIFO.  The device is configured for
// SpO2 mode, where each sample contains RED followed by IR, both 18-bit.
struct Max30102Sample {
  uint32_t red = 0;
  uint32_t ir = 0;
};

class Max30102 {
public:
  // FIFO_CONFIG uses SMP_AVE=010: every FIFO word is the average of four ADC
  // conversions.  The effective FIFO rate is therefore ADC rate / 4.
  static constexpr uint8_t FIFO_AVERAGE_SAMPLES = 4;

  bool begin(TwoWire &wire, uint8_t address, uint8_t ledCurrent);
  bool online() const { return online_; }
  uint8_t partId() const { return partId_; }
  uint8_t lastOverflow() const { return lastOverflow_; }

  // Number of complete samples waiting in the 32-sample hardware FIFO.
  uint8_t availableSamples();
  // Reads exactly one RED/IR pair. Call only when availableSamples() is nonzero.
  bool readSample(Max30102Sample &sample);

private:
  bool writeRegister(uint8_t reg, uint8_t value);
  bool readRegister(uint8_t reg, uint8_t &value);
  bool readRegisters(uint8_t reg, uint8_t *buffer, size_t length);

  TwoWire *wire_ = nullptr;
  uint8_t address_ = 0x57;
  uint8_t partId_ = 0;
  uint8_t lastOverflow_ = 0;
  bool online_ = false;
};
