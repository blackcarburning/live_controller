"""Tests for BPM-aware beat-to-seconds conversion logic.

The conversion rule is:

    duration_seconds = round(beats * 60 / bpm * 1000) / 1000

This mirrors the ``beatsToSeconds`` JavaScript helper in show-sync-editor.html
so that Python scripts (e.g. live_controller) that construct show JSON files
can generate beat-aligned durations with identical precision.
"""
import math


def beats_to_seconds(beats: float, bpm: float) -> float:
    """Convert beats to seconds at the given BPM, rounded to the nearest ms.

    Matches the JS helper:
        Math.round(beats * 60 / bpm * 1000) / 1000
    """
    if bpm <= 0:
        raise ValueError(f"BPM must be positive, got {bpm}")
    return round(beats * 60 / bpm * 1000) / 1000


# ── Basic correctness ──────────────────────────────────────────────────────────

def test_one_beat_at_120_bpm():
    """1 beat at 120 BPM = 0.5 s."""
    assert beats_to_seconds(1, 120) == 0.5


def test_two_beats_at_120_bpm():
    """2 beats at 120 BPM = 1.0 s."""
    assert beats_to_seconds(2, 120) == 1.0


def test_four_beats_at_120_bpm():
    """4 beats (whole note) at 120 BPM = 2.0 s."""
    assert beats_to_seconds(4, 120) == 2.0


def test_half_beat_at_120_bpm():
    """0.5 beat at 120 BPM = 0.25 s."""
    assert beats_to_seconds(0.5, 120) == 0.25


def test_quarter_beat_at_120_bpm():
    """0.25 beat (sixteenth note) at 120 BPM = 0.125 s."""
    assert beats_to_seconds(0.25, 120) == 0.125


def test_one_beat_at_60_bpm():
    """1 beat at 60 BPM = 1.0 s (60 BPM is 1 beat/s)."""
    assert beats_to_seconds(1, 60) == 1.0


def test_one_beat_at_240_bpm():
    """1 beat at 240 BPM = 0.25 s."""
    assert beats_to_seconds(1, 240) == 0.25


def test_one_beat_at_128_bpm():
    """1 beat at 128 BPM ≈ 0.469 s (typical electronic dance music tempo)."""
    result = beats_to_seconds(1, 128)
    assert result == round(60 / 128 * 1000) / 1000  # 0.469 s


def test_one_beat_at_100_bpm():
    """1 beat at 100 BPM = 0.6 s."""
    assert beats_to_seconds(1, 100) == 0.6


def test_fractional_result_rounded_to_ms():
    """Results are rounded to the nearest millisecond (3 decimal places)."""
    result = beats_to_seconds(1, 90)  # 60/90 = 0.6̄  → should round to 0.667
    assert result == round(60 / 90 * 1000) / 1000
    assert len(str(result).rstrip('0').split('.')[-1]) <= 3


# ── Beat divisions table at common BPMs ───────────────────────────────────────

def test_beat_table_120_bpm():
    """Verify the standard beat-duration table at 120 BPM."""
    bpm = 120
    expected = {
        0.25: 0.125,   # sixteenth note
        0.5:  0.250,   # eighth note
        1:    0.500,   # quarter note
        2:    1.000,   # half note
        4:    2.000,   # whole note
    }
    for beats, secs in expected.items():
        assert beats_to_seconds(beats, bpm) == secs, (
            f"beats={beats} at {bpm} BPM: expected {secs}s, "
            f"got {beats_to_seconds(beats, bpm)}s"
        )


def test_beat_table_128_bpm():
    """Verify that beat durations at 128 BPM are rounded deterministically."""
    bpm = 128
    for beats in (0.25, 0.5, 1, 2, 4):
        result = beats_to_seconds(beats, bpm)
        # Result must be a whole number of milliseconds
        assert math.isclose(result * 1000, round(result * 1000), abs_tol=1e-9), (
            f"beats={beats} at {bpm} BPM gave non-integer ms: {result * 1000}"
        )


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_zero_beats_returns_zero():
    """0 beats → 0 seconds regardless of BPM."""
    assert beats_to_seconds(0, 120) == 0.0


def test_large_beat_count():
    """Many beats (e.g. 32) return the expected large duration."""
    assert beats_to_seconds(32, 120) == 16.0


def test_very_high_bpm():
    """Very high BPM (300) still produces positive, ms-rounded results."""
    result = beats_to_seconds(1, 300)
    assert result > 0
    assert math.isclose(result * 1000, round(result * 1000), abs_tol=1e-9)


def test_very_low_bpm():
    """Very low BPM (20) produces large, ms-rounded durations."""
    result = beats_to_seconds(1, 20)
    assert result == 3.0   # 60/20 = 3.0 s


def test_invalid_zero_bpm_raises():
    """BPM of 0 is invalid and must raise ValueError."""
    try:
        beats_to_seconds(1, 0)
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_invalid_negative_bpm_raises():
    """Negative BPM is invalid and must raise ValueError."""
    try:
        beats_to_seconds(1, -120)
        assert False, "Expected ValueError"
    except ValueError:
        pass
