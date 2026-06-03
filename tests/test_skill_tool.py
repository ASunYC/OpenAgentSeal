"""Tests for skill tools.

The agent needs both discovery and progressive loading:
- list_skills lets the model answer questions about available skills.
- get_skill loads the full SKILL.md content on demand.
"""

import tempfile
from pathlib import Path

import pytest

from open_agent.tools.skill_loader import SkillLoader
from open_agent.tools.skill_tool import GetSkillTool, ListSkillsTool, create_skill_tools


def create_test_skill(skill_dir: Path, name: str, description: str, content: str):
    """Create a test skill."""
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"""---
name: {name}
description: {description}
---

{content}
""",
        encoding="utf-8",
    )


@pytest.fixture
def skill_loader():
    """Create a loader with test skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(2):
            skill_dir = Path(tmpdir) / f"test-skill-{i}"
            skill_dir.mkdir()
            create_test_skill(
                skill_dir,
                f"test-skill-{i}",
                f"Test skill {i} description",
                f"Test skill {i} content and instructions.",
            )

        loader = SkillLoader(tmpdir)
        loader.discover_skills()
        yield loader


@pytest.mark.asyncio
async def test_list_skill_tool(skill_loader):
    """Test ListSkillsTool."""
    tool = ListSkillsTool(skill_loader)

    result = await tool.execute()

    assert result.success
    assert "test-skill-0" in result.content
    assert "test-skill-1" in result.content
    assert "Total: 2 skills" in result.content


@pytest.mark.asyncio
async def test_get_skill_tool(skill_loader):
    """Test GetSkillTool."""
    tool = GetSkillTool(skill_loader)

    result = await tool.execute(skill_name="test-skill-0")

    assert result.success
    assert "test-skill-0" in result.content
    assert "Test skill 0 description" in result.content
    assert "Test skill 0 content" in result.content


@pytest.mark.asyncio
async def test_get_skill_tool_nonexistent(skill_loader):
    """Test getting a non-existent skill."""
    tool = GetSkillTool(skill_loader)

    result = await tool.execute(skill_name="nonexistent-skill")

    assert not result.success
    assert "not exist" in result.error.lower()


def test_create_skill_tools_returns_discovery_and_read_tools():
    """create_skill_tools returns skill discovery and read tools."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "test-skill"
        skill_dir.mkdir()
        create_test_skill(skill_dir, "test-skill", "Test skill", "Test content")

        tools, loader = create_skill_tools(tmpdir)

        assert len(tools) == 2
        assert isinstance(tools[0], ListSkillsTool)
        assert isinstance(tools[1], GetSkillTool)
        assert loader is not None


def test_tool_count_includes_discovery_and_progressive_loading():
    """The skill toolset includes discovery plus progressive content loading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "simple-skill"
        skill_dir.mkdir()
        create_test_skill(skill_dir, "simple-skill", "Simple test", "Content")

        tools, _ = create_skill_tools(tmpdir)

        assert len(tools) == 2
        assert tools[0].name == "list_skills"
        assert tools[1].name == "get_skill"
        assert "get complete content" in tools[1].description.lower()
