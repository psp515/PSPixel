import asyncio

import machine
import neopixel

from animations.off import Off
from animations.registry import MODES

SEGMENT_LENGTH_MIN = 2
PROTOCOL_TIMING = {"ws2812": 0, "ws2811": 1}


class Renderer:
    def __init__(self, state, logger):
        self.state = state
        self.logger = logger
        self.count = state["leds"]["count"]
        self.protocol = state.get("leds", "protocol", default="ws2812")
        pin = state.get("leds", "pin", default=0)
        self._pin = machine.Pin(pin)
        self.np = self._make_strip(self.count, self.protocol)
        self._reload = True
        state.subscribe(self._on_change)
        self.logger.info(
            "renderer", "leds count {0} pin {1} protocol {2}", self.count, pin, self.protocol
        )

    def _make_strip(self, count, protocol):
        timing = PROTOCOL_TIMING.get(protocol, 0)
        return neopixel.NeoPixel(self._pin, count, timing=timing)

    def _on_change(self, patch):
        self._reload = True

    def _resize(self, count, protocol):
        self.np = self._make_strip(count, protocol)
        self.count = count
        self.protocol = protocol
        self.logger.info(
            "renderer", "leds reconfigured count {0} protocol {1}", count, protocol
        )

    def _mode_name(self):
        name = self.state.mode.current if self.state.mode.on else "off"
        if name not in MODES:
            self.logger.warning("renderer", "unknown mode {0}, falling back to off", name)
            name = "off"
        return name

    def _make_animation(self, name=None):
        if name is None:
            name = self._mode_name()
        self.logger.debug("renderer", "mode -> {0}", name)
        params = self.state.mode.params(name)
        anim = MODES[name](self.state.mode, params)
        if isinstance(anim, Off):
            anim.fade_from(self.np.buf, self.count)
        return anim

    def _segment_count(self, anim):
        if not anim.segmenting_compatible:
            return self.count
        segmenting = self.state.get("leds", "segmenting", default={})
        if not segmenting.get("enabled"):
            return self.count
        length = segmenting.get("length", SEGMENT_LENGTH_MIN)
        if length < SEGMENT_LENGTH_MIN:
            length = SEGMENT_LENGTH_MIN
        if length >= self.count:
            return self.count
        return length

    def _tile(self, buf, seg_count):
        seg_size = seg_count * 3
        total = self.count * 3
        pos = seg_size
        while pos < total:
            chunk = min(seg_size, total - pos)
            buf[pos : pos + chunk] = buf[0:chunk]
            pos += chunk

    def _reverse(self, buf):
        left = 0
        right = (self.count - 1) * 3
        while left < right:
            for k in range(3):
                tmp = buf[left + k]
                buf[left + k] = buf[right + k]
                buf[right + k] = tmp
            left += 3
            right -= 3

    def _render_frame(self, anim, frame):
        buf = self.np.buf
        seg_count = self._segment_count(anim)
        anim.render(buf, seg_count, frame)
        if seg_count < self.count:
            self._tile(buf, seg_count)
        if self.state.mode.direction == "backward" and not isinstance(anim, Off):
            self._reverse(buf)
        self.np.write()

    async def start(self):
        anim = None
        anim_name = None
        frame = 0
        while True:
            new_count = self.state.get("leds", "count", default=self.count)
            new_protocol = self.state.get("leds", "protocol", default=self.protocol)
            if new_count != self.count or new_protocol != self.protocol:
                self._resize(new_count, new_protocol)
                self._reload = True
            if self._reload:
                self._reload = False
                name = self._mode_name()
                anim = self._make_animation(name)
                if name != anim_name:
                    frame = 0
                anim_name = name
            self._render_frame(anim, frame)
            frame += 1
            await asyncio.sleep_ms(anim.interval_ms)
