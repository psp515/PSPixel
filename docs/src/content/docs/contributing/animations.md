---
title: Animation internals
description: "The animation interface, the render loop, and how to add a new lighting mode."
---

How lighting modes are implemented and rendered, and how to add a new one. For
what each mode looks like and the user-facing controls, see
[Animations](../animations/index.md).

An **animation** is one lighting mode — `off`, `white`, `static`, `blink`,
`rainbow`, `runner`, `pspixel`. The `Renderer` (`src/renderer.py`) owns a single
`uasyncio` loop that
picks the active animation, calls its `render()` once per frame, and writes the
result to the NeoPixel strip. Modes never touch `neopixel`/hardware themselves;
each mode is responsible for applying brightness itself (see `apply_brightness`
below).

## The `Animation` interface

Defined in `src/animations/base.py`:

```python
class Animation:
    interval_ms = 40
    segmenting_compatible = True

    def __init__(self, mode, params):
        self.mode = mode
        self.params = params

    def render(self, buffer, count, frame):
        pass

    def apply_brightness(self, buffer, count):
        ...
```

- `interval_ms` — delay between frames; the renderer sleeps this long after
  each `render()` call. Override per-class, or mutate it at runtime — `Static`
  drops to `WIPE_INTERVAL_MS` (30) during its startup wipe and back to 500 once
  done; `Runner` renders at a fixed 30 ms and folds `mode.speed` into its
  per-frame step instead.
- `segmenting_compatible` — whether this mode may be split into repeating
  `leds.segmenting.length`-LED blocks when segmenting is enabled; see
  [Segmenting](#segmenting). Defaults to `True`; override to `False` for modes
  where segmenting wouldn't change anything (a solid fill) or wouldn't make
  sense (a single trail chasing the whole strip).
- `mode` — the shared `Mode` helper (`src/state.py`), giving read access to
  `mode.current` / `mode.brightness` / `mode.speed` / `mode.on` / `mode.color`
  / `mode.direction`. `mode.color` is the single global `[r, g, b]` used by
  every color-driven mode (`static`, `blink`, `runner`) — it is *not* a
  per-mode param.
- `params` — this mode's own config dict, e.g. `{"length": 5}` for `runner`,
  read from `modes.<name>` in the config.
- `render(buffer, count, frame)` — called every frame; must write `count`
  pixels into `buffer` and return nothing. `frame` is a monotonically
  increasing counter, reset to `0` only when the *active mode name* changes
  (including on/off flips). Other state changes (color, brightness, speed,
  direction, segmenting) rebuild the animation instance but keep `frame`
  running, so startup effects don't replay on every slider tick. When
  segmenting is active, `count` here is the *segment* length, not the full
  strip.
- `apply_brightness(buffer, count)` — scales the whole buffer down by
  `mode.brightness` (1-100) in place. Call this yourself as the last line of
  `render()` once you've written raw colors. `off` is the one built-in
  exception: it fades an already-captured snapshot down to black and produces
  final output values directly, so it doesn't call it.

### Buffer format

`buffer` is the NeoPixel driver's raw byte buffer, laid out **G, R, B** per
pixel (MicroPython's `neopixel` module default order) — that's `count * 3`
bytes. Write it directly rather than allocating a new buffer/list per frame;
none of the built-in animations allocate inside `render()` except lazily once
(see `Runner`'s cached `_zeros`).

`count` is stable for the lifetime of one animation instance — the `Renderer`
rebuilds a fresh instance whenever *any* state changes, which includes
`leds.count` itself (the strip can be resized at runtime) and `leds.segmenting`.
So it's safe to size/cache a buffer from the `count` you see on the first
`render()` call.

## Built-in modes

Registered in `src/animations/registry.py`:

| Mode | File | Params | Segmenting | Direction | Notes |
|---|---|---|---|---|---|
| `off` | `off.py` | `fade_ms` (default `600`) | No | **No** | Fades whatever was last displayed down to black over `fade_ms`, using an eased (quadratic) curve, then holds all pixels off. Entered whenever `mode.on` is `False` or an unknown mode is selected. |
| `white` | `white.py` | — | No | Yes (startup only) | `Static` subclass with the color pinned to white (`mode.color` ignored); same wipe-in startup |
| `static` | `static.py` | — | No | Yes (startup only) | Solid `mode.color`; starts with a gradient wipe-in, LED by LED from one end (see [Startup wipe](#startup-wipe)), then settles at `interval_ms=500` |
| `blink` | `blink.py` | — | No | No | Flashes `mode.color` fully on, then fully off, alternating every `interval_ms`; `mode.speed` sets the half-period between `BLINK_MIN_MS` (100) and `BLINK_MAX_MS` (600) |
| `rainbow` | `rainbow.py` | — | **Yes** | Yes | Precomputes a 256-step color wheel once; wipes the first rainbow frame in on startup, then scrolls it using `mode.speed` |
| `runner` | `runner.py` | `length` | No | Yes | Trail of `length` pixels in `mode.color` chasing around the strip, brightest in the middle and fading to black at both ends; enters cleanly from the start of the strip. Renders at a fixed 30 ms frame rate with a sub-pixel (fixed-point) head position; `mode.speed` sets travel speed in LEDs/second |
| `pspixel` | `pspixel.py` | `trails`, `length`, `dot_size` | No | Yes | Logo animation: a fixed blue→orange palette gradient dimmed to `BASE_SCALE` (32/256) as a base layer, five pulsing anchor dots in the logo colors, and `trails` comets running along the strip. `mode.color` is ignored. Renders at a fixed 30 ms with a sub-pixel head like `runner` |

`off`/`white`/`static`/`blink` opt out of segmenting because segmenting a solid
fill produces the exact same output as rendering it across the whole strip.
`runner` and `pspixel` opt out because their trails are meant to travel the
full strip, and `pspixel`'s anchor dots mark the two ends of it.

### `pspixel` internals

`src/animations/pspixel.py`. Everything that depends on `count` is built once
on the first `render()` call (`_prepare`), since `count` is stable for an
instance's lifetime:

- `_base` — a `count * 3` bytearray holding the palette gradient scaled to
  `BASE_SCALE`, copied into the frame buffer with one slice assignment each
  frame so `render()` allocates nothing.
- `_anchors` — the five dot centers, at `i * (count - 1) // 4`. The first and
  last land on LED `0` and LED `count - 1`, so their outer halves fall off the
  strip and they render as half dots — no special-casing.
- `_radius` — `dot_size // 2`, with `dot_size` falling back to
  `max(DOT_MIN, count // DOT_DIVISOR)` (3, 20) when the param is `0`. Dot
  pixels are scaled by a linear falloff from the center.
- `_gap` — the fixed-point spacing between comet heads, `count * 256 // trails`.

`_pulse` is a 64-entry brightness LUT built in `__init__` (eased triangle,
`PULSE_MIN`..255), advanced by `frame * PULSE_RATE >> 8` and offset per anchor
by `PULSE_PHASE` steps, which gives the staggered breathing of the logo dots.
Comets reuse `runner`'s trail shape — brightest at the middle of the trail,
fading to nothing at both ends — and take their color from the palette
gradient sampled at the head position (`_sample`, into a preallocated
`_tmp` list). Dots and comets are written over the base with `_blend`, an
additive write clamped to 255.

## Brightness and speed

Both are global `mode` fields, shared by all modes, and both are clamped to
**1-100** by `StateManager` (`MODE_RANGES` in `src/state.py`).

- **`mode.brightness` (1-100)** is a percentage scale applied to the whole
  frame by `apply_brightness`. `100` writes raw colors unchanged; lower values
  scale every channel down linearly. `off` ignores it.
- **`mode.speed` (1-100)** is a raw rate, *not* a percentage — each mode
  interprets it with its own unit:

| Mode | Unit | Feel |
|---|---|---|
| `runner` | LEDs per second | `10` ≈ 14 s per lap of a 144-LED strip; `100` sweeps it in ~1.4 s |
| `rainbow` | color-wheel steps (of 256) per 40 ms frame | `10` ≈ one full color cycle per second; `100` ≈ 10 cycles/s |
| `blink` | inverse half-period, `interval_ms = max(100, 600 - speed * 5)` | `10` ≈ 0.9 Hz; `100` ≈ 5 Hz (floored at the 100 ms minimum) |
| `pspixel` | LEDs per second | Same scale as `runner`; the anchor pulse is independent of `speed` |
| `off`, `white`, `static` | unused | — |

Changing either field rebuilds the animation instance without resetting
`frame`, so tweaks apply immediately mid-animation.

## Startup wipe

`static`, `white` and `rainbow` don't pop to full output when selected — they
wipe in from the start of the strip with a soft gradient front. The shared
helper lives on the base class (`src/animations/base.py`):

- `apply_wipe(buffer, count, frame)` — call it *after* writing your full frame
  (and after `apply_brightness`). It masks the buffer in place: pixels beyond
  the wipe front are blanked, the `WIPE_EDGE` (6) pixels behind the front form
  a linear brightness ramp, everything earlier is untouched. Returns `True`
  while the wipe is still running, `False` once done.
- `wipe_frames(count)` — how many frames the wipe takes for a given strip
  length (the front advances `max(1, count // WIPE_STEPS)` LEDs per frame, so
  the whole wipe lasts roughly `WIPE_STEPS` (40) frames regardless of strip
  size). `Rainbow` uses it to hold its scroll offset at zero until the wipe
  finishes.

`runner` doesn't wipe; its startup is a clean entry — the buffer is cleared
every frame and trail positions before LED 0 are skipped. Startup effects only
play when the active mode actually changes (or the strip turns on).

## Direction

`mode.direction` (`"forward"` / `"backward"`, validated in `StateManager`) is
global, handled entirely by the `Renderer` — animations always render "forward"
(from LED 0 toward the end) and never need to know about it. When `direction`
is `"backward"`, the renderer mirrors the final pixel buffer in place
(`Renderer._reverse`, after segment tiling) just before writing to the strip.

- `runner` / `rainbow` — fully direction-aware.
- `static` / `white` — direction only matters during the startup wipe; the
  steady solid fill looks identical either way.
- `blink` — no wipe and a uniform fill, so direction never changes anything.
- `off` — **not compatible**, the renderer skips the mirror: its fade works
  from a snapshot of what was last *displayed* (already mirrored), so reversing
  again would flip the image mid-fade.

## Segmenting

Splits the strip into repeating `leds.segmenting.length`-LED blocks so a
compatible mode's pattern repeats every N LEDs. Configured under
`leds.segmenting` (`src/defaults.py`):

```json
"segmenting": {"enabled": false, "length": 2}
```

- **Only applies to modes with `segmenting_compatible = True`** — incompatible
  modes always render across the full strip.
- **`length` has a floor of 2**, enforced in `StateManager.update()`.
- **No ceiling is enforced at write time.** If `length` ends up `>= leds.count`,
  the `Renderer` falls back to rendering the full strip as one segment —
  re-evaluated fresh every frame (`Renderer._segment_count`), so it self-heals.
- **Rendering**: the active animation's `render()` is called once with `count`
  set to the segment length; `Renderer._tile()` then copies that segment across
  the rest of the buffer. If `leds.count` isn't a multiple of `length`, the
  final repeat is truncated mid-pattern.
- **Overridable via MQTT** the same way `mode` fields are — see the
  [allow-list](channels.md#allow-list-for-the-update-topic).

## Adding a new mode

Nothing else needs to change: selecting `mode.current = "<name>"` (via any
channel) makes the renderer pick it up automatically. Steps:

1. Create `src/animations/<name>.py` from the template below.
2. Register it in the `MODES` dict in `src/animations/registry.py`.
3. Add a default params entry under `modes.<name>` in `DEFAULTS`
   (`src/defaults.py`) and in `config.dev.json`, even if it's just `{}`.

### Template

```python
from animations.base import Animation


class MyMode(Animation):
    interval_ms = 40  # ms between frames; override or compute from mode.speed

    def __init__(self, mode, params):
        super().__init__(mode, params)
        color = mode.color
        self._r = color[0]
        self._g = color[1]
        self._b = color[2]

    def render(self, buffer, count, frame):
        for i in range(0, count * 3, 3):
            buffer[i] = self._g      # buffer order is G, R, B
            buffer[i + 1] = self._r
            buffer[i + 2] = self._b
        self.apply_brightness(buffer, count)
```

### Rules to follow

- Don't allocate new buffers/lists inside `render()` — it runs every frame.
  Precompute lookup tables etc. in `__init__` (see `Rainbow`'s color wheel),
  and if you need a scratch buffer, allocate it once and cache it (see
  `Runner`'s `_zeros`).
- Call `self.apply_brightness(buffer, count)` as the last line of `render()`
  once you've written raw colors — it's not automatic. Skip it only if your
  mode is producing final, already-scaled output directly (see `off`).
- Read `mode.speed` / `params` defensively with `.get(...)` and a default;
  clamp anything that could be `0` or negative before using it as a divisor.
- Keep `render()` allocation-free and branch-light — it runs on a
  memory-constrained MicroPython board, once per `interval_ms`.

### Registering it

```python
# src/animations/registry.py
from animations.mymode import MyMode

MODES = {
    "off": Off,
    "white": White,
    "static": Static,
    "rainbow": Rainbow,
    "runner": Runner,
    "pspixel": PSPixel,
    "mymode": MyMode,
}
```

```python
# src/defaults.py
"modes": {
    ...
    "mymode": {},
},
```
