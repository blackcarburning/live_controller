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
from collections import deque

# --- Third-Party Library Imports ---
# This solution requires the 'keyboard' and 'psutil' libraries.
# If you see a "ModuleNotFoundError", please install them by running this command
# in your command prompt:
#
# python -m pip install keyboard psutil rtmidi-python
#
import rtmidi                  # For sending MIDI messages
import keyboard                # For global hotkey listening
import psutil                  # For setting process priority
import serial                  # For Arduino serial communication
from serial.tools import list_ports  # For discovering serial ports

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTableWidget, QTableWidgetItem, QLineEdit, QHeaderView, 
                             QGroupBox, QLabel, QFileDialog, QSizePolicy, QComboBox,
                             QAbstractButton, QSlider, QAbstractItemView, QCheckBox,
                             QGridLayout, QRadioButton, QSpinBox, QColorDialog)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QPoint, QEasingCurve, pyqtProperty, QTimer
from PyQt6.QtGui import QFont, QGuiApplication, QPainter, QColor, QBrush, QPen

# --- Core Application Configuration ---
# File paths for external media players
MPV_PATH = r"c:\mpv\mpv.exe"
MPLAYER_PATH = r"d:\mplayer\mplayer.exe"

# JSON files for persistent storage of track-specific data
BPM_STORE_FILE = "bpm_store.json"
TRACK_NAME_STORE_FILE = "track_names.json"

# Configuration and session files for the application state
CONFIG_FILE = "config.json"
SESSION_FILE = "session.json"
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

class MidiSyncWorker(QThread):
    """The main worker thread for handling synchronized mpv playback and MIDI clock output."""
    finished = pyqtSignal()          # Emitted when playback is finished.
    error = pyqtSignal(str)          # Emitted on error.
    status_update = pyqtSignal(str)  # For status messages.
    ipc_socket_path = pyqtSignal(str)# Emits the path to the mpv IPC socket.

    def __init__(self, video_file, bpm, display_num, preload_time, midi_offset_ms, 
                 send_start_port1, send_start_port2, send_start_port3, timing_method,
                 require_midi=True, max_duration_sec=0):
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
        self.bpm_data = self.load_json_store(BPM_STORE_FILE)
        self.track_name_data = self.load_json_store(TRACK_NAME_STORE_FILE)
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
        self.showFullScreen()
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
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(4)
        
        # --- Top Bar (Title, Mode Switch) ---
        top_bar_layout = QHBoxLayout()
        # Left side for "ACTIVE" label
        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0,0,0,0)
        self.active_label = QLabel("ACTIVE", self)
        self.active_label.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
        self.active_label.setStyleSheet("color: #27ae60;")
        self.active_label.hide()
        left_layout.addWidget(self.active_label)
        left_layout.addStretch(1)
        # Center for title and running time
        title_layout = QVBoxLayout()
        title_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = QLabel("Untitled Setlist")
        self.title_label.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self.running_time_label = QLabel(f"Total Running Time (incl. {TRACK_OVERHEAD_SECONDS}s overhead/track): 00:00:00")
        self.running_time_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
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
        self.edit_mode_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.live_mode_slider = Switch()
        self.live_mode_slider.toggled.connect(self.toggle_live_mode)
        self.live_mode_label = QLabel("LIVE")
        self.live_mode_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
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
        self.table.setColumnWidth(0, 80); self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 80); self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 80); self.table.setColumnWidth(6, 80); self.table.setColumnWidth(7, 100)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.rows_reordered.connect(self.reorder_tracks)
        
        # --- Right-side Control Panel ---
        controls_area = QVBoxLayout()
        controls_area.setSpacing(4)
        
        # --- Playback & Setlist Group ---
        main_controls_group = QGroupBox("")
        main_controls_layout = QVBoxLayout()
        main_controls_layout.setContentsMargins(6, 6, 6, 6)
        main_controls_layout.setSpacing(4)
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
        self.stop_button.setStyleSheet(f"background-color: #e74c3c; color: white; font-size: 12px; font-weight: bold; padding: 3px 6px;")
        self.stop_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.stop_button.clicked.connect(self.stop_all_activity)
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
        main_controls_layout.addWidget(self.stop_button)
        main_controls_layout.addLayout(add_buttons_layout)
        main_controls_layout.addWidget(self.undo_button)
        main_controls_layout.addLayout(setlist_name_layout)
        main_controls_layout.addWidget(self.save_button)
        main_controls_layout.addWidget(self.load_button)
        main_controls_group.setLayout(main_controls_layout)
        
        # --- Settings Group (Compact Grid Layout) ---
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout()
        settings_layout.setContentsMargins(6, 6, 6, 6)
        settings_layout.setSpacing(3)

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
        test_track_layout.setContentsMargins(6, 6, 6, 6)
        test_track_layout.setSpacing(4)
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
        calib_loop_layout.setContentsMargins(6, 6, 6, 6)
        calib_loop_layout.setSpacing(4)
        calib_loop_layout.addWidget(QLabel("Loop:"))
        self.calib_loop_duration_spinbox = QSpinBox()
        self.calib_loop_duration_spinbox.setRange(1, 20)
        self.calib_loop_duration_spinbox.setValue(5)
        self.calib_loop_duration_spinbox.setSuffix(" s")
        self.calib_loop_duration_spinbox.setToolTip("Duration of each calibration loop (1–20 seconds)")
        calib_loop_layout.addWidget(self.calib_loop_duration_spinbox)
        self.calib_loop_button = QPushButton("Start Calib Loop")
        self.calib_loop_button.setStyleSheet("background-color: #8e44ad; color: white; font-size: 11px; padding: 3px 6px;")
        self.calib_loop_button.setEnabled(False)
        self.calib_loop_button.clicked.connect(self.toggle_calib_loop)
        calib_loop_layout.addWidget(self.calib_loop_button)
        calib_loop_group.setLayout(calib_loop_layout)

        # --- Overlay Colours Group ---
        overlay_colours_group = QGroupBox("Overlay Colours")
        overlay_colours_layout = QGridLayout()
        overlay_colours_layout.setContentsMargins(6, 6, 6, 6)
        overlay_colours_layout.setSpacing(4)

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
        midi_test_grid_layout.setContentsMargins(6, 6, 6, 6)
        midi_test_grid_layout.setSpacing(3)
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

        # --- Application Group (Quit) ---
        app_group = QGroupBox("Application")
        app_layout = QVBoxLayout()
        app_layout.setContentsMargins(6, 6, 6, 6)
        app_layout.setSpacing(4)
        self.quit_button = QPushButton("Quit")
        self.quit_button.clicked.connect(self.close)
        app_layout.addWidget(self.quit_button)
        app_group.setLayout(app_layout)
        
        # Add all groups to the control panel area.
        controls_area.addWidget(main_controls_group)
        controls_area.addWidget(settings_group)
        controls_area.addWidget(test_track_group)
        controls_area.addWidget(calib_loop_group)
        controls_area.addWidget(overlay_colours_group)
        controls_area.addWidget(midi_test_group)
        controls_area.addWidget(app_group)
        
        # --- Assemble Main Layout ---
        main_layout.addWidget(self.table, 4) # Table takes 4/5 of the width
        main_layout.addLayout(controls_area, 1) # Controls take 1/5
        
        # --- Status Bar ---
        self.status_label = QLabel("Status: Welcome!")
        self.status_label.setStyleSheet("font-style: italic; color: #888; font-size: 14px;")
        
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
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)
    
    def apply_config_to_ui(self):
        """Sets UI elements based on the loaded general config."""
        self.display_combo.setCurrentText(str(self.config.get("display", DEFAULT_VIDEO_SCREEN_NUMBER)))
        self.preload_combo.setCurrentText(str(self.config.get("preload", DEFAULT_LOAD_DELAY_SECONDS)))
        self.check_display_setting()

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

        lines = []
        total_seconds = 0
        for row_index, item in enumerate(self.tracks):
            if item['type'] == 'divider':
                lines.append("")
                lines.append(item.get('text', 'ENCORE'))
                lines.append("")
            else:
                duration = item.get('duration', 0)
                total_seconds += duration
                name_widget = self.table.cellWidget(row_index, 1)
                bpm_widget = self.table.cellWidget(row_index, 3)
                track_name = (name_widget.text() if name_widget else "").replace('_', ' ')
                bpm = bpm_widget.text() if bpm_widget else ""
                duration_str = self.format_duration(duration)
                lines.append(f"{track_name} ({duration_str}/{bpm})")

        lines.append("")
        lines.append(f"Total Time: {self.format_duration(total_seconds, show_hours=True)}")
        track_count = len([t for t in self.tracks if t['type'] == 'track'])
        total_with_overhead = total_seconds + (track_count * TRACK_OVERHEAD_SECONDS)
        lines.append(f"Total Time (incl. {TRACK_OVERHEAD_SECONDS}s gap between songs): {self.format_duration(total_with_overhead, show_hours=True)}")

        setlist_name = self.title_label.text()
        safe_name = re.sub(r'[\\/*?:"<>|]', '', setlist_name).strip()
        if not safe_name:
            safe_name = "setlist"
        filename = f"{safe_name}_setlist.txt"
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
        else: # It's the test track
            self.test_file_label.setStyleSheet("font-weight: bold; color: #27ae60;")

        # Start the flashing "ACTIVE" label.
        self.active_flash_timer.start()
        
        # Create and start the worker thread.
        require_midi = self.require_midi_checkbox.isChecked()
        self.worker = MidiSyncWorker(track_path, bpm, display_num, preload_time, midi_offset, 
                                     send_start_port1, send_start_port2, send_start_port3, timing_method,
                                     require_midi)
        self.worker.status_update.connect(self.status_label.setText)
        self.worker.error.connect(lambda msg: self.status_label.setText(f"ERROR: {msg}"))
        self.worker.finished.connect(self.on_playback_finished)
        self.worker.ipc_socket_path.connect(self.set_ipc_socket)
        self.send_led_command("3")  # LED 3 (orange): song is playing
        self.send_led_command("6")  # LED 6 (green): track active indicator
        self.worker.start()

    def set_ipc_socket(self, path):
        """Receives the IPC socket path from the worker thread."""
        self.current_ipc_socket = path

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

        self.calib_loop_worker = MidiSyncWorker(
            self.test_track_path, bpm, display_num, preload_time, midi_offset,
            True, True, True, timing_method, require_midi,
            max_duration_sec=duration
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
    # Create and show the main window.
    controller = LiveController()
    controller.show()
    # Start the application's event loop.
    sys.exit(app.exec())
