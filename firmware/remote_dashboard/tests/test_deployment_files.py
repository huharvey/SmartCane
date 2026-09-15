from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeploymentFileTests(unittest.TestCase):
    def test_compose_keeps_application_port_off_the_public_interface(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn('"127.0.0.1:8080:8080"', compose)
        self.assertNotIn('"0.0.0.0:8080:8080"', compose)

    def test_nginx_template_supports_public_ip_and_preserves_sse(self):
        config = (ROOT / "deploy" / "nginx-smartcane.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("listen 80 default_server;", config)
        self.assertIn("server_name _;", config)
        self.assertIn("proxy_pass http://127.0.0.1:8080;", config)
        self.assertIn("proxy_buffering off;", config)
        self.assertNotIn("YOUR_DOMAIN", config)


if __name__ == "__main__":
    unittest.main()
