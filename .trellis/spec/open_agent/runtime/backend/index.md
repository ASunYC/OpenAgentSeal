# Runtime Backend

The FastAPI backend combines chat/session runtime APIs, configuration/provider/plugin management, workspace files, sandbox terminals, mobile access and packaged static delivery.

| Guide | Covers |
|---|---|
| [API, Sessions and Streaming](./api-sessions-streaming.md) | routers, SSE, profile/session identity and cancellation |
| [Persistence and Compatibility](./persistence-compatibility.md) | JSON, SQLite, context stores and migrations |
| [Workspace, Sandbox and Mobile](./workspace-sandbox-mobile.md) | filesystem confinement, WebSocket terminals and pairing |

General Python conventions remain in `../../skills/backend/`. `open_agent/app/_app.py` is the composition root; feature routers live in `app/runner/api.py`, `workspace_api.py`, `sandbox.py`, and `mobile.py`.
