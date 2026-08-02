# Verification and Delivery

## Verification matrix

| Change | Minimum focused verification |
|---|---|
| Python behavior | Relevant `pytest tests/test_<feature>.py` |
| FastAPI route | `TestClient` tests plus state/filesystem assertion |
| Agent/LLM/tool/MCP | Relevant agent, LLM, tool, MCP, integration, or recovery tests |
| Vue/TypeScript | `cd open_agent/app/web && npm run build:check` |
| Pure frontend state model | Matching `npm run test:*` script |
| Packaging/version scripts | `cd desktop && npm run test:packaging` |
| Android build behavior | Relevant package-release test; full mobile build only when required |
| Tauri host/Rust | Tauri/Rust compile or packaging path appropriate to the change |

Run the narrowest relevant test first, then expand according to blast radius. Python pytest uses `asyncio_mode = "auto"` and temporary filesystem/environment fixtures extensively.

## Current gates—not aspirational gates

- Python has pytest and pytest-cov dependencies, but no enforced coverage percentage.
- The frontend enforces strict TypeScript through `build:check`; it has Node regression scripts for selected pure models, not a general component test runner.
- No repository-wide formatter or linter is configured as a universal gate.
- Generated/bundled Skill content is not validated by the main Python suite unless loader/plugin behavior is under test.
- A successful docs-only change does not require building desktop and Android artifacts.

## Build and run entry points

```bash
# Python/CLI/web
open-agent
open-agent-cli
open-agent --web-only --port 9998
pytest

# Web
cd open_agent/app/web
npm run dev
npm run build:check

# Desktop/release orchestration
cd desktop
npm run dev
npm run build
npm run build:desktop
npm run build:cli
npm run build:mobile
npm run test:packaging
```

`desktop/package.json` delegates release builds to `scripts/package-release.mjs`. That script builds the Vue static bundle, PyInstaller sidecars/CLI artifacts, Tauri bundles, Android output, checksums, and release layout according to the selected target. `build:clean` is exceptional; normal builds retain caches.

Linux x64 uses `scripts/build-linux-docker.mjs` and `scripts/docker/linux-x64.Dockerfile`; unless `--skip-mobile` is supplied, the Android companion is built on the host before the Docker desktop/CLI build.

## Delivery invariants

- Vue output remains `open_agent/app/static` with relative Vite base for packaged loading.
- Tauri `externalBin` expects the packaged Python backend sidecar name/layout.
- Desktop development and packaged clients expect the backend address/capabilities declared in Tauri and frontend configuration.
- `scripts/sync-version.mjs` is the authority for synchronized Python, Node, Rust, Tauri, Android, and `version.json` versions.
- Do not manually delete build caches or target directories as part of routine verification.
