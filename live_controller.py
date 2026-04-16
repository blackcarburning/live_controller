# live_controller.py
#
# Author: blackcarburning
# Date: 2025-07-26 10:54:03
#
# Description:
# A comprehensive live performance controller for synchronizing video playback 
# with external MIDI devices. The application provides a graphical user interface 
# built with PyQt6 to manage a setlist of video tracks, control playback, 
# and test MIDI connections. It uses mpv for video playback, rtmidi for MIDI 
# communication, and features global hotkey support for in-show control.

# --- Standard Library Imports ---
import sys
import os
import re
import subprocess
import time
import json
import ctypes
import ctypes.wintypes
import threading
import datetime
import tempfile
import shutil
from collections import deque

# --- Third-Party Library Imports ---
# This solution requires the 'keyboard' and 'psutil' libraries.
# If you see a "ModuleNotFoundError", please install them by running this command
# in your command prompt:
#
# python -m pip install keyboard psutil rtmidi-python
#
# Stream Deck support (optional) requires two additional packages:
#   python -m pip install streamdeck Pillow
# The Elgato Stream Deck software must be closed before using the push feature.
#
import rtmidi                  # For sending MIDI messages
import keyboard                # For global hotkey listening
import psutil                  # For setting process priority
import serial                  # For Arduino serial communication
from serial.tools import list_ports  # For discovering serial ports

# Optional Stream Deck support — imported lazily inside methods so the rest of
# the app still works even if the packages are not installed.
try:
    from StreamDeck.DeviceManager import DeviceManager as _SDDeviceManager
    from StreamDeck.ImageHelpers import PILHelper as _SDPILHelper
    _STREAMDECK_AVAILABLE = True
except ImportError:
    _STREAMDECK_AVAILABLE = False

try:
    from PIL import Image as _PILImage, ImageDraw as _PILImageDraw, ImageFont as _PILImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTableWidget, QTableWidgetItem, QLineEdit, QHeaderView, 
                             QGroupBox, QLabel, QFileDialog, QSizePolicy, QComboBox,
                             QAbstractButton, QSlider, QAbstractItemView, QCheckBox,
                             QGridLayout, QRadioButton, QSpinBox, QColorDialog, QDialog,
                             QTabWidget, QStackedWidget)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QPoint, QEasingCurve, pyqtProperty, QTimer, QRect
from PyQt6.QtGui import QFont, QGuiApplication, QPainter, QColor, QBrush, QPen, QPixmap

# --- Core Application Configuration ---
# File paths for external media players
MPV_PATH = r"c:\mpv\mpv.exe"
MPLAYER_PATH = r"d:\mplayer\mplayer.exe"

# JSON files for persistent storage of track-specific data
BPM_STORE_FILE = "bpm_store.json"
TRACK_NAME_STORE_FILE = "track_names.json"
SD_STATE_FILE = "sd_state.json"

# Configuration and session files for the application state
CONFIG_FILE = "config.json"
SESSION_FILE = "session.json"
ZOOM_CONFIG_FILE = "zoom_config.json"
ZOOM_FRAME_SNAPSHOT = "zoom_frame_snapshot.png"  # Persistent frame snapshot in project dir
SETLISTS_DIR = "setlists"

# Default settings for playback and display
DEFAULT_VIDEO_SCREEN_NUMBER = 1
DEFAULT_LOAD_DELAY_SECONDS = 5
DEFAULT_MIDI_OFFSET_MS = 0
DEFAULT_COUNT_IN_SECONDS = 20
DEFAULT_TABLE_FONT_SIZE = 16
DEFAULT_COUNT_IN_FONT_SIZE = 250
DEFAULT_TRACK_PLAY_FONT_SIZE = 80
DEFAULT_COUNT_IN_BG_COLOR = "#c80000"
DEFAULT_TRACK_PLAY_BG_COLOR = "#00c800"
TRACK_OVERHEAD_SECONDS = 15  # Extra time added to total running time per track for transitions
MAX_UNDO_LEVELS = 30

# UI and timing constants
PREPARING_OVERLAY_DURATION_MS = 2000
ACTIVE_FLASH_INTERVAL_MS = 500
SAVE_POPUP_DURATION_MS = 3000
MPV_LAUNCH_HEAD_START_SECONDS = 2 # Launch mpv this many seconds before pre-roll ends

# --- MIDI Protocol Bytes (Standard MIDI Specification) ---
START_BYTE = 0xFA    # MIDI System Real-Time Message: Start
STOP_BYTE = 0xFC     # MIDI System Real-Time Message: Stop
CLOCK_BYTE = 0xF8    # MIDI System Real-Time Message: Timing Clock
SPP_BYTE = 0xF2      # MIDI System Common Message: Song Position Pointer

# --- Arduino LED Controller Constants ---
ARDUINO_BAUD = 9600
ARDUINO_TARGET_ID = "LED_TEST_PRO_MINI_01"
ARDUINO_PROBE_CMD = b'?\n'

# --- Windows Multimedia Timer API ---
# Used for high-precision timing on Windows to ensure accurate MIDI clock signals.
# `timeBeginPeriod` requests a higher timer resolution from the OS.
winmm = ctypes.windll.winmm

# --- Dark Theme Stylesheet ---
# A global stylesheet to provide a consistent dark theme for the application.
DARK_STYLESHEET = """
QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Segoe UI';
}
QGroupBox {
    font-size: 12px;
    font-weight: bold;
    border: 1px solid #444;
    border-radius: 8px;
    margin-top: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top center;
    padding: 0 10px;
}
QLabel {
    background-color: transparent;
}
QPushButton {
    background-color: #333;
    color: #d4d4d4;
    border: 1px solid #555;
    padding: 8px;
    border-radius: 6px;
    font-size: 16px;
}
QPushButton:hover {
    background-color: #454545;
}
QPushButton:pressed {
    background-color: #555;
}
QPushButton:disabled {
    background-color: #2a2a2a;
    color: #5a5a5a;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #2a2a2a;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 5px;
    font-size: 12px;
}
QComboBox::drop-down {
    border: none;
}
QTableWidget {
    background-color: #2a2a2a;
    gridline-color: #444;
    border: 1px solid #444;
}
QHeaderView::section {
    background-color: #333;
    color: #d4d4d4;
    padding: 5px;
    border: 1px solid #444;
    font-size: 14pt;
}
QTableWidget::item {
    padding-left: 5px;
    padding-right: 5px;
}
QTableWidget::item:selected {
    background-color: #3d3d3d;
    color: #d4d4d4;
}
QSlider::groove:horizontal {
    border: 1px solid #444;
    background: #333;
    height: 8px;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: #d4d4d4;
    border: 1px solid #d4d4d4;
    width: 18px;
    margin: -5px 0;
    border-radius: 9px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555;
    border-radius: 4px;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #3498db;
}
"""

def _lc_send_ipc_command(pipe_path, command_str):
    """Sends a JSON command string to mpv via its Windows named pipe."""
    try:
        with open(pipe_path, "w", encoding='utf-8') as f:
            f.write(command_str + '\n')
    except Exception as e:
        print(f"mpv IPC send error (pipe: {pipe_path}): {e}")


def _lc_query_mpv_property(pipe_path, prop):
    """Query a single mpv property via a Windows named pipe.

    Uses the Win32 CreateFile / WriteFile / ReadFile API for bidirectional
    access to the named pipe.  Returns the property value on success, or
    *None* on any error (including when running on a non-Windows host).
    """
    try:
        GENERIC_READ  = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3

        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        handle = k32.CreateFileW(
            pipe_path, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
        )
        invalid = ctypes.c_void_p(-1).value
        if handle is None or handle == invalid:
            return None
        try:
            cmd = json.dumps({"command": ["get_property", prop], "request_id": 42}) + '\n'
            cmd_bytes = cmd.encode('utf-8')
            bw = ctypes.c_uint32(0)
            if not k32.WriteFile(handle, cmd_bytes, len(cmd_bytes), ctypes.byref(bw), None):
                return None
            buf = ctypes.create_string_buffer(4096)
            br = ctypes.c_uint32(0)
            if not k32.ReadFile(handle, buf, 4096, ctypes.byref(br), None):
                return None
            if br.value == 0:
                return None
            for line in buf.raw[:br.value].decode('utf-8', errors='ignore').split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get('request_id') == 42 and obj.get('error') == 'success':
                        return obj.get('data')
                except json.JSONDecodeError:
                    pass
        finally:
            k32.CloseHandle(handle)
    except Exception:
        pass
    return None


class DraggableTableWidget(QTableWidget):
    """A QTableWidget subclass that supports drag-and-drop row reordering."""
    # Signal to notify the main controller when rows have been reordered.
    rows_reordered = pyqtSignal(int, int) # Emits start and end row indices.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Configure the widget for drag-and-drop.
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropOverwriteMode(False)
        self.source_row = -1

    def startDrag(self, supportedActions):
        """Stores the source row index when a drag operation begins."""
        self.source_row = self.currentRow()
        super().startDrag(supportedActions)

    def dropEvent(self, event):
        """Handles the drop event to reorder rows and emit the signal."""
        if not event.isAccepted() and event.source() == self:
            dest_row = self.indexAt(event.position().toPoint()).row()
            if dest_row < 0: dest_row = self.rowCount() - 1 # Handle drop outside rows
            
            # If the row has moved, emit the reordering signal.
            if self.source_row != dest_row:
                self.rows_reordered.emit(self.source_row, dest_row)
            
            event.accept()
        else:
            super().dropEvent(event)

class GlobalHotkeyListener(QThread):
    """A dedicated QThread to listen for keyboard events globally.
    This prevents the main UI from freezing while waiting for key presses.
    """
    hotkey_pressed = pyqtSignal(str) # Signal emitted when a hotkey is pressed.

    def __init__(self):
        super().__init__()
        self._is_running = True

    def run(self):
        """The main loop for the thread, using the 'keyboard' library's hook."""
        def on_key_event(event):
            # We only care about key down events to avoid double triggers.
            if event.event_type == keyboard.KEY_DOWN:
                self.hotkey_pressed.emit(event.name)
        
        keyboard.hook(on_key_event)
        # Keep the thread alive until explicitly stopped.
        while self._is_running:
            time.sleep(0.1)
        # Clean up the hook when the thread stops.
        keyboard.unhook(on_key_event)

    def stop(self):
        """Stops the thread's execution loop."""
        self._is_running = False

class MidiTestWorker(QThread):
    """A worker thread for testing MIDI clock output on a specific port."""
    finished = pyqtSignal(int)      # Emitted when the test is finished.
    error = pyqtSignal(str)         # Emitted if an error occurs.
    status_update = pyqtSignal(str) # Emitted for status messages.

    def __init__(self, port_num, bpm, send_start):
        super().__init__()
        self.port_num = port_num
        self.bpm = bpm
        self.send_start = send_start
        self._is_running = True
        self.midiout = None

    def stop(self):
        """Stops the test loop."""
        self._is_running = False

    def run(self):
        """Opens the MIDI port and sends clock signals at the specified BPM."""
        try:
            self.status_update.emit(f"Testing Port {self.port_num} at {self.bpm} BPM...")
            self.midiout = rtmidi.MidiOut()
            self.midiout.open_port(self.port_num)

            # Optionally send SPP and START messages at the beginning of the test.
            if self.send_start:
                self.midiout.send_message([SPP_BYTE, 0, 0]) # Song Position Pointer to start
                self.midiout.send_message([START_BYTE])

            # Calculate the interval between MIDI clock ticks (24 ticks per quarter note).
            tick_interval = 60.0 / self.bpm / 24.0
            next_tick = time.perf_counter()

            # Main test loop.
            while self._is_running:
                if time.perf_counter() >= next_tick:
                    self.midiout.send_message([CLOCK_BYTE])
                    next_tick += tick_interval
                time.sleep(0.001) # Small sleep to prevent pegging the CPU.

            self.status_update.emit(f"Test on Port {self.port_num} stopped.")

        except rtmidi._rtmidi.RtMidiError as e:
            self.error.emit(f"MIDI Error on port {self.port_num}: {e}")
        except Exception as e:
            self.error.emit(f"Test worker error: {e}")
        finally:
            # Ensure MIDI resources are cleaned up properly.
            if self.midiout and self.midiout.is_port_open():
                if self.send_start:
                    self.midiout.send_message([STOP_BYTE])
                self.midiout.close_port()
            self.finished.emit(self.port_num)

# ---------------------------------------------------------------------------
# Multi-zone zoom/crop configuration helpers
# ---------------------------------------------------------------------------

NUM_ZONES = 5
_ZONE_COLORS = ["#00e676", "#ff9800", "#2196f3", "#e040fb", "#ffeb3b"]  # Green, Orange, Blue, Purple, Yellow per zone


def _default_zone():
    """Return a default (disabled) zone configuration dictionary."""
    return {
        "enabled": False,
        "crop_x": 0, "crop_y": 0, "crop_w": 1920, "crop_h": 1080,
        "scale_w": -1, "scale_h": -1,
        "border_px": 0,
        "mode": "crop",
    }


def _migrate_zoom_config(cfg):
    """Return a guaranteed multi-zone config dict, migrating old single-zone format if needed."""
    if not cfg:
        zones = [_default_zone() for _ in range(NUM_ZONES)]
        zones[0]["enabled"] = True  # Enable zone 0 by default
        return {"zones": zones, "stack_direction": "horizontal"}
    if "zones" in cfg:
        zones = list(cfg["zones"])
        while len(zones) < NUM_ZONES:
            zones.append(_default_zone())
        # Ensure every existing zone has the newer fields
        for z in zones:
            z.setdefault("border_px", 0)
            z.setdefault("mode", "crop")
        return {
            "zones": zones[:NUM_ZONES],
            "stack_direction": cfg.get("stack_direction", "horizontal"),
            "frame_snapshot_path": cfg.get("frame_snapshot_path", ""),
        }
    # Old single-zone format — migrate to zone 0
    zone0 = {
        "enabled": cfg.get("enabled", True),
        "crop_x": cfg.get("crop_x", 0),
        "crop_y": cfg.get("crop_y", 0),
        "crop_w": cfg.get("crop_w", 1920),
        "crop_h": cfg.get("crop_h", 1080),
        "scale_w": cfg.get("scale_w", -1),
        "scale_h": cfg.get("scale_h", -1),
        "border_px": 0,
        "mode": "crop",
    }
    zones = [zone0] + [_default_zone() for _ in range(NUM_ZONES - 1)]
    return {"zones": zones, "stack_direction": "horizontal", "frame_snapshot_path": ""}


def _build_vf_for_zones(zoom_config):
    """Build the mpv --vf string for a multi-zone config. Returns None if no transform needed.

    If *zoom_config* is empty ({}), or contains no enabled zones with a crop region,
    returns None so mpv plays without any video filter.
    """
    # An empty dict means "never configured" — apply no filter
    if not zoom_config:
        return None
    # For old single-zone format, only apply if 'enabled' is set
    if "zones" not in zoom_config:
        if not zoom_config.get("enabled"):
            return None
    migrated = _migrate_zoom_config(zoom_config)
    zones = migrated.get("zones", [])
    direction = migrated.get("stack_direction", "horizontal")
    enabled = [z for z in zones if z.get("enabled") and z.get("crop_w", 0) > 0]
    if not enabled:
        return None

    def _zone_vf(z):
        vf = f"crop={z['crop_w']}:{z['crop_h']}:{z['crop_x']}:{z['crop_y']}"
        sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
        if sw > 0 and sh > 0:
            vf += f",scale={sw}:{sh}"
        border = z.get("border_px", 0)
        if border > 0:
            vf += f",pad=iw+{2*border}:ih+{2*border}:{border}:{border}:black"
        return vf

    def _zone_out_size(z):
        """Return the (width, height) of a zone after crop + optional scale + border."""
        sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
        w = sw if sw > 0 else z["crop_w"]
        h = sh if sh > 0 else z["crop_h"]
        border = z.get("border_px", 0)
        return w + 2 * border, h + 2 * border

    # setsar=1 is appended to every filter graph so that mpv uses the composite's
    # own pixel dimensions for display-aspect-ratio calculations, rather than
    # inheriting the SAR from the source video.  Without this, a source whose
    # metadata encodes a non-square SAR (e.g. anamorphic or display-aspect
    # overrides) causes the stitched composite to be vertically squashed or
    # stretched when rendered fullscreen instead of being letterboxed correctly.
    if len(enabled) == 1:
        # Wrap in lavfi so setsar=1 is applied inside the same graph.
        return f"lavfi=[{_zone_vf(enabled[0])},setsar=1]"

    # Multiple zones: use lavfi split + per-zone crop/scale + hstack/vstack.
    n = len(enabled)
    zone_sizes = [_zone_out_size(z) for z in enabled]

    # hstack requires all inputs to share the same height; vstack requires the
    # same width.  Compute the maximum dimension and pad shorter zones so that
    # the stack filter never sees mismatched stream sizes (which would either
    # error or silently truncate the composite).
    if direction == "horizontal":
        target_h = max(s[1] for s in zone_sizes)
    else:
        target_w = max(s[0] for s in zone_sizes)

    split_tags = "".join(f"[z{i}]" for i in range(n))
    split_part = f"split={n}{split_tags}"

    def _zone_segment(z, size, i):
        vf_str = _zone_vf(z)
        out_w, out_h = size
        if direction == "horizontal" and out_h < target_h:
            # Pad height to target_h with black at the bottom.
            vf_str += f",pad=iw:{target_h}:0:0:black"
        elif direction == "vertical" and out_w < target_w:
            # Pad width to target_w with black on the right.
            vf_str += f",pad={target_w}:ih:0:0:black"
        return f"[z{i}]{vf_str}[c{i}]"

    crop_parts = [_zone_segment(z, zone_sizes[i], i) for i, z in enumerate(enabled)]
    stack_inputs = "".join(f"[c{i}]" for i in range(n))
    stack_fn = "vstack" if direction == "vertical" else "hstack"
    # setsar=1 after the stack forces the composite's pixel dimensions to be
    # used as-is, matching the preview display and preventing squashing.
    stack_part = f"{stack_inputs}{stack_fn}=inputs={n},setsar=1"
    graph = ";".join([split_part] + crop_parts + [stack_part])
    return f"lavfi=[{graph}]"


class MidiSyncWorker(QThread):
    """The main worker thread for handling synchronized mpv playback and MIDI clock output."""
    finished = pyqtSignal()          # Emitted when playback is finished.
    error = pyqtSignal(str)          # Emitted on error.
    status_update = pyqtSignal(str)  # For status messages.
    ipc_socket_path = pyqtSignal(str)# Emits the path to the mpv IPC socket.

    def __init__(self, video_file, bpm, display_num, preload_time, midi_offset_ms, 
                 send_start_port1, send_start_port2, send_start_port3, timing_method,
                 require_midi=True, max_duration_sec=0, zoom_config=None):
        super().__init__()
        # Store all playback parameters.
        self.video_file = video_file
        self.bpm = bpm
        self.display_num = display_num
        self.preload_time = preload_time
        self.midi_offset_ms = midi_offset_ms
        self.send_start_port1 = send_start_port1
        self.send_start_port2 = send_start_port2
        self.send_start_port3 = send_start_port3
        self.timing_method = timing_method
        self.require_midi = require_midi
        self.max_duration_sec = max_duration_sec  # If > 0, limits playback via mpv --length
        self.zoom_config = zoom_config or {}
        self.mpv_process = None
        self._is_running = True
        self.midi_outputs = {}

    def stop(self):
        """Stops the playback loop."""
        self._is_running = False

    def run(self):
        """Initializes MIDI ports and selects the timing method to run."""
        # --- Pre-flight checks ---
        if not os.path.exists(MPV_PATH):
            self.error.emit(f"mpv not found at '{MPV_PATH}'")
            return
        if not os.path.exists(self.video_file):
            self.error.emit(f"File not found: '{self.video_file}'")
            return
        
        # --- Open MIDI ports (best-effort) ---
        all_ports = [1, 2, 3]
        for port_num in all_ports:
            try:
                midiout = rtmidi.MidiOut()
                midiout.open_port(port_num)
                self.midi_outputs[port_num] = midiout
            except rtmidi._rtmidi.RtMidiError as e:
                self.status_update.emit(f"Warning: MIDI port {port_num} unavailable: {e}")

        if self.midi_outputs:
            self.status_update.emit(f"MIDI ports opened: {list(self.midi_outputs.keys())}")
        elif self.require_midi:
            self.error.emit("No MIDI ports available. Check connections.")
            return
        else:
            self.status_update.emit("Warning: No MIDI ports available. Playing without MIDI.")

        # --- Select and run the appropriate timing logic ---
        if self.timing_method == 'high_precision':
            self.run_high_precision()
        else:
            self.run_standard()
            
    def _run_logic(self, is_high_precision):
        """The core logic for MIDI sync, shared by both timing methods."""
        # Create a unique IPC socket name for this mpv instance.
        socket_name = f"mpv_socket_{int(time.time())}"
        full_socket_path = fr'\\.\pipe\{socket_name}'
        # Construct the command to launch mpv with specific settings.
        file_ext = os.path.splitext(self.video_file)[1].lower()
        is_audio_only = file_ext == '.wav'

        if is_audio_only:
            # Audio-only: no video window needed
            mpv_cmd = [
                MPV_PATH,
                f"--input-ipc-server={full_socket_path}",
                "--pause",
                "--no-video",
                "--really-quiet",
                "--keep-open=no",
                self.video_file
            ]
        else:
            # Video file: full screen on selected display
            mpv_cmd = [
                MPV_PATH,
                f"--input-ipc-server={full_socket_path}",
                "--pause",
                "--fullscreen",
                f"--fs-screen={self.display_num}",
                "--no-osd-bar",
                "--no-osc",
                "--no-input-default-bindings",
                "--no-border",
                "--really-quiet",
                "--video-sync=audio",
                "--keep-open=no",
                self.video_file
            ]
        # If a maximum duration is set (e.g. for calibration loops), limit playback via mpv.
        if self.max_duration_sec > 0:
            mpv_cmd.insert(-1, f"--length={self.max_duration_sec}")
        # If a zoom/crop/scale transform is configured, apply it as an mpv video filter.
        if not is_audio_only:
            vf_str = _build_vf_for_zones(self.zoom_config)
            if vf_str:
                mpv_cmd.insert(-1, f"--vf={vf_str}")
        
        try:
            # --- Pre-roll Phase ---
            # Send MIDI clock for a specified duration before starting video.
            self.status_update.emit(f"Pre-rolling MIDI clock for {self.preload_time}s at {self.bpm} BPM...")
            tick_interval = 60.0 / self.bpm / 24.0
            start_time = time.perf_counter()
            pre_roll_end_time = start_time + self.preload_time
            # Calculate when to launch mpv so it's ready exactly when pre-roll ends.
            mpv_launch_time = pre_roll_end_time - MPV_LAUNCH_HEAD_START_SECONDS
            mpv_launched = False

            while time.perf_counter() < pre_roll_end_time and self._is_running:
                current_time = time.perf_counter()
                
                # Launch mpv just-in-time.
                if not mpv_launched and current_time >= mpv_launch_time:
                    self.status_update.emit(f"Starting mpv on screen {self.display_num}...")
                    self.mpv_process = subprocess.Popen(mpv_cmd)
                    self.ipc_socket_path.emit(full_socket_path)
                    mpv_launched = True

                # Error check: if mpv closes unexpectedly, abort.
                if self.mpv_process and self.mpv_process.poll() is not None:
                    raise InterruptedError("mpv closed prematurely during pre-roll")

                # Send clock ticks to all open MIDI ports.
                for midiout in self.midi_outputs.values():
                    midiout.send_message([CLOCK_BYTE])
                
                time.sleep(0.01) # Yield CPU time.

            if not self._is_running:
                raise InterruptedError("Playback stopped by user during pre-roll")
            if not self.mpv_process:
                raise RuntimeError("mpv process was not launched in time.")

            # --- Atomic Start Event ---
            # This section ensures that MIDI start and video unpause are offset correctly.
            self.status_update.emit("Sending START...")
            offset_sec = self.midi_offset_ms / 1000.0
            start_time_base = 0
            is_sending_any_start = self.send_start_port1 or self.send_start_port2 or self.send_start_port3

            def send_atomic_start():
                """Sends MIDI START messages to the selected ports."""
                nonlocal start_time_base
                ports_to_start = [p for p, should_send in [(1, self.send_start_port1), (2, self.send_start_port2), (3, self.send_start_port3)] if should_send]
                
                for port_num in ports_to_start:
                    if port_num in self.midi_outputs:
                        self.midi_outputs[port_num].send_message([SPP_BYTE, 0, 0])
                        self.midi_outputs[port_num].send_message([START_BYTE])

                # Send one final clock tick with the start message for tight sync.
                for midiout in self.midi_outputs.values():
                    midiout.send_message([CLOCK_BYTE])
                start_time_base = time.perf_counter()
            
            def unpause_video():
                """Unpauses the mpv instance via its IPC socket."""
                nonlocal start_time_base
                with open(full_socket_path, "w", encoding='utf-8') as ipc:
                    ipc.write('{ "command": ["set_property", "pause", false] }\n')
                if not is_sending_any_start: 
                    start_time_base = time.perf_counter()

            # Apply the MIDI offset.
            if is_sending_any_start:
                if offset_sec > 0: # Video starts before MIDI
                    unpause_video()
                    time.sleep(offset_sec)
                    send_atomic_start()
                else: # MIDI starts before or at the same time as Video
                    send_atomic_start()
                    time.sleep(abs(offset_sec))
                    unpause_video()
            else: # Not sending MIDI start, just unpause video
                unpause_video()
            
            # --- Main Clock Loop ---
            # This loop sends MIDI clock ticks synchronized with the video playback.
            next_tick = start_time_base + tick_interval
            self.status_update.emit(f"PLAYING: {os.path.basename(self.video_file)}")
            while self.mpv_process.poll() is None and self._is_running:
                # High-precision timing uses a busy-wait loop for maximum accuracy.
                if is_high_precision:
                    while time.perf_counter() < next_tick:
                        pass # Spin until it's time for the next tick.
                # Standard timing uses sleep, which is less CPU intensive but less accurate.
                else:
                    sleep_time = next_tick - time.perf_counter()
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                for midiout in self.midi_outputs.values():
                    midiout.send_message([CLOCK_BYTE])
                next_tick += tick_interval
            
            if self._is_running:
                self.status_update.emit("mpv closed. Stopping.")
            else:
                self.status_update.emit("Playback stopped by user.")

        except Exception as e:
            self.error.emit(f"Runtime error ({'High-Precision' if is_high_precision else 'Standard'}): {e}")
        finally:
            self.cleanup()

    def run_standard(self):
        """Runs the main sync logic with standard timing."""
        self._run_logic(is_high_precision=False)

    def run_high_precision(self):
        """Runs the main sync logic with high-precision timing."""
        # Request higher timer resolution from Windows.
        winmm.timeBeginPeriod(1)
        self._run_logic(is_high_precision=True)
        # Release the higher timer resolution.
        winmm.timeEndPeriod(1)

    def cleanup(self):
        """Cleans up all resources (MIDI ports, mpv process)."""
        self.status_update.emit("Cleaning up...")
        ports_to_stop = [p for p, should_send in [(1, self.send_start_port1), (2, self.send_start_port2), (3, self.send_start_port3)] if should_send]
        
        for port_num in ports_to_stop:
            if port_num in self.midi_outputs and self.midi_outputs[port_num].is_port_open():
                self.midi_outputs[port_num].send_message([STOP_BYTE])

        for out in self.midi_outputs.values():
            out.close_port()
        if self.mpv_process and self.mpv_process.poll() is None:
            self.mpv_process.terminate()
        self.finished.emit()

class ZoomCropCanvas(QWidget):
    """A canvas widget for visually defining a crop region on a captured video frame.
    
    The user can drag to create a new selection, move the selection,
    or resize it by dragging the corner/edge handles. Pixel coordinates
    are reported live via the region_changed signal.
    """
    region_changed = pyqtSignal(int, int, int, int)  # x, y, w, h in source pixels
    handle_dragged = pyqtSignal(str, int, int)        # drag_mode, abs_x, abs_y

    HANDLE_SIZE = 9  # Half-size of resize handles in canvas pixels

    def __init__(self, color="#00e676", parent=None):
        super().__init__(parent)
        self.selection_color = color  # Colour used for border and handles
        self.pixmap = None
        self.scale_factor = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.source_w = 0
        self.source_h = 0

        # Selection rectangle in source-pixel coordinates
        self._sel = QRect()
        self._drag_start = None
        self._drag_mode = None
        self._drag_orig_rect = QRect()
        self._drag_handle_pos = None  # (mode, src_x, src_y) while dragging

        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_frame(self, image_path):
        """Load a video frame image from *image_path* and display it."""
        pm = QPixmap(image_path)
        if pm.isNull():
            return
        self.pixmap = pm
        self.source_w = pm.width()
        self.source_h = pm.height()
        if self._sel.isNull():
            self._sel = QRect(0, 0, self.source_w, self.source_h)
        self._update_transform()
        self.update()

    def set_region(self, x, y, w, h):
        """Set the selection region in source-pixel coordinates."""
        self._sel = QRect(x, y, max(1, w), max(1, h))
        self.update()
        self.region_changed.emit(self._sel.x(), self._sel.y(),
                                 self._sel.width(), self._sel.height())

    def get_region(self):
        """Return (x, y, w, h) of the selection in source-pixel coordinates."""
        return self._sel.x(), self._sel.y(), self._sel.width(), self._sel.height()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _update_transform(self):
        if not self.pixmap:
            return
        sx = self.width() / max(1, self.source_w)
        sy = self.height() / max(1, self.source_h)
        self.scale_factor = min(sx, sy)
        self.offset_x = (self.width() - self.source_w * self.scale_factor) / 2.0
        self.offset_y = (self.height() - self.source_h * self.scale_factor) / 2.0

    def _to_canvas(self, sx, sy):
        return QPoint(int(sx * self.scale_factor + self.offset_x),
                      int(sy * self.scale_factor + self.offset_y))

    def _to_source(self, cx, cy):
        sx = (cx - self.offset_x) / max(1e-6, self.scale_factor)
        sy = (cy - self.offset_y) / max(1e-6, self.scale_factor)
        return int(sx), int(sy)

    def _sel_canvas(self):
        """Return the selection rect in canvas coordinates."""
        if self._sel.isNull():
            return QRect()
        tl = self._to_canvas(self._sel.left(), self._sel.top())
        br = self._to_canvas(self._sel.right(), self._sel.bottom())
        return QRect(tl, br)

    def _handle_rects(self):
        """Return list of (QRect, name) for the eight resize handles."""
        cr = self._sel_canvas()
        if cr.isNull():
            return []
        h = self.HANDLE_SIZE
        cx, cy = cr.center().x(), cr.center().y()
        points = [
            (cr.left(),   cr.top(),    'tl'),
            (cr.right(),  cr.top(),    'tr'),
            (cr.left(),   cr.bottom(), 'bl'),
            (cr.right(),  cr.bottom(), 'br'),
            (cx,          cr.top(),    't'),
            (cx,          cr.bottom(), 'b'),
            (cr.left(),   cy,          'l'),
            (cr.right(),  cy,          'r'),
        ]
        return [(QRect(px - h, py - h, h * 2, h * 2), name)
                for px, py, name in points]

    def _hit_mode(self, pos):
        """Return the drag mode string based on where *pos* lands."""
        cr = self._sel_canvas()
        for rect, name in self._handle_rects():
            if rect.contains(pos):
                return f'resize_{name}'
        if not cr.isNull() and cr.contains(pos):
            return 'move'
        return 'new'

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        if not self.pixmap:
            painter.setPen(QColor("#555"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Load a video and click 'Capture Frame'")
            return

        # Draw scaled video frame
        dest_w = int(self.source_w * self.scale_factor)
        dest_h = int(self.source_h * self.scale_factor)
        dest_rect = QRect(int(self.offset_x), int(self.offset_y), dest_w, dest_h)
        painter.drawPixmap(dest_rect, self.pixmap)

        cr = self._sel_canvas()
        if not cr.isNull():
            # Semi-transparent dark overlay outside the selection
            painter.setBrush(QBrush(QColor(0, 0, 0, 120)))
            painter.setPen(Qt.PenStyle.NoPen)
            # top strip
            painter.drawRect(dest_rect.left(), dest_rect.top(),
                             dest_rect.width(), cr.top() - dest_rect.top())
            # bottom strip
            painter.drawRect(dest_rect.left(), cr.bottom(),
                             dest_rect.width(), dest_rect.bottom() - cr.bottom())
            # left strip
            painter.drawRect(dest_rect.left(), cr.top(),
                             cr.left() - dest_rect.left(), cr.height())
            # right strip
            painter.drawRect(cr.right(), cr.top(),
                             dest_rect.right() - cr.right(), cr.height())

            # Selection border
            painter.setPen(QPen(QColor(self.selection_color), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(cr)

            # Resize handles
            painter.setPen(QPen(QColor(self.selection_color), 1))
            painter.setBrush(QBrush(QColor(self.selection_color)))
            for rect, _ in self._handle_rects():
                painter.drawRect(rect)

        # Coordinate overlay while a handle is being dragged
        if self._drag_handle_pos:
            mode, src_x, src_y = self._drag_handle_pos
            vertical_modes = ('resize_t', 'resize_b',
                              'resize_tl', 'resize_tr',
                              'resize_bl', 'resize_br')
            if mode in vertical_modes and self.source_h > 0:
                y_from_bottom = self.source_h - src_y - 1
                coord_text = f"X:{src_x}  Y:{src_y}  (↑{y_from_bottom} from bottom)"
            else:
                coord_text = f"X:{src_x}  Y:{src_y}"
            canvas_pos = self._to_canvas(src_x, src_y)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(coord_text) + 10
            th = fm.height() + 6
            tx = canvas_pos.x() + 15
            ty = canvas_pos.y() - th // 2
            # Keep the tooltip within the canvas area
            tx = max(2, min(self.width() - tw - 2, tx))
            ty = max(2, min(self.height() - th - 2, ty))
            painter.fillRect(tx, ty, tw, th, QColor(0, 0, 0, 200))
            painter.setPen(QColor(self.selection_color))
            painter.drawText(tx + 5, ty + th - 4, coord_text)

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.pixmap:
            return
        self._drag_start = event.pos()
        self._drag_mode = self._hit_mode(event.pos())
        self._drag_orig_rect = QRect(self._sel)

    def mouseMoveEvent(self, event):
        if not self.pixmap:
            return

        # Update cursor
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            mode = self._hit_mode(event.pos())
            cursors = {
                'move': Qt.CursorShape.SizeAllCursor,
                'resize_tl': Qt.CursorShape.SizeFDiagCursor,
                'resize_br': Qt.CursorShape.SizeFDiagCursor,
                'resize_tr': Qt.CursorShape.SizeBDiagCursor,
                'resize_bl': Qt.CursorShape.SizeBDiagCursor,
                'resize_t': Qt.CursorShape.SizeVerCursor,
                'resize_b': Qt.CursorShape.SizeVerCursor,
                'resize_l': Qt.CursorShape.SizeHorCursor,
                'resize_r': Qt.CursorShape.SizeHorCursor,
            }
            self.setCursor(cursors.get(mode, Qt.CursorShape.CrossCursor))
            return

        if not self._drag_start:
            return

        # Delta in source pixels
        dx_c = event.pos().x() - self._drag_start.x()
        dy_c = event.pos().y() - self._drag_start.y()
        dx_s = int(dx_c / max(1e-6, self.scale_factor))
        dy_s = int(dy_c / max(1e-6, self.scale_factor))

        r = QRect(self._drag_orig_rect)

        if self._drag_mode == 'move':
            r.translate(dx_s, dy_s)
        elif self._drag_mode == 'new':
            sx0, sy0 = self._to_source(self._drag_start.x(), self._drag_start.y())
            sx1, sy1 = self._to_source(event.pos().x(), event.pos().y())
            r = QRect(min(sx0, sx1), min(sy0, sy1),
                      abs(sx1 - sx0), abs(sy1 - sy0))
        elif self._drag_mode == 'resize_tl':
            r.setTopLeft(r.topLeft() + QPoint(dx_s, dy_s))
        elif self._drag_mode == 'resize_tr':
            r.setTopRight(r.topRight() + QPoint(dx_s, dy_s))
        elif self._drag_mode == 'resize_bl':
            r.setBottomLeft(r.bottomLeft() + QPoint(dx_s, dy_s))
        elif self._drag_mode == 'resize_br':
            r.setBottomRight(r.bottomRight() + QPoint(dx_s, dy_s))
        elif self._drag_mode == 'resize_t':
            r.setTop(r.top() + dy_s)
        elif self._drag_mode == 'resize_b':
            r.setBottom(r.bottom() + dy_s)
        elif self._drag_mode == 'resize_l':
            r.setLeft(r.left() + dx_s)
        elif self._drag_mode == 'resize_r':
            r.setRight(r.right() + dx_s)

        r = r.normalized()
        # Hard-clamp to source image bounds — no handle can escape the frame
        r.setLeft(max(0, r.left()))
        r.setTop(max(0, r.top()))
        r.setRight(min(self.source_w - 1, r.right()))
        r.setBottom(min(self.source_h - 1, r.bottom()))
        if r.width() < 1:
            r.setWidth(1)
        if r.height() < 1:
            r.setHeight(1)

        self._sel = r

        # Determine the active handle position in source coordinates and emit
        cx_s = self._sel.center().x()
        cy_s = self._sel.center().y()
        _pos_map = {
            'move':      (self._sel.left(), self._sel.top()),
            'new':       (self._sel.right(), self._sel.bottom()),
            'resize_tl': (self._sel.left(),  self._sel.top()),
            'resize_tr': (self._sel.right(), self._sel.top()),
            'resize_bl': (self._sel.left(),  self._sel.bottom()),
            'resize_br': (self._sel.right(), self._sel.bottom()),
            'resize_t':  (cx_s,              self._sel.top()),
            'resize_b':  (cx_s,              self._sel.bottom()),
            'resize_l':  (self._sel.left(),  cy_s),
            'resize_r':  (self._sel.right(), cy_s),
        }
        hx, hy = _pos_map.get(self._drag_mode, (cx_s, cy_s))
        self._drag_handle_pos = (self._drag_mode, hx, hy)
        self.handle_dragged.emit(self._drag_mode, hx, hy)

        self.update()
        self.region_changed.emit(r.x(), r.y(), r.width(), r.height())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self._drag_mode = None
            self._drag_handle_pos = None
            self.handle_dragged.emit("", 0, 0)
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_transform()
        self.update()


class ZoomScaleDialog(QDialog):
    """Edit-mode dialog for configuring video crop/scale for mpv playback.

    Workflow:
    1. Select a test video  →  mpv opens in a separate windowed preview.
    2. Use Play/Pause to navigate to the desired frame.
    3. Click 'Capture Frame' to snapshot the frame into the canvas.
    4. Drag / resize the green selection rectangle to define the crop region.
    5. Optionally enter output scale dimensions (for non-uniform stretch).
    6. Click OK to persist the settings.
    """

    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Video Zoom / Scale Configuration (Edit Mode)")
        self.setModal(True)
        self.resize(1100, 720)

        self._current_config = dict(current_config)
        self.result_config = None

        # mpv state
        self._mpv_process = None
        self._ipc_path = None
        self._temp_dir = tempfile.mkdtemp(prefix="lc_zoom_")
        self._frame_path = os.path.join(self._temp_dir, "frame.png")

        self._updating_spinboxes = False  # Guard for circular signal updates

        self._setup_ui()
        self._apply_config(current_config)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # --- Video file and playback controls ---
        file_bar = QHBoxLayout()
        self._select_btn = QPushButton("Select Video…")
        self._select_btn.clicked.connect(self._select_video)
        self._video_label = QLabel("No video selected.")
        self._video_label.setStyleSheet("font-style: italic; color: #888;")

        self._play_btn = QPushButton("▶  Play")
        self._play_btn.clicked.connect(self._play)
        self._pause_btn = QPushButton("⏸  Pause / Freeze")
        self._pause_btn.clicked.connect(self._pause)
        self._capture_btn = QPushButton("📷  Capture Frame  →")
        self._capture_btn.setStyleSheet("background-color: #007acc; color: white; font-weight: bold; padding: 4px 8px;")
        self._capture_btn.clicked.connect(self._capture_frame)
        self._capture_btn.setToolTip(
            "Pause the mpv preview and snapshot the current frame into the canvas.\n"
            "Then drag the green rectangle to define your crop region."
        )

        for btn in (self._play_btn, self._pause_btn, self._capture_btn):
            btn.setEnabled(False)

        file_bar.addWidget(self._select_btn)
        file_bar.addWidget(self._video_label, 1)
        file_bar.addWidget(self._play_btn)
        file_bar.addWidget(self._pause_btn)
        file_bar.addWidget(self._capture_btn)
        root.addLayout(file_bar)

        # --- Canvas + right panel ---
        body = QHBoxLayout()
        body.setSpacing(8)

        self._canvas = ZoomCropCanvas()
        self._canvas.region_changed.connect(self._on_region_changed)
        self._canvas.handle_dragged.connect(self._on_handle_dragged)
        body.addWidget(self._canvas, 3)

        right = QVBoxLayout()
        right.setSpacing(6)

        # Crop region spinboxes
        crop_group = QGroupBox("Source Crop Region")
        crop_grid = QGridLayout()
        crop_grid.setSpacing(4)

        self._x_sb = QSpinBox(); self._x_sb.setRange(0, 99999); self._x_sb.setSuffix(" px")
        self._y_sb = QSpinBox(); self._y_sb.setRange(0, 99999); self._y_sb.setSuffix(" px")
        self._w_sb = QSpinBox(); self._w_sb.setRange(1, 99999); self._w_sb.setSuffix(" px")
        self._h_sb = QSpinBox(); self._h_sb.setRange(1, 99999); self._h_sb.setSuffix(" px")

        for sb in (self._x_sb, self._y_sb, self._w_sb, self._h_sb):
            sb.setFixedWidth(110)
            sb.valueChanged.connect(self._on_spinbox_changed)

        crop_grid.addWidget(QLabel("X:"), 0, 0)
        crop_grid.addWidget(self._x_sb, 0, 1)
        crop_grid.addWidget(QLabel("Y:"), 1, 0)
        crop_grid.addWidget(self._y_sb, 1, 1)
        crop_grid.addWidget(QLabel("Width:"), 2, 0)
        crop_grid.addWidget(self._w_sb, 2, 1)
        crop_grid.addWidget(QLabel("Height:"), 3, 0)
        crop_grid.addWidget(self._h_sb, 3, 1)
        crop_group.setLayout(crop_grid)

        # Output scale spinboxes
        scale_group = QGroupBox("Output Scale (optional stretch)")
        scale_group.setToolTip(
            "Leave at -1 (auto) to let mpv fill the screen while preserving aspect ratio.\n"
            "Set explicit pixel dimensions to force non-uniform stretching."
        )
        scale_grid = QGridLayout()
        scale_grid.setSpacing(4)

        self._sw_sb = QSpinBox()
        self._sw_sb.setRange(-1, 99999)
        self._sw_sb.setSpecialValueText("auto")
        self._sw_sb.setSuffix(" px")
        self._sw_sb.setFixedWidth(110)

        self._sh_sb = QSpinBox()
        self._sh_sb.setRange(-1, 99999)
        self._sh_sb.setSpecialValueText("auto")
        self._sh_sb.setSuffix(" px")
        self._sh_sb.setFixedWidth(110)

        scale_grid.addWidget(QLabel("Scale W:"), 0, 0)
        scale_grid.addWidget(self._sw_sb, 0, 1)
        scale_grid.addWidget(QLabel("Scale H:"), 1, 0)
        scale_grid.addWidget(self._sh_sb, 1, 1)
        scale_group.setLayout(scale_grid)

        # Reset button
        self._reset_btn = QPushButton("Reset Selection to Full Frame")
        self._reset_btn.clicked.connect(self._reset_selection)

        # Enable checkbox
        self._enable_cb = QCheckBox("Enable crop/scale during playback")
        self._enable_cb.setChecked(True)

        # OK / Cancel
        btn_row = QHBoxLayout()
        self._ok_btn = QPushButton("✔  OK — Save Settings")
        self._ok_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 6px;")
        self._ok_btn.clicked.connect(self._ok)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(self._cancel_btn)

        right.addWidget(crop_group)
        right.addWidget(scale_group)
        right.addWidget(self._reset_btn)
        right.addStretch()
        right.addWidget(self._enable_cb)
        right.addLayout(btn_row)

        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # Status bar
        self._status = QLabel("Select a video to begin, or adjust the values directly.")
        self._status.setStyleSheet("font-style: italic; color: #888; font-size: 12px;")
        root.addWidget(self._status)

        # Live coordinate readout during handle drag
        self._coord_label = QLabel("")
        self._coord_label.setStyleSheet(
            "font-size: 11px; color: #00e676; font-family: monospace; "
            "background-color: #1a1a2e; padding: 2px 6px; border-radius: 3px;"
        )
        self._coord_label.setVisible(False)
        root.addWidget(self._coord_label)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _apply_config(self, cfg):
        self._updating_spinboxes = True
        self._x_sb.setValue(cfg.get('crop_x', 0))
        self._y_sb.setValue(cfg.get('crop_y', 0))
        self._w_sb.setValue(max(1, cfg.get('crop_w', 1920)))
        self._h_sb.setValue(max(1, cfg.get('crop_h', 1080)))
        self._sw_sb.setValue(cfg.get('scale_w', -1))
        self._sh_sb.setValue(cfg.get('scale_h', -1))
        self._enable_cb.setChecked(cfg.get('enabled', True))
        self._updating_spinboxes = False
        self._canvas.set_region(
            cfg.get('crop_x', 0), cfg.get('crop_y', 0),
            max(1, cfg.get('crop_w', 1920)), max(1, cfg.get('crop_h', 1080)),
        )

    # ------------------------------------------------------------------
    # Video / mpv control
    # ------------------------------------------------------------------

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Test Video", "d:\\",
            "Media Files (*.mov *.mp4 *.avi *.mkv *.wmv *.m4v);;All Files (*)"
        )
        if not path:
            return
        self._video_label.setText(os.path.basename(path))
        self._video_label.setStyleSheet("color: #d4d4d4;")
        self._launch_mpv(path)

    def _launch_mpv(self, video_path):
        self._stop_mpv()
        socket_name = f"mpv_zoom_{int(time.time())}"
        self._ipc_path = fr'\\.\pipe\{socket_name}'
        cmd = [
            MPV_PATH,
            f"--input-ipc-server={self._ipc_path}",
            "--pause",
            "--no-fullscreen",
            "--geometry=800x600",
            "--title=Zoom/Scale Preview — navigate then click Capture Frame",
            "--no-osd-bar",
            "--no-osc",
            "--no-input-default-bindings",
            "--loop-file=inf",
            "--really-quiet",
            video_path,
        ]
        try:
            self._mpv_process = subprocess.Popen(cmd)
            for btn in (self._play_btn, self._pause_btn, self._capture_btn):
                btn.setEnabled(True)
            self._status.setText("mpv opened. Navigate to the desired frame, then click 'Capture Frame'.")
        except Exception as exc:
            self._status.setText(f"Error launching mpv: {exc}")

    def _send_ipc(self, json_str):
        if not self._ipc_path:
            return
        try:
            with open(self._ipc_path, "w", encoding="utf-8") as f:
                f.write(json_str + "\n")
        except Exception as exc:
            self._status.setText(f"IPC error: {exc}")

    def _play(self):
        self._send_ipc('{ "command": ["set_property", "pause", false] }')

    def _pause(self):
        self._send_ipc('{ "command": ["set_property", "pause", true] }')

    def _capture_frame(self):
        """Pause the preview and schedule a frame capture after a short delay."""
        self._pause()
        QTimer.singleShot(350, self._do_capture)

    def _do_capture(self):
        # mpv uses forward slashes in screenshot-to-file path
        safe_path = self._frame_path.replace("\\", "/")
        self._send_ipc(f'{{ "command": ["screenshot-to-file", "{safe_path}", "video"] }}')
        QTimer.singleShot(600, self._load_frame)

    def _load_frame(self):
        if not os.path.exists(self._frame_path):
            self._status.setText("Frame capture failed — is mpv still running?")
            return
        self._canvas.load_frame(self._frame_path)
        x, y, w, h = self._canvas.get_region()
        self._on_region_changed(x, y, w, h)
        self._status.setText(
            f"Frame captured ({self._canvas.source_w} × {self._canvas.source_h} px). "
            "Drag the green rectangle to set the crop region."
        )

    def _stop_mpv(self):
        if self._mpv_process and self._mpv_process.poll() is None:
            if self._ipc_path:
                try:
                    with open(self._ipc_path, "w", encoding="utf-8") as f:
                        f.write('{ "command": ["quit"] }\n')
                    time.sleep(0.2)
                except Exception:
                    pass
            self._mpv_process.terminate()
        self._mpv_process = None
        self._ipc_path = None

    # ------------------------------------------------------------------
    # Region synchronisation
    # ------------------------------------------------------------------

    def _on_region_changed(self, x, y, w, h):
        """Called when the canvas selection changes — update spinboxes."""
        self._updating_spinboxes = True
        self._x_sb.setValue(x)
        self._y_sb.setValue(y)
        self._w_sb.setValue(max(1, w))
        self._h_sb.setValue(max(1, h))
        self._updating_spinboxes = False

    def _on_handle_dragged(self, mode, abs_x, abs_y):
        """Update live coordinate readout while dragging a crop handle."""
        if not mode:
            self._coord_label.setVisible(False)
            self._coord_label.setText("")
            return
        vertical_modes = ('resize_t', 'resize_b',
                          'resize_tl', 'resize_tr',
                          'resize_bl', 'resize_br')
        if mode in vertical_modes and self._canvas.source_h > 0:
            y_from_bottom = self._canvas.source_h - abs_y - 1
            text = (f"  Handle: {mode}   X: {abs_x} px   Y: {abs_y} px"
                    f"   (Y from bottom: {y_from_bottom} px)")
        else:
            text = f"  Handle: {mode}   X: {abs_x} px   Y: {abs_y} px"
        self._coord_label.setText(text)
        self._coord_label.setVisible(True)

    def _on_spinbox_changed(self):
        """Called when a spinbox changes — update the canvas."""
        if self._updating_spinboxes:
            return
        self._canvas.set_region(
            self._x_sb.value(), self._y_sb.value(),
            self._w_sb.value(), self._h_sb.value(),
        )

    def _reset_selection(self):
        """Reset selection to the full captured frame (or 1920×1080 default)."""
        w = self._canvas.source_w or 1920
        h = self._canvas.source_h or 1080
        self._canvas.set_region(0, 0, w, h)
        self._on_region_changed(0, 0, w, h)

    # ------------------------------------------------------------------
    # Dialog accept / reject
    # ------------------------------------------------------------------

    def _ok(self):
        self.result_config = {
            'enabled': self._enable_cb.isChecked(),
            'crop_x': self._x_sb.value(),
            'crop_y': self._y_sb.value(),
            'crop_w': self._w_sb.value(),
            'crop_h': self._h_sb.value(),
            'scale_w': self._sw_sb.value(),
            'scale_h': self._sh_sb.value(),
        }
        self._stop_mpv()
        self.accept()

    def _cancel(self):
        self._stop_mpv()
        self.reject()

    def closeEvent(self, event):
        self._stop_mpv()
        try:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        except Exception:
            pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# StretchCanvas — shows a cropped sub-image with draggable output-size handles
# ---------------------------------------------------------------------------

class StretchCanvas(QWidget):
    """Canvas that displays a cropped region and lets the user resize output dimensions.

    In stretch/scale edit mode the user sees the cropped sub-image drawn at the
    *current output size* (potentially distorted) and can drag the right/bottom/
    corner handles to change the scale_w × scale_h values.
    """

    output_changed = pyqtSignal(int, int)  # scale_w, scale_h
    HANDLE_SIZE = 9

    def __init__(self, color="#ff9800", parent=None):
        super().__init__(parent)
        self._color = color
        self._full_pixmap = None   # Full captured frame
        self._cropped_pm = None    # Cropped sub-image
        self._crop_w = 1920
        self._crop_h = 1080
        self._out_w = 1920
        self._out_h = 1080
        self._drag_mode = None
        self._drag_start = None
        self._drag_orig = (0, 0)
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_source(self, full_pixmap, crop_x, crop_y, crop_w, crop_h):
        """Update the displayed pixmap to the given crop region of full_pixmap."""
        self._full_pixmap = full_pixmap
        self._crop_w = max(1, crop_w)
        self._crop_h = max(1, crop_h)
        if full_pixmap and not full_pixmap.isNull():
            self._cropped_pm = full_pixmap.copy(
                max(0, crop_x), max(0, crop_y), self._crop_w, self._crop_h)
        else:
            self._cropped_pm = None
        self.update()

    def set_output(self, w, h):
        """Set the output (scale) dimensions and repaint."""
        self._out_w = max(1, w)
        self._out_h = max(1, h)
        self.update()

    def get_output(self):
        """Return (scale_w, scale_h)."""
        return self._out_w, self._out_h

    # ------------------------------------------------------------------
    # Internal geometry
    # ------------------------------------------------------------------

    def _display_rect(self):
        """Return (QRect, scale) for the output box drawn in widget space."""
        margin = 20
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin
        sx = avail_w / max(1, self._out_w)
        sy = avail_h / max(1, self._out_h)
        scale = min(sx, sy)
        dw = int(self._out_w * scale)
        dh = int(self._out_h * scale)
        ox = (self.width() - dw) // 2
        oy = (self.height() - dh) // 2
        return QRect(ox, oy, dw, dh), scale

    def _handle_rects(self):
        r, _ = self._display_rect()
        h = self.HANDLE_SIZE
        cx, cy = r.center().x(), r.center().y()
        pts = [
            (r.right(),  r.bottom(), 'br'),
            (r.right(),  r.top(),    'tr'),
            (r.left(),   r.bottom(), 'bl'),
            (r.right(),  cy,         'r'),
            (cx,         r.bottom(), 'b'),
        ]
        return [(QRect(px - h, py - h, h * 2, h * 2), name) for px, py, name in pts]

    def _hit_mode(self, pos):
        for rect, name in self._handle_rects():
            if rect.contains(pos):
                return f'resize_{name}'
        return None

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        r, _ = self._display_rect()

        if self._cropped_pm and not self._cropped_pm.isNull():
            painter.drawPixmap(r, self._cropped_pm)
        else:
            painter.setBrush(QBrush(QColor("#2a2a2a")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(r)
            painter.setPen(QColor("#555"))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter,
                             "Capture a frame first")

        col = QColor(self._color)
        painter.setPen(QPen(col, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

        painter.setPen(QPen(col, 1))
        painter.setBrush(QBrush(col))
        for rect, _ in self._handle_rects():
            painter.drawRect(rect)

        painter.setPen(col)
        painter.drawText(r.x() + 4, r.y() + 16,
                         f"Output: {self._out_w} × {self._out_h} px")

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mode = self._hit_mode(event.pos())
        if mode:
            self._drag_mode = mode
            self._drag_start = event.pos()
            self._drag_orig = (self._out_w, self._out_h)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            mode = self._hit_mode(event.pos())
            cursors = {
                'resize_br': Qt.CursorShape.SizeFDiagCursor,
                'resize_tr': Qt.CursorShape.SizeBDiagCursor,
                'resize_bl': Qt.CursorShape.SizeBDiagCursor,
                'resize_r':  Qt.CursorShape.SizeHorCursor,
                'resize_b':  Qt.CursorShape.SizeVerCursor,
            }
            self.setCursor(cursors.get(mode, Qt.CursorShape.ArrowCursor))
            return
        if not self._drag_mode or not self._drag_start:
            return
        _, scale = self._display_rect()
        dx = (event.pos().x() - self._drag_start.x()) / max(1e-6, scale)
        dy = (event.pos().y() - self._drag_start.y()) / max(1e-6, scale)
        ow, oh = self._drag_orig
        if 'r' in self._drag_mode:
            ow = max(1, int(ow + dx))
        if 'b' in self._drag_mode:
            oh = max(1, int(oh + dy))
        self._out_w = ow
        self._out_h = oh
        self.update()
        self.output_changed.emit(self._out_w, self._out_h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_mode = None
            self._drag_start = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()


# ---------------------------------------------------------------------------
# MultiZoomScaleDialog — multi-zone crop/stretch compositor dialog
# ---------------------------------------------------------------------------

class MultiZoomScaleDialog(QDialog):
    """Multi-zone crop/stretch configuration dialog.

    Up to 3 independent crop zones can be configured and enabled; the enabled
    zones are stitched (horizontally or vertically) to produce the final output
    image sent to mpv.

    Per-zone the user can toggle between:
      • Crop mode   — drag the coloured rectangle on the full source frame.
      • Stretch mode — drag handles to set output scale dimensions; the
                       cropped sub-image is previewed stretched in real-time.

    A *Final Preview* tab composites all enabled zones into one image showing
    exactly how the final stitched output will look.
    """

    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Multi-Zone Crop / Stretch Compositor")
        self.setModal(True)
        self.resize(1280, 820)

        self._cfg = _migrate_zoom_config(current_config)
        self.result_config = None

        # mpv / capture state (shared across all zone canvases)
        self._mpv_process = None
        self._ipc_path = None
        self._temp_dir = tempfile.mkdtemp(prefix="lc_mzoom_")
        self._frame_path = os.path.join(self._temp_dir, "frame.png")
        self._full_pixmap = None      # Most-recently captured video frame

        self._updating = False        # Guard for circular signal updates

        self._setup_ui()
        self._load_config_to_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ---- Video controls bar ----
        file_bar = QHBoxLayout()
        self._select_btn = QPushButton("Select Video…")
        self._select_btn.clicked.connect(self._select_video)
        self._video_label = QLabel("No video selected.")
        self._video_label.setStyleSheet("font-style: italic; color: #888;")
        self._play_btn   = QPushButton("▶  Play")
        self._play_btn.clicked.connect(self._play)
        self._pause_btn  = QPushButton("⏸  Pause")
        self._pause_btn.clicked.connect(self._pause)
        self._capture_btn = QPushButton("📷  Capture Frame  →")
        self._capture_btn.setStyleSheet(
            "background-color: #007acc; color: white; font-weight: bold; padding: 4px 8px;")
        self._capture_btn.clicked.connect(self._capture_frame)
        self._capture_btn.setToolTip(
            "Pause mpv and snapshot the current frame into all zone canvases.")
        for btn in (self._play_btn, self._pause_btn, self._capture_btn):
            btn.setEnabled(False)
        file_bar.addWidget(self._select_btn)
        file_bar.addWidget(self._video_label, 1)
        file_bar.addWidget(self._play_btn)
        file_bar.addWidget(self._pause_btn)
        file_bar.addWidget(self._capture_btn)
        root.addLayout(file_bar)

        # ---- Stitch direction ----
        stitch_bar = QHBoxLayout()
        stitch_bar.addWidget(QLabel("Stitch direction:"))
        self._stitch_h = QRadioButton("Horizontal  (zones side-by-side)")
        self._stitch_v = QRadioButton("Vertical  (zones stacked)")
        self._stitch_h.setChecked(True)
        stitch_bar.addWidget(self._stitch_h)
        stitch_bar.addWidget(self._stitch_v)
        stitch_bar.addStretch()
        # Import / Export buttons
        self._export_btn = QPushButton("⬆  Export State…")
        self._export_btn.setToolTip(
            "Export the current editor state (zones, borders, frame snapshot path) to a JSON file.")
        self._export_btn.clicked.connect(self._export_state)
        self._import_btn = QPushButton("⬇  Import State…")
        self._import_btn.setToolTip(
            "Import a previously exported editor state JSON file to restore all settings.")
        self._import_btn.clicked.connect(self._import_state)
        stitch_bar.addWidget(self._export_btn)
        stitch_bar.addWidget(self._import_btn)
        root.addLayout(stitch_bar)

        # ---- Tab widget ----
        self._tabs = QTabWidget()

        # Per-zone state lists
        self._zone_crop_canvases    = []
        self._zone_stretch_canvases = []
        self._zone_stacked          = []
        self._zone_enable_cbs       = []
        self._zone_mode_crop_rbs    = []
        self._zone_mode_stretch_rbs = []
        self._zone_x_sbs    = []
        self._zone_y_sbs    = []
        self._zone_w_sbs    = []
        self._zone_h_sbs    = []
        self._zone_sw_sbs   = []
        self._zone_sh_sbs   = []
        self._zone_border_sbs = []

        for i in range(NUM_ZONES):
            color = _ZONE_COLORS[i]
            tab_w = QWidget()
            tl = QVBoxLayout(tab_w)
            tl.setSpacing(6)
            tl.setContentsMargins(4, 4, 4, 4)

            # ---- Top bar: enable + mode toggle + reset ----
            top_bar = QHBoxLayout()
            enable_cb = QCheckBox(f"Enable Zone {i + 1}")
            enable_cb.setStyleSheet(f"color: {color}; font-weight: bold;")
            enable_cb.setChecked(i == 0)

            mode_crop_rb    = QRadioButton("✂  Crop Mode")
            mode_stretch_rb = QRadioButton("⤢  Stretch Mode")
            mode_crop_rb.setChecked(True)
            mode_crop_rb.setToolTip(
                "Drag the coloured rectangle on the captured frame to define\n"
                "which region of the source video is used for this zone.")
            mode_stretch_rb.setToolTip(
                "Drag the corner/edge handles to set the output size for this zone.\n"
                "The cropped sub-image is shown stretched to the chosen output size.")

            reset_btn = QPushButton("Reset to Full Frame")
            reset_btn.clicked.connect(lambda _, zi=i: self._reset_zone(zi))

            top_bar.addWidget(enable_cb)
            top_bar.addSpacing(16)
            top_bar.addWidget(QLabel("Mode:"))
            top_bar.addWidget(mode_crop_rb)
            top_bar.addWidget(mode_stretch_rb)
            top_bar.addStretch()
            top_bar.addWidget(reset_btn)
            tl.addLayout(top_bar)

            # ---- Canvas (stacked: crop / stretch) + right spinboxes ----
            body = QHBoxLayout()
            body.setSpacing(8)

            stacked = QStackedWidget()
            crop_canvas    = ZoomCropCanvas(color=color)
            stretch_canvas = StretchCanvas(color=color)
            stacked.addWidget(crop_canvas)      # index 0
            stacked.addWidget(stretch_canvas)   # index 1
            body.addWidget(stacked, 3)

            right = QVBoxLayout()
            right.setSpacing(4)

            crop_grp = QGroupBox("Source Crop Region")
            crop_grp.setStyleSheet(f"QGroupBox::title {{ color: {color}; }}")
            cg = QGridLayout(); cg.setSpacing(4)
            x_sb  = QSpinBox(); x_sb.setRange(0, 99999);  x_sb.setSuffix(" px");  x_sb.setFixedWidth(110)
            y_sb  = QSpinBox(); y_sb.setRange(0, 99999);  y_sb.setSuffix(" px");  y_sb.setFixedWidth(110)
            w_sb  = QSpinBox(); w_sb.setRange(1, 99999);  w_sb.setSuffix(" px");  w_sb.setFixedWidth(110)
            h_sb  = QSpinBox(); h_sb.setRange(1, 99999);  h_sb.setSuffix(" px");  h_sb.setFixedWidth(110)
            cg.addWidget(QLabel("X:"),      0, 0); cg.addWidget(x_sb, 0, 1)
            cg.addWidget(QLabel("Y:"),      1, 0); cg.addWidget(y_sb, 1, 1)
            cg.addWidget(QLabel("Width:"),  2, 0); cg.addWidget(w_sb, 2, 1)
            cg.addWidget(QLabel("Height:"), 3, 0); cg.addWidget(h_sb, 3, 1)
            crop_grp.setLayout(cg)

            scale_grp = QGroupBox("Output Scale (optional stretch)")
            scale_grp.setStyleSheet(f"QGroupBox::title {{ color: {color}; }}")
            scale_grp.setToolTip(
                "Leave at -1 (auto) to preserve aspect ratio.\n"
                "Set explicit pixel dimensions to force non-uniform stretching.")
            sg = QGridLayout(); sg.setSpacing(4)
            sw_sb = QSpinBox(); sw_sb.setRange(-1, 99999); sw_sb.setSpecialValueText("auto")
            sw_sb.setSuffix(" px"); sw_sb.setFixedWidth(110)
            sh_sb = QSpinBox(); sh_sb.setRange(-1, 99999); sh_sb.setSpecialValueText("auto")
            sh_sb.setSuffix(" px"); sh_sb.setFixedWidth(110)
            sg.addWidget(QLabel("Scale W:"), 0, 0); sg.addWidget(sw_sb, 0, 1)
            sg.addWidget(QLabel("Scale H:"), 1, 0); sg.addWidget(sh_sb, 1, 1)
            scale_grp.setLayout(sg)

            border_grp = QGroupBox("Black Border")
            border_grp.setStyleSheet(f"QGroupBox::title {{ color: {color}; }}")
            border_grp.setToolTip(
                "Add a solid black border around this zone's output.\n"
                "0 = no border.  The border is applied after cropping and scaling.")
            bg = QGridLayout(); bg.setSpacing(4)
            border_sb = QSpinBox()
            border_sb.setRange(0, 500)
            border_sb.setSuffix(" px")
            border_sb.setFixedWidth(110)
            border_sb.setToolTip("Border thickness in pixels (applied to all four sides).")
            bg.addWidget(QLabel("Thickness:"), 0, 0); bg.addWidget(border_sb, 0, 1)
            border_grp.setLayout(bg)

            right.addWidget(crop_grp)
            right.addWidget(scale_grp)
            right.addWidget(border_grp)
            right.addStretch()
            body.addLayout(right, 1)
            tl.addLayout(body, 1)

            self._tabs.addTab(tab_w, f"Zone {i + 1}")

            # Wire signals (capture zone index in default arg to avoid late-binding)
            crop_canvas.region_changed.connect(
                lambda x, y, w, h, zi=i: self._on_crop_changed(zi, x, y, w, h))
            stretch_canvas.output_changed.connect(
                lambda sw, sh, zi=i: self._on_stretch_changed(zi, sw, sh))
            for sb in (x_sb, y_sb, w_sb, h_sb):
                sb.valueChanged.connect(lambda _, zi=i: self._on_crop_spinbox_changed(zi))
            sw_sb.valueChanged.connect(lambda _, zi=i: self._on_scale_spinbox_changed(zi))
            sh_sb.valueChanged.connect(lambda _, zi=i: self._on_scale_spinbox_changed(zi))
            mode_crop_rb.toggled.connect(
                lambda checked, st=stacked: st.setCurrentIndex(0) if checked else None)
            mode_stretch_rb.toggled.connect(
                lambda checked, st=stacked: st.setCurrentIndex(1) if checked else None)

            # Store per-zone references
            self._zone_crop_canvases.append(crop_canvas)
            self._zone_stretch_canvases.append(stretch_canvas)
            self._zone_stacked.append(stacked)
            self._zone_enable_cbs.append(enable_cb)
            self._zone_mode_crop_rbs.append(mode_crop_rb)
            self._zone_mode_stretch_rbs.append(mode_stretch_rb)
            self._zone_x_sbs.append(x_sb)
            self._zone_y_sbs.append(y_sb)
            self._zone_w_sbs.append(w_sb)
            self._zone_h_sbs.append(h_sb)
            self._zone_sw_sbs.append(sw_sb)
            self._zone_sh_sbs.append(sh_sb)
            self._zone_border_sbs.append(border_sb)

        # ---- Final Preview tab ----
        final_tab = QWidget()
        final_layout = QVBoxLayout(final_tab)
        final_layout.setSpacing(6)
        final_top = QHBoxLayout()
        self._refresh_btn = QPushButton("🔄  Refresh Final Preview")
        self._refresh_btn.clicked.connect(self._refresh_final_preview)
        self._stitch_info_label = QLabel()
        final_top.addWidget(self._refresh_btn)
        final_top.addStretch()
        final_top.addWidget(self._stitch_info_label)
        final_layout.addLayout(final_top)
        self._final_canvas = QLabel()
        self._final_canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._final_canvas.setMinimumSize(400, 200)
        self._final_canvas.setStyleSheet("background: #111; border: 1px solid #444;")
        self._final_canvas.setText("Capture a frame and click 'Refresh Final Preview'")
        final_layout.addWidget(self._final_canvas, 1)
        self._tabs.addTab(final_tab, "Final Preview")

        root.addWidget(self._tabs, 1)

        # ---- Status bar + OK / Cancel ----
        self._status = QLabel("Select a video to begin, or adjust values directly.")
        self._status.setStyleSheet("font-style: italic; color: #888; font-size: 12px;")
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        self._ok_btn = QPushButton("✔  OK — Save Settings")
        self._ok_btn.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; padding: 6px;")
        self._ok_btn.clicked.connect(self._ok)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Config ↔ UI
    # ------------------------------------------------------------------

    def _load_config_to_ui(self):
        self._updating = True
        direction = self._cfg.get("stack_direction", "horizontal")
        self._stitch_h.setChecked(direction != "vertical")
        self._stitch_v.setChecked(direction == "vertical")
        for i, zone in enumerate(self._cfg["zones"][:NUM_ZONES]):
            self._zone_enable_cbs[i].setChecked(zone.get("enabled", i == 0))
            x  = zone.get("crop_x", 0)
            y  = zone.get("crop_y", 0)
            w  = max(1, zone.get("crop_w", 1920))
            h  = max(1, zone.get("crop_h", 1080))
            sw = zone.get("scale_w", -1)
            sh = zone.get("scale_h", -1)
            border = max(0, zone.get("border_px", 0))
            mode   = zone.get("mode", "crop")
            self._zone_x_sbs[i].setValue(x)
            self._zone_y_sbs[i].setValue(y)
            self._zone_w_sbs[i].setValue(w)
            self._zone_h_sbs[i].setValue(h)
            self._zone_sw_sbs[i].setValue(sw)
            self._zone_sh_sbs[i].setValue(sh)
            self._zone_border_sbs[i].setValue(border)
            if mode == "stretch":
                self._zone_mode_stretch_rbs[i].setChecked(True)
            else:
                self._zone_mode_crop_rbs[i].setChecked(True)
            self._zone_crop_canvases[i].set_region(x, y, w, h)
            self._zone_stretch_canvases[i].set_output(sw if sw > 0 else w, sh if sh > 0 else h)
        self._updating = False

        # Attempt to reload the persistent frame snapshot
        saved_path = self._cfg.get("frame_snapshot_path", "")
        if saved_path and os.path.isfile(saved_path):
            self._load_frame_from_path(saved_path)
            self._status.setText(
                f"Restored saved frame snapshot from '{os.path.basename(saved_path)}'.")

    def _collect_config(self):
        direction = "vertical" if self._stitch_v.isChecked() else "horizontal"
        zones = []
        for i in range(NUM_ZONES):
            mode = "stretch" if self._zone_mode_stretch_rbs[i].isChecked() else "crop"
            zones.append({
                "enabled":   self._zone_enable_cbs[i].isChecked(),
                "crop_x":    self._zone_x_sbs[i].value(),
                "crop_y":    self._zone_y_sbs[i].value(),
                "crop_w":    self._zone_w_sbs[i].value(),
                "crop_h":    self._zone_h_sbs[i].value(),
                "scale_w":   self._zone_sw_sbs[i].value(),
                "scale_h":   self._zone_sh_sbs[i].value(),
                "border_px": self._zone_border_sbs[i].value(),
                "mode":      mode,
            })
        snapshot_path = self._cfg.get("frame_snapshot_path", "")
        return {
            "zones": zones,
            "stack_direction": direction,
            "frame_snapshot_path": snapshot_path,
        }

    # ------------------------------------------------------------------
    # Zone signal handlers
    # ------------------------------------------------------------------

    def _on_crop_changed(self, zi, x, y, w, h):
        """Canvas selection changed → update spinboxes and stretch canvas."""
        if self._updating:
            return
        self._updating = True
        self._zone_x_sbs[zi].setValue(x)
        self._zone_y_sbs[zi].setValue(y)
        self._zone_w_sbs[zi].setValue(max(1, w))
        self._zone_h_sbs[zi].setValue(max(1, h))
        self._updating = False
        self._sync_stretch_canvas(zi)

    def _on_stretch_changed(self, zi, sw, sh):
        """Stretch canvas handles moved → update scale spinboxes."""
        if self._updating:
            return
        self._updating = True
        self._zone_sw_sbs[zi].setValue(sw)
        self._zone_sh_sbs[zi].setValue(sh)
        self._updating = False

    def _on_crop_spinbox_changed(self, zi):
        """Crop spinbox changed → update crop canvas and stretch canvas source."""
        if self._updating:
            return
        self._zone_crop_canvases[zi].set_region(
            self._zone_x_sbs[zi].value(),
            self._zone_y_sbs[zi].value(),
            self._zone_w_sbs[zi].value(),
            self._zone_h_sbs[zi].value(),
        )
        self._sync_stretch_canvas(zi)

    def _on_scale_spinbox_changed(self, zi):
        """Scale spinbox changed → update stretch canvas output dimensions."""
        if self._updating:
            return
        sw = self._zone_sw_sbs[zi].value()
        sh = self._zone_sh_sbs[zi].value()
        cw = self._zone_w_sbs[zi].value()
        ch = self._zone_h_sbs[zi].value()
        self._zone_stretch_canvases[zi].set_output(sw if sw > 0 else cw, sh if sh > 0 else ch)

    def _sync_stretch_canvas(self, zi):
        """Push the current crop region into the stretch canvas so it shows the right sub-image."""
        self._zone_stretch_canvases[zi].set_source(
            self._full_pixmap,
            self._zone_x_sbs[zi].value(),
            self._zone_y_sbs[zi].value(),
            self._zone_w_sbs[zi].value(),
            self._zone_h_sbs[zi].value(),
        )

    def _reset_zone(self, zi):
        """Reset this zone's crop to the full captured frame (or 1920×1080)."""
        w = self._zone_crop_canvases[zi].source_w or 1920
        h = self._zone_crop_canvases[zi].source_h or 1080
        self._zone_crop_canvases[zi].set_region(0, 0, w, h)
        self._on_crop_changed(zi, 0, 0, w, h)

    # ------------------------------------------------------------------
    # Final preview compositing
    # ------------------------------------------------------------------

    def _refresh_final_preview(self):
        if not self._full_pixmap or self._full_pixmap.isNull():
            self._final_canvas.setText("No frame captured yet.")
            return
        cfg = self._collect_config()
        zones = [z for z in cfg["zones"] if z.get("enabled") and z.get("crop_w", 0) > 0]
        if not zones:
            self._final_canvas.setText("No zones are currently enabled.")
            return

        direction = cfg.get("stack_direction", "horizontal")
        pieces = []
        for z in zones:
            cx, cy = max(0, z["crop_x"]), max(0, z["crop_y"])
            cw, ch = max(1, z["crop_w"]), max(1, z["crop_h"])
            sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
            border = z.get("border_px", 0)
            pm = self._full_pixmap.copy(cx, cy, cw, ch)
            if sw > 0 and sh > 0:
                pm = pm.scaled(sw, sh,
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            if border > 0:
                bordered = QPixmap(pm.width() + 2 * border, pm.height() + 2 * border)
                bordered.fill(QColor("black"))
                bp = QPainter(bordered)
                bp.drawPixmap(border, border, pm)
                bp.end()
                pm = bordered
            pieces.append(pm)

        if direction == "vertical":
            total_w = max(p.width() for p in pieces)
            total_h = sum(p.height() for p in pieces)
        else:
            total_w = sum(p.width() for p in pieces)
            total_h = max(p.height() for p in pieces)

        result = QPixmap(total_w, total_h)
        result.fill(QColor("#000000"))
        painter = QPainter(result)
        off = 0
        for pm in pieces:
            if direction == "vertical":
                painter.drawPixmap(0, off, pm)
                off += pm.height()
            else:
                painter.drawPixmap(off, 0, pm)
                off += pm.width()
        painter.end()

        label_size = self._final_canvas.size()
        scaled = result.scaled(label_size,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self._final_canvas.setPixmap(scaled)
        dir_txt = "vertical" if direction == "vertical" else "horizontal"
        self._stitch_info_label.setText(
            f"Stitch: {dir_txt}  |  {len(zones)} zone(s)  |  "
            f"Output: {total_w} × {total_h} px")

    # ------------------------------------------------------------------
    # Video / mpv control
    # ------------------------------------------------------------------

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Test Video", "d:\\",
            "Media Files (*.mov *.mp4 *.avi *.mkv *.wmv *.m4v);;All Files (*)"
        )
        if not path:
            return
        self._video_label.setText(os.path.basename(path))
        self._video_label.setStyleSheet("color: #d4d4d4;")
        self._launch_mpv(path)

    def _launch_mpv(self, video_path):
        self._stop_mpv()
        socket_name = f"mpv_mzoom_{int(time.time())}"
        self._ipc_path = fr'\\.\pipe\{socket_name}'
        cmd = [
            MPV_PATH,
            f"--input-ipc-server={self._ipc_path}",
            "--pause",
            "--no-fullscreen",
            "--geometry=800x600",
            "--title=Multi-Zone Preview — navigate then click Capture Frame",
            "--no-osd-bar",
            "--no-osc",
            "--no-input-default-bindings",
            "--loop-file=inf",
            "--really-quiet",
            video_path,
        ]
        try:
            self._mpv_process = subprocess.Popen(cmd)
            for btn in (self._play_btn, self._pause_btn, self._capture_btn):
                btn.setEnabled(True)
            self._status.setText(
                "mpv opened. Navigate to the desired frame, then click 'Capture Frame'.")
        except Exception as exc:
            self._status.setText(f"Error launching mpv: {exc}")

    def _send_ipc(self, json_str):
        if not self._ipc_path:
            return
        try:
            with open(self._ipc_path, "w", encoding="utf-8") as f:
                f.write(json_str + "\n")
        except Exception as exc:
            self._status.setText(f"IPC error: {exc}")

    def _play(self):
        self._send_ipc('{ "command": ["set_property", "pause", false] }')

    def _pause(self):
        self._send_ipc('{ "command": ["set_property", "pause", true] }')

    def _capture_frame(self):
        self._pause()
        QTimer.singleShot(350, self._do_capture)

    def _do_capture(self):
        safe_path = self._frame_path.replace("\\", "/")
        self._send_ipc(f'{{ "command": ["screenshot-to-file", "{safe_path}", "video"] }}')
        QTimer.singleShot(600, self._load_frame)

    def _load_frame(self):
        if not os.path.exists(self._frame_path):
            self._status.setText("Frame capture failed — is mpv still running?")
            return
        # Save a persistent copy to the local project directory
        try:
            shutil.copy(self._frame_path, ZOOM_FRAME_SNAPSHOT)
            self._cfg["frame_snapshot_path"] = os.path.abspath(ZOOM_FRAME_SNAPSHOT)
        except OSError:
            self._cfg["frame_snapshot_path"] = self._frame_path
        self._load_frame_from_path(self._frame_path)
        pm = self._full_pixmap
        if pm and not pm.isNull():
            self._status.setText(
                f"Frame captured ({pm.width()} × {pm.height()} px) and saved to "
                f"'{ZOOM_FRAME_SNAPSHOT}'. "
                "Drag each zone's coloured rectangle to define its crop region.")

    def _load_frame_from_path(self, path):
        """Load a frame image from *path* into all zone canvases."""
        pm = QPixmap(path)
        if pm.isNull():
            self._status.setText(f"Could not load frame image from '{path}'.")
            return
        self._full_pixmap = pm
        for i in range(NUM_ZONES):
            self._zone_crop_canvases[i].load_frame(path)
            # Restore the previously configured crop region after loading
            self._zone_crop_canvases[i].set_region(
                self._zone_x_sbs[i].value(),
                self._zone_y_sbs[i].value(),
                self._zone_w_sbs[i].value(),
                self._zone_h_sbs[i].value(),
            )
            self._sync_stretch_canvas(i)

    def _stop_mpv(self):
        if self._mpv_process and self._mpv_process.poll() is None:
            if self._ipc_path:
                try:
                    with open(self._ipc_path, "w", encoding="utf-8") as f:
                        f.write('{ "command": ["quit"] }\n')
                    time.sleep(0.2)
                except Exception:
                    pass
            self._mpv_process.terminate()
        self._mpv_process = None
        self._ipc_path = None

    # ------------------------------------------------------------------
    # Dialog accept / reject
    # ------------------------------------------------------------------

    def _ok(self):
        self.result_config = self._collect_config()
        self._stop_mpv()
        self.accept()

    def _cancel(self):
        self._stop_mpv()
        self.reject()

    def closeEvent(self, event):
        self._stop_mpv()
        try:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        except Exception:
            pass
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def _export_state(self):
        """Export the current editor state (zones, borders, snapshot path) to a JSON file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Editor State", "zoom_editor_state.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        state = self._collect_config()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4)
            self._status.setText(f"Editor state exported to '{os.path.basename(path)}'.")
        except OSError as exc:
            self._status.setText(f"Export failed: {exc}")

    def _import_state(self):
        """Import a previously exported editor state JSON file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Editor State", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self._status.setText(f"Import failed: {exc}")
            return
        self._cfg = _migrate_zoom_config(raw)
        self._load_config_to_ui()
        self._status.setText(
            f"Editor state imported from '{os.path.basename(path)}'.")


class Switch(QAbstractButton):
    """A custom animated toggle switch widget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(65, 35)
        self._circle_pos = QPoint(3, 3)
        # Animation for the toggle circle.
        self.animation = QPropertyAnimation(self, b"circle_pos", self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def paintEvent(self, e):
        """Draws the switch."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        # Background color changes based on checked state.
        bg_color = QColor("#d63031") if self.isChecked() else QColor("#00b894") # Red for LIVE, Green for EDIT
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(0, 0, self.width(), self.height(), self.height() / 2, self.height() / 2)
        # Draw the toggle circle.
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(self.circle_pos.x(), self.circle_pos.y(), 29, 29)

    # Define a property for the circle's position to be used by the animation.
    @pyqtProperty(QPoint)
    def circle_pos(self):
        return self._circle_pos

    @circle_pos.setter
    def circle_pos(self, pos):
        self._circle_pos = pos
        self.update() # Redraw the widget when the position changes.

    def setChecked(self, checked):
        """Overrides setChecked to trigger the animation."""
        super().setChecked(checked)
        start_pos = QPoint(3, 3) if checked else QPoint(self.width() - 32, 3)
        end_pos = QPoint(self.width() - 32, 3) if checked else QPoint(3, 3)
        self.animation.setStartValue(start_pos)
        self.animation.setEndValue(end_pos)
        self.animation.start()


class PositionPoller(QThread):
    """Polls mpv playback position and duration via IPC at ~500 ms intervals.

    Runs in its own thread so the main-thread UI is never blocked waiting on
    IPC I/O.  Set the active pipe path with :meth:`set_socket`; pass ``None``
    to pause polling without stopping the thread.
    """
    position_updated = pyqtSignal(float, float)   # (pos_seconds, dur_seconds)

    _POLL_INTERVAL = 0.5   # seconds between polls

    def __init__(self):
        super().__init__()
        self._socket_path = None
        self._socket_lock = threading.Lock()
        self._running = False

    def set_socket(self, path):
        """Set (or clear) the active mpv IPC pipe path (thread-safe)."""
        with self._socket_lock:
            self._socket_path = path

    def stop(self):
        """Signal the polling loop to exit."""
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            with self._socket_lock:
                path = self._socket_path
            if path:
                pos = _lc_query_mpv_property(path, "time-pos")
                dur = _lc_query_mpv_property(path, "duration")
                if pos is not None and dur is not None:
                    try:
                        self.position_updated.emit(float(pos), float(dur))
                    except Exception:
                        pass
            time.sleep(self._POLL_INTERVAL)


class LiveController(QWidget):
    """The main application window and controller."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Live Controller - blackcarburning - 2025-07-26 10:54:03")
        
        # On Windows, attempt to set the process priority to high for better real-time performance.
        try:
            p = psutil.Process(os.getpid())
            p.nice(psutil.HIGH_PRIORITY_CLASS)
            print("Process priority set to HIGH.")
        except Exception as e:
            print(f"Could not set process priority: {e}")

        # --- Initialize application state and data ---
        self.config = self.load_config()
        self.zoom_config = self.load_zoom_config()
        self.bpm_data = self.load_json_store(BPM_STORE_FILE)
        self.track_name_data = self.load_json_store(TRACK_NAME_STORE_FILE)
        sd_state = self.load_json_store(SD_STATE_FILE)
        self.sd_played_paths = set(sd_state.get("played_paths", []))
        self.worker = None
        self.current_ipc_socket = None
        self.is_live_mode = False
        self.tracks = []
        self.undo_history = deque(maxlen=MAX_UNDO_LEVELS)
        self.hotkey_map = {}
        self.available_hotkeys = self._generate_hotkeys()
        self.currently_playing_row = None
        self.test_track_path = None
        self.test_track_bpm_input = None
        self.test_worker = None
        self.running_test_port = None
        self.test_port_enabled_cbs = {}
        self.test_port_start_cbs = {}
        self.test_port_bpm_inputs = {}
        self.test_port_buttons = {}

        # --- Sync Calibration Loop State ---
        self.calib_loop_active = False
        self.calib_loop_worker = None
        self.calib_loop_ipc_socket = None

        # --- Scrub / loop state ---
        self._current_playback_pos = 0.0       # seconds, updated by position poller
        self._current_track_duration = 0.0     # seconds, updated by position poller
        self._slider_being_dragged = False      # True while the user holds the scrub slider
        self._loop_a_seconds = 0.0             # loop start point (seconds)
        self._loop_b_seconds = 0.0             # loop end point (seconds)

        # Background thread that polls mpv's playback position without blocking the UI.
        self._position_poller = PositionPoller()
        self._position_poller.position_updated.connect(self._on_position_updated)
        self._position_poller.start()
        
        # --- FONT & COLOR DEFINITIONS ---
        self.current_table_font_size = DEFAULT_TABLE_FONT_SIZE
        self.playing_color = QColor("#2ecc71") # Brighter Green for playing track
        self.default_color = QColor("#2a2a2a") # Default background
        self.count_in_bg_color = DEFAULT_COUNT_IN_BG_COLOR
        self.count_in_font_size = DEFAULT_COUNT_IN_FONT_SIZE
        self.track_play_bg_color = DEFAULT_TRACK_PLAY_BG_COLOR
        self.track_play_font_size = DEFAULT_TRACK_PLAY_FONT_SIZE
        
        # --- Timers for UI effects ---
        self.countdown_timer = QTimer(self)
        self.countdown_seconds = 0
        self.countdown_connection = None

        self.active_flash_timer = QTimer(self)
        self.active_flash_timer.setInterval(ACTIVE_FLASH_INTERVAL_MS)
        self.active_flash_timer.timeout.connect(self.toggle_active_label_visibility)

        # Timer that fires once to restart the calibration loop iteration after a short gap.
        self.calib_loop_restart_timer = QTimer(self)
        self.calib_loop_restart_timer.setSingleShot(True)
        self.calib_loop_restart_timer.setInterval(500)  # 500 ms gap between iterations
        self.calib_loop_restart_timer.timeout.connect(self._start_calib_iteration)

        # --- Build UI and start background services ---
        self.setup_ui()
        self.apply_config_to_ui()
        self.hotkey_listener = GlobalHotkeyListener()
        self.hotkey_listener.hotkey_pressed.connect(self.on_global_hotkey)
        self.hotkey_listener.start()
        self.load_session()

        # --- Arduino LED Controller Setup ---
        self.led2_on = False
        self.arduino_serial = self._connect_arduino()
        if self.arduino_serial is not None:
            self.send_led_command("5")  # Chase test: cycle through all LEDs to confirm they work
            time.sleep(2.5)             # Wait for chase animation to complete
        self.midi_available = False
        try:
            for port_index in [1, 2, 3]:
                test_out = rtmidi.MidiOut()
                try:
                    test_out.open_port(port_index)
                    self.midi_available = True
                    test_out.close_port()
                    break
                except Exception:
                    pass
        except Exception:
            pass
        if not self.midi_available:
            self.send_led_command("1")  # LED 1: no MIDI device connected
        else:
            self.send_led_command("4")  # "4" turns all LEDs off

    def setup_ui(self):
        """Constructs the entire user interface."""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(6, 4, 6, 4)
        self.layout.setSpacing(3)
        
        # --- Top Bar (Title, Mode Switch) ---
        top_bar_layout = QHBoxLayout()
        # Left side for "ACTIVE" label
        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0,0,0,0)
        self.active_label = QLabel("ACTIVE", self)
        self.active_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.active_label.setStyleSheet("color: #27ae60;")
        self.active_label.hide()
        left_layout.addWidget(self.active_label)
        left_layout.addStretch(1)
        # Center for title and running time
        title_layout = QVBoxLayout()
        title_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = QLabel("Untitled Setlist")
        self.title_label.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.running_time_label = QLabel(f"Total Running Time (incl. {TRACK_OVERHEAD_SECONDS}s overhead/track): 00:00:00")
        self.running_time_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.running_time_label.setStyleSheet("color: #888;")
        self.export_setlist_button = QPushButton("Export Set List")
        self.export_setlist_button.setStyleSheet("background-color: #8e44ad; color: white; font-size: 11px; padding: 3px 6px;")
        self.export_setlist_button.clicked.connect(self.export_setlist)
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.running_time_label)
        title_layout.addWidget(self.export_setlist_button)
        # Right side for mode switch
        right_container = QWidget()
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0,0,0,0)
        right_layout.addStretch(1)
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(10)
        self.edit_mode_label = QLabel("EDIT")
        self.edit_mode_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.live_mode_slider = Switch()
        self.live_mode_slider.toggled.connect(self.toggle_live_mode)
        self.live_mode_label = QLabel("LIVE")
        self.live_mode_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        mode_layout.addWidget(self.edit_mode_label)
        mode_layout.addWidget(self.live_mode_slider)
        mode_layout.addWidget(self.live_mode_label)
        right_layout.addLayout(mode_layout)
        # Add sections to top bar
        top_bar_layout.addWidget(left_container, 1)
        top_bar_layout.addLayout(title_layout, 2) 
        top_bar_layout.addWidget(right_container, 1)

        # --- Overlay Labels (Danger, Countdown, Preparing) ---
        self.danger_label = QLabel("DANGER!!\n\nSTOP PRESSING BUTTONS!\nAND GET YOUR HAIR CUT", self)
        self.danger_label.setFont(QFont("Arial", 60, QFont.Weight.ExtraBold))
        self.danger_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.danger_label.setStyleSheet("background-color: rgba(255, 0, 0, 0.8); color: white; border-radius: 25px;")
        self.danger_label.hide()
        
        self.countdown_label = QLabel("", self)
        self.countdown_label.setFont(QFont("Arial", DEFAULT_COUNT_IN_FONT_SIZE, QFont.Weight.ExtraBold))
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_label.setStyleSheet("background-color: rgba(200, 0, 0, 0.9); color: white; border-radius: 25px;")
        self.countdown_label.hide()

        self.preparing_label = QLabel("", self)
        self.preparing_label.setFont(QFont("Arial", DEFAULT_TRACK_PLAY_FONT_SIZE, QFont.Weight.Bold))
        self.preparing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preparing_label.setStyleSheet("background-color: rgba(0, 200, 0, 0.8); color: white; border-radius: 25px;")
        self.preparing_label.hide()

        self.no_midi_label = QLabel("NO MIDI INTERFACE\nDETECTED", self)
        self.no_midi_label.setFont(QFont("Arial", 60, QFont.Weight.ExtraBold))
        self.no_midi_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_midi_label.setStyleSheet("background-color: rgba(255, 165, 0, 0.9); color: white; border-radius: 25px;")
        self.no_midi_label.hide()
        
        self.save_notification_label = QLabel(self)
        self.save_notification_label.setStyleSheet("background-color: #27ae60; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 10px;")
        self.save_notification_label.hide()

        # --- Main Content Area (Table and Controls) ---
        main_layout = QHBoxLayout()
        self.table = DraggableTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["Hotkey", "Track Name", "Linked", "BPM", "Click", "Rich1", "Rich2", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 60); self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 60); self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 60); self.table.setColumnWidth(6, 60); self.table.setColumnWidth(7, 80)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.rows_reordered.connect(self.reorder_tracks)
        
        # --- Right-side Control Panel ---
        # (Groups are assembled below into a scrollable panel)
        
        # --- Playback & Setlist Group ---
        main_controls_group = QGroupBox("")
        main_controls_layout = QVBoxLayout()
        main_controls_layout.setContentsMargins(8, 8, 8, 8)
        main_controls_layout.setSpacing(6)
        add_buttons_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Track(s)")
        self.add_button.setStyleSheet(f"background-color: #007acc; color: white; font-size: 11px; padding: 3px 6px;")
        self.add_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_button.clicked.connect(self.add_tracks)
        self.add_encore_button = QPushButton("Add Encore Divider")
        self.add_encore_button.setStyleSheet(f"background-color: #007acc; color: white; font-size: 11px; padding: 3px 6px;")
        self.add_encore_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_encore_button.clicked.connect(self.add_encore_divider)
        add_buttons_layout.addWidget(self.add_button)
        add_buttons_layout.addWidget(self.add_encore_button)
        
        self.undo_button = QPushButton("Undo Delete")
        self.undo_button.clicked.connect(self.undo_delete)
        self.undo_button.setEnabled(False)

        self.stop_button = QPushButton("STOP (q)")
        self.stop_button.setStyleSheet(f"background-color: #e74c3c; color: white; font-size: 11px; font-weight: bold; padding: 3px 6px;")
        self.stop_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.stop_button.clicked.connect(self.stop_all_activity)
        self.quit_button = QPushButton("Quit")
        self.quit_button.setStyleSheet("font-size: 11px; padding: 3px 6px;")
        self.quit_button.clicked.connect(self.close)
        stop_quit_layout = QHBoxLayout()
        stop_quit_layout.setSpacing(4)
        stop_quit_layout.addWidget(self.stop_button, 3)
        stop_quit_layout.addWidget(self.quit_button, 1)
        setlist_name_layout = QHBoxLayout()
        self.setlist_name_input = QLineEdit()
        self.setlist_name_input.setPlaceholderText("Enter Setlist Name...")
        self.rename_button = QPushButton("Change")
        self.rename_button.clicked.connect(self.rename_setlist_title)
        setlist_name_layout.addWidget(self.setlist_name_input)
        setlist_name_layout.addWidget(self.rename_button)
        self.save_button = QPushButton("Save Setlist")
        self.save_button.setStyleSheet(f"background-color: #2980b9; color: white; font-size: 11px; padding: 3px 6px;")
        self.save_button.clicked.connect(self.save_setlist)
        self.load_button = QPushButton("Load Setlist")
        self.load_button.setStyleSheet(f"background-color: #27ae60; color: white; font-size: 11px; padding: 3px 6px;")
        self.load_button.clicked.connect(self.load_setlist)
        save_load_layout = QHBoxLayout()
        save_load_layout.setSpacing(4)
        save_load_layout.addWidget(self.save_button)
        save_load_layout.addWidget(self.load_button)
        main_controls_layout.addLayout(stop_quit_layout)
        main_controls_layout.addLayout(add_buttons_layout)
        main_controls_layout.addWidget(self.undo_button)
        main_controls_layout.addLayout(setlist_name_layout)
        main_controls_layout.addLayout(save_load_layout)
        main_controls_group.setLayout(main_controls_layout)
        
        # --- Settings Group (Compact Grid Layout) ---
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout()
        settings_layout.setContentsMargins(8, 16, 8, 8)
        settings_layout.setSpacing(6)

        self.display_combo = QComboBox(); self.display_combo.addItems([str(i) for i in range(1, 5)])
        self.display_combo.currentIndexChanged.connect(self.setting_changed)
        settings_layout.addWidget(QLabel("Display:"), 0, 0)
        settings_layout.addWidget(self.display_combo, 0, 1)

        self.preload_combo = QComboBox(); self.preload_combo.addItems([str(i) for i in range(1, 11)])
        self.preload_combo.currentIndexChanged.connect(self.setting_changed)
        settings_layout.addWidget(QLabel("Preload (s):"), 1, 0)
        settings_layout.addWidget(self.preload_combo, 1, 1)

        self.count_in_combo = QComboBox(); self.count_in_combo.addItems([str(i) for i in range(1, 31)])
        settings_layout.addWidget(QLabel("Count In (s):"), 2, 0)
        settings_layout.addWidget(self.count_in_combo, 2, 1)

        self.count_in_test_checkbox = QCheckBox("Count In on Track 1 (Testing)")
        self.count_in_test_checkbox.setChecked(True) # Always start checked
        settings_layout.addWidget(self.count_in_test_checkbox, 3, 0, 1, 2)

        self.require_midi_checkbox = QCheckBox("Require MIDI Ports")
        self.require_midi_checkbox.setChecked(True) # Always start checked; not persisted to session
        settings_layout.addWidget(self.require_midi_checkbox, 4, 0, 1, 2)

        offset_layout = QHBoxLayout()
        self.midi_offset_slider = QSlider(Qt.Orientation.Horizontal)
        self.midi_offset_slider.setRange(-250, 250)
        self.midi_offset_spinbox = QSpinBox()
        self.midi_offset_spinbox.setRange(-250, 250)
        self.midi_offset_spinbox.setSuffix(" ms")
        self.midi_offset_slider.valueChanged.connect(self.midi_offset_spinbox.setValue)
        self.midi_offset_spinbox.valueChanged.connect(self.midi_offset_slider.setValue)
        self.reset_offset_button = QPushButton("Reset"); self.reset_offset_button.clicked.connect(self.reset_midi_offset)
        offset_layout.addWidget(self.midi_offset_slider); offset_layout.addWidget(self.midi_offset_spinbox); offset_layout.addWidget(self.reset_offset_button)
        settings_layout.addWidget(QLabel("MIDI Offset:"), 5, 0)
        settings_layout.addLayout(offset_layout, 5, 1)

        font_size_layout = QHBoxLayout()
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 36)
        self.font_size_spinbox.setValue(self.current_table_font_size)
        self.apply_font_button = QPushButton("Apply"); self.apply_font_button.clicked.connect(self.apply_table_font_size)
        font_size_layout.addWidget(self.font_size_spinbox); font_size_layout.addWidget(self.apply_font_button)
        settings_layout.addWidget(QLabel("List Font Size:"), 6, 0)
        settings_layout.addLayout(font_size_layout, 6, 1)

        timing_group = QGroupBox("MIDI Timing Method")
        timing_layout = QHBoxLayout()
        timing_layout.setContentsMargins(8, 14, 8, 8)
        self.standard_timing_radio = QRadioButton("Standard")
        self.high_precision_timing_radio = QRadioButton("High-Precision")
        timing_layout.addWidget(self.standard_timing_radio)
        timing_layout.addWidget(self.high_precision_timing_radio)
        timing_group.setLayout(timing_layout)
        settings_layout.addWidget(timing_group, 7, 0, 1, 2)
        settings_group.setLayout(settings_layout)
        
        # --- Test Track Group ---
        test_track_group = QGroupBox("Test Track")
        test_track_layout = QHBoxLayout()
        test_track_layout.setContentsMargins(8, 14, 8, 8)
        test_track_layout.setSpacing(6)
        self.test_file_button = QPushButton("Select Test File...")
        self.test_file_button.clicked.connect(self.select_test_file)
        self.test_file_label = QLabel("No file selected.")
        self.test_file_label.setStyleSheet("font-style: italic;")
        self.test_track_bpm_input = QLineEdit("120")
        self.test_track_bpm_input.setFixedWidth(50)
        self.play_test_button = QPushButton("Play Test Track (t)")
        self.play_test_button.clicked.connect(self.play_test_track)
        self.play_test_button.setEnabled(False)
        test_track_layout.addWidget(self.test_file_button)
        test_track_layout.addWidget(self.test_file_label, 1)
        test_track_layout.addStretch(1)
        test_track_layout.addWidget(QLabel("BPM:"))
        test_track_layout.addWidget(self.test_track_bpm_input)
        test_track_layout.addWidget(self.play_test_button)
        test_track_group.setLayout(test_track_layout)

        # --- Sync Calibration Loop Group ---
        calib_loop_group = QGroupBox("Sync Calibration Loop (Edit Mode)")
        calib_loop_layout = QHBoxLayout()
        calib_loop_layout.setContentsMargins(8, 14, 8, 8)
        calib_loop_layout.setSpacing(6)
        calib_loop_layout.addWidget(QLabel("Loop:"))
        self.calib_loop_duration_spinbox = QSpinBox()
        self.calib_loop_duration_spinbox.setRange(1, 20)
        self.calib_loop_duration_spinbox.setValue(5)
        self.calib_loop_duration_spinbox.setSuffix(" s")
        self.calib_loop_duration_spinbox.setToolTip("Duration of each calibration loop (1–20 seconds)")
        calib_loop_layout.addWidget(self.calib_loop_duration_spinbox)
        self.calib_loop_button = QPushButton("Start Calib Loop")
        self.calib_loop_button.setStyleSheet("background-color: #8e44ad; color: white; font-size: 11px; padding: 3px 6px;")
        self.calib_loop_button.setToolTip(
            "Repeatedly plays the first X seconds of the test track so you can dial in the MIDI offset.\n"
            "\n"
            "If the MIDI feels late (audio hits before the MIDI-triggered gear responds):\n"
            "  → move the offset more negative (MIDI fires earlier, before the audio starts).\n"
            "\n"
            "If the MIDI feels early/fast (MIDI-triggered gear fires before the audio hits):\n"
            "  → move the offset more positive (audio starts first, then MIDI fires after the delay).\n"
            "\n"
            "Positive offset = audio/video unpauses first, MIDI start is delayed.\n"
            "Negative offset = MIDI start fires first, audio/video starts later.\n"
            "\n"
            "Changes to the offset apply on the next loop restart."
        )
        self.calib_loop_button.setEnabled(False)
        self.calib_loop_button.clicked.connect(self.toggle_calib_loop)
        calib_loop_layout.addWidget(self.calib_loop_button)
        calib_loop_group.setLayout(calib_loop_layout)

        # --- Overlay Colours Group ---
        overlay_colours_group = QGroupBox("Overlay Colours")
        overlay_colours_layout = QGridLayout()
        overlay_colours_layout.setContentsMargins(8, 16, 8, 8)
        overlay_colours_layout.setSpacing(6)

        self.count_in_color_button = QPushButton()
        self.count_in_color_button.setFixedSize(60, 25)
        self.count_in_color_button.setStyleSheet(f"background-color: {DEFAULT_COUNT_IN_BG_COLOR};")
        self.count_in_color_button.clicked.connect(self.pick_count_in_color)

        self.count_in_font_spinbox = QSpinBox()
        self.count_in_font_spinbox.setRange(20, 500)
        self.count_in_font_spinbox.setValue(DEFAULT_COUNT_IN_FONT_SIZE)
        self.count_in_font_spinbox.valueChanged.connect(self._on_count_in_font_changed)

        self.track_play_color_button = QPushButton()
        self.track_play_color_button.setFixedSize(60, 25)
        self.track_play_color_button.setStyleSheet(f"background-color: {DEFAULT_TRACK_PLAY_BG_COLOR};")
        self.track_play_color_button.clicked.connect(self.pick_track_play_color)

        self.track_play_font_spinbox = QSpinBox()
        self.track_play_font_spinbox.setRange(20, 500)
        self.track_play_font_spinbox.setValue(DEFAULT_TRACK_PLAY_FONT_SIZE)
        self.track_play_font_spinbox.valueChanged.connect(self._on_track_play_font_changed)

        overlay_colours_layout.addWidget(QLabel("Count-In BG:"), 0, 0)
        overlay_colours_layout.addWidget(self.count_in_color_button, 0, 1)
        overlay_colours_layout.addWidget(QLabel("Font:"), 0, 2)
        overlay_colours_layout.addWidget(self.count_in_font_spinbox, 0, 3)
        overlay_colours_layout.addWidget(QLabel("Track Play BG:"), 1, 0)
        overlay_colours_layout.addWidget(self.track_play_color_button, 1, 1)
        overlay_colours_layout.addWidget(QLabel("Font:"), 1, 2)
        overlay_colours_layout.addWidget(self.track_play_font_spinbox, 1, 3)
        overlay_colours_group.setLayout(overlay_colours_layout)
        midi_test_group = QGroupBox("MIDI Port Testing")
        midi_test_grid_layout = QGridLayout()
        midi_test_grid_layout.setContentsMargins(6, 14, 6, 4)
        midi_test_grid_layout.setSpacing(2)
        midi_test_grid_layout.addWidget(QLabel("<b>Port</b>"), 0, 0, Qt.AlignmentFlag.AlignCenter)
        midi_test_grid_layout.addWidget(QLabel("<b>Enabled</b>"), 0, 1, Qt.AlignmentFlag.AlignCenter)
        midi_test_grid_layout.addWidget(QLabel("<b>Send Start</b>"), 0, 2, Qt.AlignmentFlag.AlignCenter)
        midi_test_grid_layout.addWidget(QLabel("<b>BPM</b>"), 0, 3, Qt.AlignmentFlag.AlignCenter)
        port_names = ["Click", "Rich1", "Rich2"]
        for i, name in enumerate(port_names, start=1):
            port_label = QLabel(name)
            enabled_cb = QCheckBox(); enabled_cb.setChecked(True)
            self.test_port_enabled_cbs[i] = enabled_cb
            start_cb = QCheckBox(); start_cb.setChecked(True)
            self.test_port_start_cbs[i] = start_cb
            bpm_input = QLineEdit("120"); bpm_input.setFixedWidth(50)
            self.test_port_bpm_inputs[i] = bpm_input
            test_button = QPushButton(f"Start Test")
            test_button.clicked.connect(lambda checked, p=i: self.run_port_test(p))
            self.test_port_buttons[i] = test_button
            
            midi_test_grid_layout.addWidget(port_label, i, 0, Qt.AlignmentFlag.AlignCenter)
            midi_test_grid_layout.addWidget(enabled_cb, i, 1, Qt.AlignmentFlag.AlignCenter)
            midi_test_grid_layout.addWidget(start_cb, i, 2, Qt.AlignmentFlag.AlignCenter)
            midi_test_grid_layout.addWidget(bpm_input, i, 3, Qt.AlignmentFlag.AlignCenter)
            midi_test_grid_layout.addWidget(test_button, i, 4)
        midi_test_group.setLayout(midi_test_grid_layout)

        # --- Video Zoom / Scale Group (Edit Mode Only) ---
        zoom_group = QGroupBox("Multi-Zone Video Zoom / Scale")
        zoom_layout = QVBoxLayout()
        zoom_layout.setContentsMargins(8, 16, 8, 8)
        zoom_layout.setSpacing(6)
        self.apply_zoom_checkbox = QCheckBox("Apply zoom/scale during playback")
        self.apply_zoom_checkbox.setChecked(True)  # Default: scaling enabled on startup
        self.apply_zoom_checkbox.setToolTip(
            "When checked (default), the saved crop/scale settings are applied during playback.\n"
            "Uncheck this box to play video without any zoom/scale transform."
        )
        self.apply_zoom_checkbox.toggled.connect(self._update_zoom_status_label)
        self.apply_zoom_checkbox.toggled.connect(self.setting_changed)
        self.zoom_scale_button = QPushButton("Configure Multi-Zone Zoom / Scale…")
        self.zoom_scale_button.setStyleSheet("background-color: #8e44ad; color: white; font-size: 11px; padding: 3px 6px;")
        self.zoom_scale_button.setToolTip(
            "Open the multi-zone crop/stretch compositor.\n"
            "Configure up to 3 independent crop zones; each zone can be individually\n"
            "enabled and given its own output scale.  Enabled zones are stitched\n"
            "together (horizontally or vertically) into one final output image.\n"
            "Settings are saved and applied to all videos in play mode via mpv."
        )
        self.zoom_scale_button.clicked.connect(self.open_zoom_dialog)
        self.zoom_status_label = QLabel("Zoom: not configured")
        self.zoom_status_label.setStyleSheet("font-size: 10px; color: #888; font-style: italic;")
        zoom_layout.addWidget(self.apply_zoom_checkbox)
        zoom_layout.addWidget(self.zoom_scale_button)
        zoom_layout.addWidget(self.zoom_status_label)
        zoom_group.setLayout(zoom_layout)
        self._update_zoom_status_label()

        # --- Stream Deck Layout Group ---
        stream_deck_group = QGroupBox("Stream Deck Layout")
        sd_layout = QVBoxLayout()
        sd_layout.setContentsMargins(8, 16, 8, 8)
        sd_layout.setSpacing(6)

        sd_selector_row = QHBoxLayout()
        sd_selector_row.setSpacing(4)
        sd_selector_row.addWidget(QLabel("Target Deck:"))
        self.stream_deck_combo = QComboBox()
        self.stream_deck_combo.setToolTip(
            "Select which connected Stream Deck device to push the setlist layout to.\n"
            "Click 🔄 to scan for attached devices."
        )
        sd_selector_row.addWidget(self.stream_deck_combo, 1)
        self.sd_refresh_button = QPushButton("🔄")
        self.sd_refresh_button.setFixedWidth(32)
        self.sd_refresh_button.setToolTip("Scan for connected Stream Deck devices.")
        self.sd_refresh_button.clicked.connect(self._refresh_stream_deck_list)
        sd_selector_row.addWidget(self.sd_refresh_button)

        self.sd_push_button = QPushButton("⬆  Push Setlist to Stream Deck")
        self.sd_push_button.setStyleSheet(
            "background-color: #2980b9; color: white; font-size: 11px; padding: 3px 6px;"
        )
        self.sd_push_button.setToolTip(
            "Write the current setlist track labels to buttons 3–31 of the selected Stream Deck.\n"
            "Buttons 1 and 32 (reserved) are not modified.\n"
            "Encore/archive dividers insert a system:close marker key; tracks after the divider\n"
            "continue on subsequent buttons so the full setlist is always visible.\n\n"
            "REQUIREMENT: Close the Elgato Stream Deck software before pressing this button,\n"
            "then reopen it afterwards.  Both 'streamdeck' and 'Pillow' Python packages must\n"
            "be installed:  pip install streamdeck Pillow"
        )
        self.sd_push_button.setEnabled(False)
        self.sd_push_button.clicked.connect(self._push_to_stream_deck)

        self.sd_status_label = QLabel("Deck: not scanned")
        self.sd_status_label.setStyleSheet("font-size: 10px; color: #888; font-style: italic;")

        sd_layout.addLayout(sd_selector_row)
        sd_layout.addWidget(self.sd_push_button)
        sd_layout.addWidget(self.sd_status_label)
        stream_deck_group.setLayout(sd_layout)

        # --- Right-side panel: 2-column layout, no scroll needed at 1920×1080 ---
        controls_widget = QWidget()
        controls_vbox = QVBoxLayout(controls_widget)
        controls_vbox.setContentsMargins(6, 6, 6, 6)
        controls_vbox.setSpacing(8)

        # Upper row: left column (playback + zoom) | right column (settings + overlay colours)
        upper_row = QHBoxLayout()
        upper_row.setSpacing(8)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        left_col.addWidget(main_controls_group)
        left_col.addWidget(zoom_group)
        left_col.addWidget(stream_deck_group)
        left_col.addStretch(1)

        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_col.addWidget(settings_group)
        right_col.addWidget(overlay_colours_group)
        right_col.addStretch(1)

        upper_row.addLayout(left_col, 1)
        upper_row.addLayout(right_col, 1)
        controls_vbox.addLayout(upper_row)

        # Lower row: test track | calib loop  (side by side — both are small horizontal groups)
        lower_row = QHBoxLayout()
        lower_row.setSpacing(8)
        lower_row.addWidget(test_track_group, 2)
        lower_row.addWidget(calib_loop_group, 1)
        controls_vbox.addLayout(lower_row)

        # --- Scrub & Loop Group ---
        scrub_loop_group = QGroupBox("Scrub & Loop")
        scrub_loop_layout = QVBoxLayout()
        scrub_loop_layout.setContentsMargins(8, 16, 8, 8)
        scrub_loop_layout.setSpacing(6)

        # Scrub slider row: [pos] [slider] [dur]
        scrub_row = QHBoxLayout()
        scrub_row.setSpacing(6)
        self.scrub_pos_label = QLabel("--:--")
        self.scrub_pos_label.setFixedWidth(38)
        self.scrub_pos_label.setStyleSheet("font-size: 10px; color: #aaa;")
        self.scrub_slider = QSlider(Qt.Orientation.Horizontal)
        self.scrub_slider.setRange(0, 1000)
        self.scrub_slider.setValue(0)
        self.scrub_slider.setEnabled(False)
        self.scrub_slider.setToolTip("Drag to seek to a different position in the currently playing file.")
        self.scrub_slider.sliderMoved.connect(self._on_scrub_slider_moved)
        self.scrub_slider.sliderReleased.connect(self._on_scrub_slider_released)
        self.scrub_dur_label = QLabel("--:--")
        self.scrub_dur_label.setFixedWidth(38)
        self.scrub_dur_label.setStyleSheet("font-size: 10px; color: #aaa;")
        scrub_row.addWidget(self.scrub_pos_label)
        scrub_row.addWidget(self.scrub_slider, 1)
        scrub_row.addWidget(self.scrub_dur_label)

        # Bar-based loop controls row:
        # BPM: [120] | Bar A: [1] (00:00) | Bar B: [8] (00:15) | [□ Loop A→B]
        loop_row = QHBoxLayout()
        loop_row.setSpacing(6)
        loop_row.addWidget(QLabel("BPM:"))
        self.loop_bpm_spinbox = QSpinBox()
        self.loop_bpm_spinbox.setRange(40, 300)
        self.loop_bpm_spinbox.setValue(120)
        self.loop_bpm_spinbox.setFixedWidth(60)
        self.loop_bpm_spinbox.setToolTip(
            "BPM of the current track. Used to convert bar numbers to playback times."
        )
        self.loop_bpm_spinbox.valueChanged.connect(self._on_loop_bar_changed)
        loop_row.addWidget(self.loop_bpm_spinbox)

        loop_row.addWidget(QLabel("Bar A:"))
        self.loop_start_bar_spinbox = QSpinBox()
        self.loop_start_bar_spinbox.setRange(1, 9999)
        self.loop_start_bar_spinbox.setValue(1)
        self.loop_start_bar_spinbox.setFixedWidth(60)
        self.loop_start_bar_spinbox.setToolTip(
            "Loop start bar. Bar 1 corresponds to the very beginning of the track."
        )
        self.loop_start_bar_spinbox.valueChanged.connect(self._on_loop_bar_changed)
        loop_row.addWidget(self.loop_start_bar_spinbox)
        self.loop_a_time_label = QLabel("(--:--)")
        self.loop_a_time_label.setStyleSheet("font-size: 10px; color: #aaa;")
        loop_row.addWidget(self.loop_a_time_label)

        loop_row.addWidget(QLabel("Bar B:"))
        self.loop_end_bar_spinbox = QSpinBox()
        self.loop_end_bar_spinbox.setRange(1, 9999)
        self.loop_end_bar_spinbox.setValue(8)
        self.loop_end_bar_spinbox.setFixedWidth(60)
        self.loop_end_bar_spinbox.setToolTip(
            "Loop end bar (inclusive). The loop plays from the start of Bar A to the end of Bar B."
        )
        self.loop_end_bar_spinbox.valueChanged.connect(self._on_loop_bar_changed)
        loop_row.addWidget(self.loop_end_bar_spinbox)
        self.loop_b_time_label = QLabel("(--:--)")
        self.loop_b_time_label.setStyleSheet("font-size: 10px; color: #aaa;")
        loop_row.addWidget(self.loop_b_time_label)

        self.loop_checkbox = QCheckBox("Loop A→B")
        self.loop_checkbox.setToolTip(
            "When checked, mpv will repeat the section between bar A and bar B continuously.\n"
            "Bar positions are converted to times using the BPM above."
        )
        self.loop_checkbox.toggled.connect(self._on_loop_toggled)
        loop_row.addWidget(self.loop_checkbox)
        loop_row.addStretch(1)

        # Lock row
        self.scrub_lock_checkbox = QCheckBox("Lock scrub/loop controls")
        self.scrub_lock_checkbox.setToolTip(
            "When checked, the scrub slider and loop controls are disabled.\n"
            "Use this during live shows to prevent accidental changes.\n"
            "This setting is saved with the session."
        )
        self.scrub_lock_checkbox.toggled.connect(self._on_scrub_lock_changed)

        scrub_loop_layout.addLayout(scrub_row)
        scrub_loop_layout.addLayout(loop_row)
        scrub_loop_layout.addWidget(self.scrub_lock_checkbox)
        scrub_loop_group.setLayout(scrub_loop_layout)
        controls_vbox.addWidget(scrub_loop_group)

        # MIDI Port Testing spans full width at the bottom
        controls_vbox.addWidget(midi_test_group)

        # --- Assemble Main Layout ---
        # Give the controls side more width (3/5) so they don't feel cramped;
        # the track table takes 2/5.
        main_layout.addWidget(self.table, 2)
        main_layout.addWidget(controls_widget, 3)
        
        # --- Status Bar ---
        self.status_label = QLabel("Status: Welcome!")
        self.status_label.setStyleSheet("font-style: italic; color: #888; font-size: 11px;")
        
        # --- Final Layout Assembly ---
        self.layout.addLayout(top_bar_layout)
        self.layout.addLayout(main_layout)
        self.layout.addWidget(self.status_label)
        
        # --- Initial UI State ---
        self.live_mode_slider.setChecked(True) # Default to LIVE mode
        self.toggle_live_mode()
        self.populate_table()
        self.apply_overlay_styles()

    def apply_overlay_styles(self):
        """Updates the stylesheet and font of both overlay labels based on current settings."""
        count_in_c = QColor(self.count_in_bg_color)
        self.countdown_label.setStyleSheet(
            f"background-color: rgba({count_in_c.red()}, {count_in_c.green()}, {count_in_c.blue()}, 0.9); "
            "color: white; border-radius: 25px;"
        )
        self.countdown_label.setFont(QFont("Arial", self.count_in_font_size, QFont.Weight.ExtraBold))

        track_play_c = QColor(self.track_play_bg_color)
        self.preparing_label.setStyleSheet(
            f"background-color: rgba({track_play_c.red()}, {track_play_c.green()}, {track_play_c.blue()}, 0.8); "
            "color: white; border-radius: 25px;"
        )
        self.preparing_label.setFont(QFont("Arial", self.track_play_font_size, QFont.Weight.Bold))

    def pick_count_in_color(self):
        """Opens a colour picker dialog for the count-in overlay background."""
        color = QColorDialog.getColor(QColor(self.count_in_bg_color), self, "Count-In Background Colour")
        if color.isValid():
            self.count_in_bg_color = color.name()
            self.count_in_color_button.setStyleSheet(f"background-color: {self.count_in_bg_color};")
            self.apply_overlay_styles()

    def pick_track_play_color(self):
        """Opens a colour picker dialog for the track play overlay background."""
        color = QColorDialog.getColor(QColor(self.track_play_bg_color), self, "Track Play Background Colour")
        if color.isValid():
            self.track_play_bg_color = color.name()
            self.track_play_color_button.setStyleSheet(f"background-color: {self.track_play_bg_color};")
            self.apply_overlay_styles()

    def _on_count_in_font_changed(self, value):
        """Handles count-in font size spinbox changes."""
        self.count_in_font_size = value
        self.apply_overlay_styles()

    def _on_track_play_font_changed(self, value):
        """Handles track play font size spinbox changes."""
        self.track_play_font_size = value
        self.apply_overlay_styles()

    def apply_table_font_size(self):
        """Applies the selected font size to all items in the table."""
        self.current_table_font_size = self.font_size_spinbox.value()
        new_font = QFont("Segoe UI", self.current_table_font_size)
        
        # Adjust row height to fit the new font size.
        self.table.verticalHeader().setDefaultSectionSize(int(self.current_table_font_size * 2.5))
        
        # Iterate through every cell to apply the font.
        for row in range(self.table.rowCount()):
            # Apply to QTableWidgetItems
            item = self.table.item(row, 0) # Hotkey item
            if item:
                item.setFont(new_font)
            
            # Apply to QWidgets in cells
            for col in [1, 3]: # Track Name, BPM
                widget = self.table.cellWidget(row, col)
                if isinstance(widget, QLineEdit):
                    widget.setFont(new_font)
        
        self.status_label.setText(f"Status: Font size set to {self.current_table_font_size}pt.")

    def set_test_controls_enabled(self, enabled, except_port=None):
        """Enable or disable all test controls, optionally exempting one port."""
        for port_num in range(1, 4):
            is_exempt = (port_num == except_port)
            self.test_port_enabled_cbs[port_num].setEnabled(enabled or is_exempt)
            self.test_port_start_cbs[port_num].setEnabled(enabled or is_exempt)
            self.test_port_bpm_inputs[port_num].setEnabled(enabled or is_exempt)
            self.test_port_buttons[port_num].setEnabled(enabled or is_exempt)

    def toggle_live_mode(self):
        """Toggles between LIVE and EDIT modes, enabling/disabling UI controls accordingly."""
        self.is_live_mode = self.live_mode_slider.isChecked()
        is_edit_mode = not self.is_live_mode
        
        # Enable/disable all controls that should only be accessible in EDIT mode.
        self.add_button.setEnabled(is_edit_mode)
        self.add_encore_button.setEnabled(is_edit_mode)
        self.undo_button.setEnabled(is_edit_mode and len(self.undo_history) > 0)
        self.save_button.setEnabled(is_edit_mode)
        self.load_button.setEnabled(is_edit_mode)
        self.display_combo.setEnabled(is_edit_mode)
        self.preload_combo.setEnabled(is_edit_mode)
        self.count_in_combo.setEnabled(is_edit_mode)
        self.count_in_test_checkbox.setEnabled(is_edit_mode)
        self.require_midi_checkbox.setEnabled(is_edit_mode)
        self.midi_offset_slider.setEnabled(is_edit_mode)
        self.midi_offset_spinbox.setEnabled(is_edit_mode)
        self.reset_offset_button.setEnabled(is_edit_mode)
        self.quit_button.setEnabled(is_edit_mode)
        self.export_setlist_button.setEnabled(is_edit_mode)
        self.setlist_name_input.setEnabled(is_edit_mode)
        self.table.setDragEnabled(is_edit_mode)
        self.rename_button.setEnabled(is_edit_mode)
        self.test_file_button.setEnabled(is_edit_mode)
        self.play_test_button.setEnabled(is_edit_mode and self.test_track_path is not None)
        self.test_track_bpm_input.setEnabled(is_edit_mode)
        self.standard_timing_radio.setEnabled(is_edit_mode)
        self.high_precision_timing_radio.setEnabled(is_edit_mode)
        self.font_size_spinbox.setEnabled(is_edit_mode)
        self.apply_font_button.setEnabled(is_edit_mode)
        self.count_in_color_button.setEnabled(is_edit_mode)
        self.count_in_font_spinbox.setEnabled(is_edit_mode)
        self.track_play_color_button.setEnabled(is_edit_mode)
        self.track_play_font_spinbox.setEnabled(is_edit_mode)
        self.calib_loop_duration_spinbox.setEnabled(is_edit_mode and not self.calib_loop_active)
        self.calib_loop_button.setEnabled(is_edit_mode and self.test_track_path is not None)
        self.zoom_scale_button.setEnabled(is_edit_mode)
        # apply_zoom_checkbox is always enabled — user can toggle scaling in any mode

        # Stop the calibration loop if switching to LIVE mode.
        if self.is_live_mode and self.calib_loop_active:
            self.stop_calib_loop()

        # Enable/disable the widgets inside the table rows.
        for i in range(self.table.rowCount()):
            if i < len(self.tracks):
                item = self.tracks[i]
                if item['type'] == 'track':
                    # Columns with widgets: TrackName, Linked, BPM, Ports, Actions
                    for col in [1, 2, 3, 4, 5, 6, 7]: 
                        if widget := self.table.cellWidget(i, col):
                            widget.setEnabled(is_edit_mode)
        
        self.set_test_controls_enabled(is_edit_mode)

        # Update UI text and colors to reflect the current mode.
        self.live_mode_label.setStyleSheet("color: #d63031; font-weight: bold;" if self.is_live_mode else "color: #888;")
        self.edit_mode_label.setStyleSheet("color: #00b894; font-weight: bold;" if is_edit_mode else "color: #888;")
        self.status_label.setText("Status: LIVE MODE - Hotkeys are active." if self.is_live_mode else "Status: EDIT MODE - Hotkeys are disabled.")

    def reset_midi_offset(self):
        """Resets the MIDI offset slider to 0."""
        self.midi_offset_slider.setValue(0)

    def _generate_hotkeys(self):
        """Generates a list of available hotkeys (1-9, a-z, excluding q, t, i, and z)."""
        keys = [str(i) for i in range(1, 10)] + [chr(i) for i in range(ord('a'), ord('z') + 1)]
        keys.remove('q') # Reserved for STOP
        keys.remove('t') # Reserved for PLAY TEST
        keys.remove('i') # Excluded: visually confused with '1'
        keys.remove('z') # Reserved for Arduino LED 2 control
        return keys

    def _connect_arduino(self):
        """Probes serial ports to find and connect to the Arduino LED controller."""
        for port in list_ports.comports():
            try:
                ser = serial.Serial(port.device, ARDUINO_BAUD, timeout=1.2)
                time.sleep(2.0)
                ser.reset_input_buffer()
                ser.write(ARDUINO_PROBE_CMD)
                ser.flush()
                time.sleep(0.3)
                identity = None
                end_time = time.time() + 1.2
                while time.time() < end_time:
                    if ser.in_waiting:
                        line = ser.readline().decode(errors="ignore").strip()
                        if line:
                            identity = line
                if identity == ARDUINO_TARGET_ID:
                    print(f"Arduino LED controller connected on {port.device}")
                    return ser
                ser.close()
            except Exception:
                continue
        print("Arduino LED controller not found. LED feedback will be disabled.")
        return None

    def send_led_command(self, command):
        """Sends a single-character LED command to the Arduino."""
        if self.arduino_serial is not None and self.arduino_serial.is_open:
            try:
                self.arduino_serial.write(command.encode("utf-8"))
            except serial.SerialException as e:
                print(f"Arduino serial error: {e}")
    
    def load_config(self):
        """Loads general application configuration from config.json."""
        defaults = {"display": DEFAULT_VIDEO_SCREEN_NUMBER, "preload": DEFAULT_LOAD_DELAY_SECONDS}
        if not os.path.exists(CONFIG_FILE): return defaults
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                defaults.update(config)
                return defaults
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def save_config(self):
        """Saves general application configuration to config.json."""
        self.config['display'] = int(self.display_combo.currentText())
        self.config['preload'] = int(self.preload_combo.currentText())
        self.config['apply_zoom'] = self.apply_zoom_checkbox.isChecked()
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)
    
    def apply_config_to_ui(self):
        """Sets UI elements based on the loaded general config."""
        self.display_combo.setCurrentText(str(self.config.get("display", DEFAULT_VIDEO_SCREEN_NUMBER)))
        self.preload_combo.setCurrentText(str(self.config.get("preload", DEFAULT_LOAD_DELAY_SECONDS)))
        self.apply_zoom_checkbox.setChecked(self.config.get('apply_zoom', True))
        self._update_zoom_status_label()
        self.check_display_setting()

    def load_zoom_config(self):
        """Loads the zoom/scale configuration from zoom_config.json, migrating old format if needed."""
        if not os.path.exists(ZOOM_CONFIG_FILE):
            return {}
        try:
            with open(ZOOM_CONFIG_FILE, 'r') as f:
                raw = json.load(f)
            return _migrate_zoom_config(raw)
        except (json.JSONDecodeError, OSError):
            return {}

    def save_zoom_config(self):
        """Saves the zoom/scale configuration to zoom_config.json."""
        try:
            with open(ZOOM_CONFIG_FILE, 'w') as f:
                json.dump(self.zoom_config, f, indent=4)
        except OSError as e:
            self.status_label.setText(f"Warning: Could not save zoom config: {e}")

    def _update_zoom_status_label(self):
        """Updates the zoom status label to reflect the current multi-zone config."""
        apply_scaling = self.apply_zoom_checkbox.isChecked()
        if not apply_scaling:
            self.zoom_status_label.setText("Zoom: off (unscaled)")
            self.zoom_status_label.setStyleSheet("font-size: 10px; color: #888; font-style: italic;")
            return
        migrated = _migrate_zoom_config(self.zoom_config)
        zones = migrated.get("zones", [])
        enabled_zones = [z for z in zones if z.get("enabled") and z.get("crop_w", 0) > 0]
        if not enabled_zones:
            self.zoom_status_label.setText("Zoom: enabled — no zones configured")
            self.zoom_status_label.setStyleSheet("font-size: 10px; color: #e67e22; font-style: italic;")
        else:
            direction = migrated.get("stack_direction", "horizontal")
            parts = []
            for idx, z in enumerate(enabled_zones):
                cw, ch = z.get("crop_w", 0), z.get("crop_h", 0)
                sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
                border = z.get("border_px", 0)
                scale_txt = f"→{sw}×{sh}" if sw > 0 and sh > 0 else ""
                border_txt = f" +{border}b" if border > 0 else ""
                parts.append(f"Z{idx+1}:{cw}×{ch}{scale_txt}{border_txt}")
            dir_sym = "↔" if direction != "vertical" else "↕"
            self.zoom_status_label.setText(f"{dir_sym} " + "  ".join(parts))
            self.zoom_status_label.setStyleSheet("font-size: 10px; color: #00b894; font-style: italic;")

    def open_zoom_dialog(self):
        """Opens the MultiZoomScaleDialog for configuring multi-zone crop/stretch."""
        dialog = MultiZoomScaleDialog(self.zoom_config, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_config is not None:
            self.zoom_config = dialog.result_config
            self.save_zoom_config()
            self._update_zoom_status_label()
            self.status_label.setText("Status: Multi-zone zoom/scale settings saved and will apply in play mode.")

    # ------------------------------------------------------------------
    # Stream Deck helpers
    # ------------------------------------------------------------------

    # Slot layout constants (1-indexed button numbers as shown in Elgato software)
    _SD_FIRST_TRACK_BTN = 3   # Button 3 is the first track slot
    _SD_LAST_TRACK_BTN  = 31  # Button 31 is the last track slot
    _SD_TRACKS_PER_PAGE = _SD_LAST_TRACK_BTN - _SD_FIRST_TRACK_BTN + 1  # 29

    def _refresh_stream_deck_list(self):
        """Scans for connected Stream Deck devices and populates the selector combo box."""
        self.stream_deck_combo.clear()
        self.sd_push_button.setEnabled(False)

        if not _STREAMDECK_AVAILABLE:
            self.stream_deck_combo.addItem("streamdeck package not installed")
            self.sd_status_label.setText("Install:  pip install streamdeck Pillow")
            self.sd_status_label.setStyleSheet("font-size: 10px; color: #e74c3c; font-style: italic;")
            return

        try:
            decks = _SDDeviceManager().enumerate()
        except Exception as exc:
            self.stream_deck_combo.addItem(f"Scan error: {exc}")
            self.sd_status_label.setText("Could not enumerate devices.")
            self.sd_status_label.setStyleSheet("font-size: 10px; color: #e74c3c; font-style: italic;")
            return

        if not decks:
            self.stream_deck_combo.addItem("No Stream Decks found")
            self.sd_status_label.setText("Deck: none detected")
            self.sd_status_label.setStyleSheet("font-size: 10px; color: #888; font-style: italic;")
            return

        for idx, deck in enumerate(decks):
            try:
                deck.open()
                name = deck.deck_type()
                key_count = deck.key_count()
                try:
                    serial = deck.get_serial_number()
                except Exception:
                    serial = f"#{idx}"
                deck.close()
                self.stream_deck_combo.addItem(
                    f"{name}  ({key_count} keys)  S/N: {serial}", userData=idx
                )
            except Exception:
                self.stream_deck_combo.addItem(f"Stream Deck #{idx} (could not open)")

        self.sd_push_button.setEnabled(True)
        count = self.stream_deck_combo.count()
        self.sd_status_label.setText(f"Deck: {count} device(s) found")
        self.sd_status_label.setStyleSheet("font-size: 10px; color: #00b894; font-style: italic;")

    def _make_sd_key_image(self, deck, label_top, label_bottom="", bg_color=(39, 174, 96)):
        """Renders a PIL image for a single Stream Deck key.

        Parameters
        ----------
        deck        : open StreamDeck device (used to determine image dimensions).
        label_top   : primary text (track name), shown in the upper-centre of the key.
        label_bottom: secondary text (hotkey), shown near the bottom of the key.
        bg_color    : RGB tuple for the background fill (default green).

        Returns the image in the deck's native wire format.
        """
        fmt = deck.key_image_format()
        w, h = fmt["size"]

        img = _PILImage.new("RGB", (w, h), color=bg_color)
        draw = _PILImageDraw.Draw(img)

        # Try a system font; fall back to the built-in default if not found.
        font_sm = font_lg = None
        for font_name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
            try:
                font_lg = _PILImageFont.truetype(font_name, max(10, h // 6))
                font_sm = _PILImageFont.truetype(font_name, max(8, h // 8))
                break
            except (IOError, OSError):
                continue
        if font_lg is None:
            font_lg = _PILImageFont.load_default()
            font_sm = font_lg

        # Split the track name so that each word appears on its own line.
        # A uniform font size is used for every line so labels stay consistent.
        words = label_top.split() if label_top else []

        cx = w // 2

        def _draw_centred(text, y, font):
            """Draw *text* centred at (cx, y) without relying on the 'anchor' kwarg."""
            try:
                bbox = font.getbbox(text)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            except Exception:
                tw, th = len(text) * (h // 8), h // 8
            draw.text((cx - tw // 2, y - th // 2), text, font=font, fill="white")

        def _draw_centred_coloured(text, y, font, fill):
            try:
                bbox = font.getbbox(text)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            except Exception:
                tw, th = len(text) * (h // 8), h // 8
            draw.text((cx - tw // 2, y - th // 2), text, font=font, fill=fill)

        if words:
            # Reserve space at the bottom for the hotkey label if present
            # (matches the fixed label position used by _draw_centred_coloured below).
            bottom_reserve = 16 if label_bottom else 0
            usable_h = h - bottom_reserve
            n = len(words)
            # Distribute words evenly across the usable vertical space.
            for i, word in enumerate(words):
                y = usable_h * (i + 1) // (n + 1)
                _draw_centred(word, y, font_lg)

        if label_bottom:
            _draw_centred_coloured(label_bottom.upper(), h - 8, font_sm, (200, 255, 200))

        return _SDPILHelper.to_native_format(deck, img)

    def _push_to_stream_deck(self):
        """Pushes the current setlist layout to the selected Stream Deck device.

        Track buttons 3–31 (1-indexed) are written with track name labels.
        Tracks that have been played during this session (or a previous one) are
        rendered with an amber background so their toggled state is visible when
        the deck is re-pushed.  Unplayed tracks use the default green background.
        Encore/archive dividers insert a system:close marker key and then continue
        populating subsequent tracks on the same page.  Keys 1 and 32 (reserved)
        and any unused track slots are reset to a dark blank image.  Only the deck
        selected in the combo box is modified; the other deck is left completely
        untouched.

        Button labels use the track name currently shown in the setlist table
        (column 1), which may be a user-set name or the filename stem default.
        The raw filename is not used as a separate fallback source.

        Limitation: the python-streamdeck library only delivers hardware button-
        press events while the deck device is held open.  Because this app opens
        the deck briefly for image writes and then closes it (so that Elgato's own
        software can reattach), physical button presses cannot be intercepted
        directly.  Toggle state is therefore tracked through the application's own
        playback events (start_playback / execute_playback) and persisted in
        sd_state.json, which is the most reliable path given this architecture.
        """
        if not _STREAMDECK_AVAILABLE:
            self.sd_status_label.setText("streamdeck library not installed.")
            self.sd_status_label.setStyleSheet("font-size: 10px; color: #e74c3c; font-style: italic;")
            return

        if not _PIL_AVAILABLE:
            self.sd_status_label.setText("Pillow library not installed (pip install Pillow).")
            self.sd_status_label.setStyleSheet("font-size: 10px; color: #e74c3c; font-style: italic;")
            return

        selected_idx = self.stream_deck_combo.currentData()
        if selected_idx is None:
            self.sd_status_label.setText("No deck selected.")
            return

        # Build a map from track path to the label currently shown in the
        # setlist table (the QLineEdit in column 1).  Reading directly from the
        # widget ensures the button label matches what the user sees in the
        # table, without re-deriving a name from the raw file path.
        table_name_map = {}
        for row_idx, track_item in enumerate(self.tracks):
            if track_item.get("type") == "track":
                name_widget = self.table.cellWidget(row_idx, 1)
                if name_widget is not None:
                    table_name_map[track_item["path"]] = name_widget.text()

        # Build a flat slot list: tracks become track entries, dividers become
        # system:close marker entries.  Processing continues past every divider
        # so the full setlist (including encores) is written to the deck.
        flat_slots = []
        for item in self.tracks:
            if item.get("type") == "divider":
                flat_slots.append({"type": "close"})
            elif item.get("type") == "track":
                flat_slots.append(item)

        # Open the selected deck exclusively.
        try:
            decks = _SDDeviceManager().enumerate()
            if selected_idx >= len(decks):
                self.sd_status_label.setText("Selected deck no longer available — rescan.")
                return
            deck = decks[selected_idx]
            deck.open()
        except Exception as exc:
            self.sd_status_label.setText(f"Could not open deck: {exc}")
            self.sd_status_label.setStyleSheet("font-size: 10px; color: #e74c3c; font-style: italic;")
            return

        try:
            total_keys = deck.key_count()
            first_slot = self._SD_FIRST_TRACK_BTN - 1  # convert to 0-based
            last_slot  = self._SD_LAST_TRACK_BTN  - 1

            # Blank image for non-track keys and unused slots.
            blank_img = self._make_sd_key_image(deck, "", bg_color=(30, 30, 30))

            keys_written = 0
            for key_idx in range(first_slot, last_slot + 1):
                slot_idx = key_idx - first_slot
                if slot_idx < len(flat_slots):
                    slot = flat_slots[slot_idx]
                    if slot.get("type") == "close":
                        img = self._make_sd_key_image(
                            deck, "system:close", "", bg_color=(100, 50, 20)
                        )
                    else:
                        # Use the name from the table widget as the label source.
                        # Fall back to track_name_data if the table widget is not
                        # available (e.g., the table has not been rendered yet).
                        raw_name = table_name_map.get(
                            slot["path"],
                            self.track_name_data.get(slot["path"], ""),
                        )
                        hotkey = slot.get("hotkey", "")
                        # Tracks that have been played are rendered with an amber
                        # background so their toggled/played state is visible when
                        # the setlist is re-pushed to the deck.
                        if slot["path"] in self.sd_played_paths:
                            bg = (160, 100, 20)  # amber — played / toggled on
                        else:
                            bg = (39, 174, 96)   # green  — unplayed / toggled off
                        img = self._make_sd_key_image(deck, raw_name, hotkey, bg_color=bg)
                        keys_written += 1
                else:
                    img = blank_img
                if key_idx < total_keys:
                    deck.set_key_image(key_idx, img)

        except Exception as exc:
            self.sd_status_label.setText(f"Write error: {exc}")
            self.sd_status_label.setStyleSheet("font-size: 10px; color: #e74c3c; font-style: italic;")
            return
        finally:
            try:
                deck.close()
            except Exception:
                pass

        total_tracks = sum(1 for item in self.tracks if item.get("type") == "track")
        msg = f"Deck updated -- {keys_written} track key(s) written."
        self.sd_status_label.setText(msg)
        self.sd_status_label.setStyleSheet("font-size: 10px; color: #00b894; font-style: italic;")
        self.status_label.setText(f"Status: Stream Deck updated ({keys_written}/{total_tracks} tracks).")


    def setting_changed(self):
        """Saves the config whenever a setting is changed."""
        self.save_config()

    def check_display_setting(self):
        """Warns the user if the selected display is not available."""
        num_screens = len(QGuiApplication.screens())
        selected_screen_index = int(self.display_combo.currentText()) - 1
        if selected_screen_index >= num_screens:
            self.status_label.setText(f"WARNING: Display {selected_screen_index + 1} not found!")

    def load_json_store(self, file_path):
        """Generic helper to load data from a JSON file."""
        if not os.path.exists(file_path): return {}
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def save_json_store(self, file_path, data):
        """Generic helper to save data to a JSON file."""
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)

    def save_session(self):
        """Saves the current setlist and settings to session.json."""
        session_data = {
            'setlist_name': self.title_label.text(), 
            'tracks': self.tracks,
            'undo_history': list(self.undo_history),
            'test_track_path': self.test_track_path,
            'test_track_bpm': self.test_track_bpm_input.text(),
            'midi_offset': self.midi_offset_slider.value(),
            'timing_method': "high_precision" if self.high_precision_timing_radio.isChecked() else "standard",
            'count_in_duration': int(self.count_in_combo.currentText()),
            'table_font_size': self.current_table_font_size,
            'count_in_bg_color': self.count_in_bg_color,
            'count_in_font_size': self.count_in_font_size,
            'track_play_bg_color': self.track_play_bg_color,
            'track_play_font_size': self.track_play_font_size,
            'scrub_locked': self.scrub_lock_checkbox.isChecked(),
            'loop_enabled': self.loop_checkbox.isChecked(),
            'loop_bpm': self.loop_bpm_spinbox.value(),
            'loop_start_bar': self.loop_start_bar_spinbox.value(),
            'loop_end_bar': self.loop_end_bar_spinbox.value(),
        }
        with open(SESSION_FILE, 'w') as f:
            json.dump(session_data, f, indent=4)
    
    def load_session(self):
        """Loads the last session from session.json on startup."""
        if not os.path.exists(SESSION_FILE): 
            self.status_label.setText("Status: No previous session found. Welcome!")
            self.midi_offset_slider.setValue(DEFAULT_MIDI_OFFSET_MS)
            self.count_in_combo.setCurrentText(str(DEFAULT_COUNT_IN_SECONDS))
            self.count_in_test_checkbox.setChecked(True)
            self.standard_timing_radio.setChecked(True)
            return
        try:
            with open(SESSION_FILE, 'r') as f: 
                session_data = json.load(f)
            
            # Restore all settings from the session data.
            self.midi_offset_slider.setValue(session_data.get('midi_offset', DEFAULT_MIDI_OFFSET_MS))
            self.count_in_combo.setCurrentText(str(session_data.get('count_in_duration', DEFAULT_COUNT_IN_SECONDS)))
            self.count_in_test_checkbox.setChecked(True) # Always check this on startup
            if session_data.get('timing_method') == 'high_precision':
                self.high_precision_timing_radio.setChecked(True)
            else:
                self.standard_timing_radio.setChecked(True)
            
            self.current_table_font_size = session_data.get('table_font_size', DEFAULT_TABLE_FONT_SIZE)
            self.font_size_spinbox.setValue(self.current_table_font_size)
            
            self.count_in_bg_color = session_data.get('count_in_bg_color', DEFAULT_COUNT_IN_BG_COLOR)
            self.count_in_font_size = session_data.get('count_in_font_size', DEFAULT_COUNT_IN_FONT_SIZE)
            self.track_play_bg_color = session_data.get('track_play_bg_color', DEFAULT_TRACK_PLAY_BG_COLOR)
            self.track_play_font_size = session_data.get('track_play_font_size', DEFAULT_TRACK_PLAY_FONT_SIZE)
            self.count_in_color_button.setStyleSheet(f"background-color: {self.count_in_bg_color};")
            self.count_in_font_spinbox.setValue(self.count_in_font_size)
            self.track_play_color_button.setStyleSheet(f"background-color: {self.track_play_bg_color};")
            self.track_play_font_spinbox.setValue(self.track_play_font_size)
            self.apply_overlay_styles()

            self.undo_history = deque(session_data.get('undo_history', []), maxlen=MAX_UNDO_LEVELS)

            self._apply_setlist_data(session_data.get('tracks', []), session_data.get('setlist_name', 'Untitled Setlist'))
            
            self.test_track_path = session_data.get('test_track_path')
            self.test_track_bpm_input.setText(session_data.get('test_track_bpm', '120'))
            if self.test_track_path and os.path.exists(self.test_track_path):
                self.test_file_label.setText(os.path.basename(self.test_track_path))
                self.test_file_label.setStyleSheet("font-style: normal; color: #d4d4d4;")
                self.play_test_button.setEnabled(True)
            else:
                self.test_track_path = None

            # Restore scrub/loop settings.
            self.scrub_lock_checkbox.setChecked(session_data.get('scrub_locked', False))
            self.loop_checkbox.setChecked(session_data.get('loop_enabled', False))
            self.loop_bpm_spinbox.setValue(session_data.get('loop_bpm', 120))
            self.loop_start_bar_spinbox.setValue(session_data.get('loop_start_bar', 1))
            self.loop_end_bar_spinbox.setValue(session_data.get('loop_end_bar', 8))
            self._update_scrub_controls_state()

            self.status_label.setText(f"Status: Restored previous session: {session_data.get('setlist_name', '')}")
        except (json.JSONDecodeError, FileNotFoundError): 
            self.status_label.setText("Status: Could not load previous session file.")

    def rename_setlist_title(self):
        """Renames the setlist title based on user input."""
        new_name = self.setlist_name_input.text().strip()
        if new_name:
            self.title_label.setText(new_name)
            self.undo_history.clear()
            self.update_undo_button_state()

    def add_tracks(self):
        """Opens a file dialog to add one or more video tracks to the setlist."""
        files, _ = QFileDialog.getOpenFileNames(self, "Select Track Files", "d:\\", "Media Files (*.mov *.wav);;Video Files (*.mov);;Audio Files (*.wav)")
        if not files: return
        for file_path in files:
            # Avoid adding duplicate tracks.
            if file_path in [t.get('path') for t in self.tracks]: continue
            if not self.available_hotkeys:
                self.status_label.setText("Status: No more hotkeys available.")
                break
            
            hotkey = self.available_hotkeys.pop(0)
            duration = self.get_track_duration(file_path)
            self.tracks.append({
                'type': 'track', 
                'path': file_path, 
                'hotkey': hotkey, 
                'duration': duration, 
                'linked': False,
                'send_start_port1': True,
                'send_start_port2': False,
                'send_start_port3': False,
            })
            self.rebuild_hotkey_map()
        self.populate_table()

    def add_encore_divider(self):
        """Adds a visual divider to the setlist."""
        encore_count = sum(1 for item in self.tracks if item['type'] == 'divider')
        self.tracks.append({'type': 'divider', 'text': f'ENCORE {encore_count + 1}'})
        self.populate_table()

    def get_track_duration(self, file_path):
        """Uses mplayer to get the duration of a media file (video or audio)."""
        if not os.path.exists(MPLAYER_PATH):
            print(f"MPlayer executable not found at {MPLAYER_PATH}")
            return 0
        try:
            normalized_path = os.path.normpath(file_path)
            mplayer_dir = os.path.dirname(MPLAYER_PATH)
            # Command to get video info without playing audio/video.
            cmd = [MPLAYER_PATH, "-vo", "null", "-ao", "null", "-identify", "-frames", "0", normalized_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30, cwd=mplayer_dir, creationflags=subprocess.CREATE_NO_WINDOW)
            # Parse the output for the duration.
            for line in result.stdout.splitlines():
                if line.startswith("ID_LENGTH="):
                    return float(line.split('=')[1])
            print(f"Could not find ID_LENGTH for {file_path}")
            return 0
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError, subprocess.TimeoutExpired) as e:
            print(f"Could not get duration for {file_path}: {e}")
            return 0

    def remove_item(self, row_index):
        """Removes an item (track or divider) from the setlist."""
        if self.currently_playing_row == row_index:
            self.clear_highlight()
        
        item_to_remove = self.tracks.pop(row_index)
        
        # Add to undo history
        self.undo_history.append({'index': row_index, 'item': item_to_remove})
        self.update_undo_button_state()

        # If it was a track, return its hotkey to the available pool.
        if item_to_remove['type'] == 'track':
            hotkey = item_to_remove['hotkey']
            if hotkey not in self.available_hotkeys:
                self.available_hotkeys.append(hotkey)
                self.available_hotkeys.sort()
        
        self.rebuild_hotkey_map()
        self.populate_table()
    
    def undo_delete(self):
        """Restores the last deleted item from the undo history."""
        if not self.undo_history:
            return
        
        last_deleted = self.undo_history.pop()
        index = last_deleted['index']
        item = last_deleted['item']
        
        # If a track was restored, reclaim its hotkey if still valid, or assign a new one.
        if item.get('type') == 'track':
            hotkey = item.get('hotkey')
            valid_hotkeys = set(self._generate_hotkeys())
            if hotkey in valid_hotkeys and hotkey in self.available_hotkeys:
                self.available_hotkeys.remove(hotkey)
            elif hotkey not in valid_hotkeys:
                # Legacy/invalid hotkey — assign a new valid one.
                if self.available_hotkeys:
                    item['hotkey'] = self.available_hotkeys.pop(0)
                else:
                    item['hotkey'] = ''

        self.tracks.insert(index, item)
        self.rebuild_hotkey_map()
        self.populate_table()
        self.update_undo_button_state()

    def update_undo_button_state(self):
        """Enables or disables the undo button based on history."""
        self.undo_button.setEnabled(len(self.undo_history) > 0 and not self.is_live_mode)

    def populate_table(self):
        """Clears and repopulates the setlist table from the self.tracks data."""
        self.table.setRowCount(0)
        for i, item in enumerate(self.tracks):
            self.table.insertRow(i)
            
            tooltip_text = ""
            if item.get('type') == 'track':
                tooltip_text = f"Filename: {os.path.basename(item['path'])}\nDuration: {self.format_duration(item.get('duration', 0))}"

            if item.get('type') == 'divider':
                # --- Create Divider Row ---
                self.table.setSpan(i, 0, 1, self.table.columnCount() - 1)
                self.table.setRowHeight(i, 25)
                encore_item = QTableWidgetItem(item.get('text', 'ENCORE'))
                encore_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                encore_item.setBackground(QColor("#007acc"))
                encore_item.setForeground(QColor(Qt.GlobalColor.white))
                font = QFont("Segoe UI", self.current_table_font_size); font.setBold(False)
                encore_item.setFont(font)
                self.table.setItem(i, 0, encore_item)
                
                # Create a centered remove button for the divider row.
                remove_button = QPushButton("X"); remove_button.clicked.connect(lambda checked, i=i: self.remove_item(i))
                remove_button.setFixedSize(20, 20)
                remove_button.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; border-radius: 4px; font-size: 12px;")
                button_container = QWidget()
                button_layout = QHBoxLayout(button_container)
                button_layout.addWidget(remove_button)
                button_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                button_layout.setContentsMargins(0,0,0,0)
                self.table.setCellWidget(i, 7, button_container)
            else: 
                # --- Create Track Row ---
                table_font = QFont("Segoe UI", self.current_table_font_size)
                
                hotkey_item = QTableWidgetItem(item['hotkey'].upper())
                hotkey_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                hotkey_item.setFlags(hotkey_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                hotkey_item.setFont(table_font)
                hotkey_item.setToolTip(tooltip_text)
                self.table.setItem(i, 0, hotkey_item)
                
                track_name_input = QLineEdit(self.track_name_data.get(item['path'], os.path.splitext(os.path.basename(item['path']))[0]))
                track_name_input.setFont(table_font)
                track_name_input.textChanged.connect(lambda text, path=item['path']: self.update_track_name(path, text))
                track_name_input.setToolTip(tooltip_text)
                self.table.setCellWidget(i, 1, track_name_input)
                
                def create_linked_checkbox(row_idx, track_item):
                    linked_container = QWidget()
                    linked_layout = QHBoxLayout(linked_container)
                    linked_cb = QCheckBox()
                    linked_cb.setStyleSheet("QCheckBox::indicator { width: 12px; height: 12px; }")
                    linked_cb.setChecked(track_item.get('linked', False))
                    linked_cb.toggled.connect(lambda checked, r=row_idx: self.update_linked_setting(checked, r))
                    linked_layout.addWidget(linked_cb)
                    linked_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    linked_layout.setContentsMargins(0,0,0,0)
                    linked_container.setToolTip(tooltip_text)
                    return linked_container

                self.table.setCellWidget(i, 2, create_linked_checkbox(i, item))
                
                bpm_input = QLineEdit(str(self.bpm_data.get(item['path'], 120)))
                bpm_input.setFont(table_font)
                bpm_input.textChanged.connect(lambda text, path=item['path']: self.update_bpm(path, text))
                bpm_input.setToolTip(tooltip_text)
                self.table.setCellWidget(i, 3, bpm_input)
                
                def create_port_checkbox(port_num):
                    checkbox_container = QWidget()
                    checkbox_layout = QHBoxLayout(checkbox_container)
                    checkbox = QCheckBox()
                    checkbox.setStyleSheet("QCheckBox::indicator { width: 12px; height: 12px; }")
                    is_checked = item.get(f'send_start_port{port_num}', False)
                    checkbox.setChecked(is_checked)
                    checkbox.toggled.connect(lambda checked, i=i, p=port_num: self.update_midi_port_setting(checked, i, p))
                    checkbox_layout.addWidget(checkbox)
                    checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    checkbox_layout.setContentsMargins(0,0,0,0)
                    checkbox_container.setToolTip(tooltip_text)
                    return checkbox_container

                self.table.setCellWidget(i, 4, create_port_checkbox(1))
                self.table.setCellWidget(i, 5, create_port_checkbox(2))
                self.table.setCellWidget(i, 6, create_port_checkbox(3))

                remove_button = QPushButton("X"); remove_button.clicked.connect(lambda checked, i=i: self.remove_item(i))
                remove_button.setFixedSize(20, 20)
                remove_button.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; border-radius: 4px; font-size: 12px;")
                button_container = QWidget()
                button_layout = QHBoxLayout(button_container)
                button_layout.addWidget(remove_button)
                button_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                button_layout.setContentsMargins(0,0,0,0)
                button_container.setToolTip(tooltip_text)
                self.table.setCellWidget(i, 7, button_container)
        
        self.apply_table_font_size()
        self.update_total_running_time()
        self.toggle_live_mode()
    
    def reorder_tracks(self, source_row, dest_row):
        """Handles the reordering of tracks in the internal data list."""
        moved_item = self.tracks.pop(source_row)
        self.tracks.insert(dest_row, moved_item)
        
        # After reordering, the hotkey map must be rebuilt and the table repopulated.
        self.rebuild_hotkey_map()
        self.populate_table()
        self.status_label.setText("Status: Setlist order updated.")
    
    def rebuild_hotkey_map(self):
        """Rebuilds the mapping of hotkeys to their row indices."""
        self.hotkey_map = {item['hotkey']: i for i, item in enumerate(self.tracks) if item['type'] == 'track'}

    def highlight_row(self, row, is_playing):
        """Applies a visual highlight to a row to indicate its playing."""
        if row >= len(self.tracks) or self.tracks[row]['type'] == 'divider': return
        
        bg_color = self.playing_color if is_playing else self.default_color
        fg_color = QColor("#000000") if is_playing else QColor("#d4d4d4")
        
        font_size = self.current_table_font_size
        
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                item.setBackground(bg_color)
                item.setForeground(fg_color)
                item.setFont(QFont("Segoe UI", font_size))

            widget = self.table.cellWidget(row, col)
            if widget:
                # For containers with buttons or checkboxes, only set the background color
                # to avoid breaking the child widget's intrinsic styling.
                if col in [2, 4, 5, 6, 7]:
                    widget.setStyleSheet(f"background-color: {bg_color.name()};")
                else: # For other widgets like QLineEdit, apply full style.
                    style_sheet = f"background-color: {bg_color.name()}; color: {fg_color.name()}; font-size: {font_size}pt; border: none;"
                    widget.setStyleSheet(style_sheet)
                    # Explicitly set font on child QLineEdit to ensure it applies.
                    if hasattr(widget, 'findChildren'):
                        for child_widget in widget.findChildren(QLineEdit):
                            child_widget.setFont(QFont("Segoe UI", font_size))
                            child_widget.setStyleSheet(style_sheet)

    def clear_highlight(self):
        """Removes the highlight from the currently playing row."""
        if self.currently_playing_row is not None and self.currently_playing_row < self.table.rowCount():
            self.highlight_row(self.currently_playing_row, is_playing=False)
        self.currently_playing_row = None

    def update_track_name(self, file_path, name):
        """Saves the track name to the JSON store when edited."""
        self.track_name_data[file_path] = name
        self.save_json_store(TRACK_NAME_STORE_FILE, self.track_name_data)

    def update_bpm(self, file_path, text):
        """Saves the BPM to the JSON store when edited."""
        try: 
            self.bpm_data[file_path] = int(text)
            self.save_json_store(BPM_STORE_FILE, self.bpm_data)
        except ValueError:
            pass # Ignore invalid (non-integer) input.
        
    def update_midi_port_setting(self, is_checked, row_index, port_num):
        """Updates the MIDI port setting for a track."""
        if 0 <= row_index < len(self.tracks) and self.tracks[row_index]['type'] == 'track':
            self.tracks[row_index][f'send_start_port{port_num}'] = is_checked

    def update_linked_setting(self, is_checked, row_index):
        """Updates the linked setting for a track."""
        if 0 <= row_index < len(self.tracks) and self.tracks[row_index]['type'] == 'track':
            self.tracks[row_index]['linked'] = is_checked

    def save_setlist(self):
        """Saves the current setlist to a named JSON file."""
        setlist_name = self.setlist_name_input.text().strip()
        if not setlist_name: 
            self.status_label.setText("Status: Please enter a name for the setlist before saving.")
            return
            
        if not os.path.exists(SETLISTS_DIR):
            os.makedirs(SETLISTS_DIR)
        file_path = os.path.join(SETLISTS_DIR, f"{setlist_name}.json")
        
        setlist_data_to_save = {
            'tracks': self.tracks,
            'undo_history': list(self.undo_history),
            'midi_offset': self.midi_offset_slider.value(),
            'timing_method': "high_precision" if self.high_precision_timing_radio.isChecked() else "standard",
            'count_in_duration': int(self.count_in_combo.currentText()),
            'count_in_bg_color': self.count_in_bg_color,
            'count_in_font_size': self.count_in_font_size,
            'track_play_bg_color': self.track_play_bg_color,
            'track_play_font_size': self.track_play_font_size,
        }
        
        with open(file_path, 'w') as f:
            json.dump(setlist_data_to_save, f, indent=4)
        
        self.title_label.setText(setlist_name)
        self.status_label.setText(f"Status: Setlist '{setlist_name}' saved successfully.")
        
        # Show a temporary "Saved!" notification in the center of the screen.
        self.save_notification_label.setText(f"Setlist '{setlist_name}' Saved!")
        self.save_notification_label.adjustSize()
        center_x = (self.width() - self.save_notification_label.width()) // 2
        center_y = (self.height() - self.save_notification_label.height()) // 2
        self.save_notification_label.move(center_x, center_y)
        self.save_notification_label.raise_()
        self.save_notification_label.show()
        QTimer.singleShot(SAVE_POPUP_DURATION_MS, self.save_notification_label.hide)
    
    def load_setlist(self):
        """Loads a setlist from a JSON file."""
        if self.worker and self.worker.isRunning():
            self.stop_all_activity()
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Setlist", SETLISTS_DIR, "JSON Files (*.json)")
        if not file_path: return
        with open(file_path, 'r') as f:
            try: 
                loaded_data = json.load(f)
            except json.JSONDecodeError: 
                self.status_label.setText(f"Status: Error reading invalid setlist file.")
                return
        
        setlist_name = os.path.splitext(os.path.basename(file_path))[0]
        
        # Handle both new and old setlist formats.
        if isinstance(loaded_data, dict):
            tracks_data = loaded_data.get('tracks', [])
            self.undo_history = deque(loaded_data.get('undo_history', []), maxlen=MAX_UNDO_LEVELS)
            self.midi_offset_slider.setValue(loaded_data.get('midi_offset', DEFAULT_MIDI_OFFSET_MS))
            self.count_in_combo.setCurrentText(str(loaded_data.get('count_in_duration', DEFAULT_COUNT_IN_SECONDS)))
            if loaded_data.get('timing_method') == 'high_precision':
                self.high_precision_timing_radio.setChecked(True)
            else:
                self.standard_timing_radio.setChecked(True)
            self.count_in_bg_color = loaded_data.get('count_in_bg_color', DEFAULT_COUNT_IN_BG_COLOR)
            self.count_in_font_size = loaded_data.get('count_in_font_size', DEFAULT_COUNT_IN_FONT_SIZE)
            self.track_play_bg_color = loaded_data.get('track_play_bg_color', DEFAULT_TRACK_PLAY_BG_COLOR)
            self.track_play_font_size = loaded_data.get('track_play_font_size', DEFAULT_TRACK_PLAY_FONT_SIZE)
            self.count_in_color_button.setStyleSheet(f"background-color: {self.count_in_bg_color};")
            self.count_in_font_spinbox.setValue(self.count_in_font_size)
            self.track_play_color_button.setStyleSheet(f"background-color: {self.track_play_bg_color};")
            self.track_play_font_spinbox.setValue(self.track_play_font_size)
            self.apply_overlay_styles()
        else:
            tracks_data = loaded_data
            self.undo_history.clear()
        
        self._apply_setlist_data(tracks_data, setlist_name)
        self.update_undo_button_state()

    def _apply_setlist_data(self, setlist_data, setlist_name):
        """Helper function to apply loaded setlist data to the application state."""
        self.tracks, self.hotkey_map = [], {}
        self.available_hotkeys = self._generate_hotkeys()
        
        # Backwards compatibility: ensure 'type' key exists.
        for item in setlist_data:
            if 'type' not in item:
                item['type'] = 'track'

        # Recalculate available hotkeys, only consuming valid keys from the loaded data.
        valid_hotkeys = set(self._generate_hotkeys())
        loaded_hotkeys = {item['hotkey'] for item in setlist_data if item['type'] == 'track' and item['hotkey'] in valid_hotkeys}
        self.available_hotkeys = [k for k in self.available_hotkeys if k not in loaded_hotkeys]

        # Backwards compatibility and data validation.
        for item in setlist_data:
            if item['type'] == 'track':
                if 'duration' not in item or item['duration'] == 0:
                    item['duration'] = self.get_track_duration(item['path'])
                if 'send_start_port1' not in item:
                     item['send_start_port1'] = True
                if 'send_start_port2' not in item: item['send_start_port2'] = False
                if 'send_start_port3' not in item: item['send_start_port3'] = False
                if 'linked' not in item: item['linked'] = False
                # Reassign hotkeys that are not in the valid set (e.g. legacy 'i' assignments).
                if item['hotkey'] not in valid_hotkeys:
                    if self.available_hotkeys:
                        item['hotkey'] = self.available_hotkeys.pop(0)
                    else:
                        item['hotkey'] = ''
        
        self.tracks = setlist_data
        self.rebuild_hotkey_map()
        self.title_label.setText(setlist_name)
        self.setlist_name_input.setText(setlist_name)
        self.populate_table()

    def export_setlist(self):
        """Exports the current setlist as a plain text file to the user's Downloads folder."""
        tracks_only = [item for item in self.tracks if item['type'] == 'track']
        if not tracks_only:
            self.status_label.setText("Status: No tracks to export.")
            return

        # First pass: collect all track data to determine the max prefix length for alignment
        track_data = []
        track_number = 0
        total_seconds = 0
        for row_index, item in enumerate(self.tracks):
            if item['type'] != 'divider':
                track_number += 1
                duration = item.get('duration', 0)
                total_seconds += duration
                name_widget = self.table.cellWidget(row_index, 1)
                bpm_widget = self.table.cellWidget(row_index, 3)
                track_name = (name_widget.text() if name_widget else "").replace('_', ' ').upper()
                bpm = bpm_widget.text() if bpm_widget else ""
                duration_str = self.format_duration(duration)
                track_data.append((track_number, track_name, duration_str, bpm))

        max_prefix_len = max(len(f"{n}. {name}") for n, name, _, _ in track_data)

        # Second pass: build lines with tab-aligned columns
        lines = []
        track_data_iter = iter(track_data)
        for item in self.tracks:
            if item['type'] == 'divider':
                lines.append("")
                lines.append(item.get('text', 'ENCORE'))
                lines.append("")
            else:
                n, track_name, duration_str, bpm = next(track_data_iter)
                prefix = f"{n}. {track_name}".ljust(max_prefix_len)
                lines.append(f"{prefix}\t{duration_str}\t{bpm}")

        lines.append("")
        lines.append(f"Total Time: {self.format_duration(total_seconds, show_hours=True)}")
        track_count = len([t for t in self.tracks if t['type'] == 'track'])
        total_with_overhead = total_seconds + (track_count * TRACK_OVERHEAD_SECONDS)
        lines.append(f"Total Time (incl. {TRACK_OVERHEAD_SECONDS}s gap between songs): {self.format_duration(total_with_overhead, show_hours=True)}")

        setlist_name = self.title_label.text()
        safe_name = re.sub(r'[\\/*?:"<>|]', '', setlist_name).strip()
        if not safe_name:
            safe_name = "setlist"
        date_str = datetime.date.today().strftime("%Y-%m-%d")
        filename = f"{safe_name}_setlist_{date_str}.txt"
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        file_path = os.path.join(downloads_dir, filename)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        self.status_label.setText(f"Status: Set list exported to {file_path}")

    def update_total_running_time(self):
        """Calculates and displays the total running time for the setlist."""
        total_seconds = sum(t.get('duration', 0) for t in self.tracks if t['type'] == 'track')
        total_seconds += len([t for t in self.tracks if t['type'] == 'track']) * TRACK_OVERHEAD_SECONDS
        self.running_time_label.setText(f"Total Running Time (incl. {TRACK_OVERHEAD_SECONDS}s overhead/track): {self.format_duration(total_seconds, show_hours=True)}")

    def format_duration(self, seconds, show_hours=False):
        """Formats a duration in seconds to a MM:SS or HH:MM:SS string."""
        if seconds is None or seconds < 0: return "00:00"
        total_seconds = int(seconds)
        mins, secs = divmod(total_seconds, 60)
        if show_hours:
            hours, mins = divmod(mins, 60)
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def on_global_hotkey(self, key):
        """Handles key presses from the global hotkey listener."""
        lower_key = key.lower()

        # 'z' key toggles LED 2 on/off regardless of playback state or mode.
        if lower_key == 'z':
            self.led2_on = not self.led2_on
            self.send_led_command("2" if self.led2_on else "4")
            return

        # If playback is active, only 'q' (STOP) is allowed.
        if self.worker and self.worker.isRunning() or self.countdown_timer.isActive() or (self.test_worker and self.test_worker.isRunning()):
            if lower_key == 'q':
                self.stop_all_activity()
            else:
                self.show_danger_message() # Warn user about pressing keys during playback.
            return
        
        # '^' key toggles between EDIT and LIVE modes (for Stream Deck control).
        if lower_key == '^':
            self.live_mode_slider.setChecked(not self.live_mode_slider.isChecked())
            return

        if not self.is_live_mode: return # Ignore hotkeys in EDIT mode.
        
        if lower_key in self.hotkey_map:
            row_index = self.hotkey_map[lower_key]
            if self.tracks[row_index]['type'] == 'track':
                 self.start_playback(row_index)
        elif lower_key == 't':
            self.play_test_track()

    def start_playback(self, row_index):
        """Initiates playback for a selected track."""
        if (self.worker and self.worker.isRunning()) or (self.test_worker and self.test_worker.isRunning()):
            self.show_danger_message(); return
        if self.tracks[row_index]['type'] == 'divider': return
        if self.require_midi_checkbox.isChecked() and not self.midi_available:
            self.status_label.setText("ERROR: No MIDI hardware detected. Cannot start playback.")
            self.send_led_command("1")
            self.show_no_midi_message()
            return
        
        is_countdown_track = (row_index == 0 and self.count_in_test_checkbox.isChecked())

        # Show the "Preparing" overlay unless it's a countdown track.
        if not is_countdown_track:
            track_name_widget = self.table.cellWidget(row_index, 1)
            self.show_preparing_message(track_name_widget.text())
        
        if is_countdown_track:
            self.start_countdown(row_index)
        else:
            track = self.tracks[row_index]
            bpm_widget = self.table.cellWidget(row_index, 3)
            bpm = int(bpm_widget.text())
            self.execute_playback(track, bpm, row_index)

    def start_countdown(self, row_index):
        """Starts the visual countdown timer for the first track."""
        self.send_led_command("3")  # LED 3: track 1 count-in started
        self.countdown_seconds = int(self.count_in_combo.currentText())
        self.countdown_label.setText(str(self.countdown_seconds))
        self.countdown_label.raise_()
        self.countdown_label.show()
        
        self.countdown_connection = self.countdown_timer.timeout.connect(lambda: self._update_countdown(row_index))
        self.countdown_timer.start(1000)

    def _update_countdown(self, row_index):
        """Updates the countdown label each second."""
        self.countdown_seconds -= 1
        if self.countdown_seconds > 0:
            self.countdown_label.setText(str(self.countdown_seconds))
        else:
            # When countdown finishes, stop the timer and start the actual playback.
            self.countdown_timer.stop()
            if self.countdown_connection:
                self.countdown_timer.timeout.disconnect(self.countdown_connection)
                self.countdown_connection = None
            self.countdown_label.hide()
            
            track = self.tracks[row_index]
            bpm_widget = self.table.cellWidget(row_index, 3)
            bpm = int(bpm_widget.text())
            self.execute_playback(track, bpm, row_index)

    def execute_playback(self, track_data, bpm, row_index=None):
        """Creates and starts a MidiSyncWorker to handle playback."""
        if self.require_midi_checkbox.isChecked() and not self.midi_available:
            self.status_label.setText("ERROR: No MIDI hardware detected. Cannot start playback.")
            self.send_led_command("1")  # LED 1: no MIDI device connected
            self.show_no_midi_message()
            return
        try:
            # Gather all necessary parameters from the UI.
            display_num = int(self.display_combo.currentText())
            preload_time = int(self.preload_combo.currentText())
            midi_offset = self.midi_offset_slider.value()
            timing_method = "high_precision" if self.high_precision_timing_radio.isChecked() else "standard"
            send_start_port1 = track_data.get('send_start_port1', True)
            send_start_port2 = track_data.get('send_start_port2', False)
            send_start_port3 = track_data.get('send_start_port3', False)
            track_path = track_data.get('path')
        except (ValueError, AttributeError, KeyError) as e: 
            self.status_label.setText(f"ERROR: Invalid settings or track data. {e}")
            return
        
        self.clear_highlight()
        if row_index is not None:
            self.highlight_row(row_index, is_playing=True)
            self.currently_playing_row = row_index
            # Record that this track has been played and persist state so the
            # Stream Deck can restore the toggled visual on the next push.
            self.sd_played_paths.add(track_path)
            self.save_json_store(SD_STATE_FILE, {"played_paths": list(self.sd_played_paths)})
        else: # It's the test track
            self.test_file_label.setStyleSheet("font-weight: bold; color: #27ae60;")

        # Start the flashing "ACTIVE" label.
        self.active_flash_timer.start()
        
        # Create and start the worker thread.
        require_midi = self.require_midi_checkbox.isChecked()
        effective_zoom = self.zoom_config if self.apply_zoom_checkbox.isChecked() else {}
        self.worker = MidiSyncWorker(track_path, bpm, display_num, preload_time, midi_offset, 
                                     send_start_port1, send_start_port2, send_start_port3, timing_method,
                                     require_midi, zoom_config=effective_zoom)
        self.worker.status_update.connect(self.status_label.setText)
        self.worker.error.connect(lambda msg: self.status_label.setText(f"ERROR: {msg}"))
        self.worker.finished.connect(self.on_playback_finished)
        self.worker.ipc_socket_path.connect(self.set_ipc_socket)
        self.send_led_command("3")  # LED 3 (orange): song is playing
        self.send_led_command("6")  # LED 6 (green): track active indicator
        self.worker.start()
        # Auto-populate the loop BPM spinbox with the current track's BPM and
        # recalculate bar→time labels.  Block signals on setValue to prevent a
        # redundant _on_loop_bar_changed call before the explicit one below.
        self.loop_bpm_spinbox.blockSignals(True)
        self.loop_bpm_spinbox.setValue(bpm)
        self.loop_bpm_spinbox.blockSignals(False)
        self._on_loop_bar_changed()

    def set_ipc_socket(self, path):
        """Receives the IPC socket path from the worker thread."""
        self.current_ipc_socket = path
        self._position_poller.set_socket(path)
        self._update_scrub_controls_state()

    def stop_all_activity(self):
        """Centralized method to stop any running playback, countdown, or test."""
        if self.countdown_timer.isActive():
            self.countdown_timer.stop()
            if self.countdown_connection:
                try: self.countdown_timer.timeout.disconnect(self.countdown_connection)
                except TypeError: pass
                self.countdown_connection = None
            self.countdown_label.hide()
            self.status_label.setText("Status: Countdown aborted.")

        if self.worker and self.worker.isRunning():
            self.worker.stop()
            # Attempt to quit mpv gracefully via its socket.
            if self.current_ipc_socket:
                try:
                    with open(self.current_ipc_socket, "w", encoding='utf-8') as ipc:
                        ipc.write('{ "command": ["quit"] }\n')
                except Exception as e:
                    print(f"Stop Playback: Error sending quit command: {e}")
            self.worker.wait() # Wait for thread to finish.

        if self.test_worker and self.test_worker.isRunning():
            self.test_worker.stop()
            self.test_worker.wait()

        # Stop the calibration loop if it is active.
        if self.calib_loop_active:
            self.stop_calib_loop()

        self.active_flash_timer.stop()
        self.active_label.hide()
        self.send_led_command("4")  # Turn off all LEDs when playback is manually stopped.
        self._reset_scrub_controls()

    def on_playback_finished(self):
        """Cleans up the UI and state after playback finishes."""
        finished_row = self.currently_playing_row
        self.clear_highlight()
        self.test_file_label.setStyleSheet("font-style: italic; color: #888;") # Reset test label style
        self.status_label.setText("Status: Ready. Press a hotkey to play a track.")
        self.active_flash_timer.stop()
        self.active_label.hide()
        if self.worker:
            self.worker.deleteLater()
        self.worker = None
        self.current_ipc_socket = None
        self._reset_scrub_controls()

        # Turn off all LEDs when any track finishes.
        self.send_led_command("4")  # "4" turns all LEDs off

        # Auto-play next track if the finished track was linked.
        if finished_row is not None and finished_row < len(self.tracks):
            finished_track = self.tracks[finished_row]
            if finished_track.get('type') == 'track' and finished_track.get('linked', False):
                # Find the next track in the setlist (skip dividers).
                next_row = finished_row + 1
                while next_row < len(self.tracks) and self.tracks[next_row].get('type') == 'divider':
                    next_row += 1
                if next_row < len(self.tracks) and self.tracks[next_row].get('type') == 'track':
                    next_track = self.tracks[next_row]
                    track_name_widget = self.table.cellWidget(next_row, 1)
                    if track_name_widget:
                        self.show_preparing_message(track_name_widget.text())
                    bpm_widget = self.table.cellWidget(next_row, 3)
                    try:
                        bpm = int(bpm_widget.text()) if bpm_widget else 120
                    except (ValueError, AttributeError):
                        bpm = 120
                    self.execute_playback(next_track, bpm, next_row)

    def on_test_finished(self, port_num):
        """Resets the UI for the MIDI port test controls."""
        self.test_port_buttons[port_num].setText("Start Test")
        self.test_port_buttons[port_num].setStyleSheet("")
        self.set_test_controls_enabled(not self.is_live_mode)
        self.play_test_button.setEnabled(not self.is_live_mode and self.test_track_path is not None)
        if self.test_worker:
            self.test_worker.deleteLater()
        self.test_worker = None
        self.running_test_port = None

    def run_port_test(self, port_num):
        """Starts or stops a MIDI port test."""
        if self.worker and self.worker.isRunning():
            self.show_danger_message(); return

        # If the test for this port is already running, stop it.
        if self.running_test_port == port_num and self.test_worker:
            self.stop_all_activity()
            return

        # Don't allow multiple tests at once.
        if self.test_worker:
            self.show_danger_message(); return

        is_enabled = self.test_port_enabled_cbs[port_num].isChecked()
        if not is_enabled:
            self.status_label.setText(f"Status: Port {port_num} test is disabled.")
            return

        try:
            bpm = int(self.test_port_bpm_inputs[port_num].text())
        except ValueError:
            self.status_label.setText(f"Status: Invalid BPM for Port {port_num} test.")
            return

        send_start = self.test_port_start_cbs[port_num].isChecked()
        
        self.test_worker = MidiTestWorker(port_num, bpm, send_start)
        self.test_worker.status_update.connect(self.status_label.setText)
        self.test_worker.error.connect(lambda msg: self.status_label.setText(f"ERROR: {msg}"))
        self.test_worker.finished.connect(self.on_test_finished)
        
        self.running_test_port = port_num
        self.test_port_buttons[port_num].setText("Stop Test")
        self.test_port_buttons[port_num].setStyleSheet("background-color: #e74c3c; color: white;")
        self.set_test_controls_enabled(False, except_port=port_num)
        self.play_test_button.setEnabled(False) 
        
        self.test_worker.start()

    def show_danger_message(self):
        """Shows a large, temporary warning overlay."""
        self.danger_label.raise_()
        self.danger_label.show()
        QTimer.singleShot(2500, self.danger_label.hide)

    def show_no_midi_message(self):
        """Shows a large, temporary warning overlay when MIDI is not connected."""
        self.no_midi_label.raise_()
        self.no_midi_label.show()
        QTimer.singleShot(2500, self.no_midi_label.hide)

    def show_preparing_message(self, track_name):
        """Shows a temporary "Preparing" overlay."""
        self.preparing_label.raise_()
        self.preparing_label.show()
        self.preparing_label.setText(f"PREPARING:\n{track_name}")
        QTimer.singleShot(PREPARING_OVERLAY_DURATION_MS, self.preparing_label.hide)
    
    def toggle_active_label_visibility(self):
        """Toggles the visibility of the 'ACTIVE' label to create a flashing effect."""
        self.active_label.setVisible(not self.active_label.isVisible())

    # ------------------------------------------------------------------ #
    # Scrub & Loop
    # ------------------------------------------------------------------ #

    def _lc_send_ipc(self, command_str):
        """Sends a JSON command string to the currently active mpv instance."""
        if self.current_ipc_socket:
            _lc_send_ipc_command(self.current_ipc_socket, command_str)

    @staticmethod
    def _bars_to_seconds(bar, bpm):
        """Convert a 1-based bar number to an absolute playback time in seconds.

        Assumes 4/4 time and that the track starts at bar 1 from time zero.
        Bar 1 → 0.0 s, Bar 2 → 240/BPM s, etc.
        240 = 4 beats/bar × 60 seconds/beat at 1 BPM.
        """
        # 4 beats per bar × 60 s/beat = 240 s/bar at 1 BPM
        seconds_per_bar = 240.0 / max(1, bpm)
        return (bar - 1) * seconds_per_bar

    def _on_position_updated(self, pos: float, dur: float):
        """Slot called by PositionPoller (via signal) whenever mpv reports a new position."""
        self._current_playback_pos = pos
        self._current_track_duration = dur
        if self._slider_being_dragged:
            return
        if dur > 0:
            slider_val = int((pos / dur) * 1000)
            self.scrub_slider.blockSignals(True)
            self.scrub_slider.setValue(slider_val)
            self.scrub_slider.blockSignals(False)
        self.scrub_pos_label.setText(self.format_duration(pos))
        self.scrub_dur_label.setText(self.format_duration(dur))

    def _on_scrub_slider_moved(self, value: int):
        """Called continuously while the user drags the scrub slider handle."""
        self._slider_being_dragged = True
        if self._current_track_duration > 0:
            pos = (value / 1000.0) * self._current_track_duration
            self.scrub_pos_label.setText(self.format_duration(pos))

    def _on_scrub_slider_released(self):
        """Called when the user releases the scrub slider — seek mpv to the chosen position."""
        if not self._slider_being_dragged:
            return
        self._slider_being_dragged = False
        if self.current_ipc_socket and self._current_track_duration > 0:
            value = self.scrub_slider.value()
            pos = (value / 1000.0) * self._current_track_duration
            self._lc_send_ipc(json.dumps({"command": ["seek", pos, "absolute"]}))

    def _on_loop_bar_changed(self):
        """Recalculate loop A/B times whenever the bar spinboxes or BPM changes."""
        bpm = self.loop_bpm_spinbox.value()
        start_bar = self.loop_start_bar_spinbox.value()
        end_bar = self.loop_end_bar_spinbox.value()

        self._loop_a_seconds = self._bars_to_seconds(start_bar, bpm)
        # Bar B is inclusive: the loop plays through the *end* of bar B,
        # which is the same as the *start* of bar B+1.
        self._loop_b_seconds = self._bars_to_seconds(end_bar + 1, bpm)

        self.loop_a_time_label.setText(f"({self.format_duration(self._loop_a_seconds)})")
        self.loop_b_time_label.setText(f"({self.format_duration(self._loop_b_seconds)})")

        if self.loop_checkbox.isChecked() and self.current_ipc_socket:
            self._lc_send_ipc(json.dumps({"command": ["set_property", "ab-loop-a", self._loop_a_seconds]}))
            self._lc_send_ipc(json.dumps({"command": ["set_property", "ab-loop-b", self._loop_b_seconds]}))

    def _on_loop_toggled(self, checked: bool):
        """Enable or disable mpv's A-B loop when the loop checkbox is toggled."""
        if not self.current_ipc_socket:
            return
        if checked:
            # Recalculate from bars and send to mpv.
            self._on_loop_bar_changed()
        else:
            self._lc_send_ipc(json.dumps({"command": ["set_property", "ab-loop-a", "no"]}))
            self._lc_send_ipc(json.dumps({"command": ["set_property", "ab-loop-b", "no"]}))

    def _on_scrub_lock_changed(self, checked: bool):
        """Lock or unlock the scrub/loop controls."""
        self._update_scrub_controls_state()

    def _update_scrub_controls_state(self):
        """Refresh enabled/disabled state for all scrub and loop widgets."""
        is_playing = self.worker is not None and self.worker.isRunning()
        locked = self.scrub_lock_checkbox.isChecked()
        self.scrub_slider.setEnabled(is_playing and not locked)
        self.loop_bpm_spinbox.setEnabled(not locked)
        self.loop_start_bar_spinbox.setEnabled(not locked)
        self.loop_end_bar_spinbox.setEnabled(not locked)
        self.loop_checkbox.setEnabled(not locked)

    def _reset_scrub_controls(self):
        """Reset scrub slider and labels to their idle state when playback stops."""
        self._position_poller.set_socket(None)
        self._current_track_duration = 0.0
        self._current_playback_pos = 0.0
        self._slider_being_dragged = False
        self.scrub_slider.blockSignals(True)
        self.scrub_slider.setValue(0)
        self.scrub_slider.blockSignals(False)
        self.scrub_pos_label.setText("--:--")
        self.scrub_dur_label.setText("--:--")
        self._update_scrub_controls_state()

    def select_test_file(self):
        """Opens a file dialog to select a video file for testing."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Test File", "d:\\", "Media Files (*.mov *.mp4 *.wav);;Video Files (*.mov *.mp4);;Audio Files (*.wav)")
        if file_path:
            self.test_track_path = file_path
            self.test_file_label.setText(os.path.basename(file_path))
            self.test_file_label.setStyleSheet("font-style: normal; color: #d4d4d4;")
            self.play_test_button.setEnabled(True)
            # Also enable the calibration loop button now that a test file is available.
            if not self.is_live_mode:
                self.calib_loop_button.setEnabled(True)

    def play_test_track(self):
        """Plays the selected test track with all MIDI ports enabled."""
        if (self.worker and self.worker.isRunning()) or (self.test_worker and self.test_worker.isRunning()):
            self.show_danger_message(); return
        if not self.test_track_path:
            self.status_label.setText("Status: No test track selected."); return
        if self.require_midi_checkbox.isChecked() and not self.midi_available:
            self.status_label.setText("ERROR: No MIDI hardware detected. Cannot start test track.")
            self.send_led_command("1")
            self.show_no_midi_message()
            return
        
        self.show_preparing_message(os.path.basename(self.test_track_path))
        
        try:
            bpm = int(self.test_track_bpm_input.text())
        except (ValueError, KeyError):
             self.status_label.setText("Status: Invalid BPM for test track."); return

        test_track_data = {
            'path': self.test_track_path,
            'send_start_port1': True,
            'send_start_port2': True,
            'send_start_port3': True,
        }
        self.execute_playback(test_track_data, bpm)

    # --- Sync Calibration Loop Methods ---

    def toggle_calib_loop(self):
        """Starts or stops the sync calibration loop."""
        if self.calib_loop_active:
            self.stop_calib_loop()
        else:
            self._start_calib_loop()

    def _start_calib_loop(self):
        """Validates preconditions and starts the calibration loop."""
        if not self.test_track_path:
            self.status_label.setText("Status: No test track selected for calibration.")
            return
        if self.require_midi_checkbox.isChecked() and not self.midi_available:
            self.status_label.setText("ERROR: No MIDI hardware detected. Cannot start calibration loop.")
            self.show_no_midi_message()
            return
        if (self.worker and self.worker.isRunning()) or (self.test_worker and self.test_worker.isRunning()):
            self.show_danger_message()
            return
        try:
            int(self.test_track_bpm_input.text())
        except ValueError:
            self.status_label.setText("Status: Invalid BPM for calibration loop.")
            return

        self.calib_loop_active = True
        self.calib_loop_button.setText("Stop Calib Loop")
        self.calib_loop_button.setStyleSheet("background-color: #e74c3c; color: white; font-size: 11px; padding: 3px 6px;")
        # Lock the duration spinbox while the loop is running.
        self.calib_loop_duration_spinbox.setEnabled(False)
        self._start_calib_iteration()

    def _start_calib_iteration(self):
        """Launches a single iteration of the calibration loop."""
        if not self.calib_loop_active or not self.test_track_path:
            return
        try:
            bpm = int(self.test_track_bpm_input.text())
        except ValueError:
            self.stop_calib_loop()
            self.status_label.setText("Status: Invalid BPM, calibration loop stopped.")
            return

        duration = self.calib_loop_duration_spinbox.value()
        display_num = int(self.display_combo.currentText())
        preload_time = int(self.preload_combo.currentText())
        midi_offset = self.midi_offset_slider.value()
        timing_method = "high_precision" if self.high_precision_timing_radio.isChecked() else "standard"
        require_midi = self.require_midi_checkbox.isChecked()
        effective_zoom = self.zoom_config if self.apply_zoom_checkbox.isChecked() else {}

        self.calib_loop_worker = MidiSyncWorker(
            self.test_track_path, bpm, display_num, preload_time, midi_offset,
            True, True, True, timing_method, require_midi,
            max_duration_sec=duration, zoom_config=effective_zoom
        )
        self.calib_loop_worker.status_update.connect(self.status_label.setText)
        self.calib_loop_worker.error.connect(self._on_calib_error)
        self.calib_loop_worker.finished.connect(self._on_calib_iteration_finished)
        self.calib_loop_worker.ipc_socket_path.connect(self._set_calib_loop_ipc)
        self.active_flash_timer.start()
        self.calib_loop_worker.start()
        self.status_label.setText(
            f"Status: Calib loop playing ({duration}s, offset {midi_offset:+d} ms)..."
        )

    def _set_calib_loop_ipc(self, path):
        """Stores the IPC socket path for the active calibration loop mpv instance."""
        self.calib_loop_ipc_socket = path

    def _on_calib_error(self, msg):
        """Handles errors emitted by the calibration loop worker."""
        self.status_label.setText(f"Calibration error: {msg}")
        self.stop_calib_loop()

    def _on_calib_iteration_finished(self):
        """Called when one calibration loop iteration finishes."""
        if self.calib_loop_worker:
            self.calib_loop_worker.deleteLater()
        self.calib_loop_worker = None
        self.calib_loop_ipc_socket = None

        if self.calib_loop_active:
            # Schedule the next iteration after a brief gap so the event loop stays responsive.
            self.calib_loop_restart_timer.start()
        else:
            self.active_flash_timer.stop()
            self.active_label.hide()

    def stop_calib_loop(self):
        """Stops the calibration loop and cleans up all related resources."""
        self.calib_loop_active = False
        self.calib_loop_restart_timer.stop()

        if self.calib_loop_worker and self.calib_loop_worker.isRunning():
            self.calib_loop_worker.stop()
            if self.calib_loop_ipc_socket:
                try:
                    with open(self.calib_loop_ipc_socket, "w", encoding='utf-8') as ipc:
                        ipc.write('{ "command": ["quit"] }\n')
                except Exception as e:
                    print(f"Calib loop stop: Error sending quit to mpv: {e}")
            self.calib_loop_worker.wait()

        if self.calib_loop_worker:
            self.calib_loop_worker.deleteLater()
        self.calib_loop_worker = None
        self.calib_loop_ipc_socket = None

        self.active_flash_timer.stop()
        self.active_label.hide()
        self.calib_loop_button.setText("Start Calib Loop")
        self.calib_loop_button.setStyleSheet("background-color: #8e44ad; color: white; font-size: 11px; padding: 3px 6px;")
        self.calib_loop_duration_spinbox.setEnabled(True)
        self.status_label.setText("Status: Calibration loop stopped.")
        self.send_led_command("4")

    def resizeEvent(self, event):
        """Ensures the overlay labels resize with the main window."""
        super().resizeEvent(event)
        self.danger_label.setGeometry(0, 0, self.width(), self.height())
        self.countdown_label.setGeometry(0, 0, self.width(), self.height())
        self.preparing_label.setGeometry(0, 0, self.width(), self.height())
        self.no_midi_label.setGeometry(0, 0, self.width(), self.height())
        if self.save_notification_label.isVisible():
            center_x = (self.width() - self.save_notification_label.width()) // 2
            center_y = (self.height() - self.save_notification_label.height()) // 2
            self.save_notification_label.move(center_x, center_y)
    
    def closeEvent(self, event):
        """Handles the application close event."""
        # Save the current session and config.
        self.save_session()
        self.save_config()
        
        # Stop background threads gracefully.
        self.hotkey_listener.stop()
        self.hotkey_listener.wait()
        self.stop_all_activity()

        # Close the Arduino serial connection if open.
        if self.arduino_serial is not None and self.arduino_serial.is_open:
            self.send_led_command("4")  # Turn all LEDs off before closing
            self.arduino_serial.close()
        
        event.accept()

# --- Main Execution Block ---
if __name__ == '__main__':
    # Create the QApplication instance.
    app = QApplication(sys.argv)
    # Set a base style and apply the custom dark stylesheet.
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)
    # Create and show the main window maximised so all controls are visible on
    # a 1920×1080 laptop display without any scrolling.
    controller = LiveController()
    controller.showMaximized()
    # Start the application's event loop.
    sys.exit(app.exec())
