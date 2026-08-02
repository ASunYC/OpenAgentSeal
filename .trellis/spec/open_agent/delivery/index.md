# Desktop, Mobile and Release Delivery

| Guide | Covers |
|---|---|
| [Desktop and Sidecar](./desktop-sidecar.md) | Tauri host, Python backend sidecar and static assets |
| [Mobile Companion](./mobile-companion.md) | Capacitor Android packaging and server pairing |
| [Release Pipeline](./release-pipeline.md) | build orchestration, versions, caches and artifacts |

Delivery is cross-language: a working Vite dev server does not prove the packaged Tauri app works, and a working Python CLI does not prove the sidecar layout is correct. Use `scripts/package-release.mjs` as the current build authority.
