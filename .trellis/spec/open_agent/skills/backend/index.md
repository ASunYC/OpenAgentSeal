# Backend Development Guidelines

> Conventions observed in the `open_agent` Python package. These notes describe the current repository, not a target architecture.

## Runtime and stack

- Python 3.10+ (`pyproject.toml`).
- FastAPI for the web API and WebSocket endpoints.
- Pydantic v2 models at API, tool, configuration, and persistence boundaries.
- `pytest` and `pytest-asyncio` for tests.
- JSON files and SQLite are the normal persistence mechanisms; there is no ORM or migration framework.

## Guides

| Guide | Scope |
|---|---|
| [Directory Structure](./directory-structure.md) | Package layout and placement of new code |
| [Database Guidelines](./database-guidelines.md) | JSON/SQLite persistence and compatibility |
| [Error Handling](./error-handling.md) | Domain, API, and best-effort failures |
| [Quality Guidelines](./quality-guidelines.md) | Typing, security boundaries, and tests |
| [Logging Guidelines](./logging-guidelines.md) | Standard logging and agent-run logs |

## Commands used by the project

```bash
pytest
pytest tests/test_workspace_api.py
pytest tests/test_workspace_api.py::TestFileOperations::test_path_traversal_blocked
```

The repository does not configure a mandatory formatter, global linter, or coverage threshold. Match the surrounding module and keep changes focused.
