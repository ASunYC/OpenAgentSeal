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
    
    This should match the logic in launcher.py and config.py
    
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


def get_external_config_dir() -> Path:
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


def get_external_skills_dir() -> Path:
    """Get the external skills directory path.
    
    When frozen, looks for skills/ next to the executable.
    When not frozen, returns None (use default search path).
    
    Returns:
        Path to external skills directory, or None if not found
    """
    if is_frozen():
        exe_dir = get_executable_dir()
        skills_dir = exe_dir / "skills"
        if skills_dir.exists():
            return skills_dir
    return None


def get_logs_dir() -> Path:
    r"""Get the logs directory.
    
    Unified log directory for all platforms:
    - Windows: C:\Users\<user>\.open-agent\logs\
    - Linux/macOS: ~/.open-agent/logs/
    
    Returns:
        Path to logs directory
    """
    log_dir = get_user_app_dir() / "logs"
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