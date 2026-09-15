#pragma once

#include <Arduino.h>
#include <mqtt_client.h>

#include "../model/SystemState.h"

// Public MQTT transport.  It is owned exclusively by the existing Core 0
// NetworkTask and communicates with the app only through the same queued
// command callback already used by the HTTP and serial interfaces.
class MqttRemoteService {
public:
  using CommandHandler = bool (*)(const char *command, int value);

  enum class State : uint8_t {
    Disabled,
    ConfigError,
    WaitingWifi,
    WaitingTime,
    Connecting,
    Online,
    Error
  };

  struct Status {
    bool enabled = false;
    bool connected = false;
    State state = State::Disabled;
    uint32_t lastPublishAtMs = 0;
  };

  void begin(CommandHandler commandHandler);
  void update(uint32_t nowMs, const SensorSnapshot &sensors, AlarmKind alarm,
              bool apMode, int8_t rssi);
  Status status() const;
  static const char *stateName(State state);

private:
  enum class EventKind : uint8_t {
    SuspectedFall,
    Fall,
    Sos,
    RhythmScreeningAlert
  };

  static const char *eventName(EventKind kind);

  struct PendingEvent {
    EventKind kind = EventKind::Fall;
    SensorSnapshot sensors;
    uint32_t occurredAtMs = 0;
  };

  static esp_err_t eventThunk(esp_mqtt_event_handle_t event);
  esp_err_t handleEvent(esp_mqtt_event_handle_t event);
  void handleCommandData(const esp_mqtt_event_handle_t event);
  bool validConfiguration() const;
  bool usesTls() const;
  bool timeIsValid() const;
  void requestTime(uint32_t nowMs);
  bool ensureClient(uint32_t nowMs);
  void startClient(uint32_t nowMs);
  void stopClient();
  void captureTransitions(const SensorSnapshot &sensors, AlarmKind alarm,
                          uint32_t nowMs);
  void enqueueEvent(EventKind kind, const SensorSnapshot &sensors,
                    uint32_t nowMs);
  bool publishPresence(bool online);
  bool publishStatus(const SensorSnapshot &sensors, AlarmKind alarm,
                     int8_t rssi, uint32_t nowMs);
  bool publishVitals(const SensorSnapshot &sensors, uint32_t nowMs);
  bool publishGps(const SensorSnapshot &sensors, uint32_t nowMs);
  bool publishNextEvent(uint32_t nowMs);
  bool publish(const char *topic, const String &payload, int qos, bool retain);
  void makeTopics();

  static constexpr uint8_t EVENT_QUEUE_SIZE = 4;
  esp_mqtt_client_handle_t client_ = nullptr;
  CommandHandler commandHandler_ = nullptr;
  PendingEvent pendingEvents_[EVENT_QUEUE_SIZE];
  char telemetryTopic_[128]{};
  char vitalsTopic_[128]{};
  char gpsTopic_[128]{};
  char eventTopic_[128]{};
  char presenceTopic_[128]{};
  char commandTopic_[128]{};
  char clientId_[64]{};
  uint8_t eventHead_ = 0;
  uint8_t eventTail_ = 0;
  uint8_t eventCount_ = 0;
  uint32_t lastStatusPublishMs_ = 0;
  uint32_t lastVitalsPublishMs_ = 0;
  uint32_t lastGpsPublishMs_ = 0;
  uint32_t lastEventAttemptMs_ = 0;
  uint32_t lastStartAttemptMs_ = 0;
  uint32_t lastNtpRequestMs_ = 0;
  uint32_t lastPublishAtMs_ = 0;
  AlarmKind previousAlarm_ = AlarmKind::None;
  bool previousRhythmAlert_ = false;
  bool observedState_ = false;
  bool clientRunning_ = false;
  volatile bool connected_ = false;
  volatile bool announcePresence_ = false;
  volatile State state_ = State::Disabled;
};
