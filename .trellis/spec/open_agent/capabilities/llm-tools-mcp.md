# LLM, Tool and MCP Lifecycle

## LLM abstraction

`open_agent/llm/llm_wrapper.py::LLMClient` is the common client used by Agent/CLI/runtime code. `base.py`, `openai_client.py`, and `anthropic_client.py` own provider-specific request, streaming and response conversion. `provider_registry.py` and user model configuration drive provider/model discovery and diagnostics.

- Keep provider payload differences inside provider clients.
- Preserve token usage, tool-call and finish-reason normalization expected by `Agent`.
- Provider diagnostics/live tests are explicit API features; they should not mutate saved defaults unless the endpoint says so.
- Smart routing and retry behavior have dedicated owners (`config`, `retry.py`, routing APIs/tests); do not bury them in UI code.

## Tool contract and safety metadata

`tools/base.py::Tool` defines name, description, parameters and async execution; results use `ToolResult`. `tools/registry.py` wraps tools with inferred/explicit `ToolMetadata`, `ToolRisk`, `ToolCapability`, and `SafetyPolicy`.

CLI/runtime assembly builds the registry from built-in, workspace, MCP and control tools. Preserve metadata when wrapping a tool. Tool access mode (`default`/`full` in the web contract) affects availability and must flow from request to runtime policy.

## MCP lifecycle

`tools/mcp_loader.py` owns:

1. Config-path resolution and environment/value expansion.
2. Connection-type selection (stdio and supported remote transports).
3. Async server connection and tool/prompt discovery.
4. `MCPTool` adaptation to the normal Tool interface.
5. Timeout configuration, health checks and cleanup.
6. List/get prompt tools for discovered MCP prompts.

Plugin MCP servers are first aggregated by `PluginManager`; disabled plugins/servers must stay out of the runtime view. Cleanup must close all active MCP connections during CLI/web shutdown.

## Verification

Use `tests/test_llm.py`, `test_llm_clients.py`, `test_provider_registry.py`, `test_provider_diagnostics_api.py`, `test_tools.py`, `test_tool_schema.py`, `test_tool_registry.py`, `test_tool_context.py`, `test_mcp.py`, and `test_mcp_api.py` according to the boundary changed.
