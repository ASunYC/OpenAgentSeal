# Engineering Conventions

## Languages and toolchains

- Python 3.10+ for the agent/runtime and FastAPI backend.
- Vue 3 + strict TypeScript + Vite for the web application; Node 18+.
- Rust/Tauri for the desktop host.
- Capacitor/Gradle for the Android companion.
- Node scripts orchestrate cross-platform packaging and version synchronization.

## Change placement

- Extend the current owner from [Architecture](./architecture.md); do not create a generic service/repository/schema layer simply because one would be conventional elsewhere.
- Keep boundary contracts typed with Pydantic or TypeScript interfaces, while recognizing that not all current internal dictionaries have models.
- Preserve async interfaces for LLM, tools, MCP, runner streaming, repositories, and FastAPI handlers.
- Use `pathlib.Path`, application path helpers, and explicit UTF-8 for managed text files.
- The codebase mutates operational state. Use immutable replacement where surrounding frontend model code does, but do not impose project-wide immutability.

## Compatibility

Compatibility is a product behavior because users retain local sessions, plugin settings, queues, and config across upgrades.

- Keep old JSON/local-storage shapes readable when changing persisted data.
- Make migrations idempotent and skip already migrated records.
- Preserve API/event fields consumed by Python, Vue, mobile, and stored runtime history.
- When renaming config fields, update precedence/defaults, API models, UI forms, persistence, and packaging.
- When changing versioning, update all locations owned by `scripts/sync-version.mjs` rather than one manifest.

## Error and logging reality

- FastAPI expected failures use `HTTPException`; domain helpers may raise focused exceptions; tool/plugin operations often return structured success/error results.
- Optional discovery and cleanup boundaries catch broad exceptions, log context, and continue. Do not generalize that pattern to required operations.
- Standard modules use `logging.getLogger(__name__)`. `AgentLogger` is a separate product log that records model/tool interactions.
- API envelopes are not uniform. Match the endpoint family and TypeScript consumer.

## Existing detailed language guides

- Python: `open_agent/skills/backend/` under this spec tree.
- Vue/TypeScript: `open_agent/skills/frontend/` under this spec tree.

The `skills` path came from the initial Trellis submodule misdetection; these documents remain useful as language guides but do not define the ownership of `open_agent/skills` content.

## Git conventions

Recent history uses Conventional Commit prefixes such as `feat`, `fix`, `docs`, `build`, and scoped forms like `feat(cli)`. Match the repository and describe the actual change. Do not bypass commit or push hooks.
