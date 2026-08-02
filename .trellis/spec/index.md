# OpenAgentSeal Project Specification

This directory is the operational map future Trellis agents use before changing OpenAgentSeal. It records the current repository, including known mixed patterns; roadmap documents are not evidence that a target design already exists.

## Start here

| Change area | Read first |
|---|---|
| Any cross-module change | [Architecture](./architecture.md), [Engineering](./engineering.md) |
| Configuration, credentials, files, mobile access | [Configuration and Security](./configuration-security.md) |
| Tests, builds, packaging, handoff | [Verification and Delivery](./verification-delivery.md) |
| Agent loop, goal mode, delegation, recovery | [Core Agent](./open_agent/core/index.md) |
| FastAPI, sessions, persistence, workspace | [Runtime Backend](./open_agent/runtime/backend/index.md) |
| Vue, Pinia, SSE, desktop/mobile UI | [Runtime Frontend](./open_agent/runtime/frontend/index.md) |
| Tools, providers, MCP, plugins, Skills | [Capabilities](./open_agent/capabilities/index.md) |
| Python/TypeScript messages and state | [Shared Contracts](./open_agent/contracts/index.md) |
| Tauri, Capacitor, PyInstaller, releases | [Delivery](./open_agent/delivery/index.md) |
| Built-in Skill bundle content | [Skill Content](./open_agent/skills/index.md) |

The original bootstrap language guides remain under `open_agent/skills/backend` and `open_agent/skills/frontend`. Despite that generated path, they describe the main repository's Python and Vue conventions, not Skill content.

## Sources of truth

1. Executed code, package manifests, and tests.
2. Current configuration and build scripts.
3. `README.md` and focused current-state docs such as `docs/mobile_shell.md`.
4. Planning documents only when a statement is verified in code.

`docs/Plan.md`, `docs/agent_team.md`, `docs/knowledge_base_implementation_guide.md`, and `docs/openclaw-openhuman-hermes-goal-plan.md` mix completed work, proposals, and future architecture. Never copy their target state into implementation guidance without checking the repository.

## Project boundary

The Trellis default package is `open_agent` at the repository root. The `open_agent/skills` Git submodule is also declared as a package for changes to Skill content itself. Do not assign application backend/frontend tasks to the Skill submodule.
