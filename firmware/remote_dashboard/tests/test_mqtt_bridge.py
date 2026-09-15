import unittest
from unittest.mock import patch

from smartcane_remote.config import Settings
from smartcane_remote.mqtt_bridge import MqttBridge, SUBSCRIPTIONS
from smartcane_remote.state import StateStore


class SuccessfulReason:
    is_failure = False


class MqttBridgeTests(unittest.TestCase):
    def test_subscribes_only_to_the_five_read_only_topics(self):
        settings = Settings(
            mqtt_host="broker.example.com",
            mqtt_port=8883,
            mqtt_username="reader",
            mqtt_password="secret",
            mqtt_device_id="device01",
            mqtt_topic_root="smartcane",
            mqtt_client_id="web-test",
            mqtt_ca_file="",
            web_host="127.0.0.1",
            web_port=8080,
            dashboard_username="",
            dashboard_password="",
            demo_mode=False,
        )
        store = StateStore("device01")
        with patch("smartcane_remote.mqtt_bridge.mqtt.Client") as client_class:
            bridge = MqttBridge(settings, store)
            client = client_class.return_value
            bridge._on_connect(client, None, None, SuccessfulReason(), None)

        expected = [
            (f"smartcane/device01/{suffix}", qos)
            for suffix, qos in SUBSCRIPTIONS
        ]
        client.subscribe.assert_called_once_with(expected)
        self.assertEqual(
            {suffix for suffix, _ in SUBSCRIPTIONS},
            {"presence", "telemetry", "vitals", "gps", "event"},
        )
        self.assertNotIn("#", "".join(topic for topic, _ in expected))


if __name__ == "__main__":
    unittest.main()
