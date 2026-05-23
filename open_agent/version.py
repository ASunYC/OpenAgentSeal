"""Project version helpers."""

from __future__ import annotations

from pathlib import Path


def _version_file() -> Path:
    return Path(__file__).resolve().parent.parent / "VERSION.md"


def get_version() -> str:
    """Return the current project version from VERSION.md."""
    try:
        version_file = _version_file()
        if version_file.exists():
            for line in version_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("## Current Version:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "0.1.0"


def get_release_date() -> str:
    """Return the release date from VERSION.md if available."""
    try:
        version_file = _version_file()
        if version_file.exists():
            for line in version_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("## Last Updated:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""

