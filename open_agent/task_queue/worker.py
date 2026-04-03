"""Task worker for executing tasks in background threads.

The TaskWorker:
- Pulls tasks from the queue
- Executes them in background threads
- Reports progress and results
- Handles cancellation and errors
"""

import asyncio
import threading
import traceback
from datetime import datetime
from typing import Optional, Callable, Any

from .task import Task, TaskStatus, TaskResult
from .queue import TaskQueue


class TaskWorker:
    """Worker that executes tasks from a queue.
    
    Runs in a separate thread and processes tasks asynchronously.
    Supports progress reporting and cancellation.
    """
    
    def __init__(
        self,
        worker_id: str,
        task_queue: TaskQueue,
        executor: Callable[[Task], Any],
        on_task_complete: Optional[Callable[[Task], None]] = None,
        on_task_error: Optional[Callable[[Task, Exception], None]] = None,
    ):
        """Initialize the task worker.
        
        Args:
            worker_id: Unique identifier for this worker
            task_queue: The task queue to pull from
            executor: Function to execute tasks (can be sync or async)
            on_task_complete: Callback when a task completes successfully
            on_task_error: Callback when a task fails
        """
        self.worker_id = worker_id
        self.task_queue = task_queue
        self._executor = executor
        self._on_task_complete = on_task_complete
        self._on_task_error = on_task_error
        
        # Worker state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_task: Optional[Task] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Cancellation
        self._cancel_event = threading.Event()
        
        # Lock for current task access
        self._lock = threading.Lock()
    
    def start(self):
        """Start the worker thread."""
        if self._running:
            return
        
        self._running = True
        self._cancel_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
    
    def stop(self, wait: bool = True, timeout: float = 5.0):
        """Stop the worker thread.
        
        Args:
            wait: Whether to wait for the thread to stop
            timeout: Maximum time to wait
        """
        self._running = False
        self._cancel_event.set()
        
        if wait and self._thread:
            self._thread.join(timeout=timeout)
    
    def _run_loop(self):
        """Main worker loop - runs in separate thread."""
        # Create event loop for this thread
        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)
        
        try:
            while self._running:
                try:
                    # Get next task (blocking with timeout)
                    task = self.task_queue.get_next_task(timeout=1.0)
                    
                    if task is None:
                        continue  # Timeout, check if still running
                    
                    # Execute the task
                    with self._lock:
                        self._current_task = task
                    
                    try:
                        self._execute_task(task)
                    except Exception as e:
                        self._handle_task_error(task, e)
                    finally:
                        with self._lock:
                            self._current_task = None
                            
                except Exception as e:
                    # Log error but continue running
                    print(f"Worker {self.worker_id} error: {e}")
                    traceback.print_exc()
                    
        finally:
            self._event_loop.close()
            self._event_loop = None
    
    def _execute_task(self, task: Task):
        """Execute a single task.
        
        Args:
            task: The task to execute
        """
        # Check if already cancelled
        if self._cancel_event.is_set() or task.status == TaskStatus.CANCELLED:
            return
        
        try:
            # Execute the task
            if asyncio.iscoroutinefunction(self._executor):
                # Async executor
                result = self._event_loop.run_until_complete(
                    self._executor(task)
                )
            else:
                # Sync executor
                result = self._executor(task)
            
            # Handle result
            if isinstance(result, TaskResult):
                task.set_result(result)
            elif isinstance(result, str):
                task.set_result(TaskResult(success=True, content=result))
            elif result is None:
                task.set_result(TaskResult(success=True, content="Task completed"))
            else:
                task.set_result(TaskResult(success=True, content=str(result)))
            
            # Callback
            if self._on_task_complete:
                self._on_task_complete(task)
                
        except Exception as e:
            self._handle_task_error(task, e)
    
    def _handle_task_error(self, task: Task, error: Exception):
        """Handle task execution error.
        
        Args:
            task: The failed task
            error: The exception that occurred
        """
        error_msg = f"{type(error).__name__}: {str(error)}"
        task.set_result(TaskResult(
            success=False,
            error=error_msg,
        ))
        
        if self._on_task_error:
            self._on_task_error(task, error)
    
    def get_current_task(self) -> Optional[Task]:
        """Get the task currently being executed.
        
        Returns:
            Current task or None
        """
        with self._lock:
            return self._current_task
    
    def is_idle(self) -> bool:
        """Check if the worker is idle.
        
        Returns:
            True if not executing any task
        """
        with self._lock:
            return self._current_task is None
    
    def is_running(self) -> bool:
        """Check if the worker is running.
        
        Returns:
            True if the worker thread is active
        """
        return self._running and self._thread is not None and self._thread.is_alive()


class WorkerPool:
    """Pool of task workers for parallel execution.
    
    Manages multiple workers that can process tasks concurrently.
    """
    
    def __init__(
        self,
        task_queue: TaskQueue,
        num_workers: int = 3,
        executor: Callable[[Task], Any] = None,
        on_task_complete: Optional[Callable[[Task], None]] = None,
        on_task_error: Optional[Callable[[Task, Exception], None]] = None,
    ):
        """Initialize the worker pool.
        
        Args:
            task_queue: The task queue to process
            num_workers: Number of worker threads
            executor: Function to execute tasks
            on_task_complete: Callback for completed tasks
            on_task_error: Callback for failed tasks
        """
        self.task_queue = task_queue
        self.num_workers = num_workers
        self._executor = executor
        self._on_task_complete = on_task_complete
        self._on_task_error = on_task_error
        
        # Workers
        self._workers: list[TaskWorker] = []
        self._running = False
        
        # Lock
        self._lock = threading.Lock()
    
    def start(self):
        """Start all workers in the pool."""
        with self._lock:
            if self._running:
                return
            
            self._running = True
            
            for i in range(self.num_workers):
                worker = TaskWorker(
                    worker_id=f"worker_{i}",
                    task_queue=self.task_queue,
                    executor=self._executor,
                    on_task_complete=self._on_task_complete,
                    on_task_error=self._on_task_error,
                )
                worker.start()
                self._workers.append(worker)
    
    def stop(self, wait: bool = True, timeout: float = 5.0):
        """Stop all workers in the pool.
        
        Args:
            wait: Whether to wait for workers to stop
            timeout: Maximum time to wait per worker
        """
        with self._lock:
            self._running = False
            
            for worker in self._workers:
                worker.stop(wait=wait, timeout=timeout)
            
            self._workers.clear()
    
    def get_idle_workers(self) -> list[TaskWorker]:
        """Get list of idle workers.
        
        Returns:
            List of workers not currently executing tasks
        """
        with self._lock:
            return [w for w in self._workers if w.is_idle()]
    
    def get_busy_workers(self) -> list[TaskWorker]:
        """Get list of busy workers.
        
        Returns:
            List of workers currently executing tasks
        """
        with self._lock:
            return [w for w in self._workers if not w.is_idle()]
    
    def get_current_tasks(self) -> list[Task]:
        """Get all tasks currently being executed.
        
        Returns:
            List of current tasks
        """
        with self._lock:
            tasks = []
            for worker in self._workers:
                task = worker.get_current_task()
                if task:
                    tasks.append(task)
            return tasks
    
    def is_running(self) -> bool:
        """Check if the pool is running.
        
        Returns:
            True if any worker is active
        """
        with self._lock:
            return self._running and any(w.is_running() for w in self._workers)
    
    def get_status(self) -> dict[str, Any]:
        """Get pool status.
        
        Returns:
            Dictionary with pool status information
        """
        with self._lock:
            return {
                "num_workers": self.num_workers,
                "running": self._running,
                "idle_workers": len(self.get_idle_workers()),
                "busy_workers": len(self.get_busy_workers()),
                "current_tasks": [t.task_id for t in self.get_current_tasks()],
            }