#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB_STATIC_DIR="$ROOT_DIR/open_agent/app/static"
WEB_DIR="$ROOT_DIR/open_agent/app/web"

HOST="${OPEN_AGENT_HOST:-0.0.0.0}"
PORT="${OPEN_AGENT_PORT:-9998}"
WORKSPACE="${OPEN_AGENT_WORKSPACE:-$ROOT_DIR/workspace}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEFAULT_VENV_DIR="$ROOT_DIR/.venv"

if [ -d "$DEFAULT_VENV_DIR" ] && [ ! -f "$DEFAULT_VENV_DIR/bin/activate" ]; then
  DEFAULT_VENV_DIR="$ROOT_DIR/.venv-linux"
fi

VENV_DIR="${OPEN_AGENT_VENV:-$DEFAULT_VENV_DIR}"

cd "$ROOT_DIR"

if [ -f "$VENV_DIR/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  PYTHON_BIN="python"
elif ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 was not found. Run scripts/linux/install.sh first." >&2
  exit 1
fi

if [ ! -f "$WEB_STATIC_DIR/index.html" ]; then
  if command -v npm >/dev/null 2>&1; then
    npm --prefix "$WEB_DIR" install
    npm --prefix "$WEB_DIR" run build
  else
    echo "Web UI static files are missing and npm is not available." >&2
    echo "Install Node.js 18+ or run scripts/linux/install.sh first." >&2
    exit 1
  fi
fi

mkdir -p "$WORKSPACE"

echo "Starting OpenAgentSeal Web UI"
echo "  host:      $HOST"
echo "  port:      $PORT"
echo "  workspace: $WORKSPACE"
echo
echo "Open http://127.0.0.1:$PORT on this machine, or http://<linux-ip>:$PORT from your LAN."

export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON_BIN" -m open_agent \
  --web-only \
  --no-browser \
  --host "$HOST" \
  --port "$PORT" \
  --workspace "$WORKSPACE" \
  "$@"
