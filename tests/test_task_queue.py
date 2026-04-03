"""Tests for the task queue system."""

import asyncio
import threading
import time
from pathlib import Path

import pytest

from open_agent.task_queue import (
    Task,
    TaskStatus,
    TaskPriority,
    TaskProgress,
    TaskResult,
    SubTask,
    TaskQueue,
    TaskWorker,
    WorkerPool,
    TaskDispatcher,
    TaskStatusDisplay,
    TaskCommandHandler,
)


class TestTask:
    """Tests for Task class."""
    
    def test_task_creation(self):
        """Test basic task creation."""
        task = Task(user_input="Test task")
        
        assert task.task_id.startswith("task_")
        assert task.user_input == "Test task"
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.NORMAL
        assert task.parent_task_id is None
        assert task.assigned_agent_id is None
    
    def test_task_with_custom_id(self):
        """Test task with custom ID."""
        task = Task(user_input="Test", task_id="custom_123")
        
        assert task.task_id == "custom_123"
    
    def test_task_priority(self):
        """Test task priority."""
        low_task = Task(user_input="Low", priority=TaskPriority.LOW)
        high_task = Task(user_input="High", priority=TaskPriority.HIGH)
        urgent_task = Task(user_input="Urgent", priority=TaskPriority.URGENT)
        
        assert low_task.priority == TaskPriority.LOW
        assert high_task.priority == TaskPriority.HIGH
        assert urgent_task.priority == TaskPriority.URGENT
    
    def test_set_status(self):
        """Test status changes."""
        task = Task(user_input="Test")
        
        task.set_status(TaskStatus.QUEUED)
        assert task.status == TaskStatus.QUEUED
        
        task.set_status(TaskStatus.RUNNING, "Processing")
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None
    
    def test_update_progress(self):
        """Test progress updates."""
        task = Task(user_input="Test")
        task.set_status(TaskStatus.RUNNING)
        
        task.update_progress(1, 5, "Step 1")
        
        assert task.progress.current_step == 1
        assert task.progress.total_steps == 5
        assert task.progress.percentage == 20.0
        assert task.progress.current_action == "Step 1"
    
    def test_set_result(self):
        """Test setting result."""
        task = Task(user_input="Test")
        task.set_status(TaskStatus.RUNNING)
        
        result = TaskResult(success=True, content="Done", steps_taken=3)
        task.set_result(result)
        
        assert task.result == result
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
    
    def test_cancel(self):
        """Test task cancellation."""
        task = Task(user_input="Test")
        
        task.cancel("User cancelled")
        
        assert task.status == TaskStatus.CANCELLED
        assert task.result is not None
        assert task.result.success is False
        assert "cancelled" in task.result.error.lower()
    
    def test_get_status_message(self):
        """Test status message generation."""
        task = Task(user_input="Test")
        
        assert "waiting" in task.get_status_message().lower()
        
        task.set_status(TaskStatus.RUNNING)
        task.update_progress(1, 3, "Working")
        
        assert task.get_status_message() == "Working"
    
    def test_get_elapsed_time(self):
        """Test elapsed time calculation."""
        task = Task(user_input="Test")
        
        # Not started yet
        assert task.get_elapsed_time() == 0.0
        
        task.set_status(TaskStatus.RUNNING)
        time.sleep(0.1)
        
        elapsed = task.get_elapsed_time()
        assert elapsed >= 0.1
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        task = Task(user_input="Test task", priority=TaskPriority.HIGH)
        task.set_status(TaskStatus.RUNNING)
        
        data = task.to_dict()
        
        assert data["task_id"] == task.task_id
        assert data["user_input"] == "Test task"
        assert data["priority"] == TaskPriority.HIGH.value
        assert data["status"] == TaskStatus.RUNNING.value


class TestSubTask:
    """Tests for SubTask class."""
    
    def test_subtask_creation(self):
        """Test subtask creation."""
        subtask = SubTask(
            user_input="Subtask test",
            role="code_expert",
            parent_task_id="task_parent",
        )
        
        assert subtask.role == "code_expert"
        assert subtask.parent_task_id == "task_parent"
        assert subtask.is_parallel is False
    
    def test_subtask_to_dict(self):
        """Test subtask dictionary conversion."""
        subtask = SubTask(
            user_input="Test",
            role="doc_master",
            parent_task_id="task_123",
        )
        
        data = subtask.to_dict()
        
        assert data["role"] == "doc_master"
        assert data["is_parallel"] is False


class TestTaskQueue:
    """Tests for TaskQueue class."""
    
    def test_queue_creation(self):
        """Test queue creation."""
        queue = TaskQueue(max_parallel=5)
        
        assert queue.max_parallel == 5
        assert queue.get_queue_size() == 0
    
    def test_add_task(self):
        """Test adding tasks to queue."""
        queue = TaskQueue()
        task = Task(user_input="Test")
        
        task_id = queue.add_task(task)
        
        assert task_id == task.task_id
        assert task.status == TaskStatus.QUEUED
        assert queue.get_queue_size() == 1
    
    def test_priority_ordering(self):
        """Test that tasks are returned by priority."""
        queue = TaskQueue()
        
        low_task = Task(user_input="Low", priority=TaskPriority.LOW)
        high_task = Task(user_input="High", priority=TaskPriority.HIGH)
        normal_task = Task(user_input="Normal", priority=TaskPriority.NORMAL)
        
        # Add in random order
        queue.add_task(normal_task)
        queue.add_task(low_task)
        queue.add_task(high_task)
        
        # Get in priority order
        first = queue.get_next_task(timeout=0.1)
        second = queue.get_next_task(timeout=0.1)
        third = queue.get_next_task(timeout=0.1)
        
        assert first.task_id == high_task.task_id  # Highest priority first
        assert second.task_id == normal_task.task_id
        assert third.task_id == low_task.task_id
    
    def test_get_task(self):
        """Test getting task by ID."""
        queue = TaskQueue()
        task = Task(user_input="Test")
        queue.add_task(task)
        
        retrieved = queue.get_task(task.task_id)
        
        assert retrieved == task
    
    def test_cancel_task(self):
        """Test task cancellation."""
        queue = TaskQueue()
        task = Task(user_input="Test")
        queue.add_task(task)
        
        success = queue.cancel_task(task.task_id)
        
        assert success is True
        assert task.status == TaskStatus.CANCELLED
    
    def test_get_stats(self):
        """Test queue statistics."""
        queue = TaskQueue(max_parallel=3)
        
        task1 = Task(user_input="Test1")
        task2 = Task(user_input="Test2")
        queue.add_task(task1)
        queue.add_task(task2)
        
        stats = queue.get_stats()
        
        assert stats["total_added"] == 2
        assert stats["current_queued"] == 2
        assert stats["max_parallel"] == 3
    
    def test_get_all_tasks(self):
        """Test getting all tasks."""
        queue = TaskQueue()
        
        task1 = Task(user_input="Test1")
        task2 = Task(user_input="Test2")
        queue.add_task(task1)
        queue.add_task(task2)
        
        all_tasks = queue.get_all_tasks()
        
        assert len(all_tasks) == 2
        assert task1 in all_tasks
        assert task2 in all_tasks
    
    def test_get_running_tasks(self):
        """Test getting running tasks."""
        queue = TaskQueue()
        task = Task(user_input="Test")
        queue.add_task(task)
        
        # Get the task (marks it as running)
        queue.get_next_task(timeout=0.1)
        
        running = queue.get_running_tasks()
        
        assert len(running) == 1
        assert running[0].status == TaskStatus.RUNNING


class TestTaskResult:
    """Tests for TaskResult class."""
    
    def test_success_result(self):
        """Test successful result."""
        result = TaskResult(
            success=True,
            content="Task completed",
            steps_taken=5,
        )
        
        assert result.success is True
        assert result.content == "Task completed"
        assert result.steps_taken == 5
        assert result.error is None
    
    def test_failure_result(self):
        """Test failure result."""
        result = TaskResult(
            success=False,
            error="Something went wrong",
        )
        
        assert result.success is False
        assert result.error == "Something went wrong"


class TestTaskProgress:
    """Tests for TaskProgress class."""
    
    def test_progress_update(self):
        """Test progress updates."""
        progress = TaskProgress()
        
        progress.update(5, "Step 5")
        
        assert progress.current_step == 5
        assert progress.current_action == "Step 5"
    
    def test_percentage_calculation(self):
        """Test percentage calculation."""
        progress = TaskProgress(total_steps=10)
        
        progress.update(5)
        
        assert progress.percentage == 50.0


class TestTaskDispatcher:
    """Tests for TaskDispatcher class."""
    
    def test_dispatcher_creation(self):
        """Test dispatcher creation."""
        dispatcher = TaskDispatcher(max_workers=3)
        
        assert dispatcher.max_workers == 3
        assert dispatcher._current_status == "idle"
    
    def test_submit_task(self):
        """Test submitting a task."""
        dispatcher = TaskDispatcher(max_workers=1)
        
        task = dispatcher.submit_task("Test task")
        
        assert task is not None
        assert task.user_input == "Test task"
        assert task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.COMPLETED)
        
        # Cleanup
        dispatcher.shutdown(wait=False)
    
    def test_get_task(self):
        """Test getting a task by ID."""
        dispatcher = TaskDispatcher(max_workers=1)
        
        submitted = dispatcher.submit_task("Test task")
        retrieved = dispatcher.get_task(submitted.task_id)
        
        assert retrieved == submitted
        
        # Cleanup
        dispatcher.shutdown(wait=False)
    
    def test_cancel_task(self):
        """Test cancelling a task."""
        dispatcher = TaskDispatcher(max_workers=1)
        
        task = dispatcher.submit_task("Test task")
        
        # Try to cancel (might fail if already processed)
        dispatcher.cancel_task(task.task_id)
        
        # Cleanup
        dispatcher.shutdown(wait=False)
    
    def test_get_status(self):
        """Test getting dispatcher status."""
        dispatcher = TaskDispatcher(max_workers=2)
        
        status = dispatcher.get_status()
        
        assert "status" in status
        assert "running" in status
        assert "queue_stats" in status
        
        # Cleanup
        dispatcher.shutdown(wait=False)


class TestTaskStatusDisplay:
    """Tests for TaskStatusDisplay class."""
    
    def test_display_creation(self):
        """Test display creation."""
        display = TaskStatusDisplay()
        
        assert display.update_interval == 0.5
    
    def test_show_task_summary_empty(self):
        """Test summary with no tasks."""
        dispatcher = TaskDispatcher()
        display = TaskStatusDisplay(dispatcher)
        
        summary = display.show_task_summary()
        
        assert "No tasks" in summary
        
        # Cleanup
        dispatcher.shutdown(wait=False)


class TestTaskCommandHandler:
    """Tests for TaskCommandHandler class."""
    
    def test_handler_creation(self):
        """Test handler creation."""
        handler = TaskCommandHandler()
        
        assert handler.dispatcher is not None
    
    def test_handle_tasks_command(self):
        """Test /tasks command."""
        dispatcher = TaskDispatcher()
        handler = TaskCommandHandler(dispatcher)
        
        result = handler.handle_command("/tasks")
        
        # Should show "No tasks" since queue is empty
        assert result is not None
        
        # Cleanup
        dispatcher.shutdown(wait=False)
    
    def test_handle_queue_command(self):
        """Test /queue command."""
        dispatcher = TaskDispatcher()
        handler = TaskCommandHandler(dispatcher)
        
        result = handler.handle_command("/queue")
        
        assert result is not None
        assert "Queue Status" in result
        
        # Cleanup
        dispatcher.shutdown(wait=False)
    
    def test_handle_unknown_command(self):
        """Test unknown command returns None."""
        handler = TaskCommandHandler()
        
        result = handler.handle_command("/unknown")
        
        assert result is None


class TestIntegration:
    """Integration tests for the task queue system."""
    
    def test_task_queue_flow(self):
        """Test complete task queue flow."""
        queue = TaskQueue(max_parallel=2)
        
        # Add multiple tasks
        tasks = [
            Task(user_input=f"Task {i}", priority=TaskPriority.NORMAL)
            for i in range(3)
        ]
        
        for task in tasks:
            queue.add_task(task)
        
        # Check queue state
        assert queue.get_queue_size() == 3
        
        # Get first task (marks as running)
        first = queue.get_next_task(timeout=0.1)
        assert first is not None
        assert first.status == TaskStatus.RUNNING
        assert queue.get_running_count() == 1
        
        # Complete the task
        queue.complete_task(first.task_id, success=True)
        assert first.status == TaskStatus.COMPLETED
        
        # Stats should reflect completion
        stats = queue.get_stats()
        assert stats["total_completed"] == 1
    
    def test_priority_ordering_integration(self):
        """Test priority ordering with multiple tasks."""
        queue = TaskQueue()
        
        # Add tasks with different priorities
        tasks = [
            Task(user_input="Low", priority=TaskPriority.LOW),
            Task(user_input="Urgent", priority=TaskPriority.URGENT),
            Task(user_input="Normal", priority=TaskPriority.NORMAL),
            Task(user_input="High", priority=TaskPriority.HIGH),
        ]
        
        for task in tasks:
            queue.add_task(task)
        
        # Get tasks in priority order
        order = []
        while queue.get_queue_size() > 0:
            task = queue.get_next_task(timeout=0.1)
            if task:
                order.append(task.user_input)
        
        assert order == ["Urgent", "High", "Normal", "Low"]