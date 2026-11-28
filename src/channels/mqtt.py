import asyncio
import gc
import json
import socket
import struct
import time

import machine
from mqtt_as import MQTTClient, config as mqtt_config

from channels.base import Channel
from helpers.color import hex_to_rgb, rgb_to_hex
from storage import CERTS_DIR

WIFI_POLL_MS = 500
RETRY_MS = 15000
RETRY_SLICE_MS = 500
NTP_RETRY_MS = 2000
NTP_PORT = 123
NTP_TIMEOUT_S = 2
NTP_DELTA = 3155673600 if time.gmtime(0)[0] == 2000 else 2208988800

ALLOWED_SET_KEYS = {
    "mode": {"current", "brightness", "speed", "on", "color", "direction"},
    "leds": {"count", "segmenting"},
}


class MqttTopics:
    def __init__(self, base, single):
        self.base = base
        self._single = single

    @property
    def incoming_updates(self):
        return self.base + ("/state" if self._single else "/state/update")

    @property
    def update_events(self):
        return self.base + ("/state" if self._single else "/state/full")

    @property
    def online_status(self):
        return self.base + "/state/online"


class ExternalWifiMQTTClient(MQTTClient):
    async def wifi_connect(self, quick=False):
        while not self._sta_if.isconnected():
            await asyncio.sleep_ms(WIFI_POLL_MS)

    def close(self):
        self._close()


class MqttChannel(Channel):
    name = "mqtt"

    def __init__(self, state, logger):
        super().__init__(state, logger)
        self._running = False
        self._client = None
        self._tasks = []
        self._topics = MqttTopics("controller/led/1", False)
        self._state_publish_requested = asyncio.Event()
        self._session_restart = asyncio.Event()

    # --- Channel lifecycle ---

    async def start(self):
        self._running = True
        self.state.subscribe(self._on_change)
        while self._running:
            self._clear_session_restart_request()
            await self._session()
            await self._teardown()
            if self._running and self._session_restart_requested():
                self.logger.info("mqtt", "config changed, restarting")

    async def stop(self):
        self._running = False
        self._request_session_restart()
        await self._teardown()
        self.logger.info("mqtt", "stopped")

    # --- Session state machine ---

    async def _session(self):
        if await self._wait_if_disabled():
            return
        if not await self._initialize_session():
            return
        if not await self._connect_with_retries():
            return
        self._start_session_tasks()
        await self._wait_for_session_restart()

    async def _wait_if_disabled(self):
        reason = self._disabled_reason()
        if not reason:
            return False
        self.logger.info("mqtt", "disabled: {0}", reason)
        await self._wait_for_session_restart()
        return True

    async def _initialize_session(self):
        await self._wait_for_wifi_connected()
        if not self._session_alive():
            return False
        self._load_topic_config()
        if self._needs_clock() and not await self._sync_time_with_retries():
            return False
        self._client = self._build_client()
        return True

    async def _connect_with_retries(self):
        server = self.state.get("mqtt", "server")
        while self._session_alive():
            gc.collect()
            self.logger.debug("mqtt", "free memory before connect: {0}", gc.mem_free())
            try:
                await self._client.connect()
            except OSError as e:
                self.logger.warning("mqtt", "connect to {0} failed, retry in {1}ms: {2}", server, RETRY_MS, e)
                await self._sleep_unless_session_restarts(RETRY_MS)
                continue
            self.logger.info("mqtt", "connected to {0}:{1}", server, self.state.get("mqtt", "port", default=1883))
            return True
        return False

    def _start_session_tasks(self):
        self._tasks = [
            asyncio.create_task(self._handle_up()),
            asyncio.create_task(self._handle_messages()),
            asyncio.create_task(self._publish_state()),
        ]

    async def _teardown(self):
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        if self._client:
            try:
                await self._client.publish(self._topics.online_status, "offline", True, 0)
            except OSError:
                pass
            self._client.close()
            self._client = None

    # --- Restart & publish signalling ---

    def _on_change(self, patch):
        if "mqtt" in patch or "network" in patch:
            self._request_session_restart()
        else:
            self._request_state_publish()

    def _request_session_restart(self):
        self._session_restart.set()

    def _session_restart_requested(self):
        return self._session_restart.is_set()

    def _clear_session_restart_request(self):
        self._session_restart.clear()

    async def _wait_for_session_restart(self):
        await self._session_restart.wait()

    def _request_state_publish(self):
        self._state_publish_requested.set()

    def _session_alive(self):
        return self._running and not self._session_restart_requested()

    async def _sleep_unless_session_restarts(self, ms):
        waited = 0
        while self._session_alive() and waited < ms:
            await asyncio.sleep_ms(RETRY_SLICE_MS)
            waited += RETRY_SLICE_MS

    # --- Enablement ---

    def _disabled_reason(self):
        if not self.state.get("mqtt", "enabled", default=True):
            return "mqtt.enabled is false"
        if not self.state.get("mqtt", "server", default=""):
            return "no server configured"
        if not self.state.get("network", "wifi", "ssid", default=""):
            return "wifi is disabled"
        if self.state.get("mqtt", "ssl", default=False) and self.state.get(
            "mqtt", "certificate", "validate", default=False
        ):
            return self._certificate_disabled_reason()
        return None

    def _certificate_disabled_reason(self):
        name = self.state.get("mqtt", "certificate", "name", default="")
        if not name:
            return "certificate name is empty"
        if "/" in name or "\\" in name:
            return "certificate name {0} is invalid".format(name)
        path = CERTS_DIR + "/" + name
        try:
            with open(path, "rb"):
                pass
        except OSError:
            return "certificate {0} not readable".format(path)
        return None

    # --- Connection setup ---

    async def _wait_for_wifi_connected(self):
        while self._session_alive() and not self.state.get(
            "runtime", "network", "wifi", "connected"
        ):
            await asyncio.sleep_ms(WIFI_POLL_MS)

    def _load_topic_config(self):
        base = self.state.get("mqtt", "base_topic", default="")
        single = self.state.get("mqtt", "use_single_topic_for_state_update", default=False)
        self._topics = MqttTopics(base, single)

    def _needs_clock(self):
        return bool(
            self.state.get("mqtt", "ssl", default=False)
            and self.state.get("mqtt", "certificate", "validate", default=False)
        )

    async def _sync_time_with_retries(self):
        while self._session_alive() and not self._sync_time():
            await self._sleep_unless_session_restarts(NTP_RETRY_MS)
        return self._session_alive()

    def _sync_time(self):
        host = self.state.get("mqtt", "ntp_host", default="pool.ntp.org")
        query = bytearray(48)
        query[0] = 0x1B
        sock = None
        try:
            addr = socket.getaddrinfo(host, NTP_PORT)[0][-1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(NTP_TIMEOUT_S)
            sock.sendto(query, addr)
            msg = sock.recv(48)
        except OSError as e:
            self.logger.warning("mqtt", "ntp sync via {0} failed: {1}", host, e)
            return False
        finally:
            if sock:
                sock.close()
        if len(msg) < 44:
            self.logger.warning("mqtt", "ntp sync via {0} failed: short response", host)
            return False
        secs = struct.unpack("!I", msg[40:44])[0] - NTP_DELTA
        tm = time.gmtime(secs)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
        self.logger.info("mqtt", "time synced via {0}", host)
        return True

    def _build_client(self):
        cfg = dict(mqtt_config)
        server = self.state.get("mqtt", "server")
        cfg["client_id"] = self.state.device_id.encode()
        cfg["server"] = server
        cfg["port"] = self.state.get("mqtt", "port", default=1883)
        cfg["user"] = self.state.get("mqtt", "user", default="")
        cfg["password"] = self.state.get("mqtt", "password", default="")
        cfg["ssid"] = self.state.get("network", "wifi", "ssid", default="")
        cfg["wifi_pw"] = self.state.get("network", "wifi", "password", default="")
        cfg["will"] = (self._topics.online_status, "offline", True, 0)
        cfg["queue_len"] = 4
        ssl_enabled = self.state.get("mqtt", "ssl", default=False)
        cfg["ssl"] = ssl_enabled
        if ssl_enabled:
            ssl_params = dict(self.state.get("mqtt", "ssl_params", default={}))
            ssl_params.setdefault("server_hostname", server)
            if self.state.get("mqtt", "certificate", "validate", default=False):
                import ssl

                name = self.state.get("mqtt", "certificate", "name", default="")
                with open(CERTS_DIR + "/" + name, "rb") as f:
                    ssl_params.setdefault("cadata", f.read())
                ssl_params.setdefault("cert_reqs", ssl.CERT_REQUIRED)
            cfg["ssl_params"] = ssl_params
        return ExternalWifiMQTTClient(cfg)

    # --- Background tasks ---

    async def _handle_up(self):
        while self._running:
            await self._client.up.wait()
            self._client.up.clear()
            try:
                await self._client.subscribe(self._topics.incoming_updates, 0)
                await self._client.publish(self._topics.online_status, "online", True, 0)
            except OSError as e:
                self.logger.warning("mqtt", "failed to subscribe/announce on {0}: {1}", self._topics.base, e)
                continue
            self.logger.info("mqtt", "session up, subscribed {0}", self._topics.incoming_updates)
            self._request_state_publish()

    async def _handle_messages(self):
        async for topic, msg, retained in self._client.queue:
            try:
                patch = json.loads(msg)
            except ValueError:
                self.logger.warning("mqtt", "invalid json payload on {0}", topic)
                continue
            if not isinstance(patch, dict):
                self.logger.warning("mqtt", "payload on {0} is not an object", topic)
                continue
            if patch.get("device") == self.state.device_id:
                self.logger.info("mqtt", "ignoring own payload on {0}", topic)
                continue
            allowed = self._filter_set_patch(patch)
            if allowed:
                self.state.update(allowed)
            else:
                self.logger.warning("mqtt", "payload on {0} had no allowed keys", topic)

    def _filter_set_patch(self, patch):
        allowed = {}
        for key, fields in patch.items():
            if key not in ALLOWED_SET_KEYS or not isinstance(fields, dict):
                continue
            if key == "mode":
                fields = self._resolve_hex_color(fields)
            filtered_fields = {k: v for k, v in fields.items() if k in ALLOWED_SET_KEYS[key]}
            if filtered_fields:
                allowed[key] = filtered_fields
        return allowed

    def _resolve_hex_color(self, mode_fields):
        if "hexColor" not in mode_fields:
            return mode_fields
        rgb = hex_to_rgb(mode_fields["hexColor"])
        if rgb is None:
            self.logger.warning("mqtt", "invalid hexColor {0}, ignoring", mode_fields["hexColor"])
            return mode_fields
        mode_fields = dict(mode_fields)
        mode_fields["color"] = rgb
        return mode_fields

    async def _publish_state(self):
        while self._running:
            await self._state_publish_requested.wait()
            self._state_publish_requested.clear()
            mode = dict(self.state.get("mode") or {})
            color = mode.get("color")
            if isinstance(color, list) and len(color) == 3:
                mode["hexColor"] = rgb_to_hex(color)
            payload = json.dumps(
                {
                    "device": self.state.device_id,
                    "mode": mode,
                    "leds": {
                        "count": self.state.get("leds", "count"),
                        "segmenting": self.state.get("leds", "segmenting"),
                    },
                }
            )
            try:
                await self._client.publish(self._topics.update_events, payload, True, 0)
            except OSError as e:
                self.logger.warning("mqtt", "publish to {0} failed: {1}", self._topics.update_events, e)
