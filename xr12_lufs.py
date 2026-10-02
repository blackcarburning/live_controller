"""Optional microphone loudness metering and pure XR12 AGC decisions.

No audio packages are imported until metering or device enumeration is requested.
The fallback is an *estimate*: mono RMS dBFS minus 0.691 dB, the BS.1770
calibration offset. It does not apply K-weighting or gating and is not true LUFS.
"""

import importlib
import math
import queue
import threading
import time
from collections import deque


LUFS_DEFAULTS = {
    "xr12_lufs_agc_enabled": False,
    "xr12_lufs_meter_enabled": False,
    "xr12_lufs_threshold": -30.0,
    "xr12_lufs_hysteresis": 2.0,
    "xr12_lufs_hold_seconds": 2.0,
    "xr12_lufs_input_device": "",
}


def _finite_float(value, default):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _enabled(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return value is True or (isinstance(value, (int, float)) and value == 1)


def normalize_lufs_config(config):
    """Return only LUFS keys; legacy configs remain disabled by default.

    Numeric device indices are deliberately not migrated: their meaning changes
    when devices are added, removed, or enumerated in a different order.
    """
    config = config if isinstance(config, dict) else {}
    result = dict(LUFS_DEFAULTS)
    for key in ("xr12_lufs_agc_enabled", "xr12_lufs_meter_enabled"):
        result[key] = _enabled(config.get(key, result[key]))
    for key in ("xr12_lufs_threshold", "xr12_lufs_hysteresis",
                "xr12_lufs_hold_seconds"):
        result[key] = _finite_float(config.get(key, result[key]), result[key])
    result["xr12_lufs_threshold"] = max(-60.0, min(0.0, result["xr12_lufs_threshold"]))
    result["xr12_lufs_hysteresis"] = max(0.0, min(20.0, result["xr12_lufs_hysteresis"]))
    result["xr12_lufs_hold_seconds"] = max(0.0, min(60.0, result["xr12_lufs_hold_seconds"]))
    device = config.get("xr12_lufs_input_device", "")
    result["xr12_lufs_input_device"] = device.strip() if isinstance(device, str) else ""
    return result


def _valid_loudness(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if not math.isnan(value) and value != math.inf else None


class LufsAgc:
    """Emit edge-triggered fader high/low outside a full-width hysteresis band.

    Quiet opens (high); loud closes (low). Exact band boundaries retain state.
    Hold is the minimum time since the last emitted
    transition, not a requirement for consecutive above/below-band readings.
    """

    def __init__(self, threshold=-30, hysteresis=2, hold_seconds=2):
        config = normalize_lufs_config({
            "xr12_lufs_threshold": threshold,
            "xr12_lufs_hysteresis": hysteresis,
            "xr12_lufs_hold_seconds": hold_seconds,
        })
        self.threshold = config["xr12_lufs_threshold"]
        self.hysteresis = config["xr12_lufs_hysteresis"]
        self.hold_seconds = config["xr12_lufs_hold_seconds"]
        self.reset()

    def reset(self):
        self.state = None
        self.last_transition = None

    def update(self, value, now):
        value = _valid_loudness(value)
        now = _finite_float(now, None)
        if value is None or now is None:
            return None
        if value < self.threshold - self.hysteresis / 2:
            state = "high"
        elif value > self.threshold + self.hysteresis / 2:
            state = "low"
        else:
            return None
        if state == self.state:
            return None
        if (self.last_transition is not None
                and now - self.last_transition < self.hold_seconds):
            return None
        self.state = state
        self.last_transition = now
        return state


class RollingAudioWindow:
    """A bounded, pure-Python mono sample window, invalid until a full 2s."""

    def __init__(self, sample_rate, seconds=2.0):
        sample_rate = float(sample_rate)
        seconds = float(seconds)
        if not math.isfinite(sample_rate) or sample_rate <= 0:
            raise ValueError("Sample rate must be positive and finite")
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Window duration must be positive and finite")
        self.capacity = max(1, math.ceil(sample_rate * seconds))
        self._samples = deque(maxlen=self.capacity)

    @property
    def ready(self):
        return len(self._samples) == self.capacity

    def reset(self):
        self._samples.clear()

    def append(self, samples):
        samples = [float(sample) for sample in samples]
        if not all(math.isfinite(sample) for sample in samples):
            self.reset()
            raise ValueError("Audio contains non-finite samples")
        self._samples.extend(samples)

    def values(self):
        return list(self._samples)


def rms_lufs_estimate(samples):
    """Estimate mono LUFS as RMS dBFS - 0.691, without weighting or gating."""
    samples = [float(sample) for sample in samples]
    if not samples or not all(math.isfinite(sample) for sample in samples):
        raise ValueError("Expected finite audio samples")
    peak = max(abs(sample) for sample in samples)
    if peak == 0:
        return -math.inf
    power = sum((sample / peak) ** 2 for sample in samples) / len(samples)
    return 20 * math.log10(peak) + 10 * math.log10(power) - 0.691


def _device_entries(backend):
    hostapis = backend.query_hostapis()
    entries = []
    for index, device in enumerate(backend.query_devices()):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        host = hostapis[int(device["hostapi"])]["name"]
        name = device["name"]
        stable_id = f"{host}::{name}"
        entries.append((stable_id, f"{name} ({host})", index))
    return entries


def list_input_devices(backend=None):
    """Return stable (host API/name) identifiers; failures never escape to UI."""
    try:
        backend = backend if backend is not None else importlib.import_module("sounddevice")
        entries = _device_entries(backend)
        # Identical host/name pairs cannot safely be distinguished across boots.
        devices = list(dict.fromkeys((key, display) for key, display, _ in entries))
        return devices, "Audio inputs available" if devices else "No audio input devices"
    except Exception as exc:
        return [], f"Audio inputs unavailable: {exc}"


_AUTO = object()


class AudioLoudnessWorker:
    """Callback capture plus 5Hz analysis, with no UI-thread audio operations.

    Capture is mono (the input's first channel). A discontinuity requires a fresh
    two-second window. Snapshot expires after 0.75s without capture/analysis, even
    if the driver or analyzer hangs. Backend/module injection supports headless
    tests; production callers need only the stable ``device`` identifier.
    """

    ANALYSIS_INTERVAL = 0.2
    STALE_SECONDS = 0.75
    JOIN_SECONDS = 0.2

    def __init__(self, device="", *, backend=None, numpy_module=None,
                 loudness_module=_AUTO):
        self.device = device
        self._backend = backend
        self._numpy = numpy_module
        self._loudness = loudness_module
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._queue = queue.Queue(maxsize=8)
        self._thread = None
        self._value = None
        self._status = "Stopped"
        self._ready = False
        self._updated = None
        self._last_capture = None
        self._generation = 0

    def _invalidate(self, status):
        with self._lock:
            self._generation += 1
            self._value = None
            self._status = "Stopped" if self._stop.is_set() else status
            self._ready = False
            self._updated = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._queue = queue.Queue(maxsize=8)
        with self._lock:
            self._last_capture = None
        self._invalidate("Starting audio")
        self._thread = threading.Thread(target=self._run, name="xr12-lufs", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._invalidate("Stopped")
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(self.JOIN_SECONDS)

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
            stale_capture = (self._last_capture is not None
                             and now - self._last_capture > self.STALE_SECONDS)
            stale_analysis = (self._updated is not None
                              and now - self._updated > self.STALE_SECONDS)
            if not self._stop.is_set() and (stale_capture or stale_analysis):
                self._generation += 1
                self._value = None
                self._ready = False
                self._updated = None
                self._status = "Audio capture/analysis stalled"
            return self._value, self._status, self._ready

    def _audio_callback(self, indata, frames, timing, status):
        if self._stop.is_set():
            return
        if status:
            self._invalidate(f"Audio discontinuity: {status}")
            return
        try:
            samples = indata[:, 0].copy()
            if len(samples) != frames:
                raise ValueError("Incomplete audio block")
            with self._lock:
                self._last_capture = time.monotonic()
                generation = self._generation
                captured = self._last_capture
            self._queue.put_nowait((generation, captured, samples))
        except queue.Full:
            self._invalidate("Audio discontinuity: capture queue overflow")
        except Exception as exc:
            self._invalidate(f"Audio capture error: {exc}")

    def _run(self):
        stream = None
        try:
            backend = self._backend
            if backend is None:
                backend = importlib.import_module("sounddevice")
            numpy = self._numpy
            if numpy is None:
                numpy = importlib.import_module("numpy")
            loudness = self._loudness
            fallback = ""
            if loudness is _AUTO:
                try:
                    loudness = importlib.import_module("pyloudnorm")
                except Exception as exc:
                    loudness = None
                    fallback = f"; pyloudnorm unavailable: {exc}"
            device_index = None
            if self.device:
                matches = [index for key, _, index in _device_entries(backend)
                           if key == self.device]
                if len(matches) != 1:
                    raise ValueError(f"Input device missing or ambiguous: {self.device}")
                device_index = matches[0]
            info = backend.query_devices(device_index, "input")
            sample_rate = float(info["default_samplerate"])
            if int(info.get("max_input_channels", 0)) < 1:
                raise ValueError("Selected device has no input channels")
            window = RollingAudioWindow(sample_rate)
            meter = None
            if loudness is not None:
                try:
                    meter = loudness.Meter(sample_rate)
                except Exception as exc:
                    fallback = f"; pyloudnorm initialization failed: {exc}"
            description = ("LUFS (pyloudnorm)" if meter is not None else
                           "Estimated LUFS (RMS dBFS - 0.691; no K-weighting/gating)"
                           + fallback)
            self._invalidate(f"Warming up (2.0s): {description}")
            with self._lock:
                generation = self._generation
                self._last_capture = time.monotonic()
            stream = backend.InputStream(
                device=device_index, samplerate=sample_rate, channels=1,
                dtype="float32", blocksize=max(1, round(sample_rate * 0.1)),
                callback=self._audio_callback,
            )
            stream.start()
            next_analysis = time.monotonic()
            previous_capture = None
            while not self._stop.is_set():
                if hasattr(stream, "active") and not stream.active:
                    raise RuntimeError("Audio input disconnected")
                try:
                    block_generation, captured, samples = self._queue.get(timeout=0.1)
                except queue.Empty:
                    with self._lock:
                        last_capture = self._last_capture
                    if time.monotonic() - last_capture > self.STALE_SECONDS:
                        self._invalidate("Audio capture stalled")
                        window.reset()
                        previous_capture = None
                        next_analysis = time.monotonic()
                    continue
                with self._lock:
                    current_generation = self._generation
                if generation != current_generation:
                    window.reset()
                    generation = current_generation
                    previous_capture = None
                    next_analysis = time.monotonic()
                if block_generation != generation:
                    continue
                if (time.monotonic() - captured > self.STALE_SECONDS
                        or (previous_capture is not None
                            and captured - previous_capture > self.STALE_SECONDS)):
                    self._invalidate("Audio discontinuity: delayed capture")
                    window.reset()
                    previous_capture = None
                    continue
                previous_capture = captured
                window.append(samples)
                now = time.monotonic()
                if not window.ready or now < next_analysis:
                    continue
                next_analysis = now + self.ANALYSIS_INTERVAL
                data = window.values()
                value = (meter.integrated_loudness(numpy.asarray(data, dtype=float))
                         if meter is not None else rms_lufs_estimate(data))
                value = _valid_loudness(value)
                if value is None:
                    raise ValueError("Loudness analysis returned an invalid reading")
                with self._lock:
                    if (not self._stop.is_set() and generation == self._generation
                            and time.monotonic() - captured <= self.STALE_SECONDS):
                        self._value = value
                        self._status = description
                        self._ready = True
                        self._updated = time.monotonic()
        except Exception as exc:
            if not self._stop.is_set():
                self._invalidate(f"Audio unavailable: {exc}")
                with self._lock:
                    self._last_capture = None
        finally:
            if stream is not None:
                for method in ("abort", "close"):
                    try:
                        getattr(stream, method)()
                    except Exception as exc:
                        if not self._stop.is_set():
                            self._invalidate(f"Audio shutdown error: {exc}")
