---
layout: default
title: Development
parent: Contributing
nav_order: 1
---

# Development guide

This page is for anyone changing the code: 
- how the device works internally,
- how to set up a host-side dev environment
- how the config file is structured. 
- If you just want to run the device, see [Manual setup](setup.md) instead.

## How it works

```
Button / MQTT  ──►  StateManager  ──►  Renderer  ──►  WS2812B strip
  (channels)        (shared state)      (animations)
                         │
                         ▼
                    config.json
               (debounced autosave)
```

Everything runs in a single `uasyncio` event loop on one core. `main.py` is
just a thin starter (path setup + `asyncio.run`); the boot sequence lives in
`src/application.py`. At boot,
it loads the config, then starts the renderer, the autosave task, and
every channel (Wi-Fi, button, MQTT) concurrently as independent
tasks — nothing blocks waiting on anything else, so the strip lights up
immediately using whatever was last saved.

Every input path (a "channel") is just a translator: it turns "the user did
something" — a button press, an MQTT message —
into a small JSON patch applied to one shared application state. The renderer
watches that same state and redraws the strip whenever it changes. No input
path ever touches the LED strip directly, and the renderer never knows or
cares which channel triggered a change.

## Architecture

- **`StateManager`** (`src/state.py`) holds the entire config + runtime state
  as a plain dict, with a small `Mode` helper for the frequently-read fields
  (`current`, `brightness`, `speed`, `on`, `color`, `direction`). `update(patch)` merges a patch in,
  validates/clamps it, persists it (debounced), and notifies subscribers —
  including the renderer. Validation is per-section: a `VALIDATORS` dict maps
  a top-level key (`mode`, `leds`) to a small function
  (`_validate_mode`/`_validate_leds`) that only inspects/clamps the fields it
  owns (e.g. `mode.brightness`/`speed` to 1-100, `leds.count` to a floor of 1,
  `leds.segmenting.length` to a floor of 2) and leaves everything else in the
  patch untouched. Adding validation for a new section means writing one such
  function and registering it in `VALIDATORS` — `update()` itself doesn't
  change. `update()` only validates the *patch* passed to it — see
  `revalidate()` below for the boot-time gap that leaves.
- **Channels** (`src/channels/`) are the only things allowed to call
  `state.update(...)`. See [Channel internals](contributing/channels.md) for
  the interface and how to add a new one.
- **Renderer** (`src/renderer.py`) watches the state for changes, instantiates
  the active animation from a mode registry, and renders it into a
  preallocated NeoPixel buffer every frame, applying global brightness
  scaling and (optionally) [segmenting](contributing/animations.md#segmenting).
  It also re-checks `leds.count` every frame and reallocates the NeoPixel buffer
  on the fly if it changed — so the LED count is one more thing you can
  change at runtime without a reboot. See
  [Animation internals](contributing/animations.md) for the interface and how
  to add a new mode.
- **Storage** (`src/storage.py`) loads the config file on boot, merging over
  built-in defaults, and autosaves changes back with a debounce + atomic
  `os.rename()` write. Details below.
- **Logger** (`src/logger/`) is config-driven and disabled by default;
  application code never calls `print()` — see the `Logger` class and its
  appenders (`ConsoleAppender`).

## Setting up a development environment

The `src/` code is written so the pure-logic parts (`state.py`, `storage.py`,
`defaults.py`, and channels that don't touch hardware) also import and run
unchanged on regular CPython — that's what the test suite exercises. Code
that touches hardware (`machine`, `network`, `neopixel`) only runs
on-device; `tests/conftest.py` stubs the handful of MicroPython-only modules
and functions (`mqtt_as`, `machine` incl. `Pin`, `neopixel`,
`time.ticks_ms`/`ticks_diff`, `asyncio.sleep_ms`) needed to import
`channels/mqtt.py` and `renderer.py` under test.

Install once:

```
pip install ruff pytest
```

Then, matching `.github/workflows/ci.yml` (lint → build → test):

- Lint: `python -m ruff check src main.py`
- Compile-check (syntax only, all source files): `python -m compileall -q src main.py`
- Tests: `python -m pytest` (`pythonpath` is `src` and `lib`, configured in `pyproject.toml`; tests live in `tests/`)

To actually try a change on hardware, copy the edited files onto the device
as described in [Manual setup](setup.md) — there's no build step in between.

### Libraries in use

- `uasyncio` — the only concurrency model; no `_thread`, no second core.
- `mqtt_as` (Peter Hinch, micropython-mqtt) — async, resilient MQTT client.

### MicroPython constraints to keep in mind

- No `typing` at runtime, no heavy stdlib imports.
- Avoid per-frame heap allocations — reuse preallocated `bytearray`/buffer
  objects (see how animations write into the renderer's buffer).
- Use `time.ticks_ms()`/`time.ticks_diff()` for timing, never naive
  subtraction (`time.ticks_ms()` wraps around).
- No busy-wait `time.sleep()` inside tasks — always `await asyncio.sleep_ms()`.
- Keep modules small and prefer plain classes/dicts over metaprogramming or
  deep inheritance — this codebase is meant to stay easy to read.

## Configuration file

All configuration and runtime state lives in one JSON file, loaded by
`Storage` (`src/storage.py`) at boot and merged over the built-in `DEFAULTS`
(`src/defaults.py`), so a partial or older config still works — missing keys
just fall back to their default.

### `config.json` vs `config.dev.json`

`Storage` prefers `config.dev.json` over `config.json` if both exist on the
filesystem. `config.dev.json` is listed in `.gitignore` — it exists so you can
keep a filled-in set of real Wi-Fi/MQTT credentials on your machine for local
development without ever committing secrets to the repo. Use only one of the
two on an actual device — see [Manual setup](setup.md) for setting up
`config.json` there.

### How saves work

- Every change goes through `StateManager.update(...)`, which merges the
  patch into memory immediately (the strip reacts right away) and marks the
  state as changed.
- A background task (`Storage.autosave`) waits for that change, then keeps
  waiting in ~2s slices as long as more changes keep arriving, so rapid
  changes (e.g. dragging a brightness slider) are batched into a single
  write instead of hitting flash on every tick.
- Writes go to `config.json.tmp` then `os.rename()` over the real file — an
  atomic swap, so a power loss mid-write can't corrupt the config.
- The `runtime` key (e.g. `runtime.network.wifi.connected`) is excluded from what
  gets persisted — it's live status, not configuration.
- If the file is missing or fails to parse as JSON, `Storage` falls back to
  `DEFAULTS` and immediately recreates the file.

### Validating data loaded from disk

`StateManager.update(patch)` only validates the *patch* it's given — it never
re-checks values already sitting in `self._data`. That matters at boot:
`application.py` builds `StateManager(storage.load())` directly from whatever's in
`config.json`, bypassing `update()` entirely, so a value that's out of range
(hand-edited file, a value written by an older version of the code before a
clamp existed, a corrupted write) would otherwise load verbatim and keep
reloading verbatim every reboot — it only gets fixed if some later patch
happens to touch that exact field again.

`StateManager.revalidate()` closes that gap: it runs every function in
`VALIDATORS` against whatever's currently loaded (not a patch), corrects any
section that comes back different, and marks `state.changed` so the fix gets
autosaved back to `config.json` instead of recurring every boot. `application.py`
calls it once, right after `state.set_logger(logger)` (so a correction is
actually logged instead of happening silently before the logger exists):

```python
state.set_logger(logger)
state.revalidate()
```

### Top-level keys

The **Applies** column states how a change to the key takes effect: `live`
means it's picked up at runtime, `reboot` means it's only read at startup,
`boot only` means the key inherently only ever matters during boot.

| Key | Fields | Applies | Notes |
|---|---|---|---|
| `device` | `name` | live | Display name only |
| `leds` | `count`, `pin`, `on_after_boot`, `segmenting` | `count`/`segmenting` live; `pin` reboot; `on_after_boot` boot only | `count` is read fresh every frame by the `Renderer`, which reallocates the NeoPixel buffer if it changed — so it's changeable at runtime, no reboot needed (floor of 1, clamped in `StateManager`); `pin` is bound once at startup; `on_after_boot` controls whether the strip lights up on power-up or waits `off`; `segmenting: {"enabled": bool, "length": n}` splits the strip into repeating `length`-LED blocks for compatible modes — see [Animations](animations/index.md#segmenting) |
| `mode` | `current`, `brightness`, `speed`, `on`, `color`, `direction` | live | Runtime mode state: active mode name, global brightness/speed (1-100, clamped), on/off, global `color: [r, g, b]` (each 0-255, clamped) used by color-driven modes, and `direction` (`"forward"`/`"backward"`) — `"backward"` mirrors the rendered strip so animations run from the far end; applies to every mode except `off` — see [Animations](animations/index.md#direction) |
| `modes` | one entry per mode name | live | Each mode's own params, e.g. `runner: {"length": n}`, `off: {"fade_ms": n}` — see [Animations](animations/index.md) |
| `network` | `wifi.ssid`, `wifi.password`, `ap.ssid`, `ap.password` | reboot | Read once at boot, not reactive to config changes — saving new values only takes effect after a restart. Empty `wifi.ssid` disables Wi-Fi — and with it MQTT, which requires Wi-Fi — and goes straight to the fallback AP; a configured network the device can't reach after a few tries falls back to the same AP (`ap.ssid`/`ap.password`) — see [Channel internals](contributing/channels.md#network-channel) |
| `network` | `ap.retry_interval`, `ap.retry_quiet_period` | live | Seconds; while on the fallback AP, how often (`ap.retry_interval`, default `120`) the channel retries the configured network, gated by how long the AP must have been idle first (`ap.retry_quiet_period`, default `60`) — read fresh on every retry check, no restart needed — see [Channel internals](contributing/channels.md#network-channel) |
| `mqtt` | `enabled`, `server`, `port`, `user`, `password`, `base_topic`, `use_single_topic_for_state_update`, `ssl`, `ssl_params`, `certificate` (`validate`, `name`), `ntp_host` | live — session restarts | Disabled when `enabled` is `false`, `server` is empty, Wi-Fi is disabled, or (when `ssl` and `certificate.validate` are both true) the cert at `certs/<certificate.name>` isn't readable — fail-closed, no silent fallback to unverified TLS; `ssl: true` also triggers an NTP time sync (needed for TLS) before connecting; any change tears the session down (publishing `"offline"` on the old topic) and reconnects with the new config — see [Channel internals](contributing/channels.md#certificate-validation) |
| `button` | `pin`, `enabled` | `pin` reboot; `enabled` live | GPIO for the cover button; `enabled: false` makes the channel ignore presses |
| `webapi` | `wifi_access` | boot only | JSON API + Web UI server; read once at boot like `network.*` — `wifi_access: false` restricts the server to the device's setup AP only (never reachable over the configured Wi-Fi network), `true` (default) allows both — see [Channel internals](contributing/channels.md#web-api--web-ui-channel) |
| `system` | `default_mode`, `boot_to_config` | `default_mode` reboot; `boot_to_config` boot only | Boot modes — see [Boot modes](setup.md#boot-modes). `default_mode` is `"normal"` (default) or `"mqtt-ssl"` (validated in `StateManager`, invalid values dropped); `"mqtt-ssl"` boots without the Web API/UI so TLS gets the RAM, and falls back to `normal` unless MQTT is enabled with a server and `ssl: true`. `boot_to_config` is a one-shot flag: set by the ~5s button hold (via `application.reboot_to_config`), forces the next boot into config mode, and is cleared and saved back to disk immediately at that boot — so the restart after it returns to `default_mode` |
| `logging` | `enabled`, `level` | live | Disabled by default; `level` is one of `debug`/`info`/`warning`/`error`; both checked on every log call |
| `watchdog` | `enabled` | reboot | Hardware watchdog (see below); disabled by default, enable on production devices; checked once at startup — the RP2040 watchdog can't be disarmed once running anyway |

`runtime` is a further top-level key that appears once the device is running
(e.g. `runtime.network.wifi.connected`/`ip`) — it's written by channels, read
like any other state, but never persisted to disk.

## Watchdog

With `watchdog.enabled: true`, the heartbeat task in `src/application.py` arms the
RP2040's hardware watchdog (`machine.WDT`, 8s timeout — the hardware maximum
is ~8.3s) and feeds it every 500ms while toggling the onboard LED. If the
event loop ever stalls — a blocking call that never returns, a crashed
scheduler, wedged Wi-Fi chip state — the feed stops and the chip hard-resets
itself within 8 seconds, so a deployed device self-heals instead of hanging
until someone pulls the plug.

Things to keep in mind:

- **Keep it off during development** (`config.dev.json` sets
  `"watchdog": {"enabled": false}`). The RP2040 watchdog cannot be disarmed
  once started — dropping to the REPL (Ctrl-C) stops the heartbeat, so an
  armed watchdog reboots the board out from under your session 8s later.
- Any single synchronous operation on the event loop must finish well under
  the 8s timeout — flash writes and `gc.collect()` are comfortably inside
  that, but it's another reason every network call must have a bounded
  timeout (see the NTP sync in `src/channels/mqtt.py`).
- A watchdog reset looks like a power cycle: the device reboots cleanly,
  reloads `config.json`, and resumes the persisted mode. The MQTT broker
  publishes the last-will `"offline"` message if a session was up.

## Web installer

The [Web installer](installer.md) is a static page under `docs/installer/`
(plain HTML/JS, no Jekyll front matter, so it's copied to the site verbatim
and kept out of the nav). It runs entirely in the browser using **WebUSB**
(to flash MicroPython) and **Web Serial** (to push files over the REPL), so
it's Chromium-desktop only.

### Version picker: installs live from GitHub, no build/release step

Two dropdowns at the top of the page choose the git ref to install from.
**Install from** picks the kind of ref — *Released version* (the project's
[tags](https://github.com/psp515/PicoController/tags), `fetchTagList`,
newest first) or *Branch (unreleased)* (`fetchBranchList`, default branch
first then alphabetical) — and **Version to install** lists the refs of that
kind, with the first one preselected. Releases are the default; with no tags
published yet the page falls back to the branch list automatically.

Picking a ref calls `source.js`'s `fetchSource(ref)`, which lists that ref's
file tree via the GitHub API and pulls each file's bytes from
`raw.githubusercontent.com`, keeping only the device files
(`isDeviceFile`/`dirsFor`). There is nothing to build or publish ahead of
time: tagging a commit — or just pushing a branch — is enough for it to show
up. Everything is fetched from GitHub; there is no local/offline install
path.

Firmware comes from `MICROPYTHON_VERSION` read at the selected ref
(`fetchFirmwarePin`) and nowhere else — a ref cut before that file existed
falls back straight to `DEFAULT_FIRMWARE_URL`, a hardcoded `v1.29.0` URL in
`const.js` bumped by hand alongside the repo-root `MICROPYTHON_VERSION`
file, so an old tag always resolves to *something* installable
(`resolveFirmwarePin` in `app.js`, the fallback logged as a note). No other
ref's pin is ever borrowed: what you install is either that ref's own pin or
the installer default.

Because the `.uf2` is written straight to flash, the pin's URL must start
with `FIRMWARE_URL_PREFIX` (`https://micropython.org/resources/firmware/`) —
a URL anywhere else is a hard error, not a fallback
(`assertAllowedFirmwareUrl` in `source.js`, re-checked in `app.js` right
before `flashUf2`). `MICROPYTHON_VERSION` may hold a second
whitespace-separated field, a SHA-256 hex digest of the `.uf2`; when present
it's checked against the download (`sha256Hex` in `net.js`) before anything
is flashed. `parseUf2` also drops any block whose declared payload size is
larger than the 476-byte UF2 data area.

Every ref pre-fills the config
form from `FALLBACK_DEFAULTS`, a small hardcoded object in `app.js`
mirroring `DEFAULTS`' installer-relevant fields — there's no `defaults.json`
to fetch anywhere.

Flashing over WebUSB opens the board with an 8s timeout
(`OPEN_TIMEOUT_MS` in `app.js`) — without it, a missing WinUSB driver (the
common case on Windows; see [the installer page](installer.md#if-something-goes-wrong))
leaves `USBDevice.open()` pending indefinitely with no error and the button
stuck disabled.

Each wizard step (`step-firmware`/`step-connect`/`step-install`) gets a
green border + "✓ ..." banner on success or a red border + "✗ ..." banner on
error, via `setStepStatus()` in `app.js` — so a failed step is obvious and
it's clear which one to retry. On a successful install, the banner also
appends Wi-Fi-specific next steps (`postInstallGuidance()` in `app.js`):
find the device's IP on your router if Wi-Fi was configured, or connect to
its own setup network (`http://192.168.4.1/`) if it wasn't.

There is **no build or release step for a tagged/pushed version** — nothing
runs before a tag exists, nothing gets published after. Picking a tag or
`main` in the picker is enough; the page fetches everything it needs live.

### Page modules (`docs/installer/`)

| Module | Responsibility |
|---|---|
| `const.js` | every hardcoded endpoint, id and limit: `OWNER`/`REPO`, the GitHub API/raw bases and their `apiUrl`/`rawUrl` builders, `DEFAULT_FIRMWARE_URL`, the USB vendor/product ids, `CERT_MAX_BYTES`, `DEFAULT_BRANCH` |
| `source.js` | lists tags (`fetchTagList`) and branches (`fetchBranchList`/`orderBranches`), resolves and validates a ref's firmware pin (`fetchFirmwarePin`/`parseFirmwarePin`/`assertAllowedFirmwareUrl`), and assembles the `{dirs, files}` bundle object straight from any git ref (`fetchSource`) via the GitHub tree + raw file API |
| `net.js` | the generic `fetchBinary`, `toBase64`/`fromBase64` and `sha256Hex` helpers |
| `uf2.js` | parse a `.uf2` into coalesced `{addr, bytes}` flash runs (RP2040 family only) |
| `picoboot.js` | WebUSB PICOBOOT client — `EXCLUSIVE_ACCESS` / `EXIT_XIP` / `FLASH_ERASE` / `WRITE` / `REBOOT` in 4 KB sectors |
| `repl.js` | Web Serial raw-REPL: enter raw mode, `exec()` a snippet, then push each file in ~1 KB base64 chunks via `ubinascii.a2b_base64`, verifying each by reading it back and comparing an on-device `hashlib.sha256` digest; also `isValidCertName` |
| `app.js` | wires the version picker, the four wizard steps, per-step status, the progress bars, and the log |

`uf2.js`, `dirsFor`/`isDeviceFile`/`parseFirmwarePin`/`assertAllowedFirmwareUrl`
in `source.js`, and `splitB64`/`isValidCertName` in `repl.js` are pure and
unit-tested (`tests/installer/*.test.mjs`, run with `node --test`). The
USB/serial paths and the live GitHub fetch need real hardware/network and
aren't covered by CI — test them against a board.

### Testing the page locally

WebUSB and Web Serial need a secure context, which `http://localhost` counts
as — no HTTPS needed, but `file://` will not work. Serve the repo and open
the page:

```
python -m http.server 8000
```

then `http://localhost:8000/docs/installer/`. The page always installs from
GitHub — the ref you pick in the version picker, never your working tree —
so to try uncommitted changes, push them to a branch and select it under
*Install from → Branch*.

Without a board you can still check the wizard, the ref listings and source
downloads, and the form pre-fill. The flash + install steps need a real
Pico W (hold BOOTSEL for step 1) and Chromium.

### Config the installer writes

The form in `index.html` mirrors most of the real config page
(`src/webui/static/config.html`), grouped the same way, behind `<details>`
for anything past the always-visible basics (device name, Wi-Fi, LED
count/pin, watchdog): setup-network (AP) name/password, LED
on-after-boot/segmenting, MQTT (server/port/credentials/topic/single-topic,
TLS + NTP host + certificate validation + a certificate file upload),
button/IR/Web-UI-Wi-Fi-access enablement, boot mode, and logging. `app.js`'s
`readForm()` reads it into a flat object, `configJson()` in `repl.js` nests
it back into the real `config.json` shape and `pushBundle()` writes it
alongside the source files over the REPL — nothing is conditionally
omitted, since writing a field's own default value is a no-op through
`Storage`'s merge. `configJson`'s key paths are checked against the real
`DEFAULTS` in `tests/installer/config.test.mjs` (via `python -c
"...defaults..."`), so a typo'd key fails CI instead of silently writing a
field the device never reads.

**Certificate upload**: when "Validate broker certificate" is checked, a
drop zone (`#cert-dropzone`) appears and becomes required (enforced in
`isConfigValid()`, same 16 KB cap as `CERT_MAX_BYTES` in
`src/channels/webapi.py`). It wraps a hidden `<input type="file">`
(`#mqtt-cert-file-input`) — clicking or `Enter`/`Space` on the zone opens
the native picker, and a real drop event populates the same input via
`DataTransfer` (`certFileInput.files = event.dataTransfer.files`), so
`readCertFile()`/`isConfigValid()` don't need to know which path was used.
On install, `app.js`'s `readCertFile()` reads it into base64; `pushBundle()`
(passed as `certFile`) creates `certs/` on the device and writes it to
`certs/<filename>` alongside the other files, and `configJson()` sets
`mqtt.certificate.name` to that filename — the same file
`_certificate_disabled_reason()` in `src/channels/mqtt.py` checks for at
connect time. The filename must match `^[A-Za-z0-9._-]{1,64}$` and not be
`.`/`..` (`isValidCertName` in `repl.js`, checked in `readCertFile()`,
`isConfigValid()` and `pushBundle()`) — the device side enforces the same
rule in `_valid_cert_name()` (`src/channels/webapi.py`).

**Wi-Fi scan**: the *Scan for networks* button runs a raw REPL snippet
(`import network; ...WLAN(STA_IF).scan()...`) over the already-open step-2
connection and fills `#wifi-ssid-options`, a `<datalist>` the SSID `<input
list=...>` references — the same combo-box pattern
`src/webui/static/config.html` uses, so typing a name by hand still works.
This only needs MicroPython's built-in `network` module, not the installed
controller app, so it works even before step 4 has run.

Adding a field means touching `index.html`, `readForm`/`FALLBACK_DEFAULTS`
in `app.js`, `configJson` in `repl.js`, the "Top-level keys" table above,
and [the installer page](installer.md) if it's user-facing.

## Extending the device

- [Channel internals](contributing/channels.md) — add a new way to control the
  device (a new input path)
- [Animation internals](contributing/animations.md) — add a new lighting mode
