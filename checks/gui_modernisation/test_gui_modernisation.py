#!/usr/bin/env python3
"""Offline presentation-regression gate. NEVER imports or launches either controller.

python -B test_gui_modernisation.py --source candidate.py --baseline baseline.py --ast-only
python -B test_gui_modernisation.py --source candidate.py --baseline baseline.py --screenshot-dir TEMP/render

No device enumeration/open, MIDI, hotkeys, subprocesses, app __init__, or saved data.
AST extraction is a test seam, not a production safety sandbox for hostile Python.
"""
from __future__ import annotations
import argparse
import ast
import builtins
import collections
import functools
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
import types

sys.dont_write_bytecode = True
BASELINE_SHA256 = '56a91df1849bc879584a1ec3cecec2cbdf8222282a21263758cb975c3363e4ee'
QT_MODULES = {'PyQt6.QtWidgets', 'PyQt6.QtCore', 'PyQt6.QtGui'}
QT_CONSTRUCTORS = set('QWidget QVBoxLayout QHBoxLayout QGridLayout QFormLayout QStackedLayout QPushButton QToolButton QTableWidget QTableWidgetItem QLineEdit QGroupBox QLabel QSizePolicy QComboBox QAbstractButton QSlider QCheckBox QRadioButton QSpinBox QDoubleSpinBox QDialog QScrollArea QTabWidget QStackedWidget QFrame QSplitter QButtonGroup QSpacerItem QFont QColor QBrush QPen QPixmap QPainter QPoint QRect QSize QIcon QFontMetrics'.split())
QT_IMPORTS = QT_CONSTRUCTORS | set('QApplication QHeaderView QAbstractItemView Qt QPropertyAnimation QEasingCurve pyqtProperty pyqtSignal QGuiApplication QFontDatabase'.split())
LAYOUTS = set('QVBoxLayout QHBoxLayout QGridLayout QFormLayout QStackedLayout'.split())
# Intentionally NOT enabled/visible/checked/value/range/selection, timing or text.
VISUAL_SETTERS = set('setProperty setStyleSheet setFont setContentsMargins setSpacing setHorizontalSpacing setVerticalSpacing setAlignment setSizePolicy setFixedSize setFixedWidth setFixedHeight setMinimumWidth setMinimumHeight setMaximumWidth setMaximumHeight setMinimumSize setMaximumSize setColumnWidth setRowHeight setDefaultSectionSize setSectionResizeMode setMinimumSectionSize setStretchLastSection setWordWrap setToolTip setStatusTip setAccessibleName setAccessibleDescription setObjectName setFrameShape setFrameShadow setLineWidth setMidLineWidth setAlternatingRowColors setGridStyle setShowGrid setCornerButtonEnabled setElideMode setIcon setIconSize setCursor setFlat setAutoFillBackground setBackground setForeground setTextAlignment setBold setPointSize setPixelSize setWeight setFamily setPen setBrush setRenderHint'.split())
LAYOUT_METHODS = set('removeWidget addWidget addLayout addStretch addSpacing addItem insertWidget insertLayout insertStretch setLayout setStretch setStretchFactor setColumnStretch setRowStretch setColumnMinimumWidth setRowMinimumHeight setSizeConstraint addTab insertTab setTabText setTabToolTip setTabPosition setMovable setDocumentMode setTabsClosable setWidget setWidgetResizable setHorizontalScrollBarPolicy setVerticalScrollBarPolicy setChildrenCollapsible setCollapsible setHandleWidth setSizes setOrientation setTabOrder'.split())
# These remain byte-for-byte AST identical even in UI builders.
VISUAL_PROPERTIES = {'class','role','variant','tone','section','uiRole','primary','danger','accent'}
SEMANTIC_SETTERS = set('setEnabled setDisabled setChecked setCheckable setValue setRange setMinimum setMaximum setSingleStep setDecimals setSuffix setPrefix setCurrentIndex setCurrentText addItems addItem setText setPlaceholderText setReadOnly setEchoMode setMaxLength setInputMask setValidator setColumnCount setHorizontalHeaderLabels setRowCount setItem setCellWidget setSpan setFlags setData setDragEnabled setDragDropMode setSelectionMode setSelectionBehavior setDragDropOverwriteMode setEditTriggers setAutoExclusive blockSignals'.split())
PURE_QUERIES = set('get red green blue alpha name width height size rect contentsRect sizeHint minimumSizeHint font fontMetrics horizontalHeader verticalHeader viewport layout count itemAt widget parentWidget isChecked isEnabled currentIndex currentText value minimum maximum text length upper lower strip split join format keys values items enumerate'.split())
FORBIDDEN_NAMES = set('open exec eval compile __import__ input breakpoint os sys subprocess ctypes threading rtmidi serial keyboard psutil socket requests urllib pathlib tempfile shutil zipfile QThread QTimer QFileDialog QColorDialog QMessageBox QProcess QDesktopServices PositionPoller GlobalHotkeyListener MidiTestWorker MidiSyncWorker ArduinoConnectionAttempt ArduinoSerialWriter Xr12AudienceController'.split())
PURE_BUILTINS = set('str int float bool len range enumerate zip list tuple dict set min max abs round isinstance getattr hasattr super sorted reversed'.split())
EXTRACTED_METHODS = {'_set_xr12_status_text', '_update_zoom_status_label', 'apply_config_to_ui', 'highlight_row', 'clear_highlight', 'setup_ui', 'toggle_live_mode', 'set_test_controls_enabled', 'populate_table', 'apply_table_font_size', 'apply_overlay_styles', 'format_duration', 'update_total_running_time', 'reset_midi_offset', '_update_scrub_controls_state'}

class GateFailure(AssertionError):
    pass

def require(condition, message):
    if not condition:
        raise GateFailure(message)

def dump(node):
    # Python 3.13 omits empty AST fields by default; retain the reviewed 3.12 format.
    if sys.version_info >= (3, 13):
        return ast.dump(node, include_attributes=False, show_empty=True)
    return ast.dump(node, include_attributes=False)

def attr_path(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return attr_path(node.value) + '.' + node.attr
    if isinstance(node, ast.Subscript):
        return attr_path(node.value) + '[' + ast.unparse(node.slice) + ']'
    if isinstance(node, ast.Call):
        return attr_path(node.func) + '()'
    return ''

def method_name(call):
    return call.func.attr if isinstance(call.func, ast.Attribute) else ''

def class_map(tree):
    return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

def functions(cls):
    # Property getter/setter duplicate names remain ordered in strict class AST.
    return {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

def safe_visual_constructor(call):
    name = attr_path(call.func)
    if name == 'QPixmap':
        return not call.keywords and (not call.args or (len(call.args)==2 and all(isinstance(a,ast.Constant) and type(a.value) is int for a in call.args)))
    if name == 'QIcon':
        return not call.args and not call.keywords
    return True

def pure_expression(node, helper_names=()):
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and (n.id in FORBIDDEN_NAMES or n.id.startswith('__')):
            return False
        if isinstance(n, ast.Attribute) and (n.attr.startswith('__') or n.attr in {'start', 'stop', 'singleShot', 'connectToHost', 'send', 'write', 'read', 'save', 'load', 'launch', 'system', 'Popen', 'startDetached', 'emit', 'deleteLater'}):
            return False
        if isinstance(n, (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)):
            return False
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                if not safe_visual_constructor(n):
                    return False  # filename constructors perform IO
                if f.id not in QT_CONSTRUCTORS | PURE_BUILTINS | set(helper_names):
                    return False
            elif isinstance(f, ast.Attribute):
                if f.attr not in PURE_QUERIES | VISUAL_SETTERS | LAYOUT_METHODS | set(helper_names):
                    return False
            else:
                return False
    return True

def presentation_stmt(node, helpers=()):
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    c = node.value
    if method_name(c) == 'setProperty' and not (c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value in VISUAL_PROPERTIES):
        return False
    return (method_name(c) in VISUAL_SETTERS | set(helpers) or (isinstance(c.func,ast.Name) and c.func.id in helpers)) and all(pure_expression(a, helpers) for a in c.args) and all(pure_expression(k.value, helpers) for k in c.keywords)

# Exact reviewed helper-body hashes and scoped presentation-node rewrites.
REVIEWED_HELPERS = {'_ui_role': '3fcd32ac2cbb1e553259285248b23de9ad5bb375a6fecf9844101a1b5bbd3234', '_ui_surface': '94c45ce587433b72c0f1c768a0f1220bd852cd8d59f45154de2aafed6fd841bb', '_ui_scroll_page': '76cf5a88207de6c6e222adcb7279f30ca8d26de3fc3809cfc6821591deea68f7', '_ui_fit_dialog': 'dfc583428176bf065adab4f8f605ef1d78912aeee8b8ca4e840087c4ab77b120', '_ui_scroll_layout': '0471517dd34b1a9b942eb3cc069b32cf5ea903840b872ca5baef5d3095feeb12'}
REVIEWED_PRESENTATION_NODES = {'ArduinoPanel.__init__': {"Assign(targets=[Name(id='actions', ctx=Store())], value=Call(func=Name(id='QGridLayout', ctx=Load()), args=[], keywords=[]))": 'actions = QHBoxLayout()', "Expr(value=Call(func=Attribute(value=Name(id='actions', ctx=Load()), attr='addWidget', ctx=Load()), args=[Name(id='button', ctx=Load()), BinOp(left=Call(func=Attribute(value=Name(id='actions', ctx=Load()), attr='count', ctx=Load()), args=[], keywords=[]), op=FloorDiv(), right=Constant(value=3)), BinOp(left=Call(func=Attribute(value=Name(id='actions', ctx=Load()), attr='count', ctx=Load()), args=[], keywords=[]), op=Mod(), right=Constant(value=3))], keywords=[]))": 'actions.addWidget(button)'}, 'ZoomScaleDialog.__init__': {"Expr(value=Call(func=Name(id='_ui_fit_dialog', ctx=Load()), args=[Name(id='self', ctx=Load()), Constant(value=1100), Constant(value=720)], keywords=[]))": 'self.resize(1100, 720)'}, 'MultiZoomScaleDialog.__init__': {"Expr(value=Call(func=Name(id='_ui_fit_dialog', ctx=Load()), args=[Name(id='self', ctx=Load()), Constant(value=1280), Constant(value=820)], keywords=[]))": 'self.resize(1280, 820)'}, 'MultiZoomScaleDialog._setup_ui': {"Expr(value=Call(func=Attribute(value=Name(id='body', ctx=Load()), attr='addWidget', ctx=Load()), args=[Call(func=Name(id='_ui_scroll_layout', ctx=Load()), args=[Name(id='right', ctx=Load())], keywords=[]), Constant(value=1)], keywords=[]))": 'body.addLayout(right, 1)', "Expr(value=Call(func=Attribute(value=Name(id='comp_body', ctx=Load()), attr='addWidget', ctx=Load()), args=[Call(func=Name(id='_ui_scroll_layout', ctx=Load()), args=[Name(id='comp_right', ctx=Load())], keywords=[]), Constant(value=1)], keywords=[]))": 'comp_body.addLayout(comp_right, 1)'}, 'LiveController._set_xr12_status_text': {"Assign(targets=[Name(id='color', ctx=Store())], value=Constant(value='#9aadc2'))": "color = '#888'", "Assign(targets=[Name(id='color', ctx=Store())], value=Constant(value='#e9b96e'))": "color = '#e67e22'", "Assign(targets=[Name(id='color', ctx=Store())], value=Constant(value='#86d8b8'))": "color = '#27ae60'", "Assign(targets=[Name(id='color', ctx=Store())], value=Constant(value='#f497a7'))": "color = '#e74c3c'"}, 'LiveController.highlight_row': {"Assign(targets=[Name(id='style_sheet', ctx=Store())], value=JoinedStr(values=[Constant(value='QWidget { background-color: '), FormattedValue(value=Call(func=Attribute(value=Name(id='bg_color', ctx=Load()), attr='name', ctx=Load()), args=[], keywords=[]), conversion=-1), Constant(value='; color: '), FormattedValue(value=Call(func=Attribute(value=Name(id='fg_color', ctx=Load()), attr='name', ctx=Load()), args=[], keywords=[]), conversion=-1), Constant(value='; font-size: '), FormattedValue(value=Name(id='font_size', ctx=Load()), conversion=-1), Constant(value='pt; } QLineEdit { border: 1px solid '), FormattedValue(value=Call(func=Attribute(value=Name(id='bg_color', ctx=Load()), attr='name', ctx=Load()), args=[], keywords=[]), conversion=-1), Constant(value='; padding: 2px 4px; } QLineEdit:focus { border-color: #6bd2e3; } QPushButton[uiRole=remove] { background-color: #472a35; color: #f4b0bc; border: 1px solid #764151; border-radius: 4px; min-height: 0; padding: 0; font-size: 11px; } QPushButton[uiRole=remove]:disabled { color: #77879a; background-color: #1b2532; border-color: #2d3949; } QPushButton[uiRole=remove]:hover:enabled { background-color: #85364a; color: white; }')]))": "style_sheet = f'background-color: {bg_color.name()}; color: {fg_color.name()}; font-size: {font_size}pt; border: none;'"}}

class ReviewedPresentation(ast.NodeTransformer):
    def __init__(self):
        self.classname = None
        self.methodname = None
    def visit_ClassDef(self,n):
        previous=self.classname; self.classname=n.name
        result=self.generic_visit(n); self.classname=previous
        return result
    def visit_FunctionDef(self,n):
        previous=self.methodname; self.methodname=n.name
        result=self.generic_visit(n); self.methodname=previous
        return result
    def generic_visit(self,n):
        key=(self.classname or '')+'.'+(self.methodname or '')
        replacements=REVIEWED_PRESENTATION_NODES.get(key,{})
        replacement=replacements.get(dump(n)) if replacements and isinstance(n,(ast.Assign,ast.Expr)) else None
        if replacement is not None:
            return ast.copy_location(ast.parse(replacement).body[0],n)
        return super().generic_visit(n)

class Normalise(ast.NodeTransformer):
    def __init__(self, helpers=()):
        self.helpers = set(helpers)
    def visit_Expr(self, n):
        if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            return None  # docstrings/comments are not behavior
        if presentation_stmt(n, self.helpers):
            return None
        return self.generic_visit(n)
    def visit_Call(self, n):
        # QFont/QColor arguments are visual ONLY if side-effect-free.
        if isinstance(n.func, ast.Name) and n.func.id in {'QFont', 'QColor', 'QBrush', 'QPen'} and pure_expression(n, self.helpers):
            return ast.Call(func=ast.Name(id=n.func.id, ctx=ast.Load()), args=[ast.Constant(value='<presentation>')], keywords=[])
        return self.generic_visit(n)
    def generic_visit(self, n):
        result = super().generic_visit(n)
        # Removal of the only visual statement in a branch needs a legal placeholder.
        for field in ('body',):
            if hasattr(result, field) and isinstance(getattr(result, field), list) and not getattr(result, field) and isinstance(result, (ast.FunctionDef, ast.AsyncFunctionDef, ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler, ast.ClassDef)):
                setattr(result, field, [ast.Pass()])
        return result

def norm(node, helpers=()):
    return dump(Normalise(helpers).visit(copy.deepcopy(node)))

def qt_references(fn):
    refs = {'self'}
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and attr_path(n.value.func) in (QT_CONSTRUCTORS | {'DraggableTableWidget','Switch'}) - LAYOUTS:
            refs.update(attr_path(t) for t in n.targets)
    return refs

def without_parent(call, refs):
    result = copy.deepcopy(call)
    if result.args and attr_path(result.args[-1]) in refs:
        result.args.pop()
    result.keywords = [k for k in result.keywords if k.arg != 'parent']
    return result

def widget_bindings(fn):
    out = {}
    refs = qt_references(fn)
    for n in ast.walk(fn):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if isinstance(n.value, ast.Call):
                name = attr_path(n.value.func)
                if name in QT_CONSTRUCTORS | {'DraggableTableWidget', 'Switch'} and name not in LAYOUTS:
                    for t in targets:
                        if attr_path(t).startswith('self.'):
                            # Parents/layout placement are visual, constructor text/value is not.
                            call = without_parent(n.value, refs)
                            out[attr_path(t)] = (name, tuple(dump(a) for a in call.args), tuple(dump(k) for k in call.keywords))
    return out

def ui_contract(fn, helper_names=()):
    refs = qt_references(fn)
    signals = []
    semantic = []
    nonvisual_calls = []
    data_assignments = []
    controls = []
    constructors = []
    event_order = collections.defaultdict(list)
    for n in sorted(ast.walk(fn), key=lambda n: (getattr(n,'lineno',0),getattr(n,'col_offset',0))):
        if isinstance(n, ast.Call):
            m = method_name(n)
            if m == 'connect':
                signals.append(dump(n))
                signal = n.func.value
                receiver = attr_path(signal.value) if isinstance(signal,ast.Attribute) else attr_path(signal)
                event_order[receiver].append(dump(n))
            elif m in SEMANTIC_SETTERS or m in {'hide', 'show', 'setVisible', 'setHidden'}:
                semantic.append(dump(n))
                event_order[attr_path(n.func.value)].append(dump(n))
            elif isinstance(n.func, ast.Attribute) and attr_path(n.func.value).startswith('self') and m not in VISUAL_SETTERS | LAYOUT_METHODS | PURE_QUERIES | set(helper_names):
                nonvisual_calls.append((n.lineno, n.col_offset, dump(n)))
            if isinstance(n.func, ast.Name) and n.func.id in QT_CONSTRUCTORS | {'DraggableTableWidget', 'Switch'} and n.func.id not in LAYOUTS | {'QWidget', 'QFrame', 'QGroupBox', 'QLabel', 'QFont', 'QColor', 'QBrush', 'QPen', 'QPixmap', 'QPainter', 'QSizePolicy', 'QSpacerItem', 'QSplitter', 'QTabWidget', 'QStackedWidget', 'QScrollArea'}:
                constructors.append(dump(without_parent(n, refs)))
        if isinstance(n, ast.Assign):
            if not isinstance(n.value, ast.Call) or attr_path(n.value.func) not in QT_CONSTRUCTORS | {'DraggableTableWidget', 'Switch'} | set(helper_names):
                data_assignments.append(dump(n))
        if isinstance(n, (ast.For, ast.If, ast.While)):
            # Preserve loop bounds and branch conditions, not visual layout bodies.
            controls.append((type(n).__name__, dump(n.iter) if isinstance(n, ast.For) else dump(n.test), dump(n.target) if isinstance(n, ast.For) else ''))
    return {'signals': collections.Counter(signals), 'semantic': collections.Counter(semantic), 'calls_order': [v for _, _, v in sorted(nonvisual_calls)], 'data_assignments': collections.Counter(data_assignments), 'controls': collections.Counter(controls), 'constructors': collections.Counter(constructors), 'widget_event_order':dict(event_order)}

def validate_helper(node, original_attrs, helper_names):
    if node.name in REVIEWED_HELPERS:
        require(hashlib.sha256(dump(node).encode()).hexdigest() == REVIEWED_HELPERS[node.name], 'Reviewed presentation helper body changed: ' + node.name)
        return
    require(not isinstance(node, ast.AsyncFunctionDef), 'Async helper forbidden: ' + node.name)
    if isinstance(node, ast.ClassDef):
        require(all(attr_path(b) in {'QWidget', 'QFrame', 'QLabel', 'QPushButton', 'QToolButton', 'QGroupBox'} for b in node.bases), 'New class must be a pure visual QWidget: ' + node.name)
    local_lists = {t.id for n in ast.walk(node) if isinstance(n,ast.Assign) and (isinstance(n.value,ast.List) or (isinstance(n.value,ast.Call) and attr_path(n.value.func)=='list')) for t in n.targets if isinstance(t,ast.Name)}
    for n in ast.walk(node):
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith, ast.Await, ast.Yield, ast.YieldFrom, ast.Try, ast.Raise)):
            raise GateFailure('Nonvisual/side-effect construct in helper ' + node.name + ': ' + type(n).__name__)
        if isinstance(n, ast.Name):
            require(n.id not in FORBIDDEN_NAMES and not n.id.startswith('__'), 'Forbidden helper reference: ' + n.id)
        if isinstance(n, ast.Attribute):
            require(not n.attr.startswith('__') or n.attr == '__init__', 'Dunder reference in visual helper')
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                p = attr_path(t)
                require(isinstance(t, (ast.Name, ast.Tuple, ast.List)) or (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self'), 'Helper assignment must be local or a new self visual attribute: ' + p)
                require(p not in original_attrs, 'Helper mutates original state: ' + p)
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                require(f.id in QT_CONSTRUCTORS | PURE_BUILTINS | set(helper_names), 'Unknown call in visual helper: ' + f.id)
                require(safe_visual_constructor(n), 'File-loading Qt constructor in helper')
            elif isinstance(f, ast.Attribute):
                p, m = attr_path(f.value), f.attr
                allowed = VISUAL_SETTERS | LAYOUT_METHODS | PURE_QUERIES | {'__init__', 'append', 'extend', 'setProperty', 'setWindowTitle', 'resize', 'update', 'connect', 'drawRoundedRect', 'drawRect', 'drawEllipse', 'drawText', 'fillRect', 'end', 'restore', 'setCurrentIndex', 'setCurrentWidget', 'setVisible', 'show', 'hide', 'toggled', 'clicked'} | set(helper_names)
                require(m in allowed, 'Non-whitelisted helper call: ' + attr_path(f))
                if m == 'connect':
                    require(len(n.args) == 1, 'Visual helper connection must have one callback')
                    callback = n.args[0]
                    require(isinstance(callback,ast.Lambda) or (isinstance(callback,ast.Name) and callback.id in helper_names) or (isinstance(callback,ast.Attribute) and callback.attr in helper_names), 'New helper signal may target only a validated pure visual helper or lambda')
                if m == 'setProperty':
                    require(n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value in VISUAL_PROPERTIES, 'Only visual dynamic properties allowed in helper')
                if m in {'setCurrentIndex','setCurrentWidget','setVisible','show','hide'}:
                    require(p.startswith('self.') and p not in original_attrs, 'Navigation/visibility helper may target only a new self UI attribute')
                require(not (p in original_attrs and m in SEMANTIC_SETTERS | {'hide', 'show', 'setVisible'}), 'Helper changes existing functional control: ' + attr_path(f))
                if m in {'append','extend'}:
                    require(isinstance(f.value,ast.Name) and f.value.id in local_lists, 'Helper may append only to a new local visual collection')
            else:
                raise GateFailure('Indirect call in visual helper')


def strict_ast(baseline, candidate):
    require(set(class_map(baseline)) <= set(class_map(candidate)), 'Original class removed')
    for n in ast.walk(candidate):
        is_stylesheet = (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DARK_STYLESHEET' for t in n.targets)) or (isinstance(n,ast.Call) and method_name(n)=='setStyleSheet')
        if is_stylesheet:
            require(not any(isinstance(v,ast.Constant) and isinstance(v.value,str) and 'url(' in v.value.lower().replace(' ','') for v in ast.walk(n)), 'External stylesheet assets forbidden in offline gate')
    bclasses, cclasses = class_map(baseline), class_map(candidate)
    helpers = {}
    original_definition_names = {n.name for n in ast.walk(baseline) if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))}
    def register_helper(name,node):
        require(name not in original_definition_names, 'Visual helper shadows an original definition: ' + name)
        require(name not in helpers, 'Duplicate visual helper name: ' + name)
        helpers[name]=node
    original_attrs = {attr_path(n) for n in ast.walk(baseline) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'self'}
    for name, cc in cclasses.items():
        if name not in bclasses:
            register_helper(name,cc)
        else:
            bm = functions(bclasses[name])
            for f in cc.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name not in bm:
                    register_helper(f.name,f)
    btop = {n.name for n in baseline.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for n in candidate.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name not in btop:
            register_helper(n.name,n)
    for h in helpers.values():
        validate_helper(h, original_attrs, helpers)
    # Non-Qt imports, their order and aliases are immutable. Qt may only gain known visual names.
    def imports(t):
        return [dump(n) for n in t.body if isinstance(n, (ast.Import, ast.ImportFrom)) and not (isinstance(n, ast.ImportFrom) and n.module in QT_MODULES)]
    require(imports(baseline) == imports(candidate), 'Non-Qt imports changed')
    for n in candidate.body:
        if isinstance(n, ast.ImportFrom) and n.module in QT_MODULES:
            original = {(a.name, a.asname) for b in baseline.body if isinstance(b, ast.ImportFrom) and b.module == n.module for a in b.names}
            for a in n.names:
                require((a.name, a.asname) in original or (a.name in QT_IMPORTS and a.asname is None), 'Unsafe/new Qt import: ' + a.name)
    for module in QT_MODULES:
        original = {(a.name,a.asname) for n in baseline.body if isinstance(n,ast.ImportFrom) and n.module == module for a in n.names}
        current = {(a.name,a.asname) for n in candidate.body if isinstance(n,ast.ImportFrom) and n.module == module for a in n.names}
        require(original <= current, 'Original Qt import removed from ' + module)
    # setup_ui may move layout statements, but never change a functional contract.
    bsetup, csetup = functions(bclasses['LiveController'])['setup_ui'], functions(cclasses['LiveController'])['setup_ui']
    require(dump(bsetup.args) == dump(csetup.args), 'setup_ui signature changed')
    bw, cw = widget_bindings(bsetup), widget_bindings(csetup)
    for name, binding in bw.items():
        require(cw.get(name) == binding, 'Original widget constructor changed/removed: ' + name)
    bc, cc = ui_contract(bsetup, helpers), ui_contract(csetup, helpers)
    for key in bc:
        # New purely visual signal connections are permitted only via validated helpers.
        require(bc[key] == cc[key], 'setup_ui functional contract changed: ' + key + '\n baseline=' + repr(bc[key])[:1500] + '\n candidate=' + repr(cc[key])[:1500])
    # Reject hidden new side effects in setup_ui, including calls not captured above.
    b_calls = collections.Counter(dump(n) for n in ast.walk(bsetup) if isinstance(n, ast.Call))
    for n in ast.walk(csetup):
        if not isinstance(n, ast.Call) or dump(n) in b_calls:
            continue
        if isinstance(n.func, ast.Name):
            require(n.func.id in QT_CONSTRUCTORS | PURE_BUILTINS | set(helpers) | {'DraggableTableWidget', 'Switch'}, 'New unsafe setup call: ' + attr_path(n.func))
            require(safe_visual_constructor(n), 'New setup constructor may perform file IO')
        else:
            require(method_name(n) in VISUAL_SETTERS | LAYOUT_METHODS | PURE_QUERIES | set(helpers), 'New nonvisual setup call: ' + attr_path(n.func))
        if method_name(n) == 'setProperty':
            require(n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value in VISUAL_PROPERTIES, 'Nonvisual Qt property in setup_ui')
        for a in list(n.args) + [k.value for k in n.keywords]:
            require(pure_expression(a, helpers), 'Side-effectful new UI argument: ' + ast.unparse(n))
    # Existing module shape/statements and each original method survive, narrowly normalised.
    def cleaned(tree):
        t = ReviewedPresentation().visit(copy.deepcopy(tree))
        result = []
        for n in t.body:
            if isinstance(n, ast.ImportFrom) and n.module in QT_MODULES:
                continue
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in helpers and n.name not in bclasses and n.name not in btop:
                continue
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DARK_STYLESHEET' for t in n.targets):
                require(isinstance(n.value, ast.Constant) and isinstance(n.value.value, str), 'DARK_STYLESHEET must be a literal string')
                n.value = ast.Constant(value='<stylesheet>')
            if isinstance(n, ast.ClassDef) and n.name in bclasses:
                oldmethods = set(functions(bclasses[n.name]))
                n.body = [f for f in n.body if not (isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name not in oldmethods)]
                if n.name == 'LiveController':
                    for i, f in enumerate(n.body):
                        if isinstance(f, ast.FunctionDef) and f.name == 'setup_ui':
                            f.body = [ast.Pass()]
            result.append(n)
        t.body = result
        return norm(t, helpers)
    for name, original_class in bclasses.items():
        current_methods = functions(cclasses[name])
        for original_method in original_class.body:
            if isinstance(original_method,(ast.FunctionDef,ast.AsyncFunctionDef)) and not (name == 'LiveController' and original_method.name == 'setup_ui'):
                require(original_method.name in current_methods, 'Original method removed: ' + name + '.' + original_method.name)
                if original_method.name != 'circle_pos':  # property getter/setter duplicates checked in full class AST below
                    require(norm(ReviewedPresentation().visit(ast.Module(body=[ast.ClassDef(name=name,bases=[],keywords=[],body=[copy.deepcopy(original_method)],decorator_list=[])],type_ignores=[])),helpers) == norm(ReviewedPresentation().visit(ast.Module(body=[ast.ClassDef(name=name,bases=[],keywords=[],body=[copy.deepcopy(current_methods[original_method.name])],decorator_list=[])],type_ignores=[])),helpers), 'Non-presentation method changed: ' + name + '.' + original_method.name)
    require(cleaned(baseline) == cleaned(candidate), 'Non-presentation module/class AST changed (business logic/constants/signatures/imports)')
    return {'original_widgets': len(bw), 'signal_connections': sum(bc['signals'].values()), 'semantic_setters': sum(bc['semantic'].values()), 'new_visual_helpers': sorted(helpers)}


def negative_selftests(tree):
    tests = []
    def mutated(change):
        t = copy.deepcopy(tree); change(t); return t
    def alter_const(t):
        for n in t.body:
            if isinstance(n, ast.Assign) and any(isinstance(a, ast.Name) and a.id == 'ARDUINO_BAUD' for a in n.targets):
                n.value = ast.Constant(value=1); return
        raise AssertionError('missing ARDUINO_BAUD')
    def alter_range(t):
        fn = functions(class_map(t)['LiveController'])['setup_ui']
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and attr_path(n.func) == 'self.midi_offset_slider.setRange':
                n.args[0] = ast.Constant(value=-249); return
    def alter_lambda(t):
        fn = functions(class_map(t)['LiveController'])['setup_ui']
        for n in ast.walk(fn):
            if isinstance(n, ast.Lambda) and any(isinstance(x, ast.Call) and attr_path(x.func) == 'self.run_port_test' for x in ast.walk(n)):
                n.args.defaults[-1] = ast.Constant(value=99); return
    def alter_enabled(t):
        fn = functions(class_map(t)['LiveController'])['toggle_live_mode']
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and attr_path(n.func) == 'self.add_button.setEnabled':
                n.args[0] = ast.Constant(value=True); return
    def alter_index(t):
        fn = functions(class_map(t)['LiveController'])['populate_table']
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and attr_path(n.func) == 'self.table.setCellWidget':
                n.args[1] = ast.Constant(value=99); return
    def helper_io(t):
        class_map(t)['LiveController'].body.append(ast.parse("def sneaky_ui(self):\n    open('bad','w')\n").body[0])
    def style_io(t):
        fn = functions(class_map(t)['LiveController'])['apply_overlay_styles']
        fn.body.append(ast.parse("self.countdown_label.setStyleSheet(open('bad').read())").body[0])
    def remove_collection_append(t):
        fn = functions(class_map(t)['LiveController'])['setup_ui']
        for loop in ast.walk(fn):
            if isinstance(loop, ast.For):
                loop.body = [n for n in loop.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and attr_path(n.value.func) == 'self.xr12_ch_enabled_cbs.append')]
    def alter_default(t):
        fn = functions(class_map(t)['LiveController'])['setup_ui']
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and attr_path(n.func) == 'self.calib_loop_duration_spinbox.setValue': n.args[0] = ast.Constant(value=6); return
    def helper_timer(t):
        class_map(t)['LiveController'].body.append(ast.parse('def sneaky_timer(self):\n    QTimer.singleShot(0, self.stop_all_activity)\n').body[0])
    def alter_constructor(t):
        fn=functions(class_map(t)['LiveController'])['setup_ui']
        for n in ast.walk(fn):
            if isinstance(n,ast.Assign) and any(attr_path(a)=='self.stop_button' for a in n.targets): n.value.func.id='QToolButton'; return
    def alter_signature(t):
        functions(class_map(t)['LiveController'])['stop_all_activity'].args.args.append(ast.arg(arg='unexpected'))
    def alter_import(t):
        for n in t.body:
            if isinstance(n,ast.Import) and any(a.name=='rtmidi' for a in n.names): n.names[0].name='unapproved_midi'; return
    def change_port_names(t):
        fn=functions(class_map(t)['LiveController'])['setup_ui']
        for n in ast.walk(fn):
            if isinstance(n,ast.Assign) and any(attr_path(a)=='port_names' for a in n.targets): n.value.elts.append(ast.Constant(value='Unexpected')); return
    def alter_property(t):
        class_map(t)['LiveController'].body.append(ast.parse("def bad_property(self):\n    self.stop_button.setProperty('enabled', False)\n").body[0])
    def helper_network(t):
        class_map(t)['LiveController'].body.append(ast.parse("def bad_network(self):\n    urllib.request.urlopen('http://invalid')\n").body[0])
    def helper_file_constructor(t):
        class_map(t)['LiveController'].body.append(ast.parse("def bad_file(self):\n    return QPixmap('saved-frame.png')\n").body[0])
    for name, f in [('hardware constant', alter_const), ('slider range', alter_range), ('MIDI lambda capture', alter_lambda), ('enabled gate', alter_enabled), ('table column index', alter_index), ('new helper IO', helper_io), ('IO hidden in style', style_io), ('widget collection append', remove_collection_append), ('spin default', alter_default), ('helper timer', helper_timer), ('widget constructor class',alter_constructor), ('business method signature',alter_signature), ('non-Qt import',alter_import), ('MIDI port data',change_port_names), ('enabled via Qt property',alter_property), ('helper network',helper_network), ('Qt filename constructor',helper_file_constructor)]:
        try:
            strict_ast(tree, mutated(f))
        except GateFailure:
            tests.append(name)
        else:
            raise GateFailure('Negative self-test did not reject: ' + name)
    strict_ast(tree, copy.deepcopy(tree))
    visual = copy.deepcopy(tree)
    fn = functions(class_map(visual)['LiveController'])['setup_ui']
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and attr_path(n.func) == 'self.active_label.setStyleSheet': n.args[0] = ast.Constant(value='color: #abcdef;')
        if isinstance(n, ast.Call) and attr_path(n.func) == 'self.layout.setSpacing': n.args[0] = ast.Constant(value=12)
    strict_ast(tree, visual)  # presentation-only positive control must be accepted
    helper = ast.parse("def safe_visual(self):\n    self.status_label.setStyleSheet('color: #abcdef')\n").body[0]
    class_map(visual)['LiveController'].body.append(helper)
    strict_ast(tree, visual)  # a verified style-only helper is safe
    return tests


def reviewed_negative_selftests(baseline,candidate):
    available={n.name for n in candidate.body if isinstance(n,ast.FunctionDef)}
    rejected=[]
    for name in sorted(set(REVIEWED_HELPERS)&available):
        mutation=copy.deepcopy(candidate)
        helper=next(n for n in mutation.body if isinstance(n,ast.FunctionDef) and n.name==name)
        helper.body.append(ast.parse("open('forbidden','w')").body[0])
        try:
            strict_ast(baseline,mutation)
        except GateFailure:
            rejected.append(name+' rejects injected IO')
        else:
            raise GateFailure('Reviewed helper mutation accepted: '+name)
    return rejected

def load_source(path):
    data = Path(path).read_bytes()
    code = data.decode('utf-8-sig')
    compile(code, str(path), 'exec')  # compile only; no module execution
    return ast.parse(code, filename=str(path)), {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'crlf': data.count(bytes((13,10))), 'lf': data.count(b'\n')}


def qt_runtime(baseline, candidate, screenshot_dir, helper_names):
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'  # process-local, before Qt imports
    try:
        from PyQt6 import QtWidgets as W, QtCore as C, QtGui as G, QtTest as T
    except ImportError as e:
        raise GateFailure('Real Qt unavailable. AST checks completed; run without --ast-only in the intended Windows Python/PyQt runtime. ' + str(e))
    app = W.QApplication.instance() or W.QApplication(['offline-gui-regression'])
    if not G.QFontDatabase.families():
        font_path = Path('C:/Windows/Fonts/segoeui.ttf')
        require(font_path.is_file(), 'Empty font database and Segoe UI unavailable')
        require(G.QFontDatabase.addApplicationFont(str(font_path)) >= 0, 'Could not load process-local Segoe UI')
    app.setFont(G.QFont('Segoe UI', 9))
    event_errors = []
    old_excepthook = sys.excepthook
    sys.excepthook = lambda typ,value,tb: event_errors.append(''.join(traceback.format_exception(typ,value,tb)))
    def pump():
        app.processEvents()
        require(not event_errors, 'Exception in Qt callback: ' + '\n'.join(event_errors))
    screenshots = []
    out = Path(screenshot_dir) if screenshot_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    runtime = {'python': sys.version, 'PyQt': C.PYQT_VERSION_STR, 'Qt': C.QT_VERSION_STR, 'platform': C.QGuiApplication.platformName() if hasattr(C, 'QGuiApplication') else app.platformName()}
    safe_globals = {name: getattr(module, name) for module in (W, C, G) for name in dir(module) if name in QT_IMPORTS | {'QPropertyAnimation', 'QEasingCurve', 'pyqtProperty', 'pyqtSignal'}}
    # No OS process/hardware modules enter the extracted namespace. Pure path transforms only.
    safe_globals['os'] = types.SimpleNamespace(path=types.SimpleNamespace(basename=os.path.basename, splitext=os.path.splitext))
    safe_globals['__name__'] = 'offline_extracted_ui'
    def blocked(*args, **kwargs):
        raise GateFailure('Forbidden hardware/process/thread constructor reached')
    for n in FORBIDDEN_NAMES - {'os'}:
        safe_globals[n] = blocked
    guarded_builtins = dict(vars(builtins))
    for name in ('open','exec','eval','compile','__import__','input','breakpoint'):
        guarded_builtins[name] = blocked
    runtime['qt_cached_imports'] = []
    def qt_runtime_import(name, globals=None, locals=None, fromlist=(), level=0):
        # PyQt signal.connect lazily inspects callables via this already-loaded module.
        # No general importer or application/hardware dependency is reachable.
        require(name == 'functools' and level == 0 and sys.modules.get(name) is functools,
                'Forbidden runtime import: ' + repr(name))
        if name not in runtime['qt_cached_imports']:
            runtime['qt_cached_imports'].append(name)
        return functools
    guarded_builtins['__import__'] = qt_runtime_import
    safe_globals['__builtins__'] = guarded_builtins
    def build(tree, label):
        namespace = dict(safe_globals)
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                try:
                    value = ast.literal_eval(n.value)
                except (ValueError, TypeError):
                    continue
                namespace[n.targets[0].id] = value
        definitions = []
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.name in {'clamp_midi_value', '_migrate_zoom_config', '_default_zone', '_normalize_zone', '_zoom_int'}:
                definitions.append(copy.deepcopy(n))
            elif isinstance(n, ast.ClassDef) and n.name in {'DraggableTableWidget', 'Switch'} | set(helper_names):
                definitions.append(copy.deepcopy(n))
            elif isinstance(n, ast.FunctionDef) and n.name in helper_names:
                definitions.append(copy.deepcopy(n))
        ast.fix_missing_locations(m := ast.Module(body=definitions, type_ignores=[]))
        exec(compile(m, '<safe Qt class extraction>', 'exec'), namespace)
        controller = class_map(tree)['LiveController']
        selected = [copy.deepcopy(f) for f in controller.body if isinstance(f, ast.FunctionDef) and f.name in EXTRACTED_METHODS | set(helper_names)]
        # No controller __init__, resizeEvent, closeEvent, startup or filesystem functions.
        ast.fix_missing_locations(m := ast.Module(body=selected, type_ignores=[]))
        exec(compile(m, '<safe method extraction>', 'exec'), namespace)
        class SafeHost(W.QWidget):
            def __init__(self):
                super().__init__()
                self.calls = []
            def close(self):
                self.calls.append(('close', ()))
                return True
        for f in selected:
            setattr(SafeHost, f.name, namespace[f.name])
        real_toggle = SafeHost.toggle_live_mode
        def counted_toggle(self):
            self.calls.append(('_real_toggle_live_mode', ()))
            return real_toggle(self)
        SafeHost.toggle_live_mode = counted_toggle
        callbacks = {n.attr for n in ast.walk(controller) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'self' and n.attr in functions(controller)}
        def recorder(name):
            def callback(self, *args):
                self.calls.append((name, args))
            return callback
        for name in callbacks - EXTRACTED_METHODS - set(helper_names):
            setattr(SafeHost, name, recorder(name))
        # Reviewed pure migration/status functions are extracted; no controller startup or IO.
        host = SafeHost()
        host.setWindowTitle('OFFLINE synthetic setlist — ' + label)
        host.config = {'display':2,'preload':4,'apply_zoom':True,'sync_show_host':'https://offline.invalid','sync_show_session':'synthetic-session','sync_show_timing_trim_ms':17,'xr12_audience_fade_duration_sec':2.5,'xr12_audience_open_value':96,'xr12_audience_closed_value':3}
        host.xr12_connected = False
        host.xr12_controller = None
        host.zoom_config = {}
        host.bpm_data = {'/offline/01_neon_lights.mp4': 120, '/offline/02_the_signal.mp4': 132}
        host.track_name_data = {'/offline/01_neon_lights.mp4': 'Neon Lights', '/offline/02_the_signal.mp4': 'The Signal'}
        host.worker = None
        host.test_worker = None
        host.currently_playing_row = None
        host.test_track_path = None
        host.is_live_mode = False
        host.calib_loop_active = False
        host.undo_history = collections.deque()
        host.test_port_enabled_cbs = {}
        host.test_port_start_cbs = {}
        host.test_port_bpm_inputs = {}
        host.test_port_buttons = {}
        host.current_table_font_size = namespace['DEFAULT_TABLE_FONT_SIZE']
        host.streamdeck_font_size = namespace['DEFAULT_STREAMDECK_FONT_SIZE']
        host.count_in_bg_color = namespace['DEFAULT_COUNT_IN_BG_COLOR']
        host.count_in_font_size = namespace['DEFAULT_COUNT_IN_FONT_SIZE']
        host.track_play_bg_color = namespace['DEFAULT_TRACK_PLAY_BG_COLOR']
        host.track_play_font_size = namespace['DEFAULT_TRACK_PLAY_FONT_SIZE']
        for attr in ('playing_color','default_color'):
            assignment = next(n for n in ast.walk(functions(controller)['__init__']) if isinstance(n,ast.Assign) and any(attr_path(t)=='self.'+attr for t in n.targets))
            require(isinstance(assignment.value,ast.Call) and attr_path(assignment.value.func)=='QColor' and len(assignment.value.args)==1,'Expected literal visual QColor initializer')
            setattr(host,attr,G.QColor(ast.literal_eval(assignment.value.args[0])))
        host.tracks = [
            {'type': 'track', 'path': '/offline/01_neon_lights.mp4', 'hotkey': 'a', 'duration': 215, 'linked': False, 'send_start_port1': True, 'send_start_port2': True, 'sync_show_enabled': True, 'sync_show_file': 'neon.json'},
            {'type': 'track', 'path': '/offline/02_the_signal.mp4', 'hotkey': 's', 'duration': 248, 'linked': True, 'send_start_port1': True, 'send_start_port2': False, 'sync_show_enabled': False, 'sync_show_file': ''},
            {'type': 'divider', 'text': 'ENCORE'},
            {'type': 'track', 'path': '/offline/03_afterglow.mp4', 'hotkey': 'd', 'duration': 192, 'linked': False, 'send_start_port1': True, 'send_start_port2': True, 'sync_show_enabled': False, 'sync_show_file': ''},
        ]
        host.setStyleSheet(namespace['DARK_STYLESHEET'])
        host.setup_ui()
        host.apply_config_to_ui()
        host.show()
        pump()
        return host

    def widgets(host):
        result = {}
        for name, value in vars(host).items():
            if isinstance(value, W.QWidget):
                result[name] = value
            elif isinstance(value, (list, tuple)):
                for i, w in enumerate(value):
                    if isinstance(w, W.QWidget): result[name + '[' + str(i) + ']'] = w
            elif isinstance(value, dict):
                for k, w in value.items():
                    if isinstance(w, W.QWidget): result[name + '[' + str(k) + ']'] = w
        return result
    def state(w):
        s = {'class': type(w).__name__, 'enabled': w.isEnabled()}
        if isinstance(w, (W.QAbstractButton, W.QLabel, W.QLineEdit)):
            s['text'] = w.text()
        if isinstance(w, W.QAbstractButton):
            s.update(checked=w.isChecked(), checkable=w.isCheckable())
        if isinstance(w, (W.QAbstractSlider, W.QSpinBox, W.QDoubleSpinBox)):
            s.update(minimum=w.minimum(), maximum=w.maximum(), value=w.value(), step=w.singleStep())
        if isinstance(w, (W.QSpinBox, W.QDoubleSpinBox)):
            s.update(suffix=w.suffix(), prefix=w.prefix())
        if isinstance(w, W.QComboBox):
            s.update(index=w.currentIndex(), items=[w.itemText(i) for i in range(w.count())])
        if isinstance(w, W.QLineEdit):
            s.update(placeholder=w.placeholderText(), read_only=w.isReadOnly())
        if isinstance(w, W.QTableWidget):
            s.update(rows=w.rowCount(), columns=w.columnCount(), headers=[w.horizontalHeaderItem(i).text() for i in range(w.columnCount())], drag=w.dragEnabled())
            s['cells'] = [[{'item': w.item(r,c).text() if w.item(r,c) else None, 'widget': state(w.cellWidget(r,c)) if w.cellWidget(r,c) else None, 'children': [state(x) for x in w.cellWidget(r,c).findChildren(W.QWidget) if isinstance(x,(W.QAbstractButton, W.QLineEdit, W.QLabel))] if w.cellWidget(r,c) else []} for c in range(w.columnCount())] for r in range(w.rowCount())]
        return s
    b, c = build(baseline, 'before'), build(candidate, 'after')
    required = widgets(b)
    comparisons = []
    def compare(label):
        candidate_widgets = widgets(c)
        for name, bw in required.items():
            require(name in candidate_widgets, 'Runtime original widget missing: ' + name)
            require(state(bw) == state(candidate_widgets[name]), 'Widget-state mismatch in ' + label + ': ' + name + '\n' + repr(state(bw))[:1200] + '\n' + repr(state(candidate_widgets[name]))[:1200])
        require(b.is_live_mode == c.is_live_mode, 'Mode flag mismatch')
        comparisons.append(label)
    compare('startup synthetic LIVE')
    for mode, has_file, undo, calib in [(False, False, False, False), (False, True, True, False), (False, True, True, True), (True, True, True, True), (True, False, False, False)]:
        for h in (b,c):
            h.test_track_path = '/offline/test.mp4' if has_file else None
            h.undo_history = collections.deque([{'type':'divider'}] if undo else [])
            h.calib_loop_active = calib
            h.live_mode_slider.setChecked(mode)
            h.toggle_live_mode()
        pump()
        compare('mode=' + str(mode) + ',file=' + str(has_file) + ',undo=' + str(undo) + ',calib=' + str(calib))
    # Safe actual scrub state logic, with only a fake isRunning hook.
    for running, locked in [(False,False),(True,False),(True,True),(False,True)]:
        for h in (b,c):
            h.worker = types.SimpleNamespace(isRunning=lambda running=running: running) if running else None
            h.scrub_lock_checkbox.setChecked(locked)
            h._update_scrub_controls_state()
        compare('playing=' + str(running) + ',locked=' + str(locked))
    def prepare(h):
        h.test_track_path = '/offline/test.mp4'
        h.calib_loop_active = False
        h.live_mode_slider.setChecked(False)
        h.toggle_live_mode()
        h.scrub_lock_checkbox.setChecked(False)
        h._update_scrub_controls_state()
    for h in (b,c): prepare(h)
    # Actual Qt events: each button -> exactly one target callback. No file dialogs run.
    clicks = [('add_button','add_tracks'), ('add_encore_button','add_encore_divider'), ('stop_button','stop_all_activity'), ('arduino_panel_button','_show_arduino_panel'), ('zoom_scale_button','open_zoom_dialog'), ('save_button','save_setlist'), ('load_button','load_setlist'), ('export_setlist_button','export_setlist'), ('play_test_button','play_test_track')]
    def reveal(h, widget):
        for tabs in h.findChildren(W.QTabWidget):
            for i in range(tabs.count()):
                if tabs.widget(i) is widget or tabs.widget(i).isAncestorOf(widget): tabs.setCurrentIndex(i)
        for scroll in h.findChildren(W.QScrollArea):
            if scroll.widget() and scroll.widget().isAncestorOf(widget): scroll.ensureWidgetVisible(widget, 4, 4)
        pump()
    for h in (b,c):
        h.resize(1366,768)
        pump()
        for name, callback in clicks:
            w = getattr(h,name); reveal(h,w)
            before = len([x for x in h.calls if x[0] == callback])
            require(w.isEnabled() and w.isVisible(), 'Unreachable action: ' + name)
            T.QTest.mouseClick(w, C.Qt.MouseButton.LeftButton)
            pump()
            require(len([x for x in h.calls if x[0] == callback]) == before+1, 'Button signal is not exactly once: ' + name)
        for port in (1,2):
            w = h.test_port_buttons[port]; reveal(h,w)
            h.calls.clear()
            T.QTest.mouseClick(w, C.Qt.MouseButton.LeftButton)
            pump()
            matched = [x for x in h.calls if x[0] == 'run_port_test']
            require(matched == [('run_port_test',(port,))], 'MIDI port lambda capture wrong: ' + repr(matched))
        h.midi_offset_slider.setValue(-123)
        require(h.midi_offset_spinbox.value() == -123, 'Slider -> spin binding broken')
        h.midi_offset_spinbox.setValue(87)
        require(h.midi_offset_slider.value() == 87, 'Spin -> slider binding broken')
        h.reset_midi_offset()
        require(h.midi_offset_slider.value() == h.midi_offset_spinbox.value() == 0, 'Offset reset broken')
        # Switch receives actual mouse input; real toggle_live_mode executes through its signal.
        reveal(h,h.live_mode_slider)
        old = h.is_live_mode
        before_toggle = len([x for x in h.calls if x[0]=='_real_toggle_live_mode'])
        T.QTest.mouseClick(h.live_mode_slider,C.Qt.MouseButton.LeftButton)
        pump()
        require(len([x for x in h.calls if x[0]=='_real_toggle_live_mode']) == before_toggle+1, 'Mode click did not invoke exactly one real handler')
        require(h.is_live_mode != old, 'LIVE switch mouse input ineffective')
        require(h.arduino_panel_button.isEnabled(), 'Arduino incorrectly EDIT-gated')
        require(h.stop_button.isEnabled(), 'STOP incorrectly gated')
        prepare(h)
    compare('after actual clicks and value bindings')
    # Reparenting must not silently split Qt's auto-exclusive radio group.
    for h in (b,c):
        standard,precision=h.standard_timing_radio,h.high_precision_timing_radio
        require(standard.parentWidget() is precision.parentWidget(), 'Timing radios no longer share their auto-exclusive parent')
        require(standard.autoExclusive() and precision.autoExclusive(), 'Timing radio auto-exclusivity changed')
        for chosen,other in ((standard,precision),(precision,standard)):
            reveal(h,chosen); T.QTest.mouseClick(chosen,C.Qt.MouseButton.LeftButton); pump()
            require(chosen.isChecked() and not other.isChecked(), 'Timing radios no longer mutually exclusive on click')
    compare('radio auto-exclusivity')
    # Saved/user table-font values still drive real item and editor fonts, even after row painting.
    for size in (8,12,18,36):
        for h in (b,c):
            for row in (0,1,3):
                for col in (1,3,8): h.table.cellWidget(row,col).setStyleSheet('')
            h.font_size_spinbox.setValue(size); reveal(h,h.apply_font_button)
            T.QTest.mouseClick(h.apply_font_button,C.Qt.MouseButton.LeftButton); pump()
            require(h.current_table_font_size==size, 'Configured table font value not applied')
            for row in (0,1,3):
                require(h.table.item(row,0).font().pointSize()==size,'Table item ignored configured font')
                for col in (1,3,8):
                    editor = h.table.cellWidget(row,col)
                    if h is b:
                        # Frozen baseline QSS forces all QLineEdits to 12px; record, do not copy that defect.
                        require(editor.font().pixelSize()==12, 'Frozen baseline field-font constraint changed')
                    else:
                        require(editor.font().pointSize()==size, 'Table editor ignored configured font')
            h.highlight_row(0,is_playing=True); pump()
            for col in (1,3,8): require(h.table.cellWidget(0,col).font().pointSize()==size,'Playing-row painter overrode configured font')
            h.currently_playing_row=0; h.clear_highlight()
        compare('table font='+str(size))
    for h in (b,c):
        for row in (0,1,3):
            for col in (1,3,8): h.table.cellWidget(row,col).setStyleSheet('')
        h.font_size_spinbox.setValue(12); h.apply_table_font_size()
    if hasattr(c,'utility_tabs'):
        tabs=c.utility_tabs
        expected={'Setlist':['add_button','save_button','load_button','export_setlist_button','streamdeck_font_spinbox'], 'Settings':['display_combo','preload_combo','count_in_combo','standard_timing_radio','high_precision_timing_radio','count_in_font_spinbox','sync_show_trim_spinbox'], 'Testing':['test_file_button','play_test_button','calib_loop_button'], 'XR12':['xr12_enabled_checkbox','xr12_unity_spinbox','xr12_advanced_widget']}
        pages={tabs.tabText(i):tabs.widget(i) for i in range(tabs.count())}
        require(set(pages)==set(expected),'Utility navigation page contract changed')
        for title,names in expected.items():
            for name in names: require(pages[title].isAncestorOf(getattr(c,name)), 'Original control in wrong navigation page: '+name)
        for port in (1,2): require(pages['Testing'].isAncestorOf(c.test_port_buttons[port]),'MIDI test port in wrong page')
        for name in ('stop_button','quit_button','arduino_panel_button','zoom_scale_button','apply_zoom_checkbox','live_mode_slider','table','xr12_open_button','xr12_close_button','xr12_status_label'):
            require(not tabs.isAncestorOf(getattr(c,name)), 'Always-reachable control moved into utility tab: '+name)
    # Geometry/reachability at both sizes. Baseline constraints are diagnostics only;
    # the candidate must fit these viewports and retain an operable table.
    geometry = []
    feedback_checks = []
    statuses = ['XR12 Audience unavailable: MIDI port 3 not connected',
                'XR12 Audience open @ 96', 'XR12 Audience muted (closed @ 3)',
                'XR12 Audience disabled']
    def fully_exposed(h,w):
        r=C.QRect(w.mapTo(h,C.QPoint(0,0)),w.size())
        good=w.isVisible() and h.rect().contains(r) and w.width()>4 and w.height()>4
        for scroll in h.findChildren(W.QScrollArea):
            if scroll.widget() and scroll.widget().isAncestorOf(w):
                good=good and scroll.viewport().rect().contains(C.QRect(w.mapTo(scroll.viewport(),C.QPoint(0,0)),w.size()))
        return good
    def fit_text(label,description):
        # QLabel plain-text rendering: reserve frame, explicit margin and indentation.
        rect=label.contentsRect().adjusted(label.margin(),label.margin(),-label.margin(),-label.margin())
        width=rect.width()-max(0,label.indent())
        flags=int(C.Qt.TextFlag.TextWordWrap) if label.wordWrap() else 0
        measured=label.fontMetrics().boundingRect(C.QRect(0,0,max(1,width),100000),flags,label.text())
        require(width>0 and measured.width()<=width+1 and measured.height()<=rect.height()+1,
                description+' clips populated text: available='+str((width,rect.height()))+' measured='+str((measured.width(),measured.height())))
        return [width,rect.height(),measured.width(),measured.height()]
    def populated_feedback(size):
        # Both versions run the actual unchanged status and migration methods.
        for direction in ('horizontal','vertical'):
            zones=[{'enabled':True,'crop_w':1920,'crop_h':1080,'scale_w':1920,'scale_h':1080,
                    'border_px':500,'offset_y':5000 if i%2==0 else -5000} for i in range(5)]
            expected=('↔ ' if direction=='horizontal' else '↕ ')+'  '.join(
                'Z'+str(i+1)+':1920×1080→1920×1080 +500b y'+('+5000' if i%2==0 else '-5000') for i in range(5))
            for h in (b,c):
                h.zoom_config={'zones':copy.deepcopy(zones),'stack_direction':direction}
                h.apply_zoom_checkbox.setChecked(True)
                h._update_zoom_status_label()
                require(h.zoom_status_label.text()==expected,'Full five-zone summary changed/dropped')
            pump()
            require(len(expected)>=180,'Stress fixture unexpectedly short')
            require(c.zoom_status_label.wordWrap(),'Full five-zone summary must wrap, not clip horizontally')
            require(fully_exposed(c,c.zoom_status_label),'Zoom summary outside visible viewport at '+str(size))
            zoom_metrics=fit_text(c.zoom_status_label,'Five-zone '+direction+' summary at '+str(size))
            tabs=getattr(c,'utility_tabs',None)
            original=tabs.currentIndex() if tabs else None
            for live in (False,True):
                for h in (b,c):
                    h.live_mode_slider.setChecked(live); h.toggle_live_mode()
                for text in statuses:
                    for h in (b,c): h._set_xr12_status_text(text)
                    pump()
                    require(b.xr12_status_label.text()==c.xr12_status_label.text()==text,'XR12 status text changed')
                    for i in range(tabs.count() if tabs else 1):
                        if tabs:
                            bar=tabs.tabBar()
                            T.QTest.mouseClick(bar,C.Qt.MouseButton.LeftButton,pos=bar.tabRect(i).center()); pump()
                            require(tabs.currentIndex()==i and tabs.widget(i).isVisible(),'Utility tab unusable with full status text')
                        require(fully_exposed(c,c.xr12_status_label),'XR12 feedback hidden/clipped in '+('LIVE' if live else 'EDIT')+' tab '+str(i)+' at '+str(size))
                        fit_text(c.xr12_status_label,'XR12 feedback at '+str(size))
                        require(c.width()<=size[0] and c.height()<=size[1], 'Populated feedback expanded window beyond viewport')
                        require(fully_exposed(c,c.zoom_status_label), 'Zoom summary hidden/clipped after utility navigation')
                        fit_text(c.zoom_status_label,'Five-zone summary after utility navigation at '+str(size))
                        for name in ('stop_button','live_mode_slider','arduino_panel_button','zoom_scale_button','table'):
                            require(fully_exposed(c,getattr(c,name)),'Essential control clipped with populated feedback: '+name)
                        require(c.arduino_panel_button.isEnabled() and c.stop_button.isEnabled(),'Feedback stress EDIT-gated Arduino/STOP')
            if tabs: tabs.setCurrentIndex(original)
            feedback_checks.append({'size':size,'direction':direction,'summary_chars':len(expected),'zoom_text_metrics':zoom_metrics,'xr12_statuses':len(statuses),'modes':2,'tabs':tabs.count() if tabs else 1})
        for h in (b,c): prepare(h)
        pump()
    essentials = ['stop_button','live_mode_slider','arduino_panel_button','zoom_scale_button','table']
    for size in [(1366,768),(1920,1080)]:
        for label,h in [('before',b),('after',c)]:
            prepare(h); h.resize(*size); pump()
            geometry.append({'version':label,'size':size,'widget':'<window>','actual_size':[h.width(),h.height()]})
            if out:
                for tabs in h.findChildren(W.QTabWidget): tabs.setCurrentIndex(0)
                for scroll in h.findChildren(W.QScrollArea):
                    scroll.verticalScrollBar().setValue(0); scroll.horizontalScrollBar().setValue(0)
                pump()
                diagnostic = out / (label+'-main-'+str(size[0])+'x'+str(size[1])+'.png')
                require(h.grab().save(str(diagnostic)), 'Diagnostic screenshot save failed')
            if label == 'after':
                require(h.width() <= size[0] and h.height() <= size[1], 'Main window minimum size exceeds viewport: '+str((h.width(),h.height())))
            for name in essentials:
                w = getattr(h,name); reveal(h,w)
                p = w.mapTo(h,C.QPoint(0,0)); r = C.QRect(p,w.size())
                intersects = h.rect().contains(r)
                # A scroll ancestor must expose the entire essential button when requested.
                for s in h.findChildren(W.QScrollArea):
                    if s.widget() and s.widget().isAncestorOf(w):
                        q = w.mapTo(s.viewport(),C.QPoint(0,0))
                        intersects = intersects and s.viewport().rect().contains(C.QRect(q,w.size()))
                if label == 'after':
                    require(w.isVisible() and w.width()>4 and w.height()>4 and intersects, 'Clipped/unreachable essential control '+name+' at '+str(size))
                geometry.append({'version':label,'size':size,'widget':name,'rect':[r.x(),r.y(),r.width(),r.height()],'fully_visible':intersects})
            if label == 'after':
                populated_feedback(size)
                table = h.table
                require(table.viewport().width() >= 220 and table.viewport().height() >= 140, 'Track table too small to be useful')
                require(table.columnWidth(1)>=110, 'Track name column too narrow')
                # Arduino must follow zoom directly in the same visual section, not an edit-only parent.
                zoom = h.zoom_scale_button
                group = zoom.parentWidget()
                while group and not isinstance(group,W.QGroupBox): group=group.parentWidget()
                require(group is not None, 'Zoom group not found')
                arduino = h.arduino_panel_button
                require(not group.isAncestorOf(arduino), 'Arduino incorrectly nested inside zoom edit gate')
                parent = group.parentWidget()
                require(parent and parent.isAncestorOf(arduino), 'Arduino not in the zoom visual section')
                gy = group.mapTo(h,C.QPoint(0,0)).y()+group.height()
                ay = arduino.mapTo(h,C.QPoint(0,0)).y()
                require(0<=ay-gy<=36, 'Arduino not immediately below zoom: gap='+str(ay-gy))
                for tabs in h.findChildren(W.QTabWidget):
                    original=tabs.currentIndex()
                    for i in range(tabs.count()):
                        bar = tabs.tabBar()
                        require(bool(tabs.tabText(i).strip()), 'Navigation tab has no useful name')
                        T.QTest.mouseClick(bar,C.Qt.MouseButton.LeftButton,pos=bar.tabRect(i).center())
                        pump()
                        require(tabs.currentIndex()==i and tabs.widget(i).isVisible(),'Navigation tab click inoperable')
                    tabs.setCurrentIndex(original)
            # Render useful main view, not the last utility section visited by tests.
            for tabs in h.findChildren(W.QTabWidget): tabs.setCurrentIndex(0)
            for scroll in h.findChildren(W.QScrollArea):
                scroll.verticalScrollBar().setValue(0); scroll.horizontalScrollBar().setValue(0)
            pump()
            if out:
                p = out / (label+'-main-'+str(size[0])+'x'+str(size[1])+'.png')
                require(h.grab().save(str(p)), 'Screenshot save failed: '+str(p))
                screenshots.append(str(p))
    for h in (b,c):
        W.QWidget.hide(h)
        h.deleteLater()
    pump()
    sys.excepthook = old_excepthook
    return {'runtime':runtime,'state_comparisons':comparisons,'click_checks':len(clicks)*2+4,'baseline_visual_constraints':['Original QLineEdit stylesheet forces 12px before highlighting; candidate must honor configured 8/12/18/36pt.'],'geometry':geometry,'feedback_checks':feedback_checks,'screenshots':screenshots,'limitations':['No real hardware, MIDI, serial enumeration, hotkeys, saved session/config, playback, native Windows APIs or full-controller constructor executed.','SafeHost uses actual setup_ui, real table/Switch, real toggle_live_mode, populate_table and selected pure methods; external callbacks are counters.','Actual pure zoom migration/status and XR12 status methods execute on synthetic fixtures; hardware callbacks remain stubs. Optional hardware/zoom dialogs are not constructed.','AST normalization permits only enumerated visual setters and pure Qt helpers; it is deliberately conservative, not a sandbox for hostile input.']}


def presentation_status_contract(tree):
    setup=functions(class_map(tree)['LiveController'])['setup_ui']
    if 'self.utility_tabs' not in widget_bindings(setup):
        return {'skipped':'Original baseline has no utility navigation; runtime geometry is diagnostic only.'}
    calls=[n for n in ast.walk(setup) if isinstance(n,ast.Call)]
    additions=[attr_path(n.func.value) for n in calls if method_name(n)=='addWidget' and n.args and attr_path(n.args[0])=='self.xr12_status_label']
    require(any(receiver!='xr12_layout' for receiver in additions), 'XR12 feedback remains confined to XR12 utility page')
    require(any(attr_path(n.func)=='self.zoom_status_label.setWordWrap' and len(n.args)==1 and isinstance(n.args[0],ast.Constant) and n.args[0].value is True for n in calls), 'Full five-zone zoom summary has no word-wrap')
    require(any(attr_path(n.func)=='self.zoom_status_label.setSizePolicy' and len(n.args)==2 and attr_path(n.args[1]) in {'QSizePolicy.Policy.Preferred','QSizePolicy.Policy.Minimum','QSizePolicy.Policy.MinimumExpanding','QSizePolicy.Policy.Expanding'} for n in calls), 'Zoom summary has no vertically accommodating size policy')
    return {'xr12_added_to':additions,'zoom_wrap':True,'measured_visibility':'Requires real Qt run; AST checks are canaries only.'}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--baseline',required=True,type=Path)
    p.add_argument('--screenshot-dir',type=Path)
    p.add_argument('--ast-only',action='store_true')
    args=p.parse_args()
    report={'passed':False,'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        baseline, bmeta=load_source(args.baseline)
        require(bmeta['sha256']==BASELINE_SHA256, 'Baseline hash mismatch; refusing untrusted comparison: '+bmeta['sha256'])
        candidate,cmeta=load_source(args.source)
        report.update(baseline=bmeta,source=cmeta)
        report['negative_selftests_rejected']=negative_selftests(baseline)
        report['ast']=strict_ast(baseline,candidate)
        report['reviewed_helper_negatives']=reviewed_negative_selftests(baseline,candidate)
        report['presentation_status']=presentation_status_contract(candidate)
        if not args.ast_only:
            report['qt']=qt_runtime(baseline,candidate,args.screenshot_dir,report['ast']['new_visual_helpers'])
        else:
            report['limitations']=['AST-only run; real Qt state/events/geometry/render checks NOT executed.']
        report['passed']=True
        print(json.dumps(report,indent=2,ensure_ascii=False))
        return 0
    except Exception as e:
        report['error']=str(e)
        report['traceback']=traceback.format_exc()
        print(json.dumps(report,indent=2,ensure_ascii=False))
        return 1

if __name__=='__main__':
    raise SystemExit(main())
