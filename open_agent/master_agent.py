"""Master Agent with task queue and sub-agent coordination.

The MasterAgent is the primary agent that:
- Manages the task queue system
- Coordinates sub-agent creation and delegation
- Provides real-time feedback to users
- Handles parallel task execution
"""

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any, TYPE_CHECKING

from .agent import Agent
from .llm import LLMClient
from .schema import Message
from .tools.base import Tool
from .task_queue import (
    Task,
    TaskStatus,
    TaskPriority,
    SubTask,
    TaskQueue,
    TaskDispatcher,
)


class MasterAgent:
    """Master agent with task queue and sub-agent management.

    This is the primary agent initialized at startup that:
    - Owns the task queue and dispatcher
    - Has authority over sub-agent creation and assignment
    - Coordinates parallel task execution
    - Provides real-time status updates
    """

    def __init__(
        self,
        llm_client: LLMClient,
        system_prompt: str,
        tools: list[Tool],
        max_steps: int = 50,
        workspace_dir: str = "./workspace",
        max_parallel_tasks: int = 3,
        on_task_update: Optional[Callable[[Task], None]] = None,
        on_status_change: Optional[Callable[[str, str], None]] = None,
    ):
        """Initialize the master agent.

        Args:
            llm_client: LLM client for API calls
            system_prompt: System prompt for the agent
            tools: List of available tools
            max_steps: Maximum agent steps per task
            workspace_dir: Workspace directory
            max_parallel_tasks: Maximum parallel tasks
            on_task_update: Callback for task updates
            on_status_change: Callback for status changes
        """
        self.workspace_dir = Path(workspace_dir)
        self.max_parallel_tasks = max_parallel_tasks

        # Create the underlying agent
        self.agent = Agent(
            llm_client=llm_client,
            system_prompt=system_prompt,
            tools=tools,
            max_steps=max_steps,
            workspace_dir=str(workspace_dir),
            interactive=False,  # Non-interactive for background execution
        )

        # LLM client reference
        self.llm_client = llm_client
        self.tools = tools
        self.max_steps = max_steps

        # Task dispatcher
        self.dispatcher = TaskDispatcher(
            max_workers=max_parallel_tasks,
            workspace_dir=self.workspace_dir,
            on_task_update=on_task_update,
            on_status_change=on_status_change,
        )

        # Current task being processed
        self._current_task: Optional[Task] = None

        # Lock for thread safety
        self._lock = threading.RLock()

        # Status
        self._initialized = False
        self._master_agent_id = f"master_{id(self)}"

    def initialize(self):
        """Initialize the master agent."""
        with self._lock:
            # Initialize the dispatcher with the agent
            self.dispatcher.initialize(
                main_agent=self.agent,
            )

            self._initialized = True

    def shutdown(self, wait: bool = True, timeout: float = 5.0):
        """Shutdown the master agent.

        Args:
            wait: Whether to wait for running tasks
            timeout: Maximum wait time
        """
        with self._lock:
            self.dispatcher.shutdown(wait=wait, timeout=timeout)
            self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if master agent is initialized."""
        return self._initialized

    @property
    def master_agent_id(self) -> str:
        """Get the master agent ID."""
        return self._master_agent_id

    # Task submission methods

    def submit_task(
        self,
        user_input: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        context: Optional[dict[str, Any]] = None,
    ) -> Task:
        """Submit a task for asynchronous execution.

        The task will be queued and executed in the background.
        The UI remains responsive while the task runs.

        Args:
            user_input: User's original input/request
            priority: Task priority
            context: Additional context

        Returns:
            The created Task object
        """
        if not self._initialized:
            raise RuntimeError("Master agent not initialized")

        return self.dispatcher.submit_task(
            user_input=user_input,
            priority=priority,
            context=context,
        )

    def submit_subtask(
        self,
        user_input: str,
        role: str,
        parent_task_id: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        context: Optional[dict[str, Any]] = None,
        is_parallel: bool = False,
    ) -> SubTask:
        """Submit a subtask for a sub-agent.

        Args:
            user_input: Task description
            role: Role type for sub-agent
            parent_task_id: Parent task ID
            priority: Task priority
            context: Additional context
            is_parallel: Whether this can run in parallel

        Returns:
            The created SubTask
        """
        if not self._initialized:
            raise RuntimeError("Master agent not initialized")

        return self.dispatcher.submit_subtask(
            user_input=user_input,
            role=role,
            parent_task_id=parent_task_id,
            priority=priority,
            context=context,
            is_parallel=is_parallel,
        )

    # Task management methods

    def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a task.

        Args:
            task_id: Task ID to cancel
            reason: Cancellation reason

        Returns:
            True if cancelled, False otherwise
        """
        return self.dispatcher.cancel_task(task_id, reason)

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task if found, None otherwise
        """
        return self.dispatcher.get_task(task_id)

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks.

        Returns:
            List of all tasks
        """
        return self.dispatcher.get_all_tasks()

    def get_running_tasks(self) -> list[Task]:
        """Get running tasks.

        Returns:
            List of running tasks
        """
        return self.dispatcher.get_running_tasks()

    def get_pending_tasks(self) -> list[Task]:
        """Get pending tasks.

        Returns:
            List of pending tasks
        """
        return self.dispatcher.get_pending_tasks()

    def get_completed_tasks(self) -> list[Task]:
        """Get completed tasks.

        Returns:
            List of completed tasks
        """
        return self.dispatcher.get_completed_tasks()

    # Status methods

    def get_status(self) -> dict[str, Any]:
        """Get current status.

        Returns:
            Status dictionary
        """
        status = self.dispatcher.get_status()
        status["master_agent_id"] = self._master_agent_id
        status["initialized"] = self._initialized
        return status

    def get_current_activity(self) -> str:
        """Get description of current activity.

        Returns:
            Human-readable activity description
        """
        return self.dispatcher.get_current_activity()

    def get_task_status_message(self, task_id: str) -> str:
        """Get status message for a task.

        Args:
            task_id: Task identifier

        Returns:
            Status message
        """
        return self.dispatcher.get_task_status_message(task_id)

    # Direct agent access

    def add_message(self, role: str, content: str):
        """Add a message directly to the agent's history.

        Args:
            role: Message role (user, assistant, etc.)
            content: Message content
        """
        self.agent.messages.append(Message(role=role, content=content))

    def get_message_history(self) -> list[Message]:
        """Get the agent's message history.

        Returns:
            List of messages
        """
        return self.agent.messages.copy()

    def clear_history(self):
        """Clear message history except system prompt."""
        if self.agent.messages:
            self.agent.messages = [self.agent.messages[0]]

    # Tool management

    def add_tool(self, tool: Tool):
        """Add a tool to the agent.

        Args:
            tool: Tool to add
        """
        self.agent.tools[tool.name] = tool

    def remove_tool(self, tool_name: str) -> bool:
        """Remove a tool from the agent.

        Args:
            tool_name: Name of tool to remove

        Returns:
            True if removed
        """
        if tool_name in self.agent.tools:
            del self.agent.tools[tool_name]
            return True
        return False

    def get_tools(self) -> dict[str, Tool]:
        """Get all available tools.

        Returns:
            Dictionary of tools
        """
        return self.agent.tools.copy()

    def __repr__(self) -> str:
        return (
            f"MasterAgent(id={self._master_agent_id}, initialized={self._initialized})"
        )


# Singleton pattern for global access

_master_agent_instance: Optional[MasterAgent] = None


def get_master_agent() -> Optional[MasterAgent]:
    """Get the global master agent instance.

    Returns:
        MasterAgent instance or None
    """
    return _master_agent_instance


def set_master_agent(agent: MasterAgent):
    """Set the global master agent instance.

    Args:
        agent: MasterAgent instance
    """
    global _master_agent_instance
    _master_agent_instance = agent


def create_master_agent(
    llm_client: LLMClient,
    system_prompt: str,
    tools: list[Tool],
    max_steps: int = 50,
    workspace_dir: str = "./workspace",
    max_parallel_tasks: int = 3,
    on_task_update: Optional[Callable[[Task], None]] = None,
    on_status_change: Optional[Callable[[str, str], None]] = None,
) -> MasterAgent:
    """Create and register a master agent.

    Args:
        llm_client: LLM client
        system_prompt: System prompt
        tools: Available tools
        max_steps: Maximum steps per task
        workspace_dir: Workspace directory
        max_parallel_tasks: Maximum parallel tasks
        on_task_update: Task update callback
        on_status_change: Status change callback

    Returns:
        MasterAgent instance
    """
    global _master_agent_instance

    agent = MasterAgent(
        llm_client=llm_client,
        system_prompt=system_prompt,
        tools=tools,
        max_steps=max_steps,
        workspace_dir=workspace_dir,
        max_parallel_tasks=max_parallel_tasks,
        on_task_update=on_task_update,
        on_status_change=on_status_change,
    )

    _master_agent_instance = agent
    return agent
