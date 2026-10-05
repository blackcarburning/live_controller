#!/usr/bin/env python3
import base64
import hashlib
import hmac
import html
import json
import logging
import math
import mimetypes
import os
import pathlib
import random
import re
import secrets
import socket
import subprocess
import sys
import time
import traceback
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO, StringIO
from urllib.parse import parse_qs, quote, unquote, urlparse

import numpy as np
import paramiko
from scipy import signal
from scipy.io import wavfile


ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_PORT = 8765
AUTH_CONFIG_PATH = ROOT / "data" / "auth.json"
AUTH_COOKIE_NAME = "fs7300_documenter_session"
AUTH_COOKIE_MAX_AGE = 30 * 24 * 60 * 60
AUTH_ITERATIONS = 260_000
PROTECTED_ROUTES = [
    {"base": "/homepage", "root": ROOT, "documenter_api": False, "homepage": True},
    {"base": "/storwize-documentation", "root": ROOT, "documenter_api": True},
    {"base": "/llm-workplace", "root": pathlib.Path("/usr/share/caddy/llm-workplace"), "documenter_api": False},
    {"base": "/cohesity-architect-expert-trainer", "root": pathlib.Path("/root/.openclaw/workspace/cohesity-architect-expert-trainer"), "documenter_api": False},
    {"base": "/pdf-to-markup-converter", "root": pathlib.Path("/root/.openclaw/workspace/pdf-to-markup-converter"), "documenter_api": False},
    {"base": "/user-manual-parser", "root": pathlib.Path("/root/.openclaw/workspace/user-manual-parser"), "documenter_api": False},
    {"base": "/timesheet-tracker", "root": pathlib.Path("/root/.openclaw/workspace/timesheet-tracker"), "documenter_api": False},
    {"base": "/schematic-creator", "root": pathlib.Path("/root/.openclaw/workspace/schematic-creator"), "documenter_api": False},
    {"base": "/spectrum-log-error-finder", "root": pathlib.Path("/root/.openclaw/workspace/spectrum-log-error-finder"), "documenter_api": False},
    {"base": "/brocade-zoning-planner", "root": pathlib.Path("/root/.openclaw/workspace/SANTool"), "documenter_api": False},
    {"base": "/ibm-lin-tape-configuration", "root": pathlib.Path("/root/.openclaw/workspace/ibm-lin-tape-configuration"), "documenter_api": False},
    {"base": "/storage-protect-documentation", "root": pathlib.Path("/root/.openclaw/workspace/plugins/storage-protect-docs/public"), "documenter_api": False},
    {"base": "/veeam-storage-tools", "root": pathlib.Path("/root/.openclaw/workspace/VeeamStorageTools"), "documenter_api": False},
    {"base": "/storage-protect-redbull", "root": pathlib.Path("/root/.openclaw/workspace/storage-protect-redbull"), "documenter_api": False},
    {"base": "/unison-veeam", "root": pathlib.Path("/usr/share/caddy/unison-veeam"), "documenter_api": False},
    {"base": "/kingston-university-veeam", "root": pathlib.Path("/usr/share/caddy/kingston-university-veeam"), "documenter_api": False},
    {"base": "/customer-chat", "root": pathlib.Path("/root/.openclaw/workspace/customer-chat"), "documenter_api": False},
    {"base": "/mygrain-wavs", "root": pathlib.Path("/srv/sftp/mark_sftp/files/mygrain-loops"), "documenter_api": False, "public": True},
]

FETCH_GROUPS = [
    {
        "id": "system",
        "commands": ["lssystem -delim :", "lssystemip -delim :", "lssystemlimits -delim :", "lssystemcapacity -delim :", "lssecurity -delim :", "showtimezone", "lslicense -delim :"],
    },
    {
        "id": "hardware",
        "commands": ["lsnode -delim :", "lsnodecanister -delim :", "lsenclosure -delim :", "lsarray -delim :", "lsdrive -delim :", "lsdriveclass -delim :"],
    },
    {
        "id": "capacity",
        "commands": ["lsmdiskgrp -delim :", "lsmdiskgrp -bytes -delim :", "lspoolcapacity -delim :", "lsmdisk -delim :", "lsdependentvdisks -delim :"],
    },
    {
        "id": "volumes",
        "commands": ["lsvdisk -delim :", "lsvdisk -bytes -delim :", "lsvdiskcopy -delim :", "lsvolumegroup -delim :", "lsvdiskhostmap -delim :", "lshostvdiskmap -delim :", "lssnapshot -delim :", "lssnapshotpolicy -delim :", "lsfcmap -delim :"],
    },
    {
        "id": "partitions",
        "commands": ["lspartition -delim :", "lspartitioncandidate -delim :"],
    },
    {
        "id": "hosts",
        "commands": ["lshost -delim :", "lshostcluster -delim :", "lshostport -delim :", "lshostvdiskmap -delim :"],
    },
    {
        "id": "iscsi",
        "commands": ["lsportip -delim :", "lsroute -delim :", "lsportset -delim :", "lsiscsiauth -delim :", "lsiscsiportauth -delim :", "lsiscsistorageport -delim :"],
    },
    {
        "id": "nvme",
        "commands": ["lsnvmefabric -delim :", "lsnvmehost -delim :", "lsnvmeport -delim :"],
    },
    {
        "id": "fc",
        "commands": ["lsportfc -delim :", "lstargetportfc -delim :", "lsfabric -delim :", "lsfabricport -delim :", "lsfcportcandidate -delim :"],
    },
    {
        "id": "remote_copy",
        "commands": ["lspartnership -delim :", "lspartnershipcandidate -delim :", "lsrcrelationship -delim :", "lsrcconsistgrp -delim :", "ls3sitercrelationship -delim :", "ls3sitercconsistgrp -delim :"],
    },
    {
        "id": "policy_replication",
        "commands": ["lsreplicationpolicy -delim :", "lspartnership -delim :", "lspartition -delim :", "lsvolumegroup -delim :", "lssnapshotpolicy -delim :"],
    },
    {
        "id": "security_support",
        "commands": ["lsencryption -delim :", "lsencryptionkey -delim :", "lskeyserver -delim :", "lssystemcert -delim :", "lstruststore -delim :", "lscert -delim :", "lsuser -delim :", "lsusergrp -delim :", "lsauthservice -delim :", "lsldap -delim :", "lssra -delim :", "lsemailserver -delim :", "lssmtpserver -delim :", "lscloudcallhome -delim :", "lseventlog -alert yes -delim :", "lserrorlog -delim :", "lsauditlog -delim :"],
    },
]

ALLOWED_COMMANDS = {command for group in FETCH_GROUPS for command in group["commands"]}
HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
TEST_COMMAND = "lssystem -delim :"
MYGRAIN_WAVS_ROUTE = "/mygrain-wavs"
MYGRAIN_WAVS_ROOT = pathlib.Path("/srv/sftp/mark_sftp/files/mygrain-loops")
MYGRAIN_WAVS_MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MYGRAIN_BASTARDLOOP_REMOTE = "dropbox:SAMPLEDROP"
MYGRAIN_BASTARDLOOP_STEPS = 16
MYGRAIN_BASTARDLOOP_TARGET_SAMPLE_RATE = 44100
MYGRAIN_BASTARDLOOP_LIST_CACHE_SECONDS = 180
MYGRAIN_BASTARDLOOP_MIN_BPM = 40
MYGRAIN_BASTARDLOOP_MAX_BPM = 300
MYGRAIN_BASTARDLOOP_SAMPLE_CACHE = {
    "expires_at": 0.0,
    "files": [],
}
CUSTOMER_CHAT_STORE_PATH = ROOT / "data" / "customer_chat.json"
CUSTOMER_CHAT_LOCK = threading.RLock()
CUSTOMER_CHAT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CUSTOMER_CHAT_LLM_MODEL = "openai/gpt-5.4-mini"
CUSTOMER_CHAT_REPLY_FALLBACK = "I could not generate a reply right now. Please try again."
CUSTOMER_CHAT_CONTEXT_LIMIT = 20
UNISON_CUSTOMER_CONFIG_PATH = pathlib.Path("/etc/openclaw/mail-monitor/customers.json")
UNISON_MONITOR_STATE_PATH = pathlib.Path("/var/lib/openclaw-mail/unison-monitor-state.json")
CUSTOMER_CHAT_LEGACY_SLUG_ALIASES = {
    "kingston": "kingston-university",
}
CUSTOMER_CHAT_DEFAULT_CUSTOMERS = [
    {
        "slug": "unison",
        "name": "Unison",
        "status": "Monitoring queue",
        "summary": "Daily offload reports and collector health.",
        "tone": "Operational",
        "llm_model": "openai/gpt-5.4-mini",
        "analysis_type": "veeam",
        "notes_file": "/root/.openclaw/workspace/memory/customer-notes/unison.md",
        "state_file": str(UNISON_MONITOR_STATE_PATH),
    },
    {
        "slug": "kingston-university",
        "name": "Kingston University",
        "status": "Waiting on review",
        "summary": "Customer-facing dashboard and report checks.",
        "tone": "Customer review",
        "llm_model": "openai/gpt-5.4-mini",
        "analysis_type": "veeam",
        "state_file": "/var/lib/openclaw-mail/kingston-university-monitor-state.json",
    },
]


def mygrain_wavs_cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Filename",
        "Access-Control-Max-Age": "86400",
    }


def ensure_mygrain_wavs_root():
    MYGRAIN_WAVS_ROOT.mkdir(parents=True, exist_ok=True)


def sanitize_mygrain_wav_filename(value):
    fallback = "mygrain-loop.wav"
    raw = str(value or "").strip()
    if not raw:
        return fallback
    segment = raw.replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", segment).strip("._-")
    if not cleaned:
        return fallback
    if not cleaned.lower().endswith(".wav"):
        cleaned += ".wav"
    return cleaned


def unique_mygrain_wav_filename(filename):
    ensure_mygrain_wavs_root()
    candidate = MYGRAIN_WAVS_ROOT / filename
    if not candidate.exists():
        return filename
    stem = candidate.stem
    suffix = candidate.suffix or ".wav"
    for index in range(1, 1000):
        next_name = f"{stem}-{index}{suffix}"
        if not (MYGRAIN_WAVS_ROOT / next_name).exists():
            return next_name
    raise RuntimeError("Could not allocate a unique WAV filename.")


def list_mygrain_wav_files():
    ensure_mygrain_wavs_root()
    files = []
    for path in sorted(
        (item for item in MYGRAIN_WAVS_ROOT.iterdir() if item.is_file() and item.suffix.lower() == ".wav"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        stat = path.stat()
        files.append({
            "name": path.name,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "url": f"{MYGRAIN_WAVS_ROUTE}/{quote(path.name)}",
        })
    return files


def list_bastardloop_source_files(force_refresh=False):
    now = time.time()
    cached_files = MYGRAIN_BASTARDLOOP_SAMPLE_CACHE.get("files") or []
    if (
        not force_refresh
        and cached_files
        and MYGRAIN_BASTARDLOOP_SAMPLE_CACHE.get("expires_at", 0) > now
    ):
        return list(cached_files)

    result = subprocess.run(
        [
            "rclone",
            "lsf",
            MYGRAIN_BASTARDLOOP_REMOTE,
            "--files-only",
            "--recursive",
            "--include",
            "*.wav",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not files:
        raise RuntimeError("No WAV files were found in Dropbox SAMPLEDROP.")

    MYGRAIN_BASTARDLOOP_SAMPLE_CACHE["files"] = files
    MYGRAIN_BASTARDLOOP_SAMPLE_CACHE["expires_at"] = now + MYGRAIN_BASTARDLOOP_LIST_CACHE_SECONDS
    return list(files)


def fetch_bastardloop_sample_bytes(relative_path):
    safe_relative_path = str(relative_path or "").replace("\\", "/").lstrip("/")
    if not safe_relative_path:
        raise ValueError("Missing SAMPLEDROP file path.")

    remote_path = f"{MYGRAIN_BASTARDLOOP_REMOTE.rstrip('/')}/{safe_relative_path}"
    result = subprocess.run(
        ["rclone", "cat", remote_path],
        check=True,
        capture_output=True,
    )
    if not result.stdout:
        raise RuntimeError(f"Downloaded sample was empty: {safe_relative_path}")
    return result.stdout


def clamp_bastardloop_bpm(value, fallback=120):
    try:
        bpm = float(value)
    except (TypeError, ValueError):
        bpm = float(fallback)
    bpm = max(MYGRAIN_BASTARDLOOP_MIN_BPM, min(MYGRAIN_BASTARDLOOP_MAX_BPM, bpm))
    return int(round(bpm))


def audio_samples_to_float32(data):
    samples = np.asarray(data)
    if samples.ndim == 1:
        samples = samples[:, np.newaxis]
    elif samples.ndim > 2:
        samples = samples.reshape(samples.shape[0], -1)

    if np.issubdtype(samples.dtype, np.floating):
        return np.clip(samples.astype(np.float32), -1.0, 1.0)

    if not np.issubdtype(samples.dtype, np.integer):
        raise ValueError(f"Unsupported WAV sample type: {samples.dtype}")

    if samples.dtype == np.uint8:
        return ((samples.astype(np.float32) - 128.0) / 128.0).clip(-1.0, 1.0)

    info = np.iinfo(samples.dtype)
    if samples.dtype == np.int32:
        max_abs = int(np.max(np.abs(samples.astype(np.int64)))) if samples.size else 0
        scale = float(0x800000 if max_abs <= 0x7FFFFF else max(abs(info.min), info.max))
    else:
        scale = float(max(abs(info.min), info.max))
    return np.clip(samples.astype(np.float32) / scale, -1.0, 1.0)


def resample_audio_channels(samples, source_rate, target_rate):
    if source_rate == target_rate or samples.shape[0] == 0:
        return samples.astype(np.float32, copy=False)

    gcd = math.gcd(int(source_rate), int(target_rate))
    up = int(target_rate // gcd)
    down = int(source_rate // gcd)
    return signal.resample_poly(samples, up, down, axis=0).astype(np.float32, copy=False)


def ensure_stereo(samples):
    if samples.ndim != 2:
        raise ValueError("Expected 2D audio array after decoding.")
    if samples.shape[1] == 1:
        return np.repeat(samples, 2, axis=1)
    if samples.shape[1] >= 2:
        return samples[:, :2]
    return np.zeros((0, 2), dtype=np.float32)


def resize_audio_linear(samples, target_frames):
    target_frames = int(target_frames)
    if target_frames <= 0:
        raise ValueError("Target frame count must be positive.")
    if samples.shape[0] == target_frames:
        return samples.astype(np.float32, copy=False)
    if samples.shape[0] == 0:
        return np.zeros((target_frames, samples.shape[1]), dtype=np.float32)
    if samples.shape[0] == 1:
        return np.repeat(samples.astype(np.float32, copy=False), target_frames, axis=0)

    source_positions = np.arange(samples.shape[0], dtype=np.float32)
    target_positions = np.linspace(0, samples.shape[0] - 1, target_frames, dtype=np.float32)
    resized = np.empty((target_frames, samples.shape[1]), dtype=np.float32)
    for channel_index in range(samples.shape[1]):
        resized[:, channel_index] = np.interp(target_positions, source_positions, samples[:, channel_index]).astype(np.float32)
    return resized


def choose_bastardloop_segment(samples, sample_rate, step_frames, rng, step_index):
    total_frames = int(samples.shape[0])
    if total_frames <= 0:
        raise ValueError("Sample had no audio frames.")

    min_source_frames = max(int(sample_rate * 0.045), int(step_frames * 0.55))
    max_source_frames = min(total_frames, max(min_source_frames, int(step_frames * 2.25)))
    if max_source_frames <= 0:
        raise ValueError("Could not allocate source frames for the sample.")

    if max_source_frames == min_source_frames:
        source_frames = max_source_frames
    else:
        source_frames = rng.randint(min_source_frames, max_source_frames)

    if total_frames <= source_frames:
        start_frame = 0
    else:
        best_score = None
        best_start = 0
        for _ in range(7):
            candidate_start = rng.randint(0, total_frames - source_frames)
            window = samples[candidate_start:candidate_start + source_frames]
            rms = float(np.sqrt(np.mean(np.square(window), dtype=np.float64))) if window.size else 0.0
            transient = float(np.max(np.abs(window))) if window.size else 0.0
            score = (rms * 0.82) + (transient * 0.18) + (rng.random() * 0.025)
            if best_score is None or score > best_score:
                best_score = score
                best_start = candidate_start
        start_frame = best_start

    segment = samples[start_frame:start_frame + source_frames].copy()
    reversed_segment = False
    if rng.random() < 0.2:
        segment = np.flip(segment, axis=0).copy()
        reversed_segment = True

    segment = resize_audio_linear(segment, step_frames)

    if rng.random() < 0.22 and segment.shape[0] > 8:
        contour = np.linspace(0.4, 1.0, segment.shape[0], dtype=np.float32)
        if step_index % 2:
            contour = contour[::-1]
        segment *= contour[:, np.newaxis]

    pan = rng.uniform(-0.72, 0.72)
    left_gain = math.cos((pan + 1.0) * math.pi / 4.0)
    right_gain = math.sin((pan + 1.0) * math.pi / 4.0)
    accent = 1.08 if step_index % 4 == 0 else (0.76 + rng.random() * 0.28)
    segment[:, 0] *= left_gain * accent
    segment[:, 1] *= right_gain * accent

    fade_frames = min(segment.shape[0] // 2, max(24, int(sample_rate * 0.0065)))
    if fade_frames > 1:
        fade = np.linspace(0.0, 1.0, fade_frames, dtype=np.float32)
        segment[:fade_frames] *= fade[:, np.newaxis]
        segment[-fade_frames:] *= fade[::-1][:, np.newaxis]

    return segment, {
        "start_frame": start_frame,
        "source_frames": source_frames,
        "reversed": reversed_segment,
    }


def generate_bastardloop_file(bpm, seed=None):
    ensure_mygrain_wavs_root()
    bpm_value = clamp_bastardloop_bpm(bpm)
    resolved_seed = str(seed or secrets.token_hex(8))
    rng = random.Random(resolved_seed)
    available_files = list_bastardloop_source_files()
    if not available_files:
        raise RuntimeError("SAMPLEDROP is empty.")

    target_step_seconds = (60.0 / bpm_value) / 4.0
    target_step_frames = max(1, int(round(target_step_seconds * MYGRAIN_BASTARDLOOP_TARGET_SAMPLE_RATE)))
    total_frames = target_step_frames * MYGRAIN_BASTARDLOOP_STEPS
    output = np.zeros((total_frames, 2), dtype=np.float32)
    selected_files = []

    pool = available_files[:]
    rng.shuffle(pool)
    attempts = 0
    max_attempts = max(MYGRAIN_BASTARDLOOP_STEPS * 4, len(available_files) * 2)

    while len(selected_files) < MYGRAIN_BASTARDLOOP_STEPS and attempts < max_attempts:
        relative_path = pool.pop() if pool else rng.choice(available_files)
        attempts += 1
        try:
            payload = fetch_bastardloop_sample_bytes(relative_path)
            source_rate, raw_data = wavfile.read(BytesIO(payload))
            samples = audio_samples_to_float32(raw_data)
            samples = resample_audio_channels(samples, int(source_rate), MYGRAIN_BASTARDLOOP_TARGET_SAMPLE_RATE)
            samples = ensure_stereo(samples)
            segment, _ = choose_bastardloop_segment(samples, MYGRAIN_BASTARDLOOP_TARGET_SAMPLE_RATE, target_step_frames, rng, len(selected_files))
        except Exception:
            continue

        step_index = len(selected_files)
        frame_start = step_index * target_step_frames
        frame_end = frame_start + target_step_frames
        output[frame_start:frame_end] += segment[:target_step_frames]
        selected_files.append(relative_path)

    if len(selected_files) != MYGRAIN_BASTARDLOOP_STEPS:
        raise RuntimeError("Could not build a full 16-step bastardloop from SAMPLEDROP.")

    output -= np.mean(output, axis=0, keepdims=True)
    peak = float(np.max(np.abs(output))) if output.size else 0.0
    if peak > 0:
        output *= min(0.94 / peak, 6.0)
    pcm = np.int16(np.clip(output, -1.0, 1.0) * 32767.0)

    filename = unique_mygrain_wav_filename(
        sanitize_mygrain_wav_filename(f"bastardloop-{bpm_value}bpm-{int(time.time())}.wav")
    )
    target_path = MYGRAIN_WAVS_ROOT / filename
    wavfile.write(target_path, MYGRAIN_BASTARDLOOP_TARGET_SAMPLE_RATE, pcm)

    duration_seconds = total_frames / MYGRAIN_BASTARDLOOP_TARGET_SAMPLE_RATE
    sample_names = [pathlib.PurePosixPath(path).name for path in selected_files]
    return {
        "ok": True,
        "savedName": filename,
        "size": target_path.stat().st_size,
        "url": f"{MYGRAIN_WAVS_ROUTE}/{quote(filename)}",
        "bpm": bpm_value,
        "seed": resolved_seed,
        "stepCount": MYGRAIN_BASTARDLOOP_STEPS,
        "durationSeconds": duration_seconds,
        "sampleRate": MYGRAIN_BASTARDLOOP_TARGET_SAMPLE_RATE,
        "sampleNames": sample_names,
        "summary": f"{duration_seconds:.2f}s · {MYGRAIN_BASTARDLOOP_STEPS} cuts",
    }


def b64url(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def customer_chat_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def customer_chat_message(message_id, role, text, created_at=None):
    return {
        "id": message_id,
        "role": role,
        "text": text,
        "created_at": created_at or customer_chat_now(),
    }


def customer_chat_config_root():
    try:
        raw = UNISON_CUSTOMER_CONFIG_PATH.read_text(encoding="utf-8")
    except Exception:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def customer_chat_config_customers():
    root = customer_chat_config_root()
    customers = root.get("customers")
    if isinstance(customers, dict):
        values = customers.values()
    elif isinstance(customers, list):
        values = customers
    else:
        values = []

    veeam_customers = []
    for customer in values:
        if not isinstance(customer, dict):
            continue
        if str(customer.get("analysis_type") or "").strip().lower() != "veeam":
            continue
        slug = str(customer.get("slug") or "").strip()
        if not slug:
            continue
        veeam_customers.append(
            {
                "slug": slug,
                "name": str(customer.get("name") or slug.replace("-", " ").title()).strip(),
                "status": str(customer.get("status") or "Monitoring queue").strip(),
                "summary": str(customer.get("context_prompt") or customer.get("summary") or "Veeam customer monitoring thread.").strip(),
                "tone": str(customer.get("tone") or "Operational").strip(),
                "llm_model": str(customer.get("llm_model") or customer.get("model") or CUSTOMER_CHAT_LLM_MODEL).strip() or CUSTOMER_CHAT_LLM_MODEL,
                "analysis_type": "veeam",
                "notes_file": str(customer.get("notes_file") or "").strip(),
                "state_file": str(customer.get("state_file") or "").strip(),
            }
        )

    if veeam_customers:
        return veeam_customers

    return [dict(customer) for customer in CUSTOMER_CHAT_DEFAULT_CUSTOMERS]


def customer_chat_canonical_slug(slug):
    slug = str(slug or "").strip()
    if not slug:
        return ""
    return CUSTOMER_CHAT_LEGACY_SLUG_ALIASES.get(slug, slug)


def customer_chat_customer_catalog():
    return {customer["slug"]: dict(customer) for customer in customer_chat_config_customers()}


def customer_chat_customer_profile(customer):
    slug = customer_chat_canonical_slug(customer.get("slug"))
    if not slug:
        return dict(customer) if isinstance(customer, dict) else {}
    profile = customer_chat_customer_catalog().get(slug)
    if profile:
        return profile
    return dict(customer) if isinstance(customer, dict) else {}


def customer_chat_seed():
    customers = customer_chat_customer_catalog()
    return {
        "version": 1,
        "customers": [customers[slug] for slug in sorted(customers)],
        "threads": {
            "unison": [
                customer_chat_message("seed-unison-1", "assistant", "Unison thread loaded. This is where the customer-scoped conversation will live.", "2026-07-18T00:00:00Z"),
                customer_chat_message("seed-unison-2", "me", "Start with the latest report and keep this thread separate from Kingston.", "2026-07-18T00:00:00Z"),
            ],
            "kingston-university": [
                customer_chat_message("seed-kingston-1", "assistant", "Kingston thread loaded. Separate history, separate state.", "2026-07-18T00:00:00Z"),
            ],
        },
    }


def normalize_customer_chat_store(data):
    if not isinstance(data, dict):
        return customer_chat_seed()
    customer_catalog = customer_chat_customer_catalog()
    customer_map = {slug: dict(customer) for slug, customer in customer_catalog.items()}

    customers = data.get("customers")
    if not isinstance(customers, list):
        customers = []
    for customer in customers:
        if not isinstance(customer, dict):
            continue
        slug = customer_chat_canonical_slug(customer.get("slug"))
        if not CUSTOMER_CHAT_SLUG_RE.match(slug):
            continue
        catalog_customer = customer_catalog.get(slug)
        if not catalog_customer:
            continue
        normalized_customer = dict(catalog_customer)
        for key in ("name", "status", "summary", "tone", "llm_model", "analysis_type", "notes_file", "state_file"):
            value = str(customer.get(key) or "").strip()
            if value and not normalized_customer.get(key):
                normalized_customer[key] = value
        customer_map[slug] = normalized_customer

    threads = data.get("threads")
    if not isinstance(threads, dict):
        threads = {}
    normalized_threads = {}
    for slug, messages in threads.items():
        slug = customer_chat_canonical_slug(slug)
        if not CUSTOMER_CHAT_SLUG_RE.match(slug):
            continue
        if slug not in customer_catalog:
            continue
        if not isinstance(messages, list):
            continue
        normalized_messages = []
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            text = str(message.get("text") or "").strip()
            if not text:
                continue
            role = str(message.get("role") or "assistant")
            if role not in ("assistant", "me", "system"):
                role = "assistant"
            normalized_messages.append(
                customer_chat_message(
                    str(message.get("id") or f"{slug}-{index + 1}"),
                    role,
                    text,
                    str(message.get("created_at") or customer_chat_now()),
                )
            )
        normalized_threads[slug] = normalized_messages

    for customer in customer_map.values():
        normalized_threads.setdefault(customer["slug"], [])

    return {
        "version": 1,
        "customers": [customer_map[slug] for slug in sorted(customer_map)],
        "threads": normalized_threads,
    }


def load_customer_chat_store():
    with CUSTOMER_CHAT_LOCK:
        try:
            raw = CUSTOMER_CHAT_STORE_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            store = customer_chat_seed()
            save_customer_chat_store(store)
            return store
        except Exception:
            return customer_chat_seed()
        try:
            store = normalize_customer_chat_store(json.loads(raw))
        except Exception:
            store = customer_chat_seed()
        save_customer_chat_store(store)
        return store


def save_customer_chat_store(store):
    with CUSTOMER_CHAT_LOCK:
        CUSTOMER_CHAT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(normalize_customer_chat_store(store), indent=2, sort_keys=True)
        tmp_path = CUSTOMER_CHAT_STORE_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(CUSTOMER_CHAT_STORE_PATH)


def customer_chat_customer_map(store):
    return {customer["slug"]: customer for customer in store["customers"]}


def customer_chat_list_payload(store):
    customer_map = customer_chat_customer_map(store)
    customers = []
    for customer in store["customers"]:
        slug = customer["slug"]
        messages = store["threads"].get(slug, [])
        customers.append(
            {
                **customer,
                "message_count": len(messages),
                "last_message_at": messages[-1]["created_at"] if messages else None,
            }
        )
    return {"ok": True, "customers": customers}


def customer_chat_customer_payload(store, slug):
    customer = customer_chat_customer_map(store).get(slug)
    if not customer:
        return None
    messages = store["threads"].get(slug, [])
    context = customer_chat_context_bundle(customer)
    return {
        "ok": True,
        "customer": {
            **customer,
            "message_count": len(messages),
            "last_message_at": messages[-1]["created_at"] if messages else None,
        },
        "messages": messages,
        "context": context,
    }


def customer_chat_append_message(store, slug, text):
    with CUSTOMER_CHAT_LOCK:
        customer = customer_chat_customer_map(store).get(slug)
        if not customer:
            return None
        message = customer_chat_message(f"{slug}-{int(time.time() * 1000)}-{secrets.token_hex(3)}", "me", text)
        store["threads"].setdefault(slug, []).append(message)
        save_customer_chat_store(store)
        return customer_chat_customer_payload(store, slug)


def customer_chat_thread_lines(messages):
    lines = []
    for message in messages[-CUSTOMER_CHAT_CONTEXT_LIMIT:]:
        role = str(message.get("role") or "assistant")
        label = {
            "me": "User",
            "assistant": "Assistant",
            "system": "System",
        }.get(role, "Assistant")
        text = str(message.get("text") or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    return lines


def customer_chat_clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def customer_chat_notes_summary(notes_text, limit=18):
    notes_lines = []
    for raw_line in str(notes_text or "").splitlines():
        line = customer_chat_clean_text(raw_line)
        if not line:
            continue
        if line.startswith("## Imported notes"):
            break
        if line.startswith("# ") and not notes_lines:
            continue
        notes_lines.append(line)
        if len(notes_lines) >= limit:
            break
    return notes_lines


def customer_chat_repository_summary(state):
    repositories = (state.get("defined_repositories") or {}).get("repositories_by_name") or {}
    perf_names = [
        "Perf_VMware_Repos",
        "Perf_SQL_Repos",
        "Perf_Agent_Repos",
        "Perf_Exchange_Repos",
        "Perf_Config_Repos",
        "Perf_Fileshare_Repos",
    ]
    repo_lines = []
    for name in perf_names:
        repo = repositories.get(name) or {}
        total = customer_chat_clean_text(repo.get("total"))
        used = customer_chat_clean_text(repo.get("used"))
        free = customer_chat_clean_text(repo.get("free"))
        used_pct = customer_chat_clean_text(repo.get("used_pct"))
        tier = customer_chat_clean_text(repo.get("tier"))
        if not any([total, used, free, used_pct, tier]):
            continue
        parts = [name]
        if tier:
            parts.append(f"tier={tier}")
        if total:
            parts.append(f"total={total}")
        if used:
            parts.append(f"used={used}")
        if free:
            parts.append(f"free={free}")
        if used_pct:
            parts.append(f"used_pct={used_pct}")
        repo_lines.append(" - " + ", ".join(parts))

    captured_at = customer_chat_clean_text((state.get("defined_repositories") or {}).get("captured_at"))
    if repo_lines or captured_at:
        repo_block = []
        if repo_lines:
            repo_block.extend(repo_lines)
        if captured_at:
            repo_block.append(f"Snapshot captured at: {captured_at}")
        repo_block.append("Note: Unison performance tier rows share the same physical filesystem; do not add them together.")
        return repo_block
    return []


def customer_chat_backup_version_summary(state):
    backup_versions = state.get("backup_versions") or {}
    history = backup_versions.get("history") or []
    latest = history[-1] if history else {}
    if not isinstance(latest, dict) or not latest:
        return []

    totals = latest.get("totals") or {}
    machines = latest.get("machines") or []
    sample_date = str(latest.get("sample_date") or "").strip()
    captured_at = str(latest.get("captured_at") or "").strip()
    lines = []
    if sample_date or captured_at:
        lines.append(
            "Latest backup-version snapshot: "
            f"sample {sample_date or 'unknown'}, captured {captured_at or 'unknown'}."
        )
    lines.append(
        " - Machines: {machines}; total restore points: {total}; performance versions: {performance}; "
        "capacity versions: {capacity}; machines over 15 performance versions: {over}; "
        "machines with performance versions but no capacity versions: {missing}.".format(
            machines=totals.get("machines", 0),
            total=totals.get("total_restore_points", totals.get("sobr_versions", 0)),
            performance=totals.get("performance_versions", 0),
            capacity=totals.get("capacity_versions", 0),
            over=totals.get("over_target_machines", 0),
            missing=totals.get("missing_capacity_machines", 0),
        )
    )

    machine_rows = []
    if isinstance(machines, list):
        for machine in machines:
            if not isinstance(machine, dict):
                continue
            machine_name = str(machine.get("machine") or "").strip()
            if not machine_name:
                continue
            machine_rows.append(machine)
    if machine_rows:
        lines.append("Machine breakdown (hourly collector snapshot):")
        for machine in sorted(machine_rows, key=lambda item: str(item.get("machine") or "").casefold()):
            machine_name = str(machine.get("machine") or "unknown machine").strip()
            total_restore_points = machine.get("total_restore_points", machine.get("sobr_versions", 0))
            performance_versions = machine.get("performance_versions", 0)
            capacity_versions = machine.get("capacity_versions", 0)
            details = [
                f"total restore points {total_restore_points}",
                f"performance versions {performance_versions}",
                f"capacity versions {capacity_versions}",
            ]
            performance_over_target = machine.get("performance_over_target")
            if performance_over_target not in (None, "", 0):
                details.append(f"over target {performance_over_target}")
            capacity_shortfall = machine.get("capacity_shortfall_vs_performance")
            if capacity_shortfall not in (None, "", 0):
                details.append(f"capacity shortfall {capacity_shortfall}")
            lines.append(f" - {machine_name}: " + "; ".join(map(str, details)) + ".")
    return lines


def customer_chat_job_status_summary(state):
    job_schedule = state.get("job_schedule") or {}
    jobs = job_schedule.get("jobs") or []
    if not isinstance(jobs, list) or not jobs:
        return []

    counts = {"Success": 0, "Warning": 0, "Failed": 0}
    warning_jobs = []
    failed_jobs = []
    unknown_result_jobs = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        result = str(item.get("last_result") or "").strip().title()
        if result in counts:
            counts[result] += 1
            if result == "Warning":
                warning_jobs.append(item)
            elif result == "Failed":
                failed_jobs.append(item)
        else:
            unknown_result_jobs.append(item)

    lines = [
        (
            "Current job results: "
            f"{len(jobs)} total; {counts['Success']} Success, {counts['Warning']} Warning, {counts['Failed']} Failed."
        )
    ]
    if failed_jobs:
        failed_parts = []
        for job in failed_jobs[:3]:
            failed_job = customer_chat_clean_text(job.get("job")) or "unknown job"
            failed_run = customer_chat_clean_text(job.get("last_run")) or "unknown time"
            failed_parts.append(f"{failed_job} last ran {failed_run}")
        extra = len(failed_jobs) - len(failed_parts)
        if extra > 0:
            failed_parts.append(f"{extra} more failed job(s)")
        lines.append("Failed jobs: " + "; ".join(failed_parts) + ".")
    if warning_jobs:
        warning_parts = []
        for job in warning_jobs[:3]:
            warning_job = customer_chat_clean_text(job.get("job")) or "unknown job"
            warning_run = customer_chat_clean_text(job.get("last_run")) or "unknown time"
            warning_parts.append(f"{warning_job} last ran {warning_run}")
        extra = len(warning_jobs) - len(warning_parts)
        if extra > 0:
            warning_parts.append(f"{extra} more warning job(s)")
        lines.append("Warning jobs: " + "; ".join(warning_parts) + ".")
    if unknown_result_jobs:
        lines.append(f"{len(unknown_result_jobs)} job(s) have no usable last result in the snapshot.")
    return lines


def customer_chat_offload_summary(state):
    snapshot = state.get("sobr_offload_stats") or {}
    rows = snapshot.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return []

    running_rows = []
    non_zero_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        state_name = str(row.get("state") or "").strip().lower()
        moved = int(row.get("data_moved_bytes") or 0)
        if state_name in {"working", "running"}:
            running_rows.append(row)
        if moved > 0:
            non_zero_rows.append(row)

    lines = []
    source_received_at = str(snapshot.get("source_received_at") or "").strip()
    if source_received_at:
        lines.append(f"Latest offload snapshot from collector log: {source_received_at}.")
    lines.append(
        f"Current SOBR offload snapshot: {len(running_rows)} running/working rows, "
        f"{len(non_zero_rows)} rows moving data, {len(rows) - len(non_zero_rows)} rows with 0 B moved."
    )
    for row in running_rows[:4]:
        job_display = str(row.get("job_display") or row.get("offload") or "Unknown offload").strip()
        progress = str(row.get("progress") or "").strip()
        data_moved = str(row.get("data_moved") or "").strip()
        started = str(row.get("started") or "").strip()
        running = str(row.get("running") or "").strip()
        parts = [job_display]
        if progress:
            parts.append(progress)
        if data_moved:
            parts.append(data_moved)
        if started or running:
            parts.append(f"started {started or 'unknown'} running {running or 'unknown'}")
        lines.append(" - " + " | ".join(parts))
    return lines


def customer_chat_best_next_answer(state):
    job_schedule = state.get("job_schedule") or {}
    jobs = job_schedule.get("jobs") or []
    if not isinstance(jobs, list) or not jobs:
        return "No job snapshot is available yet, so start with the customer summary and ask for the missing evidence."

    counts = {"Success": 0, "Warning": 0, "Failed": 0}
    failed_jobs = []
    warning_jobs = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        result = str(item.get("last_result") or "").strip().title()
        if result in counts:
            counts[result] += 1
            if result == "Failed":
                failed_jobs.append(item)
            elif result == "Warning":
                warning_jobs.append(item)

    if failed_jobs:
        failed_names = [customer_chat_clean_text(job.get("job")) for job in failed_jobs if customer_chat_clean_text(job.get("job"))]
        if failed_names:
            failed_preview = ", ".join(failed_names[:3])
            if len(failed_names) > 3:
                failed_preview += f" and {len(failed_names) - 3} more"
        else:
            failed_preview = "one or more failed jobs"
        return (
            f"Lead with the {len(failed_jobs)} failed job(s) first: {failed_preview}. "
            f"Then mention the {counts['Warning']} warning job(s) and the overall split "
            f"({counts['Success']} success, {counts['Warning']} warning, {counts['Failed']} failed)."
        )

    if warning_jobs:
        warning_names = [customer_chat_clean_text(job.get("job")) for job in warning_jobs if customer_chat_clean_text(job.get("job"))]
        if warning_names:
            warning_preview = ", ".join(warning_names[:3])
            if len(warning_names) > 3:
                warning_preview += f" and {len(warning_names) - 3} more"
        else:
            warning_preview = "one or more warning jobs"
        return (
            f"No failed jobs were found. Lead with the {len(warning_jobs)} warning job(s): {warning_preview}. "
            f"Then summarize the healthy balance ({counts['Success']} success, {counts['Warning']} warning)."
        )

    return (
        f"Everything is clean in the current job snapshot: {counts['Success']} success, {counts['Warning']} warning, "
        f"{counts['Failed']} failed. Start with a short healthy-status summary and then mention any backup-version or offload details."
    )


def customer_chat_context_bundle(customer):
    profile = customer_chat_customer_profile(customer)
    bundle = {
        "customer": {
            "slug": customer_chat_clean_text(profile.get("slug")),
            "name": customer_chat_clean_text(profile.get("name")),
            "status": customer_chat_clean_text(profile.get("status")),
            "summary": customer_chat_clean_text(profile.get("summary")),
            "tone": customer_chat_clean_text(profile.get("tone")),
            "llm_model": customer_chat_clean_text(profile.get("llm_model") or CUSTOMER_CHAT_LLM_MODEL),
        },
        "sections": [],
    }

    context_prompt = customer_chat_clean_text(profile.get("summary"))
    if context_prompt:
        bundle["sections"].append({"title": "Customer operating context", "lines": [context_prompt]})

    notes_file = customer_chat_clean_text(profile.get("notes_file"))
    if notes_file:
        try:
            notes_text = pathlib.Path(notes_file).read_text(encoding="utf-8")
        except Exception:
            notes_text = ""
        notes_lines = customer_chat_notes_summary(notes_text)
        if notes_lines:
            bundle["sections"].append({"title": "Customer notes summary", "lines": notes_lines})

    state_path = customer_chat_clean_text(profile.get("state_file"))
    if not state_path and customer_chat_canonical_slug(profile.get("slug")) == "unison":
        state_path = str(UNISON_MONITOR_STATE_PATH)

    try:
        state = json.loads(pathlib.Path(state_path).read_text(encoding="utf-8")) if state_path else {}
    except Exception:
        state = {}

    job_status_lines = customer_chat_job_status_summary(state)
    if job_status_lines:
        bundle["sections"].append({"title": "Current job status", "lines": job_status_lines})

    backup_version_lines = customer_chat_backup_version_summary(state)
    if backup_version_lines:
        bundle["sections"].append({"title": "Current backup-version snapshot", "lines": backup_version_lines})

    offload_lines = customer_chat_offload_summary(state)
    if offload_lines:
        bundle["sections"].append({"title": "Current offload snapshot", "lines": offload_lines})

    reports = state.get("reports") or {}
    report_lines = []
    daily_backup_versions = reports.get("daily_backup_versions") or {}
    if daily_backup_versions:
        last_sample_date = customer_chat_clean_text(daily_backup_versions.get("last_sample_date"))
        last_sent_date = customer_chat_clean_text(daily_backup_versions.get("last_sent_date"))
        report_lines.append(
            f"Daily backup versions report: last sample {last_sample_date or 'unknown'}, last sent {last_sent_date or 'unknown'}."
        )
    daily_offload = reports.get("daily_offload") or {}
    if daily_offload:
        last_sent_date = customer_chat_clean_text(daily_offload.get("last_sent_date"))
        report_lines.append(f"Daily offload report: last sent {last_sent_date or 'unknown'}.")
    if report_lines:
        bundle["sections"].append({"title": "Prepared report markers (fallback only)", "lines": report_lines})

    repository_lines = customer_chat_repository_summary(state)
    if repository_lines:
        bundle["sections"].append({"title": "Current repository snapshot", "lines": repository_lines})

    alert_state = state.get("sobr_capacity_tier_alerts") or {}
    latest_alerts = alert_state.get("latest_by_repository") or {}
    alert_lines = []
    for repo_name in ("SOBR_VMware_Repos", "SOBR_SQL_Repos"):
        alert = latest_alerts.get(repo_name) or {}
        used_space = customer_chat_clean_text(alert.get("used_space"))
        sample_date = customer_chat_clean_text(alert.get("sample_date"))
        if used_space or sample_date:
            alert_lines.append(f"{repo_name}: last alert-derived Capacity Tier used space {used_space or 'unknown'} on {sample_date or 'unknown'}.")
    if alert_lines:
        bundle["sections"].append({"title": "Alert-derived capacity-tier markers", "lines": alert_lines})

    bundle["best_next_answer"] = customer_chat_best_next_answer(state)
    return bundle


def customer_chat_build_prompt(customer, messages, user_text, context_bundle=None):
    transcript = "\n".join(customer_chat_thread_lines(messages))
    bundle = context_bundle or customer_chat_context_bundle(customer)
    context_sections = []
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = customer_chat_clean_text(section.get("title")) or "Context"
        lines = [customer_chat_clean_text(line) for line in (section.get("lines") or []) if customer_chat_clean_text(line)]
        if lines:
            context_sections.append(f"{title}:\n" + "\n".join(lines))
    operational_context = "\n\n".join(context_sections)
    customer_name = customer_chat_clean_text(bundle.get("customer", {}).get("name")) or customer_chat_clean_text(customer.get("name")) or customer_chat_clean_text(customer.get("slug")) or "Unknown"
    customer_id = customer_chat_clean_text(bundle.get("customer", {}).get("slug")) or customer_chat_clean_text(customer.get("slug")) or "unknown"
    customer_status = customer_chat_clean_text(bundle.get("customer", {}).get("status")) or customer_chat_clean_text(customer.get("status")) or "Unknown"
    customer_summary = customer_chat_clean_text(bundle.get("customer", {}).get("summary")) or customer_chat_clean_text(customer.get("summary")) or "No summary provided."
    customer_tone = customer_chat_clean_text(bundle.get("customer", {}).get("tone")) or customer_chat_clean_text(customer.get("tone")) or "General"
    return f"""You are Veeam Customer Chat, a concise and practical assistant for customer-scoped conversations.

Customer name: {customer_name}
Customer id: {customer_id}
Customer status: {customer_status}
Customer summary: {customer_summary}
Customer tone: {customer_tone}
Operational evidence:
{operational_context or "No operational evidence available."}

Rules:
- Answer the user's latest message directly.
- Use the prior thread only as context.
- Use the customer status and summary as the thread's operational context.
- Use the evidence above when it is available and relevant.
- Do not invent facts.
- Keep the answer clear and brief.
- Use plain, conversational language rather than report-style wording.
- For all Veeam customers, treat casual shorthand like "how are backups doing", "any issues", "is success up or down", "what changed today", or "break it down by machine" as a request for the latest hourly collector snapshot in the operational evidence.
- Treat the hourly collector snapshot as the source of truth. Sent reports are fallback hints, not the default source.
- For offload questions, use the current offload snapshot from the collector log first; only fall back to the sent offload report marker if the hourly snapshot is missing or stale.
- If there are failed jobs in the snapshot, mention them first by name.
- If there are warnings, mention them after failed jobs.
- Prefer a short operational summary first, then the key figures.
- If the request is ambiguous, ask one short clarifying question.
- If the user asks about backup success rates, restore points, offloads, repository usage, or other Veeam figures, answer from the current operational snapshot first and use sent reports only as backup context.
- Never ask the user to upload a report just so you can answer; use the hourly snapshot and sent report markers already available.
- Only ask for the report name, date, host, or pasted output if the operational evidence genuinely does not contain the needed figures and there is no sent report marker to fall back to.
- Return plain text only.

Conversation history:
{transcript or "No prior conversation."}

Latest user message:
{user_text}
"""


def customer_chat_operational_context(customer):
    bundle = customer_chat_context_bundle(customer)
    lines = []
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = customer_chat_clean_text(section.get("title"))
        section_lines = [customer_chat_clean_text(line) for line in (section.get("lines") or []) if customer_chat_clean_text(line)]
        if not title or not section_lines:
            continue
        lines.append(f"{title}:\n" + "\n".join(section_lines))
    return "\n\n".join(lines)


def customer_chat_run_llm(prompt, model=None):
    model = customer_chat_clean_text(model) or CUSTOMER_CHAT_LLM_MODEL
    result = subprocess.run(
        [
            "/usr/bin/openclaw",
            "infer",
            "model",
            "run",
            "--model",
            model,
            "--json",
            "--prompt",
            prompt,
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"Customer chat model failed with exit code {result.returncode}")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse customer chat model output: {exc}") from exc
    outputs = payload.get("outputs") or []
    if not outputs:
        raise RuntimeError("Customer chat model returned no outputs")
    text = str(outputs[0].get("text") or "").strip()
    if not text:
        raise RuntimeError("Customer chat model returned an empty reply")
    return text


def customer_chat_generate_reply(store, slug, user_text):
    with CUSTOMER_CHAT_LOCK:
        customer = customer_chat_customer_map(store).get(slug)
        if not customer:
            return None
        messages = list(store["threads"].get(slug, []))
        if messages and str(messages[-1].get("role") or "") == "me" and str(messages[-1].get("text") or "").strip() == str(user_text or "").strip():
            messages = messages[:-1]

    context = customer_chat_context_bundle(customer)
    prompt = customer_chat_build_prompt(customer, messages, user_text, context)
    try:
        reply_text = customer_chat_run_llm(prompt, context.get("customer", {}).get("llm_model"))
    except Exception:
        reply_text = CUSTOMER_CHAT_REPLY_FALLBACK

    with CUSTOMER_CHAT_LOCK:
        if not customer_chat_customer_map(store).get(slug):
            return None
        message = customer_chat_message(f"{slug}-{int(time.time() * 1000)}-{secrets.token_hex(3)}", "assistant", reply_text)
        store["threads"].setdefault(slug, []).append(message)
        save_customer_chat_store(store)
        return customer_chat_customer_payload(store, slug)


def customer_chat_reset_thread(store, slug):
    with CUSTOMER_CHAT_LOCK:
        customer = customer_chat_customer_map(store).get(slug)
        if not customer:
            return None
        store["threads"][slug] = []
        save_customer_chat_store(store)
        return customer_chat_customer_payload(store, slug)


def load_auth_config():
    try:
        data = json.loads(AUTH_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None
    required = ("salt", "password_hash", "session_secret")
    if not all(isinstance(data.get(key), str) and data[key] for key in required):
        return None
    data["iterations"] = int(data.get("iterations") or AUTH_ITERATIONS)
    return data


def password_hash(password, salt, iterations):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b64url_decode(salt), iterations)
    return b64url(digest)


def verify_login_password(password):
    config = load_auth_config()
    if not config:
        return True
    actual = password_hash(password, config["salt"], config["iterations"])
    return hmac.compare_digest(actual, config["password_hash"])


def sign_session(payload, secret):
    return b64url(hmac.new(b64url_decode(secret), payload.encode("utf-8"), hashlib.sha256).digest())


def make_session_cookie():
    config = load_auth_config()
    if not config:
        return ""
    issued = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    payload = f"{issued}:{nonce}"
    signature = sign_session(payload, config["session_secret"])
    token = f"{payload}:{signature}"
    return (
        f"{AUTH_COOKIE_NAME}={token}; Path=/; Max-Age={AUTH_COOKIE_MAX_AGE}; "
        "HttpOnly; SameSite=Lax"
    )


def expire_session_cookie():
    return f"{AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


def parse_cookie_header(header):
    cookies = {}
    for part in str(header or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def valid_session_cookie(value):
    config = load_auth_config()
    if not config:
        return True
    parts = str(value or "").split(":")
    if len(parts) != 3:
        return False
    issued, nonce, signature = parts
    if not issued.isdigit() or not nonce:
        return False
    age = time.time() - int(issued)
    if age < 0 or age > AUTH_COOKIE_MAX_AGE:
        return False
    expected = sign_session(f"{issued}:{nonce}", config["session_secret"])
    return hmac.compare_digest(signature, expected)


def safe_next_path(value):
    value = unquote(str(value or "/")).strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    if value.startswith("/login") or value.startswith("/api/login") or value.endswith("/login"):
        return "/"
    return value


def auth_enabled():
    return load_auth_config() is not None


def route_for_path(request_path):
    for route in sorted(PROTECTED_ROUTES, key=lambda item: len(item["base"]), reverse=True):
        base = route["base"]
        if request_path == base:
            return {**route, "inner": "/", "needs_slash": not route.get("homepage", False)}
        if request_path.startswith(f"{base}/"):
            inner = request_path[len(base):] or "/"
            return {**route, "inner": inner, "needs_slash": False}
    return {"base": "", "root": ROOT, "documenter_api": True, "inner": request_path or "/", "needs_slash": False}


class DebugTrace:
    def __init__(self):
        self.started = time.monotonic()
        self.lines = []

    def add(self, message):
        elapsed = time.monotonic() - self.started
        self.lines.append(f"{elapsed:08.3f}s | {message}")

    def paramiko_handler(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("paramiko | %(levelname)s | %(message)s"))
        return handler, stream


class DebugHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, debug):
        self.debug = debug

    def missing_host_key(self, client, hostname, key):
        self.debug.add(f"SSH host key not in local known_hosts; accepting {key.get_name()} {fingerprint(key)} for {hostname}.")
        client.get_host_keys().add(hostname, key.get_name(), key)


class DocumenterHandler(BaseHTTPRequestHandler):
    server_version = "StorwizeDocumentation/0.1"

    def do_OPTIONS(self):
        route = route_for_path(urlparse(self.path).path)
        if route.get("base") == MYGRAIN_WAVS_ROUTE:
            self.send_response(204)
            for key, value in mygrain_wavs_cors_headers().items():
                self.send_header(key, value)
            self.end_headers()
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        request_path = parsed.path
        route = route_for_path(request_path)
        if route.get("base") == MYGRAIN_WAVS_ROUTE and route["inner"] == "/api/list":
            self.send_json({"ok": True, "files": list_mygrain_wav_files()}, extra_headers=mygrain_wavs_cors_headers())
            return
        if route.get("homepage") and route["inner"] == "/":
            self.serve_homepage()
            return
        if request_path == "/":
            if not self.is_authenticated():
                self.redirect_to_login(route)
                return
            self.serve_homepage()
            return
        if route["needs_slash"]:
            location = f"{route['base']}/"
            if parsed.query:
                location = f"{location}?{parsed.query}"
            self.send_response(308)
            self.send_header("Location", location)
            self.end_headers()
            return
        if route["inner"] == "/login":
            self.serve_login(route)
            return
        if route["inner"] == "/logout":
            self.send_response(303)
            self.send_header("Location", f"{route['base']}/login" if route["base"] else "/login")
            self.send_header("Set-Cookie", expire_session_cookie())
            self.end_headers()
            return
        if route.get("base") == MYGRAIN_WAVS_ROUTE:
            self.serve_static(route)
            return
        if route["base"] == "/customer-chat" and route["inner"].startswith("/api/"):
            if not self.is_authenticated():
                self.send_json({"ok": False, "error": "Login required"}, status=401)
                return
            self.handle_customer_chat_api("GET", route["inner"])
            return
        if not self.is_authenticated():
            self.redirect_to_login(route)
            return
        if route["documenter_api"] and route["inner"] == "/api/health":
            self.send_json({"ok": True, "time": time.time()})
            return
        self.serve_static(route)

    def do_POST(self):
        request_path = urlparse(self.path).path
        route = route_for_path(request_path)
        if route.get("base") == MYGRAIN_WAVS_ROUTE and route["inner"] == "/api/upload":
            self.handle_mygrain_wavs_upload()
            return
        if route.get("base") == MYGRAIN_WAVS_ROUTE and route["inner"] == "/api/bastardloop":
            self.handle_mygrain_bastardloop()
            return
        if route.get("base") == MYGRAIN_WAVS_ROUTE and route["inner"] == "/api/rename":
            self.handle_mygrain_wavs_rename()
            return
        if route.get("homepage") and route["inner"] in ("/login", "/api/login"):
            self.send_response(303)
            self.send_header("Location", "/homepage")
            self.end_headers()
            return
        if route["inner"] in ("/login", "/api/login"):
            self.handle_login(route)
            return
        if route["base"] == "/customer-chat" and route["inner"].startswith("/api/"):
            if not self.is_authenticated():
                self.send_json({"ok": False, "error": "Login required"}, status=401)
                return
            self.handle_customer_chat_api("POST", route["inner"])
            return
        if route.get("base") == MYGRAIN_WAVS_ROUTE:
            self.send_json({"ok": False, "error": "Unknown API endpoint"}, status=404, extra_headers=mygrain_wavs_cors_headers())
            return
        if not self.is_authenticated():
            self.send_json({"ok": False, "error": "Login required"}, status=401)
            return
        if not route["documenter_api"] or route["inner"] not in ("/api/fetch", "/api/test"):
            self.send_json({"ok": False, "error": "Unknown API endpoint"}, status=404)
            return

        try:
            payload = self.read_json()
            result = test_storage_credentials(payload) if route["inner"] == "/api/test" else fetch_from_storage(payload)
            self.send_json(result, status=200 if result.get("ok") else 400)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc), "debug": traceback.format_exc().splitlines()}, status=500)

    def handle_mygrain_wavs_upload(self):
        try:
            ensure_mygrain_wavs_root()
            filename = self.headers.get("X-Filename") or ""
            parsed = urlparse(self.path)
            if not filename and parsed.query:
                query = parse_qs(parsed.query)
                filename = (query.get("filename") or [""])[0]
            safe_name = unique_mygrain_wav_filename(sanitize_mygrain_wav_filename(filename))
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                raise ValueError("Empty upload body.")
            if content_length > MYGRAIN_WAVS_MAX_UPLOAD_BYTES:
                raise ValueError("Upload is too large.")
            payload = self.rfile.read(content_length)
            if len(payload) != content_length:
                raise ValueError("Could not read the full upload body.")
            target_path = MYGRAIN_WAVS_ROOT / safe_name
            with open(target_path, "wb") as handle:
                handle.write(payload)
            stat = target_path.stat()
            self.send_json({
                "ok": True,
                "savedName": safe_name,
                "size": stat.st_size,
                "url": f"{MYGRAIN_WAVS_ROUTE}/{quote(safe_name)}",
            }, status=201, extra_headers=mygrain_wavs_cors_headers())
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400, extra_headers=mygrain_wavs_cors_headers())

    def handle_mygrain_bastardloop(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = self.read_json() if content_length > 0 else {}
            bpm = payload.get("bpm", 120) if isinstance(payload, dict) else 120
            seed = payload.get("seed") if isinstance(payload, dict) else None
            result = generate_bastardloop_file(bpm, seed=seed)
            self.send_json(result, status=201, extra_headers=mygrain_wavs_cors_headers())
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400, extra_headers=mygrain_wavs_cors_headers())

    def do_DELETE(self):
        request_path = urlparse(self.path).path
        route = route_for_path(request_path)
        if route.get("base") == MYGRAIN_WAVS_ROUTE and route["inner"] == "/api/delete":
            self.handle_mygrain_wavs_delete()
            return
        if route.get("base") == MYGRAIN_WAVS_ROUTE:
            self.send_json({"ok": False, "error": "Unknown API endpoint"}, status=404, extra_headers=mygrain_wavs_cors_headers())
            return
        self.send_json({"ok": False, "error": "Method not allowed"}, status=405)

    def handle_mygrain_wavs_delete(self):
        try:
            ensure_mygrain_wavs_root()
            parsed = urlparse(self.path)
            filename = self.headers.get("X-Filename") or ""
            if not filename and parsed.query:
                query = parse_qs(parsed.query)
                filename = (query.get("filename") or [""])[0]
            target_name = sanitize_mygrain_wav_filename(filename)
            target_path = MYGRAIN_WAVS_ROOT / target_name
            if not target_path.exists():
                raise FileNotFoundError("File not found.")
            target_path.unlink()
            self.send_json({
                "ok": True,
                "deletedName": target_name,
            }, extra_headers=mygrain_wavs_cors_headers())
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400, extra_headers=mygrain_wavs_cors_headers())

    def handle_mygrain_wavs_rename(self):
        try:
            ensure_mygrain_wavs_root()
            payload = self.read_json()
            current_name = str(payload.get("from") or payload.get("filename") or "").strip()
            desired_name = str(payload.get("to") or payload.get("name") or "").strip()
            if not current_name:
                raise ValueError("Missing source filename.")
            if not desired_name:
                raise ValueError("Missing destination filename.")
            source_name = sanitize_mygrain_wav_filename(current_name)
            source_path = MYGRAIN_WAVS_ROOT / source_name
            if not source_path.exists():
                raise FileNotFoundError("File not found.")
            target_name = sanitize_mygrain_wav_filename(desired_name)
            target_name = unique_mygrain_wav_filename(target_name) if target_name != source_name else source_name
            target_path = MYGRAIN_WAVS_ROOT / target_name
            if target_path != source_path:
                source_path.rename(target_path)
            self.send_json({
                "ok": True,
                "oldName": source_name,
                "savedName": target_name,
                "url": f"{MYGRAIN_WAVS_ROUTE}/{quote(target_name)}",
            }, extra_headers=mygrain_wavs_cors_headers())
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400, extra_headers=mygrain_wavs_cors_headers())

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 256_000:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def read_form(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64_000:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length).decode("utf-8")
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return json.loads(raw or "{}")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def send_json(self, payload, status=200, extra_headers=None):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_customer_chat_api(self, method, inner_path):
        if inner_path == "/api/health" and method == "GET":
            store = load_customer_chat_store()
            total_messages = sum(len(messages) for messages in store["threads"].values())
            self.send_json({"ok": True, "customers": len(store["customers"]), "messages": total_messages, "time": time.time()})
            return
        if inner_path == "/api/customers" and method == "GET":
            store = load_customer_chat_store()
            self.send_json(customer_chat_list_payload(store))
            return

        match = re.match(r"^/api/customers/([^/]+)(/messages|/reset)?$", inner_path)
        if not match:
            self.send_json({"ok": False, "error": "Unknown customer chat API endpoint"}, status=404)
            return

        slug = unquote(match.group(1))
        action = match.group(2) or ""
        if not CUSTOMER_CHAT_SLUG_RE.match(slug):
            self.send_json({"ok": False, "error": "Invalid customer slug"}, status=400)
            return

        store = load_customer_chat_store()
        if method == "GET":
            if action == "":
                payload = customer_chat_customer_payload(store, slug)
                if not payload:
                    self.send_json({"ok": False, "error": "Customer not found"}, status=404)
                    return
                self.send_json(payload)
                return
            if action == "/messages":
                payload = customer_chat_customer_payload(store, slug)
                if not payload:
                    self.send_json({"ok": False, "error": "Customer not found"}, status=404)
                    return
                self.send_json(payload)
                return

        if method == "POST":
            if action == "/messages":
                payload = self.read_json()
                text = str(payload.get("text") or "").strip()
                if not text:
                    self.send_json({"ok": False, "error": "Message text is required"}, status=400)
                    return
                result = customer_chat_append_message(store, slug, text)
                if not result:
                    self.send_json({"ok": False, "error": "Customer not found"}, status=404)
                    return
                reply_result = customer_chat_generate_reply(store, slug, text)
                self.send_json(reply_result or result, status=201)
                return
            if action == "/reset":
                result = customer_chat_reset_thread(store, slug)
                if not result:
                    self.send_json({"ok": False, "error": "Customer not found"}, status=404)
                    return
                self.send_json(result, status=200)
                return

        self.send_json({"ok": False, "error": "Unsupported method"}, status=405)

    def is_authenticated(self):
        if not auth_enabled():
            return True
        cookies = parse_cookie_header(self.headers.get("Cookie", ""))
        return valid_session_cookie(cookies.get(AUTH_COOKIE_NAME))

    def redirect_to_login(self, route):
        next_path = quote(safe_next_path(self.path), safe="/?&=%")
        login_path = f"{route['base']}/login" if route["base"] else "/login"
        self.send_response(303)
        self.send_header("Location", f"{login_path}?next={next_path}")
        self.end_headers()

    def serve_login(self, route, error=""):
        query = parse_qs(urlparse(self.path).query)
        default_next = f"{route['base']}/" if route["base"] else "/"
        next_path = safe_next_path((query.get("next") or [default_next])[0])
        form_action = f"{route['base']}/login" if route["base"] else "/login"
        error_html = f'<p class="login-error">{html.escape(error)}</p>' if error else ""
        body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>OpenClaw Apps Login</title>
    <style>
      :root {{
        color-scheme: light;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #f4f6f8;
        color: #17212f;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        min-height: 100vh;
        margin: 0;
        display: grid;
        place-items: center;
        padding: 24px;
      }}
      main {{
        width: min(100%, 420px);
        background: #fff;
        border: 1px solid #d8dee6;
        border-radius: 8px;
        box-shadow: 0 18px 50px rgba(22, 32, 46, 0.12);
        padding: 28px;
      }}
      h1 {{ margin: 0 0 8px; font-size: 1.45rem; letter-spacing: 0; }}
      p {{ margin: 0 0 18px; color: #5d6a78; }}
      label {{ display: grid; gap: 8px; font-weight: 700; }}
      input {{
        width: 100%;
        min-height: 42px;
        border: 1px solid #c8d2df;
        border-radius: 6px;
        padding: 9px 10px;
        font: inherit;
      }}
      button {{
        width: 100%;
        min-height: 42px;
        margin-top: 16px;
        border: 0;
        border-radius: 6px;
        background: #0f62fe;
        color: #fff;
        font: inherit;
        font-weight: 750;
        cursor: pointer;
      }}
      button:hover {{ background: #0043ce; }}
      .login-error {{
        color: #b42318;
        background: #fff1f0;
        border: 1px solid #ffd0cc;
        border-radius: 6px;
        padding: 10px;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>OpenClaw Apps</h1>
      <p>Enter the OpenClaw password to continue.</p>
      {error_html}
      <form method="post" action="{html.escape(form_action, quote=True)}">
        <input type="hidden" name="next" value="{html.escape(next_path, quote=True)}" />
        <label>Password <input name="password" type="password" autocomplete="current-password" autofocus required /></label>
        <button type="submit">Login</button>
      </form>
    </main>
  </body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def serve_homepage(self):
        storage_tools_doc = ROOT / "plugins" / "storage-protect-docs" / "public" / "index.html"
        try:
            storage_tools_modified = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(storage_tools_doc.stat().st_mtime))
            storage_tools_foot = f"Modified {storage_tools_modified}"
        except OSError:
            storage_tools_foot = "Modified time unavailable"

        veeam_storage_tools_doc = pathlib.Path("/root/.openclaw/workspace/VeeamStorageTools/index.html")
        try:
            veeam_storage_tools_modified = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(veeam_storage_tools_doc.stat().st_mtime))
            veeam_storage_tools_foot = f"Modified {veeam_storage_tools_modified}"
        except OSError:
            veeam_storage_tools_foot = "Modified time unavailable"

        veeam_logo = """
        <span class="card-logo" aria-hidden="true">
          <svg viewBox="0 0 96 28" role="img" focusable="false">
            <rect x="1" y="1" width="94" height="26" rx="13" fill="#eefaf0" stroke="#b9dfc1" />
            <circle cx="15" cy="14" r="6" fill="#1f9d55" />
            <path d="M12.8 13.9l1.8 1.9 3.8-4.7" fill="none" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
            <text x="30" y="18" fill="#14532d" font-size="12" font-weight="800" font-family="Inter, ui-sans-serif, system-ui, sans-serif">Veeam</text>
          </svg>
        </span>
        """

        def card(title, description, href=None, tag="", accent="bcb", foot=None, logo_html="", download=False):
            title_html = html.escape(title)
            description_html = html.escape(description)
            tag_html = html.escape(tag)
            if href:
                foot_html = html.escape(foot or "Open app")
                download_attr = " download" if download else ""
                return f"""
        <a class="app-card {accent}" href="{html.escape(href, quote=True)}" target="_blank" rel="noopener noreferrer" aria-label="{title_html}"{download_attr}>
          <div class="card-top">
            {logo_html}
            <span class="card-tag">{tag_html}</span>
            <span class="card-arrow">↗</span>
          </div>
          <h3>{title_html}</h3>
          <p>{description_html}</p>
          <div class="card-foot">{foot_html}</div>
        </a>"""
            foot_html = html.escape(foot or "Ready for the next tool")
            return f"""
        <div class="app-card {accent} app-card-placeholder">
          <div class="card-top">
            <span class="card-tag">{tag_html}</span>
          </div>
          <h3>{title_html}</h3>
          <p>{description_html}</p>
          <div class="card-foot">{foot_html}</div>
        </div>"""

        veeam_cards = "\n".join([
            card("Grafana Dashboards", "IBM Storage Protect and Storwize dashboards, including system-wide reports, live trends, estate detail, and FlashSystem demo views.", "/grafana/", "Dashboards", "bcb", "Open Grafana"),
            card("Unison Veeam Grafana Overview", "Grafana view of Unison Veeam repository capacity, restore points, alert history, job status, and SOBR offload overlap.", "/grafana/d/unison-veeam-overview/unison-veeam-overview", "Grafana", "bcb", "Open dashboard"),
            card("Unison Veeam Dashboard", "Filesystem utilisation samples, restore-point summaries, and export buttons for the Unison environment.", "/unison-veeam/", "Live report", "veeam", logo_html=veeam_logo),
            card("Kingston University Veeam Dashboard", "Filesystem utilisation samples and restore-point reporting for Kingston University.", "/kingston-university-veeam/", "Live report", "veeam", logo_html=veeam_logo),
            card("Veeam Customer Chat", "Customer-scoped chat threads with persisted history and GPT 5.4 mini replies.", "/customer-chat/index.html", "Chat tool", "veeam", logo_html=veeam_logo, foot="Open customer chat"),
        ])
        customer_document_cards = "\n".join([
            card(
                "IBM Storage Protect Red Bull Racing Course",
                "Current DOCX draft covering IBM Storage Protect concepts, blueprints, retention, storage rules, device-class pools, tape, cloud, and Storage Scale/mmbackup notes.",
                "/storage-protect-download-b2163d7b-5e4f-4966-912e-4b0ae4230a71/IBM_Storage_Protect_Red_Bull_Racing_Course_Draft_v4.docx",
                "DOCX example",
                "bcb",
                "Download DOCX",
                download=True,
            ),
        ])
        bcb_cards = "\n".join([
            card("Storwize Documentation", "IBM Storwize capture, audit, batch generation, and report tools.", "/storwize-documentation/", "BCB app", "bcb"),
            card("SP Document Retrieval Demo", "Storage Protect document retrieval demo. Internal only; this LAN address is not accessible externally.", "http://192.168.1.48:8789/", "Internal only", "bcb", "Open internal demo"),
            card("LLM Workplace", "Requires an LLM API key to work.", "/llm-workplace/", "BCB app", "bcb"),
            card("Cohesity Architect Expert Trainer", "Cohesity Certified Architect Expert trainer with LLM-generated questions. Requires an API key.", "/cohesity-architect-expert-trainer/", "BCB app", "bcb", "Open app"),
            card("PDF to Markup converter", "Convert PDF files into readable text or Markdown in the browser.", "/pdf-to-markup-converter/", "BCB app", "bcb", "Open app"),
            card("User Manual Parser", "Parse Cohesity user guide content into structured JSON in the browser.", "/user-manual-parser/", "BCB app", "bcb", "Open app"),
            """
        <div class="app-downloads cohesity-downloads">
          <div class="download-title">cohesity architect Expert trainer question sets - generated by GPT 5.5 LLM</div>
          <div class="download-links">
            <a href="/cohesity-architect-expert-trainer/cohesity-question-set_1-2026-07-07---c6242159-f604-419c-80ce-a20d256c4911.json" download>Set 1 JSON</a>
            <a href="/cohesity-architect-expert-trainer/cohesity-question-set_2-2026-07-07---16a7f7ab-2ff4-4903-bd19-bce464906893.json" download>Set 2 JSON</a>
            <a href="/cohesity-architect-expert-trainer/cohesity-question-set_3-2026-07-07---4398f36c-2102-45e9-97d5-37a3c5eefdd4.json" download>Set 3 JSON</a>
            <a href="/cohesity-architect-expert-trainer/cohesity-question-set_4-2026-07-10---f54dfee4-721c-42c0-8533-598669ccf9c6.json" download>Set 4 JSON</a>
            <a href="/cohesity-architect-expert-trainer/cohesity-question-set_5-2026-07-11---512c0486-92bd-43b0-8537-9d4a38561d9e.json" download>Set 5 JSON</a>
            <a href="/cohesity-architect-expert-trainer/cohesity-question-set_6-2026-07-12---bcca23a8-d975-4821-b0c6-534b8a592c3e.json" download>Set 6 JSON</a>
          </div>
        </div>""",
            card("Timesheet Tracker", "Work hours tracker for timesheets", "/timesheet-tracker/", "BCB app", "bcb", "Open app"),
            card("Schematic Creator", "Basic Visio diagram creator", "/schematic-creator/", "BCB app", "bcb", "Open app"),
            card("Spectrum Protect Log Error Finder", "Browser-based ACTLOG processor for finding matching Spectrum Protect error lines in files up to 50 MB.", "https://openclaw.blackcarburning.com/spectrum-log-error-finder/", "BCB app", "bcb", "Open app"),
            card("Brocade Zoning Planner", "Browser-based Fabric OS zoning command planner for switchshow and alishow captures, with alias, port, config, and XLSX export views.", "/brocade-zoning-planner/", "BCB app", "bcb", "Open app"),
            card("Inspire Me", "Oblique music prompt tool with producer-inspired cards, MOTD, quotes, and creative studio nudges.", "/oblique-music/", "Music app", "bcb", "Open app"),
            card("SplitRoast", "Splitwise-style trip expenses with login, GBP/EUR expense tracking, settlement records, and simplified balances.", "/splitroast/", "BCB app", "bcb", "Open app"),
            card("Friend Video", "Invite-only browser audio and video calls with online presence, account registration, and WebRTC signalling over the existing OpenClaw HTTPS route.", "/friend-video/", "Private calls", "bcb", "Open app"),
            card("IBM lin_tape Configuration", "Detailed lin_tape configuration guide", "/ibm-lin-tape-configuration/", "BCB app", "bcb", "Open guide"),
            card(
                "VeeamStorageTools",
                "Veeam Backup & Replication report helper for Windows CMD collectors, combined JSON/text import, DOCX reports, capacity tiers, restore points, licensing, and SOBR offload data.",
                "/veeam-storage-tools/",
                "BCB app",
                "veeam",
                veeam_storage_tools_foot,
                logo_html=veeam_logo,
            ),
            card(
                "StorageTools",
                "IBM Storage Protect v8 report helper for generating dsmadmc collection scripts, importing output archives, and building coloured XLSX reports.",
                "/storage-protect-documentation/",
                "BCB app",
                "bcb",
                storage_tools_foot,
            ),
            card("Add another app", "This section is ready for more internal tools as you add them.", None, "Future slot", "placeholder"),
        ])
        body = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>OpenClaw Apps</title>
    <style>
      :root {
        color-scheme: light;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #f3f6fa;
        color: #17212f;
        --line: #d8dee8;
        --panel: #ffffff;
        --accent: #0f62fe;
        --accent-2: #0f766e;
        --accent-3: #1e293b;
        --muted: #5d6a78;
        --shadow: 0 18px 42px rgba(22, 32, 46, 0.08);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        min-height: 100vh;
        background:
          radial-gradient(circle at top left, rgba(15, 98, 254, 0.12), transparent 22%),
          radial-gradient(circle at 90% 0%, rgba(15, 118, 110, 0.10), transparent 24%),
          linear-gradient(180deg, #f7f9fc 0%, #eef3f9 100%);
        color: var(--panel);
      }
      body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background-image: linear-gradient(rgba(15, 24, 32, 0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(15, 24, 32, 0.03) 1px, transparent 1px);
        background-size: 28px 28px;
        mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.16), transparent 70%);
      }
      main {
        position: relative;
        z-index: 1;
        max-width: 1200px;
        margin: 0 auto;
        padding: 36px 20px 48px;
        color: #17212f;
      }
      .hero {
        display: grid;
        grid-template-columns: minmax(0, 1.6fr) minmax(260px, 0.9fr);
        gap: 20px;
        align-items: stretch;
        margin-bottom: 26px;
      }
      .hero-copy,
      .hero-side {
        background: rgba(255, 255, 255, 0.78);
        border: 1px solid rgba(216, 222, 232, 0.9);
        backdrop-filter: blur(14px);
        border-radius: 24px;
        box-shadow: var(--shadow);
      }
      .hero-copy {
        padding: 28px;
      }
      .brand-row {
        display: flex;
        align-items: center;
        gap: 18px;
        margin-bottom: 18px;
      }
      .mark {
        width: 84px;
        min-width: 84px;
        aspect-ratio: 1;
        filter: drop-shadow(0 16px 24px rgba(15, 98, 254, 0.18));
      }
      .eyebrow {
        margin: 0 0 8px;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        font-size: 0.74rem;
        font-weight: 800;
        color: #0f62fe;
      }
      h1 {
        margin: 0;
        font-size: clamp(2.2rem, 5vw, 4rem);
        letter-spacing: -0.03em;
        line-height: 1.02;
      }
      .lede {
        margin: 16px 0 0;
        color: var(--muted);
        font-size: 1.05rem;
        line-height: 1.6;
        max-width: 62ch;
      }
      .hero-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 22px;
      }
      .pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-height: 34px;
        padding: 0 14px;
        border-radius: 999px;
        background: #edf3fb;
        color: #304255;
        border: 1px solid #d9e1ea;
        font-size: 0.9rem;
        font-weight: 700;
      }
      .hero-side {
        padding: 22px;
        display: grid;
        gap: 14px;
        align-content: center;
      }
      .hero-side h2 {
        margin: 0;
        font-size: 1.02rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #304255;
      }
      .hero-side p {
        margin: 0;
        color: var(--muted);
        line-height: 1.55;
      }
      .mini-stack {
        display: grid;
        gap: 10px;
      }
      .mini-item {
        border: 1px solid var(--line);
        border-radius: 14px;
        background: linear-gradient(180deg, #ffffff, #f6f9fd);
        padding: 14px 16px;
      }
      .mini-item strong {
        display: block;
        margin-bottom: 4px;
        color: #17212f;
      }
      .mini-item span {
        color: var(--muted);
        font-size: 0.92rem;
      }
      .section {
        margin-top: 22px;
      }
      .section-head {
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 14px;
      }
      .section-head h2 {
        margin: 0;
        font-size: 1.35rem;
        letter-spacing: -0.02em;
      }
      .section-head p {
        margin: 6px 0 0;
        color: var(--muted);
        max-width: 72ch;
      }
      .section-badge {
        display: inline-flex;
        align-items: center;
        min-height: 30px;
        padding: 0 12px;
        border-radius: 999px;
        background: #e8f0ff;
        color: #0f62fe;
        font-size: 0.78rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        white-space: nowrap;
      }
      .app-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 14px;
      }
      .app-card {
        display: grid;
        gap: 12px;
        padding: 20px;
        min-height: 190px;
        border: 1px solid var(--line);
        border-radius: 22px;
        background:
          radial-gradient(circle at top right, rgba(15, 98, 254, 0.10), transparent 28%),
          linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
        text-decoration: none;
        color: inherit;
        box-shadow: var(--shadow);
        transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
        position: relative;
        overflow: hidden;
      }
      .app-card::after {
        content: "";
        position: absolute;
        inset: auto 18px 18px auto;
        width: 96px;
        height: 96px;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(15, 98, 254, 0.11), transparent 68%);
        pointer-events: none;
      }
      .app-card:hover {
        transform: translateY(-3px);
        border-color: #c3d0df;
        box-shadow: 0 22px 52px rgba(22, 32, 46, 0.12);
      }
      .app-card h3 {
        margin: 0;
        font-size: 1.25rem;
        letter-spacing: -0.02em;
      }
      .app-card p {
        margin: 0;
        color: var(--muted);
        line-height: 1.55;
      }
      .card-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }
      .card-logo {
        display: inline-flex;
        align-items: center;
        margin-right: auto;
      }
      .card-logo svg {
        display: block;
        width: 96px;
        height: 28px;
      }
      .card-tag {
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 0 11px;
        border-radius: 999px;
        background: #edf3fb;
        color: #304255;
        font-size: 0.78rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .card-arrow {
        color: #8fa3ba;
        font-size: 1.15rem;
        font-weight: 700;
      }
      .card-foot {
        margin-top: auto;
        color: #0f62fe;
        font-weight: 800;
        font-size: 0.95rem;
      }
      .app-downloads {
        margin: -2px 2px 8px;
        padding: 14px 16px 16px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: linear-gradient(180deg, #ffffff 0%, #f7faff 100%);
        box-shadow: var(--shadow);
      }
      .app-downloads .download-title {
        margin: 0 0 10px;
        color: #304255;
        font-size: 0.8rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .download-links {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }
      .download-links a {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-height: 34px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid #c9d6ea;
        background: #fff;
        color: #183066;
        text-decoration: none;
        font-size: 0.92rem;
        font-weight: 700;
        transition: transform 160ms ease, border-color 160ms ease, color 160ms ease;
      }
      .download-links a:hover {
        transform: translateY(-1px);
        border-color: #0f62fe;
        color: #0f62fe;
      }
      .app-card.veeam {
        background:
          radial-gradient(circle at top right, rgba(15, 98, 254, 0.13), transparent 30%),
          linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
      }
      .app-card.bcb {
        background:
          radial-gradient(circle at top right, rgba(15, 118, 110, 0.13), transparent 30%),
          linear-gradient(180deg, #ffffff 0%, #f7fbfa 100%);
      }
      .app-card.bcb .card-tag {
        background: #e7f6f3;
        color: #0f766e;
      }
      .app-card.bcb .card-foot {
        color: #0f766e;
      }
      .app-card.placeholder {
        border-style: dashed;
        background:
          linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(247, 249, 252, 0.94));
      }
      .app-card.placeholder .card-tag {
        background: #f0f4f8;
        color: #56697f;
      }
      .footer {
        margin-top: 18px;
        color: var(--muted);
        font-size: 0.92rem;
      }
      @media (max-width: 860px) {
        .hero {
          grid-template-columns: 1fr;
        }
      }
      @media (max-width: 720px) {
        .hero-copy,
        .hero-side {
          border-radius: 18px;
        }
        .hero-copy {
          padding: 22px;
        }
        .app-card {
          min-height: 180px;
        }
      }
    </style>
  </head>
  <body>
    <main>
      <section class="hero" aria-label="OpenClaw landing">
        <div class="hero-copy">
          <div class="brand-row">
            <svg class="mark" viewBox="0 0 96 96" aria-hidden="true">
              <defs>
                <linearGradient id="bcbGrad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stop-color="#0f62fe" />
                  <stop offset="55%" stop-color="#0f766e" />
                  <stop offset="100%" stop-color="#17212f" />
                </linearGradient>
              </defs>
              <circle cx="48" cy="48" r="44" fill="url(#bcbGrad)" />
              <circle cx="48" cy="48" r="33" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="2" />
              <text x="48" y="56" text-anchor="middle" font-size="23" font-weight="800" fill="#ffffff" font-family="Inter, ui-sans-serif, system-ui, sans-serif">BCB</text>
            </svg>
            <div>
              <h1>OpenClaw Dashboard</h1>
            </div>
          </div>
          <p class="lede">A neat front door for customer Veeam reports and BCB internal apps, all behind the same cached login. Add new tools here as the collection grows.</p>
          <div class="hero-meta">
            <span class="pill">Protected session</span>
            <span class="pill">Fast app links</span>
            <span class="pill">Ready to grow</span>
          </div>
        </div>
        <aside class="hero-side">
          <h2>Quick notes</h2>
          <div class="mini-stack">
            <div class="mini-item">
              <strong>Dashboards & Reports</strong>
              <span>Grafana and customer dashboards with the current operational numbers.</span>
            </div>
            <div class="mini-item">
              <strong>BCB Apps</strong>
              <span>Internal tools like Storwize Documentation, with room for more.</span>
            </div>
          </div>
        </aside>
      </section>

      <section class="section" aria-label="Dashboards and Reports">
        <div class="section-head">
          <div>
            <h2>Dashboards & Reports</h2>
            <p>Grafana, customer-facing dashboards, and report views. Keep the operational stuff here.</p>
          </div>
          <span class="section-badge">Live dashboards</span>
        </div>
        <div class="app-grid">
          __VEEAM_CARDS__
        </div>
      </section>

      <section class="section" aria-label="Customer Document Examples">
        <div class="section-head">
          <div>
            <h2>Customer Document Examples</h2>
            <p>Downloadable customer-ready document examples and drafts.</p>
          </div>
          <span class="section-badge">Documents</span>
        </div>
        <div class="app-grid">
          __CUSTOMER_DOCUMENT_CARDS__
        </div>
      </section>

      <section class="section" aria-label="BCB Apps">
        <div class="section-head">
          <div>
            <h2>BCB Apps</h2>
            <p>Internal tools, workbenches, and anything else you want on the same little launchpad.</p>
          </div>
          <span class="section-badge">BCB internal</span>
        </div>
        <div class="app-grid">
          __BCB_CARDS__
        </div>
      </section>
      <div class="footer">Protected by the same cached login session.</div>
    </main>
  </body>
</html>
"""
        body = body.replace("__VEEAM_CARDS__", veeam_cards).replace("__CUSTOMER_DOCUMENT_CARDS__", customer_document_cards).replace("__BCB_CARDS__", bcb_cards)
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def handle_login(self, route):
        try:
            payload = self.read_form()
        except Exception:
            self.serve_login(route, "Could not read login request.")
            return
        password = str(payload.get("password") or "")
        next_path = safe_next_path(payload.get("next") or (f"{route['base']}/" if route["base"] else "/"))
        if not verify_login_password(password):
            login_path = f"{route['base']}/login" if route["base"] else "/login"
            self.path = f"{login_path}?next={quote(next_path, safe='/?&=%')}"
            self.serve_login(route, "Incorrect password.")
            return
        cookie = make_session_cookie()
        self.send_response(303)
        self.send_header("Location", next_path)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def serve_static(self, route):
        request_path = route["inner"]
        if request_path in ("", "/"):
            request_path = "/index.html"
        root = route["root"].resolve()
        candidate = (root / request_path.lstrip("/")).resolve()
        if root not in candidate.parents and candidate != root:
            self.send_error(403)
            return
        if not candidate.exists() or not candidate.is_file():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if route.get("base") == MYGRAIN_WAVS_ROUTE:
            for key, value in mygrain_wavs_cors_headers().items():
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


def fetch_from_storage(payload):
    debug = DebugTrace()
    debug.add("Starting full configuration fetch request.")
    connection = connection_params(payload)
    if not connection["ok"]:
        connection["debug"] = debug.lines
        return connection

    address = connection["address"]
    username = connection["username"]
    password = connection["password"]
    port = connection["port"]
    timeout = connection["timeout"]
    commands = selected_commands(payload)
    debug.add(f"Validated request for {address}:{port} as user '{username}'.")
    debug.add(f"Selected {len(commands)} unique whitelisted svcinfo commands.")

    if not commands:
        return {"ok": False, "error": "Select at least one collection group.", "debug": debug.lines}

    preflight = tcp_preflight(address, port, timeout, debug)
    if preflight:
        return preflight

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(DebugHostKeyPolicy(debug))
    results = []
    capture_parts = []
    handler, stream = debug.paramiko_handler()
    paramiko_logger = logging.getLogger("paramiko")
    paramiko_logger.addHandler(handler)
    old_level = paramiko_logger.level
    paramiko_logger.setLevel(logging.DEBUG)

    try:
        debug.add("Opening SSH connection with password auth; look_for_keys=False, allow_agent=False.")
        client.connect(
            hostname=address,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        add_transport_debug(client, debug)
        for command in commands:
            debug.add(f"Running svcinfo {command}.")
            result = run_svcinfo(client, command, timeout)
            results.append(result)
            debug.add(f"Command completed: svcinfo {command}; ok={result['ok']}; exit={result['exitStatus']}; stdout={len(result['stdout'])} bytes; stderr={len(result['stderr'])} bytes.")
            if result["ok"] and result["stdout"].strip():
                capture_parts.append(f"svcinfo {command}\n{result['stdout'].strip()}\n")
    except paramiko.BadAuthenticationType as exc:
        debug.add(f"Authentication type rejected. Allowed types: {', '.join(exc.allowed_types or [])}.")
        return with_paramiko_debug({"ok": False, "error": "Authentication failed. The array rejected password auth type.", "results": results, "debug": debug.lines}, handler, stream, paramiko_logger, old_level)
    except paramiko.AuthenticationException as exc:
        debug.add(f"Authentication failed: {exc.__class__.__name__}: {exc}.")
        return with_paramiko_debug({"ok": False, "error": "Authentication failed. Check the FlashSystem username/password.", "results": results, "debug": debug.lines}, handler, stream, paramiko_logger, old_level)
    except (paramiko.SSHException, socket.error, OSError) as exc:
        debug.add(f"SSH connection failed: {exc.__class__.__name__}: {exc}.")
        return with_paramiko_debug({"ok": False, "error": f"SSH connection failed: {exc}", "results": results, "debug": debug.lines}, handler, stream, paramiko_logger, old_level)
    finally:
        client.close()
        debug.add("SSH client closed.")
        paramiko_logger.removeHandler(handler)
        paramiko_logger.setLevel(old_level)

    success_count = sum(1 for result in results if result["ok"])
    return {
        "ok": success_count > 0,
        "address": address,
        "commandCount": len(commands),
        "successCount": success_count,
        "failureCount": len(commands) - success_count,
        "captureText": "\n".join(capture_parts),
        "results": results,
        "debug": debug.lines + filtered_paramiko_lines(stream),
    }


def test_storage_credentials(payload):
    debug = DebugTrace()
    debug.add("Starting credential test.")
    connection = connection_params(payload)
    if not connection["ok"]:
        connection["debug"] = debug.lines
        return connection

    address = connection["address"]
    username = connection["username"]
    password = connection["password"]
    port = connection["port"]
    timeout = connection["timeout"]
    debug.add(f"Validated request for {address}:{port} as user '{username}'. Timeout={timeout}s.")
    preflight = tcp_preflight(address, port, timeout, debug)
    if preflight:
        return preflight

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(DebugHostKeyPolicy(debug))
    handler, stream = debug.paramiko_handler()
    paramiko_logger = logging.getLogger("paramiko")
    paramiko_logger.addHandler(handler)
    old_level = paramiko_logger.level
    paramiko_logger.setLevel(logging.DEBUG)

    try:
        debug.add("Opening SSH connection with password auth; look_for_keys=False, allow_agent=False.")
        client.connect(
            hostname=address,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        add_transport_debug(client, debug)
        debug.add(f"Running test command: svcinfo {TEST_COMMAND}.")
        result = run_svcinfo(client, TEST_COMMAND, timeout)
        debug.add(f"Test command completed; ok={result['ok']}; exit={result['exitStatus']}; stdout={len(result['stdout'])} bytes; stderr={len(result['stderr'])} bytes.")
    except paramiko.BadAuthenticationType as exc:
        debug.add(f"Authentication type rejected. Allowed types: {', '.join(exc.allowed_types or [])}.")
        return with_paramiko_debug({"ok": False, "stage": "authentication", "error": "Authentication failed. The array rejected password auth type.", "debug": debug.lines}, handler, stream, paramiko_logger, old_level)
    except paramiko.AuthenticationException as exc:
        debug.add(f"Authentication failed: {exc.__class__.__name__}: {exc}.")
        return with_paramiko_debug({"ok": False, "stage": "authentication", "error": "Authentication failed. Check the FlashSystem username/password.", "debug": debug.lines}, handler, stream, paramiko_logger, old_level)
    except (paramiko.SSHException, socket.error, OSError) as exc:
        debug.add(f"SSH connection failed: {exc.__class__.__name__}: {exc}.")
        return with_paramiko_debug({"ok": False, "stage": "connection", "error": f"SSH connection failed: {exc}", "debug": debug.lines}, handler, stream, paramiko_logger, old_level)
    finally:
        client.close()
        debug.add("SSH client closed.")
        paramiko_logger.removeHandler(handler)
        paramiko_logger.setLevel(old_level)

    if not result["ok"]:
        return {
            "ok": False,
            "stage": "command",
            "error": "SSH login succeeded, but svcinfo lssystem did not run successfully.",
            "results": [result],
            "debug": debug.lines + filtered_paramiko_lines(stream),
        }

    system = parse_delimited_first_row(result["stdout"])
    display_name = system.get("name") or system.get("id") or address
    code_level = system.get("code_level") or "unknown code level"
    return {
        "ok": True,
        "stage": "complete",
        "address": address,
        "message": f"Credentials verified for {display_name} ({code_level}).",
        "system": {
            "id": system.get("id", ""),
            "name": system.get("name", ""),
            "code_level": system.get("code_level", ""),
            "console_IP": system.get("console_IP", ""),
            "topology": system.get("topology", ""),
        },
        "results": [result],
        "debug": debug.lines + filtered_paramiko_lines(stream),
    }


def connection_params(payload):
    address = str(payload.get("address", "")).strip()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))

    try:
        port = int(payload.get("port") or 22)
        timeout = max(5, min(int(payload.get("timeout") or 30), 180))
    except (TypeError, ValueError):
        return {"ok": False, "error": "SSH port and timeout must be numbers."}

    if not address or not HOST_RE.match(address):
        return {"ok": False, "error": "Enter a valid storage management IP or DNS name."}
    if not username:
        return {"ok": False, "error": "Enter a username."}
    if not password:
        return {"ok": False, "error": "Enter a password."}
    if port < 1 or port > 65535:
        return {"ok": False, "error": "SSH port must be between 1 and 65535."}

    return {
        "ok": True,
        "address": address,
        "username": username,
        "password": password,
        "port": port,
        "timeout": timeout,
    }


def parse_delimited_first_row(stdout):
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(lines) < 2 or ":" not in lines[0]:
        return {}
    headers = lines[0].split(":")
    values = lines[1].split(":")
    if len(values) > len(headers):
        values = values[: len(headers) - 1] + [":".join(values[len(headers) - 1 :])]
    return {header: values[index] if index < len(values) else "" for index, header in enumerate(headers)}


def tcp_preflight(address, port, timeout, debug):
    tcp_timeout = min(timeout, 8)
    debug.add(f"Preflight: opening raw TCP connection to {address}:{port} with {tcp_timeout}s timeout.")
    started = time.monotonic()
    try:
        sock = socket.create_connection((address, port), timeout=tcp_timeout)
        peer = sock.getpeername()
        local = sock.getsockname()
        sock.close()
        debug.add(f"Preflight: TCP connect succeeded from {local[0]}:{local[1]} to {peer[0]}:{peer[1]} in {round((time.monotonic() - started) * 1000)} ms.")
        return None
    except OSError as exc:
        debug.add(f"Preflight: TCP connect failed after {round((time.monotonic() - started) * 1000)} ms: {exc.__class__.__name__}: {exc}.")
        return {
            "ok": False,
            "stage": "tcp",
            "error": f"OpenClaw server cannot reach {address}:{port} over TCP: {exc}",
            "debug": debug.lines,
        }


def add_transport_debug(client, debug):
    transport = client.get_transport()
    if not transport:
        debug.add("No Paramiko transport object available after connect.")
        return
    remote_version = getattr(transport, "remote_version", "")
    local_version = getattr(transport, "local_version", "")
    debug.add(f"SSH transport active={transport.is_active()}; authenticated={transport.is_authenticated()}.")
    if remote_version:
        debug.add(f"Remote SSH version: {remote_version}.")
    if local_version:
        debug.add(f"Local SSH version: {local_version}.")
    key = transport.get_remote_server_key()
    if key:
        debug.add(f"Remote host key: {key.get_name()} {fingerprint(key)}.")


def fingerprint(key):
    return ":".join(f"{byte:02x}" for byte in key.get_fingerprint())


def filtered_paramiko_lines(stream):
    blocked = ("passphrase",)
    lines = []
    for line in stream.getvalue().splitlines():
        if any(word in line.lower() for word in blocked):
            continue
        lines.append(line)
    return lines[-200:]


def with_paramiko_debug(payload, handler, stream, logger, old_level):
    logger.removeHandler(handler)
    logger.setLevel(old_level)
    payload["debug"] = payload.get("debug", []) + filtered_paramiko_lines(stream)
    return payload


def selected_commands(payload):
    requested = payload.get("commands")
    if requested:
        raw_commands = [str(command).strip() for command in requested]
    else:
        selected_group_ids = set(payload.get("groups") or [])
        raw_commands = [
            command
            for group in FETCH_GROUPS
            if group["id"] in selected_group_ids
            for command in group["commands"]
        ]

    commands = []
    seen = set()
    for command in raw_commands:
        if command not in ALLOWED_COMMANDS or command in seen:
            continue
        seen.add(command)
        commands.append(command)
    return commands


def run_svcinfo(client, command, timeout):
    started = time.monotonic()
    full_command = command if command.startswith("svcinfo ") else f"svcinfo {command}"
    try:
        stdin, stdout, stderr = client.exec_command(full_command, timeout=timeout)
        stdin.close()
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return {
            "command": command,
            "ok": exit_status == 0,
            "exitStatus": exit_status,
            "durationMs": round((time.monotonic() - started) * 1000),
            "stdout": out,
            "stderr": err,
        }
    except Exception as exc:
        return {
            "command": command,
            "ok": False,
            "exitStatus": None,
            "durationMs": round((time.monotonic() - started) * 1000),
            "stdout": "",
            "stderr": str(exc),
        }


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("0.0.0.0", port), DocumenterHandler)
    print(f"Storwize Documentation listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
