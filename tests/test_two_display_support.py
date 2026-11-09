"""Shared safety fixtures for the two-display tests; NEVER import the controller.

Only explicitly requested AST definitions are compiled. Unselected imports,
module initialization and the application entry point cannot execute. All file
writes used by extracted production methods go to an isolated temporary root.
"""
from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("TWO_DISPLAY_SOURCE", str(ROOT / "live_controller_two_display.py"))).resolve()
BASELINE = Path(os.environ.get("TWO_DISPLAY_BASELINE", str(ROOT / "live_controller.py"))).resolve()
BASELINE_SHA256 = "605e78b10af95828d2d09df8eb14aa5c85828be4dd73bc467d96b11ff237c346"


class ForbiddenSideEffect(AssertionError):
    pass


def forbid(*args, **kwargs):
    raise ForbiddenSideEffect("Offline harness blocked hardware, native I/O, or process creation")


class Signal:
    def __init__(self, *args):
        self.events = []
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        self.events.append(args)
        for slot in tuple(self.slots):
            slot(*args)


class SignalDescriptor:
    def __init__(self, *args):
        self.name = None

    def __set_name__(self, owner, name):
        self.name = "_offline_signal_" + name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return instance.__dict__.setdefault(self.name, Signal())


class InertThread:
    """QThread-shaped object. Starting a real worker is explicitly forbidden."""
    def __init__(self, *args, **kwargs):
        self._offline_started = False

    start = forbid

    def wait(self, timeout=None):
        return True

    def isRunning(self):
        return False

    def requestInterruption(self):
        self._offline_interrupted = True

    def isInterruptionRequested(self):
        return getattr(self, "_offline_interrupted", False)


class FakeProcess:
    def __init__(self, command=None, exit_code=None):
        self.command = list(command or [])
        self.exit_code = exit_code
        self.terminated = 0
        self.killed = 0
        self.waited = []

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated += 1
        self.exit_code = 0

    def kill(self):
        self.killed += 1
        self.exit_code = -9

    def wait(self, timeout=None):
        self.waited.append(timeout)
        return 0 if self.exit_code is None else self.exit_code


class FakeMidiOut:
    def __init__(self):
        self.messages = []
        self.closed = False

    def send_message(self, message):
        if self.closed:
            raise AssertionError("MIDI write after close")
        self.messages.append(list(message))

    def is_port_open(self):
        return not self.closed

    def close_port(self):
        self.closed = True


class FakeClock:
    """Deterministic clock; no real playback timing or sleeping."""
    def __init__(self, value=1000.0, step=0.0):
        self.value = value
        self.step = step
        self.sleeps = []

    def perf_counter(self):
        self.value += self.step
        return self.value

    monotonic = perf_counter
    time = perf_counter

    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError("negative sleep")
        self.sleeps.append(seconds)
        self.value += seconds


class IsolatedFiles:
    """Permit extracted production file access only inside one temporary root."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.opens = []
        self.before = {}

    def resolve(self, path):
        p = Path(path)
        p = p.resolve() if p.is_absolute() else (self.root / p).resolve()
        if self.root not in p.parents and p != self.root:
            raise ForbiddenSideEffect("File access outside isolated fixture: " + str(p))
        return p

    def open(self, path, mode="r", *args, **kwargs):
        p = self.resolve(path)
        self.opens.append((p.name, mode))
        return builtins.open(p, mode, *args, **kwargs)

    def seed(self, name, data):
        p = self.resolve(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
        self.before[p.name] = p.read_bytes()
        return p

    def assert_unchanged(self, case, names):
        for name in names:
            case.assertEqual(self.resolve(name).read_bytes(), self.before[name], name)


class ExtractedSource:
    def __init__(self, source=SOURCE):
        self.path = Path(source)
        if not self.path.is_file():
            raise unittest.SkipTest("candidate not yet available: " + str(self.path))
        self.bytes = self.path.read_bytes()
        self.sha256 = hashlib.sha256(self.bytes).hexdigest()
        self.tree = ast.parse(self.bytes, filename=str(self.path))
        self.defs = {}
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs[node.name] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.defs[target.id] = node

    def node(self, name):
        if name not in self.defs:
            raise AssertionError("Required candidate seam missing: " + name)
        return self.defs[name]

    def method(self, cls, method):
        node = self.node(cls)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method:
                return child
        raise AssertionError("Required candidate method missing: " + cls + "." + method)

    def segment(self, node):
        return ast.get_source_segment(self.bytes.decode("utf-8"), node) or ast.unparse(node)

    def namespace(self, names, injected=None, methods=None):
        """Compile only an explicit allowlist, in source order; no import copying.

        Dependencies are intentionally explicit. A new dependency raises rather
        than broadening the extractor into an unsafe controller importer.
        """
        names = set(names)
        absent = names - set(self.defs)
        if absent:
            raise AssertionError("Required candidate definitions missing: " + ", ".join(sorted(absent)))
        body = []
        for node in self.tree.body:
            chosen = [n for n in names if self.defs[n] is node]
            if not chosen:
                continue
            node = copy.deepcopy(node)
            if isinstance(node, ast.ClassDef) and methods and node.name in methods:
                wanted = set(methods[node.name])
                node.body = [m for m in node.body if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) or m.name in wanted]
            body.append(node)
        ns = {
            "__name__": "_two_display_ast_fixture_",
            "__file__": str(self.path),
            "json": json, "os": os, "math": math, "copy": copy,
            "threading": threading, "time": time,
            "QThread": InertThread, "pyqtSignal": SignalDescriptor,
            "subprocess": types.SimpleNamespace(Popen=forbid, run=forbid, check_output=forbid),
            "rtmidi": types.SimpleNamespace(MidiOut=forbid),
            "serial": types.SimpleNamespace(Serial=forbid),
            "ctypes": types.SimpleNamespace(WinDLL=forbid, windll=types.SimpleNamespace()),
            "open": forbid,
        }
        ns.update(injected or {})
        exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(self.path), "exec"), ns)
        return ns

    def method_namespace(self, class_name, method_names, *, injected=None):
        """Extract named methods as plain functions; never construct a controller.

        Only a literal @staticmethod decorator may be removed. Other decorators
        are rejected rather than executing class machinery or broad imports.
        """
        body = []
        for name in method_names:
            node = copy.deepcopy(self.method(class_name, name))
            if any(not isinstance(d, ast.Name) or d.id != "staticmethod" for d in node.decorator_list):
                raise AssertionError("Unreviewed extracted-method decorator")
            node.decorator_list = []
            body.append(node)
        ns = self.namespace(set(), injected=injected)
        exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
                     str(self.path), "exec"), ns)
        return ns

    def dual_helpers(self, extra=(), injected=None):
        names = {
            "TWO_DISPLAY_OUTPUTS", "TWO_DISPLAY_FALLBACK_FPS",
            "_TWO_DISPLAY_ZONE_OUTPUT_KEYS", "_TWO_DISPLAY_COMPOSITE_KEYS",
            "_two_display_default_output", "_migrate_two_display_config",
            "_two_display_output_config", "_two_display_has_routes",
            "_two_display_black_vf", "_two_display_build_vf",
            "_two_display_seek_command",
            "_two_display_resolve_outputs", "_two_display_build_playback_command",
            "_two_display_build_master_command",
        }
        # Reviewed legacy definition may remain while the audio-safe design
        # removes its call sites. Extracting it lets behavioral gates diagnose
        # real master mutations instead of a harness NameError. Never required.
        if "_two_display_video_offset_command" in self.defs:
            names.add("_two_display_video_offset_command")
        names.update(extra)
        return self.helpers(names, injected=injected)

    def helpers(self, extra=(), injected=None):
        names = {
            "NUM_ZONES", "_ZONE_INT_DEFAULTS", "_COMPOSITE_INT_DEFAULTS",
            "_default_zone", "_zoom_int", "_normalize_zone",
            "_migrate_zoom_config", "_build_vf_for_zones",
        }
        names.update(extra)
        return self.namespace(names, injected=injected)


def literal_assignments(source):
    result = {}
    for name, node in source.defs.items():
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            try:
                result[name] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result


def ast_dump(node):
    try:
        return ast.dump(node, include_attributes=False, show_empty=True)
    except TypeError:  # Python <3.13: the previous default already includes empties.
        return ast.dump(node, include_attributes=False)


class ExtractionSafetyTests(unittest.TestCase):
    def test_module_initializer_never_executes(self):
        with tempfile.TemporaryDirectory(prefix="two-display-test-") as td:
            p = Path(td) / "fixture.py"
            p.write_text("raise RuntimeError('FULL MODULE EXECUTED')\nimport serial\nN=5\ndef wanted(): return N\n", encoding="utf-8")
            ns = ExtractedSource(p).namespace({"N", "wanted"})
            self.assertEqual(ns["wanted"](), 5)
            self.assertNotIn("serial", {key: value for key, value in ns.items() if key == "serial" and not isinstance(value, types.SimpleNamespace)})

    def test_missing_allowlist_never_silently_omits_test(self):
        with tempfile.TemporaryDirectory(prefix="two-display-test-") as td:
            p = Path(td) / "fixture.py"
            p.write_text("def existing(): return 1\n", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "missing"):
                ExtractedSource(p).namespace({"missing"})

    def test_guard_rejects_outside_file(self):
        with tempfile.TemporaryDirectory(prefix="two-display-test-") as td:
            files = IsolatedFiles(td)
            with self.assertRaises(ForbiddenSideEffect):
                files.open(Path(td).parent / "outside.json", "w")


if __name__ == "__main__":
    unittest.main()
