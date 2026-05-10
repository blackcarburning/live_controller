#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("/root/.openclaw/workspace")
LOCAL_INBOX = Path("/root/.openclaw/dropbox/inbox/UEA/Diamondback")
SOURCE_REMOTE = "dropbox:OpenClaw/inbox/UEA/Diamondback"
OUTPUT_REMOTE = "dropbox:OpenClaw/output/UEA/Diamondback"
TEMPLATE_PATH = Path("/root/.openclaw/dropbox/inbox/SOW_Templates/CSI_SOW_ TEMPLATE 31 March 2020.docx")
STATE_MANIFESTS = WORKSPACE / "state" / "manifests"
PROCESSED_DIR = WORKSPACE / "processed"
RELEVANT_EXTS = {".xlsx", ".xls", ".pdf", ".docx", ".doc", ".csv", ".txt", ".cfg"}
EXCLUDED_NAME_PREFIXES = (
    "uea diamondback config sanity check review",
    "summary",
)
EXCLUDED_EXACT_NAMES = {
    "summary.md",
    "summary_result.json",
    "summary.docx",
    "summary_agent.docx",
    "agent_prompt.txt",
    "summary_input.json",
}


def iso_now():
    return datetime.now().astimezone().isoformat()


def run(cmd, *, check=True, cwd=None):
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def ensure_dirs():
    STATE_MANIFESTS.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def pull_dropbox(remote: str, local_dir: Path):
    local_dir.mkdir(parents=True, exist_ok=True)
    return run(
        [
            "rclone",
            "copy",
            remote,
            str(local_dir),
            "--create-empty-src-dirs",
            "--exclude",
            "old quotes - do not use/**",
        ]
    )


def is_excluded(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    if "old quotes - do not use" in lower_parts:
        return True

    lower_name = path.name.lower()
    if lower_name in EXCLUDED_EXACT_NAMES:
        return True
    if any(lower_name.startswith(prefix) for prefix in EXCLUDED_NAME_PREFIXES):
        return True
    if path.suffix.lower() not in RELEVANT_EXTS:
        return True
    return False


def discover_source_files(local_inbox: Path):
    files = []
    for path in sorted(local_inbox.rglob("*")):
        if path.is_file() and not is_excluded(path):
            files.append(path)
    return files


def write_manifest(files):
    batch_id = f"uea-diamondback-tape-analysis-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    output_dir = PROCESSED_DIR / batch_id
    manifest_path = STATE_MANIFESTS / f"{batch_id}.json"
    payload = {
        "batch_id": batch_id,
        "created_at": iso_now(),
        "files": [str(path) for path in files],
        "output_dir": str(output_dir),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return batch_id, output_dir, manifest_path


def prepare_bundle(manifest_path: Path):
    proc = run(
        [
            "python3",
            str(WORKSPACE / "scripts" / "process_quote_pack.py"),
            "--manifest",
            str(manifest_path),
            "--model",
            "gpt-5.4",
        ]
    )
    return json.loads(proc.stdout)


def write_specialized_prompt(summary_input_path: Path, prompt_path: Path, output_dir: Path):
    data = json.loads(summary_input_path.read_text(encoding="utf-8"))
    prompt = f"""You are analysing the current UEA Diamondback tape quote batch. Use the supplied extracted source data to produce an accurate commercial summary.

Requirements:
- Be careful and accuracy-first, not fast.
- This is a single-batch analysis, not a comparative review.
- Do not compare against earlier review documents or earlier versions.
- Use only the supplied extracted source data from this prepared bundle.
- Determine the most likely source-of-truth pricing file.
- Extract or infer: supplier/vendor, quote/project name, revision/date, subtotal, VAT, grand total, lead time, inclusions, exclusions, assumptions, and notable risks.
- If a value is uncertain, say so explicitly rather than guessing.
- Call out discrepancies or missing source material clearly.
- Ignore any files from folders named 'old quotes - do not use' (already filtered, but keep the rule mentally).
- Keep the work limited to the current UEA Diamondback raw quote files in this bundle.

Write three files in {output_dir}:
1. summary.md — a clean human-readable summary
2. summary_result.json — structured JSON with keys: project, vendor, quote_source, revision_or_date, subtotal, vat, total, lead_time, inclusions, exclusions, assumptions, risks, flags, source_files_used.
3. summary.docx — a basic DOCX rendering of the summary.md content if possible. The parent workflow will replace this with the final SOW-templated DOCX afterwards.

Here is the extracted source bundle JSON:
{json.dumps(data, indent=2)}
"""
    prompt_path.write_text(prompt, encoding="utf-8")


def run_agent(summary_input_path: Path, prompt_path: Path, output_dir: Path):
    task = (
        "This is internal batch processing, not a user chat. "
        f"Read the prepared input JSON from disk at {summary_input_path} and the prepared prompt text at {prompt_path}. "
        "Do the actual analysis work yourself using only evidence from that prepared input bundle. "
        f"Write or overwrite exactly these output files in {output_dir}:\n"
        f"- {output_dir / 'summary.md'}\n"
        f"- {output_dir / 'summary_result.json'}\n"
        f"- {output_dir / 'summary.docx'}\n\n"
        "Rules:\n"
        "- Accuracy first. Do not guess.\n"
        "- Use only evidence from the prepared input bundle.\n"
        "- Call out uncertainty and discrepancies explicitly.\n"
        "- Keep the work limited to the UEA Diamondback batch referenced by the input JSON.\n"
        "- If blocked, say exactly what failed.\n\n"
        "After writing the files, verify they exist before finishing. "
        "In your final reply, briefly state whether the files were written successfully and note any blocker."
    )

    proc = run(
        [
            "openclaw",
            "agent",
            "--agent",
            "main",
            "--thinking",
            "high",
            "--timeout",
            "1800",
            "--json",
            "--message",
            task,
        ]
    )
    return json.loads(proc.stdout)


def build_templated_docx(output_dir: Path, template_path: Path):
    basic_docx = output_dir / "summary.docx"
    backup_docx = output_dir / "summary_agent.docx"
    if basic_docx.exists():
        shutil.move(str(basic_docx), str(backup_docx))

    proc = run(
        [
            "python3",
            str(WORKSPACE / "scripts" / "build_sow_from_summary.py"),
            "--summary-md",
            str(output_dir / "summary.md"),
            "--summary-json",
            str(output_dir / "summary_result.json"),
            "--template",
            str(template_path),
            "--out",
            str(output_dir / "summary.docx"),
            "--project-title",
            "UEA Diamondback Tape Analysis",
        ]
    )
    return json.loads(proc.stdout)


def upload_outputs(output_dir: Path, output_remote: str):
    uploaded = []
    remote_batch_dir = f"{output_remote}/{output_dir.name}"
    for name in ["summary.docx", "summary.md", "summary_result.json", "summary_agent.docx"]:
        local_path = output_dir / name
        if not local_path.exists():
            continue
        remote_path = f"{remote_batch_dir}/{name}"
        run(["rclone", "copyto", str(local_path), remote_path])
        uploaded.append(remote_path)
    return uploaded


def verify_outputs(output_dir: Path):
    required = ["summary.md", "summary_result.json", "summary.docx"]
    status = {name: (output_dir / name).exists() for name in required}
    if not all(status.values()):
        raise RuntimeError(f"Missing required outputs: {status}")
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-inbox", default=str(LOCAL_INBOX))
    ap.add_argument("--source-remote", default=SOURCE_REMOTE)
    ap.add_argument("--output-remote", default=OUTPUT_REMOTE)
    ap.add_argument("--template", default=str(TEMPLATE_PATH))
    ap.add_argument("--skip-pull", action="store_true")
    ap.add_argument("--skip-upload", action="store_true")
    args = ap.parse_args()

    ensure_dirs()
    local_inbox = Path(args.local_inbox)
    template_path = Path(args.template)
    if not template_path.exists():
        raise SystemExit(f"Template not found: {template_path}")

    result = {
        "started_at": iso_now(),
        "pulled": None,
        "selected_files": [],
        "manifest": None,
        "output_dir": None,
        "uploads": [],
    }

    if not args.skip_pull:
        pull = pull_dropbox(args.source_remote, local_inbox)
        result["pulled"] = {
            "stdout": pull.stdout[-4000:],
            "stderr": pull.stderr[-4000:],
        }
    else:
        result["pulled"] = {"skipped": True}

    files = discover_source_files(local_inbox)
    if not files:
        raise SystemExit(f"No relevant source files found in {local_inbox}")
    result["selected_files"] = [str(path) for path in files]

    batch_id, output_dir, manifest_path = write_manifest(files)
    result["manifest"] = str(manifest_path)
    result["output_dir"] = str(output_dir)

    prep = prepare_bundle(manifest_path)
    summary_input_path = Path(prep["summary_input_json"])
    prompt_path = Path(prep["agent_prompt_path"])
    write_specialized_prompt(summary_input_path, prompt_path, output_dir)

    agent_result = run_agent(summary_input_path, prompt_path, output_dir)
    result["agent_result"] = agent_result

    sow_result = build_templated_docx(output_dir, template_path)
    result["sow_result"] = sow_result
    result["outputs"] = verify_outputs(output_dir)

    if not args.skip_upload:
        result["uploads"] = upload_outputs(output_dir, args.output_remote)
    else:
        result["uploads"] = ["skipped"]

    result["completed_at"] = iso_now()
    run_result_path = output_dir / "run_result.json"
    with open(run_result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
