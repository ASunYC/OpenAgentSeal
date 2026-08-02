# Shared Runtime Contracts

OpenAgentSeal does not generate TypeScript types from Pydantic schemas. Shared contracts are manually mirrored across Python and Vue, so producers and consumers must be reviewed together.

| Guide | Covers |
|---|---|
| [Messages, Events and Task State](./messages-events-task-state.md) | chat DTOs, stream events, runtime history and tasks |
| [API and Configuration Shapes](./api-configuration-shapes.md) | endpoint families, casing, model/provider/plugin/settings contracts |

Primary Python definitions are in `open_agent/schema/`, `app/runner/models.py`, `app/runner/api.py`, `task_queue/task.py`, `user_config.py`, and feature routers. Primary frontend mirrors are `app/web/src/types/index.ts`, `api/index.ts`, pure `models/`, and local component interfaces.
