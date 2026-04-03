"""Configuration file watcher for detecting changes and triggering reload.

This module provides functionality to:
1. Track modification times of MCP and Skills configuration files
2. Detect when configurations have been updated
3. Provide reload functionality for MCP connections and Skills
"""

import time
from pathlib import Path
from typing import List, Optional, Tuple

from .base import Tool


class ConfigWatcher:
    """Watches MCP and Skills configuration files for changes."""

    def __init__(self):
        self.mcp_config_path: Optional[Path] = None
        self.skills_dir: Optional[Path] = None
        self._mcp_mtime: float = 0.0
        self._skills_mtime: float = 0.0

    def initialize(self, mcp_config_path: Optional[Path], skills_dir: Optional[Path]):
        """Initialize the watcher with configuration paths."""
        self.mcp_config_path = mcp_config_path
        self.skills_dir = skills_dir
        
        # Record initial modification times
        if mcp_config_path and mcp_config_path.exists():
            self._mcp_mtime = mcp_config_path.stat().st_mtime
        
        if skills_dir and skills_dir.exists():
            self._skills_mtime = self._get_skills_latest_mtime(skills_dir)

    def _get_skills_latest_mtime(self, skills_dir: Path) -> float:
        """Get the latest modification time of any SKILL.md file."""
        latest = 0.0
        try:
            for skill_file in skills_dir.rglob("SKILL.md"):
                try:
                    mtime = skill_file.stat().st_mtime
                    latest = max(latest, mtime)
                except OSError:
                    continue
            # Also check directory itself
            try:
                dir_mtime = skills_dir.stat().st_mtime
                latest = max(latest, dir_mtime)
            except OSError:
                pass
        except Exception:
            pass
        return latest

    def check_for_changes(self) -> Tuple[bool, bool]:
        """Check if any configuration files have changed.
        
        Returns:
            Tuple of (mcp_changed, skills_changed)
        """
        mcp_changed = False
        skills_changed = False

        # Check MCP config
        if self.mcp_config_path and self.mcp_config_path.exists():
            try:
                current_mtime = self.mcp_config_path.stat().st_mtime
                if current_mtime != self._mcp_mtime:
                    mcp_changed = True
                    self._mcp_mtime = current_mtime
            except OSError:
                pass

        # Check Skills directory
        if self.skills_dir and self.skills_dir.exists():
            current_mtime = self._get_skills_latest_mtime(self.skills_dir)
            if current_mtime != self._skills_mtime:
                skills_changed = True
                self._skills_mtime = current_mtime

        return mcp_changed, skills_changed

    def get_reload_hint(self) -> Optional[str]:
        """Get a hint message if configuration has changed."""
        mcp_changed, skills_changed = self.check_for_changes()
        
        messages = []
        if mcp_changed:
            messages.append(f"MCP config updated: {self.mcp_config_path}")
        if skills_changed:
            messages.append(f"Skills directory updated: {self.skills_dir}")
        
        if messages:
            return "\n".join(messages) + "\nUse /reload to reload configuration."
        return None


# Global watcher instance
_watcher: Optional[ConfigWatcher] = None


def get_config_watcher() -> ConfigWatcher:
    """Get the global config watcher instance."""
    global _watcher
    if _watcher is None:
        _watcher = ConfigWatcher()
    return _watcher


async def reload_mcp_tools(mcp_config_path: Optional[Path]) -> List[Tool]:
    """Reload MCP tools by cleaning up existing connections and reconnecting."""
    from .mcp_loader import load_mcp_tools_async, cleanup_mcp_connections

    print("Reloading MCP services...")

    # Clean up existing connections
    try:
        await cleanup_mcp_connections()
        print("  Disconnected existing MCP connections")
    except Exception as e:
        print(f"  Warning during disconnect: {e}")

    # Reload MCP tools
    if mcp_config_path and mcp_config_path.exists():
        try:
            tools = await load_mcp_tools_async(str(mcp_config_path))
            print(f"  Reloaded {len(tools)} MCP tools")
            return tools
        except Exception as e:
            print(f"  Failed to reload MCP tools: {e}")
            return []
    else:
        print("  MCP config file not found")
        return []


def reload_skills(skills_dir: Optional[Path]) -> Tuple[List[Tool], Optional[object]]:
    """Reload skills from the skills directory."""
    from .skill_tool import create_skill_tools

    print("Reloading Skills...")

    if not skills_dir or not skills_dir.exists():
        print("  Skills directory not found")
        return [], None

    try:
        tools, skill_loader = create_skill_tools(str(skills_dir))
        if skill_loader:
            skill_count = len(skill_loader.loaded_skills)
            print(f"  Reloaded {skill_count} Skills")
        return tools, skill_loader
    except Exception as e:
        print(f"  Failed to reload Skills: {e}")
        return [], None