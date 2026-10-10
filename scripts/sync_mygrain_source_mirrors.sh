#!/usr/bin/env bash
set -euo pipefail

ROOT="/srv/sftp/mark_sftp/files/mygrain-source-mirrors"
LOCK_FILE="/tmp/openclaw-mygrain-source-sync.lock"
LOG_FILE="/root/.openclaw/workspace/logs/mygrain-source-sync.log"
MIRROR_DIRS=(
  "SAMPLEDROP"
  "SAMPLEDROP2"
  "SAMPLEDROP_CLAW"
  "SAMPLES_KICKS"
  "SAMPLES_SNARES"
  "SAMPLES_HATS"
  "SAMPLES_PIANO"
  "SAMPLES_ORCH"
  "SAMPLES_VOCAL"
)

mkdir -p "$(dirname "$LOG_FILE")"
for mirror_dir in "${MIRROR_DIRS[@]}"; do
  mkdir -p "$ROOT/$mirror_dir"
  chgrp sftpusers "$ROOT/$mirror_dir"
  chmod 2755 "$ROOT/$mirror_dir"
done

exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  printf '[%s] %s\n' "$(timestamp)" "$*" >> "$LOG_FILE"
}

sync_one() {
  local remote_path="$1"
  local local_path="$2"
  log "sync start ${remote_path} -> ${local_path}"
  rclone sync "$remote_path" "$local_path" \
    --create-empty-src-dirs \
    --transfers 8 \
    --checkers 16 \
    --fast-list
  log "sync complete ${remote_path} -> ${local_path}"
}

log "mygrain source mirror run started"
sync_one "dropbox:SAMPLEDROP" "$ROOT/SAMPLEDROP"
sync_one "dropbox:SAMPLEDROP_2" "$ROOT/SAMPLEDROP2"
sync_one "dropbox:SPLICE_CLAW" "$ROOT/SAMPLEDROP_CLAW"
sync_one "dropbox:SAMPLES_KICKS" "$ROOT/SAMPLES_KICKS"
sync_one "dropbox:SAMPLES_SNARES" "$ROOT/SAMPLES_SNARES"
sync_one "dropbox:SAMPLES_SPLICE/CLOSED HATS" "$ROOT/SAMPLES_HATS"
sync_one "dropbox:SAMPLES_PIANO" "$ROOT/SAMPLES_PIANO"
sync_one "dropbox:SAMPLES_ORCH" "$ROOT/SAMPLES_ORCH"
sync_one "dropbox:SAMPLES_VOCAL" "$ROOT/SAMPLES_VOCAL"
log "mygrain source mirror run finished"
