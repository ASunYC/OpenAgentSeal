# Frontend Development Guidelines

> Conventions observed in `open_agent/app/web`. They describe the current Vue application across browser, Tauri desktop, and Capacitor mobile runtimes.

## Stack

- Vue 3 Composition API with single-file components and `<script setup lang="ts">`.
- TypeScript in strict mode, Vite, and the `@/` alias for `src/`.
- Pinia for application-wide client state.
- Plain `fetch` behind API helper modules; no query/cache library.
- Component/global plain CSS, usually with scoped component styles; Tailwind is installed but is not the dominant component style.

## Guides

| Guide | Scope |
|---|---|
| [Directory Structure](./directory-structure.md) | Source layout and placement |
| [Component Guidelines](./component-guidelines.md) | Vue SFCs, props, events, and styles |
| [Composable Guidelines](./hook-guidelines.md) | `use*` composables and lifecycle cleanup |
| [State Management](./state-management.md) | Local refs, Pinia, storage, and server data |
| [Quality Guidelines](./quality-guidelines.md) | Build checks, runtime support, and tests |
| [Type Safety](./type-safety.md) | Interfaces, API types, and runtime narrowing |

## Verification commands

```bash
cd open_agent/app/web
npm run build:check
npm run test:workspace-selection
npm run test:message-queue
npm run test:runtime-task
npm run test:collaboration-state
```

Run the model test relevant to the change. The repository currently has no component-test runner or frontend coverage threshold.
