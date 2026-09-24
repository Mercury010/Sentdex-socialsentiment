#!/usr/bin/env bash
# One-command start for macOS / Linux: creates the virtual environment on
# first run, then starts collector + dashboard and opens the browser.
# Sources and search terms come from .env (SS_RUN_SOURCES, SS_TRACK_TERMS).
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "First run: creating virtual environment and installing dependencies..."
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m socialsentiment run "$@"
