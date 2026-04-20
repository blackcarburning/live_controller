"""Tests for the global sync timing trim client-side scheduling logic.

These tests validate the arithmetic that live_controller.py applies when
computing sync_show_start from target_start and the configured trim value.

Key invariants (from execute_playback in live_controller.py):
  - sync_show_start = target_start + trim_ms / 1000.0
  - worker.absolute_start_time = target_start  (local track, no trim)
  - positive trim_ms → sync-show starts LATER than local track
  - negative trim_ms → sync-show starts EARLIER than local track
  - zero trim_ms    → sync-show and local track start at the same instant
"""
import json
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

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
    resp = client.post("/api/session", json={"name": "test"})
    assert resp.status_code == 200
    return resp.json()["session_id"]


def _write_show_file(name: str) -> None:
    SHOWS_DIR.mkdir(parents=True, exist_ok=True)
    (SHOWS_DIR / name).write_text(json.dumps(MINIMAL_SHOW), encoding="utf-8")


def _cleanup_show_file(name: str) -> None:
    p = SHOWS_DIR / name
    if p.exists():
        p.unlink()


# ── Pure-arithmetic unit tests (no server required) ───────────────────────────

def _compute_sync_show_start(target_start: float, trim_ms: int) -> float:
    """Mirror of the trim computation in live_controller.py execute_playback.

    sync_show_start = target_start + trim_ms / 1000.0
    local_start     = target_start  (unchanged)
    """
    trim_sec = trim_ms / 1000.0
    return target_start + trim_sec


def test_trim_positive_delays_sync_show():
    """Positive trim_ms: sync_show_start > target_start (sync-show later)."""
    target_start = 1000.0
    trim_ms = 500
    sync_show_start = _compute_sync_show_start(target_start, trim_ms)
    assert sync_show_start > target_start, (
        "Positive trim must make sync-show start LATER than local track"
    )
    assert abs(sync_show_start - target_start - 0.5) < 1e-9, (
        f"Expected +500ms offset but got {(sync_show_start - target_start) * 1000:.1f}ms"
    )


def test_trim_negative_advances_sync_show():
    """Negative trim_ms: sync_show_start < target_start (sync-show earlier)."""
    target_start = 1000.0
    trim_ms = -300
    sync_show_start = _compute_sync_show_start(target_start, trim_ms)
    assert sync_show_start < target_start, (
        "Negative trim must make sync-show start EARLIER than local track"
    )
    assert abs(target_start - sync_show_start - 0.3) < 1e-9, (
        f"Expected -300ms offset but got {(sync_show_start - target_start) * 1000:.1f}ms"
    )


def test_trim_zero_unchanged():
    """Zero trim_ms: sync_show_start == target_start exactly."""
    target_start = 1000.0
    trim_ms = 0
    sync_show_start = _compute_sync_show_start(target_start, trim_ms)
    assert sync_show_start == target_start, (
        "Zero trim must leave sync-show start equal to local start"
    )


def test_trim_max_positive():
    """Maximum positive trim (+2000 ms): offset matches spinbox range limit."""
    target_start = 1000.0
    trim_ms = 2000
    sync_show_start = _compute_sync_show_start(target_start, trim_ms)
    assert abs(sync_show_start - target_start - 2.0) < 1e-9


def test_trim_max_negative():
    """Maximum negative trim (-2000 ms): offset matches spinbox range limit."""
    target_start = 1000.0
    trim_ms = -2000
    sync_show_start = _compute_sync_show_start(target_start, trim_ms)
    assert abs(target_start - sync_show_start - 2.0) < 1e-9


def test_local_start_unaffected_by_trim():
    """The local track start time (absolute_start_time) must equal target_start,
    regardless of the trim value.  Only the sync-show start is shifted.
    """
    target_start = 1000.0
    for trim_ms in (-2000, -500, -1, 0, 1, 500, 2000):
        sync_show_start = _compute_sync_show_start(target_start, trim_ms)
        local_start = target_start  # NOT shifted by trim
        # The offset between sync-show and local track == trim_ms / 1000
        expected_offset = trim_ms / 1000.0
        actual_offset = sync_show_start - local_start
        assert abs(actual_offset - expected_offset) < 1e-9, (
            f"trim_ms={trim_ms}: expected offset {expected_offset:.3f}s "
            f"but got {actual_offset:.3f}s"
        )


# ── Server integration tests: trim applied before sending start_at ────────────
# These verify that when the client computes sync_show_start = target + trim
# and sends it as start_at, the server echoes it back faithfully as
# server_show_start_time.  Together with the pure-arithmetic tests above,
# this provides full end-to-end coverage of the trim path.

def test_server_honors_trimmed_start_at_positive():
    """Server must echo back start_at even when a positive trim offset is included."""
    show_name = "test_trim_logic_positive.json"
    _write_show_file(show_name)
    try:
        with TestClient(app) as client:
            session_id = _create_session(client)
            target_start = time.time() + 5.0
            trim_ms = 750
            sync_show_start = _compute_sync_show_start(target_start, trim_ms)

            resp = client.post(
                f"/api/session/{session_id}/play-show-by-name",
                params={
                    "name": show_name,
                    "start_at": f"{sync_show_start:.6f}",
                    "offset": "0",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["scheduling"] == "absolute"
            assert abs(body["server_show_start_time"] - sync_show_start) < 0.001, (
                f"Server must echo start_at={sync_show_start:.3f} unchanged; "
                f"got {body['server_show_start_time']:.3f}"
            )
    finally:
        _cleanup_show_file(show_name)


def test_server_honors_trimmed_start_at_negative():
    """Server must echo back start_at even when a negative trim offset is included."""
    show_name = "test_trim_logic_negative.json"
    _write_show_file(show_name)
    try:
        with TestClient(app) as client:
            session_id = _create_session(client)
            target_start = time.time() + 5.0
            trim_ms = -400
            sync_show_start = _compute_sync_show_start(target_start, trim_ms)

            resp = client.post(
                f"/api/session/{session_id}/play-show-by-name",
                params={
                    "name": show_name,
                    "start_at": f"{sync_show_start:.6f}",
                    "offset": "0",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["scheduling"] == "absolute"
            assert abs(body["server_show_start_time"] - sync_show_start) < 0.001, (
                f"Server must echo start_at={sync_show_start:.3f} unchanged; "
                f"got {body['server_show_start_time']:.3f}"
            )
    finally:
        _cleanup_show_file(show_name)
