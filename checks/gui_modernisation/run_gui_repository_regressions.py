"""Run selected existing safe controller tests without pytest or app imports."""
import contextlib
import importlib
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))
suite = unittest.TestSuite()
loader = unittest.defaultTestLoader
for name in ("tests.test_xr12_audience_helpers", "tests.test_xr12_connection", "tests.test_zoom_config_zero_values"):
    suite.addTests(loader.loadTestsFromName(name))

class MiniMonkeyPatch:
    def __init__(self, stack):
        self.stack = stack
    def setattr(self, target, value):
        if target != "builtins.open":
            raise AssertionError("Unreviewed monkeypatch target: " + str(target))
        self.stack.enter_context(patch(target, value))

def adapted(fn):
    def run():
        with contextlib.ExitStack() as stack:
            fn(MiniMonkeyPatch(stack))
    return run

for name in ("tests.test_zoom_helpers", "tests.test_mk_socket_helpers"):
    module = importlib.import_module(name)
    for key in sorted(vars(module)):
        fn = getattr(module, key)
        if key.startswith("test_") and inspect.isfunction(fn):
            params = list(inspect.signature(fn).parameters)
            if params and params != ["monkeypatch"]:
                raise AssertionError("Unexpected fixture: " + key)
            case = unittest.FunctionTestCase(adapted(fn) if params else fn, description=name + "." + key)
            suite.addTest(case)
assert suite.countTestCases() == 108, suite.countTestCases()
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() and result.testsRun == 108 else 1)
