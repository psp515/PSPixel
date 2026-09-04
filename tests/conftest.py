import asyncio
import sys
import time
import types

# MicroPython-only helpers used by src/state.py. Patched onto the real `time`
# module so CPython can import and exercise that code under test.
if not hasattr(time, "ticks_ms"):
    time.ticks_ms = lambda: int(time.monotonic() * 1000)
if not hasattr(time, "ticks_diff"):
    time.ticks_diff = lambda a, b: a - b

# uasyncio-only helper used by src/renderer.py. Patched onto the real
# `asyncio` module so CPython can import and exercise that code under test.
if not hasattr(asyncio, "sleep_ms"):
    asyncio.sleep_ms = lambda ms: asyncio.sleep(ms / 1000)

# channels/mqtt.py imports these MicroPython-only libraries at module level.
# Stub them so CPython can import and exercise that code under test.
if "mqtt_as" not in sys.modules:
    mqtt_as_stub = types.ModuleType("mqtt_as")
    mqtt_as_stub.config = {}

    class _MQTTClientStub:
        def __init__(self, cfg):
            self.cfg = cfg

    mqtt_as_stub.MQTTClient = _MQTTClientStub
    sys.modules["mqtt_as"] = mqtt_as_stub

if "machine" not in sys.modules:
    machine_stub = types.ModuleType("machine")

    class _RTCStub:
        def datetime(self, value=None):
            self.value = value

    class _PinStub:
        IN = 0
        OUT = 1
        PULL_UP = 2

        def __init__(self, pin, *args, **kwargs):
            self.pin = pin

        def value(self):
            return 1

    class _WDTStub:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def feed(self):
            pass

    machine_stub.RTC = _RTCStub
    machine_stub.unique_id = lambda: b"dev"
    machine_stub.Pin = _PinStub
    machine_stub.WDT = _WDTStub
    machine_stub.reset = lambda: None
    sys.modules["machine"] = machine_stub

# channels/ir.py imports ir_rx.nec (Peter Hinch micropython_ir), a
# MicroPython-only library. Stub it so CPython can import and exercise that
# code under test.
if "ir_rx" not in sys.modules:
    ir_rx_stub = types.ModuleType("ir_rx")
    ir_rx_nec_stub = types.ModuleType("ir_rx.nec")

    class _NEC8Stub:
        def __init__(self, pin, callback):
            self.pin = pin
            self.callback = callback
            self.closed = False

        def close(self):
            self.closed = True

    ir_rx_nec_stub.NEC_8 = _NEC8Stub
    ir_rx_stub.nec = ir_rx_nec_stub
    sys.modules["ir_rx"] = ir_rx_stub
    sys.modules["ir_rx.nec"] = ir_rx_nec_stub

# channels/network.py imports network, a MicroPython-only module. Stub it so
# CPython can import and exercise that code under test; tests replace the
# channel's _wlan with their own fake.
if "network" not in sys.modules:
    network_stub = types.ModuleType("network")
    network_stub.STA_IF = 0
    network_stub.AP_IF = 1

    class _WLANStub:
        def __init__(self, interface):
            self.interface = interface

        def active(self, value=None):
            pass

        def connect(self, ssid, password):
            pass

        def isconnected(self):
            return False

        def disconnect(self):
            pass

        def config(self, **kwargs):
            pass

        def ifconfig(self):
            return ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")

        def scan(self):
            return []

    network_stub.WLAN = _WLANStub
    sys.modules["network"] = network_stub

# renderer.py imports neopixel, a MicroPython-only driver. Stub it with a
# bytearray-backed buffer so CPython can exercise the renderer's tiling logic.
if "neopixel" not in sys.modules:
    neopixel_stub = types.ModuleType("neopixel")

    class _NeoPixelStub:
        def __init__(self, pin, n, bpp=3, timing=0):
            self.pin = pin
            self.n = n
            self.timing = timing
            self.buf = bytearray(n * bpp)

        def write(self):
            pass

    neopixel_stub.NeoPixel = _NeoPixelStub
    sys.modules["neopixel"] = neopixel_stub
