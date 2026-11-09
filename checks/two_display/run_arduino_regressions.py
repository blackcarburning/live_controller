"""Run unchanged, pinned 56 + 11 + 7 Arduino regressions safely.

Only exact extraction dependencies and missing inert shutdown interfaces are adapted.
Original structural preservation assertions are NOT projected or masked.
No app import, constructor, mpv, MIDI or serial open is permitted. The original
Qt suite retains its explicitly named read-only Windows metadata test. Its raw
metadata output is captured/discarded rather than copied to artifact logs.
Default requires exactly 74 tests and zero skips. --logic-only selects the 67
non-Qt tests explicitly; it is NOT all-74 Windows qualification.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import hashlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import types
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_LF_SHA256 = '605e78b10af95828d2d09df8eb14aa5c85828be4dd73bc467d96b11ff237c346'
HARNESSES = {
    'test_controller_arduino_panel.py':'2f7b60c9912b784ae46f00e66da2ceb0d5e474fb2d6687b306053d9303997a8d',
    'test_arduino_review_regressions.py':'a332d31d81b368c7c8c67e2f72911b8b1bd555bdca3ef5d2fb3e828ac8a3c1d0',
    'check_arduino_panel_qt.py':'5db70d538db7a9eeefe68e87ba8d93958e57526f20c620d05f91f492d4b97b46',
}
DEPENDENCY_PINS = {
    '_two_display_read_path':'d8319ee412a16cfb0c8e4a1875357c9af05696dd9086c7b1423121297276765b',
    '_TWO_DISPLAY_LEGACY_FILES':'3afe34f8d421acc7a6baf2ac4e518190c5972709506d57bf783bae65448d330c',
}
LIFECYCLE_PINS = {
    '_two_display_thread_running':'3c55163f72aac85e2ee56eaccfaebfe215220773de2926d51c8150fd4f509f49',
    '_two_display_running_threads':'b0399c713358b4fb84192560aba954d885e99cec8e17bac84f714f640d96da23',
}
CONSTANTS = {
    'CONFIG_FILE':'two_display_config.json', 'SESSION_FILE':'two_display_session.json',
    'ZOOM_CONFIG_FILE':'two_display_zoom_config.json',
    'BPM_STORE_FILE':'two_display_bpm_store.json',
    'TRACK_NAME_STORE_FILE':'two_display_track_names.json',
    'ZOOM_FRAME_SNAPSHOT':'two_display_zoom_frame_snapshot.png',
}


def require(condition, message):
    if not condition: raise AssertionError(message)


def canonical(node):
    try: return ast.dump(node, include_attributes=False, show_empty=True)
    except TypeError: return ast.dump(node, include_attributes=False)


def lf_hash(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def digest(path):
    data=Path(path).read_bytes()
    return {'name':Path(path).name,'sha256':hashlib.sha256(data).hexdigest(),
            'lf_sha256':lf_hash(data),'bytes':len(data),'crlf':data.count(b'\r\n')}


def extract_dependencies(tree):
    chosen={}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in DEPENDENCY_PINS:
            chosen[node.name]=node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in set(DEPENDENCY_PINS)|set(CONSTANTS):
                    chosen[target.id]=node
    require(set(chosen)==set(DEPENDENCY_PINS)|set(CONSTANTS), 'Exact persistence extraction dependencies missing')
    for name,pin in DEPENDENCY_PINS.items():
        require(hashlib.sha256(canonical(chosen[name]).encode()).hexdigest()==pin,
                'Unreviewed persistence dependency AST: '+name)
    for name,value in CONSTANTS.items():
        require(ast.literal_eval(chosen[name].value)==value,'Persistence path changed: '+name)
    live=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='LiveController')
    lifecycle=[]
    for name,pin in LIFECYCLE_PINS.items():
        method=copy.deepcopy(next(node for node in live.body if isinstance(node,ast.FunctionDef) and node.name==name))
        require(hashlib.sha256(canonical(method).encode()).hexdigest()==pin,
                'Unreviewed lifecycle extraction dependency: '+name)
        require(all(isinstance(d,ast.Name) and d.id=='staticmethod' for d in method.decorator_list),
                'Unreviewed lifecycle method decorator')
        method.decorator_list=[]
        lifecycle.append(method)
    return [copy.deepcopy(chosen[name]) for name in (*CONSTANTS,*DEPENDENCY_PINS)]+lifecycle


def inject_dependencies(env, definitions, trace):
    # The old tests deliberately replace SESSION_FILE with a temporary path.
    # Keep that fixture binding; all other constant values are pinned above.
    session=env.get('SESSION_FILE')
    exec(compile(ast.fix_missing_locations(ast.Module(body=copy.deepcopy(definitions),type_ignores=[])),
                 '<exact two-display persistence dependencies>','exec'),env)
    if session is not None:env['SESSION_FILE']=session
    actual_close=env.get('closeEvent')
    if actual_close is not None:
        def adapted_close(owner,event):
            # Only add missing interfaces to the old inert owners. Actual
            # closeEvent and exact pinned ownership helpers run unchanged.
            additions=[]
            def missing_attr(obj,name,value):
                if not hasattr(obj,name):
                    setattr(obj,name,value)
                    additions.append((obj,name))
            missing_attr(owner,'setEnabled',lambda enabled:trace.setdefault('host_enabled',[]).append(enabled))
            missing_attr(owner,'_two_display_thread_running',env['_two_display_thread_running'])
            missing_attr(owner,'_two_display_running_threads',types.MethodType(env['_two_display_running_threads'],owner))
            listener=owner.hotkey_listener
            missing_attr(listener,'isRunning',lambda:False)
            old_wait=listener.wait
            missing=not hasattr(owner,'_position_poller')
            def wait(timeout):
                require(timeout==1200,'Unexpected hotkey shutdown timeout')
                trace['hotkey_wait_1200']+=1
                # Zero-argument callbacks remain exactly the old callbacks.
                # A timeout-aware callback, if supplied later, is not stripped.
                try:inspect.signature(old_wait).bind(timeout)
                except TypeError:return old_wait()
                return old_wait(timeout)
            listener.wait=wait
            if missing:
                def poller_stop():trace['inert_poller_stop']+=1
                def poller_wait(timeout):
                    require(timeout==1200,'Unexpected position poller timeout')
                    trace['inert_poller_wait_1200']+=1
                    return True
                owner._position_poller=types.SimpleNamespace(stop=poller_stop,wait=poller_wait,isRunning=lambda:False)
            try:
                return actual_close(owner,event)
            finally:
                listener.wait=old_wait
                if missing:del owner._position_poller
                for obj,name in reversed(additions):delattr(obj,name)
        env['closeEvent']=adapted_close
    return env


def negative_controls(tree, definitions):
    # No test callback/assertion/production AST is masked. Prove wrong helper,
    # fallback map and prefixed destination are rejected before loading tests.
    checks=[]
    for name in ('_two_display_read_path','_TWO_DISPLAY_LEGACY_FILES','SESSION_FILE',*LIFECYCLE_PINS):
        bad=copy.deepcopy(tree)
        for node in ast.walk(bad):
            if isinstance(node,ast.FunctionDef) and node.name==name:
                node.body.append(ast.Pass())
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
                node.value=ast.Constant(value='UNSAFE-MUTATION')
        try:extract_dependencies(bad)
        except AssertionError:checks.append(name)
        else:raise AssertionError('Negative dependency mutation escaped: '+name)
    events=[]
    probe={'os':os,'closeEvent':lambda owner,event:owner.hotkey_listener.wait(999)}
    trace=dict(hotkey_wait_1200=0,inert_poller_stop=0,inert_poller_wait_1200=0)
    inject_dependencies(probe,definitions,trace)
    owner=types.SimpleNamespace(hotkey_listener=types.SimpleNamespace(wait=lambda:events.append('old callback')))
    try:probe['closeEvent'](owner,None)
    except AssertionError:checks.append('inert_timeout_interface')
    else:raise AssertionError('Wrong shutdown timeout escaped compatibility adapter')
    require(events==[],'Rejected timeout still invoked old callback')
    require(not hasattr(owner,'_position_poller'),'Adapter leaked fake owner attribute')
    require(not hasattr(owner,'setEnabled'),'Adapter leaked new QWidget interface')
    require(not hasattr(owner.hotkey_listener,'isRunning'),'Adapter leaked fake thread interface')
    return checks


def load_file(path,index):
    name='_pinned_two_display_arduino_'+str(index)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


class CountResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
    def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',default=str(ROOT/'live_controller_two_display.py'))
    parser.add_argument('--baseline',default=str(ROOT/'live_controller.py'))
    parser.add_argument('--tests-dir',required=True)
    parser.add_argument('--output-dir')
    parser.add_argument('--logic-only',action='store_true')
    args=parser.parse_args()
    out=Path(args.output_dir or tempfile.mkdtemp(prefix='two-display-test-arduino-')).resolve()
    require(out not in (ROOT,Path(args.source).resolve(),Path(args.baseline).resolve()),
            'Output must be a separate artifact folder')
    out.mkdir(parents=True,exist_ok=True)
    args.output_dir=str(out)
    try:
        return run(args)
    except Exception:
        failure={'suite':'unchanged_arduino_regressions','qualified':False,
            'all_74_windows_qualified':False,'harness_exception':traceback.format_exc()}
        (out/'receipt.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
        print(failure['harness_exception'],file=sys.stderr)
        print('Receipt:',out/'receipt.json')
        return 1


def run(args):
    sys.dont_write_bytecode=True
    source=Path(args.source).resolve();baseline=Path(args.baseline).resolve()
    require(source!=baseline,'Candidate and original paths must be separate')
    require(lf_hash(baseline.read_bytes())==BASELINE_LF_SHA256,'Original baseline hash changed')
    out=Path(args.output_dir or tempfile.mkdtemp(prefix='two-display-test-arduino-')).resolve()
    require(out not in (ROOT,source,baseline),'Output must be a separate artifact folder')
    out.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    os.environ['CONTROLLER_SOURCE']=str(source)
    os.environ['CONTROLLER_BASELINE']=str(baseline)
    os.environ.pop('ARDUINO_PANEL_SCREENSHOT',None)
    receipt={'suite':'unchanged_arduino_regressions','python':sys.version,'platform':platform.platform(),
        'mode':'selected_67_logic_only' if args.logic_only else 'required_all_74_windows',
        'source':digest(source),'baseline':digest(baseline),'harnesses':{},
        'scope':{'app_imported':False,'serial_opened':False,'midi_opened':False,'mpv_launched':False,
                 'read_only_windows_metadata':not args.logic_only,
                 'original_assertions_changed':False,'hardware_output_discarded':True}}
    trace=dict(hotkey_wait_1200=0,inert_poller_stop=0,inert_poller_wait_1200=0)
    files=[]
    for name,pin in HARNESSES.items():
        path=Path(args.tests_dir)/name
        require(lf_hash(path.read_bytes())==pin,'Original harness pin mismatch: '+name)
        receipt['harnesses'][name]=digest(path)
        if not args.logic_only or name!='check_arduino_panel_qt.py':files.append(path)
    tree=ast.parse(source.read_bytes())
    definitions=extract_dependencies(tree)
    receipt['dependency_ast_pins']={**DEPENDENCY_PINS,**LIFECYCLE_PINS}
    receipt['negative_controls_passed']=negative_controls(tree,definitions)
    # The original first test explicitly requires deployment CRLF. Never alter
    # its SOURCE_BYTES or assertions: provide a disposable exact normalized copy
    # only for LF-hosted source. Receipt keeps the real selected source hash.
    with tempfile.TemporaryDirectory(prefix='two-display-test-arduino-source-') as td:
        data=source.read_bytes()
        normalized=data.replace(b'\r\n',b'\n')
        if b'\r\n' not in data:
            staged=Path(td)/'live_controller_two_display.py'
            staged.write_bytes(normalized.replace(b'\n',b'\r\n'))
            os.environ['CONTROLLER_SOURCE']=str(staged)
            receipt['temporary_crlf_fixture']={'lf_identity_preserved':lf_hash(staged.read_bytes())==lf_hash(data),
                                               'sha256':digest(staged)['sha256']}
        capture=io.StringIO()
        old_hook=sys.excepthook
        try:
            with contextlib.redirect_stdout(capture),contextlib.redirect_stderr(capture):
                modules=[]
                for index,path in enumerate(files):
                    module=load_file(path,index)
                    if hasattr(module,'environment'):
                        actual=module.environment
                        def environment(*a,_actual=actual,**kw):
                            return inject_dependencies(_actual(*a,**kw),definitions,trace)
                        module.environment=environment
                    if hasattr(module,'ENV'):inject_dependencies(module.ENV,definitions,trace)
                    modules.append(module)
                suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules)
                expected=67 if args.logic_only else 74
                require(suite.countTestCases()==expected,'Unexpected original regression test count')
                with (out/'unittest.log').open('w',encoding='utf-8') as log:
                    result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=CountResult).run(suite)
        finally:
            sys.excepthook=old_hook
        receipt.update(tests_run=result.testsRun,passed=result.passed,
            failures=[{'test':t.id(),'traceback':message} for t,message in result.failures],
            errors=[{'test':t.id(),'traceback':message} for t,message in result.errors],
            skipped=[{'test':t.id(),'reason':message} for t,message in result.skipped],
            fixture_adapter_trace=trace,captured_stdout_characters=len(capture.getvalue()))
        receipt['source_stable_during_run']=digest(source)==receipt['source'] and digest(baseline)==receipt['baseline']
        receipt['harnesses_stable_during_run']=all(digest(Path(args.tests_dir)/name)==receipt['harnesses'][name] for name in HARNESSES)
        receipt['qualified']=result.wasSuccessful() and not result.skipped and result.testsRun==expected and receipt['source_stable_during_run'] and receipt['harnesses_stable_during_run']
        receipt['all_74_windows_qualified']=receipt['qualified'] and not args.logic_only and os.name=='nt'
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print((out/'unittest.log').read_text(encoding='utf-8'))
        print('Receipt:',out/'receipt.json')
        print('Selected regressions qualified:',receipt['qualified'])
        return 0 if receipt['qualified'] else 1


if __name__=='__main__':raise SystemExit(main())
