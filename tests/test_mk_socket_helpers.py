"""Focused tests for the standalone mpv socket-path helper in MK_Kontrol_Scalar.py.

The helper is reproduced here instead of imported directly because
MK_Kontrol_Scalar.py has top-level PyQt imports that fail in headless test
environments.
"""

import os
import uuid


def _make_unique_mpv_pipe_name(prefix):
    short_id = uuid.uuid4().hex[:8]
    path = f"/tmp/{prefix}_{os.getpid()}_{short_id}.sock"
    if len(path.encode("utf-8")) > 100:
        path = f"/tmp/mpv_{short_id}.sock"
    return path


def test_make_unique_mpv_pipe_name_uses_tmp_and_prefix():
    pipe_path = _make_unique_mpv_pipe_name("mpv_test")
    assert pipe_path.startswith("/tmp/mpv_test_")
    assert pipe_path.endswith(".sock")


def test_make_unique_mpv_pipe_name_stays_under_macos_limit():
    pipe_path = _make_unique_mpv_pipe_name("mpv_socket")
    assert len(pipe_path.encode("utf-8")) <= 100


def test_make_unique_mpv_pipe_name_falls_back_for_long_prefix():
    long_prefix = "mpv_socket_" + ("verylong_" * 12)
    pipe_path = _make_unique_mpv_pipe_name(long_prefix)
    assert pipe_path.startswith("/tmp/mpv_")
    assert long_prefix not in pipe_path
    assert pipe_path.endswith(".sock")
    assert len(pipe_path.encode("utf-8")) <= 100
