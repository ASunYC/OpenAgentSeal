#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for LogMemoryWorker."""

import pytest
from unittest.mock import MagicMock

from open_agent.log_memory_worker import (
    LogMemoryWorker,
    LogEntry,
    SessionLogBatch,
    get_log_memory_worker,
    shutdown_log_memory_worker,
)


class TestLogEntry:
    """Tests for LogEntry dataclass."""

    def test_log_entry_creation(self):
        """Test creating a log entry."""
        entry = LogEntry(
            step=1,
            timestamp="2024-01-01T00:00:00",
            content="Test content",
        )
        assert entry.step == 1
        assert entry.timestamp == "2024-01-01T00:00:00"
        assert entry.content == "Test content"
        assert entry.content_hash is not None

    def test_log_entry_hash_consistency(self):
        """Test that same content produces same hash."""
        entry1 = LogEntry(step=1, timestamp="t1", content="Same content")
        entry2 = LogEntry(step=2, timestamp="t2", content="Same content")
        assert entry1.content_hash == entry2.content_hash

    def test_log_entry_hash_uniqueness(self):
        """Test that different content produces different hash."""
        entry1 = LogEntry(step=1, timestamp="t1", content="Content A")
        entry2 = LogEntry(step=1, timestamp="t1", content="Content B")
        assert entry1.content_hash != entry2.content_hash


class TestSessionLogBatch:
    """Tests for SessionLogBatch dataclass."""

    def test_batch_creation(self):
        """Test creating a session log batch."""
        batch = SessionLogBatch()
        assert batch.entries == []
        assert batch.compressed is False
        assert batch.total_steps == 0

    def test_add_entry(self):
        """Test adding entries to batch."""
        batch = SessionLogBatch()
        entry = batch.add_entry(1, "Test content")
        assert len(batch.entries) == 1
        assert batch.entries[0].content == "Test content"
        assert batch.entries[0].step == 1

    def test_add_entry_preserves_metadata(self):
        """Test adding entries preserves provenance metadata."""
        batch = SessionLogBatch()
        entry = batch.add_entry(
            2,
            "Tool Call: read_file\nResult: example" * 3,
            entry_type="tool_call",
            metadata={
                "session_id": "session-1",
                "profile_id": "main",
                "tool": "read_file",
                "success": True,
            },
        )

        assert entry.metadata["session_id"] == "session-1"
        assert entry.metadata["profile_id"] == "main"
        assert entry.metadata["tool"] == "read_file"


class TestLogMemoryWorker:
    """Tests for LogMemoryWorker class."""

    @pytest.fixture
    def mock_memory_manager(self):
        """Create a mock memory manager."""
        return MagicMock()

    @pytest.fixture
    def worker(self, mock_memory_manager):
        """Create a worker with mock memory manager."""
        worker = LogMemoryWorker(
            memory_manager=mock_memory_manager,
            auto_start=False,  # Don't auto-start for tests
        )
        yield worker
        worker.stop()

    def test_worker_creation(self, worker):
        """Test worker creation."""
        assert worker is not None
        assert worker._stats["total_entries"] == 0
        assert worker._stats["deduplicated"] == 0
        assert worker._stats["stored"] == 0

    def test_submit_log_entry(self, worker):
        """Test submitting a log entry."""
        worker.submit_log_entry("Test content" * 10)  # Long enough to meet min length
        assert worker._queue.qsize() == 1

    def test_submit_short_entry_ignored(self, worker):
        """Test that short entries are ignored."""
        worker.submit_log_entry("Short")  # Too short
        assert worker._queue.qsize() == 0

    def test_submit_step_start(self, worker):
        """Test submitting step start."""
        worker.submit_step_start(1, 100)
        assert worker._queue.qsize() == 1

    def test_submit_step_end(self, worker):
        """Test submitting step end."""
        worker.submit_step_end(1, 1.0, 1.0)
        assert worker._queue.qsize() == 1

    def test_deduplication(self, worker, mock_memory_manager):
        """Test that duplicate content is deduplicated."""
        # Process item directly
        worker._session_batch = SessionLogBatch()

        # Add first entry
        item1 = {"type": "log_entry", "content": "Unique content" * 10}
        worker._process_item(item1)

        # Add same content again
        item2 = {"type": "log_entry", "content": "Unique content" * 10}
        worker._process_item(item2)

        # First entry should be added, second should be deduplicated
        assert worker._stats["total_entries"] == 2
        assert worker._stats["deduplicated"] == 1
        assert len(worker._session_batch.entries) == 1

    def test_lru_cache_eviction(self, worker):
        """Test that LRU cache evicts old entries when full."""
        # Fill cache beyond limit
        for i in range(worker.DEDUP_CACHE_SIZE + 100):
            content = f"Unique content {i}" * 5
            worker._mark_seen(hashlib.md5(content.encode()).hexdigest() if 'hashlib' in dir() else f"hash_{i}")

        # Cache should be limited
        assert len(worker._dedup_cache) <= worker.DEDUP_CACHE_SIZE

    def test_compress_and_store(self, worker, mock_memory_manager):
        """Test compressing and storing a batch."""
        # Create a batch with entries
        batch = SessionLogBatch()
        batch.add_entry(1, "Content A" * 20)
        batch.add_entry(1, "Content B" * 20)
        worker._session_batch = batch

        # Compress and store
        worker._compress_and_store_session()

        # Verify memory manager was called
        mock_memory_manager.record.assert_called_once()
        assert batch.compressed is True

    def test_compress_and_store_includes_entry_metadata(self, worker, mock_memory_manager):
        """Test compressed memory keeps session and profile provenance."""
        batch = SessionLogBatch()
        batch.add_entry(
            3,
            "Tool Call: read_file\nResult: loaded source file" * 3,
            entry_type="tool_call",
            metadata={
                "session_id": "session-42",
                "profile_id": "main",
                "tool": "read_file",
                "success": True,
            },
        )
        worker._session_batch = batch

        worker._compress_and_store_session()

        metadata = mock_memory_manager.record.call_args.kwargs["metadata"]
        assert metadata["session_id"] == "session-42"
        assert metadata["profile_id"] == "main"
        assert metadata["provenance"]["source"] == "log_memory_worker"
        assert metadata["entries"][0]["metadata"]["tool"] == "read_file"

    def test_compress_empty_batch_skipped(self, worker, mock_memory_manager):
        """Test that empty batches are skipped."""
        batch = SessionLogBatch()
        worker._session_batch = batch

        worker._compress_and_store_session()

        # Should not call record for empty batch
        mock_memory_manager.record.assert_not_called()

    def test_worker_start_stop(self, mock_memory_manager):
        """Test starting and stopping the worker."""
        worker = LogMemoryWorker(
            memory_manager=mock_memory_manager,
            auto_start=False,
        )
        
        # Start worker
        worker.start()
        assert worker._thread is not None
        assert worker._thread.is_alive()

        # Stop worker
        worker.stop(timeout=2.0)
        assert worker._thread is None

    def test_get_stats(self, worker):
        """Test getting worker statistics."""
        stats = worker.get_stats()
        assert "total_entries" in stats
        assert "deduplicated" in stats
        assert "stored" in stats
        assert "sessions_processed" in stats
        assert "queue_size" in stats
        assert "is_running" in stats


class TestGlobalWorker:
    """Tests for global worker functions."""

    def test_get_log_memory_worker(self):
        """Test getting the global worker."""
        # Clean up any existing worker
        shutdown_log_memory_worker()
        
        worker = get_log_memory_worker()
        assert worker is not None
        assert isinstance(worker, LogMemoryWorker)
        
        # Getting again should return same instance
        worker2 = get_log_memory_worker()
        assert worker2 is worker
        
        # Clean up
        shutdown_log_memory_worker()

    def test_shutdown_log_memory_worker(self):
        """Test shutting down the global worker."""
        worker = get_log_memory_worker()
        assert worker is not None
        
        shutdown_log_memory_worker()
        
        # Global worker should be None now
        import open_agent.log_memory_worker as module
        assert module._global_worker is None


# Import hashlib for tests that need it
import hashlib

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
