#pragma once

// 脱敏示例：按实际 Broker 替换尖括号内容。
// 此文件仅说明本次 MQTT 参数，不可直接替换完整 UserConfig.h。
namespace Config {

constexpr bool MQTT_ENABLED = true;
constexpr char MQTT_URI[] = "mqtts://<broker-host>:8883";
constexpr char MQTT_USERNAME[] = "<device-publisher-username>";
constexpr char MQTT_PASSWORD[] = "<device-publisher-password>";

constexpr char MQTT_TOPIC_ROOT[] = "smartcane";
constexpr char MQTT_DEVICE_ID[] = "device01";

// 当前交付版本保持关闭。完成 Topic ACL 和独立权限账号后再评估开启。
constexpr bool MQTT_ALLOW_REMOTE_COMMANDS = false;
constexpr bool MQTT_ALLOW_INSECURE_TEST = false;

constexpr uint32_t MQTT_STATUS_INTERVAL_MS = 5000;
constexpr uint32_t MQTT_VITALS_INTERVAL_MS = 5000;
constexpr uint32_t MQTT_GPS_INTERVAL_MS = 10000;
constexpr uint32_t MQTT_RETRY_INTERVAL_MS = 5000;
constexpr uint16_t MQTT_PACKET_BUFFER_BYTES = 2048;

// 将 Broker 所需的根 CA PEM 完整填入此字符串。
constexpr char MQTT_ROOT_CA[] = R"PEM(
-----BEGIN CERTIFICATE-----
<broker-root-ca-pem>
-----END CERTIFICATE-----
)PEM";

} // namespace Config

