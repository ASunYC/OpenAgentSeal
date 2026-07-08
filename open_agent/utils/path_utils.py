"""Path utilities for supporting PyInstaller frozen executables.

When the application is packaged with PyInstaller:
- sys.frozen is True
- sys._MEIPASS points to the temp extraction folder
- sys.executable is the path to the executable

We need to load config/ and skills/ from the executable's directory (external),
NOT from inside the bundled package.
"""

import os
import platform
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    """Check if the application is running as a PyInstaller frozen executable.
    
    Returns:
        True if running from a frozen executable, False otherwise.
    """
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_user_app_dir() -> Path:
    r"""Get the user application directory for storing config and data.
    
    Unified directory for all platforms:
    - Windows: C:\Users\<user>\.open-agent\
    - Linux/macOS: ~/.open-agent/
    
    This should match the logic in config.py
    
    Returns:
        Path to user app directory
    """
    # 统一使用用户主目录下的 .open-agent
    return Path.home() / ".open-agent"


def get_executable_dir() -> Path:
    """Get the directory containing the executable or script.
    
    When frozen (PyInstaller):
        Returns the directory containing the .exe/. executable
    When not frozen (normal Python):
        Returns the project root directory
    
    Returns:
        Path to the executable/script directory
    """
    if is_frozen():
        # Running as PyInstaller bundle
        # sys.executable is the path to the executable
        return Path(sys.executable).parent.resolve()
    else:
        # Running in normal Python environment
        # Return the project root (parent of open_agent package)
        return Path(__file__).parent.parent.parent.resolve()


def get_external_config_dir() -> Path | None:
    """Get the external config directory path.
    
    When frozen, looks for config/ next to the executable.
    When not frozen, returns None (use default search path).
    
    Returns:
        Path to external config directory, or None if not found
    """
    if is_frozen():
        exe_dir = get_executable_dir()
        config_dir = exe_dir / "config"
        if config_dir.exists():
            return config_dir
    return None


def get_user_skills_dir() -> Path:
    """Get the user-editable skills directory."""
    return get_user_app_dir() / "open_agent" / "skills"


def get_bundled_skills_dir() -> Path | None:
    """Get the PyInstaller bundled skills directory, if available."""
    if is_frozen():
        bundled_dir = Path(sys._MEIPASS) / "open_agent" / "skills"
        if bundled_dir.exists():
            return bundled_dir
    return None


def _copy_missing_tree(source: Path, destination: Path) -> None:
    """Copy files from source to destination without overwriting user edits."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            _copy_missing_tree(item, target)
        elif not target.exists():
            shutil.copy2(item, target)


def ensure_user_skills_dir() -> Path | None:
    """Seed or upgrade bundled skills into the user directory.

    The installed application directory may be read-only, so installed builds use
    this editable user copy when no exe-local skills directory exists. Existing
    user files are preserved; only missing bundled skills are added.
    """
    user_skills_dir = get_user_skills_dir()
    bundled_skills_dir = get_bundled_skills_dir()
    if not bundled_skills_dir:
        return user_skills_dir if user_skills_dir.exists() else None

    user_skills_dir.parent.mkdir(parents=True, exist_ok=True)
    if user_skills_dir.exists():
        _copy_missing_tree(bundled_skills_dir, user_skills_dir)
    else:
        shutil.copytree(bundled_skills_dir, user_skills_dir)
    return user_skills_dir


def get_external_skills_dir() -> Path | None:
    """Get the external skills directory path.
    
    When frozen, looks for skills/ next to the executable, then falls back to
    a user-editable first-run copy under ~/.open-agent/open_agent/skills.
    When not frozen, returns None (use default search path).
    
    Returns:
        Path to external skills directory, or None if not found
    """
    if is_frozen():
        exe_dir = get_executable_dir()
        skills_dir = exe_dir / "skills"
        if skills_dir.exists():
            return skills_dir
        user_skills_dir = ensure_user_skills_dir()
        if user_skills_dir:
            return user_skills_dir
        bundled_skills_dir = get_bundled_skills_dir()
        if bundled_skills_dir:
            return bundled_skills_dir
    return None


def resolve_skills_dir(configured_dir: str | Path = "./skills") -> Path | None:
    """Resolve the effective skills directory across dev, portable, and user installs."""
    configured_path = Path(configured_dir).expanduser()

    if is_frozen():
        external_skills = get_external_skills_dir()
        if external_skills:
            return external_skills

    if configured_path.is_absolute() and configured_path.exists():
        return configured_path.resolve()

    project_root = Path(__file__).parent.parent.parent.resolve()
    candidates = [
        Path.cwd() / configured_path,
        Path.cwd() / "open_agent" / configured_path,
        project_root / configured_path,
        project_root / "open_agent" / configured_path,
        Path(__file__).parent.parent / configured_path,
        get_user_app_dir() / "open_agent" / "skills",
        get_user_app_dir() / "skills",
    ]

    for path in candidates:
        if path.exists():
            return path.resolve()

    return None


def get_logs_dir() -> Path:
    r"""Get the logs directory.
    
    Unified log directory for all platforms:
    - Windows: C:\Users\<user>\.open-agent\data\logs\
    - Linux/macOS: ~/.open-agent/data/logs/
    
    Returns:
        Path to logs directory
    """
    log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_data_dir() -> Path:
    r"""Get the data directory for databases and other data files.
    
    Unified data directory for all platforms:
    - Windows: C:\Users\<user>\.open-agent\data\
    - Linux/macOS: ~/.open-agent/data/
    
    Returns:
        Path to data directory
    """
    data_dir = get_user_app_dir() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_main_agent_dir() -> Path:
    r"""Get the isolated data directory for the main agent."""
    path = get_data_dir() / "main-agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_agent_profiles_root() -> Path:
    r"""Get the root directory for isolated sub-agent profiles."""
    path = get_data_dir() / "agents" / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_agent_profile_dir(profile_id: str) -> Path:
    r"""Get the isolated data directory for a sub-agent profile."""
    safe_profile_id = "".join(
        ch for ch in str(profile_id or "").strip() if ch.isalnum() or ch in {"_", "-"}
    )
    if not safe_profile_id:
        safe_profile_id = "profile"
    path = get_agent_profiles_root() / safe_profile_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_memory_dir() -> Path:
    r"""Get the memory database directory.
    
    Unified memory directory for all platforms:
    - Windows: C:\Users\<user>\.open-agent\data\memory\
    - Linux/macOS: ~/.open-agent/data/memory/
    
    Returns:
        Path to memory directory
    """
    memory_dir = get_data_dir() / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


def get_resource_path(relative_path: str) -> Path:
    """Get the correct path for a resource file.
    
    When frozen:
        Looks for the resource next to the executable first,
        then falls back to bundled resources.
    When not frozen:
        Returns the path relative to project root.
    
    Args:
        relative_path: Relative path to the resource (e.g., "config/config.yaml")
    
    Returns:
        Path to the resource file
    """
    if is_frozen():
        # First, check for external resource next to executable
        exe_dir = get_executable_dir()
        external_path = exe_dir / relative_path
        if external_path.exists():
            return external_path
        
        # Fall back to bundled resource
        # sys._MEIPASS is the temp folder where PyInstaller extracts files
        bundled_path = Path(sys._MEIPASS) / "open_agent" / relative_path
        if bundled_path.exists():
            return bundled_path
    
    # Not frozen or fallback - use project root
    project_root = Path(__file__).parent.parent.parent.resolve()
    return project_root / "open_agent" / relative_path
