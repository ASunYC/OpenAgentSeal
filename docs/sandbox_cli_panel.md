# Sandbox CLI Panel Implementation

## Overview

The sandbox CLI panel embeds Windows interactive CLI tools inside the OpenAgentSeal desktop app. It is designed for `agent-switch` workflows, so users can launch tools such as `claude`, `codex`, and `opencode` from the main UI without leaving the app.

This is not a security sandbox. It is an integrated CLI workspace that runs in the configured global workspace directory and keeps terminal sessions alive while the app is running.

## User Experience

- The main toolbar has a sandbox button.
- Clicking the button opens a right-side workspace panel, consistent with browser and conversation panels.
- Clicking it again hides the panel, but existing terminal sessions stay alive in the background.
- Each CLI launch creates a terminal tab.
- Users can switch between tab layout and grid layout.
- Closing a terminal tab is the explicit action that terminates that PTY session.

Supported providers are currently fixed:

- `claude`
- `codex`
- `codewhale`
- `deepseek`
- `kimi`
- `opencode`

The backend validates providers against this allowlist. The frontend cannot submit arbitrary commands.

## Frontend Architecture

Main files:

- `open_agent/app/web/src/components/SandboxPanel.vue`
- `open_agent/app/web/src/stores/sandbox.ts`
- `open_agent/app/web/src/api/index.ts`

The frontend uses:

- `@xterm/xterm` for terminal rendering.
- `@xterm/addon-fit` for responsive terminal sizing.
- A Pinia sandbox store for application-runtime state.

The store keeps:

- terminal tabs
- active tab id
- layout mode: `tabs` or `grid`

The store intentionally does not persist live PTY sessions across app restarts. A backend PTY process cannot be restored after the desktop backend exits.

## Layout Handling

The sandbox panel supports two layouts:

- `tabs`: only the active terminal is visible.
- `grid`: all terminals are visible at once.

Grid rules:

- 1 terminal: 1 column
- 2 terminals: 2 columns
- 3-4 terminals: 2 columns
- 5+ terminals: 3 columns

xterm must be fitted only after its DOM container is visible. The panel therefore uses:

- `ResizeObserver`
- `requestAnimationFrame`
- `nextTick`
- a `refitVisibleTerminals()` path that fits either the active terminal or all grid terminals

This avoids the common xterm bug where hidden terminals calculate zero-width columns.

## Backend Architecture

Main file:

- `open_agent/app/sandbox.py`

Backend API:

- `GET /api/sandbox/cli-status`
- `POST /api/sandbox/sessions`
- `WebSocket /api/sandbox/sessions/{session_id}/ws`
- `DELETE /api/sandbox/sessions/{session_id}`

The backend uses `pywinpty` to create Windows PTY sessions. Each session is stored in an in-memory `_sessions` map for the lifetime of the backend process.

WebSocket lifecycle is intentionally decoupled from PTY lifecycle:

- WebSocket disconnect means the UI is hidden, refreshed, or temporarily disconnected.
- It does not terminate the PTY.
- `DELETE /sessions/{id}` or a WebSocket `terminate` message terminates the PTY.

Each backend session also keeps a bounded output buffer. When the frontend reconnects, recent output is sent first, then live output continues.

## Command Launching

The backend launches commands through `agent-switch`:

```text
agent-switch <provider> --dir <capture_dir>
```

On Windows, npm-installed commands may resolve to `.ps1` before `.cmd`. That is a problem for `cmd.exe` based PTY launching. The backend therefore prefers runnable command forms:

1. direct `.cmd`, `.exe`, `.bat`, `.com`
2. `where.exe`
3. fallback command name

The final command is wrapped as:

```text
cmd.exe /d /c call <resolved-agent-switch> <provider> --dir <capture_dir>
```

The `call` keyword is important for `.cmd` scripts.

## Capture Directory

`agent-switch` needs a writable capture/session directory. The backend tries these locations in order:

1. `OPEN_AGENT_SANDBOX_AGENT_SWITCH_DIR`
2. OpenAgentSeal data directory: `data/sandbox/agent-switch`
3. `%LOCALAPPDATA%/OpenAgentSeal/sandbox/agent-switch`
4. `<workspace>/.agent-switch/sessions`

Each candidate is write-tested before use.

## Packaged Desktop Build

This feature has an important PyInstaller packaging requirement.

`pywinpty` needs runtime binaries in addition to Python modules:

- `winpty-agent.exe`
- `OpenConsole.exe`
- `winpty.dll`
- `conpty.dll`
- `winpty.cp311-win_amd64.pyd`

The normal PyInstaller analysis included only the DLL/PYD files in our packaged app, which caused the packaged sandbox session to fail with errors such as:

```text
Failed to start sandbox terminal: Unknown error
Sandbox session not found
```

The packaging plan in `scripts/package-release.mjs` explicitly includes the
missing runtime executables for Windows builds.

Relevant PyInstaller flags:

```powershell
--add-binary "$WinptyAgentExe;winpty"
--add-binary "$WinptyOpenConsoleExe;winpty"
```

The sidecar also avoids `--noconsole` because interactive PTY creation is more reliable when the PyInstaller bootloader is not the windowed subsystem. Tauri still launches the sidecar without showing an extra console window.

## Verification

Frontend build check:

```powershell
npm --prefix open_agent\app\web run build:check
```

Backend tests:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_sandbox.py tests\test_mcp.py -q
```

Package build:

```powershell
npm --prefix desktop run build
```

Packaged runtime check:

```powershell
Invoke-RestMethod http://127.0.0.1:9998/api/sandbox/cli-status
```

Expected result:

- `windows: true`
- `pty_available: true`
- `agent_switch_available: true`
- available providers marked `ready`

Manual API session check:

```powershell
@'
const base = 'http://127.0.0.1:9998';
const created = await fetch(`${base}/api/sandbox/sessions`, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ provider: 'claude', cols: 100, rows: 30 }),
}).then(async r => ({ status: r.status, body: await r.text() }));
console.log('create', created.status, created.body);
const session = JSON.parse(created.body);
const ws = new WebSocket(`ws://127.0.0.1:9998/api/sandbox/sessions/${session.session_id}/ws`);
let output = '';
ws.addEventListener('message', event => { output += String(event.data) + '\n'; });
await new Promise(resolve => setTimeout(resolve, 12000));
console.log(output.slice(0, 2000));
ws.close();
await fetch(`${base}/api/sandbox/sessions/${session.session_id}`, { method: 'DELETE' });
'@ | node -
```

Expected result:

- session creation returns HTTP 200
- WebSocket output contains `agent-switch`
- for Claude, output contains `Claude Code`
- no `Sandbox session not found`
- no immediate `exit`

## Common Failure Modes

### API Error: 404

Usually means the frontend is talking to an older backend, or the sandbox router was not registered in the running app.

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:9998/api/sandbox/cli-status
```

### `Sandbox session not found`

This means the frontend tried to connect a WebSocket session id that is absent from the backend `_sessions` map.

Possible causes:

- stale frontend state after backend restart
- backend failed during session creation
- PTY session exited and was cleaned

For packaged builds, the most important historical cause was missing `pywinpty` runtime binaries.

### `Failed to start sandbox terminal: Unknown error`

In packaged builds, check whether the sidecar archive includes:

```text
winpty\winpty-agent.exe
winpty\OpenConsole.exe
```

Use:

```powershell
.venv\Scripts\pyi-archive_viewer.exe desktop\src-tauri\binaries\open-agent-backend-x86_64-pc-windows-msvc.exe -l
```

### CLI Opens But Does Not Respond

Check these first:

- Is the target CLI installed and visible on PATH?
- Does `agent-switch <provider>` work in a normal terminal?
- Is the provider in the backend allowlist?
- Is xterm attached to a visible DOM container before fitting?

## Design Decisions

- First version is Windows-only.
- Provider list is fixed to avoid turning the panel into an arbitrary command runner.
- Closing the panel only hides it; closing a tab terminates the process.
- Sessions are application-runtime only. They are not restored after app restart.
- PTY output buffering is bounded to avoid unbounded memory growth.
- `agent-switch` capture data is kept outside project source by default.

## Future Improvements

- Add a "stop all" action in the sandbox panel.
- Add per-provider icons and richer availability diagnostics.
- Add optional per-session workspace override.
- Add command transcript export.
- Add a backend debug endpoint for active sandbox sessions.
- Support Linux/macOS with platform-specific PTY implementations.
