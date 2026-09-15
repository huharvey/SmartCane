from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_env_file(path: Path) -> None:
    """Load a small KEY=VALUE file without overriding process environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_device_id: str
    mqtt_topic_root: str
    mqtt_client_id: str
    mqtt_ca_file: str
    web_host: str
    web_port: int
    dashboard_username: str
    dashboard_password: str
    demo_mode: bool
    amap_static_map_key: str = ""
    dashboard_auth_required: bool = False
    web_threads: int = 24

    @classmethod
    def from_env(cls, app_root: Path) -> "Settings":
        load_env_file(app_root / ".env")
        device_id = os.getenv("MQTT_DEVICE_ID", "device01").strip()
        return cls(
            mqtt_host=os.getenv("MQTT_HOST", "").strip(),
            mqtt_port=int(os.getenv("MQTT_PORT", "8883")),
            mqtt_username=os.getenv("MQTT_USERNAME", "").strip(),
            mqtt_password=os.getenv("MQTT_PASSWORD", ""),
            mqtt_device_id=device_id,
            mqtt_topic_root=os.getenv("MQTT_TOPIC_ROOT", "smartcane").strip(" /"),
            mqtt_client_id=os.getenv(
                "MQTT_CLIENT_ID", f"smartcane-web-{device_id}"
            ).strip(),
            mqtt_ca_file=os.getenv("MQTT_CA_FILE", "").strip(),
            web_host=os.getenv("WEB_HOST", "127.0.0.1").strip(),
            web_port=int(os.getenv("WEB_PORT", "8080")),
            dashboard_username=os.getenv("DASHBOARD_USERNAME", "").strip(),
            dashboard_password=os.getenv("DASHBOARD_PASSWORD", ""),
            demo_mode=_as_bool(os.getenv("SMARTCANE_DEMO")),
            amap_static_map_key=os.getenv("AMAP_STATIC_MAP_KEY", "").strip(),
            dashboard_auth_required=_as_bool(
                os.getenv("DASHBOARD_AUTH_REQUIRED")
            ),
            web_threads=int(os.getenv("WEB_THREADS", "24")),
        )

    @property
    def topic_prefix(self) -> str:
        return f"{self.mqtt_topic_root}/{self.mqtt_device_id}"

    @property
    def mqtt_ready(self) -> bool:
        return bool(
            self.mqtt_host
            and self.mqtt_username
            and self.mqtt_password
            and self.mqtt_device_id
            and self.mqtt_topic_root
        )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.dashboard_username and self.dashboard_password)

    def validate(self) -> None:
        public_bind = self.web_host not in {"127.0.0.1", "localhost", "::1"}
        if bool(self.dashboard_username) != bool(self.dashboard_password):
            raise ValueError(
                "DASHBOARD_USERNAME and DASHBOARD_PASSWORD must be set together"
            )
        if (public_bind or self.dashboard_auth_required) and not self.auth_enabled:
            raise ValueError(
                "Public deployment requires DASHBOARD_USERNAME and DASHBOARD_PASSWORD"
            )
        if self.web_threads < 4:
            raise ValueError("WEB_THREADS must be at least 4")
        if self.mqtt_ca_file and not Path(self.mqtt_ca_file).is_file():
            raise ValueError(f"MQTT_CA_FILE does not exist: {self.mqtt_ca_file}")
