import asyncio
import time

from storage import merge

VERSION = "1.1.0"

MODE_RANGES = {"brightness": (1, 100), "speed": (1, 100)}
MODE_DIRECTIONS = ("forward", "backward")
DEFAULT_MODES = ("normal", "mqtt-ssl")
SEGMENT_LENGTH_MIN = 2
LEDS_COUNT_MIN = 1
LEDS_PROTOCOLS = ("ws2812", "ws2811")

try:
    import binascii
    import machine

    _DEVICE_ID = binascii.hexlify(machine.unique_id()).decode()
except ImportError:
    _DEVICE_ID = "dev"


def _validate_mode(data, mode_patch, logger):
    mode_patch = dict(mode_patch)
    if "current" in mode_patch and mode_patch["current"] not in data.get("modes", {}):
        if logger:
            logger.warning("state", "unknown mode {0}, keeping current", mode_patch["current"])
        del mode_patch["current"]
    for key, (lo, hi) in MODE_RANGES.items():
        if key not in mode_patch:
            continue
        value = mode_patch[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            if logger:
                logger.warning("state", "invalid {0} {1}, ignoring", key, value)
            del mode_patch[key]
        elif value < lo or value > hi:
            mode_patch[key] = max(lo, min(hi, value))
    if "direction" in mode_patch and mode_patch["direction"] not in MODE_DIRECTIONS:
        if logger:
            logger.warning("state", "invalid direction {0}, ignoring", mode_patch["direction"])
        del mode_patch["direction"]
    if "color" in mode_patch:
        color = mode_patch["color"]
        if (
            not isinstance(color, list)
            or len(color) != 3
            or any(isinstance(c, bool) or not isinstance(c, (int, float)) for c in color)
        ):
            if logger:
                logger.warning("state", "invalid color {0}, ignoring", color)
            del mode_patch["color"]
        else:
            mode_patch["color"] = [max(0, min(255, int(c))) for c in color]
    return mode_patch


def _validate_leds(data, leds_patch, logger):
    leds_patch = dict(leds_patch)
    if "count" in leds_patch:
        count = leds_patch["count"]
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            if logger:
                logger.warning("state", "invalid leds count {0}, ignoring", count)
            del leds_patch["count"]
        elif count < LEDS_COUNT_MIN:
            leds_patch["count"] = LEDS_COUNT_MIN
    if "protocol" in leds_patch and leds_patch["protocol"] not in LEDS_PROTOCOLS:
        if logger:
            logger.warning("state", "invalid leds protocol {0}, ignoring", leds_patch["protocol"])
        del leds_patch["protocol"]
    if isinstance(leds_patch.get("segmenting"), dict):
        segmenting_patch = dict(leds_patch["segmenting"])
        length = segmenting_patch.get("length")
        if length is not None:
            if isinstance(length, bool) or not isinstance(length, (int, float)):
                if logger:
                    logger.warning("state", "invalid segmenting length {0}, ignoring", length)
                del segmenting_patch["length"]
            elif length < SEGMENT_LENGTH_MIN:
                segmenting_patch["length"] = SEGMENT_LENGTH_MIN
        leds_patch["segmenting"] = segmenting_patch
    return leds_patch


def _validate_system(data, system_patch, logger):
    system_patch = dict(system_patch)
    if "default_mode" in system_patch and system_patch["default_mode"] not in DEFAULT_MODES:
        if logger:
            logger.warning(
                "state", "invalid default_mode {0}, ignoring", system_patch["default_mode"]
            )
        del system_patch["default_mode"]
    if "boot_to_config" in system_patch:
        system_patch["boot_to_config"] = bool(system_patch["boot_to_config"])
    return system_patch


VALIDATORS = {"mode": _validate_mode, "leds": _validate_leds, "system": _validate_system}


class BaseState:
    def __init__(self):
        self._started = time.ticks_ms()

    @property
    def device_id(self):
        return _DEVICE_ID

    @property
    def version(self):
        return VERSION

    @property
    def uptime_ms(self):
        return time.ticks_diff(time.ticks_ms(), self._started)

    def info(self):
        return {
            "id": self.device_id,
            "version": self.version,
            "uptime_ms": self.uptime_ms,
        }


class Mode:
    def __init__(self, state):
        self._state = state

    @property
    def current(self):
        return self._state.get("mode", "current", default="off")

    @property
    def brightness(self):
        return self._state.get("mode", "brightness", default=50)

    @property
    def speed(self):
        return self._state.get("mode", "speed", default=10)

    @property
    def on(self):
        return self._state.get("mode", "on", default=True)

    @property
    def color(self):
        return self._state.get("mode", "color", default=[255, 255, 255])

    @property
    def direction(self):
        return self._state.get("mode", "direction", default="forward")

    def params(self, name=None):
        if name is None:
            name = self.current
        return self._state.get("modes", name, default={})

    def next_mode(self):
        names = sorted(name for name in self._state["modes"].keys() if name != "off")
        current = self.current
        if current in names:
            next_name = names[(names.index(current) + 1) % len(names)]
        else:
            next_name = names[0]
        self._state.update({"mode": {"current": next_name}})
        return next_name


class StateManager(BaseState):
    def __init__(self, data):
        super().__init__()
        self._data = data
        self._subscribers = []
        self.changed = asyncio.Event()
        self.mode = Mode(self)
        self.logger = None

    def set_logger(self, logger):
        self.logger = logger

    def revalidate(self):
        for key, validator in VALIDATORS.items():
            section = self._data.get(key)
            if not isinstance(section, dict):
                continue
            validated = validator(self._data, section, self.logger)
            if validated != section:
                self._data[key] = validated
                self.changed.set()

    def __getitem__(self, key):
        return self._data[key]

    def get(self, *keys, default=None):
        node = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def data(self):
        return self._data

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def update(self, patch):
        patch = dict(patch)
        for key, validator in VALIDATORS.items():
            section_patch = patch.get(key)
            if not isinstance(section_patch, dict):
                continue
            validated = validator(self._data, section_patch, self.logger)
            if validated:
                patch[key] = validated
            else:
                del patch[key]
        if not patch:
            return
        merge(self._data, patch)
        self.changed.set()
        if self.logger:
            self.logger.info("state", "updated keys {0}", list(patch.keys()))
        for callback in self._subscribers:
            callback(patch)
