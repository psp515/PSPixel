import asyncio

import channels.webapi as webapi_module
import webui.webui as webui_module
from channels.webapi import WebApiChannel
from logger.logger import Logger
from state import StateManager


class FakeApp:
    def __init__(self):
        self.start_calls = []
        self._shutdown = asyncio.Event()

    async def start_server(self, port=None):
        self.start_calls.append(port)
        self._shutdown.clear()
        await self._shutdown.wait()

    def shutdown(self):
        self._shutdown.set()


def patch_timings(monkeypatch):
    monkeypatch.setattr(webapi_module, "WIFI_POLL_MS", 5)


async def run_scenario(data, body):
    # Constructed inside the running loop, not before `asyncio.run(...)`, so
    # the `asyncio.Event()`s WebApiChannel/FakeApp hold bind to the loop
    # they're actually awaited on.
    state = StateManager(data)
    logger = Logger(state)
    channel = WebApiChannel(state, logger)
    channel._app = FakeApp()
    task = asyncio.create_task(channel.start())
    try:
        await body(channel, state)
    finally:
        await channel.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def test_stays_down_without_network(monkeypatch):
    patch_timings(monkeypatch)

    async def body(channel, state):
        await asyncio.sleep(0.05)
        assert channel._app.start_calls == []

    asyncio.run(run_scenario({}, body))


def test_starts_when_connected(monkeypatch):
    patch_timings(monkeypatch)

    async def body(channel, state):
        state.update({"runtime": {"network": {"wifi": {"connected": True}}}})
        await asyncio.sleep(0.05)
        assert channel._app.start_calls == [80]

    asyncio.run(run_scenario({}, body))


def test_starts_when_only_ap_active(monkeypatch):
    patch_timings(monkeypatch)

    async def body(channel, state):
        state.update({"runtime": {"network": {"ap": {"active": True}}}})
        await asyncio.sleep(0.05)
        assert channel._app.start_calls == [80]

    asyncio.run(run_scenario({}, body))


def test_ap_only_blocks_start_when_connected_via_station(monkeypatch):
    patch_timings(monkeypatch)

    async def body(channel, state):
        state.update({"runtime": {"network": {"wifi": {"connected": True}}}})
        await asyncio.sleep(0.05)
        assert channel._app.start_calls == []

    asyncio.run(run_scenario({"webapi": {"wifi_access": False}}, body))


def test_ap_only_allows_start_when_ap_active(monkeypatch):
    patch_timings(monkeypatch)

    async def body(channel, state):
        state.update({"runtime": {"network": {"ap": {"active": True}}}})
        await asyncio.sleep(0.05)
        assert channel._app.start_calls == [80]

    asyncio.run(run_scenario({"webapi": {"wifi_access": False}}, body))


def test_enabled_is_boot_only(monkeypatch):
    patch_timings(monkeypatch)

    async def body(channel, state):
        state.update({"runtime": {"network": {"wifi": {"connected": True}}}})
        await asyncio.sleep(0.05)
        assert len(channel._app.start_calls) == 1
        state.update({"webapi": {"wifi_access": False}})
        await asyncio.sleep(0.05)
        assert not channel._app._shutdown.is_set()

    asyncio.run(run_scenario({}, body))


def test_tracks_last_request_only_while_on_ap():
    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)
        req = FakeRequest("GET", "/info")

        for handler in channel._app.before_request_handlers:
            await handler(req)
        assert state.get("runtime", "network", "ap", "last_request_ms") is None

        state.update({"runtime": {"network": {"ap": {"active": True}}}})
        for handler in channel._app.before_request_handlers:
            await handler(req)
        assert state.get("runtime", "network", "ap", "last_request_ms") is not None

    asyncio.run(scenario())


def test_restart_endpoint_responds_ok_and_schedules_reset(monkeypatch):
    monkeypatch.setattr(webapi_module, "RESTART_DELAY_MS", 5)
    calls = []
    monkeypatch.setattr(webapi_module.machine, "reset", lambda: calls.append(True))

    class FakeStorage:
        def save(self, data, logger=None):
            pass

    monkeypatch.setattr(webapi_module, "Storage", FakeStorage)

    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        result = await channel._handle_restart(None)
        assert result == {"ok": True}
        assert calls == []

        await asyncio.sleep(0.05)
        assert calls == [True]

    asyncio.run(scenario())


class FakeRequest:
    def __init__(self, method, path):
        self.method = method
        self.path = path


def test_static_routes_serve_files():
    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        for path, content_type in [
            ("/", "text/html"),
            ("/modes", "text/html"),
            ("/config", "text/html"),
            ("/styles/style.css", "text/css"),
            ("/js/app.js", "application/javascript"),
        ]:
            req = FakeRequest("GET", path)
            handler, _prefix, _subapp = channel._app.find_route(req)
            response = await handler(req)
            assert response.status_code == 200
            assert response.headers["Content-Type"].startswith(content_type)

    asyncio.run(scenario())


def test_icon_routes_serve_known_icons():
    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        for name in webui_module.ICONS:
            req = FakeRequest("GET", "/icons/" + name)
            handler, _prefix, _subapp = channel._app.find_route(req)
            response = await handler(req, **req.url_args)
            assert response.status_code == 200
            assert response.headers["Content-Type"] == "image/svg+xml"

    asyncio.run(scenario())


def test_icon_route_rejects_unknown_icon():
    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        req = FakeRequest("GET", "/icons/not-an-icon.svg")
        handler, _prefix, _subapp = channel._app.find_route(req)
        result = await handler(req, **req.url_args)

        assert result == ({"error": "not found"}, 404)

    asyncio.run(scenario())


def test_wifi_scan_endpoint_sets_request_flag():
    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        req = FakeRequest("POST", "/json/wifi/scan")
        handler, _prefix, _subapp = channel._app.find_route(req)
        result = await handler(req)

        assert result == {"ok": True}
        assert state.get("runtime", "network", "wifi", "scan_requested") is True

    asyncio.run(scenario())


class FakeUploadRequest:
    def __init__(self, name, body):
        self.args = {"name": name}
        self.body = body


def test_certificate_upload_writes_file_and_updates_state(tmp_path, monkeypatch):
    monkeypatch.setattr(webapi_module, "CERTS_DIR", str(tmp_path))

    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        result = await channel._handle_certificate_upload(
            FakeUploadRequest("ca.pem", b"cert bytes")
        )

        assert result == {"ok": True, "name": "ca.pem"}
        assert (tmp_path / "ca.pem").read_bytes() == b"cert bytes"
        assert state.get("mqtt", "certificate", "name") == "ca.pem"

    asyncio.run(scenario())


def test_certificate_upload_rejects_path_separator_in_name(tmp_path, monkeypatch):
    monkeypatch.setattr(webapi_module, "CERTS_DIR", str(tmp_path))

    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        result = await channel._handle_certificate_upload(
            FakeUploadRequest("../ca.pem", b"cert bytes")
        )

        assert result == ({"error": "invalid filename"}, 400)
        assert list(tmp_path.iterdir()) == []

    asyncio.run(scenario())


def test_certificate_upload_rejects_dotdot_and_tricky_names(tmp_path, monkeypatch):
    monkeypatch.setattr(webapi_module, "CERTS_DIR", str(tmp_path))

    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        for name in ("..", ".", "ca pem", "café.pem", "x" * 65):
            result = await channel._handle_certificate_upload(
                FakeUploadRequest(name, b"cert bytes")
            )
            assert result == ({"error": "invalid filename"}, 400)
        assert list(tmp_path.iterdir()) == []

    asyncio.run(scenario())


def test_certificate_upload_rejects_empty_body(tmp_path, monkeypatch):
    monkeypatch.setattr(webapi_module, "CERTS_DIR", str(tmp_path))

    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        result = await channel._handle_certificate_upload(FakeUploadRequest("ca.pem", b""))

        assert result == ({"error": "empty file"}, 400)

    asyncio.run(scenario())


def test_certificate_upload_rejects_oversized_body(tmp_path, monkeypatch):
    monkeypatch.setattr(webapi_module, "CERTS_DIR", str(tmp_path))
    monkeypatch.setattr(webapi_module, "CERT_MAX_BYTES", 4)

    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        result = await channel._handle_certificate_upload(
            FakeUploadRequest("ca.pem", b"too big")
        )

        assert result == ({"error": "file too large"}, 400)
        assert list(tmp_path.iterdir()) == []

    asyncio.run(scenario())


def test_certificate_list_returns_sorted_filenames_excluding_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(webapi_module, "CERTS_DIR", str(tmp_path))
    (tmp_path / "b.pem").write_bytes(b"b")
    (tmp_path / "a.pem").write_bytes(b"a")
    (tmp_path / ".hidden.tmp").write_bytes(b"tmp")

    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        result = await channel._handle_certificate_list(None)

        assert result == {"files": ["a.pem", "b.pem"]}

    asyncio.run(scenario())


def test_certificate_list_returns_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(webapi_module, "CERTS_DIR", str(tmp_path / "missing"))

    async def scenario():
        state = StateManager({})
        logger = Logger(state)
        channel = WebApiChannel(state, logger)

        result = await channel._handle_certificate_list(None)

        assert result == {"files": []}

    asyncio.run(scenario())




def test_restart_saves_config_before_reset(monkeypatch):
    patch_timings(monkeypatch)
    monkeypatch.setattr(webapi_module, "RESTART_DELAY_MS", 1)
    calls = []

    class FakeStorage:
        def save(self, data, logger=None):
            calls.append(("save", data["device"]["name"]))

    monkeypatch.setattr(webapi_module, "Storage", FakeStorage)
    monkeypatch.setattr(webapi_module.machine, "reset", lambda: calls.append(("reset",)))

    async def body(channel, state):
        await channel._handle_restart(None)
        await asyncio.sleep(0.05)
        assert calls == [("save", "Pico"), ("reset",)]

    asyncio.run(run_scenario({"device": {"name": "Pico"}}, body))
