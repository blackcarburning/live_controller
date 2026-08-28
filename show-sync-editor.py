#!/usr/bin/env python3
"""
show-sync-editor.py — Timeline-based show editor for show-sync.

Launches a local web editor in your default browser.

Usage
-----
    python show-sync-editor.py                # Start with a blank show
    python show-sync-editor.py myshow.json   # Open an existing show file

The editor is served at http://127.0.0.1:5556 (or the next free port up to
5565). Press Ctrl+C to quit.

What the editor does
--------------------
- Load a .mov (or any common video) as the primary reference track.
- Scrub / play the video; the timeline playhead follows along.
- Add draggable, resizable clips on layered tracks.
- WYSIWYG preview pane composites the active clips at the playhead.
- Export / import the show as a JSON file ready for show-sync playback.

Show file format (v3)
---------------------
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
                "clips": [ ... ]
            }
        ],
        "markers": [ { "id": "abc", "time": 12.5 } ]
    }

Backward compatibility
----------------------
The editor can also load legacy v1 show files (``"effects"`` list format) and
v2 show files. Missing v3 fields are added automatically during load.
"""

from __future__ import annotations

import errno
import http.server
import json
import mimetypes
import os
from pathlib import Path
import signal
import socketserver
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser

PORT_MIN = 5556
PORT_MAX = 5565
CHUNK_SIZE = 1024 * 1024

_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML = os.path.join(_HERE, "show-sync-editor.html")
_INITIAL = sys.argv[1] if len(sys.argv) > 1 else None
_DEFAULT_SAVE_DIR = os.path.join(_HERE, "show-sync", "app", "static", "shows")

_RECENT_FILE = os.path.join(os.path.expanduser("~"), ".show-sync-editor-recents.json")
_RECENT_MAX = 10
_SERVER_PORT = PORT_MIN

_HOME = os.path.realpath(os.path.expanduser("~"))
_ALLOWED_VIDEO_EXT = {
    ".mov", ".mp4", ".mkv", ".avi", ".m4v", ".webm",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
}
_MEDIA_MIME_OVERRIDES = {
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".m4v": "video/x-m4v",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/x-msvideo", ".avi")
mimetypes.add_type("video/quicktime", ".mov")


def _json_clone(value):
    return json.loads(json.dumps(value))


def _blank_show_v3() -> dict:
    return {
        "version": 3,
        "bpm": 120,
        "fps": 30,
        "in_point": None,
        "out_point": None,
        "media": {
            "type": "video",
            "src": "",
            "path": "",
            "duration": 0,
            "size": None,
            "mtime": None,
        },
        "tracks": [
            {"id": "t1", "name": "Solids", "layer": 1, "muted": False, "solo": False, "locked": False, "clips": []},
            {"id": "t2", "name": "Text", "layer": 10, "muted": False, "solo": False, "locked": False, "clips": []},
        ],
        "markers": [],
    }


def _is_absoluteish(path: str) -> bool:
    if not isinstance(path, str):
        return False
    path = path.strip()
    if not path:
        return False
    return os.path.isabs(path) or (len(path) > 2 and path[1] == ":" and path[2] in ("/", "\\"))


def _media_path_from_data(data) -> str:
    if not isinstance(data, dict):
        return ""
    media = data.get("media")
    if isinstance(media, dict):
        path = str(media.get("path") or "").strip()
        if path:
            return path
    return str(data.get("last_video") or "").strip()


def _migrate_v1_to_v3(data: dict) -> dict:
    solids = []
    texts = []
    for eff in (data.get("effects") or []):
        if not isinstance(eff, dict):
            continue
        clip = {
            "id": eff.get("id") or f"clip-{uuid.uuid4().hex[:8]}",
            "type": "color" if eff.get("type") == "solid" else eff.get("type"),
            "start": eff.get("start", 0),
            "duration": eff.get("duration", 1),
            "params": {"color": "#ff0000", **(eff.get("params") or {})},
            "fade_in": eff.get("fade_in", 0),
            "fade_out": eff.get("fade_out", 0),
        }
        if eff.get("type") == "text":
            texts.append(clip)
        else:
            solids.append(clip)

    show = _blank_show_v3()
    show["media"]["src"] = data.get("video") or data.get("song") or ""
    show["media"]["duration"] = data.get("duration") or 0
    show["tracks"][0]["clips"] = solids
    show["tracks"][1]["clips"] = texts
    return show


def _ensure_v3_defaults(data: dict, preferred_last_video: str = "") -> dict:
    show = _blank_show_v3()
    if isinstance(data, dict):
        show.update({k: v for k, v in data.items() if k not in {"media", "tracks", "markers"}})

    media = data.get("media") if isinstance(data, dict) and isinstance(data.get("media"), dict) else {}
    merged_media = dict(show["media"])
    merged_media.update(media)
    show["media"] = merged_media

    tracks = []
    for idx, track in enumerate((data.get("tracks") if isinstance(data, dict) else []) or []):
        if not isinstance(track, dict):
            continue
        merged_track = {
            "id": track.get("id") or f"t{idx + 1}",
            "name": track.get("name") or f"Track {idx + 1}",
            "layer": track.get("layer", idx + 1),
            "muted": bool(track.get("muted", False)),
            "solo": bool(track.get("solo", False)),
            "locked": bool(track.get("locked", False)),
            "clips": track.get("clips") if isinstance(track.get("clips"), list) else [],
        }
        tracks.append(merged_track)
    show["tracks"] = tracks or show["tracks"]
    show["markers"] = data.get("markers") if isinstance(data, dict) and isinstance(data.get("markers"), list) else []

    show["version"] = 3
    show["bpm"] = show.get("bpm") or 120
    show["fps"] = int(show.get("fps") or 30)
    show["in_point"] = show.get("in_point", None)
    show["out_point"] = show.get("out_point", None)

    media_path = str(show["media"].get("path") or "").strip()
    if not media_path:
        fallback = str(preferred_last_video or data.get("last_video") or "").strip() if isinstance(data, dict) else ""
        if not fallback:
            src = str(show["media"].get("src") or "").strip()
            if _is_absoluteish(src):
                fallback = src
        if fallback:
            show["media"]["path"] = fallback
            media_path = fallback

    if not show["media"].get("src") and media_path:
        show["media"]["src"] = os.path.basename(media_path)

    if media_path:
        try:
            real = _validate_media_path(media_path)
        except Exception:
            real = None
        if real:
            show["media"]["path"] = real
            if show["media"].get("size") is None:
                show["media"]["size"] = os.path.getsize(real)
            if show["media"].get("mtime") is None:
                show["media"]["mtime"] = os.path.getmtime(real)

    return show


def _migrate_show_data(data, preferred_last_video: str = "") -> dict:
    if isinstance(data, dict) and isinstance(data.get("effects"), list):
        return _ensure_v3_defaults(_migrate_v1_to_v3(data), preferred_last_video)
    if isinstance(data, dict) and isinstance(data.get("tracks"), list):
        return _ensure_v3_defaults(data, preferred_last_video)
    raise ValueError('Unrecognised show file format (missing "tracks" or "effects" key).')


def _load_recents():
    try:
        with open(_RECENT_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _write_recents(lst):
    try:
        with open(_RECENT_FILE, "w", encoding="utf-8") as f:
            json.dump(lst, f, indent=2)
    except Exception:
        pass


def _save_recent_entry(entry):
    try:
        entry = dict(entry or {})
        data = entry.get("data")
        if entry.get("path"):
            entry["path"] = os.path.realpath(entry["path"])
        if not entry.get("filename") and entry.get("path"):
            entry["filename"] = os.path.basename(entry["path"])

        last_video = str(entry.get("last_video") or _media_path_from_data(data) or "").strip()
        if last_video:
            entry["last_video"] = last_video

        recents = _load_recents()
        entry_path = entry.get("path")
        entry_real = os.path.realpath(entry_path) if entry_path else ""
        fingerprint = entry.get("filename") or entry_path or ""

        filtered = []
        for recent in recents:
            recent_path = recent.get("path")
            if entry_real and recent_path:
                try:
                    if os.path.realpath(recent_path) == entry_real:
                        continue
                except Exception:
                    pass
            elif fingerprint and (recent.get("filename") or recent.get("path")) == fingerprint:
                continue
            filtered.append(recent)

        now = time.time()
        entry["timestamp"] = now
        entry["updated_at"] = now
        filtered.insert(0, entry)
        _write_recents(filtered[:_RECENT_MAX])
        return True
    except Exception:
        return False


def _annotate_recents(recents):
    out = []
    for recent in recents:
        item = dict(recent)
        path = item.get("path")
        item["missing"] = bool(path and not os.path.isfile(path))
        out.append(item)
    return out


def _validate_media_path(raw: str, require_exists: bool = True) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Missing path")
    if "\x00" in raw or len(raw) > 4096:
        raise ValueError("Invalid path")
    real = os.path.realpath(raw)
    if not (real.startswith(_HOME + os.sep) or real == _HOME):
        raise ValueError("Path must be inside home directory")
    ext = os.path.splitext(real)[1].lower()
    if ext not in _ALLOWED_VIDEO_EXT:
        raise ValueError("Unsupported media extension")
    if require_exists:
        if not os.path.exists(real):
            raise FileNotFoundError("File not found")
        if not os.path.isfile(real):
            raise ValueError("Path is not a regular file")
    return real


def _safe_video(raw: str, require_exists: bool = True) -> str | None:
    try:
        return _validate_media_path(raw, require_exists=require_exists)
    except Exception:
        return None


def _media_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return _MEDIA_MIME_OVERRIDES.get(ext, "application/octet-stream")


def _parse_range_header(header: str, size: int):
    if not header or not header.startswith("bytes="):
        return None
    spec = header[6:].strip()
    if not spec or "," in spec:
        raise ValueError("Invalid Range")
    start_s, sep, end_s = spec.partition("-")
    if not sep:
        raise ValueError("Invalid Range")

    if start_s == "":
        suffix = int(end_s)
        if suffix <= 0:
            raise ValueError("Invalid Range")
        if suffix >= size:
            return 0, size - 1
        return size - suffix, size - 1

    start = int(start_s)
    if start >= size:
        raise IndexError("Range start beyond end")
    if end_s == "":
        return start, size - 1

    end = int(end_s)
    if end < start:
        raise ValueError("Invalid Range")
    return start, min(end, size - 1)


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self._file(_HTML, "text/html; charset=utf-8")
        elif parsed.path == "/api/initial":
            self._initial()
        elif parsed.path == "/api/media/check":
            self._media_check(qs.get("path", [""])[0])
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

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _server_base(self):
        return f"http://127.0.0.1:{_SERVER_PORT}"

    def _guard_post_origin(self):
        origin = self.headers.get("Origin", "")
        referer = self.headers.get("Referer", "")
        server_base = self._server_base()
        if origin and not origin.startswith(server_base):
            self.send_response(403)
            self.end_headers()
            return False
        if not origin and referer and not referer.startswith(server_base):
            self.send_response(403)
            self.end_headers()
            return False
        return True

    def _initial(self):
        recents = _annotate_recents(_load_recents())
        if _INITIAL:
            try:
                with open(_INITIAL, encoding="utf-8") as f:
                    raw = json.load(f)
                show = _migrate_show_data(raw, _media_path_from_data(raw))
                self._json({
                    "show": show,
                    "filename": os.path.basename(_INITIAL),
                    "path": os.path.realpath(_INITIAL),
                    "last_video": show.get("media", {}).get("path") or raw.get("last_video", ""),
                    "recents": recents,
                })
                return
            except Exception as exc:
                self._json({"error": str(exc), "recents": recents})
                return

        if recents:
            top = recents[0]
            show_data = top.get("data")
            migrated = None
            if isinstance(show_data, dict):
                try:
                    migrated = _migrate_show_data(show_data, top.get("last_video", ""))
                except Exception:
                    migrated = None
            self._json({
                "show": migrated,
                "filename": top.get("filename"),
                "path": top.get("path"),
                "last_video": top.get("last_video", "") or _media_path_from_data(show_data),
                "recents": recents,
            })
            return

        self._json({"recents": recents})

    def _media_check(self, raw):
        try:
            real = _validate_media_path(raw, require_exists=False)
        except Exception as exc:
            self._json({"ok": False, "exists": False, "size": None, "mtime": None, "error": str(exc)})
            return

        exists = os.path.isfile(real)
        if not exists:
            self._json({"ok": True, "exists": False, "size": None, "mtime": None, "error": None})
            return

        self._json({
            "ok": True,
            "exists": True,
            "size": os.path.getsize(real),
            "mtime": os.path.getmtime(real),
            "error": None,
        })

    def _save_recent(self, body):
        if not self._guard_post_origin():
            return
        try:
            payload = json.loads(body)
            data = payload.get("data")
            filename = payload.get("filename") or payload.get("path") or ""
            path = payload.get("path", "")
            if data is None:
                raise ValueError("Missing data")
            last_video = payload.get("last_video") or (_media_path_from_data(data) if isinstance(data, dict) else "")
            entry = {"filename": filename, "path": path, "data": data, "last_video": last_video}
            ok = _save_recent_entry(entry)
            self._json({"ok": ok})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)})

    def _stream_file(self, path: str, start: int = 0, end: int | None = None):
        with Path(path).open("rb") as f:
            f.seek(start)
            remaining = None if end is None else (end - start + 1)
            while True:
                to_read = CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
                if to_read <= 0:
                    break
                chunk = f.read(to_read)
                if not chunk:
                    break
                self.wfile.write(chunk)
                if remaining is not None:
                    remaining -= len(chunk)

    def _video(self, raw):
        if not raw:
            self.send_response(400)
            self.end_headers()
            return
        try:
            real = _validate_media_path(raw, require_exists=True)
        except Exception:
            self.send_response(403)
            self.end_headers()
            return

        size = os.path.getsize(real)
        mime = _media_mime(real)
        rng = self.headers.get("Range", "")

        if rng.startswith("bytes="):
            try:
                start, end = _parse_range_header(rng, size)
            except IndexError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return
            except Exception:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return

            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self._stream_file(real, start, end)
            return

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._stream_file(real)

    def _save(self, body):
        if not self._guard_post_origin():
            return

        try:
            payload = json.loads(body)
            path = payload.get("path", "")
            filename = payload.get("filename", "")
            data = payload.get("data")
            if data is None:
                raise ValueError("Missing data")

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
                if "\x00" in path or len(path) > 4096:
                    raise ValueError("Invalid path")
                if not path.endswith(".json"):
                    raise ValueError("Path must end with .json")
                real = os.path.realpath(path)
                if not (real.startswith(_HOME + os.sep) or real == _HOME):
                    raise ValueError("Cannot save outside of home directory")

            with open(real, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            last_video = payload.get("last_video") or (_media_path_from_data(data) if isinstance(data, dict) else "")
            _save_recent_entry({
                "filename": os.path.basename(real),
                "path": real,
                "data": data,
                "last_video": last_video,
            })
            self._json({"ok": True, "path": real, "filename": os.path.basename(real)})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)})

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_server():
    global _SERVER_PORT
    last_error = None
    for port in range(PORT_MIN, PORT_MAX + 1):
        try:
            httpd = _ThreadingHTTPServer(("127.0.0.1", port), _Handler)
            _SERVER_PORT = port
            return httpd, port
        except OSError as exc:
            last_error = exc
            if exc.errno != errno.EADDRINUSE:
                raise
    raise OSError(f"No free port found in range {PORT_MIN}-{PORT_MAX}") from last_error


def main():
    if _INITIAL and not os.path.isfile(_INITIAL):
        print(f"Error: file not found: {_INITIAL}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(_HTML):
        print(f"Error: show-sync-editor.html not found in {_HERE}", file=sys.stderr)
        sys.exit(1)

    httpd, port = _make_server()
    with httpd:
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        url = f"http://127.0.0.1:{port}/"
        print(f"show-sync editor  →  {url}")
        if _INITIAL:
            print(f"Loading show:      {_INITIAL}")
        print("Press Ctrl+C to quit.\n")
        webbrowser.open(url)

        def _shutdown_signal(signum, frame):
            print("\nStopping.")
            try:
                httpd.shutdown()
            except Exception:
                pass

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

        print("Type 'q' or 'quit' to stop the server. Commands: q, r (recents), o (open browser), h (help)")
        try:
            while t.is_alive():
                try:
                    cmd = input("editor> ").strip().lower()
                except EOFError:
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
                if cmd in ("q", "quit", "exit"):
                    print("Stopping (user requested)")
                    try:
                        httpd.shutdown()
                    except Exception:
                        pass
                    break
                if cmd in ("o", "open"):
                    webbrowser.open(url)
                    continue
                if cmd in ("r", "recents"):
                    rec = _load_recents()
                    if not rec:
                        print("No recents")
                    else:
                        for i, e in enumerate(rec, 1):
                            fn = e.get("filename") or e.get("path") or "<unnamed>"
                            lv = e.get("last_video") or ""
                            ts_val = e.get("updated_at") or e.get("timestamp")
                            ts = ts_val and time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_val)) or ""
                            print(f"{i}. {fn}  {ts}  {lv}")
                    continue
                if cmd in ("h", "help", "?"):
                    print("Commands: q/quit, r/recents, o/open, h/help")
                    continue
                print("Unknown command: " + cmd)
        except KeyboardInterrupt:
            print("\nStopping.")
            try:
                httpd.shutdown()
            except Exception:
                pass
        finally:
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
