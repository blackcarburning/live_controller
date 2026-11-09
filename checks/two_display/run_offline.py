"""Portable strict selected-suite runner. Does not import the app.

Usage (from any directory):
  python -B checks/two_display/run_offline.py --output-dir /tmp/two-display-test-results
  py -3.13 -B checks/two_display/run_offline.py --require-qt --output-dir <isolated-dir>

Artifacts include exact source/runtime hashes, tests, failures, skips and safety
scope. No credentials, hardware metadata, config contents or endpoints are logged.
Missing candidate, skipped checks, or absent required Qt fails qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReceiptResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(ROOT / "live_controller_two_display.py"))
    parser.add_argument("--baseline", default=str(ROOT / "live_controller.py"))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--require-qt", action="store_true")
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["TWO_DISPLAY_SOURCE"] = str(Path(args.source).resolve())
    os.environ["TWO_DISPLAY_BASELINE"] = str(Path(args.baseline).resolve())
    os.environ["TWO_DISPLAY_REQUIRE_QT"] = "1" if args.require_qt else "0"
    out = Path(args.output_dir or tempfile.mkdtemp(prefix="two-display-test-results-")).resolve()
    # A pre-existing application file must never be accepted as an output path.
    if out == ROOT or out in (Path(args.source).resolve(), Path(args.baseline).resolve()):
        parser.error("output-dir must be an isolated artifact directory, not the project root")
    out.mkdir(parents=True, exist_ok=True)
    os.environ["TWO_DISPLAY_TEST_ARTIFACTS"] = str(out)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    receipt = {
        "suite": "two_display_selected_offline", "python": sys.version,
        "platform": platform.platform(), "qt_required": args.require_qt,
        "scope": {
            "controller_imported": False, "hardware_opened": False,
            "serial_opened": False, "midi_opened": False,
            "native_window_created": False, "mpv_process_launched": False,
            "qt_mode": "offscreen extracted dialog/canvases, setup_ui/status SafeHost, and Event-only real QThread queued ownership guards",
            "hardware_live_qualification": "PENDING; not authorized by this suite",
            "existing_suite": "not included; parent separately runs selected existing tests and Arduino checks",
        },
    }
    for key, value in (("candidate", args.source), ("baseline", args.baseline)):
        p = Path(value)
        if p.is_file():
            b = p.read_bytes()
            receipt[key] = {
                "name": p.name, "sha256": hashlib.sha256(b).hexdigest(),
                "lf_sha256": hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest(),
                "bytes": len(b), "crlf": b.count(b"\r\n"), "lf": b.count(b"\n"),
            }
        else:
            receipt[key] = {"name": p.name, "missing": True}
    try:
        modules = [
            "tests.test_two_display_support", "tests.test_two_display_invariants",
            "tests.test_two_display_helpers", "tests.test_two_display_runtime",
            "tests.test_two_display_audio_gate", "tests.test_two_display_native_protocol",
            "tests.test_two_display_safety_delta",
            "tests.test_two_display_qt",
            "tests.test_two_display_qt_lifecycle",
        ]
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(m) for m in modules)
        log_path = out / "unittest.log"
        with log_path.open("w", encoding="utf-8") as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=ReceiptResult).run(suite)
        receipt.update(
            tests_run=result.testsRun,
            passed=result.passed,
            passed_methods=len(result.passed),
            failed_methods=len({getattr(t, "test_case", t).id() for t, _ in result.failures}),
            assertion_failures_including_subtests=len(result.failures),
            failures=[{"test": t.id(), "traceback": text} for t, text in result.failures],
            errors=[{"test": t.id(), "traceback": text} for t, text in result.errors],
            skipped=[{"test": t.id(), "reason": reason} for t, reason in result.skipped],
            unexpected_successes=[t.id() for t in result.unexpectedSuccesses],
        )
        # Linux may legitimately lack Qt: it remains explicitly pending. Windows
        # --require-qt must execute all real-widget tests with no skips.
        meaningful_skips = [x for x in receipt["skipped"] if not (
            not args.require_qt and "PyQt6 unavailable" in x["reason"])]
        source_stable = True
        for key, value in (("candidate", args.source), ("baseline", args.baseline)):
            p = Path(value)
            expected = receipt[key].get("sha256")
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
                source_stable = False
        receipt["source_stable_during_run"] = source_stable
        receipt["qualified"] = result.wasSuccessful() and not meaningful_skips and not receipt["candidate"].get("missing") and source_stable
        receipt["windows_qt_pending"] = any("PyQt6 unavailable" in x["reason"] for x in receipt["skipped"])
        receipt["release_qualified"] = False  # parent owns final Windows/visual/existing/native/deployment gates
        receipt["qualification_kind"] = "selected offline only; all parent release gates remain separate"
        print(log_path.read_text(encoding="utf-8"))
    except Exception:
        receipt["qualified"] = False
        receipt["harness_exception"] = traceback.format_exc()
        print(receipt["harness_exception"], file=sys.stderr)
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Receipt:", out / "receipt.json")
    print("Offline qualified:", receipt.get("qualified", False))
    return 0 if receipt.get("qualified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
