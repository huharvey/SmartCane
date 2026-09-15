#include "MqttRemoteService.h"

#include "../config/UserConfig.h"
#include <WiFi.h>
#include <ctype.h>
#include <math.h>
#include <string.h>
#include <time.h>

namespace {
void appendJsonNumber(String &json, double value, unsigned int decimals,
                      bool enabled = true) {
  if (enabled && isfinite(value)) json += String(value, decimals);
  else json += "null";
}

bool startsWith(const char *value, const char *prefix) {
  return value && prefix && strncmp(value, prefix, strlen(prefix)) == 0;
}

const GpsReading *bestGps(const SensorSnapshot &sensors, const char *&source) {
  if (sensors.gps.valid && isfinite(sensors.gps.latitude) &&
      isfinite(sensors.gps.longitude)) {
    source = "live";
    return &sensors.gps;
  }
  if (sensors.lastValidGpsAvailable && isfinite(sensors.lastValidGps.latitude) &&
      isfinite(sensors.lastValidGps.longitude)) {
    source = "last";
    return &sensors.lastValidGps;
  }
  source = "none";
  return nullptr;
}

void appendVitalsJson(String &json, const VitalsReading &vitals) {
  json += "{\"online\":";
  json += vitals.sensorOnline ? "true" : "false";
  json += ",\"finger\":";
  json += vitals.fingerPresent ? "true" : "false";
  json += ",\"valid\":";
  json += vitals.valid ? "true" : "false";
  json += ",\"signal_quality\":";
  appendJsonNumber(json, vitals.signalQuality, 2,
                   vitals.sensorOnline && vitals.fingerPresent);
  json += ",\"heart_rate_bpm\":";
  appendJsonNumber(json, vitals.heartRateBpm, 1, vitals.valid);
  json += ",\"spo2_pct\":";
  appendJsonNumber(json, vitals.spo2Pct, 1, vitals.valid);
  json += ",\"rhythm\":{\"state\":\"";
  json += rhythmScreenName(vitals.rhythm.state);
  json += "\",\"valid\":";
  json += vitals.rhythm.valid ? "true" : "false";
  json += ",\"alert\":";
  json += vitals.rhythm.alertActive ? "true" : "false";
  json += ",\"model_calibrated\":";
  json += vitals.rhythm.modelCalibrated ? "true" : "false";
  json += ",\"confidence\":";
  appendJsonNumber(json, vitals.rhythm.confidence, 2, vitals.rhythm.valid);
  json += ",\"inference_us\":";
  json += static_cast<unsigned long>(vitals.rhythm.inferenceUs);
  json += ",\"model_bytes\":";
  json += static_cast<unsigned int>(vitals.rhythm.modelBytes);
  json += ",\"classifier_state_bytes\":";
  json += static_cast<unsigned int>(vitals.rhythm.classifierStateBytes);
  json += "}}";
}

void appendGpsJson(String &json, const SensorSnapshot &sensors) {
  const char *source = nullptr;
  const GpsReading *gps = bestGps(sensors, source);
  json += "{\"source\":\"";
  json += source;
  json += "\",\"valid\":";
  json += gps ? "true" : "false";
  json += ",\"lat\":";
  appendJsonNumber(json, gps ? gps->latitude : NAN, 6, gps != nullptr);
  json += ",\"lon\":";
  appendJsonNumber(json, gps ? gps->longitude : NAN, 6, gps != nullptr);
  json += ",\"satellites\":";
  json += gps ? static_cast<unsigned int>(gps->satellites) : 0;
  json += "}";
}
} // namespace

const char *MqttRemoteService::eventName(EventKind kind) {
  switch (kind) {
  case EventKind::SuspectedFall: return "SUSPECTED_FALL";
  case EventKind::Fall: return "FALL";
  case EventKind::Sos: return "SOS";
  case EventKind::RhythmScreeningAlert: return "RHYTHM_SCREENING_ALERT";
  default: return "EVENT";
  }
}

void MqttRemoteService::begin(CommandHandler commandHandler) {
  commandHandler_ = commandHandler;
  state_ = Config::MQTT_ENABLED ? State::WaitingWifi : State::Disabled;
}

MqttRemoteService::Status MqttRemoteService::status() const {
  Status value;
  value.enabled = Config::MQTT_ENABLED;
  value.connected = connected_;
  value.state = state_;
  value.lastPublishAtMs = lastPublishAtMs_;
  return value;
}

const char *MqttRemoteService::stateName(State state) {
  switch (state) {
  case State::Disabled: return "DISABLED";
  case State::ConfigError: return "CONFIG_ERROR";
  case State::WaitingWifi: return "WAIT_WIFI";
  case State::WaitingTime: return "WAIT_TIME";
  case State::Connecting: return "CONNECTING";
  case State::Online: return "ONLINE";
  case State::Error: return "ERROR";
  default: return "ERROR";
  }
}

bool MqttRemoteService::usesTls() const {
  return startsWith(Config::MQTT_URI, "mqtts://");
}

bool MqttRemoteService::validConfiguration() const {
  if (Config::MQTT_URI[0] == '\0' || Config::MQTT_DEVICE_ID[0] == '\0' ||
      Config::MQTT_TOPIC_ROOT[0] == '\0') {
    return false;
  }
  if (usesTls()) return Config::MQTT_ROOT_CA[0] != '\0';
  return startsWith(Config::MQTT_URI, "mqtt://") &&
         Config::MQTT_ALLOW_INSECURE_TEST;
}

bool MqttRemoteService::timeIsValid() const {
  return static_cast<uint32_t>(time(nullptr)) >= Config::MQTT_MIN_VALID_EPOCH;
}

void MqttRemoteService::requestTime(uint32_t nowMs) {
  if (lastNtpRequestMs_ != 0 &&
      nowMs - lastNtpRequestMs_ < Config::MQTT_NTP_RETRY_INTERVAL_MS) {
    return;
  }
  lastNtpRequestMs_ = nowMs;
  configTime(Config::MQTT_TIMEZONE_OFFSET_SECONDS, 0, Config::MQTT_NTP_SERVER_1,
             Config::MQTT_NTP_SERVER_2);
  Serial.println("[MQTT] waiting for NTP time before TLS connection");
}

void MqttRemoteService::makeTopics() {
  const uint64_t chipMac = ESP.getEfuseMac();
  snprintf(clientId_, sizeof(clientId_), "%s-%06llX", Config::MQTT_DEVICE_ID,
           static_cast<unsigned long long>(chipMac & 0xFFFFFFULL));
  const String base = String(Config::MQTT_TOPIC_ROOT) + "/" +
                      Config::MQTT_DEVICE_ID + "/";
  strlcpy(telemetryTopic_, (base + "telemetry").c_str(), sizeof(telemetryTopic_));
  strlcpy(vitalsTopic_, (base + "vitals").c_str(), sizeof(vitalsTopic_));
  strlcpy(gpsTopic_, (base + "gps").c_str(), sizeof(gpsTopic_));
  strlcpy(eventTopic_, (base + "event").c_str(), sizeof(eventTopic_));
  strlcpy(presenceTopic_, (base + "presence").c_str(), sizeof(presenceTopic_));
  strlcpy(commandTopic_, (base + "command").c_str(), sizeof(commandTopic_));
}

bool MqttRemoteService::ensureClient(uint32_t nowMs) {
  if (client_) return true;
  makeTopics();
  esp_mqtt_client_config_t config{};
  config.uri = Config::MQTT_URI;
  config.event_handle = eventThunk;
  config.user_context = this;
  config.client_id = clientId_;
  config.username = Config::MQTT_USERNAME[0] ? Config::MQTT_USERNAME : nullptr;
  config.password = Config::MQTT_PASSWORD[0] ? Config::MQTT_PASSWORD : nullptr;
  config.lwt_topic = presenceTopic_;
  config.lwt_msg = "offline";
  config.lwt_qos = 1;
  config.lwt_retain = 1;
  config.keepalive = 30;
  config.reconnect_timeout_ms = Config::MQTT_RETRY_INTERVAL_MS;
  config.buffer_size = Config::MQTT_PACKET_BUFFER_BYTES;
  config.out_buffer_size = Config::MQTT_PACKET_BUFFER_BYTES;
  config.network_timeout_ms = 5000;
  config.disable_auto_reconnect = false;
  config.cert_pem = usesTls() ? Config::MQTT_ROOT_CA : nullptr;
  client_ = esp_mqtt_client_init(&config);
  if (!client_) {
    state_ = State::Error;
    lastStartAttemptMs_ = nowMs;
    Serial.println("[MQTT] client allocation failed");
    return false;
  }
  return true;
}

void MqttRemoteService::startClient(uint32_t nowMs) {
  if (!client_ || clientRunning_) return;
  if (lastStartAttemptMs_ != 0 &&
      nowMs - lastStartAttemptMs_ < Config::MQTT_RETRY_INTERVAL_MS) {
    return;
  }
  lastStartAttemptMs_ = nowMs;
  const esp_err_t result = esp_mqtt_client_start(client_);
  if (result == ESP_OK) {
    clientRunning_ = true;
    state_ = State::Connecting;
    Serial.printf("[MQTT] connecting to %s\n", Config::MQTT_URI);
  } else {
    state_ = State::Error;
    Serial.printf("[MQTT] start failed: 0x%X\n", static_cast<unsigned>(result));
  }
}

void MqttRemoteService::stopClient() {
  if (connected_) publishPresence(false);
  connected_ = false;
  announcePresence_ = false;
  if (client_ && clientRunning_) {
    esp_mqtt_client_stop(client_);
    clientRunning_ = false;
  }
}

void MqttRemoteService::enqueueEvent(EventKind kind,
                                     const SensorSnapshot &sensors,
                                     uint32_t nowMs) {
  if (eventCount_ == EVENT_QUEUE_SIZE) {
    eventHead_ = (eventHead_ + 1) % EVENT_QUEUE_SIZE;
    --eventCount_;
  }
  PendingEvent &event = pendingEvents_[eventTail_];
  event.kind = kind;
  event.sensors = sensors;
  event.occurredAtMs = nowMs;
  eventTail_ = (eventTail_ + 1) % EVENT_QUEUE_SIZE;
  ++eventCount_;
}

void MqttRemoteService::captureTransitions(const SensorSnapshot &sensors,
                                           AlarmKind alarm, uint32_t nowMs) {
  if (!observedState_) {
    observedState_ = true;
    previousAlarm_ = alarm;
    previousRhythmAlert_ = sensors.vitals.rhythm.alertActive;
    if (alarm == AlarmKind::SuspectedFall) {
      enqueueEvent(EventKind::SuspectedFall, sensors, nowMs);
    } else if (alarm == AlarmKind::Fall) {
      enqueueEvent(EventKind::Fall, sensors, nowMs);
    } else if (alarm == AlarmKind::Sos) {
      enqueueEvent(EventKind::Sos, sensors, nowMs);
    }
    if (previousRhythmAlert_)
      enqueueEvent(EventKind::RhythmScreeningAlert, sensors, nowMs);
    return;
  }
  if (alarm != previousAlarm_) {
    if (alarm == AlarmKind::SuspectedFall) {
      enqueueEvent(EventKind::SuspectedFall, sensors, nowMs);
    } else if (alarm == AlarmKind::Fall) {
      enqueueEvent(EventKind::Fall, sensors, nowMs);
    } else if (alarm == AlarmKind::Sos) {
      enqueueEvent(EventKind::Sos, sensors, nowMs);
    }
    previousAlarm_ = alarm;
  }
  if (sensors.vitals.rhythm.alertActive && !previousRhythmAlert_)
    enqueueEvent(EventKind::RhythmScreeningAlert, sensors, nowMs);
  previousRhythmAlert_ = sensors.vitals.rhythm.alertActive;
}

bool MqttRemoteService::publish(const char *topic, const String &payload,
                                int qos, bool retain) {
  if (!client_ || !connected_ || !topic) return false;
  return esp_mqtt_client_publish(client_, topic, payload.c_str(), payload.length(),
                                  qos, retain ? 1 : 0) >= 0;
}

bool MqttRemoteService::publishPresence(bool online) {
  const String payload = online ? "online" : "offline";
  return publish(presenceTopic_, payload, 1, true);
}

bool MqttRemoteService::publishStatus(const SensorSnapshot &sensors,
                                      AlarmKind alarm, int8_t rssi,
                                      uint32_t nowMs) {
  String payload;
  payload.reserve(480);
  payload += "{\"protocol\":\"smartcane.mqtt\",\"version\":1,\"online\":true";
  payload += ",\"uptime_ms\":";
  payload += static_cast<unsigned long>(nowMs);
  payload += ",\"alarm\":\"";
  payload += alarmName(alarm);
  payload += "\",\"imu_online\":";
  payload += sensors.imu.valid ? "true" : "false";
  payload += ",\"max30102_online\":";
  payload += sensors.vitals.sensorOnline ? "true" : "false";
  payload += ",\"sonar_online\":";
  payload += sensors.sonarOnline ? "true" : "false";
  payload += ",\"distance_cm\":";
  appendJsonNumber(payload, sensors.distanceCm, 1, sensors.distanceValid);
  payload += ",\"light_sensor_online\":";
  payload += sensors.lightSensorOnline ? "true" : "false";
  payload += ",\"lux\":";
  appendJsonNumber(payload, sensors.lux, 1, sensors.luxValid);
  payload += ",\"rssi\":";
  payload += static_cast<int>(rssi);
  payload += "}";
  return publish(telemetryTopic_, payload, 0, false);
}

bool MqttRemoteService::publishVitals(const SensorSnapshot &sensors,
                                      uint32_t nowMs) {
  String payload;
  payload.reserve(520);
  payload += "{\"uptime_ms\":";
  payload += static_cast<unsigned long>(nowMs);
  payload += ",\"vitals\":";
  appendVitalsJson(payload, sensors.vitals);
  payload += "}";
  return publish(vitalsTopic_, payload, 0, false);
}

bool MqttRemoteService::publishGps(const SensorSnapshot &sensors,
                                   uint32_t nowMs) {
  String payload;
  payload.reserve(300);
  payload += "{\"uptime_ms\":";
  payload += static_cast<unsigned long>(nowMs);
  payload += ",\"gps\":";
  appendGpsJson(payload, sensors);
  payload += "}";
  return publish(gpsTopic_, payload, 0, false);
}

bool MqttRemoteService::publishNextEvent(uint32_t nowMs) {
  if (eventCount_ == 0 ||
      (lastEventAttemptMs_ != 0 && nowMs - lastEventAttemptMs_ < 1000)) {
    return false;
  }
  lastEventAttemptMs_ = nowMs;
  const PendingEvent &event = pendingEvents_[eventHead_];
  String payload;
  payload.reserve(760);
  payload += "{\"event\":\"";
  payload += eventName(event.kind);
  payload += "\",\"event_uptime_ms\":";
  payload += static_cast<unsigned long>(event.occurredAtMs);
  payload += ",\"vitals\":";
  appendVitalsJson(payload, event.sensors.vitals);
  payload += ",\"gps\":";
  appendGpsJson(payload, event.sensors);
  payload += "}";
  if (!publish(eventTopic_, payload, 1, false)) return false;
  eventHead_ = (eventHead_ + 1) % EVENT_QUEUE_SIZE;
  --eventCount_;
  return true;
}

void MqttRemoteService::handleCommandData(const esp_mqtt_event_handle_t event) {
  if (!Config::MQTT_ALLOW_REMOTE_COMMANDS || !commandHandler_ || !event->topic ||
      !event->data || event->current_data_offset != 0 ||
      event->data_len != event->total_data_len || event->data_len <= 0 ||
      event->data_len > 63 || event->topic_len != static_cast<int>(strlen(commandTopic_)) ||
      strncmp(event->topic, commandTopic_, event->topic_len) != 0) {
    return;
  }
  char command[64]{};
  memcpy(command, event->data, event->data_len);
  command[event->data_len] = '\0';
  for (char *cursor = command; *cursor; ++cursor)
    *cursor = static_cast<char>(tolower(static_cast<unsigned char>(*cursor)));

  bool accepted = false;
  if (strcmp(command, "sos") == 0) accepted = commandHandler_("sos", 1);
  else if (strcmp(command, "cancel") == 0) accepted = commandHandler_("cancel", 1);
  else if (strcmp(command, "light:on") == 0) accepted = commandHandler_("light", 1);
  else if (strcmp(command, "light:off") == 0) accepted = commandHandler_("light", 0);
  else if (strcmp(command, "light:auto") == 0) accepted = commandHandler_("light", -1);
  if (accepted) Serial.printf("[MQTT] remote command accepted: %s\n", command);
  else Serial.printf("[MQTT] remote command rejected: %s\n", command);
}

esp_err_t MqttRemoteService::eventThunk(esp_mqtt_event_handle_t event) {
  if (!event || !event->user_context) return ESP_OK;
  return static_cast<MqttRemoteService *>(event->user_context)->handleEvent(event);
}

esp_err_t MqttRemoteService::handleEvent(esp_mqtt_event_handle_t event) {
  switch (event->event_id) {
  case MQTT_EVENT_CONNECTED:
    connected_ = true;
    announcePresence_ = true;
    state_ = State::Online;
    if (Config::MQTT_ALLOW_REMOTE_COMMANDS && client_) {
      esp_mqtt_client_subscribe(client_, commandTopic_, 1);
    }
    Serial.println("[MQTT] connected");
    break;
  case MQTT_EVENT_DISCONNECTED:
    connected_ = false;
    state_ = State::Connecting;
    Serial.println("[MQTT] disconnected; auto-reconnect pending");
    break;
  case MQTT_EVENT_DATA:
    handleCommandData(event);
    break;
  case MQTT_EVENT_ERROR:
    state_ = State::Error;
    Serial.println("[MQTT] transport or broker error");
    break;
  default:
    break;
  }
  return ESP_OK;
}

void MqttRemoteService::update(uint32_t nowMs, const SensorSnapshot &sensors,
                               AlarmKind alarm, bool apMode, int8_t rssi) {
  captureTransitions(sensors, alarm, nowMs);
  if (!Config::MQTT_ENABLED) {
    stopClient();
    state_ = State::Disabled;
    return;
  }
  if (!validConfiguration()) {
    stopClient();
    state_ = State::ConfigError;
    return;
  }
  if (apMode || WiFi.status() != WL_CONNECTED) {
    stopClient();
    state_ = State::WaitingWifi;
    return;
  }
  if (usesTls() && !timeIsValid()) {
    requestTime(nowMs);
    state_ = State::WaitingTime;
    return;
  }
  if (!ensureClient(nowMs)) return;
  startClient(nowMs);
  if (!connected_) {
    if (state_ != State::Error) state_ = State::Connecting;
    return;
  }

  state_ = State::Online;
  if (announcePresence_) {
    if (publishPresence(true)) announcePresence_ = false;
  }
  if (lastStatusPublishMs_ == 0 ||
      nowMs - lastStatusPublishMs_ >= Config::MQTT_STATUS_INTERVAL_MS) {
    if (publishStatus(sensors, alarm, rssi, nowMs)) lastStatusPublishMs_ = nowMs;
  }
  if (lastVitalsPublishMs_ == 0 ||
      nowMs - lastVitalsPublishMs_ >= Config::MQTT_VITALS_INTERVAL_MS) {
    if (publishVitals(sensors, nowMs)) lastVitalsPublishMs_ = nowMs;
  }
  if (lastGpsPublishMs_ == 0 ||
      nowMs - lastGpsPublishMs_ >= Config::MQTT_GPS_INTERVAL_MS) {
    if (publishGps(sensors, nowMs)) lastGpsPublishMs_ = nowMs;
  }
  if (publishNextEvent(nowMs)) lastPublishAtMs_ = nowMs;
  if (lastStatusPublishMs_ == nowMs || lastVitalsPublishMs_ == nowMs ||
      lastGpsPublishMs_ == nowMs) {
    lastPublishAtMs_ = nowMs;
  }
}
