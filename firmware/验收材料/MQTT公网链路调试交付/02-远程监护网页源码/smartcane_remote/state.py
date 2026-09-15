from __future__ import annotations

import copy
import json
import queue
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class StateStore:
    """Thread-safe latest-value cache shared by MQTT and HTTP threads."""

    def __init__(self, device_id: str, stale_after_seconds: float = 15.0) -> None:
        self.device_id = device_id
        self.stale_after_seconds = stale_after_seconds
        self._lock = threading.RLock()
        self._listeners: set[queue.Queue] = set()
        self._broker_connected = False
        self._broker_error = ""
        self._presence = "unknown"
        self._channels: dict[str, dict[str, Any]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=100)
        self._message_count = 0

    def set_broker(self, connected: bool, error: str = "") -> None:
        with self._lock:
            self._broker_connected = connected
            self._broker_error = error
            self._notify_locked()

    def apply_message(
        self, topic: str, payload_bytes: bytes, retained: bool = False
    ) -> bool:
        suffix = topic.rsplit("/", 1)[-1]
        received_at = utc_now()
        try:
            text = payload_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return False

        with self._lock:
            self._message_count += 1
            if suffix == "presence":
                self._presence = text.strip().lower()
                self._channels[suffix] = {
                    "payload": self._presence,
                    "received_at": received_at,
                    "retained": retained,
                }
            else:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    self._broker_error = f"Invalid JSON received on {topic}"
                    self._notify_locked()
                    return False
                record = {
                    "payload": payload,
                    "received_at": received_at,
                    "retained": retained,
                }
                self._channels[suffix] = record
                if suffix == "event":
                    self._events.appendleft(
                        {
                            "payload": payload,
                            "received_at": received_at,
                            "retained": retained,
                        }
                    )
            self._notify_locked()
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, Any]:
        telemetry_record = self._channels.get("telemetry")
        age_seconds: float | None = None
        if telemetry_record:
            received = datetime.fromisoformat(telemetry_record["received_at"])
            age_seconds = max(
                0.0, (datetime.now(timezone.utc) - received).total_seconds()
            )
        telemetry = telemetry_record["payload"] if telemetry_record else {}
        fresh = age_seconds is not None and age_seconds <= self.stale_after_seconds
        device_online = bool(
            self._presence == "online" and fresh and telemetry.get("online", False)
        )
        return {
            "device_id": self.device_id,
            "generated_at": utc_now(),
            "broker": {
                "connected": self._broker_connected,
                "error": self._broker_error,
                "message_count": self._message_count,
            },
            "device": {
                "online": device_online,
                "presence": self._presence,
                "telemetry_age_seconds": age_seconds,
            },
            "telemetry": telemetry,
            "vitals": self._channels.get("vitals", {}).get("payload", {}).get(
                "vitals", {}
            ),
            "gps": self._channels.get("gps", {}).get("payload", {}).get("gps", {}),
            "updated_at": {
                name: record["received_at"] for name, record in self._channels.items()
            },
            "events": list(self._events),
        }

    def subscribe(self) -> queue.Queue:
        listener: queue.Queue = queue.Queue(maxsize=2)
        with self._lock:
            self._listeners.add(listener)
        return listener

    def unsubscribe(self, listener: queue.Queue) -> None:
        with self._lock:
            self._listeners.discard(listener)

    def _notify_locked(self) -> None:
        snapshot = copy.deepcopy(self._snapshot_locked())
        dead: list[queue.Queue] = []
        for listener in self._listeners:
            try:
                while listener.qsize() > 0:
                    listener.get_nowait()
                listener.put_nowait(snapshot)
            except (queue.Empty, queue.Full):
                dead.append(listener)
        for listener in dead:
            self._listeners.discard(listener)

