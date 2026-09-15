from __future__ import annotations

import atexit
import hmac
import json
import logging
import queue
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from smartcane_remote.config import Settings
from smartcane_remote.demo import DemoFeed
from smartcane_remote.mqtt_bridge import MqttBridge
from smartcane_remote.state import StateStore

APP_ROOT = Path(__file__).resolve().parent


def create_app(settings: Settings, store: StateStore) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(APP_ROOT / "templates"),
        static_folder=str(APP_ROOT / "static"),
    )

    @app.before_request
    def require_auth():
        if request.path == "/healthz" or not settings.auth_enabled:
            return None
        auth = request.authorization
        valid = bool(
            auth
            and hmac.compare_digest(auth.username or "", settings.dashboard_username)
            and hmac.compare_digest(auth.password or "", settings.dashboard_password)
        )
        if valid:
            return None
        return Response(
            "需要登录",
            401,
            {"WWW-Authenticate": 'Basic realm="SmartCane Remote"'},
        )

    @app.after_request
    def security_headers(response: Response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'"
        )
        return response

    @app.get("/")
    def index():
        return render_template("index.html", device_id=settings.mqtt_device_id)

    @app.get("/api/state")
    def api_state():
        return jsonify(store.snapshot())

    @app.get("/api/stream")
    def api_stream():
        listener = store.subscribe()

        def generate():
            try:
                yield f"data: {json.dumps(store.snapshot(), ensure_ascii=False)}\n\n"
                while True:
                    try:
                        state = listener.get(timeout=15)
                        yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        yield ": heartbeat\n\n"
            finally:
                store.unsubscribe(listener)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/healthz")
    def healthz():
        state = store.snapshot()
        code = 200 if state["broker"]["connected"] else 503
        return jsonify({"ok": code == 200, "broker": state["broker"]}), code

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env(APP_ROOT)
    settings.validate()
    store = StateStore(settings.mqtt_device_id)

    service = None
    if settings.demo_mode:
        service = DemoFeed(settings, store)
    elif settings.mqtt_ready:
        service = MqttBridge(settings, store)
    else:
        store.set_broker(False, "请在 .env 中配置 MQTT 账号")

    if service:
        service.start()
        atexit.register(service.stop)

    app = create_app(settings, store)
    logging.info("SmartCane remote dashboard: http://%s:%d", settings.web_host, settings.web_port)
    try:
        from waitress import serve

        serve(app, host=settings.web_host, port=settings.web_port, threads=8)
    except ImportError:
        app.run(host=settings.web_host, port=settings.web_port, threaded=True)


if __name__ == "__main__":
    main()

