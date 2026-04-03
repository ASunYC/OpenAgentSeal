"""Task dispatcher for coordinating task execution.

The TaskDispatcher is the main coordinator that:
- Manages the task queue and worker pool
- Coordinates with master agent for task delegation
- Provides real-time status updates to UI
"""

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any, TYPE_CHECKING

from .task import Task, TaskStatus, TaskPriority, SubTask, TaskResult
from .queue import TaskQueue
from .worker import WorkerPool

if TYPE_CHECKING:
    from ..agent import Agent


class TaskDispatcher:
    """Central coordinator for task execution.

    This is the main entry point for the task queue system:
    - Submits tasks to the queue
    - Manages worker pool for parallel execution
    - Coordinates with master agent and sub-agents
    - Provides status updates and feedback
    """

    _instance: Optional["TaskDispatcher"] = None

    def __init__(
        self,
        max_workers: int = 3,
        workspace_dir: Optional[Path] = None,
        on_task_update: Optional[Callable[[Task], None]] = None,
        on_status_change: Optional[Callable[[str, str], None]] = None,
    ):
        """Initialize the task dispatcher.

        Args:
            max_workers: Maximum number of parallel workers
            workspace_dir: Workspace directory for agents
            on_task_update: Callback when task status/progress updates
            on_status_change: Callback when overall status changes
        """
        self.max_workers = max_workers
        self.workspace_dir = workspace_dir or Path("./workspace")

        # Callbacks
        self._on_task_update = on_task_update
        self._on_status_change = on_status_change

        # Task queue
        self._queue = TaskQueue(
            max_parallel=max_workers,
            on_task_added=self._handle_task_added,
            on_task_status_changed=self._handle_task_status_changed,
        )

        # Worker pool
        self._worker_pool = WorkerPool(
            task_queue=self._queue,
            num_workers=max_workers,
            executor=self._execute_task,
            on_task_complete=self._handle_task_complete,
            on_task_error=self._handle_task_error,
        )

        # Agent references (set later)
        self._main_agent: Optional["Agent"] = None

        # Current status
        self._current_status = "idle"
        self._status_message = ""

        # Running flag
        self._running = False

        # Lock for thread safety
        self._lock = threading.RLock()

        # Event loop reference (for async calls from sync context)
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def get_instance(cls) -> Optional["TaskDispatcher"]:
        """Get the singleton instance."""
        return cls._instance

    @classmethod
    def set_instance(cls, instance: "TaskDispatcher"):
        """Set the singleton instance."""
        cls._instance = instance

    def initialize(
        self,
        main_agent: "Agent",
    ):
        """Initialize with agent references.

        Args:
            main_agent: The main agent instance
        """
        with self._lock:
            self._main_agent = main_agent

            # Start the worker pool
            self._worker_pool.start()
            self._running = True

            # Update status
            self._set_status("ready", "Ready to accept tasks")

    def shutdown(self, wait: bool = True, timeout: float = 5.0):
        """Shutdown the dispatcher.

        Args:
            wait: Whether to wait for running tasks
            timeout: Maximum time to wait
        """
        with self._lock:
            self._running = False
            self._worker_pool.stop(wait=wait, timeout=timeout)
            self._set_status("shutdown", "Dispatcher shut down")

    def submit_task(
        self,
        user_input: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        context: Optional[dict[str, Any]] = None,
        on_progress: Optional[Callable[[Any], None]] = None,
        on_complete: Optional[Callable[[Task], None]] = None,
    ) -> Task:
        """Submit a new task to the queue.

        Args:
            user_input: The user's original input
            priority: Task priority
            context: Additional context
            on_progress: Progress callback
            on_complete: Completion callback

        Returns:
            The created Task
        """
        task = Task(
            user_input=user_input,
            priority=priority,
            context=context,
            on_progress=on_progress,
            on_complete=on_complete,
        )

        self._queue.add_task(task)

        self._set_status("processing", f"Task submitted: {task.task_id}")

        return task

    def submit_subtask(
        self,
        user_input: str,
        role: str,
        parent_task_id: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        context: Optional[dict[str, Any]] = None,
        is_parallel: bool = False,
        on_progress: Optional[Callable[[Any], None]] = None,
        on_complete: Optional[Callable[[Task], None]] = None,
    ) -> SubTask:
        """Submit a subtask for a sub-agent.

        Args:
            user_input: The task description
            role: The role type for the sub-agent
            parent_task_id: ID of parent task
            priority: Task priority
            context: Additional context
            is_parallel: Whether this can run in parallel
            on_progress: Progress callback
            on_complete: Completion callback

        Returns:
            The created SubTask
        """
        subtask = SubTask(
            user_input=user_input,
            role=role,
            priority=priority,
            parent_task_id=parent_task_id,
            context=context,
            on_progress=on_progress,
            on_complete=on_complete,
        )
        subtask.is_parallel = is_parallel

        self._queue.add_task(subtask)

        return subtask

    def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a task.

        Args:
            task_id: The task ID
            reason: Cancellation reason

        Returns:
            True if cancelled, False otherwise
        """
        return self._queue.cancel_task(task_id, reason)

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            The task if found
        """
        return self._queue.get_task(task_id)

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks.

        Returns:
            List of all tasks
        """
        return self._queue.get_all_tasks()

    def get_running_tasks(self) -> list[Task]:
        """Get all running tasks.

        Returns:
            List of running tasks
        """
        return self._queue.get_running_tasks()

    def get_pending_tasks(self) -> list[Task]:
        """Get all pending tasks.

        Returns:
            List of pending tasks
        """
        return self._queue.get_pending_tasks()

    def get_completed_tasks(self) -> list[Task]:
        """Get all completed tasks.

        Returns:
            List of completed tasks
        """
        return self._queue.get_completed_tasks()

    def get_status(self) -> dict[str, Any]:
        """Get current dispatcher status.

        Returns:
            Status dictionary
        """
        with self._lock:
            queue_stats = self._queue.get_stats()
            worker_status = self._worker_pool.get_status()

            return {
                "status": self._current_status,
                "status_message": self._status_message,
                "running": self._running,
                "queue_stats": queue_stats,
                "worker_status": worker_status,
            }

    def get_task_status_message(self, task_id: str) -> str:
        """Get human-readable status for a task.

        Args:
            task_id: The task identifier

        Returns:
            Status message string
        """
        task = self._queue.get_task(task_id)
        if not task:
            return f"Task {task_id} not found"

        return task.get_status_message()

    def get_current_activity(self) -> str:
        """Get description of current activity.

        Returns:
            Human-readable description of what's happening
        """
        with self._lock:
            running = self._queue.get_running_tasks()

            if not running:
                if self._queue.get_queue_size() > 0:
                    return f"Waiting to process {self._queue.get_queue_size()} queued tasks"
                return "Idle - no tasks running"

            if len(running) == 1:
                task = running[0]
                msg = task.get_status_message()
                return f"Working on: {msg}"

            return f"Processing {len(running)} tasks in parallel"

    # Internal methods

    def _execute_task(self, task: Task) -> TaskResult:
        """Execute a task (called by worker).

        Args:
            task: The task to execute

        Returns:
            Task result
        """
        # Update progress
        task.update_progress(0, 1, "Starting task execution...")

        try:
            # Execute with main agent
            return self._execute_with_main_agent(task)

        except Exception as e:
            return TaskResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
            )

    def _execute_with_main_agent(self, task: Task) -> TaskResult:
        """Execute a task using the main agent.

        Args:
            task: The task to execute

        Returns:
            Task result
        """
        if not self._main_agent:
            return TaskResult(
                success=False,
                error="Main agent not initialized",
            )

        # Add task as user message
        self._main_agent.add_user_message(task.user_input)

        # Update progress
        task.update_progress(1, 1, "Processing with main agent...")

        # Create cancellation event
        cancel_event = asyncio.Event()

        # Run the agent in its own event loop
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)

            # Create task for agent run
            async def run_with_cancel():
                # Set up cancellation monitoring
                def check_cancel():
                    if task.status == TaskStatus.CANCELLED:
                        cancel_event.set()

                # Run agent with cancellation support
                self._main_agent.cancel_event = cancel_event
                result = await self._main_agent.run()
                return result

            result = loop.run_until_complete(run_with_cancel())

            return TaskResult(
                success=True,
                content=result,
            )

        finally:
            loop.close()

    def _handle_task_added(self, task: Task):
        """Handle task added to queue."""
        if self._on_task_update:
            self._on_task_update(task)

    def _handle_task_status_changed(self, task: Task, status: TaskStatus):
        """Handle task status change."""
        if self._on_task_update:
            self._on_task_update(task)

        # Update dispatcher status
        running = self._queue.get_running_tasks()
        if running:
            self._set_status("processing", f"Processing {len(running)} task(s)")
        elif self._queue.get_queue_size() > 0:
            self._set_status(
                "queued", f"{self._queue.get_queue_size()} task(s) waiting"
            )
        else:
            self._set_status("ready", "Ready for new tasks")

    def _handle_task_complete(self, task: Task):
        """Handle task completion."""
        if self._on_task_update:
            self._on_task_update(task)

    def _handle_task_error(self, task: Task, error: Exception):
        """Handle task error."""
        if self._on_task_update:
            self._on_task_update(task)

    def _set_status(self, status: str, message: str):
        """Set dispatcher status."""
        with self._lock:
            self._current_status = status
            self._status_message = message

        if self._on_status_change:
            self._on_status_change(status, message)

    def __repr__(self) -> str:
        return f"TaskDispatcher(status={self._current_status}, running={self._running})"


# Convenience functions for CLI integration


def create_task_dispatcher(
    max_workers: int = 3,
    workspace_dir: Optional[Path] = None,
) -> TaskDispatcher:
    """Create and return a TaskDispatcher instance.

    Args:
        max_workers: Maximum parallel workers
        workspace_dir: Workspace directory

    Returns:
        TaskDispatcher instance
    """
    dispatcher = TaskDispatcher(
        max_workers=max_workers,
        workspace_dir=workspace_dir,
    )
    TaskDispatcher.set_instance(dispatcher)
    return dispatcher


def get_task_dispatcher() -> Optional[TaskDispatcher]:
    """Get the global TaskDispatcher instance.

    Returns:
        TaskDispatcher instance or None
    """
    return TaskDispatcher.get_instance()
