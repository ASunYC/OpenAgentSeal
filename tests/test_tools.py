"""Test cases for tools."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from open_agent.tools import BashTool, EditTool, ReadTool, WriteTool


@pytest.mark.asyncio
async def test_read_tool():
    """Test read file tool."""
    print("\n=== Testing ReadTool ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        # Create a file inside the workspace
        test_file = ws / "hello.txt"
        test_file.write_text("Hello, World!")

        tool = ReadTool(workspace_dir=str(ws))
        result = await tool.execute(path="hello.txt")

        assert result.success, f"Read failed: {result.error}"
        # ReadTool now returns content with line numbers in format: "LINE_NUMBER|LINE_CONTENT"
        assert "Hello, World!" in result.content, f"Content mismatch: {result.content}"
        assert "|Hello, World!" in result.content, f"Expected line number format: {result.content}"
        print("✅ ReadTool test passed")


@pytest.mark.asyncio
async def test_write_tool():
    """Test write file tool."""
    print("\n=== Testing WriteTool ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)

        tool = WriteTool(workspace_dir=str(ws))
        result = await tool.execute(path="test.txt", content="Test content")

        assert result.success, f"Write failed: {result.error}"
        assert (ws / "test.txt").exists(), "File was not created"
        assert (ws / "test.txt").read_text() == "Test content", "Content mismatch"
        print("✅ WriteTool test passed")


@pytest.mark.asyncio
async def test_edit_tool():
    """Test edit file tool."""
    print("\n=== Testing EditTool ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        # Create a file inside the workspace
        test_file = ws / "edit.txt"
        test_file.write_text("Hello, World!")

        tool = EditTool(workspace_dir=str(ws))
        result = await tool.execute(
            path="edit.txt", old_str="World", new_str="Agent"
        )

        assert result.success, f"Edit failed: {result.error}"
        content = test_file.read_text()
        assert content == "Hello, Agent!", f"Content mismatch: {content}"
        print("✅ EditTool test passed")


@pytest.mark.asyncio
async def test_bash_tool():
    """Test bash command tool."""
    print("\n=== Testing BashTool ===")

    tool = BashTool()

    # Test successful command
    result = await tool.execute(command="echo 'Hello from bash'")
    assert result.success, f"Bash failed: {result.error}"
    assert "Hello from bash" in result.content, f"Output mismatch: {result.content}"
    print("✅ BashTool test passed")

    # Test failed command
    result = await tool.execute(command="exit 1")
    assert not result.success, "Command should have failed"
    print("✅ BashTool error handling test passed")


async def main():
    """Run all tool tests."""
    print("=" * 80)
    print("Running Tool Tests")
    print("=" * 80)

    await test_read_tool()
    await test_write_tool()
    await test_edit_tool()
    await test_bash_tool()

    print("\n" + "=" * 80)
    print("All tool tests passed! ✅")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
