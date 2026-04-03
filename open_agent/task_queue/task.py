"""Task data structure for the task queue system.

A Task represents a unit of work that can be executed by an agent.
It tracks the original user input, execution status, progress, and results.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Callable, Awaitable
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a task in the queue."""
    
    PENDING = "pending"  # Waiting to be picked up
    QUEUED = "queued"    # In the queue, waiting for worker
    RUNNING = "running"  # Currently being executed
    PAUSED = "paused"    # Temporarily paused
    COMPLETED = "completed"  # Successfully finished
    FAILED = "failed"    # Execution failed
    CANCELLED = "cancelled"  # Cancelled by user


class TaskPriority(int, Enum):
    """Priority levels for task scheduling."""
    
    LOW = 1
    NORMAL = 5
    HIGH = 10
    URGENT = 20


class TaskProgress(BaseModel):
    """Progress information for a running task."""
    
    current_step: int = 0
    total_steps: int = 0
    current_action: str = ""
    percentage: float = 0.0
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: Optional[float] = None
    
    def update(self, step: int, action: str = ""):
        """Update progress with new step information."""
        self.current_step = step
        self.current_action = action
        if self.total_steps > 0:
            self.percentage = (step / self.total_steps) * 100


class TaskResult(BaseModel):
    """Result of a completed task."""
    
    success: bool
    content: str = ""
    error: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0
    steps_taken: int = 0
    execution_time_seconds: float = 0.0


class Task:
    """A task in the agent task queue.
    
    Represents a unit of work that can be executed by an agent.
    Supports async execution with progress tracking and cancellation.
    """
    
    def __init__(
        self,
        user_input: str,
        task_id: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        parent_task_id: Optional[str] = None,
        assigned_agent_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        on_progress: Optional[Callable[[TaskProgress], None]] = None,
        on_complete: Optional[Callable[["Task"], None]] = None,
    ):
        """Initialize a new task.
        
        Args:
            user_input: The original user input/request
            task_id: Unique identifier (auto-generated if not provided)
            priority: Task priority for scheduling
            parent_task_id: ID of parent task if this is a subtask
            assigned_agent_id: ID of agent assigned to this task
            context: Additional context data for the task
            on_progress: Callback for progress updates
            on_complete: Callback when task completes
        """
        self.task_id = task_id or self._generate_id()
        self.user_input = user_input
        self.priority = priority
        self.parent_task_id = parent_task_id
        self.assigned_agent_id = assigned_agent_id
        self.context = context or {}
        
        # Callbacks
        self._on_progress = on_progress
        self._on_complete = on_complete
        
        # Status tracking
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        
        # Progress tracking
        self.progress = TaskProgress()
        
        # Result
        self.result: Optional[TaskResult] = None
        
        # Execution tracking
        self._current_status_message: str = ""
        self._log_entries: list[dict[str, Any]] = []
    
    @staticmethod
    def _generate_id() -> str:
        """Generate a unique task ID."""
        return f"task_{uuid.uuid4().hex[:8]}"
    
    def set_status(self, status: TaskStatus, message: str = ""):
        """Update task status.
        
        Args:
            status: New status
            message: Optional status message
        """
        self.status = status
        self._current_status_message = message
        
        if status == TaskStatus.RUNNING and self.started_at is None:
            self.started_at = datetime.now()
        
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.completed_at = datetime.now()
        
        self._add_log_entry(f"Status changed to {status.value}", {"message": message})
    
    def update_progress(self, step: int, total_steps: int, action: str = ""):
        """Update task progress.
        
        Args:
            step: Current step number
            total_steps: Total number of steps
            action: Description of current action
        """
        self.progress.total_steps = total_steps
        self.progress.update(step, action)
        
        # Calculate elapsed time
        if self.started_at:
            elapsed = (datetime.now() - self.started_at).total_seconds()
            self.progress.elapsed_seconds = elapsed
            
            # Estimate remaining time
            if step > 0 and total_steps > 0:
                avg_time_per_step = elapsed / step
                remaining_steps = total_steps - step
                self.progress.estimated_remaining_seconds = avg_time_per_step * remaining_steps
        
        # Call progress callback
        if self._on_progress:
            self._on_progress(self.progress)
        
        self._add_log_entry(f"Progress: {step}/{total_steps}", {"action": action})
    
    def set_result(self, result: TaskResult):
        """Set the task result.
        
        Args:
            result: The task result
        """
        self.result = result
        
        if result.success:
            self.set_status(TaskStatus.COMPLETED, "Task completed successfully")
        else:
            self.set_status(TaskStatus.FAILED, result.error or "Task failed")
        
        # Call completion callback
        if self._on_complete:
            self._on_complete(self)
    
    def cancel(self, reason: str = "Cancelled by user"):
        """Cancel the task.
        
        Args:
            reason: Reason for cancellation
        """
        if self.status in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED):
            self.set_status(TaskStatus.CANCELLED, reason)
            self.result = TaskResult(
                success=False,
                error=reason,
            )
            
            if self._on_complete:
                self._on_complete(self)
    
    def get_status_message(self) -> str:
        """Get the current status message.
        
        Returns:
            Human-readable status message
        """
        if self._current_status_message:
            return self._current_status_message
        
        if self.status == TaskStatus.PENDING:
            return "Waiting to be processed..."
        elif self.status == TaskStatus.QUEUED:
            return "In queue, waiting for available worker..."
        elif self.status == TaskStatus.RUNNING:
            if self.progress.current_action:
                return self.progress.current_action
            return "Processing..."
        elif self.status == TaskStatus.PAUSED:
            return "Task is paused"
        elif self.status == TaskStatus.COMPLETED:
            return "Task completed"
        elif self.status == TaskStatus.FAILED:
            return f"Task failed: {self.result.error if self.result else 'Unknown error'}"
        elif self.status == TaskStatus.CANCELLED:
            return "Task cancelled"
        
        return "Unknown status"
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds.
        
        Returns:
            Elapsed time since task started, or 0 if not started
        """
        if self.started_at is None:
            return 0.0
        
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()
    
    def _add_log_entry(self, action: str, data: Optional[dict] = None):
        """Add a log entry for this task.
        
        Args:
            action: Description of the action
            data: Additional data to log
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "data": data or {},
            "status": self.status.value,
        }
        self._log_entries.append(entry)
    
    def get_log_entries(self) -> list[dict[str, Any]]:
        """Get all log entries for this task.
        
        Returns:
            List of log entry dictionaries
        """
        return self._log_entries.copy()
    
    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary representation.
        
        Returns:
            Dictionary containing task information
        """
        return {
            "task_id": self.task_id,
            "user_input": self.user_input,
            "priority": self.priority.value,
            "parent_task_id": self.parent_task_id,
            "assigned_agent_id": self.assigned_agent_id,
            "status": self.status.value,
            "status_message": self.get_status_message(),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": {
                "current_step": self.progress.current_step,
                "total_steps": self.progress.total_steps,
                "percentage": self.progress.percentage,
                "current_action": self.progress.current_action,
                "elapsed_seconds": self.progress.elapsed_seconds,
            },
            "result": self.result.model_dump() if self.result else None,
        }
    
    def __repr__(self) -> str:
        return f"Task(id={self.task_id}, status={self.status.value}, input={self.user_input[:30]}...)"


class SubTask(Task):
    """A subtask that can be delegated to a sub-agent.
    
    Extends Task with additional fields for sub-agent delegation.
    """
    
    def __init__(
        self,
        user_input: str,
        role: str,
        task_id: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        parent_task_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        on_progress: Optional[Callable[[TaskProgress], None]] = None,
        on_complete: Optional[Callable[[Task], None]] = None,
    ):
        """Initialize a new subtask.
        
        Args:
            user_input: The original user input/request
            role: The role type for the sub-agent
            task_id: Unique identifier
            priority: Task priority
            parent_task_id: ID of parent task (required for subtasks)
            context: Additional context data
            on_progress: Progress callback
            on_complete: Completion callback
        """
        super().__init__(
            user_input=user_input,
            task_id=task_id,
            priority=priority,
            parent_task_id=parent_task_id,
            context=context,
            on_progress=on_progress,
            on_complete=on_complete,
        )
        self.role = role
        self.is_parallel = False  # Whether this subtask can run in parallel
    
    def to_dict(self) -> dict[str, Any]:
        """Convert subtask to dictionary representation."""
        data = super().to_dict()
        data["role"] = self.role
        data["is_parallel"] = self.is_parallel
        return data