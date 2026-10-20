#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3.10 or newer was not found; install it and try again." >&2
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    echo "Creating .venv…"
    "$PYTHON" -m venv .venv
fi

if ! .venv/bin/python -c "import PySide6, bleak, numpy, sounddevice" >/dev/null 2>&1; then
    echo "Installing Python dependencies…"
    .venv/bin/python -m pip install -r requirements.txt
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "warning: ffmpeg was not found; music playback will be unavailable." >&2
fi

exec .venv/bin/python -m mrstar "$@"
