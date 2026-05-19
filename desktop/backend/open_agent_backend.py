"""Desktop backend entry point for the Tauri sidecar build."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    os.environ.setdefault("OPEN_AGENT_DESKTOP", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
