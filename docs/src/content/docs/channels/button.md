---
title: Button
description: "The two gestures of the enclosure-cover button: short press and hold."
---

The button on the enclosure cover is the whole no-phone, no-network interface —
two gestures, one button.

| Device is | You do | What happens |
|---|---|---|
| Off | **Click** (short press) | Lights turn **on**, resuming the last mode |
| On | **Click** (short press) | Switches to the **next lighting mode** |
| On | **Hold ~1s**, then release | Lights turn **off** |
| Off | **Hold ~1s**, then release | Lights turn **on** |
| Any | **Hold ~2-5s**, then release | Nothing — the press is cancelled, so an accidental long hold does nothing |
| Any | **Hold ~5s** | Lights turn **off** as a "you can let go now" signal, and one second later the device **restarts into config mode** — its setup Wi-Fi network with the dashboard, for changing settings. Releasing after the lights go off doesn't cancel it. See [boot modes](../setup.md#boot-modes) |

So: click to wake it up or change the look, hold briefly to switch it off,
hold long to get to the settings.
Everything the button changes is saved automatically — after a power cut the
device comes back exactly as you left it.

## Settings

Configured in the `button` section of `config.json`:

| Setting | Default | What it does |
|---|---|---|
| `button.pin` | `3` | Which GPIO pin the button is wired to. Changing it needs a reboot (you're rewiring anyway). |
| `button.enabled` | `true` | Set to `false` to make the device ignore the button entirely. |

:::note
How the press timing and debouncing work is covered in
[Channel internals](../contributing/channels.md#button-channel).
:::
