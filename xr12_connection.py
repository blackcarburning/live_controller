"""Bound XR12 MIDI connection attempts without blocking the application's UI."""

import threading
import time


class Xr12ConnectionAttempt:
    def __init__(self, operation, dispose, timeout_seconds=15.0):
        self._dispose = dispose
        self._deadline = time.monotonic() + timeout_seconds
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._cancelled = False
        self._result = None
        self._error = None
        self._done = False
        threading.Thread(target=self._run, args=(operation,), daemon=True).start()

    def _run(self, operation):
        result = None
        error = None
        try:
            result = operation()
        except Exception as exc:
            error = exc
        with self._lock:
            if not self._cancelled:
                self._result = result
                self._error = error
                self._done = True
                return
        if result is not None:
            self._dispose_result(result)

    def poll(self):
        """Return (finished, result, error), transferring ownership on success."""
        with self._lock:
            if time.monotonic() < self._deadline:
                if not self._done:
                    return False, None, None
                result, error = self._result, self._error
                self._result = None
                self._cancelled = True
                return True, result, error
        self.cancel()
        return True, None, TimeoutError(
            f"XR12 connection timed out after {self._timeout_seconds:g} seconds"
        )

    def cancel(self):
        with self._lock:
            self._cancelled = True
            result = self._result
            self._result = None
        if result is not None:
            # Native close calls can also block when a device has disappeared.
            threading.Thread(target=self._dispose_result, args=(result,), daemon=True).start()

    def _dispose_result(self, result):
        try:
            self._dispose(result)
        except Exception as exc:
            print(f"XR12 connection cleanup failed: {exc}")
