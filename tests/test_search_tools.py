"""Tests for workspace search tools: glob, grep, list_dir."""

import pytest

from open_agent.tools.search_tools import (
    GlobTool,
    GrepTool,
    ListDirTool,
    glob_to_regex,
    collect_files_relative,
)


@pytest.fixture
def workspace(tmp_path):
    """Create a test workspace with sample files."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Create directory structure
    (ws / "src").mkdir()
    (ws / "src" / "main.py").write_text("print('hello')\nprint('world')")
    (ws / "src" / "utils.py").write_text("def helper():\n    return 42")
    (ws / "tests").mkdir()
    (ws / "tests" / "test_main.py").write_text("def test_hello():\n    assert True")
    (ws / "README.md").write_text("# Project\nA test project")
    (ws / "config.yaml").write_text("key: value")

    # Create a nested directory
    (ws / "src" / "lib").mkdir()
    (ws / "src" / "lib" / "core.py").write_text("class Core:\n    pass")

    # Create a node_modules directory (should be skipped)
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "pkg").mkdir()
    (ws / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}")

    return ws


# ── glob_to_regex tests ──


class TestGlobToRegex:
    def test_simple_star(self):
        regex = glob_to_regex("*.py")
        assert regex.match("main.py")
        assert not regex.match("src/main.py")

    def test_double_star(self):
        regex = glob_to_regex("**/*.py")
        assert regex.match("main.py")
        assert regex.match("src/main.py")
        assert regex.match("src/lib/core.py")

    def test_directory_prefix(self):
        regex = glob_to_regex("src/**/*.py")
        assert not regex.match("main.py")
        assert regex.match("src/main.py")
        assert regex.match("src/lib/core.py")

    def test_question_mark(self):
        regex = glob_to_regex("?.py")
        assert regex.match("a.py")
        assert not regex.match("ab.py")


# ── collect_files_relative tests ──


class TestCollectFiles:
    def test_collects_text_files(self, workspace):
        files = []
        collect_files_relative(workspace, workspace, files)
        rel_files = set(files)
        assert "README.md" in rel_files
        assert "src/main.py" in rel_files
        assert "src/utils.py" in rel_files
        assert "tests/test_main.py" in rel_files

    def test_skips_hidden_dirs(self, workspace):
        (workspace / ".hidden").mkdir()
        (workspace / ".hidden" / "secret.py").write_text("secret")
        files = []
        collect_files_relative(workspace, workspace, files)
        assert not any(".hidden" in f for f in files)

    def test_skips_node_modules(self, workspace):
        files = []
        collect_files_relative(workspace, workspace, files)
        assert not any("node_modules" in f for f in files)


# ── GlobTool tests ──


class TestGlobTool:
    @pytest.mark.asyncio
    async def test_find_python_files(self, workspace):
        tool = GlobTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="**/*.py")
        assert result.success
        files = result.content.split("\n")
        assert any("main.py" in f for f in files)
        assert any("utils.py" in f for f in files)
        assert any("test_main.py" in f for f in files)

    def test_find_markdown_files(self, workspace):
        import asyncio
        tool = GlobTool(workspace_dir=str(workspace))
        result = asyncio.get_event_loop().run_until_complete(
            tool.execute(pattern="*.md")
        )
        assert result.success
        assert "README.md" in result.content

    @pytest.mark.asyncio
    async def test_no_match(self, workspace):
        tool = GlobTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="**/*.xyz")
        assert result.success
        assert "没有匹配" in result.content

    @pytest.mark.asyncio
    async def test_skip_node_modules(self, workspace):
        tool = GlobTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="**/*.js")
        assert result.success
        # node_modules should be skipped
        assert "node_modules" not in result.content


# ── GrepTool tests ──


class TestGrepTool:
    @pytest.mark.asyncio
    async def test_search_content(self, workspace):
        tool = GrepTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="hello")
        assert result.success
        assert "main.py" in result.content

    @pytest.mark.asyncio
    async def test_search_files_with_matches(self, workspace):
        tool = GrepTool(workspace_dir=str(workspace))
        result = await tool.execute(
            pattern="def", output_mode="files_with_matches"
        )
        assert result.success
        files = result.content.split("\n")
        assert any("utils.py" in f for f in files)

    @pytest.mark.asyncio
    async def test_search_with_include(self, workspace):
        tool = GrepTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="assert", include=".py")
        assert result.success
        assert "test_main.py" in result.content

    @pytest.mark.asyncio
    async def test_search_count_mode(self, workspace):
        tool = GrepTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="print", output_mode="count")
        assert result.success
        assert "main.py" in result.content

    @pytest.mark.asyncio
    async def test_empty_pattern_rejected(self, workspace):
        tool = GrepTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="")
        assert not result.success

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, workspace):
        tool = GrepTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="test", path="../../../etc")
        assert not result.success

    @pytest.mark.asyncio
    async def test_no_match(self, workspace):
        tool = GrepTool(workspace_dir=str(workspace))
        result = await tool.execute(pattern="zzzznonexistent")
        assert result.success
        assert "没有匹配" in result.content


# ── ListDirTool tests ──


class TestListDirTool:
    @pytest.mark.asyncio
    async def test_list_root(self, workspace):
        tool = ListDirTool(workspace_dir=str(workspace))
        result = await tool.execute(path=".")
        assert result.success
        assert "src" in result.content
        assert "README.md" in result.content

    @pytest.mark.asyncio
    async def test_list_subdirectory(self, workspace):
        tool = ListDirTool(workspace_dir=str(workspace))
        result = await tool.execute(path="src")
        assert result.success
        assert "main.py" in result.content
        assert "utils.py" in result.content

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, workspace):
        tool = ListDirTool(workspace_dir=str(workspace))
        result = await tool.execute(path="../../../etc")
        assert not result.success

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, workspace):
        tool = ListDirTool(workspace_dir=str(workspace))
        result = await tool.execute(path="nonexistent")
        assert not result.success

    @pytest.mark.asyncio
    async def test_dirs_listed_first(self, workspace):
        tool = ListDirTool(workspace_dir=str(workspace))
        result = await tool.execute(path=".")
        lines = result.content.split("\n")
        # Find positions of directories and files
        dir_indices = [i for i, l in enumerate(lines) if "📁" in l]
        file_indices = [i for i, l in enumerate(lines) if "📄" in l]
        # All dirs should come before all files
        if dir_indices and file_indices:
            assert max(dir_indices) < min(file_indices)
