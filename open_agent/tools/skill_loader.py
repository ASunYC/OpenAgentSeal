"""
Skill Loader - Load Agent Skills.

Supports loading skills from SKILL.md files and providing them to Agent.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """Skill data structure."""

    name: str
    description: str
    content: str
    license: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    metadata: Optional[Dict[str, str]] = None
    skill_path: Optional[Path] = None

    def to_prompt(self) -> str:
        """Convert skill to prompt format."""
        skill_root = str(self.skill_path.parent) if self.skill_path else "unknown"

        return f"""
# Skill: {self.name}

{self.description}

**Skill Root Directory:** `{skill_root}`

All files and references in this skill are relative to this directory.

---

{self.content}
"""


class SkillLoader:
    """Skill loader."""

    def __init__(self, skills_dir: str = "./skills"):
        self.skills_dir = Path(skills_dir)
        self.loaded_skills: Dict[str, Skill] = {}

    def load_skill(self, skill_path: Path) -> Optional[Skill]:
        """Load a single skill from a SKILL.md file."""
        try:
            content = skill_path.read_text(encoding="utf-8")
            frontmatter_match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)

            if not frontmatter_match:
                logger.warning("%s missing YAML frontmatter", skill_path)
                return None

            frontmatter_text = frontmatter_match.group(1)
            skill_content = frontmatter_match.group(2).strip()

            try:
                frontmatter = yaml.safe_load(frontmatter_text)
            except yaml.YAMLError as exc:
                logger.warning("Failed to parse YAML frontmatter in %s: %s", skill_path, exc)
                return None

            if not isinstance(frontmatter, dict) or "name" not in frontmatter or "description" not in frontmatter:
                logger.warning("%s missing required fields (name or description)", skill_path)
                return None

            skill_dir = skill_path.parent
            processed_content = self._process_skill_paths(skill_content, skill_dir)

            return Skill(
                name=frontmatter["name"],
                description=frontmatter["description"],
                content=processed_content,
                license=frontmatter.get("license"),
                allowed_tools=frontmatter.get("allowed-tools"),
                metadata=frontmatter.get("metadata"),
                skill_path=skill_path,
            )
        except Exception as exc:
            logger.warning("Failed to load skill (%s): %s", skill_path, exc)
            return None

    def _process_skill_paths(self, content: str, skill_dir: Path) -> str:
        """Convert relative skill references to absolute paths when possible."""

        def replace_dir_path(match):
            prefix = match.group(1)
            rel_path = match.group(2)
            abs_path = skill_dir / rel_path
            if abs_path.exists():
                return f"{prefix}{abs_path}"
            return match.group(0)

        content = re.sub(r"(python\s+|`)((?:scripts|references|assets)/[^\s`\)]+)", replace_dir_path, content)

        def replace_doc_path(match):
            prefix = match.group(1)
            filename = match.group(2)
            suffix = match.group(3)
            abs_path = skill_dir / filename
            if abs_path.exists():
                return f"{prefix}`{abs_path}` (use read_file to access){suffix}"
            return match.group(0)

        content = re.sub(
            r"(see|read|refer to|check)\s+([a-zA-Z0-9_-]+\.(?:md|txt|json|yaml))([.,;\s])",
            replace_doc_path,
            content,
            flags=re.IGNORECASE,
        )

        def replace_markdown_link(match):
            prefix = match.group(1) if match.group(1) else ""
            link_text = match.group(2)
            filepath = match.group(3)
            clean_path = filepath[2:] if filepath.startswith("./") else filepath
            abs_path = skill_dir / clean_path
            if abs_path.exists():
                return f"{prefix}[{link_text}](`{abs_path}`) (use read_file to access)"
            return match.group(0)

        content = re.sub(
            r"(?:(Read|See|Check|Refer to|Load|View)\s+)?\[(`?[^`\]]+`?)\]\(((?:\./)?[^)]+\.(?:md|txt|json|yaml|js|py|html))\)",
            replace_markdown_link,
            content,
            flags=re.IGNORECASE,
        )

        return content

    def discover_skills(self) -> List[Skill]:
        """Discover and load all skills in the skills directory."""
        skills = []

        if not self.skills_dir.exists():
            logger.warning("Skills directory does not exist: %s", self.skills_dir)
            return skills

        for skill_file in self.skills_dir.rglob("SKILL.md"):
            skill = self.load_skill(skill_file)
            if skill:
                skills.append(skill)
                self.loaded_skills[skill.name] = skill

        return skills

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a loaded skill by name."""
        return self.loaded_skills.get(name)

    def list_skills(self) -> List[str]:
        """List all loaded skill names."""
        return list(self.loaded_skills.keys())

    def get_skills_metadata_prompt(self) -> str:
        """Generate metadata-only prompt for progressive disclosure."""
        if not self.loaded_skills:
            return ""

        prompt_parts = ["## Available Skills\n"]
        prompt_parts.append("You have access to specialized skills. Each skill provides expert guidance for specific tasks.\n")
        prompt_parts.append("Load a skill's full content using the appropriate skill tool when needed.\n")

        for skill in self.loaded_skills.values():
            prompt_parts.append(f"- `{skill.name}`: {skill.description}")

        return "\n".join(prompt_parts)
