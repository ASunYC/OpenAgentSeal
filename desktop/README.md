# OpenAgentSeal Desktop Shell

This directory contains the Tauri 2 desktop shell. Tauri owns the native window,
system tray, backend lifecycle, and desktop bundles; the Agent runtime remains in
Python and the UI remains in `open_agent/app/web`.

## Development

From this directory:

```powershell
npm install
npm run dev
```

The development shell starts the Vue dev server and launches the Python backend
from the project environment. Set `OPEN_AGENT_DESKTOP_PYTHON` to select a
specific Python executable.

## Windows x64 release

Run on Windows x64:

```powershell
npm run build
```

The cross-platform Node build pipeline synchronizes versions, builds the Vue UI,
packages the Python backend and standalone CLI with PyInstaller, builds the Tauri
desktop bundles, and writes checksums.

Builds are incremental by default. PyInstaller reuses its analysis cache, and the
Tauri application is compiled once before the native installers are bundled.
Use `npm run build:clean` only when caches are stale or the toolchain changes.

```text
dist/OpenAgentSeal-windows-x64/
├── desktop/installers/OpenAgentSeal_0.1.0_x64-setup.exe
├── desktop/installers/OpenAgentSeal_0.1.0_x64_en-US.msi
├── desktop/portable/OpenAgentSeal.exe
├── cli/OpenAgentSeal-CLI-0.1.0-windows-x64.zip
├── release-manifest.json
└── SHA256SUMS
```

## Linux x64 release

Linux releases are built in the pinned Ubuntu 22.04 Docker environment, so the
Windows host does not need a local Linux toolchain:

```powershell
npm run build:linux:docker
```

```text
dist/OpenAgentSeal-linux-x64/
├── desktop/installers/OpenAgentSeal_0.1.0_amd64.deb
├── desktop/installers/OpenAgentSeal_0.1.0_amd64.AppImage
├── cli/OpenAgentSeal-CLI-0.1.0-linux-x64.tar.gz
├── release-manifest.json
└── SHA256SUMS
```

See [README_LINUX.md](../README_LINUX.md) for installation and execution notes.

## Focused commands

```powershell
npm run build:clean
npm run build:desktop
npm run build:cli
npm run test:packaging
```

`build:desktop` and `build:cli` target the current host platform and preserve the
other release type. macOS packaging is intentionally outside the current release
scope.

Backend logs are written to `%LOCALAPPDATA%\OpenAgentSeal` on Windows and
`$XDG_STATE_HOME/OpenAgentSeal` or `~/.local/state/OpenAgentSeal` on Linux.
