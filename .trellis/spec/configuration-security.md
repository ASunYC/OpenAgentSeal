# Configuration and Security Boundaries

## Configuration ownership and precedence

| Source | Consumer and role | Secret policy |
|---|---|---|
| `open_agent/config/config.yaml` | `Config.load()` development/package defaults | Do not add real credentials |
| `~/.open-agent/config/config.yaml` | user override found before packaged fallback | Local credentials/settings may live here; never commit |
| `open_agent/config/mcp.json` and user equivalent | MCP server definitions loaded by `mcp_loader.py` | Prefer environment expansion for credentials |
| `open_agent/user_config.py` models | web/CLI-editable model, system, routing settings | Stored under application data; API responses must mask secrets where defined |
| plugin manifests and `.open-agent/settings.json` | `PluginManager` marketplace metadata and settings schema | Schema is publishable; values live in the application data plugin store |
| browser `localStorage` | language, mobile target/token/agent, scoped message queue | Never treat it as a server-side secret store |
| `version.json`, Python/Node/Rust/Android manifests | release version consumers | Updated together by `scripts/sync-version.mjs` |

`Config.find_config_file()` resolves development config, user config, then package config. Keep related `config.yaml`, `mcp.json`, and prompt resources within the selected config directory; do not add a second undocumented precedence chain.

## Filesystem boundaries

- Application state belongs under paths returned by `open_agent/utils/path_utils.py`, particularly `get_data_dir()` and its config/log/session/profile subdirectories.
- Workspace operations must resolve user paths with `open_agent/utils/safe_join.py`. Path traversal is translated to HTTP 403 and covered by `tests/test_workspace_api.py`.
- Rename/upload names are a single path segment; reject `..`, separators, and names whose `Path.name` differs.
- Deletion in the workspace API uses `send2trash` where implemented; preserve the `trashed` contract.
- Local attachments/workspace sources are sanitized before persistence and must not silently escape configured roots.

## Mobile and local service boundary

- FastAPI normally listens on the local backend port used by the web/Tauri clients (`127.0.0.1:9998` in frontend/desktop configuration).
- Pairing-code creation is local-only. Mobile devices authenticate with bearer tokens issued by `open_agent/app/mobile.py`.
- Tokens are persisted for the mobile client in local storage and must not appear in logs, summaries, or API error details.
- Revocation must invalidate the stored device authorization, not merely hide it in the UI.

## Plugins, MCP, and secrets

- Plugin settings marked `secret` are stored in the plugin data area. Detail/list responses expose a mask (`********`), while the effective MCP configuration receives the real value; see `tests/test_plugins.py`.
- Placeholder expansion in plugin MCP config includes known runtime values and settings. Missing/invalid placeholders produce warnings rather than exposing raw settings.
- MCP stdio commands and remote endpoints are external execution/network boundaries. Preserve explicit timeout configuration and cleanup in `mcp_loader.py`.
- Disabled plugins contribute neither Skill roots nor MCP servers at runtime. A settings view may request disabled server metadata explicitly.

## Security checks for relevant changes

- File APIs: traversal, symlink/root confinement, filename validation, recycle-bin behavior.
- Mobile: local-only pairing, token checks, revocation, no token leakage.
- Plugins/config: secret masking, masked-update preservation, placeholder expansion, publishable manifests without values.
- Tool execution: retain `ToolRegistry` risk/capability metadata and the selected tool access mode.
- SQL: use SQLite parameters; never interpolate user-controlled values.
- UI rendering: Markdown is rendered through the existing marked/highlight pipeline; do not introduce raw unsanitized HTML paths without reviewing the renderer.

The repository does not currently provide global authentication, CSRF middleware, or rate limiting for every FastAPI endpoint. Record and preserve actual local trust assumptions; do not state that these controls universally exist.
