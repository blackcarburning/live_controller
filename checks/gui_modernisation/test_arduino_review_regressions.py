"""Independent hardware-free regressions for review-discovered edge cases."""
import ast
from collections import deque
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest

SOURCE=Path(os.environ.get('CONTROLLER_SOURCE',str(Path(__file__).with_name('controller-arduino-panel.py'))))
TREE=ast.parse(SOURCE.read_bytes())
CLASSES={n.name:n for n in TREE.body if isinstance(n,ast.ClassDef)}
METHODS={n.name:n for n in CLASSES['LiveController'].body if isinstance(n,ast.FunctionDef)}
ENV=dict(deque=deque,threading=threading,time=time,json=json,os=os,tempfile=tempfile)
exec(compile(ast.Module(body=[CLASSES['ArduinoSerialWriter'],METHODS['save_session'],METHODS['closeEvent'],METHODS['_stop_arduino_led_test'],METHODS['_arduino_panel_hidden']],type_ignores=[]),'<review regressions>','exec'),ENV)

def wait_for(predicate,seconds=2):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(0.001)
    raise AssertionError('Timed out waiting for mocked writer state')

class BlockingSerial:
    def __init__(self,block):
        self.port='COM5'; self.block=block; self.started=threading.Event(); self.release=threading.Event()
        self.writes=[]; self.state=set(); self._blocked=False; self.closed=False; self._lock=threading.Lock()
    def write(self,data):
        with self._lock:
            self.writes.append(data)
            should_block=(not self._blocked and self.block(data))
            if should_block: self._blocked=True
        if should_block:
            self.started.set()
            if not self.release.wait(4): raise TimeoutError('Mock write was not released')
        with self._lock:
            for value in data.decode('ascii'):
                if value=='4': self.state.clear()
                elif value in '1236': self.state.add(value)
        return len(data)
    def close(self): self.closed=True

class QueueReviewTests(unittest.TestCase):
    def writer(self,block=lambda data:data==b'1'):
        s=BlockingSerial(block); w=ENV['ArduinoSerialWriter'](s)
        self.addCleanup(lambda:self.cleanup(w,s))
        return w,s
    def cleanup(self,w,s):
        s.release.set(); w.close(); self.assertTrue(w.released.wait(2),'Writer cleanup did not finish')

    def cancel_before_dispatch(self,restore):
        w,s=self.writer(); w.send('1'); self.assertTrue(s.started.wait(1))
        self.assertTrue(w.test_chase(seconds=10))
        w.finish_chase(restore=restore); w.send('3'); s.release.set()
        wait_for(lambda:b'3' in s.writes)
        self.assertNotIn(b'5',s.writes,'Cancelled chase was dispatched after cancellation')
    def test_cancel_before_dispatch_without_restore(self): self.cancel_before_dispatch(False)
    def test_cancel_before_dispatch_with_restore(self): self.cancel_before_dispatch(True)

    def test_new_activity_discards_undispatched_chase(self):
        w,s=self.writer(); w.send('1'); self.assertTrue(s.started.wait(1))
        self.assertTrue(w.test_chase(seconds=10)); w.send('3'); s.release.set()
        wait_for(lambda:b'3' in s.writes)
        self.assertNotIn(b'5',s.writes,'New activity did not invalidate queued chase')

    def test_cancel_removes_restore_tail_after_first_off_is_inflight(self):
        w,s=self.writer(block=lambda data:data==b'4')
        w.send('1'); w.send('2'); wait_for(lambda:b'2' in s.writes)
        self.assertTrue(w.test_chase(seconds=0.01))
        self.assertTrue(s.started.wait(2),'Automatic restore did not start')
        first_off=s.writes.index(b'4')
        w.finish_chase(restore=False); w.send('4'); w.send('3'); s.release.set()
        wait_for(lambda:b'3' in s.writes)
        self.assertNotIn(b'1',s.writes[first_off+1:],'Stale restore LED1 was dispatched')
        self.assertNotIn(b'2',s.writes[first_off+1:],'Stale restore LED2 was dispatched')
        self.assertEqual(s.state,{'3'})

    def panel_owner(self,w):
        o=types.SimpleNamespace(_arduino_writer=w,_arduino_chase_active=True,
            _arduino_led_test_kind='manual',_arduino_led_timer=types.SimpleNamespace(stop=lambda:None),
            _arduino_listing=None,_arduino_operation_kind=None,_arduino_pending_port=None)
        o._stop_arduino_led_test=types.MethodType(ENV['_stop_arduino_led_test'],o)
        return o

    def test_finish_then_immediate_panel_close_preserves_restore_while_chase_blocked(self):
        w,s=self.writer(block=lambda data:data==b'5')
        w.send('1'); wait_for(lambda:s.state=={'1'})
        self.assertTrue(w.test_chase(seconds=10)); self.assertTrue(s.started.wait(1))
        o=self.panel_owner(w); o._stop_arduino_led_test(restore=True)
        self.assertFalse(o._arduino_chase_active)
        ENV['_arduino_panel_hidden'](o); ENV['_arduino_panel_hidden'](o)
        s.release.set(); wait_for(lambda:not w.chase_pending())
        self.assertIn(b'4',s.writes[s.writes.index(b'5')+1:],'Panel close discarded required all-off restoration')
        self.assertEqual(s.writes[-1],b'1','Original LED snapshot was not restored')
        self.assertEqual(s.state,{'1'})

    def test_finish_then_immediate_panel_close_preserves_restore_tail_while_off_blocked(self):
        w,s=self.writer(block=lambda data:data==b'4')
        w.send('1'); wait_for(lambda:s.state=={'1'})
        self.assertTrue(w.test_chase(seconds=0.01)); self.assertTrue(s.started.wait(2))
        o=self.panel_owner(w); o._stop_arduino_led_test(restore=True)
        ENV['_arduino_panel_hidden'](o); s.release.set()
        wait_for(lambda:not w.chase_pending())
        self.assertEqual(s.writes[-1],b'1','Closing panel removed an unfinished restore tail')
        self.assertEqual(s.state,{'1'})

    def test_activity_still_invalidates_restore_after_finish_and_repeated_panel_close(self):
        w,s=self.writer(block=lambda data:data==b'5')
        w.send('1'); wait_for(lambda:s.state=={'1'})
        self.assertTrue(w.test_chase(seconds=10)); self.assertTrue(s.started.wait(1))
        o=self.panel_owner(w); o._stop_arduino_led_test(restore=True)
        ENV['_arduino_panel_hidden'](o); ENV['_arduino_panel_hidden'](o)
        o._stop_arduino_led_test(restore=False); w.send('4'); w.send('3')
        s.release.set(); wait_for(lambda:s.state=={'3'})
        self.assertNotIn(b'1',s.writes[s.writes.index(b'5')+1:],'New activity leaked a stale restoration')

    def test_backlog_compaction_reconciles_off_before_additive_leds(self):
        w,s=self.writer(); w.send('1'); self.assertTrue(s.started.wait(1))
        w.send('4')
        for _ in range(80): w.send('3')
        s.release.set(); wait_for(lambda:b'3' in s.writes)
        self.assertIn(b'4',s.writes,'Backlog compaction lost required all-off transition')
        self.assertEqual(s.state,{'3'},'Physical fake LEDs differ from latest requested state')

class ShutdownReviewTests(unittest.TestCase):
    def test_malformed_session_is_reported_without_overwrite_or_exception(self):
        with tempfile.TemporaryDirectory(prefix='arduino-review-session-') as folder:
            p=Path(folder)/'session.json'; original=b'{bad'; p.write_bytes(original)
            env=ENV.copy(); env['SESSION_FILE']=str(p)
            exec(compile(ast.Module(body=[METHODS['save_session']],type_ignores=[]),'<malformed session>','exec'),env)
            owner=types.SimpleNamespace(status_label=types.SimpleNamespace(setText=lambda text:None), _arduino_set_status=lambda text:None, _arduino_panel=None)
            env['save_session'](owner)
            self.assertEqual(p.read_bytes(),original,'Damaged session was replaced without consent')

    def check_close(self,bad_saver):
        calls=[]
        def save(name):
            calls.append(name)
            if name==bad_saver: raise OSError('Simulated save failure')
        owner=types.SimpleNamespace(_app_is_closing=False,
            _startup_poll_timer=types.SimpleNamespace(stop=lambda:calls.append('startup_timer_stop')),
            _shutdown_arduino_panel=lambda:calls.append('arduino_shutdown'),_startup_probes={},
            save_session=lambda:save('save_session'),save_config=lambda:save('save_config'),
            hotkey_listener=types.SimpleNamespace(stop=lambda:calls.append('hotkey_stop'),wait=lambda:calls.append('hotkey_wait')),
            stop_all_activity=lambda:calls.append('playback_stop'),
            xr12_controller=types.SimpleNamespace(shutdown=lambda:calls.append('xr12_shutdown')),
            status_label=types.SimpleNamespace(setText=lambda text:None))
        event=types.SimpleNamespace(accept=lambda:calls.append('event_accepted'))
        ENV['closeEvent'](owner,event)
        for expected in ('arduino_shutdown','hotkey_stop','hotkey_wait','playback_stop','xr12_shutdown','event_accepted'):
            self.assertIn(expected,calls,f'{expected} was skipped after {bad_saver} failure')
        self.assertTrue(owner._app_is_closing)
    def test_close_cleans_up_even_when_session_save_fails(self): self.check_close('save_session')
    def test_close_cleans_up_even_when_config_save_fails(self): self.check_close('save_config')

if __name__=='__main__': unittest.main(verbosity=2)
