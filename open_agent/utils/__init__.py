"""Utility modules for open-agent."""

from .terminal_utils import (
    calculate_display_width,
    pad_to_width,
    truncate_with_ellipsis,
)
from .path_utils import (
    is_frozen,
    get_executable_dir,
    get_external_config_dir,
    get_external_skills_dir,
    get_resource_path,
)

__all__ = [
    # Terminal utilities
    "calculate_display_width",
    "pad_to_width",
    "truncate_with_ellipsis",
    # Path utilities (for PyInstaller frozen executables)
    "is_frozen",
    "get_executable_dir",
    "get_external_config_dir",
    "get_external_skills_dir",
    "get_resource_path",
]

