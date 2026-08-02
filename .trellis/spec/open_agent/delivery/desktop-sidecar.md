# Desktop Host and Python Sidecar

## Ownership

- `desktop/src-tauri/src/main.rs`: Tauri process, tray/window commands and backend sidecar control.
- `desktop/src-tauri/tauri.conf.json`: dev/build commands, bundle resources, capabilities and `externalBin`.
- `desktop/src-tauri/capabilities/default.json`: allowed local HTTP targets and Tauri capabilities.
- `open_agent/app/static`: built Vue files served/embedded for packaged operation.
- `scripts/package-release.mjs`: produces the Python backend binary in the name/location Tauri expects.

## Runtime relationship

The desktop webview connects to the local Python FastAPI backend. Frontend Tauri detection selects `127.0.0.1:9998`; the host starts and supervises the sidecar. Changing the port, binary name or readiness behavior requires coordinated updates across Rust, Tauri config, frontend API constants, Python launch and packaging tests.

Tauri-only UI actions use `@tauri-apps/api` dynamic imports/invocations. Keep browser fallback behavior because the same Vue application runs outside Tauri.

## Verification

- Rust/Tauri configuration or host change: compile/run the appropriate Tauri target.
- Sidecar naming/layout change: update and run `desktop` packaging tests.
- Static path/base change: build the web bundle and exercise packaged loading, not only Vite dev.

Do not manually place a development Python executable in `desktop/src-tauri/binaries` as a source change; the release script owns generated sidecars.
