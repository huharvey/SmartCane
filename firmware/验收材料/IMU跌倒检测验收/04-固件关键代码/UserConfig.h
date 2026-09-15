#pragma once

#include <Arduino.h>

// User-adjustable runtime parameters.  Alarm and fall values are initial
// classroom-demo values only: validate against recordings from this cane before
// relying on them in demonstrations, and never treat them as a safety guarantee.
namespace Config {

constexpr char WIFI_SSID[] = "";
constexpr char WIFI_PASSWORD[] = "";
constexpr char AP_SSID[] = "SmartCane-Camera";
constexpr char AP_PASSWORD[] = "12345678";
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 12000;

// 高德 Web 服务 Key：用于网页中的只读静态定位地图。该 Key 会随网页下发到
// 浏览器，因此请仅授予静态地图所需权限，并留意高德控制台中的调用配额。
constexpr char AMAP_STATIC_MAP_KEY[] = "";

constexpr bool CAMERA_VFLIP = false;
constexpr bool CAMERA_HMIRROR = false;

// Current bench profile: OLED and ultrasonic module are not installed.
// Keep them disabled so the ultrasonic driver's 0x57 probe cannot mistake the
// MAX30102 (which uses the same address) for a distance sensor.
constexpr bool SONAR_ENABLED = false;
constexpr bool OLED_ENABLED = false;
constexpr uint8_t SONAR_I2C_ADDRESS = 0x57;
constexpr uint8_t OLED_I2C_ADDRESS = 0x3C;
constexpr uint32_t SONAR_INTERVAL_MS = 220;
constexpr uint32_t LIGHT_INTERVAL_MS = 500;
constexpr uint32_t DISPLAY_INTERVAL_MS = 250;
constexpr uint32_t TELEMETRY_INTERVAL_MS = 200;

// Obstacle thresholds in centimetres; keep them in descending order.
constexpr float OBSTACLE_CAUTION_CM = 100.0f;
constexpr float OBSTACLE_WARNING_CM = 50.0f;
constexpr float OBSTACLE_DANGER_CM = 30.0f;
// A zone only relaxes after this extra clearance, preventing alarm chatter
// when an ultrasonic measurement fluctuates near a boundary.
constexpr float OBSTACLE_HYSTERESIS_CM = 5.0f;
constexpr float DARK_LUX_THRESHOLD = 20.0f;

// Frozen prototype profile selected after replaying three rounds / 48 recorded
// trials.  The strict path still requires an impact.  A second, longer hold
// path accepts a deeply sampled low-g event even when the 10 Hz JY901S stream
// misses the impact peak.  This is not a safety guarantee.
constexpr float FALL_FREE_FALL_G = 0.55f;
constexpr float FALL_DEEP_FREE_FALL_G = 0.40f;
constexpr float FALL_IMPACT_G = 2.20f;
constexpr float FALL_TILT_DEG = 55.0f;
constexpr float FALL_STILL_GYRO_DPS = 45.0f;
constexpr uint32_t FALL_SEQUENCE_WINDOW_MS = 2000;
constexpr uint32_t FALL_TILT_HOLD_MS = 600;
constexpr uint32_t FALL_DEEP_TILT_HOLD_MS = 1200;
constexpr uint32_t FALL_COOLDOWN_MS = 3000;

static_assert(FALL_DEEP_FREE_FALL_G <= FALL_FREE_FALL_G,
              "deep free-fall threshold must be no greater than free-fall");
static_assert(FALL_TILT_HOLD_MS <= FALL_SEQUENCE_WINDOW_MS,
              "strict fall hold must fit inside the sequence window");
static_assert(FALL_DEEP_TILT_HOLD_MS <= FALL_SEQUENCE_WINDOW_MS,
              "deep fall hold must fit inside the sequence window");

// A detected IMU fall pattern first enters SUSPECTED_FALL. The user may cancel
// it from the existing physical button or web-page cancel button before it
// becomes the latched FALL alarm. This is intentionally timestamp-based rather
// than delay()-based, so the other FreeRTOS tasks keep running.
constexpr uint32_t SUSPECTED_FALL_CONFIRM_MS = 4000;
constexpr uint32_t FALL_CANCEL_COOLDOWN_MS = 3000;

// The currently connected MAX30102 is on the primary GPIO41/42 bus.  Using that
// bus also leaves the ESP32-S3's second hardware I2C controller available for
// the camera SCCB link.  Before enabling the 0x57 ultrasonic module, separate
// the two 0x57 devices with an I2C multiplexer or move one to software I2C.
constexpr bool MAX30102_ENABLED = true;
constexpr bool MAX30102_USE_PRIMARY_I2C = true;
constexpr uint8_t MAX30102_I2C_ADDRESS = 0x57;
constexpr uint16_t MAX30102_SAMPLE_RATE_HZ = 100;
constexpr uint8_t MAX30102_LED_CURRENT = 0x24; // initial, tune with PPG data
constexpr uint8_t MAX30102_MAX_FIFO_SAMPLES_PER_UPDATE = 6;
constexpr uint32_t MAX30102_RETRY_MS = 5000;
constexpr uint32_t MAX30102_STALE_MS = 1500;
constexpr uint32_t MAX30102_SPO2_WINDOW_MS = 4000;
constexpr uint32_t MAX30102_FINGER_IR_THRESHOLD = 50000;
constexpr float MAX30102_MIN_RELATIVE_AMPLITUDE = 0.0020f;
constexpr float MAX30102_VALID_QUALITY_MIN = 0.45f;
constexpr float MAX30102_HEART_RATE_MIN_BPM = 40.0f;
constexpr float MAX30102_HEART_RATE_MAX_BPM = 180.0f;

static_assert(!(MAX30102_ENABLED && MAX30102_USE_PRIMARY_I2C && SONAR_ENABLED),
              "MAX30102 and sonar both use address 0x57; separate their buses");

// Lightweight, on-device PPG rhythm screening.  This is a non-medical
// pre-screen that intentionally stays independent from SOS/FALL alarms.  A
// 15-second stable PPG window is classified only after the user keeps the cane
// still; a possible AF-like pattern must persist for multiple windows before
// it becomes a remote notification.
constexpr bool RHYTHM_SCREENING_ENABLED = true;
constexpr bool RHYTHM_BASELINE_MODEL_ENABLED = true;
// The bundled quantized model verifies the embedded inference/data path.  It
// is not trained with ECG-referenced clinical data, so the UI and MQTT payload
// always disclose this as false.  Replace the model data after offline model
// training and validation before changing this flag to true.
constexpr bool RHYTHM_MODEL_CALIBRATED = false;
constexpr uint32_t RHYTHM_FEATURE_WINDOW_MS = 15000;
constexpr uint32_t RHYTHM_INFERENCE_INTERVAL_MS = 5000;
constexpr uint8_t RHYTHM_MIN_IBI_COUNT = 12;
constexpr float RHYTHM_MIN_SIGNAL_QUALITY = 0.70f;
constexpr bool RHYTHM_REQUIRE_STILL_IMU = true;
constexpr float RHYTHM_MAX_GYRO_DPS = 20.0f;
constexpr float RHYTHM_MAX_ACCEL_DELTA_G = 0.18f;
constexpr uint32_t RHYTHM_SETTLE_AFTER_MOTION_MS = RHYTHM_FEATURE_WINDOW_MS;
constexpr float RHYTHM_MIN_MODEL_CONFIDENCE = 0.60f;
constexpr uint8_t RHYTHM_ALERT_CONSECUTIVE_WINDOWS = 3;

// Public MQTT remote-care channel.  It is intentionally disabled and empty
// by default: do not put production credentials in a public repository.  Set
// the values after creating a TLS-enabled broker account, then enable it.
constexpr bool MQTT_ENABLED = false;
constexpr char MQTT_URI[] = "mqtts://<broker-host>:8883";
constexpr char MQTT_USERNAME[] = "";
constexpr char MQTT_PASSWORD[] = "";
constexpr char MQTT_ROOT_CA[] = R"PEM(
-----BEGIN CERTIFICATE-----
MIIDjjCCAnagAwIBAgIQAzrx5qcRqaC7KGSxHQn65TANBgkqhkiG9w0BAQsFADBh
MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3
d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH
MjAeFw0xMzA4MDExMjAwMDBaFw0zODAxMTUxMjAwMDBaMGExCzAJBgNVBAYTAlVT
MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5j
b20xIDAeBgNVBAMTF0RpZ2lDZXJ0IEdsb2JhbCBSb290IEcyMIIBIjANBgkqhkiG
9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuzfNNNx7a8myaJCtSnX/RrohCgiN9RlUyfuI
2/Ou8jqJkTx65qsGGmvPrC3oXgkkRLpimn7Wo6h+4FR1IAWsULecYxpsMNzaHxmx
1x7e/dfgy5SDN67sH0NO3Xss0r0upS/kqbitOtSZpLYl6ZtrAGCSYP9PIUkY92eQ
q2EGnI/yuum06ZIya7XzV+hdG82MHauVBJVJ8zUtluNJbd134/tJS7SsVQepj5Wz
tCO7TG1F8PapspUwtP1MVYwnSlcUfIKdzXOS0xZKBgyMUNGPHgm+F6HmIcr9g+UQ
vIOlCsRnKPZzFBQ9RnbDhxSJITRNrw9FDKZJobq7nMWxM4MphQIDAQABo0IwQDAP
BgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBhjAdBgNVHQ4EFgQUTiJUIBiV
5uNu5g/6+rkS7QYXjzkwDQYJKoZIhvcNAQELBQADggEBAGBnKJRvDkhj6zHd6mcY
1Yl9PMWLSn/pvtsrF9+wX3N3KjITOYFnQoQj8kVnNeyIv/iPsGEMNKSuIEyExtv4
NeF22d+mQrvHRAiGfzZ0JFrabA0UWTW98kndth/Jsw1HKj2ZL7tcu7XUIOGZX1NG
Fdtom/DzMNU+MeKNhJ7jitralj41E6Vf8PlwUHBHQRFXGU7Aj64GxJUTFy8bJZ91
8rGOmaFvE7FBcf6IKshPECBV1/MUReXgRPTqh5Uykw7+U0b6LJ3/iyK5S9kJRaTe
pLiaWN0bfVKfjllDiIGknibVb63dDcY3fe0Dkhvld1927jyNxF1WW6LZZm6zNTfl
MrY=
-----END CERTIFICATE-----
)PEM";
constexpr char MQTT_TOPIC_ROOT[] = "smartcane";
constexpr char MQTT_DEVICE_ID[] = "device01";
constexpr bool MQTT_ALLOW_REMOTE_COMMANDS = false;
// Plain mqtt:// is allowed only for a temporary isolated lab test.  Public
// deployment must use mqtts:// plus MQTT_ROOT_CA and broker ACLs.
constexpr bool MQTT_ALLOW_INSECURE_TEST = false;
constexpr uint32_t MQTT_STATUS_INTERVAL_MS = 5000;
constexpr uint32_t MQTT_VITALS_INTERVAL_MS = 5000;
constexpr uint32_t MQTT_GPS_INTERVAL_MS = 10000;
constexpr uint32_t MQTT_RETRY_INTERVAL_MS = 5000;
constexpr uint32_t MQTT_NTP_RETRY_INTERVAL_MS = 10000;
constexpr int32_t MQTT_TIMEZONE_OFFSET_SECONDS = 8 * 60 * 60;
constexpr char MQTT_NTP_SERVER_1[] = "ntp.aliyun.com";
constexpr char MQTT_NTP_SERVER_2[] = "pool.ntp.org";
constexpr uint32_t MQTT_MIN_VALID_EPOCH = 1704067200UL; // 2024-01-01 UTC
constexpr uint16_t MQTT_PACKET_BUFFER_BYTES = 2048;

// MJPEG is rate-limited in normal mode and runs unrestricted for SOS/fall.
constexpr uint32_t CAMERA_NORMAL_FRAME_INTERVAL_MS = 150;
constexpr uint32_t CAMERA_INCIDENT_FRAME_INTERVAL_MS = 0;

constexpr uint32_t SENSOR_STALE_MS = 2000;
constexpr uint32_t GPS_STALE_MS = 5000;

// Temporary bring-up aid.  At boot, test common UART rates and print the first
// checksum-valid NMEA sentences to the ESP32 debug serial port.  Set this to
// false after the GPS baud rate has been confirmed to remove the boot delay.
constexpr bool GPS_BAUD_DIAGNOSTIC_ON_BOOT = false;
constexpr uint32_t GPS_BAUD_DIAGNOSTIC_DWELL_MS = 2500;
constexpr uint8_t GPS_BAUD_DIAGNOSTIC_REQUIRED_LINES = 2;

// FreeRTOS timing.  Sensor I/O and decision-making stay on Core 1 while the
// ESP32 Wi-Fi/HTTP stack is serviced from Core 0.
constexpr uint32_t SENSOR_TASK_PERIOD_MS = 10;
constexpr uint32_t DECISION_TASK_PERIOD_MS = 20;
constexpr uint32_t ACTUATOR_TASK_PERIOD_MS = 10;
constexpr uint32_t NETWORK_TASK_PERIOD_MS = 20;
constexpr uint32_t TELEMETRY_TASK_PERIOD_MS = 10;
} // namespace Config
