import json
import unittest

from smartcane_remote.state import StateStore


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = StateStore("device01")
        self.prefix = "smartcane/device01"

    def send(self, suffix, payload, retained=False):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return self.store.apply_message(
            f"{self.prefix}/{suffix}", data, retained=retained
        )

    def test_device_becomes_online_with_presence_and_fresh_telemetry(self):
        self.store.apply_message(f"{self.prefix}/presence", b"online", True)
        self.send("telemetry", {"online": True, "alarm": "NORMAL"})
        state = self.store.snapshot()
        self.assertTrue(state["device"]["online"])
        self.assertEqual(state["device"]["presence"], "online")

    def test_vitals_and_gps_are_unwrapped(self):
        self.send("vitals", {"vitals": {"online": True, "heart_rate_bpm": 72}})
        self.send("gps", {"gps": {"valid": True, "lat": 30.0, "lon": 120.0}})
        state = self.store.snapshot()
        self.assertEqual(state["vitals"]["heart_rate_bpm"], 72)
        self.assertTrue(state["gps"]["valid"])

    def test_telemetry_keeps_environment_and_sensor_health_fields(self):
        self.send(
            "telemetry",
            {
                "online": True,
                "sonar_online": True,
                "distance_cm": 86.4,
                "light_sensor_online": True,
                "lux": 32.0,
            },
        )
        telemetry = self.store.snapshot()["telemetry"]
        self.assertTrue(telemetry["sonar_online"])
        self.assertEqual(telemetry["distance_cm"], 86.4)
        self.assertTrue(telemetry["light_sensor_online"])
        self.assertEqual(telemetry["lux"], 32.0)

    def test_event_is_added_to_timeline(self):
        self.send("event", {"event": "SOS", "event_uptime_ms": 1234})
        state = self.store.snapshot()
        self.assertEqual(len(state["events"]), 1)
        self.assertEqual(state["events"][0]["payload"]["event"], "SOS")

    def test_invalid_json_is_rejected(self):
        ok = self.store.apply_message(f"{self.prefix}/telemetry", b"not-json")
        self.assertFalse(ok)
        self.assertIn("Invalid JSON", self.store.snapshot()["broker"]["error"])

    def test_unknown_topic_and_non_object_payload_are_rejected(self):
        self.assertFalse(self.send("command", {"command": "sos"}))
        self.assertFalse(
            self.store.apply_message(f"{self.prefix}/telemetry", b"[]")
        )
        self.assertEqual(self.store.snapshot()["events"], [])

    def test_last_valid_gps_survives_signal_loss(self):
        self.store.apply_message(f"{self.prefix}/presence", b"online", True)
        self.send("telemetry", {"online": True, "alarm": "NORMAL"})
        self.send(
            "gps",
            {
                "gps": {
                    "valid": True,
                    "source": "live",
                    "lat": 30.306869,
                    "lon": 120.077684,
                    "satellites": 5,
                }
            },
        )
        self.assertEqual(self.store.snapshot()["gps"]["source"], "live")

        self.send("gps", {"gps": {"valid": False, "source": "none"}})
        gps = self.store.snapshot()["gps"]
        self.assertTrue(gps["valid"])
        self.assertEqual(gps["source"], "last")
        self.assertEqual(gps["lat"], 30.306869)


if __name__ == "__main__":
    unittest.main()
