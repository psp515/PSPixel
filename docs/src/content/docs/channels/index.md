---
title: Channels
description: "The ways to control PSPixel — the cover button, MQTT, and the browser dashboard."
---

A **channel** is a way to control the device. They all work at the same time
and stay in sync — a change made one way shows up everywhere else instantly.

- [Button](button.md) — the physical button on the enclosure cover.
- [MQTT](mqtt.md) — control it from a home-automation system, phone app, or a
  script anywhere on your network.
- [Web API](webapi.md) — a browser dashboard and configuration page served
  by the device itself.

Wi-Fi isn't a control method on its own — the [Network channel](network.md) just
keeps the device connected (falling back to its own network if it can't) so
MQTT and the Web UI can reach it.

Every change you make is saved automatically, so after a power cut the device
comes back exactly as you left it.

:::note
Want to add a new way to control the device in code? See
[Channel internals](../contributing/channels.md) in the Contributing section.
:::
