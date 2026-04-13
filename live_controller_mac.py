# live_controller_mac.py
#
# Author: blackcarburning
#
# Description:
# A macOS-compatible version of live_fallback.py.
# A stripped-down video-only live performance controller for macOS.
# Uses mpv for video playback, PyQt6 for the GUI, and supports global
# hotkeys, setlist management, and full session persistence.
#
# macOS Installation
# ------------------
# 1. Install system packages via Homebrew:
#       brew install mpv mplayer
#
# 2. Install Python packages:
#       pip install PyQt6 pynput
#
# 3. Grant Accessibility / Input Monitoring permissions:
#    Global hotkeys require macOS to trust your terminal or Python runtime.
#    Go to: System Settings > Privacy & Security > Accessibility
#    Add your terminal app (e.g. Terminal, iTerm2) or the Python binary.
#    You may also need to add it under Input Monitoring in the same pane.
#
# 4. Run:
#       python live_controller_mac.py

# --- Standard Library Imports ---
import sys
import os
import re
import signal
import socket
import subprocess
import tempfile
import time
import json
import shutil
from collections import deque

# --- Third-Party Library Imports ---
# Requires: pynput
# Install with: pip install pynput
from pynput import keyboard as pynput_keyboard

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QLineEdit, QHeaderView,
                             QGroupBox, QLabel, QFileDialog, QSizePolicy, QComboBox,
                             QAbstractButton, QAbstractItemView, QCheckBox,
                             QGridLayout, QSpinBox, QColorDialog)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QPoint, QEasingCurve, pyqtProperty, QTimer
from PyQt6.QtGui import QFont, QGuiApplication, QPainter, QColor, QBrush, QPen


# --- Executable Path Detection ---
def _find_executable(name):
    """Find an executable in PATH, falling back to common Homebrew locations."""
    found = shutil.which(name)
    if found:
        return found
    for prefix in ['/opt/homebrew/bin', '/usr/local/bin']:
        candidate = os.path.join(prefix, name)
        if os.path.exists(candidate):
            return candidate
    return name  # Return bare name; subprocess will raise a clear error if missing.


MPV_PATH = _find_executable('mpv')
MPLAYER_PATH = _find_executable('mplayer')

# JSON files for persistent storage — mac-specific names avoid clobbering Windows data.
TRACK_NAME_STORE_FILE = "mac_track_names.json"
CONFIG_FILE = "mac_fallback_config.json"
SESSION_FILE = "mac_fallback_session.json"
SETLISTS_DIR = "setlists"

# Default settings for playback and display
DEFAULT_VIDEO_SCREEN_NUMBER = 1
DEFAULT_LOAD_DELAY_SECONDS = 5
DEFAULT_COUNT_IN_SECONDS = 20
DEFAULT_TABLE_FONT_SIZE = 11           # Compact: was 16 on Windows
DEFAULT_COUNT_IN_FONT_SIZE = 120       # Compact: was 250 on Windows
DEFAULT_TRACK_PLAY_FONT_SIZE = 50      # Compact: was 80 on Windows
DEFAULT_COUNT_IN_BG_COLOR = "#c80000"
DEFAULT_TRACK_PLAY_BG_COLOR = "#00c800"
TRACK_OVERHEAD_SECONDS = 15
MAX_UNDO_LEVELS = 30

# UI and timing constants
PREPARING_OVERLAY_DURATION_MS = 2000
ACTIVE_FLASH_INTERVAL_MS = 500
SAVE_POPUP_DURATION_MS = 3000

# Default directory for file dialogs (macOS Movies folder or home dir)
_DEFAULT_DIALOG_DIR = os.path.join(os.path.expanduser("~"), "Movies")
if not os.path.isdir(_DEFAULT_DIALOG_DIR):
    _DEFAULT_DIALOG_DIR = os.path.expanduser("~")

# --- Modern macOS-Dark Stylesheet ---
MODERN_STYLESHEET = """
QWidget {
    background-color: #1c1c1e;
    color: #f2f2f7;
    font-family: 'Helvetica Neue', 'Arial', sans-serif;
    font-size: 12px;
}
QGroupBox {
    font-size: 9px;
    font-weight: 600;
    color: #636366;
    border: 1px solid #38383a;
    border-radius: 10px;
    margin-top: 8px;
    padding-top: 4px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #636366;
}
QLabel {
    background-color: transparent;
    color: #f2f2f7;
}
QPushButton {
    background-color: #2c2c2e;
    color: #f2f2f7;
    border: 1px solid #3a3a3c;
    padding: 5px 12px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #3a3a3c;
    border-color: #636366;
}
QPushButton:pressed {
    background-color: #48484a;
}
QPushButton:disabled {
    background-color: #1c1c1e;
    color: #3a3a3c;
    border-color: #2c2c2e;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #2c2c2e;
    border: 1px solid #38383a;
    border-radius: 6px;
    padding: 4px 8px;
    color: #f2f2f7;
    font-size: 12px;
    selection-background-color: #0a84ff;
    selection-color: #ffffff;
}
QLineEdit:focus {
    border-color: #0a84ff;
}
QComboBox::drop-down {
    border: none;
    padding-right: 4px;
}
QTableWidget {
    background-color: #2c2c2e;
    gridline-color: #38383a;
    border: 1px solid #38383a;
    border-radius: 8px;
    alternate-background-color: #323234;
}
QHeaderView::section {
    background-color: #1c1c1e;
    color: #636366;
    padding: 6px 4px;
    border: none;
    border-bottom: 1px solid #38383a;
    font-size: 10px;
    font-weight: 600;
}
QTableWidget::item {
    padding: 3px 6px;
}
QTableWidget::item:selected {
    background-color: #0a84ff;
    color: #ffffff;
}
QScrollBar:vertical {
    background-color: #1c1c1e;
    width: 6px;
    border-radius: 3px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background-color: #48484a;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background-color: #1c1c1e;
    height: 6px;
    border-radius: 3px;
}
QScrollBar::handle:horizontal {
    background-color: #48484a;
    border-radius: 3px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1.5px solid #48484a;
    border-radius: 4px;
    background-color: #2c2c2e;
}
QCheckBox::indicator:checked {
    background-color: #0a84ff;
    border-color: #0a84ff;
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: transparent;
    border: none;
    width: 14px;
}
"""

# Branded logo HTML — ▲ (U+25B2) replaces each A in KATTMAN CONTROL
KATTMAN_LOGO_HTML = (
    '<span style="color:#f2f2f7; font-weight:700; font-size:22px; letter-spacing:4px;">'
    'K<span style="color:#0a84ff;">&#9650;</span>TTM'
    '<span style="color:#0a84ff;">&#9650;</span>N&nbsp;&nbsp;CONTROL'
    '</span>'
)



def _send_ipc_command(socket_path, command_str):
    """Sends a JSON command string to mpv via its Unix domain socket."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(socket_path)
        sock.sendall((command_str + '\n').encode('utf-8'))
        sock.close()
    except Exception as e:
        print(f"mpv IPC error: {e}")


class DraggableTableWidget(QTableWidget):
    """A QTableWidget subclass that supports drag-and-drop row reordering."""
    rows_reordered = pyqtSignal(int, int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropOverwriteMode(False)
        self.source_row = -1

    def startDrag(self, supportedActions):
        self.source_row = self.currentRow()
        super().startDrag(supportedActions)

    def dropEvent(self, event):
        if not event.isAccepted() and event.source() == self:
            dest_row = self.indexAt(event.position().toPoint()).row()
            if dest_row < 0:
                dest_row = self.rowCount() - 1
            if self.source_row != dest_row:
                self.rows_reordered.emit(self.source_row, dest_row)
            event.accept()
        else:
            super().dropEvent(event)


class GlobalHotkeyListener(QThread):
    """A dedicated QThread to listen for keyboard events globally using pynput.

    NOTE: On macOS, global key capture outside the active application requires
    Accessibility (and possibly Input Monitoring) permissions.  Grant them in:
      System Settings > Privacy & Security > Accessibility
    for whichever terminal or Python binary you use to run this script.
    """
    hotkey_pressed = pyqtSignal(str)
    listener_failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._listener = None

    def run(self):
        def on_press(key):
            try:
                # key.char is set for regular printable characters (a-z, 0-9, ^, etc.)
                if hasattr(key, 'char') and key.char:
                    self.hotkey_pressed.emit(key.char)
            except Exception:
                pass

        try:
            with pynput_keyboard.Listener(on_press=on_press) as listener:
                self._listener = listener
                listener.join()
        except Exception as exc:
            self.listener_failed.emit(
                f"Global hotkeys unavailable: {exc}. "
                "Grant Accessibility/Input Monitoring permissions in "
                "System Settings > Privacy & Security."
            )

    def stop(self):
        """Stops the pynput listener."""
        if self._listener:
            self._listener.stop()


class VideoPlaybackWorker(QThread):
    """A worker thread for managing video/audio playback via mpv (macOS)."""
    finished = pyqtSignal()
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)
    ipc_socket_path = pyqtSignal(str)

    def __init__(self, video_file, display_num, preload_time):
        super().__init__()
        self.video_file = video_file
        self.display_num = display_num
        self.preload_time = preload_time
        self.mpv_process = None
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        """Launches mpv (paused), waits for preload, unpauses via Unix socket, then monitors."""
        if not os.path.exists(self.video_file):
            self.error.emit(f"File not found: '{self.video_file}'")
            return

        mpv_bin = MPV_PATH
        if not os.path.isabs(mpv_bin) or not os.path.exists(mpv_bin):
            # Try to resolve again at runtime in case PATH changed.
            mpv_bin = _find_executable('mpv')

        # Unix domain socket in the system temp directory.
        socket_name = f"mpv_socket_{int(time.time())}"
        full_socket_path = os.path.join(tempfile.gettempdir(), socket_name)

        file_ext = os.path.splitext(self.video_file)[1].lower()
        is_audio_only = file_ext == '.wav'

        if is_audio_only:
            mpv_cmd = [
                mpv_bin,
                f"--input-ipc-server={full_socket_path}",
                "--pause",
                "--no-video",
                "--really-quiet",
                "--keep-open=no",
                self.video_file,
            ]
        else:
            mpv_cmd = [
                mpv_bin,
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
                self.video_file,
            ]

        try:
            self.status_update.emit(f"Starting mpv on screen {self.display_num}...")
            # No CREATE_NO_WINDOW or other Windows flags on macOS.
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

            # Wait for the Unix socket file to appear (up to 5 additional seconds).
            socket_deadline = time.perf_counter() + 5.0
            while not os.path.exists(full_socket_path) and time.perf_counter() < socket_deadline:
                time.sleep(0.05)

            # Unpause mpv via the Unix domain socket.
            self.status_update.emit(f"PLAYING: {os.path.basename(self.video_file)}")
            _send_ipc_command(full_socket_path, '{ "command": ["set_property", "pause", false] }')

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
            self.cleanup(full_socket_path)

    def cleanup(self, socket_path=None):
        """Cleans up the mpv process and removes the Unix socket file."""
        self.status_update.emit("Cleaning up...")
        if self.mpv_process and self.mpv_process.poll() is None:
            self.mpv_process.terminate()
        if socket_path and os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except OSError:
                pass
        self.finished.emit()


class Switch(QAbstractButton):
    """A custom animated toggle switch widget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(52, 28)
        self._circle_pos = QPoint(2, 2)
        self.animation = QPropertyAnimation(self, b"circle_pos", self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        bg_color = QColor("#ff453a") if self.isChecked() else QColor("#30d158")
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(0, 0, self.width(), self.height(), self.height() / 2, self.height() / 2)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(self.circle_pos.x(), self.circle_pos.y(), 24, 24)

    @pyqtProperty(QPoint)
    def circle_pos(self):
        return self._circle_pos

    @circle_pos.setter
    def circle_pos(self, pos):
        self._circle_pos = pos
        self.update()

    def setChecked(self, checked):
        super().setChecked(checked)
        start_pos = QPoint(2, 2) if checked else QPoint(self.width() - 26, 2)
        end_pos = QPoint(self.width() - 26, 2) if checked else QPoint(2, 2)
        self.animation.setStartValue(start_pos)
        self.animation.setEndValue(end_pos)
        self.animation.start()


class LiveControllerMac(QWidget):
    """The main application window and controller — macOS version."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("KATTMAN CONTROL")

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

        self.current_table_font_size = DEFAULT_TABLE_FONT_SIZE
        self.playing_color = QColor("#30d158")
        self.default_color = QColor("#2c2c2e")
        self.count_in_bg_color = DEFAULT_COUNT_IN_BG_COLOR
        self.count_in_font_size = DEFAULT_COUNT_IN_FONT_SIZE
        self.track_play_bg_color = DEFAULT_TRACK_PLAY_BG_COLOR
        self.track_play_font_size = DEFAULT_TRACK_PLAY_FONT_SIZE

        self.countdown_timer = QTimer(self)
        self.countdown_seconds = 0
        self.countdown_connection = None

        self.active_flash_timer = QTimer(self)
        self.active_flash_timer.setInterval(ACTIVE_FLASH_INTERVAL_MS)
        self.active_flash_timer.timeout.connect(self.toggle_active_label_visibility)

        self.setup_ui()
        self.apply_config_to_ui()
        # Do NOT call showFullScreen() — use a regular resizable window for MacBook.
        self.hotkey_listener = None
        self._start_hotkey_listener()
        self.load_session()

    def setup_ui(self):
        """Constructs the entire user interface (compact layout for MacBook)."""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 8, 12, 8)
        self.layout.setSpacing(6)

        # --- Top Bar ---
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setContentsMargins(0, 0, 0, 0)

        # Left: ACTIVE flash label
        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.active_label = QLabel("ACTIVE", self)
        self.active_label.setFont(QFont("Helvetica Neue", 16, QFont.Weight.Bold))
        self.active_label.setStyleSheet("color: #30d158; letter-spacing: 2px;")
        self.active_label.hide()
        left_layout.addWidget(self.active_label)
        left_layout.addStretch(1)

        # Center: K▲TTM▲N CONTROL logo + setlist info stacked
        title_layout = QVBoxLayout()
        title_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.setSpacing(2)

        logo_label = QLabel()
        logo_label.setTextFormat(Qt.TextFormat.RichText)
        logo_label.setText(KATTMAN_LOGO_HTML)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("Untitled Setlist")
        self.title_label.setFont(QFont("Helvetica Neue", 12, QFont.Weight.Bold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("color: #aeaeb2;")

        self.running_time_label = QLabel(
            f"Total Running Time (incl. {TRACK_OVERHEAD_SECONDS}s overhead/track): 00:00:00"
        )
        self.running_time_label.setFont(QFont("Helvetica Neue", 9))
        self.running_time_label.setStyleSheet("color: #636366;")
        self.running_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.export_setlist_button = QPushButton("Export Set List")
        self.export_setlist_button.setStyleSheet(
            "background-color: #2a1040; color: #bf5af2; border: 1px solid #6e2c9e; "
            "font-size: 10px; padding: 3px 10px; border-radius: 5px;"
        )
        self.export_setlist_button.clicked.connect(self.export_setlist)

        title_layout.addWidget(logo_label)
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.running_time_label)
        title_layout.addWidget(self.export_setlist_button, 0, Qt.AlignmentFlag.AlignCenter)

        # Right: mode toggle
        right_container = QWidget()
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addStretch(1)
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(8)
        self.edit_mode_label = QLabel("EDIT")
        self.edit_mode_label.setFont(QFont("Helvetica Neue", 10, QFont.Weight.Bold))
        self.live_mode_slider = Switch()
        self.live_mode_slider.toggled.connect(self.toggle_live_mode)
        self.live_mode_label = QLabel("LIVE")
        self.live_mode_label.setFont(QFont("Helvetica Neue", 10, QFont.Weight.Bold))
        mode_layout.addWidget(self.edit_mode_label)
        mode_layout.addWidget(self.live_mode_slider)
        mode_layout.addWidget(self.live_mode_label)
        right_layout.addLayout(mode_layout)

        top_bar_layout.addWidget(left_container, 1)
        top_bar_layout.addLayout(title_layout, 2)
        top_bar_layout.addWidget(right_container, 1)

        # Thin separator beneath the top bar
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #38383a;")

        # --- Overlay Labels (full-window, always on top) ---
        self.danger_label = QLabel("DANGER!!\n\nSTOP PRESSING BUTTONS!\nAND GET YOUR HAIR CUT", self)
        self.danger_label.setFont(QFont("Helvetica Neue", 40, QFont.Weight.ExtraBold))
        self.danger_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.danger_label.setStyleSheet("background-color: rgba(255, 69, 58, 0.9); color: white; border-radius: 20px;")
        self.danger_label.hide()

        self.countdown_label = QLabel("", self)
        self.countdown_label.setFont(QFont("Helvetica Neue", DEFAULT_COUNT_IN_FONT_SIZE, QFont.Weight.ExtraBold))
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_label.setStyleSheet("background-color: rgba(200, 0, 0, 0.9); color: white; border-radius: 20px;")
        self.countdown_label.hide()

        self.preparing_label = QLabel("", self)
        self.preparing_label.setFont(QFont("Helvetica Neue", DEFAULT_TRACK_PLAY_FONT_SIZE, QFont.Weight.Bold))
        self.preparing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preparing_label.setStyleSheet("background-color: rgba(0, 200, 0, 0.85); color: white; border-radius: 20px;")
        self.preparing_label.hide()

        self.save_notification_label = QLabel(self)
        self.save_notification_label.setStyleSheet(
            "background-color: #1a3a2a; color: #30d158; font-size: 14px; font-weight: bold; "
            "padding: 12px 20px; border-radius: 10px; border: 1px solid #30d158;"
        )
        self.save_notification_label.hide()

        # --- Main Content: Table + Controls ---
        main_layout = QHBoxLayout()
        main_layout.setSpacing(10)
        self.table = DraggableTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Key", "Track Name", "Link", "Del"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(2, 42)
        self.table.setColumnWidth(3, 42)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.rows_reordered.connect(self.reorder_tracks)

        # --- Right-side Control Panel ---
        controls_area = QVBoxLayout()
        controls_area.setSpacing(6)

        # Playback & Setlist group
        main_controls_group = QGroupBox("Playback & Setlist")
        main_controls_layout = QVBoxLayout()
        main_controls_layout.setContentsMargins(8, 10, 8, 8)
        main_controls_layout.setSpacing(6)

        self.stop_button = QPushButton("■  STOP  (q)")
        self.stop_button.setStyleSheet(
            "background-color: #3a0a0a; color: #ff453a; border: 1px solid #7a1a1a; "
            "font-size: 12px; font-weight: 700; padding: 6px 12px; border-radius: 6px;"
        )
        self.stop_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.stop_button.clicked.connect(self.stop_all_activity)

        add_buttons_layout = QHBoxLayout()
        add_buttons_layout.setSpacing(6)
        self.add_button = QPushButton("+ Add Track(s)")
        self.add_button.setStyleSheet(
            "background-color: #0a2a4a; color: #0a84ff; border: 1px solid #1a4a7a; "
            "font-size: 11px; padding: 4px 8px; border-radius: 6px;"
        )
        self.add_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_button.clicked.connect(self.add_tracks)
        self.add_encore_button = QPushButton("+ Add Encore")
        self.add_encore_button.setStyleSheet(
            "background-color: #0a2a4a; color: #0a84ff; border: 1px solid #1a4a7a; "
            "font-size: 11px; padding: 4px 8px; border-radius: 6px;"
        )
        self.add_encore_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_encore_button.clicked.connect(self.add_encore_divider)
        add_buttons_layout.addWidget(self.add_button)
        add_buttons_layout.addWidget(self.add_encore_button)

        self.undo_button = QPushButton("↩  Undo Delete")
        self.undo_button.clicked.connect(self.undo_delete)
        self.undo_button.setEnabled(False)

        setlist_name_layout = QHBoxLayout()
        setlist_name_layout.setSpacing(6)
        self.setlist_name_input = QLineEdit()
        self.setlist_name_input.setPlaceholderText("Setlist name…")
        self.rename_button = QPushButton("Set")
        self.rename_button.setFixedWidth(44)
        self.rename_button.clicked.connect(self.rename_setlist_title)
        setlist_name_layout.addWidget(self.setlist_name_input)
        setlist_name_layout.addWidget(self.rename_button)

        save_load_layout = QHBoxLayout()
        save_load_layout.setSpacing(6)
        self.save_button = QPushButton("Save")
        self.save_button.setStyleSheet(
            "background-color: #0a2a4a; color: #0a84ff; border: 1px solid #1a4a7a; "
            "font-size: 11px; padding: 4px 8px; border-radius: 6px;"
        )
        self.save_button.clicked.connect(self.save_setlist)
        self.load_button = QPushButton("Load")
        self.load_button.setStyleSheet(
            "background-color: #0a2a0a; color: #30d158; border: 1px solid #1a5a1a; "
            "font-size: 11px; padding: 4px 8px; border-radius: 6px;"
        )
        self.load_button.clicked.connect(self.load_setlist)
        save_load_layout.addWidget(self.save_button)
        save_load_layout.addWidget(self.load_button)

        main_controls_layout.addWidget(self.stop_button)
        main_controls_layout.addLayout(add_buttons_layout)
        main_controls_layout.addWidget(self.undo_button)
        main_controls_layout.addLayout(setlist_name_layout)
        main_controls_layout.addLayout(save_load_layout)
        main_controls_group.setLayout(main_controls_layout)

        # Settings group
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout()
        settings_layout.setContentsMargins(8, 10, 8, 8)
        settings_layout.setSpacing(6)

        self.display_combo = QComboBox()
        self.display_combo.addItems([str(i) for i in range(1, 5)])
        self.display_combo.currentIndexChanged.connect(self.setting_changed)
        settings_layout.addWidget(QLabel("Display:"), 0, 0)
        settings_layout.addWidget(self.display_combo, 0, 1)

        self.preload_combo = QComboBox()
        self.preload_combo.addItems([str(i) for i in range(1, 11)])
        self.preload_combo.currentIndexChanged.connect(self.setting_changed)
        settings_layout.addWidget(QLabel("Preload (s):"), 1, 0)
        settings_layout.addWidget(self.preload_combo, 1, 1)

        self.count_in_combo = QComboBox()
        self.count_in_combo.addItems([str(i) for i in range(1, 31)])
        settings_layout.addWidget(QLabel("Count In (s):"), 2, 0)
        settings_layout.addWidget(self.count_in_combo, 2, 1)

        self.count_in_test_checkbox = QCheckBox("Count In on Track 1")
        self.count_in_test_checkbox.setChecked(True)
        settings_layout.addWidget(self.count_in_test_checkbox, 3, 0, 1, 2)

        font_size_layout = QHBoxLayout()
        font_size_layout.setSpacing(6)
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 36)
        self.font_size_spinbox.setValue(self.current_table_font_size)
        self.apply_font_button = QPushButton("Apply")
        self.apply_font_button.setFixedWidth(54)
        self.apply_font_button.clicked.connect(self.apply_table_font_size)
        font_size_layout.addWidget(self.font_size_spinbox)
        font_size_layout.addWidget(self.apply_font_button)
        settings_layout.addWidget(QLabel("List Font:"), 4, 0)
        settings_layout.addLayout(font_size_layout, 4, 1)
        settings_group.setLayout(settings_layout)

        # Test Track group
        test_track_group = QGroupBox("Test Track")
        test_track_layout = QHBoxLayout()
        test_track_layout.setContentsMargins(8, 10, 8, 8)
        test_track_layout.setSpacing(6)
        self.test_file_button = QPushButton("Select…")
        self.test_file_button.setFixedWidth(62)
        self.test_file_button.clicked.connect(self.select_test_file)
        self.test_file_label = QLabel("No file selected.")
        self.test_file_label.setStyleSheet("font-style: italic; color: #636366;")
        self.play_test_button = QPushButton("▶  Play Test  (t)")
        self.play_test_button.setStyleSheet(
            "background-color: #0a2a0a; color: #30d158; border: 1px solid #1a5a1a; "
            "font-size: 11px; padding: 4px 8px; border-radius: 6px;"
        )
        self.play_test_button.clicked.connect(self.play_test_track)
        self.play_test_button.setEnabled(False)
        test_track_layout.addWidget(self.test_file_button)
        test_track_layout.addWidget(self.test_file_label, 1)
        test_track_layout.addWidget(self.play_test_button)
        test_track_group.setLayout(test_track_layout)

        # Overlay Colours group
        overlay_colours_group = QGroupBox("Overlay Colours")
        overlay_colours_layout = QGridLayout()
        overlay_colours_layout.setContentsMargins(8, 10, 8, 8)
        overlay_colours_layout.setSpacing(6)

        self.count_in_color_button = QPushButton()
        self.count_in_color_button.setFixedSize(50, 24)
        self.count_in_color_button.setStyleSheet(
            f"background-color: {DEFAULT_COUNT_IN_BG_COLOR}; border-radius: 4px; border: 1px solid #38383a;"
        )
        self.count_in_color_button.clicked.connect(self.pick_count_in_color)

        self.count_in_font_spinbox = QSpinBox()
        self.count_in_font_spinbox.setRange(20, 500)
        self.count_in_font_spinbox.setValue(DEFAULT_COUNT_IN_FONT_SIZE)
        self.count_in_font_spinbox.valueChanged.connect(self._on_count_in_font_changed)

        self.track_play_color_button = QPushButton()
        self.track_play_color_button.setFixedSize(50, 24)
        self.track_play_color_button.setStyleSheet(
            f"background-color: {DEFAULT_TRACK_PLAY_BG_COLOR}; border-radius: 4px; border: 1px solid #38383a;"
        )
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

        # Application group
        app_group = QGroupBox("Application")
        app_layout = QVBoxLayout()
        app_layout.setContentsMargins(8, 10, 8, 8)
        app_layout.setSpacing(4)
        self.quit_button = QPushButton("Quit")
        self.quit_button.setStyleSheet(
            "background-color: #3a0a0a; color: #ff453a; border: 1px solid #7a1a1a; "
            "font-size: 12px; padding: 5px 12px; border-radius: 6px;"
        )
        self.quit_button.clicked.connect(self.close)
        app_layout.addWidget(self.quit_button)
        app_group.setLayout(app_layout)

        controls_area.addWidget(main_controls_group)
        controls_area.addWidget(settings_group)
        controls_area.addWidget(test_track_group)
        controls_area.addWidget(overlay_colours_group)
        controls_area.addWidget(app_group)
        controls_area.addStretch(1)

        main_layout.addWidget(self.table, 3)
        main_layout.addLayout(controls_area, 2)

        self.status_label = QLabel("Status: Welcome!")
        self.status_label.setStyleSheet(
            "font-style: italic; color: #636366; font-size: 11px; "
            "padding: 3px 0px; border-top: 1px solid #2c2c2e;"
        )

        self.layout.addLayout(top_bar_layout)
        self.layout.addWidget(separator)
        self.layout.addLayout(main_layout)
        self.layout.addWidget(self.status_label)

        self.live_mode_slider.setChecked(True)
        self.toggle_live_mode()
        self.populate_table()
        self.apply_overlay_styles()

    # ------------------------------------------------------------------ #
    # Overlay helpers
    # ------------------------------------------------------------------ #

    def apply_overlay_styles(self):
        count_in_c = QColor(self.count_in_bg_color)
        self.countdown_label.setStyleSheet(
            f"background-color: rgba({count_in_c.red()}, {count_in_c.green()}, {count_in_c.blue()}, 0.9); "
            "color: white; border-radius: 20px;"
        )
        self.countdown_label.setFont(QFont("Helvetica Neue", self.count_in_font_size, QFont.Weight.ExtraBold))

        track_play_c = QColor(self.track_play_bg_color)
        self.preparing_label.setStyleSheet(
            f"background-color: rgba({track_play_c.red()}, {track_play_c.green()}, {track_play_c.blue()}, 0.8); "
            "color: white; border-radius: 20px;"
        )
        self.preparing_label.setFont(QFont("Helvetica Neue", self.track_play_font_size, QFont.Weight.Bold))

    def pick_count_in_color(self):
        color = QColorDialog.getColor(QColor(self.count_in_bg_color), self, "Count-In Background Colour")
        if color.isValid():
            self.count_in_bg_color = color.name()
            self.count_in_color_button.setStyleSheet(f"background-color: {self.count_in_bg_color};")
            self.apply_overlay_styles()

    def pick_track_play_color(self):
        color = QColorDialog.getColor(QColor(self.track_play_bg_color), self, "Track Play Background Colour")
        if color.isValid():
            self.track_play_bg_color = color.name()
            self.track_play_color_button.setStyleSheet(f"background-color: {self.track_play_bg_color};")
            self.apply_overlay_styles()

    def _on_count_in_font_changed(self, value):
        self.count_in_font_size = value
        self.apply_overlay_styles()

    def _on_track_play_font_changed(self, value):
        self.track_play_font_size = value
        self.apply_overlay_styles()

    # ------------------------------------------------------------------ #
    # Table font
    # ------------------------------------------------------------------ #

    def apply_table_font_size(self):
        self.current_table_font_size = self.font_size_spinbox.value()
        new_font = QFont("Helvetica Neue", self.current_table_font_size)
        self.table.verticalHeader().setDefaultSectionSize(int(self.current_table_font_size * 2.5))
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setFont(new_font)
            for col in [1]:
                widget = self.table.cellWidget(row, col)
                if isinstance(widget, QLineEdit):
                    widget.setFont(new_font)
        self.status_label.setText(f"Status: Font size set to {self.current_table_font_size}pt.")

    # ------------------------------------------------------------------ #
    # Mode toggle
    # ------------------------------------------------------------------ #

    def toggle_live_mode(self):
        self.is_live_mode = self.live_mode_slider.isChecked()
        is_edit_mode = not self.is_live_mode

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

        for i in range(self.table.rowCount()):
            if i < len(self.tracks):
                item = self.tracks[i]
                if item['type'] == 'track':
                    for col in [1, 2, 3]:
                        if widget := self.table.cellWidget(i, col):
                            widget.setEnabled(is_edit_mode)

        self.live_mode_label.setStyleSheet("color: #ff453a; font-weight: bold; letter-spacing: 1px;" if self.is_live_mode else "color: #48484a;")
        self.edit_mode_label.setStyleSheet("color: #30d158; font-weight: bold; letter-spacing: 1px;" if is_edit_mode else "color: #48484a;")
        self.status_label.setText(
            "Status: LIVE MODE - Hotkeys are active." if self.is_live_mode
            else "Status: EDIT MODE - Hotkeys are disabled."
        )

    # ------------------------------------------------------------------ #
    # Hotkey helpers
    # ------------------------------------------------------------------ #

    def _generate_hotkeys(self):
        keys = [str(i) for i in range(1, 10)] + [chr(i) for i in range(ord('a'), ord('z') + 1)]
        keys.remove('q')
        keys.remove('t')
        keys.remove('i')
        return keys

    # ------------------------------------------------------------------ #
    # Config persistence
    # ------------------------------------------------------------------ #

    def load_config(self):
        defaults = {"display": DEFAULT_VIDEO_SCREEN_NUMBER, "preload": DEFAULT_LOAD_DELAY_SECONDS}
        if not os.path.exists(CONFIG_FILE):
            return defaults
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                defaults.update(config)
                return defaults
        except (json.JSONDecodeError, FileNotFoundError):
            return defaults

    def save_config(self):
        self.config['display'] = int(self.display_combo.currentText())
        self.config['preload'] = int(self.preload_combo.currentText())
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)

    def apply_config_to_ui(self):
        self.display_combo.setCurrentText(str(self.config.get("display", DEFAULT_VIDEO_SCREEN_NUMBER)))
        self.preload_combo.setCurrentText(str(self.config.get("preload", DEFAULT_LOAD_DELAY_SECONDS)))
        self.check_display_setting()

    def setting_changed(self):
        self.save_config()

    def check_display_setting(self):
        num_screens = len(QGuiApplication.screens())
        selected_screen_index = int(self.display_combo.currentText()) - 1
        if selected_screen_index >= num_screens:
            self.status_label.setText(f"WARNING: Display {selected_screen_index + 1} not found!")

    # ------------------------------------------------------------------ #
    # Generic JSON store helpers
    # ------------------------------------------------------------------ #

    def load_json_store(self, file_path):
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def save_json_store(self, file_path, data):
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)

    # ------------------------------------------------------------------ #
    # Session persistence
    # ------------------------------------------------------------------ #

    def save_session(self):
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
        if not os.path.exists(SESSION_FILE):
            self.status_label.setText("Status: No previous session found. Welcome!")
            self.count_in_combo.setCurrentText(str(DEFAULT_COUNT_IN_SECONDS))
            self.count_in_test_checkbox.setChecked(True)
            return
        try:
            with open(SESSION_FILE, 'r') as f:
                session_data = json.load(f)

            self.count_in_combo.setCurrentText(str(session_data.get('count_in_duration', DEFAULT_COUNT_IN_SECONDS)))
            self.count_in_test_checkbox.setChecked(True)

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
                self.test_file_label.setStyleSheet("font-style: normal; color: #aeaeb2;")
                self.play_test_button.setEnabled(True)
            else:
                self.test_track_path = None

            self.status_label.setText(f"Status: Restored previous session: {session_data.get('setlist_name', '')}")
        except (json.JSONDecodeError, FileNotFoundError):
            self.status_label.setText("Status: Could not load previous session file.")

    # ------------------------------------------------------------------ #
    # Setlist management
    # ------------------------------------------------------------------ #

    def rename_setlist_title(self):
        new_name = self.setlist_name_input.text().strip()
        if new_name:
            self.title_label.setText(new_name)
            self.undo_history.clear()
            self.update_undo_button_state()

    def add_tracks(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Track Files", _DEFAULT_DIALOG_DIR,
            "Media Files (*.mov *.mp4 *.wav);;Video Files (*.mov *.mp4);;Audio Files (*.wav)"
        )
        if not files:
            return
        for file_path in files:
            if file_path in [t.get('path') for t in self.tracks]:
                continue
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
        encore_count = sum(1 for item in self.tracks if item['type'] == 'divider')
        self.tracks.append({'type': 'divider', 'text': f'ENCORE {encore_count + 1}'})
        self.populate_table()

    def get_track_duration(self, file_path):
        """Uses mplayer to get the duration of a media file."""
        mplayer_bin = MPLAYER_PATH
        if not os.path.isabs(mplayer_bin) or not os.path.exists(mplayer_bin):
            mplayer_bin = _find_executable('mplayer')

        if not os.path.exists(mplayer_bin):
            print(f"mplayer not found at {mplayer_bin}")
            return 0
        try:
            normalized_path = os.path.normpath(file_path)
            mplayer_dir = os.path.dirname(mplayer_bin)
            cmd = [mplayer_bin, "-vo", "null", "-ao", "null", "-identify", "-frames", "0", normalized_path]
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
                timeout=30, cwd=mplayer_dir or None
            )
            for line in result.stdout.splitlines():
                if line.startswith("ID_LENGTH="):
                    return float(line.split('=')[1])
            print(f"Could not find ID_LENGTH for {file_path}")
            return 0
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError, subprocess.TimeoutExpired) as e:
            print(f"Could not get duration for {file_path}: {e}")
            return 0

    def remove_item(self, row_index):
        if self.currently_playing_row == row_index:
            self.clear_highlight()
        item_to_remove = self.tracks.pop(row_index)
        self.undo_history.append({'index': row_index, 'item': item_to_remove})
        self.update_undo_button_state()
        if item_to_remove['type'] == 'track':
            hotkey = item_to_remove['hotkey']
            if hotkey not in self.available_hotkeys:
                self.available_hotkeys.append(hotkey)
                self.available_hotkeys.sort()
        self.rebuild_hotkey_map()
        self.populate_table()

    def undo_delete(self):
        if not self.undo_history:
            return
        last_deleted = self.undo_history.pop()
        index = last_deleted['index']
        item = last_deleted['item']
        if item.get('type') == 'track':
            hotkey = item.get('hotkey')
            valid_hotkeys = set(self._generate_hotkeys())
            if hotkey in valid_hotkeys and hotkey in self.available_hotkeys:
                self.available_hotkeys.remove(hotkey)
            elif hotkey not in valid_hotkeys:
                if self.available_hotkeys:
                    item['hotkey'] = self.available_hotkeys.pop(0)
                else:
                    item['hotkey'] = ''
        self.tracks.insert(index, item)
        self.rebuild_hotkey_map()
        self.populate_table()
        self.update_undo_button_state()

    def update_undo_button_state(self):
        self.undo_button.setEnabled(len(self.undo_history) > 0 and not self.is_live_mode)

    def populate_table(self):
        self.table.setRowCount(0)
        for i, item in enumerate(self.tracks):
            self.table.insertRow(i)
            tooltip_text = ""
            if item.get('type') == 'track':
                tooltip_text = f"Filename: {os.path.basename(item['path'])}\nDuration: {self.format_duration(item.get('duration', 0))}"

            if item.get('type') == 'divider':
                self.table.setSpan(i, 0, 1, self.table.columnCount() - 1)
                self.table.setRowHeight(i, 20)
                encore_item = QTableWidgetItem(item.get('text', 'ENCORE'))
                encore_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                encore_item.setBackground(QColor("#0a84ff"))
                encore_item.setForeground(QColor(Qt.GlobalColor.white))
                font = QFont("Helvetica Neue", self.current_table_font_size)
                font.setBold(False)
                encore_item.setFont(font)
                self.table.setItem(i, 0, encore_item)

                remove_button = QPushButton("X")
                remove_button.clicked.connect(lambda checked, i=i: self.remove_item(i))
                remove_button.setFixedSize(18, 18)
                remove_button.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; border-radius: 3px; font-size: 10px;")
                btn_container = QWidget()
                btn_layout = QHBoxLayout(btn_container)
                btn_layout.addWidget(remove_button)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                self.table.setCellWidget(i, 3, btn_container)
            else:
                table_font = QFont("Helvetica Neue", self.current_table_font_size)

                hotkey_item = QTableWidgetItem(item['hotkey'].upper())
                hotkey_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                hotkey_item.setFlags(hotkey_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                hotkey_item.setFont(table_font)
                hotkey_item.setToolTip(tooltip_text)
                self.table.setItem(i, 0, hotkey_item)

                track_name_input = QLineEdit(
                    self.track_name_data.get(item['path'],
                    os.path.splitext(os.path.basename(item['path']))[0])
                )
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
                    linked_layout.setContentsMargins(0, 0, 0, 0)
                    linked_container.setToolTip(tooltip_text)
                    return linked_container

                self.table.setCellWidget(i, 2, create_linked_checkbox(i, item))

                remove_button = QPushButton("X")
                remove_button.clicked.connect(lambda checked, i=i: self.remove_item(i))
                remove_button.setFixedSize(18, 18)
                remove_button.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; border-radius: 3px; font-size: 10px;")
                btn_container = QWidget()
                btn_layout = QHBoxLayout(btn_container)
                btn_layout.addWidget(remove_button)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_container.setToolTip(tooltip_text)
                self.table.setCellWidget(i, 3, btn_container)

        self.apply_table_font_size()
        self.update_total_running_time()
        self.toggle_live_mode()

    def reorder_tracks(self, source_row, dest_row):
        moved_item = self.tracks.pop(source_row)
        self.tracks.insert(dest_row, moved_item)
        self.rebuild_hotkey_map()
        self.populate_table()
        self.status_label.setText("Status: Setlist order updated.")

    def rebuild_hotkey_map(self):
        self.hotkey_map = {item['hotkey']: i for i, item in enumerate(self.tracks) if item['type'] == 'track'}

    def highlight_row(self, row, is_playing):
        if row >= len(self.tracks) or self.tracks[row]['type'] == 'divider':
            return
        bg_color = self.playing_color if is_playing else self.default_color
        fg_color = QColor("#000000") if is_playing else QColor("#f2f2f7")
        font_size = self.current_table_font_size
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                item.setBackground(bg_color)
                item.setForeground(fg_color)
                item.setFont(QFont("Helvetica Neue", font_size))
            widget = self.table.cellWidget(row, col)
            if widget:
                if col in [2, 3]:
                    widget.setStyleSheet(f"background-color: {bg_color.name()};")
                else:
                    style_sheet = f"background-color: {bg_color.name()}; color: {fg_color.name()}; font-size: {font_size}pt; border: none;"
                    widget.setStyleSheet(style_sheet)
                    if hasattr(widget, 'findChildren'):
                        for child_widget in widget.findChildren(QLineEdit):
                            child_widget.setFont(QFont("Helvetica Neue", font_size))
                            child_widget.setStyleSheet(style_sheet)

    def clear_highlight(self):
        if self.currently_playing_row is not None and self.currently_playing_row < self.table.rowCount():
            self.highlight_row(self.currently_playing_row, is_playing=False)
        self.currently_playing_row = None

    def update_track_name(self, file_path, name):
        self.track_name_data[file_path] = name
        self.save_json_store(TRACK_NAME_STORE_FILE, self.track_name_data)

    def update_linked_setting(self, is_checked, row_index):
        if 0 <= row_index < len(self.tracks) and self.tracks[row_index]['type'] == 'track':
            self.tracks[row_index]['linked'] = is_checked

    def save_setlist(self):
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

        self.save_notification_label.setText(f"Setlist '{setlist_name}' Saved!")
        self.save_notification_label.adjustSize()
        center_x = (self.width() - self.save_notification_label.width()) // 2
        center_y = (self.height() - self.save_notification_label.height()) // 2
        self.save_notification_label.move(center_x, center_y)
        self.save_notification_label.raise_()
        self.save_notification_label.show()
        QTimer.singleShot(SAVE_POPUP_DURATION_MS, self.save_notification_label.hide)

    def load_setlist(self):
        if self.worker and self.worker.isRunning():
            self.stop_all_activity()
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Setlist", SETLISTS_DIR, "JSON Files (*.json)")
        if not file_path:
            return
        with open(file_path, 'r') as f:
            try:
                loaded_data = json.load(f)
            except json.JSONDecodeError:
                self.status_label.setText("Status: Error reading invalid setlist file.")
                return

        setlist_name = os.path.splitext(os.path.basename(file_path))[0]

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
        self.tracks, self.hotkey_map = [], {}
        self.available_hotkeys = self._generate_hotkeys()
        for item in setlist_data:
            if 'type' not in item:
                item['type'] = 'track'
        valid_hotkeys = set(self._generate_hotkeys())
        loaded_hotkeys = {item['hotkey'] for item in setlist_data if item['type'] == 'track' and item['hotkey'] in valid_hotkeys}
        self.available_hotkeys = [k for k in self.available_hotkeys if k not in loaded_hotkeys]
        for item in setlist_data:
            if item['type'] == 'track':
                if 'duration' not in item or item['duration'] == 0:
                    item['duration'] = self.get_track_duration(item['path'])
                if 'linked' not in item:
                    item['linked'] = False
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
                lines.append(f"{track_name} ({self.format_duration(duration)})")
        lines.append("")
        lines.append(f"Total Time: {self.format_duration(total_seconds, show_hours=True)}")
        track_count = len([t for t in self.tracks if t['type'] == 'track'])
        total_with_overhead = total_seconds + (track_count * TRACK_OVERHEAD_SECONDS)
        lines.append(f"Total Time (incl. {TRACK_OVERHEAD_SECONDS}s gap between songs): {self.format_duration(total_with_overhead, show_hours=True)}")

        setlist_name = self.title_label.text()
        safe_name = re.sub(r'[\\/*?:"<>|]', '', setlist_name).strip() or "setlist"
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        file_path = os.path.join(downloads_dir, f"{safe_name}_setlist.txt")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        self.status_label.setText(f"Status: Set list exported to {file_path}")

    def update_total_running_time(self):
        total_seconds = sum(t.get('duration', 0) for t in self.tracks if t['type'] == 'track')
        total_seconds += len([t for t in self.tracks if t['type'] == 'track']) * TRACK_OVERHEAD_SECONDS
        self.running_time_label.setText(
            f"Total Running Time (incl. {TRACK_OVERHEAD_SECONDS}s overhead/track): {self.format_duration(total_seconds, show_hours=True)}"
        )

    def format_duration(self, seconds, show_hours=False):
        if seconds is None or seconds < 0:
            return "00:00"
        total_seconds = int(seconds)
        mins, secs = divmod(total_seconds, 60)
        if show_hours:
            hours, mins = divmod(mins, 60)
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    # ------------------------------------------------------------------ #
    # Hotkey handler
    # ------------------------------------------------------------------ #

    def _start_hotkey_listener(self):
        """Starts the global hotkey listener, handling SIGTRAP and other failures gracefully.

        On macOS, pynput requires Accessibility and Input Monitoring permissions.
        If those are missing the OS may send SIGTRAP to the process, which would
        otherwise crash it.  We install a temporary SIGTRAP handler that converts
        the signal into a Python exception so we can catch it and degrade gracefully.
        """
        # Install a SIGTRAP handler so that macOS permission failures do not kill
        # the process.  The handler raises OSError which the try/except below catches.
        _original_sigtrap = signal.SIG_DFL
        if hasattr(signal, 'SIGTRAP'):
            def _sigtrap_handler(signum, frame):
                raise OSError("macOS denied Input Monitoring access (SIGTRAP received). "
                              "Grant permissions in System Settings > Privacy & Security.")
            _original_sigtrap = signal.signal(signal.SIGTRAP, _sigtrap_handler)

        try:
            self.hotkey_listener = GlobalHotkeyListener()
            self.hotkey_listener.hotkey_pressed.connect(self.on_global_hotkey)
            self.hotkey_listener.listener_failed.connect(self._on_hotkey_listener_failed)
            self.hotkey_listener.start()
        except Exception as exc:
            self.hotkey_listener = None
            self._show_hotkey_unavailable(str(exc))
        finally:
            # Restore the original SIGTRAP disposition.
            if hasattr(signal, 'SIGTRAP'):
                signal.signal(signal.SIGTRAP, _original_sigtrap)

    def _on_hotkey_listener_failed(self, error_msg):
        """Called via signal when the pynput listener thread fails to start."""
        self.hotkey_listener = None
        self._show_hotkey_unavailable(error_msg)

    def _show_hotkey_unavailable(self, detail=""):
        """Updates the status label to inform the user that hotkeys are disabled."""
        self.status_label.setText(
            "Status: Global hotkeys unavailable — grant Accessibility/Input Monitoring "
            "permissions in System Settings > Privacy & Security, then restart the app."
        )

    def on_global_hotkey(self, key):
        """Handles key presses from the pynput-based global hotkey listener."""
        lower_key = key.lower()

        if self.worker and self.worker.isRunning() or self.countdown_timer.isActive():
            if lower_key == 'q':
                self.stop_all_activity()
            else:
                self.show_danger_message()
            return

        # '^' toggles EDIT/LIVE mode (e.g. from a Stream Deck).
        if lower_key == '^':
            self.live_mode_slider.setChecked(not self.live_mode_slider.isChecked())
            return

        if not self.is_live_mode:
            return

        if lower_key in self.hotkey_map:
            row_index = self.hotkey_map[lower_key]
            if self.tracks[row_index]['type'] == 'track':
                self.start_playback(row_index)
        elif lower_key == 't':
            self.play_test_track()

    # ------------------------------------------------------------------ #
    # Playback
    # ------------------------------------------------------------------ #

    def start_playback(self, row_index):
        if self.worker and self.worker.isRunning():
            self.show_danger_message()
            return
        if self.tracks[row_index]['type'] == 'divider':
            return
        is_countdown_track = (row_index == 0 and self.count_in_test_checkbox.isChecked())
        if not is_countdown_track:
            track_name_widget = self.table.cellWidget(row_index, 1)
            self.show_preparing_message(track_name_widget.text())
        if is_countdown_track:
            self.start_countdown(row_index)
        else:
            self.execute_playback(self.tracks[row_index], row_index)

    def start_countdown(self, row_index):
        self.countdown_seconds = int(self.count_in_combo.currentText())
        self.countdown_label.setText(str(self.countdown_seconds))
        self.countdown_label.raise_()
        self.countdown_label.show()
        self.countdown_connection = self.countdown_timer.timeout.connect(lambda: self._update_countdown(row_index))
        self.countdown_timer.start(1000)

    def _update_countdown(self, row_index):
        self.countdown_seconds -= 1
        if self.countdown_seconds > 0:
            self.countdown_label.setText(str(self.countdown_seconds))
        else:
            self.countdown_timer.stop()
            if self.countdown_connection:
                self.countdown_timer.timeout.disconnect(self.countdown_connection)
                self.countdown_connection = None
            self.countdown_label.hide()
            self.execute_playback(self.tracks[row_index], row_index)

    def execute_playback(self, track_data, row_index=None):
        try:
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
        else:
            self.test_file_label.setStyleSheet("font-weight: bold; color: #30d158;")

        self.active_flash_timer.start()
        self.worker = VideoPlaybackWorker(track_path, display_num, preload_time)
        self.worker.status_update.connect(self.status_label.setText)
        self.worker.error.connect(lambda msg: self.status_label.setText(f"ERROR: {msg}"))
        self.worker.finished.connect(self.on_playback_finished)
        self.worker.ipc_socket_path.connect(self.set_ipc_socket)
        self.worker.start()

    def set_ipc_socket(self, path):
        self.current_ipc_socket = path

    def stop_all_activity(self):
        if self.countdown_timer.isActive():
            self.countdown_timer.stop()
            if self.countdown_connection:
                try:
                    self.countdown_timer.timeout.disconnect(self.countdown_connection)
                except TypeError:
                    pass
                self.countdown_connection = None
            self.countdown_label.hide()
            self.status_label.setText("Status: Countdown aborted.")

        if self.worker and self.worker.isRunning():
            self.worker.stop()
            if self.current_ipc_socket:
                _send_ipc_command(self.current_ipc_socket, '{ "command": ["quit"] }')
            self.worker.wait()

        self.active_flash_timer.stop()
        self.active_label.hide()

    def on_playback_finished(self):
        finished_row = self.currently_playing_row
        self.clear_highlight()
        self.test_file_label.setStyleSheet("font-style: italic; color: #636366;")
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
        self.danger_label.raise_()
        self.danger_label.show()
        QTimer.singleShot(2500, self.danger_label.hide)

    def show_preparing_message(self, track_name):
        self.preparing_label.raise_()
        self.preparing_label.show()
        self.preparing_label.setText(f"PREPARING:\n{track_name}")
        QTimer.singleShot(PREPARING_OVERLAY_DURATION_MS, self.preparing_label.hide)

    def toggle_active_label_visibility(self):
        self.active_label.setVisible(not self.active_label.isVisible())

    def select_test_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Test File", _DEFAULT_DIALOG_DIR,
            "Media Files (*.mov *.mp4 *.wav);;Video Files (*.mov *.mp4);;Audio Files (*.wav)"
        )
        if file_path:
            self.test_track_path = file_path
            self.test_file_label.setText(os.path.basename(file_path))
            self.test_file_label.setStyleSheet("font-style: normal; color: #aeaeb2;")
            self.play_test_button.setEnabled(True)

    def play_test_track(self):
        if self.worker and self.worker.isRunning():
            self.show_danger_message()
            return
        if not self.test_track_path:
            self.status_label.setText("Status: No test track selected.")
            return
        self.show_preparing_message(os.path.basename(self.test_track_path))
        self.execute_playback({'path': self.test_track_path})

    # ------------------------------------------------------------------ #
    # Qt event overrides
    # ------------------------------------------------------------------ #

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.danger_label.setGeometry(0, 0, self.width(), self.height())
        self.countdown_label.setGeometry(0, 0, self.width(), self.height())
        self.preparing_label.setGeometry(0, 0, self.width(), self.height())
        if self.save_notification_label.isVisible():
            center_x = (self.width() - self.save_notification_label.width()) // 2
            center_y = (self.height() - self.save_notification_label.height()) // 2
            self.save_notification_label.move(center_x, center_y)

    def closeEvent(self, event):
        self.save_session()
        self.save_config()
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
            self.hotkey_listener.wait()
        self.stop_all_activity()
        event.accept()


# --- Main Execution Block ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(MODERN_STYLESHEET)
    controller = LiveControllerMac()
    controller.resize(1280, 800)
    controller.show()
    sys.exit(app.exec())
