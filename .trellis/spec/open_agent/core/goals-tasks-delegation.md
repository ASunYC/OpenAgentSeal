# Goals, Tasks and Delegation

## Distinct systems

Do not conflate these current owners:

- `GoalController` (`goal_mode.py`) stores durable goal state, budgets, status, progress and judge results.
- `MasterAgent` (`master_agent.py`) decomposes/co-ordinates work and creates subtasks.
- `AgentService` (`agent_service.py`) manages agent definitions, sessions and execution status.
- `Task`, `SubTask`, `TaskQueue`, `TaskWorker`, `WorkerPool`, and `TaskDispatcher` (`task_queue/`) manage queued background work, priorities, progress and cancellation.
- `control_plane.py` exposes higher-level runtime control used by API/CLI integrations.

They integrate but are not one state machine. Extend the owner that already represents the requested lifecycle.

## Task state contract

`TaskStatus` currently includes pending/queued/running/paused and terminal completed/failed/cancelled states. `Task.to_dict()` exposes IDs, priority, parent/assigned agent, timestamps, status message, progress, and result. `SubTask` adds role and `is_parallel`.

State changes use `set_status()`, `update_progress()`, `set_result()`, and `cancel()` so timestamps, callbacks, and log entries stay consistent. Do not assign status fields directly in new queue code when these methods apply.

## Goal state contract

Goal state is durable and budget-aware. A goal-status change must preserve stored objective, status, progress/judgment metadata, token accounting and reload behavior. Goal completion is not equivalent to one successful turn; the controller/judge decides against the objective.

## API/UI consumers

- `/api/agent-tasks*` exposes control-plane tasks.
- `/api/tasks` in the main app exposes dispatcher status and grouped task records.
- `TasksSettings.vue` expects the serialized task/progress fields.
- Runtime task and collaboration frontend models have dedicated Node tests.

## Verification

Use `tests/test_goal_mode.py`, `test_task_queue.py`, `test_agent_profiles.py`, `test_agent_iteration_limit.py`, `test_runtime_api.py`, and the frontend runtime/collaboration model scripts as appropriate. Cover legal transitions, cancellation, reload, parent/child linkage, and progress/result serialization.
