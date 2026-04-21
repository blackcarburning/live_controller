"""Tests for device viewport preset definitions and orientation-toggle logic.

Mirrors the ``DEVICE_PRESETS`` constant and ``currentDeviceDims()`` function in
show-sync-editor.html so that any future tooling that generates or validates
show files for specific device targets can rely on the same data.
"""

# ── Preset table (mirrors DEVICE_PRESETS in show-sync-editor.html) ─────────────

DEVICE_PRESETS = [
    {'id': 'iphone-se',      'name': 'iPhone SE  375×667',              'w': 375, 'h': 667},
    {'id': 'iphone-14',      'name': 'iPhone 14  390×844',              'w': 390, 'h': 844},
    {'id': 'iphone-14-plus', 'name': 'iPhone 14 Plus  428×926',         'w': 428, 'h': 926},
    {'id': 'iphone-14-pm',   'name': 'iPhone 14 Pro Max  430×932',      'w': 430, 'h': 932},
    {'id': 'iphone-15-pro',  'name': 'iPhone 15 Pro  393×852',          'w': 393, 'h': 852},
    {'id': 'iphone-16-pm',   'name': 'iPhone 16 Pro Max  440×956',      'w': 440, 'h': 956},
    {'id': 'android-sm',     'name': 'Android S  360×800',              'w': 360, 'h': 800},
    {'id': 'android-px7',    'name': 'Android M – Pixel 7  412×915',    'w': 412, 'h': 915},
    {'id': 'android-s22u',   'name': 'Android L – S22 Ultra  384×854',  'w': 384, 'h': 854},
]

DEFAULT_PRESET_IDX = 1  # iPhone 14


def current_device_dims(preset: dict, landscape: bool) -> tuple:
    """Return (width, height) respecting orientation.

    Mirrors ``currentDeviceDims()`` in show-sync-editor.html.
    Portrait  → (w, h)
    Landscape → (h, w)  (axes swapped)
    """
    if landscape:
        return preset['h'], preset['w']
    return preset['w'], preset['h']


# ── Preset list structure ─────────────────────────────────────────────────────

def test_preset_count():
    """There must be at least 6 presets (several iPhone + Android sizes)."""
    assert len(DEVICE_PRESETS) >= 6


def test_all_presets_have_required_keys():
    for p in DEVICE_PRESETS:
        assert 'id'   in p, f"Preset missing 'id': {p}"
        assert 'name' in p, f"Preset missing 'name': {p}"
        assert 'w'    in p, f"Preset missing 'w': {p}"
        assert 'h'    in p, f"Preset missing 'h': {p}"


def test_all_preset_ids_are_unique():
    ids = [p['id'] for p in DEVICE_PRESETS]
    assert len(ids) == len(set(ids)), "Duplicate preset IDs found"


def test_all_presets_have_positive_dimensions():
    for p in DEVICE_PRESETS:
        assert p['w'] > 0, f"{p['id']} has non-positive width"
        assert p['h'] > 0, f"{p['id']} has non-positive height"


def test_all_portrait_presets_are_taller_than_wide():
    """Portrait phones are taller than they are wide (h > w)."""
    for p in DEVICE_PRESETS:
        assert p['h'] > p['w'], (
            f"{p['id']} portrait dims should have h > w, got {p['w']}×{p['h']}"
        )


# ── Default preset ────────────────────────────────────────────────────────────

def test_default_preset_is_iphone_14():
    default = DEVICE_PRESETS[DEFAULT_PRESET_IDX]
    assert default['id'] == 'iphone-14'
    assert default['w'] == 390
    assert default['h'] == 844


# ── iPhone presets ────────────────────────────────────────────────────────────

def test_iphone_se_dims():
    p = next(x for x in DEVICE_PRESETS if x['id'] == 'iphone-se')
    assert p['w'] == 375
    assert p['h'] == 667


def test_iphone_14_dims():
    p = next(x for x in DEVICE_PRESETS if x['id'] == 'iphone-14')
    assert p['w'] == 390
    assert p['h'] == 844


def test_at_least_three_iphone_presets():
    iphone_presets = [p for p in DEVICE_PRESETS if p['id'].startswith('iphone')]
    assert len(iphone_presets) >= 3


# ── Android presets ───────────────────────────────────────────────────────────

def test_at_least_two_android_presets():
    android_presets = [p for p in DEVICE_PRESETS if p['id'].startswith('android')]
    assert len(android_presets) >= 2


def test_pixel7_dims():
    p = next(x for x in DEVICE_PRESETS if x['id'] == 'android-px7')
    assert p['w'] == 412
    assert p['h'] == 915


# ── Orientation toggle ────────────────────────────────────────────────────────

def test_portrait_returns_w_h():
    p = DEVICE_PRESETS[DEFAULT_PRESET_IDX]  # iPhone 14: 390×844
    w, h = current_device_dims(p, landscape=False)
    assert w == 390
    assert h == 844


def test_landscape_swaps_axes():
    p = DEVICE_PRESETS[DEFAULT_PRESET_IDX]  # iPhone 14: 390×844
    w, h = current_device_dims(p, landscape=True)
    assert w == 844   # was height
    assert h == 390   # was width


def test_landscape_is_wider_than_tall():
    for p in DEVICE_PRESETS:
        w, h = current_device_dims(p, landscape=True)
        assert w > h, (
            f"{p['id']} landscape should have w > h, got {w}×{h}"
        )


def test_double_orientation_toggle_returns_original():
    """Toggling orientation twice returns the original portrait dimensions."""
    for p in DEVICE_PRESETS:
        w1, h1 = current_device_dims(p, landscape=False)
        w2, h2 = current_device_dims(p, landscape=True)
        w3, h3 = current_device_dims(p, landscape=False)
        assert (w1, h1) == (w3, h3), f"{p['id']} double-toggle mismatch"


# ── Scale-to-fit calculation ──────────────────────────────────────────────────

def compute_preview_scale(device_w: int, device_h: int, outer_w: int, outer_h: int) -> float:
    """Return the CSS scale factor to fit the device inside the outer panel.

    Mirrors the scale calculation in ``updatePreviewSize()`` in show-sync-editor.html.
    The scale is capped at 1 so the preview is never magnified beyond 1:1.
    """
    return min(outer_w / device_w, outer_h / device_h, 1.0)


def test_scale_fits_within_outer():
    outer_w, outer_h = 163, 220
    for p in DEVICE_PRESETS:
        dw, dh = current_device_dims(p, landscape=False)
        scale = compute_preview_scale(dw, dh, outer_w, outer_h)
        assert dw * scale <= outer_w + 0.5, f"{p['id']} scaled width exceeds outer"
        assert dh * scale <= outer_h + 0.5, f"{p['id']} scaled height exceeds outer"


def test_scale_never_exceeds_one():
    """Preview is never magnified (scale ≤ 1.0)."""
    outer_w, outer_h = 163, 220
    for p in DEVICE_PRESETS:
        dw, dh = current_device_dims(p, landscape=False)
        scale = compute_preview_scale(dw, dh, outer_w, outer_h)
        assert scale <= 1.0, f"{p['id']} scale {scale} > 1"
