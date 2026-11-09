"""Pure-Python protocol/race tests for extracted native IPC implementation.

No DLL loads and no real threads: a Python fake models all Win32 calls.
Parent separately owns genuine Windows pipe test verify_windows_pipe_transport.py.
"""
from __future__ import annotations

import ctypes
import json
import types
import unittest

try:
    from .test_two_display_support import ExtractedSource
    from . import test_two_display_runtime as runtime
except ImportError:
    from test_two_display_support import ExtractedSource
    import test_two_display_runtime as runtime


class StrictNativeIpcTests(unittest.TestCase):
    fixture = runtime.BoundedIpcTests.fixture

    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()

    def scripted(self, chunks, *, request_id=123):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture()
        ns["uuid"] = types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(int=request_id))
        queue = list(chunks)
        def read(handle, buffer, length, amount, overlapped):
            kernel.requests.append("read")
            data = queue.pop(0) if queue else b""
            if callable(data):
                data = data(kernel.payload["request_id"])
            if isinstance(data, str): data = data.encode("utf-8")
            if len(data) > length:
                raise AssertionError("fixture chunk exceeds read buffer")
            ctypes.memmove(buffer, data, len(data))
            amount._obj.value = len(data)
            clock.value += 0.002
            return True
        kernel.ReadFile = read
        return ns, pipe, kernel, clock, cancel, deferred

    @staticmethod
    def line(reply):
        return (json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8")

    def test_non_object_json_does_not_abort_before_own_valid_reply(self):
        for bad in (None, [], 7, "string", True):
            with self.subTest(kind=type(bad).__name__):
                raw = self.line(bad) + self.line({"request_id":123, "error":"success", "data":4.25})
                ns, pipe, kernel, clock, cancel, deferred = self.scripted([raw])
                result = pipe.request("OFFLINE-PIPE", ["get_property", "time-pos"])
                self.assertIs(result["ok"], True)
                self.assertEqual(result["data"], 4.25)

    def test_request_id_requires_integer_not_bool_float_string_or_null(self):
        for bad, own in ((True,1), (123.0,123), ("123",123), (None,123)):
            with self.subTest(kind=type(bad).__name__):
                raw = self.line({"request_id":bad, "error":"success", "data":"WRONG"})
                raw += self.line({"request_id":own, "error":"success", "data":"CORRECT"})
                ns, pipe, kernel, clock, cancel, deferred = self.scripted([raw], request_id=own)
                result = pipe.request("OFFLINE-PIPE", ["get_property", "time-pos"])
                self.assertIs(result["ok"], True)
                self.assertEqual(result["data"], "CORRECT", "Python equality must not correlate bool/float IDs")

    def test_error_status_must_be_exact_success_not_truthy(self):
        for value in (True, 1, None, "Success", "", {"success":True}):
            with self.subTest(status=repr(value)):
                ns, pipe, kernel, clock, cancel, deferred = self.scripted([
                    self.line({"request_id":123,"error":value,"data":5.0})])
                result = pipe.request("OFFLINE-PIPE", ["get_property", "time-pos"])
                self.assertIs(result["ok"], False)
                self.assertNotIn("OFFLINE", result["error"])

    def test_chunked_unicode_and_events_are_buffered_until_own_reply(self):
        raw = self.line({"event":"property-change", "data":"Ω display"})
        raw += self.line({"request_id":999,"error":"success","data":"wrong"})
        raw += self.line({"request_id":123,"error":"success","data":"Ω 正确"})
        split = raw.index("Ω".encode()) + 1
        chunks = [raw[:split],raw[split:split+1],raw[split+1:split+7],raw[split+7:]]
        ns, pipe, kernel, clock, cancel, deferred = self.scripted(chunks)
        result = pipe.request("OFFLINE-PIPE", ["get_property", "media-title"])
        self.assertIs(result["ok"], True)
        self.assertEqual(result["data"], "Ω 正确")
        self.assertEqual(kernel.requests.count("read"), len(chunks))
        self.assertEqual(kernel.closed.count(101), 1)

    def test_invalid_utf8_line_ignored_without_damaging_next_reply(self):
        raw = b"\xff\xfe\n" + self.line({"request_id":123,"error":"success","data":0.0})
        ns, pipe, kernel, clock, cancel, deferred = self.scripted([raw])
        result = pipe.request("OFFLINE-PIPE", ["get_property", "time-pos"])
        self.assertIs(result["ok"], True)
        self.assertEqual(result["data"], 0.0)

    def test_reply_size_limit_is_bounded_and_sanitized(self):
        ns, pipe, kernel, clock, cancel, deferred = self.scripted([b"x"*16384]*5)
        result = pipe.request("OFFLINE-PIPE", ["get_property", "time-pos"], timeout=0.2)
        self.assertIs(result["ok"], False)
        self.assertLessEqual(kernel.requests.count("read"), 5)
        self.assertLess(len(result["error"]), 120)
        self.assertEqual(kernel.closed.count(101), 1)

    def test_partial_writes_resume_exact_payload_before_any_read(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture()
        original_read = kernel.ReadFile
        payload = bytearray()
        writes, reads = [], []
        def short_write(handle, buffer, length, amount, overlapped):
            accepted = min(7,length)
            payload.extend(buffer.raw[:accepted])
            amount._obj.value = accepted
            writes.append((length,accepted))
            if payload.endswith(b"\n"):
                kernel.payload = json.loads(payload.decode("utf-8"))
            return True
        def read(*args):
            self.assertTrue(payload.endswith(b"\n"),"Read began before all request bytes were written")
            reads.append(True)
            return original_read(*args)
        kernel.WriteFile, kernel.ReadFile = short_write,read
        result = pipe.request("OFFLINE-PIPE",["get_property","time-pos"])
        self.assertIs(result["ok"],True)
        self.assertGreater(len(writes),1)
        self.assertEqual(reads,[True])
        self.assertEqual(json.loads(payload)["command"],["get_property","time-pos"])
        self.assertEqual(kernel.closed.count(101),1)
        self.assertEqual(pipe._inflight,0)

    def test_zero_length_write_fails_without_read_or_leaked_reservation(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture()
        reads=[]
        def zero_write(handle,buffer,length,amount,overlapped):
            amount._obj.value=0
            return True
        kernel.WriteFile=zero_write
        kernel.ReadFile=lambda *args:reads.append(args) or True
        result=pipe.request("OFFLINE-PIPE",["quit"])
        self.assertIs(result["ok"],False)
        self.assertEqual(reads,[])
        self.assertEqual(kernel.closed.count(101),1)
        self.assertEqual(pipe._inflight,0)

    def test_invalid_timeout_releases_atomic_admission_reservation(self):
        ns,pipe,kernel,clock,cancel,deferred=self.fixture()
        result=pipe.request("OFFLINE-PIPE",["quit"],timeout="invalid")
        self.assertIs(result["ok"],False)
        self.assertEqual(pipe._inflight,0)
        self.assertFalse(kernel.requests)

    def test_cancel_after_write_cannot_dispatch_another_native_read(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture()
        original_write, original_read = kernel.WriteFile, kernel.ReadFile
        reads = []
        def write(*args):
            result = original_write(*args)
            cancel.set()
            return result
        def read(*args):
            reads.append(True)
            return original_read(*args)
        kernel.WriteFile, kernel.ReadFile = write, read
        result = pipe.request("OFFLINE-PIPE", ["get_property","time-pos"], cancel=cancel)
        self.assertIs(result["ok"], False)
        self.assertEqual(reads, [], "cancellation must be rechecked before each native dispatch")
        self.assertIn("cancel", result["error"])

    def test_pointer_sized_high_bit_handle_is_not_truncated(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture()
        high = (1 << 47) + 101
        kernel.CreateFileW = lambda *args: high
        result = pipe.request("OFFLINE-PIPE", ["get_property","time-pos"])
        self.assertIs(result["ok"], True)
        self.assertEqual(kernel.closed.count(high), 1)
        self.assertNotIn(101, kernel.closed)

    def test_capacity_is_reserved_before_reentrant_concurrent_admission(self):
        # Deterministic interleaving, not real threads: the second request enters
        # while the first is in native dispatch. Admission must already be owned.
        ns, pipe, kernel, clock, cancel, deferred = self.fixture("pending")
        pipe._MAX_PENDING = 1
        pipe._pending = []
        pipe._defer = classmethod(lambda cls, state: (cls._pending.append(state), deferred.append(state)))
        original = kernel.ReadFile
        nested = []
        def read(*args):
            if not nested:
                nested.append("entered")
                nested.append(pipe.request("OFFLINE-SECOND", ["get_property","time-pos"], timeout=0.01))
            return original(*args)
        kernel.ReadFile = read
        result = pipe.request("OFFLINE-FIRST", ["get_property","time-pos"], timeout=0.03)
        self.assertIs(result["ok"], False)
        self.assertEqual(len(nested), 2)
        self.assertIs(nested[1]["ok"], False)
        self.assertIn("backlog", nested[1]["error"], "check-then-append cannot bound concurrent native owners")
        self.assertLessEqual(len(pipe._pending), pipe._MAX_PENDING)

    def test_signaled_event_is_not_proof_native_operation_completed(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture("pending")
        # A stale/signaled event plus ERROR_IO_INCOMPLETE must retain ownership.
        kernel.WaitForSingleObject = lambda *args: 0
        def incomplete(handle, overlapped, amount, wait):
            self.assertFalse(wait, "native completion check must never block")
            kernel.error = 996  # ERROR_IO_INCOMPLETE
            kernel.get_results += 1
            return False
        kernel.GetOverlappedResult = incomplete
        result = pipe.request("OFFLINE-PIPE", ["get_property","time-pos"], timeout=0.02)
        self.assertIs(result["ok"], False)
        self.assertEqual(len(deferred), 1, "incomplete native operation must own live buffers after return")
        self.assertNotIn(101, kernel.closed)

    def test_reaper_verifies_completion_before_freeing_late_cancel_buffers(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture("pending")
        pipe.request("OFFLINE-PIPE", ["get_property","time-pos"], timeout=0.01)
        self.assertEqual(len(deferred), 1)
        pipe._pending = [deferred[0]]
        pipe._reaper_running = True
        complete = [False]
        checks = []
        sleeps = []
        kernel.WaitForSingleObject = lambda *args: 0
        def completion(handle, overlapped, amount, wait):
            self.assertFalse(wait)
            checks.append(complete[0])
            kernel.error = 995 if complete[0] else 996  # aborted is terminal, incomplete is not
            return False
        kernel.GetOverlappedResult = completion
        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                self.assertNotIn(101, kernel.closed,
                                 "event state alone cannot free OVERLAPPED/buffer/handle")
                complete[0] = True
            elif len(sleeps) > 3:
                raise AssertionError("test reaper failed to terminate after real completion")
        clock.sleep = sleep
        pipe._reap()
        self.assertTrue(checks)
        self.assertEqual(kernel.closed.count(101), 1)
        self.assertEqual(pipe._pending, [])


if __name__ == "__main__":
    unittest.main()
