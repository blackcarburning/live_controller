#!/bin/sh
# Wrapper to start the Live Controller GUI once a graphical session is available.
# Waits until a DISPLAY or XDG_RUNTIME_DIR is present (max 120s) then launches.
MAX_WAIT=120
WAITED=0
while [ -z "$DISPLAY" ] && [ -z "$XDG_RUNTIME_DIR" ] && [ "$WAITED" -lt "$MAX_WAIT" ]; do
    sleep 1
    WAITED=$((WAITED + 1))
done
# Launch the app and capture logs
exec /usr/bin/env python3 /root/.openclaw/workspace/live_controller/live_controller.py >> /root/.openclaw/workspace/live_controller/live_controller.log 2>&1
