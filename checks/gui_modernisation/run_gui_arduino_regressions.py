#!/usr/bin/env python3
"""Run the original 74 Arduino regressions against presentation-only source.

Never imports/executes the controller module. Original test files are run with
runpy under a non-main name, then loaded by unittest. One assertEqual invocation
in one source-regression test permits only approved XR12 palette/style literal
changes, after an independent fail-closed AST comparison. All other assertions,
test bodies, fake devices, lifecycle regressions and Qt checks remain original.

Default --suite all retains 56 + 11 + 7 = 74 tests, with skips treated as failure.
--suite mocked runs the original 67 non-Qt tests for gateway/offline evidence;
this is explicitly NOT a substitute for the full intended-Windows 74-test run.
--verify-only exercises compatibility/tamper gates without loading any tests/Qt.
"""
import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import types
import unittest

TEST_FILES = (
    ('mocked', 'test_controller_arduino_panel.py', 56),
    ('mocked', 'test_arduino_review_regressions.py', 11),
    ('qt', 'check_arduino_panel_qt.py', 7),
)
STATUS_NAME = '_set_xr12_status_text'
PALETTE = {
    '#888': '#9aadc2',
    '#e67e22': '#e9b96e',
    '#27ae60': '#86d8b8',
    '#e74c3c': '#f497a7',
}
STYLE_CONSTANTS = {
    'font-size: 10px; color: ': 'font-size: 11px; color: ',
    '; font-style: italic;': '; font-style: normal;',
}
HELPER_SOURCE = '''
def _ui_role(widget, role):
    """Tag operator chrome for semantic styling without changing widget state."""
    widget.setProperty("uiRole", role)
    return widget

def _ui_surface(widget, surface="card"):
    """Style a specific container; borders never leak into its child labels."""
    widget.setProperty("uiSurface", surface)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return widget

def _ui_scroll_page(*groups):
    """Presentation-only utility page; keeps original controls and signals intact."""
    page = QWidget()
    page_layout = QVBoxLayout(page)
    page_layout.setContentsMargins(8, 5, 8, 8)
    page_layout.setSpacing(8)
    for group in groups:
        page_layout.addWidget(group)
    page_layout.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(page)
    return scroll

def _ui_fit_dialog(dialog, width, height):
    """Keep initial dialog chrome on the available screen without changing state."""
    screen = dialog.screen()
    if screen is not None:
        area = screen.availableGeometry()
        width = min(width, max(640, area.width() - 36))
        height = min(height, max(480, area.height() - 52))
    dialog.resize(width, height)

def _ui_scroll_layout(layout):
    """Scroll an existing numeric column, preserving its controls and signals."""
    content = QWidget()
    content.setLayout(layout)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setMinimumWidth(285)
    scroll.setWidget(content)
    return scroll
'''


def require(value, message):
    if not value:
        raise AssertionError(message)


def dump(node):
    return ast.dump(node, include_attributes=False)


def owner_methods(tree):
    owners = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LiveController']
    require(len(owners) == 1, 'Expected one LiveController AST class')
    return {n.name: n for n in owners[0].body if isinstance(n, ast.FunctionDef)}


def ordered_nodes(node, predicate):
    return sorted((n for n in ast.walk(node) if predicate(n)), key=lambda n: (n.lineno, n.col_offset))


def is_color_assignment(node):
    return (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'color')


def status_styles(node):
    return ordered_nodes(node, lambda n: isinstance(n, ast.Call)
                         and ast.unparse(n.func) == 'self.xr12_status_label.setStyleSheet')


def normalized_status_pair(baseline, candidate):
    """Normalize only approved palette assignments and one exact stylesheet call.

    The candidate's complete remaining AST must equal baseline, including method
    signature, predicates, branches/order, messages, setText, expressions/targets,
    formatting variable and all calls. Added/deleted/reordered statements fail.
    No generic string/color removal or blanket setStyleSheet ignore is used.
    """
    require(baseline.name == candidate.name == STATUS_NAME, 'Wrong status method')
    left, right = copy.deepcopy(baseline), copy.deepcopy(candidate)
    before = ordered_nodes(left, is_color_assignment)
    after = ordered_nodes(right, is_color_assignment)
    require(len(before) == len(after) == 5, 'XR12 color assignment count changed')
    for old, new in zip(before, after):
        require(isinstance(old.value, ast.Constant) and old.value.value in PALETTE,
                'Unrecognized baseline status-color assignment')
        require(isinstance(new.value, ast.Constant), 'Status color became executable expression')
        require(new.value.value in (old.value.value, PALETTE[old.value.value]),
                'Unapproved status palette literal')
        new.value = copy.deepcopy(old.value)
    old_styles, new_styles = status_styles(left), status_styles(right)
    require(len(old_styles) == len(new_styles) == 1, 'XR12 stylesheet call count changed')
    old_style, new_style = old_styles[0], new_styles[0]
    require(not old_style.keywords and len(old_style.args) == 1,
            'Unexpected baseline stylesheet call shape')
    expected = copy.deepcopy(old_style)
    constants = [n for n in ast.walk(expected) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    require({n.value for n in constants} == set(STYLE_CONSTANTS),
            'Unrecognized baseline stylesheet constants')
    for value in constants:
        value.value = STYLE_CONSTANTS[value.value]
    require(dump(new_style) in (dump(old_style), dump(expected)),
            'XR12 stylesheet changed beyond approved exact font/color presentation')
    # Replace only after the entire changed call, including formatting variable,
    # has been checked against baseline or the independently generated expected.
    new_style.args = copy.deepcopy(old_style.args)
    require(dump(left) == dump(right), 'XR12 status business/control-flow AST changed')
    return dump(left), dump(right)


def verified_visual_helpers(tree):
    expected = {n.name: n for n in ast.parse(HELPER_SOURCE).body if isinstance(n, ast.FunctionDef)}
    found = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith('_ui_')}
    require(not (set(found) - set(expected)), 'Unknown presentation helper cannot enter Qt fixture')
    for name, node in found.items():
        require(dump(node) == dump(expected[name]), 'Presentation helper changed: ' + name)
    return list(found.values())


def exercise_tamper_guards(baseline, candidate):
    """Negative controls prove genuine business changes are still rejected."""
    normalized_status_pair(baseline, candidate)
    rejected = []
    def check(label, node):
        try:
            normalized_status_pair(baseline, node)
        except AssertionError:
            rejected.append(label)
        else:
            raise AssertionError('Compatibility gate accepted business mutation: ' + label)
    n = copy.deepcopy(candidate)
    branch = next(x for x in ast.walk(n) if isinstance(x, ast.Compare))
    branch.left = ast.Constant('unavailable-or-different-business-predicate')
    check('predicate', n)
    n = copy.deepcopy(candidate)
    call = next(x for x in ast.walk(n) if isinstance(x, ast.Call) and ast.unparse(x.func) == 'self.xr12_status_label.setText')
    call.args = [ast.Constant('changed user-facing status')]
    check('status-text', n)
    n = copy.deepcopy(candidate); n.body.append(ast.parse('self.open_xr12_audience()').body[0])
    check('extra-business-call', n)
    n = copy.deepcopy(candidate); n.body[-1], n.body[-2] = n.body[-2], n.body[-1]
    check('statement-order', n)
    n = copy.deepcopy(candidate)
    color = ordered_nodes(n, is_color_assignment)[0]
    color.value = ast.parse('self.open_xr12_audience()').body[0].value
    check('executable-color-expression', n)
    n = copy.deepcopy(candidate)
    styles = status_styles(n); styles[0].args = [ast.Constant('entirely different stylesheet')]
    check('unapproved-stylesheet', n)
    n = copy.deepcopy(candidate)
    joined = status_styles(n)[0].args[0]
    formatted = next(x for x in ast.walk(joined) if isinstance(x, ast.FormattedValue))
    formatted.value = ast.Name(id='text', ctx=ast.Load())
    check('stylesheet-format-variable', n)
    return rejected


def load_test_module(path):
    # run_path executes ONLY an original test harness, not controller source.
    # A non-main module name prevents its unittest.main side effect.
    namespace = runpy.run_path(str(path), run_name='gui_compat_' + path.stem)
    module = types.ModuleType(namespace['__name__'])
    module.__dict__.update(namespace)
    return module


def install_status_assertion_adapter(module, baseline_node, candidate_node, receipt):
    case = module.SourceTests
    original_assert = case.assertEqual
    baseline_dump, candidate_dump = dump(baseline_node), dump(candidate_node)
    expected_pair = normalized_status_pair(baseline_node, candidate_node)
    def assert_equal(self, first, second, msg=None):
        if (self._testMethodName == 'test_xr12_implementations_unchanged'
                and msg == STATUS_NAME and first == baseline_dump and second == candidate_dump):
            # Recheck the real methods used by the unchanged test, not just saved
            # preflight strings. Every other class/method comparison is exact.
            actual_candidate = module.METHODS[STATUS_NAME]
            actual_baseline = owner_methods(ast.parse(module.BASELINE_PATH.read_bytes()))[STATUS_NAME]
            current_pair = normalized_status_pair(actual_baseline, actual_candidate)
            original_assert(self, current_pair, expected_pair, 'XR12 compatibility operands changed')
            receipt['normalized_assertions'] += 1
            return original_assert(self, *current_pair, msg=msg)
        return original_assert(self, first, second, msg=msg)
    case.assertEqual = assert_equal


def augment_qt_namespace(module, helper_nodes):
    from PyQt6.QtWidgets import QGridLayout, QScrollArea
    module.ENV.update(QGridLayout=QGridLayout, QScrollArea=QScrollArea)
    # Extracted functions were exact-whitelisted above; definitions only.
    exec(compile(ast.Module(body=copy.deepcopy(helper_nodes), type_ignores=[]),
                 '<verified pure Qt presentation helpers>', 'exec'), module.ENV)
    # No test function or assertion is rewritten. Existing class constructor's
    # globals already refer to ENV, so these missing visual names resolve there.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--tests-dir', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--suite', choices=('all', 'mocked', 'qt'), default='all')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    for path in (args.source, args.baseline):
        require(path.is_file(), 'Required source/baseline missing: ' + str(path))
    source_raw, baseline_raw = args.source.read_bytes(), args.baseline.read_bytes()
    compile(source_raw, str(args.source), 'exec', dont_inherit=True)
    source_tree, baseline_tree = ast.parse(source_raw), ast.parse(baseline_raw)
    source_method = owner_methods(source_tree)[STATUS_NAME]
    baseline_method = owner_methods(baseline_tree)[STATUS_NAME]
    helpers = verified_visual_helpers(source_tree)
    negative_controls = exercise_tamper_guards(baseline_method, source_method)
    receipt = dict(source_sha256=hashlib.sha256(source_raw).hexdigest(),
                   baseline_sha256=hashlib.sha256(baseline_raw).hexdigest(),
                   suite=args.suite, normalized_assertions=0,
                   rejected_business_mutations=negative_controls,
                   verified_pure_qt_helpers=[n.name for n in helpers],
                   original_test_hashes={}, original_test_counts={})
    if args.verify_only:
        print('COMPATIBILITY_PREFLIGHT=' + json.dumps(receipt, sort_keys=True), flush=True)
        return 0
    os.environ['CONTROLLER_SOURCE'] = str(args.source.resolve())
    os.environ['CONTROLLER_BASELINE'] = str(args.baseline.resolve())
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    # No accidental screenshot writes from the original optional render path.
    os.environ.pop('ARDUINO_PANEL_SCREENSHOT', None)
    suites = []
    expected_count = 0
    loaded_paths = []
    for kind, filename, expected in TEST_FILES:
        if args.suite not in ('all', kind):
            continue
        path = args.tests_dir / filename
        require(path.is_file(), 'Required ORIGINAL test file missing: ' + str(path))
        raw = path.read_bytes()
        receipt['original_test_hashes'][filename] = hashlib.sha256(raw).hexdigest()
        module = load_test_module(path)
        if filename == 'test_controller_arduino_panel.py':
            install_status_assertion_adapter(module, baseline_method, source_method, receipt)
        elif kind == 'qt':
            augment_qt_namespace(module, helpers)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        count = suite.countTestCases()
        require(count == expected, '%s test count %s != %s' % (filename, count, expected))
        receipt['original_test_counts'][filename] = count
        suites.append(suite); expected_count += expected; loaded_paths.append((path, raw))
    require(expected_count == {'all': 74, 'mocked': 67, 'qt': 7}[args.suite], 'Required test count changed')
    print('COMPATIBILITY_PREFLIGHT=' + json.dumps(receipt, sort_keys=True), flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites))
    require(result.testsRun == expected_count, 'Original tests not all executed')
    require(not result.skipped, 'Required tests were skipped: ' + repr(result.skipped))
    if args.suite in ('all', 'mocked'):
        require(receipt['normalized_assertions'] == 1, 'Narrow original XR12 assertion was not exercised exactly once')
    for path, raw in loaded_paths:
        require(path.read_bytes() == raw, 'Original test was modified: ' + str(path))
    require(args.source.read_bytes() == source_raw, 'Source changed during regression run')
    require(args.baseline.read_bytes() == baseline_raw, 'Baseline changed during regression run')
    receipt.update(tests_run=result.testsRun, skips=len(result.skipped),
                   failures=len(result.failures), errors=len(result.errors),
                   successful=result.wasSuccessful())
    print('COMPATIBILITY_RESULT=' + json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, ImportError, OSError) as exc:
        print('COMPATIBILITY_BLOCKED=' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
        raise SystemExit(2)
