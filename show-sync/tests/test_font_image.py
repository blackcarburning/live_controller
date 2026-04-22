"""Tests for font-selection serialisation and image-URL validation.

These tests mirror the JavaScript helpers added in show-sync-editor.html:

  - ``validate_image_url()``  — mirrors ``validateImageUrl()`` in the editor.
  - Font preset id / CSS mapping — mirrors ``FONT_PRESETS`` and ``fontCss()``.
  - Clip serialisation round-trips for ``font_family`` and ``image`` clips.
"""
import json
import re
from urllib.parse import urlparse


# ── Image URL validation (mirrors validateImageUrl in show-sync-editor.html) ───

def validate_image_url(raw: str) -> str:
    """Validate an image URL.  Only http and https are permitted.

    Mirrors ``validateImageUrl()`` in show-sync-editor.html.
    Returns the stripped URL string on success, or '' on failure.
    """
    if not raw:
        return ''
    trimmed = raw.strip()
    try:
        u = urlparse(trimmed)
        if u.scheme in ('http', 'https') and u.netloc:
            return trimmed
    except Exception:
        pass
    return ''


# ── Safe image URLs ────────────────────────────────────────────────────────────

def test_http_image_allowed():
    assert validate_image_url('http://example.com/img.jpg') == 'http://example.com/img.jpg'


def test_https_image_allowed():
    assert validate_image_url('https://cdn.example.com/photo.webp') == 'https://cdn.example.com/photo.webp'


def test_https_with_query_allowed():
    url = 'https://example.com/image.jpg?w=800&h=600'
    assert validate_image_url(url) == url


def test_whitespace_trimmed_https():
    assert validate_image_url('  https://example.com/img.png  ') == 'https://example.com/img.png'


# ── Unsafe image URLs ─────────────────────────────────────────────────────────

def test_javascript_blocked():
    assert validate_image_url('javascript:alert(1)') == ''


def test_data_uri_blocked():
    assert validate_image_url('data:image/png;base64,abc123') == ''


def test_blob_blocked():
    assert validate_image_url('blob:http://localhost/some-uuid') == ''


def test_ftp_blocked():
    assert validate_image_url('ftp://example.com/img.jpg') == ''


def test_vbscript_blocked():
    assert validate_image_url('vbscript:msgbox(1)') == ''


def test_empty_string_returns_empty():
    assert validate_image_url('') == ''


def test_whitespace_only_returns_empty():
    assert validate_image_url('   ') == ''


def test_bare_path_blocked():
    assert validate_image_url('/images/photo.jpg') == ''


def test_http_without_host_blocked():
    assert validate_image_url('http:///no-host/img.jpg') == ''


# ── Font preset id / CSS mapping ───────────────────────────────────────────────
# Mirrors FONT_PRESETS and fontCss() in show-sync-editor.html.

FONT_PRESETS = [
    {'id': '',          'label': 'Default (system UI)',  'css': ''},
    {'id': 'sans',      'label': 'Sans-serif',
     'css': "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"},
    {'id': 'serif',     'label': 'Serif',
     'css': "Georgia, 'Times New Roman', Times, serif"},
    {'id': 'mono',      'label': 'Monospace',
     'css': "'Courier New', Courier, monospace"},
    {'id': 'impact',    'label': 'Impact',
     'css': "Impact, Haettenschweiner, 'Arial Narrow Bold', sans-serif"},
    {'id': 'georgia',   'label': 'Georgia',
     'css': "Georgia, Palatino, 'Palatino Linotype', serif"},
    {'id': 'verdana',   'label': 'Verdana',
     'css': "Verdana, Geneva, Tahoma, sans-serif"},
    {'id': 'trebuchet', 'label': 'Trebuchet MS',
     'css': "'Trebuchet MS', 'Lucida Sans Unicode', 'Lucida Grande', sans-serif"},
]


def font_css(font_id: str) -> str:
    """Return the CSS font-family string for a stored font id.
    Mirrors ``fontCss()`` in show-sync-editor.html.
    """
    preset = next((f for f in FONT_PRESETS if f['id'] == font_id), None)
    return preset['css'] if preset and preset['css'] else ''


def test_empty_font_id_returns_empty_string():
    """The empty font id ('') maps to '' so the browser default is inherited."""
    assert font_css('') == ''


def test_unknown_font_id_returns_empty_string():
    """An unrecognised id returns '' — safe fallback to browser default."""
    assert font_css('papyrus') == ''


def test_sans_preset_returns_css_stack():
    css = font_css('sans')
    assert 'Arial' in css
    assert 'sans-serif' in css


def test_serif_preset_returns_css_stack():
    css = font_css('serif')
    assert 'Georgia' in css
    assert 'serif' in css


def test_mono_preset_returns_css_stack():
    css = font_css('mono')
    assert 'Courier' in css
    assert 'monospace' in css


def test_impact_preset_returns_css_stack():
    css = font_css('impact')
    assert 'Impact' in css


def test_verdana_preset_returns_css_stack():
    css = font_css('verdana')
    assert 'Verdana' in css


def test_trebuchet_preset_returns_css_stack():
    css = font_css('trebuchet')
    assert 'Trebuchet' in css


def test_all_preset_ids_are_unique():
    ids = [f['id'] for f in FONT_PRESETS]
    assert len(ids) == len(set(ids)), 'Duplicate font preset ids found'


def test_all_named_presets_have_css():
    """Every preset with a non-empty id must have a non-empty css value."""
    for fp in FONT_PRESETS:
        if fp['id']:
            assert fp['css'], f"Preset '{fp['id']}' has an empty css stack"


# ── Clip serialisation round-trips ─────────────────────────────────────────────

def test_font_family_survives_json_round_trip():
    """font_family stored in a text clip round-trips through JSON without loss."""
    clip = {
        'id': 'abc1',
        'type': 'text',
        'start': 2.0,
        'duration': 3.0,
        'params': {'color': '#ffffff', 'text': 'Hello', 'size': 5, 'font_family': 'sans'},
    }
    serialised = json.dumps(clip)
    restored = json.loads(serialised)
    assert restored['params']['font_family'] == 'sans'


def test_missing_font_family_defaults_gracefully():
    """Clips without font_family (older files) load without error; default is ''."""
    clip = {
        'id': 'abc2',
        'type': 'text',
        'start': 0.0,
        'duration': 1.0,
        'params': {'color': '#ffffff', 'text': 'Hi', 'size': 5},
    }
    # Simulate the JS fallback: params.font_family || ''
    font_id = clip['params'].get('font_family', '')
    assert font_id == ''
    assert font_css(font_id) == ''


def test_image_clip_survives_json_round_trip():
    """Image clip params (src, fit) round-trip through JSON without loss."""
    url = 'https://example.com/banner.jpg'
    clip = {
        'id': 'img1',
        'type': 'image',
        'start': 1.0,
        'duration': 5.0,
        'params': {'src': url, 'fit': 'cover'},
        'fade_in': 0.5,
        'fade_out': 0.5,
    }
    serialised = json.dumps(clip)
    restored = json.loads(serialised)
    assert restored['type'] == 'image'
    assert restored['params']['src'] == url
    assert restored['params']['fit'] == 'cover'


def test_image_clip_unsafe_src_not_stored():
    """A javascript: src is rejected by validate_image_url — nothing stored."""
    src = validate_image_url('javascript:evil()')
    assert src == ''
    params = {}
    if src:
        params['src'] = src
    assert 'src' not in params


def test_image_clip_missing_src_defaults_gracefully():
    """An image clip with no src renders nothing (empty string is falsy)."""
    clip = {
        'id': 'img2',
        'type': 'image',
        'start': 0.0,
        'duration': 2.0,
        'params': {'fit': 'contain'},
    }
    src = validate_image_url(clip['params'].get('src', ''))
    assert src == ''


def test_show_with_image_and_font_clips_round_trips():
    """A complete show containing both an image clip and a text+font clip
    serialises to JSON and deserialises back without loss of the new fields."""
    show = {
        'version': 2,
        'bpm': 120,
        'media': {'type': 'video', 'src': 'show.mov', 'duration': 60.0},
        'tracks': [
            {'id': 't1', 'name': 'Solids', 'layer': 1, 'clips': []},
            {
                'id': 't2', 'name': 'Text', 'layer': 10, 'clips': [
                    {
                        'id': 'c1', 'type': 'text', 'start': 5.0, 'duration': 3.0,
                        'params': {'color': '#fff', 'text': 'HELLO', 'size': 8,
                                   'font_family': 'impact'},
                        'fade_in': 0, 'fade_out': 0,
                    },
                    {
                        'id': 'c2', 'type': 'image', 'start': 10.0, 'duration': 5.0,
                        'params': {'src': 'https://example.com/logo.png', 'fit': 'contain'},
                        'fade_in': 0.5, 'fade_out': 0.5,
                    },
                ],
            },
        ],
        'markers': [],
    }
    serialised = json.dumps(show, indent=2)
    restored = json.loads(serialised)

    text_clip = restored['tracks'][1]['clips'][0]
    img_clip  = restored['tracks'][1]['clips'][1]

    assert text_clip['params']['font_family'] == 'impact'
    assert img_clip['params']['src'] == 'https://example.com/logo.png'
    assert img_clip['params']['fit'] == 'contain'
    assert img_clip['fade_in'] == 0.5
