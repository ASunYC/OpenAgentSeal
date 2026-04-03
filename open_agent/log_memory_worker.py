#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Log Memory Worker - Background thread for automatic log memory compression.

This module provides a background worker that:
1. Monitors agent step iterations
2. Compresses log content into memory using tree structure (session -> steps)
3. Stores one memory per session (not per step) for efficient querying
4. Deduplicates log entries before storing

Tree Structure Design:
- One memory record per session (not per step)
- Session contains: task summary, tools used, key decisions
- Queried by time range (today, week, month)
- Prevents database bloat as usage grows
"""

import hashlib
import queue
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .memory_manager import MemoryManager, get_memory_manager


@dataclass
class LogEntry:
    """Represents a single log entry."""

    step: int
    timestamp: str
    content: str
    entry_type: str = "general"
    content_hash: str = field(init=False)

    def __post_init__(self):
        """Generate content hash for deduplication."""
        self.content_hash = hashlib.md5(self.content.encode()).hexdigest()


@dataclass
class SessionLogBatch:
    """Batch of log entries for an entire session (multiple steps).

    Tree structure: one memory per session, not per step.
    This prevents database bloat and keeps queries fast.
    """

    session_start: str = field(default_factory=lambda: datetime.now().isoformat())
    entries: list[LogEntry] = field(default_factory=list)
    step_info: dict[int, dict[str, Any]] = field(default_factory=dict)
    total_steps: int = 0
    compressed: bool = False
    
    # Track unique tools used in this session
    tools_used: set = field(default_factory=set)
    # Track key topics/decisions
    key_topics: list = field(default_factory=list)

    def add_entry(self, step: int, content: str, entry_type: str = "general") -> LogEntry:
        """Add a log entry to the session batch."""
        entry = LogEntry(
            step=step,
            timestamp=datetime.now().isoformat(),
            content=content,
            entry_type=entry_type,
        )
        self.entries.append(entry)
        
        # Track step info
        if step not in self.step_info:
            self.step_info[step] = {
                "start_time": datetime.now().isoformat(),
                "entry_count": 0,
                "types": set(),
            }
        self.step_info[step]["entry_count"] += 1
        self.step_info[step]["types"].add(entry_type)
        
        # Track tools used
        if entry_type == "tool_call" and "Tool Call:" in content:
            import re
            match = re.search(r"Tool Call:\s*(\w+)", content)
            if match:
                self.tools_used.add(match.group(1))
        
        return entry


class LogMemoryWorker:
    """Background worker for compressing log entries into memory.

    Features:
    - Runs in a separate thread to avoid blocking agent execution
    - Tree structure: one memory per session (not per step)
    - Stores daily session summaries, not individual steps
    - Deduplicates log entries using content hashing
    - Maintains an LRU cache of recent content hashes for fast dedup
    """

    # Maximum entries in the LRU dedup cache
    DEDUP_CACHE_SIZE = 1000

    # Minimum content length to store (skip trivial logs)
    MIN_CONTENT_LENGTH = 50

    # Category for log memories
    MEMORY_CATEGORY = "conversation"

    # Importance for log memories (daily session = normal importance)
    MEMORY_IMPORTANCE = "normal"

    def __init__(
        self,
        memory_manager: Optional[MemoryManager] = None,
        auto_start: bool = True,
    ):
        """Initialize the log memory worker.

        Args:
            memory_manager: Optional MemoryManager instance. If None, uses default.
            auto_start: Whether to start the worker thread automatically.
        """
        self.memory_manager = memory_manager or get_memory_manager()

        # Queue for incoming log entries
        self._queue: queue.Queue[Optional[dict[str, Any]]] = queue.Queue()

        # LRU cache for content deduplication (ordered dict for LRU behavior)
        self._dedup_cache: OrderedDict[str, bool] = OrderedDict()

        # Current session batch (one per agent run, not per step)
        self._session_batch: Optional[SessionLogBatch] = None

        # Worker thread
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Statistics
        self._stats = {
            "total_entries": 0,
            "deduplicated": 0,
            "stored": 0,
            "sessions_processed": 0,
        }

        if auto_start:
            self.start()

    def start(self):
        """Start the background worker thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0):
        """Stop the background worker thread.

        Args:
            timeout: Maximum time to wait for the thread to finish.
        """
        if self._thread is None or not self._thread.is_alive():
            return

        # Signal the worker to stop
        self._stop_event.set()

        # Send None to unblock the queue.get() call
        self._queue.put(None)

        # Wait for the thread to finish
        self._thread.join(timeout=timeout)
        self._thread = None

    def submit_step_start(self, step: int, max_steps: int):
        """Submit a step start event.

        Creates a new session batch if this is the first step.

        Args:
            step: Current step number.
            max_steps: Maximum steps allowed.
        """
        self._queue.put({
            "type": "step_start",
            "step": step,
            "max_steps": max_steps,
        })

    def submit_log_entry(
        self,
        content: str,
        entry_type: str = "general",
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Submit a log entry for potential storage.

        Args:
            content: The log content.
            entry_type: Type of log entry (e.g., "thinking", "tool_call", "result").
            metadata: Optional additional metadata.
        """
        if not content or len(content) < self.MIN_CONTENT_LENGTH:
            return

        self._queue.put({
            "type": "log_entry",
            "content": content,
            "entry_type": entry_type,
            "metadata": metadata or {},
        })

    def submit_step_end(
        self,
        step: int,
        elapsed_time: float,
        total_time: float,
    ):
        """Submit a step end event.

        Args:
            step: Completed step number.
            elapsed_time: Time taken for this step.
            total_time: Total elapsed time.
        """
        self._queue.put({
            "type": "step_end",
            "step": step,
            "elapsed_time": elapsed_time,
            "total_time": total_time,
        })

    def _worker_loop(self):
        """Main worker loop running in background thread."""
        while not self._stop_event.is_set():
            try:
                # Wait for items from queue
                item = self._queue.get(timeout=1.0)

                if item is None:
                    # Stop signal
                    break

                self._process_item(item)

            except queue.Empty:
                # Timeout, check if we should stop
                continue
            except Exception as e:
                # Log error but continue running
                print(f"[LogMemoryWorker] Error processing item: {e}")

        # Process any remaining items before stopping
        self._flush_queue()

    def _process_item(self, item: dict[str, Any]):
        """Process a single item from the queue.

        Args:
            item: The item to process.
        """
        item_type = item.get("type")

        if item_type == "log_entry":
            self._handle_log_entry(item)
        elif item_type == "step_end":
            self._handle_step_end(item)
        elif item_type == "step_start":
            self._handle_step_start(item)

    def _handle_step_start(self, item: dict[str, Any]):
        """Handle a step start event.

        Creates new session on first step, tracks step count.

        Args:
            item: The step start item.
        """
        step = item.get("step", 1)
        max_steps = item.get("max_steps", 100)

        # Create new session batch on first step
        if step == 1 or self._session_batch is None:
            # Store previous session if exists
            if self._session_batch is not None and not self._session_batch.compressed:
                self._compress_and_store_session()
            
            # Start new session
            self._session_batch = SessionLogBatch()
            self._stats["sessions_processed"] += 1

        # Update step count
        if self._session_batch:
            self._session_batch.total_steps = max(step, self._session_batch.total_steps)

    def _handle_log_entry(self, item: dict[str, Any]):
        """Handle a log entry item.

        Args:
            item: The log entry item.
        """
        content = item.get("content", "")
        entry_type = item.get("entry_type", "general")
        metadata = item.get("metadata", {})
        content_hash = hashlib.md5(content.encode()).hexdigest()

        self._stats["total_entries"] += 1

        # Check for duplicate
        if self._is_duplicate(content_hash):
            self._stats["deduplicated"] += 1
            return

        # Create session batch if not exists
        if self._session_batch is None:
            self._session_batch = SessionLogBatch()
            self._stats["sessions_processed"] += 1

        # Determine step from metadata or use latest
        step = metadata.get("step", self._session_batch.total_steps)

        # Add entry to session batch
        self._session_batch.add_entry(step, content, entry_type)

        # Mark hash as seen
        self._mark_seen(content_hash)

    def _handle_step_end(self, item: dict[str, Any]):
        """Handle a step end event.

        Updates timing info but does NOT store immediately.
        Session is stored only when:
        1. A new session starts (step 1)
        2. Worker stops (flush)

        Args:
            item: The step end item.
        """
        step = item.get("step", 0)
        elapsed_time = item.get("elapsed_time", 0)
        total_time = item.get("total_time", 0)

        # Update step info with timing
        if self._session_batch and step in self._session_batch.step_info:
            self._session_batch.step_info[step]["elapsed_time"] = elapsed_time
            self._session_batch.step_info[step]["total_time"] = total_time

    def _compress_and_store_session(self):
        """Compress the current session and store in memory.
        
        This is the key method: stores ONE memory per session, not per step.
        This prevents database bloat and keeps queries fast.
        """
        if self._session_batch is None or not self._session_batch.entries:
            return

        batch = self._session_batch

        # Skip if already compressed
        if batch.compressed:
            return

        # Create session summary content
        summary_content = self._create_session_summary(batch)

        if not summary_content:
            batch.compressed = True
            return

        # Extract keywords for indexing
        keywords = self._extract_session_keywords(batch)

        # Store in memory (ONE record per session)
        try:
            self.memory_manager.record(
                content=summary_content,
                category=self.MEMORY_CATEGORY,
                importance=self.MEMORY_IMPORTANCE,
                keywords=keywords,
                metadata={
                    "session_start": batch.session_start,
                    "total_steps": batch.total_steps,
                    "total_entries": len(batch.entries),
                    "tools_used": list(batch.tools_used),
                }
            )
            self._stats["stored"] += 1
            batch.compressed = True
            print(f"[LogMemoryWorker] Session stored: {batch.total_steps} steps, {len(batch.entries)} entries")

        except Exception as e:
            print(f"[LogMemoryWorker] Failed to store session memory: {e}")

    def _create_session_summary(self, batch: SessionLogBatch) -> str:
        """Create a concise session summary from all entries.

        Args:
            batch: The session log batch.

        Returns:
            Formatted summary content.
        """
        if not batch.entries:
            return ""

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Build summary parts
        lines = []
        lines.append(f"[Session Summary] {timestamp}")
        lines.append(f"Duration: {batch.session_start.split('T')[0]} to {timestamp}")
        lines.append(f"Total Steps: {batch.total_steps}")
        
        # Tools used
        if batch.tools_used:
            lines.append(f"Tools Used: {', '.join(sorted(batch.tools_used))}")
        
        lines.append("")  # Empty line
        
        # Key activities (grouped by step, truncated)
        # Take at most 5 steps with most activity
        step_entries = {}
        for entry in batch.entries:
            if entry.step not in step_entries:
                step_entries[entry.step] = []
            step_entries[entry.step].append(entry)
        
        # Get top steps by activity
        top_steps = sorted(step_entries.keys(), key=lambda s: len(step_entries[s]), reverse=True)[:5]
        
        for step in sorted(top_steps):
            entries = step_entries[step]
            lines.append(f"### Step {step}")
            
            for entry in entries[:3]:  # Max 3 entries per step
                # Truncate long content
                content_preview = entry.content[:300]
                if len(entry.content) > 300:
                    content_preview += "..."
                lines.append(f"- [{entry.entry_type}] {content_preview}")
            
            if len(entries) > 3:
                lines.append(f"  ... and {len(entries) - 3} more entries")
            
            lines.append("")  # Empty line between steps

        return "\n".join(lines)

    def _extract_session_keywords(self, batch: SessionLogBatch) -> list[str]:
        """Extract keywords from session for indexing.

        Args:
            batch: The session log batch.

        Returns:
            List of extracted keywords.
        """
        keywords = []

        # Add date keywords
        keywords.append(datetime.now().strftime("%Y-%m-%d"))
        keywords.append(datetime.now().strftime("%Y-%m"))

        # Add tools used as keywords
        keywords.extend(list(batch.tools_used))

        # Add step keywords
        if batch.total_steps > 0:
            keywords.append(f"session_{batch.total_steps}_steps")

        # Extract keywords from first few entries (most important)
        for entry in batch.entries[:5]:
            # Look for important patterns
            import re
            
            # File patterns
            files = re.findall(r'[\w/\\-]+\.(py|js|ts|json|md|txt|yaml)', entry.content)
            keywords.extend(files[:2])
            
            # Error patterns
            if "error" in entry.content.lower() or "failed" in entry.content.lower():
                keywords.append("error")

        return list(set(keywords))[:15]  # Dedupe and limit

    def _is_duplicate(self, content_hash: str) -> bool:
        """Check if content hash is already seen.

        Args:
            content_hash: The content hash to check.

        Returns:
            True if duplicate, False otherwise.
        """
        if content_hash in self._dedup_cache:
            # Move to end for LRU
            self._dedup_cache.move_to_end(content_hash)
            return True
        return False

    def _mark_seen(self, content_hash: str):
        """Mark a content hash as seen.

        Args:
            content_hash: The content hash to mark.
        """
        self._dedup_cache[content_hash] = True

        # Enforce cache size limit
        while len(self._dedup_cache) > self.DEDUP_CACHE_SIZE:
            # Remove oldest (first) item
            self._dedup_cache.popitem(last=False)

    def _flush_queue(self):
        """Flush remaining items in queue."""
        while True:
            try:
                item = self._queue.get_nowait()
                if item is not None:
                    self._process_item(item)
            except queue.Empty:
                break

        # Store the current session
        if self._session_batch is not None and not self._session_batch.compressed:
            self._compress_and_store_session()

    def get_stats(self) -> dict[str, Any]:
        """Get worker statistics.

        Returns:
            Dictionary of statistics.
        """
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
            "dedup_cache_size": len(self._dedup_cache),
            "is_running": self._thread is not None and self._thread.is_alive(),
            "has_active_session": self._session_batch is not None,
        }


# Global worker instance (lazy initialization)
_global_worker: Optional[LogMemoryWorker] = None


def get_log_memory_worker() -> LogMemoryWorker:
    """Get the global log memory worker instance.

    Returns:
        The global LogMemoryWorker instance.
    """
    global _global_worker
    if _global_worker is None:
        _global_worker = LogMemoryWorker()
    return _global_worker


def shutdown_log_memory_worker():
    """Shutdown the global log memory worker."""
    global _global_worker
    if _global_worker is not None:
        _global_worker.stop()
        _global_worker = None