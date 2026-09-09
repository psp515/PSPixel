# Project

PSPixel — a MicroPython ARGB LED controller. (The GitHub repo slug stays
`psp515/PSPixel`; only the product/display name is PSPixel.)

## Requirements

### Current

- primarly it is designed to handle WS2812B LED 5V
- Available communication protocols for configuration
  - NEC Reveiver
  - Button on the cover
  - MQTT Protocol
  - Web API + a browser Web UI (dashboard, modes page, full-config page)
    served by the device itself
- If the configured Wi-Fi network is empty or unreachable, the device falls
  back to its own temporary access point so the Web UI is always reachable
  to fix credentials. If a network was configured but just unreachable, the
  device keeps periodically retrying it in the background while on the AP
  (quietly, so it doesn't interrupt an active setup session) — see
  [Configuration](#configuration) and `docs/src/content/docs/channels/network.md`
- Controller Mircopython code should be as simple as possible to understand without complex elements
  - for that aplication might use python abstractions to abtract elements like modes communications and so on
- Controller should support multiple Animation Modes and animations should be easilly extensible
- Configuration should be dynamic - device reflects changes after hitting save on webui or after api call,
  except `network.wifi.ssid`/`network.wifi.password` which need a restart
  (see Configuration)
- Configuration should be presited between on and off in .json file (also runtime data like current mode and mode specs)
- if device will be turned off there should be posted message to mqtt broker about last will
- provide option whether to tunr on led after powering up 
- Three boot modes resolved once at boot (`src/application.py`), because the Pico W
  can't hold microdot/webapi and an MQTT TLS session in RAM at once (mbedTLS
  handshake needs ~33KB contiguous heap): **normal** (all channels),
  **mqtt-ssl** (`system.default_mode: "mqtt-ssl"`, no Web UI/API loaded;
  falls back to normal unless mqtt is enabled with a server and `ssl: true`),
  **config** (one-shot: setup AP + Web UI/API + button, no mqtt; entered by
  holding the button ~5s — LEDs turn off as feedback, 1s later the device
  restarts into config mode regardless of release; the `system.boot_to_config`
  flag is cleared and saved immediately at that boot, so the next restart
  returns to `default_mode`)
- lightinginh modes:
  - white mode
  - static color mode
  - rainbow effect
  - running few leds around the LEDS
  - pspixel mode - the project logo on the strip (gradient base, five pulsing dots, running comets)
- on / off function for device LEDS

### Future directions

If introducing helpfull abstraction will not be problematic it is advised to apply this abstraction.
- in future there will be more like WS2811 LED 12V support
- introducing more modes 

### Selected Libraries 

- for mircopython connection use mqtt_as
- uasyncio for main loop 

## Hardware 

### Current

- Board: Raspberry Pi Pico W
- WS2812B data line: GP0 
- Optional - IR receiver (NEC protocol, remote control): GP2, interrupt-driven
- Optional - Push button (on cover): GP3, active low, internal pull-up, debounced in software
- LED count: 144 default, configurable in `config.json`

### Future directions

- Board: ESP32

## Architecture rules

- Single `uasyncio` event loop on core 0. Do NOT use `_thread` or core 1.
- Animation modes live in `src/animations/`, one class/function per mode, registered in
  a mode table (dict/list). Adding a new animation must not require touching the core loop.
- IR receiver: pin IRQ records edge timestamps only. ISRs must not allocate memory,
  print, or decode. NEC decoding happens later in a uasyncio task
  (pattern: Peter Hinch `micropython_ir`).
- All inputs (IR, button, MQTT, Web API) translate into the same command/event
  objects feeding one shared application state. No input path talks to the LED
  strip or renderer directly. State Manager class manages channels 
- Communication channels (MQTT, Web API, IR, button) are abstracted behind a common
  interface so new channels can be added without changing core logic. (`src/channels/`)
- The network channel (`NetworkChannel`) is the radio's single owner — both
  `STA_IF` and `AP_IF`.
  No other code drives either interface directly; requests from other
  channels (e.g. the Web API's scan button) go through shared state, not a
  direct reference to `NetworkChannel` — mqtt uses `ExternalWifiMQTTClient`
  (subclass in `src/channels/mqtt.py`) so `mqtt_as` never connects/disconnects
  Wi-Fi itself, it only waits for the radio to be up. The AP is a fallback
  only, never run concurrently with an active station *connection attempt*
  (shared single-radio channel constraints) — the deliberate exceptions are
  a Wi-Fi scan, which briefly reactivates the station interface even while
  the AP is up (needed to pick a network's exact SSID while on the setup
  network), and the periodic AP-to-station retry (see below), which briefly
  drops the AP to attempt reconnecting to the configured network — see
  `docs/src/content/docs/contributing/channels.md`.
- The Web API channel keeps JSON API routes (`src/channels/webapi.py`) and
  static Web UI routes (`src/webui/webui.py`) in separate modules sharing one
  `Microdot` app/port, so either can change without touching the other.
- Application should start as quickly as possible and cahnnels should start concurrenctly
- `main.py` is a thin starter only (sys.path setup + `asyncio.run`); all
  application logic lives in `src/application.py`, which builds the channel
  list per boot mode (see Requirements) with **lazy imports inside `main()`**
  — a skipped channel's module (microdot, mqtt_as) must never be imported in
  that mode. No module-top channel imports in `application.py`, and no import
  chain from always-loaded modules into `channels.webapi`/`channels.mqtt`
  (that's why `CERTS_DIR` lives in `src/storage.py`, not `channels/mqtt.py`).
- Every reset path (`application.reboot_to_config`, webapi restart endpoint) must
  save config synchronously via `Storage().save(...)` before `machine.reset()`
  — the debounced autosave (2s) loses writes made just before a reset.

## Selected libraries

- `uasyncio` — main loop and all tasks
- `mqtt_as` (Peter Hinch, micropython-mqtt) — async, resilient MQTT client
- `micropython_ir` (Peter Hinch) — NEC IR decoding
- Do not add other dependencies without asking. Never use blocking `umqtt.simple`/`umqtt.robust`.

## Configuration

- Persisted in `config.json` on the device filesystem; includes runtime state
  (current mode, mode parameters, brightness) so state survives power cycles.
- for development `config.dev.json` should be used 
- Changes are dynamic: applying config via Web API or WebUI "save" takes effect
  immediately, no reboot, for most sections. This includes `mqtt.*`
  (channel tears the session down, publishes `offline` on the old topic, and
  reconnects with the new config). `network.wifi.ssid`/`network.wifi.password`
  are the exception — see below.
- `system.default_mode` (`"normal"`/`"mqtt-ssl"`, validated in `StateManager`)
  is read once at boot (reboot to apply); `system.boot_to_config` is a
  one-shot boot flag, never a lasting setting — cleared and re-saved to disk
  immediately when config mode boots.
- Boot-only exceptions: pin assignments (`leds.pin`, `button.pin`, `ir.pin` —
  pin changes imply rewiring, reboot is free), `watchdog.enabled` (RP2040 WDT
  can't be disarmed once armed), `leds.on_after_boot` (boot-only by nature),
  `network.wifi.ssid`/`network.wifi.password` — read once at boot; saving new
  values from the Web UI has no live effect, the device must be restarted
  (restart button or power cycle) to try them. This is deliberate: there's no
  auto-reconnect/revert machinery to reason about, and the AP fallback below
  is always the safe way back in if new credentials are wrong — and
  `webapi.wifi_access`, for the same reason: it's read once at boot so
  saving a new value can never immediately cut off the page that just
  saved it.
- Every channel except wifi and webapi has an `enabled` flag (`mqtt.enabled`,
  `button.enabled`, `ir.enabled`, default true, dynamic): disabled channels
  skip their work loop and just sleep/wait. Wifi's "disabled" state is an
  empty `ssid`; a disabled wifi also disables mqtt (mqtt requires non-empty
  `network.wifi.ssid`). Empty `ssid`, and a configured network the device
  can't reach after a few tries, both fall back to the same temporary access
  point (`network.ap.ssid`/`network.ap.password`). While on that AP, the
  device periodically retries the original network in the background
  (`network.ap.retry_interval` seconds, default 120) instead of staying on
  the AP forever — but only once at least `network.ap.retry_quiet_period`
  seconds (default 60) have passed since the last Web UI/API request made on
  the AP, so an active setup/recovery session on the AP isn't interrupted
  mid-use (a retry attempt briefly drops the AP, since station and AP share
  one radio — see
  [Channel internals](docs/src/content/docs/contributing/channels.md#network-channel)).
  Both retry settings are dynamic, no restart needed. `webapi.wifi_access`
  (boot-only, see above) doesn't mean "off" the same way the other channels'
  flags do: `false` restricts the Web UI/API to the device's setup AP only —
  never reachable over the configured Wi-Fi network — while `true` (default)
  allows both; the server itself is never fully disabled, since the setup AP
  must always stay reachable. The Web UI can scan for nearby networks
  (`POST /json/wifi/scan`, mediated through `NetworkChannel` since it's the
  radio's sole owner — see `docs/src/content/docs/contributing/channels.md`).
- Every config key must be documented in the docs config tables — the
  user channel page's "Settings" table and/or the "Top-level keys"
  table in `docs/src/content/docs/development.md` — with its default and what it's used for.
  The "Top-level keys" table (developer reference) also carries an
  **Applies** column stating whether a change takes effect live or requires
  a reboot. Adding or changing a config key means updating those tables in
  the same change.
- Writes: temp file + `os.rename()` (atomic, protects against corruption).
- Debounce/batch saves — never write flash per frame or per slider tick.
- Missing or corrupt file → fall back to built-in defaults and recreate the file.
- for quick acces keep dict in memory so fields can be easily accessible via `state["value1"]["value2"]`

## Logging

- Use the `Logger` class from `src/logger/` (injected via constructor), never `print()`
  in application code — output goes through appenders (`ConsoleAppender`, future file appender).
- Config-driven via the `logging` config section; disabled by default.
- Message parameters use positional placeholders, formatted lazily (skipped when disabled):
  `logger.info("network", "connected ip {0}", ip)` — no f-strings, no named `{value}` kwargs.

## Web API

- Async HTTP server (e.g. microdot) as a uasyncio task; JSON request/response.
- Future: static WebUI served by the same server; keep API and UI serving separate modules.

## MicroPython constraints

- This is MicroPython, not CPython: no `typing` at runtime, no heavy stdlib imports.
- Avoid per-frame heap allocations — reuse preallocated `bytearray` pixel buffers.
- Use `time.ticks_ms()` / `time.ticks_diff()` for timing, never naive subtraction.
- Use `micropython.const()` for constants; keep modules small (RAM limits).
- No busy-wait `time.sleep()` inside tasks — always `await asyncio.sleep_ms()`.

## Code style

- Simple to understand. Prefer plain classes and dicts over
  metaprogramming, decorators-heavy designs, or deep inheritance.
- Introduce an abstraction only when it clearly helps extensibility
  (animations, comm channels, LED drivers) — otherwise keep it flat.
- Don't comment 

## Planning work (IMPORTANT)

When planning any task (plan mode, a todo list, or a multi-step change),
structure the plan as a sequence of **small steps**, each independently
verifiable. Never plan one big "implement everything, then test" step.

Each step follows this cycle:

1. **Add the test first, when possible** — if the new behavior can be
   expressed as a test before the code exists (new function, new validation
   rule, new channel behavior), write the failing test first, then make it
   pass. If a test-first approach isn't practical (e.g. hardware-bound code
   needing new stubs, large refactors), write the test in the same step,
   immediately after the change — never defer tests to a later step.
2. **Make one small code change** — one behavior, one module, one concern.
3. **Check tests** — run `python -m pytest` (plus `python -m ruff check src
   main.py` and `python -m compileall -q src main.py`) after every step, not
   only at the end.
4. **Fix failures before moving on** — a step is done only when lint,
   compile-check, and tests are green. Don't start the next step on top of a
   red suite.

Steps should be small enough that a failure clearly points at the change
that caused it. Docs/CLAUDE.md updates required by the change (see
[Keeping this file and the docs in sync](#keeping-this-file-and-the-docs-in-sync))
are part of the plan too — as their own step, in the same change.

## Development

Mirrors `.github/workflows/ci.yml` (lint → build → test → installer → docs),
runs on CPython/Node, not on-device.

- Lint: `python -m ruff check src main.py`
- Compile-check (syntax only, all source files): `python -m compileall -q src main.py`
- Tests: `python -m pytest` (pythonpath is `src` and `lib`, configured in `pyproject.toml`; tests live in `tests/`)
- Installer JS: `node --test tests/installer/*.test.mjs`
- Docs build: `cd docs && npm ci && npm run build` (Astro + Starlight)
- Always invoke tools via `python -m` (`ruff`, `pytest`) — bare executables are not on PATH here.

## Web installer

- Browser-based flash + install for a blank Pico W, served from GitHub Pages at
  `…/PSPixel/installer/`. The app lives in `docs/public/installer/`
  (plain static HTML/JS in the Astro site's `public/`, copied verbatim,
  outside Starlight — linked from the `web-installer` doc page). Chromium
  desktop only (WebUSB + Web Serial).
- The page's **version picker** is two dropdowns: *Install from*
  (Released version / Branch) and the ref list itself — tags
  (`GET /repos/.../tags`, newest first, the default) or branches
  (`GET /repos/.../branches`, default branch first then alphabetical), with
  the first entry preselected and an automatic fall back to branches when no
  tags exist. Picking a ref assembles the install bundle **live** from it via
  the GitHub API (file tree + `raw.githubusercontent.com`), so nothing needs
  building or releasing ahead of time.
- Firmware is resolved from the selected ref's own `MICROPYTHON_VERSION`
  file only; a ref from before that file existed falls back to the hardcoded
  `v1.29.0` `DEFAULT_FIRMWARE_URL` in `const.js` (`app.js`'s
  `resolveFirmwarePin`) — never to another ref's pin. Bump that constant by
  hand alongside the repo-root `MICROPYTHON_VERSION` file so it doesn't
  drift.
- The firmware `.uf2` is written straight to flash, so its URL must start
  with `FIRMWARE_URL_PREFIX` (`https://micropython.org/resources/firmware/`,
  in `const.js`) — a pin pointing anywhere else is a hard error, never a
  fallback (`source.js`'s `assertAllowedFirmwareUrl`, re-checked in `app.js`
  before flashing). `MICROPYTHON_VERSION` may carry an optional second field
  (whitespace-separated): a SHA-256 hex digest of the `.uf2`, verified
  against the download before `flashUf2` (`source.js`'s `parseFirmwarePin`).
- Every file pushed over the REPL (source files, `config.json`, the
  certificate) is verified by reading it back on-device and comparing a
  `hashlib.sha256` digest to the bytes that were sent (`repl.js`'s
  `pushBundle`) — not just a size check.
- Certificate filenames must match `^[A-Za-z0-9._-]{1,64}$` and not be
  `.`/`..` (`repl.js`'s `isValidCertName`, mirrored by
  `src/channels/webapi.py`'s `_valid_cert_name`) — they become a device path
  and a Python string literal.
- Everything the installer needs is fetched from GitHub at the selected ref.
  There is **no local/offline install path** and no build or release step —
  nothing to run before tagging, nothing to publish after. To test
  uncommitted work, push it to a branch and pick it under *Install from →
  Branch*.
- All hardcoded endpoints, ids and limits live in `docs/public/installer/const.js`
  (`OWNER`/`REPO`, GitHub API + raw bases with the `apiUrl`/`rawUrl`
  builders, `DEFAULT_FIRMWARE_URL`, `FIRMWARE_URL_PREFIX`, USB vendor/product
  ids, `CERT_MAX_BYTES`, `DEFAULT_BRANCH`) — no URL literals in the other
  modules.
- `MICROPYTHON_VERSION` (repo root) pins the exact firmware `.uf2` URL, with
  an optional whitespace-separated SHA-256 of that file. Bump it deliberately
  — the installer reads it straight from the selected ref for every version,
  live.
- Installer flow: WebUSB PICOBOOT flash (`picoboot.js`/`uf2.js`) with a
  drag-`.uf2` fallback → Web Serial raw-REPL file push (`repl.js`) → write
  `config.json` from the form → reboot. See the `development` doc page.
- The config form mirrors most of `src/webui/static/config.html`, grouped
  the same way behind `<details>` for everything past the basics (device
  name, Wi-Fi, LED count/pin, watchdog): setup network, LEDs, MQTT (incl.
  TLS/certificate validation, with a matching certificate file upload —
  written to `certs/<name>` alongside the other files during install,
  mirroring `src/channels/webapi.py`'s `_handle_certificate_upload`), the
  button/IR/webapi Wi-Fi-access toggles, boot mode, logging. Every value is
  always written (harmless no-op through `Storage`'s merge when it matches
  `DEFAULTS`) — `configJson`'s key paths are checked against real `DEFAULTS`
  in `tests/installer/config.test.mjs` (which imports from
  `docs/public/installer/`). Adding a form field means updating the
  `web-installer` doc page, the form in `docs/public/installer/index.html`,
  and `readForm`/`FALLBACK_DEFAULTS` in `app.js` + `configJson` in `repl.js`.

## Documentation (GitHub Pages)

- `docs/` is an **Astro + Starlight** project (`docs/astro.config.mjs`,
  `docs/package.json`). `site: https://psp515.github.io`, `base: /PSPixel`.
  Published by **GitHub Actions** (`.github/workflows/deploy-docs.yml`,
  `withastro/action` → `actions/deploy-pages`) on push to `main` touching
  `docs/**`. The repo's Pages source must be set to "GitHub Actions" in
  Settings. CI also builds the site on every push/PR (`docs-build` job).
- Local preview (needs Node 22):
  ```
  cd docs
  npm install
  npm run dev
  ```
  then open http://localhost:4321/PSPixel/. `npm run build` for a
  production build.
- **Content** is Markdown in `docs/src/content/docs/` — one Starlight
  collection. Frontmatter is `title` + `description` (Starlight renders the
  `title` as the page H1, so the body has no `# heading`). Callouts use
  `:::note` / `:::caution` asides. Cross-links between pages are relative
  `.md` links (`../setup.md#anchor`); a small rehype plugin in
  `astro.config.mjs` (`rehypeDocLinks`) resolves them to final routes —
  Astro 7's own resolver drops `#fragments`.
- **Two sidebars** via the `starlight-sidebar-topics` plugin, configured in
  `astro.config.mjs`: a **User guide** topic (`setup`, `web-installer`,
  `channels/*`, `animations`) and a **Developer guide** topic (`development`,
  `contributing/*`). Each page shows only its topic's list, with a switcher.
  Adding a page = create the `.md` and add its slug to the right topic's
  `items` array.
- The site **home page is `docs/src/pages/index.astro`** — a hand-built dark
  landing page (split hero + section cards), a plain Astro page *outside*
  Starlight (no sidebar). The Starlight header logo links back to it (site
  root). Editing it means editing that `.astro` file directly; keep its
  palette in step with the web installer (`docs/public/installer/style.css`).
  Card links use `import.meta.env.BASE_URL`.
- The **web installer app** is static files in `docs/public/installer/`,
  served verbatim at `…/PSPixel/installer/` (see the Web installer section
  above). Never a Starlight page. `astro dev` does not serve `index.html`
  for a bare `public/` directory URL — in dev open `…/installer/index.html`;
  `npm run preview` and the deployed site serve `…/installer/` directly.
- Assets: `docs/src/assets/` (imported/optimised, e.g. `schema.png`,
  `logo.svg`); `docs/public/` (verbatim, e.g. `favicon.svg`, the installer).
- Theme accent is tuned in `docs/src/styles/custom.css` to match the landing
  page / installer blue. Starlight keeps its light/dark toggle for doc pages;
  the landing page is dark-only by design.

## Session-specific guidance

- Skills are stored in `.claude/skills/` in this repo (tracked in git) so they
  persist across machines via GitHub instead of only living in the global
  `~/.claude` config.
- Invoke the `caveman` skill at the start of every chat in this project by
  default, no trigger phrase needed. Keep it active per its own persistence
  rules (stays on until user says "stop caveman" / "normal mode").
- Don't remove added comments by developers - they will start with U

## Keeping this file and the docs in sync

Whenever a change affects something described in this file or in `docs/` —
a new/changed config field, a new mode or channel, a new architecture rule,
a behavior change (e.g. what's now dynamically updatable, what gets
validated, what a channel exposes) — update both **in the same change**,
not as a follow-up:

- Update the relevant section of this file (`.claude/CLAUDE.md`) if the
  change affects a requirement, architecture rule, or convention stated
  here.
- The docs are split into two tracks (two Starlight sidebars) and changes
  must respect it. All pages live under `docs/src/content/docs/`:
  the **User guide** topic — `setup.md`, `web-installer.md`, `channels/*.md`,
  `animations/index.md` — explains use, configuration and behavior in plain
  language, with **no implementation details** (no internal method names,
  constants, or code walkthroughs); the **Developer guide** topic —
  `development.md`, `contributing/index.md`, `contributing/channels.md`,
  `contributing/animations.md` — holds the architecture and all internals.
  Put user-visible behavior on the user page, implementation on the
  developer page, and cross-link between them (relative `.md` links).
- Update the relevant page(s) under `docs/src/content/docs/` — see
  [Documentation (GitHub Pages)](#documentation-github-pages) above for
  frontmatter and how to register a new page in a topic sidebar.
- If a change only affects internal implementation with no user- or
  contributor-visible behavior change, no doc update is needed — don't pad
  docs with internal detail no one reading them would act on.
