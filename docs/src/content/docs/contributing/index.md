---
title: Contributing
description: "Developer documentation: how PSPixel works internally and how to extend it."
---

Technical documentation for anyone working on the code: how the device is built
internally, how to set up a host-side dev environment, and how to add new
control methods or lighting modes. If you only want to *use* the device, the
rest of the docs (Home, Setup, Channels, Animations) is written for that.

## Pages

- [Development guide](../development.md) — how it works, the architecture, the
  config file, and the full list of config keys.
- [Channel internals](channels.md) — how the Wi-Fi, button and MQTT channels
  work under the hood, and how to add a new channel.
- [Animation internals](animations.md) — the animation interface, the render
  loop, and how to add a new lighting mode.

## Quick dev loop

Mirrors `.github/workflows/ci.yml` (lint → build → test → installer → docs), all on CPython:

```
python -m ruff check src main.py
python -m compileall -q src main.py
python -m pytest
```

See the [Development guide](../development.md#setting-up-a-development-environment)
for the full setup.
