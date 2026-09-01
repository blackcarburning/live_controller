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


if __name__ == "__main__":
    unittest.main()
