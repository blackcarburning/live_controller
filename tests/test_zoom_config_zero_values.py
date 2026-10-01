"""Regression tests: explicit zero values in the multi-zone zoom config.

Unlike tests/test_zoom_helpers.py (which mirrors helpers by hand), these tests
extract the *real* pure helpers from live_controller.py via ``ast`` so they can
run headless without importing PyQt, and cannot drift out of sync.

Covers the bug where changing a zone border from 14 px to 0 px (or importing a
JSON config with ``"border_px": 0``) made the composite appear to reset to the
uncropped/default state.
"""

import ast
import copy
import os
import unittest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "live_controller.py")
_NAMES = {
    "NUM_ZONES", "_ZONE_INT_DEFAULTS", "_COMPOSITE_INT_DEFAULTS",
    "_default_zone", "_zoom_int", "_normalize_zone",
    "_migrate_zoom_config", "_build_vf_for_zones",
}


def _load_helpers():
    with open(_SRC, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=_SRC)
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _NAMES:
            body.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in _NAMES for t in node.targets):
            body.append(node)
    ns = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), _SRC, "exec"), ns)
    missing = _NAMES - set(ns)
    if missing:
        raise RuntimeError(f"helpers not found in live_controller.py: {missing}")
    return ns


_H = _load_helpers()
_migrate = _H["_migrate_zoom_config"]
_build_vf = _H["_build_vf_for_zones"]
_zoom_int = _H["_zoom_int"]


def _zone(crop_x=0, crop_y=0, crop_w=960, crop_h=1080, border_px=0, **kw):
    z = {"enabled": True, "crop_x": crop_x, "crop_y": crop_y,
         "crop_w": crop_w, "crop_h": crop_h, "scale_w": -1, "scale_h": -1,
         "border_px": border_px, "offset_y": 0, "mode": "crop"}
    z.update(kw)
    return z


def _cfg(border):
    """Two-zone composite with a whole-composite crop sized for 14 px borders."""
    return {
        "zones": [_zone(0, 0, border_px=border), _zone(960, 0, border_px=border)],
        "stack_direction": "horizontal",
        "frame_snapshot_path": "",
        "out_w": 1920, "out_h": 1080, "out_sim_enabled": False,
        # Composite with 14 px borders is (988*2) x 1108 = 1976 x 1108
        "comp_crop_x": 0, "comp_crop_y": 0,
        "comp_crop_w": 1976, "comp_crop_h": 1108,
        "comp_scale_w": 1920, "comp_scale_h": 1080,
    }


class ZoomIntTests(unittest.TestCase):
    def test_zero_is_preserved(self):
        self.assertEqual(_zoom_int(0, 14), 0)
        self.assertEqual(_zoom_int("0", 14), 0)
        self.assertEqual(_zoom_int(0.0, 14), 0)

    def test_missing_or_invalid_falls_back(self):
        for bad in (None, "", "abc", True, [], {}):
            self.assertEqual(_zoom_int(bad, 7), 7, bad)

    def test_numeric_strings_and_floats(self):
        self.assertEqual(_zoom_int("14", 0), 14)
        self.assertEqual(_zoom_int(14.0, 0), 14)
        self.assertEqual(_zoom_int(-1, 0), -1)


class MigrateZeroValueTests(unittest.TestCase):
    def test_border_zero_preserved_with_composite(self):
        m = _migrate(_cfg(0))
        self.assertEqual([z["border_px"] for z in m["zones"][:2]], [0, 0])
        self.assertTrue(all(z["enabled"] for z in m["zones"][:2]))
        self.assertEqual(m["comp_crop_w"], 1976)
        self.assertEqual(m["comp_scale_w"], 1920)
        self.assertEqual(m["zones"][1]["crop_x"], 960)

    def test_explicit_zero_offsets_and_origins_preserved(self):
        cfg = _cfg(0)
        cfg["zones"][0].update(crop_x=0, crop_y=0, offset_y=0)
        cfg.update(comp_crop_x=0, comp_crop_y=0)
        m = _migrate(cfg)
        z0 = m["zones"][0]
        self.assertEqual((z0["crop_x"], z0["crop_y"], z0["offset_y"]), (0, 0, 0))
        self.assertEqual((m["comp_crop_x"], m["comp_crop_y"]), (0, 0))

    def test_null_and_string_values_do_not_break_load(self):
        cfg = _cfg(14)
        cfg["zones"][0]["border_px"] = None
        cfg["zones"][1]["border_px"] = "0"
        cfg["comp_crop_x"] = None
        m = _migrate(cfg)
        self.assertEqual(m["zones"][0]["border_px"], 0)
        self.assertEqual(m["zones"][1]["border_px"], 0)
        self.assertEqual(m["comp_crop_x"], 0)
        self.assertIsNotNone(_build_vf(cfg))

    def test_migration_is_idempotent_and_does_not_mutate_input(self):
        cfg = _cfg(0)
        before = copy.deepcopy(cfg)
        once = _migrate(cfg)
        self.assertEqual(cfg, before)
        self.assertEqual(_migrate(once), once)

    def test_old_single_zone_format_still_migrates(self):
        m = _migrate({"enabled": True, "crop_x": 0, "crop_y": 0,
                      "crop_w": 1280, "crop_h": 720, "scale_w": -1, "scale_h": -1})
        z0 = m["zones"][0]
        self.assertTrue(z0["enabled"])
        self.assertEqual((z0["crop_w"], z0["crop_h"], z0["border_px"]), (1280, 720, 0))
        self.assertEqual(m["comp_crop_w"], 0)
        self.assertEqual(m["out_w"], -1)


class BuildVfBorderZeroTests(unittest.TestCase):
    def test_border_14_keeps_original_comp_crop(self):
        vf = _build_vf(_cfg(14))
        self.assertIn("pad=iw+28:ih+28:14:14:black", vf)
        self.assertIn("crop=1976:1108:0:0", vf)
        self.assertIn("scale=1920:1080", vf)

    def test_border_zero_keeps_composite_and_clamps_crop(self):
        vf = _build_vf(_cfg(0))
        self.assertIsNotNone(vf)
        self.assertNotIn("pad=iw+", vf)
        self.assertIn("hstack=inputs=2", vf)
        # Composite is now 1920x1080 — the stale 1976x1108 crop must be clamped
        # or ffmpeg rejects the crop and mpv drops the whole filter graph.
        self.assertIn("crop=1920:1080:0:0", vf)
        self.assertNotIn("crop=1976:1108", vf)
        self.assertIn("scale=1920:1080", vf)

    def test_single_zone_border_zero_clamps_crop(self):
        cfg = _cfg(0)
        cfg["zones"] = [_zone(0, 0, crop_w=1920, crop_h=1080)]
        cfg.update(comp_crop_x=10, comp_crop_y=5, comp_crop_w=1948, comp_crop_h=1108)
        vf = _build_vf(cfg)
        self.assertIn("crop=1910:1075:10:5", vf)

    def test_in_bounds_comp_crop_unchanged(self):
        cfg = _cfg(0)
        cfg.update(comp_crop_x=100, comp_crop_y=50, comp_crop_w=1600, comp_crop_h=900)
        self.assertIn("crop=1600:900:100:50", _build_vf(cfg))

    def test_comp_crop_zero_is_still_noop(self):
        cfg = _cfg(0)
        cfg.update(comp_crop_w=0, comp_crop_h=0)
        vf = _build_vf(cfg)
        self.assertNotIn("hstack=inputs=2,crop=", vf)


if __name__ == "__main__":
    unittest.main()
