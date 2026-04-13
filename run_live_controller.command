#!/bin/zsh
# run_live_controller.command
# Double-click this file in Finder, or run it from a terminal, to start
# live_controller_mac.py inside its virtual environment.

# Change to the directory containing this script so relative paths work.
cd "$(dirname "$0")" || exit 1

# Activate the virtual environment.
if [ ! -f ".venv/bin/activate" ]; then
    echo "Error: virtual environment not found at .venv/"
    echo "Create it with:  python3 -m venv .venv && pip install PyQt6 pynput"
    exit 1
fi

source .venv/bin/activate || exit 1

exec python live_controller_mac.py
