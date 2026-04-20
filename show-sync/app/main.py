from typing import Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
import json
import pathlib
import time
import uuid

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Directory where exported show JSON files are stored and served from.
SHOWS_DIR = pathlib.Path("app/static/shows")

sessions: Dict[str, Dict[str, Any]] = {}

# ── Helper: broadcast a JSON payload to all live clients in a session ─────────

async def _broadcast(session: Dict[str, Any], payload: Dict[str, Any]) -> int:
    """Send *payload* to every connected WebSocket in *session*.

    Returns the number of clients successfully reached.
    Dead connections are removed from the session.
    """
    dead: list[WebSocket] = []
    sent = 0
    for ws in session["clients"]:
        try:
            await ws.send_json(payload)
            sent += 1
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in session["clients"]:
            session["clients"].remove(ws)
    return sent


class SessionCreate(BaseModel):
    name: str


class Cue(BaseModel):
    cue_id: str
    effect: str
    server_start_time: float
    duration: Optional[float] = None
    params: Dict[str, Any] = {}

@app.get("/")
def root():
    return {"ok": True, "service": "show-sync"}


@app.post("/api/session")
def create_session(payload: SessionCreate):
    session_id = uuid.uuid4().hex[:8]
    sessions[session_id] = {
        "name": payload.name,
        "clients": [],
        "last_cue": None,
        "last_show": None,      # stores show_load payload for late-joining clients
        "last_start": None,     # stores show_start payload for late-joining clients
    }
    print(f"CREATE_SESSION {session_id}")
    return {
        "session_id": session_id,
        "join_url": f"/join/{session_id}"
    }


@app.get("/join/{session_id}", response_class=HTMLResponse)
def join_page(request: Request, session_id: str):
    if session_id not in sessions:
        sessions[session_id] = {
            "name": session_id,
            "clients": [],
            "last_cue": None,
            "last_show": None,
            "last_start": None,
        }
    return templates.TemplateResponse(
        "join.html",
        {"request": request, "session_id": session_id}
    )


@app.post("/api/session/{session_id}/cue")
async def send_cue(session_id: str, cue: Cue):
    session = sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "session_not_found"}

    payload = {
        "type": "cue",
        "cue_id": cue.cue_id,
        "effect": cue.effect,
        "server_start_time": cue.server_start_time,
        "duration": cue.duration,
        "params": cue.params,
    }

    session["last_cue"] = payload

    sent = await _broadcast(session, payload)

    print(
        f"SEND_CUE session={session_id} cue={cue.cue_id} "
        f"sent={sent} start={cue.server_start_time:.3f}"
    )

    return {"ok": True, "sent": sent}


async def _play_show_task(session_id: str, effects: list, offset: float):
    """Background task: send each show effect as a timed cue (legacy mode)."""
    show_start = time.time() + offset

    for effect in sorted(effects, key=lambda e: e.get("start", 0)):
        target = show_start + effect.get("start", 0)
        delay = target - time.time()
        if delay > 0:
            await asyncio.sleep(delay)

        session = sessions.get(session_id)
        if not session:
            break

        payload = {
            "type": "cue",
            "cue_id": effect.get("id", uuid.uuid4().hex[:8]),
            "effect": effect.get("type", "solid"),
            "server_start_time": target,
            "duration": effect.get("duration"),
            "params": effect.get("params", {}),
        }

        session["last_cue"] = payload
        await _broadcast(session, payload)


@app.post("/api/session/{session_id}/play-show")
async def play_show(
    session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    offset: float = 5.0,
):
    """Schedule all effects from a show JSON body as individual cues (legacy).

    Accepts both the v1 flat-effects format and v2 tracks format (falls back
    to flattening clips from all tracks).

    The JSON body must contain either an ``"effects"`` list (v1) or a
    ``"tracks"`` list (v2)::

        { "effects": [ {...}, ... ] }

        { "tracks": [ { "clips": [ {...}, ... ] }, ... ] }

    The optional ``offset`` query parameter controls how many seconds from now
    the show starts (default: 5).
    """
    session = sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "session_not_found"}

    body = await request.json()

    # Support both v1 (effects list) and v2 (tracks + clips)
    effects = body.get("effects")
    if effects is None:
        effects = []
        for track in body.get("tracks", []):
            effects.extend(track.get("clips", []))

    if not effects:
        return {"ok": False, "error": "no_effects"}

    background_tasks.add_task(_play_show_task, session_id, effects, offset)
    return {"ok": True, "effects": len(effects), "offset": offset}


@app.post("/api/session/{session_id}/play-timeline")
async def play_timeline(
    session_id: str,
    request: Request,
    offset: float = 5.0,
):
    """Load a v2 show and start timeline playback across all connected clients.

    Sends two messages to each client:

    1. ``show_load``  — delivers the full show JSON so clients can pre-parse it.
    2. ``show_start`` — sent *immediately after*, carries ``server_show_start_time``
       which is ``now + offset``.  Clients begin their rAF composite loop at
       that instant.

    Both messages are also stored in the session so late-joining clients
    receive them on connection.

    The show JSON body must follow the v2 format produced by the
    show-sync-editor (``tracks`` + ``clips``).
    """
    session = sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "session_not_found"}

    show = await request.json()

    tracks = show.get("tracks", [])
    if not tracks:
        return {"ok": False, "error": "no_tracks"}

    server_start = time.time() + offset

    load_payload = {"type": "show_load", "show": show}
    start_payload = {
        "type": "show_start",
        "server_show_start_time": server_start,
        "show": show,
    }

    # Persist so late-joining clients can catch up
    session["last_show"]  = load_payload
    session["last_start"] = start_payload
    session["last_cue"]   = None  # clear any legacy cue state

    # Broadcast to all currently connected clients
    sent_load  = await _broadcast(session, load_payload)
    sent_start = await _broadcast(session, start_payload)

    clip_count = sum(len(t.get("clips", [])) for t in tracks)

    print(
        f"PLAY_TIMELINE session={session_id} tracks={len(tracks)} "
        f"clips={clip_count} offset={offset:.1f}s "
        f"sent_load={sent_load} sent_start={sent_start}"
    )

    return {
        "ok": True,
        "tracks": len(tracks),
        "clips": clip_count,
        "offset": offset,
        "server_show_start_time": server_start,
    }


@app.post("/api/session/{session_id}/stop")
async def stop_show(session_id: str):
    """Stop timeline playback and clear any pending show state."""
    session = sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "session_not_found"}

    session["last_show"]  = None
    session["last_start"] = None
    session["last_cue"]   = None

    stop_payload = {"type": "show_stop"}
    sent = await _broadcast(session, stop_payload)

    print(f"STOP_SHOW session={session_id} sent={sent}")
    return {"ok": True, "sent": sent}


@app.get("/api/shows")
def list_shows():
    """List available show JSON files in the shows directory.

    Returns a JSON object with a ``shows`` key containing the sorted list of
    ``.json`` filenames that can be passed to ``play-show-by-name``.

    Example response::

        {"shows": ["A_storm_is_coming.json", "outro.json"]}
    """
    if not SHOWS_DIR.exists():
        return {"shows": []}
    shows = sorted(f.name for f in SHOWS_DIR.iterdir() if f.is_file() and f.suffix == ".json")
    return {"shows": shows}


@app.post("/api/session/{session_id}/play-show-by-name")
async def play_show_by_name(
    session_id: str,
    name: str,
    offset: float = 5.0,
):
    """Load a show from the shows directory by filename and start timeline playback.

    The ``name`` query parameter must be the bare filename (e.g.
    ``A_storm_is_coming.json``) of a JSON file present in
    ``app/static/shows/``.  Path separators and ``..`` are rejected.

    This endpoint is functionally identical to ``play-timeline`` but sources
    the show JSON from disk rather than the request body, making it easy to
    trigger a named show from an external controller (e.g. live_controller).

    Example::

        curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-show-by-name?name=A_storm_is_coming.json&offset=5"
    """
    session = sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "session_not_found"}

    # Look up the show by matching the requested name against the directory
    # listing.  The path object used for I/O comes from os.scandir (trusted),
    # not from the user-supplied string, which eliminates path-injection risk.
    show_path = None
    if SHOWS_DIR.exists():
        for entry in SHOWS_DIR.iterdir():
            if entry.is_file() and entry.suffix == ".json" and entry.name == name:
                show_path = entry
                break

    if show_path is None:
        return {"ok": False, "error": "show_not_found"}

    try:
        show = json.loads(show_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"PLAY_SHOW_BY_NAME load error: {exc}")
        return {"ok": False, "error": "show_load_failed"}

    tracks = show.get("tracks", [])
    if not tracks:
        return {"ok": False, "error": "no_tracks"}

    server_start = time.time() + offset

    load_payload = {"type": "show_load", "show": show}
    start_payload = {
        "type": "show_start",
        "server_show_start_time": server_start,
        "show": show,
    }

    session["last_show"]  = load_payload
    session["last_start"] = start_payload
    session["last_cue"]   = None

    sent_load  = await _broadcast(session, load_payload)
    sent_start = await _broadcast(session, start_payload)

    clip_count = sum(len(t.get("clips", [])) for t in tracks)

    print(
        f"PLAY_SHOW_BY_NAME session={session_id} show={name} "
        f"tracks={len(tracks)} clips={clip_count} offset={offset:.1f}s "
        f"sent_load={sent_load} sent_start={sent_start}"
    )

    return {
        "ok": True,
        "show": name,
        "tracks": len(tracks),
        "clips": clip_count,
        "offset": offset,
        "server_show_start_time": server_start,
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()

    if session_id not in sessions:
        sessions[session_id] = {
            "name": session_id,
            "clients": [],
            "last_cue": None,
            "last_show": None,
            "last_start": None,
        }

    session = sessions[session_id]
    session["clients"].append(websocket)

    # Replay the most recent state so late-joining clients catch up.
    # Priority: timeline show_start (v2) > legacy cue (v1).
    last_start = session.get("last_start")
    last_show  = session.get("last_show")
    last_cue   = session.get("last_cue")

    try:
        if last_start is not None:
            # v2 timeline mode — replay as long as the show may still be running.
            # Fall back to a 3-hour window if duration is missing or zero so
            # late-joining clients always catch up on shows without media metadata.
            show_data = last_start.get("show", {})
            dur = show_data.get("media", {}).get("duration") or 0
            if dur <= 0:
                # No media duration — compute from the latest clip end time.
                dur = max(
                    (
                        cl.get("start", 0) + cl.get("duration", 0)
                        for tr in show_data.get("tracks", [])
                        for cl in tr.get("clips", [])
                    ),
                    default=10800,  # 3 h fallback
                )
            start_t = last_start.get("server_show_start_time", 0)
            if time.time() < start_t + dur + 30:
                if last_show is not None:
                    await websocket.send_json(last_show)
                await websocket.send_json(last_start)
        elif last_cue is not None:
            # v1 legacy mode — replay if still within the cue window (2 s).
            if last_cue["server_start_time"] + 2.0 > time.time():
                await websocket.send_json(last_cue)
    except Exception:
        pass

    try:
        while True:
            msg = await websocket.receive_json()

            if msg.get("type") == "sync":
                await websocket.send_json({
                    "type": "sync_reply",
                    "t0": msg["t0"],
                    "server_time": time.time(),
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in session["clients"]:
            session["clients"].remove(websocket)
