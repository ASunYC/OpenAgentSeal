# Release Pipeline

## Authority

`desktop/package.json` delegates desktop, CLI, mobile and combined builds to `scripts/package-release.mjs`. The script plans target triples, builds the Vue app, produces PyInstaller artifacts, compiles/bundles Tauri, gathers Android output, and assembles/checksums release directories.

Use its exported planning helpers and `scripts/tests/package-release.test.mjs` when changing behavior; avoid duplicating platform logic in package scripts.

## Version synchronization

`scripts/sync-version.mjs` updates the tracked version authorities/consumers, including `version.json`, Python/CLI, web/desktop Node manifests, Rust/Tauri and Android files. Change the mapping and its test when adding a new version-bearing manifest.

## Caches and clean builds

Normal builds intentionally retain PyInstaller, Cargo and other caches. `build:clean` is for stale caches/toolchain changes. Linux Docker builds use BuildKit cache mounts and retry failed builds; do not add unconditional recursive cache deletion to routine builds.

## Artifact invariants

- Tauri external binary name matches the built sidecar target.
- Vue static output is present before desktop packaging.
- Platform bundle directories are selected by the release script helpers.
- Android APK is copied from the expected Gradle output.
- Checksums/version metadata describe the assembled artifacts.

Run `cd desktop && npm run test:packaging` for planning/version changes. A full platform build is warranted for toolchain, sidecar, bundle-resource or artifact-layout changes, but not for unrelated runtime docs/code.
