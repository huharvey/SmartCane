from __future__ import annotations

import atexit
import hmac
import json
import logging
import queue
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from smartcane_remote.amap import AmapStaticMap, MapUnavailable
from smartcane_remote.config import Settings
from smartcane_remote.demo import DemoFeed
from smartcane_remote.mqtt_bridge import MqttBridge
from smartcane_remote.state import StateStore

APP_ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = APP_ROOT / "frontend"


def create_app(settings: Settings, store: StateStore) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(FRONTEND_ROOT),
        static_url_path="/assets",
    )
    amap = AmapStaticMap(settings.amap_static_map_key)

    def decorate_snapshot(state: dict) -> dict:
        state["features"] = {
            "amap_static_map": amap.configured,
            "camera_remote": False,
            "read_only": True,
        }
        return state

    def public_snapshot() -> dict:
        return decorate_snapshot(store.snapshot())

    @app.before_request
    def require_auth():
        if request.path in {"/healthz", "/livez", "/readyz"} or not settings.auth_enabled:
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
        response.headers["Cache-Control"] = (
            "private, max-age=60" if request.path == "/api/map.png" else "no-store"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'"
        )
        return response

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_ROOT, "index.html")

    @app.get("/api/state")
    @app.get("/api/status")
    def api_state():
        return jsonify(public_snapshot())

    @app.get("/api/map.png")
    def api_map():
        try:
            image = amap.get(store.snapshot().get("gps", {}))
        except MapUnavailable:
            return jsonify({"error": "map unavailable"}), 503
        return Response(image.data, mimetype=image.content_type)

    @app.get("/api/stream")
    def api_stream():
        listener = store.subscribe()

        def generate():
            try:
                yield "retry: 3000\n"
                yield f"data: {json.dumps(public_snapshot(), ensure_ascii=False)}\n\n"
                while True:
                    try:
                        state = listener.get(timeout=15)
                        yield f"data: {json.dumps(decorate_snapshot(state), ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        # Recompute staleness so an open page changes to offline
                        # even when no new MQTT message arrives.
                        yield f"data: {json.dumps(public_snapshot(), ensure_ascii=False)}\n\n"
            finally:
                store.unsubscribe(listener)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/healthz")
    @app.get("/livez")
    def healthz():
        return jsonify({"ok": True})

    @app.get("/readyz")
    def readyz():
        ready = bool(store.snapshot()["broker"]["connected"])
        return jsonify({"ok": ready}), 200 if ready else 503

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

        serve(
            app,
            host=settings.web_host,
            port=settings.web_port,
            threads=settings.web_threads,
        )
    except ImportError:
        app.run(host=settings.web_host, port=settings.web_port, threaded=True)


if __name__ == "__main__":
    main()
