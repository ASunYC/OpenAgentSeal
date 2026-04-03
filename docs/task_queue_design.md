# Task Queue System Design

## Overview

The Task Queue System provides asynchronous task execution for the Open Agent framework. It enables:

- **Non-blocking UI**: Users can continue interacting while tasks run in the background
- **Real-time feedback**: Progress updates and status notifications
- **Parallel execution**: Multiple tasks can run concurrently
- **Master-Sub agent coordination**: Main agent can delegate tasks to sub-agents

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         MasterAgent                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    TaskDispatcher                        │    │
│  │  ┌─────────────┐    ┌──────────────────────────────┐   │    │
│  │  │ TaskQueue   │───▶│      WorkerPool              │   │    │
│  │  │             │    │  ┌────────┐ ┌────────┐       │   │    │
│  │  │ Priority    │    │  │Worker 1│ │Worker 2│ ...   │   │    │
│  │  │ Queue       │    │  └────────┘ └────────┘       │   │    │
│  │  └─────────────┘    └──────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                      Agent                                │    │
│  │  (Main agent for task execution)                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  SubAgentManager                          │    │
│  │  (Manages sub-agents for task delegation)                │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Task

A `Task` represents a unit of work:

```python
from open_agent.task_queue import Task, TaskPriority

task = Task(
    user_input="Create a Python script that processes CSV files",
    priority=TaskPriority.HIGH,
    context={"files": ["data.csv"]},
)
```

**Task Properties:**
- `task_id`: Unique identifier
- `user_input`: Original user request
- `status`: Current status (PENDING, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)
- `priority`: Task priority (LOW, NORMAL, HIGH, URGENT)
- `progress`: Progress information
- `result`: Execution result

### 2. TaskQueue

Thread-safe priority queue for tasks:

```python
from open_agent.task_queue import TaskQueue

queue = TaskQueue(max_parallel=3)

# Add tasks
queue.add_task(task)

# Get next task (by priority)
next_task = queue.get_next_task()

# Query tasks
running = queue.get_running_tasks()
pending = queue.get_pending_tasks()
completed = queue.get_completed_tasks()
```

### 3. TaskDispatcher

Central coordinator for task execution:

```python
from open_agent.task_queue import TaskDispatcher

dispatcher = TaskDispatcher(max_workers=3)

# Initialize with agent
dispatcher.initialize(main_agent=agent)

# Submit task
task = dispatcher.submit_task("Write a hello world program")

# Check status
status = dispatcher.get_status()
activity = dispatcher.get_current_activity()

# Cleanup
dispatcher.shutdown()
```

### 4. MasterAgent

The primary agent that owns the task queue:

```python
from open_agent.master_agent import MasterAgent

master = MasterAgent(
    llm_client=llm_client,
    system_prompt=system_prompt,
    tools=tools,
    max_parallel_tasks=3,
)

# Initialize
master.initialize(sub_agent_manager=sub_agent_manager)

# Submit task (non-blocking)
task = master.submit_task("Analyze the codebase")

# UI remains responsive - check status anytime
print(master.get_current_activity())

# Get task result when complete
if task.status == TaskStatus.COMPLETED:
    print(task.result.content)
```

## Task Lifecycle

```
PENDING ──▶ QUEUED ──▶ RUNNING ──▶ COMPLETED
                           │
                           ├──▶ FAILED
                           │
                           └──▶ CANCELLED
```

1. **PENDING**: Task created, waiting to be queued
2. **QUEUED**: Task added to queue, waiting for worker
3. **RUNNING**: Task being executed by worker
4. **COMPLETED**: Task finished successfully
5. **FAILED**: Task execution failed
6. **CANCELLED**: Task cancelled by user

## CLI Integration

### New Commands

| Command | Description |
|---------|-------------|
| `/tasks` | List all tasks (running, pending, completed) |
| `/task <id>` | Show detailed info for a task |
| `/cancel <id>` | Cancel a pending or running task |
| `/queue` | Show queue status and statistics |
| `/activity` | Show current agent activity |

### Usage Example

```
You › Analyze the sales data and create a report

Agent › Task submitted: task_abc123
        Use /tasks to check status

You › /tasks

▶ Running (1):
  task_abc123 - Processing with main agent (5s)

You › What other files need analysis?

Agent › While the analysis runs, I can help with other tasks...
        (UI remains responsive)

You › /activity

Current Activity: Working on: Processing sales data...

You › /task task_abc123

Task: task_abc123
──────────────────────────────────────────────────
  Input: Analyze the sales data and create a report
  Status: completed
  Progress: 100% (5/5)
  Elapsed: 12.3s

  Result:
  Analysis complete. Found 3 key trends...
```

## Sub-Agent Integration

The MasterAgent can delegate tasks to sub-agents:

```python
# Submit a subtask for a sub-agent
subtask = master.submit_subtask(
    user_input="Review the code for security issues",
    role="security_expert",
    parent_task_id=main_task.task_id,
)

# Or create a sub-agent directly
wrapper = master.create_sub_agent(
    role="code_expert",
    task="Refactor the authentication module",
    auto_start=True,
)
```

## Configuration

Task queue settings can be configured:

```python
master = MasterAgent(
    llm_client=llm_client,
    system_prompt=system_prompt,
    tools=tools,
    max_parallel_tasks=3,  # Maximum concurrent tasks
    on_task_update=my_callback,  # Progress updates
    on_status_change=status_callback,  # Status changes
)
```

## Best Practices

### 1. Task Priority

Use appropriate priority levels:
- `URGENT`: Critical tasks that need immediate attention
- `HIGH`: Important tasks
- `NORMAL`: Standard tasks (default)
- `LOW`: Background tasks

### 2. Progress Updates

Provide progress callbacks for long-running tasks:

```python
def on_progress(progress):
    print(f"Progress: {progress.percentage:.0f}%")

task = Task(
    user_input="Long running task",
    on_progress=on_progress,
)
```

### 3. Cancellation Handling

Tasks should check for cancellation:

```python
# In task execution
if task.status == TaskStatus.CANCELLED:
    # Cleanup and exit
    return
```

### 4. Resource Management

Always shutdown properly:

```python
try:
    master.initialize()
    # ... use master agent ...
finally:
    master.shutdown(wait=True, timeout=10.0)
```

## Implementation Files

| File | Description |
|------|-------------|
| `open_agent/task_queue/task.py` | Task data structures |
| `open_agent/task_queue/queue.py` | Priority queue implementation |
| `open_agent/task_queue/worker.py` | Worker and WorkerPool |
| `open_agent/task_queue/dispatcher.py` | Task dispatcher |
| `open_agent/task_queue/cli_integration.py` | CLI commands and display |
| `open_agent/master_agent.py` | Master agent implementation |

## Testing

Run tests with:

```bash
pytest tests/test_task_queue.py -v
```

## Future Enhancements

1. **Task Dependencies**: Allow tasks to depend on other tasks
2. **Task Retry**: Automatic retry for failed tasks
3. **Task Scheduling**: Schedule tasks for future execution
4. **Load Balancing**: Distribute tasks across multiple agents
5. **Result Caching**: Cache task results for similar requests