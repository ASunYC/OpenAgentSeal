"""Desktop backend entry point for the Tauri sidecar build."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _desktop_log_path(platform_name: str | None = None) -> Path:
    platform_name = platform_name or os.name
    if platform_name == "nt":
        base_dir = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.environ.get("USERPROFILE")
            or "."
        )
    else:
        base_dir = os.environ.get("XDG_STATE_HOME")
        if not base_dir:
            home = Path(os.environ.get("HOME") or Path.home())
            base_dir = home / ".local" / "state"
    log_dir = Path(base_dir) / "OpenAgentSeal"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "desktop-backend.log"


def _ensure_text_streams() -> None:
    log_path = _desktop_log_path()
    if sys.stdout is None:
        sys.stdout = log_path.open("a", encoding="utf-8", errors="replace", buffering=1)
    if sys.stderr is None:
        sys.stderr = log_path.open("a", encoding="utf-8", errors="replace", buffering=1)


def main() -> None:
    os.environ.setdefault("OPEN_AGENT_DESKTOP", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    _ensure_text_streams()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) <= 1:
        workspace = os.environ.get("OPEN_AGENT_DESKTOP_WORKSPACE")
        if not workspace:
            workspace = str(Path.home() / "OpenAgentSeal")

        sys.argv = [
            "open-agent-backend",
            "--web-only",
            "--no-browser",
            "--host",
            os.environ.get("OPEN_AGENT_DESKTOP_HOST", "127.0.0.1"),
            "--port",
            os.environ.get("OPEN_AGENT_DESKTOP_PORT", "9998"),
            "--workspace",
            workspace,
        ]

    from open_agent.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
