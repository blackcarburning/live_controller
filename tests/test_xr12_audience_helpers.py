"""Tests for the pure-Python XR12 helper functions mirrored from live_controller.py.

live_controller.py has top-level PyQt6 imports that prevent importing it in
headless/CI environments, so the pure helpers are mirrored here following the
same pattern as tests/test_zoom_helpers.py.  When updating helper logic in
live_controller.py, update the mirrored section below accordingly.
"""

import unittest
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Mirror of the standalone helpers from live_controller.py.
# live_controller.py cannot be imported in headless CI (PyQt6 top-level),
# so these pure helpers are inlined here following the test_zoom_helpers.py
# pattern.  Keep in sync with live_controller.py when logic changes.
# ---------------------------------------------------------------------------

XR12_AUDIENCE_PORT_INDEX = 3
XR12_AUDIENCE_CHANNELS = (0, 1)
XR12_FADER_STATUS = 0xB0   # CC on MIDI channel 1 (faders: CC 0-15)
XR12_MUTE_STATUS = 0xB1    # CC on MIDI channel 2 (mutes: CC 0-15)

DEFAULT_XR12_AUDIENCE_ENABLED = True
DEFAULT_XR12_AUDIENCE_FADE_SECONDS = 3.0
DEFAULT_XR12_AUDIENCE_OPEN_VALUE = 96
DEFAULT_XR12_AUDIENCE_CLOSED_VALUE = 0
DEFAULT_XR12_AUDIENCE_MUTED_VALUE = 0
DEFAULT_XR12_AUDIENCE_UNMUTED_VALUE = 127
DEFAULT_XR12_MUTED_VALUE = DEFAULT_XR12_AUDIENCE_MUTED_VALUE
DEFAULT_XR12_UNMUTED_VALUE = DEFAULT_XR12_AUDIENCE_UNMUTED_VALUE
LEGACY_DEFAULT_XR12_AUDIENCE_MUTED_VALUE = 127
LEGACY_DEFAULT_XR12_AUDIENCE_UNMUTED_VALUE = 0
DEFAULT_XR12_AUDIENCE_UNITY_VALUE = DEFAULT_XR12_AUDIENCE_OPEN_VALUE


def clamp_midi_value(value):
    """Clamp an arbitrary value into the valid 7-bit MIDI data range."""
    return max(0, min(127, int(round(value))))


def build_audience_fader_messages(value, muted_value=DEFAULT_XR12_MUTED_VALUE,
                                   unmuted_value=DEFAULT_XR12_UNMUTED_VALUE):
    """Build XR12 fader CC messages for linked audience inputs 1-2."""
    midi_value = clamp_midi_value(value)
    return [[XR12_FADER_STATUS, ch, midi_value] for ch in XR12_AUDIENCE_CHANNELS]


def build_audience_mute_messages(muted, muted_value=DEFAULT_XR12_MUTED_VALUE,
                                  unmuted_value=DEFAULT_XR12_UNMUTED_VALUE):
    """Build XR12 mute CC messages for linked audience inputs 1-2."""
    mute_val = muted_value if muted else unmuted_value
    return [[XR12_MUTE_STATUS, ch, mute_val] for ch in XR12_AUDIENCE_CHANNELS]


def interpolate_midi_value(start_value, target_value, progress):
    """Linearly interpolate a MIDI value for the supplied 0-1 progress fraction."""
    bounded = max(0.0, min(1.0, float(progress)))
    return clamp_midi_value(start_value + (target_value - start_value) * bounded)


def migrate_xr12_mute_polarity(config, defaults):
    """Upgrade the old untouched XR12 mute defaults to the verified polarity."""
    if (
        "xr12_audience_muted_value" not in config
        or "xr12_audience_unmuted_value" not in config
    ):
        return
    if (
        defaults.get("xr12_audience_muted_value") == LEGACY_DEFAULT_XR12_AUDIENCE_MUTED_VALUE
        and defaults.get("xr12_audience_unmuted_value") == LEGACY_DEFAULT_XR12_AUDIENCE_UNMUTED_VALUE
    ):
        defaults["xr12_audience_muted_value"] = DEFAULT_XR12_MUTED_VALUE
        defaults["xr12_audience_unmuted_value"] = DEFAULT_XR12_UNMUTED_VALUE


@dataclass
class FadeCommand:
    initial_messages: list
    start_value: int
    target_value: int
    mute_after_fade: bool


class Xr12AudienceState:
    """Pure XR12 audience state machine."""

    def __init__(self, open_value=DEFAULT_XR12_AUDIENCE_OPEN_VALUE,
                 closed_value=DEFAULT_XR12_AUDIENCE_CLOSED_VALUE,
                 muted_value=DEFAULT_XR12_MUTED_VALUE,
                 unmuted_value=DEFAULT_XR12_UNMUTED_VALUE):
        self.open_value = clamp_midi_value(open_value)
        self.closed_value = clamp_midi_value(closed_value)
        self.muted_value = clamp_midi_value(muted_value)
        self.unmuted_value = clamp_midi_value(unmuted_value)
        self.current_value = self.closed_value
        self.muted = True
        self.unity_value = self.open_value

    def set_open_value(self, value):
        self.open_value = clamp_midi_value(value)
        self.unity_value = self.open_value

    def set_closed_value(self, value):
        self.closed_value = clamp_midi_value(value)

    def set_muted_value(self, value):
        self.muted_value = clamp_midi_value(value)

    def set_unmuted_value(self, value):
        self.unmuted_value = clamp_midi_value(value)

    def set_unity_value(self, value):
        self.set_open_value(value)

    def request_open(self):
        if not self.muted and self.current_value == self.open_value:
            return FadeCommand([], self.open_value, self.open_value, False)
        was_muted = self.muted
        start = self.current_value if not was_muted else self.closed_value
        self.muted = False
        initial = []
        if self.current_value == self.closed_value or was_muted:
            initial = (
                build_audience_fader_messages(
                    self.closed_value, self.muted_value, self.unmuted_value
                )
                + build_audience_mute_messages(
                    False, self.muted_value, self.unmuted_value
                )
            )
            self.current_value = self.closed_value
            start = self.closed_value
        return FadeCommand(initial, start, self.open_value, False)

    def request_close(self):
        return FadeCommand([], clamp_midi_value(self.current_value), self.closed_value, True)

    def apply_fader_value(self, value):
        self.current_value = clamp_midi_value(value)
        return build_audience_fader_messages(
            self.current_value, self.muted_value, self.unmuted_value
        )

    def finish_close(self):
        self.current_value = self.closed_value
        self.muted = True
        return build_audience_mute_messages(True, self.muted_value, self.unmuted_value)


def migrate_xr12_config(loaded_config=None):
    defaults = {
        "xr12_audience_enabled": DEFAULT_XR12_AUDIENCE_ENABLED,
        "xr12_audience_fade_duration_sec": DEFAULT_XR12_AUDIENCE_FADE_SECONDS,
        "xr12_audience_open_value": DEFAULT_XR12_AUDIENCE_OPEN_VALUE,
        "xr12_audience_closed_value": DEFAULT_XR12_AUDIENCE_CLOSED_VALUE,
        "xr12_audience_muted_value": DEFAULT_XR12_MUTED_VALUE,
        "xr12_audience_unmuted_value": DEFAULT_XR12_UNMUTED_VALUE,
    }
    config = dict(loaded_config or {})
    defaults.update(config)
    if "xr12_audience_unity_value" in config and "xr12_audience_open_value" not in config:
        defaults["xr12_audience_open_value"] = config["xr12_audience_unity_value"]
    for key, fallback in (
        ("xr12_audience_open_value", DEFAULT_XR12_AUDIENCE_OPEN_VALUE),
        ("xr12_audience_closed_value", DEFAULT_XR12_AUDIENCE_CLOSED_VALUE),
        ("xr12_audience_muted_value", DEFAULT_XR12_MUTED_VALUE),
        ("xr12_audience_unmuted_value", DEFAULT_XR12_UNMUTED_VALUE),
    ):
        try:
            defaults[key] = clamp_midi_value(defaults[key])
        except (TypeError, ValueError, KeyError):
            defaults[key] = fallback
    migrate_xr12_mute_polarity(config, defaults)
    return defaults


class Xr12AudienceHelperTests(unittest.TestCase):
    def test_build_audience_fader_messages_targets_channels_one_and_two(self):
        self.assertEqual(
            build_audience_fader_messages(DEFAULT_XR12_AUDIENCE_OPEN_VALUE),
            [
                [XR12_FADER_STATUS, 0, DEFAULT_XR12_AUDIENCE_OPEN_VALUE],
                [XR12_FADER_STATUS, 1, DEFAULT_XR12_AUDIENCE_OPEN_VALUE],
            ],
        )

    def test_build_audience_mute_messages_target_both_channels(self):
        self.assertEqual(
            build_audience_mute_messages(True),
            [
                [XR12_MUTE_STATUS, 0, 0],
                [XR12_MUTE_STATUS, 1, 0],
            ],
        )
        self.assertEqual(
            build_audience_mute_messages(False),
            [
                [XR12_MUTE_STATUS, 0, 127],
                [XR12_MUTE_STATUS, 1, 127],
            ],
        )

    def test_request_open_starts_from_closed_then_targets_open(self):
        state = Xr12AudienceState()
        command = state.request_open()
        self.assertEqual(command.start_value, DEFAULT_XR12_AUDIENCE_CLOSED_VALUE)
        self.assertEqual(command.target_value, DEFAULT_XR12_AUDIENCE_OPEN_VALUE)
        self.assertFalse(command.mute_after_fade)
        self.assertEqual(
            command.initial_messages,
            [
                [XR12_FADER_STATUS, 0, 0],
                [XR12_FADER_STATUS, 1, 0],
                [XR12_MUTE_STATUS, 0, 127],
                [XR12_MUTE_STATUS, 1, 127],
            ],
        )
        self.assertFalse(state.muted)

    def test_request_open_supports_open_less_than_closed(self):
        state = Xr12AudienceState(open_value=10, closed_value=100)
        command = state.request_open()
        self.assertEqual(command.start_value, 100)
        self.assertEqual(command.target_value, 10)
        self.assertEqual(interpolate_midi_value(command.start_value, command.target_value, 1.0), 10)

    def test_close_reaches_configured_closed_value(self):
        state = Xr12AudienceState(closed_value=20)
        state.muted = False
        state.current_value = 96
        command = state.request_close()
        self.assertEqual(command.target_value, 20)
        self.assertEqual(interpolate_midi_value(command.start_value, command.target_value, 1.0), 20)
        self.assertEqual(state.finish_close(), build_audience_mute_messages(True))
        self.assertEqual(state.current_value, 20)
        self.assertTrue(state.muted)

    def test_interrupted_close_open_starts_from_current(self):
        state = Xr12AudienceState()
        state.muted = False
        state.current_value = 40
        command = state.request_open()
        self.assertEqual(command.start_value, 40)
        self.assertEqual(command.target_value, DEFAULT_XR12_AUDIENCE_OPEN_VALUE)
        self.assertEqual(command.initial_messages, [])

    def test_redundant_open_is_idempotent(self):
        state = Xr12AudienceState()
        state.muted = False
        state.current_value = state.open_value
        command = state.request_open()
        self.assertEqual(command.start_value, command.target_value)
        self.assertEqual(command.target_value, state.open_value)
        self.assertEqual(command.initial_messages, [])

    def test_raw_fader_messages_target_both_channels_with_exact_value(self):
        self.assertEqual(
            build_audience_fader_messages(64),
            [
                [XR12_FADER_STATUS, 0, 64],
                [XR12_FADER_STATUS, 1, 64],
            ],
        )

    def test_raw_mute_messages_target_both_channels(self):
        self.assertEqual(
            build_audience_mute_messages(True, muted_value=42, unmuted_value=0),
            [
                [XR12_MUTE_STATUS, 0, 42],
                [XR12_MUTE_STATUS, 1, 42],
            ],
        )
        self.assertEqual(
            build_audience_mute_messages(False, muted_value=42, unmuted_value=5),
            [
                [XR12_MUTE_STATUS, 0, 5],
                [XR12_MUTE_STATUS, 1, 5],
            ],
        )

    def test_request_close_uses_current_value_and_mutes_after_finish(self):
        state = Xr12AudienceState()
        state.current_value = 72
        command = state.request_close()
        self.assertEqual(command.start_value, 72)
        self.assertEqual(command.target_value, DEFAULT_XR12_AUDIENCE_CLOSED_VALUE)
        self.assertTrue(command.mute_after_fade)
        self.assertEqual(state.finish_close(), build_audience_mute_messages(True))
        self.assertTrue(state.muted)

    def test_interpolate_midi_value_clamps_progress(self):
        self.assertEqual(interpolate_midi_value(0, 96, 0.5), 48)
        self.assertEqual(interpolate_midi_value(0, 96, -1), 0)
        self.assertEqual(interpolate_midi_value(0, 96, 2), 96)

    def test_set_open_value_clamped_to_midi_range(self):
        state = Xr12AudienceState()
        state.set_open_value(200)
        self.assertEqual(state.open_value, 127)
        self.assertEqual(state.unity_value, 127)
        state.set_open_value(-5)
        self.assertEqual(state.open_value, 0)
        state.set_open_value(96)
        self.assertEqual(state.open_value, 96)

    def test_default_open_value_is_96(self):
        state = Xr12AudienceState()
        self.assertEqual(state.open_value, DEFAULT_XR12_AUDIENCE_OPEN_VALUE)
        self.assertEqual(DEFAULT_XR12_AUDIENCE_UNITY_VALUE, 96)

    def test_default_mute_polarity_is_verified(self):
        self.assertEqual(DEFAULT_XR12_MUTED_VALUE, 0)
        self.assertEqual(DEFAULT_XR12_UNMUTED_VALUE, 127)

    def test_config_migration_defaults_and_clamping(self):
        migrated = migrate_xr12_config(
            {
                "xr12_audience_unity_value": 200,
                "xr12_audience_closed_value": -5,
                "xr12_audience_muted_value": 130,
                "xr12_audience_unmuted_value": None,
            }
        )
        self.assertTrue(migrated["xr12_audience_enabled"])
        self.assertEqual(migrated["xr12_audience_fade_duration_sec"], 3.0)
        self.assertEqual(migrated["xr12_audience_open_value"], 127)
        self.assertEqual(migrated["xr12_audience_closed_value"], 0)
        self.assertEqual(migrated["xr12_audience_muted_value"], 127)
        self.assertEqual(migrated["xr12_audience_unmuted_value"], 127)

    def test_config_migration_rewrites_old_untouched_mute_defaults(self):
        migrated = migrate_xr12_config(
            {
                "xr12_audience_muted_value": 127,
                "xr12_audience_unmuted_value": 0,
            }
        )
        self.assertEqual(migrated["xr12_audience_muted_value"], 0)
        self.assertEqual(migrated["xr12_audience_unmuted_value"], 127)

    def test_config_migration_preserves_deliberate_custom_mute_pair(self):
        migrated = migrate_xr12_config(
            {
                "xr12_audience_muted_value": 0,
                "xr12_audience_unmuted_value": 96,
            }
        )
        self.assertEqual(migrated["xr12_audience_muted_value"], 0)
        self.assertEqual(migrated["xr12_audience_unmuted_value"], 96)


if __name__ == "__main__":
    unittest.main()
