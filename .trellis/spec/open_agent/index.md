# OpenAgentSeal Package Map

The `open_agent` Trellis package is the repository root and owns the application, tests, desktop/mobile hosts and release scripts.

| Domain | Specification | Main source |
|---|---|---|
| Agent execution and durable work | [Core](./core/index.md) | `open_agent/agent.py`, goal/task/control modules |
| FastAPI, chat, persistence and local services | [Runtime Backend](./runtime/backend/index.md) | `open_agent/app/` |
| Vue browser/desktop/mobile UI | [Runtime Frontend](./runtime/frontend/index.md) | `open_agent/app/web/` |
| Providers, tools, MCP, plugins and Skill loading | [Capabilities](./capabilities/index.md) | `open_agent/llm/`, `tools/`, `plugins/` |
| Cross-language DTO/event state | [Contracts](./contracts/index.md) | runner models/API and frontend types/stores |
| Tauri, Capacitor and release artifacts | [Delivery](./delivery/index.md) | `desktop/`, `scripts/`, Android host |
| Built-in Skill content submodule | [Skill Content](./skills/index.md) | `open_agent/skills/` |

Project-wide architecture, configuration/security, engineering and verification rules are one directory above. Read those before a cross-domain change.

The Python package name and the Trellis package label are both `open_agent`, but the Trellis boundary intentionally includes repository-level delivery files outside the Python directory.
