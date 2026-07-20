# Backend Logging Guidelines

## Standard application logging

Most modules use the standard library:

```python
import logging

logger = logging.getLogger(__name__)
logger.info("Migrated %d records into %s", count, path)
```

Examples include `open_agent/app/_app.py`, `open_agent/app/runner/api.py`, `open_agent/app/runner/repo.py`, and `open_agent/plugins/manager.py`.

The codebase contains both `%s` parameterized logging and f-strings. For new statements, use parameterized arguments when convenient so formatting is deferred; do not rewrite existing logging only for style.

## Levels as currently used

- `debug`: request/file lookup details and diagnostic state that is noisy in normal operation.
- `info`: lifecycle events, selected runtime resources, successful migrations, and user-visible create/update/delete events.
- `warning`: recoverable failures, missing optional assets/dependencies, cleanup failures, and invalid optional configuration.
- `error`: an operation or API action failed and cannot produce its normal result.
- `exception` or `exc_info=True`: used when the traceback is useful for an unexpected failure.

Include enough context to identify the operation and resource (session ID, plugin/path, provider), but avoid dumping whole configuration objects.

## Agent run logs

`open_agent/logger.py` implements a separate `AgentLogger` that writes per-run request, response, and tool-result records beneath `get_logs_dir() / "agent"`. It is a product feature, not a replacement for `logging`.

When extending it, preserve the indexed, timestamped text format and JSON serialization conventions. Be aware that these logs can contain conversation/tool content; never add credentials or environment dumps.

## Do not log

- API keys, bearer tokens, passwords, pairing tokens, or unmasked plugin secret settings.
- Entire environment mappings or authorization headers.
- Duplicate tracebacks at every layer. Log where a failure is handled or gains useful context.
