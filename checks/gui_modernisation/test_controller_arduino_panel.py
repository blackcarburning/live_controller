"""Hardware-free Arduino panel regression tests (no main-module import).

CONTROLLER_SOURCE overrides the staged source path; CONTROLLER_BASELINE may
point to the exact deployed baseline for XR12/unrelated-code regression checks.
Run with python -B test_controller_arduino_panel.py. All device/native calls
are mocked. Files created by tests use an arduino-panel- prefixed temp folder.
"""
import ast
import contextlib
from collections import deque
from enum import IntFlag
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

SOURCE_PATH = Path(os.environ.get('CONTROLLER_SOURCE', str(Path(__file__).with_name('controller-arduino-panel.py'))))
BASELINE_PATH = Path(os.environ.get('CONTROLLER_BASELINE', str(Path(__file__).with_name('controller-arduino-patched.py'))))
SOURCE_BYTES = SOURCE_PATH.read_bytes()
TREE = ast.parse(SOURCE_BYTES.decode('utf-8'))
CLASSES = {node.name: node for node in TREE.body if isinstance(node, ast.ClassDef)}
FUNCTIONS = {node.name: node for node in TREE.body if isinstance(node, ast.FunctionDef)}
METHODS = {node.name: node for node in CLASSES['LiveController'].body if isinstance(node, ast.FunctionDef)}


class Signal:
    def __init__(self): self.callback = None
    def connect(self, callback): self.callback = callback


class Timer:
    def __init__(self, *args): self.active = False; self.timeout = Signal(); self.interval = None
    def setInterval(self, value): self.interval = value
    def setSingleShot(self, value): self.single = value
    def start(self, *args): self.active = True
    def stop(self): self.active = False
    def isActive(self): return self.active


class Flag(IntFlag):
    ItemIsSelectable = 1
    ItemIsEnabled = 2


class Item:
    def __init__(self, value): self.value = value; self._data = {}; self._flags = Flag(3)
    def setData(self, key, value): self._data[key] = value
    def data(self, key): return self._data.get(key)
    def flags(self): return self._flags
    def setFlags(self, value): self._flags = value
    def setText(self, value): self.value = value


class Table:
    def __init__(self): self.items = {}; self.current = -1; self.rows = 0
    def currentRow(self): return self.current
    def rowCount(self): return self.rows
    def item(self, row, column): return self.items.get((row, column))
    def blockSignals(self, value): pass
    def setRowCount(self, value): self.items = {}; self.rows = value; self.current = -1
    def setItem(self, row, column, item): self.items[row, column] = item
    def clearSelection(self): self.current = -1
    def setCurrentCell(self, row, column): self.current = row
    def selectRow(self, row): self.current = row


class FakeWriter:
    def __init__(self, sent): self.sent=sent; self.state=[]; self.snapshot=None
    def send(self, value):
        if value=="4": self.state=[]
        elif value not in self.state: self.state.append(value)
        self.sent.append(value); return True
    def test_chase(self, seconds=2.5, restore_commands=None):
        if restore_commands is not None: self.state=list(restore_commands)
        self.snapshot=list(self.state); self.sent.append("5"); return True
    def set_chase_restore(self, commands):
        if self.snapshot is None: return False
        self.state=list(commands); self.snapshot=list(commands); return True
    def chase_pending(self): return self.snapshot is not None
    def finish_chase(self, restore=True):
        if self.snapshot is not None and restore: self.sent.extend(["4"]+self.snapshot)
        self.snapshot=None


class Clock:
    def __init__(self): self.now = 0
    def monotonic(self): return self.now


class ScanAttempt:
    def __init__(self, clock, deadline=15, cancel_wait=None):
        self.clock = clock; self.deadline = deadline; self.cancel_wait = cancel_wait
        self.cancelled = False; self.details = []
    def stopped(self): return self.cancelled or self.clock.now >= self.deadline
    def wait(self, seconds):
        self.clock.now += seconds
        if self.cancel_wait == seconds: self.cancelled = True
        return self.stopped()
    def report(self, value): self.details.append(value)


class Handle:
    def __init__(self, port, identity=b'LED_TEST_PRO_MINI_01\n', hook=None, close_hook=None):
        self.port = port; self.identity = identity; self.hook = hook; self.close_hook = close_hook
        self.closed = 0; self.writes = []; self.is_open = True
    def reset_input_buffer(self): pass
    def write(self, value): self.writes.append(value)
    @property
    def in_waiting(self): return bool(self.identity)
    def readline(self):
        value, self.identity = self.identity, b''
        if self.hook: self.hook()
        return value
    def close(self):
        self.closed += 1
        if self.close_hook: self.close_hook()
        self.is_open = False


def environment(clock=time, serial=None, ports=()):
    env = dict(time=clock, threading=threading, deque=deque, re=re, os=os, json=json,
               tempfile=tempfile, serial=serial, QTimer=Timer, QDialog=object,
               list_ports=types.SimpleNamespace(comports=lambda: [types.SimpleNamespace(device=port, description='Mock device', hwid='MOCK') for port in ports]),
               ARDUINO_BAUD=9600, ARDUINO_TARGET_ID='LED_TEST_PRO_MINI_01', ARDUINO_PROBE_CMD=b'?\n',
               SESSION_FILE='unused-session.json', QTableWidgetItem=Item,
               Qt=types.SimpleNamespace(ItemDataRole=types.SimpleNamespace(UserRole=32), ItemFlag=Flag))
    method_names = [name for name in METHODS if ('arduino' in name or name in
                    ('_update_startup_leds', '_configure_startup_hardware', '_poll_startup_hardware',
                     '_maybe_finish_startup_hardware', 'send_led_command', 'save_session', 'closeEvent'))]
    nodes = [CLASSES['Xr12ConnectionAttempt'], CLASSES['ArduinoConnectionAttempt'],
             FUNCTIONS['_arduino_serial_target'], FUNCTIONS['_arduino_list_devices'],
             CLASSES['ArduinoSerialWriter'], CLASSES['ArduinoPanel']] + [METHODS[name] for name in method_names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<extracted Arduino panel>', 'exec'), env)
    env['_arduino_windows_lpt_devices'] = lambda: []
    return env


def owner_for(env):
    methods = {name: env[name] for name in METHODS if name in env}
    owner = type("MockLiveController", (), methods)()
    owner._app_is_closing = False
    owner.is_live_mode = False
    owner.arduino_connected = True
    owner.arduino_serial = None
    owner._arduino_last_port = 'COM5'
    owner._arduino_chase_active = False
    owner.running_test_port = None
    owner.calib_loop_worker = None
    owner._active_sync_show_session = None
    owner._has_active_playback = lambda: False
    owner.midi_available = True
    owner._hardware_status = {}
    owner._startup_probes = {}
    owner._startup_poll_timer = Timer()
    owner._refresh_hardware_status = lambda: None
    owner._init_arduino_panel()
    return owner


def eventually(predicate, seconds=2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate(): return True
        time.sleep(0.002)
    return False


class SourceTests(unittest.TestCase):
    def test_compile_and_crlf(self):
        compile(SOURCE_BYTES, str(SOURCE_PATH), 'exec')
        self.assertEqual(SOURCE_BYTES.count(b'\n'), SOURCE_BYTES.count(b'\r\n'))

    @unittest.skipUnless(BASELINE_PATH.exists(), 'Optional exact baseline source not provided')
    def test_xr12_implementations_unchanged(self):
        baseline = ast.parse(BASELINE_PATH.read_text(encoding='utf-8'))
        for node in baseline.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith('Xr12'):
                self.assertEqual(ast.dump(node), ast.dump(CLASSES[node.name]), node.name)
        original = next(node for node in baseline.body if isinstance(node, ast.ClassDef) and node.name == 'LiveController')
        for node in original.body:
            if isinstance(node, ast.FunctionDef) and (('xr12' in node.name) or ('audience' in node.name) or node.name == '_has_active_playback'):
                self.assertEqual(ast.dump(node), ast.dump(METHODS[node.name]), node.name)

    def test_discoverable_modeless_panel_and_async_shutdown(self):
        self.assertIn('Arduino…', ast.unparse(METHODS['setup_ui']))
        panel = ast.unparse(CLASSES['ArduinoPanel'])
        self.assertIn('setModal(False)', panel)
        self.assertNotIn('.exec(', panel)
        shutdown = ast.unparse(METHODS['_shutdown_arduino_panel'])
        self.assertNotIn('.join(', shutdown)
        self.assertNotIn('.wait(', shutdown)
        self.assertNotIn('QThread', ast.unparse(CLASSES['ArduinoConnectionAttempt']))
        close = ast.unparse(METHODS['closeEvent'])
        self.assertIn('_shutdown_arduino_panel', close)
        self.assertNotIn('arduino_serial.close', close)

    def test_each_activity_path_invalidates_test_before_native_work(self):
        for name in ('start_playback', 'start_countdown', 'execute_playback', 'play_test_track', 'run_port_test', '_start_calib_loop', 'trigger_sync_show'):
            self.assertEqual(ast.unparse(METHODS[name].body[1]), 'self._arduino_before_activity()', name)


class ProbeTests(unittest.TestCase):
    def scan(self, ports, identities, selected=None, last='COM5', hook=None, cancel_wait=None, limit=15):
        clock = Clock(); attempt = ScanAttempt(clock, deadline=limit, cancel_wait=cancel_wait)
        opened = []; handles = []
        def serial_factory(port, *args, **kwargs):
            opened.append(port)
            value = identities.get(port, b'')
            if isinstance(value, Exception): raise value
            handle = Handle(port, value, hook=lambda: hook(attempt) if hook else None)
            handles.append(handle)
            return handle
        env = environment(clock, types.SimpleNamespace(Serial=serial_factory), ports)
        owner = types.SimpleNamespace(arduino_connected=True, _app_is_closing=False, _arduino_last_port=last)
        with contextlib.redirect_stdout(io.StringIO()):
            result = env['_connect_arduino'](owner, attempt, selected_port=selected)
        return result, opened, handles, attempt

    def test_manual_selected_only_failure_never_falls_back(self):
        result, opened, handles, attempt = self.scan(['COM8','COM5'], {'COM5':b'LED_TEST_PRO_MINI_01\n', 'COM8':b'WRONG\n'}, selected='COM8')
        self.assertIsNone(result); self.assertEqual(opened, ['COM8']); self.assertEqual(handles[0].closed, 1)
        self.assertIn('WRONG', attempt.details[-1])

    def test_selected_only_does_not_even_enumerate(self):
        clock=Clock(); attempt=ScanAttempt(clock); opened=[]
        env=environment(clock, types.SimpleNamespace(Serial=lambda port,*a,**kw: opened.append(port) or Handle(port)))
        env['list_ports'].comports=lambda: (_ for _ in ()).throw(AssertionError('unexpected enumeration'))
        owner=types.SimpleNamespace(arduino_connected=True,_app_is_closing=False)
        result=env['_connect_arduino'](owner,attempt,selected_port='COM12')
        self.assertEqual(opened,['COM12']); self.assertEqual(result.port,'COM12')

    def test_lpt_can_never_be_serial_target(self):
        result, opened, *_ = self.scan(['LPT1','COM5'], {}, selected='LPT1')
        self.assertIsNone(result); self.assertEqual(opened,[])
        result, opened, *_ = self.scan(['LPT1','COM5'], {'COM5':b'LED_TEST_PRO_MINI_01\n'})
        self.assertEqual(opened,['COM5'])

    def test_startup_remembered_before_com5_and_fallback(self):
        result, opened, *_ = self.scan(['COM8','COM5','COM12'], {'COM12':b'WRONG\n','COM5':b'LED_TEST_PRO_MINI_01\n'},last='COM12')
        self.assertEqual(opened,['COM12','COM5']); self.assertEqual(result.port,'COM5')
        result, opened, *_ = self.scan(['COM8','COM5'], {'COM8':b'LED_TEST_PRO_MINI_01\n'})
        self.assertEqual(opened,['COM5','COM8']); self.assertEqual(result.port,'COM8')
        result, opened, *_ = self.scan(['COM11'], {'COM11':b'LED_TEST_PRO_MINI_01\n'},last='COM12')
        self.assertEqual(opened,['COM11']); self.assertEqual(result.port,'COM11')

    def test_optional_no_never_lists_or_opens(self):
        env=environment()
        env['list_ports'].comports=lambda: self.fail('No must not enumerate')
        owner=types.SimpleNamespace(arduino_connected=False,_app_is_closing=False)
        self.assertIsNone(env['_connect_arduino'](owner,ScanAttempt(Clock())))

    def test_native_read_after_deadline_and_cancel_cleans_and_stops_fallback(self):
        for hook in (lambda a:setattr(a.clock,'now',16), lambda a:setattr(a,'cancelled',True)):
            result, opened, handles, _ = self.scan(['COM5','COM8'], {'COM5':b'LED_TEST_PRO_MINI_01\n'}, hook=hook)
            self.assertIsNone(result); self.assertEqual(opened,['COM5']); self.assertEqual(handles[0].closed,1)
        result, opened, handles, _ = self.scan(['COM5','COM8'],{},cancel_wait=2.0)
        self.assertIsNone(result); self.assertEqual(opened,['COM5']); self.assertEqual(handles[0].writes,[])

    def test_error_includes_selected_port_and_useful_native_reason(self):
        result, opened, _, attempt=self.scan(['COM5'],{'COM5':PermissionError('Access denied (in use)')},selected='COM5')
        self.assertIsNone(result); self.assertIn('COM5',attempt.details[-1]); self.assertIn('Access denied',attempt.details[-1])


class EnumerationTests(unittest.TestCase):
    def test_metadata_listing_never_opens_hardware_and_reports_lpt(self):
        calls=[]
        env=environment(serial=types.SimpleNamespace(Serial=lambda *a,**kw:self.fail('hardware opened')),ports=['COM12','COM5'])
        env['_arduino_windows_lpt_devices']=lambda:[dict(port='LPT1',description='Printer',hwid='',serial=False)]
        result=env['_arduino_list_devices'](ScanAttempt(Clock()))
        self.assertEqual([r['port'] for r in result['rows']],['COM5','COM12','LPT1'])
        self.assertFalse(result['rows'][-1]['serial'])

    def test_lpt_rows_are_disabled_and_have_no_selection_data(self):
        env=environment(); owner=owner_for(env)
        panel=types.SimpleNamespace(table=Table(),controller=owner,refresh_state=lambda:None)
        panel.selected_port=types.MethodType(env['ArduinoPanel'].selected_port,panel)
        env['ArduinoPanel'].set_devices(panel,[dict(port='COM5',description='USB',hwid='',serial=True),dict(port='LPT1',description='Parallel',hwid='',serial=False)])
        item=panel.table.item(1,0)
        self.assertIsNone(item.data(32)); self.assertFalse(item.flags() & Flag.ItemIsSelectable); self.assertFalse(item.flags() & Flag.ItemIsEnabled)
        panel.table.current=1; self.assertIsNone(panel.selected_port())
        owner._arduino_devices=[dict(port='LPT1',serial=False)]
        self.assertFalse(owner._connect_selected_arduino('LPT1'))

    def test_refresh_returns_while_metadata_driver_is_slow_and_serial_not_opened(self):
        entered=threading.Event(); release=threading.Event()
        env=environment(serial=types.SimpleNamespace(Serial=lambda *a,**k:self.fail('hardware opened')))
        env['list_ports'].comports=lambda: (entered.set(),release.wait(2),[])[2]
        owner=owner_for(env)
        owner._refresh_arduino_devices()
        self.assertTrue(entered.wait(1)); self.assertIsNotNone(owner._arduino_listing)
        owner._arduino_panel_hidden(); self.assertFalse(owner._arduino_listing.released())
        self.assertIsNotNone(owner._arduino_listing)
        release.set(); self.assertTrue(eventually(owner._arduino_listing.released))
        owner._poll_arduino_panel(); self.assertIsNone(owner._arduino_listing)


class StartupIntegrationTests(unittest.TestCase):
    def make_owner(self, env, arduino_choice):
        owner=owner_for(env); calls=[]; owner.xr12_connected=False
        owner._ask_hardware_connected=lambda device,details: arduino_choice if device.startswith('Arduino') else False
        owner.apply_config_to_ui=lambda:None
        owner.xr12_controller=types.SimpleNamespace(enabled=False)
        owner._open_audience_if_idle=lambda:None
        owner._set_xr12_status_text=lambda value:None
        owner.xr12_enabled_checkbox=types.SimpleNamespace(setToolTip=lambda value:None)
        owner._startup_probes={}; owner._startup_poll_timer=Timer()
        owner._check_playback_midi=lambda:False
        owner._start_arduino_probe=lambda **kw:calls.append(kw)
        return owner,calls

    def test_startup_no_never_requests_arduino_operation(self):
        env=environment(); owner,calls=self.make_owner(env,False)
        owner._configure_startup_hardware()
        self.assertEqual(calls,[]); self.assertEqual(owner._hardware_status['Arduino'],'skipped (no serial scan)')
        self.assertNotIn('Arduino',owner._startup_probes)
        for probe in owner._startup_probes.values(): probe.cancel()

    def test_startup_yes_uses_shared_arduino_ownership_not_an_independent_probe(self):
        env=environment(); owner,calls=self.make_owner(env,True)
        owner._configure_startup_hardware()
        self.assertEqual(calls,[dict(startup=True)]); self.assertNotIn('Arduino',owner._startup_probes)
        for probe in owner._startup_probes.values(): probe.cancel()


class OperationFenceTests(unittest.TestCase):
    def test_cancel_waits_for_slow_late_native_close_and_blocks_retry(self):
        env=environment(); owner=owner_for(env)
        entered=threading.Event(); native_release=threading.Event(); close_entered=threading.Event(); close_release=threading.Event()
        handle=Handle('COM12',close_hook=lambda:(close_entered.set(),close_release.wait(2)))
        def operation(attempt, selected_port=None): entered.set(); native_release.wait(2); return handle
        type(owner)._connect_arduino=staticmethod(lambda context,attempt,selected_port=None:operation(attempt,selected_port=selected_port))
        self.assertTrue(owner._start_arduino_probe(selected_port='COM12'))
        self.assertTrue(entered.wait(1)); probe=owner._arduino_operation
        owner._cancel_arduino_operation(); owner._poll_arduino_panel()
        self.assertIs(owner._arduino_operation,probe)
        self.assertFalse(owner._start_arduino_probe(selected_port='COM5'))
        native_release.set(); self.assertTrue(close_entered.wait(1))
        self.assertFalse(probe.released()); owner._poll_arduino_panel(); self.assertIs(owner._arduino_operation,probe)
        close_release.set(); self.assertTrue(eventually(probe.released)); owner._poll_arduino_panel()
        self.assertIsNone(owner._arduino_operation); self.assertIsNone(owner.arduino_serial); self.assertEqual(handle.closed,1)

    def test_main_shutdown_detaches_slow_probe_without_native_gui_close(self):
        env=environment(); owner=owner_for(env); entered=threading.Event(); release=threading.Event(); closed=threading.Event()
        handle=Handle('COM5',close_hook=closed.set)
        def operation(context,attempt,selected_port=None): entered.set(); release.wait(2); return handle
        type(owner)._connect_arduino=staticmethod(operation)
        owner._start_arduino_probe(selected_port='COM5'); self.assertTrue(entered.wait(1))
        probe=owner._arduino_operation; owner._app_is_closing=True
        owner._shutdown_arduino_panel()
        self.assertTrue(probe.stopped()); self.assertFalse(probe.released()); self.assertFalse(owner._arduino_panel_timer.active)
        release.set(); self.assertTrue(closed.wait(1)); self.assertTrue(eventually(probe.released)); self.assertEqual(handle.closed,1)

    def test_deadline_reports_before_native_return_but_retains_cleanup_fence(self):
        clock=Clock(); env=environment(clock); entered=threading.Event(); release=threading.Event(); closed=threading.Event()
        def operation(attempt): entered.set(); release.wait(2); return Handle('COM5',close_hook=closed.set)
        probe=env['ArduinoConnectionAttempt'](operation)
        self.assertTrue(entered.wait(1)); clock.now=16
        done,result,error=probe.poll(); self.assertTrue(done); self.assertIsNone(result); self.assertIsInstance(error,TimeoutError)
        self.assertFalse(probe.released()); release.set(); self.assertTrue(closed.wait(1)); self.assertTrue(eventually(probe.released))

    def test_cancel_after_worker_finished_still_fences_async_disposal(self):
        env=environment(); close_entered=threading.Event(); close_release=threading.Event()
        handle=Handle('COM5',close_hook=lambda:(close_entered.set(),close_release.wait(2)))
        probe=env['ArduinoConnectionAttempt'](lambda a:handle)
        self.assertTrue(eventually(probe.released)); probe.cancel()
        self.assertTrue(close_entered.wait(1)); self.assertFalse(probe.released())
        close_release.set(); self.assertTrue(eventually(probe.released)); self.assertEqual(handle.closed,1)
        done,result,error=probe.poll(); self.assertTrue(done); self.assertIsNone(result)

    def test_expired_completed_result_is_disposed_not_adopted(self):
        clock=Clock(); env=environment(clock); handle=Handle('COM5')
        probe=env['ArduinoConnectionAttempt'](lambda a:handle)
        self.assertTrue(eventually(probe.released)); clock.now=16
        done,result,error=probe.poll(); self.assertTrue(done); self.assertIsNone(result); self.assertIsInstance(error,TimeoutError)
        self.assertTrue(eventually(lambda:handle.closed==1))

    def test_busy_activity_and_live_show_guard_even_direct_calls(self):
        env=environment(); owner=owner_for(env); owner._arduino_devices=[dict(port='COM5',serial=True)]
        for change,undo in ((lambda:setattr(owner,'is_live_mode',True),lambda:setattr(owner,'is_live_mode',False)),
                            (lambda:setattr(owner,'_has_active_playback',lambda:True),lambda:setattr(owner,'_has_active_playback',lambda:False)),
                            (lambda:setattr(owner,'running_test_port',1),lambda:setattr(owner,'running_test_port',None)),
                            (lambda:setattr(owner,'_active_sync_show_session','show'),lambda:setattr(owner,'_active_sync_show_session',None))):
            change(); self.assertFalse(owner._connect_selected_arduino('COM5')); self.assertFalse(owner._test_arduino_leds()); self.assertFalse(owner._disconnect_arduino()); undo()

    def test_activity_transition_cancels_inflight_manual_result(self):
        env=environment(); owner=owner_for(env); entered=threading.Event(); release=threading.Event(); handle=Handle('COM5')
        def operation(attempt, selected_port=None): entered.set(); release.wait(2); return handle
        type(owner)._connect_arduino=staticmethod(lambda context,attempt,selected_port=None:operation(attempt,selected_port=selected_port))
        owner._start_arduino_probe(selected_port='COM5'); self.assertTrue(entered.wait(1))
        owner.is_live_mode=True; owner._poll_arduino_panel(); release.set()
        self.assertTrue(eventually(owner._arduino_operation.released)); owner._poll_arduino_panel()
        self.assertIsNone(owner.arduino_serial); self.assertEqual(handle.closed,1); self.assertEqual(owner._arduino_last_port,'COM5')


class WriterAndLedTests(unittest.TestCase):
    def test_worker_timed_chase_restores_all_preexisting_leds_without_gui_tick(self):
        env=environment(); handle=Handle('COM5'); writer=env['ArduinoSerialWriter'](handle)
        try:
            writer.send('1'); writer.send('2')
            self.assertTrue(eventually(lambda:len(handle.writes)>=2))
            self.assertTrue(writer.test_chase(seconds=0.025))
            self.assertTrue(eventually(lambda:len(handle.writes)>=6))
            self.assertEqual(handle.writes,[b'1',b'2',b'5',b'4',b'1',b'2'])
        finally:
            writer.close(); self.assertTrue(writer.released.wait(1))

    def test_worker_new_activity_command_cancels_stale_restore(self):
        env=environment(); handle=Handle('COM5'); writer=env['ArduinoSerialWriter'](handle)
        try:
            writer.send('1'); writer.test_chase(seconds=0.05)
            self.assertTrue(eventually(lambda:b'5' in handle.writes))
            writer.finish_chase(restore=False); writer.send('3')
            self.assertTrue(eventually(lambda:b'3' in handle.writes)); time.sleep(0.07)
            self.assertEqual(handle.writes,[b'1',b'5',b'3'])
        finally:
            writer.close(); self.assertTrue(writer.released.wait(1))

    def test_live_writer_serializes_write_then_close_and_never_on_caller_thread(self):
        env=environment(); entered=threading.Event(); release=threading.Event(); events=[]
        class SlowHandle(Handle):
            def write(self,value):
                events.append(('write',value,threading.get_ident()))
                if value==b'5': entered.set(); release.wait(2)
            def close(self): events.append(('close',None,threading.get_ident())); super().close()
        handle=SlowHandle('COM5'); writer=env['ArduinoSerialWriter'](handle)
        writer.send('5'); self.assertTrue(entered.wait(1)); writer.close()
        self.assertFalse(writer.released.is_set()); self.assertFalse(writer.send('1')); self.assertEqual(handle.closed,0)
        release.set(); self.assertTrue(writer.released.wait(1))
        self.assertEqual([x[:2] for x in events],[('write',b'5'),('write',b'4'),('close',None)])
        self.assertTrue(all(x[2]!=threading.get_ident() for x in events))

    def test_switch_waits_for_live_writer_native_close_before_probe(self):
        env=environment(); owner=owner_for(env); close_entered=threading.Event(); close_release=threading.Event(); calls=[]
        handle=Handle('COM5',close_hook=lambda:(close_entered.set(),close_release.wait(2)))
        owner.arduino_serial=handle; owner._arduino_writer=env['ArduinoSerialWriter'](handle)
        owner._arduino_devices=[dict(port='COM12',serial=True)]
        type(owner)._connect_arduino=staticmethod(lambda context,attempt,selected_port=None:calls.append(selected_port))
        self.assertTrue(owner._connect_selected_arduino('COM12')); self.assertTrue(close_entered.wait(1))
        owner._poll_arduino_panel(); self.assertEqual(calls,[])
        close_release.set(); closing=owner._arduino_closing_writer; self.assertTrue(closing.released.wait(1))
        owner._poll_arduino_panel(); self.assertTrue(eventually(lambda:calls==['COM12']))
        if owner._arduino_operation is not None:
            self.assertTrue(eventually(owner._arduino_operation.released)); owner._poll_arduino_panel()

    def test_reuse_live_validated_handle_no_open_or_probe_and_led_timer_restore(self):
        env=environment(); owner=owner_for(env); sent=[]
        owner.arduino_serial=Handle('COM5'); owner._arduino_writer=FakeWriter(sent)
        owner._arduino_devices=[dict(port='COM5',serial=True)]
        owner._start_arduino_probe=lambda **kw:self.fail('must reuse live handle')
        self.assertTrue(owner._connect_selected_arduino('COM5')); self.assertIn('reusing',owner._arduino_panel_status)
        owner._arduino_writer.state=['2']
        self.assertTrue(owner._test_arduino_leds()); self.assertTrue(owner._arduino_led_timer.active); self.assertEqual(sent,['5'])
        owner._finish_arduino_led_test(); self.assertEqual(sent,['5','4','2']); self.assertFalse(owner._arduino_chase_active)
        owner._test_arduino_leds(); owner.send_led_command('3'); owner._finish_arduino_led_test()
        self.assertEqual(sent,['5','4','2','5','3'])

    def test_panel_close_cancels_manual_but_does_not_close_validated_live_handle(self):
        env=environment(); owner=owner_for(env); sent=[]
        owner.arduino_serial=Handle('COM5'); owner._arduino_writer=FakeWriter(sent)
        owner._arduino_writer.state=['1']; owner._test_arduino_leds(); owner._arduino_panel_hidden()
        self.assertEqual(sent,['5','4','1']); self.assertEqual(owner.arduino_serial.closed,0)


class PersistenceTests(unittest.TestCase):
    def test_success_merges_only_verified_port_and_preserves_unrelated_keys(self):
        env=environment(); owner=owner_for(env)
        with tempfile.TemporaryDirectory(prefix='arduino-panel-') as directory:
            path=Path(directory)/'session.json'; path.write_text(json.dumps(dict(arduino_last_port='COM5',tracks=[{'name':'Keep'}],unknown={'key':[1,2]})),encoding='utf-8')
            env['SESSION_FILE']=str(path)
            owner._accept_arduino_connection(Handle('COM12'))
            writer=owner._arduino_writer
            try:
                saved=json.loads(path.read_text()); self.assertEqual(saved['arduino_last_port'],'COM12'); self.assertEqual(saved['tracks'],[{'name':'Keep'}]); self.assertEqual(saved['unknown'],{'key':[1,2]}); self.assertEqual(owner._arduino_last_port,'COM12')
            finally:
                writer.close(); self.assertTrue(writer.released.wait(1))

    def test_failure_and_cancel_do_not_persist_bad_selection(self):
        env=environment(); owner=owner_for(env); called=[]
        owner._save_arduino_port=lambda value:called.append(value)
        class FailedProbe:
            def poll(self): return True,None,None
            def messages(self): return ['COM12: expected LED_TEST_PRO_MINI_01; received WRONG']
            def released(self): return True
        owner._arduino_operation=FailedProbe(); owner._arduino_operation_kind='manual'; owner._arduino_operation_port='COM12'
        owner._poll_arduino_panel()
        self.assertEqual(called,[]); self.assertEqual(owner._arduino_last_port,'COM5'); self.assertIn('WRONG',owner._arduino_port_results['COM12'])

    def test_invalid_existing_session_and_replace_failure_preserve_old_saved_value(self):
        env=environment(); owner=owner_for(env)
        with tempfile.TemporaryDirectory(prefix='arduino-panel-') as directory:
            path=Path(directory)/'session.json'; path.write_text('{bad',encoding='utf-8'); env['SESSION_FILE']=str(path)
            with self.assertRaises(json.JSONDecodeError): owner._save_arduino_port('COM12')
            self.assertEqual(path.read_text(),'{bad'); self.assertEqual(owner._arduino_last_port,'COM5')
            path.write_text('{"arduino_last_port":"COM5","other":99}',encoding='utf-8')
            with patch.object(os,'replace',side_effect=PermissionError('read-only')):
                with self.assertRaises(PermissionError): owner._save_arduino_port('COM12')
            self.assertEqual(json.loads(path.read_text())['other'],99); self.assertEqual(owner._arduino_last_port,'COM5')
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),['session.json'])

    def test_normal_save_session_merges_unrelated_keys(self):
        env=environment(); exec(compile(ast.Module(body=[METHODS['save_session']],type_ignores=[]),'<save session>','exec'),env)
        class Value:
            def text(self): return '120'
            def value(self): return 1
            def isChecked(self): return False
            def currentText(self): return '20'
        owner=types.SimpleNamespace(_arduino_last_port='COM12',tracks=[],undo_history=[],test_track_path=None,
            current_table_font_size=16,count_in_bg_color='red',count_in_font_size=100,track_play_bg_color='green',track_play_font_size=80)
        for name in ('title_label','test_track_bpm_input','midi_offset_slider','high_precision_timing_radio','count_in_combo','streamdeck_font_spinbox','scrub_lock_checkbox','loop_checkbox','loop_bpm_spinbox','loop_start_bar_spinbox','loop_end_bar_spinbox'):
            setattr(owner,name,Value())
        with tempfile.TemporaryDirectory(prefix='arduino-panel-') as directory:
            path=Path(directory)/'session.json'; path.write_text('{"unknown":123}',encoding='utf-8'); env['SESSION_FILE']=str(path)
            env['save_session'](owner)
            saved=json.loads(path.read_text()); self.assertEqual(saved['unknown'],123); self.assertEqual(saved['arduino_last_port'],'COM12')


class BlockingLedHandle(Handle):
    """A driver fake that blocks one write and tracks actual additive LEDs."""
    def __init__(self, block=b'1'):
        super().__init__('COM5')
        self.block=block; self.entered=threading.Event(); self.release=threading.Event()
        self.blocked=False; self.state=set()
    def write(self, value):
        self.writes.append(value)
        if value==self.block and not self.blocked:
            self.blocked=True; self.entered.set()
            if not self.release.wait(3): raise TimeoutError('Test did not release mocked native write')
        for character in value.decode('ascii'):
            if character=='4': self.state.clear()
            elif character in '1236': self.state.add(character)


class QueuedLedGenerationTests(unittest.TestCase):
    def make_writer(self, block=b'1'):
        env=environment(); handle=BlockingLedHandle(block); writer=env['ArduinoSerialWriter'](handle)
        def cleanup():
            handle.release.set(); writer.close(); self.assertTrue(writer.released.wait(1))
        self.addCleanup(cleanup)
        return env,writer,handle

    def test_cancel_with_and_without_restore_removes_chase_before_dispatch(self):
        for restore in (False,True):
            with self.subTest(restore=restore):
                _,writer,handle=self.make_writer()
                writer.send('1'); self.assertTrue(handle.entered.wait(1))
                self.assertTrue(writer.test_chase(seconds=10))
                writer.finish_chase(restore=restore); writer.send('3')
                handle.release.set(); self.assertTrue(eventually(lambda:b'3' in handle.writes))
                self.assertEqual(handle.writes,[b'1',b'3'])

    def test_ordinary_command_itself_invalidates_queued_chase(self):
        _,writer,handle=self.make_writer()
        writer.send('1'); self.assertTrue(handle.entered.wait(1))
        writer.test_chase(seconds=10); writer.send('3'); handle.release.set()
        self.assertTrue(eventually(lambda:b'3' in handle.writes))
        self.assertNotIn(b'5',handle.writes)

    def test_expired_undispatched_chase_does_not_start_after_slow_native_write(self):
        _,writer,handle=self.make_writer()
        writer.send('1'); self.assertTrue(handle.entered.wait(1))
        writer.test_chase(seconds=0.02); time.sleep(0.04); handle.release.set()
        self.assertTrue(eventually(lambda:not writer.chase_pending()))
        self.assertEqual(handle.writes,[b'1'])

    def test_cancel_mid_restore_removes_all_unsent_generation_entries(self):
        _,writer,handle=self.make_writer(block=b'4')
        writer.send('1'); writer.send('2'); self.assertTrue(eventually(lambda:b'2' in handle.writes))
        writer.test_chase(seconds=0.02); self.assertTrue(handle.entered.wait(1))
        first_off=handle.writes.index(b'4')
        writer.finish_chase(restore=False); writer.send('4'); writer.send('3'); handle.release.set()
        self.assertTrue(eventually(lambda:handle.state=={'3'}))
        self.assertNotIn(b'1',handle.writes[first_off+1:]); self.assertNotIn(b'2',handle.writes[first_off+1:])

    def test_cancel_restore_then_new_activity_never_leaks_replacement_restore(self):
        _,writer,handle=self.make_writer(block=b'4')
        writer.send('1'); writer.send('2'); self.assertTrue(eventually(lambda:b'2' in handle.writes))
        writer.test_chase(seconds=0.02); self.assertTrue(handle.entered.wait(1))
        first_off=handle.writes.index(b'4')
        writer.finish_chase(restore=True); writer.send('4'); writer.send('3'); handle.release.set()
        self.assertTrue(eventually(lambda:handle.state=={'3'}))
        self.assertNotIn(b'1',handle.writes[first_off+1:]); self.assertNotIn(b'2',handle.writes[first_off+1:])

    def test_overflow_preserves_required_off_and_full_latest_desired_state(self):
        _,writer,handle=self.make_writer()
        writer.send('1'); self.assertTrue(handle.entered.wait(1)); writer.send('4')
        for index in range(160): writer.send('3' if index%2 else '6')
        self.assertLessEqual(len(writer._commands),64)
        handle.release.set(); self.assertTrue(eventually(lambda:handle.state=={'3','6'}))
        self.assertIn(b'4',handle.writes); self.assertNotIn('1',handle.state)

    def test_activity_hook_cancels_startup_chase_even_in_default_live_mode(self):
        env,writer,handle=self.make_writer(); owner=owner_for(env)
        owner.is_live_mode=True; owner.arduino_serial=handle; owner._arduino_writer=writer
        writer.send('1'); self.assertTrue(handle.entered.wait(1)); writer.test_chase(seconds=10)
        owner._arduino_chase_active=True; owner._arduino_led_test_kind='startup'
        owner._arduino_before_activity(); owner.send_led_command('3'); handle.release.set()
        self.assertTrue(eventually(lambda:b'3' in handle.writes))
        self.assertNotIn(b'5',handle.writes); self.assertFalse(owner._arduino_chase_active)

    def test_activity_hook_removes_restore_tail_even_after_gui_chase_flag_cleared(self):
        env,writer,handle=self.make_writer(block=b'4'); owner=owner_for(env)
        owner.arduino_serial=handle; owner._arduino_writer=writer
        writer.send('1'); writer.send('2'); self.assertTrue(eventually(lambda:b'2' in handle.writes))
        writer.test_chase(seconds=0.02); self.assertTrue(handle.entered.wait(1))
        first_off=handle.writes.index(b'4')
        owner._arduino_chase_active=False; owner._arduino_led_test_kind=None
        owner._arduino_before_activity(); owner.send_led_command('4'); owner.send_led_command('3'); handle.release.set()
        self.assertTrue(eventually(lambda:handle.state=={'3'}))
        self.assertNotIn(b'1',handle.writes[first_off+1:]); self.assertNotIn(b'2',handle.writes[first_off+1:])


class StartupChaseTests(unittest.TestCase):
    def accepted_owner(self, midi=False):
        env=environment(); owner=owner_for(env); owner.is_live_mode=True; owner.midi_available=midi
        owner._save_arduino_port=lambda port:setattr(owner,'_arduino_last_port',port)
        handle=Handle('COM12'); owner._accept_arduino_connection(handle,startup=True)
        writer=owner._arduino_writer
        self.addCleanup(lambda:(writer.close(),writer.released.wait(1)))
        return owner,writer,handle

    def test_idle_startup_chase_is_preserved_in_live_mode_and_restores_latest_midi(self):
        owner,writer,handle=self.accepted_owner(midi=False)
        self.assertTrue(eventually(lambda:b'5' in handle.writes))
        self.assertTrue(owner._arduino_chase_active); self.assertEqual(owner._arduino_led_test_kind,'startup')
        owner._poll_arduino_panel(); self.assertTrue(owner._arduino_chase_active)
        owner.midi_available=True; owner._update_startup_leds()
        self.assertNotIn(b'4',handle.writes)
        owner._finish_arduino_led_test()
        self.assertTrue(eventually(lambda:b'4' in handle.writes))
        self.assertNotIn(b'1',handle.writes); self.assertFalse(owner._arduino_chase_active)

    def test_startup_latest_unavailable_status_overrides_old_available_snapshot(self):
        owner,writer,handle=self.accepted_owner(midi=True)
        self.assertTrue(eventually(lambda:b'5' in handle.writes))
        owner.midi_available=False; owner._update_startup_leds(); owner._finish_arduino_led_test()
        self.assertTrue(eventually(lambda:b'1' in handle.writes))
        self.assertEqual(handle.writes[-2:],[b'4',b'1'])

    def test_startup_never_starts_chase_when_any_playback_test_calibration_show_active(self):
        for state in ('playback','midi_test','calibration','show'):
            with self.subTest(state=state):
                env=environment(); owner=owner_for(env); owner.is_live_mode=True
                owner._save_arduino_port=lambda port:None
                if state=='playback': owner._has_active_playback=lambda:True
                elif state=='midi_test': owner.running_test_port=1
                elif state=='calibration': owner.calib_loop_worker=types.SimpleNamespace(isRunning=lambda:True)
                else: owner._active_sync_show_session='show'
                handle=Handle('COM12'); owner._accept_arduino_connection(handle,startup=True)
                writer=owner._arduino_writer
                try:
                    self.assertFalse(writer.chase_pending()); self.assertFalse(owner._arduino_chase_active); self.assertEqual(handle.writes,[])
                finally:
                    writer.close(); self.assertTrue(writer.released.wait(1))

    def test_latest_startup_status_replaces_an_already_queued_restore_tail(self):
        env=environment(); handle=BlockingLedHandle(block=b'4'); writer=env['ArduinoSerialWriter'](handle)
        self.addCleanup(lambda:(handle.release.set(),writer.close(),writer.released.wait(1)))
        writer.test_chase(seconds=0.02,restore_commands=['1'])
        self.assertTrue(handle.entered.wait(1))
        self.assertTrue(writer.set_chase_restore([])); handle.release.set()
        self.assertTrue(eventually(lambda:not writer.chase_pending()))
        self.assertNotIn(b'1',handle.writes); self.assertEqual(handle.state,set())

    def test_startup_finished_notice_waits_for_probe_cleanup_and_chase(self):
        env=environment(); owner=owner_for(env)
        owner._startup_hardware_started=True; owner._startup_poll_timer.start()
        owner._arduino_operation=object(); owner._arduino_operation_kind='startup'
        owner._maybe_finish_startup_hardware()
        self.assertFalse(owner._startup_hardware_announced); self.assertTrue(owner._startup_poll_timer.active)
        owner._arduino_operation=None; owner._arduino_chase_active=True; owner._arduino_led_test_kind='startup'
        owner._maybe_finish_startup_hardware(); self.assertFalse(owner._startup_hardware_announced)
        owner._arduino_chase_active=False; owner._arduino_led_test_kind=None
        owner._maybe_finish_startup_hardware()
        self.assertTrue(owner._startup_hardware_announced); self.assertFalse(owner._startup_poll_timer.active)


class ShutdownAndPersistenceReviewTests(unittest.TestCase):
    def test_malformed_and_non_object_session_saves_preserve_original_and_report(self):
        env=environment(); messages=[]
        owner=types.SimpleNamespace(status_label=types.SimpleNamespace(setText=messages.append))
        with tempfile.TemporaryDirectory(prefix='arduino-panel-') as directory:
            path=Path(directory)/'session.json'; env['SESSION_FILE']=str(path)
            for original in ('{broken','[1,2]'):
                path.write_text(original,encoding='utf-8')
                self.assertFalse(env['save_session'](owner))
                self.assertEqual(path.read_text(),original); self.assertIn('preserved',messages[-1])
                self.assertEqual([p.name for p in Path(directory).iterdir()],['session.json'])

    def test_close_runs_every_normal_cleanup_after_either_save_raises(self):
        env=environment()
        for bad_saver in ('session','config'):
            with self.subTest(bad_saver=bad_saver):
                calls=[]
                def save(name):
                    calls.append(name)
                    if name==bad_saver: raise OSError('mock save failure')
                owner=types.SimpleNamespace(_app_is_closing=False,
                    _startup_poll_timer=types.SimpleNamespace(stop=lambda:calls.append('timer')),
                    _shutdown_arduino_panel=lambda:calls.append('arduino'),_startup_probes={},
                    save_session=lambda:save('session'),save_config=lambda:save('config'),
                    hotkey_listener=types.SimpleNamespace(stop=lambda:calls.append('hotkey stop'),wait=lambda:calls.append('hotkey wait')),
                    stop_all_activity=lambda:calls.append('playback'),xr12_controller=types.SimpleNamespace(shutdown=lambda:calls.append('xr12')))
                env['closeEvent'](owner,types.SimpleNamespace(accept=lambda:calls.append('accepted')))
                for expected in ('session','config','arduino','hotkey stop','hotkey wait','playback','xr12','accepted'):
                    self.assertIn(expected,calls)

    def test_actual_malformed_session_does_not_bypass_main_shutdown(self):
        env=environment(); calls=[]
        with tempfile.TemporaryDirectory(prefix='arduino-panel-') as directory:
            path=Path(directory)/'session.json'; path.write_text('{bad',encoding='utf-8'); env['SESSION_FILE']=str(path)
            owner=types.SimpleNamespace(_app_is_closing=False,
                status_label=types.SimpleNamespace(setText=lambda value:calls.append('reported')),
                _startup_poll_timer=types.SimpleNamespace(stop=lambda:None),_shutdown_arduino_panel=lambda:calls.append('arduino'),
                _startup_probes={},save_config=lambda:calls.append('config'),
                hotkey_listener=types.SimpleNamespace(stop=lambda:calls.append('hotkeys'),wait=lambda:None),
                stop_all_activity=lambda:calls.append('playback'),xr12_controller=types.SimpleNamespace(shutdown=lambda:calls.append('xr12')))
            owner.save_session=types.MethodType(env['save_session'],owner)
            env['closeEvent'](owner,types.SimpleNamespace(accept=lambda:calls.append('accepted')))
            self.assertEqual(path.read_text(),'{bad')
            for expected in ('reported','arduino','config','hotkeys','playback','xr12','accepted'): self.assertIn(expected,calls)

    def test_normal_session_write_failure_preserves_valid_original_and_removes_temp(self):
        env=environment(); messages=[]
        class Value:
            def text(self): return '120'
            def value(self): return 1
            def isChecked(self): return False
            def currentText(self): return '20'
        owner=types.SimpleNamespace(_arduino_last_port='COM12',tracks=[],undo_history=[],test_track_path=None,
            current_table_font_size=16,count_in_bg_color='red',count_in_font_size=100,track_play_bg_color='green',track_play_font_size=80,
            status_label=types.SimpleNamespace(setText=messages.append))
        for name in ('title_label','test_track_bpm_input','midi_offset_slider','high_precision_timing_radio','count_in_combo','streamdeck_font_spinbox','scrub_lock_checkbox','loop_checkbox','loop_bpm_spinbox','loop_start_bar_spinbox','loop_end_bar_spinbox'):
            setattr(owner,name,Value())
        with tempfile.TemporaryDirectory(prefix='arduino-panel-') as directory:
            path=Path(directory)/'session.json'; original='{"unknown":123,"arduino_last_port":"COM5"}'
            path.write_text(original,encoding='utf-8'); env['SESSION_FILE']=str(path)
            with patch.object(os,'replace',side_effect=PermissionError('mock save denied')):
                self.assertFalse(env['save_session'](owner))
            self.assertEqual(path.read_text(),original); self.assertIn('mock save denied',messages[-1])
            self.assertEqual([p.name for p in Path(directory).iterdir()],['session.json'])

    def test_reused_verified_connection_retries_failed_save_without_reopen(self):
        env=environment(); owner=owner_for(env); calls=[]
        owner.arduino_serial=Handle('COM12'); owner._arduino_writer=FakeWriter([])
        owner._arduino_devices=[dict(port='COM12',serial=True)]
        def save(port): calls.append(port); owner._arduino_last_port=port
        owner._save_arduino_port=save
        self.assertTrue(owner._connect_selected_arduino('COM12'))
        self.assertEqual(calls,['COM12']); self.assertEqual(owner._arduino_last_port,'COM12')
        self.assertIsNone(owner._arduino_operation)

    def test_disconnected_row_no_longer_claims_current_connection(self):
        env=environment(); owner=owner_for(env); handle=Handle('COM5')
        owner.arduino_serial=handle; owner._arduino_writer=env['ArduinoSerialWriter'](handle)
        owner._arduino_port_results['COM5']='Connected — verified'
        owner._disconnect_arduino(); closing=owner._arduino_closing_writer
        self.assertTrue(closing.released.wait(1)); owner._poll_arduino_panel()
        self.assertTrue(owner._arduino_port_results['COM5'].startswith('Disconnected'))
        self.assertIsNone(owner.arduino_serial)


class PanelRestoreLifecycleTests(unittest.TestCase):
    def make_blocked_test(self, blocked_command, complete):
        env=environment(); owner=owner_for(env); handle=BlockingLedHandle(block=blocked_command)
        writer=env['ArduinoSerialWriter'](handle)
        owner.arduino_serial=handle; owner._arduino_writer=writer
        def cleanup():
            handle.release.set(); writer.close(); self.assertTrue(writer.released.wait(1))
        self.addCleanup(cleanup)
        writer.send('1'); writer.send('2')
        self.assertTrue(eventually(lambda:handle.state=={'1','2'}))
        self.assertTrue(owner._test_arduino_leds())
        self.assertTrue(eventually(lambda:b'5' in handle.writes))
        if blocked_command==b'5': self.assertTrue(handle.entered.wait(1))
        if complete=='finish': owner._finish_arduino_led_test()
        else: owner._cancel_arduino_operation()
        self.assertFalse(owner._arduino_chase_active)
        self.assertTrue(handle.entered.wait(1))
        return owner,writer,handle

    def assert_restore_completes(self, writer, handle):
        handle.release.set()
        self.assertTrue(eventually(lambda:not writer.chase_pending()))
        self.assertIn(b'4',handle.writes,'Panel close dropped the pending all-off restore')
        self.assertEqual(handle.writes[-2:],[b'1',b'2'])
        self.assertEqual(handle.state,{'1','2'})
        self.assertEqual(handle.writes.count(b'5'),1)

    def test_finish_or_cancel_then_panel_close_preserves_restore_while_chase_write_blocked(self):
        for complete in ('finish','cancel'):
            with self.subTest(complete=complete):
                owner,writer,handle=self.make_blocked_test(b'5',complete)
                owner._arduino_panel_hidden()
                self.assert_restore_completes(writer,handle)

    def test_finish_or_cancel_then_panel_close_preserves_restore_while_off_write_blocked(self):
        for complete in ('finish','cancel'):
            with self.subTest(complete=complete):
                owner,writer,handle=self.make_blocked_test(b'4',complete)
                owner._arduino_panel_hidden()
                self.assert_restore_completes(writer,handle)

    def test_repeated_close_and_cancel_preserve_pending_restore_and_keep_queue_bounded(self):
        for blocked in (b'5',b'4'):
            for complete in ('finish','cancel'):
                with self.subTest(blocked=blocked,complete=complete):
                    owner,writer,handle=self.make_blocked_test(blocked,complete)
                    for _ in range(5):
                        owner._arduino_panel_hidden(); owner._cancel_arduino_operation()
                    with writer._condition:
                        self.assertLessEqual(len(writer._commands),3)
                    self.assert_restore_completes(writer,handle)

    def test_activity_after_repeated_panel_closes_still_invalidates_all_unsent_restore(self):
        for blocked in (b'5',b'4'):
            for complete in ('finish','cancel'):
                with self.subTest(blocked=blocked,complete=complete):
                    owner,writer,handle=self.make_blocked_test(blocked,complete)
                    for _ in range(3):
                        owner._arduino_panel_hidden(); owner._cancel_arduino_operation()
                    barrier=handle.writes.index(blocked)
                    owner._arduino_before_activity(); owner.send_led_command('4'); owner.send_led_command('3')
                    handle.release.set()
                    self.assertTrue(eventually(lambda:handle.state=={'3'}))
                    self.assertNotIn(b'1',handle.writes[barrier+1:]); self.assertNotIn(b'2',handle.writes[barrier+1:])
                    self.assertFalse(writer.chase_pending())


if __name__ == '__main__':
    unittest.main(verbosity=2)
