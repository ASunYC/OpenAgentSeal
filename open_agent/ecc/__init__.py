"""
ECC Integration Module for OpenAgentSeal

This module provides integration with Everything Claude Code (ECC),
including installation management, configuration, and workflow execution.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
ECC_DIR = PROJECT_ROOT / ".ecc"


class ECCManager:
    """Manager for ECC installation and configuration."""

    def __init__(self, ecc_dir: Optional[Path] = None):
        self.ecc_dir = ecc_dir or ECC_DIR

    @property
    def is_installed(self) -> bool:
        return self._check_installation()

    @property
    def version(self) -> Optional[str]:
        version_file = self.ecc_dir / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
        return None

    @property
    def agents_dir(self) -> Path:
        return self.ecc_dir / "agents"

    @property
    def skills_dir(self) -> Path:
        return self.ecc_dir / "skills"

    @property
    def commands_dir(self) -> Path:
        return self.ecc_dir / "commands"

    @property
    def hooks_dir(self) -> Path:
        return self.ecc_dir / "hooks"

    @property
    def rules_dir(self) -> Path:
        return self.ecc_dir / "rules"

    @property
    def mcp_configs_dir(self) -> Path:
        return self.ecc_dir / "mcp-configs"

    @property
    def claude_md(self) -> Path:
        return self.ecc_dir / "CLAUDE.md"

    @property
    def agents_md(self) -> Path:
        return self.ecc_dir / "AGENTS.md"

    def _check_installation(self) -> bool:
        if not self.ecc_dir.exists():
            return False

        essential_dirs = ["agents", "skills", "commands", "hooks", "rules"]
        for dir_name in essential_dirs:
            if not (self.ecc_dir / dir_name).exists():
                return False

        essential_files = ["CLAUDE.md", "AGENTS.md"]
        for file_name in essential_files:
            if not (self.ecc_dir / file_name).exists():
                return False

        return True

    def install(self, force: bool = False) -> bool:
        from open_agent.ecc.installer import install_ecc

        return install_ecc(force=force)

    def get_agent(self, agent_name: str) -> Optional[Path]:
        agent_file = self.agents_dir / f"{agent_name}.md"
        if agent_file.exists():
            return agent_file
        return None

    def get_skill(self, skill_name: str) -> Optional[Path]:
        skill_dir = self.skills_dir / skill_name
        if skill_dir.exists():
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                return skill_file
        return None

    def get_command(self, command_name: str) -> Optional[Path]:
        command_file = self.commands_dir / f"{command_name}.md"
        if command_file.exists():
            return command_file
        return None

    def get_hook_config(self) -> Optional[dict]:
        hooks_file = self.hooks_dir / "hooks.json"
        if hooks_file.exists():
            return json.loads(hooks_file.read_text())
        return None

    def get_mcp_config(self) -> Optional[dict]:
        mcp_file = self.ecc_dir / ".mcp.json"
        if mcp_file.exists():
            return json.loads(mcp_file.read_text())
        return None

    def list_agents(self) -> list[str]:
        if not self.agents_dir.exists():
            return []
        return [f.stem for f in self.agents_dir.glob("*.md")]

    def list_skills(self) -> list[str]:
        if not self.skills_dir.exists():
            return []
        return [d.name for d in self.skills_dir.iterdir() if d.is_dir()]

    def list_commands(self) -> list[str]:
        if not self.commands_dir.exists():
            return []
        return [f.stem for f in self.commands_dir.glob("*.md")]

    def execute_command(self, command_name: str, *args) -> int:
        command_file = self.get_command(command_name)
        if not command_file:
            print(f"Command not found: {command_name}")
            return 1

        print(f"Executing ECC command: {command_name}")

        return 0


_ecc_manager: Optional[ECCManager] = None


def get_ecc_manager() -> ECCManager:
    global _ecc_manager
    if _ecc_manager is None:
        _ecc_manager = ECCManager()
    return _ecc_manager


def check_and_install_ecc() -> bool:
    manager = get_ecc_manager()

    if manager.is_installed:
        return True

    print("\n" + "=" * 50)
    print("ECC (Everything Claude Code) not found")
    print("Installing ECC...")
    print("=" * 50 + "\n")

    return manager.install()


def get_ecc_status() -> dict[str, Any]:
    manager = get_ecc_manager()
    return {
        "installed": manager.is_installed,
        "version": manager.version,
        "path": str(manager.ecc_dir),
        "agents": len(manager.list_agents()),
        "skills": len(manager.list_skills()),
        "commands": len(manager.list_commands()),
    }


__all__ = [
    "ECCManager",
    "get_ecc_manager",
    "check_and_install_ecc",
    "get_ecc_status",
]
