"""Worker lifecycle / frame-unit checks from explicit extracted AST seams.

The baseline-compatible worker tests use only in-memory MIDI/process/IPC fakes.
No native process/thread/hardware constructors are allowed in the namespace.
"""
import ast
import ctypes
import ctypes.wintypes
import json
import os
import threading
import types
import unittest
from unittest import mock

try:
    from .test_two_display_support import (
        ExtractedSource, FakeClock, FakeMidiOut, FakeProcess, InertThread,
        SignalDescriptor, forbid,
    )
except ImportError:
    from test_two_display_support import (
        ExtractedSource, FakeClock, FakeMidiOut, FakeProcess, InertThread,
        SignalDescriptor, forbid,
    )


class WorkerOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()

    def test_only_one_midi_worker_construction_per_playback(self):
        for method in ("execute_playback",):
            node = self.source.method("LiveController", method)
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == "MidiSyncWorker"]
            self.assertEqual(len(calls), 1, method)

    def test_midi_port_ownership_stays_in_one_primary_worker(self):
        node = self.source.node("MidiSyncWorker")
        midi_calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute) and n.func.attr == "MidiOut"]
        self.assertEqual(len(midi_calls), 1)
        for name, other in self.source.defs.items():
            if isinstance(other, ast.ClassDef) and any(k in name.lower() for k in ("follower", "secondary")):
                for call in ast.walk(other):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                        self.assertNotIn(call.func.attr, ("MidiOut", "open_port", "send_message"), name)

    def worker_fixture(self, process_factory):
        clock = FakeClock(value=1000, step=0.001)
        coordinator_events = []
        class Coordinator:
            def __init__(self, *args, **kwargs):
                self.master_started = False
                self.cancel = threading.Event()
                coordinator_events.append(("create", kwargs))
            def start(self): coordinator_events.append(("start",))
            def attach_master(self, *args): coordinator_events.append(("attach",))
            def request_start(self):
                self.master_started = True
                coordinator_events.append(("request-start",))
            def stop(self):
                self.cancel.set()
                coordinator_events.append(("stop",))
            def join(self, timeout=None): coordinator_events.append(("join", timeout))
            def is_alive(self): return False
        injected = {
            "time": clock, "TwoDisplayCoordinator": Coordinator,
            "MPV_PATH": "OFFLINE-MPV", "MPV_LAUNCH_HEAD_START_SECONDS": 2,
            "START_BYTE": 0xFA, "STOP_BYTE": 0xFC, "CLOCK_BYTE": 0xF8, "SPP_BYTE": 0xF2,
            "_make_unique_mpv_pipe_name": lambda *args: "OFFLINE-MASTER",
            "winmm": types.SimpleNamespace(timeBeginPeriod=forbid, timeEndPeriod=forbid),
            "subprocess": types.SimpleNamespace(Popen=process_factory, TimeoutExpired=TimeoutError),
        }
        ns = self.source.dual_helpers({"MidiSyncWorker", "_two_display_stop_process"}, injected=injected)
        cfg = ns["_migrate_two_display_config"]({})
        cfg["display_available"] = {"HDMI": True, "DP": True}
        cfg["display_warnings"] = []
        worker = ns["MidiSyncWorker"]("SYNTHETIC.mp4", 120, 1, 0, 0,
                                     True, False, "standard", require_midi=False, zoom_config=cfg)
        midi = FakeMidiOut()
        worker.midi_outputs = {1: midi}
        return worker, midi, coordinator_events

    def test_primary_launch_failure_closes_midi_without_waiting_for_video(self):
        def fail(*args, **kwargs):
            raise OSError("SYNTHETIC primary launch failure")
        worker, midi, events = self.worker_fixture(fail)
        worker._run_logic(is_high_precision=False)
        self.assertTrue(midi.closed)
        self.assertEqual(midi.messages.count([0xFC]), 1)
        self.assertEqual(len(worker.finished.events), 1)
        self.assertTrue(worker.error.events)
        self.assertEqual([e[0] for e in events], ["create"],
                         "Video start/stop/IPC/wait must not be inserted into the original MIDI worker")

    def test_primary_exits_pre_roll_cleanup_does_not_launch_second_midi_owner(self):
        process = FakeProcess(exit_code=1)
        worker, midi, events = self.worker_fixture(lambda *a, **k: process)
        worker.preload_time = 1
        worker._run_logic(is_high_precision=False)
        self.assertTrue(midi.closed)
        self.assertTrue(worker.error.events)
        self.assertEqual(len(worker.finished.events), 1)
        self.assertEqual([e[0] for e in events], ["create"])

    def test_clock_loop_contains_no_follower_wait_query_or_join(self):
        node = self.source.method("MidiSyncWorker", "_run_logic")
        # Locate the clock hot loop structurally by its next_tick increment and
        # actual clock-byte transmission. Pre-roll/helper loops are not confused
        # with it. New implementations must keep a single master clock loop.
        loops = []
        for child in ast.walk(node):
            if isinstance(child, (ast.While, ast.For)):
                text = ast.unparse(child)
                if "next_tick +=" in text and "send_message" in text:
                    loops.append(child)
        self.assertEqual(len(loops), 1, "single master MIDI clock loop not found")
        forbidden = (".join(", ".wait(", "get_property", "_query", "_wait_for", "readline(", ".read(", "Popen(")
        loop = ast.unparse(loops[0])
        for token in forbidden:
            self.assertNotIn(token, loop, "blocking operation on MIDI hot loop: " + token)

    def test_calibration_still_uses_single_midi_worker_and_duration_limit(self):
        node = self.source.node("LiveController")
        calibrations = [m for m in node.body if isinstance(m, ast.FunctionDef)
                        and "calib" in m.name and "MidiSyncWorker" in ast.unparse(m)]
        self.assertTrue(calibrations, "calibration worker path removed")
        for method in calibrations:
            text = ast.unparse(method)
            self.assertIn("max_duration_sec", text)
            calls = [n for n in ast.walk(method) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == "MidiSyncWorker"]
            self.assertEqual(len(calls), 1)


class CoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()

    def fixture(self, *, fps=30000/1001, fps_estimate=None, fail=None,
                master_position=10.0, follower_position=10.0, paused=False):
        clock = FakeClock(value=10)
        events, reports, fps_updates, sync_updates, spawned = [], [], [], [], []
        state = {"master_position": master_position,
                 "positions": {"HDMI": follower_position, "DP": follower_position},
                 "pause": paused, "speed": 1.0, "seeking": False,
                 "fps": fps, "estimated": fps_estimate, "duration": 120.0,
                 "params": {"w":1920,"h":1080}, "fail": fail}
        def transport(pipe, command, **kwargs):
            events.append((pipe,list(command),kwargs.get("timeout")))
            if state["fail"] and state["fail"](pipe, command):
                return {"ok":False,"data":None,"error":"fixture failure"}
            value = None
            if command[0] == "get_property":
                prop = command[1]
                if prop == "pause": value = state["pause"] if pipe == "MASTER" else True
                elif prop == "speed": value = state["speed"]
                elif prop == "seeking": value = state["seeking"]
                elif prop == "time-pos":
                    value = state["master_position"] if pipe == "MASTER" else state["positions"][pipe.split("-")[0]]
                elif prop == "container-fps": value = state["fps"]
                elif prop == "estimated-vf-fps": value = state["estimated"]
                elif prop == "duration": value = state["duration"]
                elif prop == "video-params": value = state["params"]
            return {"ok":True,"data":value,"error":""}
        def popen(command, **kwargs):
            process = FakeProcess(command)
            spawned.append((process,kwargs))
            return process
        injected = {
            "MPV_PATH":"OFFLINE-MPV", "time":clock,
            "uuid":types.SimpleNamespace(uuid4=lambda:types.SimpleNamespace(hex="OFFLINE-GENERATION")),
            "_two_display_ipc_request":forbid,
            "_make_unique_mpv_pipe_name":lambda prefix:prefix.rsplit("_",1)[-1].upper()+"-PIPE",
            "subprocess":types.SimpleNamespace(Popen=forbid,TimeoutExpired=TimeoutError,
                                                BELOW_NORMAL_PRIORITY_CLASS=0x4000),
        }
        ns = self.source.dual_helpers({"TwoDisplayCoordinator","_two_display_stop_process"},injected=injected)
        cfg = ns["_migrate_two_display_config"]({})
        cfg["display_available"] = {"HDMI":True,"DP":True}
        cfg["zones"][0]["route"] = "both"
        coordinator = ns["TwoDisplayCoordinator"]("SYNTHETIC.mp4",cfg,transport=transport,
            popen=popen,report=reports.append,fps_callback=lambda *x:fps_updates.append(x),
            sync_callback=sync_updates.append)
        # Constructing Python Thread is inert; .start() is NEVER invoked.
        coordinator.attach_master("MASTER",FakeProcess())
        for output, follower in coordinator.followers.items():
            follower["pipe"] = output+"-PIPE"
        return types.SimpleNamespace(c=coordinator,ns=ns,state=state,events=events,reports=reports,
            fps_updates=fps_updates,sync_updates=sync_updates,spawned=spawned,clock=clock)

    def ready(self, f, output):
        state = f.c.followers[output]
        state.update(process=FakeProcess(),pipe=output+"-PIPE",ready=True,attempted=True,
                     retired=False,deadline=20.0)
        return state

    @staticmethod
    def writes(f):
        return [(pipe,cmd) for pipe,cmd,_ in f.events if cmd[0] != "get_property"]

    def test_handoffs_nonblocking_latest_only_and_stop_immediate(self):
        f = self.fixture()
        f.c.transport = forbid
        f.c.set_display_availability({"HDMI":True,"DP":False})
        f.c.set_frame_settings("HDMI",3,4)
        previous = f.c.frame_settings
        f.c.set_frame_settings("DP",-7,5)
        self.assertEqual(previous["DP"]["offset_frames"],0)
        self.assertEqual(f.c.frame_settings["HDMI"],{"offset_frames":3,"drift_threshold_frames":4})
        f.c.attach_master("NEW-MASTER",FakeProcess())
        f.c.stop()
        f.c.set_frame_settings("DP",100,2)
        self.assertEqual(f.c.frame_settings["DP"]["offset_frames"],-7)
        self.assertTrue(f.c.cancel.is_set())
        self.assertFalse(f.events)

    def test_fractional_fps_metadata_keeps_audible_master_read_only(self):
        f = self.fixture()
        f.c._prepare_master_metadata()
        self.assertTrue(f.c.master_prepared)
        self.assertFalse(f.c.fps_fallback)
        self.assertAlmostEqual(f.c.fps,30000/1001)
        self.assertEqual(f.c.source_size,(1920,1080))
        self.assertEqual(f.c.duration,120.0)
        self.assertEqual(self.writes(f),[])

    def test_missing_nan_boolean_and_invalid_fps_explicit_fallback(self):
        for bad in (None,0,-25,float("nan"),float("inf"),True,"garbage"):
            with self.subTest(fps=bad):
                f = self.fixture(fps=bad)
                f.c._prepare_master_metadata()
                self.assertEqual(f.c.fps,25.0)
                self.assertTrue(f.c.fps_fallback)
                self.assertEqual(f.fps_updates,[(25.0,True)])
                self.assertTrue(any("25 FPS" in text for text in f.reports))
                self.assertEqual(self.writes(f),[])

    def test_estimated_media_fps_precedes_fallback(self):
        f = self.fixture(fps=None,fps_estimate=24000/1001)
        f.c._prepare_master_metadata()
        self.assertAlmostEqual(f.c.fps,24000/1001)
        self.assertFalse(f.c.fps_fallback)

    def test_supervisor_refuses_every_audible_master_write(self):
        f = self.fixture()
        for command in (["set_property","pause",False],["seek",10,"absolute+exact"],
                        ["set_property","speed",1.1],["set_property","audio-delay",0.1],
                        ["set_property","vid","no"],["vf","set","null"]):
            with self.subTest(command=command):
                result = f.c._request("MASTER",command)
                self.assertIs(result["ok"],False)
        self.assertFalse(f.events)
        self.assertFalse(hasattr(f.c,"request_start"),"No asynchronous audible-release owner allowed")
        self.assertFalse(hasattr(f.c,"_release_master"))

    def test_both_outputs_threshold_is_integer_frames(self):
        for output in ("HDMI","DP"):
            with self.subTest(output=output):
                f = self.fixture(fps=25,master_position=10,follower_position=10+2/25)
                f.c.fps = 25
                state = self.ready(f,output)
                state.update(force=False,last_offset=0,speed=1.0,pause=False)
                f.c._follow_output(output,f.c._master_state())
                self.assertFalse([cmd for _,cmd in self.writes(f) if cmd[0]=="seek"])
                f.events.clear()
                state["last_master"] = None
                f.state["positions"][output] = 10+3/25
                f.c._follow_output(output,f.c._master_state())
                seeks = [cmd for _,cmd in self.writes(f) if cmd[0]=="seek"]
                self.assertEqual(seeks,[["seek",10.0,"absolute+exact"]])
                self.assertTrue(all(pipe==output+"-PIPE" for pipe,_ in self.writes(f)))
                self.assertTrue(all("frames" in text for text in f.sync_updates))

    def test_offsets_first_and_last_frame_clamp_hold(self):
        for output in ("HDMI","DP"):
            for offset,position,expected,hold in ((3,0,0,True),(-3,0,3/25,False),(-3,1,24/25,True)):
                with self.subTest(output=output,offset=offset,position=position):
                    f = self.fixture(fps=25,master_position=position,follower_position=0)
                    f.c.fps,f.c.duration = 25,1.0
                    state = self.ready(f,output)
                    f.c.set_frame_settings(output,offset,2)
                    f.c._follow_output(output,f.c._master_state())
                    seeks = [cmd for _,cmd in self.writes(f) if cmd[0]=="seek"]
                    self.assertEqual(len(seeks),1)
                    self.assertAlmostEqual(seeks[0][1],expected)
                    self.assertEqual(seeks[0][2:],["absolute+exact"])
                    self.assertEqual(state["pause"],hold)

    def test_pause_seek_speed_and_discontinuity_follower_only(self):
        for output in ("HDMI","DP"):
            with self.subTest(output=output):
                f = self.fixture(fps=25,master_position=40,follower_position=5,paused=True)
                f.c.fps = 25
                state = self.ready(f,output)
                f.state["speed"] = 1.25
                f.c._follow_output(output,f.c._master_state())
                writes = self.writes(f)
                self.assertTrue(all(pipe==output+"-PIPE" for pipe,_ in writes))
                self.assertIn((output+"-PIPE",["set_property","speed",1.25]),writes)
                self.assertIn((output+"-PIPE",["seek",40.0,"absolute+exact"]),writes)
                self.assertIs(state["pause"],True)
                f.events.clear()
                f.state["master_position"] = f.state["positions"][output] = 5.0
                state["force"] = False
                f.c._follow_output(output,f.c._master_state())
                self.assertTrue(any(cmd[0]=="seek" for _,cmd in self.writes(f)))

    def test_small_paused_offset_edit_forces_correction_each_output(self):
        f = self.fixture(fps=25,master_position=10,follower_position=10,paused=True)
        f.c.fps = 25
        for output in ("HDMI","DP"):
            state = self.ready(f,output)
            state.update(force=False,last_offset=0,speed=1.0,pause=True)
        f.c.set_frame_settings("HDMI",1,5)
        f.c._follow_output("HDMI",f.c._master_state())
        self.assertIn(("HDMI-PIPE",["seek",9.96,"absolute+exact"]),self.writes(f))
        self.assertEqual(f.c.frame_settings["DP"]["offset_frames"],0)
        self.assertTrue(f.c.followers["HDMI"]["pause"])
        f.events.clear()
        f.c.set_frame_settings("DP",-1,5)
        f.c._follow_output("DP",f.c._master_state())
        self.assertIn(("DP-PIPE",["seek",10.04,"absolute+exact"]),self.writes(f))
        self.assertTrue(all(pipe!="MASTER" for pipe,_ in self.writes(f)))

    def test_paused_master_manual_steps_ignore_moving_drift_threshold(self):
        # A transient seeking=True can be missed between polls. A paused source
        # edit is intentional, not allowable moving-playback drift. Old 9fa78
        # fails these cases and permanently consumes the edit in last_master.
        for output in ("HDMI","DP"):
            for fps in (25.0,30000/1001):
                for threshold in (2,250):
                    for delta_frames in (-1,1,125):
                        with self.subTest(output=output,fps=fps,threshold=threshold,delta=delta_frames):
                            f=self.fixture(fps=fps,master_position=10,follower_position=10,paused=True)
                            f.c.fps=fps
                            state=self.ready(f,output)
                            state.update(force=False,last_offset=0,speed=1.0,pause=True,
                                last_master=(10.0,f.clock.value,True,1.0))
                            f.c.set_frame_settings(output,0,threshold)
                            f.state["master_position"]=10+delta_frames/fps
                            f.c._follow_output(output,f.c._master_state())
                            seeks=[(pipe,cmd) for pipe,cmd in self.writes(f) if cmd[0]=="seek"]
                            self.assertEqual(len(seeks),1,"Paused manual source edit must not be swallowed by drift threshold")
                            self.assertEqual(seeks[0][0],output+"-PIPE")
                            self.assertAlmostEqual(seeks[0][1][1],f.state["master_position"],places=10)
                            self.assertEqual(seeks[0][1][2:],["absolute+exact"])
                            self.assertTrue(state["pause"])
                            self.assertTrue(all(pipe!="MASTER" for pipe,_ in self.writes(f)))
                            # A stable next paused sample must not seek forever.
                            f.state["positions"][output]=f.state["master_position"]
                            f.events.clear()
                            f.c._follow_output(output,f.c._master_state())
                            self.assertFalse([cmd for _,cmd in self.writes(f) if cmd[0]=="seek"])

    def test_paused_source_edit_clamps_first_last_frame_and_float_noise(self):
        for output in ("HDMI","DP"):
            for fps in (25.0,30000/1001):
                for offset,old_pos,new_pos,expected in ((3,2/fps,1/fps,0.0),
                        (-3,10-3/fps,10-2/fps,10-1/fps)):
                    with self.subTest(output=output,fps=fps,offset=offset):
                        f=self.fixture(fps=fps,master_position=new_pos,
                            follower_position=max(0.0,min(old_pos-offset/fps,10-1/fps)),paused=True)
                        f.c.fps,f.c.duration=fps,10.0
                        state=self.ready(f,output)
                        state.update(force=False,last_offset=offset,speed=1.0,pause=True,
                            last_master=(old_pos,f.clock.value,True,1.0))
                        f.c.set_frame_settings(output,offset,250)
                        f.c._follow_output(output,f.c._master_state())
                        seeks=[cmd for _,cmd in self.writes(f) if cmd[0]=="seek"]
                        self.assertEqual(len(seeks),1)
                        self.assertAlmostEqual(seeks[0][1],expected,places=10)
                        self.assertTrue(state["pause"])
                f=self.fixture(fps=fps,master_position=10+1e-12,follower_position=10,paused=True)
                f.c.fps=fps
                state=self.ready(f,output)
                state.update(force=False,last_offset=0,speed=1.0,pause=True,
                    last_master=(10.0,f.clock.value,True,1.0))
                f.c.set_frame_settings(output,0,250)
                f.c._follow_output(output,f.c._master_state())
                self.assertFalse([cmd for _,cmd in self.writes(f) if cmd[0]=="seek"],
                    "Sub-frame binary float noise is not an intentional manual seek")

    def test_failed_paused_manual_seek_retries_same_position_without_audible_write(self):
        for output in ("HDMI","DP"):
            for fps in (25.0,30000/1001):
                for failed_command in ("pause","seek"):
                    with self.subTest(output=output,fps=fps,failure=failed_command):
                        f=self.fixture(fps=fps,master_position=10,follower_position=10,paused=True)
                        f.c.fps=fps
                        state=self.ready(f,output)
                        state.update(force=False,last_offset=0,speed=1.0,pause=True,
                            last_master=(10.0,f.clock.value,True,1.0))
                        f.c.set_frame_settings(output,0,250)
                        f.state["master_position"]=10+1/fps
                        original=f.c.transport
                        blocked={"value":True}
                        def transport(pipe,command,**kwargs):
                            selected=(command[:2]==["set_property","pause"] if failed_command=="pause" else command[0]=="seek")
                            if blocked["value"] and pipe==output+"-PIPE" and selected:
                                return {"ok":False,"error":"synthetic transient deadline"}
                            return original(pipe,command,**kwargs)
                        f.c.transport=transport
                        f.c._follow_output(output,f.c._master_state())
                        self.assertTrue(state["force"],"Failed paused correction must remain pending after last_master advances")
                        blocked["value"]=False
                        f.events.clear()
                        f.c._follow_output(output,f.c._master_state())
                        seeks=[cmd for _,cmd in self.writes(f) if cmd[0]=="seek"]
                        self.assertEqual(len(seeks),1)
                        self.assertAlmostEqual(seeks[0][1],f.state["master_position"],places=10)
                        self.assertFalse(state["force"])
                        self.assertTrue(state["pause"])
                        self.assertTrue(all(pipe!="MASTER" for pipe,_ in self.writes(f)))

    def test_pause_transition_with_one_frame_source_edit_corrects_follower(self):
        for output in ("HDMI","DP"):
            f=self.fixture(fps=25,master_position=10.04,follower_position=10,paused=True)
            f.c.fps=25.0
            state=self.ready(f,output)
            state.update(force=False,last_offset=0,speed=1.0,pause=False,
                last_master=(10.0,f.clock.value,False,1.0))
            f.c.set_frame_settings(output,0,250)
            f.c._follow_output(output,f.c._master_state())
            self.assertIn((output+"-PIPE",["seek",10.04,"absolute+exact"]),self.writes(f))
            self.assertTrue(state["pause"])
            self.assertTrue(all(pipe!="MASTER" for pipe,_ in self.writes(f)))

    def test_independent_fractional_offsets_for_two_silent_outputs(self):
        f = self.fixture(fps=30000/1001,paused=True)
        f.c._prepare_master_metadata()
        f.c.set_frame_settings("HDMI",3,2)
        f.c.set_frame_settings("DP",-4,2)
        for output in ("HDMI","DP"):
            self.ready(f,output)
            f.c._follow_output(output,f.c._master_state())
        seeks = {pipe:cmd for pipe,cmd in self.writes(f) if cmd[0]=="seek"}
        self.assertAlmostEqual(seeks["HDMI-PIPE"][1],10-3*1001/30000,places=12)
        self.assertAlmostEqual(seeks["DP-PIPE"][1],10+4*1001/30000,places=12)
        self.assertTrue(all(cmd[2:]==["absolute+exact"] for cmd in seeks.values()))

    def test_two_follower_commands_silent_unique_black_and_lower_priority(self):
        f = self.fixture()
        f.c.source_size = (1920,1080)
        for output in ("HDMI","DP"): f.c._start_output(output)
        self.assertEqual(len(f.spawned),2)
        self.assertNotEqual(f.c.followers["HDMI"]["pipe"],f.c.followers["DP"]["pipe"])
        for process,kwargs in f.spawned:
            for flag in ("--no-audio","--mute=yes","--keep-open=yes","--pause","--video-sync=audio"):
                self.assertIn(flag,process.command)
            self.assertTrue(any(arg.startswith("--vf=") and "black" in arg for arg in process.command))
            self.assertFalse(any("audio-delay" in arg or "initial-audio-sync" in arg for arg in process.command))
            if os.name=="nt":self.assertEqual(kwargs.get("creationflags"),0x4000)
        self.assertEqual(self.writes(f),[])

    def test_launch_failure_is_per_output_and_nonfatal(self):
        for output in ("HDMI","DP"):
            with self.subTest(output=output):
                f = self.fixture()
                f.c.source_size = (1920,1080)
                other = self.ready(f,"DP" if output=="HDMI" else "HDMI")["process"]
                f.c.popen = lambda *a,**k:(_ for _ in ()).throw(OSError("SYNTHETIC"))
                f.c._start_output(output)
                self.assertTrue(f.c.followers[output]["retired"])
                self.assertFalse(f.c.cancel.is_set())
                self.assertEqual(f.c.master_process.terminated,0)
                self.assertEqual(other.terminated,0)
                self.assertTrue(any(output+" launch failed" in text for text in f.reports))

    def test_filter_rejection_retires_only_its_output_never_raw(self):
        for output in ("HDMI","DP"):
            with self.subTest(output=output):
                f = self.fixture(fail=lambda pipe,cmd:pipe==output+"-PIPE" and cmd[0]=="vf")
                f.c.source_size = (1920,1080)
                state = self.ready(f,output)
                process = state["process"]
                other = self.ready(f,"DP" if output=="HDMI" else "HDMI")["process"]
                f.c._prepare_output(output)
                self.assertTrue(state["retired"])
                self.assertFalse(state["ready"])
                self.assertEqual(process.terminated,1)
                self.assertEqual(other.terminated,0)
                self.assertEqual(f.c.master_process.terminated,0)
                self.assertTrue(any("rather than raw" in text for text in f.reports))

    def test_primary_eof_failure_cleans_both_followers(self):
        for code in (0,1):
            with self.subTest(code=code):
                f = self.fixture()
                f.c.master_process.exit_code = code
                processes = [self.ready(f,out)["process"] for out in ("HDMI","DP")]
                f.c.run()  # synchronous: EOF is already observed; no real waits
                self.assertTrue(all(p.terminated==1 for p in processes))
                self.assertTrue(all(s["process"] is None for s in f.c.followers.values()))
                self.assertFalse(f.events)

    def test_cancellation_during_popen_owns_late_process(self):
        for output in ("HDMI","DP"):
            with self.subTest(output=output):
                f = self.fixture()
                f.c.source_size = (1920,1080)
                process = FakeProcess()
                def late(*args,**kwargs):
                    f.c.stop()
                    return process
                f.c.popen = late
                f.c._start_output(output)
                self.assertEqual(process.terminated,1)
                self.assertIsNone(f.c.followers[output]["process"])
                self.assertFalse(f.c.followers[output]["ready"])
                self.assertEqual(f.c.master_process.terminated,0)

    def test_readiness_deadline_does_not_retime_audio_or_other_video(self):
        f = self.fixture(fail=lambda pipe,cmd:pipe=="DP-PIPE")
        f.c.master_started = True
        f.c.source_size = (1920,1080)
        state = self.ready(f,"DP")
        state["deadline"] = 9.0
        process = state["process"]
        other = self.ready(f,"HDMI")["process"]
        f.c._prepare_output("DP")
        self.assertTrue(state["retired"])
        self.assertEqual(process.terminated,1)
        self.assertEqual(other.terminated,0)
        self.assertTrue(f.c.master_started)
        self.assertTrue(all(pipe=="DP-PIPE" for pipe,_,_ in f.events))

    def test_stop_process_waits_bounded_and_escalates(self):
        f = self.fixture()
        process = FakeProcess()
        def timeout_wait(timeout):
            process.waited.append(timeout)
            raise TimeoutError()
        process.wait = timeout_wait
        f.ns["_two_display_stop_process"](process,timeout=0.017)
        self.assertEqual(process.terminated,1)
        self.assertEqual(process.killed,1)
        self.assertEqual(process.waited,[0.017,0.017])

    def test_stop_before_launch_and_repeat_teardown_safe(self):
        f = self.fixture()
        f.c.source_size = (1920,1080)
        f.c.stop()
        for output in ("HDMI","DP"): f.c._start_output(output)
        self.assertFalse(f.spawned)
        process = FakeProcess()
        f.ns["_two_display_stop_process"](process)
        f.ns["_two_display_stop_process"](process)
        self.assertEqual(process.terminated,1)
        self.assertEqual(process.waited,[0.2])

    def test_eight_follower_telemetry_misses_retire_only_video(self):
        f = self.fixture(fail=lambda pipe,cmd:pipe=="DP-PIPE")
        f.c.fps = 25
        state = self.ready(f,"DP")
        process = state["process"]
        other = self.ready(f,"HDMI")["process"]
        for _ in range(8): f.c._follow_output("DP",f.c._master_state())
        self.assertTrue(state["retired"])
        self.assertEqual(process.terminated,1)
        self.assertEqual(other.terminated,0)
        self.assertFalse(f.c.cancel.is_set())
        self.assertTrue(all(timeout<=0.04 for _,_,timeout in f.events))

    def test_eight_follower_command_failures_retire_only_video(self):
        f = self.fixture(fail=lambda pipe,cmd:pipe=="DP-PIPE" and cmd[0]!="get_property")
        state = self.ready(f,"DP")
        process = state["process"]
        for _ in range(8): f.c._follow_output("DP",f.c._master_state())
        self.assertTrue(state["retired"])
        self.assertEqual(process.terminated,1)
        self.assertFalse(f.c.cancel.is_set())
        self.assertEqual(f.c.master_process.terminated,0)

    def test_empty_or_unavailable_outputs_never_launch_raw_fallback(self):
        for reason in ("disabled","no-routes","missing"):
            with self.subTest(reason=reason):
                f = self.fixture()
                f.c.source_size = (1920,1080)
                if reason=="disabled":
                    for out in f.c.config["outputs"].values():out["enabled"]=False
                elif reason=="no-routes":
                    for zone in f.c.config["zones"]:zone["enabled"]=False
                else:f.c.available={"HDMI":False,"DP":False}
                for output in ("HDMI","DP"):f.c._start_output(output)
                self.assertFalse(f.spawned)
                self.assertTrue(all(s["retired"] for s in f.c.followers.values()))
                self.assertEqual(self.writes(f),[])

    def test_master_numeric_boolean_or_nonfinite_telemetry_rejected(self):
        for prop in ("master_position","speed"):
            for bad in (True,False,None,float("nan"),float("inf")):
                with self.subTest(prop=prop,value=bad):
                    f = self.fixture()
                    f.state[prop]=bad
                    self.assertIsNone(f.c._master_state())
                    self.assertEqual(self.writes(f),[])
        for prop in ("pause","seeking"):
            for bad in (0,1,None,"false"):
                with self.subTest(prop=prop,value=bad):
                    f = self.fixture()
                    f.state[prop]=bad
                    self.assertIsNone(f.c._master_state())
                    self.assertFalse(self.writes(f))

    def test_seeking_and_stale_samples_suspend_correction(self):
        f = self.fixture()
        state = self.ready(f,"DP")
        f.state["seeking"]=True
        f.c._follow_output("DP",f.c._master_state())
        self.assertTrue(state["force"])
        self.assertFalse(any(cmd[0]=="seek" for _,cmd in self.writes(f)))
        self.assertIn(("DP-PIPE",["set_property","pause",True]),self.writes(f))
        f.events.clear()
        f.state["seeking"]=False
        master=f.c._master_state()
        master["sample_time"]-=0.3
        f.c._follow_output("DP",master)
        self.assertFalse(self.writes(f))
        self.assertFalse(f.sync_updates)

    def test_old_generation_stop_blocks_late_requests_launch_and_callbacks(self):
        f = self.fixture()
        owner=types.SimpleNamespace(_is_running=False)
        f.c.master_owner=owner
        f.c.source_size=(1920,1080)
        result=f.c._request("DP-PIPE",["seek",10,"absolute+exact"])
        self.assertFalse(result["ok"])
        f.c._start_output("DP")
        f.c._prepare_master_metadata()
        self.assertFalse(f.spawned)
        self.assertFalse(f.events)
        self.assertFalse(f.fps_updates)
        self.assertFalse(f.sync_updates)
        self.assertFalse(f.reports)

    def test_wav_never_launches_followers_or_video_queries(self):
        f=self.fixture()
        f.c.audio_only=True
        f.c.source_size=(1920,1080)
        for output in ("HDMI","DP"):f.c._start_output(output)
        self.assertFalse(f.spawned)
        f.c.master_process.exit_code=0
        f.c.run()
        self.assertFalse(f.events)


class FakeKernel:
    """Pure Python Win32-overlapped protocol fake; no Windows function loads."""
    def __init__(self, ctypes_module, clock, *, mode="success", cancel=None):
        self.ctypes = ctypes_module
        self.clock = clock
        self.mode = mode
        self.cancel = cancel
        self.closed = []
        self.cancelled = []
        self.events = 200
        self.payload = None
        self.requests = []
        self.get_results = 0
        self.waits = []
        self.error = 0
        self.keep_buffers = []

    def CreateFileW(self, *args):
        self.requests.append("open")
        if self.mode == "missing":
            return self.ctypes.c_void_p(-1).value
        return 101

    def CreateEventW(self, *args):
        self.events += 1
        return self.events

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def WriteFile(self, handle, buffer, length, amount, overlapped):
        self.payload = json.loads(bytes(buffer.raw[:length]).decode())
        self.requests.append(self.payload["command"])
        amount._obj.value = length
        return True

    def ReadFile(self, handle, buffer, length, amount, overlapped):
        if self.mode in ("pending", "cancel"):
            self.error = 997
            self.keep_buffers.append(buffer)
            if self.mode == "cancel":
                self.cancel.set()
            return False
        rid = self.payload["request_id"]
        if self.mode == "mismatch":
            reply = ({"event": "time-pos", "data": 1.25},
                     {"request_id": rid + 1, "error": "success", "data": "wrong"},
                     {"request_id": rid, "error": "success", "data": 29.97002997002997})
        elif self.mode == "rejected":
            reply = ({"request_id": rid, "error": "property unavailable"},)
        elif self.mode == "bad-json":
            reply = None
        else:
            reply = ({"request_id": rid, "error": "success", "data": 29.97002997002997},)
        data = (("not json" + chr(10)) if reply is None else
                "".join(json.dumps(item) + chr(10) for item in reply)).encode()
        self.ctypes.memmove(buffer, data, len(data))
        amount._obj.value = len(data)
        self.clock.value += 0.002
        return True

    def WaitForSingleObject(self, event, milliseconds):
        self.waits.append(milliseconds)
        if self.mode in ("pending", "cancel"):
            self.clock.value += milliseconds / 1000.0 + 0.001
            return 258
        return 0

    def GetOverlappedResult(self, *args):
        self.get_results += 1
        return True

    def CancelIoEx(self, handle, overlapped):
        self.cancelled.append(handle)
        return True


class BoundedIpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ExtractedSource()

    def fixture(self, mode="success"):
        clock = FakeClock(value=0)
        cancel = threading.Event()
        kernel = FakeKernel(ctypes, clock, mode=mode, cancel=cancel)
        # Real ctypes memory/structures are safe; only DLL loading/native calls
        # are blocked. Every Win32 operation is the Python fake above.
        c = types.SimpleNamespace(**{name: getattr(ctypes, name) for name in (
            "Structure", "c_size_t", "c_void_p", "byref", "create_string_buffer")})
        c.wintypes = ctypes.wintypes
        c.get_last_error = lambda: kernel.error
        c.WinDLL = forbid
        ns = self.source.namespace({"_TwoDisplayPipeIO", "_two_display_ipc_request"}, injected={
            "ctypes": c, "uuid": types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(int=123)),
            "os": types.SimpleNamespace(name="nt"), "time": clock,
        })
        pipe = ns["_TwoDisplayPipeIO"]
        pipe._kernel = staticmethod(lambda: kernel)
        deferred = []
        pipe._defer = classmethod(lambda cls, state: deferred.append(state))
        return ns, pipe, kernel, clock, cancel, deferred

    def test_request_reply_correlates_id_and_closes_handles(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture("mismatch")
        result = pipe.request("OFFLINE-PIPE", ["get_property", "estimated-vf-fps"], cancel=cancel)
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["data"], 30000 / 1001)
        self.assertIn(101, kernel.closed)
        self.assertFalse(kernel.cancelled)
        self.assertFalse(deferred)

    def test_rejected_command_returns_sanitized_error(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture("rejected")
        result = pipe.request("OFFLINE-PIPE", ["get_property", "private-media-path"], cancel=cancel)
        self.assertFalse(result["ok"])
        self.assertNotIn("private", result["error"])
        self.assertIn(101, kernel.closed)

    def test_cancel_before_dispatch_never_calls_kernel(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture()
        cancel.set()
        pipe._kernel = staticmethod(forbid)
        result = pipe.request("OFFLINE-PIPE", ["quit"], cancel=cancel)
        self.assertFalse(result["ok"])
        self.assertIn("cancel", result["error"])
        self.assertEqual(kernel.requests, [])

    def test_open_deadline_is_bounded(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture("missing")
        result = pipe.request("OFFLINE-PIPE", ["quit"], timeout=0.02)
        self.assertFalse(result["ok"])
        self.assertIn("deadline", result["error"])
        self.assertLessEqual(clock.value, 0.03)
        self.assertFalse(kernel.closed)

    def test_pending_deadline_cancels_and_preserves_native_buffers(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture("pending")
        result = pipe.request("OFFLINE-PIPE", ["get_property", "time-pos"], timeout=0.03)
        self.assertFalse(result["ok"])
        self.assertIn("deadline", result["error"])
        self.assertEqual(kernel.cancelled, [101])
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0][1], 101)
        self.assertIs(deferred[0][-1], kernel.keep_buffers[-1])
        self.assertNotIn(101, kernel.closed, "late native operation still owns handle/buffer")
        self.assertLess(clock.value, 0.06)
        self.assertTrue(all(ms <= 10 for ms in kernel.waits))

    def test_cancel_during_pending_read_returns_without_join_or_native_wait(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture("cancel")
        result = pipe.request("OFFLINE-PIPE", ["get_property", "time-pos"], cancel=cancel)
        self.assertFalse(result["ok"])
        self.assertIn("cancel", result["error"])
        self.assertEqual(kernel.cancelled, [101])
        self.assertEqual(len(deferred), 1)
        self.assertTrue(all(ms == 0 for ms in kernel.waits))

    def test_cancellation_backlog_refuses_dispatch(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture()
        pipe._pending = [object()] * pipe._MAX_PENDING
        pipe._kernel = staticmethod(forbid)
        result = pipe.request("OFFLINE-PIPE", ["get_property", "time-pos"])
        self.assertFalse(result["ok"])
        self.assertIn("backlog", result["error"])
        self.assertFalse(kernel.requests)

    def test_transport_injection_forwards_cancellation_and_timeout(self):
        ns, pipe, kernel, clock, cancel, deferred = self.fixture()
        received = []
        def transport(*args, **kwargs):
            received.append((args, kwargs))
            return {"ok": True, "data": 1, "error": ""}
        result = ns["_two_display_ipc_request"]("TEST", ["quit"], cancel=cancel,
                                               timeout=0.123, transport=transport)
        self.assertTrue(result["ok"])
        self.assertEqual(received, [(("TEST", ["quit"]), {"cancel": cancel, "timeout": 0.123})])


if __name__ == "__main__":
    unittest.main()
