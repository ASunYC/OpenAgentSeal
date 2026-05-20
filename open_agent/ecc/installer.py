"""
ECC Installer Module

Standalone installer that can be called without circular imports.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
ECC_DIR = PROJECT_ROOT / ".ecc"
ECC_LOCAL_FALLBACK = r"D:\git-workspace\AI\everything-claude-code"
ECC_GITHUB_URL = "https://github.com/affaan-m/everything-claude-code.git"

ECC_ESSENTIAL_DIRS = [
    "agents",
    "skills",
    "commands",
    "hooks",
    "rules",
    "mcp-configs",
    "scripts",
]

ECC_ESSENTIAL_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    "RULES.md",
]


def _log(message: str, level: str = "INFO"):
    prefix = {
        "INFO": "[ECC]",
        "SUCCESS": "[ECC] ✅",
        "WARNING": "[ECC] ⚠️",
        "ERROR": "[ECC] ❌",
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
            issues.append(f"Missing: {dir_name}/")

    for file_name in ECC_ESSENTIAL_FILES:
        if not (ECC_DIR / file_name).exists():
            issues.append(f"Missing: {file_name}")

    if issues:
        for issue in issues:
            _log(issue, "WARNING")
        return False

    return True


def _try_git_clone() -> bool:
    if not is_git_available():
        _log("Git not available", "WARNING")
        return False

    _log(f"Cloning from GitHub: {ECC_GITHUB_URL}")

    try:
        if ECC_DIR.exists():
            shutil.rmtree(ECC_DIR)

        result = subprocess.run(
            ["git", "clone", "--depth", "1", ECC_GITHUB_URL, str(ECC_DIR)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            _log("Git clone successful", "SUCCESS")
            return True
        else:
            _log(f"Git clone failed: {result.stderr[:100]}", "WARNING")
            return False

    except subprocess.TimeoutExpired:
        _log("Git clone timed out", "WARNING")
        return False
    except Exception as e:
        _log(f"Git clone error: {e}", "WARNING")
        return False


def _copy_from_local() -> bool:
    local_path = Path(ECC_LOCAL_FALLBACK)

    if not local_path.exists():
        _log(f"Local fallback not found: {local_path}", "ERROR")
        return False

    _log(f"Copying from local: {local_path}")

    try:
        if ECC_DIR.exists():
            shutil.rmtree(ECC_DIR)

        ECC_DIR.mkdir(parents=True, exist_ok=True)

        for dir_name in ECC_ESSENTIAL_DIRS:
            src = local_path / dir_name
            dst = ECC_DIR / dir_name
            if src.exists():
                shutil.copytree(src, dst)

        for file_name in ECC_ESSENTIAL_FILES:
            src = local_path / file_name
            dst = ECC_DIR / file_name
            if src.exists():
                shutil.copy2(src, dst)

        for extra in [".mcp.json", "package.json", "VERSION"]:
            src = local_path / extra
            dst = ECC_DIR / extra
            if src.exists():
                shutil.copy2(src, dst)

        _log("Local copy successful", "SUCCESS")
        return True

    except Exception as e:
        _log(f"Local copy failed: {e}", "ERROR")
        return False


def install_ecc(force: bool = False, update: bool = False) -> bool:
    if is_ecc_installed() and not force and not update:
        _log("ECC already installed")
        return True

    _log("=" * 40)
    _log("Installing Everything Claude Code (ECC)")
    _log("=" * 40)

    success = _try_git_clone()

    if not success:
        _log("Falling back to local copy...")
        success = _copy_from_local()

    if success:
        _log(f"Installed at: {ECC_DIR}", "SUCCESS")
        version = get_ecc_version()
        if version:
            _log(f"Version: {version}", "SUCCESS")
    else:
        _log("Installation failed", "ERROR")

    return success
