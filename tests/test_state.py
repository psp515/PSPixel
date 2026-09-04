from state import VALIDATORS, StateManager, _validate_leds, _validate_mode, _validate_system


def test_get_returns_default_for_missing_path():
    state = StateManager({"mode": {"current": "static"}})
    assert state.get("mode", "brightness", default=42) == 42


def test_update_merges_patch_and_notifies_subscribers():
    state = StateManager({"mode": {"current": "static", "brightness": 40}})
    seen = []
    state.subscribe(lambda patch: seen.append(patch))

    state.update({"mode": {"brightness": 80}})

    assert state.get("mode", "brightness") == 80
    assert state.get("mode", "current") == "static"
    assert seen == [{"mode": {"brightness": 80}}]


def test_mode_helper_reads_through_state():
    state = StateManager({"mode": {"current": "rainbow", "brightness": 10, "speed": 3}})
    assert state.mode.current == "rainbow"
    assert state.mode.brightness == 10
    assert state.mode.speed == 3


def test_update_ignores_unknown_mode_current():
    state = StateManager({"mode": {"current": "static"}, "modes": {"static": {}, "rainbow": {}}})
    seen = []
    state.subscribe(lambda patch: seen.append(patch))

    state.update({"mode": {"current": "sparkle"}})

    assert state.mode.current == "static"
    assert seen == []


def test_update_applies_other_fields_when_mode_current_unknown():
    state = StateManager(
        {"mode": {"current": "static", "brightness": 40}, "modes": {"static": {}}}
    )

    state.update({"mode": {"current": "sparkle", "brightness": 80}})

    assert state.mode.current == "static"
    assert state.mode.brightness == 80


def test_update_allows_known_mode_current():
    state = StateManager({"mode": {"current": "static"}, "modes": {"static": {}, "rainbow": {}}})

    state.update({"mode": {"current": "rainbow"}})

    assert state.mode.current == "rainbow"


def test_update_clamps_brightness_and_speed_to_1_100():
    state = StateManager({"mode": {"current": "static", "brightness": 50, "speed": 50}})

    state.update({"mode": {"brightness": 500, "speed": -5}})

    assert state.mode.brightness == 100
    assert state.mode.speed == 1


def test_update_ignores_non_numeric_brightness():
    state = StateManager({"mode": {"current": "static", "brightness": 50}})
    seen = []
    state.subscribe(lambda patch: seen.append(patch))

    state.update({"mode": {"brightness": "bright"}})

    assert state.mode.brightness == 50
    assert seen == []


def test_update_ignores_bool_speed():
    state = StateManager({"mode": {"current": "static", "speed": 50}})

    state.update({"mode": {"speed": True}})

    assert state.mode.speed == 50


def test_update_allows_valid_color_and_clamps_components():
    state = StateManager({"mode": {"current": "static", "color": [1, 2, 3]}})

    state.update({"mode": {"color": [300, -5, 128]}})

    assert state.mode.color == [255, 0, 128]


def test_update_ignores_malformed_color():
    state = StateManager({"mode": {"current": "static", "color": [1, 2, 3]}})

    state.update({"mode": {"color": [255, 255]}})
    state.update({"mode": {"color": "red"}})
    state.update({"mode": {"color": [255, True, 0]}})

    assert state.mode.color == [1, 2, 3]


def test_update_allows_valid_direction():
    state = StateManager({"mode": {"current": "static", "direction": "forward"}})

    state.update({"mode": {"direction": "backward"}})

    assert state.mode.direction == "backward"


def test_update_ignores_unknown_direction():
    state = StateManager({"mode": {"current": "static", "direction": "forward"}})

    state.update({"mode": {"direction": "sideways"}})

    assert state.mode.direction == "forward"


def test_mode_color_and_direction_defaults():
    state = StateManager({"mode": {"current": "static"}})
    assert state.mode.color == [255, 255, 255]
    assert state.mode.direction == "forward"


def test_mode_brightness_defaults_to_50():
    state = StateManager({"mode": {"current": "static"}})
    assert state.mode.brightness == 50


def test_update_clamps_segmenting_length_to_minimum():
    state = StateManager({"leds": {"count": 100, "segmenting": {"enabled": True, "length": 10}}})

    state.update({"leds": {"segmenting": {"length": 1}}})

    assert state.get("leds", "segmenting", "length") == 2


def test_update_ignores_non_numeric_segmenting_length():
    state = StateManager({"leds": {"count": 100, "segmenting": {"enabled": True, "length": 10}}})

    state.update({"leds": {"segmenting": {"length": "many"}}})

    assert state.get("leds", "segmenting", "length") == 10


def test_update_allows_valid_segmenting_length():
    state = StateManager({"leds": {"count": 100, "segmenting": {"enabled": False, "length": 2}}})

    state.update({"leds": {"segmenting": {"enabled": True, "length": 8}}})

    assert state.get("leds", "segmenting") == {"enabled": True, "length": 8}


def test_update_allows_valid_leds_count():
    state = StateManager({"leds": {"count": 8, "pin": 0}})

    state.update({"leds": {"count": 20}})

    assert state.get("leds", "count") == 20


def test_update_clamps_leds_count_to_minimum():
    state = StateManager({"leds": {"count": 8, "pin": 0}})

    state.update({"leds": {"count": -5}})

    assert state.get("leds", "count") == 1


def test_update_ignores_non_numeric_leds_count():
    state = StateManager({"leds": {"count": 8, "pin": 0}})

    state.update({"leds": {"count": "many"}})

    assert state.get("leds", "count") == 8


def test_update_allows_valid_leds_protocol():
    state = StateManager({"leds": {"count": 8, "pin": 0, "protocol": "ws2812"}})

    state.update({"leds": {"protocol": "ws2811"}})

    assert state.get("leds", "protocol") == "ws2811"


def test_update_ignores_invalid_leds_protocol():
    state = StateManager({"leds": {"count": 8, "pin": 0, "protocol": "ws2812"}})

    state.update({"leds": {"protocol": "sk6812"}})

    assert state.get("leds", "protocol") == "ws2812"


def test_validate_mode_drops_unknown_current_in_isolation():
    data = {"modes": {"static": {}, "rainbow": {}}}

    result = _validate_mode(data, {"current": "sparkle", "brightness": 80}, logger=None)

    assert result == {"brightness": 80}


def test_validate_mode_clamps_range_in_isolation():
    result = _validate_mode({"modes": {}}, {"brightness": 500, "speed": -5}, logger=None)

    assert result == {"brightness": 100, "speed": 1}


def test_validate_mode_drops_non_numeric_field_in_isolation():
    result = _validate_mode({"modes": {}}, {"speed": True}, logger=None)

    assert result == {}


def test_validate_leds_clamps_count_in_isolation():
    result = _validate_leds({}, {"count": -5}, logger=None)

    assert result == {"count": 1}


def test_validate_leds_clamps_segmenting_length_in_isolation():
    result = _validate_leds({}, {"segmenting": {"length": 1}}, logger=None)

    assert result == {"segmenting": {"length": 2}}


def test_validate_leds_ignores_non_numeric_segmenting_length_in_isolation():
    result = _validate_leds({}, {"segmenting": {"enabled": True, "length": "many"}}, logger=None)

    assert result == {"segmenting": {"enabled": True}}


def test_validators_registry_covers_mode_leds_and_system():
    assert set(VALIDATORS) == {"mode", "leds", "system"}
    assert VALIDATORS["mode"] is _validate_mode
    assert VALIDATORS["leds"] is _validate_leds
    assert VALIDATORS["system"] is _validate_system


def test_revalidate_clamps_out_of_range_values_loaded_from_disk():
    state = StateManager(
        {"mode": {"current": "static", "brightness": 128, "speed": -5}, "modes": {"static": {}}}
    )

    state.revalidate()

    assert state.mode.brightness == 100
    assert state.mode.speed == 1


def test_revalidate_clamps_leds_section_loaded_from_disk():
    state = StateManager({"leds": {"count": -5, "segmenting": {"enabled": True, "length": 1}}})

    state.revalidate()

    assert state.get("leds", "count") == 1
    assert state.get("leds", "segmenting", "length") == 2


def test_revalidate_leaves_valid_data_untouched_and_does_not_mark_changed():
    state = StateManager(
        {"mode": {"current": "static", "brightness": 50, "speed": 10}, "modes": {"static": {}}}
    )

    state.revalidate()

    assert state.mode.brightness == 50
    assert state.mode.speed == 10
    assert not state.changed.is_set()


def test_revalidate_marks_changed_when_a_value_gets_corrected():
    state = StateManager({"mode": {"current": "static", "brightness": 128}})

    state.revalidate()

    assert state.changed.is_set()


def test_update_passes_through_sections_without_a_validator_untouched():
    state = StateManager({"network": {"wifi": {"ssid": "", "password": ""}}})

    state.update({"network": {"wifi": {"ssid": "MyNetwork", "password": "hunter2"}}})

    assert state.get("network", "wifi", "ssid") == "MyNetwork"
    assert state.get("network", "wifi", "password") == "hunter2"


def test_update_drops_invalid_default_mode():
    state = StateManager({"system": {"default_mode": "normal", "boot_to_config": False}})

    state.update({"system": {"default_mode": "party"}})

    assert state.get("system", "default_mode") == "normal"


def test_update_allows_valid_default_mode():
    state = StateManager({"system": {"default_mode": "normal", "boot_to_config": False}})

    state.update({"system": {"default_mode": "mqtt-ssl"}})

    assert state.get("system", "default_mode") == "mqtt-ssl"


def test_update_coerces_boot_to_config_to_bool():
    state = StateManager({"system": {"default_mode": "normal", "boot_to_config": False}})

    state.update({"system": {"boot_to_config": 1}})

    assert state.get("system", "boot_to_config") is True
