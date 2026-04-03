"""Task queue for managing and scheduling tasks.

The TaskQueue provides:
- Priority-based task scheduling
- Parallel task execution
- Thread-safe operations
- Event-driven notifications
"""

import asyncio
import threading
import heapq
from collections import defaultdict
from datetime import datetime
from typing import Optional, Callable, Any
from queue import PriorityQueue, Empty

from .task import Task, TaskStatus, TaskPriority


class TaskQueue:
    """A thread-safe priority queue for tasks.
    
    Supports:
    - Priority-based ordering
    - Parallel execution limits
    - Status tracking
    - Event callbacks
    """
    
    def __init__(
        self,
        max_parallel: int = 3,
        on_task_added: Optional[Callable[[Task], None]] = None,
        on_task_status_changed: Optional[Callable[[Task, TaskStatus], None]] = None,
    ):
        """Initialize the task queue.
        
        Args:
            max_parallel: Maximum number of parallel tasks
            on_task_added: Callback when a task is added
            on_task_status_changed: Callback when task status changes
        """
        self.max_parallel = max_parallel
        
        # Callbacks
        self._on_task_added = on_task_added
        self._on_task_status_changed = on_task_status_changed
        
        # Internal storage
        self._queue: list[tuple[int, int, Task]] = []  # (-priority, order, task)
        self._counter = 0  # For FIFO ordering within same priority
        self._tasks: dict[str, Task] = {}  # task_id -> Task
        self._running_tasks: dict[str, Task] = {}
        
        # Lock for thread safety
        self._lock = threading.RLock()
        
        # Event for queue not empty
        self._not_empty = threading.Event()
        
        # Statistics
        self._stats = {
            "total_added": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_cancelled": 0,
        }
    
    def add_task(self, task: Task) -> str:
        """Add a task to the queue.
        
        Args:
            task: The task to add
            
        Returns:
            The task ID
        """
        with self._lock:
            # Set status to queued
            task.set_status(TaskStatus.QUEUED)
            
            # Add to storage
            self._tasks[task.task_id] = task
            
            # Add to priority queue (negative priority for max-heap behavior)
            heapq.heappush(
                self._queue,
                (-task.priority.value, self._counter, task)
            )
            self._counter += 1
            
            # Update stats
            self._stats["total_added"] += 1
            
            # Signal that queue is not empty
            self._not_empty.set()
        
        # Call callback outside lock
        if self._on_task_added:
            self._on_task_added(task)
        
        return task.task_id
    
    def get_next_task(self, timeout: Optional[float] = None) -> Optional[Task]:
        """Get the next highest priority task from the queue.
        
        Args:
            timeout: Maximum time to wait for a task (None = wait forever)
            
        Returns:
            The next task, or None if timeout
        """
        with self._lock:
            while True:
                if self._queue:
                    _, _, task = heapq.heappop(self._queue)
                    
                    # Skip if task was cancelled while waiting
                    if task.status == TaskStatus.CANCELLED:
                        continue
                    
                    # Mark as running
                    task.set_status(TaskStatus.RUNNING)
                    self._running_tasks[task.task_id] = task
                    
                    # Clear event if queue is empty
                    if not self._queue:
                        self._not_empty.clear()
                    
                    return task
                
                # Wait for a task to be added
                self._lock.release()
                try:
                    got_task = self._not_empty.wait(timeout)
                    if not got_task:
                        return None  # Timeout
                finally:
                    self._lock.acquire()
    
    def peek_next_task(self) -> Optional[Task]:
        """Peek at the next task without removing it.
        
        Returns:
            The next task, or None if queue is empty
        """
        with self._lock:
            if not self._queue:
                return None
            return self._queue[0][2]
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID.
        
        Args:
            task_id: The task identifier
            
        Returns:
            The task if found, None otherwise
        """
        return self._tasks.get(task_id)
    
    def complete_task(self, task_id: str, success: bool = True, error: str = None):
        """Mark a task as completed.
        
        Args:
            task_id: The task identifier
            success: Whether the task succeeded
            error: Error message if failed
        """
        with self._lock:
            task = self._running_tasks.pop(task_id, None)
            if not task:
                task = self._tasks.get(task_id)
            
            if task:
                from .task import TaskResult
                task.set_result(TaskResult(
                    success=success,
                    error=error,
                    execution_time_seconds=task.get_elapsed_time(),
                ))
                
                # Update stats
                if success:
                    self._stats["total_completed"] += 1
                else:
                    self._stats["total_failed"] += 1
                
                # Call callback
                if self._on_task_status_changed:
                    self._on_task_status_changed(task, task.status)
    
    def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a task.
        
        Args:
            task_id: The task identifier
            reason: Reason for cancellation
            
        Returns:
            True if cancelled, False if not found or already done
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False
            
            task.cancel(reason)
            
            # Remove from running if there
            if task_id in self._running_tasks:
                del self._running_tasks[task_id]
            
            # Update stats
            self._stats["total_cancelled"] += 1
            
            # Call callback
            if self._on_task_status_changed:
                self._on_task_status_changed(task, TaskStatus.CANCELLED)
            
            return True
    
    def pause_task(self, task_id: str) -> bool:
        """Pause a running task.
        
        Args:
            task_id: The task identifier
            
        Returns:
            True if paused, False otherwise
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status != TaskStatus.RUNNING:
                return False
            
            task.set_status(TaskStatus.PAUSED)
            
            if self._on_task_status_changed:
                self._on_task_status_changed(task, TaskStatus.PAUSED)
            
            return True
    
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task.
        
        Args:
            task_id: The task identifier
            
        Returns:
            True if resumed, False otherwise
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status != TaskStatus.PAUSED:
                return False
            
            task.set_status(TaskStatus.RUNNING)
            
            if self._on_task_status_changed:
                self._on_task_status_changed(task, TaskStatus.RUNNING)
            
            return True
    
    def get_all_tasks(self) -> list[Task]:
        """Get all tasks.
        
        Returns:
            List of all tasks
        """
        with self._lock:
            return list(self._tasks.values())
    
    def get_pending_tasks(self) -> list[Task]:
        """Get all pending/queued tasks.
        
        Returns:
            List of pending tasks
        """
        with self._lock:
            return [
                task for task in self._tasks.values()
                if task.status in (TaskStatus.PENDING, TaskStatus.QUEUED)
            ]
    
    def get_running_tasks(self) -> list[Task]:
        """Get all running tasks.
        
        Returns:
            List of running tasks
        """
        with self._lock:
            return list(self._running_tasks.values())
    
    def get_completed_tasks(self) -> list[Task]:
        """Get all completed tasks.
        
        Returns:
            List of completed tasks (including failed and cancelled)
        """
        with self._lock:
            return [
                task for task in self._tasks.values()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
    
    def get_tasks_by_parent(self, parent_id: str) -> list[Task]:
        """Get all subtasks of a parent task.
        
        Args:
            parent_id: The parent task ID
            
        Returns:
            List of subtasks
        """
        with self._lock:
            return [
                task for task in self._tasks.values()
                if task.parent_task_id == parent_id
            ]
    
    def clear_completed(self) -> int:
        """Remove all completed tasks from tracking.
        
        Returns:
            Number of tasks removed
        """
        with self._lock:
            to_remove = [
                task_id for task_id, task in self._tasks.items()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
            
            for task_id in to_remove:
                del self._tasks[task_id]
            
            return len(to_remove)
    
    def get_queue_size(self) -> int:
        """Get the number of tasks waiting in queue.
        
        Returns:
            Number of queued tasks
        """
        with self._lock:
            return len(self._queue)
    
    def get_running_count(self) -> int:
        """Get the number of currently running tasks.
        
        Returns:
            Number of running tasks
        """
        with self._lock:
            return len(self._running_tasks)
    
    def can_start_more(self) -> bool:
        """Check if more tasks can be started.
        
        Returns:
            True if below parallel limit
        """
        with self._lock:
            return len(self._running_tasks) < self.max_parallel
    
    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics.
        
        Returns:
            Dictionary of statistics
        """
        with self._lock:
            return {
                **self._stats,
                "current_queued": len(self._queue),
                "current_running": len(self._running_tasks),
                "max_parallel": self.max_parallel,
            }
    
    def __len__(self) -> int:
        """Get the number of tasks in queue (not including running)."""
        with self._lock:
            return len(self._queue)
    
    def __contains__(self, task_id: str) -> bool:
        """Check if a task is in the queue."""
        return task_id in self._tasks