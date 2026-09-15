from __future__ import annotations

import json
import threading
import time

from .config import Settings
from .state import StateStore


class DemoFeed:
    def __init__(self, settings: Settings, store: StateStore) -> None:
        self.settings = settings
        self.store = store
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.store.set_broker(True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)

    def _send(self, suffix: str, payload: object) -> None:
        topic = f"{self.settings.topic_prefix}/{suffix}"
        if isinstance(payload, str):
            data = payload.encode()
        else:
            data = json.dumps(payload).encode()
        self.store.apply_message(topic, data)

    def _run(self) -> None:
        self._send("presence", "online")
        uptime = 100_000
        event_sent = False
        while not self._stop.wait(1):
            uptime += 1000
            self._send(
                "telemetry",
                {
                    "protocol": "smartcane.mqtt",
                    "version": 1,
                    "online": True,
                    "uptime_ms": uptime,
                    "alarm": "NORMAL",
                    "imu_online": True,
                    "max30102_online": True,
                    "rssi": -37,
                },
            )
            self._send(
                "vitals",
                {
                    "uptime_ms": uptime,
                    "vitals": {
                        "online": True,
                        "finger": True,
                        "valid": True,
                        "signal_quality": 0.86,
                        "heart_rate_bpm": 72.0,
                        "spo2_pct": 98.0,
                        "rhythm": {
                            "state": "NORMAL",
                            "valid": True,
                            "alert": False,
                            "model_calibrated": False,
                            "confidence": 0.91,
                        },
                    },
                },
            )
            self._send(
                "gps",
                {
                    "uptime_ms": uptime,
                    "gps": {
                        "source": "live",
                        "valid": True,
                        "lat": 30.274085,
                        "lon": 120.155070,
                        "satellites": 9,
                    },
                },
            )
            if not event_sent and uptime >= 103_000:
                self._send(
                    "event",
                    {
                        "event": "SOS",
                        "event_uptime_ms": uptime,
                        "vitals": {"online": True, "finger": False, "valid": False},
                        "gps": {"source": "live", "valid": True, "lat": 30.274085, "lon": 120.155070, "satellites": 9},
                    },
                )
                event_sent = True

