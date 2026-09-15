#pragma once

// 仅用于验收归档的脱敏配置节选。
// 完整 UserConfig.h 含 Wi-Fi/MQTT 配置，因此没有复制到提交包。
namespace Config {

constexpr bool MAX30102_ENABLED = true;
constexpr bool MAX30102_USE_PRIMARY_I2C = true;
constexpr unsigned char MAX30102_I2C_ADDRESS = 0x57;
constexpr unsigned short MAX30102_SAMPLE_RATE_HZ = 100;
constexpr unsigned char MAX30102_LED_CURRENT = 0x24;
constexpr unsigned char MAX30102_MAX_FIFO_SAMPLES_PER_UPDATE = 6;
constexpr unsigned long MAX30102_RETRY_MS = 5000;
constexpr unsigned long MAX30102_STALE_MS = 1500;
constexpr unsigned long MAX30102_SPO2_WINDOW_MS = 4000;
constexpr unsigned long MAX30102_FINGER_IR_THRESHOLD = 50000;
constexpr float MAX30102_MIN_RELATIVE_AMPLITUDE = 0.0020f;
constexpr float MAX30102_VALID_QUALITY_MIN = 0.45f;
constexpr float MAX30102_HEART_RATE_MIN_BPM = 40.0f;
constexpr float MAX30102_HEART_RATE_MAX_BPM = 180.0f;

// ADC 设置为 100 SPS；FIFO 4 点平均同时产生 4 倍抽取，实际输出约 25 Hz。

constexpr bool RHYTHM_SCREENING_ENABLED = true;
constexpr bool RHYTHM_BASELINE_MODEL_ENABLED = true;
constexpr bool RHYTHM_MODEL_CALIBRATED = false;
constexpr unsigned long RHYTHM_FEATURE_WINDOW_MS = 15000;
constexpr unsigned long RHYTHM_INFERENCE_INTERVAL_MS = 5000;
constexpr unsigned char RHYTHM_MIN_IBI_COUNT = 12;
constexpr float RHYTHM_MIN_SIGNAL_QUALITY = 0.70f;
constexpr bool RHYTHM_REQUIRE_STILL_IMU = true;
constexpr float RHYTHM_MAX_GYRO_DPS = 20.0f;
constexpr float RHYTHM_MAX_ACCEL_DELTA_G = 0.18f;
constexpr unsigned long RHYTHM_SETTLE_AFTER_MOTION_MS = 15000;
constexpr float RHYTHM_MIN_MODEL_CONFIDENCE = 0.60f;
constexpr unsigned char RHYTHM_ALERT_CONSECUTIVE_WINDOWS = 3;

} // namespace Config

