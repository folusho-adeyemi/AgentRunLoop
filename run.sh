#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Create the venv on first run, then reuse it.
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

exec ./.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --reload
