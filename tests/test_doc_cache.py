"""Tests for binary document content cache."""

import time

import pytest

from open_agent.utils.doc_cache import DocContentCache


@pytest.fixture
def cache(tmp_path):
    """Create a cache instance with a temp workspace."""
    return DocContentCache(tmp_path)


@pytest.fixture
def text_file(tmp_path):
    """Create a test text file."""
    f = tmp_path / "test.txt"
    f.write_text("Hello, World!", encoding="utf-8")
    return f


class TestDocContentCache:
    def test_miss_returns_none(self, cache, text_file):
        assert cache.get(text_file) is None

    def test_put_then_get(self, cache, text_file):
        cache.put(text_file, "cached text")
        assert cache.get(text_file) == "cached text"

    def test_invalidated_on_mtime_change(self, cache, text_file):
        cache.put(text_file, "cached text")
        assert cache.get(text_file) == "cached text"

        # Modify file to change mtime
        time.sleep(0.05)
        text_file.write_text("modified", encoding="utf-8")
        assert cache.get(text_file) is None

    def test_invalidated_on_size_change(self, cache, text_file):
        cache.put(text_file, "cached text")
        assert cache.get(text_file) == "cached text"

        # Change file content (same mtime possible but size different)
        time.sleep(0.05)
        text_file.write_text("much longer content that changes size", encoding="utf-8")
        assert cache.get(text_file) is None

    def test_get_or_extract_extracts_on_miss(self, cache, text_file):
        result = cache.get_or_extract(text_file)
        assert result == "Hello, World!"
        # Now cached
        assert cache.get(text_file) == "Hello, World!"

    def test_get_or_extract_returns_cached(self, cache, text_file):
        # Pre-populate cache
        cache.put(text_file, "pre-cached")
        result = cache.get_or_extract(text_file)
        assert result == "pre-cached"

    def test_invalidate_removes_entry(self, cache, text_file):
        cache.put(text_file, "cached text")
        cache.invalidate(text_file)
        assert cache.get(text_file) is None

    def test_invalidate_nonexistent_no_error(self, cache, text_file):
        # Should not raise
        cache.invalidate(text_file)

    def test_clear_removes_all(self, cache, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")

        cache.put(f1, "text a")
        cache.put(f2, "text b")

        count = cache.clear()
        assert count >= 4  # 2 text files + 2 meta files
        assert cache.get(f1) is None
        assert cache.get(f2) is None

    def test_clear_empty_cache(self, cache):
        assert cache.clear() == 0

    def test_cache_dir_created_automatically(self, tmp_path):
        cache = DocContentCache(tmp_path)
        f = tmp_path / "test.txt"
        f.write_text("hello")
        cache.put(f, "hello")
        assert (tmp_path / ".workspace" / "cache").exists()

    def test_deleted_file_invalidates_cache(self, cache, text_file):
        cache.put(text_file, "cached text")
        text_file.unlink()
        assert cache.get(text_file) is None


class TestReadToolWithCache:
    """Test ReadTool integration with the cache."""

    @pytest.mark.asyncio
    async def test_binary_doc_cached(self, tmp_path):
        from open_agent.tools.file_tools import ReadTool

        # Create a fake "pdf" file
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-fake-content")

        tool = ReadTool(workspace_dir=str(tmp_path))

        # First read — extracts (and caches)
        result1 = await tool.execute(path="test.pdf")
        assert result1.success

        # Second read — should come from cache
        result2 = await tool.execute(path="test.pdf")
        assert result2.success
        assert result1.content == result2.content
