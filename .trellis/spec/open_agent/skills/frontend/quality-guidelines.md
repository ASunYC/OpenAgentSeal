# Frontend Quality Guidelines

## Required by repository configuration

- Target Vue 3, TypeScript, Vite, and Node 18+.
- Keep strict TypeScript and unused/fallthrough checks passing.
- Use the `@/` alias for stable source imports.
- Preserve Vite's relative `base: './'` and output to `open_agent/app/static`; these support packaged desktop builds.
- Account for the three runtime surfaces already present: browser/server UI, Tauri desktop, and Capacitor mobile. Guard platform-only APIs.

## Established implementation practices

- Centralize backend calls and response typing in `src/api/index.ts`.
- Surface async errors and reset busy/loading flags in `finally`.
- Encode path/query identifiers with `encodeURIComponent` or `URLSearchParams`.
- Preserve bilingual strings in desktop settings components.
- Clear intervals, timeouts, WebSockets, and event listeners on teardown or before replacing them.
- Keep pure transition/serialization behavior outside components when it is complex enough to test as a model.

## Tests that actually exist

The frontend uses Node scripts for selected pure models rather than a component-test framework:

- `scripts/test-workspace-selection.mjs`
- `scripts/test-message-queue.mjs`
- `scripts/test-runtime-task.mjs`
- `scripts/test-collaboration-state.mjs`

Add cases there when changing those models. For component/API work, the baseline automated verification is `npm run build:check`; relevant backend API behavior is often covered in the Python suite. Do not assert a mandatory frontend coverage percentage or universal component-test requirement—the project does not currently enforce either.

## Review checklist

- Does `vue-tsc` accept the template and script types?
- Does a loading/busy flag recover on both success and failure?
- Are dynamic/external values narrowed before use?
- Are API payload casing and response shapes consistent with the backend?
- Are browser/Tauri/Capacitor APIs guarded appropriately?
- Are timers/listeners cleaned up and persisted storage backward-compatible?
- Does new settings UI provide both Chinese and English copy?

Avoid introducing a second state, request, styling, or validation framework for a small feature without an existing project precedent.
