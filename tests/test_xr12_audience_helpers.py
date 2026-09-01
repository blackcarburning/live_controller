"""Tests for the pure-Python XR12 helper functions mirrored from live_controller.py.

live_controller.py has top-level PyQt6 imports that prevent importing it in
headless/CI environments, so the pure helpers are mirrored here following the
same pattern as tests/test_zoom_helpers.py.  When updating helper logic in
live_controller.py, update the mirrored section below accordingly.
"""

import unittest
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Mirror of the standalone helpers from live_controller.py.
# live_controller.py cannot be imported in headless CI (PyQt6 top-level),
# so these pure helpers are inlined here following the test_zoom_helpers.py
# pattern.  Keep in sync with live_controller.py when logic changes.
# ---------------------------------------------------------------------------

XR12_AUDIENCE_PORT_INDEX = 3
XR12_AUDIENCE_CHANNELS = (0, 1)
XR12_NUM_CHANNELS = 4
XR12_FADER_STATUS = 0xB0   # CC on MIDI channel 1 (faders: CC 0-15)
XR12_MUTE_STATUS = 0xB1    # CC on MIDI channel 2 (mutes) — kept for compat; never sent automatically

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
DEFAULT_XR12_CH_ENABLED = [True, True, False, False]
DEFAULT_XR12_CH_OPEN_VALUES = [DEFAULT_XR12_AUDIENCE_OPEN_VALUE] * XR12_NUM_CHANNELS


def clamp_midi_value(value):
    """Clamp an arbitrary value into the valid 7-bit MIDI data range."""
    return max(0, min(127, int(round(value))))


def build_audience_fader_messages(value, muted_value=DEFAULT_XR12_MUTED_VALUE,
                                   unmuted_value=DEFAULT_XR12_UNMUTED_VALUE,
                                   channels=None):
    """Build XR12 fader CC messages for the selected audience inputs."""
    midi_value = clamp_midi_value(value)
    chs = channels if channels is not None else XR12_AUDIENCE_CHANNELS
    return [[XR12_FADER_STATUS, ch, midi_value] for ch in chs]


def build_audience_mute_messages(muted, muted_value=DEFAULT_XR12_MUTED_VALUE,
                                  unmuted_value=DEFAULT_XR12_UNMUTED_VALUE,
                                  channels=None):
    """Build XR12 mute CC messages. Kept for compatibility; not called by automatic control."""
    mute_val = muted_value if muted else unmuted_value
    chs = channels if channels is not None else XR12_AUDIENCE_CHANNELS
    return [[XR12_MUTE_STATUS, ch, mute_val] for ch in chs]


def interpolate_midi_value(start_value, target_value, progress):
    """Linearly interpolate a MIDI value for the supplied 0-1 progress fraction."""
    bounded = max(0.0, min(1.0, float(progress)))
    return clamp_midi_value(start_value + (target_value - start_value) * bounded)


@dataclass
class FadeCommand:
    initial_messages: list
    start_value: int
    target_value: int
    mute_after_fade: bool


class Xr12AudienceState:
    """Pure XR12 audience state machine. Fader-only; no automatic mute CC messages."""

    def __init__(self, open_value=DEFAULT_XR12_AUDIENCE_OPEN_VALUE,
                 closed_value=DEFAULT_XR12_AUDIENCE_CLOSED_VALUE,
                 muted_value=DEFAULT_XR12_MUTED_VALUE,
                 unmuted_value=DEFAULT_XR12_UNMUTED_VALUE,
                 channel=None):
        self.open_value = clamp_midi_value(open_value)
        self.closed_value = clamp_midi_value(closed_value)
        self.muted_value = clamp_midi_value(muted_value)
        self.unmuted_value = clamp_midi_value(unmuted_value)
        self.current_value = self.closed_value
        self.muted = True
        self._channels = (channel,) if channel is not None else XR12_AUDIENCE_CHANNELS
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
        """Fade to open value using only fader CC messages. No mute CC sent."""
        if self.current_value == self.open_value:
            return FadeCommand([], self.open_value, self.open_value, False)
        start = self.current_value
        self.muted = False
        return FadeCommand(
            initial_messages=[],
            start_value=start,
            target_value=self.open_value,
            mute_after_fade=False,
        )

    def request_close(self):
        """Fade to closed value using only fader CC messages. No mute CC sent."""
        return FadeCommand(
            initial_messages=[],
            start_value=clamp_midi_value(self.current_value),
            target_value=self.closed_value,
            mute_after_fade=False,
        )

    def apply_fader_value(self, value):
        self.current_value = clamp_midi_value(value)
        return build_audience_fader_messages(
            self.current_value, self.muted_value, self.unmuted_value,
            channels=self._channels,
        )

    def finish_close(self):
        """Update internal state after a close fade. Returns empty list (no mute CC)."""
        self.current_value = self.closed_value
        self.muted = True
        return []


def migrate_xr12_config(loaded_config=None):
    defaults = {
        "xr12_audience_enabled": DEFAULT_XR12_AUDIENCE_ENABLED,
        "xr12_audience_fade_duration_sec": DEFAULT_XR12_AUDIENCE_FADE_SECONDS,
        "xr12_audience_open_value": DEFAULT_XR12_AUDIENCE_OPEN_VALUE,
        "xr12_audience_closed_value": DEFAULT_XR12_AUDIENCE_CLOSED_VALUE,
    }
    config = dict(loaded_config or {})
    defaults.update(config)
    if "xr12_audience_unity_value" in config and "xr12_audience_open_value" not in config:
        defaults["xr12_audience_open_value"] = config["xr12_audience_unity_value"]
    # Migrate per-channel open values -> shared open value (prefer ch1's value)
    if "xr12_audience_open_value" not in config:
        for i in range(XR12_NUM_CHANNELS):
            ch_num = i + 1
            per_ch_key = f"xr12_audience_ch{ch_num}_open_value"
            if per_ch_key in config:
                try:
                    defaults["xr12_audience_open_value"] = clamp_midi_value(config[per_ch_key])
                    break
                except (TypeError, ValueError):
                    pass
    for key, fallback in (
        ("xr12_audience_open_value", DEFAULT_XR12_AUDIENCE_OPEN_VALUE),
        ("xr12_audience_closed_value", DEFAULT_XR12_AUDIENCE_CLOSED_VALUE),
    ):
        try:
            defaults[key] = clamp_midi_value(defaults[key])
        except (TypeError, ValueError, KeyError):
            defaults[key] = fallback
    for i in range(XR12_NUM_CHANNELS):
        ch_num = i + 1
        enabled_key = f"xr12_audience_ch{ch_num}_enabled"
        defaults.setdefault(enabled_key, DEFAULT_XR12_CH_ENABLED[i])
    return defaults


class MirroredXr12AudienceController:
    def __init__(self, ch_enabled=None, open_value=DEFAULT_XR12_AUDIENCE_OPEN_VALUE,
                 closed_value=DEFAULT_XR12_AUDIENCE_CLOSED_VALUE):
        self._ch_enabled = list(ch_enabled if ch_enabled is not None else DEFAULT_XR12_CH_ENABLED)
        self._ch_states = [
            Xr12AudienceState(open_value=open_value, closed_value=closed_value, channel=i)
            for i in range(XR12_NUM_CHANNELS)
        ]


class Xr12AudienceHelperTests(unittest.TestCase):

    def test_build_audience_fader_messages_targets_channels_one_and_two(self):
        self.assertEqual(
            build_audience_fader_messages(DEFAULT_XR12_AUDIENCE_OPEN_VALUE),
            [
                [XR12_FADER_STATUS, 0, DEFAULT_XR12_AUDIENCE_OPEN_VALUE],
                [XR12_FADER_STATUS, 1, DEFAULT_XR12_AUDIENCE_OPEN_VALUE],
            ],
        )

    def test_build_audience_fader_messages_with_explicit_channels_targets_exactly_those_channels(self):
        self.assertEqual(
            build_audience_fader_messages(90, channels=(1, 3)),
            [
                [XR12_FADER_STATUS, 1, 90],
                [XR12_FADER_STATUS, 3, 90],
            ],
        )

    def test_request_open_sends_only_fader_messages_no_mute_cc(self):
        state = Xr12AudienceState()
        command = state.request_open()
        self.assertEqual(command.start_value, DEFAULT_XR12_AUDIENCE_CLOSED_VALUE)
        self.assertEqual(command.target_value, DEFAULT_XR12_AUDIENCE_OPEN_VALUE)
        self.assertFalse(command.mute_after_fade)
        # No initial messages - no mute CC 0xB1 sent on open
        self.assertEqual(command.initial_messages, [])
        self.assertFalse(state.muted)

    def test_no_0xb1_messages_from_request_open(self):
        state = Xr12AudienceState()
        command = state.request_open()
        for msg in command.initial_messages:
            self.assertNotEqual(msg[0], XR12_MUTE_STATUS, "request_open must not emit 0xB1 mute CC")

    def test_no_0xb1_messages_from_request_close(self):
        state = Xr12AudienceState()
        state.current_value = 96
        command = state.request_close()
        for msg in command.initial_messages:
            self.assertNotEqual(msg[0], XR12_MUTE_STATUS, "request_close must not emit 0xB1 mute CC")
        self.assertFalse(command.mute_after_fade)

    def test_no_0xb1_messages_from_finish_close(self):
        state = Xr12AudienceState()
        state.current_value = 96
        msgs = state.finish_close()
        self.assertEqual(msgs, [], "finish_close must return empty list - no mute CC")

    def test_request_open_supports_open_less_than_closed(self):
        state = Xr12AudienceState(open_value=10, closed_value=100)
        state.current_value = 100
        command = state.request_open()
        self.assertEqual(command.start_value, 100)
        self.assertEqual(command.target_value, 10)
        self.assertEqual(interpolate_midi_value(command.start_value, command.target_value, 1.0), 10)

    def test_close_reaches_configured_closed_value_via_fader_only(self):
        state = Xr12AudienceState(closed_value=20)
        state.muted = False
        state.current_value = 96
        command = state.request_close()
        self.assertEqual(command.target_value, 20)
        self.assertEqual(interpolate_midi_value(command.start_value, command.target_value, 1.0), 20)
        # finish_close returns no messages (no mute CC)
        self.assertEqual(state.finish_close(), [])
        self.assertEqual(state.current_value, 20)
        self.assertTrue(state.muted)

    def test_close_with_low_value_zero_sends_fader_zero(self):
        """Setting low/closed to 0 produces fader value 0 on selected channels."""
        state = Xr12AudienceState(closed_value=0, channel=0)
        state.current_value = 96
        command = state.request_close()
        self.assertEqual(command.target_value, 0)
        msgs = state.apply_fader_value(command.target_value)
        self.assertEqual(msgs, [[XR12_FADER_STATUS, 0, 0]])
        for msg in msgs:
            self.assertNotEqual(msg[0], XR12_MUTE_STATUS)

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

    def test_request_close_uses_current_value_and_no_mute_after(self):
        state = Xr12AudienceState()
        state.current_value = 72
        command = state.request_close()
        self.assertEqual(command.start_value, 72)
        self.assertEqual(command.target_value, DEFAULT_XR12_AUDIENCE_CLOSED_VALUE)
        self.assertFalse(command.mute_after_fade)
        self.assertEqual(state.finish_close(), [])
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

    def test_default_channel_enablement_has_first_two_channels_only(self):
        controller = MirroredXr12AudienceController()
        self.assertEqual(controller._ch_enabled, [True, True, False, False])

    def test_config_migration_defaults_and_clamping(self):
        migrated = migrate_xr12_config(
            {
                "xr12_audience_unity_value": 200,
                "xr12_audience_closed_value": -5,
            }
        )
        self.assertTrue(migrated["xr12_audience_enabled"])
        self.assertEqual(migrated["xr12_audience_fade_duration_sec"], 3.0)
        self.assertEqual(migrated["xr12_audience_open_value"], 127)
        self.assertEqual(migrated["xr12_audience_closed_value"], 0)
        self.assertEqual(migrated["xr12_audience_ch1_enabled"], True)
        self.assertEqual(migrated["xr12_audience_ch4_enabled"], False)

    def test_config_migration_derives_shared_open_value_from_ch1(self):
        """Migration from per-channel config prefers ch1's saved open value."""
        migrated = migrate_xr12_config({
            "xr12_audience_ch1_open_value": 88,
            "xr12_audience_ch2_open_value": 72,
        })
        self.assertEqual(migrated["xr12_audience_open_value"], 88)

    def test_config_migration_falls_back_to_first_valid_channel_value(self):
        """If ch1 has no saved value, use the first channel that does."""
        migrated = migrate_xr12_config({
            "xr12_audience_ch2_open_value": 80,
        })
        self.assertEqual(migrated["xr12_audience_open_value"], 80)

    def test_config_migration_skips_invalid_ch1_and_uses_ch2(self):
        """If ch1 has an invalid value, migration skips it and uses the next valid channel."""
        migrated = migrate_xr12_config({
            "xr12_audience_ch1_open_value": None,
            "xr12_audience_ch2_open_value": 75,
        })
        self.assertEqual(migrated["xr12_audience_open_value"], 75)

    def test_config_migration_defaults_to_96_when_no_per_channel_values(self):
        migrated = migrate_xr12_config({})
        self.assertEqual(migrated["xr12_audience_open_value"], DEFAULT_XR12_AUDIENCE_OPEN_VALUE)

    def test_config_migration_preserves_explicit_shared_open_value(self):
        migrated = migrate_xr12_config({"xr12_audience_open_value": 90})
        self.assertEqual(migrated["xr12_audience_open_value"], 90)

    def test_config_round_trip_preserves_four_channels_and_shared_levels(self):
        """Config round-trip preserves channel checkboxes, shared high/low, and fade duration."""
        config = {
            "xr12_audience_ch1_enabled": True,
            "xr12_audience_ch2_enabled": True,
            "xr12_audience_ch3_enabled": False,
            "xr12_audience_ch4_enabled": False,
            "xr12_audience_open_value": 100,
            "xr12_audience_closed_value": 10,
            "xr12_audience_fade_duration_sec": 2.5,
        }
        migrated = migrate_xr12_config(config)
        self.assertEqual(migrated["xr12_audience_ch1_enabled"], True)
        self.assertEqual(migrated["xr12_audience_ch2_enabled"], True)
        self.assertEqual(migrated["xr12_audience_ch3_enabled"], False)
        self.assertEqual(migrated["xr12_audience_ch4_enabled"], False)
        self.assertEqual(migrated["xr12_audience_open_value"], 100)
        self.assertEqual(migrated["xr12_audience_closed_value"], 10)
        self.assertEqual(migrated["xr12_audience_fade_duration_sec"], 2.5)

    def test_shared_open_value_applies_to_all_channel_states(self):
        """Shared high/open value targets all selected channels."""
        controller = MirroredXr12AudienceController(open_value=88)
        for state in controller._ch_states:
            self.assertEqual(state.open_value, 88)

    def test_fade_up_sends_only_0xb0_fader_messages(self):
        """Fade up (open) produces only 0xB0 fader CC messages, never 0xB1 mute CC."""
        state = Xr12AudienceState(open_value=96, closed_value=0, channel=0)
        state.current_value = 0
        command = state.request_open()
        all_msgs = list(command.initial_messages)
        # Simulate fade steps
        for step in (0.25, 0.5, 0.75, 1.0):
            v = interpolate_midi_value(command.start_value, command.target_value, step)
            all_msgs.extend(state.apply_fader_value(v))
        for msg in all_msgs:
            self.assertEqual(msg[0], XR12_FADER_STATUS,
                             f"Expected 0xB0 fader CC only, got status 0x{msg[0]:02X}")
        self.assertEqual(state.current_value, 96)

    def test_fade_down_sends_only_0xb0_fader_messages(self):
        """Fade down (close) produces only 0xB0 fader CC messages, never 0xB1 mute CC."""
        state = Xr12AudienceState(open_value=96, closed_value=0, channel=1)
        state.current_value = 96
        state.muted = False
        command = state.request_close()
        all_msgs = list(command.initial_messages)
        for step in (0.25, 0.5, 0.75, 1.0):
            v = interpolate_midi_value(command.start_value, command.target_value, step)
            all_msgs.extend(state.apply_fader_value(v))
        all_msgs.extend(state.finish_close())
        for msg in all_msgs:
            self.assertEqual(msg[0], XR12_FADER_STATUS,
                             f"Expected 0xB0 fader CC only, got status 0x{msg[0]:02X}")
        self.assertEqual(state.current_value, 0)

    def test_interrupted_fade_reversal_continues_from_current_value(self):
        """Interrupted fade reversal is smooth from each channel's current position."""
        state = Xr12AudienceState(open_value=96, closed_value=0, channel=0)
        state.current_value = 0
        # Start fading up, interrupted mid-way
        open_cmd = state.request_open()
        mid_value = interpolate_midi_value(open_cmd.start_value, open_cmd.target_value, 0.5)
        state.apply_fader_value(mid_value)
        self.assertEqual(state.current_value, mid_value)
        # Now fade down - must start from mid_value, not from open_value
        close_cmd = state.request_close()
        self.assertEqual(close_cmd.start_value, mid_value)
        self.assertEqual(close_cmd.target_value, 0)


if __name__ == "__main__":
    unittest.main()
