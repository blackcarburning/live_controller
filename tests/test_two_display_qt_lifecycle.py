"""Actual QThread/queued-signal ownership checks on an extracted QWidget SafeHost.

Only test-owned threads run; their work is an Event wait. No controller class,
MIDI/media/serial/native operation or process is constructed. Production close,
completion and bounded-wait guards are extracted unchanged by explicit name.
The older 12 real-widget/render tests remain in their unchanged file.
"""
from __future__ import annotations

import json
import threading
import time
import types
import unittest

try:
    from .test_two_display_support import ExtractedSource, forbid
    from .test_two_display_qt import qt_environment
except ImportError:
    from test_two_display_support import ExtractedSource, forbid
    from test_two_display_qt import qt_environment


OWNERSHIP_METHODS = (
    "closeEvent", "stop_all_activity", "stop_calib_loop",
    "_two_display_cancel_supervisor", "_two_display_thread_running",
    "_two_display_running_threads", "_two_display_schedule_completion_check",
    "_two_display_defer_thread_completion", "_two_display_poll_thread_completions",
    "on_playback_finished", "on_test_finished", "_on_calib_iteration_finished",
)
OWNER_SLOTS = ("worker", "test_worker", "calib_loop_worker")


class RealQtThreadOwnershipTests(unittest.TestCase):
    # Only used on unexpected cleanup failure: a strong reference is safer than
    # destroying a running QThread. Every controlled Event is always released.
    kept_for_safe_exit = []

    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()
        injected = qt_environment(cls, "thread-ownership")
        injected.update(MidiSyncWorker=forbid, MidiTestWorker=forbid,
                        _send_mpv_ipc_command=forbid, _lc_send_ipc_command=forbid)
        cls.ns = cls.source.method_namespace("LiveController", OWNERSHIP_METHODS,
                                              injected=injected)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "artifacts"):
            (cls.artifacts / "qt_lifecycle_traces.json").write_text(json.dumps({
                "source_sha256": cls.source.sha256,
                "qt_version": cls.QtCore.QT_VERSION_STR,
                "pyqt_version": cls.QtCore.PYQT_VERSION_STR,
                "traces": cls.traces, "qt_errors": cls.qt_errors,
                "scope": "AST-selected guards; QWidget SafeHost; Event-only test QThreads; no full app/hardware",
            }, indent=2), encoding="utf-8")

    def setUp(self):
        self.qt_errors.clear()

    def pump(self):
        self.app.processEvents(self.QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.QtCore.QCoreApplication.sendPostedEvents(None, self.QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents(self.QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertEqual(self.qt_errors, [], "A queued Qt callback raised; ownership proof is invalid")

    def until(self, predicate, explanation, timeout_ms=3500):
        deadline = time.monotonic() + timeout_ms / 1000.0
        while not predicate() and time.monotonic() < deadline:
            self.pump()
            self.QtTest.QTest.qWait(5)
        self.pump()
        self.assertTrue(predicate(), explanation)

    def fixture(self, slot):
        core, widgets, ns = self.QtCore, self.QtWidgets, self.ns
        case = self
        events, threads, records, relays = [], [], [], []

        class SafeHost(widgets.QWidget):
            def closeEvent(self, event):
                events.append(["close-enter"])
                ns["closeEvent"](self, event)
                events.append(["close-result", event.isAccepted(),
                               len(self._two_display_running_threads())])

        for name in OWNERSHIP_METHODS:
            if name == "closeEvent":
                continue
            method = ns[name]
            if name in ("_two_display_cancel_supervisor", "_two_display_thread_running"):
                method = staticmethod(method)
            setattr(SafeHost, name, method)
        host = SafeHost()
        host.resize(420, 160)
        host.setWindowTitle("OFFLINE QThread ownership SafeHost")
        host._app_is_closing = False
        host._manual_stop_requested = False
        host.worker = host.test_worker = host.calib_loop_worker = None
        host.calib_loop_active = slot == "calib_loop_worker"
        host.countdown_connection = None
        host.running_test_port = 1
        host.currently_playing_row = None
        host._playback_error_seen = False
        host.tracks = []
        host.current_ipc_socket = "OFFLINE-NO-IPC"
        host.calib_loop_ipc_socket = "OFFLINE-NO-CALIB-IPC"
        host.test_track_path = "SYNTHETIC-NOT-OPENED.mp4"
        host.is_live_mode = False
        host.status_label = widgets.QLabel("OFFLINE", host)
        host.countdown_label = widgets.QLabel("OFFLINE", host)
        host.active_label = widgets.QLabel("OFFLINE", host)
        host.test_file_label = widgets.QLabel("OFFLINE", host)
        host.calib_loop_button = widgets.QPushButton("OFFLINE", host)
        host.play_test_button = widgets.QPushButton("OFFLINE", host)
        host.test_port_buttons = {1: widgets.QPushButton("OFFLINE", host)}
        host.calib_loop_duration_spinbox = widgets.QSpinBox(host)
        for name in ("_startup_poll_timer", "countdown_timer", "calib_loop_restart_timer", "active_flash_timer"):
            setattr(host, name, core.QTimer(host))
        host.calib_loop_restart_timer.setSingleShot(True)
        host.calib_loop_restart_timer.setInterval(100)
        host._startup_probes = {}
        host._shutdown_arduino_panel = lambda: events.append(["arduino-stop"])
        host.save_session = lambda: events.append(["session-save"])
        host.save_config = lambda: events.append(["config-save"])
        host.xr12_controller = types.SimpleNamespace(shutdown=lambda: events.append(["xr12-stop"]))
        host.stop_sync_show = lambda: events.append(["sync-stop"])
        host.send_led_command = lambda value: events.append(["led", value])
        host._reset_scrub_controls = lambda: events.append(["scrub-reset"])
        host._open_audience_if_idle = lambda: events.append(["audience-idle"])
        host.clear_highlight = lambda: events.append(["highlight-clear"])
        host.set_test_controls_enabled = lambda enabled: events.append(["test-controls", enabled])
        for name in ("hotkey_listener", "_position_poller"):
            setattr(host, name, types.SimpleNamespace(
                stop=lambda n=name: events.append([n, "stop"]),
                wait=lambda timeout, n=name: (events.append([n, "wait", timeout]) or True),
                isRunning=lambda: False))

        def finished(owner):
            if slot == "worker":
                host.on_playback_finished(owner=owner)
            elif slot == "test_worker":
                host.on_test_finished(1, owner=owner)
            else:
                host._on_calib_iteration_finished(owner=owner)

        class Relay(core.QObject):
            def __init__(self, owner, record):
                super().__init__(host)
                self.owner, self.record = owner, record

            @core.pyqtSlot()
            def early(self):
                self.record["custom_deliveries"] += 1
                self.record["gui_deliveries"].append(core.QThread.currentThread() == case.app.thread())
                events.append([self.record["name"], "queued-custom-completion"])
                finished(self.owner)

            @core.pyqtSlot()
            def exited(self):
                self.record["actual_finished_deliveries"] += 1
                self.record["gui_deliveries"].append(core.QThread.currentThread() == case.app.thread())
                events.append([self.record["name"], "queued-actual-finished"])
                finished(self.owner)

        class EventWorker(core.QThread):
            early_complete = core.pyqtSignal()

            def __init__(self, name, early):
                # No QWidget parent: even a detected production regression cannot
                # destroy a running C++ QThread when a test host is hidden/closed.
                super().__init__()
                self.release = threading.Event()
                self.entered = threading.Event()
                self.run_exited = threading.Event()
                self.emit_early = early
                self.record = dict(name=name, delete_requests=0, destroyed=0,
                                   custom_deliveries=0, actual_finished_deliveries=0,
                                   gui_deliveries=[], waits=[], violations=[], stopped=0,
                                   event_wait_timed_out=False)
                records.append(self.record)
                self._display_coordinator = types.SimpleNamespace(
                    stop=lambda: events.append([name, "nonblocking-video-cancel"]))
                record = self.record
                self.destroyed.connect(lambda _obj=None: (
                    record.__setitem__("destroyed", record["destroyed"] + 1),
                    events.append([name, "qobject-destroyed"])))

            def run(self):
                self.entered.set()
                events.append([self.record["name"], "actual-run-entered"])
                if self.emit_early:
                    self.early_complete.emit()
                if not self.release.wait(20):
                    self.record["event_wait_timed_out"] = True
                events.append([self.record["name"], "actual-run-exited"])
                self.run_exited.set()

            def stop(self):
                # Intentionally do not release: exercise actual wait(2500)==False
                # rather than replacing the real QThread wait with a fake.
                self.record["stopped"] += 1
                events.append([self.record["name"], "stop-request"])

            def wait(self, timeout):
                self.record["waits"].append(timeout)
                return super().wait(timeout)

            def deleteLater(self):
                self.record["delete_requests"] += 1
                try:
                    running = self.isRunning()
                except RuntimeError:
                    self.record["violations"].append("delete after QObject destruction")
                    return
                if running:
                    # Fail safely, not by aborting the process from Qt's destructor.
                    self.record["violations"].append("delete while real QThread running")
                    return
                if self.record["delete_requests"] != 1:
                    self.record["violations"].append("duplicate production deleteLater")
                    return
                events.append([self.record["name"], "production-deleteLater"])
                super().deleteLater()

        def start(name, early=False):
            owner = EventWorker(name, early)
            threads.append(owner)
            setattr(host, slot, owner)
            relay = Relay(owner, owner.record)
            relays.append(relay)
            owner.early_complete.connect(relay.early, core.Qt.ConnectionType.QueuedConnection)
            owner.finished.connect(relay.exited, core.Qt.ConnectionType.QueuedConnection)
            owner.start()  # Only this Event-only test class is ever started.
            self.until(owner.entered.is_set, "Test QThread did not enter its controlled Event wait")
            return owner

        def cleanup():
            incomplete = []
            try:
                for owner in threads:
                    owner.release.set()
                for owner in threads:
                    try:
                        if owner.isRunning() and not core.QThread.wait(owner, 2000):
                            incomplete.append(owner)
                    except RuntimeError:  # C++ object already destroyed after genuine exit.
                        pass
                if incomplete:
                    self.kept_for_safe_exit.append((host, threads, relays))
                    self.fail("Controlled QThread did not finish during bounded cleanup; kept alive, never terminated")
                # Flush queued callbacks before deleting any test-owned QObject.
                self.pump()
                host._app_is_closing = False
                host._two_display_pending_completions = {}
                for name in OWNER_SLOTS:
                    setattr(host, name, None)
                self.QtTest.QTest.qWait(35)
                self.pump()
                for owner in threads:
                    if not owner.record["destroyed"]:
                        core.QThread.deleteLater(owner)  # Fixture disposal, not a production completion.
                self.pump()
                host.hide()
                host.deleteLater()
                self.pump()
                self.assertTrue(all(not r["violations"] for r in records), records)
                self.assertTrue(all(not r["event_wait_timed_out"] for r in records), records)
                self.assertTrue(all(r["destroyed"] == 1 for r in records), records)
            finally:
                self.traces.append(dict(test=self.id(), slot=slot, records=records,
                                        events=events, cleanup_incomplete=bool(incomplete)))

        self.addCleanup(cleanup)
        host.show()
        self.pump()
        return types.SimpleNamespace(host=host, start=start, threads=threads,
                                     events=events, records=records)

    def assert_clean_completion(self, fixture, owner):
        self.until(lambda: getattr(fixture.host, fixture.slot, None) is None and
                   owner.record["destroyed"] == 1 and owner.record["actual_finished_deliveries"] == 1,
                   "Actual queued QThread finish must release and delete its exact owner once")
        self.assertTrue(owner.run_exited.is_set())
        self.assertEqual(owner.record["delete_requests"], 1)
        self.assertEqual(owner.record["violations"], [])
        self.assertTrue(all(owner.record["gui_deliveries"]))
        self.assertFalse(fixture.host._two_display_running_threads())

    def test_close_ignored_and_repeated_close_idempotent_until_real_thread_finishes(self):
        for slot in OWNER_SLOTS:
            with self.subTest(owner=slot):
                f = self.fixture(slot)
                f.slot = slot
                owner = f.start("close-" + slot)
                start = time.monotonic()
                self.assertFalse(f.host.close(), "A live QThread must make QWidget close return False")
                self.assertLess(time.monotonic() - start, 4.5, "Production bounded wait unexpectedly became unbounded")
                self.assertTrue(f.host.isVisible())
                self.assertIs(getattr(f.host, slot), owner)
                self.assertTrue(owner.isRunning())
                self.assertEqual(owner.record["waits"], [2500])
                self.assertEqual(owner.record["delete_requests"], 0)
                waits = list(owner.record["waits"])
                for _ in range(3):
                    self.assertFalse(f.host.close())
                self.assertEqual(owner.record["waits"], waits, "Close retry must not repeat the blocking wait")
                for event in ("session-save", "config-save", "arduino-stop", "xr12-stop"):
                    self.assertEqual(f.events.count([event]), 1)
                self.assertFalse(any(e[0] == "close-result" and e[1] for e in f.events))
                self.QtCore.QTimer.singleShot(0, owner.release.set)
                self.assert_clean_completion(f, owner)
                self.until(lambda: any(e[0] == "close-result" and e[1] for e in f.events),
                           "Actual finish must allow deferred close to complete")
                accepted = next(i for i, e in enumerate(f.events) if e[0] == "close-result" and e[1])
                deleted = f.events.index([owner.record["name"], "production-deleteLater"])
                self.assertLess(deleted, accepted)
                self.assertTrue(all(e[2] == 0 for e in f.events if e[0] == "close-result" and e[1]))
                self.assertEqual(f.events.count(["session-save"]), 1)

    def test_early_actual_queued_custom_completion_never_deletes_running_thread(self):
        for slot in OWNER_SLOTS:
            with self.subTest(owner=slot):
                f = self.fixture(slot)
                f.slot = slot
                owner = f.start("early-" + slot, early=True)
                self.until(lambda: owner.record["custom_deliveries"] == 1, "Custom completion was not queued to GUI")
                self.assertTrue(owner.isRunning())
                self.assertIs(getattr(f.host, slot), owner)
                self.assertEqual(owner.record["delete_requests"], 0)
                self.assertEqual(owner.record["destroyed"], 0)
                self.assertIs(f.host._two_display_pending_completions[(slot, id(owner))][1], owner)
                self.QtTest.QTest.qWait(60)  # Exercise real 25ms QTimer retry(s), not a fake poller.
                self.pump()
                self.assertTrue(owner.isRunning())
                self.assertIs(getattr(f.host, slot), owner)
                self.assertEqual(owner.record["delete_requests"], 0)
                self.assertEqual(owner.record["gui_deliveries"], [True])
                self.QtCore.QTimer.singleShot(0, owner.release.set)
                self.assert_clean_completion(f, owner)

    def test_delayed_old_generation_queued_finish_never_releases_running_replacement(self):
        for slot in OWNER_SLOTS:
            with self.subTest(owner=slot):
                f = self.fixture(slot)
                f.slot = slot
                old = f.start("old-" + slot, early=True)
                self.until(lambda: old.record["custom_deliveries"] == 1, "Old custom completion was not queued")
                replacement = f.start("replacement-" + slot)
                old.early_complete.emit()  # Explicit queued connection, even from GUI affinity.
                self.until(lambda: old.record["custom_deliveries"] == 2, "Delayed old callback was not delivered")
                self.assertIs(getattr(f.host, slot), replacement)
                self.assertTrue(replacement.isRunning())
                self.assertEqual(replacement.record["delete_requests"], 0)
                self.assertTrue(any(owner is old for _, owner in f.host._two_display_running_threads()))
                self.QtCore.QTimer.singleShot(0, old.release.set)
                self.until(lambda: old.record["actual_finished_deliveries"] == 1 and
                           not any(item[1] is old for item in f.host._two_display_pending_completions.values()),
                           "Old real finish must drain only its own pending generation")
                self.assertIs(getattr(f.host, slot), replacement)
                self.assertTrue(replacement.isRunning())
                self.assertEqual(replacement.record["delete_requests"], 0)
                self.assertEqual(replacement.record["destroyed"], 0)
                self.assertTrue(all(old.record["gui_deliveries"]))
                self.QtCore.QTimer.singleShot(0, replacement.release.set)
                self.assert_clean_completion(f, replacement)

    def test_actual_finished_releases_and_destroys_once_before_explicit_widget_close(self):
        for slot in OWNER_SLOTS:
            with self.subTest(owner=slot):
                f = self.fixture(slot)
                f.slot = slot
                owner = f.start("actual-finished-" + slot)
                spy = self.QtTest.QSignalSpy(owner.finished)
                self.QtCore.QTimer.singleShot(0, owner.release.set)
                self.assert_clean_completion(f, owner)
                self.assertEqual(len(spy), 1, "The genuine QThread.finished signal must arrive once")
                self.assertTrue(f.host.close())
                self.pump()
                accepted = next(i for i, e in enumerate(f.events) if e[0] == "close-result" and e[1])
                destroyed = f.events.index([owner.record["name"], "qobject-destroyed"])
                self.assertLess(destroyed, accepted)
                self.assertEqual(owner.record["delete_requests"], 1)
                self.assertFalse(f.host._two_display_running_threads())


if __name__ == "__main__":
    unittest.main()
