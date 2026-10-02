"""Headless tests of LUFS configuration, decisions, and optional audio capture."""

import importlib.util
import math
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import xr12_lufs as lufs


class ConfigTests(unittest.TestCase):
    def test_legacy_and_missing_config_disable_meter_and_agc(self):
        for config in (None, {}, {"xr12_audience_enabled": True}, []):
            self.assertEqual(lufs.normalize_lufs_config(config), lufs.LUFS_DEFAULTS)

    def test_normalization_is_not_in_place(self):
        config = {
            "xr12_lufs_agc_enabled": "TRUE",
            "xr12_lufs_meter_enabled": "false",
            "xr12_lufs_threshold": "-35.5",
            "xr12_lufs_hysteresis": "-2",
            "xr12_lufs_hold_seconds": "0",
            "xr12_lufs_input_device": " ALSA::Microphone ",
            "unrelated": 1,
        }
        normalized = lufs.normalize_lufs_config(config)
        self.assertTrue(normalized["xr12_lufs_agc_enabled"])
        self.assertFalse(normalized["xr12_lufs_meter_enabled"])
        self.assertEqual(normalized["xr12_lufs_threshold"], -35.5)
        self.assertEqual(normalized["xr12_lufs_hysteresis"], 0.0)
        self.assertEqual(normalized["xr12_lufs_hold_seconds"], 0.0)
        self.assertEqual(normalized["xr12_lufs_input_device"], "ALSA::Microphone")
        self.assertEqual(config["xr12_lufs_threshold"], "-35.5")
        self.assertEqual(set(normalized), set(lufs.LUFS_DEFAULTS))

    def test_invalid_values_and_old_numeric_device_indices(self):
        for invalid in (None, math.nan, math.inf, -math.inf, "bad"):
            config = {key: invalid for key in lufs.LUFS_DEFAULTS
                      if key != "xr12_lufs_input_device"}
            self.assertEqual(lufs.normalize_lufs_config(config), lufs.LUFS_DEFAULTS)
        self.assertEqual(lufs.normalize_lufs_config({
            "xr12_lufs_input_device": 3,
        })["xr12_lufs_input_device"], "")

    def test_boolean_normalization_does_not_enable_truthy_garbage(self):
        for value in ("yes", "on", "1", 1, True):
            self.assertTrue(lufs.normalize_lufs_config({
                "xr12_lufs_agc_enabled": value,
            })["xr12_lufs_agc_enabled"])
        for value in ("no", "0", "garbage", {}, [], 2):
            self.assertFalse(lufs.normalize_lufs_config({
                "xr12_lufs_agc_enabled": value,
            })["xr12_lufs_agc_enabled"])

    def test_numeric_settings_match_ui_ranges(self):
        normalized = lufs.normalize_lufs_config({
            "xr12_lufs_threshold": -100,
            "xr12_lufs_hysteresis": 100,
            "xr12_lufs_hold_seconds": 100,
        })
        self.assertEqual(normalized["xr12_lufs_threshold"], -60)
        self.assertEqual(normalized["xr12_lufs_hysteresis"], 20)
        self.assertEqual(normalized["xr12_lufs_hold_seconds"], 60)
        normalized = lufs.normalize_lufs_config({
            "xr12_lufs_threshold": 10,
            "xr12_lufs_hysteresis": -10,
            "xr12_lufs_hold_seconds": -10,
        })
        self.assertEqual(normalized["xr12_lufs_threshold"], 0)
        self.assertEqual(normalized["xr12_lufs_hysteresis"], 0)
        self.assertEqual(normalized["xr12_lufs_hold_seconds"], 0)


class AgcTests(unittest.TestCase):
    def test_strict_half_width_hysteresis_boundaries_and_duplicates(self):
        agc = lufs.LufsAgc(hold_seconds=0)
        self.assertIsNone(agc.update(-30, 0))
        self.assertIsNone(agc.update(-31, 0))
        self.assertIsNone(agc.update(-29, 0))
        self.assertEqual(agc.update(-31.001, 1), "high")
        self.assertIsNone(agc.update(-40, 2))
        self.assertIsNone(agc.update(-29, 3))
        self.assertEqual(agc.state, "high")
        self.assertEqual(agc.update(-28.999, 4), "low")
        self.assertIsNone(agc.update(-20, 5))
        self.assertIsNone(agc.update(-31, 6))
        self.assertEqual(agc.state, "low")
        self.assertEqual(agc.update(-31.001, 7), "high")

    def test_hold_is_since_last_transition_not_since_first_candidate(self):
        agc = lufs.LufsAgc()
        self.assertEqual(agc.update(-20, 10), "low")
        self.assertIsNone(agc.update(-40, 11.999))
        self.assertEqual(agc.update(-40, 12), "high")
        self.assertIsNone(agc.update(-20, 13))
        self.assertEqual(agc.update(-20, 14), "low")

    def test_invalid_readings_do_not_change_hold_or_state(self):
        agc = lufs.LufsAgc()
        self.assertEqual(agc.update(-20, 0), "low")
        for invalid in (None, math.nan, math.inf, "bad"):
            self.assertIsNone(agc.update(invalid, 1))
        for invalid_now in (None, math.nan, math.inf, "bad"):
            self.assertIsNone(agc.update(-40, invalid_now))
        self.assertEqual(agc.update(-math.inf, 2), "high")
        self.assertIsNone(agc.update(-math.inf, 3))

    def test_reset_and_backwards_clock(self):
        agc = lufs.LufsAgc()
        self.assertEqual(agc.update(-20, 10), "low")
        self.assertIsNone(agc.update(-40, 9))
        agc.reset()
        self.assertEqual(agc.update(-40, 9), "high")
        self.assertEqual(agc.update(-20, 11), "low")

    def test_manual_override_does_not_retrigger_same_state(self):
        agc = lufs.LufsAgc()
        self.assertEqual(agc.update(-20, 0), "low")
        # UI manual fader changes do not reset this instance.
        self.assertIsNone(agc.update(-20, 10))
        self.assertEqual(agc.update(-40, 11), "high")

    def test_zero_hysteresis_and_zero_hold(self):
        agc = lufs.LufsAgc(hysteresis=0, hold_seconds=0)
        self.assertIsNone(agc.update(-30, 0))
        self.assertEqual(agc.update(-29.99, 0), "low")
        self.assertIsNone(agc.update(-30, 0))
        self.assertEqual(agc.state, "low")
        self.assertEqual(agc.update(-30.01, 0), "high")


class WindowAndConversionTests(unittest.TestCase):
    def test_full_two_seconds_required_and_old_samples_roll_out(self):
        window = lufs.RollingAudioWindow(10)
        window.append(range(19))
        self.assertFalse(window.ready)
        window.append([19])
        self.assertTrue(window.ready)
        window.append(range(20, 45))
        self.assertEqual(window.values(), list(range(25, 45)))
        self.assertEqual(len(window.values()), 20)
        window.reset()
        self.assertFalse(window.ready)
        self.assertEqual(window.values(), [])

    def test_fractional_rate_rounds_up_not_shorter_than_two_seconds(self):
        self.assertEqual(lufs.RollingAudioWindow(10.1).capacity, 21)

    def test_invalid_audio_invalidates_window(self):
        window = lufs.RollingAudioWindow(1)
        window.append([0, 0])
        for invalid in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                window.append([invalid])
            self.assertFalse(window.ready)
        for rate in (0, -1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                lufs.RollingAudioWindow(rate)

    def test_rms_calibration_silence_and_full_scale(self):
        self.assertEqual(lufs.rms_lufs_estimate([0, 0]), -math.inf)
        self.assertAlmostEqual(lufs.rms_lufs_estimate([1, -1]), -0.691)
        self.assertAlmostEqual(lufs.rms_lufs_estimate([0.1, -0.1]), -20.691)
        self.assertAlmostEqual(lufs.rms_lufs_estimate([1, 0]), -3.70129995664)
        self.assertTrue(math.isfinite(lufs.rms_lufs_estimate([1e-300])))
        for data in ([], [math.nan], [math.inf]):
            with self.assertRaises(ValueError):
                lufs.rms_lufs_estimate(data)


class FakeAudio:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, key):
        if key != (slice(None), 0):
            raise AssertionError(f"Unexpected audio slice: {key}")
        return self

    def copy(self):
        return list(self.values)


class FakeStream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.options = kwargs
        self.active = False
        self.closed = False

    def start(self):
        self.active = True

    def abort(self):
        self.active = False

    def close(self):
        self.closed = True

    def feed(self, values, status=""):
        self.callback(FakeAudio(values), len(values), None, status)


class FakeBackend:
    def __init__(self):
        self.stream = None
        self.devices = [
            {"name": "Speaker", "hostapi": 0, "max_input_channels": 0,
             "default_samplerate": 10},
            {"name": "Microphone", "hostapi": 0, "max_input_channels": 1,
             "default_samplerate": 10},
        ]

    def query_hostapis(self):
        return [{"name": "Test API"}]

    def query_devices(self, device=None, kind=None):
        if kind is None:
            return self.devices
        return self.devices[1 if device is None else device]

    def InputStream(self, **kwargs):
        self.stream = FakeStream(**kwargs)
        return self.stream


class FakeNumpy:
    def asarray(self, data, dtype=None):
        return list(data)


class DeviceAndImportTests(unittest.TestCase):
    def test_device_identifiers_are_stable_when_indices_change(self):
        backend = FakeBackend()
        expected = [("Test API::Microphone", "Microphone (Test API)")]
        self.assertEqual(lufs.list_input_devices(backend)[0], expected)
        backend.devices.reverse()
        self.assertEqual(lufs.list_input_devices(backend)[0], expected)

    def test_list_failures_and_missing_optional_import_are_nonfatal(self):
        with patch.object(lufs.importlib, "import_module", side_effect=ImportError("missing")):
            devices, status = lufs.list_input_devices()
        self.assertEqual(devices, [])
        self.assertIn("missing", status)
        backend = FakeBackend()
        with patch.object(backend, "query_devices", side_effect=RuntimeError("unplugged")):
            self.assertIn("unplugged", lufs.list_input_devices(backend)[1])
        backend.devices = []
        self.assertEqual(lufs.list_input_devices(backend), ([], "No audio input devices"))

    def test_importing_module_does_not_attempt_optional_imports(self):
        spec = importlib.util.spec_from_file_location("isolated_lufs", lufs.__file__)
        module = importlib.util.module_from_spec(spec)
        with patch.object(lufs.importlib, "import_module", side_effect=ImportError("missing")):
            spec.loader.exec_module(module)
            self.assertEqual(module.LufsAgc().update(-math.inf, 0), "high")


class WorkerTests(unittest.TestCase):
    def wait_for(self, predicate, timeout=1.5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Timed out waiting for audio worker")

    def make_worker(self, device="", loudness_module=None, **kwargs):
        backend = FakeBackend()
        worker = lufs.AudioLoudnessWorker(
            device, backend=backend, numpy_module=FakeNumpy(),
            loudness_module=loudness_module, **kwargs,
        )
        self.addCleanup(worker.stop)
        worker.start()
        self.wait_for(lambda: backend.stream is not None and backend.stream.active)
        return worker, backend

    def feed(self, worker, backend, values, status=""):
        backend.stream.feed(values, status)
        self.wait_for(lambda: worker._queue.empty())

    def test_no_reading_before_full_window_then_calibrated_fallback(self):
        worker, backend = self.make_worker()
        self.feed(worker, backend, [0.1] * 19)
        self.assertIsNone(worker.snapshot()[0])
        self.assertFalse(worker.snapshot()[2])
        self.feed(worker, backend, [0.1])
        self.wait_for(lambda: worker.snapshot()[2])
        value, status, ready = worker.snapshot()
        self.assertAlmostEqual(value, -20.691)
        self.assertTrue(ready)
        self.assertIn("Estimated LUFS", status)
        self.assertIn("0.691", status)
        self.assertEqual(backend.stream.options["channels"], 1)

    def test_true_lufs_preferred_and_analysis_is_off_calling_thread(self):
        threads = []
        windows = []

        class Meter:
            def __init__(self, rate):
                self.rate = rate

            def integrated_loudness(self, data):
                threads.append(threading.get_ident())
                windows.append(data)
                return -24.5

        worker, backend = self.make_worker(loudness_module=SimpleNamespace(Meter=Meter))
        self.feed(worker, backend, [0.1] * 20)
        self.wait_for(lambda: worker.snapshot()[2])
        self.assertEqual(worker.snapshot(), (-24.5, "LUFS (pyloudnorm)", True))
        self.assertEqual(len(windows[0]), 20)
        self.assertNotEqual(threads[0], threading.get_ident())
        self.feed(worker, backend, [0.2] * 20)
        self.assertEqual(len(windows), 1)  # Not faster than 5Hz.
        time.sleep(0.21)
        self.feed(worker, backend, [0.2])
        self.wait_for(lambda: len(windows) == 2)

    def test_silence_is_a_ready_negative_infinity(self):
        worker, backend = self.make_worker()
        self.feed(worker, backend, [0] * 20)
        self.wait_for(lambda: worker.snapshot()[2])
        self.assertEqual(worker.snapshot()[0], -math.inf)

    def test_overflow_invalidates_immediately_and_requires_new_full_window(self):
        worker, backend = self.make_worker()
        self.feed(worker, backend, [0.1] * 20)
        self.wait_for(lambda: worker.snapshot()[2])
        backend.stream.feed([0.1], "input overflow")
        self.assertFalse(worker.snapshot()[2])
        self.assertIsNone(worker.snapshot()[0])
        self.wait_for(lambda: worker._queue.empty())
        self.feed(worker, backend, [0.1] * 19)
        self.assertFalse(worker.snapshot()[2])
        time.sleep(0.21)
        self.feed(worker, backend, [0.1])
        self.wait_for(lambda: worker.snapshot()[2])

    def test_stall_invalidates_and_recovery_requires_new_window(self):
        worker, backend = self.make_worker()
        worker.STALE_SECONDS = 0.15
        self.feed(worker, backend, [0.1] * 20)
        self.wait_for(lambda: worker.snapshot()[2])
        self.wait_for(lambda: not worker.snapshot()[2])
        self.assertIsNone(worker.snapshot()[0])
        self.assertIn("stalled", worker.snapshot()[1])
        self.feed(worker, backend, [0.1])
        self.assertFalse(worker.snapshot()[2])
        self.feed(worker, backend, [0.1] * 19)
        self.wait_for(lambda: worker.snapshot()[2])

    def test_disconnect_invalidates_and_closes_stream(self):
        worker, backend = self.make_worker()
        self.feed(worker, backend, [0.1] * 20)
        self.wait_for(lambda: worker.snapshot()[2])
        backend.stream.active = False
        self.wait_for(lambda: not worker.snapshot()[2])
        self.assertIn("disconnected", worker.snapshot()[1])
        self.wait_for(lambda: backend.stream.closed)

    def test_open_failure_is_visible_and_no_snapshot_is_ready(self):
        backend = FakeBackend()
        worker = lufs.AudioLoudnessWorker(
            backend=backend, numpy_module=FakeNumpy(), loudness_module=None,
        )
        self.addCleanup(worker.stop)
        with patch.object(backend, "InputStream", side_effect=RuntimeError("device busy")):
            worker.start()
            self.wait_for(lambda: "device busy" in worker.snapshot()[1])
        self.assertIsNone(worker.snapshot()[0])
        self.assertFalse(worker.snapshot()[2])

    def test_ambiguous_device_is_not_silently_selected(self):
        backend = FakeBackend()
        backend.devices.append(dict(backend.devices[1]))
        worker = lufs.AudioLoudnessWorker(
            "Test API::Microphone", backend=backend, numpy_module=FakeNumpy(),
            loudness_module=None,
        )
        self.addCleanup(worker.stop)
        worker.start()
        self.wait_for(lambda: "ambiguous" in worker.snapshot()[1])
        self.assertIsNone(backend.stream)
        self.assertEqual(len(lufs.list_input_devices(backend)[0]), 1)

    def test_device_missing_does_not_fall_back_to_default(self):
        backend = FakeBackend()
        worker = lufs.AudioLoudnessWorker(
            "Test API::Removed", backend=backend, numpy_module=FakeNumpy(),
            loudness_module=None,
        )
        self.addCleanup(worker.stop)
        worker.start()
        self.wait_for(lambda: "missing" in worker.snapshot()[1])
        self.assertEqual(worker.snapshot()[0], None)
        self.assertFalse(worker.snapshot()[2])
        self.assertIsNone(backend.stream)

    def test_stable_device_is_resolved_at_start_not_saved_as_index(self):
        worker, backend = self.make_worker("Test API::Microphone")
        self.assertEqual(backend.stream.options["device"], 1)
        worker.stop()
        backend.devices.reverse()
        worker.start()
        self.wait_for(lambda: backend.stream.active)
        self.assertEqual(backend.stream.options["device"], 0)

    def test_missing_required_packages_fail_visible_not_fatal(self):
        for missing in ("sounddevice", "numpy"):
            with self.subTest(missing=missing):
                backend = None if missing == "sounddevice" else FakeBackend()
                worker = lufs.AudioLoudnessWorker(backend=backend)
                with patch.object(lufs.importlib, "import_module",
                                  side_effect=ImportError(f"No module named {missing}")):
                    worker.start()
                    self.wait_for(lambda: "unavailable" in worker.snapshot()[1])
                    self.assertIn(missing, worker.snapshot()[1])
                    self.assertFalse(worker.snapshot()[2])
                worker.stop()

    def test_missing_pyloudnorm_explicitly_reports_fallback(self):
        backend = FakeBackend()
        worker = lufs.AudioLoudnessWorker(backend=backend, numpy_module=FakeNumpy())
        self.addCleanup(worker.stop)
        with patch.object(lufs.importlib, "import_module",
                          side_effect=ImportError("No module named pyloudnorm")):
            worker.start()
            self.wait_for(lambda: backend.stream is not None and backend.stream.active)
            self.feed(worker, backend, [0.1] * 20)
            self.wait_for(lambda: worker.snapshot()[2])
        self.assertIn("pyloudnorm unavailable", worker.snapshot()[1])
        self.assertAlmostEqual(worker.snapshot()[0], -20.691)

    def test_pyloudnorm_constructor_failure_explicitly_reports_fallback(self):
        class Meter:
            def __init__(self, rate):
                raise RuntimeError("incompatible version")

        worker, backend = self.make_worker(loudness_module=SimpleNamespace(Meter=Meter))
        self.feed(worker, backend, [0.1] * 20)
        self.wait_for(lambda: worker.snapshot()[2])
        self.assertIn("pyloudnorm initialization failed", worker.snapshot()[1])
        self.assertIn("incompatible version", worker.snapshot()[1])
        self.assertAlmostEqual(worker.snapshot()[0], -20.691)

    def test_analyzer_failure_invalidates_previous_reading(self):
        class Meter:
            def __init__(self, rate):
                self.calls = 0

            def integrated_loudness(self, data):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("analysis failed")
                return -24

        worker, backend = self.make_worker(loudness_module=SimpleNamespace(Meter=Meter))
        self.feed(worker, backend, [0.1] * 20)
        self.wait_for(lambda: worker.snapshot()[2])
        time.sleep(0.21)
        self.feed(worker, backend, [0.1])
        self.wait_for(lambda: "analysis failed" in worker.snapshot()[1])
        self.assertIsNone(worker.snapshot()[0])
        self.assertFalse(worker.snapshot()[2])

    def test_invalid_audio_and_invalid_analyzer_results(self):
        worker, backend = self.make_worker()
        self.feed(worker, backend, [math.nan])
        self.wait_for(lambda: "non-finite" in worker.snapshot()[1])
        self.assertFalse(worker.snapshot()[2])
        for invalid in (math.nan, math.inf, None):
            with self.subTest(invalid=invalid):
                class Meter:
                    def __init__(self, rate):
                        pass

                    def integrated_loudness(self, data):
                        return invalid

                worker, backend = self.make_worker(
                    loudness_module=SimpleNamespace(Meter=Meter))
                self.feed(worker, backend, [0.1] * 20)
                self.wait_for(lambda: "invalid reading" in worker.snapshot()[1])
                self.assertFalse(worker.snapshot()[2])
                worker.stop()

    def test_stop_closes_and_joins_and_start_is_idempotent(self):
        worker, backend = self.make_worker()
        thread = worker._thread
        worker.start()
        self.assertIs(worker._thread, thread)
        worker.stop()
        self.assertFalse(thread.is_alive())
        self.assertTrue(backend.stream.closed)
        self.assertEqual(worker.snapshot(), (None, "Stopped", False))
        worker.stop()
        self.assertEqual(worker.snapshot(), (None, "Stopped", False))

    def test_hung_analysis_does_not_block_snapshot_or_stop(self):
        release = threading.Event()
        analyzing = threading.Event()

        class Meter:
            def __init__(self, rate):
                pass

            def integrated_loudness(self, data):
                analyzing.set()
                release.wait(2)
                return -24

        worker, backend = self.make_worker(loudness_module=SimpleNamespace(Meter=Meter))
        self.addCleanup(release.set)
        worker.STALE_SECONDS = 0.1
        self.feed(worker, backend, [0.1] * 20)
        self.assertTrue(analyzing.wait(0.5))
        time.sleep(0.12)
        self.assertEqual(worker.snapshot()[0], None)
        self.assertIn("stalled", worker.snapshot()[1])
        started = time.monotonic()
        worker.stop()
        self.assertLess(time.monotonic() - started, 0.35)
        self.assertEqual(worker.snapshot(), (None, "Stopped", False))
        release.set()
        self.wait_for(lambda: not worker._thread.is_alive())
        self.assertTrue(backend.stream.closed)

    def test_capture_queue_is_bounded_and_overflow_is_immediately_invalid(self):
        release = threading.Event()
        analyzing = threading.Event()

        class Meter:
            def __init__(self, rate):
                pass

            def integrated_loudness(self, data):
                analyzing.set()
                release.wait(2)
                return -24

        worker, backend = self.make_worker(loudness_module=SimpleNamespace(Meter=Meter))
        self.addCleanup(release.set)
        self.feed(worker, backend, [0.1] * 20)
        self.assertTrue(analyzing.wait(0.5))
        for _ in range(20):
            backend.stream.feed([0.1])
        self.assertEqual(worker._queue.qsize(), worker._queue.maxsize)
        self.assertIn("queue overflow", worker.snapshot()[1])
        self.assertFalse(worker.snapshot()[2])
        self.assertIsNone(worker.snapshot()[0])
        release.set()
        self.wait_for(lambda: worker._queue.empty())
        self.assertFalse(worker.snapshot()[2])


if __name__ == "__main__":
    unittest.main()
