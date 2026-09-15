from __future__ import annotations

import logging
import ssl
from typing import Any

import paho.mqtt.client as mqtt

from .config import Settings
from .state import StateStore

LOG = logging.getLogger(__name__)

SUBSCRIPTIONS = (
    ("presence", 1),
    ("telemetry", 0),
    ("vitals", 0),
    ("gps", 0),
    ("event", 1),
)


class MqttBridge:
    def __init__(self, settings: Settings, store: StateStore) -> None:
        self.settings = settings
        self.store = store
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311,
        )
        self._client.username_pw_set(
            settings.mqtt_username, settings.mqtt_password
        )
        tls_context = ssl.create_default_context()
        if settings.mqtt_ca_file:
            tls_context.load_verify_locations(settings.mqtt_ca_file)
        tls_context.check_hostname = True
        tls_context.verify_mode = ssl.CERT_REQUIRED
        self._client.tls_set_context(tls_context)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_connect_fail = self._on_connect_fail

    def start(self) -> None:
        self.store.set_broker(False, "正在连接公网 MQTT…")
        self._client.connect_async(
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            keepalive=60,
        )
        self._client.loop_start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            message = f"MQTT 拒绝连接：{reason_code}"
            LOG.error(message)
            self.store.set_broker(False, message)
            return
        topics = [
            (f"{self.settings.topic_prefix}/{suffix}", qos)
            for suffix, qos in SUBSCRIPTIONS
        ]
        client.subscribe(topics)
        LOG.info(
            "MQTT connected; subscribed to %s",
            ", ".join(topic for topic, _ in topics),
        )
        self.store.set_broker(True, "")

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        message = "MQTT 已断开，正在自动重连"
        if reason_code.is_failure:
            message += f"：{reason_code}"
        LOG.warning(message)
        self.store.set_broker(False, message)

    def _on_connect_fail(self, client: mqtt.Client, userdata: Any) -> None:
        self.store.set_broker(False, "无法连接 MQTT Broker，正在重试")

    def _on_message(
        self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage
    ) -> None:
        self.store.apply_message(message.topic, message.payload, message.retain)
