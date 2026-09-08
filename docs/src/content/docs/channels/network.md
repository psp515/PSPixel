---
title: Network
description: "How PSPixel joins your Wi-Fi and falls back to its own setup network."
---

Wi-Fi isn't something you control the device *with* — it just keeps the device
connected to your network so the [MQTT channel](mqtt.md) and the [Web
UI](webapi.md) can reach it.

## Setting it up

Put your network name and password in `config.json`, or use the Wi-Fi
section of the [Configuration page](webapi.md):

| Setting | Default | What it does |
|---|---|---|
| `network.wifi.ssid` | `""` | Your Wi-Fi network name. Leave it empty to turn Wi-Fi off — which also turns MQTT off, since MQTT needs the network. |
| `network.wifi.password` | `""` | Your Wi-Fi password. |
| `network.ap.ssid` | `"PSPixel"` | Name of the device's own setup network (see below). |
| `network.ap.password` | `"Pico123456!"` | Password for the setup network. Leave it empty for an open (no password) network. |
| `network.ap.retry_interval` | `120` | Seconds between automatic retries of your Wi-Fi network while the device is on its setup AP. |
| `network.ap.retry_quiet_period` | `60` | Minimum seconds of no Web UI/API activity on the setup AP before a retry is attempted, so an active setup session isn't interrupted. |

:::caution
**Changes need a restart.** Unlike most settings, saving a new
`network.wifi.ssid`/`network.wifi.password` (or `network.ap.ssid`/
`network.ap.password`) doesn't take effect immediately — use the restart
button on the [Web UI](webapi.md), or power-cycle the device, to actually
try the new credentials. This is deliberate, not a bug: it keeps the
network channel simple, and the setup network below is always there as a
safe way back in if the new credentials turn out to be wrong.
:::

## Can't connect? The device opens its own setup network

If no `network.wifi.ssid` is set, or the device can't join the one that is
(wrong password, network unreachable), it opens a temporary Wi-Fi network of
its own so you can still reach it. It tries a few times before giving up and
opening the setup network.

If a network *was* configured but just unreachable, the device doesn't give
up on it for good: while on the setup network, it periodically retries your
Wi-Fi network in the background (every `network.ap.retry_interval` seconds,
2 minutes by default) and switches back automatically the moment it
succeeds — no restart needed. To avoid yanking the setup network out from
under you mid-configuration, it waits until the setup network has been
quiet (no Web UI/API requests) for at least `network.ap.retry_quiet_period`
seconds (1 minute by default) before trying — a retry briefly drops the
setup network for the duration of the attempt, since the device only has
one radio. If no `network.wifi.ssid` is set at all, there's nothing to
retry, so the setup network just stays up.

Connect a phone or laptop to that network, then open the device's
[Web UI](webapi.md) in a browser at `http://192.168.4.1/` to fix your Wi-Fi
settings — if you're changing credentials, restart the device to try them;
if you're just waiting for your existing network to come back, no action is
needed.

Not sure of your network's exact name? The Wi-Fi → Network section of the
[Configuration page](webapi.md) has a **Scan for networks** button; nearby
networks (with signal strength) then show up as suggestions on the Network
name field — handy while connected to the setup network.

## Good to know

- **Config mode is setup-network only.** After the ~5s button hold restarts
  the device into [config mode](../setup.md#boot-modes), it opens the setup
  network directly and never tries your configured Wi-Fi — so the dashboard
  is always at the predictable `http://192.168.4.1/` while you reconfigure.
- **Automatic reconnect.** If an established connection drops (router
  reboot, brief outage), the device keeps retrying with the *same*
  credentials until it's back online — no restart needed for that. A
  restart is only needed after you change the credentials themselves.
- **Wi-Fi settings can't be changed over MQTT**, only by editing the config
  or through the Web UI.

:::note
The connect-and-reconnect logic is documented in
[Channel internals](../contributing/channels.md#network-channel).
:::
