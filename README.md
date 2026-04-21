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

---

## show-sync — Load Testing

`show-sync/load_test.py` is a standalone Python utility that simulates many
phone-like WebSocket clients connecting to the show-sync listener endpoint.
Use it to verify that the server handles audience-scale load before a live event.

### Install the extra dependency

```bash
pip install -r show-sync/load-test-requirements.txt
# or just:
pip install websockets
```

### Quick start

```bash
# From the repository root:
python show-sync/load_test.py --help

# 100 clients, 10 s ramp, hold 30 s (default session "load-test")
python show-sync/load_test.py --clients 100 --ramp 10 --hold 30
```

### CLI reference

| Flag | Default | Description |
|---|---|---|
| `--url URL` | `wss://localhost-0.tailc4daa4.ts.net/ws/` | Base WebSocket URL (session ID is appended) |
| `--session ID` | `load-test` | Session ID to use |
| `--clients N` | `100` | Number of simulated clients (up to 2000+) |
| `--ramp SECONDS` | `10` | Spread window — clients connect evenly over this period |
| `--hold SECONDS` | `30` | How long each client stays connected after handshake |
| `--no-verify` | off | Disable TLS certificate verification (self-signed / local certs) |

### Example commands

**500 clients over 30 seconds** (recommended for pre-show warmup testing):

```bash
python show-sync/load_test.py \
    --url wss://localhost-0.tailc4daa4.ts.net/ws/ \
    --session a1b2c3d4 \
    --clients 500 \
    --ramp 30 \
    --hold 120
```

**2000 clients over 60 seconds** (full audience simulation):

```bash
python show-sync/load_test.py \
    --url wss://localhost-0.tailc4daa4.ts.net/ws/ \
    --session a1b2c3d4 \
    --clients 2000 \
    --ramp 60 \
    --hold 120 \
    --no-verify
```

**Local development** (plain `ws://`, no TLS):

```bash
# Start show-sync first:  cd show-sync && uvicorn app.main:app --reload
python show-sync/load_test.py \
    --url ws://localhost:8000/ws/ \
    --session load-test \
    --clients 200 \
    --ramp 15 \
    --hold 60
```

### Sample output

```
Target URL : wss://localhost-0.tailc4daa4.ts.net/ws/load-test
TLS verify : disabled

Starting load test: 2000 clients | ramp 60s | hold 120s | url=wss://…/ws/load-test
----------------------------------------------------------------------
[12:00:05] attempted=167/2000 connected=164 active=164 failed=3 lat avg=42.1ms p50=38.6ms p95=91.3ms
[12:00:10] attempted=333/2000 connected=329 active=329 failed=4 lat avg=43.5ms p50=39.2ms p95=95.1ms
…
----------------------------------------------------------------------
Load test complete.
  Clients attempted : 2000
  Connected         : 1987
  Failed            : 13
  Success rate      : 99.4%
  Latency (connect) : avg=44.2ms p50=40.1ms p95=97.8ms p99=143.2ms
  Sample errors (13):
    client-42: ConnectionRefusedError: …
```

### Notes and limitations

- **OS file-descriptor limit** — each WebSocket uses a file descriptor.
  On Linux/macOS `load_test.py` automatically raises `RLIMIT_NOFILE` up to the
  system hard limit.  For 2000 clients you may still need
  `ulimit -n 4096` in your shell before running.
- **Windows** — the fd-limit adjustment is skipped automatically; set
  `HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\MaxUserPort` if you
  hit connection failures at high counts.
- **Local machine** — running 2000 async connections from a laptop is feasible
  with asyncio, but the machine's CPU/memory and the loopback stack will become
  the bottleneck before the server does.  For a realistic server stress test,
  run `load_test.py` from a separate machine or a cloud VM.
- The tool does **not** disrupt existing sessions — it connects to whichever
  session ID you specify (default `load-test`) and only reads messages; it never
  sends cues or modifies server state.
