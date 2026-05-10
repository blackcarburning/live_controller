#!/usr/bin/env python3
import argparse
import json
import time
import hashlib
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

INBOX = Path("/root/.openclaw/dropbox/inbox/UEA/Diamondback")
DROPBOX_REMOTE = "dropbox:OpenClaw/inbox/UEA/Diamondback"
WORKSPACE = Path("/root/.openclaw/workspace")
STATE_DIR = WORKSPACE / "state"
STATE_FILE = STATE_DIR / "quote_watcher_state.json"
MANIFEST_DIR = STATE_DIR / "manifests"
PROCESSED_DIR = WORKSPACE / "processed"

QUIET_PERIOD_SECONDS = 300
POLL_INTERVAL_SECONDS = 30
PULL_INTERVAL_SECONDS = 120
RELEVANT_EXTS = {".xlsx", ".xls", ".pdf", ".docx", ".doc", ".csv", ".txt", ".cfg", ".cfr", ".xml"}
IGNORE_NAME = "old quotes - do not use"
IGNORED_OUTPUT_PREFIXES = ("uea diamondback config sanity check review",)


def now_ts() -> int:
    return int(time.time())


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def ensure_dirs():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def load_state():
    if not STATE_FILE.exists():
        return {
            "known_files": {},
            "pending_files": [],
            "last_new_file_at": None,
            "processing": False,
            "last_batch_id": None,
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp.replace(STATE_FILE)


def is_ignored(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if IGNORE_NAME in parts:
        return True

    name = path.name.lower()
    if name.endswith((".docx", ".md", ".json")) and any(name.startswith(prefix) for prefix in IGNORED_OUTPUT_PREFIXES):
        return True

    return False


def is_within_inbox(path: Path) -> bool:
    try:
        path.resolve().relative_to(INBOX.resolve())
        return True
    except (FileNotFoundError, RuntimeError, ValueError):
        return False


def is_relevant(path: Path) -> bool:
    return (
        path.is_file()
        and is_within_inbox(path)
        and path.suffix.lower() in RELEVANT_EXTS
        and not is_ignored(path)
    )


def file_fingerprint(path: Path):
    st = path.stat()
    raw = f"{path}:{st.st_size}:{int(st.st_mtime)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def scan_inbox():
    if not INBOX.exists():
        return []
    files = []
    for path in INBOX.rglob("*"):
        try:
            if is_relevant(path):
                files.append(path)
        except FileNotFoundError:
            continue
    return sorted(files)


def pull_remote_inbox():
    cmd = [
        "rclone",
        "copy",
        DROPBOX_REMOTE,
        str(INBOX),
        "--create-empty-src-dirs",
        "--exclude",
        "old quotes - do not use/**",
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def discover_new_files(files, known_files):
    new_files = []
    updated_known = dict(known_files)
    for path in files:
        fp = file_fingerprint(path)
        key = str(path)
        if updated_known.get(key) != fp:
            new_files.append(path)
            updated_known[key] = fp
    existing_paths = {str(p) for p in files}
    updated_known = {k: v for k, v in updated_known.items() if k in existing_paths}
    return new_files, updated_known


def dedupe_keep_order(items):
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def infer_batch_name(paths):
    names = [Path(p).stem for p in paths]
    if not names:
        return "quote-batch"
    base = names[0].lower().replace(" ", "-")
    return base[:80]


def write_manifest(pending_files):
    batch_name = infer_batch_name(pending_files)
    batch_id = f"{batch_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    manifest_path = MANIFEST_DIR / f"{batch_id}.json"
    payload = {
        "batch_id": batch_id,
        "created_at": iso_now(),
        "files": pending_files,
        "output_dir": str(PROCESSED_DIR / batch_id),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return batch_id, manifest_path


def run_processor(manifest_path: Path):
    prep_cmd = [
        "python3",
        "/root/.openclaw/workspace/scripts/process_quote_pack.py",
        "--manifest",
        str(manifest_path),
        "--model",
        "gpt-5.4",
    ]
    prep = subprocess.run(prep_cmd, capture_output=True, text=True)
    if prep.returncode != 0:
        return prep

    try:
        prep_payload = json.loads(prep.stdout)
    except Exception:
        return prep

    handoff_cmd = [
        sys.executable,
        "/root/.openclaw/workspace/scripts/run_quote_summary_agent.py",
        "--input",
        prep_payload["summary_input_json"],
    ]
    handoff = subprocess.run(handoff_cmd, capture_output=True, text=True)
    combined = {
        "prep": prep.stdout,
        "agent": handoff.stdout,
        "agent_stderr": handoff.stderr,
    }
    return subprocess.CompletedProcess(
        args=handoff_cmd,
        returncode=handoff.returncode,
        stdout=json.dumps(combined),
        stderr=prep.stderr + handoff.stderr,
    )


def run_cycle(state):
    if now_ts() - int(state.get("last_pull_at") or 0) >= PULL_INTERVAL_SECONDS:
        pull = pull_remote_inbox()
        state["last_pull_at"] = now_ts()
        state["last_pull"] = {
            "returncode": pull.returncode,
            "stdout": pull.stdout[-4000:],
            "stderr": pull.stderr[-4000:],
            "finished_at": iso_now(),
        }
        save_state(state)

    files = scan_inbox()
    new_files, known_files = discover_new_files(files, state.get("known_files", {}))
    state["known_files"] = known_files

    if new_files:
        pending = state.get("pending_files", [])
        pending.extend(str(p) for p in new_files)
        state["pending_files"] = dedupe_keep_order(pending)
        state["last_new_file_at"] = now_ts()

    pending_files = state.get("pending_files", [])
    last_new_file_at = state.get("last_new_file_at")
    processing = state.get("processing", False)

    if pending_files and last_new_file_at and not processing:
        quiet_for = now_ts() - last_new_file_at
        if quiet_for >= QUIET_PERIOD_SECONDS:
            state["processing"] = True
            save_state(state)

            batch_id, manifest_path = write_manifest(pending_files)
            result = run_processor(manifest_path)

            state["last_batch_id"] = batch_id
            state["last_result"] = {
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
                "manifest": str(manifest_path),
                "finished_at": iso_now(),
            }
            state["pending_files"] = []
            state["last_new_file_at"] = None
            state["processing"] = False

    save_state(state)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Run one watcher cycle and exit")
    args = ap.parse_args()

    ensure_dirs()
    state = load_state()
    while True:
        try:
            run_cycle(state)
        except Exception as e:
            state["last_error"] = {
                "message": str(e),
                "at": iso_now(),
            }
            state["processing"] = False
            save_state(state)

        if args.once:
            break

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
