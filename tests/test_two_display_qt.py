"""Windows-portable real-PyQt6 tests of AST-extracted editor classes only.

No real hardware constructors, native calls, controller or mpv process may run.
The fixture uses real widgets/signals/QTimer, an inert position poller, synthetic
pixmaps and a temporary file root. --require-qt in the standalone runner makes
missing PyQt a failure instead of a Linux-only explicit pending check.
"""
from __future__ import annotations

import ast
import builtins
from collections import deque
import contextlib
import functools
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import tempfile
import time
import types
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from .test_two_display_support import (
        BASELINE, ExtractedSource, Signal, forbid, literal_assignments,
    )
    from .test_two_display_invariants import BASELINE_DIALOG_CONTROLS
except ImportError:
    from test_two_display_support import BASELINE, ExtractedSource, Signal, forbid, literal_assignments
    from test_two_display_invariants import BASELINE_DIALOG_CONTROLS


class InertPositionPoller:
    def __init__(self, *args, **kwargs):
        self.position_updated = Signal()
        self.started = 0
        self.stopped = 0
        self.path = None

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def wait(self, *args):
        return True

    def set_socket_path(self, value):
        self.path = value

    def set_socket(self, value):
        self.path = value


def qt_environment(cls, prefix):
    """Real Qt only; cached-only signal import and process-local font setup."""
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets, QtTest
    except ImportError as exc:
        if os.environ.get("TWO_DISPLAY_REQUIRE_QT") == "1":
            raise AssertionError("PyQt6 unavailable; required real-widget qualification cannot run") from exc
        raise unittest.SkipTest("PyQt6 unavailable; Windows real-widget qualification pending") from exc
    cls.QtCore,cls.QtGui,cls.QtWidgets,cls.QtTest=QtCore,QtGui,QtWidgets,QtTest
    cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    cls.app.setStyle("Fusion")
    if not QtGui.QFontDatabase.families():
        font=Path("C:/Windows/Fonts/segoeui.ttf")
        if not font.is_file() or QtGui.QFontDatabase.addApplicationFont(str(font))<0:
            raise AssertionError("No process-local readable font available for genuine Qt screenshots")
    cls.app.setFont(QtGui.QFont("Segoe UI",9))
    cls.temp=tempfile.TemporaryDirectory(prefix="two-display-test-qt-"+prefix+"-")
    cls.addClassCleanup(cls.temp.cleanup)
    cls.root=Path(cls.temp.name)
    cls.artifacts=Path(os.environ.get("TWO_DISPLAY_TEST_ARTIFACTS",str(cls.root)))
    cls.artifacts.mkdir(parents=True,exist_ok=True)
    cls.traces=[]
    cls.qt_errors=[]
    cls.cached_imports=[]
    previous=sys.excepthook
    sys.excepthook=lambda typ,value,tb:cls.qt_errors.append("".join(traceback.format_exception(typ,value,tb)))
    cls.addClassCleanup(setattr,sys,"excepthook",previous)
    injected={}
    for module in (QtCore,QtGui,QtWidgets):
        for name in dir(module):
            if name.startswith("Q") or name in ("Qt","pyqtSignal","pyqtProperty"):
                injected[name]=getattr(module,name)
    guarded=dict(vars(builtins))
    for name in ("open","exec","eval","compile","input","breakpoint"):
        guarded[name]=forbid
    def cached_import(name,globals=None,locals=None,fromlist=(),level=0):
        if name!="functools" or level!=0 or sys.modules.get(name) is not functools:
            raise AssertionError("Unreviewed lazy import inside extracted Qt fixture: "+repr(name))
        if name not in cls.cached_imports:cls.cached_imports.append(name)
        return functools
    guarded["__import__"]=cached_import
    injected["__builtins__"]=guarded
    return injected


def label_geometry(case,label):
    """Check laid-out rich/plain wrapped text against its actual content area."""
    case.assertGreater(label.width(),0)
    case.assertGreater(label.height(),0)
    margin=label.margin()
    area=label.contentsRect().adjusted(margin,margin,-margin,-margin)
    case.assertGreater(area.width(),0)
    metrics=label.fontMetrics()
    case.assertGreater(metrics.height(),0)
    # Document uses Qt's real rich/plain-text interpretation, including br and
    # styled labels, rather than measuring HTML tags as displayed characters.
    document=case.QtGui.QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(label.font())
    if label.textFormat()==case.QtCore.Qt.TextFormat.PlainText:
        document.setPlainText(label.text())
    else:
        document.setHtml(label.text())
    document.setTextWidth(float(area.width()))
    needed=document.size().height()
    case.assertLessEqual(needed,area.height()+3,
        "Wrapped label clips text at actual allocated geometry: "+label.text())
    return {"width":label.width(),"height":label.height(),
            "content_width":area.width(),"content_height":area.height(),
            "font_height":metrics.height(),"needed_height":needed}


class RealQtEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()
        injected = qt_environment(cls,"editor")
        injected.update(
            PositionPoller=InertPositionPoller,
            DEFAULT_VIDEO_SCREEN_NUMBER=1,
            MPV_PATH="OFFLINE-MPV-FORBIDDEN",
            ZOOM_FRAME_SNAPSHOT=str(cls.root / "two_display_zoom_frame_snapshot.png"),
            tempfile=types.SimpleNamespace(mkdtemp=lambda **kw: tempfile.mkdtemp(dir=cls.root, **kw)),
            shutil=shutil, time=time,
            # No actual legacy frame is read; synthetic fixture snapshot only.
            _two_display_read_path=lambda path:path,
            os=types.SimpleNamespace(path=types.SimpleNamespace(
                join=os.path.join,basename=os.path.basename,
                isfile=lambda path:Path(path).is_file() if Path(path).resolve().is_relative_to(cls.root) else False)),
            _send_mpv_ipc_command=forbid,
            _lc_query_mpv_property=forbid,
            _lc_send_ipc_command=forbid,
            _two_display_screen_rows=lambda: [
                {"index": 0, "name": "OFFLINE operator", "primary": True},
                {"index": 1, "name": "OFFLINE HDMI", "primary": False},
                {"index": 2, "name": "OFFLINE DP", "primary": False},
            ],
        )
        names = {
            "NUM_ZONES", "_ZONE_INT_DEFAULTS", "_COMPOSITE_INT_DEFAULTS", "_ZONE_COLORS",
            "_default_zone", "_zoom_int", "_normalize_zone", "_migrate_zoom_config",
            "_build_vf_for_zones", "_mz_format_duration", "ZoomCropCanvas", "StretchCanvas",
            "MultiZoomScaleDialog",
        }
        names.update({
            "TWO_DISPLAY_OUTPUTS", "TWO_DISPLAY_FALLBACK_FPS",
            "_TWO_DISPLAY_ZONE_OUTPUT_KEYS", "_TWO_DISPLAY_COMPOSITE_KEYS",
            "_two_display_default_output", "_migrate_two_display_config",
            "_two_display_output_config", "_two_display_has_routes",
            "_two_display_black_vf", "_two_display_build_vf",
            "_two_display_resolve_outputs", "_two_display_combo_index",
            "_two_display_fill_display_combo",
        })
        cls.ns = cls.source.namespace(names, injected=injected)
        cls.dialog_type = cls.ns["MultiZoomScaleDialog"]
        cls.guard = contextlib.ExitStack()
        # Any unexpected player/native path in dialog construction is fatal.
        for method in ("_launch_mpv", "_open_external_preview", "_select_video", "_capture_frame"):
            cls.guard.enter_context(mock.patch.object(cls.dialog_type, method, forbid))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "guard"):
            cls.guard.close()
        if hasattr(cls, "traces"):
            (cls.artifacts / "qt_editor_traces.json").write_text(json.dumps({"traces":cls.traces,
                "cached_imports":cls.cached_imports,"qt_errors":cls.qt_errors}, indent=2), encoding="utf-8")
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def pump(self):
        self.app.processEvents()
        self.assertEqual(self.qt_errors,[],"Qt callback raised; screenshot qualification is invalid")

    def setUp(self):
        self.qt_errors.clear()
        self.dialog = self.dialog_type({})
        self.addCleanup(self.close_dialog)
        self.dialog.resize(1400, 960)
        self.dialog.show()  # offscreen Qt only; never native fullscreen output
        self.pump()

    def close_dialog(self):
        if self.dialog is not None:
            self.dialog._update_timer.stop()
            self.dialog.close()
            self.pump()
            self.dialog.deleteLater()
            self.pump()
            self.dialog = None

    def trace(self, action, **details):
        self.traces.append({"action": action, **details})

    def test_all_existing_controls_and_five_zone_canvases_present(self):
        for name in BASELINE_DIALOG_CONTROLS:
            self.assertTrue(hasattr(self.dialog, name), name)
        for name in ("_zone_enable_cbs", "_zone_x_sbs", "_zone_y_sbs", "_zone_w_sbs",
                     "_zone_h_sbs", "_zone_sw_sbs", "_zone_sh_sbs", "_zone_border_sbs",
                     "_zone_offset_y_sbs", "_zone_crop_canvases", "_zone_stretch_canvases"):
            self.assertEqual(len(getattr(self.dialog, name)), 5, name)
        self.assertGreaterEqual(self.dialog._tabs.count(), 7)
        self.assertEqual(self.dialog._pos_poller.started, 1)
        self.trace("controls", zones=5, tab_count=self.dialog._tabs.count(),
                   retained=len(BASELINE_DIALOG_CONTROLS))

    def test_global_zone_enable_and_zero_values_collect_from_real_widgets(self):
        d = self.dialog
        for i in range(5):
            d._zone_enable_cbs[i].setChecked(True)
            d._zone_x_sbs[i].setValue(i*120)
            d._zone_y_sbs[i].setValue(0)
            d._zone_w_sbs[i].setValue(120)
            d._zone_h_sbs[i].setValue(80)
            d._zone_border_sbs[i].setValue(0)
            d._zone_offset_y_sbs[i].setValue(0)
        self.pump()
        cfg = d._collect_config()
        self.assertEqual(len(cfg["zones"]), 5)
        self.assertTrue(all(z["enabled"] for z in cfg["zones"]))
        self.assertEqual([z["crop_x"] for z in cfg["zones"]], [0, 120, 240, 360, 480])
        self.assertTrue(all(z["border_px"] == 0 and z["offset_y"] == 0 for z in cfg["zones"]))
        d._zone_enable_cbs[4].setChecked(False)
        self.assertFalse(d._collect_config()["zones"][4]["enabled"])
        self.trace("global-zone-enable", enabled=[z["enabled"] for z in d._collect_config()["zones"]])

    def test_crop_stretch_composite_and_canvas_controls_roundtrip(self):
        d = self.dialog
        d._zone_sw_sbs[0].setValue(333)
        d._zone_sh_sbs[0].setValue(222)
        d._zone_border_sbs[0].setValue(14)
        d._zone_offset_y_sbs[0].setValue(-12)
        d._zone_mode_stretch_rbs[0].setChecked(True)
        d._stitch_v.setChecked(True)
        d._comp_x_sb.setValue(0)
        d._comp_y_sb.setValue(0)
        d._comp_w_sb.setValue(300)
        d._comp_h_sb.setValue(200)
        d._comp_sw_sb.setValue(900)
        d._comp_sh_sb.setValue(600)
        d._out_w_sb.setValue(1280)
        d._out_h_sb.setValue(720)
        d._out_sim_playback_cb.setChecked(True)
        cfg = d._collect_config()
        d._cfg = json.loads(json.dumps(cfg))
        d._load_config_to_ui()
        self.assertEqual(d._collect_config(), cfg)
        self.assertEqual(cfg["zones"][0]["mode"], "stretch")
        self.assertEqual(cfg["stack_direction"], "vertical")
        self.trace("real-widget-roundtrip", success=True)

    def test_hdmi_dp_switch_retains_independent_output_settings_shared_crops(self):
        d = self.dialog
        self.assertEqual([d._output_combo.itemText(i) for i in range(d._output_combo.count())], ["HDMI", "DP"])
        self.assertEqual(len(d._zone_route_combos), 5)
        for i in range(5):
            d._zone_enable_cbs[i].setChecked(True)
            combo = d._zone_route_combos[i]
            self.assertEqual(combo.currentData(), "hdmi")
            combo.setCurrentIndex(combo.findData("both" if i < 2 else "hdmi"))
            d._zone_x_sbs[i].setValue(i*100)
            d._zone_w_sbs[i].setValue(100)
            d._zone_h_sbs[i].setValue(60)
        d._zone_sw_sbs[0].setValue(333)
        d._zone_sh_sbs[0].setValue(222)
        d._zone_border_sbs[0].setValue(0)
        d._zone_offset_y_sbs[0].setValue(-9)
        d._comp_sw_sb.setValue(800)
        d._out_w_sb.setValue(1280)
        d._stitch_v.setChecked(True)
        d._output_offset_frames_sb.setValue(3)
        d._output_drift_frames_sb.setValue(2)
        self.assertIsInstance(d._output_offset_frames_sb, self.QtWidgets.QSpinBox)
        self.assertIsInstance(d._output_drift_frames_sb, self.QtWidgets.QSpinBox)
        self.assertIn("frames", d._output_offset_frames_sb.suffix())
        d._output_combo.setCurrentText("DP")
        self.pump()
        self.assertEqual(d._editing_output, "DP")
        self.assertEqual([x.value() for x in d._zone_x_sbs], [0,100,200,300,400])
        d._zone_sw_sbs[0].setValue(444)
        d._zone_sh_sbs[0].setValue(111)
        d._zone_border_sbs[0].setValue(15)
        d._zone_offset_y_sbs[0].setValue(7)
        d._comp_sw_sb.setValue(900)
        d._out_w_sb.setValue(1920)
        d._stitch_h.setChecked(True)
        d._output_offset_frames_sb.setValue(-4)
        d._output_drift_frames_sb.setValue(5)
        d._zone_x_sbs[4].setValue(451)
        d._zone_enable_cbs[4].setChecked(False)
        dp = d._collect_config()["outputs"]["DP"]
        d._output_combo.setCurrentText("HDMI")
        self.pump()
        self.assertEqual(d._zone_sw_sbs[0].value(), 333)
        self.assertEqual(d._zone_sh_sbs[0].value(), 222)
        self.assertEqual(d._zone_border_sbs[0].value(), 0)
        self.assertEqual(d._zone_offset_y_sbs[0].value(), -9)
        self.assertEqual(d._out_w_sb.value(), 1280)
        self.assertEqual(d._comp_sw_sb.value(), 800)
        self.assertTrue(d._stitch_v.isChecked())
        self.assertEqual(d._output_offset_frames_sb.value(), 3)
        self.assertEqual(d._zone_x_sbs[4].value(), 451)
        self.assertFalse(d._zone_enable_cbs[4].isChecked())
        self.assertEqual(d._collect_config()["outputs"]["DP"], dp)
        d._output_combo.setCurrentText("DP")
        self.pump()
        self.assertEqual(d._zone_sw_sbs[0].value(), 444)
        self.assertEqual(d._zone_border_sbs[0].value(), 15)
        self.assertEqual(d._output_offset_frames_sb.value(), -4)
        self.assertEqual(d._output_drift_frames_sb.value(), 5)
        self.trace("dual-output-widget-independence", shared_crop=True,
                   global_enable=True, frame_widgets_integer=True)

    def test_separate_external_preview_states_never_launch(self):
        d = self.dialog
        self.assertEqual(set(d._output_still_canvases), {"HDMI", "DP"})
        d._ext_preview_start_pos = 12.5
        d._ext_preview_paused = False
        d._output_combo.setCurrentText("DP")
        self.pump()
        self.assertEqual(d._ext_preview_start_pos, 0.0)
        self.assertTrue(d._ext_preview_paused)
        d._ext_preview_start_pos = 38.0
        d._ext_preview_paused = True
        d._output_combo.setCurrentText("HDMI")
        self.pump()
        self.assertEqual(d._ext_preview_start_pos, 12.5)
        self.assertFalse(d._ext_preview_paused)
        d._output_combo.setCurrentText("DP")
        self.pump()
        self.assertEqual(d._ext_preview_start_pos, 38.0)
        self.assertTrue(d._ext_preview_paused)
        self.assertIsNone(d._ext_preview_process)
        self.assertFalse(d._ext_preview_open)
        self.trace("independent-preview-states", outputs=["HDMI", "DP"], process_launches=0)

    def test_all_exit_paths_stop_inert_poller_once(self):
        d = self.dialog
        d._cancel()
        self.pump()
        self.assertTrue(d._two_display_disposed)
        self.assertEqual(d._pos_poller.stopped, 1)
        d.reject()
        self.pump()
        self.assertEqual(d._pos_poller.stopped, 1)
        self.trace("idempotent-reject-cleanup", poller_stops=1)

    def test_transport_controls_emit_only_inert_ipc_commands(self):
        d = self.dialog
        commands = []
        d._send_ipc = lambda command: commands.append(command)
        d._apply_external_preview_playback_state = lambda: None
        d._play_from_beginning()
        d._frame_forward()
        self.assertTrue(d._ext_preview_paused)
        d._frame_back()
        d._ipc_path = "OFFLINE-PIPE"
        d._mz_dur = 120.0
        d._mz_scrub_slider.setValue(250)
        d._on_mz_scrub_moved(250)
        d._on_mz_scrub_released()
        self.assertIn(["seek", 0, "absolute"], commands)
        self.assertIn(["frame-step"], commands)
        self.assertIn(["frame-back-step"], commands)
        self.assertIn(["seek", 30.0, "absolute+exact"], commands)
        self.trace("transport-inert", commands=commands)

    def test_populated_five_zones_both_outputs_1366_and_1920_geometry(self):
        d=self.dialog
        frame=self.QtGui.QPixmap(1920,1080)
        frame.fill(self.QtGui.QColor("#334455"))
        painter=self.QtGui.QPainter(frame)
        colors=("#e74c3c","#3498db","#2ecc71","#f1c40f","#9b59b6")
        for i,color in enumerate(colors):
            painter.fillRect(i*384,0,384,1080,self.QtGui.QColor(color))
        painter.end()
        path=self.root/"synthetic-five-zone-wide.png"
        self.assertTrue(frame.save(str(path)))
        d._load_frame_from_path(str(path))
        d._video_label.setText("SYNTHETIC_LONG_MEDIA_NAME_five_shared_crops_HDMI_DP_30000_1001fps.mp4")
        for i in range(5):
            d._zone_enable_cbs[i].setChecked(True)
            d._zone_route_combos[i].setCurrentIndex(d._zone_route_combos[i].findData("both"))
            d._zone_x_sbs[i].setValue(i*384)
            d._zone_y_sbs[i].setValue(0)
            d._zone_w_sbs[i].setValue(384)
            d._zone_h_sbs[i].setValue(400)
        captures=[]
        for width,height in ((1366,768),(1920,1080)):
            d.resize(width,height)
            self.pump()
            self.assertEqual((d.width(),d.height()),(width,height),
                "Editor minimum geometry exceeds requested operator display")
            for output in ("HDMI","DP"):
                d._output_combo.setCurrentText(output)
                self.pump()
                d._output_offset_frames_sb.setValue(3 if output=="HDMI" else -4)
                d._output_drift_frames_sb.setValue(2 if output=="HDMI" else 5)
                for zone in range(5):
                    d._tabs.setCurrentIndex(zone)
                    d._zone_sw_sbs[zone].setValue(360 if output=="HDMI" else 320)
                    d._zone_sh_sbs[zone].setValue(300 if output=="HDMI" else 240)
                    for mode,radio in (("crop",d._zone_mode_crop_rbs[zone]),
                                       ("stretch",d._zone_mode_stretch_rbs[zone])):
                        radio.setChecked(True)
                        self.pump()
                        name="editor-%dx%d-%s-zone%d-%s.png"%(width,height,output.lower(),zone+1,mode)
                        self.assertTrue(d.grab().save(str(self.artifacts/name)))
                        captures.append(name)
                        canvas=d._zone_crop_canvases[zone] if mode=="crop" else d._zone_stretch_canvases[zone]
                        self.assertTrue(canvas.isVisible())
                        self.assertGreater(canvas.width(),0)
                        self.assertGreater(canvas.height(),0)
                for index in range(5,d._tabs.count()):
                    d._tabs.setCurrentIndex(index)
                    self.pump()
                    name="editor-%dx%d-%s-composite%d.png"%(width,height,output.lower(),index)
                    self.assertTrue(d.grab().save(str(self.artifacts/name)))
                    captures.append(name)
                d._refresh_final_preview()
                d._refresh_output_stills()
                self.pump()
                for target in ("HDMI","DP"):
                    preview=d._output_still_canvases[target].pixmap()
                    self.assertIsNotNone(preview)
                    self.assertFalse(preview.isNull())
                    info=d._output_still_info[target]
                    self.assertIn("1 → 2 → 3 → 4 → 5",info.text())
                    self.assertTrue(info.wordWrap())
                    self.trace("still-label-font-bounds",output=target,geometry=[width,height],
                        **label_geometry(self,info))
                d._tabs.setCurrentIndex(0)
                self.pump()
                self.assertTrue(d._output_offset_frames_sb.isVisible())
                self.assertTrue(d._output_drift_frames_sb.isVisible())
        self.trace("populated-both-output-geometry",zones=5,outputs=["HDMI","DP"],
            geometries=[[1366,768],[1920,1080]],screenshots=captures,processes=0)

    def test_synthetic_frame_render_all_tabs_no_player(self):
        d = self.dialog
        frame = self.QtGui.QPixmap(960, 540)
        frame.fill(self.QtGui.QColor("#224466"))
        path = self.root / "synthetic-frame.png"
        self.assertTrue(frame.save(str(path)))
        d._load_frame_from_path(str(path))
        for i in range(5):
            d._zone_enable_cbs[i].setChecked(True)
            d._zone_x_sbs[i].setValue(i*160)
            d._zone_y_sbs[i].setValue(0)
            d._zone_w_sbs[i].setValue(160)
            d._zone_h_sbs[i].setValue(100)
        self.pump()
        for index in range(d._tabs.count()):
            d._tabs.setCurrentIndex(index)
            self.pump()
            self.assertTrue(d.grab().save(str(self.artifacts / ("editor-tab-%02d.png" % index))))
        d._refresh_final_preview()
        preview = d._final_canvas.pixmap()
        self.assertIsNotNone(preview)
        self.assertFalse(preview.isNull())
        d._refresh_output_stills()
        hdmi = d._output_still_canvases["HDMI"].pixmap()
        self.assertIsNotNone(hdmi)
        self.assertFalse(hdmi.isNull())
        self.assertIn("no assigned", d._output_still_canvases["DP"].text())
        for combo in d._zone_route_combos:
            combo.setCurrentIndex(combo.findData("both"))
        d._refresh_output_stills()
        for output in ("HDMI", "DP"):
            preview = d._output_still_canvases[output].pixmap()
            self.assertIsNotNone(preview)
            self.assertFalse(preview.isNull())
            self.assertTrue(preview.save(str(self.artifacts / (output.lower() + "-still.png"))))
        self.trace("synthetic-render", zones=5, tabs=d._tabs.count(),
                   screenshot_count=d._tabs.count()+2, processes=0, outputs=["HDMI", "DP"])



class RealQtMainControlsTests(unittest.TestCase):
    """A QWidget SafeHost, NOT a LiveController object or constructor.

    Only setup_ui and named pure display/status handlers execute. Every other
    controller callback is an explicit recorder, including all saves/activity.
    This is a bounded additive-controls smoke, not whole-app qualification.
    """
    @classmethod
    def setUpClass(cls):
        cls.source=ExtractedSource()
        injected=qt_environment(cls,"main")
        cls.rows=[
            {"index":0,"name":"SYNTHETIC operator primary","primary":True},
            {"index":1,"name":"SYNTHETIC HDMI extended","primary":False},
            {"index":2,"name":"SYNTHETIC DP extended","primary":False},
        ]
        values=literal_assignments(cls.source)
        injected.update({name:value for name,value in values.items()
                         if name.startswith("DEFAULT_") or name in ("DARK_STYLESHEET","TRACK_OVERHEAD_SECONDS","XR12_NUM_CHANNELS")})
        # Pure path formatting only. No app data, native API, process, hardware,
        # network implementation or general runtime importer enters the host.
        injected.update(os=types.SimpleNamespace(path=types.SimpleNamespace(
            basename=os.path.basename,splitext=os.path.splitext)),
            _two_display_screen_rows=lambda:[dict(row) for row in cls.rows],
            _two_display_black_vf=forbid,MPV_PATH="OFFLINE-MPV-FORBIDDEN")
        ns=cls.source.dual_helpers({"DraggableTableWidget","Switch",
            "_two_display_combo_index","_two_display_fill_display_combo"},injected=injected)
        selected=("setup_ui","_two_display_profile_changed","_two_display_refresh_profiles",
            "check_display_setting","_update_zoom_status_label",
            "_two_display_fps_updated","_two_display_sync_updated")
        ns=cls.source.method_namespace("LiveController",selected,injected=ns)
        class SafeHost(cls.QtWidgets.QWidget):
            def __init__(self):
                super().__init__()
                self.calls=[]
        for name in selected:setattr(SafeHost,name,ns[name])
        methods={node.name for node in cls.source.node("LiveController").body if isinstance(node,ast.FunctionDef)}
        refs={node.attr for node in ast.walk(cls.source.method("LiveController","setup_ui"))
              if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name)
              and node.value.id=="self" and node.attr in methods}
        # Status handlers call these two inert persistence callbacks explicitly.
        refs.update(("save_zoom_config","setting_changed"))
        def recorder(name):
            def callback(self,*args):self.calls.append((name,args))
            return callback
        for name in refs-set(selected)-{"close"}:setattr(SafeHost,name,recorder(name))
        cls.host_type=SafeHost
        cls.ns=ns
        baseline=ExtractedSource(BASELINE)
        cls.old_widget_attributes={}
        ui=baseline.method("LiveController","setup_ui")
        for node in ast.walk(ui):
            if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call):
                function=node.value.func
                if isinstance(function,ast.Name) and function.id.startswith("Q"):
                    for target in node.targets:
                        if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=="self":
                            cls.old_widget_attributes[target.attr]=function.id

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,"traces"):
            (cls.artifacts/"qt_main_traces.json").write_text(json.dumps({
                "traces":cls.traces,"cached_imports":cls.cached_imports,
                "qt_errors":cls.qt_errors,"safe_host":True,
                "livecontroller_constructed":False},indent=2),encoding="utf-8")

    def pump(self):
        self.app.processEvents()
        self.assertEqual(self.qt_errors,[],"Exception in extracted main UI callback")

    def setUp(self):
        self.qt_errors.clear()
        self.host=None
        self.addCleanup(self.close_host)
        self.host=self.make_host()

    def make_host(self,zoom=None):
        host=self.host_type()
        host.setWindowTitle("OFFLINE synthetic Live Controller Two Display controls")
        host.config={"display":1,"preload":4,"apply_zoom":True,
            "xr12_audience_fade_duration_sec":2.5,"xr12_audience_open_value":96,
            "xr12_audience_closed_value":3}
        host.zoom_config=self.ns["_migrate_two_display_config"](zoom or {})
        host._applying_config=False
        host.xr12_connected=False
        host.xr12_controller=None
        host.worker=host.test_worker=host.calib_loop_worker=None
        host.currently_playing_row=None
        host.test_track_path=None
        host.is_live_mode=False
        host.calib_loop_active=False
        host.undo_history=deque()
        host.test_port_enabled_cbs={}
        host.test_port_start_cbs={}
        host.test_port_bpm_inputs={}
        host.test_port_buttons={}
        for attribute,constant in (
                ("current_table_font_size","DEFAULT_TABLE_FONT_SIZE"),
                ("streamdeck_font_size","DEFAULT_STREAMDECK_FONT_SIZE"),
                ("count_in_bg_color","DEFAULT_COUNT_IN_BG_COLOR"),
                ("count_in_font_size","DEFAULT_COUNT_IN_FONT_SIZE"),
                ("track_play_bg_color","DEFAULT_TRACK_PLAY_BG_COLOR"),
                ("track_play_font_size","DEFAULT_TRACK_PLAY_FONT_SIZE")):
            setattr(host,attribute,self.ns[constant])
        host.tracks=[]
        host.setStyleSheet(self.ns["DARK_STYLESHEET"])
        host.setup_ui()
        host.apply_zoom_checkbox.setChecked(True)
        # Populate real table items with synthetic data; no original media path,
        # constructor, populate callback or persistent store is touched.
        host.table.setRowCount(5)
        for row in range(5):
            host.table.setItem(row,0,self.QtWidgets.QTableWidgetItem(chr(65+row)))
            host.table.setItem(row,1,self.QtWidgets.QTableWidgetItem(
                "Synthetic long setlist track %d — shared source crop, HDMI + DP"%(row+1)))
            host.table.setItem(row,3,self.QtWidgets.QTableWidgetItem(str(120+row)))
        host.resize(1366,768)
        host.show()
        self.pump()
        return host

    def close_host(self):
        if self.host is not None:
            self.host.hide()
            self.host.deleteLater()
            self.pump()
            self.host=None

    def test_all_original_main_widgets_and_additive_profiles_present(self):
        h=self.host
        for attribute,kind in self.old_widget_attributes.items():
            with self.subTest(attribute=attribute):
                self.assertTrue(hasattr(h,attribute),"Original main control removed: "+attribute)
                expected=getattr(self.QtWidgets,kind,None) or getattr(self.QtCore,kind,None)
                if expected is not None:self.assertIsInstance(getattr(h,attribute),expected)
        for name in ("display_combo","dp_display_combo"):
            self.assertIsInstance(getattr(h,name),self.QtWidgets.QComboBox)
        self.assertEqual(h.display_combo.currentData(),1)
        self.assertEqual(h.dp_display_combo.currentData(),2)
        self.assertTrue(h.video_fps_label.wordWrap())
        self.assertTrue(h.video_sync_label.wordWrap())
        self.assertIn("Source FPS",h.video_fps_label.text())
        self.traces.append({"action":"main-retained-controls","old_controls":len(self.old_widget_attributes),
            "new_controls":["dp_display_combo","video_fps_label","video_sync_label"],
            "synthetic_rows":5,"hardware_callbacks":0})

    def test_real_profile_handlers_unavailable_duplicate_and_fractional_fps(self):
        h=self.host
        h.calls.clear()
        h.dp_display_combo.setCurrentIndex(h.dp_display_combo.findData(1))
        self.pump()
        self.assertEqual(h.zoom_config["outputs"]["DP"]["display_index"],1)
        self.assertIn("duplicate",h.video_sync_label.text().lower())
        self.assertTrue(any(name=="save_zoom_config" for name,args in h.calls))
        h.dp_display_combo.setCurrentIndex(h.dp_display_combo.findData(2))
        self.pump()
        self.assertNotIn("duplicate",h.video_sync_label.text().lower())
        h.zoom_config["outputs"]["DP"]["display_index"]=99
        h.zoom_config["outputs"]["DP"]["screen_name"]="SYNTHETIC missing saved monitor"
        h._two_display_refresh_profiles()
        self.pump()
        self.assertEqual(h.dp_display_combo.currentData(),99)
        self.assertIn("unavailable",h.dp_display_combo.currentText().lower())
        self.assertIn("unavailable",h.video_sync_label.text().lower())
        self.assertEqual(h.display_combo.currentData(),1)
        h._two_display_fps_updated(30000/1001,False)
        self.assertIn("29.970",h.video_fps_label.text())
        self.assertIn("integer frames",h.video_fps_label.text())
        h._two_display_fps_updated(25.0,True)
        self.assertIn("fallback",h.video_fps_label.text())
        for i,zone in enumerate(h.zoom_config["zones"]):
            zone["enabled"]=True
            zone["route"]="both" if i%2==0 else "hdmi"
        h._update_zoom_status_label()
        self.assertIn("HDMI: Z1→2→3→4→5",h.zoom_status_label.text())
        self.assertIn("DP: Z1→3→5",h.zoom_status_label.text())
        self.traces.append({"action":"main-profile-handler-states","duplicate_disabled":True,
            "saved_unavailable_preserved":99,"fractional_fps":30000/1001,"fallback_explicit":True})

    def test_main_populated_controls_geometry_and_scroll_screenshots(self):
        h=self.host
        captures=[]
        for width,height in ((1366,768),(1920,1080)):
            h.resize(width,height)
            self.pump()
            self.assertEqual((h.width(),h.height()),(width,height),
                "Main controls minimum geometry exceeds target operator display")
            name="main-%dx%d.png"%(width,height)
            self.assertTrue(h.grab().save(str(self.artifacts/name)))
            captures.append(name)
            scrolls=h.findChildren(self.QtWidgets.QScrollArea)
            self.assertEqual(len(scrolls),1)
            area=scrolls[0]
            for label,target in (("hdmi-dp-profiles",h.dp_display_combo),
                                 ("source-fps-status",h.video_fps_label),
                                 ("zoom-routing-status",h.zoom_status_label),
                                 ("scrub-loop-controls",h.loop_bpm_spinbox),
                                 ("midi-tests",h.test_port_buttons[1])):
                area.ensureWidgetVisible(target,12,12)
                self.pump()
                point=target.mapTo(area.viewport(),self.QtCore.QPoint(0,0))
                rect=self.QtCore.QRect(point,target.size())
                self.assertTrue(area.viewport().rect().intersects(rect),
                    "Required main control unreachable by scrolling: "+label)
                self.assertGreater(target.width(),0)
                self.assertGreater(target.height(),0)
                name="main-%dx%d-%s.png"%(width,height,label)
                self.assertTrue(h.grab().save(str(self.artifacts/name)))
                captures.append(name)
            # Font-metric labels must wrap instead of making the whole window
            # wider than either target; raw long monitor names may elide in combo.
            for label in (h.video_fps_label,h.video_sync_label,h.zoom_status_label):
                self.assertTrue(label.wordWrap())
                self.assertLessEqual(label.width(),width)
                self.traces.append({"action":"main-label-font-bounds",
                    "geometry":[width,height],**label_geometry(self,label)})
        self.traces.append({"action":"main-geometry","geometries":[[1366,768],[1920,1080]],
            "screenshots":captures,"controller_constructor":False,"synthetic_only":True})


if __name__ == "__main__":
    unittest.main()
