"""
OpenAgentSeal ECC Command Integration

This module provides CLI commands for interacting with ECC
(Everything Claude Code) from within OpenAgentSeal.

Commands:
- ecc-status: Check ECC installation status
- ecc-install: Install/update ECC
- ecc-hooks: Manage ECC hooks
- ecc-agents: List available ECC agents
- ecc-skills: List available ECC skills
"""

import json
import subprocess
from pathlib import Path
from typing import Any

from open_agent.ecc.installer import (
    get_ecc_version,
    install_ecc,
    is_ecc_installed,
    verify_ecc_installation,
)


def get_ecc_dir() -> Path | None:
    """Get the ECC installation directory."""
    project_root = Path(__file__).parent.parent.parent
    ecc_dir = project_root / ".ecc"
    return ecc_dir if ecc_dir.exists() else None


def ecc_status() -> dict[str, Any]:
    """
    Get ECC installation status.

    Returns:
        Dictionary with installation status information
    """
    status = {
        "installed": False,
        "version": None,
        "location": None,
        "components": {},
        "valid": False,
    }

    ecc_dir = get_ecc_dir()
    if not ecc_dir:
        return status

    status["installed"] = True
    status["location"] = str(ecc_dir)
    status["version"] = get_ecc_version()
    status["valid"] = verify_ecc_installation()

    components = ["agents", "skills", "commands", "hooks", "rules", "mcp-configs"]
    for comp in components:
        comp_dir = ecc_dir / comp
        if comp_dir.exists():
            if comp in ["agents", "skills", "commands"]:
                count = len(list(comp_dir.glob("*.md")))
            elif comp == "hooks":
                count = 1 if (comp_dir / "hooks.json").exists() else 0
            elif comp == "rules":
                count = len(list(comp_dir.glob("**/*.md")))
            else:
                count = len(list(comp_dir.iterdir()))
            status["components"][comp] = count
        else:
            status["components"][comp] = 0

    return status


def ecc_install(force: bool = False) -> dict[str, Any]:
    """
    Install or update ECC.

    Args:
        force: Force reinstallation

    Returns:
        Dictionary with installation result
    """
    if is_ecc_installed() and not force:
        return {
            "success": True,
            "message": "ECC already installed. Use --force to reinstall.",
            "version": get_ecc_version(),
        }

    success = install_ecc()

    return {
        "success": success,
        "message": "ECC installed successfully"
        if success
        else "ECC installation failed",
        "version": get_ecc_version() if success else None,
    }


def ecc_list_agents() -> list[dict[str, str]]:
    """
    List available ECC agents.

    Returns:
        List of agent information dictionaries
    """
    agents = []
    ecc_dir = get_ecc_dir()
    if not ecc_dir:
        return agents

    agents_dir = ecc_dir / "agents"
    if not agents_dir.exists():
        return agents

    for agent_file in sorted(agents_dir.glob("*.md")):
        try:
            content = agent_file.read_text(encoding="utf-8")
            name = agent_file.stem

            description = ""
            if "---" in content:
                frontmatter = content.split("---")[1]
                for line in frontmatter.strip().split("\n"):
                    if line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()
                        break

            agents.append(
                {
                    "name": name,
                    "description": description,
                    "file": str(agent_file),
                }
            )
        except Exception:
            continue

    return agents


def ecc_list_skills() -> list[dict[str, str]]:
    """
    List available ECC skills.

    Returns:
        List of skill information dictionaries
    """
    skills = []
    ecc_dir = get_ecc_dir()
    if not ecc_dir:
        return skills

    skills_dir = ecc_dir / "skills"
    if not skills_dir.exists():
        return skills

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        try:
            content = skill_file.read_text(encoding="utf-8")
            name = skill_dir.name

            description = ""
            if "---" in content:
                frontmatter = content.split("---")[1]
                for line in frontmatter.strip().split("\n"):
                    if line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()
                        break

            skills.append(
                {
                    "name": name,
                    "description": description,
                    "path": str(skill_dir),
                }
            )
        except Exception:
            continue

    return skills


def ecc_list_commands() -> list[dict[str, str]]:
    """
    List available ECC commands.

    Returns:
        List of command information dictionaries
    """
    commands = []
    ecc_dir = get_ecc_dir()
    if not ecc_dir:
        return commands

    commands_dir = ecc_dir / "commands"
    if not commands_dir.exists():
        return commands

    for cmd_file in sorted(commands_dir.glob("*.md")):
        try:
            content = cmd_file.read_text(encoding="utf-8")
            name = cmd_file.stem

            description = ""
            if "---" in content:
                frontmatter = content.split("---")[1]
                for line in frontmatter.strip().split("\n"):
                    if line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()
                        break

            commands.append(
                {
                    "name": f"/{name}",
                    "description": description,
                    "file": str(cmd_file),
                }
            )
        except Exception:
            continue

    return commands


def ecc_run_agent(agent_name: str, prompt: str) -> dict[str, Any]:
    """
    Run an ECC agent with a prompt.

    Args:
        agent_name: Name of the agent to run
        prompt: Prompt to send to the agent

    Returns:
        Dictionary with execution result
    """
    ecc_dir = get_ecc_dir()
    if not ecc_dir:
        return {"error": "ECC not installed"}

    agent_file = ecc_dir / "agents" / f"{agent_name}.md"
    if not agent_file.exists():
        return {"error": f"Agent '{agent_name}' not found"}

    return {
        "agent": agent_name,
        "prompt": prompt,
        "message": "ECC agents are executed by Claude Code, not directly.",
        "hint": f"Use the agent in Claude Code with the Task tool: agent='{agent_name}'",
    }


def format_status_output(status: dict[str, Any]) -> str:
    """Format ECC status for CLI output."""
    lines = [
        "=" * 50,
        "ECC (Everything Claude Code) Status",
        "=" * 50,
    ]

    if not status["installed"]:
        lines.append("[NOT INSTALLED]")
        lines.append("Run 'python -m open_agent.ecc install' to install.")
        return "\n".join(lines)

    lines.append(f"Version:    {status['version'] or 'unknown'}")
    lines.append(f"Location:   {status['location']}")
    lines.append(
        f"Valid:      {'Yes' if status['valid'] else 'No (missing components)'}"
    )
    lines.append("")
    lines.append("Components:")

    for comp, count in status["components"].items():
        lines.append(f"  {comp:15} {count} items")

    return "\n".join(lines)


def format_list_output(items: list[dict[str, str]], title: str) -> str:
    """Format a list of items for CLI output."""
    lines = [
        "=" * 50,
        title,
        "=" * 50,
    ]

    if not items:
        lines.append("(none found)")
        return "\n".join(lines)

    for item in items:
        name = item.get("name", "unknown")
        desc = item.get("description", "")[:60]
        if len(item.get("description", "")) > 60:
            desc += "..."
        lines.append(f"  {name:20} {desc}")

    lines.append("")
    lines.append(f"Total: {len(items)}")

    return "\n".join(lines)


def main():
    """CLI entry point for ECC commands."""
    import argparse

    parser = argparse.ArgumentParser(
        description="OpenAgentSeal ECC Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="ECC command")

    subparsers.add_parser("status", help="Check ECC installation status")
    subparsers.add_parser("agents", help="List available ECC agents")
    subparsers.add_parser("skills", help="List available ECC skills")
    subparsers.add_parser("commands", help="List available ECC commands")

    install_parser = subparsers.add_parser("install", help="Install ECC")
    install_parser.add_argument("--force", action="store_true", help="Force reinstall")

    args = parser.parse_args()

    if args.command == "status":
        status = ecc_status()
        print(format_status_output(status))

    elif args.command == "install":
        result = ecc_install(force=args.force)
        if result["success"]:
            print(f"[OK] {result['message']}")
            if result["version"]:
                print(f"     Version: {result['version']}")
        else:
            print(f"[ERROR] {result['message']}")

    elif args.command == "agents":
        agents = ecc_list_agents()
        print(format_list_output(agents, "ECC Agents"))

    elif args.command == "skills":
        skills = ecc_list_skills()
        print(format_list_output(skills, "ECC Skills"))

    elif args.command == "commands":
        commands = ecc_list_commands()
        print(format_list_output(commands, "ECC Commands"))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
