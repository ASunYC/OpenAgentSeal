# Backend Directory Structure

## Layout

```text
open_agent/
├── agent.py, master_agent.py       # core agent orchestration
├── llm/                            # provider-neutral and provider clients
├── tools/                          # Tool implementations and registry
├── schema/                         # shared message/tool schemas
├── config/ and config.py           # configuration support
├── app/
│   ├── _app.py                     # FastAPI application and legacy/general routes
│   ├── mobile.py, sandbox.py       # feature routers
│   └── runner/
│       ├── api.py, workspace_api.py# chat/workspace routers
│       ├── models.py               # runner Pydantic models
│       ├── repo.py                 # chat/message persistence
│       └── manager.py, runner.py   # application/runtime coordination
├── plugins/                        # plugin manager and bundled plugins
├── task_queue/                     # task, queue, worker, dispatcher
└── utils/                          # shared path, terminal, document helpers
tests/                              # pytest suite, named test_*.py
```

## Placement rules observed in the repository

- Put reusable agent capabilities under `open_agent/tools/`; implement the base contracts from `open_agent/tools/base.py` and register them through the existing registry/loader path.
- Put provider integrations under `open_agent/llm/`, not in route handlers.
- A self-contained API feature may define an `APIRouter`, request models, and helpers in one module, as in `open_agent/app/mobile.py` and `open_agent/app/sandbox.py`.
- Runner-specific API, state, and persistence stay in `open_agent/app/runner/`. `api.py` exposes chat/session routes while `repo.py` owns persistence details.
- Cross-cutting filesystem helpers belong in `open_agent/utils/`; security-sensitive path joining is centralized in `open_agent/utils/safe_join.py`.
- Tests live in the top-level `tests/` directory and usually mirror a feature (`test_mobile.py`, `test_plugins.py`, `test_workspace_api.py`).

## Naming

- Modules, functions, variables, and pytest files use `snake_case`.
- Classes and Pydantic models use `PascalCase`.
- Internal helpers use a leading underscore (`_load_file`, `_validate_entry_name`).
- FastAPI request models commonly end in `Request`, `Create`, or `Update`, e.g. `AgentTaskRequest` and `WorkspaceCreate`.

## Representative examples

- `open_agent/app/runner/workspace_api.py`: cohesive router with request models and boundary validation.
- `open_agent/app/runner/repo.py`: persistence interfaces plus JSON/SQLite implementations.
- `open_agent/plugins/manager.py`: a larger domain service with filesystem-backed state.

Do not introduce a new top-level layer merely to satisfy a generic architecture pattern. Extend the nearest existing feature boundary.
