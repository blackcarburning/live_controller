# live_controller

A live performance video/audio playback controller with setlist management, global hotkeys, count-in overlays, and session persistence.

Two scripts are provided:

| Script | Platform | Hotkey library |
|---|---|---|
| `live_fallback.py` | Windows | `keyboard` |
| `live_controller_mac.py` | macOS 12 Monterey or later, Python 3.9+ | `pynput` |

---

## macOS — `live_controller_mac.py`

### Requirements

#### System packages (via [Homebrew](https://brew.sh))

```bash
brew install mpv mplayer
```

`mpv` is the primary playback engine.  
`mplayer` is used only to read media file durations when tracks are added to the setlist. If `mplayer` is not installed, track durations will show as `00:00` but playback will still work.

#### Python packages

```bash
pip install PyQt6 pynput
```

Python 3.9 or later is recommended.

### macOS Accessibility permissions (required for global hotkeys)

`pynput` needs permission to monitor keyboard input system-wide.

1. Open **System Settings → Privacy & Security → Accessibility**.
2. Click **+** and add your terminal application (e.g. *Terminal*, *iTerm2*) or the Python binary you are using.
3. You may also need to do the same under **Input Monitoring** in the same pane.
4. Restart your terminal session after granting permissions.

Without these permissions the hotkey listener will start but key presses outside the app window will be silently ignored.

### Running

**Option 1 — double-click launcher (easiest)**

After the virtual environment is set up, double-click `run_live_controller.command` in Finder.  
macOS may ask for permission the first time; click *Open*.

**Option 2 — terminal**

```bash
cd ~/live_controller
source .venv/bin/activate
python live_controller_mac.py
```

The window opens maximized to fill the screen on launch.

### Hotkeys (in LIVE mode)

| Key | Action |
|---|---|
| `1`–`9`, `a`–`z` (excluding `q`, `t`, `i`) | Play assigned track |
| `q` | Stop all playback / abort countdown |
| `t` | Play test track |
| `^` (Shift+6) | Toggle EDIT / LIVE mode |

### macOS-specific data files

To avoid overwriting Windows session data, the Mac version uses separate file names:

| File | Purpose |
|---|---|
| `mac_fallback_config.json` | Display / preload settings |
| `mac_fallback_session.json` | Setlist and UI state |
| `mac_track_names.json` | Custom track name store |
| `setlists/` | Saved named setlists (shared with Windows) |

---

## Windows — `live_fallback.py`

### Requirements

```bash
python -m pip install PyQt6 keyboard
```

`mpv` executable at `c:\mpv\mpv.exe`  
`mplayer` executable at `d:\mplayer\mplayer.exe`

Run:

```bash
python live_fallback.py
```
