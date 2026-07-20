# Backend Quality Guidelines

## Language and models

- Support Python 3.10+.
- Use type hints on public APIs and data-bearing helpers. Both built-in generics (`list[str]`) and `typing` forms exist; match the touched module.
- Use Pydantic v2 methods such as `model_dump()` for structured boundary data.
- Use `pathlib.Path` for new filesystem code and explicit UTF-8 for project-managed text files.
- Preserve async interfaces for I/O-facing repositories, runners, tools, and FastAPI handlers. Do not call a coroutine without `await`.

The repository is not consistently immutable: models, queues, caches, and progress objects are deliberately mutated. Do not apply the generic AGENTS.md immutability statement as a project-wide rule.

## Security boundaries already enforced

- Resolve paths within a trusted root using `safe_join`; catch `PathTraversalError` and return 403 at the API boundary (`workspace_api.py`, `tests/test_workspace_api.py`).
- Validate uploaded/renamed entry names as a single path segment.
- Parameterize SQLite statements.
- Mask persisted plugin secrets in API/detail responses (`tests/test_plugins.py`).
- Bind privileged/local-only features to their existing access checks; mobile pairing is explicitly local-only.

## Testing practices

- Add or update a focused `tests/test_<feature>.py` regression test for behavior changes.
- Use pytest fixtures and built-ins such as `tmp_path`, `monkeypatch`, and `capsys` to isolate filesystem, environment, and output state.
- FastAPI routes are exercised with a small test app and `TestClient`, as in `tests/test_workspace_api.py` and `tests/test_mobile.py`.
- Async behavior uses `pytest-asyncio`; `asyncio_mode = "auto"` is configured.
- Tests commonly assert both the response/result and the side effect on disk or runtime state.
- Security fixes include a negative test (path traversal, secret masking, invalid token, unsupported input).

Run the narrow test first, then the full suite when practical. There is no repository-enforced 80% coverage threshold, and frontend/Python coverage is not uniformly measured.

## Review checklist

- Does the change preserve existing API and persisted-data shapes?
- Are filesystem inputs confined to the intended root?
- Are optional failures contained while real failures remain visible?
- Are sync/async boundaries and locks/caches preserved?
- Does the test isolate user data and avoid network/provider calls?
- Are secrets absent from logs, returned configuration, and fixtures?

Avoid unrelated formatting churn, new architecture layers without an existing analogue, and generic response/repository abstractions imposed across unrelated features.
