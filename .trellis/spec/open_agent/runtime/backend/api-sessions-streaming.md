# API, Sessions and Streaming

## Router ownership

- `create_app()` and `_setup_app_routes()` in `app/_app.py` assemble the application and retain many settings/provider/plugin routes.
- `app/runner/api.py` owns chats, context blocks, runtime threads/events, agent sessions/tasks, `/run`, and cancellation.
- `workspace_api.py`, `sandbox.py`, and `mobile.py` use feature `APIRouter` instances.

New endpoints should join the existing feature router where one exists. Register a new router in the composition root; do not instantiate another FastAPI application.

## Chat identities

- `ChatSpec.id` identifies chat metadata.
- `session_id` identifies the runner/conversation channel.
- Runtime persistence adds thread and turn IDs.
- Agent profiles select isolated managers/control planes through `profile_id`; `main` is the default frontend profile.

Always pass/encode the identity expected by the endpoint. Profile-scoped APIs must resolve the matching manager rather than silently using the global main manager.

## SSE contract

`POST /api/run` returns an SSE stream. `runAgentStream()` reads `response.body`, splits SSE frames, parses each `data:` JSON payload and yields `AgentEvent` values. Keep newline framing and terminal events intact.

The mobile authenticated stream uses a parallel frontend helper and `/api/mobile` boundary. When changing shared events, inspect both readers.

## Response reality

Chat endpoints often return model-shaped dictionaries, workspace operations use `ok`, and settings/plugin routes frequently use `success`. Preserve each family; a global response migration requires updating all callers and is not incidental refactoring.

## Errors

Expected absence/invalid input uses `HTTPException`. Streaming exceptions must become an SSE `error` event after logging; do not return a JSON error body mid-stream. See `tests/test_runtime_api.py`, `test_mobile.py`, and session tests.
