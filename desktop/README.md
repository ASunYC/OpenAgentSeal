# OpenAgentSeal Desktop Shell

This directory contains the lightweight Tauri desktop shell for OpenAgentSeal.

The desktop shell owns native application concerns only:

- app window
- system tray
- local Python backend lifecycle
- desktop packaging

The tray menu includes Open Window, Open in Browser, Restart Backend, Open Backend Log, and Quit.
Backend stdout/stderr is written to `desktop-backend.log` at the repository root.

The Agent core remains in Python and the Web UI remains in `open_agent/app/web`.

## Development

From this directory:

```powershell
npm install
npm run dev
```

The Tauri shell starts the Vue dev server and launches the Python backend with:

```powershell
python -m open_agent --web-only --no-browser --host 127.0.0.1 --port 9998
```

Set `OPEN_AGENT_DESKTOP_PYTHON` to force a specific Python executable.

## Build

```powershell
npm run build
```

The first version expects Python and project dependencies to be available on the target machine.
Packaging Python as a bundled sidecar should be handled as a follow-up packaging step.
