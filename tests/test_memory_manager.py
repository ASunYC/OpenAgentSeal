#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the tree-structured memory system."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from open_agent.memory_manager import (
    MemoryManager,
    Memory,
    MemoryImportance,
    MemoryCategory,
    get_memory_manager,
)


class TestMemoryManager(unittest.TestCase):
    """Test cases for MemoryManager."""

    def setUp(self):
        """Set up test fixtures with a temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = MemoryManager(memory_dir=self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        self.manager.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_memory(self):
        """Test recording a memory."""
        memory = self.manager.record(
            content="User prefers Python with type hints",
            category="user_preference",
            importance="critical",
        )

        self.assertIsNotNone(memory.id)
        self.assertEqual(memory.content, "User prefers Python with type hints")
        self.assertEqual(memory.category, "user_preference")
        self.assertEqual(memory.importance, "critical")
        self.assertIsNotNone(memory.keywords)
        self.assertIsNotNone(memory.timestamp)

    def test_record_with_custom_keywords(self):
        """Test recording with custom keywords."""
        memory = self.manager.record(
            content="Project uses Python 3.12",
            keywords=["python", "project", "version"],
        )

        self.assertIn("python", memory.keywords)
        self.assertIn("project", memory.keywords)
        self.assertIn("version", memory.keywords)

    def test_recall_by_id(self):
        """Test retrieving a memory by ID."""
        recorded = self.manager.record(
            content="Test memory for ID lookup",
            category="general",
        )

        retrieved = self.manager.get_by_id(recorded.id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, recorded.id)
        self.assertEqual(retrieved.content, "Test memory for ID lookup")

    def test_recall_by_keywords(self):
        """Test retrieving memories by keywords."""
        # Record multiple memories
        self.manager.record(
            content="Watched the movie Inception",
            keywords=["movie", "inception"],
        )
        self.manager.record(
            content="Recommended the movie The Matrix",
            keywords=["movie", "matrix"],
        )
        self.manager.record(
            content="Had lunch at the Italian restaurant",
            keywords=["lunch", "restaurant"],
        )

        # Search by keyword
        memories = self.manager.recall(keywords=["movie"])

        self.assertEqual(len(memories), 2)
        for m in memories:
            self.assertIn("movie", m.keywords)

    def test_recall_by_category(self):
        """Test retrieving memories by category."""
        self.manager.record(
            content="User is a Python developer",
            category="user_info",
        )
        self.manager.record(
            content="User prefers dark mode",
            category="user_preference",
        )
        self.manager.record(
            content="Discussed project architecture",
            category="project_info",
        )

        memories = self.manager.recall(category="user_info")

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].category, "user_info")

    def test_recall_by_importance(self):
        """Test retrieving memories by importance."""
        self.manager.record(
            content="Critical: User's name is Alex",
            importance="critical",
        )
        self.manager.record(
            content="Normal: Discussed weather today",
            importance="normal",
        )

        memories = self.manager.recall(importance="critical")

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].importance, "critical")

    def test_recall_by_time_range(self):
        """Test retrieving memories by time range."""
        # Record a memory with a specific timestamp
        past_date = datetime.now() - timedelta(days=60)
        self.manager.record(
            content="Old memory from 60 days ago",
            timestamp=past_date.isoformat(),
        )

        # Record a recent memory
        self.manager.record(
            content="Recent memory from today",
        )

        # Search for recent memories
        memories = self.manager.recall(time_range="month")

        # Should only get the recent one
        for m in memories:
            self.assertIn("Recent", m.content)

    def test_full_text_search(self):
        """Test full-text search functionality."""
        self.manager.record(
            content="The quick brown fox jumps over the lazy dog",
        )
        self.manager.record(
            content="Python is a great programming language",
        )

        # Full-text search for "python"
        memories = self.manager.recall(query="python")

        self.assertGreaterEqual(len(memories), 1)
        found_python = any("Python" in m.content for m in memories)
        self.assertTrue(found_python)

    def test_find_by_keyword_tree(self):
        """Test keyword tree structure search."""
        # Record memories across different dates
        self.manager.record(
            content="Movie: Inception",
            keywords=["movie"],
        )
        self.manager.record(
            content="Movie: The Matrix",
            keywords=["movie"],
        )

        tree = self.manager.find_by_keyword_tree("movie")

        self.assertEqual(tree["keyword"], "movie")
        self.assertGreaterEqual(tree["total_count"], 2)
        self.assertIn("years", tree)

    def test_update_memory(self):
        """Test updating a memory."""
        memory = self.manager.record(
            content="Original content",
        )

        success = self.manager.update(
            memory.id,
            content="Updated content",
            importance="high",
        )

        self.assertTrue(success)

        updated = self.manager.get_by_id(memory.id)
        self.assertEqual(updated.content, "Updated content")
        self.assertEqual(updated.importance, "high")

    def test_delete_memory(self):
        """Test deleting a memory."""
        memory = self.manager.record(
            content="Memory to be deleted",
        )

        success = self.manager.delete(memory.id)
        self.assertTrue(success)

        retrieved = self.manager.get_by_id(memory.id)
        self.assertIsNone(retrieved)

    def test_get_stats(self):
        """Test getting memory statistics."""
        self.manager.record(content="Memory 1", importance="critical")
        self.manager.record(content="Memory 2", importance="normal")
        self.manager.record(content="Memory 3", category="project_info")

        stats = self.manager.get_stats()

        self.assertEqual(stats["total_memories"], 3)
        self.assertIn("critical", stats["by_importance"])
        self.assertIn("project_info", stats["by_category"])
        self.assertGreater(stats["unique_keywords"], 0)

    def test_memory_path(self):
        """Test getting memory path."""
        memory = self.manager.record(
            content="Test memory for path",
        )

        path = self.manager.get_memory_path(memory)

        # Path should be in format: YYYY/MM/DD#id
        self.assertIn("/", path)
        self.assertIn("#", path)

    def test_export_to_json(self):
        """Test exporting memories to JSON."""
        self.manager.record(content="Memory for export 1")
        self.manager.record(content="Memory for export 2")

        export_dir = Path(self.temp_dir) / "exports"
        stats = self.manager.export_to_json(export_dir)

        self.assertEqual(stats["total_memories"], 2)
        self.assertGreater(len(stats["files"]), 0)

        # Verify files exist
        self.assertTrue(export_dir.exists())


class TestMemory(unittest.TestCase):
    """Test cases for Memory dataclass."""

    def test_memory_creation(self):
        """Test creating a Memory object."""
        memory = Memory(
            content="Test content",
            category="user_info",
            importance="critical",
        )

        self.assertEqual(memory.content, "Test content")
        self.assertEqual(memory.category, "user_info")
        self.assertEqual(memory.importance, "critical")
        self.assertIsNotNone(memory.timestamp)
        self.assertIsNotNone(memory.keywords)
        self.assertEqual(memory.keywords, [])

    def test_memory_auto_date_extraction(self):
        """Test automatic date extraction from timestamp."""
        memory = Memory(
            content="Test",
            timestamp="2025-02-27T10:30:00",
        )

        self.assertEqual(memory.year, 2025)
        self.assertEqual(memory.month, 2)
        self.assertEqual(memory.day, 27)

    def test_memory_to_dict(self):
        """Test converting Memory to dictionary."""
        memory = Memory(
            id=1,
            content="Test",
            category="general",
            importance="normal",
            keywords=["test"],
            timestamp="2025-02-27T10:30:00",
            year=2025,
            month=2,
            day=27,
        )

        data = memory.to_dict()

        self.assertEqual(data["id"], 1)
        self.assertEqual(data["content"], "Test")
        self.assertEqual(data["keywords"], ["test"])


class TestMemoryTools(unittest.TestCase):
    """Test cases for memory tools."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = MemoryManager(memory_dir=self.temp_dir)

    def tearDown(self):
        """Clean up."""
        self.manager.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_note_tool(self):
        """Test RecordNoteTool."""
        from open_agent.tools.note_tool import RecordNoteTool
        import asyncio

        tool = RecordNoteTool(memory_dir=self.temp_dir)

        self.assertEqual(tool.name, "record_note")
        self.assertIn("record", tool.description.lower())

        # Test execution
        async def run_test():
            result = await tool.execute(
                content="Test note",
                category="user_info",
                importance="critical",
            )
            self.assertTrue(result.success)
            self.assertIn("Recorded", result.content)

        asyncio.run(run_test())

    def test_recall_notes_tool(self):
        """Test RecallNotesTool."""
        from open_agent.tools.note_tool import RecallNotesTool
        import asyncio

        # First record a note
        self.manager.record(
            content="Test memory for recall",
            keywords=["test"],
        )

        tool = RecallNotesTool(memory_dir=self.temp_dir)

        self.assertEqual(tool.name, "recall_notes")

        # Test execution
        async def run_test():
            result = await tool.execute(keywords=["test"])
            self.assertTrue(result.success)
            self.assertIn("Found", result.content)

        asyncio.run(run_test())

    def test_search_memory_tree_tool(self):
        """Test SearchMemoryTreeTool."""
        from open_agent.tools.note_tool import SearchMemoryTreeTool
        import asyncio

        # Record memories with specific keyword
        self.manager.record(
            content="Movie discussion",
            keywords=["movie"],
        )

        tool = SearchMemoryTreeTool(memory_dir=self.temp_dir)

        self.assertEqual(tool.name, "search_memory_tree")

        # Test execution
        async def run_test():
            result = await tool.execute(keyword="movie")
            self.assertTrue(result.success)
            self.assertIn("movie", result.content.lower())

        asyncio.run(run_test())

    def test_get_memory_stats_tool(self):
        """Test GetMemoryStatsTool."""
        from open_agent.tools.note_tool import GetMemoryStatsTool
        import asyncio

        # Record some memories
        self.manager.record(content="Memory 1")
        self.manager.record(content="Memory 2")

        tool = GetMemoryStatsTool(memory_dir=self.temp_dir)

        self.assertEqual(tool.name, "get_memory_stats")

        # Test execution
        async def run_test():
            result = await tool.execute()
            self.assertTrue(result.success)
            self.assertIn("Statistics", result.content)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()