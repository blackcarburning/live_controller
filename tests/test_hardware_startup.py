"""Real Qt startup checks with simulated disconnected/stalled hardware."""

import ast
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtWidgets import QApplication, QDialog, QPushButton
    from PyQt6.QtCore import QTimer
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 is required for real-window startup tests")
class HardwareStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        source = Path(__file__).resolve().parents[1] / "live_controller.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        tree.body = [
            node for node in tree.body
            if not (
                isinstance(node, ast.Import)
                and any(alias.name in {"rtmidi", "keyboard", "psutil", "serial"} for alias in node.names)
                or isinstance(node, ast.ImportFrom) and node.module == "serial.tools"
                or isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "winmm" for target in node.targets)
            )
        ]
        cls.namespace = {
            "__name__": "startup_test", "rtmidi": Mock(), "keyboard": Mock(),
            "psutil": Mock(), "serial": Mock(), "list_ports": Mock(), "winmm": Mock(),
        }
        exec(compile(tree, str(source), "exec"), cls.namespace)
        cls.namespace["GlobalHotkeyListener"] = Mock()
        cls.namespace["PositionPoller"] = Mock()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        old_directory = os.getcwd()
        os.chdir(self.directory.name)
        self.addCleanup(os.chdir, old_directory)
        self.namespace["rtmidi"] = Mock()
        self.namespace["list_ports"] = Mock()
        self.namespace["list_ports"].comports.return_value = []

    def make_window(self, **kwargs):
        window = self.namespace["LiveController"](**kwargs)
        window.showMaximized()

        def cleanup():
            window.close()
            window.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup)
        return window

    def pump_until(self, predicate, seconds=2):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def test_prompt_defaults_to_skip_and_accepts_selections(self):
        dialog = self.namespace["StartupHardwareDialog"]()
        self.assertFalse(dialog.xr12_connected.isChecked())
        self.assertFalse(dialog.arduino_connected.isChecked())
        dialog.xr12_connected.setChecked(True)
        dialog.arduino_connected.setChecked(True)
        dialog.findChild(QPushButton).click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(dialog.xr12_connected.isChecked())
        self.assertTrue(dialog.arduino_connected.isChecked())
        dialog.deleteLater()

    def test_skip_opens_real_window_without_xr12_or_arduino_calls(self):
        window = self.make_window()
        window._connect_arduino = Mock()
        self.pump_until(lambda: not window._hardware_timer.isActive()
                        and self.namespace["rtmidi"].MidiOut.called)
        self.assertTrue(window.isVisible())
        window._connect_arduino.assert_not_called()
        self.assertFalse(window.xr12_controller.enabled)
        self.assertIsNone(window.xr12_controller._port_probe)
        ports = self.namespace["rtmidi"].MidiOut.return_value.open_port.call_args_list
        self.assertTrue(all(call.args[0] != 3 for call in ports))

    def test_stalled_devices_time_out_after_ten_real_seconds_while_ui_runs(self):
        release = threading.Event()
        arduino_started = threading.Event()
        xr12_started = threading.Event()
        port = Mock()
        port.is_port_open.return_value = True

        def open_midi(index):
            if index == 3:
                xr12_started.set()
            release.wait()

        self.namespace["rtmidi"].MidiOut.return_value = port
        port.open_port.side_effect = open_midi
        started_at = time.monotonic()
        window = self.make_window(xr12_connected=True, arduino_connected=True)
        self.addCleanup(release.set)
        arduino = Mock()
        arduino_closed = threading.Event()
        arduino.close.side_effect = arduino_closed.set

        def connect_arduino():
            arduino_started.set()
            release.wait()
            return arduino

        window._connect_arduino = connect_arduino
        ticks = []
        heartbeat = QTimer(window)
        heartbeat.setInterval(25)
        heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
        heartbeat.start()
        self.pump_until(lambda: arduino_started.is_set() and xr12_started.is_set())
        self.assertTrue(window.isVisible())
        self.assertLess(time.monotonic() - started_at, 2)
        self.pump_until(
            lambda: window.xr12_controller._port_timed_out and not window._hardware_probes,
            seconds=11,
        )
        self.assertGreaterEqual(time.monotonic() - started_at, 10)
        self.assertLess(time.monotonic() - started_at, 11.5)
        self.assertGreater(len(ticks), 100)
        self.assertIn("timed out after 10 seconds", window.xr12_status_label.text())
        self.assertIsNone(window.arduino_serial)
        self.assertFalse(window.midi_available)
        self.assertTrue(window.isVisible())
        self.assertFalse(window._hardware_timer.isActive())
        release.set()
        self.assertTrue(arduino_closed.wait(1))
        self.assertIsNone(window.arduino_serial)
        heartbeat.stop()

    def test_selected_missing_devices_report_failure_without_holding_window(self):
        self.namespace["rtmidi"].MidiOut.return_value.open_port.side_effect = RuntimeError("No MIDI")
        window = self.make_window(xr12_connected=True, arduino_connected=True)
        self.pump_until(lambda: window.xr12_controller.last_error
                        and not window._hardware_probes)
        self.assertTrue(window.isVisible())
        self.assertIsNone(window.arduino_serial)
        self.assertFalse(window.midi_available)
        self.assertIn("No MIDI", window.xr12_status_label.text())

    def test_connected_arduino_preserves_chase_and_clock_led_feedback(self):
        window = self.make_window(arduino_connected=True)
        arduino = Mock(is_open=True)
        window._connect_arduino = Mock(return_value=arduino)
        self.pump_until(lambda: window.arduino_serial is arduino
                        and not window._hardware_probes)
        arduino.write.assert_called_once_with(b"5")
        self.assertTrue(window.midi_available)
        window._finish_startup_led_test()
        arduino.write.assert_called_with(b"4")

    def test_close_during_arduino_probe_discards_late_result(self):
        release = threading.Event()
        started = threading.Event()
        closed = threading.Event()
        arduino = Mock()
        arduino.close.side_effect = closed.set
        window = self.make_window(arduino_connected=True)
        self.addCleanup(release.set)

        def connect():
            started.set()
            release.wait()
            return arduino

        window._connect_arduino = connect
        self.pump_until(started.is_set)
        window.close()
        self.assertFalse(window._hardware_timer.isActive())
        self.assertFalse(window._hardware_probes)
        release.set()
        self.assertTrue(closed.wait(1))
        self.assertIsNone(window.arduino_serial)
        arduino.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
