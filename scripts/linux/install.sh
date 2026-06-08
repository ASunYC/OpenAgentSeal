#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB_DIR="$ROOT_DIR/open_agent/app/web"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEFAULT_VENV_DIR="$ROOT_DIR/.venv"

if [ -d "$DEFAULT_VENV_DIR" ] && [ ! -f "$DEFAULT_VENV_DIR/bin/activate" ]; then
  DEFAULT_VENV_DIR="$ROOT_DIR/.venv-linux"
fi

VENV_DIR="${OPEN_AGENT_VENV:-$DEFAULT_VENV_DIR}"

cd "$ROOT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 was not found. Install Python 3.10+ first." >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("OpenAgentSeal requires Python 3.10+")
PY

if [ -d "$VENV_DIR" ] && [ ! -f "$VENV_DIR/bin/activate" ]; then
  rm -rf "$VENV_DIR"
fi

if [ ! -f "$VENV_DIR/bin/activate" ]; then
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    if command -v uv >/dev/null 2>&1; then
      if [ -d "$VENV_DIR" ] && [ ! -f "$VENV_DIR/bin/activate" ]; then
        rm -rf "$VENV_DIR"
      fi
      uv venv "$VENV_DIR" --python "$PYTHON_BIN"
    else
      cat >&2 <<'EOF'

Failed to create the Python virtual environment.

On Ubuntu/Debian, install the venv package first:
  sudo apt install python3-venv

Alternatively install uv and rerun this script:
  curl -LsSf https://astral.sh/uv/install.sh | sh

Then rerun:
  bash scripts/linux/install.sh
EOF
      exit 1
    fi
  fi
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
DEPS_FILE="$VENV_DIR/openagentseal-requirements.txt"
"$PYTHON_BIN" - <<PY > "$DEPS_FILE"
from pathlib import Path
import tomllib

data = tomllib.loads(Path("$ROOT_DIR/pyproject.toml").read_text(encoding="utf-8"))
for dependency in data["project"]["dependencies"]:
    print(dependency)
PY

if python -m pip --version >/dev/null 2>&1; then
  python -m pip install --upgrade pip
  python -m pip install -r "$DEPS_FILE"
elif command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV_DIR/bin/python" -r "$DEPS_FILE"
else
  cat >&2 <<'EOF'

Neither pip nor uv is available for installing Python dependencies.

On Ubuntu/Debian, install pip:
  sudo apt install python3-pip

Or install uv:
  curl -LsSf https://astral.sh/uv/install.sh | sh
EOF
  exit 1
fi

if command -v npm >/dev/null 2>&1; then
  npm --prefix "$WEB_DIR" install
  npm --prefix "$WEB_DIR" run build
else
  echo "npm was not found. Install Node.js 18+ and run this script again to build the Web UI." >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/workspace"

cat <<EOF

OpenAgentSeal Linux Web-only setup is ready.

Start it with:
  bash scripts/linux/start-web.sh

Then open:
  http://127.0.0.1:9998
EOF
