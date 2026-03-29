# live_fallback.py
#
# Author: blackcarburning
#
# Description:
# A stripped-down video-only live performance controller. This is a cut-down
# version of live_controller.py with all MIDI, Arduino, psutil, and ctypes
# dependencies removed. It uses mpv for video playback, PyQt6 for the GUI,
# and supports global hotkeys, setlist management, and full session persistence.
#
# Install required dependencies with:
#   python -m pip install keyboard

# --- Standard Library Imports ---
import sys
import os
import re
import subprocess
import time
import json
from collections import deque

# --- Third-Party Library Imports ---
# This solution requires the 'keyboard' library.
# If you see a "ModuleNotFoundError", please install it by running this command
# in your command prompt:
#
# python -m pip install keyboard
#
import keyboard                # For global hotkey listening

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QLineEdit, QHeaderView,
                             QGroupBox, QLabel, QFileDialog, QSizePolicy, QComboBox,
                             QAbstractButton, QAbstractItemView, QCheckBox,
                             QGridLayout, QSpinBox, QColorDialog)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QPoint, QEasingCurve, pyqtProperty, QTimer
from PyQt6.QtGui import QFont, QGuiApplication, QPainter, QColor, QBrush, QPen

# --- Core Application Configuration ---
# File paths for external media players
MPV_PATH = r"c:\mpv\mpv.exe"
MPLAYER_PATH = r"d:\mplayer\mplayer.exe"

# JSON files for persistent storage of track-specific data
TRACK_NAME_STORE_FILE = "track_names.json"

# Configuration and session files for the application state
# These are separate from the main app's config.json / session.json
CONFIG_FILE = "fallback_config.json"
SESSION_FILE = "fallback_session.json"
SETLISTS_DIR = "setlists"

# Default settings for playback and display
DEFAULT_VIDEO_SCREEN_NUMBER = 1
DEFAULT_LOAD_DELAY_SECONDS = 5
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
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555;
    border-radius: 4px;
}
QCheckBox::indicator:checked {
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

class VideoPlaybackWorker(QThread):
    """A worker thread for managing video/audio playback via mpv."""
    finished = pyqtSignal()          # Emitted when playback is finished.
    error = pyqtSignal(str)          # Emitted on error.
    status_update = pyqtSignal(str)  # For status messages.
    ipc_socket_path = pyqtSignal(str)# Emits the path to the mpv IPC socket.

    def __init__(self, video_file, display_num, preload_time):
        super().__init__()
        self.video_file = video_file
        self.display_num = display_num
        self.preload_time = preload_time
        self.mpv_process = None
        self._is_running = True

    def stop(self):
        """Stops the playback loop."""
        self._is_running = False

    def run(self):
        """Launches mpv, waits for preload, unpauses, then monitors until done."""
        # --- Pre-flight checks ---
        if not os.path.exists(MPV_PATH):
            self.error.emit(f"mpv not found at '{MPV_PATH}'")
            return
        if not os.path.exists(self.video_file):
            self.error.emit(f"File not found: '{self.video_file}'")
            return

        # Create a unique IPC socket name for this mpv instance.
        socket_name = f"mpv_socket_{int(time.time())}"
        full_socket_path = fr'\\.\pipe\{socket_name}'
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

        try:
            # Launch mpv in paused mode.
            self.status_update.emit(f"Starting mpv on screen {self.display_num}...")
            self.mpv_process = subprocess.Popen(mpv_cmd)
            self.ipc_socket_path.emit(full_socket_path)

            # Wait for the preload time before unpausing.
            self.status_update.emit(f"Pre-loading for {self.preload_time}s...")
            end_time = time.perf_counter() + self.preload_time
            while time.perf_counter() < end_time and self._is_running:
                if self.mpv_process.poll() is not None:
                    raise InterruptedError("mpv closed prematurely during preload")
                time.sleep(0.1)

            if not self._is_running:
                raise InterruptedError("Playback stopped by user during preload")

            # Unpause mpv via its IPC socket.
            self.status_update.emit(f"PLAYING: {os.path.basename(self.video_file)}")
            with open(full_socket_path, "w", encoding='utf-8') as ipc:
                ipc.write('{ "command": ["set_property", "pause", false] }\n')

            # Poll until mpv exits or is stopped.
            while self.mpv_process.poll() is None and self._is_running:
                time.sleep(0.1)

            if self._is_running:
                self.status_update.emit("mpv closed. Stopping.")
            else:
                self.status_update.emit("Playback stopped by user.")

        except Exception as e:
            self.error.emit(f"Playback error: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        """Cleans up the mpv process."""
        self.status_update.emit("Cleaning up...")
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

class LiveFallback(QWidget):
    """The main application window and controller (video-only fallback)."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live Fallback - blackcarburning - Video Only")

        # --- Initialize application state and data ---
        self.config = self.load_config()
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

        # --- Build UI and start background services ---
        self.setup_ui()
        self.apply_config_to_ui()
        self.showFullScreen()
        self.hotkey_listener = GlobalHotkeyListener()
        self.hotkey_listener.hotkey_pressed.connect(self.on_global_hotkey)
        self.hotkey_listener.start()
        self.load_session()

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

        self.save_notification_label = QLabel(self)
        self.save_notification_label.setStyleSheet("background-color: #27ae60; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 10px;")
        self.save_notification_label.hide()

        # --- Main Content Area (Table and Controls) ---
        main_layout = QHBoxLayout()
        self.table = DraggableTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Hotkey", "Track Name", "Linked", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 80); self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 100)
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

        font_size_layout = QHBoxLayout()
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 36)
        self.font_size_spinbox.setValue(self.current_table_font_size)
        self.apply_font_button = QPushButton("Apply"); self.apply_font_button.clicked.connect(self.apply_table_font_size)
        font_size_layout.addWidget(self.font_size_spinbox); font_size_layout.addWidget(self.apply_font_button)
        settings_layout.addWidget(QLabel("List Font Size:"), 4, 0)
        settings_layout.addLayout(font_size_layout, 4, 1)

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
        self.play_test_button = QPushButton("Play Test Track (t)")
        self.play_test_button.clicked.connect(self.play_test_track)
        self.play_test_button.setEnabled(False)
        test_track_layout.addWidget(self.test_file_button)
        test_track_layout.addWidget(self.test_file_label, 1)
        test_track_layout.addStretch(1)
        test_track_layout.addWidget(self.play_test_button)
        test_track_group.setLayout(test_track_layout)

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
        controls_area.addWidget(overlay_colours_group)
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
            for col in [1]: # Track Name
                widget = self.table.cellWidget(row, col)
                if isinstance(widget, QLineEdit):
                    widget.setFont(new_font)

        self.status_label.setText(f"Status: Font size set to {self.current_table_font_size}pt.")

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
        self.quit_button.setEnabled(is_edit_mode)
        self.export_setlist_button.setEnabled(is_edit_mode)
        self.setlist_name_input.setEnabled(is_edit_mode)
        self.table.setDragEnabled(is_edit_mode)
        self.rename_button.setEnabled(is_edit_mode)
        self.test_file_button.setEnabled(is_edit_mode)
        self.play_test_button.setEnabled(is_edit_mode and self.test_track_path is not None)
        self.font_size_spinbox.setEnabled(is_edit_mode)
        self.apply_font_button.setEnabled(is_edit_mode)
        self.count_in_color_button.setEnabled(is_edit_mode)
        self.count_in_font_spinbox.setEnabled(is_edit_mode)
        self.track_play_color_button.setEnabled(is_edit_mode)
        self.track_play_font_spinbox.setEnabled(is_edit_mode)

        # Enable/disable the widgets inside the table rows.
        for i in range(self.table.rowCount()):
            if i < len(self.tracks):
                item = self.tracks[i]
                if item['type'] == 'track':
                    # Columns with widgets: TrackName, Linked, Actions
                    for col in [1, 2, 3]:
                        if widget := self.table.cellWidget(i, col):
                            widget.setEnabled(is_edit_mode)

        # Update UI text and colors to reflect the current mode.
        self.live_mode_label.setStyleSheet("color: #d63031; font-weight: bold;" if self.is_live_mode else "color: #888;")
        self.edit_mode_label.setStyleSheet("color: #00b894; font-weight: bold;" if is_edit_mode else "color: #888;")
        self.status_label.setText("Status: LIVE MODE - Hotkeys are active." if self.is_live_mode else "Status: EDIT MODE - Hotkeys are disabled.")

    def _generate_hotkeys(self):
        """Generates a list of available hotkeys (1-9, a-z, excluding q, t, and i)."""
        keys = [str(i) for i in range(1, 10)] + [chr(i) for i in range(ord('a'), ord('z') + 1)]
        keys.remove('q') # Reserved for STOP
        keys.remove('t') # Reserved for PLAY TEST
        keys.remove('i') # Excluded: visually confused with '1'
        return keys

    def load_config(self):
        """Loads general application configuration from fallback_config.json."""
        defaults = {"display": DEFAULT_VIDEO_SCREEN_NUMBER, "preload": DEFAULT_LOAD_DELAY_SECONDS}
        if not os.path.exists(CONFIG_FILE): return defaults
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                defaults.update(config)
                return defaults
        except (json.JSONDecodeError, FileNotFoundError):
            return defaults

    def save_config(self):
        """Saves general application configuration to fallback_config.json."""
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
        """Saves the current setlist and settings to fallback_session.json."""
        session_data = {
            'setlist_name': self.title_label.text(),
            'tracks': self.tracks,
            'undo_history': list(self.undo_history),
            'test_track_path': self.test_track_path,
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
        """Loads the last session from fallback_session.json on startup."""
        if not os.path.exists(SESSION_FILE):
            self.status_label.setText("Status: No previous session found. Welcome!")
            self.count_in_combo.setCurrentText(str(DEFAULT_COUNT_IN_SECONDS))
            self.count_in_test_checkbox.setChecked(True)
            return
        try:
            with open(SESSION_FILE, 'r') as f:
                session_data = json.load(f)

            # Restore all settings from the session data.
            self.count_in_combo.setCurrentText(str(session_data.get('count_in_duration', DEFAULT_COUNT_IN_SECONDS)))
            self.count_in_test_checkbox.setChecked(True) # Always check this on startup

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
        files, _ = QFileDialog.getOpenFileNames(self, "Select Track Files", "d:\\", "Media Files (*.mov *.mp4 *.wav);;Video Files (*.mov *.mp4);;Audio Files (*.wav)")
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
                self.table.setCellWidget(i, 3, button_container)
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

                remove_button = QPushButton("X"); remove_button.clicked.connect(lambda checked, i=i: self.remove_item(i))
                remove_button.setFixedSize(20, 20)
                remove_button.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; border-radius: 4px; font-size: 12px;")
                button_container = QWidget()
                button_layout = QHBoxLayout(button_container)
                button_layout.addWidget(remove_button)
                button_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                button_layout.setContentsMargins(0,0,0,0)
                button_container.setToolTip(tooltip_text)
                self.table.setCellWidget(i, 3, button_container)

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
                if col in [2, 3]:
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
        # MIDI-related fields (midi_offset, timing_method, BPM/port data) are ignored.
        if isinstance(loaded_data, dict):
            tracks_data = loaded_data.get('tracks', [])
            self.undo_history = deque(loaded_data.get('undo_history', []), maxlen=MAX_UNDO_LEVELS)
            self.count_in_combo.setCurrentText(str(loaded_data.get('count_in_duration', DEFAULT_COUNT_IN_SECONDS)))
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
                track_name = (name_widget.text() if name_widget else "").replace('_', ' ')
                duration_str = self.format_duration(duration)
                lines.append(f"{track_name} ({duration_str})")

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

        # If playback is active, only 'q' (STOP) is allowed.
        if self.worker and self.worker.isRunning() or self.countdown_timer.isActive():
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
        if self.worker and self.worker.isRunning():
            self.show_danger_message(); return
        if self.tracks[row_index]['type'] == 'divider': return

        is_countdown_track = (row_index == 0 and self.count_in_test_checkbox.isChecked())

        # Show the "Preparing" overlay unless it's a countdown track.
        if not is_countdown_track:
            track_name_widget = self.table.cellWidget(row_index, 1)
            self.show_preparing_message(track_name_widget.text())

        if is_countdown_track:
            self.start_countdown(row_index)
        else:
            track = self.tracks[row_index]
            self.execute_playback(track, row_index)

    def start_countdown(self, row_index):
        """Starts the visual countdown timer for the first track."""
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
            self.execute_playback(track, row_index)

    def execute_playback(self, track_data, row_index=None):
        """Creates and starts a VideoPlaybackWorker to handle playback."""
        try:
            # Gather all necessary parameters from the UI.
            display_num = int(self.display_combo.currentText())
            preload_time = int(self.preload_combo.currentText())
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
        self.worker = VideoPlaybackWorker(track_path, display_num, preload_time)
        self.worker.status_update.connect(self.status_label.setText)
        self.worker.error.connect(lambda msg: self.status_label.setText(f"ERROR: {msg}"))
        self.worker.finished.connect(self.on_playback_finished)
        self.worker.ipc_socket_path.connect(self.set_ipc_socket)
        self.worker.start()

    def set_ipc_socket(self, path):
        """Receives the IPC socket path from the worker thread."""
        self.current_ipc_socket = path

    def stop_all_activity(self):
        """Centralized method to stop any running playback or countdown."""
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

        self.active_flash_timer.stop()
        self.active_label.hide()

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
                    self.execute_playback(next_track, next_row)

    def show_danger_message(self):
        """Shows a large, temporary warning overlay."""
        self.danger_label.raise_()
        self.danger_label.show()
        QTimer.singleShot(2500, self.danger_label.hide)

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

    def play_test_track(self):
        """Plays the selected test track."""
        if self.worker and self.worker.isRunning():
            self.show_danger_message(); return
        if not self.test_track_path:
            self.status_label.setText("Status: No test track selected."); return

        self.show_preparing_message(os.path.basename(self.test_track_path))
        test_track_data = {'path': self.test_track_path}
        self.execute_playback(test_track_data)

    def resizeEvent(self, event):
        """Ensures the overlay labels resize with the main window."""
        super().resizeEvent(event)
        self.danger_label.setGeometry(0, 0, self.width(), self.height())
        self.countdown_label.setGeometry(0, 0, self.width(), self.height())
        self.preparing_label.setGeometry(0, 0, self.width(), self.height())
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

        event.accept()

# --- Main Execution Block ---
if __name__ == '__main__':
    # Create the QApplication instance.
    app = QApplication(sys.argv)
    # Set a base style and apply the custom dark stylesheet.
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)
    # Create and show the main window.
    controller = LiveFallback()
    controller.show()
    # Start the application's event loop.
    sys.exit(app.exec())
