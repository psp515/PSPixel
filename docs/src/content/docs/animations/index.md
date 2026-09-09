---
title: Animations
description: "The lighting modes and the shared brightness, speed, colour and direction controls."
---

An **animation** is one lighting mode — a look the strip shows. You pick a
mode, and a few shared controls (brightness, speed, color, direction) tune how
it looks. Everything you choose is saved, so the strip comes back the same
after a power cut.

## Modes

| Mode | What it looks like |
|---|---|
| `off` | Fades the strip smoothly down to black, then stays off. |
| `white` | Solid white. |
| `static` | A solid color of your choosing (see [Color](#color)). Fades in from one end when you switch to it. |
| `blink` | Your chosen color flashing on and off. Speed controls how fast it blinks. |
| `rainbow` | A rainbow that scrolls along the strip. Its speed and direction are adjustable, and it works with [segmenting](#segmenting). |
| `runner` | A short trail of light that chases along the strip, brightest in the middle and fading at the ends. |
| `pspixel` | The project logo brought to the strip: a dim blue-to-orange gradient with five glowing dots that breathe in turn, and comets in the logo colors running along it. |

## PSPixel

`pspixel` recreates the project logo on the strip. Three settings live under
`modes.pspixel`:

```json
"pspixel": {"trails": 2, "length": 10, "dot_size": 0}
```

- `trails` — how many comets run along the strip at once, **1 to 4**
  (default `2`). They are spread evenly around it.
- `length` — how many LEDs each comet spans (default `10`). A comet is
  brightest in its middle and fades away at both ends.
- `dot_size` — how many LEDs each of the five glowing dots covers. Leave it at
  `0` (default) to size them from the strip length — about 5 LEDs on a
  100-LED strip. The LEDs at a dot's edges are dimmer than its center.

The two outermost dots sit right on the first and last LED, so they show as
half dots marking each end of the strip.

## Shared controls

These apply across modes and are set together with the mode (over
[MQTT](../channels/mqtt.md), or cycled with the [button](../channels/button.md)):

### Brightness

`brightness` runs from **1 to 100** — a simple percentage of full brightness.
`100` is as bright as the strip goes; lower values dim everything evenly.

### Speed

`speed` also runs from **1 to 100**, and controls how fast the animated modes
move. It affects `rainbow`, `runner`, and `blink`; `white` and `static` ignore
it.

| Mode | What speed feels like |
|---|---|
| `runner` | How fast the trail travels. `10` takes about 14 seconds to go once around a 144-LED strip; `100` sweeps it in under 2 seconds. |
| `rainbow` | How fast the rainbow scrolls. `10` is roughly one full color cycle per second; `100` is strobe-fast. |
| `blink` | How fast it flashes. `10` blinks a little slower than once a second; `100` blinks five times a second. |
| `pspixel` | How fast the comets travel, in LEDs per second — same feel as `runner`. The dots breathe at a fixed rate. |

Comfortable everyday values are around **5–20**.

### Color

`color` is a single `[red, green, blue]` value (each 0–255) used by the
color-driven modes — `static` fills the strip with it, `blink` flashes it, and
`runner`'s trail takes it. `white`, `rainbow` and `pspixel` ignore it.

### Direction

`direction` is either `"forward"` or `"backward"`. `"backward"` mirrors the
strip so animations play from the far end instead of the near end. It affects
every mode except `off`.

## Segmenting

Segmenting splits the strip into repeating blocks, so a pattern repeats every
few LEDs instead of stretching across the whole strip once. Configure it under
`leds.segmenting`:

```json
"segmenting": {"enabled": true, "length": 5}
```

- `enabled` turns it on; `length` is how many LEDs each repeat spans (minimum
  2).
- It only affects modes that repeat sensibly — mainly `rainbow`. Solid fills
  and the single running trail always use the whole strip.
- If `length` ends up as large as the strip, the whole strip is treated as one
  block (no repeat).

:::note
The animation code interface, frame rendering, and how to add a new mode are
in [Animation internals](../contributing/animations.md).
:::
