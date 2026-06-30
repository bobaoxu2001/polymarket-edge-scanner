#!/usr/bin/env bash
# One-command local runner: sets up a venv, installs deps, and starts the app.
set -euo pipefail
cd "$(dirname "$0")"

# --- pick a Python 3.11+ interpreter ----------------------------------------
PYBIN=""
for cand in python3.12 python3.11 python3.13 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver=$("$cand" -c 'import sys; print(f"{sys.version_info[0]}{sys.version_info[1]:02d}")')
    if [ "$ver" -ge 311 ]; then PYBIN="$cand"; break; fi
  fi
done
if [ -z "$PYBIN" ]; then
  echo "ERROR: Python 3.11+ is required but was not found." >&2
  exit 1
fi
echo "Using $($PYBIN --version) ($PYBIN)"

# --- venv -------------------------------------------------------------------
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment in .venv ..."
  "$PYBIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# --- deps -------------------------------------------------------------------
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

# --- env file ---------------------------------------------------------------
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example (edit it to customize)."
fi

# --- run --------------------------------------------------------------------
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo ""
echo "Dashboard:  http://${HOST}:${PORT}"
echo "API docs:   http://${HOST}:${PORT}/docs"
echo ""
exec uvicorn backend.main:app --host "$HOST" --port "$PORT"
