---
title: Web installer
description: "Flash MicroPython and install PSPixel onto a Raspberry Pi Pico W from the browser, no tools required."
---

The web installer flashes MicroPython and installs the controller onto a
Raspberry Pi Pico W straight from your browser — no tools to install, no files
to copy by hand. It's the quickest way to get a fresh board running.

**[Open the installer →](../installer/)**

Prefer to do it by hand, or want to understand every step? See
[Manual setup](setup.md).

## What you need

- A **Raspberry Pi Pico W** and a USB cable.
- Desktop **Chrome**, **Edge**, or **Opera**. Firefox, Safari, and phones
  can't talk to USB devices from a web page — the installer will tell you if
  the browser isn't supported.
- Your Wi-Fi name and password (optional — you can also set Wi-Fi up later
  from the device's own setup network).

## How it works

0. **Pick a version.** *Install from* chooses between
   **Released version** — the project's
   [tags](https://github.com/psp515/PSPixel/tags), newest first, and
   what you want almost always — and **Branch (unreleased)**, which lists the
   repository's branches (`main` first) and installs whatever is on the one
   you pick. Branches are useful for trying unreleased changes, but aren't
   guaranteed stable. The second dropdown lists the versions of the kind you
   chose; the newest release is preselected.
1. **Flash MicroPython.** Hold the **BOOTSEL** button while plugging the Pico W
   in, then press *Flash via USB*. If your browser can't flash directly, the
   installer links you to the official MicroPython download page (with the
   exact version to grab) to download the `.uf2` yourself and drag it onto
   the `RPI-RP2` drive. Already have MicroPython on the board? Press
   *Already flashed — skip* instead.
2. **Connect.** After the board reboots (about five seconds), press *Connect*
   and pick the Pico's serial port.
3. **Configure.** Fill in the device name, Wi-Fi, LED count and data pin, and
   watchdog — everything else (the setup network's name/password, LED
   behavior, MQTT including TLS and certificate validation, the cover
   button/IR remote, boot mode, logging) is tucked behind its own
   **(advanced)** section, pre-filled with sensible defaults, so the basics
   stay quick and the rest is there when you need it. Press *Scan for
   networks* to fill in nearby Wi-Fi names to pick from — you can still type
   any name by hand. If you turn on MQTT certificate validation, a drop
   zone appears — drag a certificate file in or click to browse, and it's
   uploaded onto the device along with everything else in step 4. Its
   filename may use only letters, digits, dots, dashes and underscores
   (up to 64 characters).
4. **Install.** The installer copies the controller onto the board, writes your
   settings, and reboots it. The strip lights up on the persisted mode.

## After installing

The device behaves exactly as a hand-installed one, and the last step tells
you how to reach it:

- **If you set up Wi-Fi**, find the device's IP address on your router (its
  connected-devices list) and open it in a browser. If it can't join that
  network — wrong password, network out of range — it automatically opens
  its own setup network instead, same as below.
- **If you left Wi-Fi blank**, the device starts up as its own Wi-Fi access
  point on this first boot instead of joining a network — that's expected.
  Connect your phone or computer's Wi-Fi to it (`PSPixel` by default)
  and open `http://192.168.4.1/` to finish setup — see
  [Can't connect?](channels/network.md#cant-connect-the-device-opens-its-own-setup-network).

To change anything later, use the Web UI (the dashboard the device serves) or
re-run the installer.

## If something goes wrong

- **"This browser cannot talk to USB devices"** — switch to desktop Chrome,
  Edge, or Opera.
- **You pick the board from the USB prompt and then nothing happens** — on
  Windows, USB flashing needs a WinUSB driver bound to the board's boot
  interface, which isn't installed by default. The installer now times out
  after a few seconds and reports this; either way, use the drag-the-`.uf2`
  fallback link instead (no driver needed).
- **Flashing doesn't start** — on Windows the Pico's bootloader occasionally
  needs a moment to be recognised; unplug, hold BOOTSEL, plug back in. If it
  still won't, use the drag-the-`.uf2` fallback link.
- **"GitHub API rate limit hit"** — the installer reads the picked version
  straight from GitHub; wait a few minutes and reload.
- **"Failed to open serial port"** — usually means the board hasn't finished
  booting yet right after flashing/rebooting; wait a few seconds and press
  *Connect* again. Also check no other program (Thonny, the Arduino IDE,
  another browser tab) already has the port open.
- **The install stalls partway** — unplug the board and start again from
  step 1 (re-flashing MicroPython wipes the half-written filesystem).

Each step turns green with a checkmark once it succeeds, or red with the
error if it didn't — so you can always tell which one to retry.
