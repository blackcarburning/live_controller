"""Behavioral coverage for narrowly approved persistence/preview/shutdown deltas.

Only named methods/helpers execute. Owners are SimpleNamespace fakes, never a
LiveController instance. All writes stay in temporary isolated fixture folders.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest

try:
    from .test_two_display_support import BASELINE, ExtractedSource, FakeProcess, IsolatedFiles, ast_dump, forbid
except ImportError:
    from test_two_display_support import BASELINE, ExtractedSource, FakeProcess, IsolatedFiles, ast_dump, forbid


class Value:
    def text(self): return "120"
    def value(self): return 1
    def isChecked(self): return False
    def currentText(self): return "20"


def session_owner(messages):
    owner = types.SimpleNamespace(_arduino_last_port="SYNTHETIC",tracks=[],undo_history=[],
        test_track_path=None,current_table_font_size=16,count_in_bg_color="red",
        count_in_font_size=100,track_play_bg_color="green",track_play_font_size=80,
        status_label=types.SimpleNamespace(setText=messages.append))
    for name in ("title_label","test_track_bpm_input","midi_offset_slider",
                 "high_precision_timing_radio","count_in_combo","streamdeck_font_spinbox",
                 "scrub_lock_checkbox","loop_checkbox","loop_bpm_spinbox",
                 "loop_start_bar_spinbox","loop_end_bar_spinbox"):
        setattr(owner,name,Value())
    return owner


class ActualPersistenceSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.source = ExtractedSource()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="two-display-test-persistence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = IsolatedFiles(self.root)
        path = types.SimpleNamespace(
            exists=lambda p:self.files.resolve(p).exists(),
            isfile=lambda p:self.files.resolve(p).is_file(),
            abspath=lambda p:str(self.files.resolve(p)),
            dirname=os.path.dirname,normcase=os.path.normcase)
        self.os = types.SimpleNamespace(path=path,replace=os.replace,unlink=os.unlink)
        constants = {
            "CONFIG_FILE":"two_display_config.json","SESSION_FILE":"two_display_session.json",
            "ZOOM_CONFIG_FILE":"two_display_zoom_config.json","BPM_STORE_FILE":"two_display_bpm_store.json",
            "TRACK_NAME_STORE_FILE":"two_display_track_names.json","ZOOM_FRAME_SNAPSHOT":"two_display_zoom_frame_snapshot.png"}
        injected = {key:str(self.root/value) for key,value in constants.items()}
        injected.update(os=self.os,open=self.files.open,tempfile=tempfile)
        ns = self.source.namespace({"_TWO_DISPLAY_LEGACY_FILES","_two_display_read_path"},injected=injected)
        self.ns = self.source.method_namespace("LiveController",["save_session"],injected=ns)
        self.messages = []
        self.owner = session_owner(self.messages)
        self.new = self.root/"two_display_session.json"
        self.legacy = self.root/"session.json"

    def save(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.ns["save_session"](self.owner)

    def test_legacy_fallback_read_only_no_eager_write_then_separate_new_save(self):
        legacy = {"unknown":{"preserve":[0,False,None]},"legacy-marker":123}
        self.files.seed("session.json",legacy)
        self.assertEqual(self.ns["_two_display_read_path"](str(self.new)),"session.json")
        self.assertFalse(self.new.exists(),"lookup must never install/migrate eagerly")
        self.assertTrue(self.save())
        data = json.loads(self.new.read_text())
        self.assertEqual(data["unknown"],legacy["unknown"])
        self.assertEqual(data["legacy-marker"],123)
        self.files.assert_unchanged(self,["session.json"])
        legacy_opens = [mode for name,mode in self.files.opens if name=="session.json"]
        self.assertEqual(legacy_opens,["r"])

    def test_existing_new_store_wins_and_preserves_unknown_extensions(self):
        self.files.seed("session.json",{"origin":"legacy","legacy-only":1})
        self.files.seed("two_display_session.json",{"origin":"new","unknown":{"zero":0}})
        self.assertTrue(self.save())
        data = json.loads(self.new.read_text())
        self.assertEqual(data["origin"],"new")
        self.assertEqual(data["unknown"],{"zero":0})
        self.assertNotIn("legacy-only",data)
        self.files.assert_unchanged(self,["session.json"])
        self.assertFalse(any(name=="session.json" for name,_ in self.files.opens))

    def test_malformed_legacy_or_new_store_never_overwritten(self):
        for name in ("session.json","two_display_session.json"):
            for malformed in ("{bad","[1,2]"):
                with self.subTest(name=name,malformed=malformed):
                    for p in self.root.iterdir():p.unlink()
                    p=self.root/name
                    p.write_text(malformed)
                    before=p.read_bytes()
                    self.assertFalse(self.save())
                    self.assertEqual(p.read_bytes(),before)
                    if name=="session.json":self.assertFalse(self.new.exists())
                    self.assertIn("preserved",self.messages[-1])
                    self.assertFalse(list(self.root.glob("*.tmp")))

    def test_atomic_save_failure_preserves_both_stores_and_removes_temp(self):
        self.files.seed("session.json",{"legacy":True})
        self.files.seed("two_display_session.json",{"new":{"zero":0}})
        self.os.replace=lambda *args:(_ for _ in ()).throw(PermissionError("synthetic save denied"))
        self.assertFalse(self.save())
        self.files.assert_unchanged(self,["session.json","two_display_session.json"])
        self.assertEqual({p.name for p in self.root.iterdir()},{"session.json","two_display_session.json"})
        self.assertIn("synthetic save denied",self.messages[-1])


class ShutdownAndPreviewSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.source = ExtractedSource()

    def test_actual_shutdown_cleans_new_inert_poller_and_all_old_callbacks(self):
        ns=self.source.method_namespace("LiveController",["closeEvent","_two_display_thread_running",
            "_two_display_running_threads"])
        for bad in (None,"session","config"):
            with self.subTest(bad=bad):
                events=[]
                def save(name):
                    events.append(name)
                    if name==bad:raise OSError("synthetic save failure")
                owner=types.SimpleNamespace(_app_is_closing=False,
                    setEnabled=lambda value:events.append(("host-enabled",value)),
                    _two_display_thread_running=ns["_two_display_thread_running"],
                    _startup_poll_timer=types.SimpleNamespace(stop=lambda:events.append("startup-stop")),
                    _shutdown_arduino_panel=lambda:events.append("arduino-stop"),
                    _startup_probes={"old":types.SimpleNamespace(cancel=lambda:events.append("probe-cancel"))},
                    save_session=lambda:save("session"),save_config=lambda:save("config"),
                    hotkey_listener=types.SimpleNamespace(stop=lambda:events.append("hotkey-stop"),
                        wait=lambda timeout:(events.append(("hotkey-wait",timeout)) or True),isRunning=lambda:False),
                    _position_poller=types.SimpleNamespace(stop=lambda:events.append("poller-stop"),
                        wait=lambda timeout:(events.append(("poller-wait",timeout)) or True),isRunning=lambda:False),
                    stop_all_activity=lambda:events.append("playback-stop"),
                    xr12_controller=types.SimpleNamespace(shutdown=lambda:events.append("xr12-stop")))
                owner._two_display_running_threads=types.MethodType(ns["_two_display_running_threads"],owner)
                with contextlib.redirect_stdout(io.StringIO()):
                    ns["closeEvent"](owner,types.SimpleNamespace(accept=lambda:events.append("accepted")))
                self.assertTrue(owner._app_is_closing)
                self.assertEqual(owner._startup_probes,{})
                self.assertEqual(events,[("host-enabled",False),"startup-stop","arduino-stop","probe-cancel","session","config",
                    "hotkey-stop",("hotkey-wait",1200),"poller-stop",("poller-wait",1200),
                    "playback-stop","xr12-stop","accepted"])

    def test_supervisor_cancel_helper_is_nonblocking_and_generation_specific(self):
        ns=self.source.method_namespace("LiveController",["_two_display_cancel_supervisor"])
        events=[]
        def supervisor(name):
            return types.SimpleNamespace(stop=lambda:events.append(name),join=forbid,wait=forbid,transport=forbid)
        old=types.SimpleNamespace(_display_coordinator=supervisor("old"))
        new=types.SimpleNamespace(_display_coordinator=supervisor("new"))
        ns["_two_display_cancel_supervisor"](old)
        ns["_two_display_cancel_supervisor"](None)
        self.assertEqual(events,["old"])
        self.assertIsNot(old._display_coordinator,new._display_coordinator)

    def test_legacy_preview_retains_controls_but_is_silent_and_unique(self):
        events=[]
        process=FakeProcess()
        ns=self.source.method_namespace("ZoomScaleDialog",["_launch_mpv","_send_ipc","_stop_mpv"],injected={
            "MPV_PATH":"OFFLINE-MPV","subprocess":types.SimpleNamespace(
                Popen=lambda command:(events.append(("launch",command)) or process)),
            "_make_unique_mpv_pipe_name":lambda prefix:"OFFLINE-UNIQUE-PIPE",
            "_send_mpv_ipc_command":lambda pipe,command:(events.append(("ipc",pipe,command)) or (True,"")),
            "_two_display_stop_process":lambda p:events.append(("stop",p))})
        owner=types.SimpleNamespace(_mpv_process=None,_ipc_path=None,
            _play_btn=types.SimpleNamespace(setEnabled=lambda x:events.append(("play",x))),
            _pause_btn=types.SimpleNamespace(setEnabled=lambda x:events.append(("pause",x))),
            _capture_btn=types.SimpleNamespace(setEnabled=lambda x:events.append(("capture",x))),
            _status=types.SimpleNamespace(setText=lambda text:None))
        owner._stop_mpv=types.MethodType(ns["_stop_mpv"],owner)
        ns["_launch_mpv"](owner,"SYNTHETIC.mp4")
        command=next(e[1] for e in events if e[0]=="launch")
        self.assertIn("--no-audio",command)
        self.assertIn("--mute=yes",command)
        self.assertIn("--input-ipc-server=OFFLINE-UNIQUE-PIPE",command)
        for control in ("play","pause","capture"):self.assertIn((control,True),events)
        ns["_send_ipc"](owner,'{"command":["frame-step"]}')
        self.assertIn(("ipc","OFFLINE-UNIQUE-PIPE",["frame-step"]),events)
        ns["_stop_mpv"](owner)
        self.assertIsNone(owner._mpv_process)
        self.assertIsNone(owner._ipc_path)

    def test_delayed_preview_never_adopts_another_output_or_new_pipe(self):
        events=[]
        ns=self.source.method_namespace("MultiZoomScaleDialog",["_send_preview_generation_command"],
            injected={"_send_mpv_ipc_command":lambda pipe,command,**kw:(events.append((pipe,command)) or (True,""))})
        owner=types.SimpleNamespace(_two_display_disposed=False,_editing_output="HDMI",
            _ext_preview_ipc_path="HDMI-NEW",_ext_preview_process=FakeProcess(),
            _external_previews={"DP":{"_ext_preview_ipc_path":"DP-CURRENT","_ext_preview_process":FakeProcess()}})
        send=ns["_send_preview_generation_command"]
        self.assertFalse(send(owner,"HDMI","HDMI-OLD",["seek",1,"absolute+exact"]))
        self.assertFalse(send(owner,"DP","HDMI-NEW",["seek",2,"absolute+exact"]))
        self.assertEqual(events,[])
        self.assertTrue(send(owner,"HDMI","HDMI-NEW",["seek",3,"absolute+exact"]))
        self.assertTrue(send(owner,"DP","DP-CURRENT",["seek",4,"absolute+exact"]))
        self.assertEqual(events,[("HDMI-NEW",["seek",3,"absolute+exact"]),("DP-CURRENT",["seek",4,"absolute+exact"])])
        owner._two_display_disposed=True
        self.assertFalse(send(owner,"HDMI","HDMI-NEW",["seek",5,"absolute+exact"]))
        self.assertEqual(len(events),2)

    def test_old_video_status_callbacks_cannot_replace_new_worker_ui(self):
        ns=self.source.method_namespace("LiveController",["_two_display_connect_video_signals"])
        events=[]
        def worker():
            return types.SimpleNamespace(source_fps=types.SimpleNamespace(connect=lambda cb:None),
                video_sync_status=types.SimpleNamespace(connect=lambda cb:None))
        callbacks={}
        old=worker()
        old.source_fps.connect=lambda cb:callbacks.__setitem__("fps",cb)
        old.video_sync_status.connect=lambda cb:callbacks.__setitem__("status",cb)
        current=worker()
        owner=types.SimpleNamespace(worker=old,calib_loop_worker=None,
            _two_display_fps_updated=lambda *args:events.append(("fps",args)),
            _two_display_sync_updated=lambda *args:events.append(("status",args)))
        ns["_two_display_connect_video_signals"](owner,old)
        callbacks["fps"](25.0,False)
        callbacks["status"]("HDMI current")
        self.assertEqual(len(events),2)
        owner.worker=current
        callbacks["fps"](30.0,True)
        callbacks["status"]("HDMI STALE")
        self.assertEqual(len(events),2)
        owner.calib_loop_worker=old
        callbacks["fps"](30000/1001,False)
        self.assertEqual(events[-1],("fps",(30000/1001,False)))

    def test_cancellable_poller_stop_before_run_issues_no_queries(self):
        events=[]
        ns=self.source.namespace({"PositionPoller"},injected={
            "_lc_query_mpv_property":lambda *args:events.append(args)})
        poller=ns["PositionPoller"]()
        poller.set_socket("OFFLINE-PIPE")
        poller.stop()
        poller.run()  # synchronous, event already cancelled: no real thread/wait
        self.assertEqual(events,[])



class DelayedQtWorker:
    """No real Qt thread; completion must be observed, never presumed by wait."""
    def __init__(self,name,events,running=True):
        self.name,self.events,self.running=name,events,running
        self.stops=0
        self.deleted=0
        self.waits=[]
        self.finished=types.SimpleNamespace(connect=lambda cb:None)
        self._display_coordinator=types.SimpleNamespace(stop=lambda:self.events.append((name,"video-cancel")))
    def isRunning(self):return self.running
    def stop(self):self.stops+=1;self.events.append((self.name,"stop-request"))
    def wait(self,timeout):
        self.waits.append(timeout)
        self.events.append((self.name,"wait",timeout))
        return not self.running
    def deleteLater(self):
        if self.running:raise AssertionError("Deleting a still-running owned QThread")
        self.deleted+=1
        self.events.append((self.name,"deleted"))


def require_cancellation_hook(source,baseline):
    # The restored legacy pre-activity hook only cancels old operations.
    # Execute that exact baseline body with inert cancel/LED interfaces,
    # never a replacement hook that could conceal native/start work.
    if ast_dump(source.method("LiveController","_arduino_before_activity")) != ast_dump(
            baseline.method("LiveController","_arduino_before_activity")):
        raise AssertionError("Unreviewed Arduino cancellation hook in shutdown fixture")


class BoundedShutdownOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=ExtractedSource()
        require_cancellation_hook(cls.source,ExtractedSource(BASELINE))

    def fixture(self,running_name):
        events=[]
        scheduled=[]
        class Timer:
            @staticmethod
            def singleShot(delay,callback):
                if not isinstance(delay,int) or delay<=0 or delay>1000:
                    raise AssertionError("Shutdown retry must use a bounded nonzero GUI timer")
                scheduled.append((delay,callback))
        names=["closeEvent","stop_all_activity","stop_calib_loop","_two_display_cancel_supervisor"]
        # b01 explicitly reviewed namespace-only lifecycle methods. No full
        # controller class or constructor executes. Completion uses fake timers.
        names.extend(("_two_display_thread_running","_two_display_running_threads",
            "_two_display_activity_blocked","_two_display_schedule_completion_check",
            "_two_display_defer_thread_completion","_two_display_poll_thread_completions",
            "on_playback_finished","on_playback_error","on_test_finished",
            "_on_calib_iteration_finished","_on_calib_error",
            "execute_playback","_start_calib_iteration","run_port_test",
            "_arduino_before_activity"))
        ns=self.source.method_namespace("LiveController",names,injected={"QTimer":Timer,
            "MidiSyncWorker":forbid,"MidiTestWorker":forbid})
        noop=lambda *a,**k:None
        owner=types.SimpleNamespace(_app_is_closing=False,_manual_stop_requested=False,
            worker=None,test_worker=None,calib_loop_worker=None,
            calib_loop_active=running_name=="calib_loop_worker",countdown_connection=None,
            _startup_poll_timer=types.SimpleNamespace(stop=lambda:events.append("startup-stop")),
            _shutdown_arduino_panel=lambda:events.append("arduino-stop"),_startup_probes={},
            save_session=lambda:events.append("session-save"),save_config=lambda:events.append("config-save"),
            status_label=types.SimpleNamespace(setText=lambda text:events.append(("status",text))),
            countdown_timer=types.SimpleNamespace(isActive=lambda:False),countdown_label=types.SimpleNamespace(hide=noop),
            calib_loop_restart_timer=types.SimpleNamespace(stop=lambda:events.append("calib-restart-stop")),
            calib_loop_ipc_socket="SYNTHETIC-CALIB-PIPE",
            calib_loop_button=types.SimpleNamespace(setText=noop,setStyleSheet=noop),
            calib_loop_duration_spinbox=types.SimpleNamespace(setEnabled=noop),
            active_flash_timer=types.SimpleNamespace(stop=noop),active_label=types.SimpleNamespace(hide=noop),
            stop_sync_show=lambda:events.append("sync-stop"),send_led_command=lambda x:events.append(("led",x)),
            _reset_scrub_controls=lambda:events.append("scrub-reset"),_open_audience_if_idle=noop,
            xr12_controller=types.SimpleNamespace(shutdown=lambda:events.append("xr12-stop")),
            setEnabled=lambda value:events.append(("host-enabled",value)),
            running_test_port=1,_playback_error_seen=False,currently_playing_row=None,
            tracks=[],current_ipc_socket="SYNTHETIC-MASTER",test_track_path="SYNTHETIC.mp4",
            test_file_label=types.SimpleNamespace(setStyleSheet=noop),
            clear_highlight=lambda:events.append("highlight-clear"),
            is_live_mode=False,set_test_controls_enabled=noop,
            play_test_button=types.SimpleNamespace(setEnabled=noop),
            test_port_buttons={1:types.SimpleNamespace(setText=noop,setStyleSheet=noop)},
            _arduino_pending_port="SYNTHETIC-PENDING",_arduino_operation_cancelled=False,
            _arduino_operation=types.SimpleNamespace(cancel=lambda:events.append("arduino-operation-cancel")),
            _stop_arduino_led_test=lambda *,restore:events.append(("arduino-led-stop",restore)),
            show_danger_message=forbid)
        for name in ("hotkey_listener","_position_poller"):
            setattr(owner,name,types.SimpleNamespace(stop=lambda n=name:events.append((n,"stop")),
                wait=lambda timeout,n=name:(events.append((n,"wait",timeout)) or True),isRunning=lambda:False))
        for name in names:
            if name in ("_two_display_cancel_supervisor","_two_display_thread_running"):setattr(owner,name,ns[name])
            elif name!="closeEvent":setattr(owner,name,types.MethodType(ns[name],owner))
        worker=DelayedQtWorker(running_name,events)
        setattr(owner,running_name,worker)
        def event():
            result=types.SimpleNamespace(accepted=False,ignored=False)
            result.accept=lambda:(setattr(result,"accepted",True),events.append("accepted"))
            result.ignore=lambda:(setattr(result,"ignored",True),events.append("ignored"))
            return result
        owner.close=lambda:ns["closeEvent"](owner,event())
        def pump():
            batch=scheduled[:]
            scheduled.clear()
            for delay,callback in batch:callback()
        return types.SimpleNamespace(owner=owner,worker=worker,events=events,scheduled=scheduled,
            ns=ns,event=event,pump=pump)

    def test_stop_timeout_retains_each_worker_until_actual_completion(self):
        for name in ("worker","test_worker","calib_loop_worker"):
            with self.subTest(worker=name):
                f=self.fixture(name)
                f.owner._app_is_closing=True
                f.owner.stop_all_activity()
                self.assertIs(getattr(f.owner,name),f.worker)
                self.assertTrue(f.worker.running)
                self.assertGreaterEqual(f.worker.stops,1)
                self.assertEqual(f.worker.deleted,0)
                self.assertIn(2500,f.worker.waits)
                self.assertTrue(all(timeout==2500 for timeout in f.worker.waits))
                # A repeated request must keep exactly the same running owner.
                f.owner.stop_all_activity()
                self.assertIs(getattr(f.owner,name),f.worker)
                self.assertEqual(f.worker.deleted,0)

    def test_close_ignores_owned_worker_timeout_then_completes_after_finish(self):
        for name in ("worker","test_worker","calib_loop_worker"):
            with self.subTest(worker=name):
                f=self.fixture(name)
                first=f.event()
                with contextlib.redirect_stdout(io.StringIO()):f.ns["closeEvent"](f.owner,first)
                self.assertTrue(first.ignored,"Timed-out QThread must defer GUI close, not destroy its owner")
                self.assertFalse(first.accepted)
                self.assertIs(getattr(f.owner,name),f.worker)
                self.assertEqual(f.worker.deleted,0)
                self.assertTrue(f.owner._app_is_closing)
                self.assertNotIn("accepted",f.events)
                # Complete without starting a QThread; then exercise a genuine
                # second close attempt. No asynchronous video joins occur.
                f.worker.running=False
                last=f.event()
                with contextlib.redirect_stdout(io.StringIO()):f.ns["closeEvent"](f.owner,last)
                self.assertTrue(last.accepted,"A finished owner must not trap the UI in deferred-close state")
                self.assertFalse(last.ignored)
                self.assertLessEqual(f.worker.deleted,1)
                self.assertEqual(f.events.count("session-save"),1,"Close retry must not repeat persistence")
                self.assertEqual(f.events.count("config-save"),1)
                self.assertEqual(f.events.count("arduino-stop"),1)
                self.assertEqual(f.events.count("xr12-stop"),1)

    def test_completion_timer_releases_each_exact_owner_and_finishes_close_once(self):
        for name in ("worker","test_worker","calib_loop_worker"):
            with self.subTest(worker=name):
                f=self.fixture(name)
                first=f.event()
                f.ns["closeEvent"](f.owner,first)
                self.assertTrue(first.ignored)
                self.assertEqual(len(f.scheduled),1)
                self.assertEqual(f.worker.deleted,0)
                # Repeated GUI close must not block in another bounded wait.
                old_waits=list(f.worker.waits)
                f.ns["closeEvent"](f.owner,f.event())
                self.assertEqual(f.worker.waits,old_waits)
                self.assertEqual(len(f.scheduled),1)
                f.worker.running=False
                f.pump()
                self.assertIsNone(getattr(f.owner,name))
                self.assertEqual(f.worker.deleted,1)
                self.assertEqual(f.events.count("accepted"),1)
                self.assertEqual(f.events.count("session-save"),1)
                self.assertEqual(f.events.count("arduino-stop"),1)
                self.assertFalse(f.owner._two_display_pending_completions)
                self.assertFalse(f.scheduled)

    def test_early_finished_and_old_generation_callbacks_never_delete_running_replacement(self):
        for name in ("worker","test_worker","calib_loop_worker"):
            with self.subTest(worker=name):
                f=self.fixture(name)
                finish={"worker":lambda:f.owner.on_playback_finished(owner=f.worker),
                    "test_worker":lambda:f.owner.on_test_finished(1,owner=f.worker),
                    "calib_loop_worker":lambda:f.owner._on_calib_iteration_finished(owner=f.worker)}[name]
                finish()
                self.assertIs(getattr(f.owner,name),f.worker)
                self.assertEqual(f.worker.deleted,0)
                self.assertTrue(f.scheduled)
                replacement=DelayedQtWorker("REPLACEMENT",f.events)
                setattr(f.owner,name,replacement)
                finish()
                f.pump()
                self.assertIs(getattr(f.owner,name),replacement)
                self.assertEqual(replacement.deleted,0)
                self.assertTrue(any(owner is f.worker for slot,owner in f.owner._two_display_running_threads()))
                f.worker.running=False
                f.pump()
                self.assertIs(getattr(f.owner,name),replacement)
                self.assertEqual(replacement.deleted,0)
                self.assertFalse(f.owner._two_display_pending_completions)

    def test_timed_out_owner_blocks_new_playback_calibration_and_port_test(self):
        for name in ("worker","test_worker","calib_loop_worker"):
            with self.subTest(worker=name):
                f=self.fixture(name)
                f.owner.stop_all_activity()
                f.owner.execute_playback({},120)
                f.owner.calib_loop_active=True
                f.owner._start_calib_iteration()
                # Same-port Stop remains available for a running test; other
                # activity must never reach the forbidden hardware seam.
                if name!="test_worker":f.owner.run_port_test(1)
                self.assertIs(getattr(f.owner,name),f.worker)
                self.assertEqual(f.worker.deleted,0)
                expected_cancellations=1 if name=="test_worker" else 2
                self.assertEqual(f.events.count("arduino-operation-cancel"),expected_cancellations)
                self.assertEqual(f.events.count(("arduino-led-stop",False)),expected_cancellations)
                self.assertTrue(f.owner._arduino_operation_cancelled)
                self.assertIsNone(f.owner._arduino_pending_port)

    def test_helper_qthread_timeout_also_defers_close(self):
        for name in ("hotkey_listener","_position_poller"):
            with self.subTest(helper=name):
                f=self.fixture("worker")
                f.worker.running=False
                helper=DelayedQtWorker(name,f.events)
                setattr(f.owner,name,helper)
                first=f.event()
                with contextlib.redirect_stdout(io.StringIO()):f.ns["closeEvent"](f.owner,first)
                self.assertTrue(first.ignored)
                self.assertFalse(first.accepted)
                self.assertIs(getattr(f.owner,name),helper)
                self.assertEqual(helper.deleted,0)
                self.assertIn(1200,helper.waits)
                helper.running=False
                last=f.event()
                with contextlib.redirect_stdout(io.StringIO()):f.ns["closeEvent"](f.owner,last)
                self.assertTrue(last.accepted)


if __name__=="__main__":unittest.main()
