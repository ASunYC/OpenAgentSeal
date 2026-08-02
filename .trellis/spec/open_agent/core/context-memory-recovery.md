# Context, Memory and Recovery

## Separate persistence concerns

- Chat metadata: monthly JSON via `JsonChatRepository`.
- Message bodies: monthly SQLite via `MonthlyMessageRepository`.
- Runtime threads, turns, and events: `open_agent/app/runner/context_store.py` and runner integration.
- Compacted context blocks: `context_compaction.py` plus API read/list/status endpoints.
- User/agent memory: `memory_manager.py` and application data paths.
- CLI session persistence/recovery: `cli_sessions.py`, `cli_prompt_session.py`, and runner recovery logic.

Do not treat chat ID, runner session ID, thread ID, and turn ID as interchangeable. Mappings exist so old chats and resumed sessions can locate the correct runtime state.

## Compaction

Compaction responds to configured/model context limits. `AgentRunner` may emit a `context_compaction` event and persist blocks containing original/compacted text and metadata. Frontend APIs expose status, block summaries, and details.

When changing compaction:

- Preserve the original-to-compacted audit path and `truncated` indicator.
- Keep token/window calculations consistent with model configuration.
- Avoid duplicating already persisted messages after recovery.
- Clear related context blocks when the established chat-clear path does so; cleanup failures are logged as warnings.

## Recovery

Recovery reconstructs a valid continuation from persisted chat/runtime records and marks interrupted work consistently. It must tolerate legacy or partial data without inventing a successful terminal event.

## Verification

Use `tests/test_context_compaction.py`, `test_session_recovery.py`, `test_session_integration.py`, `test_cli_sessions.py`, `test_cli_prompt_session.py`, `test_memory_manager.py`, and `test_log_memory_worker.py`. Tests should use temporary storage and verify both returned state and persisted records.
