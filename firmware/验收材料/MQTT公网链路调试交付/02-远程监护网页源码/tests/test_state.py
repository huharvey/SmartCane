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

    def test_event_is_added_to_timeline(self):
        self.send("event", {"event": "SOS", "event_uptime_ms": 1234})
        state = self.store.snapshot()
        self.assertEqual(len(state["events"]), 1)
        self.assertEqual(state["events"][0]["payload"]["event"], "SOS")

    def test_invalid_json_is_rejected(self):
        ok = self.store.apply_message(f"{self.prefix}/telemetry", b"not-json")
        self.assertFalse(ok)
        self.assertIn("Invalid JSON", self.store.snapshot()["broker"]["error"])


if __name__ == "__main__":
    unittest.main()

