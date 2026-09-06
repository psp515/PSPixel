import asyncio
import json
import os
import time

import machine
from microdot import Microdot

from channels.base import Channel
from storage import CERTS_DIR, Storage
from webui.webui import register_ui_routes

WIFI_POLL_MS = 500
PORT = 80
RESTART_DELAY_MS = 300
CERT_MAX_BYTES = 16 * 1024
CERT_NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"


def _valid_cert_name(name):
    if not name or len(name) > 64 or name in (".", ".."):
        return False
    return all(c in CERT_NAME_CHARS for c in name)


class WebApiChannel(Channel):
    name = "webapi"

    def __init__(self, state, logger):
        super().__init__(state, logger)
        self._running = False
        self._lan_access = True
        self._app = Microdot()
        self._routes()
        register_ui_routes(self._app)

    def _network_available(self):
        return bool(
            self.state.get("runtime", "network", "wifi", "connected")
            or self.state.get("runtime", "network", "ap", "active")
        )

    def _access_allowed(self):
        if self._lan_access:
            return self._network_available()
        return bool(self.state.get("runtime", "network", "ap", "active"))

    async def _delayed_restart(self):
        await asyncio.sleep_ms(RESTART_DELAY_MS)
        # Special case: config is saved every 2 seconds so we need to ensure that the state is saved before restarting
        Storage().save(self.state.data(), self.logger)
        machine.reset()

    async def _handle_restart(self, request):
        self.logger.warning("webapi", "restart requested")
        asyncio.create_task(self._delayed_restart())
        return {"ok": True}

    async def _handle_certificate_upload(self, request):
        name = request.args.get("name", "")
        if not _valid_cert_name(name):
            return {"error": "invalid filename"}, 400
        body = request.body
        if not body:
            return {"error": "empty file"}, 400
        if len(body) > CERT_MAX_BYTES:
            return {"error": "file too large"}, 400
        try:
            os.stat(CERTS_DIR)
        except OSError:
            os.mkdir(CERTS_DIR)
        tmp = CERTS_DIR + "/." + name + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.rename(tmp, CERTS_DIR + "/" + name)
        self.state.update({"mqtt": {"certificate": {"name": name}}})
        self.logger.info("webapi", "certificate {0} uploaded", name)
        return {"ok": True, "name": name}

    async def _handle_certificate_list(self, request):
        try:
            names = [n for n in os.listdir(CERTS_DIR) if not n.startswith(".")]
        except OSError:
            names = []
        return {"files": sorted(names)}

    def _routes(self):
        app = self._app
        state = self.state
        logger = self.logger

        @app.before_request
        async def track_ap_activity(request):
            if state.get("runtime", "network", "ap", "active"):
                state.update(
                    {"runtime": {"network": {"ap": {"last_request_ms": time.ticks_ms()}}}}
                )

        @app.get("/json/state")
        async def get_state(request):
            return state.data()

        @app.post("/json/state")
        async def post_state(request):
            try:
                patch = json.loads(request.body)
            except ValueError:
                logger.warning("webapi", "invalid json in POST /json/state")
                return {"error": "invalid json"}, 400
            if not isinstance(patch, dict):
                logger.warning("webapi", "POST /json/state body is not an object")
                return {"error": "invalid json"}, 400
            state.update(patch)
            return {"ok": True}

        @app.get("/info")
        async def info(request):
            return state.info()

        @app.post("/json/restart")
        async def restart(request):
            return await self._handle_restart(request)

        @app.post("/json/wifi/scan")
        async def wifi_scan(request):
            state.update({"runtime": {"network": {"wifi": {"scan_requested": True}}}})
            return {"ok": True}

        @app.post("/json/mqtt/certificate")
        async def mqtt_certificate_upload(request):
            return await self._handle_certificate_upload(request)

        @app.get("/json/mqtt/certificates")
        async def mqtt_certificate_list(request):
            return await self._handle_certificate_list(request)

    async def start(self):
        self._running = True
        self._lan_access = self.state.get("webapi", "wifi_access", default=True)
        while self._running:
            while self._running and not self._access_allowed():
                await asyncio.sleep_ms(WIFI_POLL_MS)
            if not self._running:
                break
            self.logger.info("webapi", "listening on port {0}", PORT)
            await self._app.start_server(port=PORT)
            self.logger.info("webapi", "server stopped")

    async def stop(self):
        self._running = False
        self._app.shutdown()
        self.logger.info("webapi", "stopped")
