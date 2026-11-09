#!/usr/bin/env python3
"""Read-only AST-extracted controller DIALOG QA; NEVER import/run controller module.
Usage: python -B test_gui_modernisation_dialogs.py --candidate candidate.py --baseline baseline.py
       [--static-only] [--screenshots-dir EXISTING_EXPLICIT_OUTPUT_DIRECTORY]
Only optional PNG screenshots write data; no directory is created. No real timer/thread,
media canvas, process, serial/MIDI, hotkeys, config/session or app lifecycle is loaded.
"""
import argparse
import ast
import builtins
import copy
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import traceback
from types import SimpleNamespace

EXPECTED_CANDIDATE = '185516a9b7978198055a714c40e24286edd132ce4b457eb6bd774c13011b2a9a'
EXPECTED_BASELINE = '56a91df1849bc879584a1ec3cecec2cbdf8222282a21263758cb975c3363e4ee'
DIALOG_AST_PINS = {
    '_ui_role': '3fcd32ac2cbb1e553259285248b23de9ad5bb375a6fecf9844101a1b5bbd3234',
    '_ui_surface': '94c45ce587433b72c0f1c768a0f1220bd852cd8d59f45154de2aafed6fd841bb',
    '_ui_scroll_page': '76cf5a88207de6c6e222adcb7279f30ca8d26de3fc3809cfc6821591deea68f7',
    '_ui_fit_dialog': 'dfc583428176bf065adab4f8f605ef1d78912aeee8b8ca4e840087c4ab77b120',
    '_ui_scroll_layout': '0471517dd34b1a9b942eb3cc069b32cf5ea903840b872ca5baef5d3095feeb12',
    'ArduinoPanel': '92950961fa9f386b16aa668591408ff41db4f1054a254141b911b28195935581',
    'ZoomScaleDialog': '0a7490b3e19b97f0b0a31a5f85b2d79d96ae0c37f99b1f34164784b3682be370',
    'MultiZoomScaleDialog': 'e4ef6b7a2ba0af7024bce514f8662126cf5bf22ceb3c1b8d116857c1e8e692ed',
}
CLASSES = ('ArduinoPanel', 'ZoomScaleDialog', 'MultiZoomScaleDialog')
PURE = {'_default_zone', '_zoom_int', '_normalize_zone', '_migrate_zoom_config'}
CONSTANTS = {'NUM_ZONES', '_ZONE_COLORS', '_ZONE_INT_DEFAULTS', '_COMPOSITE_INT_DEFAULTS',
             'DEFAULT_VIDEO_SCREEN_NUMBER', 'ARDUINO_TARGET_ID', 'ARDUINO_BAUD', 'DARK_STYLESHEET'}
METHODS = {
    'ArduinoPanel': {'__init__', 'selected_port', 'set_devices', '_connect_selected', 'refresh_state', 'done', 'closeEvent'},
    'ZoomScaleDialog': {'__init__', '_setup_ui', '_apply_config'},
    'MultiZoomScaleDialog': {'__init__', '_setup_ui', '_load_config_to_ui', '_update_external_source_availability'},
}
REPORT = {'scope': 'AST-isolated dialogs only', 'limitations': [
    'Inert QWidget canvas stand-ins: no canvas painting, drag geometry or media validated.',
    'All non-builder dialog callbacks are recording stubs; no real preview/file/save/cancel lifecycle executed.',
    'PositionPoller and QTimer are inert QObject test doubles; no background work or timers run.',
    'Screen areas are controlled Python seams; Windows OS chrome/DPI still needs visual inspection.'
]}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def denied(*args, **kwargs):
    raise AssertionError('Forbidden external I/O reached in isolated dialog harness')


def parse_source(path, expected):
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    require(digest == expected, 'Frozen source mismatch: ' + str(path) + ': ' + digest)
    compile(data, str(path), 'exec')  # syntax only, no execution
    return ast.parse(data, filename=str(path)), digest


def class_node(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def method_node(tree, name, method):
    return next(node for node in class_node(tree, name).body if isinstance(node, ast.FunctionDef) and node.name == method)


def canonical_dump(node):
    # Retain reviewed empty fields consistently across Python 3.12 and 3.13.
    if sys.version_info >= (3, 13):
        return ast.dump(node, include_attributes=False, show_empty=True)
    return ast.dump(node, include_attributes=False)


def static_contracts(base, candidate):
    actual_pins = {n.name: hashlib.sha256(canonical_dump(n).encode()).hexdigest()
                   for n in candidate.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in DIALOG_AST_PINS}
    require(actual_pins == DIALOG_AST_PINS, 'Dialog/helper AST differs from frozen 185516 reference')
    REPORT['dialog_ast_pins'] = actual_pins
    rows = []
    semantic_methods = {'setRange', 'setValue', 'setChecked', 'setSuffix', 'setSpecialValueText',
                        'setDecimals', 'setSingleStep', 'addItems', 'setSelectionBehavior',
                        'setSelectionMode', 'setEditTriggers', 'setColumnCount', 'setHorizontalHeaderLabels'}
    for name in CLASSES:
        for method in METHODS[name]:
            b, c = method_node(base, name, method), method_node(candidate, name, method)
            def calls(node, members):
                return [ast.dump(n, include_attributes=False) for n in ast.walk(node)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in members]
            require(calls(b, {'connect'}) == calls(c, {'connect'}), name + '.' + method + ' connection AST changed')
            require(calls(b, semantic_methods) == calls(c, semantic_methods), name + '.' + method + ' control semantic AST changed')
        rows.append(name)
    for n in candidate.body:
        if isinstance(n, ast.FunctionDef) and (n.name in PURE or n.name.startswith('_ui_')):
            for x in ast.walk(n):
                require(not isinstance(x, (ast.Import, ast.ImportFrom)), 'Unexpected import in extracted helper')
    return {'passed': rows, 'checks': 'Frozen hashes, source compile, selected constructors/builders connect AST and numeric/item semantics'}


def qt_run(args, base_tree, cand_tree):
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
    except ImportError as error:
        REPORT['qt'] = {'status': 'BLOCKED', 'reason': str(error), 'action': 'Run the same script with verified Windows PyQt6 interpreter.'}
        return 2
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle('Fusion')
    initial_families = list(QtGui.QFontDatabase.families())
    REPORT['fonts'] = {'initial_family_count': len(initial_families), 'process_local_fallback': False}
    if not initial_families:
        # Read an existing Windows font into this process ONLY; never install a font.
        font_path = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'segoeui.ttf')
        font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
        require(font_id >= 0, 'Empty Qt font database and Segoe UI process-local fallback unavailable: ' + font_path)
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        require(bool(families), 'Segoe UI fallback returned no families')
        app.setFont(QtGui.QFont(families[0], 10))
        REPORT['fonts'].update(process_local_fallback=True, family=families[0], font_path=font_path)
    SLOT_ERRORS = []
    sys.excepthook = lambda kind, value, tb: SLOT_ERRORS.append(''.join(traceback.format_exception(kind, value, tb)))
    REPORT['runtime_import_requests'] = []

    def runtime_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Diagnose arguments BEFORE deciding. C-extension signal.connect may resolve
        # its already-loaded QMetaObject.Connection type via PyImport_ImportModule.
        # Source AST Import/ImportFrom is independently prohibited below.
        event = {'name': str(name), 'fromlist': list(fromlist or ()), 'level': level,
                 'caller_module': (globals or {}).get('__name__'), 'allowed': False}
        REPORT['runtime_import_requests'].append(event)
        print('QT_RUNTIME_IMPORT_REQUEST ' + json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)
        if args.diagnose_imports:
            raise AssertionError('Runtime import diagnostic (no import permitted): ' + repr(event))
        # Exact reviewed whitelist, and ONLY reuse already-loaded modules. No general
        # importer is invoked; serial/MIDI/app imports cannot enter this route.
        whitelist = {'PyQt6.QtCore': QtCore, 'functools': functools}
        module = whitelist.get(name) if level == 0 else None
        if module is None or sys.modules.get(name) is not module:
            raise AssertionError('Runtime import not whitelisted: ' + repr(event))
        event['allowed'] = True
        if fromlist or name == 'functools':
            return module
        package = sys.modules.get('PyQt6')
        require(package is not None, 'Qt package unexpectedly absent from sys.modules')
        return package
    alive = []
    outputs = []

    class FakeCanvas(QtWidgets.QWidget):
        region_changed = QtCore.pyqtSignal(int, int, int, int)
        handle_dragged = QtCore.pyqtSignal(str, int, int)
        output_changed = QtCore.pyqtSignal(int, int)
        drag_started = QtCore.pyqtSignal()
        drag_finished = QtCore.pyqtSignal()

        def __init__(self, color='#00e676', parent=None):
            super().__init__(parent)
            self.setMinimumSize(480, 270)
            self._region = (0, 0, 1920, 1080)
            self._output = (1920, 1080)
            self.color = color

        def set_region(self, *region):
            self._region = tuple(region)
            self.region_changed.emit(*self._region)

        def set_output(self, width, height):
            self._output = (width, height)
            self.output_changed.emit(width, height)

        def get_region(self):
            return self._region

        def get_output(self):
            return self._output

    class FakePoller(QtCore.QObject):
        position_updated = QtCore.pyqtSignal(float, float)

        def start(self):
            self.started_inertly = True

    class FakeTimer(QtCore.QObject):
        timeout = QtCore.pyqtSignal()

        def setSingleShot(self, value):
            self.single_shot = value

        def setInterval(self, value):
            self.interval = value

        def start(self, *args):
            self.started_inertly = True

        def stop(self):
            pass

        def isActive(self):
            return False

    class FakeOwner(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.calls = []
            self.arduino_serial = None
            self._arduino_last_port = 'COM7'
            self._arduino_operation = None
            self._arduino_closing_writer = None
            self._arduino_chase_active = False
            self._arduino_listing = None
            self._app_is_closing = False
            self._arduino_pending_port = None
            self._arduino_panel_status = 'Offline fake controller; no hardware access'
            self._arduino_list_status = 'Synthetic device rows only'
            self._arduino_port_results = {}
            self.reason = ''

        def _arduino_controls_blocked(self):
            return self.reason

        def __getattr__(self, name):
            if name in {'_refresh_arduino_devices', '_test_arduino_leds', '_disconnect_arduino',
                        '_cancel_arduino_operation', '_arduino_panel_hidden', '_connect_selected_arduino'}:
                return lambda *a, n=name: self.calls.append((n, a))
            raise AttributeError(name)

    def pump():
        app.processEvents()
        require(not SLOT_ERRORS, 'Qt callback exception: ' + repr(SLOT_ERRORS))

    def build_namespace(tree, size):
        class ScreenDialog(QtWidgets.QDialog):
            def screen(self):
                return SimpleNamespace(availableGeometry=lambda: QtCore.QRect(0, 0, *size))
        namespace = {n: getattr(QtWidgets, n) for n in dir(QtWidgets) if n.startswith('Q')}
        namespace.update({n: getattr(QtCore, n) for n in dir(QtCore) if n.startswith('Q')})
        namespace.update({n: getattr(QtGui, n) for n in dir(QtGui) if n.startswith('Q')})
        namespace.update({'__name__': 'isolated_dialog_qa', 'QDialog': ScreenDialog,
                          'Qt': QtCore.Qt, 'pyqtSignal': QtCore.pyqtSignal,
                          'QTimer': FakeTimer, 'PositionPoller': FakePoller,
                          'ZoomCropCanvas': FakeCanvas, 'StretchCanvas': FakeCanvas,
                          'tempfile': SimpleNamespace(mkdtemp=lambda **k: 'INERT_NOT_A_DIRECTORY'),
                          'os': SimpleNamespace(path=SimpleNamespace(join=lambda *p: '/'.join(p),
                                    isfile=lambda p: False, basename=lambda p: p.rsplit('/', 1)[-1])),
                          '_arduino_serial_target': lambda port: bool(re.fullmatch(r'COM[0-9]+', str(port), re.I))})
        safe_builtins = dict(vars(builtins))
        for name in ('open', 'eval', 'exec', 'compile', 'input'):
            safe_builtins[name] = denied
        safe_builtins['__import__'] = runtime_import
        namespace['__builtins__'] = safe_builtins
        extracted = []
        callbacks = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets):
                ast.literal_eval(node.value)  # reject arbitrary constant expressions
                extracted.append(copy.deepcopy(node))
            elif isinstance(node, ast.FunctionDef) and (node.name in PURE or node.name.startswith('_ui_')):
                extracted.append(copy.deepcopy(node))
            elif isinstance(node, ast.ClassDef) and node.name in CLASSES:
                clone = copy.deepcopy(node)
                callbacks[node.name] = [n.name for n in clone.body if isinstance(n, ast.FunctionDef) and n.name not in METHODS[node.name]]
                clone.body = [n for n in clone.body if not isinstance(n, ast.FunctionDef) or n.name in METHODS[node.name]]
                extracted.append(clone)
        module = ast.fix_missing_locations(ast.Module(body=extracted, type_ignores=[]))
        forbidden_roots = {'serial', 'rtmidi', 'keyboard', 'ctypes', 'threading', 'subprocess', 'socket', 'requests', 'urllib'}
        for node in ast.walk(module):
            require(not isinstance(node, (ast.Import, ast.ImportFrom)), 'Imports not allowed in extracted AST')
            require(not (isinstance(node, ast.Name) and node.id in forbidden_roots), 'Forbidden dependency in extracted AST')
        exec(compile(module, '<selected-safe-dialog-AST>', 'exec'), namespace)
        for class_name, names in callbacks.items():
            cls = namespace[class_name]
            for method in names:
                def callback(self, *a, _name=method, **kw):
                    self._qa_calls.append((_name, a))
                    if _name == 'closeEvent' and a:
                        a[0].accept()
                setattr(cls, method, callback)
        return namespace

    def widget_contract(dialog):
        result = {}
        def describe(widget):
            data = {'class': type(widget).__name__}
            if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox, QtWidgets.QSlider)):
                data.update(minimum=widget.minimum(), maximum=widget.maximum(), value=widget.value())
            if isinstance(widget, QtWidgets.QAbstractSpinBox):
                data.update(suffix=widget.suffix(), special=widget.specialValueText())
            if isinstance(widget, QtWidgets.QAbstractButton):
                data.update(text=widget.text(), checked=widget.isChecked(), enabled=widget.isEnabled())
            if isinstance(widget, QtWidgets.QComboBox):
                data.update(items=[(widget.itemText(i), widget.itemData(i)) for i in range(widget.count())], index=widget.currentIndex())
            if isinstance(widget, QtWidgets.QTabWidget):
                data.update(tabs=[widget.tabText(i) for i in range(widget.count())], index=widget.currentIndex())
            signals = {}
            for signal_name in ('clicked', 'toggled', 'stateChanged', 'valueChanged', 'currentIndexChanged', 'sliderMoved', 'sliderReleased'):
                signal = getattr(widget, signal_name, None)
                if signal is not None:
                    try:
                        signals[signal_name] = widget.receivers(signal)
                    except TypeError:
                        pass
            data['signal_receiver_counts'] = signals
            return data
        for name, value in vars(dialog).items():
            if isinstance(value, QtWidgets.QWidget):
                result[name] = describe(value)
            elif isinstance(value, list) and value and all(isinstance(x, QtWidgets.QWidget) for x in value):
                result[name] = [describe(x) for x in value]
        radios = dialog.findChildren(QtWidgets.QRadioButton)
        result['radio_parent_grouping'] = [[i, j] for i, a in enumerate(radios) for j, b in enumerate(radios) if i < j and a.parent() is b.parent()]
        return result

    def make(namespace, name):
        cls = namespace[name]
        cls._qa_calls = []
        if name == 'ArduinoPanel':
            owner = FakeOwner()
            alive.append(owner)
            dialog = cls(owner)
        else:
            parent = QtWidgets.QWidget()
            alive.append(parent)
            dialog = cls({}, parent=parent)
        alive.append(dialog)
        return dialog

    def assert_numeric_and_radios(dialog, name, zones):
        if name == 'ZoomScaleDialog':
            require((dialog._x_sb.value(), dialog._y_sb.value(), dialog._w_sb.value(), dialog._h_sb.value()) == (0, 0, 1920, 1080), 'Single-zone initial crop')
            require(dialog._sw_sb.value() == dialog._sh_sb.value() == -1, 'Single-zone auto scale')
            return
        if name != 'MultiZoomScaleDialog':
            return
        require(dialog._tabs.count() == zones + 2, 'Tab count')
        require(dialog._COMP_TAB_INDEX == zones and dialog._FINAL_TAB_INDEX == zones + 1, 'Tab constants')
        for i in range(zones):
            require(dialog._zone_x_sbs[i].minimum() == 0 and dialog._zone_x_sbs[i].maximum() == 99999, 'Crop range')
            require(dialog._zone_offset_y_sbs[i].minimum() == -5000 and dialog._zone_offset_y_sbs[i].maximum() == 5000, 'Offset range')
            require(dialog._zone_sw_sbs[i].minimum() == -1 and dialog._zone_sw_sbs[i].value() == -1, 'Auto scale range/value')
            require(dialog._zone_border_sbs[i].minimum() == 0 and dialog._zone_border_sbs[i].maximum() == 500, 'Border range')
            crop, stretch = dialog._zone_mode_crop_rbs[i], dialog._zone_mode_stretch_rbs[i]
            require(crop.parent() is stretch.parent(), 'Zone radio parents')
            others = [(x.isChecked(), y.isChecked()) for x, y in zip(dialog._zone_mode_crop_rbs, dialog._zone_mode_stretch_rbs)]
            stretch.setChecked(True)
            require(stretch.isChecked() and not crop.isChecked() and dialog._zone_stacked[i].currentIndex() == 1, 'Zone radio exclusivity/stack')
            for j, (x, y) in enumerate(zip(dialog._zone_mode_crop_rbs, dialog._zone_mode_stretch_rbs)):
                if j != i:
                    require((x.isChecked(), y.isChecked()) == others[j], 'Cross-zone radio interference')
            crop.setChecked(True)
            require(not stretch.isChecked() and dialog._zone_stacked[i].currentIndex() == 0, 'Crop return path')
        dialog._stitch_v.setChecked(True)
        require(not dialog._stitch_h.isChecked(), 'Stitch exclusivity')
        dialog._stitch_h.setChecked(True)
        dialog._comp_mode_stretch_rb.setChecked(True)
        require(not dialog._comp_mode_crop_rb.isChecked() and dialog._comp_stacked.currentIndex() == 1, 'Composite radio/stack')
        dialog._comp_mode_crop_rb.setChecked(True)
        require(dialog._comp_stacked.currentIndex() == 0, 'Composite crop return')
        require(dialog._ext_source_combo.count() == 2 and not dialog._ext_source_combo.model().item(1).isEnabled(), 'No-video external source remains disabled')

    def exercise_fixture_and_callbacks(dialog, namespace, name):
        if name == 'ArduinoPanel':
            return None
        before = len(dialog._qa_calls)
        for attr, target in (('_select_btn', '_select_video'), ('_play_btn', '_play'),
                             ('_pause_btn', '_pause'), ('_capture_btn', '_capture_frame'),
                             ('_ok_btn', '_ok'), ('_cancel_btn', '_cancel')):
            getattr(dialog, attr).clicked.emit(False)
            require(dialog._qa_calls[-1][0] == target, 'Safe callback route: ' + attr)
        if name == 'ZoomScaleDialog':
            dialog._apply_config({'crop_x': 14, 'crop_y': 27, 'crop_w': 960, 'crop_h': 540,
                                  'scale_w': 1280, 'scale_h': 720, 'enabled': False})
            require((dialog._x_sb.value(), dialog._y_sb.value(), dialog._w_sb.value(), dialog._h_sb.value()) == (14, 27, 960, 540), 'Single-zone explicit fixture')
        else:
            dialog._cfg = namespace['_migrate_zoom_config']({'zones': [{'enabled': True,
                'crop_x': 14, 'crop_y': 27, 'crop_w': 960, 'crop_h': 540,
                'scale_w': 1280, 'scale_h': 720, 'border_px': 12, 'offset_y': -18, 'mode': 'stretch'}],
                'stack_direction': 'vertical', 'out_w': 1280, 'out_h': 720,
                'out_sim_enabled': True, 'comp_crop_w': 800, 'comp_crop_h': 450,
                'comp_scale_w': 1920, 'comp_scale_h': 1080, 'frame_snapshot_path': ''})
            dialog._load_config_to_ui()
            require(dialog._zone_x_sbs[0].value() == 14 and dialog._zone_border_sbs[0].value() == 12 and dialog._zone_offset_y_sbs[0].value() == -18, 'Multi-zone explicit fixture')
            require(dialog._stitch_v.isChecked() and dialog._zone_stacked[0].currentIndex() == 1, 'Fixture mode/stitch')
            require(dialog._out_w_sb.value() == 1280 and dialog._out_sim_playback_cb.isChecked(), 'Fixture output canvas')
        require(len(dialog._qa_calls) >= before + 6, 'Callback emissions recorded')
        return widget_contract(dialog)

    def test_arduino(dialog, modern):
        owner = dialog.controller
        dialog.set_devices([{'serial': True, 'port': 'COM7', 'description': 'Synthetic Arduino', 'hwid': 'FAKE_NO_DEVICE'},
                            {'serial': False, 'port': 'LPT1', 'description': 'Synthetic LPT', 'hwid': 'FAKE_INFORMATION_ONLY'}])
        require(dialog.selected_port() == 'COM7', 'Saved-port selection semantics')
        item = dialog.table.item(1, 0)
        require(item.data(QtCore.Qt.ItemDataRole.UserRole) is None and not (item.flags() & QtCore.Qt.ItemFlag.ItemIsSelectable), 'LPT remains nonselectable')
        dialog.connect_button.click()
        require(owner.calls[-1] == ('_connect_selected_arduino', ('COM7',)), 'Connect signal route')
        owner.arduino_serial = SimpleNamespace(port='COM7')
        dialog.refresh_state()
        require(dialog.led_button.isEnabled() and dialog.disconnect_button.isEnabled(), 'Ready action gates')
        for button, callback in ((dialog.refresh_button, '_refresh_arduino_devices'), (dialog.led_button, '_test_arduino_leds'), (dialog.disconnect_button, '_disconnect_arduino')):
            button.click()
            require(owner.calls[-1][0] == callback, 'Arduino callback route')
        owner._arduino_operation = object()
        dialog.refresh_state()
        require(dialog.cancel_button.isEnabled() and not dialog.connect_button.isEnabled(), 'Busy action gates')
        dialog.cancel_button.click()
        require(owner.calls[-1][0] == '_cancel_arduino_operation', 'Cancel signal route')
        owner._arduino_operation = None
        owner.reason = 'Synthetic live/playing lock'
        dialog.refresh_state()
        require(not dialog.led_button.isEnabled() and 'Controls locked:' in dialog.status_label.text(), 'Activity lock')
        owner.reason = ''
        dialog.refresh_state()
        if modern:
            grid = dialog.layout().itemAt(dialog.layout().count()-1).layout()
            require(isinstance(grid, QtWidgets.QGridLayout) and grid.count() == 6, 'Arduino actions are six grid buttons')
            require([(grid.getItemPosition(i)[0], grid.getItemPosition(i)[1]) for i in range(6)] == [(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)], 'Arduino actions 2x3')
        return {'synthetic_port': dialog.selected_port(), 'buttons': 6, 'gates': 'empty/selected/connected/busy/locked verified'}

    def reachable(dialog, widget):
        chain = []
        p = widget
        while p is not None and p is not dialog:
            chain.append(p)
            p = p.parentWidget()
        for tab in dialog.findChildren(QtWidgets.QTabWidget):
            for i in range(tab.count()):
                page = tab.widget(i)
                if page is widget or page.isAncestorOf(widget):
                    tab.setCurrentIndex(i)
        for stack in dialog.findChildren(QtWidgets.QStackedWidget):
            for i in range(stack.count()):
                page = stack.widget(i)
                if page is widget or page.isAncestorOf(widget):
                    stack.setCurrentIndex(i)
        pump()
        for p in chain:
            if isinstance(p, QtWidgets.QScrollArea):
                p.ensureWidgetVisible(widget, 3, 3)
        pump()
        if widget.isHidden():
            return 'intentionally-hidden'
        center = widget.mapTo(dialog, widget.rect().center())
        require(dialog.rect().contains(center), 'Control outside dialog: ' + type(widget).__name__ + ' ' + getattr(widget, 'text', lambda: '')())
        for p in chain:
            if isinstance(p, QtWidgets.QScrollArea):
                require(p.viewport().rect().contains(widget.mapTo(p.viewport(), widget.rect().center())), 'Control unreachable through scroll: ' + type(widget).__name__)
        return 'reachable'

    screenshots = Path(args.screenshots_dir) if args.screenshots_dir else None
    if screenshots:
        require(screenshots.is_dir(), 'Screenshot directory must already exist and be explicitly authorized')
    for size in ((1366, 768), (1920, 1080)):
        baseline = build_namespace(base_tree, size)
        candidate = build_namespace(cand_tree, size)
        for name in CLASSES:
            app.setStyleSheet(baseline['DARK_STYLESHEET'])
            old = make(baseline, name)
            old_contract = widget_contract(old)
            assert_numeric_and_radios(old, name, baseline['NUM_ZONES'])
            old_fixture = exercise_fixture_and_callbacks(old, baseline, name)
            if name == 'ArduinoPanel':
                test_arduino(old, False)
            old.hide()
            app.setStyleSheet(candidate['DARK_STYLESHEET'])
            new = make(candidate, name)
            require(old_contract == widget_contract(new), 'Baseline control/initial-value/receiver/radio-parent contract differs: ' + name)
            assert_numeric_and_radios(new, name, candidate['NUM_ZONES'])
            require(old_fixture == exercise_fixture_and_callbacks(new, candidate, name), 'Explicit numeric fixture contract differs: ' + name)
            arduino = test_arduino(new, True) if name == 'ArduinoPanel' else None
            new.show()
            pump()
            require(new.width() <= size[0] and new.height() <= size[1], 'Dialog exceeds controlled screen area: ' + name + ' ' + str((new.width(), new.height())))
            counts = {'reachable': 0, 'intentionally-hidden': 0}
            for widget in new.findChildren(QtWidgets.QWidget):
                if isinstance(widget, (QtWidgets.QAbstractButton, QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox, QtWidgets.QSlider, QtWidgets.QTableWidget)):
                    counts[reachable(new, widget)] += 1
            # Footer buttons must be visible without a scroll wrapper.
            if hasattr(new, '_ok_btn'):
                for button in (new._ok_btn, new._cancel_btn):
                    require(new.rect().contains(button.mapTo(new, button.rect().center())), 'Save/Cancel not visible')
            saved = []
            if screenshots:
                tabs = getattr(new, '_tabs', None)
                indices = range(tabs.count()) if tabs else [None]
                for index in indices:
                    if tabs:
                        tabs.setCurrentIndex(index)
                    for scroll in new.findChildren(QtWidgets.QScrollArea):
                        scroll.verticalScrollBar().setValue(0)
                        scroll.horizontalScrollBar().setValue(0)
                    pump()
                    dest = screenshots / ('dialog_%s_%sx%s%s.png' % (name, *size, '' if index is None else '_tab%s' % index))
                    require(new.grab().save(str(dest)), 'Screenshot save failed: ' + str(dest))
                    saved.append(str(dest))
            outputs.append({'dialog': name, 'screen_area': size, 'actual_size': [new.width(), new.height()], 'controls': counts, 'arduino': arduino, 'screenshots': saved})
            new.hide()
            old.deleteLater()
            new.deleteLater()
            pump()
    REPORT['qt'] = {'status': 'PASS', 'qt_version': QtCore.QT_VERSION_STR, 'pyqt_version': QtCore.PYQT_VERSION_STR, 'runs': outputs}
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--static-only', action='store_true')
    parser.add_argument('--screenshots-dir')
    parser.add_argument('--diagnose-imports', action='store_true', help='Report first runtime import request and fail closed before allowing it')
    parser.add_argument('--candidate-sha256', default=EXPECTED_CANDIDATE, help='Explicit parent-verified full candidate hash; dialog/helper AST pins remain mandatory')
    args = parser.parse_args()
    require(bool(re.fullmatch(r'[0-9a-f]{64}', args.candidate_sha256)), 'Invalid explicit candidate SHA256')
    baseline, bh = parse_source(args.baseline, EXPECTED_BASELINE)
    candidate, ch = parse_source(args.candidate, args.candidate_sha256)
    REPORT['hashes'] = {'candidate': ch, 'baseline': bh}
    REPORT['static'] = static_contracts(baseline, candidate)
    if args.static_only:
        REPORT['qt'] = {'status': 'NOT_RUN', 'reason': '--static-only'}
        code = 0
    else:
        saved_excepthook = sys.excepthook
        try:
            code = qt_run(args, baseline, candidate)
        finally:
            sys.excepthook = saved_excepthook
    # Recheck read-only source freeze after all isolated exercises.
    require(hashlib.sha256(Path(args.candidate).read_bytes()).hexdigest() == ch, 'Candidate changed during QA')
    require(hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest() == bh, 'Baseline changed during QA')
    print(json.dumps(REPORT, indent=2, ensure_ascii=False))
    return code


if __name__ == '__main__':
    original_excepthook = sys.excepthook
    try:
        exit_code = main()
    except BaseException as error:
        if isinstance(error, SystemExit):
            raise
        REPORT['failure'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
        print(json.dumps(REPORT, indent=2, ensure_ascii=False), flush=True)
        traceback.print_exc(file=sys.stderr)
        exit_code = 1
    finally:
        sys.excepthook = original_excepthook
    raise SystemExit(exit_code)
