"""Exercise the real XR12 controller with fake Qt timers and MIDI hardware."""

import ast
from contextlib import redirect_stdout
from dataclasses import dataclass
import io
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from xr12_connection import Xr12ConnectionAttempt


class FakeTimer:
    def __init__(self, parent):
        self.timeout = Mock()
        self.active = False

    def setInterval(self, interval):
        self.interval = interval

    def start(self):
        self.active = True

    def stop(self):
        self.active = False


SOURCE = Path(__file__).resolve().parents[1] / "live_controller.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
NAMESPACE = {
    "QObject": type("QObject", (), {"__init__": lambda self, parent: None}),
    "QTimer": FakeTimer, "time": time, "dataclass": dataclass,
    "Xr12ConnectionAttempt": Xr12ConnectionAttempt,
}
NODES = [
    node for node in TREE.body
    if (
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name)
                and target.id.startswith(("XR12_", "DEFAULT_XR12_", "LEGACY_DEFAULT_XR12_"))
                for target in node.targets)
    ) or (
        isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and node.name in {
            "clamp_midi_value", "build_audience_fader_messages",
            "build_audience_mute_messages", "interpolate_midi_value",
            "FadeCommand", "Xr12AudienceState", "Xr12AudienceController",
        }
    )
]
exec(compile(ast.Module(body=NODES, type_ignores=[]), str(SOURCE), "exec"), NAMESPACE)
Controller = NAMESPACE["Xr12AudienceController"]


class Xr12ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.port = Mock()
        self.port.is_port_open.return_value = True
        self.rtmidi = SimpleNamespace(MidiOut=Mock(return_value=self.port))
        self.status = Mock()
        self.controller = Controller(self.status, self.rtmidi, fade_duration_sec=0)
        self.addCleanup(self.controller.shutdown)

    def finish_connection(self):
        for _ in range(1000):
            self.controller._poll_port_connection()
            if self.controller._port_probe is None:
                return
            time.sleep(0.001)
        self.fail("Connection did not finish")

    def block_connection(self):
        started = threading.Event()
        release = threading.Event()

        def open_port(index):
            started.set()
            release.wait()

        self.port.open_port.side_effect = open_port
        self.addCleanup(release.set)
        return started, release

    def test_success_replays_open_with_existing_fader_behavior(self):
        self.controller.set_fade_duration(3)
        self.assertFalse(self.controller.request_open())
        self.finish_connection()
        self.assertTrue(self.controller.available)
        self.port.open_port.assert_called_once_with(3)
        with patch("xr12_connection.time.monotonic",
                   return_value=max(self.controller._ch_fade_started_at) + 3.1):
            self.controller._on_fade_step()
        self.assertEqual(
            [call.args[0] for call in self.port.send_message.call_args_list],
            [[0xB0, 0, 96], [0xB0, 1, 96]],
        )
        self.assertFalse(self.controller.connection_timer.active)

    def test_missing_port_reports_unavailable_without_raising(self):
        self.port.open_port.side_effect = RuntimeError("No MIDI port 3")
        self.assertFalse(self.controller.request_open())
        self.finish_connection()
        self.assertFalse(self.controller.available)
        self.assertIn("No MIDI port 3", self.status.call_args.args[0])
        self.port.send_message.assert_not_called()
        self.port.close_port.assert_called_once()

    def test_wait_times_out_at_exactly_15_seconds_without_blocking(self):
        started, release = self.block_connection()
        with patch("xr12_connection.time.monotonic", return_value=100):
            self.assertFalse(self.controller.request_open())
        self.assertTrue(started.wait(1))
        with patch("xr12_connection.time.monotonic", return_value=114.999):
            self.controller._poll_port_connection()
            self.assertTrue(self.controller.connection_timer.active)
            self.assertFalse(self.controller._port_timed_out)
        with patch("xr12_connection.time.monotonic", return_value=115):
            self.controller._poll_port_connection()
        self.assertTrue(self.controller._port_timed_out)
        self.assertFalse(self.controller.available)
        self.assertFalse(self.controller.connection_timer.active)
        self.assertIn("timed out after 15 seconds", self.status.call_args.args[0])
        self.assertIn("continuing without XR12", self.status.call_args.args[0])
        self.assertIsNone(self.controller._pending_port_command)
        self.assertFalse(any(self.controller._ch_fade_active))
        for _ in range(3):
            self.assertFalse(self.controller.request_open())
        self.rtmidi.MidiOut.assert_called_once()
        self.assertIn("timed out after 15 seconds", self.status.call_args.args[0])
        closed = threading.Event()
        self.port.close_port.side_effect = closed.set
        release.set()
        self.assertTrue(closed.wait(1))
        self.port.send_message.assert_not_called()

    def test_latest_close_replaces_pending_idle_open(self):
        started, release = self.block_connection()
        self.controller.request_open()
        self.assertTrue(started.wait(1))
        self.controller.request_close()
        self.rtmidi.MidiOut.assert_called_once()
        release.set()
        self.finish_connection()
        self.assertTrue(self.controller.available)
        self.assertEqual(self.controller.state.current_value, 0)
        self.port.send_message.assert_not_called()

    def test_latest_open_replaces_pending_close(self):
        started, release = self.block_connection()
        self.controller.request_close()
        self.assertTrue(started.wait(1))
        self.controller.request_open()
        release.set()
        self.finish_connection()
        self.assertEqual(self.controller.state.current_value, 96)

    def test_disable_discards_late_connection(self):
        started, release = self.block_connection()
        self.controller.request_open()
        self.assertTrue(started.wait(1))
        self.controller.set_enabled(False)
        self.assertFalse(self.controller.connection_timer.active)
        self.assertIsNone(self.controller._port_probe)
        closed = threading.Event()
        self.port.close_port.side_effect = closed.set
        release.set()
        self.assertTrue(closed.wait(1))
        self.assertFalse(self.controller.available)
        self.assertEqual(self.status.call_args.args[0], "XR12 Audience: disabled")
        self.port.send_message.assert_not_called()

    def test_shutdown_discards_late_connection(self):
        started, release = self.block_connection()
        self.controller.request_open()
        self.assertTrue(started.wait(1))
        self.controller.shutdown()
        self.assertFalse(self.controller.connection_timer.active)
        closed = threading.Event()
        self.port.close_port.side_effect = closed.set
        release.set()
        self.assertTrue(closed.wait(1))
        self.port.send_message.assert_not_called()

    def test_toggle_after_timeout_allows_new_connection(self):
        started, release = self.block_connection()
        with patch("xr12_connection.time.monotonic", return_value=0):
            self.controller.request_open()
        self.assertTrue(started.wait(1))
        with patch("xr12_connection.time.monotonic", return_value=15):
            self.controller._poll_port_connection()
        self.controller.set_enabled(False)
        self.controller.set_enabled(True)
        replacement = Mock()
        replacement.is_port_open.return_value = True
        self.rtmidi.MidiOut.return_value = replacement
        self.controller.request_open()
        self.finish_connection()
        self.assertTrue(self.controller.available)
        self.assertIs(self.controller.midiout, replacement)
        self.assertFalse(self.controller._port_timed_out)
        closed = threading.Event()
        self.port.close_port.side_effect = closed.set
        release.set()
        self.assertTrue(closed.wait(1))
        self.assertIs(self.controller.midiout, replacement)

    def test_raw_fader_and_mute_commands_replay_after_connection(self):
        for method, status in (("send_raw_fader", 0xB0), ("send_raw_mute", 0xB1)):
            with self.subTest(method=method):
                self.controller.set_enabled(False)
                self.controller.set_enabled(True)
                self.port.send_message.reset_mock()
                getattr(self.controller, method)(45)
                self.finish_connection()
                self.assertEqual(
                    [call.args[0] for call in self.port.send_message.call_args_list],
                    [[status, 0, 45], [status, 1, 45]],
                )

    def test_disabled_channels_are_not_opened_after_connection(self):
        self.controller.set_fade_duration(3)
        started, release = self.block_connection()
        self.controller.request_open()
        self.assertTrue(started.wait(1))
        self.controller.set_ch_enabled(1, False)
        release.set()
        self.finish_connection()
        with patch("xr12_connection.time.monotonic",
                   return_value=max(self.controller._ch_fade_started_at) + 3.1):
            self.controller._on_fade_step()
        self.port.send_message.assert_called_once_with([0xB0, 0, 96])

    def test_disabled_controller_never_connects(self):
        self.controller.set_enabled(False)
        self.assertFalse(self.controller.request_open())
        self.rtmidi.MidiOut.assert_not_called()

    def test_normal_fade_uses_existing_duration_after_connection(self):
        self.controller.set_fade_duration(3)
        self.controller.request_open()
        self.finish_connection()
        self.assertTrue(self.controller.fade_timer.active)
        self.assertEqual(self.controller._ch_fade_total_sec[:2], [3, 3])
        with patch("xr12_connection.time.monotonic",
                   return_value=self.controller._ch_fade_started_at[0] + 3.1):
            self.controller._on_fade_step()
        self.assertFalse(self.controller.fade_timer.active)
        self.assertEqual(self.controller.state.current_value, 96)


if __name__ == "__main__":
    unittest.main()
