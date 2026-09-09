from animations.base import WIPE_INTERVAL_MS
from animations.blink import BLINK_MIN_MS, Blink
from animations.pspixel import PSPixel
from animations.rainbow import Rainbow
from animations.runner import Runner
from animations.static import Static
from animations.white import White
from state import StateManager


def make_mode(color=None, brightness=100, speed=10):
    state = StateManager(
        {
            "mode": {
                "current": "static",
                "brightness": brightness,
                "speed": speed,
                "on": True,
                "color": color or [255, 255, 255],
                "direction": "forward",
            },
            "modes": {
                "static": {},
                "white": {},
                "blink": {},
                "rainbow": {},
                "runner": {"length": 5},
                "pspixel": {},
            },
        }
    )
    return state.mode


def render_until_wipe_done(anim, count):
    buffer = bytearray(count * 3)
    for frame in range(anim.wipe_frames(count) + 1):
        anim.render(buffer, count, frame)
    return buffer


def test_static_first_frame_is_dark():
    mode = make_mode(color=[10, 20, 30])
    anim = Static(mode, mode.params("static"))
    buffer = bytearray(12)

    anim.render(buffer, 4, 0)

    assert buffer == bytearray(12)
    assert anim.interval_ms == WIPE_INTERVAL_MS


def test_static_wipe_fills_from_start():
    mode = make_mode(color=[10, 20, 30])
    anim = Static(mode, mode.params("static"))
    count = 20
    buffer = bytearray(count * 3)

    anim.render(buffer, count, 10)

    assert bytes(buffer[0:3]) == bytes([20, 10, 30])
    assert 0 < buffer[21] < 20
    assert bytes(buffer[-3:]) == bytes(3)


def test_static_after_wipe_full_color_and_slow_interval():
    mode = make_mode(color=[10, 20, 30])
    anim = Static(mode, mode.params("static"))

    buffer = render_until_wipe_done(anim, 4)

    assert bytes(buffer) == bytes([20, 10, 30] * 4)
    assert anim.interval_ms == 500


def test_white_ignores_mode_color():
    mode = make_mode(color=[10, 20, 30])
    anim = White(mode, mode.params("white"))

    buffer = render_until_wipe_done(anim, 2)

    assert bytes(buffer) == bytes([255] * 6)


def test_blink_alternates_lit_and_dark_on_even_odd_frames():
    mode = make_mode(color=[10, 20, 30], speed=100)
    anim = Blink(mode, mode.params("blink"))
    count = 4
    buffer = bytearray(count * 3)

    anim.render(buffer, count, 0)
    assert bytes(buffer) == bytes([20, 10, 30] * count)

    anim.render(buffer, count, 1)
    assert bytes(buffer) == bytes(count * 3)


def test_blink_interval_scales_with_speed_and_has_a_floor():
    fast = Blink(make_mode(speed=100), {})
    slow = Blink(make_mode(speed=1), {})

    assert fast.interval_ms == BLINK_MIN_MS
    assert slow.interval_ms > fast.interval_ms


def test_rainbow_first_frame_is_dark_then_fills():
    mode = make_mode()
    anim = Rainbow(mode, mode.params("rainbow"))
    count = 8
    buffer = bytearray(count * 3)

    anim.render(buffer, count, 0)
    assert buffer == bytearray(count * 3)

    buffer = render_until_wipe_done(anim, count)
    assert any(buffer)
    for i in range(count):
        assert any(buffer[i * 3 : i * 3 + 3])


def test_rainbow_scrolls_after_wipe():
    mode = make_mode()
    anim = Rainbow(mode, mode.params("rainbow"))
    count = 8
    done = anim.wipe_frames(count)
    first = bytearray(count * 3)
    second = bytearray(count * 3)

    anim.render(first, count, done)
    anim.render(second, count, done + 1)

    assert bytes(first) != bytes(second)


def test_runner_enters_from_start_without_wrapping():
    mode = make_mode(color=[255, 255, 255], speed=100)
    anim = Runner(mode, mode.params("runner"))
    count = 10
    buffer = bytearray(count * 3)

    anim.render(buffer, count, 1)

    assert any(buffer[0:9])
    assert bytes(buffer[9:]) == bytes(count * 3 - 9)


def test_runner_trail_middle_is_brightest_and_symmetric():
    mode = make_mode(color=[255, 255, 255], speed=100)
    anim = Runner(mode, mode.params("runner"))
    count = 12
    buffer = bytearray(count * 3)

    anim.render(buffer, count, 2)

    levels = [buffer[i * 3] for i in range(count)]
    assert levels[6] == 0
    assert levels[3] == levels[4] == max(levels)
    assert levels[2] == levels[5]
    assert 0 < levels[2] < levels[3]


def test_runner_moves_sub_pixel_between_frames():
    mode = make_mode(color=[255, 255, 255], speed=50)
    anim = Runner(mode, mode.params("runner"))
    count = 12
    first = bytearray(count * 3)
    second = bytearray(count * 3)

    anim.render(first, count, 2)
    anim.render(second, count, 3)

    assert bytes(first) != bytes(second)
    assert 0 < second[3 * 3] < 255


def test_runner_wraps_after_first_pass():
    mode = make_mode(color=[255, 255, 255], speed=100)
    anim = Runner(mode, mode.params("runner"))
    count = 12
    buffer = bytearray(count * 3)

    anim.render(buffer, count, 5)

    assert any(buffer[0:3])
    assert any(buffer[-3:])


def pspixel_levels(anim, count, frame):
    buffer = bytearray(count * 3)
    anim.render(buffer, count, frame)
    return [sum(buffer[i * 3 : i * 3 + 3]) for i in range(count)]


def test_pspixel_dot_width_scales_with_strip_length():
    mode = make_mode(speed=100)
    anim = PSPixel(mode, {"trails": 1, "length": 6})

    levels = pspixel_levels(anim, 100, 0)

    assert levels[49] > levels[48] > levels[47] > levels[46]
    assert levels[51] < levels[50] < levels[49]
    assert levels[52] < levels[51]


def test_pspixel_edge_anchors_are_half_dots():
    mode = make_mode(speed=100)
    anim = PSPixel(mode, {"trails": 1, "length": 6})

    levels = pspixel_levels(anim, 100, 10)

    assert levels[0] > levels[1] > levels[2] > levels[3]
    assert levels[99] > levels[98] > levels[97] > levels[96]


def test_pspixel_comet_is_dim_at_both_ends():
    mode = make_mode(speed=100)
    anim = PSPixel(mode, {"trails": 1, "length": 6})

    levels = pspixel_levels(anim, 60, 2)

    assert levels[3] == max(levels[2:7])
    assert levels[2] > levels[6]
    assert levels[5] > levels[6]
    assert levels[4] > levels[5]


def test_pspixel_trails_param_spreads_comets_around_strip():
    mode = make_mode(speed=100)
    one = PSPixel(mode, {"trails": 1, "length": 6})
    two = PSPixel(mode, {"trails": 2, "length": 6})

    single = pspixel_levels(one, 60, 2)
    double = pspixel_levels(two, 60, 2)

    assert double[33] > single[33]
    assert double[3] == single[3]


def test_pspixel_comet_moves_between_frames():
    mode = make_mode(speed=100)
    anim = PSPixel(mode, {"trails": 1, "length": 6})

    first = pspixel_levels(anim, 60, 2)
    second = pspixel_levels(anim, 60, 3)

    assert first != second


def test_pspixel_anchors_pulse_over_time():
    mode = make_mode(speed=100)
    anim = PSPixel(mode, {"trails": 1, "length": 6})

    first = pspixel_levels(anim, 60, 0)
    later = pspixel_levels(anim, 60, 20)

    assert first[29] != later[29]


def test_pspixel_ignores_mode_color():
    warm = PSPixel(make_mode(color=[255, 0, 0], speed=100), {"trails": 1, "length": 6})
    cold = PSPixel(make_mode(color=[0, 0, 255], speed=100), {"trails": 1, "length": 6})

    assert pspixel_levels(warm, 60, 2) == pspixel_levels(cold, 60, 2)


def test_pspixel_applies_brightness():
    full = PSPixel(make_mode(brightness=100, speed=100), {"trails": 1, "length": 6})
    dim = PSPixel(make_mode(brightness=20, speed=100), {"trails": 1, "length": 6})

    assert sum(pspixel_levels(dim, 60, 2)) < sum(pspixel_levels(full, 60, 2))


def test_pspixel_default_params_render_whole_strip():
    mode = make_mode(speed=100)
    anim = PSPixel(mode, mode.params("pspixel"))

    levels = pspixel_levels(anim, 144, 5)

    assert all(level > 0 for level in levels)
    assert anim.segmenting_compatible is False


def test_pspixel_registered_with_defaults():
    from animations.registry import MODES
    from defaults import DEFAULTS

    assert MODES["pspixel"] is PSPixel
    assert DEFAULTS["modes"]["pspixel"] == {"trails": 2, "length": 10, "dot_size": 0}
