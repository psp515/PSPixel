---
title: MQTT
description: "Control PSPixel and watch its state from Home Assistant, Node-RED, or any MQTT client."
---

MQTT lets anything on your network — Home Assistant, Node-RED, a phone app, or
a command line — control the device and watch its state. Where the
[button](button.md) gives you two gestures, MQTT gives you full control.

MQTT only works once [Wi-Fi](network.md) is connected and a broker is configured.

## What you can do

- **Control the lights** — turn them on or off, switch mode, adjust brightness,
  speed and color, resize the strip, turn on segmenting — by publishing a small
  message (see [Examples](#examples)).
- **See the current state** — the device publishes its full state whenever
  anything changes, so a fresh subscriber gets the latest immediately.
- **Know if it's online** — an online/offline status updates automatically,
  even if the device loses power unexpectedly.

For safety, settings that could knock the device off your network — Wi-Fi
credentials, the broker address, pin assignments — **can't** be changed over
MQTT, only the light controls above.

## Setting it up

Fill in the `mqtt` section of `config.json`:

| Setting | Default | What it does |
|---|---|---|
| `mqtt.enabled` | `true` | Master on/off switch for MQTT. |
| `mqtt.server` | `""` | Your broker's address (a hostname). Empty turns MQTT off. |
| `mqtt.port` | `1883` | Broker port. |
| `mqtt.user` / `mqtt.password` | `""` | Broker login, if it needs one. |
| `mqtt.base_topic` | `controller/led/1` | The prefix for every topic below — give each device its own. |
| `mqtt.use_single_topic_for_state_update` | `false` | Combine command and state onto one topic (see [Single-topic mode](#single-topic-mode)). |
| `mqtt.ssl` | `false` | Encrypt the connection (see [Secure connections](#secure-connections)). |
| `mqtt.certificate.validate` | `false` | Also verify the broker's identity (see [Secure connections](#secure-connections)). |
| `mqtt.certificate.name` | `""` | Filename of your CA certificate, stored in `certs/` on the device. |
| `mqtt.ntp_host` | `pool.ntp.org` | Time server, used only for secure connections. |

Changes take effect right away — the device reconnects with the new settings,
no reboot.

## Topics

Everything sits under your `base_topic` (default `controller/led/1`):

| You... | Topic | Purpose |
|---|---|---|
| Publish to | `<base_topic>/state/update` | Send a command. |
| Subscribe to | `<base_topic>/state/full` | The device's full current state, updated on every change. |
| Subscribe to | `<base_topic>/state/online` | `"online"` / `"offline"` availability. |

### What you can set

A command sent to `state/update` may only contain these:

| Group | Fields |
|---|---|
| `mode` | `current` (mode name), `brightness`, `speed`, `on`, `color`, `direction` |
| `leds` | `count`, `segmenting` |

Anything else is ignored. See [Animations](../animations/index.md) for what the
modes, `color`, `speed`, `direction` and `segmenting` actually do.

As a convenience you can set the color with a `mode.hexColor` string
(`"#ff781e"`, with or without the `#`) instead of the `color` array — MQTT
converts it to `color` for you. The published state reports both.

## Examples

These use `mosquitto_pub`/`mosquitto_sub`, but any MQTT client works the same
way. Replace `<broker>` and `<base_topic>` with yours.

Set brightness and switch to the rainbow mode:

```
mosquitto_pub -h <broker> -t <base_topic>/state/update \
  -m '{"mode": {"brightness": 80, "current": "rainbow"}}'
```

Resize the strip to 60 LEDs:

```
mosquitto_pub -h <broker> -t <base_topic>/state/update \
  -m '{"leds": {"count": 60}}'
```

Set the color (here as a `hexColor` string) and play the animation from the far
end of the strip:

```
mosquitto_pub -h <broker> -t <base_topic>/state/update \
  -m '{"mode": {"direction": "backward", "hexColor": "#ff781e"}}'
```

Turn on segmenting with a 5-LED repeat:

```
mosquitto_pub -h <broker> -t <base_topic>/state/update \
  -m '{"leds": {"segmenting": {"enabled": true, "length": 5}}}'
```

Watch the full state, which arrives on connect and after every change:

```
mosquitto_sub -h <broker> -t <base_topic>/state/full -v
```

```json
{"device": "e6614c311b331b35", "mode": {"current": "rainbow", "brightness": 80, "speed": 10, "on": true, "color": [255, 120, 30], "hexColor": "#ff781e", "direction": "forward"}, "leds": {"count": 144, "segmenting": {"enabled": true, "length": 5}}}
```

Each state message carries a `"device"` id; you don't need to send it.

## Single-topic mode

Some integrations prefer commands and state on a single topic. Set
`mqtt.use_single_topic_for_state_update: true` and both move onto
`<base_topic>/state` — you publish commands there and subscribe there for
state. The online/offline topic is unchanged.

## Secure connections

By default MQTT is unencrypted. Two settings tighten this:

- **`mqtt.ssl: true`** encrypts the connection (TLS).
- **`mqtt.certificate.validate: true`** additionally checks that the broker is
  who it claims to be, using a CA certificate stored at
  `certs/<mqtt.certificate.name>` on the device. This protects against someone
  impersonating your broker. Upload the certificate from the MQTT → Certificate
  section of `/config` (**Upload certificate**) — it's saved
  under its filename, which then appears in the **Certificate name** dropdown
  next to the other certificates already on the device; no manual file
  transfer needed. The filename may use only letters, digits, dots, dashes
  and underscores (up to 64 characters).

When certificate checking is on but the certificate is missing or unreadable,
the device refuses to connect rather than falling back to an unverified
connection — it fails safe. A couple of practical notes:

- `mqtt.server` must be a **hostname**, not a bare IP address — certificates
  are issued for names, not IPs.
- Secure connections need the correct time, so the device syncs its clock from
  `mqtt.ntp_host` before connecting.

## Online / offline status

`<base_topic>/state/online` reports `"online"` while the device is connected
and `"offline"` when it isn't — including when it loses power or drops off
unexpectedly (the broker publishes that for it). Use it to drive an
availability indicator in your dashboard without polling.

:::note
How the connection, message handling and certificate loading are implemented
is documented in [Channel internals](../contributing/channels.md#mqtt-channel).
:::
