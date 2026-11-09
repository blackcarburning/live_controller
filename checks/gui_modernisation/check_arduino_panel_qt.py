"""Real PyQt6 offline panel checks; never imports/launches LiveController.
Only the explicitly named Windows metadata test enumerates actual devices.
Serial opens are forbidden; connection/LED tests use fake handles.
"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import ast
from collections import deque
import ctypes
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import types
import unittest
import uuid
from unittest.mock import patch
import serial
from serial.tools import list_ports
from PyQt6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView)
from PyQt6.QtCore import Qt, QTimer, QT_VERSION_STR, PYQT_VERSION_STR
from PyQt6.QtTest import QTest

SOURCE_PATH = Path(os.environ.get('CONTROLLER_SOURCE', str(Path(__file__).parent.parent / 'live_controller.py')))
TREE = ast.parse(SOURCE_PATH.read_bytes())
CLASSES = {n.name:n for n in TREE.body if isinstance(n, ast.ClassDef)}
FUNCTIONS = {n.name:n for n in TREE.body if isinstance(n, ast.FunctionDef)}
OWNER = {n.name:n for n in CLASSES['LiveController'].body if isinstance(n, ast.FunctionDef)}
ENV = globals().copy()
ENV.update(ARDUINO_BAUD=9600, ARDUINO_TARGET_ID='LED_TEST_PRO_MINI_01', ARDUINO_PROBE_CMD=b'?\n')
names = [n for n in OWNER if 'arduino' in n or n in ('send_led_command','_update_startup_leds','_maybe_finish_startup_hardware')]
nodes = [CLASSES['ArduinoConnectionAttempt'], FUNCTIONS['_arduino_serial_target'],
    FUNCTIONS['_arduino_windows_lpt_devices'], FUNCTIONS['_arduino_list_devices'],
    CLASSES['ArduinoSerialWriter'], CLASSES['ArduinoPanel']] + [OWNER[n] for n in names]
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<isolated actual Arduino panel>', 'exec'), ENV)
REAL_ENUMERATION = ENV['_arduino_list_devices']
ROWS = [dict(port='COM5',description='USB Serial Device (COM5)',hwid='USB VID:PID=2341:8037',serial=True),
    dict(port='COM9',description='Bluetooth Serial (COM9)',hwid='MOCK',serial=True),
    dict(port='LPT1',description='Printer port (LPT1)',hwid='',serial=False)]
APP = QApplication.instance() or QApplication([])
APP.setStyle('Fusion')
from PyQt6.QtGui import QFont, QFontDatabase
# Windows offscreen has no font database by default. Load a font only into
# this isolated test process; no system font installation/change is made.
if os.name == 'nt' and not QFontDatabase.families():
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
    assert font_id >= 0, 'Cannot render isolated preview with a readable font'
    APP.setFont(QFont('Segoe UI', 10))
for node in TREE.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DARK_STYLESHEET' for t in node.targets):
        APP.setStyleSheet(ast.literal_eval(node.value))
SLOT_ERRORS = []
sys.excepthook = lambda typ, value, tb: SLOT_ERRORS.append(repr(value))

class FakeSerial:
    def __init__(self, port):
        self.port=port; self.is_open=True; self.writes=[]; self.closed=threading.Event()
    def write(self, data): self.writes.append(data); return len(data)
    def close(self): self.is_open=False; self.closed.set()

class QtChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='arduino-panel-qt-')
        self.session = Path(self.tmp.name)/'session.json'
        self.session.write_text(json.dumps({'unrelated':{'keep':[1,2]}}), encoding='utf-8')
        ENV['SESSION_FILE'] = str(self.session)
        ENV['_arduino_list_devices'] = lambda attempt: dict(rows=[dict(row) for row in ROWS],warnings=[])
        self.handles=[]
        methods={n:ENV[n] for n in names}
        def fake_probe(context, attempt, selected_port=None):
            handle=FakeSerial(selected_port or 'COM5'); self.handles.append(handle); return handle
        methods['_connect_arduino'] = fake_probe
        self.owner=type('IsolatedPanelOwner',(QWidget,),methods)()
        o=self.owner
        o._app_is_closing=False; o.is_live_mode=False; o.arduino_connected=True
        o.arduino_serial=None; o._arduino_last_port='COM5'; o._arduino_chase_active=False
        o.running_test_port=None; o.calib_loop_worker=None; o._active_sync_show_session=None
        o._has_active_playback=lambda:False; o._hardware_status={}; o.midi_available=True
        o._refresh_hardware_status=lambda:None
        o._init_arduino_panel()
        self.forbid=patch.object(serial,'Serial',side_effect=AssertionError('Real serial open forbidden by offline test'))
        self.forbid.start()
        SLOT_ERRORS.clear()

    def pump(self, predicate, seconds=3):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            APP.processEvents()
            if predicate():
                self.assertEqual(SLOT_ERRORS,[],'Qt slot raised an exception')
                return
            QTest.qWait(5)
        self.fail('Timed out waiting for isolated Qt state')

    def panel(self):
        self.owner._show_arduino_panel()
        self.pump(lambda:self.owner._arduino_listing is None)
        return self.owner._arduino_panel

    def tearDown(self):
        self.owner._app_is_closing=True
        self.owner._shutdown_arduino_panel()
        for h in self.handles: self.assertTrue(h.closed.wait(2),'Fake native handle leaked')
        if self.owner._arduino_panel: self.owner._arduino_panel.hide()
        self.owner.deleteLater(); APP.processEvents()
        self.forbid.stop(); self.tmp.cleanup()
        self.assertEqual(SLOT_ERRORS,[],'Qt slot raised an exception')

    def test_actual_table_selection_lpt_flags_and_modeless_construction(self):
        p=self.panel()
        self.assertTrue(p.isVisible()); self.assertFalse(p.isModal())
        self.assertEqual(p.table.rowCount(),3)
        self.assertEqual(p.selected_port(),'COM5')
        self.assertTrue(p.connect_button.isEnabled())
        item=p.table.item(2,0)
        self.assertIsNone(item.data(Qt.ItemDataRole.UserRole))
        self.assertFalse(item.flags() & Qt.ItemFlag.ItemIsEnabled)
        self.assertFalse(item.flags() & Qt.ItemFlag.ItemIsSelectable)
        p.table.setCurrentCell(2,0); p.refresh_state()
        # Real Qt refuses to make a disabled row current, retaining the last
        # valid COM selection; it must never expose LPT as a connection target.
        self.assertNotEqual(p.selected_port(),'LPT1')
        p.table.clearSelection(); p.table.setCurrentCell(-1,-1); p.refresh_state()
        self.assertIsNone(p.selected_port())
        self.assertFalse(p.connect_button.isEnabled())
        p.table.selectRow(1); p.refresh_state()
        self.assertEqual(p.selected_port(),'COM9')
        self.assertTrue(p.connect_button.isEnabled())
        self.assertEqual(self.handles,[])
        if os.environ.get('ARDUINO_PANEL_SCREENSHOT'):
            p.grab().save(str(SOURCE_PATH.parent/'arduino-panel-preview.png'))

    def test_real_button_signals_connect_reuse_chase_timer_and_disconnect(self):
        p=self.panel(); p.connect_button.click()
        self.pump(lambda:self.owner._arduino_operation is None and self.owner.arduino_serial is not None)
        self.assertEqual(self.owner._arduino_last_port,'COM5')
        data=json.loads(self.session.read_text(encoding='utf-8'))
        self.assertEqual(data,{'unrelated':{'keep':[1,2]},'arduino_last_port':'COM5'})
        self.assertTrue(p.led_button.isEnabled())
        p.connect_button.click(); APP.processEvents()
        self.assertEqual(len(self.handles),1,'Live validated connection reopened')
        p.led_button.click()
        self.pump(lambda:b'5' in self.handles[0].writes)
        self.assertTrue(self.owner._arduino_chase_active)
        self.assertFalse(p.connect_button.isEnabled())
        self.pump(lambda:not self.owner._arduino_chase_active,seconds=3.2)
        self.assertIn(b'4',self.handles[0].writes)
        p.refresh_state(); p.disconnect_button.click()
        self.pump(lambda:self.owner._arduino_closing_writer is None and self.owner.arduino_serial is None)
        self.assertTrue(self.handles[0].closed.is_set())

    def test_finish_then_real_close_signal_keeps_slow_native_restoration(self):
        p=self.panel(); o=self.owner
        entered=threading.Event(); release=threading.Event()
        handle=FakeSerial('COM5'); self.handles.append(handle); base_write=handle.write
        def blocking_write(data):
            count=base_write(data)
            if data==b'5':
                entered.set()
                if not release.wait(3): raise TimeoutError('Fake chase write was not released')
            return count
        handle.write=blocking_write
        self.addCleanup(release.set)
        try:
            o._accept_arduino_connection(handle); o.send_led_command('1')
            self.pump(lambda:handle.writes[-1:]==[b'1'])
            p.refresh_state(); p.led_button.click(); self.pump(entered.is_set)
            o._finish_arduino_led_test()
            next(b for b in p.findChildren(QPushButton) if b.text()=='Close').click()
            APP.processEvents(); self.assertFalse(p.isVisible())
            release.set(); self.pump(lambda:not o._arduino_writer.chase_pending())
            self.assertIn(b'4',handle.writes[handle.writes.index(b'5')+1:])
            self.assertEqual(handle.writes[-1],b'1')
        finally:
            release.set()

    def test_startup_chase_real_timer_preserves_default_live_and_latest_midi(self):
        p=self.panel(); o=self.owner; o.is_live_mode=True
        handle=FakeSerial('COM5'); self.handles.append(handle)
        o._accept_arduino_connection(handle,startup=True)
        self.pump(lambda:b'5' in handle.writes)
        self.assertTrue(o._arduino_chase_active)
        self.assertEqual(o._arduino_led_test_kind,'startup')
        p.refresh_state(); self.assertFalse(p.led_button.isEnabled())
        o.midi_available=False; o._update_startup_leds()
        self.pump(lambda:not o._arduino_chase_active and not o._arduino_writer.chase_pending(),seconds=3.3)
        self.pump(lambda:handle.writes[-1:]==[b'1'])
        self.assertEqual(handle.writes.count(b'5'),1)
        self.assertIn(b'4',handle.writes)
        self.assertTrue(o.is_live_mode)

    def test_live_mode_lock_and_escape_cancel_real_signal_path(self):
        p=self.panel(); self.owner.is_live_mode=True; p.refresh_state()
        self.assertFalse(p.connect_button.isEnabled()); self.assertFalse(p.led_button.isEnabled())
        self.assertFalse(self.owner._connect_selected_arduino('COM5'))
        self.assertEqual(self.handles,[])
        self.owner.is_live_mode=False
        entered=threading.Event(); release=threading.Event()
        def slow_probe(context,attempt,selected_port=None):
            entered.set(); release.wait(2); return None
        type(self.owner)._connect_arduino=slow_probe
        p.refresh_state(); p.connect_button.click()
        self.assertTrue(entered.wait(1))
        op=self.owner._arduino_operation
        QTest.keyClick(p,Qt.Key.Key_Escape); APP.processEvents()
        self.assertFalse(p.isVisible()); self.assertTrue(op.stopped())
        self.assertFalse(self.owner._connect_selected_arduino('COM9'))
        release.set(); self.pump(lambda:self.owner._arduino_operation is None)

    def test_close_button_and_reopen_keep_single_dialog(self):
        p=self.panel()
        button=next(b for b in p.findChildren(QPushButton) if b.text()=='Close')
        button.click(); APP.processEvents(); self.assertFalse(p.isVisible())
        self.owner._show_arduino_panel(); self.pump(lambda:self.owner._arduino_listing is None)
        self.assertIs(self.owner._arduino_panel,p); self.assertTrue(p.isVisible())
        self.assertEqual(self.handles,[])

    @unittest.skipUnless(os.name=='nt','Actual Windows metadata enumeration')
    def test_windows_setupapi_metadata_without_serial_opens(self):
        op=ENV['ArduinoConnectionAttempt'](REAL_ENUMERATION,timeout_seconds=8,dispose=lambda result:None)
        self.pump(op.released,seconds=9)
        done,result,error=op.poll()
        self.assertTrue(done); self.assertIsNone(error)
        self.assertEqual(result['warnings'],[])
        self.assertTrue(all('port' in r and 'serial' in r for r in result['rows']))
        print('WINDOWS_METADATA='+json.dumps(result),flush=True)

if __name__=='__main__':
    print('OFFSCREEN_QT='+json.dumps({'platform':APP.platformName(),'qt':QT_VERSION_STR,'pyqt':PYQT_VERSION_STR}),flush=True)
    unittest.main(verbosity=2)
