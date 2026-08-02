# Agent Execution and Events

## Core loop

`open_agent/agent.py::Agent` owns model turns, message history, tool calls, step limits, token accounting, callbacks, and interruption. CLI and `AgentRunner` configure and invoke it; do not create a second tool loop in an API handler.

The normal shape is:

```text
input/messages -> LLMClient -> assistant content/tool calls
  -> ToolRegistry/SafetyPolicy selection -> Tool.execute()
  -> tool result appended to history -> next LLM turn
  -> completion/error/cancellation callback
```

Provider-specific conversion remains in `open_agent/llm/`. Tool implementations return `ToolResult`; the Agent converts model tool calls into execution and history events.

## Runner event adaptation

`AgentRunner.run_stream()` translates Agent callbacks and lifecycle into `open_agent.app.runner.models.AgentEvent`. It emits and persists events such as:

- `run_start`
- content/message and thinking events forwarded from callbacks
- tool-call/tool-result event types produced by the Agent callback contract
- `context_compaction`
- `complete`
- `cancelled`
- `error`

Each persisted event may carry `session_id`, `thread_id`, `turn_id`, sequence and creation time. Additions must update the Python model, runner persistence, SSE serialization, TypeScript `AgentEvent`, and every UI reducer/branch that needs the event.

## Cancellation and terminal states

- Runner sessions have an `asyncio.Event` in `_active_cancel_events`.
- `/api/cancel` calls the runner cancellation path.
- Cancellation must terminate streaming with a `cancelled` event and clean active-run bookkeeping.
- Exceptions produce a terminal `error` event; normal completion produces `complete` with idle status.
- Do not emit both a successful completion and an error/cancel terminal state for one run.

## Verification

Relevant tests include `tests/test_agent.py`, `test_agent_iteration_limit.py`, `test_agent_token_usage.py`, `test_llm.py`, `test_tools.py`, `test_tool_registry.py`, `test_integration.py`, and runner/session tests. For a new event, add producer and consumer coverage rather than testing only serialization.
