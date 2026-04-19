from typing import Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
import time
import uuid

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

sessions: Dict[str, Dict[str, Any]] = {}


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

    dead = []
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

    print(
        f"SEND_CUE session={session_id} cue={cue.cue_id} "
        f"sent={sent} dead={len(dead)} start={cue.server_start_time:.3f}"
    )

    return {"ok": True, "sent": sent}


async def _play_show_task(session_id: str, effects: list, offset: float):
    """Background task: send each show effect as a timed cue."""
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

        dead = []
        for ws in session["clients"]:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            if ws in session["clients"]:
                session["clients"].remove(ws)


@app.post("/api/session/{session_id}/play-show")
async def play_show(
    session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    offset: float = 5.0,
):
    """Schedule all effects from a show JSON body as cues.

    The JSON body must match the format produced by show-sync.py::

        {
          "effects": [
            {"id": "...", "type": "solid", "start": 0.0,
             "duration": 2.0, "params": {"color": "#ff0000"}},
            ...
          ]
        }

    The optional ``offset`` query parameter controls how many seconds from now
    the show starts (default: 5).
    """
    session = sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "session_not_found"}

    body = await request.json()
    effects = body.get("effects", [])

    if not effects:
        return {"ok": False, "error": "no_effects"}

    background_tasks.add_task(_play_show_task, session_id, effects, offset)
    return {"ok": True, "effects": len(effects), "offset": offset}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()

    if session_id not in sessions:
        sessions[session_id] = {
            "name": session_id,
            "clients": [],
            "last_cue": None,
        }

    session = sessions[session_id]
    session["clients"].append(websocket)

    # Replay the most recent cue if it is still relevant (within 2 s of start).
    last_cue = session.get("last_cue")
    if last_cue is not None:
        if last_cue["server_start_time"] + 2.0 > time.time():
            try:
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
