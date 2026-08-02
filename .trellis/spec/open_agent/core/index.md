# Core Agent Runtime

Use this section for changes to the execution loop, control plane, goal mode, delegation, task scheduling, memory, or recovery.

| Guide | Covers |
|---|---|
| [Execution and Events](./execution-and-events.md) | Agent loop, LLM/tool turns, callbacks and cancellation |
| [Goals, Tasks and Delegation](./goals-tasks-delegation.md) | GoalController, MasterAgent, AgentService and task queue |
| [Context, Memory and Recovery](./context-memory-recovery.md) | Context compaction, persisted events, session recovery and memory |

Primary owners are `open_agent/agent.py`, `master_agent.py`, `agent_service.py`, `control_plane.py`, `goal_mode.py`, `task_queue/`, `memory_manager.py`, and runner persistence/adaptation under `open_agent/app/runner/`.

The CLI, web runner, and ACP are surfaces over overlapping core behavior. A core change must check more than the surface where it was requested.
