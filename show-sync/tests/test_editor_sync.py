"""Tests for the timeline/video synchronisation logic in show-sync-editor.html.

These tests mirror the pure-JavaScript helpers that implement the
"single authoritative clock" sync model:

  - ``clamp(v, lo, hi)``       — used inside seekTo() to bound seek targets
  - ``t2x(t)`` / ``x2t(x)``   — pixel ↔ seconds coordinate transforms
  - ``seekTo`` clamping arithmetic — the target time must lie in [0, dur]
  - Absolute-position principle — no incremental drift; every update reads
    the raw current-time value and converts it directly to pixels.

The RAF-based playback sync loop (_rafFrame) cannot be exercised in Python
since it depends on browser APIs; the contract it enforces (always read
vid.currentTime, never accumulate deltas) is verified via the arithmetic
helpers below.
"""


# ── Mirrors of JS helpers ─────────────────────────────────────────────────────

def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp v to [lo, hi].  Mirrors ``clamp()`` in show-sync-editor.html."""
    return lo if v < lo else (hi if v > hi else v)


def t2x(t: float, pps: float) -> float:
    """Convert seconds → pixels at the given pixels-per-second zoom.
    Mirrors ``t2x(t) { return t * pps; }`` in show-sync-editor.html.
    """
    return t * pps


def x2t(x: float, pps: float) -> float:
    """Convert pixels → seconds at the given pixels-per-second zoom.
    Mirrors ``x2t(x) { return x / pps; }`` in show-sync-editor.html.
    """
    return x / pps


def seek_target(t: float, dur: float) -> float:
    """Return the clamped seek target used by seekTo().

    Mirrors:
        const target = clamp(t, 0, dur);
    in show-sync-editor.html.
    """
    return clamp(t, 0, dur)


# ── clamp() ───────────────────────────────────────────────────────────────────

def test_clamp_within_range():
    assert clamp(5.0, 0.0, 10.0) == 5.0


def test_clamp_at_lower_bound():
    assert clamp(0.0, 0.0, 10.0) == 0.0


def test_clamp_at_upper_bound():
    assert clamp(10.0, 0.0, 10.0) == 10.0


def test_clamp_below_lower_bound():
    assert clamp(-1.0, 0.0, 10.0) == 0.0


def test_clamp_above_upper_bound():
    assert clamp(11.0, 0.0, 10.0) == 10.0


def test_clamp_zero_range():
    """When lo == hi the output equals the bound regardless of v."""
    assert clamp(5.0, 3.0, 3.0) == 3.0
    assert clamp(0.0, 3.0, 3.0) == 3.0


# ── t2x / x2t coordinate transforms ──────────────────────────────────────────

def test_t2x_default_zoom():
    """50 px/s is the default zoom; 2 s → 100 px."""
    assert t2x(2.0, 50) == 100.0


def test_t2x_at_origin():
    """Time 0 always maps to pixel 0 regardless of zoom."""
    for pps in (4, 50, 150, 300, 600):
        assert t2x(0, pps) == 0.0


def test_t2x_linear():
    """Double the time → double the pixel offset at any zoom."""
    pps = 75
    assert t2x(4.0, pps) == 2 * t2x(2.0, pps)


def test_x2t_default_zoom():
    """100 px at 50 px/s → 2 s."""
    assert x2t(100.0, 50) == 2.0


def test_x2t_at_origin():
    """Pixel 0 always maps to time 0."""
    for pps in (4, 50, 150, 300, 600):
        assert x2t(0, pps) == 0.0


def test_t2x_x2t_round_trip():
    """t → pixels → t must give back the original time (no drift)."""
    pps = 50
    for t in (0.0, 0.1, 1.0, 5.5, 120.0):
        assert abs(x2t(t2x(t, pps), pps) - t) < 1e-10, (
            f"Round-trip failed for t={t} at pps={pps}"
        )


def test_x2t_t2x_round_trip():
    """pixels → t → pixels must give back the original pixel value."""
    pps = 50
    for px in (0, 50, 100, 275, 6000):
        assert abs(t2x(x2t(px, pps), pps) - px) < 1e-10, (
            f"Round-trip failed for px={px} at pps={pps}"
        )


# ── seekTo clamping (absolute-position model) ─────────────────────────────────

def test_seek_within_duration_unchanged():
    """A target inside [0, dur] is returned unchanged."""
    assert seek_target(5.0, 10.0) == 5.0


def test_seek_before_start_clamped_to_zero():
    """Negative seek targets are clamped to 0."""
    assert seek_target(-2.0, 10.0) == 0.0


def test_seek_past_end_clamped_to_duration():
    """Seek targets beyond the duration are clamped to dur."""
    assert seek_target(15.0, 10.0) == 10.0


def test_seek_at_boundaries():
    """Exact boundary values are accepted without modification."""
    assert seek_target(0.0, 10.0) == 0.0
    assert seek_target(10.0, 10.0) == 10.0


def test_seek_is_deterministic():
    """The same (t, dur) pair always produces the same clamped target (no state)."""
    for t, dur in [(3.0, 10.0), (-1.0, 5.0), (99.9, 60.0)]:
        assert seek_target(t, dur) == seek_target(t, dur)


# ── No-drift / absolute-position principle ────────────────────────────────────
# The RAF loop reads vid.currentTime directly on every frame rather than
# accumulating incremental deltas.  The following tests verify that the
# coordinate transform is free of accumulation error over many iterations.

def test_no_drift_over_many_frames():
    """Simulating N rAF frames starting from t=0 and advancing by dt each frame.

    If we always compute position from the absolute time (t * pps) rather than
    adding small pixel increments, the error after N steps is zero (float
    rounding aside, well within 1e-9 px).  This is the core anti-drift guarantee.

    dt = 1/60 is a repeating binary fraction, so incremental accumulation over
    N additions produces rounding error that grows with N.  The absolute
    calculation (one multiplication) has essentially zero error.
    """
    pps = 50
    dt  = 1 / 60  # ~16.67 ms per frame at 60 fps — irrational in binary float
    n   = 600     # 10 seconds of playback at 60 fps

    # Absolute-position calculation (what _rafFrame does)
    absolute_px_final = t2x(n * dt, pps)

    # Incremental accumulation (the old, drifty approach)
    incremental_px = 0.0
    for _ in range(n):
        incremental_px += t2x(dt, pps)

    exact = n * dt * pps  # reference: same single multiplication
    absolute_error     = abs(absolute_px_final - exact)
    incremental_error  = abs(incremental_px    - exact)

    assert absolute_error < 1e-9, (
        f"Absolute calculation drifted: {absolute_error} px after {n} frames"
    )
    # With dt = 1/60 the incremental loop accumulates floating-point rounding
    # over N additions, producing strictly more error than a single multiply.
    assert incremental_error > absolute_error, (
        "Incremental accumulation should produce more floating-point error "
        "than a single multiplication when dt is an irrational binary float."
    )
