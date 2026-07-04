"""Tests for path traversal protection and file tool security."""

import tempfile
from pathlib import Path

import pytest

from open_agent.utils.safe_join import PathTraversalError, safe_join
from open_agent.tools.file_tools import ReadTool, WriteTool, EditTool


# ── safe_join tests ──


class TestSafeJoin:
    """Tests for safe_join path validation."""

    def setup_method(self):
        self.workspace = Path(tempfile.mkdtemp())
        # Create some test files
        (self.workspace / "hello.txt").write_text("hello")
        (self.workspace / "sub").mkdir()
        (self.workspace / "sub" / "nested.txt").write_text("nested")

    def test_relative_path_resolves(self):
        result = safe_join(self.workspace, "hello.txt")
        assert result == self.workspace / "hello.txt"

    def test_nested_relative_path(self):
        result = safe_join(self.workspace, "sub/nested.txt")
        assert result == self.workspace / "sub" / "nested.txt"

    def test_dot_path_resolves_to_workspace(self):
        result = safe_join(self.workspace, ".")
        assert result == self.workspace

    def test_empty_path_resolves_to_workspace(self):
        result = safe_join(self.workspace, "")
        assert result == self.workspace

    def test_parent_traversal_rejected(self):
        with pytest.raises(PathTraversalError):
            safe_join(self.workspace, "../../../etc/passwd")

    def test_dotdot_prefix_rejected(self):
        with pytest.raises(PathTraversalError):
            safe_join(self.workspace, "../secret")

    def test_absolute_path_escaped(self):
        """Absolute paths are treated as relative to workspace."""
        # An absolute path like /etc/passwd should be resolved
        # as workspace + /etc/passwd, not as the actual /etc/passwd
        with pytest.raises(PathTraversalError):
            safe_join(self.workspace, "/etc/passwd")

    def test_encoded_traversal_rejected(self):
        with pytest.raises(PathTraversalError):
            safe_join(self.workspace, "sub/../../secret")

    def test_backslash_traversal_rejected(self):
        with pytest.raises(PathTraversalError):
            safe_join(self.workspace, "..\\..\\etc\\passwd")


# ── File tool security tests ──


class TestFileToolSecurity:
    """Tests that file tools reject path traversal."""

    def setup_method(self):
        self.workspace = Path(tempfile.mkdtemp())
        (self.workspace / "safe.txt").write_text("safe content")

    @pytest.mark.asyncio
    async def test_read_tool_rejects_traversal(self):
        tool = ReadTool(workspace_dir=str(self.workspace))
        result = await tool.execute(path="../../../etc/passwd")
        assert result.success is False
        assert "越过" in result.error or "path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_tool_rejects_traversal(self):
        tool = WriteTool(workspace_dir=str(self.workspace))
        result = await tool.execute(path="../../../tmp/evil.txt", content="evil")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_edit_tool_rejects_traversal(self):
        tool = EditTool(workspace_dir=str(self.workspace))
        result = await tool.execute(path="../../../etc/passwd", old_str="x", new_str="y")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_read_tool_accepts_valid_path(self):
        tool = ReadTool(workspace_dir=str(self.workspace))
        result = await tool.execute(path="safe.txt")
        assert result.success is True
        assert "safe content" in result.content

    @pytest.mark.asyncio
    async def test_write_tool_accepts_valid_path(self):
        tool = WriteTool(workspace_dir=str(self.workspace))
        result = await tool.execute(path="new.txt", content="new content")
        assert result.success is True
        assert (self.workspace / "new.txt").read_text() == "new content"
