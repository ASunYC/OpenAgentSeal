# Persistence Guidelines

## Current storage model

The project has no server database, ORM, or migration tool. Runtime data is local and uses:

- JSON/YAML for configuration and metadata.
- Monthly JSON chat metadata (`chat_YYYYMM.json`) in `JsonChatRepository`.
- Monthly SQLite message databases in `MonthlyMessageRepository`.
- Pydantic models to validate and serialize stored structures.

See `open_agent/app/runner/repo.py`, `open_agent/app/runner/models.py`, `open_agent/plugins/manager.py`, and `open_agent/user_config.py`.

## File persistence patterns

- Resolve application storage through `open_agent.utils.path_utils` (`get_data_dir()`, `get_logs_dir()`), rather than scattering home-directory calculations.
- Use `pathlib.Path` and explicit UTF-8 for text:

```python
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

- Create parent directories before writing and use stable, human-readable JSON when the surrounding store does so.
- Deserialize persisted structures through Pydantic (`ChatFile(**json.load(f))`) when a model exists.
- In-process caches must be invalidated after writes. `JsonChatRepository` sets `self._cache = None` after update/delete.
- Existing stores use locks around shared file/cache access. Preserve that behavior when changing concurrent paths.

## SQLite patterns

- Use the standard `sqlite3` module; do not add an ORM for an isolated change.
- Always parameterize values with `?` placeholders. Never interpolate user-controlled values into SQL.
- Keep connection/schema details inside the repository implementation so callers use the async repository interface.
- Serialize Pydantic objects with `model_dump()` and timestamps with `isoformat()` where the existing schema expects JSON/text.

## Compatibility and migrations

There is no numbered migration system. Compatibility is implemented in code and run when a repository/store initializes. Examples include `_migrate_legacy_session_dir()` and `_migrate_legacy_chats()` in `open_agent/app/runner/repo.py`, and local-storage migrations in the frontend message queue.

When changing a stored format:

- Continue reading the previous format.
- Make migration idempotent: skip records/targets already present.
- Do not silently discard unreadable current data. Follow the containing store's established fallback/logging behavior and add a regression test.

## Avoid

- Claiming relational constraints or transaction semantics that the JSON stores do not provide.
- Writing outside the resolved application/workspace root.
- SQL string concatenation.
- Destructive format changes without legacy-read coverage.
