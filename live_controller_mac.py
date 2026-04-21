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
import ctypes
import ctypes.util
import signal
import socket
import subprocess
import tempfile
import threading
import time
import json
import shutil
from collections import deque
from datetime import datetime

# --- Third-Party Library Imports ---
# Requires: pynput
# Install with: pip install pynput
from pynput import keyboard as pynput_keyboard

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QLineEdit, QHeaderView,
                             QGroupBox, QLabel, QFileDialog, QSizePolicy, QComboBox,
                             QAbstractButton, QAbstractItemView, QCheckBox,
                             QGridLayout, QSpinBox, QColorDialog, QTextEdit, QDialog,
                             QSlider)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QPoint, QEasingCurve, pyqtProperty, QTimer
from PyQt6.QtGui import QFont, QGuiApplication, QPainter, QColor, QBrush, QPen, QTextCursor


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


def _is_accessibility_trusted():
    """Return True if this process has macOS Accessibility/Input Monitoring trust.

    Uses the ``AXIsProcessTrusted`` C function from the ApplicationServices
    framework.  Returns *None* on any platform other than macOS or whenever the
    library cannot be loaded so callers can distinguish "definitely denied" from
    "unknown".
    """
    _framework = (
        '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices'
    )
    try:
        lib = ctypes.CDLL(_framework)
        return bool(lib.AXIsProcessTrusted())
    except (OSError, AttributeError):
        return None  # Non-macOS or library unavailable — treat as unknown.


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
# Delay (ms) before the second focus-restore pass after stopping playback on macOS.
# macOS may reassign focus during fullscreen/maximize teardown; a deferred re-activation
# ensures the main window reliably ends up in front after pressing q.
MACOS_FOCUS_RESTORE_DELAY_MS = 250

# Default directory for file dialogs (macOS Movies folder or home dir)
_DEFAULT_DIALOG_DIR = os.path.join(os.path.expanduser("~"), "Movies")
if not os.path.isdir(_DEFAULT_DIALOG_DIR):
    _DEFAULT_DIALOG_DIR = os.path.expanduser("~")

# --- Modern macOS-Dark Stylesheet ---
MODERN_STYLESHEET = """
QWidget {
    background-color: #1c1c1e;
    color: #f2f2f7;
    font-family: Arial;
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
QSlider::groove:horizontal {
    height: 4px;
    background: #38383a;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #0a84ff;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #0a84ff;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:disabled {
    background: #48484a;
}
QSlider::sub-page:horizontal:disabled {
    background: #38383a;
}
"""

# Branded logo HTML — ▲ (U+25B2) replaces each A in KATTMAN CONTROL
KATTMAN_LOGO_HTML = (
    '<span style="color:#f2f2f7; font-weight:700; font-size:22px; letter-spacing:4px;">'
    'K<span style="color:#0a84ff;">&#9650;</span>TTM'
    '<span style="color:#0a84ff;">&#9650;</span>N&nbsp;&nbsp;CONTROL'
    '</span>'
)

# Default color scheme — matches the colors used in MODERN_STYLESHEET.
# Keys cover backgrounds and text only; button styling is intentionally excluded.
DEFAULT_COLOR_SCHEME = {
    'app_bg':       '#1c1c1e',   # Main app/window background
    'app_fg':       '#f2f2f7',   # Main text / foreground color
    'panel_bg':     '#2c2c2e',   # Inputs, checkboxes, secondary panels
    'table_bg':     '#2c2c2e',   # Table widget background
    'table_alt_bg': '#323234',   # Table alternating row background
    'header_fg':    '#636366',   # Column header text and group-box title text
    'border_color': '#38383a',   # Borders, grid lines, and separators
}

# File extension / filter used for color-scheme export/import.
COLOR_SCHEME_FILE_FILTER = "Color Scheme (*.json)"

# Twenty coherent preset color themes.  Each entry is (display_name, scheme_dict).
COLOR_SCHEME_PRESETS = [
    ("Dark (Default)", {
        'app_bg': '#1c1c1e', 'app_fg': '#f2f2f7', 'panel_bg': '#2c2c2e',
        'table_bg': '#2c2c2e', 'table_alt_bg': '#323234',
        'header_fg': '#636366', 'border_color': '#38383a',
    }),
    ("Midnight Blue", {
        'app_bg': '#0d1117', 'app_fg': '#c9d1d9', 'panel_bg': '#161b22',
        'table_bg': '#161b22', 'table_alt_bg': '#1c2128',
        'header_fg': '#6e7681', 'border_color': '#30363d',
    }),
    ("Forest Green", {
        'app_bg': '#0d1a10', 'app_fg': '#d8e8d8', 'panel_bg': '#1a2e1c',
        'table_bg': '#1a2e1c', 'table_alt_bg': '#1f3522',
        'header_fg': '#5a8060', 'border_color': '#2d4a30',
    }),
    ("Crimson Night", {
        'app_bg': '#1a0a0a', 'app_fg': '#f0d8d8', 'panel_bg': '#2a1212',
        'table_bg': '#2a1212', 'table_alt_bg': '#311515',
        'header_fg': '#7a4444', 'border_color': '#4a2020',
    }),
    ("Deep Purple", {
        'app_bg': '#120a1a', 'app_fg': '#e8d8f0', 'panel_bg': '#1e1028',
        'table_bg': '#1e1028', 'table_alt_bg': '#23122f',
        'header_fg': '#6a4a80', 'border_color': '#3a2050',
    }),
    ("Slate", {
        'app_bg': '#0f1923', 'app_fg': '#cdd6f4', 'panel_bg': '#1b2838',
        'table_bg': '#1b2838', 'table_alt_bg': '#1f2d3d',
        'header_fg': '#5d7a99', 'border_color': '#2d4460',
    }),
    ("Mocha", {
        'app_bg': '#1a1210', 'app_fg': '#ede0d4', 'panel_bg': '#2d1f1b',
        'table_bg': '#2d1f1b', 'table_alt_bg': '#342420',
        'header_fg': '#7a5c52', 'border_color': '#4a3028',
    }),
    ("Light", {
        'app_bg': '#f5f5f5', 'app_fg': '#1c1c1e', 'panel_bg': '#e8e8ec',
        'table_bg': '#e8e8ec', 'table_alt_bg': '#e0e0e4',
        'header_fg': '#8e8e93', 'border_color': '#c8c8cc',
    }),
    ("Solarized Dark", {
        'app_bg': '#002b36', 'app_fg': '#839496', 'panel_bg': '#073642',
        'table_bg': '#073642', 'table_alt_bg': '#0a3d4a',
        'header_fg': '#586e75', 'border_color': '#1a4a56',
    }),
    ("Solarized Light", {
        'app_bg': '#fdf6e3', 'app_fg': '#657b83', 'panel_bg': '#eee8d5',
        'table_bg': '#eee8d5', 'table_alt_bg': '#e8e2ce',
        'header_fg': '#93a1a1', 'border_color': '#d0c9b8',
    }),
    ("Nord", {
        'app_bg': '#2e3440', 'app_fg': '#d8dee9', 'panel_bg': '#3b4252',
        'table_bg': '#3b4252', 'table_alt_bg': '#434c5e',
        'header_fg': '#7b8fa6', 'border_color': '#4c566a',
    }),
    ("Dracula", {
        'app_bg': '#282a36', 'app_fg': '#f8f8f2', 'panel_bg': '#343746',
        'table_bg': '#343746', 'table_alt_bg': '#3c3f54',
        'header_fg': '#6272a4', 'border_color': '#44475a',
    }),
    ("Gruvbox Dark", {
        'app_bg': '#282828', 'app_fg': '#ebdbb2', 'panel_bg': '#3c3836',
        'table_bg': '#3c3836', 'table_alt_bg': '#44403c',
        'header_fg': '#928374', 'border_color': '#504945',
    }),
    ("One Dark", {
        'app_bg': '#282c34', 'app_fg': '#abb2bf', 'panel_bg': '#2d333b',
        'table_bg': '#2d333b', 'table_alt_bg': '#323840',
        'header_fg': '#6b7280', 'border_color': '#404857',
    }),
    ("Tokyo Night", {
        'app_bg': '#1a1b26', 'app_fg': '#a9b1d6', 'panel_bg': '#24283b',
        'table_bg': '#24283b', 'table_alt_bg': '#292e42',
        'header_fg': '#565f89', 'border_color': '#3b3f5c',
    }),
    ("Catppuccin Mocha", {
        'app_bg': '#1e1e2e', 'app_fg': '#cdd6f4', 'panel_bg': '#313244',
        'table_bg': '#313244', 'table_alt_bg': '#363850',
        'header_fg': '#6c7086', 'border_color': '#45475a',
    }),
    ("Rosé Pine", {
        'app_bg': '#191724', 'app_fg': '#e0def4', 'panel_bg': '#26233a',
        'table_bg': '#26233a', 'table_alt_bg': '#2a2740',
        'header_fg': '#6e6a86', 'border_color': '#393552',
    }),
    ("Material Dark", {
        'app_bg': '#212121', 'app_fg': '#eeffff', 'panel_bg': '#2d2d2d',
        'table_bg': '#2d2d2d', 'table_alt_bg': '#333333',
        'header_fg': '#7a7a7a', 'border_color': '#424242',
    }),
    ("Ayu Dark", {
        'app_bg': '#0d1017', 'app_fg': '#bfbdb6', 'panel_bg': '#131721',
        'table_bg': '#131721', 'table_alt_bg': '#181d28',
        'header_fg': '#4d5566', 'border_color': '#272d38',
    }),
    ("Retro Terminal", {
        'app_bg': '#0a0a0a', 'app_fg': '#00ff41', 'panel_bg': '#0f0f0f',
        'table_bg': '#0f0f0f', 'table_alt_bg': '#141414',
        'header_fg': '#008f11', 'border_color': '#1a2a1a',
    }),
]


def _build_stylesheet(scheme):
    """Return a full Qt stylesheet built from *scheme*.

    Button (QPushButton) rules are kept as fixed constants so that the
    user-configurable color scheme never alters button appearance.
    All other background and text rules are parameterised from *scheme*.
    """
    app_bg       = scheme.get('app_bg',       DEFAULT_COLOR_SCHEME['app_bg'])
    app_fg       = scheme.get('app_fg',       DEFAULT_COLOR_SCHEME['app_fg'])
    panel_bg     = scheme.get('panel_bg',     DEFAULT_COLOR_SCHEME['panel_bg'])
    table_bg     = scheme.get('table_bg',     DEFAULT_COLOR_SCHEME['table_bg'])
    table_alt_bg = scheme.get('table_alt_bg', DEFAULT_COLOR_SCHEME['table_alt_bg'])
    header_fg    = scheme.get('header_fg',    DEFAULT_COLOR_SCHEME['header_fg'])
    border_color = scheme.get('border_color', DEFAULT_COLOR_SCHEME['border_color'])

    return f"""
QWidget {{
    background-color: {app_bg};
    color: {app_fg};
    font-family: Arial;
    font-size: 12px;
}}
QGroupBox {{
    font-size: 9px;
    font-weight: 600;
    color: {header_fg};
    border: 1px solid {border_color};
    border-radius: 10px;
    margin-top: 8px;
    padding-top: 4px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {header_fg};
}}
QLabel {{
    background-color: transparent;
    color: {app_fg};
}}
QPushButton {{
    background-color: #2c2c2e;
    color: #f2f2f7;
    border: 1px solid #3a3a3c;
    padding: 5px 12px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    min-height: 22px;
}}
QPushButton:hover {{
    background-color: #3a3a3c;
    border-color: #636366;
}}
QPushButton:pressed {{
    background-color: #48484a;
}}
QPushButton:disabled {{
    background-color: #1c1c1e;
    color: #3a3a3c;
    border-color: #2c2c2e;
}}
QLineEdit, QComboBox, QSpinBox {{
    background-color: {panel_bg};
    border: 1px solid {border_color};
    border-radius: 6px;
    padding: 4px 8px;
    color: {app_fg};
    font-size: 12px;
    selection-background-color: #0a84ff;
    selection-color: #ffffff;
}}
QLineEdit:focus {{
    border-color: #0a84ff;
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 4px;
}}
QTableWidget {{
    background-color: {table_bg};
    gridline-color: {border_color};
    border: 1px solid {border_color};
    border-radius: 8px;
    alternate-background-color: {table_alt_bg};
}}
QHeaderView::section {{
    background-color: {app_bg};
    color: {header_fg};
    padding: 6px 4px;
    border: none;
    border-bottom: 1px solid {border_color};
    font-size: 10px;
    font-weight: 600;
}}
QTableWidget::item {{
    padding: 3px 6px;
}}
QTableWidget::item:selected {{
    background-color: #0a84ff;
    color: #ffffff;
}}
QScrollBar:vertical {{
    background-color: {app_bg};
    width: 6px;
    border-radius: 3px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background-color: #48484a;
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background-color: {app_bg};
    height: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background-color: #48484a;
    border-radius: 3px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QCheckBox {{
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1.5px solid #48484a;
    border-radius: 4px;
    background-color: {panel_bg};
}}
QCheckBox::indicator:checked {{
    background-color: #0a84ff;
    border-color: #0a84ff;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 14px;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {border_color};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: #0a84ff;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #0a84ff;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:disabled {{
    background: #48484a;
}}
QSlider::sub-page:horizontal:disabled {{
    background: {border_color};
}}
"""


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


def _query_ipc_property(socket_path, prop):
    """Query a single mpv property via its Unix domain socket.

    Returns the property value on success, or *None* on any error.
    Uses a short timeout so callers in background threads are not blocked.
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect(socket_path)
        req_id = 1
        cmd = json.dumps({"command": ["get_property", prop], "request_id": req_id}) + '\n'
        sock.sendall(cmd.encode('utf-8'))
        buf = b""
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                try:
                    obj = json.loads(line.decode('utf-8'))
                    if obj.get('request_id') == req_id:
                        sock.close()
                        return obj.get('data') if obj.get('error') == 'success' else None
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
        sock.close()
    except Exception:
        pass
    return None


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
        # Pre-flight trust check: emit a clear signal instead of letting pynput
        # print the raw "This process is not trusted!" message to stderr.
        if _is_accessibility_trusted() is False:
            self.listener_failed.emit(
                "This process is not trusted for Input Monitoring. "
                "Add your terminal or Python binary to "
                "System Settings → Privacy & Security → Accessibility, "
                "then restart the app."
            )
            return

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

    def __init__(self, video_file, display_num, preload_time, audio_only_mode=False):
        super().__init__()
        self.video_file = video_file
        self.display_num = display_num
        self.preload_time = preload_time
        self.audio_only_mode = audio_only_mode
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
        is_audio_only = file_ext == '.wav' or self.audio_only_mode

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


class PositionPoller(QThread):
    """Polls mpv playback position and duration via IPC at ~500 ms intervals.

    Runs entirely in its own thread so the main-thread UI is never blocked
    waiting on IPC socket I/O.  Set the active socket path with
    :meth:`set_socket`; pass ``None`` to pause polling without stopping the
    thread.
    """
    position_updated = pyqtSignal(float, float)   # (pos_seconds, dur_seconds)

    _POLL_INTERVAL = 0.5   # seconds between polls

    def __init__(self):
        super().__init__()
        self._socket_path = None
        self._socket_lock = threading.Lock()
        self._running = False

    def set_socket(self, path):
        """Set (or clear) the active mpv IPC socket path (thread-safe)."""
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
                pos = _query_ipc_property(path, "time-pos")
                dur = _query_ipc_property(path, "duration")
                if pos is not None and dur is not None:
                    try:
                        self.position_updated.emit(float(pos), float(dur))
                    except Exception:
                        pass
            time.sleep(self._POLL_INTERVAL)


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


class DebugConsoleWindow(QDialog):
    """A floating, copyable debug log window for diagnosing runtime issues.

    The log text area is read-only but fully selectable so the user can
    copy individual lines or the entire log.  A "Copy All" button copies
    everything to the clipboard in one click.
    """

    MAX_LINES = 500  # Prevent unbounded memory growth.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Debug Console")
        self.resize(700, 380)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._log_view.setFont(QFont("Menlo", 10))
        self._log_view.setStyleSheet(
            "background-color: #1c1c1e; color: #e5e5ea; "
            "border: 1px solid #38383a; border-radius: 6px; "
            "selection-background-color: #0a84ff; selection-color: #ffffff;"
        )
        layout.addWidget(self._log_view)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        copy_btn = QPushButton("Copy All")
        copy_btn.setFixedWidth(90)
        copy_btn.clicked.connect(self._copy_all)
        btn_row.addWidget(copy_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(70)
        clear_btn.clicked.connect(self._log_view.clear)
        btn_row.addWidget(clear_btn)

        btn_row.addStretch(1)

        close_btn = QPushButton("✕ Close")
        close_btn.setFixedWidth(80)
        close_btn.setToolTip("Close the debug console")
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _copy_all(self):
        QApplication.clipboard().setText(self._log_view.toPlainText())

    def append(self, message: str):
        """Append a timestamped message (local time).  Trims the log if it grows too large."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_view.append(f"[{ts}]  {message}")

        # Trim to MAX_LINES to avoid unbounded growth.
        doc = self._log_view.document()
        while doc.blockCount() > self.MAX_LINES:
            cursor = self._log_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # Remove the trailing newline.

        # Auto-scroll to the latest entry.
        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum()
        )


class LiveControllerMac(QWidget):
    """The main application window and controller — macOS version."""

    # Milliseconds of main-thread silence before the freeze watchdog logs a warning.
    _FREEZE_WARN_MS = 1500

    def __init__(self):
        super().__init__()
        self.setWindowTitle("KATTMAN CONTROL")

        # Debug console (created early so _debug_log works immediately).
        self._debug_console = DebugConsoleWindow(self)

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
        self._user_stopped = False
        self.test_track_path = None

        self.current_table_font_size = DEFAULT_TABLE_FONT_SIZE
        self.playing_color = QColor("#30d158")
        self.default_color = QColor("#2c2c2e")
        self.count_in_bg_color = DEFAULT_COUNT_IN_BG_COLOR
        self.count_in_font_size = DEFAULT_COUNT_IN_FONT_SIZE
        self.track_play_bg_color = DEFAULT_TRACK_PLAY_BG_COLOR
        self.track_play_font_size = DEFAULT_TRACK_PLAY_FONT_SIZE

        # Color scheme for backgrounds and text (populated from session on load).
        self._color_scheme = dict(DEFAULT_COLOR_SCHEME)

        # --- Scrub / loop state ---
        self._current_playback_pos = 0.0       # seconds, updated by position poller
        self._current_track_duration = 0.0     # seconds, updated by position poller
        self._slider_being_dragged = False      # True while user holds the scrub slider
        self._loop_a_seconds = 0.0             # loop start point (seconds)
        self._loop_b_seconds = 0.0             # loop end point (seconds)

        # Background thread that polls mpv's playback position without blocking the UI.
        self._position_poller = PositionPoller()
        self._position_poller.position_updated.connect(self._on_position_updated)
        self._position_poller.start()

        self.countdown_timer = QTimer(self)
        self.countdown_seconds = 0
        self.countdown_connection = None

        self.active_flash_timer = QTimer(self)
        self.active_flash_timer.setInterval(ACTIVE_FLASH_INTERVAL_MS)
        self.active_flash_timer.timeout.connect(self.toggle_active_label_visibility)

        # Single-shot timer used to defer a second focus-restore pass after q is pressed.
        # Storing it as an instance allows cancelling any pending shot before rescheduling.
        self._focus_restore_timer = QTimer(self)
        self._focus_restore_timer.setSingleShot(True)
        self._focus_restore_timer.setInterval(MACOS_FOCUS_RESTORE_DELAY_MS)
        self._focus_restore_timer.timeout.connect(self._focus_main_window)

        self.setup_ui()
        self.apply_config_to_ui()
        # Full-screen mode is requested at startup from the __main__ block via QTimer.
        self.hotkey_listener = None
        self._start_hotkey_listener()
        self.load_session()
        self._debug_log("App started.")

        # UI-freeze watchdog: fires every 500 ms from the main thread.
        # _last_heartbeat is set immediately before the timer starts so the
        # first tick never produces a spurious freeze warning.
        self._last_heartbeat = time.monotonic()
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(500)
        self._heartbeat_timer.timeout.connect(self._update_heartbeat)
        self._heartbeat_timer.start()

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
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Key", "Track Name", "Link", "Secs", "Del"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(10)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(2, 36)
        self.table.setColumnWidth(3, 46)
        self.table.setColumnWidth(4, 36)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.rows_reordered.connect(self.reorder_tracks)

        # --- Right-side Control Panel (2-column layout, no scroll area) ---
        controls_area = QVBoxLayout()
        controls_area.setSpacing(3)

        # Playback & Setlist group
        main_controls_group = QGroupBox("Playback & Setlist")
        main_controls_layout = QVBoxLayout()
        main_controls_layout.setContentsMargins(4, 6, 4, 4)
        main_controls_layout.setSpacing(3)

        self.stop_button = QPushButton("■  STOP  (q)")
        self.stop_button.setStyleSheet(
            "background-color: #3a0a0a; color: #ff453a; border: 1px solid #7a1a1a; "
            "font-size: 12px; font-weight: 700; padding: 5px 8px; border-radius: 6px;"
        )
        self.stop_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.stop_button.clicked.connect(self.stop_all_activity)

        add_buttons_layout = QHBoxLayout()
        add_buttons_layout.setSpacing(4)
        self.add_button = QPushButton("+ Add Track(s)")
        self.add_button.setStyleSheet(
            "background-color: #0a2a4a; color: #0a84ff; border: 1px solid #1a4a7a; "
            "font-size: 11px; padding: 3px 6px; border-radius: 6px;"
        )
        self.add_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_button.clicked.connect(self.add_tracks)
        self.add_encore_button = QPushButton("+ Add Encore")
        self.add_encore_button.setStyleSheet(
            "background-color: #0a2a4a; color: #0a84ff; border: 1px solid #1a4a7a; "
            "font-size: 11px; padding: 3px 6px; border-radius: 6px;"
        )
        self.add_encore_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_encore_button.clicked.connect(self.add_encore_divider)
        add_buttons_layout.addWidget(self.add_button)
        add_buttons_layout.addWidget(self.add_encore_button)

        self.undo_button = QPushButton("↩  Undo Delete")
        self.undo_button.clicked.connect(self.undo_delete)
        self.undo_button.setEnabled(False)

        setlist_name_layout = QHBoxLayout()
        setlist_name_layout.setSpacing(4)
        self.setlist_name_input = QLineEdit()
        self.setlist_name_input.setPlaceholderText("Setlist name…")
        self.rename_button = QPushButton("Set")
        self.rename_button.setFixedWidth(48)
        self.rename_button.clicked.connect(self.rename_setlist_title)
        setlist_name_layout.addWidget(self.setlist_name_input, 1)
        setlist_name_layout.addWidget(self.rename_button)

        save_load_layout = QHBoxLayout()
        save_load_layout.setSpacing(4)
        self.save_button = QPushButton("Save")
        self.save_button.setStyleSheet(
            "background-color: #0a2a4a; color: #0a84ff; border: 1px solid #1a4a7a; "
            "font-size: 11px; padding: 3px 6px; border-radius: 6px;"
        )
        self.save_button.clicked.connect(self.save_setlist)
        self.load_button = QPushButton("Load")
        self.load_button.setStyleSheet(
            "background-color: #0a2a0a; color: #30d158; border: 1px solid #1a5a1a; "
            "font-size: 11px; padding: 3px 6px; border-radius: 6px;"
        )
        self.load_button.clicked.connect(self.load_setlist)
        save_load_layout.addWidget(self.save_button)
        save_load_layout.addWidget(self.load_button)

        main_controls_layout.addWidget(self.stop_button)
        main_controls_layout.addLayout(add_buttons_layout)
        main_controls_layout.addWidget(self.undo_button)
        main_controls_layout.addLayout(setlist_name_layout)
        main_controls_layout.addLayout(save_load_layout)

        self.audio_only_checkbox = QCheckBox("Audio Only (no video)")
        self.audio_only_checkbox.setToolTip(
            "When checked, audio plays from video files but no video is sent to the display.\n"
            "Useful when no projector or external screen is connected.\n"
            "This setting is saved with the setlist."
        )
        main_controls_layout.addWidget(self.audio_only_checkbox)
        main_controls_group.setLayout(main_controls_layout)

        # Settings group
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout()
        settings_layout.setContentsMargins(4, 6, 4, 4)
        settings_layout.setSpacing(3)

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
        font_size_layout.setSpacing(4)
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 36)
        self.font_size_spinbox.setValue(self.current_table_font_size)
        self.apply_font_button = QPushButton("Apply")
        self.apply_font_button.setMinimumWidth(64)
        self.apply_font_button.clicked.connect(self.apply_table_font_size)
        font_size_layout.addWidget(self.font_size_spinbox)
        font_size_layout.addWidget(self.apply_font_button)
        settings_layout.addWidget(QLabel("List Font:"), 4, 0)
        settings_layout.addLayout(font_size_layout, 4, 1)
        settings_group.setLayout(settings_layout)

        # Test Track group (full-width, single compact row)
        test_track_group = QGroupBox("Test Track")
        test_track_layout = QHBoxLayout()
        test_track_layout.setContentsMargins(4, 6, 4, 4)
        test_track_layout.setSpacing(3)
        self.test_file_button = QPushButton("Select…")
        self.test_file_button.setFixedWidth(70)
        self.test_file_button.clicked.connect(self.select_test_file)
        self.test_file_label = QLabel("No file selected.")
        self.test_file_label.setStyleSheet("font-style: italic; color: #636366;")
        self.test_file_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.play_test_button = QPushButton("▶  Play Test  (t)")
        self.play_test_button.setStyleSheet(
            "background-color: #0a2a0a; color: #30d158; border: 1px solid #1a5a1a; "
            "font-size: 11px; padding: 3px 6px; border-radius: 6px;"
        )
        self.play_test_button.clicked.connect(self.play_test_track)
        self.play_test_button.setEnabled(False)
        test_track_layout.addWidget(self.test_file_button)
        test_track_layout.addWidget(self.test_file_label, 1)
        test_track_layout.addWidget(self.play_test_button)
        test_track_group.setLayout(test_track_layout)

        # Scrub & Loop group
        scrub_loop_group = QGroupBox("Scrub & Loop")
        scrub_loop_layout = QVBoxLayout()
        scrub_loop_layout.setContentsMargins(4, 6, 4, 4)
        scrub_loop_layout.setSpacing(3)

        # Scrub slider row: [pos] [slider] [dur]
        scrub_row = QHBoxLayout()
        scrub_row.setSpacing(4)
        self.scrub_pos_label = QLabel("--:--")
        self.scrub_pos_label.setFixedWidth(38)
        self.scrub_pos_label.setStyleSheet("font-size: 10px; color: #aeaeb2;")
        self.scrub_slider = QSlider(Qt.Orientation.Horizontal)
        self.scrub_slider.setRange(0, 1000)
        self.scrub_slider.setValue(0)
        self.scrub_slider.setEnabled(False)
        self.scrub_slider.setToolTip("Drag to seek to a different position in the currently playing file.")
        self.scrub_slider.sliderMoved.connect(self._on_scrub_slider_moved)
        self.scrub_slider.sliderReleased.connect(self._on_scrub_slider_released)
        self.scrub_dur_label = QLabel("--:--")
        self.scrub_dur_label.setFixedWidth(38)
        self.scrub_dur_label.setStyleSheet("font-size: 10px; color: #aeaeb2;")
        scrub_row.addWidget(self.scrub_pos_label)
        scrub_row.addWidget(self.scrub_slider, 1)
        scrub_row.addWidget(self.scrub_dur_label)

        # Loop points row: [A: --:--] [B: --:--] [Loop A→B]
        # Each button combines the label and current time so the loop point text
        # is always visible inside the button itself.
        loop_row = QHBoxLayout()
        loop_row.setSpacing(3)
        self.loop_set_a_btn = QPushButton("A: --:--")
        self.loop_set_a_btn.setFixedWidth(82)
        self.loop_set_a_btn.setEnabled(False)
        self.loop_set_a_btn.setToolTip("Mark the current playback position as loop start (A).")
        self.loop_set_a_btn.clicked.connect(self._set_loop_a)
        self.loop_set_b_btn = QPushButton("B: --:--")
        self.loop_set_b_btn.setFixedWidth(82)
        self.loop_set_b_btn.setEnabled(False)
        self.loop_set_b_btn.setToolTip("Mark the current playback position as loop end (B).")
        self.loop_set_b_btn.clicked.connect(self._set_loop_b)
        self.loop_checkbox = QCheckBox("Loop A→B")
        self.loop_checkbox.setToolTip(
            "When checked, mpv will repeat the section between loop points A and B continuously."
        )
        self.loop_checkbox.toggled.connect(self._on_loop_toggled)
        loop_row.addWidget(self.loop_set_a_btn)
        loop_row.addWidget(self.loop_set_b_btn)
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

        # Overlay Colours group
        overlay_colours_group = QGroupBox("Overlay Colours")
        overlay_colours_layout = QGridLayout()
        overlay_colours_layout.setContentsMargins(4, 6, 4, 4)
        overlay_colours_layout.setSpacing(3)

        self.count_in_color_button = QPushButton()
        self.count_in_color_button.setFixedSize(18, 18)
        self.count_in_color_button.setStyleSheet(
            f"background-color: {DEFAULT_COUNT_IN_BG_COLOR}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;"
        )
        self.count_in_color_button.clicked.connect(self.pick_count_in_color)

        self.count_in_font_spinbox = QSpinBox()
        self.count_in_font_spinbox.setRange(20, 500)
        self.count_in_font_spinbox.setValue(DEFAULT_COUNT_IN_FONT_SIZE)
        self.count_in_font_spinbox.setMaximumWidth(58)
        self.count_in_font_spinbox.valueChanged.connect(self._on_count_in_font_changed)

        self.track_play_color_button = QPushButton()
        self.track_play_color_button.setFixedSize(18, 18)
        self.track_play_color_button.setStyleSheet(
            f"background-color: {DEFAULT_TRACK_PLAY_BG_COLOR}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;"
        )
        self.track_play_color_button.clicked.connect(self.pick_track_play_color)

        self.track_play_font_spinbox = QSpinBox()
        self.track_play_font_spinbox.setRange(20, 500)
        self.track_play_font_spinbox.setValue(DEFAULT_TRACK_PLAY_FONT_SIZE)
        self.track_play_font_spinbox.setMaximumWidth(58)
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

        # Color Scheme group — controls app background and text colors.
        # Button styling is intentionally excluded (buttons use fixed inline styles).
        color_scheme_group = QGroupBox("Color Scheme")
        color_scheme_layout = QGridLayout()
        color_scheme_layout.setContentsMargins(4, 6, 4, 4)
        color_scheme_layout.setSpacing(3)

        # Preset themes dropdown — row 0, spans all columns.
        self.scheme_preset_combo = QComboBox()
        self.scheme_preset_combo.addItem("— Presets —")
        for _preset_name, _ in COLOR_SCHEME_PRESETS:
            self.scheme_preset_combo.addItem(_preset_name)
        self.scheme_preset_combo.setToolTip("Apply a built-in color theme to the whole UI")
        self.scheme_preset_combo.currentIndexChanged.connect(self._apply_preset_scheme)
        color_scheme_layout.addWidget(self.scheme_preset_combo, 0, 0, 1, 4)

        # Helper: create a compact color swatch button for *key* with *label* text.
        def make_swatch(key, hex_color):
            btn = QPushButton()
            btn.setFixedSize(18, 18)
            btn.setStyleSheet(
                f"background-color: {hex_color}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;"
            )
            btn.clicked.connect(lambda _checked, k=key: self._pick_scheme_color(k))
            return btn

        scheme = self._color_scheme
        self._scheme_swatches = {}  # key → QPushButton

        self._scheme_swatches['app_bg']       = make_swatch('app_bg',       scheme['app_bg'])
        self._scheme_swatches['app_fg']       = make_swatch('app_fg',       scheme['app_fg'])
        self._scheme_swatches['panel_bg']     = make_swatch('panel_bg',     scheme['panel_bg'])
        self._scheme_swatches['table_bg']     = make_swatch('table_bg',     scheme['table_bg'])
        self._scheme_swatches['table_alt_bg'] = make_swatch('table_alt_bg', scheme['table_alt_bg'])
        self._scheme_swatches['header_fg']    = make_swatch('header_fg',    scheme['header_fg'])
        self._scheme_swatches['border_color'] = make_swatch('border_color', scheme['border_color'])

        color_scheme_layout.addWidget(QLabel("App BG:"),        1, 0)
        color_scheme_layout.addWidget(self._scheme_swatches['app_bg'],        1, 1)
        color_scheme_layout.addWidget(QLabel("App Text:"),      1, 2)
        color_scheme_layout.addWidget(self._scheme_swatches['app_fg'],        1, 3)

        color_scheme_layout.addWidget(QLabel("Panel BG:"),      2, 0)
        color_scheme_layout.addWidget(self._scheme_swatches['panel_bg'],      2, 1)
        color_scheme_layout.addWidget(QLabel("Table Alt:"),     2, 2)
        color_scheme_layout.addWidget(self._scheme_swatches['table_alt_bg'],  2, 3)

        color_scheme_layout.addWidget(QLabel("Table BG:"),      3, 0)
        color_scheme_layout.addWidget(self._scheme_swatches['table_bg'],      3, 1)
        color_scheme_layout.addWidget(QLabel("Header Text:"),   3, 2)
        color_scheme_layout.addWidget(self._scheme_swatches['header_fg'],     3, 3)

        color_scheme_layout.addWidget(QLabel("Borders:"),       4, 0)
        color_scheme_layout.addWidget(self._scheme_swatches['border_color'],  4, 1)

        # Action buttons row
        scheme_btns_layout = QHBoxLayout()
        scheme_btns_layout.setSpacing(3)
        self.scheme_reset_button = QPushButton("Reset")
        self.scheme_reset_button.setToolTip("Reset all colors to the built-in default scheme")
        self.scheme_reset_button.clicked.connect(self._reset_color_scheme)
        self.scheme_export_button = QPushButton("Export…")
        self.scheme_export_button.setToolTip("Save the current color scheme to a JSON file")
        self.scheme_export_button.clicked.connect(self._export_color_scheme)
        self.scheme_import_button = QPushButton("Import…")
        self.scheme_import_button.setToolTip("Load a color scheme from a JSON file")
        self.scheme_import_button.clicked.connect(self._import_color_scheme)
        scheme_btns_layout.addWidget(self.scheme_reset_button)
        scheme_btns_layout.addWidget(self.scheme_export_button)
        scheme_btns_layout.addWidget(self.scheme_import_button)

        color_scheme_layout.addLayout(scheme_btns_layout, 5, 0, 1, 4)
        color_scheme_group.setLayout(color_scheme_layout)

        # Application group (horizontal for compactness)
        app_group = QGroupBox("Application")
        app_layout = QHBoxLayout()
        app_layout.setContentsMargins(4, 6, 4, 4)
        app_layout.setSpacing(3)
        self.debug_console_button = QPushButton("Debug Console")
        self.debug_console_button.setStyleSheet(
            "background-color: #1a1a3a; color: #636396; border: 1px solid #2a2a5a; "
            "font-size: 11px; padding: 3px 6px; border-radius: 6px;"
        )
        self.debug_console_button.clicked.connect(self._show_debug_console)
        self.quit_button = QPushButton("Quit")
        self.quit_button.setStyleSheet(
            "background-color: #3a0a0a; color: #ff453a; border: 1px solid #7a1a1a; "
            "font-size: 12px; padding: 4px 8px; border-radius: 6px;"
        )
        self.quit_button.clicked.connect(self.close)
        app_layout.addWidget(self.debug_console_button)
        app_layout.addWidget(self.quit_button)
        app_group.setLayout(app_layout)

        # Arrange groups in 2 columns to avoid vertical overflow.
        # Row 1: Playback & Setlist (left) + Settings (right)
        row_top = QHBoxLayout()
        row_top.setSpacing(6)
        row_top.addWidget(main_controls_group)
        row_top.addWidget(settings_group)

        # Row 2: Scrub & Loop (left) + Overlay Colours / Color Scheme / Application stacked (right)
        row_mid = QHBoxLayout()
        row_mid.setSpacing(6)
        row_mid.addWidget(scrub_loop_group)
        right_col = QVBoxLayout()
        right_col.setSpacing(3)
        right_col.addWidget(overlay_colours_group)
        right_col.addWidget(color_scheme_group)
        right_col.addWidget(app_group)
        row_mid.addLayout(right_col)

        controls_area.addLayout(row_top)
        controls_area.addWidget(test_track_group)
        controls_area.addLayout(row_mid)
        controls_area.addStretch(1)

        controls_widget = QWidget()
        controls_widget.setLayout(controls_area)

        main_layout.addWidget(self.table, 1)
        main_layout.addWidget(controls_widget, 1)

        # Trust warning banner — hidden until Accessibility permission is missing.
        self.trust_banner = QWidget()
        self.trust_banner.setStyleSheet(
            "background-color: #3a2a00; border: 1px solid #c8a000; border-radius: 6px;"
        )
        trust_banner_layout = QHBoxLayout(self.trust_banner)
        trust_banner_layout.setContentsMargins(8, 4, 8, 4)
        trust_banner_layout.setSpacing(8)
        trust_warn_label = QLabel(
            "⚠  Global hotkeys need Accessibility permission — "
            "System Settings → Privacy & Security → Accessibility, "
            "add your terminal or Python binary, then restart."
        )
        trust_warn_label.setStyleSheet(
            "color: #ffd60a; font-size: 11px; background: transparent; border: none;"
        )
        trust_warn_label.setWordWrap(True)
        self._open_settings_btn = QPushButton("Open Settings")
        self._open_settings_btn.setFixedWidth(110)
        self._open_settings_btn.setStyleSheet(
            "background-color: #c8a000; color: #1c1c1e; border: none; "
            "font-size: 11px; padding: 3px 8px; border-radius: 5px; font-weight: 600;"
        )
        self._open_settings_btn.clicked.connect(self._open_accessibility_settings)
        trust_banner_layout.addWidget(trust_warn_label, 1)
        trust_banner_layout.addWidget(self._open_settings_btn)
        self.trust_banner.hide()

        self.status_label = QLabel("Status: Welcome!")
        self.status_label.setStyleSheet(
            "font-style: italic; color: #636366; font-size: 11px; "
            "padding: 3px 0px; border-top: 1px solid #2c2c2e;"
        )

        self.layout.addLayout(top_bar_layout)
        self.layout.addWidget(separator)
        self.layout.addLayout(main_layout, 1)
        self.layout.addWidget(self.trust_banner)
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
            f"color: white; border-radius: 20px; font-family: 'Helvetica Neue'; "
            f"font-size: {self.count_in_font_size}pt; font-weight: 800;"
        )

        track_play_c = QColor(self.track_play_bg_color)
        self.preparing_label.setStyleSheet(
            f"background-color: rgba({track_play_c.red()}, {track_play_c.green()}, {track_play_c.blue()}, 0.8); "
            f"color: white; border-radius: 20px; font-family: 'Helvetica Neue'; "
            f"font-size: {self.track_play_font_size}pt; font-weight: 700;"
        )

    def pick_count_in_color(self):
        color = QColorDialog.getColor(QColor(self.count_in_bg_color), self, "Count-In Background Colour")
        if color.isValid():
            self.count_in_bg_color = color.name()
            self.count_in_color_button.setStyleSheet(f"background-color: {self.count_in_bg_color}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;")
            self.apply_overlay_styles()

    def pick_track_play_color(self):
        color = QColorDialog.getColor(QColor(self.track_play_bg_color), self, "Track Play Background Colour")
        if color.isValid():
            self.track_play_bg_color = color.name()
            self.track_play_color_button.setStyleSheet(f"background-color: {self.track_play_bg_color}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;")
            self.apply_overlay_styles()

    def _on_count_in_font_changed(self, value):
        self.count_in_font_size = value
        self.apply_overlay_styles()

    def _on_track_play_font_changed(self, value):
        self.track_play_font_size = value
        self.apply_overlay_styles()

    # ------------------------------------------------------------------ #
    # Color scheme helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_color_scheme(raw):
        """Return a clean scheme dict built from *raw*, falling back to defaults for invalid entries.

        Accepts any mapping; unknown keys are ignored and invalid color strings
        are replaced with their DEFAULT_COLOR_SCHEME equivalents.
        """
        scheme = dict(DEFAULT_COLOR_SCHEME)
        for key in DEFAULT_COLOR_SCHEME:
            value = raw.get(key)
            if isinstance(value, str) and QColor(value).isValid():
                scheme[key] = value
        return scheme

    def apply_color_scheme(self, scheme):
        """Apply *scheme* to the application stylesheet and update all swatch buttons."""
        self._color_scheme = dict(scheme)
        QApplication.instance().setStyleSheet(_build_stylesheet(self._color_scheme))
        for key, btn in self._scheme_swatches.items():
            color = self._color_scheme.get(key, DEFAULT_COLOR_SCHEME[key])
            btn.setStyleSheet(
                f"background-color: {color}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;"
            )

    def _pick_scheme_color(self, key):
        """Open a color picker for *key* and apply the result."""
        current = self._color_scheme.get(key, DEFAULT_COLOR_SCHEME[key])
        label_map = {
            'app_bg':       'App Background',
            'app_fg':       'App Text',
            'panel_bg':     'Panel Background',
            'table_bg':     'Table Background',
            'table_alt_bg': 'Table Alternate Row',
            'header_fg':    'Header Text',
            'border_color': 'Border / Lines',
        }
        color = QColorDialog.getColor(QColor(current), self, label_map.get(key, key))
        if color.isValid():
            new_scheme = dict(self._color_scheme)
            new_scheme[key] = color.name()
            self.apply_color_scheme(new_scheme)
            self.save_session()
            self.status_label.setText(f"Status: Color '{label_map.get(key, key)}' updated.")

    def _reset_color_scheme(self):
        """Reset the color scheme to the built-in defaults."""
        self.apply_color_scheme(dict(DEFAULT_COLOR_SCHEME))
        self.save_session()
        self.status_label.setText("Status: Color scheme reset to defaults.")

    def _apply_preset_scheme(self, index):
        """Apply the preset theme selected in scheme_preset_combo (index 0 = placeholder)."""
        if index <= 0:
            return
        name, scheme = COLOR_SCHEME_PRESETS[index - 1]
        self.apply_color_scheme(dict(scheme))
        self.save_session()
        self.status_label.setText(f"Status: Theme '{name}' applied.")

    def _export_color_scheme(self):
        """Save the current color scheme to a JSON file chosen by the user."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Color Scheme", _DEFAULT_DIALOG_DIR, COLOR_SCHEME_FILE_FILTER
        )
        if not path:
            return
        if not path.endswith('.json'):
            path += '.json'
        try:
            with open(path, 'w') as f:
                json.dump(self._color_scheme, f, indent=4)
            self.status_label.setText(f"Status: Color scheme exported to {os.path.basename(path)}.")
        except OSError as exc:
            self.status_label.setText(f"Status: Export failed — {exc}")

    def _import_color_scheme(self):
        """Load a color scheme from a user-selected JSON file and apply it."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Color Scheme", _DEFAULT_DIALOG_DIR, COLOR_SCHEME_FILE_FILTER
        )
        if not path:
            return
        try:
            with open(path, 'r') as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self.status_label.setText(f"Status: Import failed — {exc}")
            return
        self.apply_color_scheme(self._validate_color_scheme(loaded))
        self.save_session()
        self.status_label.setText(f"Status: Color scheme imported from {os.path.basename(path)}.")

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
        self.audio_only_checkbox.setEnabled(is_edit_mode)
        # Color scheme controls — only available in edit mode.
        for swatch in self._scheme_swatches.values():
            swatch.setEnabled(is_edit_mode)
        self.scheme_preset_combo.setEnabled(is_edit_mode)
        self.scheme_reset_button.setEnabled(is_edit_mode)
        self.scheme_export_button.setEnabled(is_edit_mode)
        self.scheme_import_button.setEnabled(is_edit_mode)
        # Debug console button is always accessible.
        self.debug_console_button.setEnabled(True)

        for i in range(self.table.rowCount()):
            if i < len(self.tracks):
                item = self.tracks[i]
                if item['type'] == 'track':
                    for col in [1, 2, 3]:
                        if widget := self.table.cellWidget(i, col):
                            widget.setEnabled(is_edit_mode)

        self.live_mode_label.setStyleSheet("color: #ff453a; font-weight: bold; letter-spacing: 1px;" if self.is_live_mode else "color: #48484a;")
        self.edit_mode_label.setStyleSheet("color: #30d158; font-weight: bold; letter-spacing: 1px;" if is_edit_mode else "color: #48484a;")
        mode_name = "LIVE" if self.is_live_mode else "EDIT"
        self.status_label.setText(
            "Status: LIVE MODE - Hotkeys are active." if self.is_live_mode
            else "Status: EDIT MODE - Hotkeys are disabled."
        )
        self._debug_log(f"Mode changed → {mode_name}")

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
            'audio_only': self.audio_only_checkbox.isChecked(),
            'scrub_locked': self.scrub_lock_checkbox.isChecked(),
            'loop_enabled': self.loop_checkbox.isChecked(),
            'color_scheme': self._color_scheme,
        }
        with open(SESSION_FILE, 'w') as f:
            json.dump(session_data, f, indent=4)

    def load_session(self):
        if not os.path.exists(SESSION_FILE):
            self.status_label.setText("Status: No previous session found. Welcome!")
            self.count_in_combo.setCurrentText(str(DEFAULT_COUNT_IN_SECONDS))
            self.count_in_test_checkbox.setChecked(True)
            self._debug_log("No previous session file found.")
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
            self.count_in_color_button.setStyleSheet(f"background-color: {self.count_in_bg_color}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;")
            self.count_in_font_spinbox.setValue(self.count_in_font_size)
            self.track_play_color_button.setStyleSheet(f"background-color: {self.track_play_bg_color}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;")
            self.track_play_font_spinbox.setValue(self.track_play_font_size)
            self.apply_overlay_styles()

            # Restore color scheme (validate all keys before applying).
            self.apply_color_scheme(self._validate_color_scheme(session_data.get('color_scheme', {})))

            self.undo_history = deque(session_data.get('undo_history', []), maxlen=MAX_UNDO_LEVELS)
            self._apply_setlist_data(session_data.get('tracks', []), session_data.get('setlist_name', 'Untitled Setlist'))

            self.audio_only_checkbox.setChecked(session_data.get('audio_only', False))

            self.scrub_lock_checkbox.setChecked(session_data.get('scrub_locked', False))
            self.loop_checkbox.setChecked(session_data.get('loop_enabled', False))
            self._update_scrub_controls_state()

            self.test_track_path = session_data.get('test_track_path')
            if self.test_track_path and os.path.exists(self.test_track_path):
                self.test_file_label.setText(os.path.basename(self.test_track_path))
                self.test_file_label.setStyleSheet("font-style: normal; color: #aeaeb2;")
                self.play_test_button.setEnabled(True)
            else:
                self.test_track_path = None

            setlist_name = session_data.get('setlist_name', '')
            track_count = len([t for t in session_data.get('tracks', []) if t.get('type') == 'track'])
            self._debug_log(
                f"Session restored: '{setlist_name}' ({track_count} tracks, "
                f"audio_only={session_data.get('audio_only', False)})"
            )
            self.status_label.setText(f"Status: Restored previous session: {setlist_name}")
        except (json.JSONDecodeError, FileNotFoundError) as exc:
            self._debug_log(f"ERROR loading session file: {exc}")
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
        mplayer_bin = MPLAYER_PATH if (os.path.isabs(MPLAYER_PATH) and os.path.exists(MPLAYER_PATH)) else shutil.which('mplayer')
        if not mplayer_bin:
            print("mplayer not found in PATH")
            return 0
        try:
            normalized_path = os.path.normpath(file_path)
            cmd = [mplayer_bin, "-vo", "null", "-ao", "null", "-identify", "-frames", "0", normalized_path]
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, timeout=30
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

                remove_button = QPushButton("✕")
                remove_button.clicked.connect(lambda checked, i=i: self.remove_item(i))
                remove_button.setFixedSize(18, 18)
                remove_button.setStyleSheet(
                    "background-color: transparent; color: #636366; border: none; "
                    "font-size: 12px; padding: 0px;"
                )
                btn_container = QWidget()
                btn_layout = QHBoxLayout(btn_container)
                btn_layout.addWidget(remove_button)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                self.table.setCellWidget(i, 4, btn_container)
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

                is_linked = item.get('linked', False)
                seconds_input = QLineEdit(str(max(0, min(99, item.get('gap_seconds', 0)))).zfill(2))
                seconds_input.setFont(table_font)
                seconds_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
                seconds_input.setMaxLength(2)
                seconds_input.setToolTip("Gap in seconds before next song (only active when Link is on)")
                seconds_input.setEnabled(is_linked)
                seconds_input.textChanged.connect(lambda text, path=item['path']: self.update_gap_seconds(path, text))
                seconds_input.editingFinished.connect(lambda w=seconds_input: w.setText(w.text().zfill(2) if w.text() else "00"))
                self.table.setCellWidget(i, 3, seconds_input)

                remove_button = QPushButton("✕")
                remove_button.clicked.connect(lambda checked, i=i: self.remove_item(i))
                remove_button.setFixedSize(18, 18)
                remove_button.setStyleSheet(
                    "background-color: transparent; color: #636366; border: none; "
                    "font-size: 12px; padding: 0px;"
                )
                btn_container = QWidget()
                btn_layout = QHBoxLayout(btn_container)
                btn_layout.addWidget(remove_button)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_container.setToolTip(tooltip_text)
                self.table.setCellWidget(i, 4, btn_container)

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
            seconds_widget = self.table.cellWidget(row_index, 3)
            if isinstance(seconds_widget, QLineEdit):
                seconds_widget.setEnabled(is_checked)

    def update_gap_seconds(self, file_path, text):
        try:
            value = max(0, min(99, int(text)))
        except ValueError:
            value = 0
        for item in self.tracks:
            if item.get('type') == 'track' and item.get('path') == file_path:
                item['gap_seconds'] = value
                break

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
            'audio_only': self.audio_only_checkbox.isChecked(),
            'table_font_size': self.current_table_font_size,
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
            self.count_in_color_button.setStyleSheet(f"background-color: {self.count_in_bg_color}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;")
            self.count_in_font_spinbox.setValue(self.count_in_font_size)
            self.track_play_color_button.setStyleSheet(f"background-color: {self.track_play_bg_color}; border-radius: 3px; border: 1px solid #38383a; min-height: 18px; max-height: 18px;")
            self.track_play_font_spinbox.setValue(self.track_play_font_size)
            self.apply_overlay_styles()
            self.audio_only_checkbox.setChecked(loaded_data.get('audio_only', False))
            table_font_size = loaded_data.get('table_font_size')
            if table_font_size is not None:
                self.current_table_font_size = table_font_size
                self.font_size_spinbox.setValue(self.current_table_font_size)
                # apply_table_font_size() is called by _apply_setlist_data() below
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
                if 'gap_seconds' not in item:
                    item['gap_seconds'] = 0
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
        If those are missing the OS may send SIGTRAP to the process at any point
        while the listener is running — including when special keys such as
        Caps Lock are pressed.  We install a permanent SIG_IGN handler so the
        signal is absorbed for the entire lifetime of the app rather than
        terminating the process.
        """
        # Permanently ignore SIGTRAP for the lifetime of the process.
        # macOS sends SIGTRAP when an untrusted process intercepts input events
        # (e.g. Caps Lock).  Restoring the default handler after listener startup
        # would leave the app exposed to that crash whenever those keys are pressed.
        if hasattr(signal, 'SIGTRAP'):
            signal.signal(signal.SIGTRAP, signal.SIG_IGN)

        # Pre-flight check: proactively show the guidance banner when the OS
        # has already denied Accessibility / Input Monitoring permissions.
        if _is_accessibility_trusted() is False:
            self._show_trust_banner()

        try:
            self.hotkey_listener = GlobalHotkeyListener()
            self.hotkey_listener.hotkey_pressed.connect(self.on_global_hotkey)
            self.hotkey_listener.listener_failed.connect(self._on_hotkey_listener_failed)
            self.hotkey_listener.start()
            self._debug_log("Hotkey listener started.")
        except Exception as exc:
            self.hotkey_listener = None
            self._show_hotkey_unavailable(str(exc))

    def _on_hotkey_listener_failed(self, error_msg):
        """Called via signal when the pynput listener thread fails to start."""
        self._debug_log(f"Hotkey listener failed: {error_msg}")
        lower_msg = error_msg.lower()
        if ('not trusted' in lower_msg or 'accessibility' in lower_msg
                or 'input monitoring' in lower_msg or 'permission' in lower_msg):
            self._show_trust_banner()
        else:
            self._show_hotkey_unavailable(error_msg)

    def _show_trust_banner(self):
        """Show the accessibility/trust warning banner with actionable guidance."""
        self.trust_banner.show()
        self.status_label.setText(
            "Status: Global hotkeys unavailable — Accessibility permission required (see banner above)."
        )
        self._debug_log("Accessibility/Input Monitoring trust check failed; showing guidance banner.")

    def _open_accessibility_settings(self):
        """Open macOS System Settings directly to the Accessibility privacy pane."""
        try:
            subprocess.Popen([
                'open',
                'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility',
            ])
        except Exception as exc:
            self._debug_log(f"Could not open System Settings: {exc}")

    def _show_hotkey_unavailable(self, detail=""):
        """Updates the status label to inform the user that hotkeys are disabled."""
        base = ("Status: Global hotkeys unavailable — grant Accessibility/Input Monitoring "
                "permissions in System Settings > Privacy & Security, then restart the app.")
        self.status_label.setText(f"{base} ({detail})" if detail else base)

    def _focus_main_window(self):
        """Brings the main window to the foreground and activates it."""
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def on_global_hotkey(self, key):
        """Handles key presses from the pynput-based global hotkey listener."""
        lower_key = key.lower()

        if self.worker and self.worker.isRunning() or self.countdown_timer.isActive():
            if lower_key == 'q':
                self._focus_main_window()
                self.stop_all_activity()
                self._focus_restore_timer.start()
            else:
                self.show_danger_message()
            return

        # '^' toggles EDIT/LIVE mode (e.g. from a Stream Deck).
        if lower_key == '^':
            self.live_mode_slider.setChecked(not self.live_mode_slider.isChecked())
            return

        if lower_key == 'q':
            self._focus_main_window()
            self._focus_restore_timer.start()
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
            self._debug_log(f"ERROR: execute_playback — invalid settings or track data: {e}")
            return

        audio_only = self.audio_only_checkbox.isChecked()
        label = "test track" if row_index is None else f"row {row_index}"
        self._debug_log(
            f"Playback start: {os.path.basename(track_path or '')} "
            f"({label}, display={display_num}, preload={preload_time}s, "
            f"audio_only={audio_only})"
        )

        self.clear_highlight()
        if row_index is not None:
            self.highlight_row(row_index, is_playing=True)
            self.currently_playing_row = row_index
        else:
            self.test_file_label.setStyleSheet("font-weight: bold; color: #30d158;")

        self.active_flash_timer.start()
        self.worker = VideoPlaybackWorker(track_path, display_num, preload_time,
                                          audio_only_mode=audio_only)
        self.worker.status_update.connect(self.status_label.setText)
        self.worker.error.connect(self._on_playback_error)
        self.worker.finished.connect(self.on_playback_finished)
        self.worker.ipc_socket_path.connect(self.set_ipc_socket)
        self.worker.start()
        self._update_scrub_controls_state()

    def _on_playback_error(self, msg):
        self.status_label.setText(f"ERROR: {msg}")
        self._debug_log(f"Playback ERROR: {msg}")

    def set_ipc_socket(self, path):
        self.current_ipc_socket = path
        self._position_poller.set_socket(path)

    def stop_all_activity(self):
        self._user_stopped = True
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
            self._debug_log("Countdown aborted by user.")

        if self.worker and self.worker.isRunning():
            self._debug_log("Stopping playback worker.")
            self.worker.stop()
            if self.current_ipc_socket:
                _send_ipc_command(self.current_ipc_socket, '{ "command": ["quit"] }')
            self.worker.wait()

        self.active_flash_timer.stop()
        self.active_label.hide()
        self._reset_scrub_controls()

    def on_playback_finished(self):
        finished_row = self.currently_playing_row
        self._debug_log("Playback finished.")
        self.clear_highlight()
        self.test_file_label.setStyleSheet("font-style: italic; color: #636366;")
        self.status_label.setText("Status: Ready. Press a hotkey to play a track.")
        self.active_flash_timer.stop()
        self.active_label.hide()
        if self.worker:
            self.worker.deleteLater()
        self.worker = None
        self.current_ipc_socket = None
        self._reset_scrub_controls()

        # Auto-play next track if the finished track was linked.
        if not self._user_stopped and finished_row is not None and finished_row < len(self.tracks):
            finished_track = self.tracks[finished_row]
            if finished_track.get('type') == 'track' and finished_track.get('linked', False):
                next_row = finished_row + 1
                while next_row < len(self.tracks) and self.tracks[next_row].get('type') == 'divider':
                    next_row += 1
                if next_row < len(self.tracks) and self.tracks[next_row].get('type') == 'track':
                    next_track = self.tracks[next_row]
                    delay_ms = max(0, finished_track.get('gap_seconds', 0)) * 1000
                    track_name_widget = self.table.cellWidget(next_row, 1)
                    if track_name_widget:
                        self.show_preparing_message(track_name_widget.text())
                    QTimer.singleShot(delay_ms, lambda nt=next_track, nr=next_row: self.execute_playback(nt, nr))
        self._user_stopped = False

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

    # ------------------------------------------------------------------ #
    # Scrub & Loop
    # ------------------------------------------------------------------ #

    def _on_position_updated(self, pos: float, dur: float):
        """Slot called by PositionPoller (via signal) whenever mpv reports a new position."""
        self._current_playback_pos = pos
        self._current_track_duration = dur
        if self._slider_being_dragged:
            return
        if dur > 0:
            slider_val = int((pos / dur) * 1000)
            # Block the sliderMoved signal while we update the slider programmatically.
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
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["seek", pos, "absolute"]}),
            )
            self._debug_log(f"Scrub seek → {self.format_duration(pos)}")

    def _set_loop_a(self):
        """Capture the current playback position as loop point A."""
        pos = self._current_playback_pos
        self._loop_a_seconds = pos
        self.loop_set_a_btn.setText(f"A: {self.format_duration(pos)}")
        if self.loop_checkbox.isChecked() and self.current_ipc_socket:
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["set_property", "ab-loop-a", pos]}),
            )
        self._debug_log(f"Loop A set → {self.format_duration(pos)}")

    def _set_loop_b(self):
        """Capture the current playback position as loop point B."""
        pos = self._current_playback_pos
        self._loop_b_seconds = pos
        self.loop_set_b_btn.setText(f"B: {self.format_duration(pos)}")
        if self.loop_checkbox.isChecked() and self.current_ipc_socket:
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["set_property", "ab-loop-b", pos]}),
            )
        self._debug_log(f"Loop B set → {self.format_duration(pos)}")

    def _on_loop_toggled(self, checked: bool):
        """Enable or disable mpv's A-B loop when the loop checkbox is toggled."""
        if not self.current_ipc_socket:
            return
        if checked:
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["set_property", "ab-loop-a", self._loop_a_seconds]}),
            )
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["set_property", "ab-loop-b", self._loop_b_seconds]}),
            )
            self._debug_log(
                f"Loop enabled: A={self.format_duration(self._loop_a_seconds)} "
                f"B={self.format_duration(self._loop_b_seconds)}"
            )
        else:
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["set_property", "ab-loop-a", "no"]}),
            )
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["set_property", "ab-loop-b", "no"]}),
            )
            self._debug_log("Loop disabled.")

    def _on_scrub_lock_changed(self, checked: bool):
        """Lock or unlock the scrub/loop controls and persist the setting."""
        self._update_scrub_controls_state()
        self._debug_log(f"Scrub/loop controls {'locked' if checked else 'unlocked'}.")

    def _update_scrub_controls_state(self):
        """Refresh enabled/disabled state for all scrub and loop widgets."""
        is_playing = self.worker is not None and self.worker.isRunning()
        locked = self.scrub_lock_checkbox.isChecked()
        self.scrub_slider.setEnabled(is_playing and not locked)
        self.loop_set_a_btn.setEnabled(is_playing and not locked)
        self.loop_set_b_btn.setEnabled(is_playing and not locked)
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
        self.loop_set_a_btn.setText("A: --:--")
        self.loop_set_b_btn.setText("B: --:--")
        self._update_scrub_controls_state()

    def _debug_log(self, message: str):
        """Append a message to the debug console (thread-safe from main thread)."""
        self._debug_console.append(message)

    def _show_debug_console(self):
        """Show (or bring to front) the debug console window."""
        self._debug_console.show()
        self._debug_console.raise_()
        self._debug_console.activateWindow()

    def _update_heartbeat(self):
        """Main-thread heartbeat tick used by the freeze watchdog."""
        now = time.monotonic()
        gap_ms = (now - self._last_heartbeat) * 1000
        if gap_ms > self._FREEZE_WARN_MS:
            self._debug_log(
                f"WARNING: main thread was unresponsive for ~{gap_ms:.0f} ms "
                "(UI freeze detected)"
            )
        self._last_heartbeat = now

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
        self._position_poller.stop()
        self._position_poller.wait()
        event.accept()


# --- Main Execution Block ---

def _set_high_priority():
    """Best-effort attempt to raise the process scheduling priority on macOS.

    Uses os.nice() to request a lower niceness value (higher CPU priority).
    On macOS, only root/privileged processes can set negative niceness values
    (i.e. niceness below 0); a standard user process cannot raise its priority
    above the default (niceness 0).  We attempt niceness -10 as a reasonable
    elevated value and let the OS refuse gracefully if permissions are lacking.

    Real-time / kernel-level priority (SCHED_RR / SCHED_FIFO) is not used
    here because it requires elevated privileges and is unsafe for a GUI app.
    """
    try:
        current_nice = os.nice(0)           # read current niceness
        desired_delta = -10 - current_nice  # aim for niceness == -10
        os.nice(desired_delta)              # OS raises PermissionError if not allowed
    except (OSError, PermissionError):
        # Graceful degradation: run at default priority if adjustment fails.
        pass


if __name__ == '__main__':
    # Raise process priority as much as is safely possible for a user-space app.
    _set_high_priority()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(_build_stylesheet(DEFAULT_COLOR_SCHEME))
    controller = LiveControllerMac()
    # Fill the primary screen's available geometry on startup so the window
    # launches visibly maximised without entering macOS fullscreen-space mode.
    # Using screen.availableGeometry() (excludes the menu bar and Dock) is more
    # reliable than showMaximized() / showFullScreen() on macOS, and avoids the
    # regression where the app appeared smaller than the display.
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        controller.setGeometry(screen.availableGeometry())
    # If primaryScreen() is None (no display available), fall back to showing at
    # the default window size so the app still starts rather than crashing.
    controller.show()
    controller.raise_()
    controller.activateWindow()
    sys.exit(app.exec())
