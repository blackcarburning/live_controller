"""Safe extracted production helper tests for isolated two-display source.

Legacy helpers must remain available for feature compatibility. Dual-output
specific helper seams are appended after the implementation is staged; they
are never replaced by a test-only reimplementation of production behavior.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    from .test_two_display_support import ExtractedSource
except ImportError:
    from test_two_display_support import ExtractedSource


def legacy_zone(**updates):
    result = {
        "enabled": True, "crop_x": 0, "crop_y": 0,
        "crop_w": 960, "crop_h": 1080, "scale_w": -1, "scale_h": -1,
        "border_px": 0, "offset_y": 0, "place_x": 0, "place_y": 0,
        "mode": "crop",
    }
    result.update(updates)
    return result


def legacy_config(**updates):
    result = {
        "zones": [legacy_zone(), legacy_zone(crop_x=960)],
        "stack_direction": "horizontal", "frame_snapshot_path": "",
        "out_w": 1920, "out_h": 1080, "out_sim_enabled": False,
        "free_placement_enabled": False,
        "comp_crop_x": 0, "comp_crop_y": 0, "comp_crop_w": 0,
        "comp_crop_h": 0, "comp_scale_w": -1, "comp_scale_h": -1,
    }
    result.update(updates)
    return result


class LegacyZoomCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()
        cls.helpers = cls.source.helpers()

    def migrate(self, value):
        return self.helpers["_migrate_zoom_config"](value)

    def vf(self, value):
        return self.helpers["_build_vf_for_zones"](value)

    def test_integer_zero_and_negative_auto_preserved(self):
        convert = self.helpers["_zoom_int"]
        for value in (0, "0", 0.0):
            self.assertEqual(convert(value, 14), 0)
        self.assertEqual(convert(-1, 12), -1)
        for bad in (None, "", "abc", True, [], {}):
            self.assertEqual(convert(bad, 7), 7)

    def test_exactly_five_zones_default(self):
        cfg = self.migrate({})
        self.assertEqual(len(cfg["zones"]), 5)
        self.assertTrue(cfg["zones"][0]["enabled"])
        self.assertFalse(any(z["enabled"] for z in cfg["zones"][1:]))

    def test_legacy_single_zone_preserves_zero_crop_and_border(self):
        cfg = legacy_zone(crop_w=1280, crop_h=720)
        migrated = self.migrate(cfg)
        self.assertEqual(len(migrated["zones"]), 5)
        for key in ("enabled", "crop_x", "crop_y", "crop_w", "crop_h",
                    "scale_w", "scale_h", "border_px", "offset_y"):
            self.assertEqual(migrated["zones"][0][key], cfg[key], key)

    def test_legacy_explicit_zero_survives_migration(self):
        cfg = legacy_config(comp_crop_w=1976, comp_crop_h=1108,
                            comp_scale_w=1920, comp_scale_h=1080)
        migrated = self.migrate(cfg)
        self.assertEqual([z["border_px"] for z in migrated["zones"][:2]], [0, 0])
        self.assertEqual([z["offset_y"] for z in migrated["zones"][:2]], [0, 0])
        self.assertEqual(migrated["comp_crop_x"], 0)
        self.assertEqual(migrated["comp_crop_y"], 0)
        self.assertEqual(migrated["zones"][1]["crop_x"], 960)

    def test_migration_no_mutation_idempotent_or_zone_aliasing(self):
        raw = legacy_config()
        before = copy.deepcopy(raw)
        once = self.migrate(raw)
        self.assertEqual(raw, before)
        self.assertEqual(self.migrate(once), once)
        once["zones"][0]["border_px"] = 27
        self.assertEqual(raw, before)
        self.assertNotEqual(once["zones"][1]["border_px"], 27)

    def test_legacy_json_roundtrip_preserves_values(self):
        raw = legacy_config()
        raw["zones"][0].update(border_px=0, offset_y=-17, scale_w=480, scale_h=540)
        expected = self.migrate(raw)
        self.assertEqual(self.migrate(json.loads(json.dumps(expected))), expected)

    def test_border_zero_does_not_reset_composite_to_raw(self):
        raw = legacy_config(comp_crop_w=1976, comp_crop_h=1108,
                            comp_scale_w=1920, comp_scale_h=1080)
        vf = self.vf(raw)
        self.assertIsNotNone(vf)
        self.assertIn("hstack=inputs=2", vf)
        self.assertIn("crop=1920:1080:0:0", vf)
        self.assertIn("scale=1920:1080", vf)
        self.assertNotIn("pad=iw+", vf)

    def test_border_and_output_y_are_after_shared_crop(self):
        raw = legacy_config(zones=[legacy_zone(crop_x=11, crop_y=13,
                            crop_w=800, crop_h=600, scale_w=400,
                            scale_h=300, border_px=8, offset_y=-9)])
        vf = self.vf(raw)
        self.assertIn("crop=800:600:11:13", vf)
        self.assertIn("scale=400:300", vf)
        self.assertIn("pad=iw+16:ih+16:8:8:black", vf)
        self.assertLess(vf.index("crop=800:600:11:13"), vf.index("scale=400:300"))
        self.assertLess(vf.index("scale=400:300"), vf.index("pad=iw+16"))

    def test_all_five_legacy_zones_build_without_losing_last_zone(self):
        raw = legacy_config(zones=[legacy_zone(crop_x=i*100, crop_w=100,
                                               crop_h=50) for i in range(5)])
        vf = self.vf(raw)
        self.assertIn("split=5", vf)
        self.assertIn("hstack=inputs=5", vf)
        self.assertIn("crop=100:50:400:0", vf)

    def test_legacy_vertical_and_canvas_output_controls_retained(self):
        raw = legacy_config(stack_direction="vertical", out_sim_enabled=True,
                            out_w=3000, out_h=3000)
        vf = self.vf(raw)
        self.assertIn("vstack=inputs=2", vf)
        self.assertIn("pad=3000:3000", vf)


class DualOutputConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()
        cls.h = cls.source.dual_helpers(injected={"MPV_PATH": "offline-mpv"})

    def migrate(self, value=None, hdmi_display=1):
        return self.h["_migrate_two_display_config"]({} if value is None else value, hdmi_display)

    def projection(self, cfg, output):
        return self.h["_two_display_output_config"](cfg, output)

    def test_default_five_shared_zones_default_to_hdmi(self):
        cfg = self.migrate()
        self.assertEqual(len(cfg["zones"]), 5)
        self.assertEqual(set(cfg["outputs"]), {"HDMI", "DP"})
        self.assertEqual([z["route"] for z in cfg["zones"]], ["hdmi"] * 5)
        self.assertEqual(cfg["outputs"]["HDMI"]["display_index"], 1)
        self.assertEqual(cfg["outputs"]["DP"]["display_index"], 2)
        self.assertTrue(self.h["_two_display_has_routes"](cfg, "HDMI"))
        self.assertFalse(self.h["_two_display_has_routes"](cfg, "DP"))
        self.assertEqual(self.migrate(hdmi_display=3)["outputs"]["HDMI"]["display_index"], 3)

    def test_legacy_migration_zero_preservation_for_both_outputs(self):
        raw = legacy_config(comp_crop_x=0, comp_crop_y=0, comp_crop_w=0,
                            comp_crop_h=0, comp_scale_w=-1, comp_scale_h=-1)
        raw["zones"][0].update(scale_w=0, scale_h=0, border_px=0, offset_y=0)
        cfg = self.migrate(raw)
        for output in ("HDMI", "DP"):
            p = cfg["outputs"][output]
            for key in ("comp_crop_x", "comp_crop_y", "comp_crop_w", "comp_crop_h"):
                self.assertEqual(p[key], 0, (output, key))
            self.assertEqual(p["zones"][0], {"scale_w": 0, "scale_h": 0, "border_px": 0, "offset_y": 0})
        self.assertEqual([z["crop_x"] for z in cfg["zones"][:2]], [0, 960])

    def test_migration_idempotent_input_not_mutated(self):
        raw = legacy_config()
        raw["user_extension"] = {"preserve": 0}
        before = copy.deepcopy(raw)
        cfg = self.migrate(raw)
        self.assertEqual(raw, before)
        self.assertEqual(self.migrate(cfg), cfg)
        self.assertEqual(cfg["user_extension"], {"preserve": 0})

    def test_per_output_transform_dicts_never_alias(self):
        cfg = self.migrate()
        cfg["outputs"]["HDMI"]["zones"][0]["border_px"] = 31
        self.assertEqual(cfg["outputs"]["DP"]["zones"][0]["border_px"], 0)
        self.assertEqual(cfg["outputs"]["HDMI"]["zones"][1]["border_px"], 0)
        cfg["outputs"]["DP"]["comp_crop_x"] = 73
        self.assertEqual(cfg["outputs"]["HDMI"]["comp_crop_x"], 0)

    def test_both_output_settings_json_roundtrip_independent(self):
        cfg = self.migrate()
        cfg["zones"][0]["route"] = "both"
        hdmi, dp = cfg["outputs"]["HDMI"], cfg["outputs"]["DP"]
        hdmi["zones"][0].update(scale_w=333, scale_h=222, border_px=0, offset_y=-7)
        dp["zones"][0].update(scale_w=444, scale_h=111, border_px=13, offset_y=9)
        hdmi.update(stack_direction="vertical", comp_crop_x=0, comp_crop_y=0,
                    comp_crop_w=200, comp_crop_h=150, comp_scale_w=600, comp_scale_h=400,
                    out_w=1280, out_h=720, out_sim_enabled=True, offset_frames=0)
        dp.update(stack_direction="horizontal", comp_crop_x=14, comp_crop_y=11,
                  comp_crop_w=300, comp_crop_h=200, comp_scale_w=900, comp_scale_h=500,
                  out_w=1920, out_h=1080, out_sim_enabled=True, offset_frames=-3)
        migrated = self.migrate(cfg)
        roundtrip = self.migrate(json.loads(json.dumps(migrated)))
        self.assertEqual(roundtrip, migrated)
        for output in ("HDMI", "DP"):
            projected = self.projection(roundtrip, output)
            self.assertEqual(projected["zones"][0]["crop_x"], cfg["zones"][0]["crop_x"])
            for key in ("scale_w", "scale_h", "border_px", "offset_y"):
                self.assertEqual(projected["zones"][0][key], cfg["outputs"][output]["zones"][0][key])
            for key in ("stack_direction", "comp_crop_x", "comp_crop_w", "comp_scale_w", "out_w"):
                self.assertEqual(projected[key], cfg["outputs"][output][key])

    def test_global_enable_routing_matrix_all_five_zones(self):
        cfg = self.migrate(legacy_config(zones=[legacy_zone(crop_x=i*100, crop_w=100,
                                      crop_h=50) for i in range(5)]))
        routes = ("hdmi", "dp", "both", "none", "both")
        for z, route in zip(cfg["zones"], routes):
            z["route"] = route
        self.assertEqual([z["enabled"] for z in self.projection(cfg, "HDMI")["zones"]],
                         [True, False, True, False, True])
        self.assertEqual([z["enabled"] for z in self.projection(cfg, "DP")["zones"]],
                         [False, True, True, False, True])
        cfg["zones"][2]["enabled"] = False
        for output in ("HDMI", "DP"):
            self.assertFalse(self.projection(cfg, output)["zones"][2]["enabled"])
        cfg["outputs"]["DP"]["enabled"] = False
        self.assertFalse(any(z["enabled"] for z in self.projection(cfg, "DP")["zones"]))

    def test_routes_compact_stitch_in_original_zone_order(self):
        cfg = self.migrate(legacy_config(zones=[legacy_zone(crop_x=i*100, crop_w=100,
                                      crop_h=50) for i in range(5)]))
        for i,z in enumerate(cfg["zones"]):
            z["route"] = "dp" if i in (1, 4) else "hdmi"
        hdmi = self.h["_two_display_build_vf"](cfg, "HDMI")
        dp = self.h["_two_display_build_vf"](cfg, "DP")
        self.assertIn("split=3", hdmi)
        self.assertIn("hstack=inputs=3", hdmi)
        self.assertIn("split=2", dp)
        self.assertIn("hstack=inputs=2", dp)
        self.assertLess(dp.index("crop=100:50:100:0"), dp.index("crop=100:50:400:0"))
        self.assertNotIn("crop=100:50:0:0", dp)

    def test_empty_output_never_raw_even_apply_zoom_disabled(self):
        cfg = self.migrate()
        cfg["apply_transforms"] = False
        vf = self.h["_two_display_build_vf"](cfg, "DP")
        self.assertTrue(vf)
        self.assertIn("black", vf)
        self.assertNotIn("null,setsar", vf)
        for z in cfg["zones"]:
            z["enabled"] = False
        for output in ("HDMI", "DP"):
            vf = self.h["_two_display_build_vf"](cfg, output)
            self.assertTrue(vf)
            self.assertIn("black", vf)

    def test_malformed_route_is_not_both_or_raw(self):
        cfg = self.migrate(legacy_config(zones=[legacy_zone(route="bad-route")]))
        self.assertEqual(cfg["zones"][0]["route"], "none")
        for output in ("HDMI", "DP"):
            self.assertFalse(self.h["_two_display_has_routes"](cfg, output))
            self.assertIn("black", self.h["_two_display_build_vf"](cfg, output))

    def test_output_y_shift_preserves_height(self):
        cfg = self.migrate(legacy_config(zones=[legacy_zone(crop_w=800, crop_h=600)]))
        for shift in (-9, 9):
            cfg["outputs"]["HDMI"]["zones"][0]["offset_y"] = shift
            vf = self.h["_two_display_build_vf"](cfg, "HDMI")
            self.assertIn("crop=iw:ih-9", vf)
            self.assertNotIn("crop=iw:ih:0:", vf)

    def test_source_crop_clamps_to_actual_media_not_operator_screen(self):
        cfg = self.migrate(legacy_config(zones=[legacy_zone(crop_x=1900, crop_y=1000,
                                                            crop_w=100, crop_h=100)]))
        vf = self.h["_two_display_build_vf"](cfg, "HDMI", source_size=(1280, 720))
        self.assertIn("crop=1:1:1279:719", vf)

    def test_display_duplicate_missing_primary_and_renamed_guard(self):
        rows = [{"index": 0, "name": "operator", "primary": True},
                {"index": 1, "name": "HDMI test", "primary": False},
                {"index": 2, "name": "DP test", "primary": False}]
        cfg = self.migrate()
        available, warnings = self.h["_two_display_resolve_outputs"](cfg, rows)
        self.assertEqual(available, {"HDMI": True, "DP": True})
        self.assertFalse(warnings)
        for invalid in (0, 7, -1):
            cfg["outputs"]["DP"]["display_index"] = invalid
            available, warnings = self.h["_two_display_resolve_outputs"](cfg, rows)
            self.assertTrue(available["HDMI"])
            self.assertFalse(available["DP"])
            self.assertTrue(warnings)
        cfg["outputs"]["DP"]["display_index"] = 1
        available, warnings = self.h["_two_display_resolve_outputs"](cfg, rows)
        self.assertEqual(available, {"HDMI": True, "DP": False})
        self.assertTrue(any("duplicate" in s for s in warnings))
        cfg["outputs"]["DP"].update(display_index=2, screen_name="disconnected display")
        available, warnings = self.h["_two_display_resolve_outputs"](cfg, rows)
        self.assertFalse(available["DP"])


class IsolatedPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="two-display-test-data-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        constants = {
            "CONFIG_FILE": "two_display_config.json", "SESSION_FILE": "two_display_session.json",
            "ZOOM_CONFIG_FILE": "two_display_zoom_config.json", "BPM_STORE_FILE": "two_display_bpm_store.json",
            "TRACK_NAME_STORE_FILE": "two_display_track_names.json",
            "ZOOM_FRAME_SNAPSHOT": "two_display_zoom_frame_snapshot.png",
        }
        self.h = self.source.namespace({"_TWO_DISPLAY_LEGACY_FILES", "_two_display_read_path",
                                        "_two_display_guard_write_path"}, injected=constants)
        self.mapping = self.h["_TWO_DISPLAY_LEGACY_FILES"]

    def test_new_file_precedence_and_read_only_legacy_fallback(self):
        files = {"config.json", "session.json", "zoom_config.json", "bpm_store.json",
                 "track_names.json", "zoom_frame_snapshot.png"}
        before = {name: ("SYNTHETIC-LEGACY-" + name).encode() for name in files}
        for name, data in before.items():
            (self.root / name).write_bytes(data)
        # Relative path semantics are injected; the process cwd never changes.
        proxy = mock.Mock(wraps=os)
        proxy.path = mock.Mock(wraps=os.path)
        proxy.path.exists.side_effect = lambda path: (self.root / path).exists()
        proxy.path.isfile.side_effect = lambda path: (self.root / path).is_file()
        self.h["os"] = proxy
        read_path = self.h["_two_display_read_path"]
        for new, legacy in self.mapping.items():
            self.assertEqual(read_path(new), legacy)
            (self.root / new).write_bytes(b"NEW-ONLY")
            self.assertEqual(read_path(new), new)
            self.assertEqual((self.root / legacy).read_bytes(), before[legacy])
        for name, data in before.items():
            self.assertEqual((self.root / name).read_bytes(), data)

    def test_write_guard_blocks_original_files_and_allows_new_paths(self):
        guard = self.h["_two_display_guard_write_path"]
        for new, legacy in self.mapping.items():
            with self.subTest(legacy=legacy):
                with self.assertRaisesRegex(ValueError, "read-only"):
                    guard(legacy)
                with self.assertRaises(ValueError):
                    guard(os.path.abspath(legacy))
                self.assertEqual(guard(new), new)
                self.assertEqual(guard(str(self.root / ("export-" + legacy))), str(self.root / ("export-" + legacy)))

    def test_missing_new_and_legacy_never_eagerly_create(self):
        proxy = mock.Mock(wraps=os)
        proxy.path = mock.Mock(wraps=os.path)
        proxy.path.exists.return_value = False
        proxy.path.isfile.return_value = False
        self.h["os"] = proxy
        for new in self.mapping:
            self.assertEqual(self.h["_two_display_read_path"](new), new)
        self.assertEqual(list(self.root.iterdir()), [])


class FrameAndCommandBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()
        cls.h = cls.source.dual_helpers(injected={"MPV_PATH": "offline-mpv"})

    def test_fractional_media_fps_frame_seek_math(self):
        fps = 30000 / 1001
        cmd = self.h["_two_display_seek_command"](10.0, 3, fps)
        self.assertEqual(cmd[0], "seek")
        self.assertAlmostEqual(cmd[1], 10.0 - 3 * 1001 / 30000, places=12)
        self.assertEqual(cmd[2:], ["absolute+exact"], "mpv seek accepts one flags argument")
        self.assertEqual(self.h["_two_display_seek_command"](0, 10, fps)[1], 0.0)
        self.assertGreater(self.h["_two_display_seek_command"](10, -3, fps)[1], 10)

    def test_frame_offsets_do_not_use_audible_master_pts_or_audio_options(self):
        coordinator = self.source.node("TwoDisplayCoordinator")
        text = self.source.segment(coordinator)
        self.assertNotIn("_two_display_video_offset_command(", text,
                         "Independent offsets belong to silent followers, not audible master PTS")
        cfg = self.h["_migrate_two_display_config"]({})
        command = self.h["_two_display_build_master_command"](
            "test.mp4", "master-pipe")
        for option in ("initial-audio-sync", "audio-delay", "speed=", "audio-pitch-correction", "setpts"):
            self.assertFalse(any(option in arg for arg in command), option)

    def test_primary_and_follower_commands_start_paused_and_black(self):
        cfg = self.h["_migrate_two_display_config"]({})
        builder = self.h["_two_display_build_playback_command"]
        for output, silent in (("HDMI", True), ("DP", True)):
            command = builder("test.mp4", "offline-pipe", cfg, output, silent=silent)
            self.assertIn("--pause", command)
            self.assertTrue(any(x.startswith("--vf=") and "black" in x for x in command))
            self.assertIn("--fs-screen=" + str(cfg["outputs"][output]["display_index"]), command)
            if silent:
                self.assertIn("--no-audio", command)
                self.assertIn("--mute=yes", command)
            else:
                self.assertNotIn("--no-audio", command)
                self.assertNotIn("--audio-delay", str(command))
            self.assertEqual(command[-1], "test.mp4")

    def test_headless_master_keeps_video_only_media_timeline(self):
        cfg = self.h["_migrate_two_display_config"]({})
        cmd = self.h["_two_display_build_master_command"]("silent-video.mp4", "pipe")
        self.assertIn("--vo=null", cmd)
        self.assertNotIn("--no-video", cmd)
        self.assertNotIn("--no-audio", cmd)
        self.assertFalse(any(x.startswith("--fs-screen") for x in cmd))

    def test_audio_only_and_calibration_length_paths(self):
        cfg = self.h["_migrate_two_display_config"]({})
        cmd = self.h["_two_display_build_master_command"]("test.wav", "pipe",
                         audio_only=True, max_duration_sec=12.5)
        self.assertIn("--no-video", cmd)
        self.assertIn("--length=12.5", cmd)
        self.assertNotIn("--fullscreen", cmd)
        self.assertNotIn("--no-audio", cmd)


if __name__ == "__main__":
    unittest.main()
