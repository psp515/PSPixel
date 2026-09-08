---
title: Web UI / Web API
description: "The dashboard and configuration page PSPixel serves over the network."
---

A browser-based dashboard and configuration page, served by the device
itself — no app, no cloud account, nothing to install. It works over your
normal Wi-Fi network, and also over the device's own
[setup network](network.md#cant-connect-the-device-opens-its-own-setup-network)
if it can't join yours, so there's always a way in.

## Reaching it

Open the device's IP address (or `http://192.168.4.1/` if you're connected to
its setup network) in a browser:

- **`/`** — the dashboard: current mode, on/off, brightness, speed, color.
- **`/modes`** — settings specific to each lighting mode (e.g. the runner's
  length, the off-fade duration).
- **`/config`** — device/network/system configuration, grouped into three
  sections: **Default** (device, Wi-Fi, LEDs), **Channels** (MQTT, button,
  IR remote, Web API), and **Others** (logging, watchdog), plus a separate
  **Device control** section with the restart button. Changes take effect as
  soon as you hit Save — most settings apply immediately, a few need a
  restart (see the **Applies** column in the
  [Development guide](../development.md#top-level-keys)) — **Wi-Fi network
  settings always need a restart**, see [Network](network.md).

Some sections have their own action button beyond Save:

- **LEDs → Test** lights the strip using whatever count is currently typed
  in the form, so you can confirm it before saving.
- **Wi-Fi → Network → Scan for networks** lists nearby networks with signal
  strength as suggestions on the Network name field — useful for getting the
  exact name right, especially while connected to the device's own setup
  network.
- **MQTT → SSL → Certificate → Upload certificate** sends a CA certificate
  file straight to the device's `certs/` folder and selects it in the
  Certificate name dropdown for you — see
  [Secure connections](mqtt.md#secure-connections).

Both pages are just a thin layer over the same JSON API every other
integration uses (`GET`/`POST /json/state`) — nothing you can do here that
you couldn't do with a raw HTTP request, it's just easier.

## Settings

Configured in the `webapi` section of `config.json`:

| Setting | Default | What it does |
|---|---|---|
| `webapi.wifi_access` | `true` | Set to `false` to restrict the dashboard/API to the device's own [setup AP](network.md#cant-connect-the-device-opens-its-own-setup-network) — they stay unreachable over your configured Wi-Fi network, but always reachable on the setup AP. `true` (default) allows both. |

:::caution
**Changes need a restart.** Like Wi-Fi credentials, saving a new
`webapi.wifi_access` value doesn't take effect immediately — restart the
device (restart button or power cycle) to apply it. This is deliberate:
it means saving this setting can never immediately lock you out of the
page you just used to change it.
:::

:::caution
**Not available in mqtt-ssl mode.** With `system.default_mode` set to
`"mqtt-ssl"`, the dashboard and JSON API aren't started at all — that's
the point of the mode, freeing memory for the encrypted MQTT connection.
Hold the device button ~5 seconds to restart into
[config mode](../setup.md#boot-modes), where the dashboard is available on
the setup network. The **Restart device** button also saves any pending
config changes before rebooting.
:::

:::note
How the server, routing, and static-file serving work internally is
covered in
[Channel internals](../contributing/channels.md#web-api--web-ui-channel).
:::
