"""Tests for link URL validation logic.

The validation rule mirrors ``validateLinkUrl()`` in show-sync-editor.html and
``_safeLinkUrl()`` in show-sync/app/static/client.js:

  - Allow http: and https: (full URL with host required; href re-serialized from
    URL object so raw user input never reaches the DOM directly).
  - Allow mailto: (no angle-brackets, double-quotes, backticks, or backslashes).
  - Allow tel: (digits, spaces, +, -, (, ) only).
  - Reject everything else, including ``javascript:``, ``data:``, ``vbscript:``,
    bare strings, and empty input.
  - Return '' for invalid/unsafe input; return the validated string for valid input.
"""
import re
from urllib.parse import urlparse


def validate_link_url(raw: str) -> str:
    """Validate a link URL for use in text clips.

    Mirrors the stricter version of ``validateLinkUrl()`` in show-sync-editor.html
    and ``_safeLinkUrl()`` in client.js.  Returns a safe string or ``''``.
    """
    if not raw:
        return ''
    trimmed = raw.strip()
    # mailto: — allow only printable non-whitespace chars, no HTML special chars
    if re.match(r'^mailto:', trimmed, re.IGNORECASE):
        if re.match(r'^mailto:[^\s<>"\'`\\]+$', trimmed, re.IGNORECASE):
            return trimmed
        return ''
    # tel: — allow only digits, spaces, +, -, (, )
    if re.match(r'^tel:', trimmed, re.IGNORECASE):
        if re.match(r'^tel:[+\d\s\-()]+$', trimmed, re.IGNORECASE):
            return trimmed
        return ''
    # http / https
    try:
        u = urlparse(trimmed)
        if u.scheme in ('http', 'https') and u.netloc:
            return trimmed
    except Exception:
        pass
    return ''


# ── Safe / allowed URLs ────────────────────────────────────────────────────────

def test_http_url_allowed():
    assert validate_link_url('http://example.com') == 'http://example.com'


def test_https_url_allowed():
    assert validate_link_url('https://example.com/path?q=1') == 'https://example.com/path?q=1'


def test_mailto_allowed():
    assert validate_link_url('mailto:user@example.com') == 'mailto:user@example.com'


def test_tel_allowed():
    assert validate_link_url('tel:+441234567890') == 'tel:+441234567890'


def test_https_with_port_allowed():
    assert validate_link_url('https://example.com:8443/secure') == 'https://example.com:8443/secure'


def test_whitespace_trimmed_https():
    url = '  https://example.com  '
    assert validate_link_url(url) == 'https://example.com'


# ── Unsafe / blocked URLs ─────────────────────────────────────────────────────

def test_javascript_blocked():
    assert validate_link_url('javascript:alert(1)') == ''


def test_javascript_mixed_case_blocked():
    assert validate_link_url('JavaScript:void(0)') == ''


def test_data_uri_blocked():
    assert validate_link_url('data:text/html,<h1>hi</h1>') == ''


def test_vbscript_blocked():
    assert validate_link_url('vbscript:msgbox(1)') == ''


def test_ftp_blocked():
    """ftp: is not in the allow-list."""
    assert validate_link_url('ftp://files.example.com/file.zip') == ''


def test_bare_string_blocked():
    assert validate_link_url('just some text') == ''


def test_empty_string_returns_empty():
    assert validate_link_url('') == ''


def test_whitespace_only_returns_empty():
    assert validate_link_url('   ') == ''


def test_http_without_host_blocked():
    """http: without a netloc (e.g. 'http:///path') should be blocked."""
    result = validate_link_url('http:///no-host')
    assert result == ''


def test_mailto_with_html_chars_blocked():
    """mailto: with HTML special characters should be rejected."""
    assert validate_link_url('mailto:<script>alert(1)</script>') == ''


def test_tel_with_letters_blocked():
    """tel: with non-digit non-allowed characters should be rejected."""
    assert validate_link_url('tel:javascript:alert(1)') == ''


# ── Serialisation round-trip ──────────────────────────────────────────────────

def test_safe_url_survives_json_round_trip():
    """A validated URL stored in clip params round-trips through JSON correctly."""
    import json
    url = 'https://example.com/show'
    clip = {'type': 'text', 'params': {'text': 'Click here', 'link_url': validate_link_url(url)}}
    serialised = json.dumps(clip)
    restored = json.loads(serialised)
    assert restored['params']['link_url'] == url


def test_unsafe_url_not_stored():
    """An invalid URL produces '' which should not be stored in clip params."""
    url = validate_link_url('javascript:evil()')
    assert url == ''
    # Simulate the editor behaviour: only set link_url when valid
    params = {}
    if url:
        params['link_url'] = url
    assert 'link_url' not in params
