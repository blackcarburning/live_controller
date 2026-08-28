# show-sync Timeline Editor

A browser-based timeline editor for authoring show-sync effect sequences, served by a local Python HTTP server.

## Quick Start

```bash
python show-sync-editor.py              # blank show
python show-sync-editor.py myshow.json  # open existing show
```

The editor opens at `http://127.0.0.1:5556` (or next available port up to 5565).  
Press `Ctrl+C` or type `q` at the `editor>` prompt to quit.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `J` | Shuttle reverse (0 → −0.25× → −0.5× → −1× → −2× → −4×) |
| `K` | Stop shuttle |
| `L` | Shuttle forward (0 → 0.25× → 0.5× → 1× → 2× → 4×) |
| `←` / `→` | Step one frame back/forward |
| `Shift+←` / `Shift+→` | Step 1 second back/forward |
| `Home` | Go to in-point (or start) |
| `End` | Go to out-point (or end) |
| `[` or `i` | Set in-point at playhead |
| `]` or `o` | Set out-point at playhead |
| `m` | Add marker at playhead |
| `Delete` / `Backspace` | Delete selected clip or marker |
| `Ctrl+C` | Copy selected clip |
| `Ctrl+V` | Paste clip at playhead |
| `Ctrl+D` | Duplicate selected clip |
| `S` | Split selected clip at playhead |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` | Redo |
| `Ctrl+S` | Save show |

## Media (.mov) Reference

The editor loads a reference `.mov` (or other video) and keeps track of its absolute filesystem path so the video is **automatically restored** on next launch.

### How it works

1. **Drag & drop** a `.mov` onto the video panel, or click **Load .mov** (file picker), or type/paste an absolute path in the path field and press **Load Path**.
2. The path is stored in `show.media.path` and in the recents entry (`last_video`).
3. On startup, the server returns `last_video` for the most recent show; the editor auto-loads the video.
4. If the file is missing, a red banner appears: **"Reference video not found: /path/to/x.mov — Relocate…"**  
   Click **Relocate** to enter the new path.
5. If the file's size or modification time changed since last save, the video label shows a ⚠ warning (timings may be off).

### Security

The `/video?path=` and `/api/media/check?path=` endpoints only serve files that are:
- Inside the user's home directory (`~`)  
- A recognised media extension (`.mov .mp4 .mkv .avi .m4v .webm .mp3 .wav .flac .aac .ogg .m4a`)
- A regular file (not a symlink pointing outside home)

## Show File Format (v3)

```json
{
  "version": 3,
  "bpm": 120,
  "fps": 30,
  "in_point": null,
  "out_point": null,
  "media": {
    "type": "video",
    "src": "show.mov",
    "path": "/Users/you/Videos/show.mov",
    "duration": 185.2,
    "size": 1234567890,
    "mtime": 1717000000.0
  },
  "tracks": [
    {
      "id": "t1", "name": "Solids", "layer": 1,
      "muted": false, "solo": false, "locked": false,
      "clips": [ … ]
    }
  ],
  "markers": [ { "id": "abc", "time": 12.5 } ]
}
```

### Migration

| Version | Change |
|---------|--------|
| v1 | `effects` list → v3 tracks (auto-migrated on load) |
| v2 | Missing `fps`, `in_point`, `out_point`, `media.path` → defaults added on load |

## Waveform Display

When a video is loaded via the path endpoint, the editor attempts to decode up to 10 MB of audio using the Web Audio API and render a waveform under the video player. This is **non-blocking** — if decoding fails (large file, no audio, codec not supported), it is silently skipped.

## Recents

Recents are stored in `~/.show-sync-editor-recents.json`. The Load Recent dialog shows missing projects with a "Missing" badge. Each entry stores:
- `filename`, `path` — show file location
- `last_video` — absolute path of the reference video
- `updated_at` — Unix timestamp of last save
