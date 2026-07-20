# Backend Error Handling

## Boundary-specific behavior

This repository does not use one custom exception hierarchy or one universal response envelope. Match the boundary being changed.

### FastAPI routes

- Raise `HTTPException` with an appropriate status and short `detail` for expected client failures.
- Common meanings in current routers: `400` invalid request/name, `401` missing token, `403` disallowed access/path traversal, `404` missing resource, and `500` unavailable runtime dependency.
- Pydantic request models handle request-shape validation.
- Preserve explicit exceptions rather than converting every failure to HTTP 200.

```python
if chat is None:
    raise HTTPException(status_code=404, detail="Chat not found")
```

Examples: `open_agent/app/runner/api.py`, `open_agent/app/runner/workspace_api.py`, `open_agent/app/mobile.py`.

### Domain and utility code

- Domain helpers may raise focused exceptions such as `PathTraversalError` (`open_agent/utils/safe_join.py`). Translate them at the API boundary.
- Return structured domain results where that is the existing contract, e.g. `ToolResult(success=False, error=...)` and plugin dictionaries containing `success`/`error`.
- Use `raise ... from exc` when converting an unexpected lower-level exception and its cause matters.

### Best-effort operations

Optional cleanup, legacy reads, or optional integrations sometimes catch broad `Exception`, log a warning/error, and continue. This is established in repository loading, MCP/plugin discovery, and context cleanup. Keep broad catches limited to such containment boundaries; include the path/resource and exception in the log.

```python
except Exception as exc:
    logger.warning("Failed to read plugin config %s: %s", path, exc)
```

## Response shapes

Current APIs are mixed: some return domain objects directly, some return `{ "success": ... }`, and file/workspace operations often return `{ "ok": ... }`. Preserve the endpoint family's existing shape and the matching TypeScript declaration; do not impose a new global envelope in an unrelated change.

## Avoid

- Bare `except:` blocks.
- Swallowing an exception without either an intentional fallback or a log.
- Leaking tokens, secrets, raw authorization headers, or unnecessary local paths in client-facing details.
- Catching `HTTPException` inside a generic handler and accidentally changing its status code.
