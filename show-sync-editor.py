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
import signal

PORT = 5556

_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML = os.path.join(_HERE, "show-sync-editor.html")
_INITIAL = sys.argv[1] if len(sys.argv) > 1 else None
_DEFAULT_SAVE_DIR = os.path.join(_HERE, "show-sync", "app", "static", "shows")

_RECENT_FILE = os.path.join(os.path.expanduser('~'), '.show-sync-editor-recents.json')
_RECENT_MAX = 10

import time

def _load_recents():
    try:
        with open(_RECENT_FILE, encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _write_recents(lst):
    try:
        with open(_RECENT_FILE, 'w', encoding='utf-8') as f:
            json.dump(lst, f, indent=2)
    except Exception:
        pass


def _save_recent_entry(entry):
    # Normalise entry and prepend to recents, trimming to _RECENT_MAX
    try:
        recents = _load_recents()
        # Remove any existing with same fingerprint (path or filename)
        fingerprint = entry.get('path') or entry.get('filename')
        if fingerprint:
            recents = [r for r in recents if (r.get('path') or r.get('filename')) != fingerprint]
        # Preserve last_video if provided; otherwise try to reuse existing value
        if not entry.get('last_video') and recents:
            # If the existing top entry had last_video, keep it when updating
            if recents and isinstance(recents[0], dict) and recents[0].get('last_video'):
                entry['last_video'] = recents[0].get('last_video')
        entry['timestamp'] = time.time()
        recents.insert(0, entry)
        recents = recents[:_RECENT_MAX]
        _write_recents(recents)
        return True
    except Exception:
        return False


# The server only binds to 127.0.0.1 (loopback).  Video and save endpoints
# accept user-supplied paths but restrict them to the user home directory to
# limit exposure if a malicious local page ever tried a CSRF-style request.
_HOME = os.path.realpath(os.path.expanduser("~"))

_ALLOWED_VIDEO_EXT = {
    ".mov", ".mp4", ".mkv", ".avi", ".m4v", ".webm",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
}


def _safe_video(raw: str) -> str | None:
    """Return the resolved path only if it is an allowed media file under HOME.

    Security checks applied:
      1. Reject null bytes and excessively long strings.
      2. Resolve symlinks to the real on-disk path.
      3. Require the file to be under the user's home directory.
      4. Allow only a fixed set of media extensions.
      5. Verify the path points to an existing regular file.
    """
    if not raw or "\x00" in raw or len(raw) > 4096:
        return None
    real = os.path.realpath(raw)
    # Restrict to files within the user's home directory.
    if not (real.startswith(_HOME + os.sep) or real == _HOME):
        return None
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
        elif parsed.path == "/api/recent":
            n = int(self.headers.get("Content-Length", 0))
            self._save_recent(self.rfile.read(n))
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
        recents = _load_recents()
        # If a filename was passed to the server, try to load that show.
        if _INITIAL:
            try:
                with open(_INITIAL, encoding="utf-8") as f:
                    data = json.load(f)
                self._json({"show": data, "filename": os.path.basename(_INITIAL), "path": os.path.realpath(_INITIAL), "recents": recents})
                return
            except Exception as exc:
                # Fall through and still return recents + error
                self._json({"error": str(exc), "recents": recents})
                return
        # No initial file — return the most recent autosave (if any) plus the list
        if recents:
            top = recents[0]
            self._json({
                "show": top.get('data'),
                "filename": top.get('filename'),
                "path": top.get('path'),
                "last_video": top.get('last_video', ''),
                "recents": recents,
            })
        else:
            self._json({"recents": recents})

    def _save_recent(self, body):
        # CSRF guard: only accept requests that originate from our own editor page.
        origin = self.headers.get("Origin", "")
        referer = self.headers.get("Referer", "")
        server_base = f"http://127.0.0.1:{PORT}"
        if origin and not origin.startswith(server_base):
            self.send_response(403)
            self.end_headers()
            return
        if not origin and referer and not referer.startswith(server_base):
            self.send_response(403)
            self.end_headers()
            return

        try:
            payload = json.loads(body)
            data = payload.get('data')
            filename = payload.get('filename') or payload.get('path') or ''
            path = payload.get('path', '')
            if data is None:
                raise ValueError('Missing data')
            entry = {'filename': filename, 'path': path, 'data': data}
            if payload.get('last_video'):
                entry['last_video'] = payload.get('last_video')
            ok = _save_recent_entry(entry)
            self._json({'ok': ok})
        except Exception as exc:
            self._json({'ok': False, 'error': str(exc)})

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
        mime = mimetypes.types_map.get(ext, "application/octet-stream")
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
        # CSRF guard: only accept saves that originate from our own editor page.
        origin = self.headers.get("Origin", "")
        referer = self.headers.get("Referer", "")
        server_base = f"http://127.0.0.1:{PORT}"
        if origin and not origin.startswith(server_base):
            self.send_response(403)
            self.end_headers()
            return
        if not origin and referer and not referer.startswith(server_base):
            self.send_response(403)
            self.end_headers()
            return

        try:
            payload = json.loads(body)
            path = payload.get("path", "")
            filename = payload.get("filename", "")
            data = payload.get("data")
            if data is None:
                raise ValueError("Missing data")

            # Save accepts either:
            #   - an absolute/relative path under HOME, or
            #   - a filename, which is saved into show-sync/app/static/shows.
            # The filename route is what the browser editor uses for Save As.
            if filename:
                if "\x00" in filename or len(filename) > 255:
                    raise ValueError("Invalid filename")
                filename = os.path.basename(filename.strip())
                if not filename:
                    raise ValueError("Missing filename")
                if not filename.lower().endswith(".json"):
                    filename += ".json"
                if filename in (".", "..") or os.sep in filename or (os.altsep and os.altsep in filename):
                    raise ValueError("Invalid filename")
                os.makedirs(_DEFAULT_SAVE_DIR, exist_ok=True)
                real = os.path.realpath(os.path.join(_DEFAULT_SAVE_DIR, filename))
                default_dir = os.path.realpath(_DEFAULT_SAVE_DIR)
                if not (real.startswith(default_dir + os.sep) or real == default_dir):
                    raise ValueError("Cannot save outside shows directory")
            else:
                if not path:
                    raise ValueError("Missing path or filename")
                # Validate path: null bytes, length, .json extension, home directory.
                if "\x00" in path or len(path) > 4096:
                    raise ValueError("Invalid path")
                if not path.endswith(".json"):
                    raise ValueError("Path must end with .json")
                real = os.path.realpath(path)
                if not (real.startswith(_HOME + os.sep) or real == _HOME):
                    raise ValueError("Cannot save outside of home directory")

            with open(real, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            _save_recent_entry({"filename": os.path.basename(real), "path": real, "data": data})
            self._json({"ok": True, "path": real, "filename": os.path.basename(real)})
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

        # Ensure SIGINT (Ctrl+C) and SIGTERM both cause a clean shutdown.
        def _shutdown_signal(signum, frame):
            print("\nStopping.")
            try:
                httpd.shutdown()
            except Exception:
                pass
        # Register handlers (save old ones so we can restore later if needed)
        old_sigint = signal.getsignal(signal.SIGINT)
        try:
            old_sigterm = signal.getsignal(signal.SIGTERM)
        except Exception:
            old_sigterm = None
        signal.signal(signal.SIGINT, _shutdown_signal)
        try:
            signal.signal(signal.SIGTERM, _shutdown_signal)
        except Exception:
            pass

        # Interactive command loop on stdin. This runs in the main thread
        # so Ctrl+C (SIGINT) reliably raises KeyboardInterrupt here.
        print("Type 'q' or 'quit' to stop the server. Commands: q, r (recents), o (open browser), h (help)")
        try:
            while t.is_alive():
                try:
                    cmd = input('editor> ').strip().lower()
                except EOFError:
                    # No stdin available (IDE/remote runner). Fall back to sleep loop.
                    while t.is_alive():
                        time.sleep(0.5)
                    break
                except KeyboardInterrupt:
                    print("\nStopping.")
                    try:
                        httpd.shutdown()
                    except Exception:
                        pass
                    break

                if not cmd:
                    continue
                if cmd in ('q', 'quit', 'exit'):
                    print("Stopping (user requested)")
                    try:
                        httpd.shutdown()
                    except Exception:
                        pass
                    break
                if cmd in ('o', 'open'):
                    webbrowser.open(url)
                    continue
                if cmd in ('r', 'recents'):
                    rec = _load_recents()
                    if not rec:
                        print('No recents')
                    else:
                        for i, e in enumerate(rec, 1):
                            fn = e.get('filename') or e.get('path') or '<unnamed>'
                            lv = e.get('last_video') or ''
                            ts = e.get('timestamp') and time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e.get('timestamp'))) or ''
                            print(f"{i}. {fn}  {ts}  {lv}")
                    continue
                if cmd in ('h', 'help', '?'):
                    print("Commands: q/quit, r/recents, o/open, h/help")
                    continue
                print('Unknown command: ' + cmd)
        except KeyboardInterrupt:
            # Final fallback — ensure server shuts down on Ctrl+C
            print("\nStopping.")
            try:
                httpd.shutdown()
            except Exception:
                pass
        finally:
            # restore original handlers
            try:
                signal.signal(signal.SIGINT, old_sigint)
            except Exception:
                pass
            if old_sigterm is not None:
                try:
                    signal.signal(signal.SIGTERM, old_sigterm)
                except Exception:
                    pass


if __name__ == "__main__":
    main()
