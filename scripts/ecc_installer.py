#!/usr/bin/env python3
"""
ECC (Everything Claude Code) Installer

This script installs ECC from either:
1. GitHub repository (preferred)
2. Local fallback path (when network unavailable)

Usage:
    python scripts/ecc_installer.py [--force] [--update]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

ECC_GITHUB_URL = "https://github.com/affaan-m/everything-claude-code.git"
ECC_LOCAL_FALLBACK = r"D:\git-workspace\AI\everything-claude-code"

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
ECC_DIR = PROJECT_ROOT / ".ecc"

ECC_ESSENTIAL_DIRS = [
    "agents",
    "skills",
    "commands",
    "hooks",
    "rules",
    "mcp-configs",
    "scripts",
    "docs",
]

ECC_ESSENTIAL_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    "RULES.md",
    "CONTRIBUTING.md",
]


def log(message: str, level: str = "INFO"):
    prefix = {
        "INFO": "[ECC]",
        "SUCCESS": "[ECC] OK",
        "WARNING": "[ECC] WARN",
        "ERROR": "[ECC] ERR",
    }.get(level, "[ECC]")
    print(f"{prefix} {message}")


def is_git_available() -> bool:
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def is_ecc_installed() -> bool:
    if not ECC_DIR.exists():
        return False

    for dir_name in ECC_ESSENTIAL_DIRS:
        if not (ECC_DIR / dir_name).exists():
            return False

    for file_name in ECC_ESSENTIAL_FILES:
        if not (ECC_DIR / file_name).exists():
            return False

    return True


def try_git_clone() -> bool:
    if not is_git_available():
        log("Git not available, skipping remote clone", "WARNING")
        return False

    log(f"Attempting to clone ECC from GitHub...")
    log(f"  URL: {ECC_GITHUB_URL}")
    log(f"  Target: {ECC_DIR}")

    try:
        if ECC_DIR.exists():
            log("Removing existing .ecc directory...")
            shutil.rmtree(ECC_DIR)

        result = subprocess.run(
            ["git", "clone", "--depth", "1", ECC_GITHUB_URL, str(ECC_DIR)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            log("Successfully cloned ECC from GitHub", "SUCCESS")
            return True
        else:
            log(f"Git clone failed: {result.stderr}", "WARNING")
            return False

    except subprocess.TimeoutExpired:
        log("Git clone timed out", "WARNING")
        return False
    except Exception as e:
        log(f"Git clone error: {e}", "WARNING")
        return False


def copy_from_local() -> bool:
    local_path = Path(ECC_LOCAL_FALLBACK)

    if not local_path.exists():
        log(f"Local ECC fallback path not found: {local_path}", "ERROR")
        return False

    log(f"Copying ECC from local path...")
    log(f"  Source: {local_path}")
    log(f"  Target: {ECC_DIR}")

    try:
        if ECC_DIR.exists():
            log("Removing existing .ecc directory...")
            shutil.rmtree(ECC_DIR)

        ECC_DIR.mkdir(parents=True, exist_ok=True)

        for dir_name in ECC_ESSENTIAL_DIRS:
            src = local_path / dir_name
            dst = ECC_DIR / dir_name
            if src.exists():
                shutil.copytree(src, dst)
                log(f"  Copied: {dir_name}/")

        for file_name in ECC_ESSENTIAL_FILES:
            src = local_path / file_name
            dst = ECC_DIR / file_name
            if src.exists():
                shutil.copy2(src, dst)
                log(f"  Copied: {file_name}")

        for extra_file in [".mcp.json", "package.json"]:
            src = local_path / extra_file
            dst = ECC_DIR / extra_file
            if src.exists():
                shutil.copy2(src, dst)

        log("Successfully copied ECC from local path", "SUCCESS")
        return True

    except Exception as e:
        log(f"Failed to copy from local: {e}", "ERROR")
        return False


def install_ecc(force: bool = False, update: bool = False) -> bool:
    if is_ecc_installed() and not force and not update:
        log("ECC already installed. Use --force to reinstall or --update to update.")
        return True

    if force:
        log("Force reinstall requested", "INFO")

    if update:
        log("Update requested", "INFO")

    log("=" * 50)
    log("Installing Everything Claude Code (ECC)")
    log("=" * 50)

    success = try_git_clone()

    if not success:
        log("Git clone failed, falling back to local copy...", "WARNING")
        success = copy_from_local()

    if success:
        log("=" * 50)
        log("ECC installation completed successfully!", "SUCCESS")
        log(f"  Location: {ECC_DIR}")
        log("=" * 50)
    else:
        log("=" * 50)
        log("ECC installation failed!", "ERROR")
        log("Please check network connection or local fallback path")
        log("=" * 50)

    return success


def get_ecc_version() -> Optional[str]:
    version_file = ECC_DIR / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return None


def verify_ecc_installation() -> bool:
    if not is_ecc_installed():
        return False

    issues = []

    for dir_name in ECC_ESSENTIAL_DIRS:
        if not (ECC_DIR / dir_name).exists():
            issues.append(f"Missing directory: {dir_name}")

    for file_name in ECC_ESSENTIAL_FILES:
        if not (ECC_DIR / file_name).exists():
            issues.append(f"Missing file: {file_name}")

    if issues:
        log("ECC installation verification failed:", "WARNING")
        for issue in issues:
            log(f"  - {issue}", "WARNING")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Install Everything Claude Code (ECC)")
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force reinstall even if already installed",
    )
    parser.add_argument(
        "--update",
        "-u",
        action="store_true",
        help="Update ECC to latest version",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing installation",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show installation status",
    )

    args = parser.parse_args()

    if args.status:
        print(f"ECC Directory: {ECC_DIR}")
        print(f"Installed: {is_ecc_installed()}")
        if is_ecc_installed():
            version = get_ecc_version()
            print(f"Version: {version or 'unknown'}")
            print(f"Verified: {verify_ecc_installation()}")
        return 0

    if args.verify:
        if verify_ecc_installation():
            log("ECC installation verified successfully", "SUCCESS")
            return 0
        else:
            log("ECC installation verification failed", "ERROR")
            return 1

    success = install_ecc(force=args.force, update=args.update)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
