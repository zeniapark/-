#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
mkdir -p data
export CS_DB="$(pwd)/data/cs.sqlite3"
export PORT="${PORT:-3000}"
echo "[HANARO] Starting at http://localhost:${PORT}"
echo "[HANARO] Keep this terminal open. Press Ctrl+C to stop."
python3 app.py
