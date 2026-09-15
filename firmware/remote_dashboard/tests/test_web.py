import base64
import unittest

from app import create_app
from smartcane_remote.config import Settings
from smartcane_remote.state import StateStore


def settings(**overrides):
    values = {
        "mqtt_host": "broker.example.com",
        "mqtt_port": 8883,
        "mqtt_username": "reader",
        "mqtt_password": "secret",
        "mqtt_device_id": "device01",
        "mqtt_topic_root": "smartcane",
        "mqtt_client_id": "web-test",
        "mqtt_ca_file": "",
        "web_host": "127.0.0.1",
        "web_port": 8080,
        "dashboard_username": "",
        "dashboard_password": "",
        "demo_mode": False,
    }
    values.update(overrides)
    return Settings(**values)


class WebAppTests(unittest.TestCase):
    def test_state_api_and_security_headers(self):
        app = create_app(settings(), StateStore("device01"))
        response = app.test_client().get("/api/state")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["device_id"], "device01")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_status_alias_returns_same_cloud_snapshot(self):
        app = create_app(settings(), StateStore("device01"))
        client = app.test_client()
        state = client.get("/api/state").get_json()
        status = client.get("/api/status").get_json()

        self.assertEqual(status["device_id"], state["device_id"])
        self.assertEqual(status["telemetry"], state["telemetry"])
        self.assertTrue(status["features"]["read_only"])

    def test_basic_auth_protects_dashboard_and_api(self):
        app = create_app(
            settings(dashboard_username="guardian", dashboard_password="safe-pass"),
            StateStore("device01"),
        )
        client = app.test_client()

        self.assertEqual(client.get("/").status_code, 401)
        token = base64.b64encode(b"guardian:safe-pass").decode("ascii")
        response = client.get("/api/state", headers={"Authorization": f"Basic {token}"})
        self.assertEqual(response.status_code, 200)

    def test_health_endpoint_remains_available_for_hosting_probe(self):
        store = StateStore("device01")
        store.set_broker(True)
        app = create_app(
            settings(dashboard_username="guardian", dashboard_password="safe-pass"),
            store,
        )

        self.assertEqual(app.test_client().get("/healthz").status_code, 200)

    def test_readiness_reports_mqtt_separately_from_liveness(self):
        app = create_app(settings(), StateStore("device01"))
        client = app.test_client()
        self.assertEqual(client.get("/livez").status_code, 200)
        self.assertEqual(client.get("/readyz").status_code, 503)

    def test_frontend_is_separate_and_contains_no_remote_controls(self):
        app = create_app(settings(), StateStore("device01"))
        client = app.test_client()
        page = client.get("/")
        script = client.get("/assets/app.js")

        self.assertEqual(page.status_code, 200)
        page_source = page.get_data(as_text=True)
        source = script.get_data(as_text=True)
        page.close()
        script.close()
        self.assertIn("摄像头仅支持近场访问", page_source)
        self.assertIn("前方距离", page_source)
        self.assertIn("环境光照", page_source)
        self.assertIn("超声波距离传感器", page_source)
        self.assertIn("BH1750 光照传感器", page_source)
        self.assertIn("/api/status", source)
        self.assertIn("telemetry.distance_cm", source)
        self.assertIn("telemetry.lux", source)
        self.assertIn("sonar_online", source)
        self.assertIn("light_sensor_online", source)
        self.assertNotIn("MQTT_PASSWORD", source)
        self.assertNotIn("/api/sos", source)
        self.assertNotIn(":81/stream", source)

    def test_map_proxy_requires_server_side_key_and_position(self):
        app = create_app(settings(), StateStore("device01"))
        response = app.test_client().get("/api/map.png")
        self.assertEqual(response.status_code, 503)

    def test_sse_starts_with_current_snapshot(self):
        app = create_app(settings(), StateStore("device01"))
        response = app.test_client().get("/api/stream", buffered=False)
        iterator = iter(response.response)
        self.assertIn(b"retry: 3000", next(iterator))
        self.assertIn(b'"device_id": "device01"', next(iterator))
        response.close()


if __name__ == "__main__":
    unittest.main()
