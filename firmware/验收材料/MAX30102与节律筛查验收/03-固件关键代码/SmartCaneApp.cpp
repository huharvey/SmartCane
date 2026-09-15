#include "SmartCaneApp.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

namespace {
void appendJsonNumber(String &json, double value, unsigned int decimals,
                      bool enabled = true) {
  if (enabled && isfinite(value)) json += String(value, decimals);
  else json += "null";
}

constexpr uint32_t GPS_BAUD_CANDIDATES[] = {
    9600, 4800, 19200, 38400, 57600, 115200};

// The scanner is deliberately independent of the normal GPS parser.  It only
// accepts complete NMEA lines with a valid checksum, so random bytes from a
// wrong UART rate cannot be mistaken for a detected baud rate.
bool hasValidNmeaChecksum(const char *line) {
  if (!line || line[0] != '$') return false;
  const char *star = strchr(line, '*');
  if (!star || strlen(star) < 3) return false;

  uint8_t checksum = 0;
  for (const char *p = line + 1; p < star; ++p) checksum ^= *p;
  return checksum == static_cast<uint8_t>(strtoul(star + 1, nullptr, 16));
}
}

SmartCaneApp *SmartCaneApp::instance_ = nullptr;

SmartCaneApp::SmartCaneApp()
    : sonar_(Wire, Config::SONAR_I2C_ADDRESS), lightSensor_(Wire),
      oled_(Wire, Config::OLED_I2C_ADDRESS),
      sosButton_(Board::PIN_SOS_KEY, true),
      outputs_(Board::PIN_BUZZER, Board::PIN_LIGHT_LED, true) {}

void SmartCaneApp::begin() {
  instance_ = this;
  Serial.begin(Board::DEBUG_BAUD);
  delay(250);
  Serial.println("\n[SmartCane] boot");

  outputs_.begin();
  sosButton_.begin();
  sensorQueue_ = xQueueCreate(1, sizeof(SensorSnapshot));
  actuatorQueue_ = xQueueCreate(1, sizeof(ActuatorIntent));
  commandQueue_ = xQueueCreate(12, sizeof(ControlCommand));
  imuDebugQueue_ = xQueueCreate(48, sizeof(ImuDebugRecord));
  ppgDebugQueue_ = xQueueCreate(64, sizeof(PpgDebugRecord));
  i2cMutex_ = xSemaphoreCreateMutex();
  stateMutex_ = xSemaphoreCreateMutex();
  if (!sensorQueue_ || !actuatorQueue_ || !commandQueue_ || !imuDebugQueue_ ||
      !ppgDebugQueue_ ||
      !i2cMutex_ || !stateMutex_) {
    Serial.println("[FreeRTOS] allocation failed; tasks not started");
    return;
  }

  Wire.begin(Board::PIN_I2C_SDA, Board::PIN_I2C_SCL, Board::I2C_CLOCK_HZ);
  Wire.setTimeOut(50);
  if (Config::MAX30102_ENABLED) {
    if (!Config::MAX30102_USE_PRIMARY_I2C) {
      max30102Wire_.begin(Board::PIN_MAX30102_SDA, Board::PIN_MAX30102_SCL,
                          Board::MAX30102_I2C_CLOCK_HZ);
      max30102Wire_.setTimeOut(20);
    }
    TwoWire &maxWire = Config::MAX30102_USE_PRIMARY_I2C ? Wire : max30102Wire_;
    const int maxSda = Config::MAX30102_USE_PRIMARY_I2C
                           ? Board::PIN_I2C_SDA : Board::PIN_MAX30102_SDA;
    const int maxScl = Config::MAX30102_USE_PRIMARY_I2C
                           ? Board::PIN_I2C_SCL : Board::PIN_MAX30102_SCL;
    lastMax30102ProbeMs_ = millis();
    const bool maxReady = max30102_.begin(maxWire, Config::MAX30102_I2C_ADDRESS,
                                           Config::MAX30102_LED_CURRENT);
    vitalsProcessor_.setSensorOnline(maxReady, lastMax30102ProbeMs_);
    Serial.printf("[MAX30102] %s on %s SDA=%d SCL=%d%s\n",
                  maxReady ? "online" : "not found",
                  Config::MAX30102_USE_PRIMARY_I2C ? "primary I2C" : "I2C1",
                  maxSda, maxScl,
                  maxReady ? "" : " (will retry every 5 s)");
  }
  scanI2c();
  Serial.printf("[BH1750] %s\n", lightSensor_.begin() ? "online" : "not found");
  if (Config::SONAR_ENABLED) {
    Serial.printf("[Sonar] %s at 0x%02X\n",
                  sonar_.begin() ? "online" : "not found",
                  Config::SONAR_I2C_ADDRESS);
  } else {
    Serial.println("[Sonar] disabled (not installed)");
  }
  if (Config::OLED_ENABLED) {
    Serial.printf("[OLED] %s\n", oled_.begin() ? "online" : "not found");
  } else {
    Serial.println("[OLED] disabled (not installed)");
  }
  imu_.begin(imuSerial_, Board::IMU_BAUD, Board::PIN_IMU_RX, Board::PIN_IMU_TX);
  const uint32_t gpsBaud = Config::GPS_BAUD_DIAGNOSTIC_ON_BOOT
                               ? diagnoseGpsBaud()
                               : Board::GPS_BAUD;
  gps_.begin(gpsSerial_, gpsBaud, Board::PIN_GPS_RX, Board::PIN_GPS_TX);
  Serial.printf("[GPS] parser started at %lu bps\n",
                static_cast<unsigned long>(gpsBaud));

  if (oled_.online()) {
    oled_.clear();
    oled_.drawText(10, 8, "SMART CANE", 2);
    oled_.drawText(20, 34, "STARTING...", 1);
    oled_.display();
  }
  serialTelemetry_.begin(Serial, jsonThunk, commandThunk,
                         Config::TELEMETRY_INTERVAL_MS);
  network_.begin(jsonThunk, commandThunk);
  mqttRemote_.begin(commandThunk);

  // Core 1 owns the time-sensitive sensor, decision, display and GPIO path.
  // ESP-IDF keeps Wi-Fi/HTTP internally scheduled; this small service task on
  // Core 0 only advances reconnection state and publishes network metadata.
  const BaseType_t sensorOk = xTaskCreatePinnedToCore(sensorTaskThunk, "SensorTask",
      6144, this, 5, &sensorTaskHandle_, 1);
  const BaseType_t decisionOk = xTaskCreatePinnedToCore(decisionTaskThunk, "DecisionTask",
      6144, this, 4, &decisionTaskHandle_, 1);
  const BaseType_t actuatorOk = xTaskCreatePinnedToCore(actuatorTaskThunk, "ActuatorTask",
      4096, this, 3, &actuatorTaskHandle_, 1);
  const BaseType_t networkOk = xTaskCreatePinnedToCore(networkTaskThunk, "NetworkTask",
      4096, this, 2, &networkTaskHandle_, 0);
  const BaseType_t telemetryOk = xTaskCreatePinnedToCore(telemetryTaskThunk, "TelemetryTask",
      4096, this, 2, &telemetryTaskHandle_, 0);
  if (sensorOk != pdPASS || decisionOk != pdPASS || actuatorOk != pdPASS ||
      networkOk != pdPASS || telemetryOk != pdPASS) {
    Serial.println("[FreeRTOS] task creation failed; reboot after checking heap");
  } else {
    Serial.println("[FreeRTOS] Sensor/Decision/Actuator=Core1, Network/Telemetry=Core0");
  }
}

void SmartCaneApp::scanI2c() {
  Serial.print("[I2C] devices:");
  uint8_t count = 0;
  for (uint8_t address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf(" 0x%02X", address);
      ++count;
    }
  }
  if (!count) Serial.print(" none");
  Serial.println();
}

uint32_t SmartCaneApp::diagnoseGpsBaud() {
  Serial.println("[GPS-DIAG] boot scan enabled; waiting for valid NMEA");
  char line[128]{};

  for (const uint32_t baud : GPS_BAUD_CANDIDATES) {
    Serial.printf("[GPS-DIAG] testing %lu bps for %lu ms\n",
                  static_cast<unsigned long>(baud),
                  static_cast<unsigned long>(Config::GPS_BAUD_DIAGNOSTIC_DWELL_MS));
    gpsSerial_.end();
    gpsSerial_.begin(baud, SERIAL_8N1, Board::PIN_GPS_RX, Board::PIN_GPS_TX);

    size_t length = 0;
    uint8_t validLines = 0;
    const uint32_t startedAtMs = millis();
    while (millis() - startedAtMs < Config::GPS_BAUD_DIAGNOSTIC_DWELL_MS) {
      while (gpsSerial_.available()) {
        const char c = static_cast<char>(gpsSerial_.read());
        if (c == '\n') {
          line[length] = '\0';
          if (length > 6 && hasValidNmeaChecksum(line)) {
            Serial.printf("[GPS-NMEA @%lu] %s\n", static_cast<unsigned long>(baud),
                          line);
            if (++validLines >= Config::GPS_BAUD_DIAGNOSTIC_REQUIRED_LINES) {
              Serial.printf("[GPS-DIAG] detected %lu bps\n",
                            static_cast<unsigned long>(baud));
              return baud;
            }
          }
          length = 0;
        } else if (c != '\r') {
          if (length < sizeof(line) - 1) line[length++] = c;
          else length = 0;
        }
      }
      delay(1); // setup-time scan only; lets the watchdog and USB serial run.
    }
  }

  Serial.printf("[GPS-DIAG] no valid NMEA found; falling back to %lu bps\n",
                static_cast<unsigned long>(Board::GPS_BAUD));
  return Board::GPS_BAUD;
}

void SmartCaneApp::update() {
  // Work is performed by FreeRTOS tasks.  Keep Arduino's loop task idle so it
  // cannot accidentally become a second owner of a sensor or GPIO.
  vTaskDelay(pdMS_TO_TICKS(1000));
}

void SmartCaneApp::sensorTaskThunk(void *context) {
  static_cast<SmartCaneApp *>(context)->sensorTask();
}
void SmartCaneApp::decisionTaskThunk(void *context) {
  static_cast<SmartCaneApp *>(context)->decisionTask();
}
void SmartCaneApp::actuatorTaskThunk(void *context) {
  static_cast<SmartCaneApp *>(context)->actuatorTask();
}
void SmartCaneApp::networkTaskThunk(void *context) {
  static_cast<SmartCaneApp *>(context)->networkTask();
}
void SmartCaneApp::telemetryTaskThunk(void *context) {
  static_cast<SmartCaneApp *>(context)->telemetryTask();
}

void SmartCaneApp::sensorTask() {
  TickType_t lastWake = xTaskGetTickCount();
  for (;;) {
    const uint32_t nowMs = millis();
    updateSensors(nowMs);
    processButton(nowMs);
    xQueueOverwrite(sensorQueue_, &sensors_); // latest snapshot wins
    vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(Config::SENSOR_TASK_PERIOD_MS));
  }
}

void SmartCaneApp::decisionTask() {
  TickType_t lastWake = xTaskGetTickCount();
  SensorSnapshot current{};
  for (;;) {
    const uint32_t nowMs = millis();
    SensorSnapshot received;
    while (xQueueReceive(sensorQueue_, &received, 0) == pdPASS) current = received;
    processCommands();
    if (current.imu.valid) {
      fallDetector_.update(current.imu, nowMs);
      if (fallDetector_.takeDetected()) alarmController_.triggerSuspectedFall(nowMs);
    } else {
      // Invalid IMU data must never be interpreted as a stationary fall.
      fallDetector_.update(current.imu, nowMs);
    }
    const ActuatorIntent intent = alarmController_.update(current, nowMs);
    xQueueOverwrite(actuatorQueue_, &intent);
    network_.setIncidentActive(intent.incidentActive);
    publishDecision(intent);
    queueImuDebugRecord(current, intent);
    vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(Config::DECISION_TASK_PERIOD_MS));
  }
}

void SmartCaneApp::actuatorTask() {
  TickType_t lastWake = xTaskGetTickCount();
  ActuatorIntent intent;
  for (;;) {
    ActuatorIntent received;
    if (xQueueReceive(actuatorQueue_, &received, 0) == pdPASS) intent = received;
    outputs_.setBuzzer(intent.buzzerOn);
    outputs_.setLight(intent.lightOn);
    updateDisplay(readPublished(), millis());
    vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(Config::ACTUATOR_TASK_PERIOD_MS));
  }
}

void SmartCaneApp::networkTask() {
  TickType_t lastWake = xTaskGetTickCount();
  for (;;) {
    const uint32_t nowMs = millis();
    network_.update(nowMs);
    publishNetworkState();
    const PublishedState state = readPublished();
    mqttRemote_.update(nowMs, state.sensors, state.alarm, state.apMode,
                       state.rssi);
    publishMqttState();
    vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(Config::NETWORK_TASK_PERIOD_MS));
  }
}

void SmartCaneApp::telemetryTask() {
  TickType_t lastWake = xTaskGetTickCount();
  for (;;) {
    const uint32_t nowMs = millis();
    serialTelemetry_.update(nowMs);
    updateImuDebugStream();
    updatePpgDebugStream();
    logStatus(nowMs);
    vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(Config::TELEMETRY_TASK_PERIOD_MS));
  }
}

void SmartCaneApp::updateSensors(uint32_t nowMs) {
  imu_.update(nowMs);
  ImuReading imuReading;
  if (imu_.takeReading(imuReading)) sensors_.imu = imuReading;

  gps_.update(nowMs);
  GpsReading gpsReading;
  if (gps_.takeReading(gpsReading)) {
    sensors_.gps = gpsReading;
    // Do not let an invalid RMC/GGA overwrite the last known good position.
    // This lives in RAM for the current power-on session and is exposed to the
    // web page only as a fall-back while GNSS is searching for satellites.
    if (gpsReading.valid && isfinite(gpsReading.latitude) &&
        isfinite(gpsReading.longitude)) {
      sensors_.lastValidGps = gpsReading;
      sensors_.lastValidGpsAvailable = true;
    }
  }

  // In the current bench profile MAX30102 shares Wire/GPIO41-42 with BH1750;
  // the same-address ultrasonic sensor is disabled. All accesses happen only
  // in SensorTask, preserving single-task sensor ownership.
  if (Config::MAX30102_ENABLED) {
    if (!max30102_.online() &&
        nowMs - lastMax30102ProbeMs_ >= Config::MAX30102_RETRY_MS) {
      lastMax30102ProbeMs_ = nowMs;
      TwoWire &maxWire = Config::MAX30102_USE_PRIMARY_I2C ? Wire : max30102Wire_;
      const bool maxReady = max30102_.begin(maxWire,
                                            Config::MAX30102_I2C_ADDRESS,
                                            Config::MAX30102_LED_CURRENT);
      vitalsProcessor_.setSensorOnline(maxReady, nowMs);
      Serial.printf("[MAX30102] retry: %s\n", maxReady ? "online" : "not found");
    }

    if (max30102_.online()) {
      vitalsProcessor_.setSensorOnline(true, nowMs);
      uint8_t samplesToRead = max30102_.availableSamples();
      if (samplesToRead > Config::MAX30102_MAX_FIFO_SAMPLES_PER_UPDATE)
        samplesToRead = Config::MAX30102_MAX_FIFO_SAMPLES_PER_UPDATE;
      constexpr uint32_t fifoSampleRateHz =
          Config::MAX30102_SAMPLE_RATE_HZ / Max30102::FIFO_AVERAGE_SAMPLES;
      static_assert(fifoSampleRateHz > 0,
                    "MAX30102 effective FIFO sample rate must be nonzero");
      const uint32_t samplePeriodMs = 1000U / fifoSampleRateHz;
      const uint32_t sampleOffsetMs = samplesToRead > 0
          ? static_cast<uint32_t>(samplesToRead - 1U) * samplePeriodMs : 0;
      uint32_t sampleAtMs = nowMs > sampleOffsetMs ? nowMs - sampleOffsetMs : 0;
      Max30102Sample sample;
      for (uint8_t index = 0; index < samplesToRead; ++index) {
        if (!max30102_.readSample(sample)) break;
        vitalsProcessor_.update(sample, sampleAtMs);
        queuePpgDebugRecord(sample, sampleAtMs, max30102_.lastOverflow());
        sampleAtMs += samplePeriodMs;
      }
    }
    if (!max30102_.online()) vitalsProcessor_.setSensorOnline(false, nowMs);
    sensors_.vitals = vitalsProcessor_.reading();
  }

  if (xSemaphoreTake(i2cMutex_, pdMS_TO_TICKS(20)) == pdTRUE) {
    if (Config::SONAR_ENABLED) {
      sonar_.update(nowMs);
      float distanceCm;
      uint32_t distanceAt;
      if (sonar_.takeReading(distanceCm, distanceAt)) {
        sensors_.distanceCm = distanceCm;
        sensors_.distanceUpdatedAtMs = distanceAt;
        sensors_.distanceValid = true;
      }
      if (lastSonarStartMs_ == 0 ||
          nowMs - lastSonarStartMs_ >= Config::SONAR_INTERVAL_MS) {
        sonar_.startMeasurement(nowMs);
        lastSonarStartMs_ = nowMs;
      }
    }
    if (lastLightReadMs_ == 0 ||
        nowMs - lastLightReadMs_ >= Config::LIGHT_INTERVAL_MS) {
      float lux;
      if (lightSensor_.readLux(lux)) {
        sensors_.lux = lux;
        sensors_.luxUpdatedAtMs = nowMs;
        sensors_.luxValid = true;
      }
      lastLightReadMs_ = nowMs;
    }
    xSemaphoreGive(i2cMutex_);
  }
  if (sensors_.distanceValid &&
      nowMs - sensors_.distanceUpdatedAtMs > Config::SENSOR_STALE_MS)
    sensors_.distanceValid = false;
  if (sensors_.luxValid && nowMs - sensors_.luxUpdatedAtMs > Config::SENSOR_STALE_MS)
    sensors_.luxValid = false;
  if (sensors_.vitals.sensorOnline && sensors_.vitals.updatedAtMs != 0 &&
      nowMs - sensors_.vitals.updatedAtMs > Config::MAX30102_STALE_MS) {
    sensors_.vitals.fingerPresent = false;
    sensors_.vitals.valid = false;
    sensors_.vitals.signalQuality = 0.0f;
    sensors_.vitals.heartRateBpm = NAN;
    sensors_.vitals.spo2Pct = NAN;
  }
  if (!imu_.online(nowMs, Config::SENSOR_STALE_MS)) sensors_.imu.valid = false;
  if (!gps_.online(nowMs, Config::GPS_STALE_MS)) sensors_.gps.valid = false;

  // Rhythm screening remains inside SensorTask and consumes only the PPG
  // features emitted by VitalsProcessor.  It deliberately has no path into
  // AlarmController, so a health-screening result cannot trigger SOS/FALL.
  RhythmFeatures rhythmFeatures = vitalsProcessor_.rhythmFeatures(nowMs);
  if (!sensors_.vitals.sensorOnline) rhythmFeatures.sensorOnline = false;
  if (!sensors_.vitals.fingerPresent) {
    rhythmFeatures.fingerPresent = false;
    rhythmFeatures.ppgValid = false;
    rhythmFeatures.ready = false;
  }
  rhythmClassifier_.update(rhythmFeatures, sensors_.imu, nowMs);
  sensors_.vitals.rhythm = rhythmClassifier_.reading();
}

void SmartCaneApp::processButton(uint32_t nowMs) {
  sosButton_.update(nowMs);
  // The physical SOS button is an edge-triggered toggle.  Acting only on the
  // debounced press event means holding the button cannot repeatedly enqueue
  // commands, and releasing it has no effect.
  if (!sosButton_.takePressed() || !commandQueue_) return;

  const PublishedState state = readPublished();
  if (state.sosLatched || state.suspectedFall || state.fallLatched) {
    const ControlCommand command{CommandKind::Cancel, 1};
    xQueueSend(commandQueue_, &command, 0);
    Serial.println("[Button] pressed: alarm clear requested");
  } else {
    const ControlCommand command{CommandKind::Sos, 1};
    xQueueSend(commandQueue_, &command, 0);
    Serial.println("[Button] pressed: SOS requested");
  }
}

void SmartCaneApp::processCommands() {
  ControlCommand command{};
  while (commandQueue_ && xQueueReceive(commandQueue_, &command, 0) == pdPASS) {
    switch (command.kind) {
    case CommandKind::Sos: alarmController_.triggerSos(); break;
    case CommandKind::Cancel:
      alarmController_.cancelLatchedAlarms();
      fallDetector_.cancelAndCooldown(millis());
      break;
    case CommandKind::Light: alarmController_.setManualLight(command.value); break;
    case CommandKind::ImuStream:
      imuDebugStreamEnabled_ = command.value > 0;
      if (imuDebugStreamEnabled_) ppgDebugStreamEnabled_ = false;
      lastImuDebugSampleAtMs_ = 0;
      imuDebugSequence_ = 0;
      break;
    case CommandKind::PpgStream:
      ppgDebugStreamEnabled_ = command.value > 0;
      if (ppgDebugStreamEnabled_) imuDebugStreamEnabled_ = false;
      ppgDebugSequence_ = 0;
      break;
    }
  }
}

void SmartCaneApp::queueImuDebugRecord(const SensorSnapshot &current,
                                       const ActuatorIntent &intent) {
  if (!imuDebugStreamEnabled_ || !imuDebugQueue_ || !current.imu.valid ||
      current.imu.updatedAtMs == 0 ||
      current.imu.updatedAtMs == lastImuDebugSampleAtMs_) return;
  lastImuDebugSampleAtMs_ = current.imu.updatedAtMs;

  const FallDetector::Diagnostics diagnostics = fallDetector_.diagnostics();
  ImuDebugRecord record;
  record.sequence = ++imuDebugSequence_;
  record.sampleAtMs = current.imu.updatedAtMs;
  record.imu = current.imu;
  record.accelerationG = diagnostics.accelerationG;
  record.gyroDps = diagnostics.gyroDps;
  record.tiltDeg = diagnostics.tiltDeg;
  record.phase = diagnostics.phase;
  record.freeFall = diagnostics.freeFall;
  record.impact = diagnostics.impact;
  record.tiltedAndStill = diagnostics.tiltedAndStill;
  record.alarm = intent.alarm;
  record.suspectedFall = intent.suspectedFall;
  record.fallLatched = intent.fallLatched;
  // A full queue deliberately drops this record. sequence has already advanced,
  // allowing the Qt host to report the exact number of missing records.
  xQueueSend(imuDebugQueue_, &record, 0);
}

void SmartCaneApp::updateImuDebugStream() {
  if (!imuDebugQueue_) return;
  const bool enabled = imuDebugStreamEnabled_;
  if (enabled != imuDebugWriterActive_) {
    xQueueReset(imuDebugQueue_);
    imuDebugWriterActive_ = enabled;
    if (enabled) serialTelemetry_.sendImuHeader();
  }
  if (!enabled) return;

  ImuDebugRecord record;
  char csv[320];
  while (xQueueReceive(imuDebugQueue_, &record, 0) == pdPASS) {
    snprintf(csv, sizeof(csv),
             "%lu,%lu,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,"
             "%.4f,%.2f,%.2f,%s,%u,%u,%u,%s,%u,%u",
             static_cast<unsigned long>(record.sequence),
             static_cast<unsigned long>(record.sampleAtMs),
             record.imu.axG, record.imu.ayG, record.imu.azG,
             record.imu.gyroX, record.imu.gyroY, record.imu.gyroZ,
             record.imu.rollDeg, record.imu.pitchDeg, record.imu.yawDeg,
             record.accelerationG, record.gyroDps, record.tiltDeg,
             FallDetector::phaseName(record.phase), record.freeFall ? 1U : 0U,
             record.impact ? 1U : 0U, record.tiltedAndStill ? 1U : 0U,
             alarmName(record.alarm), record.suspectedFall ? 1U : 0U,
             record.fallLatched ? 1U : 0U);
    serialTelemetry_.sendImuCsv(csv);
  }
}

void SmartCaneApp::queuePpgDebugRecord(const Max30102Sample &sample,
                                       uint32_t sampleAtMs,
                                       uint8_t fifoOverflow) {
  if (!ppgDebugStreamEnabled_ || !ppgDebugQueue_) return;
  const PpgProcessingDebug &debug = vitalsProcessor_.debugReading();
  const VitalsReading &vitals = vitalsProcessor_.reading();
  PpgDebugRecord record;
  record.sequence = ++ppgDebugSequence_;
  record.sampleAtMs = sampleAtMs;
  record.red = sample.red;
  record.ir = sample.ir;
  record.redDc = debug.redDc;
  record.irDc = debug.irDc;
  record.redAc = debug.redAc;
  record.irAc = debug.irAc;
  record.filteredIr = debug.filteredIr;
  record.envelope = debug.envelope;
  record.ibiMs = debug.ibiMs;
  record.signalQuality = vitals.signalQuality;
  record.heartRateBpm = vitals.heartRateBpm;
  record.spo2Pct = vitals.spo2Pct;
  record.fifoOverflow = fifoOverflow;
  record.peakCandidate = debug.peakCandidate;
  record.beatAccepted = debug.beatAccepted;
  record.fingerPresent = vitals.fingerPresent;
  record.valid = vitals.valid;
  // Sequence advances even on a full queue, so the host can count every loss.
  xQueueSend(ppgDebugQueue_, &record, 0);
}

void SmartCaneApp::updatePpgDebugStream() {
  if (!ppgDebugQueue_) return;
  const bool enabled = ppgDebugStreamEnabled_;
  if (enabled != ppgDebugWriterActive_) {
    xQueueReset(ppgDebugQueue_);
    ppgDebugWriterActive_ = enabled;
    if (enabled) serialTelemetry_.sendPpgHeader();
  }
  if (!enabled) return;

  PpgDebugRecord record;
  char csv[320];
  while (xQueueReceive(ppgDebugQueue_, &record, 0) == pdPASS) {
    snprintf(csv, sizeof(csv),
             "%lu,%lu,%lu,%lu,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%u,%u,"
             "%.2f,%u,%.4f,%.2f,%.2f,%u,%u",
             static_cast<unsigned long>(record.sequence),
             static_cast<unsigned long>(record.sampleAtMs),
             static_cast<unsigned long>(record.red),
             static_cast<unsigned long>(record.ir), record.redDc, record.irDc,
             record.redAc, record.irAc, record.filteredIr, record.envelope,
             record.peakCandidate ? 1U : 0U,
             record.beatAccepted ? 1U : 0U, record.ibiMs,
             record.fingerPresent ? 1U : 0U, record.signalQuality,
             record.heartRateBpm, record.spo2Pct, record.valid ? 1U : 0U,
             static_cast<unsigned int>(record.fifoOverflow));
    serialTelemetry_.sendPpgCsv(csv);
  }
}

void SmartCaneApp::updateDisplay(const PublishedState &state, uint32_t nowMs) {
  if (!oled_.online() || nowMs - lastDisplayMs_ < Config::DISPLAY_INTERVAL_MS) return;
  if (xSemaphoreTake(i2cMutex_, 0) != pdTRUE) return;
  lastDisplayMs_ = nowMs;
  char line[24];
  oled_.clear();
  const char *displayAlarm = state.alarm == AlarmKind::SuspectedFall
                                 ? "CHECK FALL" : alarmName(state.alarm);
  oled_.drawText(0, 0, displayAlarm, 2);
  if (state.sensors.distanceValid) snprintf(line, sizeof(line), "D:%.1FCM", state.sensors.distanceCm);
  else strcpy(line, "D:--.-CM");
  oled_.drawText(0, 18, line);
  if (state.sensors.luxValid) snprintf(line, sizeof(line), "L:%.0FLX", state.sensors.lux);
  else strcpy(line, "L:---LX");
  oled_.drawText(0, 29, line);
  snprintf(line, sizeof(line), "GPS:%s S:%02u", state.sensors.gps.valid ? "OK" : "NO",
           state.sensors.gps.satellites);
  oled_.drawText(0, 40, line);
  snprintf(line, sizeof(line), "IP:%s", state.ip);
  oled_.drawText(0, 51, line);
  oled_.display();
  xSemaphoreGive(i2cMutex_);
}

void SmartCaneApp::publishDecision(const ActuatorIntent &intent) {
  if (xSemaphoreTake(stateMutex_, pdMS_TO_TICKS(10)) != pdTRUE) return;
  published_.sensors = intent.sensors;
  published_.alarm = intent.alarm;
  published_.buzzerOn = intent.buzzerOn;
  published_.lightOn = intent.lightOn;
  published_.sosLatched = intent.sosLatched;
  published_.suspectedFall = intent.suspectedFall;
  published_.fallLatched = intent.fallLatched;
  published_.manualLightMode = intent.manualLightMode;
  xSemaphoreGive(stateMutex_);
}

void SmartCaneApp::publishNetworkState() {
  if (xSemaphoreTake(stateMutex_, pdMS_TO_TICKS(10)) != pdTRUE) return;
  published_.cameraReady = network_.cameraReady();
  published_.apMode = network_.apMode();
  published_.rssi = network_.rssi();
  const String ip = network_.ipAddress();
  strlcpy(published_.ip, ip.c_str(), sizeof(published_.ip));
  xSemaphoreGive(stateMutex_);
}

void SmartCaneApp::publishMqttState() {
  const MqttRemoteService::Status mqtt = mqttRemote_.status();
  if (xSemaphoreTake(stateMutex_, pdMS_TO_TICKS(10)) != pdTRUE) return;
  published_.mqttEnabled = mqtt.enabled;
  published_.mqttConnected = mqtt.connected;
  strlcpy(published_.mqttState, MqttRemoteService::stateName(mqtt.state),
          sizeof(published_.mqttState));
  published_.mqttLastPublishAtMs = mqtt.lastPublishAtMs;
  xSemaphoreGive(stateMutex_);
}

SmartCaneApp::PublishedState SmartCaneApp::readPublished() const {
  PublishedState result;
  if (stateMutex_ && xSemaphoreTake(stateMutex_, pdMS_TO_TICKS(10)) == pdTRUE) {
    result = published_;
    xSemaphoreGive(stateMutex_);
  }
  return result;
}

String SmartCaneApp::buildJson() const {
  const PublishedState p = readPublished();
  String json;
  json.reserve(2400);
  json += "{\"protocol\":\"smartcane.telemetry\",\"version\":1";
  json += ",\"uptime_ms\":"; json += static_cast<unsigned long>(millis());
  json += ",\"alarm\":\""; json += alarmName(p.alarm); json += "\"";
  json += ",\"distance_cm\":"; appendJsonNumber(json, p.sensors.distanceCm, 1, p.sensors.distanceValid);
  json += ",\"lux\":"; appendJsonNumber(json, p.sensors.lux, 1, p.sensors.luxValid);
  json += ",\"buzzer\":"; json += p.buzzerOn ? "true" : "false";
  json += ",\"light\":"; json += p.lightOn ? "true" : "false";
  json += ",\"light_mode\":"; json += static_cast<int>(p.manualLightMode);
  json += ",\"sos_latched\":"; json += p.sosLatched ? "true" : "false";
  json += ",\"fall_suspected\":"; json += p.suspectedFall ? "true" : "false";
  json += ",\"fall_latched\":"; json += p.fallLatched ? "true" : "false";
  json += ",\"ip\":\""; json += p.ip; json += "\"";
  json += ",\"ap_mode\":"; json += p.apMode ? "true" : "false";
  json += ",\"rssi\":"; json += static_cast<int>(p.rssi);
  json += ",\"camera\":"; json += p.cameraReady ? "true" : "false";
  json += ",\"camera_incident\":"; json += (p.sosLatched || p.fallLatched) ? "true" : "false";
  json += ",\"mqtt\":{\"enabled\":";
  json += p.mqttEnabled ? "true" : "false";
  json += ",\"connected\":";
  json += p.mqttConnected ? "true" : "false";
  json += ",\"state\":\"";
  json += p.mqttState;
  json += "\",\"last_publish_ms\":";
  json += static_cast<unsigned long>(p.mqttLastPublishAtMs);
  json += "}";
  json += ",\"imu\":{\"valid\":"; json += p.sensors.imu.valid ? "true" : "false";
  json += ",\"ax_g\":"; appendJsonNumber(json, p.sensors.imu.axG, 3, p.sensors.imu.valid);
  json += ",\"ay_g\":"; appendJsonNumber(json, p.sensors.imu.ayG, 3, p.sensors.imu.valid);
  json += ",\"az_g\":"; appendJsonNumber(json, p.sensors.imu.azG, 3, p.sensors.imu.valid);
  json += ",\"gyro_x_dps\":"; appendJsonNumber(json, p.sensors.imu.gyroX, 1, p.sensors.imu.valid);
  json += ",\"gyro_y_dps\":"; appendJsonNumber(json, p.sensors.imu.gyroY, 1, p.sensors.imu.valid);
  json += ",\"gyro_z_dps\":"; appendJsonNumber(json, p.sensors.imu.gyroZ, 1, p.sensors.imu.valid);
  json += ",\"roll_deg\":"; appendJsonNumber(json, p.sensors.imu.rollDeg, 1, p.sensors.imu.valid);
  json += ",\"pitch_deg\":"; appendJsonNumber(json, p.sensors.imu.pitchDeg, 1, p.sensors.imu.valid);
  json += ",\"yaw_deg\":"; appendJsonNumber(json, p.sensors.imu.yawDeg, 1, p.sensors.imu.valid);
  json += ",\"accel_g\":"; appendJsonNumber(json, p.sensors.imu.accelerationMagnitudeG(), 2, p.sensors.imu.valid);
  json += "},\"gps\":{\"valid\":"; json += p.sensors.gps.valid ? "true" : "false";
  json += ",\"lat\":"; appendJsonNumber(json, p.sensors.gps.latitude, 6, p.sensors.gps.valid);
  json += ",\"lon\":"; appendJsonNumber(json, p.sensors.gps.longitude, 6, p.sensors.gps.valid);
  json += ",\"speed_kmh\":"; appendJsonNumber(json, p.sensors.gps.speedKmh, 1, p.sensors.gps.valid);
  json += ",\"altitude_m\":"; appendJsonNumber(json, p.sensors.gps.altitudeM, 1, p.sensors.gps.valid);
  json += ",\"satellites\":"; json += static_cast<unsigned int>(p.sensors.gps.satellites);
  json += ",\"utc\":\""; json += p.sensors.gps.utc; json += "\"}";
  json += ",\"vitals\":{\"online\":";
  json += p.sensors.vitals.sensorOnline ? "true" : "false";
  json += ",\"finger\":"; json += p.sensors.vitals.fingerPresent ? "true" : "false";
  json += ",\"valid\":"; json += p.sensors.vitals.valid ? "true" : "false";
  json += ",\"signal_quality\":";
  appendJsonNumber(json, p.sensors.vitals.signalQuality, 2,
                   p.sensors.vitals.sensorOnline && p.sensors.vitals.fingerPresent);
  json += ",\"heart_rate_bpm\":";
  appendJsonNumber(json, p.sensors.vitals.heartRateBpm, 1, p.sensors.vitals.valid);
  json += ",\"spo2_pct\":";
  appendJsonNumber(json, p.sensors.vitals.spo2Pct, 1, p.sensors.vitals.valid);
  json += ",\"raw_red\":";
  json += p.sensors.vitals.sensorOnline ? p.sensors.vitals.rawRed : 0;
  json += ",\"raw_ir\":";
  json += p.sensors.vitals.sensorOnline ? p.sensors.vitals.rawIr : 0;
  json += ",\"rhythm\":{\"state\":\"";
  json += rhythmScreenName(p.sensors.vitals.rhythm.state);
  json += "\",\"model_available\":";
  json += p.sensors.vitals.rhythm.modelAvailable ? "true" : "false";
  json += ",\"model_calibrated\":";
  json += p.sensors.vitals.rhythm.modelCalibrated ? "true" : "false";
  json += ",\"valid\":";
  json += p.sensors.vitals.rhythm.valid ? "true" : "false";
  json += ",\"alert\":";
  json += p.sensors.vitals.rhythm.alertActive ? "true" : "false";
  json += ",\"confidence\":";
  appendJsonNumber(json, p.sensors.vitals.rhythm.confidence, 2,
                   p.sensors.vitals.rhythm.valid);
  json += ",\"ibi_mean_ms\":";
  appendJsonNumber(json, p.sensors.vitals.rhythm.ibiMeanMs, 1,
                   p.sensors.vitals.rhythm.valid);
  json += ",\"sdnn_ms\":";
  appendJsonNumber(json, p.sensors.vitals.rhythm.sdnnMs, 1,
                   p.sensors.vitals.rhythm.valid);
  json += ",\"rmssd_ms\":";
  appendJsonNumber(json, p.sensors.vitals.rhythm.rmssdMs, 1,
                   p.sensors.vitals.rhythm.valid);
  json += ",\"pnn50\":";
  appendJsonNumber(json, p.sensors.vitals.rhythm.pnn50, 2,
                   p.sensors.vitals.rhythm.valid);
  json += ",\"beat_count\":";
  json += static_cast<unsigned int>(p.sensors.vitals.rhythm.beatCount);
  json += ",\"inference_us\":";
  json += static_cast<unsigned long>(p.sensors.vitals.rhythm.inferenceUs);
  json += ",\"inference_count\":";
  json += static_cast<unsigned long>(p.sensors.vitals.rhythm.inferenceCount);
  json += ",\"model_bytes\":";
  json += static_cast<unsigned int>(p.sensors.vitals.rhythm.modelBytes);
  json += ",\"classifier_state_bytes\":";
  json += static_cast<unsigned int>(p.sensors.vitals.rhythm.classifierStateBytes);
  json += "}";
  json += "}";
  const bool hasLastFix = p.sensors.lastValidGpsAvailable &&
                           isfinite(p.sensors.lastValidGps.latitude) &&
                           isfinite(p.sensors.lastValidGps.longitude);
  json += ",\"last_fix\":{\"available\":"; json += hasLastFix ? "true" : "false";
  json += ",\"lat\":"; appendJsonNumber(json, p.sensors.lastValidGps.latitude, 6, hasLastFix);
  json += ",\"lon\":"; appendJsonNumber(json, p.sensors.lastValidGps.longitude, 6, hasLastFix);
  json += ",\"satellites\":"; json += static_cast<unsigned int>(p.sensors.lastValidGps.satellites);
  json += ",\"utc\":\""; json += hasLastFix ? p.sensors.lastValidGps.utc : "--:--:--";
  json += "\",\"age_ms\":";
  json += hasLastFix ? static_cast<unsigned long>(millis() - p.sensors.lastValidGps.updatedAtMs) : 0;
  json += "}}";
  return json;
}

String SmartCaneApp::jsonThunk() {
  return instance_ ? instance_->buildJson() : String("{}");
}

bool SmartCaneApp::commandThunk(const char *command, int value) {
  if (!instance_ || !instance_->commandQueue_ || !command) return false;
  ControlCommand queued{};
  if (strcmp(command, "sos") == 0) queued.kind = CommandKind::Sos;
  else if (strcmp(command, "cancel") == 0) queued.kind = CommandKind::Cancel;
  else if (strcmp(command, "light") == 0) {
    queued.kind = CommandKind::Light;
    queued.value = static_cast<int8_t>(value);
  } else if (strcmp(command, "imu_stream") == 0) {
    queued.kind = CommandKind::ImuStream;
    queued.value = value > 0 ? 1 : 0;
  } else if (strcmp(command, "ppg_stream") == 0) {
    queued.kind = CommandKind::PpgStream;
    queued.value = value > 0 ? 1 : 0;
  } else return false;
  return xQueueSend(instance_->commandQueue_, &queued, 0) == pdPASS;
}

void SmartCaneApp::logStatus(uint32_t nowMs) {
  if (nowMs - lastLogMs_ < 2000) return;
  lastLogMs_ = nowMs;
  const PublishedState p = readPublished();
  Serial.printf("[State] %s distance=%.1fcm lux=%.1f gps=%s imu=%s "
                "max30102=%s finger=%s hr=%.1f spo2=%.1f sq=%.2f rhythm=%s ip=%s\n",
                alarmName(p.alarm), p.sensors.distanceCm, p.sensors.lux,
                p.sensors.gps.valid ? "fix" : "no-fix",
                p.sensors.imu.valid ? "ok" : "offline",
                 p.sensors.vitals.sensorOnline ? "ok" : "offline",
                 p.sensors.vitals.fingerPresent ? "yes" : "no",
                 p.sensors.vitals.heartRateBpm, p.sensors.vitals.spo2Pct,
                 p.sensors.vitals.signalQuality,
                 rhythmScreenName(p.sensors.vitals.rhythm.state), p.ip);
}
