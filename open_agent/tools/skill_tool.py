"""
Skill tools for loading Agent Skills on demand.

Implements progressive disclosure:
- list_skills: discover available skills and descriptions
- get_skill: load the full SKILL.md guidance for one skill
"""

import logging
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult
from .skill_loader import SkillLoader

logger = logging.getLogger(__name__)


class ListSkillsTool(Tool):
    """Tool to list all available skills."""

    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader

    @property
    def name(self) -> str:
        return "list_skills"

    @property
    def description(self) -> str:
        return "List all available skills with their descriptions. Use this to discover what skills are available."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self) -> ToolResult:
        skills = self.skill_loader.list_skills()

        if not skills:
            return ToolResult(
                success=True,
                content="No skills available. Make sure the skills directory exists and contains SKILL.md files.",
            )

        lines = ["## Available Skills\n"]
        for skill_name in sorted(skills):
            skill = self.skill_loader.get_skill(skill_name)
            if skill:
                lines.append(f"- **{skill_name}**: {skill.description}")

        lines.append(f"\n**Total: {len(skills)} skills**")
        lines.append("\nUse `get_skill` with the skill name to load the full skill content.")

        return ToolResult(success=True, content="\n".join(lines))


class GetSkillTool(Tool):
    """Tool to get detailed information about a specific skill."""

    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader

    @property
    def name(self) -> str:
        return "get_skill"

    @property
    def description(self) -> str:
        return "Get complete content and guidance for a specified skill, used for executing specific types of tasks."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to retrieve. Use list_skills to view available skills.",
                }
            },
            "required": ["skill_name"],
        }

    async def execute(self, skill_name: str) -> ToolResult:
        skill = self.skill_loader.get_skill(skill_name)

        if not skill:
            available = ", ".join(self.skill_loader.list_skills())
            return ToolResult(
                success=False,
                content="",
                error=f"Skill '{skill_name}' does not exist. Available skills: {available}",
            )

        return ToolResult(success=True, content=skill.to_prompt())


def create_skill_tools(
    skills_dir: str = "./skills",
    extra_roots: Optional[list[dict[str, str]]] = None,
    disabled_paths: Optional[set[str]] = None,
) -> tuple[List[Tool], Optional[SkillLoader]]:
    """Create skill tools and their backing loader."""
    loader = SkillLoader(skills_dir, extra_roots=extra_roots, disabled_paths=disabled_paths)
    skills = loader.discover_skills()
    logger.info("Discovered %d Agent Skills from %s", len(skills), skills_dir)

    tools = [
        ListSkillsTool(loader),
        GetSkillTool(loader),
    ]

    return tools, loader
