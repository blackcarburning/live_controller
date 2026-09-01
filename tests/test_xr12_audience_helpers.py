import unittest

from xr12_audience import (
    DEFAULT_XR12_AUDIENCE_UNITY_VALUE,
    XR12_FADER_MIN,
    XR12_FADER_STATUS,
    XR12_MUTE_STATUS,
    Xr12AudienceState,
    build_audience_fader_messages,
    build_audience_mute_messages,
    interpolate_midi_value,
)


class Xr12AudienceHelperTests(unittest.TestCase):
    def test_build_audience_fader_messages_targets_channels_one_and_two(self):
        self.assertEqual(
            build_audience_fader_messages(DEFAULT_XR12_AUDIENCE_UNITY_VALUE),
            [
                [XR12_FADER_STATUS, 0, DEFAULT_XR12_AUDIENCE_UNITY_VALUE],
                [XR12_FADER_STATUS, 1, DEFAULT_XR12_AUDIENCE_UNITY_VALUE],
            ],
        )

    def test_build_audience_mute_messages_target_both_channels(self):
        self.assertEqual(
            build_audience_mute_messages(True),
            [
                [XR12_MUTE_STATUS, 0, 127],
                [XR12_MUTE_STATUS, 1, 127],
            ],
        )
        self.assertEqual(
            build_audience_mute_messages(False),
            [
                [XR12_MUTE_STATUS, 0, 0],
                [XR12_MUTE_STATUS, 1, 0],
            ],
        )

    def test_request_open_starts_from_minimum_then_targets_unity(self):
        state = Xr12AudienceState()
        command = state.request_open()
        self.assertEqual(command.start_value, XR12_FADER_MIN)
        self.assertEqual(command.target_value, DEFAULT_XR12_AUDIENCE_UNITY_VALUE)
        self.assertFalse(command.mute_after_fade)
        self.assertEqual(
            command.initial_messages,
            [
                [XR12_FADER_STATUS, 0, 0],
                [XR12_FADER_STATUS, 1, 0],
                [XR12_MUTE_STATUS, 0, 0],
                [XR12_MUTE_STATUS, 1, 0],
            ],
        )
        self.assertFalse(state.muted)

    def test_request_open_target_reaches_default_unity_96_not_zero(self):
        """Regression: fade-up must target 96 (default unity), not 0 or a small value."""
        state = Xr12AudienceState()
        command = state.request_open()
        self.assertEqual(command.target_value, 96)
        # Simulate the full fade completing at progress=1.0
        final = interpolate_midi_value(command.start_value, command.target_value, 1.0)
        self.assertEqual(final, 96)

    def test_request_open_is_idempotent_when_already_at_unity(self):
        """Regression: repeated request_open while already open at unity must be a no-op."""
        state = Xr12AudienceState()
        # Simulate first open: set muted=False, current_value=unity
        state.muted = False
        state.current_value = state.unity_value
        command = state.request_open()
        # No-op: start==target, no initial messages
        self.assertEqual(command.start_value, command.target_value)
        self.assertEqual(command.initial_messages, [])

    def test_interrupted_close_open_fades_from_current_position(self):
        """Regression: an interrupted close→open must fade from current value, not 0."""
        state = Xr12AudienceState()
        # Simulate fade-up has progressed to 60
        state.muted = False
        state.current_value = 60
        # Now a close is requested and interrupted at 40
        state.current_value = 40
        # request_open from here: should start at 40, not 0
        command = state.request_open()
        self.assertEqual(command.start_value, 40)
        self.assertEqual(command.target_value, DEFAULT_XR12_AUDIENCE_UNITY_VALUE)
        # No snap-to-min initial messages since we're not at 0
        self.assertEqual(command.initial_messages, [])

    def test_request_open_from_muted_state_sends_initial_messages(self):
        """When muted, request_open must snap fader to min and unmute before fading."""
        state = Xr12AudienceState()
        self.assertTrue(state.muted)
        command = state.request_open()
        self.assertNotEqual(command.initial_messages, [])
        self.assertFalse(state.muted)

    def test_request_close_uses_current_value_and_mutes_after_finish(self):
        state = Xr12AudienceState()
        state.current_value = 72
        command = state.request_close()
        self.assertEqual(command.start_value, 72)
        self.assertEqual(command.target_value, XR12_FADER_MIN)
        self.assertTrue(command.mute_after_fade)
        self.assertEqual(state.finish_close(), build_audience_mute_messages(True))
        self.assertTrue(state.muted)

    def test_interpolate_midi_value_clamps_progress(self):
        self.assertEqual(interpolate_midi_value(0, 96, 0.5), 48)
        self.assertEqual(interpolate_midi_value(0, 96, -1), 0)
        self.assertEqual(interpolate_midi_value(0, 96, 2), 96)

    def test_set_unity_value_clamped_to_midi_range(self):
        state = Xr12AudienceState()
        state.set_unity_value(200)
        self.assertEqual(state.unity_value, 127)
        state.set_unity_value(-5)
        self.assertEqual(state.unity_value, 0)
        state.set_unity_value(96)
        self.assertEqual(state.unity_value, 96)

    def test_default_unity_value_is_96(self):
        state = Xr12AudienceState()
        self.assertEqual(state.unity_value, DEFAULT_XR12_AUDIENCE_UNITY_VALUE)
        self.assertEqual(DEFAULT_XR12_AUDIENCE_UNITY_VALUE, 96)


if __name__ == "__main__":
    unittest.main()
