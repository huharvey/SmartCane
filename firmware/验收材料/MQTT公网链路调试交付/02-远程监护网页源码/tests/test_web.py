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


if __name__ == "__main__":
    unittest.main()
