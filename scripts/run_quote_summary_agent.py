#!/usr/bin/env python3
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_MODEL = "gpt-5.4"
DEFAULT_TIMEOUT_SECONDS = 1800
DROPBOX_OUTPUT_REMOTE_DIR = "dropbox:OpenClaw/output/UEA/Diamondback"


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def sanitize_session_id(value: str) -> str:
    cleaned = []
    for ch in value.lower():
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in {"-", "_"}:
            cleaned.append(ch)
        else:
            cleaned.append("-")
    return "".join(cleaned).strip("-")[:100] or "uea-diamondback-quote-summary"


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def extract_text_payloads(agent_result):
    payloads = agent_result.get("result", {}).get("payloads", [])
    texts = []
    for payload in payloads:
        text = payload.get("text")
        if text:
            texts.append(text)
    return texts


def build_task(input_path: Path, output_dir: Path, prompt_path: Path) -> str:
    return (
        "Automated UEA Diamondback quote-summary handoff. "
        "This is internal batch processing, not a user chat. "
        "Read the prepared input JSON from disk, then immediately spawn exactly one subagent that uses model gpt-5.4 and thinking high. "
        "The subagent must do the actual analysis work; do not keep the analysis in the parent turn. "
        "Wait for the child run to finish, verify the output files exist, and only then finish this turn.\n\n"
        f"Prepared input JSON: {input_path}\n"
        f"Prepared prompt text: {prompt_path}\n"
        f"Output directory: {output_dir}\n\n"
        "Required outputs to write or overwrite:\n"
        f"- {output_dir / 'summary.md'}\n"
        f"- {output_dir / 'summary_result.json'}\n"
        f"- {output_dir / 'summary.docx'}\n\n"
        "Rules:\n"
        "- Accuracy first. Do not guess.\n"
        "- Use only evidence from the prepared input bundle.\n"
        "- Call out uncertainty and discrepancies explicitly.\n"
        "- Keep the work limited to the UEA Diamondback batch referenced by the input JSON.\n"
        "- If blocked, say exactly what failed.\n\n"
        "Reply only with a short JSON object containing: ok, status, output_dir, and notes."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    ap.add_argument("--skip-upload", action="store_true")
    args = ap.parse_args()

    input_path = Path(args.input)
    with open(input_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    model = payload.get("model") or REQUIRED_MODEL
    if model != REQUIRED_MODEL:
        raise SystemExit(f"Expected model {REQUIRED_MODEL}, got {model}")

    output_dir = Path(payload["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = Path(payload.get("agent_prompt_path") or (output_dir / "agent_prompt.txt"))
    session_id = sanitize_session_id(f"uea-diamondback-{output_dir.name}")

    handoff_path = output_dir / "quote_summary_handoff.json"
    dispatch_log_path = output_dir / "quote_summary_dispatch.json"
    required_outputs = [
        output_dir / "summary.md",
        output_dir / "summary_result.json",
        output_dir / "summary.docx",
    ]

    handoff_state = {
        "status": "dispatching",
        "requested_at": iso_now(),
        "requested_model": REQUIRED_MODEL,
        "session_id": session_id,
        "input_json": str(input_path),
        "prompt_path": str(prompt_path),
        "output_dir": str(output_dir),
        "required_outputs": [str(path) for path in required_outputs],
    }
    write_json(handoff_path, handoff_state)

    cmd = [
        "openclaw",
        "agent",
        "--agent",
        "main",
        "--session-id",
        session_id,
        "--thinking",
        "high",
        "--timeout",
        str(args.timeout),
        "--json",
        "--message",
        build_task(input_path=input_path, output_dir=output_dir, prompt_path=prompt_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)

    agent_result = None
    parse_error = None
    if proc.stdout.strip():
        try:
            agent_result = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    dispatch_record = {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "parsed": agent_result,
        "parse_error": parse_error,
        "finished_at": iso_now(),
    }
    write_json(dispatch_log_path, dispatch_record)

    output_status = {str(path): path.exists() for path in required_outputs}
    completed = proc.returncode == 0 and all(output_status.values())

    remote_upload = None
    if completed and not args.skip_upload:
        remote_docx_name = f"{output_dir.name}.docx"
        remote_docx_path = f"{DROPBOX_OUTPUT_REMOTE_DIR}/{remote_docx_name}"
        upload_cmd = [
            "rclone",
            "copyto",
            str(output_dir / "summary.docx"),
            remote_docx_path,
        ]
        upload_proc = subprocess.run(upload_cmd, capture_output=True, text=True)
        remote_upload = {
            "command": upload_cmd,
            "returncode": upload_proc.returncode,
            "stdout": upload_proc.stdout,
            "stderr": upload_proc.stderr,
            "remote_docx_path": remote_docx_path,
        }
        if upload_proc.returncode != 0:
            completed = False
    elif completed and args.skip_upload:
        remote_upload = {
            "skipped": True,
            "reason": "--skip-upload set",
        }

    handoff_state.update({
        "status": "completed" if completed else "failed",
        "finished_at": iso_now(),
        "returncode": proc.returncode,
        "dispatch_log": str(dispatch_log_path),
        "outputs": output_status,
        "agent_reply_text": extract_text_payloads(agent_result or {}),
        "parse_error": parse_error,
        "remote_upload": remote_upload,
    })
    write_json(handoff_path, handoff_state)

    result = {
        "ok": completed,
        "status": handoff_state["status"],
        "session_id": session_id,
        "output_dir": str(output_dir),
        "handoff_path": str(handoff_path),
        "dispatch_log": str(dispatch_log_path),
        "outputs": output_status,
        "agent_reply_text": handoff_state["agent_reply_text"],
        "remote_upload": remote_upload,
    }
    print(json.dumps(result, indent=2))

    if not completed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
