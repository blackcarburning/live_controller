# live_controller_mac.py
#
# Author: blackcarburning
#
# Description:
# A macOS-native live performance controller with synchronized playback,
# MIDI clock support, multi-zone zoom/scale compositing, Stream Deck export,
# and full setlist/session persistence.
#
# macOS Installation
# ------------------
# 1. Install system packages via Homebrew:
#       brew install mpv mplayer
#
# 2. Install Python packages:
#       pip install PyQt6 pynput python-rtmidi psutil pyserial
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
import platform
import re
import ssl
import ctypes
import ctypes.util
import signal
import shlex
import socket
import subprocess
import tempfile
import threading
import time
import traceback
import json
import shutil
import uuid
import zipfile
import urllib.request
import urllib.parse
from collections import deque
from datetime import datetime

# --- Third-Party Library Imports ---
# Requires: pynput
# Install with: pip install pynput
try:
    import pynput.keyboard as pynput_keyboard
except Exception:
    pynput_keyboard = None
try:
    import rtmidi
except Exception:
    rtmidi = None
try:
    import psutil
except Exception:
    psutil = None
try:
    import serial
    from serial.tools import list_ports
except Exception:
    serial = None
    list_ports = None

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QLineEdit, QHeaderView,
                             QGroupBox, QLabel, QFileDialog, QSizePolicy, QComboBox,
                             QAbstractButton, QAbstractItemView, QCheckBox,
                             QGridLayout, QSpinBox, QColorDialog, QTextEdit, QDialog,
                             QSlider, QRadioButton, QTabWidget, QStackedWidget, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QPoint, QEasingCurve, pyqtProperty, QTimer, QRect
from PyQt6.QtGui import QFont, QGuiApplication, QPainter, QColor, QBrush, QPen, QPixmap, QTextCursor


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


_DEBUG_LOG_HOOK = None


def _set_debug_log_hook(hook):
    global _DEBUG_LOG_HOOK
    _DEBUG_LOG_HOOK = hook


def _debug_log_runtime(message):
    hook = _DEBUG_LOG_HOOK
    if callable(hook):
        try:
            hook(message)
        except Exception:
            pass


def _format_command_for_log(command):
    return shlex.join([str(part) for part in command])


def _truncate_for_log(text, limit=500):
    if text is None:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


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
BPM_STORE_FILE = "mac_bpm_store.json"
CONFIG_FILE = "mac_fallback_config.json"
SESSION_FILE = "mac_fallback_session.json"
ZOOM_CONFIG_FILE = "mac_zoom_config.json"
ZOOM_FRAME_SNAPSHOT = "mac_zoom_frame_snapshot.png"
SETLISTS_DIR = "setlists"

# Default settings for playback and display
DEFAULT_VIDEO_SCREEN_NUMBER = 1
DEFAULT_LOAD_DELAY_SECONDS = 5
DEFAULT_MIDI_OFFSET_MS = 0
DEFAULT_COUNT_IN_SECONDS = 20
DEFAULT_TABLE_FONT_SIZE = 11           # Compact: was 16 on Windows
DEFAULT_COUNT_IN_FONT_SIZE = 120       # Compact: was 250 on Windows
DEFAULT_TRACK_PLAY_FONT_SIZE = 50      # Compact: was 80 on Windows
DEFAULT_STREAMDECK_FONT_SIZE = 12
DEFAULT_COUNT_IN_BG_COLOR = "#c80000"
DEFAULT_TRACK_PLAY_BG_COLOR = "#00c800"
TRACK_OVERHEAD_SECONDS = 15
MAX_UNDO_LEVELS = 30

# UI and timing constants
PREPARING_OVERLAY_DURATION_MS = 2000
ACTIVE_FLASH_INTERVAL_MS = 500
SAVE_POPUP_DURATION_MS = 3000
MPV_LAUNCH_HEAD_START_SECONDS = 2
# Delay (ms) before the second focus-restore pass after stopping playback on macOS.
# macOS may reassign focus during fullscreen/maximize teardown; a deferred re-activation
# ensures the main window reliably ends up in front after pressing q.
MACOS_FOCUS_RESTORE_DELAY_MS = 250

# Default directory for file dialogs (macOS Movies folder or home dir)
_DEFAULT_DIALOG_DIR = os.path.join(os.path.expanduser("~"), "Movies")
if not os.path.isdir(_DEFAULT_DIALOG_DIR):
    _DEFAULT_DIALOG_DIR = os.path.expanduser("~")

# --- MIDI Protocol Bytes ---
START_BYTE = 0xFA
STOP_BYTE = 0xFC
CLOCK_BYTE = 0xF8
SPP_BYTE = 0xF2

# --- Sync-Show API Defaults ---
DEFAULT_SYNC_SHOW_HOST = "https://meshlive.blackcarburning.com"
DEFAULT_SYNC_SHOW_SESSION = "0e49315f"
DEFAULT_SYNC_TIMING_TRIM_MS = 0

# --- Zoom compositor defaults ---
NUM_ZONES = 5
_ZONE_COLORS = ["#00e676", "#ff9800", "#2196f3", "#e040fb", "#ffeb3b"]

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

# Branded logo HTML — ▲ (U+25B2) replaces each A in KATTMAN
KATTMAN_LOGO_HTML = (
    '<span style="color:#f2f2f7; font-weight:700; font-size:22px; letter-spacing:4px;">'
    'K<span style="color:#0a84ff;">&#9650;</span>TTM'
    '<span style="color:#0a84ff;">&#9650;</span>N&nbsp;&nbsp;KONTROL&nbsp;&nbsp;KOMPLETE'
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
    _debug_log_runtime(f"IPC send → socket={socket_path} command={command_str}")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(socket_path)
        sock.sendall((command_str + '\n').encode('utf-8'))
        sock.close()
        _debug_log_runtime(f"IPC success → socket={socket_path} command={command_str}")
        return True
    except Exception as e:
        _debug_log_runtime(f"IPC error → socket={socket_path} command={command_str} error={e}")
        return False


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
    except Exception as exc:
        _debug_log_runtime(f"IPC query error → socket={socket_path} property={prop} error={exc}")
    return None


def _default_zone():
    return {
        "enabled": False,
        "crop_x": 0, "crop_y": 0, "crop_w": 1920, "crop_h": 1080,
        "scale_w": -1, "scale_h": -1,
        "border_px": 0,
        "offset_y": 0,
        "mode": "crop",
    }


def _normalize_snapshot_path(path):
    if not path:
        return ""
    return os.path.abspath(path)


def _migrate_zoom_config(cfg):
    def _backfill_composite(d):
        d.setdefault("out_w", -1)
        d.setdefault("out_h", -1)
        d.setdefault("out_sim_enabled", False)
        d.setdefault("comp_crop_x", 0)
        d.setdefault("comp_crop_y", 0)
        d.setdefault("comp_crop_w", 0)
        d.setdefault("comp_crop_h", 0)
        d.setdefault("comp_scale_w", -1)
        d.setdefault("comp_scale_h", -1)

    if not cfg:
        zones = [_default_zone() for _ in range(NUM_ZONES)]
        zones[0]["enabled"] = True
        result = {"zones": zones, "stack_direction": "horizontal", "frame_snapshot_path": ""}
        _backfill_composite(result)
        return result
    if "zones" in cfg:
        zones = list(cfg["zones"])
        while len(zones) < NUM_ZONES:
            zones.append(_default_zone())
        for z in zones:
            z.setdefault("border_px", 0)
            z.setdefault("offset_y", 0)
            z.setdefault("mode", "crop")
        result = {
            "zones": zones[:NUM_ZONES],
            "stack_direction": cfg.get("stack_direction", "horizontal"),
            "frame_snapshot_path": _normalize_snapshot_path(cfg.get("frame_snapshot_path", "")),
        }
        for k in ("out_w", "out_h", "out_sim_enabled",
                  "comp_crop_x", "comp_crop_y", "comp_crop_w", "comp_crop_h",
                  "comp_scale_w", "comp_scale_h"):
            if k in cfg:
                result[k] = cfg[k]
        _backfill_composite(result)
        return result
    zone0 = {
        "enabled": cfg.get("enabled", True),
        "crop_x": cfg.get("crop_x", 0),
        "crop_y": cfg.get("crop_y", 0),
        "crop_w": cfg.get("crop_w", 1920),
        "crop_h": cfg.get("crop_h", 1080),
        "scale_w": cfg.get("scale_w", -1),
        "scale_h": cfg.get("scale_h", -1),
        "border_px": 0,
        "offset_y": 0,
        "mode": "crop",
    }
    zones = [zone0] + [_default_zone() for _ in range(NUM_ZONES - 1)]
    result = {
        "zones": zones,
        "stack_direction": "horizontal",
        "frame_snapshot_path": _normalize_snapshot_path(cfg.get("frame_snapshot_path", "")),
    }
    _backfill_composite(result)
    return result


def _build_vf_for_zones(zoom_config):
    if not zoom_config:
        return None
    if "zones" not in zoom_config and not zoom_config.get("enabled"):
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
        offset_y = int(z.get("offset_y", 0))
        if offset_y != 0:
            abs_offset = abs(offset_y)
            pad_y = max(offset_y, 0)
            crop_y = max(-offset_y, 0)
            vf += f",pad=iw:ih+{abs_offset}:0:{pad_y}:black,crop=iw:ih:0:{crop_y}"
        return vf

    def _zone_out_size(z):
        sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
        w = sw if sw > 0 else z["crop_w"]
        h = sh if sh > 0 else z["crop_h"]
        border = z.get("border_px", 0)
        return w + 2 * border, h + 2 * border

    comp_crop_w = int(migrated.get("comp_crop_w", 0))
    comp_crop_h = int(migrated.get("comp_crop_h", 0))
    comp_crop_x = int(migrated.get("comp_crop_x", 0))
    comp_crop_y = int(migrated.get("comp_crop_y", 0))
    comp_scale_w = int(migrated.get("comp_scale_w", -1))
    comp_scale_h = int(migrated.get("comp_scale_h", -1))
    out_w = int(migrated.get("out_w", -1))
    out_h = int(migrated.get("out_h", -1))
    out_sim_enabled = bool(migrated.get("out_sim_enabled", False))

    def _composite_suffix():
        parts = []
        if comp_crop_w > 0 and comp_crop_h > 0:
            parts.append(f"crop={comp_crop_w}:{comp_crop_h}:{comp_crop_x}:{comp_crop_y}")
        if comp_scale_w > 0 and comp_scale_h > 0:
            parts.append(f"scale={comp_scale_w}:{comp_scale_h}")
        if out_sim_enabled and out_w > 0 and out_h > 0:
            parts.append(f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black")
        return "," + ",".join(parts) if parts else ""

    if len(enabled) == 1:
        return f"lavfi=[{_zone_vf(enabled[0])}{_composite_suffix()},setsar=1]"

    n = len(enabled)
    zone_sizes = [_zone_out_size(z) for z in enabled]
    target_h = max(s[1] for s in zone_sizes)
    target_w = max(s[0] for s in zone_sizes)

    split_tags = "".join(f"[z{i}]" for i in range(n))
    split_part = f"split={n}{split_tags}"

    def _zone_segment(z, size, i):
        vf_str = _zone_vf(z)
        out_w_z, out_h_z = size
        if direction == "horizontal" and out_h_z < target_h:
            vf_str += f",pad=iw:{target_h}:0:0:black"
        elif direction == "vertical" and out_w_z < target_w:
            vf_str += f",pad={target_w}:ih:0:0:black"
        return f"[z{i}]{vf_str}[c{i}]"

    crop_parts = [_zone_segment(z, zone_sizes[i], i) for i, z in enumerate(enabled)]
    stack_inputs = "".join(f"[c{i}]" for i in range(n))
    stack_fn = "vstack" if direction == "vertical" else "hstack"
    stack_part = f"{stack_inputs}{stack_fn}=inputs={n}{_composite_suffix()},setsar=1"
    graph = ";".join([split_part] + crop_parts + [stack_part])
    return f"lavfi=[{graph}]"


def _make_unique_mpv_pipe_name(prefix):
    # macOS divergence: Unix-domain socket path (no Windows named pipes).
    # AF_UNIX paths are capped at ~104 bytes on macOS, and the per-user
    # TMPDIR (/var/folders/<...>/T/) alone eats ~50 of them. Use /tmp and a
    # short unique suffix so the total stays well under the limit.
    short_id = uuid.uuid4().hex[:8]
    path = f"/tmp/{prefix}_{os.getpid()}_{short_id}.sock"
    if len(path.encode("utf-8")) > 100:
        path = f"/tmp/mpv_{short_id}.sock"
    return path




def _build_external_preview_mpv_command(
    mpv_path,
    ipc_path,
    output_display_num,
    source_path,
    *,
    is_video_source,
    paused=False,
    vf_str="",
):
    """Build the external-preview mpv command line for either video or still images."""
    cmd = [
        mpv_path,
        f"--input-ipc-server={ipc_path}",
        "--fullscreen",
        f"--fs-screen={output_display_num}",
        "--no-osd-bar",
        "--no-osc",
        "--no-input-default-bindings",
        "--really-quiet",
        "--keep-open=yes",
    ]
    if is_video_source:
        cmd.append("--loop-file=inf")
    else:
        cmd.append("--image-display-duration=inf")
    if paused:
        cmd.append("--pause")
    if vf_str:
        cmd.append(f"--vf={vf_str}")
    cmd.append(source_path)
    return cmd


def _build_multizone_capture_preview_mpv_command(mpv_path, ipc_path, video_path):
    """Build the windowed mpv command used for Multi-Zone frame capture preview."""
    return [
        mpv_path,
        f"--input-ipc-server={ipc_path}",
        "--pause",
        "--no-fullscreen",
        "--geometry=800x600",
        "--title=Multi-Zone Preview — navigate then click Capture Frame",
        "--ontop",
        "--no-osd-bar",
        "--no-osc",
        "--no-input-default-bindings",
        "--loop-file=inf",
        "--really-quiet",
        video_path,
    ]


def _mz_format_duration(seconds):
    """Format *seconds* as MM:SS for display in the Multi-Zone scrub bar."""
    if seconds is None or seconds < 0:
        return "00:00"
    total = int(seconds)
    mins, secs = divmod(total, 60)
    return f"{mins:02d}:{secs:02d}"

def _send_mpv_ipc_command(ipc_path, command, max_attempts=2, retry_delay=0.05):
    payload = json.dumps({"command": command}, ensure_ascii=False)
    attempts = max(1, max_attempts)
    last_error = "Unknown IPC error."
    for i in range(attempts):
        try:
            if _send_ipc_command(ipc_path, payload):
                return True, ""
            last_error = f"IPC send failed for socket {ipc_path}"
        except Exception as exc:
            last_error = str(exc)
        if i < attempts - 1:
            time.sleep(retry_delay)
    return False, last_error


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


class MidiTestWorker(QThread):
    finished = pyqtSignal(int)
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, port_num, bpm, send_start):
        super().__init__()
        self.port_num = port_num
        self.bpm = bpm
        self.send_start = send_start
        self._is_running = True
        self.midiout = None

    def stop(self):
        self._is_running = False

    def run(self):
        if rtmidi is None:
            self.error.emit("python-rtmidi not installed.")
            self.finished.emit(self.port_num)
            return
        try:
            self.status_update.emit(f"Testing MIDI port {self.port_num} at {self.bpm} BPM...")
            self.midiout = rtmidi.MidiOut()
            self.midiout.open_port(self.port_num)
            if self.send_start:
                self.midiout.send_message([SPP_BYTE, 0, 0])
                self.midiout.send_message([START_BYTE])
            tick_interval = 60.0 / max(1, self.bpm) / 24.0
            next_tick = time.perf_counter()
            while self._is_running:
                if time.perf_counter() >= next_tick:
                    self.midiout.send_message([CLOCK_BYTE])
                    next_tick += tick_interval
                time.sleep(0.001)
        except Exception as e:
            self.error.emit(f"MIDI test error on port {self.port_num}: {e}")
        finally:
            try:
                if self.midiout and self.midiout.is_port_open():
                    if self.send_start:
                        self.midiout.send_message([STOP_BYTE])
                    self.midiout.close_port()
            except Exception:
                pass
            self.finished.emit(self.port_num)


class MidiSyncWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)
    ipc_socket_path = pyqtSignal(str)

    def __init__(self, video_file, bpm, display_num, preload_time, midi_offset_ms,
                 send_start_port1, send_start_port2, send_start_port3, timing_method,
                 require_midi=True, max_duration_sec=0, zoom_config=None,
                 absolute_start_time=None, audio_only_mode=False):
        super().__init__()
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
        self.max_duration_sec = max_duration_sec
        self.zoom_config = zoom_config or {}
        self.absolute_start_time = absolute_start_time
        self.audio_only_mode = audio_only_mode
        self.mpv_process = None
        self._is_running = True
        self.midi_outputs = {}
        self._mpv_exit_logged = False
        self._mpv_stderr_cache = None

    def stop(self):
        self._is_running = False

    def run(self):
        if not os.path.exists(self.video_file):
            self.error.emit(f"File not found: '{self.video_file}'")
            return
        if rtmidi is not None:
            for port_num in (1, 2, 3):
                try:
                    midiout = rtmidi.MidiOut()
                    midiout.open_port(port_num)
                    self.midi_outputs[port_num] = midiout
                except Exception:
                    pass
        if not self.midi_outputs and self.require_midi:
            self.error.emit("No MIDI ports available.")
            return

        if self.timing_method == 'high_precision':
            self.run_high_precision()
        else:
            self.run_standard()

    def run_standard(self):
        self._run_logic(is_high_precision=False)

    def run_high_precision(self):
        # macOS divergence: no Windows multimedia timer API; high-precision mode is busy-wait only.
        self._run_logic(is_high_precision=True)

    def _log_debug(self, message):
        _debug_log_runtime(message)

    def _read_mpv_stderr(self):
        if self._mpv_stderr_cache is not None:
            return self._mpv_stderr_cache
        stderr_text = ""
        if self.mpv_process and self.mpv_process.stderr and self.mpv_process.poll() is not None:
            try:
                _stdout_text, stderr_text = self.mpv_process.communicate(timeout=0.2)
                stderr_text = stderr_text or ""
            except Exception as exc:
                try:
                    stderr_text = self.mpv_process.stderr.read() or ""
                except Exception:
                    stderr_text = f"<stderr read failed: {exc}>"
        self._mpv_stderr_cache = stderr_text
        return stderr_text

    def _log_mpv_exit(self, context="playback"):
        if not self.mpv_process or self.mpv_process.poll() is None or self._mpv_exit_logged:
            return
        rc = self.mpv_process.returncode
        stderr_text = _truncate_for_log(self._read_mpv_stderr())
        msg = f"mpv exited ({context}) with return code {rc}"
        if stderr_text:
            msg += f"; stderr={stderr_text}"
        self._log_debug(msg)
        self._mpv_exit_logged = True

    def _launch_mpv_and_wait_for_socket(self, mpv_cmd, socket_path):
        track_exists = os.path.exists(self.video_file)
        self._log_debug(
            f"Resolved track path: {self.video_file} (exists={track_exists})"
        )
        self._log_debug(
            f"mpv IPC socket path: {socket_path} ({len(socket_path.encode('utf-8'))} bytes)"
        )
        self._log_debug(f"mpv command: {_format_command_for_log(mpv_cmd)}")
        self.status_update.emit(f"Starting mpv on screen {self.display_num}...")
        self.mpv_process = subprocess.Popen(
            mpv_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._mpv_exit_logged = False
        self._mpv_stderr_cache = None
        self.ipc_socket_path.emit(socket_path)
        socket_deadline = time.perf_counter() + 5.0
        while (not os.path.exists(socket_path)
               and time.perf_counter() < socket_deadline
               and self._is_running):
            if self.mpv_process.poll() is not None:
                stderr_text = _truncate_for_log(self._read_mpv_stderr())
                self._log_mpv_exit("startup")
                raise RuntimeError(
                    "mpv exited before creating its IPC socket "
                    f"(returncode={self.mpv_process.returncode}, "
                    f"socket={socket_path}, socket_bytes={len(socket_path.encode('utf-8'))}, "
                    f"command={_format_command_for_log(mpv_cmd)}, "
                    f"stderr={stderr_text or '<empty>'})"
                )
            time.sleep(0.02)
        if not self._is_running:
            raise InterruptedError("Playback stopped by user while waiting for mpv IPC socket")
        if not os.path.exists(socket_path):
            raise RuntimeError(
                f"mpv IPC socket did not appear: {socket_path} "
                f"({len(socket_path.encode('utf-8'))} bytes)"
            )

    def _run_logic(self, is_high_precision):
        mpv_bin = MPV_PATH if (os.path.isabs(MPV_PATH) and os.path.exists(MPV_PATH)) else _find_executable('mpv')
        socket_path = _make_unique_mpv_pipe_name("mpv_socket")
        file_ext = os.path.splitext(self.video_file)[1].lower()
        is_audio_only = file_ext == '.wav' or self.audio_only_mode
        mpv_cmd = [
            mpv_bin,
            f"--input-ipc-server={socket_path}",
            "--pause",
            "--msg-level=all=warn",
            "--keep-open=no",
        ]
        if self.max_duration_sec > 0:
            mpv_cmd.append(f"--length={self.max_duration_sec}")
        if is_audio_only:
            mpv_cmd.append("--no-video")
        else:
            mpv_cmd += [
                "--fullscreen",
                f"--fs-screen={self.display_num}",
                "--no-osd-bar",
                "--no-osc",
                "--no-input-default-bindings",
                "--no-border",
                "--video-sync=audio",
            ]
            vf_str = _build_vf_for_zones(self.zoom_config)
            if vf_str:
                mpv_cmd.append(f"--vf={vf_str}")
        mpv_cmd.append(self.video_file)

        started_ports = []
        try:
            if self.absolute_start_time is not None:
                wait_until = self.absolute_start_time - self.preload_time
                while self._is_running and time.time() < wait_until:
                    time.sleep(0.01)

            tick_interval = 60.0 / max(1, self.bpm) / 24.0
            pre_roll_end_time = time.perf_counter() + self.preload_time
            mpv_launch_time = max(time.perf_counter(), pre_roll_end_time - MPV_LAUNCH_HEAD_START_SECONDS)
            next_tick = time.perf_counter()
            launched = False
            while self._is_running and time.perf_counter() < pre_roll_end_time:
                now = time.perf_counter()
                if not launched and now >= mpv_launch_time:
                    self._launch_mpv_and_wait_for_socket(mpv_cmd, socket_path)
                    launched = True
                if now >= next_tick:
                    for midiout in self.midi_outputs.values():
                        midiout.send_message([CLOCK_BYTE])
                    next_tick += tick_interval
                if is_high_precision:
                    pass
                else:
                    time.sleep(0.001)

            if not self._is_running:
                raise InterruptedError("Playback stopped by user during preload")
            if self.mpv_process is None:
                self._launch_mpv_and_wait_for_socket(mpv_cmd, socket_path)

            # Positive offset = video/audio starts AFTER MIDI (compensates a MIDI rig
            # that runs early). Negative offset = video/audio starts BEFORE MIDI, which
            # is what compensates for sound-card output latency.
            offset_sec = self.midi_offset_ms / 1000.0
            now = time.perf_counter()
            lead = max(0.0, -offset_sec)          # never schedule an event in the past
            midi_start_time = now + lead
            video_unpause_time = midi_start_time + offset_sec

            midi_started = False
            video_unpaused = False
            # NOTE: next_tick carries over from the pre-roll loop — do NOT reset it,
            # otherwise the clock phase jumps and the offset is cancelled out.
            while self._is_running and not (midi_started and video_unpaused):
                now = time.perf_counter()

                if not video_unpaused and now >= video_unpause_time:
                    if not _send_ipc_command(
                            socket_path, '{ "command": ["set_property", "pause", false] }'):
                        raise RuntimeError(f"Failed to unpause mpv via IPC socket {socket_path}")
                    video_unpaused = True

                if not midi_started and now >= midi_start_time:
                    for port_num, midiout in self.midi_outputs.items():
                        send_start = {
                            1: self.send_start_port1,
                            2: self.send_start_port2,
                            3: self.send_start_port3,
                        }.get(port_num, False)
                        if send_start:
                            midiout.send_message([SPP_BYTE, 0, 0])
                            midiout.send_message([START_BYTE])
                            started_ports.append(port_num)
                    midi_started = True

                if now >= next_tick:
                    for midiout in self.midi_outputs.values():
                        midiout.send_message([CLOCK_BYTE])
                    next_tick += tick_interval

                if not is_high_precision:
                    time.sleep(0.0005)

            if not self._is_running:
                raise InterruptedError("Playback stopped by user during offset window")

            self._log_debug(
                f"MIDI offset applied: {self.midi_offset_ms} ms "
                f"(midi_start in +{lead:.4f}s, "
                f"video_unpause in +{lead + offset_sec:.4f}s)")
            self.status_update.emit(f"PLAYING: {os.path.basename(self.video_file)}")

            while self._is_running and self.mpv_process.poll() is None:
                now = time.perf_counter()
                if now >= next_tick:
                    for midiout in self.midi_outputs.values():
                        midiout.send_message([CLOCK_BYTE])
                    next_tick += tick_interval
                if is_high_precision:
                    pass
                else:
                    time.sleep(0.001)
            self._log_mpv_exit("playback")
        except InterruptedError:
            pass
        except Exception as e:
            self._log_debug(f"Playback exception: {traceback.format_exc()}")
            self.error.emit(f"Playback error: {e}")
        finally:
            self.cleanup(socket_path, started_ports)

    def cleanup(self, socket_path=None, started_ports=None):
        started_ports = started_ports or []
        if self.mpv_process and self.mpv_process.poll() is None:
            self.mpv_process.terminate()
            try:
                self.mpv_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.mpv_process.kill()
                try:
                    self.mpv_process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        self._log_mpv_exit("cleanup")
        if socket_path and os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except OSError:
                pass
        for port_num, midiout in self.midi_outputs.items():
            try:
                if port_num in started_ports:
                    midiout.send_message([STOP_BYTE])
                if midiout.is_port_open():
                    midiout.close_port()
            except Exception:
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
            if path and os.path.exists(path):
                pos = _query_ipc_property(path, "time-pos")
                dur = _query_ipc_property(path, "duration")
                if pos is not None and dur is not None:
                    try:
                        self.position_updated.emit(float(pos), float(dur))
                    except Exception:
                        pass
            time.sleep(self._POLL_INTERVAL)


class ZoomCropCanvas(QWidget):
    """A canvas widget for visually defining a crop region on a captured video frame.
    
    The user can drag to create a new selection, move the selection,
    or resize it by dragging the corner/edge handles. Pixel coordinates
    are reported live via the region_changed signal.
    """
    region_changed = pyqtSignal(int, int, int, int)  # x, y, w, h in source pixels
    handle_dragged = pyqtSignal(str, int, int)        # drag_mode, abs_x, abs_y
    drag_started   = pyqtSignal()                     # emitted once on left-button press (drag begins)
    drag_finished  = pyqtSignal()                     # emitted once on mouse-button release after a drag

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
        painter.fillRect(self.rect(), QColor("#1c1c1e"))
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
        if self._drag_mode is not None:
            self.drag_started.emit()

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
            was_dragging = self._drag_mode is not None
            self._drag_start = None
            self._drag_mode = None
            self._drag_handle_pos = None
            self.handle_dragged.emit("", 0, 0)
            if was_dragging:
                self.drag_finished.emit()
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_transform()
        self.update()


class StretchCanvas(QWidget):
    """Canvas that displays a cropped region and lets the user resize output dimensions.

    In stretch/scale edit mode the user sees the cropped sub-image drawn at the
    *current output size* (potentially distorted) and can drag the right/bottom/
    corner handles to change the scale_w × scale_h values.
    """

    output_changed = pyqtSignal(int, int)  # scale_w, scale_h
    drag_started   = pyqtSignal()          # emitted once on left-button press when a handle is hit
    drag_finished  = pyqtSignal()          # emitted once on mouse-button release after a drag
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

    def get_source_size(self):
        """Return (crop_w, crop_h) — the natural source dimensions of the displayed image."""
        return self._crop_w, self._crop_h

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
        painter.fillRect(self.rect(), QColor("#1c1c1e"))
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
            self.drag_started.emit()

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
        suffix = self._drag_mode[len('resize_'):]
        if 'r' in suffix:
            ow = max(1, int(ow + dx))
        if 'b' in suffix:
            oh = max(1, int(oh + dy))
        self._out_w = ow
        self._out_h = oh
        self.update()
        self.output_changed.emit(self._out_w, self._out_h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._drag_mode is not None
            self._drag_mode = None
            self._drag_start = None
            if was_dragging:
                self.drag_finished.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()


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

    # Tab indices — zone tabs occupy 0 … NUM_ZONES-1
    _COMP_TAB_INDEX  = NUM_ZONES      # "Composite Output"
    _FINAL_TAB_INDEX = NUM_ZONES + 1  # "Final Preview"

    def __init__(self, current_config, output_display_num=DEFAULT_VIDEO_SCREEN_NUMBER, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Multi-Zone Crop / Stretch Compositor")
        self.setModal(True)
        self.resize(1280, 820)

        self._cfg = _migrate_zoom_config(current_config)
        self.result_config = None
        self._output_display_num = max(1, int(output_display_num))

        # mpv / capture state (shared across all zone canvases)
        self._mpv_process = None
        self._ipc_path = None
        self._selected_video_path = None
        self._temp_dir = os.path.join(os.getcwd(), f".lc_mzoom_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self._temp_dir, exist_ok=True)
        self._frame_path = os.path.join(self._temp_dir, "frame.png")
        self._full_pixmap = None      # Most-recently captured video frame

        # Dedicated mpv process for fullscreen external preview on final-output display
        self._ext_preview_process = None
        self._ext_preview_ipc_path = None
        self._ext_preview_open = False
        self._ext_preview_paused = True
        self._ext_preview_source_path = None
        self._ext_preview_start_pos = 0.0
        self._ext_preview_wall_start = None
        self._ext_preview_vf = None

        self._updating = False        # Guard for circular signal updates

        # Scrub-slider tracking state (capture-preview transport)
        self._mz_pos = 0.0            # Most-recently known playback position (seconds)
        self._mz_dur = 0.0            # Most-recently known video duration (seconds)
        self._mz_slider_dragging = False  # True while the user has the handle pressed

        # Background position poller for the capture-preview mpv instance
        self._pos_poller = PositionPoller()
        self._pos_poller.position_updated.connect(self._on_mz_position_updated)

        # Debounce timer for real-time composite/preview updates
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(120)  # ms — short delay to smooth drag interactions
        self._update_timer.timeout.connect(self._do_composite_update)

        self._setup_ui()
        self._load_config_to_ui()
        # Start the position poller after all UI widgets are constructed so the
        # slot cannot reference attributes that do not yet exist.
        self._pos_poller.start()

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

        # ---- Transport / scrub controls row ----
        transport_bar = QHBoxLayout()

        # Play-from-beginning button
        self._beg_btn = QPushButton("⏮  Beginning")
        self._beg_btn.setToolTip("Seek to position 0 and start playback.")
        self._beg_btn.clicked.connect(self._play_from_beginning)
        self._beg_btn.setEnabled(False)

        # Frame-step buttons
        self._frame_back_btn = QPushButton("◀  Frame Back")
        self._frame_back_btn.setToolTip("Step exactly one frame backward (works while paused).")
        self._frame_back_btn.clicked.connect(self._frame_back)
        self._frame_back_btn.setEnabled(False)

        self._frame_fwd_btn = QPushButton("Frame Forward  ▶")
        self._frame_fwd_btn.setToolTip("Step exactly one frame forward (works while paused).")
        self._frame_fwd_btn.clicked.connect(self._frame_forward)
        self._frame_fwd_btn.setEnabled(False)

        # Scrub slider with MM:SS labels either side
        self._mz_pos_label = QLabel("00:00")
        self._mz_pos_label.setMinimumWidth(42)
        self._mz_pos_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._mz_scrub_slider = QSlider(Qt.Orientation.Horizontal)
        self._mz_scrub_slider.setRange(0, 1000)
        self._mz_scrub_slider.setValue(0)
        self._mz_scrub_slider.setEnabled(False)
        self._mz_scrub_slider.setToolTip("Drag to jump to any position in the video.")
        self._mz_scrub_slider.sliderMoved.connect(self._on_mz_scrub_moved)
        self._mz_scrub_slider.sliderReleased.connect(self._on_mz_scrub_released)

        self._mz_dur_label = QLabel("00:00")
        self._mz_dur_label.setMinimumWidth(42)
        self._mz_dur_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        transport_bar.addWidget(self._beg_btn)
        transport_bar.addWidget(self._frame_back_btn)
        transport_bar.addWidget(self._frame_fwd_btn)
        transport_bar.addSpacing(8)
        transport_bar.addWidget(self._mz_pos_label)
        transport_bar.addWidget(self._mz_scrub_slider, 1)
        transport_bar.addWidget(self._mz_dur_label)
        root.addLayout(transport_bar)

        ext_bar = QHBoxLayout()
        ext_bar.addWidget(QLabel("External preview:"))
        self._ext_source_combo = QComboBox()
        self._ext_source_combo.addItems(["Frame (captured/restored)", "Video (selected source)"])
        self._ext_source_combo.setToolTip(
            "Choose what to preview on the final-output display selected in the main window.\n"
            "Frame mode loops the captured/restored snapshot. Video mode plays the selected source video.\n"
            "This preview is separate from actual live playback.")
        self._ext_source_combo.currentIndexChanged.connect(self._on_external_source_mode_changed)
        self._ext_toggle_btn = QPushButton("Open External Preview")
        self._ext_toggle_btn.setToolTip(
            "Open/close a dedicated fullscreen mpv preview on the selected final-output display.\n"
            "Uses the same composite filter chain as live playback and does not start automatically.")
        self._ext_toggle_btn.clicked.connect(self._toggle_external_preview)
        self._ext_live_refresh_btn = QPushButton("Live Refresh")
        self._ext_live_refresh_btn.setToolTip(
            "Apply current zone/composite settings to the external preview.\n"
            "Click to reload the preview once.")
        self._ext_live_refresh_btn.clicked.connect(self._on_live_refresh_clicked)
        self._ext_preview_label = QLabel(f"Target display: {self._output_display_num}")
        self._ext_preview_label.setStyleSheet("color: #888; font-style: italic;")
        ext_bar.addWidget(self._ext_source_combo)
        ext_bar.addWidget(self._ext_toggle_btn)
        ext_bar.addWidget(self._ext_live_refresh_btn)
        ext_bar.addWidget(self._ext_preview_label)
        ext_bar.addStretch()
        root.addLayout(ext_bar)
        self._update_external_source_availability()

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
        self._zone_offset_y_sbs = []

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

            pos_grp = QGroupBox("Final Display Position")
            pos_grp.setStyleSheet(f"QGroupBox::title {{ color: {color}; }}")
            pos_grp.setToolTip(
                "Move this zone's rendered output within the final stitched display.\n"
                "This does NOT change the source crop rectangle.")
            pg = QGridLayout(); pg.setSpacing(4)
            offset_y_sb = QSpinBox()
            offset_y_sb.setRange(-5000, 5000)
            offset_y_sb.setSuffix(" px")
            offset_y_sb.setFixedWidth(110)
            offset_y_sb.setToolTip(
                "Vertical offset in the final output (+ down, - up).\n"
                "Does not affect source crop coordinates.")
            pg.addWidget(QLabel("Y offset:"), 0, 0); pg.addWidget(offset_y_sb, 0, 1)
            pos_grp.setLayout(pg)

            right.addWidget(crop_grp)
            right.addWidget(scale_grp)
            right.addWidget(border_grp)
            right.addWidget(pos_grp)
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
            self._zone_offset_y_sbs.append(offset_y_sb)

        # ---- Composite Output tab ----
        # This tab lets the operator crop and/or stretch the already-stitched zone
        # composite as a whole (after per-zone transforms are applied).
        comp_tab = QWidget()
        comp_layout = QVBoxLayout(comp_tab)
        comp_layout.setSpacing(6)
        comp_layout.setContentsMargins(4, 4, 4, 4)

        comp_top_bar = QHBoxLayout()
        comp_top_bar.addWidget(QLabel(
            "<b>Composite Output</b> — crop and/or stretch the full stitched composite "
            "after all per-zone transforms have been applied."))
        self._comp_refresh_btn = QPushButton("🔄  Rebuild Composite")
        self._comp_refresh_btn.setToolTip(
            "Manually stitch the current zone settings into the composite canvas.\n"
            "The composite is also rebuilt automatically when this tab is opened\n"
            "or when any zone/composite control changes (with a short debounce).")
        self._comp_refresh_btn.clicked.connect(self._rebuild_composite_canvas)
        comp_top_bar.addStretch()
        comp_top_bar.addWidget(self._comp_refresh_btn)
        comp_layout.addLayout(comp_top_bar)

        # Mode toggle: Crop or Stretch
        comp_mode_bar = QHBoxLayout()
        self._comp_mode_crop_rb    = QRadioButton("✂  Edit Crop")
        self._comp_mode_stretch_rb = QRadioButton("⤢  Edit Stretch / Output Size")
        self._comp_mode_crop_rb.setChecked(True)
        self._comp_mode_crop_rb.setToolTip(
            "Show the crop-handle canvas to define which region of the stitched\n"
            "composite is kept.  This affects the ENTIRE stitched composite,\n"
            "not an individual zone.")
        self._comp_mode_stretch_rb.setToolTip(
            "Show the stretch-handle canvas to set the final output dimensions of\n"
            "the stitched composite after cropping.  Drag the handles to resize\n"
            "width and/or height independently (non-uniform stretch).\n"
            "This scales the ENTIRE stitched composite, not an individual zone.")
        comp_mode_bar.addWidget(self._comp_mode_crop_rb)
        comp_mode_bar.addWidget(self._comp_mode_stretch_rb)
        comp_mode_bar.addStretch()
        comp_layout.addLayout(comp_mode_bar)

        comp_body = QHBoxLayout()
        comp_body.setSpacing(8)

        # Stacked canvas — index 0: crop handles, index 1: stretch handles
        self._comp_stacked = QStackedWidget()

        self._comp_crop_canvas = ZoomCropCanvas(color="#e040fb")
        self._comp_crop_canvas.setToolTip(
            "Drag the handles to define the crop rectangle for the ENTIRE stitched composite.\n"
            "This crop is applied AFTER all per-zone transforms and BEFORE the composite stretch.\n"
            "Set Width to 0 in the numeric controls to disable cropping (pass-through).")
        self._comp_crop_canvas.region_changed.connect(self._on_comp_crop_changed)

        self._comp_stretch_canvas = StretchCanvas(color="#e040fb")
        self._comp_stretch_canvas.setToolTip(
            "Drag the right/bottom/corner handles to set the final output dimensions\n"
            "of the ENTIRE stitched composite (after the composite crop step).\n"
            "Width and height can be set independently for non-uniform stretching.\n"
            "Set both Scale W and Scale H to -1 (auto) to skip this step.")
        self._comp_stretch_canvas.output_changed.connect(self._on_comp_stretch_changed)

        self._comp_stacked.addWidget(self._comp_crop_canvas)    # index 0
        self._comp_stacked.addWidget(self._comp_stretch_canvas) # index 1
        comp_body.addWidget(self._comp_stacked, 3)

        self._comp_mode_stretch_rb.toggled.connect(
            lambda checked: self._comp_stacked.setCurrentIndex(1 if checked else 0))

        comp_right = QVBoxLayout()
        comp_right.setSpacing(4)

        comp_crop_grp = QGroupBox("Whole-Composite Crop  (entire stitched composite)")
        comp_crop_grp.setStyleSheet("QGroupBox::title { color: #e040fb; }")
        comp_crop_grp.setToolTip(
            "Crop the stitched composite image. Set Width to 0 to disable (pass-through).\n"
            "Applies to the ENTIRE composite, not an individual zone.")
        ccg = QGridLayout(); ccg.setSpacing(4)
        self._comp_x_sb  = QSpinBox(); self._comp_x_sb.setRange(0, 99999);  self._comp_x_sb.setSuffix(" px"); self._comp_x_sb.setFixedWidth(110)
        self._comp_y_sb  = QSpinBox(); self._comp_y_sb.setRange(0, 99999);  self._comp_y_sb.setSuffix(" px"); self._comp_y_sb.setFixedWidth(110)
        self._comp_w_sb  = QSpinBox(); self._comp_w_sb.setRange(0, 99999);  self._comp_w_sb.setSuffix(" px"); self._comp_w_sb.setFixedWidth(110)
        self._comp_w_sb.setSpecialValueText("Full (no crop)")
        self._comp_h_sb  = QSpinBox(); self._comp_h_sb.setRange(0, 99999);  self._comp_h_sb.setSuffix(" px"); self._comp_h_sb.setFixedWidth(110)
        self._comp_h_sb.setSpecialValueText("Full (no crop)")
        ccg.addWidget(QLabel("X:"),      0, 0); ccg.addWidget(self._comp_x_sb, 0, 1)
        ccg.addWidget(QLabel("Y:"),      1, 0); ccg.addWidget(self._comp_y_sb, 1, 1)
        ccg.addWidget(QLabel("Width:"),  2, 0); ccg.addWidget(self._comp_w_sb, 2, 1)
        ccg.addWidget(QLabel("Height:"), 3, 0); ccg.addWidget(self._comp_h_sb, 3, 1)
        comp_crop_grp.setLayout(ccg)

        comp_scale_grp = QGroupBox("Whole-Composite Stretch / Output Size  (entire stitched composite)")
        comp_scale_grp.setStyleSheet("QGroupBox::title { color: #e040fb; }")
        comp_scale_grp.setToolTip(
            "Stretch the ENTIRE stitched composite to exact output dimensions after cropping.\n"
            "Width and height are set independently — non-uniform stretching is supported.\n"
            "Set both to -1 (auto) to skip this step and pass the cropped composite unchanged.\n"
            "Equivalent to mpv's scale= filter applied to the full composite image,\n"
            "and to the draggable handles in the 'Edit Stretch' canvas view above.")
        csg = QGridLayout(); csg.setSpacing(4)
        self._comp_sw_sb = QSpinBox(); self._comp_sw_sb.setRange(-1, 99999); self._comp_sw_sb.setSuffix(" px"); self._comp_sw_sb.setSpecialValueText("auto"); self._comp_sw_sb.setFixedWidth(110)
        self._comp_sh_sb = QSpinBox(); self._comp_sh_sb.setRange(-1, 99999); self._comp_sh_sb.setSuffix(" px"); self._comp_sh_sb.setSpecialValueText("auto"); self._comp_sh_sb.setFixedWidth(110)
        self._comp_sw_sb.setToolTip(
            "Output width of the ENTIRE composite after stretch.\n"
            "Set to -1 (auto) together with Scale H to skip this step.")
        self._comp_sh_sb.setToolTip(
            "Output height of the ENTIRE composite after stretch.\n"
            "Set to -1 (auto) together with Scale W to skip this step.")
        csg.addWidget(QLabel("Stretch W:"), 0, 0); csg.addWidget(self._comp_sw_sb, 0, 1)
        csg.addWidget(QLabel("Stretch H:"), 1, 0); csg.addWidget(self._comp_sh_sb, 1, 1)
        comp_scale_grp.setLayout(csg)

        self._comp_reset_btn = QPushButton("↺  Reset to Full Composite")
        self._comp_reset_btn.setToolTip(
            "Remove the composite crop (pass-through) and clear stretch overrides\n"
            "for the ENTIRE stitched composite.")
        self._comp_reset_btn.clicked.connect(self._reset_composite_crop)

        comp_right.addWidget(comp_crop_grp)
        comp_right.addWidget(comp_scale_grp)
        comp_right.addWidget(self._comp_reset_btn)
        comp_right.addStretch()
        comp_body.addLayout(comp_right, 1)
        comp_layout.addLayout(comp_body, 1)

        self._tabs.addTab(comp_tab, "Composite Output")

        # Wire composite spinbox signals
        for sb in (self._comp_x_sb, self._comp_y_sb,
                   self._comp_w_sb, self._comp_h_sb):
            sb.valueChanged.connect(self._on_comp_spinbox_changed)
        for sb in (self._comp_sw_sb, self._comp_sh_sb):
            sb.valueChanged.connect(self._on_comp_scale_spinbox_changed)

        # ---- Final Preview tab ----
        final_tab = QWidget()
        final_layout = QVBoxLayout(final_tab)
        final_layout.setSpacing(6)

        # Output resolution controls
        out_res_bar = QHBoxLayout()
        out_res_bar.addWidget(QLabel("Simulated output resolution:"))
        self._out_w_sb = QSpinBox()
        self._out_w_sb.setRange(160, 32768)
        self._out_w_sb.setValue(1920)
        self._out_w_sb.setSuffix(" px")
        self._out_w_sb.setFixedWidth(100)
        self._out_w_sb.setToolTip("Simulated display canvas width in pixels.")
        self._out_h_sb = QSpinBox()
        self._out_h_sb.setRange(120, 32768)
        self._out_h_sb.setValue(1080)
        self._out_h_sb.setSuffix(" px")
        self._out_h_sb.setFixedWidth(100)
        self._out_h_sb.setToolTip("Simulated display canvas height in pixels.")
        out_res_bar.addWidget(self._out_w_sb)
        out_res_bar.addWidget(QLabel("×"))
        out_res_bar.addWidget(self._out_h_sb)
        out_res_bar.addSpacing(12)
        self._out_sim_playback_cb = QCheckBox("Apply output canvas to mpv playback")
        self._out_sim_playback_cb.setToolTip(
            "When checked, mpv will pad the final composite into the configured output\n"
            "canvas during actual playback — matching the preview letterboxing/pillarboxing.\n"
            "Leave unchecked to keep existing playback behaviour (no padding added).")
        out_res_bar.addWidget(self._out_sim_playback_cb)
        out_res_bar.addStretch()
        final_layout.addLayout(out_res_bar)

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

        # ---- Real-time update signal wiring ----
        # Connect all controls that affect the composite to _schedule_composite_update
        # so the composite canvas and final preview refresh in real time (with debounce).
        for cb in self._zone_enable_cbs:
            cb.stateChanged.connect(self._schedule_composite_update)
        for rb in self._zone_mode_crop_rbs + self._zone_mode_stretch_rbs:
            rb.toggled.connect(lambda _: self._schedule_composite_update())
        for sbs in (self._zone_x_sbs, self._zone_y_sbs, self._zone_w_sbs, self._zone_h_sbs,
                    self._zone_sw_sbs, self._zone_sh_sbs, self._zone_border_sbs,
                    self._zone_offset_y_sbs):
            for sb in sbs:
                sb.valueChanged.connect(self._schedule_composite_update)
        self._stitch_h.toggled.connect(lambda _: self._schedule_composite_update())
        self._stitch_v.toggled.connect(lambda _: self._schedule_composite_update())
        for sb in (self._comp_x_sb, self._comp_y_sb, self._comp_w_sb, self._comp_h_sb,
                   self._comp_sw_sb, self._comp_sh_sb, self._out_w_sb, self._out_h_sb):
            sb.valueChanged.connect(self._schedule_composite_update)
        self._out_sim_playback_cb.stateChanged.connect(self._schedule_composite_update)

        # Auto-rebuild when switching to Composite Output or Final Preview tabs
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # ---- Status bar + OK / Cancel ----
        self._status = QLabel(
            "Select a video/capture frame to edit. External preview is optional and opens on the selected final-output display.")
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
            offset_y = int(zone.get("offset_y", 0))
            mode   = zone.get("mode", "crop")
            self._zone_x_sbs[i].setValue(x)
            self._zone_y_sbs[i].setValue(y)
            self._zone_w_sbs[i].setValue(w)
            self._zone_h_sbs[i].setValue(h)
            self._zone_sw_sbs[i].setValue(sw)
            self._zone_sh_sbs[i].setValue(sh)
            self._zone_border_sbs[i].setValue(border)
            self._zone_offset_y_sbs[i].setValue(offset_y)
            if mode == "stretch":
                self._zone_mode_stretch_rbs[i].setChecked(True)
            else:
                self._zone_mode_crop_rbs[i].setChecked(True)

        # Load composite output fields
        out_w  = self._cfg.get("out_w",  -1)
        out_h  = self._cfg.get("out_h",  -1)
        self._out_w_sb.setValue(out_w if out_w > 0 else 1920)
        self._out_h_sb.setValue(out_h if out_h > 0 else 1080)
        self._out_sim_playback_cb.setChecked(bool(self._cfg.get("out_sim_enabled", False)))
        self._comp_x_sb.setValue(int(self._cfg.get("comp_crop_x", 0)))
        self._comp_y_sb.setValue(int(self._cfg.get("comp_crop_y", 0)))
        self._comp_w_sb.setValue(int(self._cfg.get("comp_crop_w", 0)))
        self._comp_h_sb.setValue(int(self._cfg.get("comp_crop_h", 0)))
        self._comp_sw_sb.setValue(int(self._cfg.get("comp_scale_w", -1)))
        self._comp_sh_sb.setValue(int(self._cfg.get("comp_scale_h", -1)))

        self._updating = False
        self._push_restored_values_to_canvases()

        # Attempt to reload the persistent frame snapshot
        saved_path = _normalize_snapshot_path(self._cfg.get("frame_snapshot_path", ""))
        self._cfg["frame_snapshot_path"] = saved_path
        if saved_path and os.path.isfile(saved_path):
            self._load_frame_from_path(saved_path)
            self._status.setText(
                f"Restored saved frame snapshot from '{os.path.basename(saved_path)}'.")

    def _push_restored_values_to_canvases(self):
        prev_updating = self._updating
        self._updating = True
        for i in range(NUM_ZONES):
            x = self._zone_x_sbs[i].value()
            y = self._zone_y_sbs[i].value()
            w = self._zone_w_sbs[i].value()
            h = self._zone_h_sbs[i].value()
            sw = self._zone_sw_sbs[i].value()
            sh = self._zone_sh_sbs[i].value()
            self._zone_crop_canvases[i].set_region(x, y, w, h)
            self._zone_stretch_canvases[i].set_output(sw if sw > 0 else w, sh if sh > 0 else h)
            self._zone_stacked[i].setCurrentIndex(1 if self._zone_mode_stretch_rbs[i].isChecked() else 0)
            self._sync_stretch_canvas(i)

        cw = self._comp_w_sb.value()
        ch = self._comp_h_sb.value()
        if cw > 0 and ch > 0:
            self._comp_crop_canvas.set_region(
                self._comp_x_sb.value(),
                self._comp_y_sb.value(),
                cw,
                ch,
            )
        else:
            src_w = self._comp_crop_canvas.source_w
            src_h = self._comp_crop_canvas.source_h
            if src_w > 0 and src_h > 0:
                self._comp_crop_canvas.set_region(0, 0, src_w, src_h)

        comp_sw = self._comp_sw_sb.value()
        comp_sh = self._comp_sh_sb.value()
        src_w, src_h = self._comp_stretch_canvas.get_source_size()
        self._comp_stretch_canvas.set_output(
            comp_sw if comp_sw > 0 else max(1, src_w),
            comp_sh if comp_sh > 0 else max(1, src_h),
        )
        self._comp_stacked.setCurrentIndex(1 if self._comp_mode_stretch_rb.isChecked() else 0)
        self._updating = prev_updating

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
                "offset_y":  self._zone_offset_y_sbs[i].value(),
                "mode":      mode,
            })
        snapshot_path = _normalize_snapshot_path(self._cfg.get("frame_snapshot_path", ""))
        self._cfg["frame_snapshot_path"] = snapshot_path
        out_sim = self._out_sim_playback_cb.isChecked()
        return {
            "zones": zones,
            "stack_direction": direction,
            "frame_snapshot_path": snapshot_path,
            # Composite output / output simulation fields
            "out_w":          self._out_w_sb.value(),
            "out_h":          self._out_h_sb.value(),
            "out_sim_enabled": out_sim,
            "comp_crop_x":    self._comp_x_sb.value(),
            "comp_crop_y":    self._comp_y_sb.value(),
            "comp_crop_w":    self._comp_w_sb.value(),
            "comp_crop_h":    self._comp_h_sb.value(),
            "comp_scale_w":   self._comp_sw_sb.value(),
            "comp_scale_h":   self._comp_sh_sb.value(),
        }

    def collect_config(self):
        return _migrate_zoom_config(self.result_config if self.result_config is not None else self._collect_config())


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
        self._schedule_composite_update()

    def _on_stretch_changed(self, zi, sw, sh):
        """Stretch canvas handles moved → update scale spinboxes."""
        if self._updating:
            return
        self._updating = True
        self._zone_sw_sbs[zi].setValue(sw)
        self._zone_sh_sbs[zi].setValue(sh)
        self._updating = False
        self._schedule_composite_update()

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
    # Composite Output canvas handlers
    # ------------------------------------------------------------------

    def _on_comp_crop_changed(self, x, y, w, h):
        """Composite canvas crop changed → update composite spinboxes."""
        if self._updating:
            return
        self._updating = True
        self._comp_x_sb.setValue(x)
        self._comp_y_sb.setValue(y)
        self._comp_w_sb.setValue(max(1, w))
        self._comp_h_sb.setValue(max(1, h))
        self._updating = False
        self._schedule_composite_update()

    def _on_comp_spinbox_changed(self):
        """Composite crop spinboxes changed → update canvas selection."""
        if self._updating:
            return
        cw = self._comp_w_sb.value()
        ch = self._comp_h_sb.value()
        if cw > 0 and ch > 0:
            self._comp_crop_canvas.set_region(
                self._comp_x_sb.value(),
                self._comp_y_sb.value(),
                cw, ch,
            )
        self._schedule_composite_update()

    def _on_comp_scale_spinbox_changed(self):
        """Composite stretch spinboxes changed → update the stretch canvas output dimensions."""
        if self._updating:
            return
        sw = self._comp_sw_sb.value()
        sh = self._comp_sh_sb.value()
        # Use composite source dimensions as fallback when value is -1
        src_w, src_h = self._comp_stretch_canvas.get_source_size()
        self._comp_stretch_canvas.set_output(
            sw if sw > 0 else src_w,
            sh if sh > 0 else src_h,
        )
        self._schedule_composite_update()

    def _on_comp_stretch_changed(self, sw, sh):
        """Stretch canvas handles moved → update composite scale spinboxes."""
        if self._updating:
            return
        self._updating = True
        self._comp_sw_sb.setValue(sw)
        self._comp_sh_sb.setValue(sh)
        self._updating = False
        self._schedule_composite_update()

    # ------------------------------------------------------------------
    # Real-time composite update scheduling
    # ------------------------------------------------------------------

    def _schedule_composite_update(self, *_args):
        """Schedule a debounced composite update (handles spurious signal args)."""
        if self._updating:
            return
        self._update_timer.start()

    def _do_composite_update(self):
        """Debounced handler: rebuild composite canvases and refresh the final preview."""
        current = self._tabs.currentIndex()
        if current == self._COMP_TAB_INDEX:
            self._rebuild_composite_canvas()
        elif current == self._FINAL_TAB_INDEX:
            self._refresh_final_preview()

    def _on_tab_changed(self, index):
        """Auto-rebuild when the user switches to Composite Output or Final Preview."""
        if index == self._COMP_TAB_INDEX:
            self._rebuild_composite_canvas()
        elif index == self._FINAL_TAB_INDEX:
            self._refresh_final_preview()

    def _reset_composite_crop(self):
        """Reset composite crop to full composite (pass-through) and clear scale."""
        self._comp_x_sb.setValue(0)
        self._comp_y_sb.setValue(0)
        w = self._comp_crop_canvas.source_w or 0
        h = self._comp_crop_canvas.source_h or 0
        self._comp_w_sb.setValue(0)   # 0 = no crop (full composite)
        self._comp_h_sb.setValue(0)
        if w > 0 and h > 0:
            self._comp_crop_canvas.set_region(0, 0, w, h)
        self._comp_sw_sb.setValue(-1)
        self._comp_sh_sb.setValue(-1)

    def _rebuild_composite_canvas(self):
        """Stitch zones and load the composite into the composite crop and stretch canvases."""
        if not self._full_pixmap or self._full_pixmap.isNull():
            self._status.setText("Capture a frame first before rebuilding the composite canvas.")
            return
        composite = self._build_composite_pixmap()
        if composite is None or composite.isNull():
            self._status.setText("No enabled zones — composite canvas cannot be built.")
            return
        # Save composite to a temp file and load via load_frame
        tmp_path = os.path.join(self._temp_dir, "composite_preview.png")
        composite.save(tmp_path)
        self._comp_crop_canvas.load_frame(tmp_path)
        # Restore crop region from spinboxes (if valid)
        cw = self._comp_w_sb.value()
        ch = self._comp_h_sb.value()
        if cw > 0 and ch > 0:
            self._comp_crop_canvas.set_region(
                self._comp_x_sb.value(),
                self._comp_y_sb.value(),
                cw, ch,
            )
        else:
            # Full composite — set to whole image
            self._comp_crop_canvas.set_region(
                0, 0, composite.width(), composite.height())

        # Update the stretch canvas with the composite as the source image
        sw = self._comp_sw_sb.value()
        sh = self._comp_sh_sb.value()
        out_w = sw if sw > 0 else composite.width()
        out_h = sh if sh > 0 else composite.height()
        self._comp_stretch_canvas.set_source(
            composite, 0, 0, composite.width(), composite.height())
        self._comp_stretch_canvas.set_output(out_w, out_h)

        self._status.setText(
            f"Composite canvas rebuilt  ({composite.width()} × {composite.height()} px). "
            "Switch to 'Edit Crop' or 'Edit Stretch' to adjust the composite output.")

    def _build_composite_pixmap(self, cfg=None):
        """Build and return the stitched composite QPixmap from current zone settings.

        Applies per-zone crop, optional scale, border, and offset_y then stitches
        according to the current stitch direction.  Returns None if no zones are enabled.

        *cfg* may be a pre-collected config dict (to avoid a duplicate
        :meth:`_collect_config` call when the caller already has one).
        """
        if not self._full_pixmap or self._full_pixmap.isNull():
            return None
        if cfg is None:
            cfg = self._collect_config()
        zones = [z for z in cfg["zones"] if z.get("enabled") and z.get("crop_w", 0) > 0]
        if not zones:
            return None

        direction = cfg.get("stack_direction", "horizontal")
        pieces = []
        for z in zones:
            cx, cy = max(0, z["crop_x"]), max(0, z["crop_y"])
            cw, ch = max(1, z["crop_w"]), max(1, z["crop_h"])
            sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
            border = z.get("border_px", 0)
            offset_y = int(z.get("offset_y", 0))
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
            if offset_y != 0:
                # Match mpv filter: pad then crop to keep dimensions constant
                abs_off = abs(offset_y)
                pad_y   = max(offset_y, 0)
                crop_y  = max(-offset_y, 0)
                taller = QPixmap(pm.width(), pm.height() + abs_off)
                taller.fill(QColor("black"))
                tp = QPainter(taller)
                tp.drawPixmap(0, pad_y, pm)
                tp.end()
                # Crop back to original height
                pm = taller.copy(0, crop_y, pm.width(), pm.height())
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
        return result

    # ------------------------------------------------------------------
    # Final preview compositing
    # ------------------------------------------------------------------

    def _refresh_final_preview(self):
        if not self._full_pixmap or self._full_pixmap.isNull():
            self._final_canvas.setText("No frame captured yet.")
            return

        cfg = self._collect_config()

        # Step 1: build zone composite (pass cfg so we don't call _collect_config twice)
        result = self._build_composite_pixmap(cfg)
        if result is None or result.isNull():
            self._final_canvas.setText("No zones are currently enabled.")
            return

        direction = cfg.get("stack_direction", "horizontal")
        n_zones = sum(1 for z in cfg["zones"] if z.get("enabled") and z.get("crop_w", 0) > 0)

        composite_w = result.width()
        composite_h = result.height()

        # Step 2: whole-composite crop
        comp_crop_w = int(cfg.get("comp_crop_w", 0))
        comp_crop_h = int(cfg.get("comp_crop_h", 0))
        comp_crop_x = int(cfg.get("comp_crop_x", 0))
        comp_crop_y = int(cfg.get("comp_crop_y", 0))
        if comp_crop_w > 0 and comp_crop_h > 0:
            # Clamp to composite bounds
            cx = max(0, min(comp_crop_x, composite_w - 1))
            cy = max(0, min(comp_crop_y, composite_h - 1))
            cw = min(comp_crop_w, composite_w - cx)
            ch = min(comp_crop_h, composite_h - cy)
            if cw > 0 and ch > 0:
                result = result.copy(cx, cy, cw, ch)


        # Step 3: whole-composite scale
        comp_sw = int(cfg.get("comp_scale_w", -1))
        comp_sh = int(cfg.get("comp_scale_h", -1))
        if comp_sw > 0 and comp_sh > 0:
            result = result.scaled(comp_sw, comp_sh,
                                   Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)

        # Step 4: place in output canvas (letterbox/pillarbox)
        out_w = self._out_w_sb.value()
        out_h = self._out_h_sb.value()
        display_w = result.width()
        display_h = result.height()

        canvas = QPixmap(out_w, out_h)
        canvas.fill(QColor("black"))
        cp = QPainter(canvas)
        # Centre the composite in the output canvas
        ox = (out_w - display_w) // 2
        oy = (out_h - display_h) // 2
        cp.drawPixmap(ox, oy, result)
        cp.end()

        # Step 5: scale the output canvas to fit the preview label
        label_size = self._final_canvas.size()
        scaled = canvas.scaled(label_size,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self._final_canvas.setPixmap(scaled)

        dir_txt = "vertical" if direction == "vertical" else "horizontal"
        crop_info = (f"  |  Comp crop: {comp_crop_w}×{comp_crop_h}"
                     if comp_crop_w > 0 and comp_crop_h > 0 else "")
        scale_info = (f"  |  Comp scale: {comp_sw}×{comp_sh}"
                      if comp_sw > 0 and comp_sh > 0 else "")
        self._stitch_info_label.setText(
            f"Stitch: {dir_txt}  |  {n_zones} zone(s)  |  "
            f"Composite: {composite_w}×{composite_h} px"
            f"{crop_info}{scale_info}  |  "
            f"Output canvas: {out_w}×{out_h} px")


    # ------------------------------------------------------------------
    # Video / mpv control
    # ------------------------------------------------------------------

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Test Video", _DEFAULT_DIALOG_DIR,
            "Media Files (*.mov *.mp4 *.avi *.mkv *.wmv *.m4v);;All Files (*)"
        )
        if not path:
            return
        self._selected_video_path = path
        self._update_external_source_availability()
        self._video_label.setText(os.path.basename(path))
        self._video_label.setStyleSheet("color: #d4d4d4;")
        self._launch_mpv(path)
        if self._ext_preview_open and self._is_external_source_video():
            self._ext_preview_start_pos = 0.0
            self._open_external_preview()

    def _launch_mpv(self, video_path):
        self._stop_mpv()
        self._ipc_path = _make_unique_mpv_pipe_name("mpv_mzoom")
        cmd = _build_multizone_capture_preview_mpv_command(MPV_PATH, self._ipc_path, video_path)
        try:
            self._mpv_process = subprocess.Popen(cmd)
            for btn in (self._play_btn, self._pause_btn, self._capture_btn,
                        self._beg_btn, self._frame_back_btn, self._frame_fwd_btn):
                btn.setEnabled(True)
            self._mz_scrub_slider.setEnabled(True)
            # Point the position poller at the new pipe so scrub labels update live.
            self._pos_poller.set_socket(self._ipc_path)
            self._status.setText(
                "mpv opened. Navigate to the desired frame, then click 'Capture Frame'.")
        except Exception as exc:
            self._status.setText(f"Error launching mpv: {exc}")

    def _send_ipc(self, command, max_attempts=2):
        ok, err = _send_mpv_ipc_command(self._ipc_path, command, max_attempts=max_attempts)
        if not ok:
            self._status.setText(f"IPC error: {err}")
        return ok

    def _play(self):
        self._send_ipc(["set_property", "pause", False])
        self._ext_preview_paused = False
        self._apply_external_preview_playback_state()
        if self._ext_preview_open and self._is_external_source_video():
            self._send_external_preview_command(["set_property", "pause", False], tolerate_closed=True)

    def _pause(self):
        self._send_ipc(["set_property", "pause", True])
        self._snapshot_external_preview_position()
        self._ext_preview_paused = True
        self._apply_external_preview_playback_state()
        if self._ext_preview_open and self._is_external_source_video():
            self._send_external_preview_command(["set_property", "pause", True], tolerate_closed=True)

    def _capture_frame(self):
        self._pause()
        QTimer.singleShot(350, self._do_capture)

    def _do_capture(self):
        safe_path = self._frame_path
        self._send_ipc(["screenshot-to-file", safe_path, "video"])
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
        # Push restored crop/stretch state and rebuild composite canvases immediately.
        self._push_restored_values_to_canvases()
        self._rebuild_composite_canvas()
        if self._tabs.currentIndex() == self._FINAL_TAB_INDEX:
            self._refresh_final_preview()

    def _stop_mpv(self):
        # Pause position polling before tearing down the IPC pipe.
        self._pos_poller.set_socket(None)
        if self._mpv_process and self._mpv_process.poll() is None:
            if self._ipc_path:
                _send_mpv_ipc_command(self._ipc_path, ["quit"], max_attempts=2)
                time.sleep(0.2)
            self._mpv_process.terminate()
        self._mpv_process = None
        self._ipc_path = None
        # Disable transport controls until a new video is loaded.
        for btn in (self._beg_btn, self._frame_back_btn, self._frame_fwd_btn):
            btn.setEnabled(False)
        self._mz_scrub_slider.setEnabled(False)

    # ------------------------------------------------------------------
    # Capture-preview transport controls
    # ------------------------------------------------------------------

    def _on_mz_position_updated(self, pos: float, dur: float):
        """Slot connected to PositionPoller.position_updated for the capture-preview mpv.

        Updates the scrub slider and MM:SS labels.  Blocked while the user is
        dragging the handle to prevent the slider jumping back to the poll value.
        """
        self._mz_pos = pos
        self._mz_dur = dur
        if not self._mz_slider_dragging:
            if dur > 0:
                slider_val = int((pos / dur) * 1000)
                self._mz_scrub_slider.blockSignals(True)
                self._mz_scrub_slider.setValue(slider_val)
                self._mz_scrub_slider.blockSignals(False)
            self._mz_pos_label.setText(_mz_format_duration(pos))
            self._mz_dur_label.setText(_mz_format_duration(dur))

    def _on_mz_scrub_moved(self, value: int):
        """Called continuously while the user drags the scrub-slider handle.

        Updates the position label live so the operator sees where they are
        landing; the actual seek is deferred to sliderReleased.
        """
        self._mz_slider_dragging = True
        if self._mz_dur > 0:
            pos = (value / 1000.0) * self._mz_dur
            self._mz_pos_label.setText(_mz_format_duration(pos))

    def _on_mz_scrub_released(self):
        """Called when the user releases the scrub-slider handle.

        Issues an absolute seek to the chosen position.  ``hr-seek yes``
        ensures frame-accurate positioning so the mpv window shows the exact
        frame at the new position even while paused.
        """
        if not self._mz_slider_dragging:
            return
        self._mz_slider_dragging = False
        if not self._ipc_path or self._mz_dur <= 0:
            return
        value = self._mz_scrub_slider.value()
        pos = (value / 1000.0) * self._mz_dur
        # Use "exact" flag for frame-accurate positioning so the mpv window
        # shows the precise frame even while paused (equivalent to hr-seek).
        self._send_ipc(["seek", pos, "absolute", "exact"])

    def _play_from_beginning(self):
        """Seek to position 0 and start playback."""
        self._send_ipc(["seek", 0, "absolute"])
        self._send_ipc(["set_property", "pause", False])
        self._ext_preview_paused = False
        self._apply_external_preview_playback_state()

    def _frame_forward(self):
        """Advance exactly one frame using mpv's native frame-step command.

        mpv pauses playback as a side-effect of frame-step, which is the desired
        behaviour here (the operator is locating a precise frame for capture).
        We update ``_ext_preview_paused`` accordingly so the external-preview
        logic stays consistent.
        """
        self._send_ipc(["frame-step"])
        # mpv pauses automatically after frame-step.
        self._ext_preview_paused = True
        self._apply_external_preview_playback_state()

    def _frame_back(self):
        """Step exactly one frame backward using mpv's frame-back-step command.

        Like frame-step, mpv pauses as a side-effect, which is desired.
        """
        self._send_ipc(["frame-back-step"])
        self._ext_preview_paused = True
        self._apply_external_preview_playback_state()

    def _is_external_source_video(self):
        return self._ext_source_combo.currentIndex() == 1

    def _update_external_source_availability(self):
        model = self._ext_source_combo.model()
        video_item = model.item(1)
        has_video = bool(self._selected_video_path)
        if video_item is not None:
            video_item.setEnabled(has_video)
        if not has_video and self._ext_source_combo.currentIndex() == 1:
            self._ext_source_combo.setCurrentIndex(0)

    def _on_external_source_mode_changed(self, _index):
        if self._ext_preview_open:
            self._open_external_preview()

    def _toggle_external_preview(self):
        if self._ext_preview_open:
            self._close_external_preview("External preview closed.")
            return
        self._open_external_preview()

    def _get_external_preview_frame_path(self):
        if self._cfg.get("frame_snapshot_path") and os.path.isfile(self._cfg["frame_snapshot_path"]):
            return self._cfg["frame_snapshot_path"]
        if os.path.isfile(self._frame_path):
            return self._frame_path
        return None

    def _get_external_preview_source_path(self):
        if self._is_external_source_video():
            return self._selected_video_path
        return self._get_external_preview_frame_path()

    def _send_external_preview_command(self, command, max_attempts=2, tolerate_closed=False):
        if self._ext_preview_process and self._ext_preview_process.poll() is not None:
            if not tolerate_closed:
                self._close_external_preview("External preview was closed.")
            return False
        ok, err = _send_mpv_ipc_command(self._ext_preview_ipc_path, command, max_attempts=max_attempts)
        if not ok and not tolerate_closed:
            self._status.setText(f"External preview IPC error: {err}")
        return ok

    def _snapshot_external_preview_position(self):
        if self._is_external_source_video() and not self._ext_preview_paused and self._ext_preview_wall_start is not None:
            self._ext_preview_start_pos = max(0.0, time.time() - self._ext_preview_wall_start)

    def _apply_external_preview_playback_state(self):
        if self._is_external_source_video() and not self._ext_preview_paused:
            self._ext_preview_wall_start = time.time() - max(0.0, self._ext_preview_start_pos)
        else:
            self._ext_preview_wall_start = None

    def _update_external_preview_button(self):
        self._ext_toggle_btn.setText("Close External Preview" if self._ext_preview_open else "Open External Preview")

    def _open_external_preview(self):
        self._snapshot_external_preview_position()
        source_path = self._get_external_preview_source_path()
        if self._is_external_source_video() and not source_path:
            self._status.setText("Select a source video before opening Video external preview.")
            return
        if not self._is_external_source_video() and not source_path:
            self._status.setText("Capture or restore a frame before opening Frame external preview.")
            return

        self._close_external_preview()
        self._ext_preview_ipc_path = _make_unique_mpv_pipe_name("mpv_mzoom_external")
        self._ext_preview_source_path = source_path
        vf_str = _build_vf_for_zones(self._collect_config())
        self._ext_preview_vf = vf_str or ""

        cmd = _build_external_preview_mpv_command(
            MPV_PATH,
            self._ext_preview_ipc_path,
            self._output_display_num,
            source_path,
            is_video_source=self._is_external_source_video(),
            paused=self._ext_preview_paused,
            vf_str=self._ext_preview_vf,
        )

        try:
            self._ext_preview_process = subprocess.Popen(cmd)
        except Exception as exc:
            self._ext_preview_process = None
            self._ext_preview_ipc_path = None
            self._status.setText(f"Could not open external preview mpv: {exc}")
            return

        self._ext_preview_open = True
        self._ext_preview_start_pos = max(0.0, self._ext_preview_start_pos)
        self._apply_external_preview_playback_state()
        self._update_external_preview_button()
        src_label = "video" if self._is_external_source_video() else "captured frame"
        self._status.setText(
            f"External preview opened on display {self._output_display_num} using {src_label}. "
            "This is a separate preview process from live playback.")
        if self._is_external_source_video() and self._ext_preview_start_pos > 0:
            QTimer.singleShot(
                300,
                lambda: self._send_external_preview_command(
                    ["set_property", "time-pos", max(0.0, self._ext_preview_start_pos)],
                    max_attempts=8,
                    tolerate_closed=True))

    def _close_external_preview(self, status_text=None):
        self._snapshot_external_preview_position()
        if self._ext_preview_process and self._ext_preview_process.poll() is None:
            self._send_external_preview_command(["quit"], max_attempts=2, tolerate_closed=True)
            try:
                self._ext_preview_process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                self._ext_preview_process.terminate()
        self._ext_preview_process = None
        self._ext_preview_ipc_path = None
        self._ext_preview_open = False
        self._ext_preview_source_path = None
        self._ext_preview_vf = None
        self._ext_preview_wall_start = None
        self._update_external_preview_button()
        if status_text:
            self._status.setText(status_text)

    def _on_live_refresh_clicked(self):
        """Manually reload external preview using current settings."""
        if not self._ext_preview_open:
            self._status.setText("External preview is not open.")
            return
        self._open_external_preview()

    # ------------------------------------------------------------------
    # Dialog accept / reject
    # ------------------------------------------------------------------

    def _ok(self):
        self.result_config = self.collect_config()
        self._close_external_preview()
        self._stop_mpv()
        self.accept()

    def _cancel(self):
        self._close_external_preview()
        self._stop_mpv()
        self.reject()

    def closeEvent(self, event):
        self._close_external_preview()
        self._stop_mpv()
        # Stop the position-poller thread so it is not leaked when the dialog closes.
        self._pos_poller.stop()
        self._pos_poller.wait()
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
            self, "Export Editor State", os.path.join(_DEFAULT_DIALOG_DIR, "zoom_editor_state.json"),
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
            self, "Import Editor State", _DEFAULT_DIALOG_DIR,
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
        # Rebuild composite preview immediately after importing state
        self._schedule_composite_update()
        self._status.setText(
            f"Editor state imported from '{os.path.basename(path)}'.")


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

    MAX_LINES = 1000  # Prevent unbounded memory growth while keeping startup preflight visible.

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

    debug_message = pyqtSignal(str)

    # Milliseconds of main-thread silence before the freeze watchdog logs a warning.
    _FREEZE_WARN_MS = 1500

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kattman Komplete Kontreol")

        # Debug console (created early so _debug_log works immediately).
        self._debug_console = DebugConsoleWindow(self)
        self.debug_message.connect(self._debug_console.append)
        _set_debug_log_hook(self._debug_log)

        self.config = self.load_config()
        self._run_startup_preflight()
        self.track_name_data = self.load_json_store(TRACK_NAME_STORE_FILE)
        self.bpm_store = self.load_json_store(BPM_STORE_FILE)
        self.zoom_config = self.load_zoom_config()
        self.worker = None
        self.test_worker = None
        self.current_ipc_socket = None
        self.is_live_mode = False
        self.tracks = []
        self.undo_history = deque(maxlen=MAX_UNDO_LEVELS)
        self.hotkey_map = {}
        self.available_hotkeys = self._generate_hotkeys()
        self.currently_playing_row = None
        self._user_stopped = False
        self.test_track_path = None
        self.absolute_start_time = None
        self.active_sync_show_session = None
        self.streamdeck_font_size = DEFAULT_STREAMDECK_FONT_SIZE
        self.led2_on = False

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
        self._loop_bpm = 120
        self._loop_start_bar = 1
        self._loop_end_bar = 8

        self.midi_available = False
        self.rtmidi_available = rtmidi is not None
        self.pyserial_available = serial is not None
        if self.rtmidi_available:
            try:
                test_out = rtmidi.MidiOut()
                self.midi_available = test_out.get_port_count() > 0
            except Exception:
                self.midi_available = False
        self.arduino_serial = self._connect_arduino()

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
        if self.midi_available:
            self.send_led_command("4")
        else:
            self.send_led_command("1")
        if rtmidi is None:
            self._debug_log("python-rtmidi not installed; MIDI features disabled.")
        if psutil is None:
            self._debug_log("psutil not installed; running without extra process priority hints.")
        if serial is None:
            self._debug_log("pyserial not installed; Arduino LED controls disabled.")

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

        # Center: K▲TTM▲N KONTROL KOMPLETE logo + setlist info stacked
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
        self.export_streamdeck_button = QPushButton("Export StreamDeck")
        self.export_streamdeck_button.setStyleSheet(
            "background-color: #103020; color: #30d158; border: 1px solid #2b7a52; "
            "font-size: 10px; padding: 3px 10px; border-radius: 5px;"
        )
        self.export_streamdeck_button.clicked.connect(self.export_streamdeck_profile)
        self.streamdeck_font_spinbox = QSpinBox()
        self.streamdeck_font_spinbox.setRange(6, 36)
        self.streamdeck_font_spinbox.setValue(self.streamdeck_font_size)
        self.streamdeck_font_spinbox.setSuffix(" pt")
        self.streamdeck_font_spinbox.setFixedWidth(68)
        export_buttons_row = QHBoxLayout()
        export_buttons_row.setSpacing(4)
        export_buttons_row.addWidget(self.export_setlist_button)
        export_buttons_row.addWidget(self.export_streamdeck_button)
        export_buttons_row.addWidget(self.streamdeck_font_spinbox)

        title_layout.addWidget(logo_label)
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.running_time_label)
        title_layout.addLayout(export_buttons_row)

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
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(["Key", "Name", "Lnk", "BPM", "C", "R1", "R2", "Syn", "Secs", "Del"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(20)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(2, 40)
        self.table.setColumnWidth(3, 66)
        self.table.setColumnWidth(4, 34)
        self.table.setColumnWidth(5, 36)
        self.table.setColumnWidth(6, 36)
        self.table.setColumnWidth(7, 38)
        self.table.setColumnWidth(8, 50)
        self.table.setColumnWidth(9, 40)
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
        self.require_midi_checkbox = QCheckBox("Require MIDI")
        self.require_midi_checkbox.setChecked(True)
        settings_layout.addWidget(self.require_midi_checkbox, 5, 0, 1, 2)
        self.midi_offset_slider = QSlider(Qt.Orientation.Horizontal)
        self.midi_offset_slider.setRange(-1000, 1000)
        self.midi_offset_slider.setValue(DEFAULT_MIDI_OFFSET_MS)
        self.midi_offset_spinbox = QSpinBox()
        self.midi_offset_spinbox.setRange(-1000, 1000)
        self.midi_offset_spinbox.setValue(DEFAULT_MIDI_OFFSET_MS)
        self.midi_offset_spinbox.setSuffix(" ms")
        self.midi_offset_spinbox.setFixedWidth(76)
        self.midi_offset_slider.valueChanged.connect(self.midi_offset_spinbox.setValue)
        self.midi_offset_spinbox.valueChanged.connect(self.midi_offset_slider.setValue)
        midi_offset_row = QHBoxLayout()
        midi_offset_row.setSpacing(4)
        midi_offset_row.addWidget(self.midi_offset_slider, 1)
        midi_offset_row.addWidget(self.midi_offset_spinbox)
        self.midi_offset_reset_btn = QPushButton("Reset")
        self.midi_offset_reset_btn.setFixedWidth(52)
        self.midi_offset_reset_btn.clicked.connect(lambda: self.midi_offset_spinbox.setValue(DEFAULT_MIDI_OFFSET_MS))
        midi_offset_row.addWidget(self.midi_offset_reset_btn)
        settings_layout.addWidget(QLabel("MIDI Offset:"), 6, 0)
        settings_layout.addLayout(midi_offset_row, 6, 1)
        self.timing_standard_radio = QRadioButton("Std")
        self.timing_high_precision_radio = QRadioButton("HP")
        self.timing_standard_radio.setChecked(True)
        timing_row = QHBoxLayout()
        timing_row.setSpacing(4)
        timing_row.addWidget(self.timing_standard_radio)
        timing_row.addWidget(self.timing_high_precision_radio)
        settings_layout.addWidget(QLabel("Timing:"), 7, 0)
        settings_layout.addLayout(timing_row, 7, 1)
        self.no_midi_overlay = QLabel("NO MIDI INTERFACE DETECTED")
        self.no_midi_overlay.setStyleSheet("color: #ff453a; font-size: 10px; font-weight: 700;")
        self.no_midi_overlay.setVisible(not self.midi_available)
        settings_layout.addWidget(self.no_midi_overlay, 8, 0, 1, 2)
        settings_group.setLayout(settings_layout)

        midi_ports_group = QGroupBox("MIDI Port Testing")
        midi_ports_layout = QGridLayout()
        midi_ports_layout.setContentsMargins(4, 6, 4, 4)
        midi_ports_layout.setSpacing(3)
        midi_ports_layout.addWidget(QLabel("Port"), 0, 0)
        midi_ports_layout.addWidget(QLabel("On"), 0, 1)
        midi_ports_layout.addWidget(QLabel("Start"), 0, 2)
        midi_ports_layout.addWidget(QLabel("BPM"), 0, 3)
        midi_ports_layout.addWidget(QLabel("Test"), 0, 4)
        self.midi_port_controls = {}
        for row, (label, port_num) in enumerate((("Click", 1), ("Rich1", 2), ("Rich2", 3)), start=1):
            midi_ports_layout.addWidget(QLabel(label), row, 0)
            enabled_cb = QCheckBox()
            enabled_cb.setChecked(True)
            start_cb = QCheckBox()
            bpm_spin = QSpinBox()
            bpm_spin.setRange(40, 280)
            bpm_spin.setValue(120)
            bpm_spin.setFixedWidth(62)
            test_btn = QPushButton("Start")
            test_btn.setFixedWidth(58)
            test_btn.clicked.connect(lambda _c=False, p=port_num: self.toggle_midi_test(p))
            midi_ports_layout.addWidget(enabled_cb, row, 1)
            midi_ports_layout.addWidget(start_cb, row, 2)
            midi_ports_layout.addWidget(bpm_spin, row, 3)
            midi_ports_layout.addWidget(test_btn, row, 4)
            self.midi_port_controls[port_num] = {
                "enabled": enabled_cb,
                "send_start": start_cb,
                "bpm": bpm_spin,
                "button": test_btn,
                "worker": None,
            }
        midi_ports_group.setLayout(midi_ports_layout)

        sync_show_group = QGroupBox("Sync Show API")
        sync_show_layout = QGridLayout()
        sync_show_layout.setContentsMargins(4, 6, 4, 4)
        sync_show_layout.setSpacing(3)
        self.sync_show_host_input = QLineEdit()
        self.sync_show_host_input.setPlaceholderText(DEFAULT_SYNC_SHOW_HOST)
        self.sync_show_session_input = QLineEdit()
        self.sync_show_session_input.setText(DEFAULT_SYNC_SHOW_SESSION)
        self.sync_show_session_input.setEnabled(False)
        self.sync_show_trim_spinbox = QSpinBox()
        self.sync_show_trim_spinbox.setRange(-5000, 5000)
        self.sync_show_trim_spinbox.setValue(DEFAULT_SYNC_TIMING_TRIM_MS)
        self.sync_show_trim_spinbox.setSuffix(" ms")
        sync_show_layout.addWidget(QLabel("Host"), 0, 0)
        sync_show_layout.addWidget(self.sync_show_host_input, 0, 1)
        sync_show_layout.addWidget(QLabel("Session"), 1, 0)
        sync_show_layout.addWidget(self.sync_show_session_input, 1, 1)
        sync_show_layout.addWidget(QLabel("Trim"), 2, 0)
        sync_show_layout.addWidget(self.sync_show_trim_spinbox, 2, 1)
        sync_show_group.setLayout(sync_show_layout)

        calibration_group = QGroupBox("Sync Calibration")
        calibration_layout = QHBoxLayout()
        calibration_layout.setContentsMargins(4, 6, 4, 4)
        calibration_layout.setSpacing(4)
        self.calib_duration_spinbox = QSpinBox()
        self.calib_duration_spinbox.setRange(1, 20)
        self.calib_duration_spinbox.setValue(8)
        self.calib_duration_spinbox.setSuffix(" s")
        self.calib_duration_spinbox.setToolTip("Runs an auto-restart loop with mpv --length for iterative sync calibration.")
        self.calib_button = QPushButton("Start")
        self.calib_button.clicked.connect(self.toggle_calib_loop)
        calibration_layout.addWidget(QLabel("Duration:"))
        calibration_layout.addWidget(self.calib_duration_spinbox)
        calibration_layout.addWidget(self.calib_button)
        calibration_group.setLayout(calibration_layout)

        zoom_group = QGroupBox("Zoom / Scale")
        zoom_layout = QHBoxLayout()
        zoom_layout.setContentsMargins(4, 6, 4, 4)
        zoom_layout.setSpacing(4)
        self.apply_zoom_checkbox = QCheckBox("Apply")
        self.apply_zoom_checkbox.setChecked(False)
        self.zoom_status_label = QLabel("Not configured")
        self.zoom_status_label.setStyleSheet("font-size: 10px; color: #636366;")
        self.zoom_button = QPushButton("Configure…")
        self.zoom_button.clicked.connect(self.open_zoom_dialog)
        self.apply_zoom_checkbox.toggled.connect(self._update_zoom_status_label)
        zoom_layout.addWidget(self.apply_zoom_checkbox)
        zoom_layout.addWidget(self.zoom_button)
        zoom_layout.addWidget(self.zoom_status_label, 1)
        zoom_group.setLayout(zoom_layout)

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

        # Bar-based loop row: BPM / Bar A / Bar B / Loop A→B.
        loop_row = QHBoxLayout()
        loop_row.setSpacing(3)
        self.loop_bpm_spinbox = QSpinBox()
        self.loop_bpm_spinbox.setRange(40, 280)
        self.loop_bpm_spinbox.setValue(120)
        self.loop_bpm_spinbox.setFixedWidth(56)
        self.loop_bpm_spinbox.valueChanged.connect(self._on_loop_bar_changed)
        self.loop_start_bar_spinbox = QSpinBox()
        self.loop_start_bar_spinbox.setRange(1, 9999)
        self.loop_start_bar_spinbox.setValue(1)
        self.loop_start_bar_spinbox.setFixedWidth(54)
        self.loop_start_bar_spinbox.valueChanged.connect(self._on_loop_bar_changed)
        self.loop_end_bar_spinbox = QSpinBox()
        self.loop_end_bar_spinbox.setRange(1, 9999)
        self.loop_end_bar_spinbox.setValue(8)
        self.loop_end_bar_spinbox.setFixedWidth(54)
        self.loop_end_bar_spinbox.valueChanged.connect(self._on_loop_bar_changed)
        self.loop_a_time_label = QLabel("(00:00)")
        self.loop_a_time_label.setStyleSheet("font-size: 10px; color: #aeaeb2;")
        self.loop_b_time_label = QLabel("(00:15)")
        self.loop_b_time_label.setStyleSheet("font-size: 10px; color: #aeaeb2;")
        self.loop_checkbox = QCheckBox("Loop A→B")
        self.loop_checkbox.setToolTip(
            "When checked, mpv will repeat the section between loop points A and B continuously."
        )
        self.loop_checkbox.toggled.connect(self._on_loop_toggled)
        loop_row.addWidget(QLabel("BPM:"))
        loop_row.addWidget(self.loop_bpm_spinbox)
        loop_row.addWidget(QLabel("A:"))
        loop_row.addWidget(self.loop_start_bar_spinbox)
        loop_row.addWidget(self.loop_a_time_label)
        loop_row.addWidget(QLabel("B:"))
        loop_row.addWidget(self.loop_end_bar_spinbox)
        loop_row.addWidget(self.loop_b_time_label)
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
        self.right_tabs = QTabWidget()
        self.right_tabs.setDocumentMode(True)
        look_tab = QWidget()
        look_layout = QVBoxLayout(look_tab)
        look_layout.setContentsMargins(0, 0, 0, 0)
        look_layout.setSpacing(3)
        look_layout.addWidget(overlay_colours_group)
        look_layout.addWidget(color_scheme_group)
        look_layout.addWidget(app_group)
        look_layout.addStretch(1)
        midi_tab = QWidget()
        midi_layout = QVBoxLayout(midi_tab)
        midi_layout.setContentsMargins(0, 0, 0, 0)
        midi_layout.setSpacing(3)
        midi_layout.addWidget(midi_ports_group)
        midi_layout.addWidget(sync_show_group)
        midi_layout.addWidget(calibration_group)
        midi_layout.addWidget(zoom_group)
        midi_layout.addStretch(1)
        self.right_tabs.addTab(look_tab, "Look")
        self.right_tabs.addTab(midi_tab, "Sync")
        row_mid.addWidget(self.right_tabs)

        controls_area.addLayout(row_top)
        controls_area.addWidget(test_track_group)
        controls_area.addLayout(row_mid)
        controls_area.addStretch(1)

        controls_widget = QWidget()
        controls_widget.setLayout(controls_area)

        main_layout.addWidget(self.table, 3)
        main_layout.addWidget(controls_widget, 2)

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
        self._on_loop_bar_changed()
        self._update_zoom_status_label()
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
        self.export_streamdeck_button.setEnabled(is_edit_mode)
        self.streamdeck_font_spinbox.setEnabled(is_edit_mode)
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
        self.require_midi_checkbox.setEnabled(is_edit_mode)
        self.midi_offset_slider.setEnabled(is_edit_mode)
        self.midi_offset_spinbox.setEnabled(is_edit_mode)
        self.midi_offset_reset_btn.setEnabled(is_edit_mode)
        self.timing_standard_radio.setEnabled(is_edit_mode)
        self.timing_high_precision_radio.setEnabled(is_edit_mode)
        self.sync_show_host_input.setEnabled(is_edit_mode)
        self.sync_show_trim_spinbox.setEnabled(is_edit_mode)
        self.calib_duration_spinbox.setEnabled(is_edit_mode)
        self.calib_button.setEnabled(True)
        self.apply_zoom_checkbox.setEnabled(is_edit_mode)
        self.zoom_button.setEnabled(is_edit_mode)
        self.set_test_controls_enabled(is_edit_mode)
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
                    for col in [1, 2, 3, 4, 5, 6, 7, 8]:
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
        keys.remove('z')
        return keys

    # ------------------------------------------------------------------ #
    # Config persistence
    # ------------------------------------------------------------------ #

    def load_config(self):
        defaults = {
            "display": DEFAULT_VIDEO_SCREEN_NUMBER,
            "preload": DEFAULT_LOAD_DELAY_SECONDS,
            "sync_show_host": DEFAULT_SYNC_SHOW_HOST,
            "sync_show_session": DEFAULT_SYNC_SHOW_SESSION,
            "sync_show_timing_trim_ms": DEFAULT_SYNC_TIMING_TRIM_MS,
        }
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
        self.config['sync_show_host'] = self.sync_show_host_input.text().strip()
        self.config['sync_show_session'] = self.sync_show_session_input.text().strip() or DEFAULT_SYNC_SHOW_SESSION
        self.config['sync_show_timing_trim_ms'] = int(self.sync_show_trim_spinbox.value())
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)

    def apply_config_to_ui(self):
        self.display_combo.setCurrentText(str(self.config.get("display", DEFAULT_VIDEO_SCREEN_NUMBER)))
        self.preload_combo.setCurrentText(str(self.config.get("preload", DEFAULT_LOAD_DELAY_SECONDS)))
        self.sync_show_host_input.setText(self.config.get('sync_show_host', DEFAULT_SYNC_SHOW_HOST))
        self.sync_show_session_input.setText(self.config.get('sync_show_session', DEFAULT_SYNC_SHOW_SESSION))
        self.sync_show_trim_spinbox.setValue(int(self.config.get('sync_show_timing_trim_ms', DEFAULT_SYNC_TIMING_TRIM_MS)))
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
            'loop_bpm': self.loop_bpm_spinbox.value(),
            'loop_start_bar': self.loop_start_bar_spinbox.value(),
            'loop_end_bar': self.loop_end_bar_spinbox.value(),
            'midi_offset_ms': self.midi_offset_spinbox.value(),
            'timing_method': 'high_precision' if self.timing_high_precision_radio.isChecked() else 'standard',
            'require_midi': self.require_midi_checkbox.isChecked(),
            'streamdeck_font_size': self.streamdeck_font_spinbox.value(),
            'apply_zoom': self.apply_zoom_checkbox.isChecked(),
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
            self.loop_bpm_spinbox.setValue(int(session_data.get('loop_bpm', 120)))
            self.loop_start_bar_spinbox.setValue(int(session_data.get('loop_start_bar', 1)))
            self.loop_end_bar_spinbox.setValue(int(session_data.get('loop_end_bar', 8)))
            self.midi_offset_spinbox.setValue(int(session_data.get('midi_offset_ms', DEFAULT_MIDI_OFFSET_MS)))
            self.require_midi_checkbox.setChecked(bool(session_data.get('require_midi', True)))
            timing_method = session_data.get('timing_method', 'standard')
            self.timing_high_precision_radio.setChecked(timing_method == 'high_precision')
            self.timing_standard_radio.setChecked(timing_method != 'high_precision')
            self.streamdeck_font_spinbox.setValue(int(session_data.get('streamdeck_font_size', DEFAULT_STREAMDECK_FONT_SIZE)))
            self.apply_zoom_checkbox.setChecked(bool(session_data.get('apply_zoom', False)))
            self._update_scrub_controls_state()
            self._on_loop_bar_changed()

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
                'gap_seconds': 0,
                'bpm': int(self.bpm_store.get(file_path, 120)),
                'midi_click': True,
                'midi_rich1': True,
                'midi_rich2': True,
                'sync_show_enabled': False,
                'sync_show_file': "",
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
            self._debug_log("WARNING: mplayer not found in PATH; track duration defaults to 0.")
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
            self._debug_log(f"WARNING: Could not parse ID_LENGTH for {file_path}; track duration defaults to 0.")
            return 0
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError, subprocess.TimeoutExpired) as e:
            self._debug_log(f"WARNING: Could not get duration for {file_path}: {e}")
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
                self.table.setCellWidget(i, 9, btn_container)
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

                bpm_spin = QSpinBox()
                bpm_spin.setRange(40, 280)
                bpm_spin.setValue(int(item.get('bpm', 120)))
                bpm_spin.setFixedWidth(66)
                bpm_spin.valueChanged.connect(lambda value, r=i: self.update_bpm(value, r))
                self.table.setCellWidget(i, 3, bpm_spin)

                def create_midi_checkbox(row_idx, key_name):
                    container = QWidget()
                    layout = QHBoxLayout(container)
                    cb = QCheckBox()
                    cb.setStyleSheet("QCheckBox::indicator { width: 12px; height: 12px; }")
                    cb.setChecked(bool(self.tracks[row_idx].get(key_name, True)))
                    cb.toggled.connect(lambda checked, r=row_idx, k=key_name: self.update_midi_port_setting(r, k, checked))
                    layout.addWidget(cb)
                    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    layout.setContentsMargins(0, 0, 0, 0)
                    return container

                self.table.setCellWidget(i, 4, create_midi_checkbox(i, 'midi_click'))
                self.table.setCellWidget(i, 5, create_midi_checkbox(i, 'midi_rich1'))
                self.table.setCellWidget(i, 6, create_midi_checkbox(i, 'midi_rich2'))
                self.table.setCellWidget(i, 7, create_midi_checkbox(i, 'sync_show_enabled'))

                is_linked = item.get('linked', False)
                seconds_input = QLineEdit(str(max(0, min(99, item.get('gap_seconds', 0)))).zfill(2))
                seconds_input.setFont(table_font)
                seconds_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
                seconds_input.setMaxLength(2)
                seconds_input.setToolTip("Gap in seconds before next song (only active when Link is on)")
                seconds_input.setEnabled(is_linked)
                seconds_input.textChanged.connect(lambda text, path=item['path']: self.update_gap_seconds(path, text))
                seconds_input.editingFinished.connect(lambda w=seconds_input: w.setText(w.text().zfill(2) if w.text() else "00"))
                self.table.setCellWidget(i, 8, seconds_input)

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
                self.table.setCellWidget(i, 9, btn_container)

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
            seconds_widget = self.table.cellWidget(row_index, 8)
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

    def update_bpm(self, bpm, row_index):
        if 0 <= row_index < len(self.tracks) and self.tracks[row_index].get('type') == 'track':
            self.tracks[row_index]['bpm'] = int(bpm)
            path = self.tracks[row_index].get('path')
            if path:
                self.bpm_store[path] = int(bpm)
                self.save_json_store(BPM_STORE_FILE, self.bpm_store)

    def update_midi_port_setting(self, row_index, key_name, checked):
        if 0 <= row_index < len(self.tracks) and self.tracks[row_index].get('type') == 'track':
            self.tracks[row_index][key_name] = bool(checked)

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
            'streamdeck_font_size': self.streamdeck_font_spinbox.value(),
            'loop_bpm': self.loop_bpm_spinbox.value(),
            'loop_start_bar': self.loop_start_bar_spinbox.value(),
            'loop_end_bar': self.loop_end_bar_spinbox.value(),
            'midi_offset_ms': self.midi_offset_spinbox.value(),
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
            self.streamdeck_font_spinbox.setValue(int(loaded_data.get('streamdeck_font_size', DEFAULT_STREAMDECK_FONT_SIZE)))
            self.loop_bpm_spinbox.setValue(int(loaded_data.get('loop_bpm', 120)))
            self.loop_start_bar_spinbox.setValue(int(loaded_data.get('loop_start_bar', 1)))
            self.loop_end_bar_spinbox.setValue(int(loaded_data.get('loop_end_bar', 8)))
            self.midi_offset_spinbox.setValue(int(loaded_data.get('midi_offset_ms', DEFAULT_MIDI_OFFSET_MS)))
            table_font_size = loaded_data.get('table_font_size')
            if table_font_size is not None:
                self.current_table_font_size = table_font_size
                self.font_size_spinbox.setValue(self.current_table_font_size)
                # apply_table_font_size() is called by _apply_setlist_data() below
        else:
            tracks_data = loaded_data
            self.undo_history.clear()

        self._apply_setlist_data(tracks_data, setlist_name)
        self._on_loop_bar_changed()
        self.update_undo_button_state()

    def _apply_setlist_data(self, setlist_data, setlist_name):
        self.tracks, self.hotkey_map = [], {}
        self.available_hotkeys = self._generate_hotkeys()
        for item in setlist_data:
            if 'type' not in item:
                item['type'] = 'track'
        valid_hotkeys = set(self._generate_hotkeys())
        loaded_hotkeys = {
            item.get('hotkey') for item in setlist_data
            if item.get('type') == 'track' and item.get('hotkey') in valid_hotkeys
        }
        self.available_hotkeys = [k for k in self.available_hotkeys if k not in loaded_hotkeys]
        for item in setlist_data:
            if item['type'] == 'track':
                if 'duration' not in item or item['duration'] == 0:
                    item['duration'] = self.get_track_duration(item['path'])
                if 'linked' not in item:
                    item['linked'] = False
                if 'gap_seconds' not in item:
                    item['gap_seconds'] = 0
                item.setdefault('bpm', int(self.bpm_store.get(item.get('path', ''), 120)))
                item.setdefault('midi_click', True)
                item.setdefault('midi_rich1', True)
                item.setdefault('midi_rich2', True)
                item.setdefault('sync_show_enabled', False)
                item.setdefault('sync_show_file', "")
                item.setdefault('hotkey', '')
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
        index = 0
        name_col = max([len((self.table.cellWidget(i, 1).text() if self.table.cellWidget(i, 1) else "").upper())
                        for i in range(self.table.rowCount()) if i < len(self.tracks) and self.tracks[i].get('type') == 'track'] + [10])
        for row_index, item in enumerate(self.tracks):
            if item['type'] == 'divider':
                lines.append("")
                lines.append(item.get('text', 'ENCORE'))
                lines.append("")
            else:
                index += 1
                duration = item.get('duration', 0)
                total_seconds += duration
                name_widget = self.table.cellWidget(row_index, 1)
                track_name = (name_widget.text() if name_widget else "").replace('_', ' ').upper()
                bpm = int(item.get('bpm', 120))
                lines.append(
                    f"{index:02d}. {track_name:<{name_col}}"
                    f"\t{self.format_duration(duration):>5}\t{bpm:>3} BPM"
                )
        lines.append("")
        lines.append(f"Total Time: {self.format_duration(total_seconds, show_hours=True)}")
        track_count = len([t for t in self.tracks if t['type'] == 'track'])
        total_with_overhead = total_seconds + (track_count * TRACK_OVERHEAD_SECONDS)
        lines.append(f"Total Time (incl. {TRACK_OVERHEAD_SECONDS}s gap between songs): {self.format_duration(total_with_overhead, show_hours=True)}")

        setlist_name = self.title_label.text()
        safe_name = re.sub(r'[\\/*?:"<>|]', '', setlist_name).strip() or "setlist"
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d")
        file_path = os.path.join(downloads_dir, f"{safe_name}_{stamp}_setlist.txt")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        self.status_label.setText(f"Status: Set list exported to {file_path}")

    @staticmethod
    def _wrap_button_title(name: str) -> str:
        name = (name or "").strip()
        if not name:
            return ""
        words = name.split()
        if len(words) <= 2:
            return "\n".join(words)
        first = " ".join(words[:2])
        second = " ".join(words[2:])
        return f"{first}\n{second}"

    def export_streamdeck_profile(self):
        icons_dir = os.path.join(os.getcwd(), "STREAMDECK ICONS")
        profile_dir = os.path.join(os.getcwd(), "MESH LIVE TTDM 2026")
        if not os.path.isdir(icons_dir) or not os.path.isdir(profile_dir):
            self.status_label.setText("Status: StreamDeck assets missing (STREAMDECK ICONS/ or MESH LIVE TTDM 2026/).")
            return
        output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "MESH LIVE TTDM 2026.streamDeckProfile")
        try:
            if os.path.exists(output_path):
                if os.path.isdir(output_path):
                    shutil.rmtree(output_path)
                else:
                    os.unlink(output_path)
            shutil.copytree(profile_dir, output_path)
            self.status_label.setText(f"Status: StreamDeck profile exported to {output_path}")
            subprocess.Popen(["open", output_path])
        except Exception as exc:
            self.status_label.setText(f"Status: StreamDeck export failed — {exc}")

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

        if pynput_keyboard is None:
            self.hotkey_listener = None
            self._show_hotkey_unavailable("pynput not installed")
            self._debug_log("Hotkey listener unavailable: pynput not installed.")
            return

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
        if lower_key == 'z':
            self.led2_on = not self.led2_on
            self.send_led_command("2" if self.led2_on else "4")
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
        bpm = int(track_data.get('bpm', 120))
        if self.require_midi_checkbox.isChecked() and not self.midi_available:
            self.send_led_command("1")
            self.status_label.setText("Status: MIDI required but no MIDI interface detected.")
            return
        label = "test track" if row_index is None else f"row {row_index}"
        self._debug_log(
            f"Playback start: {os.path.basename(track_path or '')} "
            f"({label}, display={display_num}, preload={preload_time}s, "
            f"audio_only={audio_only}, bpm={bpm})"
        )

        self.clear_highlight()
        if row_index is not None:
            self.highlight_row(row_index, is_playing=True)
            self.currently_playing_row = row_index
        else:
            self.test_file_label.setStyleSheet("font-weight: bold; color: #30d158;")

        self.active_flash_timer.start()
        midi_offset = self.midi_offset_spinbox.value()
        timing_method = 'high_precision' if self.timing_high_precision_radio.isChecked() else 'standard'
        zoom_cfg = self.zoom_config if self.apply_zoom_checkbox.isChecked() else {}
        track_trim_ms = int(self.config.get('sync_show_timing_trim_ms', DEFAULT_SYNC_TIMING_TRIM_MS))
        self.absolute_start_time = time.time() + preload_time + (track_trim_ms / 1000.0)
        self.worker = MidiSyncWorker(
            track_path, bpm, display_num, preload_time, midi_offset,
            track_data.get('midi_click', True),
            track_data.get('midi_rich1', True),
            track_data.get('midi_rich2', True),
            timing_method,
            require_midi=self.require_midi_checkbox.isChecked(),
            zoom_config=zoom_cfg,
            absolute_start_time=self.absolute_start_time,
            audio_only_mode=audio_only
        )
        self.worker.status_update.connect(self.status_label.setText)
        self.worker.error.connect(self._on_playback_error)
        self.worker.finished.connect(self.on_playback_finished)
        self.worker.ipc_socket_path.connect(self.set_ipc_socket)
        self.worker.start()
        self.send_led_command("3")
        self.send_led_command("6")
        if track_data.get('sync_show_enabled') and track_data.get('sync_show_file'):
            self.trigger_sync_show(track_data.get('sync_show_file'), start_at=self.absolute_start_time, offset_sec=0)
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
        self.stop_sync_show()
        self.send_led_command("4")

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
        self.stop_sync_show()
        self.send_led_command("4")

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

    def _bars_to_seconds(self, bar_index):
        beats_per_bar = 4.0
        bpm = max(1, self.loop_bpm_spinbox.value())
        return ((max(1, bar_index) - 1) * beats_per_bar) * (60.0 / bpm)

    def _on_loop_bar_changed(self, *_args):
        start_bar = self.loop_start_bar_spinbox.value()
        end_bar = self.loop_end_bar_spinbox.value()
        if end_bar < start_bar:
            self.loop_end_bar_spinbox.blockSignals(True)
            self.loop_end_bar_spinbox.setValue(start_bar)
            self.loop_end_bar_spinbox.blockSignals(False)
            end_bar = start_bar
        start_sec = self._bars_to_seconds(start_bar)
        end_sec = self._bars_to_seconds(end_bar + 1)
        self._loop_a_seconds = start_sec
        self._loop_b_seconds = end_sec
        self.loop_a_time_label.setText(f"({self.format_duration(start_sec)})")
        self.loop_b_time_label.setText(f"({self.format_duration(end_sec)})")
        if self.loop_checkbox.isChecked() and self.current_ipc_socket:
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["set_property", "ab-loop-a", self._loop_a_seconds]}),
            )
            _send_ipc_command(
                self.current_ipc_socket,
                json.dumps({"command": ["set_property", "ab-loop-b", self._loop_b_seconds]}),
            )

    def _on_loop_toggled(self, checked: bool):
        self._on_loop_bar_changed()
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
        self._on_loop_bar_changed()
        self._update_scrub_controls_state()

    def _debug_log(self, message: str):
        """Append a message to the debug console (thread-safe from main thread)."""
        self.debug_message.emit(message)

    def _run_startup_preflight(self):
        def log(message):
            self._debug_log(message)

        def first_non_empty_line(text):
            for line in (text or "").splitlines():
                line = line.strip()
                if line:
                    return line
            return ""

        def check_binary(name, version_args, missing_level):
            try:
                resolved = _find_executable(name)
                exists = os.path.exists(resolved)
                executable = os.access(resolved, os.X_OK) if exists else False
                log(f"{name}: path={resolved} exists={exists} executable={executable}")
                if not exists or not executable:
                    log(f"{missing_level}: {name} is missing or not executable.")
                    return
                try:
                    result = subprocess.run(
                        [resolved] + version_args,
                        capture_output=True,
                        text=True,
                        timeout=2,
                        stdin=subprocess.DEVNULL,
                        check=False,
                    )
                    version_line = first_non_empty_line(result.stdout) or first_non_empty_line(result.stderr) or "<no version output>"
                    log(f"{name}: version={version_line}")
                except Exception as exc:
                    log(f"{missing_level}: {name} version check failed: {exc}")
            except Exception as exc:
                log(f"{missing_level}: {name} preflight failed: {exc}")

        log("===== PREFLIGHT =====")
        try:
            check_binary("mpv", ["--version"], "ERROR")
        except Exception as exc:
            log(f"ERROR: mpv preflight failed: {exc}")
        try:
            check_binary("mplayer", ["-version"], "WARNING")
        except Exception as exc:
            log(f"WARNING: mplayer preflight failed: {exc}")
        try:
            log(f"module rtmidi: {'available' if rtmidi is not None else 'missing'}")
            log(f"module psutil: {'available' if psutil is not None else 'missing'}")
            log(f"module serial: {'available' if serial is not None else 'missing'}")
            log(f"module pynput: {'available' if pynput_keyboard is not None else 'missing'}")
        except Exception as exc:
            log(f"ERROR: module preflight failed: {exc}")
        try:
            if rtmidi is None:
                log("MIDI: unavailable (python-rtmidi not installed)")
            else:
                midi_out = rtmidi.MidiOut()
                try:
                    port_count = midi_out.get_port_count()
                    log(f"MIDI output ports: {port_count}")
                    for port_num in range(port_count):
                        try:
                            log(f"MIDI port {port_num}: {midi_out.get_port_name(port_num)}")
                        except Exception as exc:
                            log(f"WARNING: MIDI port {port_num} name unavailable: {exc}")
                finally:
                    del midi_out
        except Exception as exc:
            log(f"ERROR: MIDI preflight failed: {exc}")
        try:
            screens = QGuiApplication.screens()
            log(f"Displays: {len(screens)}")
            for idx, screen in enumerate(screens, start=1):
                geom = screen.geometry()
                log(
                    f"Display {idx}: x={geom.x()} y={geom.y()} "
                    f"w={geom.width()} h={geom.height()}"
                )
            configured_display = int(self.config.get("display", DEFAULT_VIDEO_SCREEN_NUMBER))
            if configured_display < 1 or configured_display > len(screens):
                log(
                    f"WARNING: Configured display {configured_display} is outside available screen count {len(screens)}."
                )
        except Exception as exc:
            log(f"ERROR: display preflight failed: {exc}")
        try:
            sample_socket = _make_unique_mpv_pipe_name("mpv_socket")
            socket_bytes = len(sample_socket.encode("utf-8"))
            log(f"IPC socket sample: {sample_socket} ({socket_bytes} bytes)")
            if socket_bytes > 100:
                log("ERROR: IPC socket sample exceeds 100 bytes and may fail on macOS.")
        except Exception as exc:
            log(f"ERROR: IPC socket preflight failed: {exc}")
        try:
            log(f"Accessibility trusted: {_is_accessibility_trusted()}")
        except Exception as exc:
            log(f"ERROR: accessibility preflight failed: {exc}")
        try:
            log(f"Environment: sys.executable={sys.executable}")
            log(f"Environment: sys.version={sys.version}")
            log(f"Environment: platform.mac_ver={platform.mac_ver()}")
            log(f"Environment: tempfile.gettempdir()={tempfile.gettempdir()}")
        except Exception as exc:
            log(f"ERROR: environment preflight failed: {exc}")
        log("===== END PREFLIGHT =====")

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

    def set_test_controls_enabled(self, enabled, except_port=None):
        for port_num, controls in self.midi_port_controls.items():
            disable = (not enabled) and (except_port is None or except_port != port_num)
            controls["enabled"].setEnabled(not disable)
            controls["send_start"].setEnabled(not disable)
            controls["bpm"].setEnabled(not disable)
            controls["button"].setEnabled(not disable)

    def toggle_midi_test(self, port_num):
        controls = self.midi_port_controls.get(port_num)
        if not controls:
            return
        worker = controls.get("worker")
        if worker and worker.isRunning():
            worker.stop()
            return
        worker = MidiTestWorker(port_num, controls["bpm"].value(), controls["send_start"].isChecked())
        controls["worker"] = worker
        controls["button"].setText("Stop")
        worker.status_update.connect(self.status_label.setText)
        worker.error.connect(self._on_playback_error)
        worker.finished.connect(self._on_midi_test_finished)
        self.set_test_controls_enabled(False, except_port=port_num)
        worker.start()

    def _on_midi_test_finished(self, port_num):
        controls = self.midi_port_controls.get(port_num)
        if controls:
            controls["button"].setText("Start")
            controls["worker"] = None
        self.set_test_controls_enabled(not self.is_live_mode)

    def toggle_calib_loop(self):
        if getattr(self, "calib_loop_active", False):
            self.stop_calib_loop()
        else:
            self.calib_loop_active = True
            self.calib_button.setText("Stop")
            self._start_calib_iteration()

    def _start_calib_iteration(self):
        if not getattr(self, "calib_loop_active", False) or not self.tracks:
            return
        first_track = next((t for t in self.tracks if t.get('type') == 'track'), None)
        if not first_track:
            self.stop_calib_loop()
            return
        track = dict(first_track)
        track['duration'] = min(track.get('duration', 0), self.calib_duration_spinbox.value())
        self.execute_playback(track, None)
        QTimer.singleShot(self.calib_duration_spinbox.value() * 1000 + 500, self._on_calib_iteration_finished)

    def _on_calib_iteration_finished(self):
        if getattr(self, "calib_loop_active", False):
            self.stop_all_activity()
            QTimer.singleShot(350, self._start_calib_iteration)

    def _on_calib_error(self, msg):
        self.status_label.setText(f"Calibration error: {msg}")
        self.stop_calib_loop()

    def stop_calib_loop(self):
        self.calib_loop_active = False
        self.calib_button.setText("Start")

    def trigger_sync_show(self, show_file, start_at=None, offset_sec=None):
        session = self.sync_show_session_input.text().strip() or DEFAULT_SYNC_SHOW_SESSION
        host = (self.sync_show_host_input.text().strip() or DEFAULT_SYNC_SHOW_HOST).rstrip("/")
        self.active_sync_show_session = session

        def _worker():
            try:
                query = {"session": session, "show_file": show_file}
                if start_at is not None:
                    query["start_at"] = f"{float(start_at):.6f}"
                    query["offset"] = "0"
                elif offset_sec is not None:
                    query["offset"] = f"{float(offset_sec):.6f}"
                url = f"{host}/api/start-show?{urllib.parse.urlencode(query)}"
                # Intentionally disable cert verification: operator deployments use private cert chains.
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(url, context=ctx, timeout=4) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                self._debug_log(f"sync-show start response: {body[:500]}")
            except Exception as exc:
                self._debug_log(f"sync-show start failed: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def stop_sync_show(self):
        session = self.active_sync_show_session
        if not session:
            return
        host = (self.sync_show_host_input.text().strip() or DEFAULT_SYNC_SHOW_HOST).rstrip("/")
        self.active_sync_show_session = None
        def _worker():
            try:
                url = f"{host}/api/stop-show?{urllib.parse.urlencode({'session': session})}"
                # Intentionally disable cert verification: operator deployments use private cert chains.
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                urllib.request.urlopen(url, context=ctx, timeout=4).read()
            except Exception as exc:
                self._debug_log(f"sync-show stop failed: {exc}")
        threading.Thread(target=_worker, daemon=True).start()

    def load_zoom_config(self):
        if not os.path.exists(ZOOM_CONFIG_FILE):
            return {}
        try:
            with open(ZOOM_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return _migrate_zoom_config(json.load(f))
        except Exception as exc:
            self._debug_log(f"Zoom config load failed: {exc}")
            return {}

    def save_zoom_config(self):
        try:
            with open(ZOOM_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(_migrate_zoom_config(self.zoom_config), f, indent=2)
        except Exception as exc:
            self._debug_log(f"Zoom config save failed: {exc}")

    def _update_zoom_status_label(self):
        cfg = _migrate_zoom_config(self.zoom_config)
        enabled_zones = [
            z for z in cfg.get("zones", [])
            if z.get("enabled") and z.get("crop_w", 0) > 0 and z.get("crop_h", 0) > 0
        ]
        apply_enabled = self.apply_zoom_checkbox.isChecked()
        if not enabled_zones:
            self.zoom_status_label.setText("Not configured" if not apply_enabled else "Apply enabled — not configured")
            color = "#636366" if not apply_enabled else "#ff9f0a"
            self.zoom_status_label.setStyleSheet(f"font-size: 10px; color: {color};")
            return
        if not apply_enabled:
            suffix = "s" if len(enabled_zones) != 1 else ""
            self.zoom_status_label.setText(f"Configured ({len(enabled_zones)} zone{suffix}) — Apply off")
            self.zoom_status_label.setStyleSheet("font-size: 10px; color: #636366; font-style: italic;")
            return
        direction = cfg.get("stack_direction", "horizontal")
        parts = []
        for idx, z in enumerate(enabled_zones):
            cw, ch = z.get("crop_w", 0), z.get("crop_h", 0)
            sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
            border = z.get("border_px", 0)
            offset_y = int(z.get("offset_y", 0))
            scale_txt = f"→{sw}×{sh}" if sw > 0 and sh > 0 else ""
            border_txt = f" +{border}b" if border > 0 else ""
            offset_txt = f" y{offset_y:+d}" if offset_y != 0 else ""
            parts.append(f"Z{idx + 1}:{cw}×{ch}{scale_txt}{border_txt}{offset_txt}")
        dir_sym = "↔" if direction != "vertical" else "↕"
        self.zoom_status_label.setText(f"{dir_sym} " + "  ".join(parts))
        self.zoom_status_label.setStyleSheet("font-size: 10px; color: #30d158; font-style: italic;")

    def open_zoom_dialog(self):
        try:
            output_display_num = int(self.display_combo.currentText())
        except (TypeError, ValueError):
            output_display_num = DEFAULT_VIDEO_SCREEN_NUMBER
        dialog = MultiZoomScaleDialog(self.zoom_config, output_display_num=output_display_num, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            cfg = dialog.result_config if dialog.result_config is not None else dialog.collect_config()
            self.zoom_config = _migrate_zoom_config(cfg)
            self.save_zoom_config()
            self._update_zoom_status_label()
            QMessageBox.information(
                self,
                "Restart Recommended",
                "Multi-zone zoom/scale settings were changed.\n"
                "If an external preview player is open, restart playback to apply fully."
            )

    def _connect_arduino(self):
        if serial is None or list_ports is None:
            self._debug_log("pyserial not installed; LED controller disabled.")
            return None
        try:
            for port in list_ports.comports():
                dev = getattr(port, "device", "")
                if "/dev/cu.usb" not in dev:
                    continue
                try:
                    ser = serial.Serial(dev, 9600, timeout=0.1)
                    self._debug_log(f"Arduino connected on {dev}")
                    return ser
                except Exception:
                    continue
        except Exception as exc:
            self._debug_log(f"Arduino scan failed: {exc}")
        return None

    def send_led_command(self, command):
        if not self.arduino_serial:
            return
        try:
            self.arduino_serial.write(f"{command}\n".encode("utf-8"))
        except Exception as exc:
            self._debug_log(f"LED send failed: {exc}")

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
        self.stop_sync_show()
        self.send_led_command("4")
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
            self.hotkey_listener.wait()
        self.stop_all_activity()
        self._position_poller.stop()
        self._position_poller.wait()
        try:
            if self.arduino_serial:
                self.arduino_serial.close()
        except Exception:
            pass
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
