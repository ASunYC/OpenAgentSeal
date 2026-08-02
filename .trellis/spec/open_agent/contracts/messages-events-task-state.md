# Messages, Events and Task State Contracts

## Chat and messages

Python `ChatSpec`, `Message`, `ContentItem`, and `ChatHistory` in `app/runner/models.py` persist and serialize the chat model. TypeScript `Chat`, `Message`, `ChatHistory`, attachments and workspace sources in `src/types/index.ts` consume API forms.

The frontend `Message` is a UI-oriented projection: it includes loading/thinking/user-query fields not all persisted by the backend, while backend content may be structured. Do not assume the two definitions are structurally identical just because they share a name.

## Stream events

Python `AgentEvent` is produced by `AgentRunner`, serialized as SSE, stored with runtime thread/turn context, and consumed by TypeScript `AgentEvent` plus store branches. Important identity fields are optional in the frontend because some legacy/surface events omit them.

For an event change, inspect:

1. Agent callback producer.
2. `AgentRunner` conversion and persistence.
3. `/api/run` SSE serialization and mobile stream.
4. TypeScript `AgentEvent`.
5. chat/agent store reducer branches and visual components.
6. runtime history/event APIs and recovery.

Keep `event`, `status`, sequence, timestamp and terminal semantics stable. Unknown events should not crash the stream reader, but required UI behavior needs an explicit branch.

## Tasks

Task queue serialization uses `task_id`, `user_input`, numeric priority value, parent/assigned IDs, status/status message, ISO timestamps, nested progress and optional result. `TasksSettings.vue` currently uses a local partial interface; runtime task models cover a different UI workflow. Changing queue serialization requires checking both.

## Casing

Backend DTOs and JSON persistence predominantly use `snake_case`. Frontend domain/API types often retain that casing; UI-only state uses `camelCase`. Convert only at an established adapter boundary, not opportunistically in one component.
