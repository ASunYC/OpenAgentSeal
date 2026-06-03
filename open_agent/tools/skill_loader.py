"""
Skill Loader - Load Agent Skills.

Supports loading skills from SKILL.md files and providing them to Agent.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    source: str = "builtin"
    source_label: str = "OpenAgentSeal"
    plugin_id: Optional[str] = None
    original_name: Optional[str] = None

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

    def __init__(
        self,
        skills_dir: str | Path | list[str | Path | dict[str, Any]] = "./skills",
        extra_roots: Optional[list[dict[str, str]]] = None,
        disabled_paths: Optional[set[str]] = None,
    ):
        self.skill_roots = self._normalize_roots(skills_dir)
        if extra_roots:
            self.skill_roots.extend(self._normalize_roots(extra_roots))
        self.skills_dir = Path(self.skill_roots[0]["path"]) if self.skill_roots else Path("./skills")
        self.loaded_skills: Dict[str, Skill] = {}
        self.disabled_paths = disabled_paths or set()

    def _normalize_roots(self, roots: str | Path | list[str | Path | dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(roots, list):
            roots = [roots]
        normalized = []
        for root in roots:
            if isinstance(root, dict):
                path = root.get("path")
                if path:
                    normalized.append({
                        "path": Path(path),
                        "source": root.get("source", "plugin"),
                        "source_label": root.get("plugin_name") or root.get("source_label") or root.get("plugin_id") or "Plugin",
                        "plugin_id": root.get("plugin_id"),
                    })
            else:
                normalized.append({
                    "path": Path(root),
                    "source": "builtin",
                    "source_label": "OpenAgentSeal",
                    "plugin_id": None,
                })
        return normalized

    def load_skill(self, skill_path: Path, root_info: Optional[dict[str, Any]] = None) -> Optional[Skill]:
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
                source=(root_info or {}).get("source", "builtin"),
                source_label=(root_info or {}).get("source_label", "OpenAgentSeal"),
                plugin_id=(root_info or {}).get("plugin_id"),
                original_name=frontmatter["name"],
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

        for root_info in self.skill_roots:
            skills_dir = Path(root_info["path"])
            if not skills_dir.exists():
                logger.warning("Skills directory does not exist: %s", skills_dir)
                continue

            for skill_file in skills_dir.rglob("SKILL.md"):
                if str(skill_file) in self.disabled_paths:
                    continue
                skill = self.load_skill(skill_file, root_info)
                if not skill:
                    continue
                if skill.name in self.loaded_skills:
                    if skill.plugin_id:
                        skill.name = f"{skill.source_label}:{skill.name}"
                    else:
                        suffix = skills_dir.name
                        skill.name = f"{suffix}:{skill.name}"
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
