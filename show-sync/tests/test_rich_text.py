"""Tests for rich-text span serialisation, backward compatibility, and rendering logic.

These tests mirror the rich-text data model and helper functions added in
show-sync-editor.html (``buildRichTextDOM``, ``extractRichSpans``) and
show-sync/app/static/client.js (``_buildRichTextDOM``), verifying that:

  - ``rich_spans`` round-trips through JSON without loss.
  - Clips without ``rich_spans`` continue to work (backward compatibility).
  - Mixed bold/italic/underline/strikethrough spans are stored correctly.
  - Plain text is always reflected in ``params.text`` for legacy consumers.
  - Edge cases (empty spans list, all-plain spans, None value) are handled.
"""
import json


# ── Helpers that mirror the JavaScript logic ──────────────────────────────────

def build_plain_text(params: dict) -> str:
    """Return the plain-text representation of a text clip's params.

    Mirrors the rendering fallback: if ``rich_spans`` is absent or empty,
    return ``params['text']``; otherwise concatenate all span texts.
    """
    spans = params.get('rich_spans')
    if not spans:
        return params.get('text', '')
    return ''.join(s['text'] for s in spans)


def spans_have_formatting(spans: list) -> bool:
    """Return True if any span carries non-default formatting.

    Mirrors the ``hasFormatting`` check in the editor's ``syncEditorToParams``.
    """
    return any(
        s.get('bold') or s.get('italic') or s.get('underline') or s.get('strikethrough')
        for s in spans
    )


# ── Backward compatibility: plain-text clips ──────────────────────────────────

def test_plain_text_clip_no_rich_spans():
    """An existing plain-text clip has no rich_spans; params.text is used."""
    clip = {
        'id': 'abc1', 'type': 'text', 'start': 1.0, 'duration': 2.0,
        'params': {'color': '#ffffff', 'text': 'Hello World', 'size': 5},
    }
    assert clip['params'].get('rich_spans') is None
    assert build_plain_text(clip['params']) == 'Hello World'


def test_plain_text_clip_round_trips_json():
    """Plain-text clip survives JSON serialisation without gaining rich_spans."""
    clip = {
        'id': 'abc2', 'type': 'text', 'start': 0.0, 'duration': 3.0,
        'params': {'color': '#ff0000', 'text': 'LIVE NOW', 'size': 8, 'align': 'center'},
    }
    restored = json.loads(json.dumps(clip))
    assert restored['params']['text'] == 'LIVE NOW'
    assert 'rich_spans' not in restored['params']


def test_empty_text_defaults_gracefully():
    """A clip with empty text and no rich_spans renders as empty string."""
    params = {'color': '#fff', 'text': '', 'size': 5}
    assert build_plain_text(params) == ''


# ── Rich-span data model ──────────────────────────────────────────────────────

def test_bold_span_round_trips():
    """A bold span survives JSON round-trip with correct flag values."""
    clip = {
        'id': 'r1', 'type': 'text', 'start': 0.0, 'duration': 2.0,
        'params': {
            'color': '#ffffff', 'size': 5, 'align': 'center',
            'text': 'Hello',
            'rich_spans': [
                {'text': 'Hello', 'bold': True, 'italic': False,
                 'underline': False, 'strikethrough': False},
            ],
        },
    }
    restored = json.loads(json.dumps(clip))
    span = restored['params']['rich_spans'][0]
    assert span['text'] == 'Hello'
    assert span['bold'] is True
    assert span['italic'] is False
    assert span['underline'] is False
    assert span['strikethrough'] is False


def test_mixed_format_spans_round_trip():
    """Multiple spans with different formatting survive JSON round-trip."""
    spans = [
        {'text': 'Bold ',      'bold': True,  'italic': False, 'underline': False, 'strikethrough': False},
        {'text': 'italic ',    'bold': False, 'italic': True,  'underline': False, 'strikethrough': False},
        {'text': 'underlined', 'bold': False, 'italic': False, 'underline': True,  'strikethrough': False},
        {'text': ' normal',    'bold': False, 'italic': False, 'underline': False, 'strikethrough': False},
    ]
    params = {'color': '#fff', 'text': 'Bold italic underlined normal', 'size': 5, 'rich_spans': spans}
    restored = json.loads(json.dumps({'params': params}))['params']

    assert len(restored['rich_spans']) == 4
    assert restored['rich_spans'][0]['bold']      is True
    assert restored['rich_spans'][1]['italic']    is True
    assert restored['rich_spans'][2]['underline'] is True
    assert restored['rich_spans'][3]['bold']      is False
    assert restored['rich_spans'][3]['italic']    is False


def test_strikethrough_span_round_trips():
    """A strikethrough span survives JSON round-trip."""
    params = {
        'color': '#fff', 'text': 'old price', 'size': 5,
        'rich_spans': [
            {'text': 'old price', 'bold': False, 'italic': False,
             'underline': False, 'strikethrough': True},
        ],
    }
    restored = json.loads(json.dumps({'params': params}))['params']
    assert restored['rich_spans'][0]['strikethrough'] is True


def test_plain_text_always_kept_in_sync():
    """params.text is the plain-text join of all span texts."""
    spans = [
        {'text': 'Hello ', 'bold': True,  'italic': False, 'underline': False, 'strikethrough': False},
        {'text': 'World',  'bold': False, 'italic': True,  'underline': False, 'strikethrough': False},
    ]
    params = {
        'color': '#fff', 'size': 5,
        'text': ''.join(s['text'] for s in spans),  # editor keeps this in sync
        'rich_spans': spans,
    }
    assert build_plain_text(params) == 'Hello World'
    assert params['text'] == 'Hello World'


def test_multiline_text_via_newline_span():
    """A newline span ({'text': '\\n'}) produces a line break."""
    spans = [
        {'text': 'Line 1', 'bold': True,  'italic': False, 'underline': False, 'strikethrough': False},
        {'text': '\n',     'bold': False, 'italic': False, 'underline': False, 'strikethrough': False},
        {'text': 'Line 2', 'bold': False, 'italic': True,  'underline': False, 'strikethrough': False},
    ]
    params = {'color': '#fff', 'size': 5, 'text': 'Line 1\nLine 2', 'rich_spans': spans}
    assert build_plain_text(params) == 'Line 1\nLine 2'


# ── has_formatting detection ──────────────────────────────────────────────────

def test_all_plain_spans_no_formatting():
    """Spans that are all default-style have no formatting."""
    spans = [
        {'text': 'Hello', 'bold': False, 'italic': False, 'underline': False, 'strikethrough': False},
        {'text': ' World', 'bold': False, 'italic': False, 'underline': False, 'strikethrough': False},
    ]
    assert not spans_have_formatting(spans)


def test_one_bold_span_has_formatting():
    spans = [
        {'text': 'Hi ',   'bold': True,  'italic': False, 'underline': False, 'strikethrough': False},
        {'text': 'there', 'bold': False, 'italic': False, 'underline': False, 'strikethrough': False},
    ]
    assert spans_have_formatting(spans)


def test_empty_spans_list_no_formatting():
    assert not spans_have_formatting([])


# ── rich_spans absent / null handling ────────────────────────────────────────

def test_null_rich_spans_falls_back_to_text():
    """rich_spans: null is treated the same as absent."""
    params = {'color': '#fff', 'text': 'Fallback', 'size': 5, 'rich_spans': None}
    assert build_plain_text(params) == 'Fallback'


def test_empty_rich_spans_falls_back_to_text():
    """rich_spans: [] is treated the same as absent."""
    params = {'color': '#fff', 'text': 'Fallback', 'size': 5, 'rich_spans': []}
    assert build_plain_text(params) == 'Fallback'


# ── Full show round-trip ──────────────────────────────────────────────────────

def test_show_with_rich_text_clip_round_trips():
    """A complete show JSON containing a rich-text clip serialises and restores correctly."""
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
                        'params': {
                            'color': '#fff', 'size': 8, 'align': 'center',
                            'text': 'BOLD italic',
                            'rich_spans': [
                                {'text': 'BOLD ',  'bold': True,  'italic': False,
                                 'underline': False, 'strikethrough': False},
                                {'text': 'italic', 'bold': False, 'italic': True,
                                 'underline': False, 'strikethrough': False},
                            ],
                        },
                        'fade_in': 0.2, 'fade_out': 0.2,
                    },
                ],
            },
        ],
        'markers': [],
    }
    serialised = json.dumps(show, indent=2)
    restored   = json.loads(serialised)

    clip   = restored['tracks'][1]['clips'][0]
    spans  = clip['params']['rich_spans']
    assert len(spans) == 2
    assert spans[0]['bold']   is True
    assert spans[1]['italic'] is True
    assert clip['params']['text'] == 'BOLD italic'
    assert clip['fade_in'] == 0.2


def test_show_with_plain_and_rich_clips_coexist():
    """A show may have some text clips with rich_spans and some without."""
    show = {
        'version': 2, 'bpm': 120,
        'media': {'type': 'video', 'src': '', 'duration': 30.0},
        'tracks': [{
            'id': 't1', 'name': 'Text', 'layer': 10, 'clips': [
                {
                    'id': 'plain', 'type': 'text', 'start': 0.0, 'duration': 2.0,
                    'params': {'color': '#fff', 'text': 'Plain', 'size': 5},
                    'fade_in': 0, 'fade_out': 0,
                },
                {
                    'id': 'rich', 'type': 'text', 'start': 3.0, 'duration': 2.0,
                    'params': {
                        'color': '#fff', 'text': 'Rich',  'size': 5,
                        'rich_spans': [
                            {'text': 'Rich', 'bold': True, 'italic': False,
                             'underline': False, 'strikethrough': False},
                        ],
                    },
                    'fade_in': 0, 'fade_out': 0,
                },
            ],
        }],
        'markers': [],
    }
    restored = json.loads(json.dumps(show))
    clips = restored['tracks'][0]['clips']

    assert clips[0]['params'].get('rich_spans') is None
    assert clips[1]['params']['rich_spans'][0]['bold'] is True
