import asyncio
import json

import channels.mqtt as mqtt_module
from channels.mqtt import ExternalWifiMQTTClient, MqttChannel, MqttTopics
from logger.logger import Logger
from state import StateManager


class FakeStaIf:
    def __init__(self, connected_results):
        self._connected_results = list(connected_results)
        self.calls = []

    def isconnected(self):
        self.calls.append("isconnected")
        return self._connected_results.pop(0) if self._connected_results else True

    def connect(self, *args):
        self.calls.append("connect")

    def disconnect(self):
        self.calls.append("disconnect")

    def active(self, value=None):
        self.calls.append("active")


class FakeQueue:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class FakeClient:
    def __init__(self, queue_items=None):
        self.queue = FakeQueue(queue_items or [])
        self.published = []
        self.subscribed = []
        self.up = asyncio.Event()

    async def publish(self, topic, msg, retain, qos):
        self.published.append((topic, msg, retain, qos))

    async def subscribe(self, topic, qos):
        self.subscribed.append((topic, qos))

    def close(self):
        self.closed = True


def make_channel(data):
    state = StateManager(data)
    logger = Logger(state)
    return MqttChannel(state, logger), state


def test_filter_set_patch_keeps_allowed_and_drops_unknown():
    channel, _ = make_channel({})
    patch = {
        "mode": {"current": "rainbow", "on": False, "unknown": 1},
        "leds": {"count": 100, "pin": 5},
        "network": {"wifi": {"password": "secret"}},
    }

    allowed = channel._filter_set_patch(patch)

    assert allowed == {"mode": {"current": "rainbow", "on": False}, "leds": {"count": 100}}


def test_filter_set_patch_keeps_segmenting():
    channel, _ = make_channel({})
    patch = {"leds": {"count": 100, "segmenting": {"enabled": True, "length": 5}, "pin": 5}}

    allowed = channel._filter_set_patch(patch)

    assert allowed == {"leds": {"count": 100, "segmenting": {"enabled": True, "length": 5}}}


def test_filter_set_patch_converts_hex_color_to_rgb():
    channel, _ = make_channel({})
    patch = {"mode": {"hexColor": "#ff781e", "on": True}}

    allowed = channel._filter_set_patch(patch)

    assert allowed == {"mode": {"color": [255, 120, 30], "on": True}}


def test_filter_set_patch_drops_invalid_hex_color():
    channel, _ = make_channel({})
    patch = {"mode": {"hexColor": "nope", "on": True}}

    allowed = channel._filter_set_patch(patch)

    assert allowed == {"mode": {"on": True}}


def test_handle_messages_applies_hex_color():
    channel, state = make_channel({"mode": {"current": "static", "color": [1, 2, 3]}})
    channel._client = FakeClient(
        queue_items=[
            (b"controller/led/1/state/update", json.dumps({"mode": {"hexColor": "#ff781e"}}).encode(), False),
        ]
    )

    asyncio.run(channel._handle_messages())

    assert state.mode.color == [255, 120, 30]


def test_handle_messages_applies_allowed_patch():
    channel, state = make_channel({"mode": {"current": "static", "on": True}})
    channel._client = FakeClient(
        queue_items=[
            (b"controller/led/1/state/update", json.dumps({"mode": {"on": False}}).encode(), False),
        ]
    )

    asyncio.run(channel._handle_messages())

    assert state.mode.on is False
    assert state.mode.current == "static"


def test_handle_messages_applies_partial_segmenting_patch_preserving_sibling_key():
    channel, state = make_channel(
        {"leds": {"count": 100, "segmenting": {"enabled": True, "length": 10}}}
    )
    channel._client = FakeClient(
        queue_items=[
            (
                b"controller/led/1/state/update",
                json.dumps({"leds": {"segmenting": {"length": 5}}}).encode(),
                False,
            ),
        ]
    )

    asyncio.run(channel._handle_messages())

    assert state.get("leds", "segmenting") == {"enabled": True, "length": 5}


def test_handle_messages_ignores_invalid_json():
    channel, state = make_channel({"mode": {"current": "static"}})
    channel._client = FakeClient(queue_items=[(b"controller/led/1/state/update", b"not json", False)])

    asyncio.run(channel._handle_messages())

    assert state.mode.current == "static"


def test_handle_messages_ignores_disallowed_keys():
    channel, state = make_channel({"mode": {"current": "static"}})
    channel._client = FakeClient(
        queue_items=[
            (
                b"controller/led/1/state/update",
                json.dumps({"network": {"wifi": {"password": "hacked"}}}).encode(),
                False,
            ),
        ]
    )

    asyncio.run(channel._handle_messages())

    assert "network" not in state.data()


def test_handle_messages_ignores_own_device_payload():
    channel, state = make_channel({"mode": {"current": "static", "on": True}})
    channel._client = FakeClient(
        queue_items=[
            (
                b"controller/led/1/state",
                json.dumps({"device": state.device_id, "mode": {"on": False}}).encode(),
                True,
            ),
        ]
    )

    asyncio.run(channel._handle_messages())

    assert state.mode.on is True


def test_handle_up_subscribes_to_state_update_and_announces_online():
    channel, _ = make_channel({})
    channel._topics = MqttTopics("mytopic", False)
    channel._running = True
    client = FakeClient()
    channel._client = client

    async def run_briefly():
        client.up.set()
        task = asyncio.create_task(channel._handle_up())
        await asyncio.sleep(0.01)
        channel._running = False
        client.up.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_briefly())

    assert ("mytopic/state/update", 0) in client.subscribed
    assert ("mytopic/state/online", "online", True, 0) in client.published


def test_publish_state_sends_full_mode_and_leds_on_change():
    channel, state = make_channel(
        {
            "mode": {"current": "static", "on": True},
            "leds": {"count": 10, "pin": 0, "segmenting": {"enabled": False, "length": 5}},
        }
    )
    channel._topics = MqttTopics("controller/led/1", False)
    channel._running = True
    client = FakeClient()
    channel._client = client

    async def run_briefly():
        channel._state_publish_requested.set()
        task = asyncio.create_task(channel._publish_state())
        await asyncio.sleep(0.01)
        channel._running = False
        channel._state_publish_requested.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_briefly())

    assert len(client.published) == 1
    topic, payload, retain, qos = client.published[0]
    assert topic == "controller/led/1/state/full"
    assert retain is True
    assert qos == 0
    data = json.loads(payload)
    assert data["mode"] == {"current": "static", "on": True}
    assert data["leds"] == {"count": 10, "segmenting": {"enabled": False, "length": 5}}
    assert data["device"] == state.device_id


def test_publish_state_adds_hex_color_from_rgb():
    channel, _ = make_channel(
        {
            "mode": {"current": "static", "on": True, "color": [255, 120, 30]},
            "leds": {"count": 10, "pin": 0, "segmenting": {"enabled": False, "length": 5}},
        }
    )
    channel._topics = MqttTopics("controller/led/1", False)
    channel._running = True
    client = FakeClient()
    channel._client = client

    async def run_briefly():
        channel._state_publish_requested.set()
        task = asyncio.create_task(channel._publish_state())
        await asyncio.sleep(0.01)
        channel._running = False
        channel._state_publish_requested.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_briefly())

    _, payload, _, _ = client.published[0]
    data = json.loads(payload)
    assert data["mode"]["color"] == [255, 120, 30]
    assert data["mode"]["hexColor"] == "#ff781e"


def test_on_change_mqtt_patch_triggers_restart_not_publish():
    channel, _ = make_channel({})

    channel._on_change({"mqtt": {"server": "broker.local"}})

    assert channel._session_restart.is_set()
    assert not channel._state_publish_requested.is_set()


def test_on_change_wifi_patch_triggers_restart():
    channel, _ = make_channel({})

    channel._on_change({"network": {"wifi": {"ssid": "new"}}})

    assert channel._session_restart.is_set()


def test_on_change_other_patch_triggers_publish_not_restart():
    channel, _ = make_channel({})

    channel._on_change({"mode": {"on": False}})

    assert channel._state_publish_requested.is_set()
    assert not channel._session_restart.is_set()


def test_teardown_publishes_offline_and_closes_client():
    channel, _ = make_channel({})
    channel._topics = MqttTopics("mytopic", False)
    client = FakeClient()
    channel._client = client

    asyncio.run(channel._teardown())

    assert ("mytopic/state/online", "offline", True, 0) in client.published
    assert client.closed is True
    assert channel._client is None


def test_session_disabled_without_server_wakes_on_restart():
    channel, state = make_channel({"mqtt": {"server": ""}})

    async def run():
        task = asyncio.create_task(channel._session())
        await asyncio.sleep(0.01)
        assert not task.done()
        state.subscribe(channel._on_change)
        state.update({"mqtt": {"server": "broker.local"}})
        await asyncio.sleep(0.01)
        assert task.done()

    channel._running = True
    asyncio.run(run())


def _run_initialize_session(data):
    channel, _ = make_channel(data)
    ntp_calls = []
    channel._sync_time = lambda: ntp_calls.append(True) or True
    channel._build_client = lambda: FakeClient()
    channel._running = True
    result = asyncio.run(channel._initialize_session())
    return result, ntp_calls


def test_initialize_session_skips_ntp_when_ssl_without_certificate_validation():
    result, ntp_calls = _run_initialize_session(
        {
            "mqtt": {"server": "b", "ssl": True, "certificate": {"validate": False}},
            "runtime": {"network": {"wifi": {"connected": True}}},
        }
    )
    assert result is True
    assert ntp_calls == []


def test_initialize_session_syncs_ntp_when_certificate_validation_on():
    result, ntp_calls = _run_initialize_session(
        {
            "mqtt": {"server": "b", "ssl": True, "certificate": {"validate": True, "name": "c.pem"}},
            "runtime": {"network": {"wifi": {"connected": True}}},
        }
    )
    assert result is True
    assert ntp_calls == [True]


def test_disabled_reason_covers_enabled_server_and_wifi():
    channel, _ = make_channel(
        {"mqtt": {"enabled": False, "server": "b"}, "network": {"wifi": {"ssid": "x"}}}
    )
    assert channel._disabled_reason() == "mqtt.enabled is false"

    channel, _ = make_channel({"mqtt": {"server": ""}, "network": {"wifi": {"ssid": "x"}}})
    assert channel._disabled_reason() == "no server configured"

    channel, _ = make_channel({"mqtt": {"server": "b"}, "network": {"wifi": {"ssid": ""}}})
    assert channel._disabled_reason() == "wifi is disabled"

    channel, _ = make_channel({"mqtt": {"server": "b"}, "network": {"wifi": {"ssid": "x"}}})
    assert channel._disabled_reason() is None


def test_disabled_reason_ignores_certificate_when_ssl_off(tmp_path, monkeypatch):
    monkeypatch.setattr(mqtt_module, "CERTS_DIR", str(tmp_path))
    channel, _ = make_channel(
        {
            "mqtt": {"server": "b", "ssl": False, "certificate": {"validate": True, "name": "missing.pem"}},
            "network": {"wifi": {"ssid": "x"}},
        }
    )
    assert channel._disabled_reason() is None


def test_disabled_reason_certificate_missing_name(tmp_path, monkeypatch):
    monkeypatch.setattr(mqtt_module, "CERTS_DIR", str(tmp_path))
    channel, _ = make_channel(
        {
            "mqtt": {"server": "b", "ssl": True, "certificate": {"validate": True, "name": ""}},
            "network": {"wifi": {"ssid": "x"}},
        }
    )
    assert channel._disabled_reason() == "certificate name is empty"


def test_disabled_reason_certificate_name_rejects_path_separator(tmp_path, monkeypatch):
    monkeypatch.setattr(mqtt_module, "CERTS_DIR", str(tmp_path))
    channel, _ = make_channel(
        {
            "mqtt": {"server": "b", "ssl": True, "certificate": {"validate": True, "name": "../secrets.pem"}},
            "network": {"wifi": {"ssid": "x"}},
        }
    )
    assert channel._disabled_reason() == "certificate name ../secrets.pem is invalid"


def test_disabled_reason_certificate_file_not_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(mqtt_module, "CERTS_DIR", str(tmp_path))
    channel, _ = make_channel(
        {
            "mqtt": {"server": "b", "ssl": True, "certificate": {"validate": True, "name": "ca.pem"}},
            "network": {"wifi": {"ssid": "x"}},
        }
    )
    assert channel._disabled_reason() == f"certificate {tmp_path}/ca.pem not readable"


def test_disabled_reason_certificate_file_present(tmp_path, monkeypatch):
    monkeypatch.setattr(mqtt_module, "CERTS_DIR", str(tmp_path))
    (tmp_path / "ca.pem").write_bytes(b"cert bytes")
    channel, _ = make_channel(
        {
            "mqtt": {"server": "b", "ssl": True, "certificate": {"validate": True, "name": "ca.pem"}},
            "network": {"wifi": {"ssid": "x"}},
        }
    )
    assert channel._disabled_reason() is None


def test_build_client_ssl_without_certificate_validation_has_no_cadata():
    channel, _ = make_channel({"mqtt": {"server": "b", "ssl": True}})
    client = channel._build_client()
    assert "cadata" not in client.cfg["ssl_params"]
    assert "cert_reqs" not in client.cfg["ssl_params"]


def test_build_client_certificate_validation_sets_cadata_and_cert_reqs(tmp_path, monkeypatch):
    import ssl

    monkeypatch.setattr(mqtt_module, "CERTS_DIR", str(tmp_path))
    (tmp_path / "ca.pem").write_bytes(b"cert bytes")
    channel, _ = make_channel(
        {"mqtt": {"server": "b", "ssl": True, "certificate": {"validate": True, "name": "ca.pem"}}}
    )

    client = channel._build_client()

    assert client.cfg["ssl_params"]["cadata"] == b"cert bytes"
    assert client.cfg["ssl_params"]["cert_reqs"] == ssl.CERT_REQUIRED


def test_build_client_user_ssl_params_win_over_certificate_defaults(tmp_path, monkeypatch):
    import ssl

    monkeypatch.setattr(mqtt_module, "CERTS_DIR", str(tmp_path))
    (tmp_path / "ca.pem").write_bytes(b"cert bytes")
    channel, _ = make_channel(
        {
            "mqtt": {
                "server": "b",
                "ssl": True,
                "certificate": {"validate": True, "name": "ca.pem"},
                "ssl_params": {"cert_reqs": ssl.CERT_OPTIONAL},
            }
        }
    )

    client = channel._build_client()

    assert client.cfg["ssl_params"]["cert_reqs"] == ssl.CERT_OPTIONAL
    assert client.cfg["ssl_params"]["cadata"] == b"cert bytes"


def test_build_client_returns_external_wifi_client():
    channel, _ = make_channel({"mqtt": {"server": "b"}})

    client = channel._build_client()

    assert isinstance(client, ExternalWifiMQTTClient)


def test_external_wifi_client_wifi_connect_waits_without_driving_radio(monkeypatch):
    monkeypatch.setattr(mqtt_module, "WIFI_POLL_MS", 1)
    client = ExternalWifiMQTTClient({})
    client._sta_if = FakeStaIf([False, False, True])

    asyncio.run(client.wifi_connect())

    assert "connect" not in client._sta_if.calls
    assert "disconnect" not in client._sta_if.calls
    assert client._sta_if.calls.count("isconnected") == 3


def test_external_wifi_client_close_keeps_radio_up():
    client = ExternalWifiMQTTClient({})
    client._sta_if = FakeStaIf([True])
    closed = []
    client._close = lambda: closed.append(True)

    client.close()

    assert closed == [True]
    assert client._sta_if.calls == []


def test_single_topic_joins_update_and_full():
    topics = MqttTopics("mytopic", True)

    assert topics.incoming_updates == "mytopic/state"
    assert topics.update_events == "mytopic/state"


def test_two_topic_mode_splits_update_and_full():
    topics = MqttTopics("mytopic", False)

    assert topics.incoming_updates == "mytopic/state/update"
    assert topics.update_events == "mytopic/state/full"
    assert topics.online_status == "mytopic/state/online"


def test_single_topic_subscribe_and_publish_use_joined_topic():
    channel, _ = make_channel({"mode": {"current": "static", "on": True}})
    channel._topics = MqttTopics("mytopic", True)
    channel._running = True
    client = FakeClient()
    channel._client = client

    async def run_briefly():
        client.up.set()
        channel._state_publish_requested.set()
        tasks = [
            asyncio.create_task(channel._handle_up()),
            asyncio.create_task(channel._publish_state()),
        ]
        await asyncio.sleep(0.01)
        channel._running = False
        client.up.set()
        channel._state_publish_requested.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(run_briefly())

    assert ("mytopic/state", 0) in client.subscribed
    assert any(topic == "mytopic/state" for topic, _, _, _ in client.published)
