"""Exercise real Windows UI/controller methods without importing Qt or hardware."""

import ast
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from xr12_lufs import LUFS_DEFAULTS, LufsAgc, normalize_lufs_config


SOURCE = Path(__file__).resolve().parents[1] / "live_controller.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
METHODS = {
    "load_config", "save_config", "_update_lufs", "_lufs_controls_audience",
    "_open_audience_if_idle", "_close_audience_for_playback",
    "_stop_lufs_control", "open_xr12_audience", "mute_xr12_audience",
    "_restart_lufs_worker", "_on_lufs_capture_changed",
}
APP = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "LiveController")
NAMESPACE = {
    "json": json, "os": os, "time": time,
    "LUFS_DEFAULTS": LUFS_DEFAULTS, "normalize_lufs_config": normalize_lufs_config,
    "DEFAULT_VIDEO_SCREEN_NUMBER": 2, "DEFAULT_LOAD_DELAY_SECONDS": 3,
    "DEFAULT_SYNC_TIMING_TRIM_MS": 0, "DEFAULT_XR12_AUDIENCE_ENABLED": True,
    "DEFAULT_XR12_AUDIENCE_FADE_SECONDS": 3.0, "DEFAULT_XR12_AUDIENCE_OPEN_VALUE": 96,
    "DEFAULT_XR12_AUDIENCE_CLOSED_VALUE": 0, "XR12_NUM_CHANNELS": 4,
    "DEFAULT_XR12_CH_ENABLED": [True, True, False, False],
    "clamp_midi_value": lambda value: max(0, min(127, int(round(value)))),
}
CLASS = ast.ClassDef(
    name="HeadlessApp", bases=[], keywords=[],
    body=[node for node in APP.body if isinstance(node, ast.FunctionDef) and node.name in METHODS],
    decorator_list=[],
)
exec(compile(ast.fix_missing_locations(ast.Module(body=[CLASS], type_ignores=[])), str(SOURCE), "exec"), NAMESPACE)
HeadlessApp = NAMESPACE["HeadlessApp"]
MIDI = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "Xr12AudienceController")
MIDI_CLASS = ast.ClassDef(
    name="HeadlessMidi", bases=[], keywords=[],
    body=[node for node in MIDI.body if isinstance(node, ast.FunctionDef)
          and node.name in ("request_open", "request_open_channels", "request_close", "_enabled_channel_indexes")],
    decorator_list=[],
)
exec(compile(ast.fix_missing_locations(ast.Module(body=[MIDI_CLASS], type_ignores=[])), str(SOURCE), "exec"), NAMESPACE)
HeadlessMidi = NAMESPACE["HeadlessMidi"]


def checkbox(checked):
    return SimpleNamespace(isChecked=lambda: checked)


def make_app(enabled=True):
    app = HeadlessApp()
    app._app_is_closing = False
    app._lufs_scan_result = None
    app._lufs_valid = False
    app._lufs_fade_owned = False
    app._lufs_retry_at = 0.0
    app._lufs_agc = LufsAgc()
    app._lufs_worker = Mock()
    app._lufs_worker.snapshot.return_value = (-40.0, "Measuring", True)
    app.xr12_controller = Mock(enabled=True)
    app.xr12_lufs_agc_checkbox = checkbox(enabled)
    app.xr12_lufs_meter_checkbox = checkbox(False)
    app.xr12_lufs_device_combo = SimpleNamespace(currentData=lambda: "")
    app.xr12_lufs_readout = Mock()
    app.xr12_lufs_meter = Mock()
    app.xr12_lufs_status = Mock()
    app.xr12_lufs_settings = {"xr12_lufs_threshold": SimpleNamespace(value=lambda: -30.0)}
    app._has_active_playback = lambda: False
    return app


class LufsIntegrationTests(unittest.TestCase):
    def test_quiet_opens_loud_closes_without_duplicate_commands(self):
        app = make_app()
        app._update_lufs()
        app._update_lufs()
        app.xr12_controller.request_open.assert_called_once_with()
        app.xr12_controller.request_close.assert_not_called()
        app._lufs_worker.snapshot.return_value = (-20.0, "Measuring", True)
        with unittest.mock.patch.object(time, "monotonic", return_value=time.monotonic() + 3):
            app._update_lufs()
            app._update_lufs()
        app.xr12_controller.request_close.assert_called_once_with()

    def test_playback_callbacks_do_not_fight_valid_agc(self):
        app = make_app()
        app._update_lufs()
        app._open_audience_if_idle()
        app._close_audience_for_playback()
        app.xr12_controller.request_open.assert_called_once_with()
        app.xr12_controller.request_close.assert_not_called()

    def test_failed_midi_request_retries_without_consuming_transition(self):
        app = make_app()
        app.xr12_controller.request_open.side_effect = [False, True]
        with unittest.mock.patch.object(time, "monotonic", return_value=10):
            app._update_lufs()
        self.assertFalse(app._lufs_controls_audience())
        with unittest.mock.patch.object(time, "monotonic", return_value=11):
            app._update_lufs()
        self.assertEqual(app.xr12_controller.request_open.call_count, 1)
        with unittest.mock.patch.object(time, "monotonic", return_value=12):
            app._update_lufs()
            app._update_lufs()
        self.assertTrue(app._lufs_controls_audience())
        self.assertEqual(app.xr12_controller.request_open.call_count, 2)

    def test_disabled_agc_preserves_playback_automation(self):
        app = make_app(enabled=False)
        app._update_lufs()
        app.xr12_controller.request_open.assert_not_called()
        app._close_audience_for_playback()
        app._open_audience_if_idle()
        app.xr12_controller.request_close.assert_called_once_with()
        app.xr12_controller.request_open.assert_called_once_with()

    def test_missing_invalid_and_unready_readings_never_command(self):
        for value, ready in ((None, False), (-40, False), (float("nan"), True), (float("inf"), True)):
            with self.subTest(value=value, ready=ready):
                app = make_app()
                app._lufs_worker.snapshot.return_value = (value, "Unavailable", ready)
                app._update_lufs()
                app.xr12_controller.request_open.assert_not_called()
                app.xr12_controller.request_close.assert_not_called()

    def test_silence_only_opens_after_full_window(self):
        app = make_app()
        app._lufs_worker.snapshot.return_value = (float("-inf"), "Warming up", False)
        app._update_lufs()
        app.xr12_controller.request_open.assert_not_called()
        app._lufs_worker.snapshot.return_value = (float("-inf"), "Silence", True)
        app._update_lufs()
        app.xr12_controller.request_open.assert_called_once_with()

    def test_manual_override_remains_until_next_transition(self):
        app = make_app()
        app._update_lufs()
        app.mute_xr12_audience()
        app._update_lufs()
        app.xr12_controller.request_open.assert_called_once_with()
        app.xr12_controller.request_close.assert_called_once_with()
        self.assertFalse(app._lufs_fade_owned)
        self.assertTrue(app._lufs_controls_audience())

    def test_disabling_or_losing_readings_cancels_only_agc_owned_fade(self):
        app = make_app()
        app._update_lufs()
        app._stop_lufs_control()
        app.xr12_controller.cancel_fades.assert_called_once_with()
        app.xr12_controller.request_close.assert_not_called()
        app = make_app()
        app._update_lufs()
        app.open_xr12_audience()
        app._lufs_worker.snapshot.return_value = (None, "Disconnected", False)
        app._update_lufs()
        app.xr12_controller.cancel_fades.assert_not_called()
        self.assertFalse(app._lufs_controls_audience())

    def test_master_xr12_disabled_never_receives_agc_commands(self):
        app = make_app()
        app.xr12_controller.enabled = False
        app._update_lufs()
        app.xr12_controller.request_open.assert_not_called()

    def test_agc_uses_actual_fade_targets_and_only_selected_channels(self):
        midi = HeadlessMidi()
        midi.enabled = True
        midi._ch_enabled = [True, False, True, False]
        midi.fade_duration_sec = 3.5
        for field in ("start", "target", "started_at", "total_sec"):
            setattr(midi, f"_ch_fade_{field}", [50] * 4)
        midi._ch_mute_after = [False] * 4
        midi._ch_fade_active = [False] * 4
        midi._ch_states = []
        for _ in range(4):
            state = Mock()
            state.request_open.return_value = SimpleNamespace(
                initial_messages=[], start_value=50, target_value=96, mute_after_fade=False)
            state.request_close.return_value = SimpleNamespace(
                initial_messages=[], start_value=50, target_value=12, mute_after_fade=False)
            midi._ch_states.append(state)
        for method in ("_cancel_fades", "_send_messages", "_emit_runtime_status"):
            setattr(midi, method, Mock())
        midi._ensure_port = Mock(return_value=True)
        midi._start_or_finish_fades = Mock(return_value=True)
        app = make_app()
        app.xr12_controller = midi
        app._update_lufs()
        self.assertEqual(midi._ch_fade_target, [96, 50, 96, 50])
        self.assertEqual(midi._ch_fade_total_sec, [3.5, 50, 3.5, 50])
        app._lufs_worker.snapshot.return_value = (-20.0, "Measuring", True)
        with unittest.mock.patch.object(time, "monotonic", return_value=time.monotonic() + 3):
            app._update_lufs()
        self.assertEqual(midi._ch_fade_target, [12, 50, 12, 50])
        for index in (1, 3):
            midi._ch_states[index].request_open.assert_not_called()
            midi._ch_states[index].request_close.assert_not_called()

    def test_disabling_agc_stops_capture_and_owned_fade_immediately(self):
        app = make_app()
        app._update_lufs()
        worker = app._lufs_worker
        app.xr12_lufs_agc_checkbox = checkbox(False)
        app.save_config = Mock()
        app._on_lufs_capture_changed(False)
        worker.stop.assert_called_once_with()
        self.assertIsNone(app._lufs_worker)
        app.xr12_controller.cancel_fades.assert_called_once_with()
        app.xr12_controller.request_open.assert_called_once_with()
        app.xr12_controller.request_close.assert_not_called()

    def test_all_playback_close_paths_use_guard(self):
        for name in ("start_countdown", "execute_playback", "play_test_track", "_start_calib_loop"):
            method = next(node for node in APP.body if isinstance(node, ast.FunctionDef) and node.name == name)
            calls = [node.func.attr for node in ast.walk(method)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
            self.assertIn("_close_audience_for_playback", calls)
            self.assertNotIn("request_close", calls)

    def test_real_load_config_old_file_and_new_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            NAMESPACE["CONFIG_FILE"] = str(Path(directory) / "config.json")
            app = HeadlessApp()
            self.assertFalse(app.load_config()["xr12_lufs_agc_enabled"])
            Path(NAMESPACE["CONFIG_FILE"]).write_text(json.dumps({
                "xr12_audience_unity_value": 87,
                "xr12_lufs_threshold": -42.5, "xr12_lufs_hysteresis": 0,
                "xr12_lufs_hold_seconds": 0, "xr12_lufs_input_device": "host:input",
            }))
            config = app.load_config()
            self.assertEqual(config["xr12_audience_open_value"], 87)
            self.assertEqual(config["xr12_lufs_threshold"], -42.5)
            self.assertEqual(config["xr12_lufs_hysteresis"], 0)
            self.assertEqual(config["xr12_lufs_hold_seconds"], 0)
            self.assertEqual(config["xr12_lufs_input_device"], "host:input")
            self.assertFalse(config["xr12_lufs_agc_enabled"])

    def test_real_save_config_persists_lufs_settings(self):
        app = make_app()
        app.config = {}
        for name, text in (("display_combo", "2"), ("preload_combo", "3"),
                           ("sync_show_host_input", "localhost"), ("sync_show_session_input", "session")):
            setattr(app, name, SimpleNamespace(currentText=lambda value=text: value,
                                               text=lambda value=text: value))
        for name in ("apply_zoom_checkbox", "xr12_enabled_checkbox", "xr12_lufs_meter_checkbox"):
            setattr(app, name, checkbox(True))
        for name in ("sync_show_trim_spinbox", "xr12_fade_duration_spinbox",
                     "xr12_unity_spinbox", "xr12_closed_value_spinbox"):
            setattr(app, name, SimpleNamespace(value=lambda: 0))
        app.xr12_ch_enabled_cbs = [checkbox(True), checkbox(True), checkbox(False), checkbox(False)]
        app.xr12_lufs_device_combo = SimpleNamespace(currentData=lambda: "host:input")
        app.xr12_lufs_settings = {key: SimpleNamespace(value=lambda value=value: value)
                                 for key, value in LUFS_DEFAULTS.items()
                                 if key in ("xr12_lufs_threshold", "xr12_lufs_hysteresis", "xr12_lufs_hold_seconds")}
        with tempfile.TemporaryDirectory() as directory:
            NAMESPACE["CONFIG_FILE"] = str(Path(directory) / "config.json")
            app.save_config()
            saved = json.loads(Path(NAMESPACE["CONFIG_FILE"]).read_text())
        self.assertTrue(saved["xr12_lufs_agc_enabled"])
        self.assertTrue(saved["xr12_lufs_meter_enabled"])
        self.assertEqual(saved["xr12_lufs_input_device"], "host:input")
        self.assertEqual(saved["xr12_lufs_threshold"], -30.0)


if __name__ == "__main__":
    unittest.main()
