"""Task queue system for async agent execution.

This module provides a task queue system that enables:
- Asynchronous task execution without blocking the UI
- Real-time progress feedback to users
- Parallel task execution
- Master agent coordination with sub-agents
"""

from .task import Task, TaskStatus, TaskPriority, TaskProgress, TaskResult, SubTask
from .queue import TaskQueue
from .worker import TaskWorker, WorkerPool
from .dispatcher import TaskDispatcher, create_task_dispatcher, get_task_dispatcher

__all__ = [
    # Core classes
    "Task",
    "TaskStatus",
    "TaskPriority",
    "TaskProgress",
    "TaskResult",
    "SubTask",
    "TaskQueue",
    "TaskWorker",
    "WorkerPool",
    "TaskDispatcher",
    # Convenience functions
    "create_task_dispatcher",
    "get_task_dispatcher",
]
