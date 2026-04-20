"""Tests for play_show_by_name timing — specifically that the legacy offset=5
is never applied in the absolute-time scheduling path.

Key invariant: when a caller supplies ``start_at``, ``server_show_start_time``
must equal ``start_at`` exactly, regardless of the value of ``offset``.
"""
import json
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

# Import the FastAPI app from the show-sync server.
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from app.main import app, sessions, SHOWS_DIR


# ── Helpers ───────────────────────────────────────────────────────────────────

MINIMAL_SHOW = {
    "tracks": [
        {
            "layer": 0,
            "clips": [
                {"start": 0.0, "duration": 10.0, "type": "color", "params": {"color": "#ff0000"}},
            ],
        }
    ]
}


def _create_session(client: TestClient) -> str:
    """Create a test session and return its ID."""
    resp = client.post("/api/session", json={"name": "test"})
    assert resp.status_code == 200
    return resp.json()["session_id"]


def _write_show_file(name: str) -> None:
    """Write a minimal show JSON file to the shows directory."""
    SHOWS_DIR.mkdir(parents=True, exist_ok=True)
    (SHOWS_DIR / name).write_text(json.dumps(MINIMAL_SHOW), encoding="utf-8")


def _cleanup_show_file(name: str) -> None:
    p = SHOWS_DIR / name
    if p.exists():
        p.unlink()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_absolute_time_no_offset_applied():
    """When start_at is provided, server_show_start_time must equal start_at exactly.

    This guards against the legacy offset=5 being added on top of start_at,
    which was the root cause of the 5-second sync-show delay.
    """
    show_name = "test_timing_abs.json"
    _write_show_file(show_name)
    try:
        with TestClient(app) as client:
            session_id = _create_session(client)
            target_start = time.time() + 10.0  # 10 s in the future

            resp = client.post(
                f"/api/session/{session_id}/play-show-by-name",
                params={"name": show_name, "start_at": f"{target_start:.6f}"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["scheduling"] == "absolute"
            # server_show_start_time must equal start_at precisely (no offset added)
            assert abs(body["server_show_start_time"] - target_start) < 0.001, (
                f"Expected server_show_start_time≈{target_start:.3f}, "
                f"got {body['server_show_start_time']:.3f}"
            )
    finally:
        _cleanup_show_file(show_name)


def test_absolute_time_explicit_offset_zero_ignored():
    """Explicit offset=0 alongside start_at: start_at is still used unchanged."""
    show_name = "test_timing_abs_offset0.json"
    _write_show_file(show_name)
    try:
        with TestClient(app) as client:
            session_id = _create_session(client)
            target_start = time.time() + 5.0

            resp = client.post(
                f"/api/session/{session_id}/play-show-by-name",
                params={
                    "name": show_name,
                    "start_at": f"{target_start:.6f}",
                    "offset": "0",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["scheduling"] == "absolute"
            assert abs(body["server_show_start_time"] - target_start) < 0.001
    finally:
        _cleanup_show_file(show_name)


def test_absolute_time_offset_five_ignored():
    """Even if offset=5 is passed alongside start_at, start_at takes precedence.

    This is the critical regression test: previously the show was starting
    5 seconds late because offset=5 was applied on top of start_at.
    """
    show_name = "test_timing_offset5.json"
    _write_show_file(show_name)
    try:
        with TestClient(app) as client:
            session_id = _create_session(client)
            target_start = time.time() + 3.0

            resp = client.post(
                f"/api/session/{session_id}/play-show-by-name",
                params={
                    "name": show_name,
                    "start_at": f"{target_start:.6f}",
                    "offset": "5",  # legacy default — must NOT be added to start_at
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["scheduling"] == "absolute"
            # Must equal target_start, NOT target_start + 5
            assert abs(body["server_show_start_time"] - target_start) < 0.001, (
                "offset=5 was applied on top of start_at — this is the 5-second delay bug!"
            )
    finally:
        _cleanup_show_file(show_name)


def test_absolute_time_late_request_still_uses_start_at():
    """Server must honour start_at even when the request arrives after start_at.

    This guards the server-side half of the pre-roll pinning fix: if the HTTP
    request is sent late (e.g. because MIDI port setup was slow on the local
    machine), the server must still schedule the show at the *original*
    start_at value — not at 'now + offset'.  This ensures that when the
    local worker pins the pre-roll end to absolute_start_time, the remote
    show's time-zero matches.
    """
    show_name = "test_timing_late_request.json"
    _write_show_file(show_name)
    try:
        with TestClient(app) as client:
            session_id = _create_session(client)
            # Simulate a start_at that is slightly in the past (as if the
            # request arrived a few seconds after the intended play time).
            target_start = time.time() - 2.0

            resp = client.post(
                f"/api/session/{session_id}/play-show-by-name",
                params={
                    "name": show_name,
                    "start_at": f"{target_start:.6f}",
                    "offset": "0",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["scheduling"] == "absolute"
            # server_show_start_time must still equal the original start_at,
            # not be bumped forward to 'now'.
            assert abs(body["server_show_start_time"] - target_start) < 0.001, (
                f"Expected server_show_start_time={target_start:.3f}, "
                f"got {body['server_show_start_time']:.3f} — server must not "
                "override a past start_at with 'now'"
            )
    finally:
        _cleanup_show_file(show_name)


def test_relative_fallback_default_offset_zero():
    """Without start_at, the default offset is now 0 (not 5).

    The play_show_by_name endpoint defaults to offset=0 because it is designed
    for absolute-time scheduling; using offset=5 as the fallback default could
    silently reintroduce a 5-second delay if start_at is ever absent.
    """
    show_name = "test_timing_rel_default.json"
    _write_show_file(show_name)
    try:
        with TestClient(app) as client:
            session_id = _create_session(client)

            t_before = time.time()
            resp = client.post(
                f"/api/session/{session_id}/play-show-by-name",
                params={"name": show_name},  # no start_at, no explicit offset
            )
            t_after = time.time()

            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["scheduling"] == "relative"
            # With offset=0 the start time should be essentially "now"
            # (allow 1 second of test execution slack).
            assert t_before <= body["server_show_start_time"] <= t_after + 1.0, (
                f"Expected server_show_start_time near 'now' ({t_before:.3f}–{t_after:.3f}), "
                f"got {body['server_show_start_time']:.3f} — legacy offset=5 may be in effect"
            )
    finally:
        _cleanup_show_file(show_name)
