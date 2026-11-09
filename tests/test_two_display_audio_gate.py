"""Exact baseline audio/MIDI gates; AST extraction only, never app imports.

The only removable additions inside the pinned timing try are the exact
nonblocking attach_master handoffs immediately after the two existing Popen
sites.  No constants, calls, branches or clock expressions are normalized.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import io
import json
import types
import unittest

try:
    from .test_two_display_support import (
        BASELINE, ExtractedSource, FakeMidiOut, FakeProcess, ast_dump, forbid,
    )
except ImportError:
    from test_two_display_support import (
        BASELINE, ExtractedSource, FakeMidiOut, FakeProcess, ast_dump, forbid,
    )


PINS = {
    "run": "40f37a42fd73509ac9ecb44a22e31500b0915d2194da46a9a7d367720c0cb110",
    "run_standard": "c2704ce27528f5145e5c824767764706d5dd902121f29f1bca463bbfa818db28",
    "run_high_precision": "ec543fb5a0a8acc1009000bbbcb490caa757b89c4cf59463d09fe7d0150ce64f",
    "timing_try": "2baf34287af08e908339575d9fee2687f0a41bfe2489b46e6233dd0070244fc0",
    "send_atomic_start": "6fa00e837b65d499c64d950cac9503fa36b2a53b9b9bbdf7ba95046048bd2013",
    "unpause_video": "49ad8c94979a72af8f293e2c40389e08d9f09625fde0959102743a5d26565937",
    "offset_branch": "ee7709481f8d2e5a0757da2ca7537ee1017c81244358c3efb4e9ab364b7154a4",
    "main_loop": "02d0402c894c7755f4c20ef0d7492b8594eb4b501db864f858dbc7015be665ba",
}


def digest(node):
    return hashlib.sha256(ast_dump(node).encode("utf-8")).hexdigest()


def timing_try(source):
    method = source.method("MidiSyncWorker", "_run_logic")
    matches = [n for n in method.body if isinstance(n, ast.Try)]
    if len(matches) != 1:
        raise AssertionError("Expected exactly one existing timing try")
    return matches[0]


def timing_part(source, name):
    node = timing_try(source)
    if name == "timing_try":
        return node
    if name in ("send_atomic_start", "unpause_video"):
        return next(n for n in ast.walk(node) if isinstance(n, ast.FunctionDef) and n.name == name)
    if name == "offset_branch":
        return next(n for n in node.body if isinstance(n, ast.If)
                    and isinstance(n.test, ast.Name) and n.test.id == "is_sending_any_start")
    if name == "main_loop":
        return next(n for n in node.body if isinstance(n, ast.While)
                    and any(isinstance(x, ast.AugAssign) and isinstance(x.target, ast.Name)
                            and x.target.id == "next_tick" for x in ast.walk(n)))
    return source.method("MidiSyncWorker", name)


def audited_timing_try(source):
    """Remove only exact, source-located attach hooks; reject any wider change."""
    node = copy.deepcopy(timing_try(source))
    hook = ast_dump(ast.parse(
        "self._display_coordinator.attach_master(full_socket_path, self.mpv_process)"
    ).body[0])
    launch = ast_dump(ast.parse("self.mpv_process = subprocess.Popen(mpv_cmd)").body[0])
    announce = ast_dump(ast.parse("self.ipc_socket_path.emit(full_socket_path)").body[0])
    removed = []

    def visit(parent):
        for field, value in ast.iter_fields(parent):
            if isinstance(value, list):
                original = list(value)
                clean = []
                for index, child in enumerate(original):
                    if isinstance(child, ast.Expr) and ast_dump(child) == hook:
                        if (index == 0 or index + 1 >= len(original)
                                or ast_dump(original[index - 1]) != launch
                                or ast_dump(original[index + 1]) != announce):
                            raise AssertionError("attach_master hook moved outside existing launch handoff")
                        removed.append(child)
                    else:
                        if isinstance(child, ast.AST):
                            visit(child)
                        clean.append(child)
                setattr(parent, field, clean)
            elif isinstance(value, ast.AST):
                visit(value)
    visit(node)
    if len(removed) not in (0, 2):
        raise AssertionError("Only both audited launch-site attach hooks are permitted")
    return node


class ExactAudioTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = ExtractedSource(BASELINE)
        cls.source = ExtractedSource()

    def test_pinned_baseline_canonicalization_is_cross_version(self):
        for name, expected in PINS.items():
            with self.subTest(part=name):
                self.assertEqual(digest(timing_part(self.baseline, name)), expected)

    def test_run_and_both_timing_wrappers_exact(self):
        for name in ("run", "run_standard", "run_high_precision"):
            with self.subTest(method=name):
                self.assertEqual(digest(timing_part(self.source, name)), PINS[name])

    def test_entire_timing_try_exact_except_audited_attach_handoffs(self):
        self.assertEqual(digest(audited_timing_try(self.source)), PINS["timing_try"],
                         "Audio/MIDI try changed: only exact nonblocking launch attach hooks are allowed")

    def test_atomic_start_offset_and_main_loop_exact(self):
        for name in ("send_atomic_start", "offset_branch", "main_loop"):
            with self.subTest(part=name):
                self.assertEqual(digest(timing_part(self.source, name)), PINS[name])

    def test_actual_audible_unpause_stays_at_original_worker_timing_point(self):
        self.assertEqual(digest(timing_part(self.source, "unpause_video")), PINS["unpause_video"],
                         "An event/request_start cannot replace the actual audible IPC write")

    def test_attach_hook_itself_has_no_ipc_native_process_lock_or_wait(self):
        method = self.source.method("TwoDisplayCoordinator", "attach_master")
        permitted_calls = {"time.monotonic", "self.wake.set"}
        for call in (n for n in ast.walk(method) if isinstance(n, ast.Call)):
            self.assertIn(ast.unparse(call.func), permitted_calls,
                          "Unreviewed call in timing-thread attach hook")
        self.assertFalse(any(isinstance(n, (ast.With, ast.AsyncWith, ast.While, ast.For))
                             for n in ast.walk(method)))

    def test_worker_stop_and_cleanup_add_no_video_join_ipc_or_process_wait(self):
        for name in ("stop", "cleanup"):
            method = self.source.method("MidiSyncWorker", name)
            for call in (n for n in ast.walk(method) if isinstance(n, ast.Call)):
                target = ast.unparse(call.func)
                self.assertNotIn(target.rsplit(".", 1)[-1],
                                 ("join", "wait", "_request", "_get", "transport", "_two_display_stop_process"),
                                 name + " adds video wait/IPC beyond the baseline")

    def test_negative_mutations_cannot_pass_exact_gate(self):
        original = timing_try(self.baseline)
        for old, new in (("24.0", "48.0"), ("0.01", "0.02"), ("1000.0", "100.0")):
            mutated = copy.deepcopy(original)
            changed = False
            for node in ast.walk(mutated):
                if isinstance(node, ast.Constant) and node.value == float(old):
                    node.value = float(new)
                    changed = True
                    break
            self.assertTrue(changed)
            self.assertNotEqual(digest(mutated), PINS["timing_try"])

    def test_audible_master_is_headless_for_every_video_route(self):
        method = self.source.method("MidiSyncWorker", "_run_logic")
        calls = [n for n in ast.walk(method) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_two_display_build_master_command"]
        self.assertEqual(len(calls), 1)
        keywords = {kw.arg: kw.value for kw in calls[0].keywords}
        self.assertEqual(len(calls[0].args), 2, "Audible builder receives only source and master pipe")
        self.assertEqual(set(keywords), {"audio_only", "max_duration_sec"})
        builder = self.source.node("_two_display_build_master_command")
        self.assertNotIn("config", {n.id for n in ast.walk(builder) if isinstance(n, ast.Name)})
        self.assertIn("--vo=null", ast.unparse(builder))
        self.assertNotIn("--fullscreen", ast.unparse(builder))

    def test_dual_supervisor_cannot_write_or_retime_audible_master(self):
        # Inspect literal master-pipe commands as an additional negative gate.
        # A behavioral recording below catches commands assembled indirectly.
        node = self.source.node("TwoDisplayCoordinator")
        forbidden_props = {"pause", "speed", "audio-delay", "time-pos", "vid"}
        for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
            if len(call.args) < 2 or ast.unparse(call.args[0]) != "self.master_pipe":
                continue
            command = call.args[1]
            if isinstance(command, (ast.List, ast.Tuple)) and command.elts:
                values = [x.value if isinstance(x, ast.Constant) else None for x in command.elts]
                self.assertNotIn(values[0], ("seek", "vf", "loadfile"), "video supervisor mutates audible master")
                if values[0] == "set_property" and len(values) > 1:
                    self.assertNotIn(values[1], forbidden_props,
                                     "video supervisor mutates audible master")


class TraceClock:
    def __init__(self, events, stop_phase=None):
        self.value = 1000.0
        self.events = events
        self.stop_phase = stop_phase
        self.worker = None
        self.sleep_count = 0

    def time(self): return self.value
    def monotonic(self): return self.value
    def perf_counter(self):
        self.value += 0.00025
        return self.value
    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError("negative sleep")
        self.events.append(("sleep", round(seconds, 8)))
        self.value += seconds
        self.sleep_count += 1
        if self.worker is not None and self.stop_phase and self.sleep_count == 1:
            self.worker.stop()


def worker_trace(source, *, offset_ms, ports, method, absolute, stop_phase=None):
    events = []
    clock = TraceClock(events, stop_phase)
    class Midi(FakeMidiOut):
        def __init__(self, port):
            super().__init__()
            self.port = port
        def send_message(self, message):
            super().send_message(message)
            events.append(("midi", self.port, tuple(message)))
        def close_port(self):
            super().close_port()
            events.append(("close-midi", self.port))
    class Process(FakeProcess):
        def poll(self):
            return 0 if self.exit_code is not None or clock.value >= 1000.30 else None
        def terminate(self):
            super().terminate()
            events.append(("terminate-master",))
    process = Process()
    def popen(command, **kwargs):
        events.append(("launch-master",))
        return process
    class Pipe:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def write(self, data):
            command = json.loads(data)["command"]
            events.append(("master-ipc", tuple(command)))
    def memory_open(path, mode="r", *args, **kwargs):
        if mode != "w": raise AssertionError("Unexpected real-file operation")
        return Pipe()
    class Coordinator:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def attach_master(self, *args): pass
        def request_start(self): events.append(("WRONG-async-audible-release",))
        def stop(self): pass
        def is_alive(self): return False
        def join(self, *args, **kwargs): raise AssertionError("MIDI owner must not join video")
    ns = source.namespace({"MidiSyncWorker"}, injected={
        "MPV_PATH": "OFFLINE-MPV", "MPV_LAUNCH_HEAD_START_SECONDS": 2,
        "START_BYTE": 0xFA, "STOP_BYTE": 0xFC, "CLOCK_BYTE": 0xF8, "SPP_BYTE": 0xF2,
        "time": clock, "open": memory_open,
        "subprocess": types.SimpleNamespace(Popen=popen),
        "_build_vf_for_zones": lambda cfg: "",
        "_migrate_two_display_config": lambda cfg, *args: cfg or {},
        "_two_display_has_routes": lambda *args: True,
        "_two_display_build_playback_command": lambda *args, **kwargs: ["OFFLINE-MPV"],
        "_two_display_build_master_command": lambda *args, **kwargs: ["OFFLINE-MPV"],
        "_make_unique_mpv_pipe_name": lambda *args: "OFFLINE-MASTER",
        "_two_display_stop_process": lambda p, **kw: p.terminate() if p and p.poll() is None else None,
        "TwoDisplayCoordinator": Coordinator,
        "winmm": types.SimpleNamespace(
            timeBeginPeriod=lambda n: events.append(("timer-start", n)),
            timeEndPeriod=lambda n: events.append(("timer-end", n))),
    })
    preload = 0.08 if stop_phase == "preroll" else 0.03
    abs_time = None if absolute == "none" else (999.9 if absolute == "past" else 1000.12)
    worker = ns["MidiSyncWorker"]("SYNTHETIC.mp4", 120, 1, preload, offset_ms,
        ports[0], ports[1], method, require_midi=False, zoom_config={
            "display_available": {"HDMI": True, "DP": True}}, absolute_start_time=abs_time)
    clock.worker = worker
    worker.midi_outputs = {1: Midi(1), 2: Midi(2)}
    worker.finished.connect(lambda: events.append(("finished",)))
    with contextlib.redirect_stdout(io.StringIO()):
        if method == "high_precision": worker.run_high_precision()
        else: worker.run_standard()
    return events, worker.error.events


class OrderedAudioMidiTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = ExtractedSource(BASELINE)
        cls.source = ExtractedSource()

    def test_baseline_and_candidate_ordered_events_match_full_matrix(self):
        for offset in (-40, 0, 40):
            for ports in ((False,False), (True,False), (False,True), (True,True)):
                for method in ("standard", "high_precision"):
                    for absolute in ("none", "future", "past"):
                        with self.subTest(offset=offset, ports=ports, method=method, absolute=absolute):
                            kw = dict(offset_ms=offset, ports=ports, method=method, absolute=absolute)
                            expected = worker_trace(self.baseline, **kw)
                            actual = worker_trace(self.source, **kw)
                            self.assertEqual(actual, expected,
                                "Actual master IPC, SPP/START/CLOCK/STOP and sleeps must preserve baseline order")

    def test_stop_during_absolute_wait_and_preroll_matches_baseline(self):
        for phase, absolute in (("wait", "future"), ("preroll", "none")):
            with self.subTest(phase=phase):
                kw = dict(offset_ms=0, ports=(True,True), method="standard", absolute=absolute,
                          stop_phase=phase)
                self.assertEqual(worker_trace(self.source, **kw), worker_trace(self.baseline, **kw))


if __name__ == "__main__":
    unittest.main()
