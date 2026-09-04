import asyncio

from logger.logger import Logger
from renderer import Renderer, SEGMENT_LENGTH_MIN
from state import StateManager


def make_renderer(count=12, segmenting=None, mode_current="rainbow", protocol="ws2812"):
    data = {
        "leds": {
            "count": count,
            "pin": 0,
            "protocol": protocol,
            "segmenting": segmenting or {"enabled": False, "length": 2},
        },
        "mode": {
            "current": mode_current,
            "brightness": 100,
            "speed": 10,
            "on": True,
            "color": [10, 20, 30],
            "direction": "forward",
        },
        "modes": {
            "rainbow": {},
            "static": {},
            "runner": {"length": 1},
        },
    }
    state = StateManager(data)
    logger = Logger(state)
    return Renderer(state, logger), state


def test_segment_count_full_strip_when_segmenting_disabled():
    renderer, _ = make_renderer(count=12, segmenting={"enabled": False, "length": 4})
    anim = renderer._make_animation()
    assert renderer._segment_count(anim) == 12


def test_segment_count_uses_configured_length_when_enabled():
    renderer, _ = make_renderer(count=12, segmenting={"enabled": True, "length": 4})
    anim = renderer._make_animation()
    assert renderer._segment_count(anim) == 4


def test_segment_count_clamps_below_minimum():
    renderer, _ = make_renderer(count=12, segmenting={"enabled": True, "length": 1})
    anim = renderer._make_animation()
    assert renderer._segment_count(anim) == SEGMENT_LENGTH_MIN


def test_segment_count_falls_back_to_full_strip_when_length_exceeds_count():
    renderer, _ = make_renderer(count=12, segmenting={"enabled": True, "length": 20})
    anim = renderer._make_animation()
    assert renderer._segment_count(anim) == 12


def test_segment_count_ignored_for_incompatible_mode():
    renderer, _ = make_renderer(
        count=12, segmenting={"enabled": True, "length": 4}, mode_current="static"
    )
    anim = renderer._make_animation()
    assert renderer._segment_count(anim) == 12


def test_segment_count_ignored_for_runner_mode():
    renderer, _ = make_renderer(
        count=12, segmenting={"enabled": True, "length": 4}, mode_current="runner"
    )
    anim = renderer._make_animation()
    assert renderer._segment_count(anim) == 12


def test_tile_repeats_segment_and_truncates_remainder():
    renderer, _ = make_renderer(count=7, segmenting={"enabled": True, "length": 2})
    buf = bytearray(21)
    buf[0:6] = bytes([1, 2, 3, 4, 5, 6])

    renderer._tile(buf, 2)

    assert bytes(buf) == bytes([1, 2, 3, 4, 5, 6] * 3 + [1, 2, 3])


def test_start_tiles_pixel_buffer_for_compatible_mode():
    renderer, _ = make_renderer(
        count=6, segmenting={"enabled": True, "length": 2}, mode_current="rainbow"
    )

    async def run_one_frame():
        task = asyncio.create_task(renderer.start())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_one_frame())

    buf = renderer.np.buf
    segment = bytes(buf[0:6])
    assert bytes(buf[6:12]) == segment
    assert bytes(buf[12:18]) == segment


def test_reverse_mirrors_pixel_triples_in_place():
    renderer, _ = make_renderer(count=3)
    buf = renderer.np.buf
    buf[:] = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9])

    renderer._reverse(buf)

    assert bytes(buf) == bytes([7, 8, 9, 4, 5, 6, 1, 2, 3])


def test_render_frame_reverses_output_when_direction_backward():
    forward, _ = make_renderer(count=6, mode_current="runner")
    backward, state = make_renderer(count=6, mode_current="runner")
    state.update({"mode": {"direction": "backward"}})

    forward._render_frame(forward._make_animation(), 5)
    backward._render_frame(backward._make_animation(), 5)

    fwd = forward.np.buf
    bwd = backward.np.buf
    assert any(fwd)
    for i in range(6):
        src = i * 3
        dst = (5 - i) * 3
        assert bytes(fwd[src : src + 3]) == bytes(bwd[dst : dst + 3])


def test_start_resizes_pixel_buffer_when_leds_count_changes():
    renderer, state = make_renderer(count=6, mode_current="rainbow")

    async def run_two_frames():
        task = asyncio.create_task(renderer.start())
        await asyncio.sleep(0.01)
        state.update({"leds": {"count": 10}})
        await asyncio.sleep(0.08)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_two_frames())

    assert renderer.count == 10
    assert renderer.np.n == 10
    assert len(renderer.np.buf) == 30


def test_renderer_uses_ws2811_timing_from_config():
    renderer, _ = make_renderer(count=6, protocol="ws2811")
    assert renderer.np.timing == 1


def test_renderer_uses_ws2812_timing_by_default():
    renderer, _ = make_renderer(count=6, protocol="ws2812")
    assert renderer.np.timing == 0


def test_start_reconfigures_strip_when_leds_protocol_changes():
    renderer, state = make_renderer(count=6, mode_current="rainbow", protocol="ws2812")

    async def run_two_frames():
        task = asyncio.create_task(renderer.start())
        await asyncio.sleep(0.01)
        state.update({"leds": {"protocol": "ws2811"}})
        await asyncio.sleep(0.08)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_two_frames())

    assert renderer.protocol == "ws2811"
    assert renderer.np.timing == 1
