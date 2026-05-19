# OpenAgentSeal Desktop Shell

This directory contains the lightweight Tauri desktop shell for OpenAgentSeal.

The desktop shell owns native application concerns only:

- app window
- system tray
- local Python backend lifecycle
- desktop packaging

The tray menu includes Open Window, Open in Browser, Restart Backend, Open Backend Log, and Quit.
Backend stdout/stderr is written to `%LOCALAPPDATA%\OpenAgentSeal\desktop-backend.log` on Windows.

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

This runs `../scripts/build_desktop_sidecar.ps1`, which:

1. builds the Vue frontend,
2. packages the Python backend with PyInstaller,
3. places the sidecar at `src-tauri/binaries/open-agent-backend-x86_64-pc-windows-msvc.exe`,
4. runs the Tauri build,
5. collects installer and portable outputs into `dist/OpenAgentSeal-win-x64`.

Build outputs:

```text
dist/OpenAgentSeal-win-x64/installers/OpenAgentSeal_0.1.0_x64-setup.exe
dist/OpenAgentSeal-win-x64/installers/OpenAgentSeal_0.1.0_x64_en-US.msi
dist/OpenAgentSeal-win-x64/portable/OpenAgentSeal.exe
dist/OpenAgentSeal-win-x64/OpenAgentSeal-portable-win-x64.zip
```
