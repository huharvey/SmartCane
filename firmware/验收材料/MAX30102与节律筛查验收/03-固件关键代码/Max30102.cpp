#include "Max30102.h"

namespace {
constexpr uint8_t REG_FIFO_WR_PTR = 0x04;
constexpr uint8_t REG_OVF_COUNTER = 0x05;
constexpr uint8_t REG_FIFO_RD_PTR = 0x06;
constexpr uint8_t REG_FIFO_DATA = 0x07;
constexpr uint8_t REG_FIFO_CONFIG = 0x08;
constexpr uint8_t REG_MODE_CONFIG = 0x09;
constexpr uint8_t REG_SPO2_CONFIG = 0x0A;
constexpr uint8_t REG_LED1_PA = 0x0C; // RED
constexpr uint8_t REG_LED2_PA = 0x0D; // IR
constexpr uint8_t REG_PART_ID = 0xFF;

constexpr uint8_t MAX30102_PART_ID = 0x15;
constexpr uint8_t MODE_RESET = 0x40;
constexpr uint8_t MODE_SPO2 = 0x03;
// Four-sample averaging, FIFO rollover and an almost-full threshold of 15.
// The averaging stage also decimates FIFO output, so 100 ADC samples/s become
// 25 RED/IR FIFO pairs/s.  Keep this in sync with FIFO_AVERAGE_SAMPLES.
constexpr uint8_t FIFO_CONFIG = 0x5F;
static_assert(Max30102::FIFO_AVERAGE_SAMPLES == 4,
              "MAX30102 FIFO averaging metadata must match register 0x5F");
// 4096 nA ADC range, 100 samples/s, 411 us LED pulse width.
constexpr uint8_t SPO2_CONFIG = 0x27;
}

bool Max30102::begin(TwoWire &wire, uint8_t address, uint8_t ledCurrent) {
  wire_ = &wire;
  address_ = address;
  online_ = false;
  partId_ = 0;
  lastOverflow_ = 0;

  uint8_t id = 0;
  if (!readRegister(REG_PART_ID, id)) return false;
  partId_ = id;
  if (partId_ != MAX30102_PART_ID) return false;

  if (!writeRegister(REG_MODE_CONFIG, MODE_RESET)) return false;
  delay(10); // setup-time reset only; no FreeRTOS task is running yet.

  // Clear FIFO pointers before enabling RED/IR acquisition.
  if (!writeRegister(REG_FIFO_WR_PTR, 0) ||
      !writeRegister(REG_OVF_COUNTER, 0) ||
      !writeRegister(REG_FIFO_RD_PTR, 0) ||
      !writeRegister(REG_FIFO_CONFIG, FIFO_CONFIG) ||
      !writeRegister(REG_SPO2_CONFIG, SPO2_CONFIG) ||
      !writeRegister(REG_LED1_PA, ledCurrent) ||
      !writeRegister(REG_LED2_PA, ledCurrent) ||
      !writeRegister(REG_MODE_CONFIG, MODE_SPO2)) {
    return false;
  }

  online_ = true;
  return true;
}

uint8_t Max30102::availableSamples() {
  if (!online_) return 0;
  uint8_t writePtr = 0;
  uint8_t overflow = 0;
  uint8_t readPtr = 0;
  if (!readRegister(REG_FIFO_WR_PTR, writePtr) ||
      !readRegister(REG_OVF_COUNTER, overflow) ||
      !readRegister(REG_FIFO_RD_PTR, readPtr)) {
    online_ = false;
    return 0;
  }

  // FIFO pointers are five bits. A nonzero overflow counter means samples were
  // dropped, but the remaining pointer distance is still safe to process.
  lastOverflow_ = static_cast<uint8_t>(overflow & 0x1F);
  return static_cast<uint8_t>((writePtr - readPtr) & 0x1F);
}

bool Max30102::readSample(Max30102Sample &sample) {
  if (!online_) return false;
  uint8_t data[6]{};
  if (!readRegisters(REG_FIFO_DATA, data, sizeof(data))) {
    online_ = false;
    return false;
  }
  sample.red = (static_cast<uint32_t>(data[0]) << 16 | data[1] << 8 | data[2]) &
               0x3FFFF;
  sample.ir = (static_cast<uint32_t>(data[3]) << 16 | data[4] << 8 | data[5]) &
              0x3FFFF;
  return true;
}

bool Max30102::writeRegister(uint8_t reg, uint8_t value) {
  if (!wire_) return false;
  wire_->beginTransmission(address_);
  wire_->write(reg);
  wire_->write(value);
  return wire_->endTransmission() == 0;
}

bool Max30102::readRegister(uint8_t reg, uint8_t &value) {
  return readRegisters(reg, &value, 1);
}

bool Max30102::readRegisters(uint8_t reg, uint8_t *buffer, size_t length) {
  if (!wire_ || !buffer || length == 0) return false;
  wire_->beginTransmission(address_);
  wire_->write(reg);
  if (wire_->endTransmission(false) != 0) return false;
  const size_t received = wire_->requestFrom(static_cast<int>(address_),
                                             static_cast<int>(length));
  if (received != length) {
    while (wire_->available()) wire_->read();
    return false;
  }
  for (size_t index = 0; index < length; ++index) {
    if (!wire_->available()) return false;
    buffer[index] = static_cast<uint8_t>(wire_->read());
  }
  return true;
}
