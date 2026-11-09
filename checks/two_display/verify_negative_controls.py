"""Prove selected safety regressions detect pre-fix and mutated AST semantics.

No controller import, hardware, native I/O, real worker or subprocess. Runs the
actual selected test fixtures against immutable input and disposable AST copies.
Expected failing regressions are successful NEGATIVE evidence, never app passes.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import traceback
import unittest

ROOT=Path(__file__).resolve().parents[2]
BASELINE_LF_SHA256="605e78b10af95828d2d09df8eb14aa5c85828be4dd73bc467d96b11ff237c346"
PAUSED_TESTS=(
    "test_paused_master_manual_steps_ignore_moving_drift_threshold",
    "test_paused_source_edit_clamps_first_last_frame_and_float_noise",
    "test_pause_transition_with_one_frame_source_edit_corrects_follower",
    "test_failed_paused_manual_seek_retries_same_position_without_audible_write",
)
CLOSE_TEST="test_close_ignores_owned_worker_timeout_then_completes_after_finish"
EARLY_TEST="test_early_finished_and_old_generation_callbacks_never_delete_running_replacement"


def digest(path):
    data=Path(path).read_bytes()
    return {"sha256":hashlib.sha256(data).hexdigest(),
            "lf_sha256":hashlib.sha256(data.replace(b"\r\n",b"\n")).hexdigest(),"bytes":len(data)}


def selected(base,names,path,label):
    from tests.test_two_display_support import BASELINE, ExtractedSource
    from tests.test_two_display_safety_delta import require_cancellation_hook
    class Case(base):
        @classmethod
        def setUpClass(cls):
            cls.source=ExtractedSource(path)
            require_cancellation_hook(cls.source,ExtractedSource(BASELINE))
    Case.__name__=label
    Case.__qualname__=label
    return unittest.TestSuite(Case(name) for name in names)


def run_case(base,names,path,out,label,negative):
    with (out/(label+".log")).open("w",encoding="utf-8") as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(selected(base,names,path,label))
    return {"label":label,"negative":negative,"tests_run":result.testsRun,
        "failed_methods":len({getattr(test,"test_case",test).id() for test,_ in result.failures}),
        "assertion_failures":len(result.failures),"errors":len(result.errors),"skips":len(result.skipped),
        "detected":bool(result.failures) and not result.errors and not result.skipped if negative
                   else result.wasSuccessful() and not result.skipped,
        "source":digest(path),"log":label+".log"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",default=str(ROOT/"live_controller_two_display.py"))
    parser.add_argument("--baseline",default=str(ROOT/"live_controller.py"))
    parser.add_argument("--prior-source",help="Optional immutable pre-fix 9fa snapshot for paused-seek negative evidence")
    parser.add_argument("--output-dir")
    args=parser.parse_args()
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(ROOT))
    out=Path(args.output_dir or tempfile.mkdtemp(prefix="two-display-test-negatives-")).resolve()
    source=Path(args.source).resolve()
    baseline=Path(args.baseline).resolve()
    if out in (ROOT,source,baseline):parser.error("Use a separate artifact directory")
    out.mkdir(parents=True,exist_ok=True)
    receipt={"suite":"regression_sensitivity_only","release_qualified":False,
        "python":sys.version,"platform":platform.platform(),"checks":[]}
    try:
        assert source!=baseline,"Candidate and original must be separate"
        receipt["source"]=digest(source)
        receipt["baseline"]=digest(baseline)
        assert receipt["baseline"]["lf_sha256"]==BASELINE_LF_SHA256,"Original baseline changed"
        os.environ["TWO_DISPLAY_SOURCE"]=str(source)
        os.environ["TWO_DISPLAY_BASELINE"]=str(baseline)
        from tests.test_two_display_runtime import CoordinatorTests
        from tests.test_two_display_safety_delta import BoundedShutdownOwnershipTests, require_cancellation_hook
        from tests.test_two_display_support import ExtractedSource
        receipt["checks"].append(run_case(CoordinatorTests,PAUSED_TESTS,source,out,"positive_paused",False))
        receipt["checks"].append(run_case(BoundedShutdownOwnershipTests,(CLOSE_TEST,EARLY_TEST),source,out,"positive_lifecycle",False))
        tree=ast.parse(source.read_bytes())
        hook_tree=copy.deepcopy(tree)
        hook_class=next(n for n in hook_tree.body if isinstance(n,ast.ClassDef) and n.name=="LiveController")
        hook=next(n for n in hook_class.body if isinstance(n,ast.FunctionDef) and n.name=="_arduino_before_activity")
        restore=[kw for n in ast.walk(hook) if isinstance(n,ast.Call) and
                 isinstance(n.func,ast.Attribute) and n.func.attr=="_stop_arduino_led_test"
                 for kw in n.keywords if kw.arg=="restore"]
        assert len(restore)==1 and isinstance(restore[0].value,ast.Constant) and restore[0].value.value is False
        restore[0].value=ast.Constant(value=True)
        hook_path=out/"negative_cancellation_hook.py"
        hook_path.write_text(ast.unparse(ast.fix_missing_locations(hook_tree))+chr(10),encoding="utf-8")
        compile(hook_path.read_bytes(),str(hook_path),"exec")
        try:require_cancellation_hook(ExtractedSource(hook_path),ExtractedSource(baseline))
        except AssertionError:hook_detected=True
        else:hook_detected=False
        receipt["checks"].append({"label":"negative_cancellation_hook","negative":True,
            "mutation":"restore=False changed to True; rejected before any selected execution",
            "detected":hook_detected,"errors":0,"skips":0,"source":digest(hook_path)})
        for label,method_name,called_attr,test_name in (
                ("negative_accept_running","closeEvent","_two_display_running_threads",CLOSE_TEST),
                ("negative_delete_running","on_playback_finished","_two_display_thread_running",EARLY_TEST)):
            changed=copy.deepcopy(tree)
            controller=next(n for n in changed.body if isinstance(n,ast.ClassDef) and n.name=="LiveController")
            method=next(n for n in controller.body if isinstance(n,ast.FunctionDef) and n.name==method_name)
            checks=[n for n in method.body if isinstance(n,ast.If) and isinstance(n.test,ast.Call)
                    and isinstance(n.test.func,ast.Attribute) and n.test.func.attr==called_attr]
            assert len(checks)==1,"Exact mutation seam changed: "+label
            checks[0].test=ast.Constant(value=False)
            folder=out/label
            folder.mkdir(exist_ok=True)
            path=folder/"live_controller_two_display.py"
            path.write_text(ast.unparse(ast.fix_missing_locations(changed))+chr(10),encoding="utf-8")
            compile(path.read_bytes(),str(path),"exec")
            receipt["checks"].append(run_case(BoundedShutdownOwnershipTests,(test_name,),path,out,label,True))
        if args.prior_source:
            prior=Path(args.prior_source).resolve()
            receipt["prior_source"]=digest(prior)
            assert receipt["prior_source"]["lf_sha256"]=="9fa78e741d454dd2c53030cdac9d0dcec7561c3d4eca96588086999690367085","Unrecognized pre-fix negative snapshot"
            receipt["checks"].append(run_case(CoordinatorTests,PAUSED_TESTS,prior,out,"negative_prior_paused_9fa",True))
            assert digest(prior)==receipt["prior_source"],"Pre-fix input changed"
        receipt["source_stable"]=digest(source)==receipt["source"] and digest(baseline)==receipt["baseline"]
        receipt["qualified"]=all(check["detected"] for check in receipt["checks"]) and receipt["source_stable"]
    except Exception:
        receipt["qualified"]=False
        receipt["harness_exception"]=traceback.format_exc()
        print(receipt["harness_exception"],file=sys.stderr)
    (out/"receipt.json").write_text(json.dumps(receipt,indent=2),encoding="utf-8")
    print(json.dumps(receipt,indent=2))
    return 0 if receipt.get("qualified") else 1


if __name__=="__main__":raise SystemExit(main())
