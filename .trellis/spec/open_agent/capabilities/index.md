# Capability System

OpenAgentSeal composes model providers, built-in tools, MCP tools/prompts, progressively disclosed Skills, and installed plugins into the Agent runtime.

| Guide | Covers |
|---|---|
| [LLM, Tools and MCP](./llm-tools-mcp.md) | provider abstraction, registry/safety, MCP connection lifecycle |
| [Plugins and Skills](./plugins-skills.md) | marketplaces, installation, settings, runtime projection and Skill loading |

Primary owners: `open_agent/llm/`, `provider_registry.py`, `tools/`, `plugins/manager.py`, and the `open_agent/skills` submodule. UI/API management surfaces live in `_app.py`, `api/index.ts`, and settings components.

A capability is available only when discovery, configuration, runtime registration, execution and the relevant UI/API view agree. A manifest or settings row alone is not proof of runtime availability.
