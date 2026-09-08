---
title: Channel internals
description: "How the Wi-Fi, button, MQTT and Web API channels work, and how to add a new one."
---

How the control channels work under the hood, and how to add a new one. For
what each channel does from a user's point of view, see the
[Channels](../channels/index.md) section.

Every channel is a `uasyncio` task started concurrently at boot from `src/application.py`
— none of them block startup on each other, and none of them touch the LED
strip or renderer directly. A channel's only job is to turn "something
happened" into a patch on the shared state via `self.state.update(patch)`.
`StateManager` validates/clamps the patch, persists it (debounced), and
notifies everyone else (including the renderer). A new input method never needs
to know anything about animations or the LED buffer, and the renderer never
needs to know anything about button presses or MQTT topics.

## The `Channel` interface

Defined in `src/channels/base.py`:

```python
class Channel:
    name = "channel"

    def __init__(self, state, logger):
        self.state = state
        self.logger = logger

    async def start(self):
        pass

    async def stop(self):
        pass
```

- `name` — short identifier, used in log lines.
- `start()` — the channel's main coroutine; runs for the lifetime of the
  device. Long-running channels loop internally with
  `await asyncio.sleep_ms(...)` between polls; don't return early unless the
  channel is intentionally idle (see `MqttChannel`/`NetworkChannel` when
  unconfigured).
- `stop()` — cooperative shutdown; not currently called from `application.py` but
  implemented for symmetry and for tests.

## Network channel

Implemented in `src/channels/network.py`. It doesn't accept commands from
anything — it only keeps the station interface connected and publishes
`runtime.network.wifi.connected`/`ip` (station) and
`runtime.network.ap.active`/`ip` (setup AP), which other channels can use —
`webapi.py`'s gating on either flag is the main consumer, see [Web API / Web
UI channel](#web-api--web-ui-channel). The relationship also runs the other
way: `WebApiChannel` writes `runtime.network.ap.last_request_ms` so this
channel knows whether the setup AP is currently in active use before
attempting a retry — see below.

### Boot-once credentials, AP fallback with a quiet-gated retry

There's no external library here, just `network.WLAN(network.STA_IF)` (and,
for the fallback, `network.WLAN(network.AP_IF)`) driven from a single
`uasyncio` loop. `network.wifi.ssid`/`network.wifi.password` are deliberately
**not** dynamic: read exactly once, in `start()`, not re-read on a config
change — there is no subscription to `StateManager` for credentials in this
channel (contrast `MqttChannel`, which reacts to config changes live). This
is a simplicity trade-off: no revert-on-bad-credentials machinery to
maintain, at the cost of needing a restart to try new credentials.
`network.ap.retry_interval` and `network.ap.retry_quiet_period`, by
contrast, *are* read live (every retry check) — there's no lockout risk in
changing retry cadence, so no reason to make them boot-only.

- **Config boot mode** (`runtime.system.mode == "config"`, published by
  `application.py`'s boot-mode resolution) → straight to
  `_run_ap_forever()` before credentials are even read — config mode is
  AP-only by design, so the dashboard is always at the AP's predictable
  address while reconfiguring.
- **Empty `ssid` at boot** → straight to `_run_ap_forever()`, no connection
  attempt — there's nothing to attempt, and nothing to retry, so the AP just
  stays up until restart.
- **Non-empty `ssid`** → `_keep_connected(ssid, password)`: connect
  (`_connect()`, a bounded poll up to `CONNECT_TIMEOUT_MS`, never a blocking
  call), and on success, monitor forever at `MONITOR_MS`. If an established
  connection drops, it retries with the *same* credentials — exponential
  backoff (`BACKOFF_MIN_MS` up to `BACKOFF_MAX_MS`) between attempts. This
  is resilience against a transient outage, not the dynamic-reconfiguration
  behavior that was deliberately removed.
- **After `AP_FALLBACK_ATTEMPTS` consecutive failures** (whether at boot or
  after a later drop), `_keep_connected` calls `_run_ap_with_retry(ssid,
  password)`. Unlike the empty-`ssid` case, this *does* keep trying the
  configured network in the background — it isn't giving up on the station
  side, just parking on the AP between attempts.
- **`_run_ap_with_retry()`** brings up the AP (`_activate_ap()` — same setup
  `_run_ap_forever()` uses) and polls every `AP_POLL_MS`, tracking elapsed
  time since the last attempt. Once `_retry_interval_ms()`
  (`network.ap.retry_interval`, seconds → ms) has elapsed, it checks
  `_quiet_long_enough()`: has it been at least `_retry_quiet_ms()`
  (`network.ap.retry_quiet_period`) since `runtime.network.ap.last_request_ms`
  (set by `WebApiChannel`'s `before_request` hook — see [Web API / Web UI
  channel](#web-api--web-ui-channel) — only while `ap.active` is true, so
  it doesn't matter once the device is properly connected; missing/`None`
  counts as quiet). If not quiet, it skips this round without resetting the
  elapsed timer, so it rechecks every `AP_POLL_MS` and retries as soon as
  activity stops. If quiet, `_try_reconnect_from_ap()` deactivates the AP,
  attempts `_connect()`, and either publishes `connected: true` and returns
  (control goes back to `_keep_connected`, which resumes normal monitoring)
  or restores the AP and keeps waiting for the next interval. This is the
  other deliberate exception to "AP and an active station connection
  attempt never run concurrently" — noted in `.claude/CLAUDE.md` — and
  exactly why the quiet gate exists: a retry is disruptive (it drops anyone
  connected to the AP for up to `CONNECT_TIMEOUT_MS`), so it only happens
  when nobody's actively using the setup network.
- **Downstream channels gate on state, not on this channel directly.**
  `NetworkChannel` never calls into `MqttChannel`/`WebApiChannel` — it just
  writes to shared state, and those channels poll the fields they need
  themselves. The same is true in the other direction — see Wi-Fi scan below
  for how a *request* to this channel is made without a direct reference,
  and above for how `last_request_ms` flows the other way (`WebApiChannel`
  writing, `NetworkChannel` reading).

### Wi-Fi scan

`webapi.py`'s scan button can't call `network.WLAN(...).scan()` directly —
this channel is the radio's sole owner (see the Architecture rule in
`.claude/CLAUDE.md`). Instead it's mediated through shared state, the same
pattern used elsewhere for cross-channel needs:

1. `POST /json/wifi/scan` sets `runtime.network.wifi.scan_requested: true`.
2. A small polling task (`_scan_service()`, spawned from `start()` alongside
   the main connect logic — the same "background task from `start()`"
   pattern `MqttChannel` uses) notices the flag, calls `_perform_scan()`,
   and writes `runtime.network.wifi.scan_results` (list of `{ssid, rssi,
   channel, open}`) plus clears the flag.
3. The client polls the existing `GET /json/state` until `scan_requested`
   goes back to `false`.

Two things worth knowing if you touch this:

- **`WLAN.scan()` is a blocking call** — MicroPython has no async scan API.
  For the few seconds it runs, the *entire* device (LED rendering, button,
  MQTT, HTTP requests) is frozen, not just this channel — a deliberate,
  bounded exception to the "no blocking calls" rule, not an oversight.
- **Scanning has to work while the AP fallback is up** (the main real-world
  use case — picking your home network's exact SSID while connected to the
  setup network), so `_perform_scan()` reactivates the station interface
  even during `_run_ap_forever()`. Whether cyw43 handles a scan cleanly
  while its AP is active needs verifying on real hardware, same caveat as
  the rest of the AP/STA work in this channel.

### Network exposed functions

| Function | Type | What it does |
|---|---|---|
| `start()` | `Channel` interface | Reads credentials once, spawns the scan service, runs the connect-or-AP logic; the device's single long-lived entry point for this channel |
| `stop()` | `Channel` interface | Disconnects and deactivates both interfaces |
| `_keep_connected(ssid, password)` | internal | Connect/monitor/backoff loop for the boot's one set of credentials, escalating to `_run_ap_with_retry()` after repeated failures and resuming monitoring if it reconnects |
| `_connect(ssid, password)` | internal | One bounded connection attempt, `await`-polled up to `CONNECT_TIMEOUT_MS` |
| `_reset_radio()` | internal | Deactivates the radio and pauses `RADIO_RESET_MS` before the connect loop begins |
| `_run_ap_forever()` | internal | Brings up the setup AP and idles until `stop()` — no timer, no early exit; used only when no `ssid` is configured |
| `_run_ap_with_retry(ssid, password)` | internal | Brings up the setup AP and periodically retries `ssid`/`password` in the background, gated by `_retry_interval_ms()`/`_quiet_long_enough()`; returns `True` on reconnect, `False` on shutdown |
| `_try_reconnect_from_ap(ssid, password)` | internal | One gated retry attempt: drops the AP, calls `_connect()`, publishes success or restores the AP on failure |
| `_activate_ap()` | internal | Shared AP setup (config + `_publish_ap`) used by both `_run_ap_forever()` and `_run_ap_with_retry()` |
| `_retry_interval_ms()` / `_retry_quiet_ms()` | internal | Live reads of `network.ap.retry_interval`/`network.ap.retry_quiet_period`, seconds converted to ms |
| `_quiet_long_enough(quiet_ms)` | internal | Whether `runtime.network.ap.last_request_ms` is old enough (or unset) to allow a retry |
| `_ap_credentials()` | internal | Reads `network.ap.ssid`/`password`, defaulting the SSID to `"<device.name>-setup"` |
| `_perform_scan()` | internal | Reactivates the station interface, calls `WLAN.scan()`, formats the results |
| `_scan_service()` | internal | Background task: polls `runtime.network.wifi.scan_requested`, runs `_perform_scan()`, writes `scan_results` |
| `_publish(connected, ip)` | internal | De-dupes against the last known state, logs on change, and writes `runtime.network.wifi.connected`/`ip` |
| `_publish_ap(active, ip)` | internal | Same de-dupe pattern as `_publish`, for `runtime.network.ap.active`/`ip` |

## Button channel

Implemented in `src/channels/button.py`. Polls a single push button on the
cover and turns short/long presses into state patches — no library, no
interrupts, just a debounced poll loop.

### Debounced poll loop

The pin is read every `POLL_MS`; a level only "counts" once it's been stable
for `STABLE_POLLS` consecutive polls, which filters out mechanical bounce
without any hardware debounce circuit. What happens next depends on how long
the button was held between the debounced press and the debounced release.

- **Active low, internal pull-up.** `Pin(pin_no, Pin.IN, Pin.PULL_UP)` — the
  pin reads `1` at rest and `0` while pressed, matching a button wired to
  ground.
- **Debounce is time-based, not edge-based.** A raw level change resets the
  stability counter (`count = 0`); only after `STABLE_POLLS` polls in a row
  agree on the new level does it become the accepted `stable` value.
- **Timing is measured on release, not on press.** `pressed_at` is recorded on
  the debounced falling edge; the action taken is decided on the debounced
  rising edge, from `held_ms = ticks_diff(now, pressed_at)`.
- **No ISR.** A button doesn't need microsecond edge capture, so a plain
  `asyncio.sleep_ms(POLL_MS)` poll loop is simple enough and matches the
  project's "as simple as possible" rule.

`start()` runs for the lifetime of the device, polling every `POLL_MS`:

1. Debounce the raw pin level against `STABLE_POLLS`.
2. On a debounced **press** (level goes to `0`): record `pressed_at`.
3. On a debounced **release** (level goes back to `1`), classify `held_ms`:
   - after the config-hold feedback fired (see below): ignored — the reboot
     is already committed.
   - `>= ABORT_MS`: held far too long, treated as an aborted gesture — no state
     change, just a log line.
   - `>= LONG_PRESS_MS`: toggles `mode.on` (device on/off).
   - otherwise (**short press**): if the device is currently **off**, turn it
     **on** (the press is consumed by waking the device, it does not also
     advance the mode); if already **on**, advance to the next mode via
     `state.mode.next_mode()`.

One gesture is detected **while held**, not on release: once a press has
lasted `OFF_FEEDBACK_MS` (5 s), the loop turns the LEDs off as user feedback
(one-shot, guarded by a flag) and arms a timestamp; `CONFIG_REBOOT_DELAY_MS`
(1 s) later — checked every poll, whether the button was released or not —
it calls `application.reboot_to_config()` (`src/application.py`), which sets the
one-shot `system.boot_to_config` flag, saves the config to disk
*synchronously* (the debounced autosave would lose it), and resets the
device into [config mode](../development.md#top-level-keys).

The press-timing thresholds (`POLL_MS`, `STABLE_POLLS`, `LONG_PRESS_MS`,
`ABORT_MS`, `OFF_FEEDBACK_MS`, `CONFIG_REBOOT_DELAY_MS`) are module constants
in `src/channels/button.py`, not config —
change them there and re-flash if the physical button needs different timing.
The pin is bound once at startup, so moving the button (`button.pin`) needs a
reboot; the same applies to `leds.pin`.

When `button.enabled` is `false`, the loop just sleeps (`DISABLED_POLL_MS`,
1 s) instead of polling the pin, picking the flag change up within a second.

### Button exposed functions

| Function | Type | What it does |
|---|---|---|
| `start()` | `Channel` interface | Runs the debounce/classify loop; the device's single long-lived entry point for this channel |
| `stop()` | `Channel` interface | Stops the poll loop |

## MQTT channel

Implemented in `src/channels/mqtt.py`. Only active if `mqtt.enabled` is true
(the default), `mqtt.server` is set, **and** Wi-Fi is enabled (non-empty
`network.wifi.ssid`) — a disabled network channel implies a disabled MQTT
channel. If `mqtt.certificate.validate` is also on (see
[Certificate validation](#certificate-validation)), the configured CA
certificate must be readable too. When any of those isn't met, `start()` waits
without touching the network (logging which condition failed) until the
`mqtt`/`network` config changes.

### Non-blocking, via `mqtt_as`

The channel is built entirely on `mqtt_as.MQTTClient` (Peter Hinch,
[`micropython-mqtt`](https://github.com/peterhinch/micropython-mqtt)), vendored
at `lib/mqtt_as.py` (`VERSION = (0, 8, 5)` as of this writing). Every network
call — `connect()`, `subscribe()`, `publish()`, iterating `client.queue` — is
an `await`ed coroutine running on the shared `uasyncio` loop. Nothing in this
channel calls `time.sleep()` or any other blocking socket API, matching the
project rule of never using the blocking `umqtt.simple`/`umqtt.robust` clients.

- **Wi-Fi first.** `start()` blocks (via a non-blocking poll loop, not a real
  block) on `runtime.network.wifi.connected` before doing anything else —
  MQTT never attempts to connect on its own.
- **Wi-Fi stays with the network channel.** Stock `mqtt_as` manages the radio
  itself: its `wifi_connect()` re-issues `connect(ssid, password)` on an
  already-connected interface (forcing a reassociation that can break DNS
  right before the broker lookup), and its `close()` disconnects and
  deactivates the whole interface. Both conflict with the
  [Network channel](#network-channel) being the radio's single owner, so the
  channel builds an `ExternalWifiMQTTClient` (a small `MQTTClient` subclass in
  `src/channels/mqtt.py`) instead: `wifi_connect()` only polls
  `_sta_if.isconnected()` until the radio is up, and `close()` only closes the
  socket. This also skips `mqtt_as`'s ~6s connect-and-verify Wi-Fi dance on
  every broker connect attempt. The `ssid`/`wifi_pw` config keys are still
  populated (the `MQTTClient` constructor requires them) but never used to
  drive the radio.
- **`mqtt.enabled` true, `mqtt.server` non-empty, `network.wifi.ssid`
  non-empty.** Any of them missing is an explicit "disabled" state, not an
  error — the channel logs the reason and waits for a config change.
- **`machine.unique_id()` must be available** — it's hex-encoded into
  `client_id` (`StateManager.device_id`) so multiple devices on the same broker
  don't collide.
- **NTP reachability if `mqtt.ssl: true`.** TLS needs a correct clock for
  certificate validation, so `_sync_time()` runs once against `mqtt.ntp_host`
  before the first connect attempt, retrying every `NTP_RETRY_MS` until it
  succeeds.
- **Reconnection is `mqtt_as`'s job, not ours.** The channel doesn't implement
  its own reconnect loop for an established session — it awaits `client.up`,
  which `mqtt_as` sets/clears internally, and just re-subscribes and
  re-announces (`_handle_up`) whenever that event fires.
- **Incoming messages are queued, not handled inline.** `mqtt_as` buffers
  incoming messages in `client.queue` (`queue_len: 4`); `_handle_messages`
  drains it with `async for`, so a burst of messages can't block publishing or
  the rest of the event loop.

### Basic workflow

`start()` runs for the lifetime of the device. It subscribes to internal state
changes once (`self.state.subscribe(self._on_change)` — the app's own
`StateManager` pub/sub, not MQTT), then loops over *sessions* (`_session`), one
per set of `mqtt`/`network` config. Each session, in order:

1. If the channel is disabled (`mqtt.enabled` false, empty `mqtt.server`, empty
   `network.wifi.ssid`, or an unusable certificate when validation is on), log
   the reason and wait until the `mqtt`/`network` section changes.
2. Wait for `runtime.network.wifi.connected`.
3. Read `mqtt.base_topic`.
4. If `mqtt.ssl` is true, sync the clock over NTP, retrying until it works.
5. Build the `mqtt_as` client from config (`_build_client`).
6. Attempt `client.connect()`, retrying every `RETRY_MS` on failure.
7. Launch three background tasks for the rest of the session:
   - `_handle_up` — on every (re)connect, subscribes to
     `<base_topic>/state/update` and publishes `"online"` (retained).
   - `_handle_messages` — drains incoming messages, applies allow-listed
     patches to the shared state.
   - `_publish_state` — whenever the shared state changes, publishes the full
     state (retained).
8. `_session` itself then just waits — all real work happens in the three tasks
   above.

The whole `mqtt` section is **dynamic**: whenever a state patch touches `mqtt`
or `wifi` (the client also carries the Wi-Fi credentials), the current session
ends — the three tasks are cancelled, `"offline"` is published (retained) on
the old `<base_topic>/state/online` so dashboards don't show a ghost device,
the client is closed — and a fresh session starts, re-reading every `mqtt.*`
value. The swap happens within `RETRY_SLICE_MS`-sized wait slices, typically
well under a second. The `mqtt` section is deliberately kept off this channel's
own allow-list (see [Allow-list](#allow-list-for-the-update-topic)), so an
incoming MQTT patch can't reconfigure the connection it arrives on.

### Installing a different `mqtt_as` version

`lib/mqtt_as.py` is a vendored copy, not a package dependency — there's no
`pip`/`mip` step on-device. To use a different version:

1. Download the replacement `mqtt_as.py` from the
   [`micropython-mqtt`](https://github.com/peterhinch/micropython-mqtt) repo
   and overwrite `lib/mqtt_as.py` wholesale — don't hand-edit the existing file
   into a mix of versions.
2. Keep the same public surface this project relies on:
   `from mqtt_as import MQTTClient, config as mqtt_config`, and the `config`
   dict keys read/written in `_build_client` (`client_id`, `server`, `port`,
   `user`, `password`, `ssid`, `wifi_pw`, `will`, `queue_len`, `ssl`,
   `ssl_params`). If a newer version renames or drops one of these,
   `_build_client` needs a matching update. `ExternalWifiMQTTClient` also
   overrides `wifi_connect()`/`close()` and reaches into the `_sta_if` and
   `_close` internals — verify those still exist and that the base class still
   funnels all radio handling through `wifi_connect()`/`close()`, or the
   Wi-Fi-ownership split breaks silently.
3. `tests/conftest.py` stubs `mqtt_as` for host-side testing — if you start
   depending on new fields/behavior, make sure that stub still satisfies
   `channels/mqtt.py`'s imports before `pytest` will pass.
4. Re-run the usual checks (`ruff check`, `compileall`, `pytest`; see the
   [Development guide](../development.md)), then copy `lib/` back onto the
   device as in [Manual setup](../setup.md).

### Certificate validation

`mqtt.ssl: true` alone gets you an encrypted connection but does **not** verify
the broker's identity — `mqtt_as`/`ussl` accept any certificate the server
presents, so a network-position attacker can MITM the TLS session undetected.
Setting `mqtt.certificate.validate: true` closes that gap: `_build_client`
reads the CA certificate from `certs/<mqtt.certificate.name>` on the device
filesystem (PEM or DER — the underlying `ssl.wrap_socket`/mbedtls binding
accepts either) and passes it as `cadata` with `cert_reqs = ssl.CERT_REQUIRED`,
so the handshake fails closed if the broker's chain doesn't validate against
it.

This is **fail-closed by design**: if `mqtt.ssl` and `mqtt.certificate.validate`
are both true but `mqtt.certificate.name` is empty, contains a path separator,
or the file isn't readable at `certs/<name>`, `_disabled_reason()` reports it
and the channel parks itself exactly like `mqtt.enabled: false` — it does
**not** silently fall back to unverified TLS. Fixing it (uploading the missing
cert, correcting the name) needs no reboot: any `mqtt.*` save re-triggers the
session restart, which re-runs the check.

Notes:

- `mqtt.server` must be a hostname, not a bare IP — certificate verification
  checks the presented cert against `ssl_params.server_hostname` (filled in
  from `mqtt.server`), and CA-issued certs aren't issued for IP addresses.
- To get a DER file from a PEM one:
  `openssl x509 -in cert.pem -outform der -out cert.der`.
- A handshake failure caused by a genuinely wrong/expired cert isn't treated
  specially — it surfaces as an `OSError` in `_connect_with_retries`, logged
  and retried like any other connect failure.
- The default (`certificate.validate: false`) preserves the previous unverified
  behavior, so existing setups aren't affected until you opt in.

### Topics and payloads

All topics are prefixed with `<base_topic>` (`mqtt.base_topic`, default
`controller/led/1`):

| Direction | Topic | Payload |
|---|---|---|
| Subscribes | `<base_topic>/state/update` | JSON patch — only the allow-listed keys are applied; everything else is silently dropped |
| Publishes, retained | `<base_topic>/state/full` | `{"device": "<id>", "mode": {...}, "leds": {...}}`, sent whenever the state changes |
| Publishes, retained (last will) | `<base_topic>/state/online` | `"online"` while connected, `"offline"` if the device drops off unexpectedly |

Every published state payload carries a `"device"` field with the device's own
id (`StateManager.device_id`, derived from `machine.unique_id()`), and
`_handle_messages` drops any incoming patch whose `device` equals that id. In
the default two-topic setup this never triggers; it exists for single-topic
mode.

`<base_topic>/state/online` is set as the connection's last-will topic at
connect time (`will=(...,"offline", True, 0)` in `_build_client`), so the broker
publishes `"offline"` (retained) automatically if the device disconnects
uncleanly. On a clean connect (and every reconnect), `_handle_up` explicitly
publishes `"online"`. On a clean shutdown or a config-triggered session
restart, the will doesn't fire, so `_teardown` publishes `"offline"` explicitly
before closing — important when `base_topic` changes, as nothing would ever
update the old topic again.

#### Single-topic mode

Set `mqtt.use_single_topic_for_state_update: true` and both `state/update` and
`state/full` collapse onto `<base_topic>/state`. Because the device is now
subscribed to the topic it publishes on, the broker echoes its own state
publishes back (MQTT 3.1.1, which `mqtt_as` speaks, has no MQTT 5 "No Local"
option). The `"device"` field breaks that loop: the device ignores any payload
stamped with its own id — including the retained copy replayed on every
reconnect. `<base_topic>/state/online` is unaffected by the switch.

### Allow-list for the `update` topic

The `update` topic only accepts a fixed, small set of keys, not whatever patch
it's given (`ALLOWED_SET_KEYS` / `_filter_set_patch` in `src/channels/mqtt.py`):

| Key | Allowed fields |
|---|---|
| `mode` | `current`, `brightness`, `speed`, `on`, `color`, `direction` |
| `leds` | `count`, `segmenting` |

Anything outside this shape — an unknown top-level key, a field not listed, or
a non-object value — is dropped rather than applied; if *nothing* in the patch
survives filtering, the whole message is ignored and a warning is logged. MQTT
topics are commonly wired into shared home-automation systems, so this keeps a
stray or malformed automation from rewriting the device's Wi-Fi/MQTT
credentials or any other config it shouldn't touch. `segmenting` is allowed as
a whole field; `length` is still floor-clamped to `2` by
`StateManager.update()` regardless of what's published (see
[Segmenting](../animations/index.md#segmenting)).

The color is a `hexColor` convenience that lives entirely in this channel, not
in `StateManager` (which only ever stores `mode.color` as an `[r, g, b]`
array). On the way in, `_resolve_hex_color` (in `_filter_set_patch`) turns a
`mode.hexColor` string into `mode.color` via `hex_to_rgb`
(`src/helpers/color.py`) before allow-list filtering — an invalid string is
logged and dropped. On the way out, `_publish_state` adds a `mode.hexColor`
string derived from `mode.color` with `rgb_to_hex`. `hexColor` is never
persisted and isn't itself on the allow-list.

### MQTT exposed functions

`src/channels/mqtt.py` holds two classes: `MqttTopics`, a small value object
that derives the topic strings from `base_topic` + single-topic mode, and
`MqttChannel`, which implements the standard `Channel` interface.

**`MqttTopics`:**

| Member | What it is |
|---|---|
| `base` | The configured `base_topic` prefix |
| `incoming_updates` | Topic subscribed to for incoming state patches (`<base>/state/update`, or `<base>/state` in single-topic mode) |
| `update_events` | Topic full-state events are published to (`<base>/state/full`, or `<base>/state` in single-topic mode) |
| `online_status` | The online/last-will topic (`<base>/state/online`) |

**`MqttChannel`:**

| Function | Section | What it does |
|---|---|---|
| `start()` | Channel lifecycle | Loops over sessions; the device's single long-lived entry point for this channel |
| `stop()` | Channel lifecycle | Ends the current session: cancels the background tasks, publishes `"offline"`, closes the client |
| `_session()` | Session state machine | Five-step story: wait-if-disabled, initialize, connect, start tasks, wait for restart |
| `_wait_if_disabled()` | Session state machine | If `_disabled_reason()` is set, logs it and waits for a restart |
| `_initialize_session()` | Session state machine | Waits for Wi-Fi, loads topic config, runs the NTP sync when TLS is on, builds the client |
| `_connect_with_retries()` | Session state machine | `client.connect()` retry loop; returns `True` once connected, `False` if a restart interrupts it |
| `_start_session_tasks()` | Session state machine | Spawns the three background tasks |
| `_teardown()` | Session state machine | Cancels the session's tasks, publishes `"offline"` (retained), closes the client |
| `_on_change(patch)` | Restart & publish signalling | `StateManager` subscriber; a patch touching `mqtt`/`wifi` calls `_request_session_restart`, anything else `_request_state_publish` |
| `_request_session_restart()` / `_session_restart_requested()` / `_clear_session_restart_request()` / `_wait_for_session_restart()` | Restart & publish signalling | Intention-named wrappers around the session-restart event |
| `_request_state_publish()` | Restart & publish signalling | Fires the event `_publish_state` waits on |
| `_session_alive()` | Restart & publish signalling | `True` while the channel runs and no session restart is pending |
| `_sleep_unless_session_restarts(ms)` | Restart & publish signalling | Sliced sleep that returns early when a session restart is requested |
| `_disabled_reason()` | Enablement | Returns why the channel can't run, or `None` when it can |
| `_certificate_disabled_reason()` | Enablement | Checks the certificate is usable when `mqtt.ssl` and `mqtt.certificate.validate` are both true |
| `_wait_for_wifi_connected()` | Connection setup | Polls `runtime.network.wifi.connected` until up |
| `_load_topic_config()` | Connection setup | Reads `base_topic`/single-topic mode into a fresh `MqttTopics` |
| `_sync_time_with_retries()` / `_sync_time()` | Connection setup | NTP clock sync (needed for TLS) |
| `_build_client()` | Connection setup | Builds the `mqtt_as` config dict and `MQTTClient` instance from `state` |
| `_handle_up()` | Background tasks | Re-subscribes and re-announces online status after every connect/reconnect |
| `_handle_messages()` | Background tasks | Parses incoming JSON, filters it through the allow-list, applies it to `state` |
| `_filter_set_patch(patch)` | Background tasks | Implements the allow-list above |
| `_resolve_hex_color(mode_fields)` | Background tasks | Converts an incoming `mode.hexColor` string into `mode.color` (`hex_to_rgb`) |
| `_publish_state()` | Background tasks | Publishes the retained full-state payload whenever `state` changes; adds `mode.hexColor` (`rgb_to_hex`) |

## Web API / Web UI channel

Implemented in `src/channels/webapi.py`, built on the vendored `microdot`
(`lib/microdot`, single-file, works unmodified on both MicroPython and
CPython — that's what makes it testable on host). It's the one channel that
serves *out* to a client rather than reading an input, but it follows the
same shape: `state.update(...)` on `POST /json/state`, nothing else touches
the LED strip or renderer directly.

### Gating: same server, two ways to reach it

`webapi.wifi_access` is read once at startup into `self._lan_access` — it's a
boot-only key (see [Configuration](../development.md#top-level-keys)), not a
live toggle, specifically so saving a new value can never cut off the page
you just used to save it. `start()` polls `_access_allowed()` before calling
`self._app.start_server(port=PORT)`:

- `self._lan_access` true (default) — allowed whenever `_network_available()`
  is true, i.e. `runtime.network.wifi.connected` **or**
  `runtime.network.ap.active` — the dashboard works identically whether the
  device joined your network or fell back to its own [setup
  AP](#network-channel).
- `self._lan_access` false — allowed only while `runtime.network.ap.active`
  is true, so the server is reachable exclusively on the setup AP, never
  over the configured Wi-Fi network. The server is never fully "off": the
  setup AP must always stay reachable as the safety net.

Because none of this reacts to config changes anymore, there's no
subscriber, no restart event, and no mid-response `shutdown()` call — the
only place the server stops is `stop()` (channel lifecycle) or naturally
when `_access_allowed()` next comes up false on the polling loop.

### Activity tracking for the Wi-Fi retry

A `before_request` handler (`track_ap_activity`, registered in `_routes()`)
writes `runtime.network.ap.last_request_ms` on every request, but only while
`runtime.network.ap.active` is true — it's a no-op once the device is
properly connected, so normal operation never touches this field.
`NetworkChannel` reads it back to decide whether the setup AP has been idle
long enough to attempt a disruptive retry of the configured network without
interrupting an active setup session — see [Network channel](#network-channel).

### Routes: API and UI, same app, separate modules

`_routes()` (in `webapi.py`) registers the JSON API:

| Route | What it does |
|---|---|
| `GET /json/state` | Returns the full state (config + `mode`/`runtime`) |
| `POST /json/state` | Merges a JSON patch into state via `state.update(...)` |
| `GET /info` | `{"id", "version", "uptime_ms"}` |
| `POST /json/restart` | `_handle_restart` — see below |
| `POST /json/wifi/scan` | Sets `runtime.network.wifi.scan_requested: true` — see [Wi-Fi scan](#wi-fi-scan); the result lands in `runtime.network.wifi.scan_results`, read back via `GET /json/state` (no separate results route) |

`register_ui_routes(app)` (in `src/webui/webui.py`, a plain function, not a
`Channel`) registers the static UI on the *same* `Microdot` instance —
called from `WebApiChannel.__init__` right after `_routes()`:

| Route | Serves |
|---|---|
| `GET /` | `src/webui/static/index.html` — the dashboard |
| `GET /modes` | `src/webui/static/modes.html` — per-mode parameters (`modes.*`) |
| `GET /config` | `src/webui/static/config.html` — device/network/system config |
| `GET /styles/style.css` | `src/webui/static/styles/style.css` — shared styling |
| `GET /js/app.js` | `src/webui/static/js/app.js` — client-side glue |
| `GET /icons/<name>` | One SVG from `src/webui/static/icons/`, allowlisted against the `ICONS` set in `webui.py` (anything else is a 404) |

Each uses `Response.send_file(...)` (microdot's static-file helper) to read
straight off the filesystem — no templating, no build step. Because deploy
already copies `src/` onto the device wholesale (see [Manual
setup](../setup.md)), the static files ship with the rest of the code, no
separate deploy step. Splitting API routes (`webapi.py`) from UI routes
(`webui.py`) into separate modules — while still sharing one `app`/port — is
deliberate: either can change without touching the other, and it keeps
`webapi.py` focused on state, not markup.

The pages themselves are plain HTML/CSS with one small vanilla `app.js` (no
framework, no build step): on load it `GET`s `/json/state` and populates
form fields; on change/submit it `POST`s a patch back — sliders are
debounced client-side (300ms) so dragging one doesn't flood `state.update()`
(which itself debounces the flash write, but there's no reason to send a
request per animation frame of a drag). `config.html`/`modes.html` inputs
carry a `data-key` attribute (e.g. `data-key="leds.segmenting.length"`) that
`app.js`'s `initFormPage()` walks as a dot-path to read/write the nested
JSON — adding a new config field to either page means adding one labeled
input with the right `data-key`, no JS changes. A checkbox can also carry
`data-toggles="<id>"` to show/hide a sibling container (`id="<id>"
class="collapsible"`) based on its own checked state — used to keep each
`enabled`-gated section's other fields out of the way until enabled (MQTT,
Button, IR, Logging on `config.html`). Icons are also fetched rather than
inlined: any element with `data-icon="<name>"` gets its markup replaced by
`initIcons()` with the contents of `GET /icons/<name>.svg` once fetched (and
cached per page load) — this keeps icon markup out of the HTML/JS while
still letting the SVG's `stroke="currentColor"` track the page's light/dark
theme, which a plain `<img>` reference couldn't do.

Two buttons intentionally have **no** dedicated backend route:

- **LEDs "Test"** (`config.html`) just `POST`s the count currently typed in
  the form plus `{"mode": {"on": true, "current": "blink"}}` to the existing
  `/json/state` — the `Renderer` already re-reads `leds.count` every frame and
  reallocates its buffer on change, so this "just works" through the existing
  live-config path with no new server-side code. `blink` (`animations/blink.py`)
  is a regular mode like any other — it uses whatever `mode.color` is already
  configured, so switching to it for a test needs no color logic on either
  side. Blinking rather than a static fill makes a re-test after changing the
  count obvious even when the color doesn't change: a steady color can look
  identical to the previous test, but a restarted on/off cycle can't. Getting
  back to normal afterwards is just picking any other mode again — `blink` is
  a first-class entry in `modes`, not a special overlay state.
- **Wi-Fi "Scan for networks"** *does* need a route (`POST
  /json/wifi/scan`), because unlike the LED count, a scan needs the radio —
  see [Wi-Fi scan](#wi-fi-scan) in the Wi-Fi channel section for why that's
  mediated through state instead of a direct call.

### Restart

`POST /json/restart` calls `_handle_restart`, which schedules
`_delayed_restart` as a background task and returns `{"ok": true}`
immediately — `_delayed_restart` waits `RESTART_DELAY_MS` (300ms) before
calling `machine.reset()`, so the HTTP response has time to actually reach
the client before the device drops off the network. Right before the reset
it saves the config to disk via `Storage().save(...)` — the debounced
autosave (2s) would otherwise lose a change made just before restarting,
e.g. a freshly saved `system.default_mode`.

### Web API exposed functions

| Function | Section | What it does |
|---|---|---|
| `start()` | `Channel` interface | Caches `webapi.wifi_access` (boot-only) into `self._lan_access`, polls `_access_allowed()`, runs the server, loops on server exit |
| `stop()` | `Channel` interface | Shuts the server down |
| `_network_available()` | Enablement | `runtime.network.wifi.connected` or `runtime.network.ap.active` |
| `_access_allowed()` | Enablement | `_network_available()` when `self._lan_access` is true; `runtime.network.ap.active` only when it's false |
| `track_ap_activity(request)` | Activity tracking | `before_request` hook; writes `runtime.network.ap.last_request_ms` while `runtime.network.ap.active` is true, for `NetworkChannel`'s retry gating |
| `_routes()` | Routing | Registers the JSON API on `self._app` |
| `_handle_restart(request)` / `_delayed_restart()` | Restart | Schedules save-then-`machine.reset()` after `RESTART_DELAY_MS` so the response reaches the client first |

## Adding a new channel

No other file needs to change — the renderer and every other channel are
unaware of each other. Steps:

1. Create `src/channels/<name>.py` from the template below.
2. Register an instance of it in the `channels` list in `src/application.py`.
3. If it needs config, add defaults for it to `DEFAULTS` in `src/defaults.py`
   (and to `config.dev.json` for local testing).

### Template

```python
import asyncio

from channels.base import Channel

POLL_MS = 100  # how often start() loops; pick something sane for the input


class MyChannel(Channel):
    name = "mychannel"

    def __init__(self, state, logger):
        super().__init__(state, logger)
        self._running = False
        # read any pins/config needed, e.g.:
        # self._pin = Pin(state.get("mychannel", "pin", default=4), Pin.IN)

    async def start(self):
        self._running = True
        self.logger.info("mychannel", "started")
        while self._running:
            # read input, and when something happened:
            # self.state.update({"mode": {"brightness": new_value}})
            await asyncio.sleep_ms(POLL_MS)

    async def stop(self):
        self._running = False
        self.logger.info("mychannel", "stopped")
```

### Rules to follow

- **Never** touch the LED strip / `Renderer` / `neopixel` directly — only ever
  call `self.state.update(patch)`.
- **Never** use `time.sleep()` or any other busy-wait — always
  `await asyncio.sleep_ms(...)` between polls, so the single event loop stays
  responsive to every other channel.
- **Never** allocate/print/decode inside a hardware interrupt handler if your
  channel is interrupt-driven — the ISR should just record a timestamp/flag and
  let a `uasyncio` task do the real work.
- Read config through `self.state.get(...)` with an explicit `default=`, don't
  assume keys exist — configs can be old/partial.
- Use `self.logger.debug/info/warning/error(...)` with positional
  `{0}`/`{1}` placeholders, never `print()` or f-strings in the log call.
- If the channel is conditionally disabled (no config), still keep `start()`
  alive with an idle sleep loop instead of returning immediately, matching the
  other channels' shape.

### Wiring it in

`src/application.py` builds the channel list per **boot mode** (`main.py` is
only a thin starter — path setup + `asyncio.run`), resolved once at boot by
`resolve_boot_mode(state)` (same module) and published as
`runtime.system.mode`: `normal` runs everything, `config` skips
`MqttChannel`, `mqtt-ssl` skips `WebApiChannel`. Channel imports are lazy —
inside `main()`, after the mode is known — so a skipped channel's module
(and its dependencies, e.g. `microdot` or `mqtt_as`) is never loaded; that's
what frees the contiguous heap the TLS handshake needs in mqtt-ssl mode.
Keep it that way: a module-top import of a channel in `application.py` (or any
import chain from an always-loaded module into `channels.webapi`/
`channels.mqtt`) silently defeats the mode split.

If the device should boot into config mode, `system.boot_to_config` is set,
saved synchronously, and the device reset (`application.reboot_to_config`);
`main()` clears and re-saves the flag immediately after resolving it, before
channels start, so config mode is always one-shot even if a later crash
reboots the device.

```python
# src/application.py, inside main()
mode = resolve_boot_mode(state)
...
from channels.mychannel import MyChannel
channels.append(MyChannel(state, logger))   # in the right mode branch
```
