<div align="center">

  <img src="src/webui/static/icons/logo.png" alt="PSPixel logo" width="96" height="96" />

  <h1>PSPixel</h1>
  <p>MicroPython ARGB LED controller for the Raspberry Pi Pico W</p>

  <div>
    <a href="https://github.com/psp515/PSPixel/actions/workflows/ci.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/psp515/PSPixel/ci.yml?branch=main&label=CI" alt="CI status" />
    </a>
    <a href="https://psp515.github.io/PSPixel/">
      <img src="https://img.shields.io/github/deployments/psp515/PSPixel/github-pages?label=docs" alt="docs" />
    </a>
    <a href="">
      <img src="https://img.shields.io/github/last-commit/psp515/PSPixel" alt="last update" />
    </a>
    <a href="https://github.com/psp515/PSPixel/network/members">
      <img src="https://img.shields.io/github/forks/psp515/PSPixel" alt="forks" />
    </a>
    <a href="https://github.com/psp515/PSPixel/stargazers">
      <img src="https://img.shields.io/github/stars/psp515/PSPixel" alt="stars" />
    </a>
    <a href="https://github.com/psp515/PSPixel/issues/">
      <img src="https://img.shields.io/github/issues/psp515/PSPixel" alt="open issues" />
    </a>
    <a href="https://github.com/psp515/PSPixel/blob/main/LICENSE">
      <img src="https://img.shields.io/github/license/psp515/PSPixel" alt="license" />
    </a>
  </div>
</div>

<br/>

### Built With

![Micro Python](https://img.shields.io/badge/MicroPython-14354C?style=for-the-badge&logo=micropython&logoColor=white&style=flat)
![Raspberry Pi](https://img.shields.io/badge/-Raspberry%20Pi%20Pico%20W-C51A4A?style=for-the-badge&logo=Raspberry-Pi&logoColor=white&style=flat)
![HiveMq](https://img.shields.io/badge/-HiveMQ-F5F5F5?style=for-the-badge&logo=hivemq&logoColor=yellow&style=flat)

## About the project

PSPixel turns a Raspberry Pi Pico W and a WS2812B ARGB LED strip into a
smart light you can control however suits you in the moment — the button on the
enclosure or a home automation system.

- **Turn the LEDs on or off**, and switch between lighting modes (static color, rainbow, running trail, etc.)
- **Adjust brightness, speed, color and direction**, shared across whichever mode is active.
- **Split the strip into repeating segments** for compatible modes.
- **Remembers your settings.** Mode, brightness, speed, and on/off state all
  survive a power cycle — the strip comes back exactly as you left it.
- **Announces when it goes offline**, if you're watching it over MQTT (a
  retained "last will" message)

Pick whichever control method's convenient — they both work at the same time and stay in sync:

- **The button** on the enclosure cover — short press cycles modes, a longer press toggles the strip on/off
- **MQTT** — for Home Assistant, Node-RED, or any other automation system

## Documentation

Full docs live at **[psp515.github.io/PSPixel](https://psp515.github.io/PSPixel/)** (built with Astro + Starlight). They're split into a plain-language **user guide** and a **developer guide**, each with its own sidebar:

- [Web installer](https://psp515.github.io/PSPixel/installer/) — flash MicroPython and install the controller onto a Pico W from the browser (Chrome/Edge/Opera)
- [Manual setup](https://psp515.github.io/PSPixel/setup/) — the by-hand version: wiring, flashing MicroPython, copying the project on, and configuring it
- [Channels](https://psp515.github.io/PSPixel/channels/) — the ways to control it (button and MQTT)
- [Animations](https://psp515.github.io/PSPixel/animations/) — the lighting modes and their shared controls
- [Developer guide](https://psp515.github.io/PSPixel/development/) — architecture, dev-environment setup, the config file, and how to add a new channel or mode

## Contributing

This is an open-source, hobby-driven project — contributions, bug reports, and
ideas are all welcome. If you build one, run into an issue, or have a mode or
channel you'd like to add:

- ⭐ **Star** the repo if you find it useful — it helps others find it too.
- 🐛 Open an [issue](https://github.com/psp515/PSPixel/issues) for bugs or feature requests.
- 🔀 Fork it and send a pull request — the [Contributing docs](https://psp515.github.io/PSPixel/contributing/) cover how the pieces fit together and how to add a new channel or mode without touching the core loop.

## License

Distributed under the MIT License. See `LICENSE` for more information.
