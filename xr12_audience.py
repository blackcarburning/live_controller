from dataclasses import dataclass

XR12_AUDIENCE_PORT_INDEX = 3
XR12_AUDIENCE_CHANNELS = (0, 1)
XR12_FADER_STATUS = 0xB0
XR12_MUTE_STATUS = 0xB1
XR12_FADER_MIN = 0
XR12_MUTED_VALUE = 127
XR12_UNMUTED_VALUE = 0

DEFAULT_XR12_AUDIENCE_ENABLED = True
DEFAULT_XR12_AUDIENCE_FADE_SECONDS = 3.0
DEFAULT_XR12_AUDIENCE_UNITY_VALUE = 96


def clamp_midi_value(value):
    """Clamp an arbitrary value into the valid 7-bit MIDI data range."""
    return max(0, min(127, int(round(value))))


def build_audience_fader_messages(value):
    """Build XR12 fader CC messages for linked audience inputs 1-2."""
    midi_value = clamp_midi_value(value)
    return [[XR12_FADER_STATUS, channel, midi_value] for channel in XR12_AUDIENCE_CHANNELS]


def build_audience_mute_messages(muted):
    """Build XR12 mute CC messages for linked audience inputs 1-2."""
    mute_value = XR12_MUTED_VALUE if muted else XR12_UNMUTED_VALUE
    return [[XR12_MUTE_STATUS, channel, mute_value] for channel in XR12_AUDIENCE_CHANNELS]


def interpolate_midi_value(start_value, target_value, progress):
    """Linearly interpolate a MIDI value for the supplied 0-1 progress fraction."""
    bounded_progress = max(0.0, min(1.0, float(progress)))
    return clamp_midi_value(start_value + ((target_value - start_value) * bounded_progress))


@dataclass
class FadeCommand:
    initial_messages: list
    start_value: int
    target_value: int
    mute_after_fade: bool


class Xr12AudienceState:
    """Pure XR12 audience state machine used by the Qt controller and tests."""

    def __init__(self, unity_value=DEFAULT_XR12_AUDIENCE_UNITY_VALUE):
        self.unity_value = clamp_midi_value(unity_value)
        self.current_value = XR12_FADER_MIN
        self.muted = True

    def set_unity_value(self, unity_value):
        self.unity_value = clamp_midi_value(unity_value)

    def request_open(self):
        self.current_value = XR12_FADER_MIN
        self.muted = False
        return FadeCommand(
            initial_messages=build_audience_fader_messages(XR12_FADER_MIN) + build_audience_mute_messages(False),
            start_value=XR12_FADER_MIN,
            target_value=self.unity_value,
            mute_after_fade=False,
        )

    def request_close(self):
        return FadeCommand(
            initial_messages=[],
            start_value=clamp_midi_value(self.current_value),
            target_value=XR12_FADER_MIN,
            mute_after_fade=True,
        )

    def apply_fader_value(self, value):
        self.current_value = clamp_midi_value(value)
        return build_audience_fader_messages(self.current_value)

    def finish_close(self):
        self.current_value = XR12_FADER_MIN
        self.muted = True
        return build_audience_mute_messages(True)
