"""Candidate invariants checked from AST, without importing/starting the app.

Run: python -B -m unittest tests.test_two_display_invariants -v
The separately versioned source is mandatory for release qualification; unittest
skips candidate-dependent classes while the implementation is not yet staged.
"""
import ast
import copy
import hashlib
from pathlib import Path
import unittest

try:
    from .test_two_display_support import (
        BASELINE, BASELINE_SHA256, SOURCE, ExtractedSource,
        ast_dump, literal_assignments,
    )
except ImportError:
    from test_two_display_support import (
        BASELINE, BASELINE_SHA256, SOURCE, ExtractedSource,
        ast_dump, literal_assignments,
    )


class OriginalPreservationTests(unittest.TestCase):
    def test_original_source_exact_authorized_lf_hash(self):
        data = BASELINE.read_bytes()
        self.assertEqual(hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest(), BASELINE_SHA256)
        self.assertNotIn(b"\r", data.replace(b"\r\n", b"\n"))
        if b"\r\n" in data:
            self.assertEqual(hashlib.sha256(data).hexdigest(),
                             "56a91df1849bc879584a1ec3cecec2cbdf8222282a21263758cb975c3363e4ee")

    def test_candidate_is_a_separate_path(self):
        self.assertNotEqual(SOURCE, BASELINE)
        self.assertEqual(SOURCE.name, "live_controller_two_display.py")


# Unrelated hardware, MIDI helpers, widgets and transport/interaction semantics
# must remain identical. The explicitly changed dual-output seams are tested
# behaviorally in companion tests rather than weakening this preservation gate.
UNCHANGED_TOP_LEVEL = (
    "DraggableTableWidget", "GlobalHotkeyListener", "MidiTestWorker",
    "clamp_midi_value", "build_audience_fader_messages", "build_audience_mute_messages",
    "interpolate_midi_value", "migrate_xr12_mute_polarity", "FadeCommand",
    "Xr12AudienceState", "Xr12ConnectionAttempt", "ArduinoConnectionAttempt",
    "_arduino_serial_target", "_arduino_windows_lpt_devices", "_arduino_list_devices",
    "ArduinoSerialWriter", "ArduinoPanel", "Xr12AudienceController",
    "ZoomCropCanvas", "StretchCanvas", "ZoomScaleDialog", "Switch", "PositionPoller",
)
UNCHANGED_CONTROLLER_METHODS = (
    "_configure_startup_hardware", "_check_playback_midi", "on_playback_error",
    "on_playback_finished", "trigger_sync_show", "stop_sync_show",
)
BASELINE_DIALOG_CONTROLS = (
    "_select_btn", "_video_label", "_play_btn", "_pause_btn", "_capture_btn",
    "_beg_btn", "_frame_back_btn", "_frame_fwd_btn", "_mz_scrub_slider",
    "_mz_pos_label", "_mz_dur_label", "_ext_source_combo", "_ext_toggle_btn",
    "_ext_live_refresh_btn", "_export_btn", "_import_btn", "_tabs",
    "_zone_crop_canvases", "_zone_stretch_canvases", "_zone_stacked",
    "_zone_enable_cbs", "_zone_mode_crop_rbs", "_zone_mode_stretch_rbs",
    "_zone_x_sbs", "_zone_y_sbs", "_zone_w_sbs", "_zone_h_sbs",
    "_zone_sw_sbs", "_zone_sh_sbs", "_zone_border_sbs", "_zone_offset_y_sbs",
    "_stitch_h", "_stitch_v", "_comp_x_sb", "_comp_y_sb", "_comp_w_sb",
    "_comp_h_sb", "_comp_sw_sb", "_comp_sh_sb", "_out_w_sb", "_out_h_sb",
    "_out_sim_playback_cb", "_comp_crop_canvas", "_comp_stretch_canvas",
    "_refresh_btn", "_final_canvas", "_ok_btn", "_cancel_btn", "_status",
)


# Exactly reviewed safety changes in the new app. These full-method pins are
# NOT wildcards: all remaining class fields/methods still compare exactly with
# the baseline, and changing even a permitted method fails its reviewed pin.
REVIEWED_SAFETY_METHOD_PINS = {
    "ZoomScaleDialog": {
        "_launch_mpv":"7ef4fd6fbc43c8c717a8d0d04b01f06035281643616d316fea8a7d8a1afae8ac",
        "_send_ipc":"2bf0e09e2f2afa7701431367212675a4506a057198f45d02e849f6354e8e942d",
        "_stop_mpv":"3cc5496ce7bbd947b2afedf48e4cce3c8d60e0bf8c6579ab2f55ca8c6ad14b36",
    },
    "PositionPoller": {
        "__init__":"b91959d1b5cc3823c877989d9759f1727afb2def8f44039190d856a606cb34c5",
        "stop":"07cfaf1576d5843a62f21be06ec883a98b8476b82689ec28ef267bd54de13adb",
        "run":"cc8c3849e69ccfe81a5b0e328891f5378bdc0fd10432dd444e783508d437ab4a",
    },
}


def reviewed_class_projection(source, baseline, name):
    node = copy.deepcopy(source.node(name))
    pins = REVIEWED_SAFETY_METHOD_PINS.get(name,{})
    for index, method in enumerate(node.body):
        if isinstance(method,ast.FunctionDef) and method.name in pins:
            actual = hashlib.sha256(ast_dump(method).encode("utf-8")).hexdigest()
            if actual != pins[method.name]:
                raise AssertionError("Reviewed safety method changed: "+name+"."+method.name)
            node.body[index] = copy.deepcopy(baseline.method(name,method.name))
    return node


REVIEWED_COMPLETION_METHOD_PINS = {
    "on_playback_error":"c5b340bdb09c40bcc1c6e1442580710419d922209ae97fcb9b1f1d97daf827f0",
    "on_playback_finished":"1cd059e5ace927f055409f867335c3a4f22792a59c55df12fe9b95f0f861a2a9",
}


def reviewed_finish_projection(source, name):
    method = copy.deepcopy(source.method("LiveController",name))
    if name not in REVIEWED_COMPLETION_METHOD_PINS:
        return method
    actual = hashlib.sha256(ast_dump(method).encode("utf-8")).hexdigest()
    if actual != REVIEWED_COMPLETION_METHOD_PINS[name]:
        raise AssertionError("Unreviewed completion method changed: "+name)
    # Reviewed b01 P1 fix: retain exact worker generations through real QThread
    # exit. Only the pinned owner guard/prelude is removed. All original UI,
    # linked-track, error/stop and LED callback bodies remain exact below.
    prelude_count = 4
    del method.body[1:1+prelude_count]
    method.args = ast.parse("def "+name+"(self"+(", msg" if name=="on_playback_error" else "")+"):\n    pass").body[0].args
    if name == "on_playback_finished":
        method.body[0] = ast.Expr(value=ast.Constant(value="Cleans up the UI and state after playback finishes."))
        autoplay = next(n for n in method.body if isinstance(n,ast.If) and
                        any(isinstance(v,ast.Name) and v.id=="finished_row" for v in ast.walk(n.test)))
        expected_guard = ast_dump(ast.parse("not self._app_is_closing",mode="eval").body)
        if not isinstance(autoplay.test,ast.BoolOp) or ast_dump(autoplay.test.values[0]) != expected_guard:
            raise AssertionError("Missing exact no-autoplay-during-close guard")
        del autoplay.test.values[0]
    return method


class CandidateStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()
        cls.baseline = ExtractedSource(BASELINE)

    def test_candidate_compiles_without_importing(self):
        compile(self.source.bytes, str(self.source.path), "exec")

    def test_unrelated_features_preserved_exact_ast(self):
        for name in UNCHANGED_TOP_LEVEL:
            with self.subTest(definition=name):
                self.assertEqual(ast_dump(reviewed_class_projection(self.source,self.baseline,name)),
                                 ast_dump(self.baseline.node(name)))
        for name in UNCHANGED_CONTROLLER_METHODS:
            with self.subTest(method=name):
                self.assertEqual(ast_dump(reviewed_finish_projection(self.source,name)),
                                 ast_dump(self.baseline.method("LiveController", name)))

    def test_reviewed_safety_pins_reject_a_mutated_allowed_method(self):
        changed = copy.copy(self.source)
        changed.defs = dict(self.source.defs)
        changed.defs["ZoomScaleDialog"] = copy.deepcopy(self.source.node("ZoomScaleDialog"))
        launch = next(n for n in changed.defs["ZoomScaleDialog"].body
                      if isinstance(n,ast.FunctionDef) and n.name=="_launch_mpv")
        constant = next(n for n in ast.walk(launch) if isinstance(n,ast.Constant) and n.value=="--no-audio")
        constant.value = "--audio=yes"
        with self.assertRaisesRegex(AssertionError,"Reviewed safety method changed"):
            reviewed_class_projection(changed,self.baseline,"ZoomScaleDialog")

    def test_completion_pins_reject_deleted_running_guard_or_changed_led_callback(self):
        for method_name, target_attr in (("on_playback_finished","_two_display_thread_running"),
                                         ("on_playback_finished","send_led_command"),
                                         ("on_playback_error","_two_display_defer_thread_completion")):
            changed = copy.copy(self.source)
            changed.defs = dict(self.source.defs)
            changed.defs["LiveController"] = copy.deepcopy(self.source.node("LiveController"))
            method = changed.method("LiveController",method_name)
            attr = next(n for n in ast.walk(method) if isinstance(n,ast.Attribute) and n.attr==target_attr)
            attr.attr = "UNSAFE_MUTATION"
            with self.assertRaisesRegex(AssertionError,"Unreviewed completion method changed"):
                reviewed_finish_projection(changed,method_name)

    def test_no_existing_controller_or_dialog_methods_removed(self):
        for class_name in ("LiveController", "MultiZoomScaleDialog", "MidiSyncWorker"):
            def names(node):
                return {m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
            missing = names(self.baseline.node(class_name)) - names(self.source.node(class_name))
            self.assertFalse(missing, class_name + " lost methods " + repr(sorted(missing)))

    def test_existing_editor_controls_still_constructed(self):
        node = self.source.method("MultiZoomScaleDialog", "_setup_ui")
        attributes = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        self.assertFalse(set(BASELINE_DIALOG_CONTROLS) - attributes,
                         "baseline editor controls removed: " + repr(sorted(set(BASELINE_DIALOG_CONTROLS) - attributes)))

    def test_new_persistent_files_cannot_alias_legacy_files(self):
        values = literal_assignments(self.source)
        baseline = literal_assignments(self.baseline)
        keys = ("CONFIG_FILE", "SESSION_FILE", "ZOOM_CONFIG_FILE", "ZOOM_FRAME_SNAPSHOT")
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, values, "persistent path must be a reviewable literal")
                self.assertTrue(Path(values[key]).name.startswith("two_display_"), (key, values.get(key)))
                self.assertNotEqual(values[key], baseline[key])
        self.assertEqual(len({values[key] for key in keys}), len(keys))

    def test_no_import_of_original_controller(self):
        for node in ast.walk(self.source.tree):
            if isinstance(node, ast.Import):
                self.assertFalse(any(a.name.startswith("live_controller") for a in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith("live_controller"))

    def test_exactly_five_zones(self):
        values = literal_assignments(self.source)
        self.assertEqual(values.get("NUM_ZONES"), 5)

    def test_baseline_controls_preservation_gate_negative_control(self):
        """Prove our gate notices a removed old control, rather than vacuous pass."""
        node = self.source.method("MultiZoomScaleDialog", "_setup_ui")
        attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        removed = attrs - {"_frame_back_btn"}
        self.assertIn("_frame_back_btn", set(BASELINE_DIALOG_CONTROLS) - removed)


if __name__ == "__main__":
    unittest.main()
