# show-sync Timeline Editor — Usage Notes

## Overview

`show-sync-editor.py` is a standalone timeline-based editor for composing
light/display shows that are played back through the **show-sync** web client.
It replaces the previous simple effect-list approach with a proper
multitrack-style editor complete with draggable clips, resize handles, a
WYSIWYG preview, and `.mov` video reference.

---

## Launching the editor

```bash
# Blank show
python show-sync-editor.py

# Open an existing show file
python show-sync-editor.py my-show.json
```

The editor starts a local HTTP server on **http://127.0.0.1:5556** and opens
your default browser automatically.  Press **Ctrl+C** in the terminal to stop
the server.

---

## Loading a .mov reference video

1. Click **Load .mov** in the toolbar, *or*
2. Drag and drop a `.mov` (or `.mp4`, `.mkv`, etc.) file onto the video player.

The video appears in the **Reference Video** panel on the right.  Its duration
is used to set the timeline length.

You can also type a filename directly into the video path field if you prefer
to use a server-side path (the `/video?path=…` endpoint serves the file with
range-request support for seeking).

---

## Transport controls

| Control | Action |
|---------|--------|
| **▶ Play / ⏸ Pause** button | Play or pause the reference video |
| **Spacebar** | Toggle play/pause (when no text field is focused) |
| Scrub bar | Drag to seek; timeline playhead follows |
| Click on the timeline ruler | Seek to that position |

---

## Creating clips

Use the **Add** buttons in the timeline toolbar to create a clip at the current
playhead position:

| Button | Clip type | Description |
|--------|-----------|-------------|
| **+ Solid** | `color` | Fills the screen with a solid colour for the duration |
| **+ Text** | `text` | Displays centred text above the colour layer |
| **+ Fade In** | `fade_in` | Fades from black into a colour over the duration |
| **+ Fade Out** | `fade_out` | Fades from a colour back to black over the duration |

Solid / fade clips go on the **Solids** track (layer 1).
Text clips go on the **Text** track (layer 10 — rendered on top).

---

## Moving and resizing clips

- **Drag the clip body** left or right to move it in time.
- **Drag the left edge handle** to change the clip's start time (and
  consequently its duration).
- **Drag the right edge handle** to change the clip's end time (duration).
- **Click a clip** to select it; selected clips are highlighted with a white
  outline.
- **Delete / Backspace** removes the selected clip.

---

## Editing clip properties

When a clip is selected, the **properties bar** at the bottom shows:

| Field | Notes |
|-------|-------|
| **Type** | Change the clip type (Solid colour / Text / Fade In / Fade Out) |
| **Start (s)** | Exact start time in seconds |
| **Duration (s)** | Length of the clip in seconds |
| **Colour** | Background / text colour (colour picker) |
| **Text** | *(text clips only)* The text string to display |
| **Size (vmin)** | *(text clips only)* Font size in `vmin` units (1–30) |
| **Fade In (s)** | Ramp-up time at the start of the clip (0 = instant) |
| **Fade Out (s)** | Ramp-down time at the end of the clip (0 = instant) |

---

## WYSIWYG preview

The **WYSIWYG Preview** pane (left panel) shows a live composite of the active
clips at the current playhead position:

- Solid colour / fade clips form the background layer.
- Text clips render on top with their configured colour and size.
- Fade in/out opacity is applied in real time as you scrub or play.

---

## Zoom

Use the **Zoom − / +** buttons in the timeline toolbar to increase or decrease
the pixels-per-second scale.  The default is 50 px/s.

---

## Exporting (saving) the show file

Click **Save Show** (or press **Ctrl+S** / **⌘S**) to download the show as a
`.json` file.

If the editor was opened with an existing file on the command line, it will
attempt to save back to that path via the server; otherwise it triggers a
browser download.

### Show file format (v2)

```json
{
  "version": 2,
  "media": {
    "type": "video",
    "src": "my-show.mov",
    "duration": 185.2
  },
  "tracks": [
    {
      "id": "t1",
      "name": "Solids",
      "layer": 1,
      "clips": [
        {
          "id": "abc12345",
          "type": "color",
          "start": 12.2,
          "duration": 3.5,
          "params": { "color": "#ff0000" },
          "fade_in": 0.2,
          "fade_out": 0.5
        }
      ]
    },
    {
      "id": "t2",
      "name": "Text",
      "layer": 10,
      "clips": [
        {
          "id": "def67890",
          "type": "text",
          "start": 13.0,
          "duration": 2.0,
          "params": { "text": "GO", "color": "#ffffff", "size": 5 },
          "fade_in": 0.1,
          "fade_out": 0.2
        }
      ]
    }
  ]
}
```

---

## Importing (loading) a show file

Click **Load Show** and choose a `.json` file.

The editor supports both:
- **v2 format** (tracks + clips, as above)
- **v1 legacy format** (flat `"effects"` list from the old Tkinter editor) —
  automatically migrated to v2 on load.

---

## Playing a show back through show-sync

### 1 — Start the show-sync server

```bash
cd show-sync
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2 — Create a session

```bash
curl -X POST http://localhost:8000/api/session \
     -H 'Content-Type: application/json' \
     -d '{"name": "my-show"}'
# → {"session_id": "a1b2c3d4", "join_url": "/join/a1b2c3d4"}
```

### 3 — Open the join URL on client devices

```
http://<server-ip>:8000/join/a1b2c3d4
```

### 4a — Timeline playback (v2, recommended)

```bash
curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-timeline?offset=5" \
     -H 'Content-Type: application/json' \
     -d @my-show.json
```

The server broadcasts `show_load` + `show_start` to all connected clients.
Each client runs its own rAF composite loop, evaluating clips at the
synchronised show time.

### 4c — Play a show by name (from the shows library)

Place exported show JSON files in `show-sync/app/static/shows/`.  They are
served statically and can be triggered by name without uploading the JSON body
on each call — ideal for scripted control from `live_controller`.

**List available shows:**

```bash
curl http://localhost:8000/api/shows
# → {"shows": ["A_storm_is_coming.json", "outro.json"]}
```

**Trigger a named show (legacy relative offset):**

```bash
curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-show-by-name?name=A_storm_is_coming.json&offset=5"
```

**Trigger a named show with absolute-time scheduling (recommended):**

Pass `start_at` as a Unix timestamp (seconds, float) for the exact wall-clock
moment when show time = 0 begins.  Both the server and all clients wait until
that instant before starting the animation loop, eliminating the network-latency
error that accumulates with a relative offset.

```bash
# start_at = Unix timestamp 2 seconds in the future
START=$(python -c "import time; print(f'{time.time()+2:.6f}')")
curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-show-by-name?name=A_storm_is_coming.json&start_at=$START"
```

`live_controller` uses this mode automatically for all sync-enabled setlist
items.  It computes `target_start = now + preload_time + 1.5 s`, sends the
request with `start_at=target_start`, and schedules the local MIDI pre-roll so
the video unpauses at the same absolute timestamp.

**Preload a show on the client via query parameter:**

Append `?show=<filename>` to the join URL.  The client fetches the show JSON
from `/static/shows/` immediately on load so it is ready before the server
sends `show_start`.

```
http://<server-ip>:8000/join/a1b2c3d4?show=A_storm_is_coming.json
```

### 4b — Legacy cue playback (v1)

```bash
curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-show?offset=5" \
     -H 'Content-Type: application/json' \
     -d @my-show.json
```

### 5 — Stop the show

```bash
curl -X POST http://localhost:8000/api/session/a1b2c3d4/stop
```

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| **Space** | Play / Pause |
| **Delete** or **Backspace** | Delete selected clip |
| **Ctrl+S** / **⌘S** | Save show |
| **Ctrl+C** / **⌘C** | Copy selected clip (text or solid) |
| **Ctrl+V** / **⌘V** | Paste copied clip at current playhead |
| **m** | Add a marker at the current playhead position |

---

## Copy / Paste clips

1. Click a **text** or **solid/colour** clip to select it.
2. Press **Ctrl+C** (or **⌘C** on Mac) to copy it.
   - The full clip is copied: type, duration, colour, text, size, fade in/out.
3. Seek or play to the position where you want the duplicate.
4. Press **Ctrl+V** (or **⌘V**) to paste.
   - A new clip is placed with its start at the **current playhead position**.
   - All other properties are identical to the original.
   - The pasted clip is automatically selected so you can adjust it immediately.

---

## Timeline markers

Press **`m`** at any time (the timeline does not need to be playing) to drop an amber
marker at the current playback position.

- Markers appear as **amber (yellow) vertical lines** on the timeline ruler and
  on every track lane.
- A small time label is drawn at the top of the ruler for each marker.
- Markers are saved with the show file (`"markers"` key in the JSON).

### Snapping clips to markers

When you **drag** a clip or **resize** it by its handles, the clip's moving edge
will **snap** to the nearest marker if it comes within ~8 px of it at the current
zoom level.

- Moving a clip: the **start edge** snaps to nearby markers.
- Resizing from the left handle: the **start** snaps.
- Resizing from the right handle: the **end** snaps.

This makes it easy to align clip boundaries to musical or visual cue points that
you marked while the show was playing.

> **Tip:** mark cue points first (let the show play, press `m`), then drag clips
> onto those positions — they will lock in cleanly.

---

## Architecture notes

- `show-sync-editor.py` — Python stdlib HTTP server (no extra dependencies).
- `show-sync-editor.html` — Self-contained browser editor (HTML + CSS + JS).
- `show-sync/app/main.py` — FastAPI server; new `/play-timeline` and `/stop`
  endpoints added alongside the existing `/play-show` legacy endpoint.
- `show-sync/app/static/client.js` — Updated to handle `show_load`,
  `show_start`, `show_stop` messages in addition to the legacy `cue` protocol.
- `show-sync/app/templates/join.html` — Text overlay moved to its own `z-index`
  layer above the colour display; font size is now dynamic per clip.
