#!/usr/bin/env python3
"""
show-sync-editor.py — Timeline-based show editor for show-sync.

Launches a local web editor in your default browser.

Usage
-----
    python show-sync-editor.py                # Start with a blank show
    python show-sync-editor.py myshow.json   # Open an existing show file

The editor is served at http://127.0.0.1:5556  (press Ctrl+C to quit).

What the editor does
--------------------
- Load a .mov (or any common video) as the primary reference track.
- Scrub / play the video; the timeline playhead follows along.
- Add draggable, resizable clips on two layered tracks:
    Solids track  (layer 1)  — solid-colour, fade-in, fade-out clips
    Text track    (layer 10) — text clips rendered above solids
- WYSIWYG preview pane composites the active clips at the playhead.
- Export / import the show as a JSON file ready for show-sync playback.

Show file format (v2)
---------------------
    {
        "version": 2,
        "media": { "type": "video", "src": "show.mov", "duration": 185.2 },
        "tracks": [
            {
                "id": "t1", "name": "Solids", "layer": 1,
                "clips": [
                    {
                        "id": "abc12345",
                        "type": "color",        // or fade_in / fade_out / text
                        "start":    12.2,
                        "duration":  3.5,
                        "params":   { "color": "#ff0000" },
                        "fade_in":   0.2,
                        "fade_out":  0.5
                    }
                ]
            },
            {
                "id": "t2", "name": "Text", "layer": 10,
                "clips": [
                    {
                        "id": "def67890",
                        "type": "text",
                        "start":    13.0,
                        "duration":  2.0,
                        "params":   { "text": "GO", "color": "#ffffff", "size": 5 },
                        "fade_in":   0.1,
                        "fade_out":  0.2
                    }
                ]
            }
        ]
    }

Backward compatibility
----------------------
The editor can also load legacy v1 show files (``"effects"`` list format) and
will automatically migrate them to the v2 tracks format.

Running the show
----------------
    1. Save the show file as myshow.json (use Save Show button or Ctrl+S).

    2. Start the show-sync server:
           cd show-sync
           uvicorn app.main:app --host 0.0.0.0 --port 8000

    3. Create a session:
           curl -X POST http://localhost:8000/api/session \\
                -H 'Content-Type: application/json' \\
                -d '{"name": "test"}'
       Note the returned session_id.

    4. Load the show and start playback (replace <id>):
           curl -X POST "http://localhost:8000/api/session/<id>/play-timeline?offset=5" \\
                -H 'Content-Type: application/json' \\
                -d @myshow.json

    5. Open http://localhost:8000/join/<id> on each client device.
"""

import http.server
import json
import mimetypes
import os
import socketserver
import sys
import threading
import urllib.parse
import webbrowser

PORT = 5556

_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML = os.path.join(_HERE, "show-sync-editor.html")
_INITIAL = sys.argv[1] if len(sys.argv) > 1 else None

_ALLOWED_VIDEO_EXT = {
    ".mov", ".mp4", ".mkv", ".avi", ".m4v", ".webm",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
}


def _safe_video(raw: str) -> str | None:
    """Return the resolved absolute path only if it refers to an allowed video/audio file.

    Applies multiple checks to mitigate path-traversal and injection:
      - Rejects null bytes and excessively long strings.
      - Resolves symlinks via ``os.path.realpath``.
      - Allows only a fixed set of media extensions.
      - Verifies the path points to an existing regular file.
    """
    if not raw or "\x00" in raw or len(raw) > 4096:
        return None
    real = os.path.realpath(raw)
    if os.path.splitext(real)[1].lower() not in _ALLOWED_VIDEO_EXT:
        return None
    if not os.path.isfile(real):
        return None
    return real


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self._file(_HTML, "text/html; charset=utf-8")
        elif parsed.path == "/api/initial":
            self._initial()
        elif parsed.path == "/video":
            self._video(qs.get("path", [""])[0])
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/save":
            n = int(self.headers.get("Content-Length", 0))
            self._save(self.rfile.read(n))
        else:
            self.send_response(404)
            self.end_headers()

    # ------------------------------------------------------------------ helpers

    def _file(self, path, ctype):
        try:
            data = open(path, "rb").read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(data))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _initial(self):
        if not _INITIAL:
            return self._json(None)
        try:
            with open(_INITIAL, encoding="utf-8") as f:
                data = json.load(f)
            self._json({"show": data, "filename": os.path.basename(_INITIAL)})
        except Exception as exc:
            self._json({"error": str(exc)})

    def _video(self, raw):
        if not raw:
            self.send_response(400)
            self.end_headers()
            return
        real = _safe_video(raw)
        if real is None:
            self.send_response(403)
            self.end_headers()
            return
        ext = os.path.splitext(real)[1].lower()
        mime = mimetypes.types_map.get(ext, "video/octet-stream")
        size = os.path.getsize(real)
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            parts = rng[6:].split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else size - 1
            end = min(end, size - 1)
            length = end - start + 1
            with open(real, "rb") as f:
                f.seek(start)
                chunk = f.read(length)
            self.send_response(206)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", length)
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(chunk)
        else:
            with open(real, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", size)
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(data)

    def _save(self, body):
        try:
            payload = json.loads(body)
            path = payload.get("path", "")
            data = payload.get("data")
            if not path or data is None:
                raise ValueError("Missing path or data")
            # Validate the save path before writing.
            if "\x00" in path or len(path) > 4096:
                raise ValueError("Invalid path")
            if not path.endswith(".json"):
                raise ValueError("Path must end with .json")
            # Resolve to absolute path (mitigates traversal sequences).
            real = os.path.realpath(path)
            with open(real, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._json({"ok": True, "path": real})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)})

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # suppress access log
        pass


class _ReuseAddrServer(socketserver.TCPServer):
    allow_reuse_address = True


def main():
    if _INITIAL and not os.path.isfile(_INITIAL):
        print(f"Error: file not found: {_INITIAL}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(_HTML):
        print(f"Error: show-sync-editor.html not found in {_HERE}", file=sys.stderr)
        sys.exit(1)

    with _ReuseAddrServer(("127.0.0.1", PORT), _Handler) as httpd:
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        url = f"http://127.0.0.1:{PORT}/"
        print(f"show-sync editor  →  {url}")
        if _INITIAL:
            print(f"Loading show:      {_INITIAL}")
        print("Press Ctrl+C to quit.\n")
        webbrowser.open(url)
        try:
            t.join()
        except KeyboardInterrupt:
            print("\nStopping.")
            httpd.shutdown()


if __name__ == "__main__":
    main()
