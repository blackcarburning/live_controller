#!/usr/bin/env bash
set -euo pipefail

ROOT="/srv/sftp/mark_sftp/files/mygrain-source-mirrors"
LOCK_FILE="/tmp/openclaw-mygrain-source-sync.lock"
LOG_FILE="/root/.openclaw/workspace/logs/mygrain-source-sync.log"

mkdir -p "$ROOT/SAMPLEDROP" "$ROOT/SAMPLEDROP2" "$ROOT/SAMPLEDROP_CLAW" "$(dirname "$LOG_FILE")"

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
log "mygrain source mirror run finished"
