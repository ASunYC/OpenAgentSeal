# Frontend Directory Structure

## Layout

```text
open_agent/app/web/
├── package.json, vite.config.ts, tsconfig.json
├── scripts/                       # Node regression tests for pure models
└── src/
    ├── main.ts                    # Vue/Pinia bootstrap
    ├── App.vue, DesktopApp.vue    # runtime shells
    ├── api/index.ts               # HTTP/WebSocket clients and API DTOs
    ├── assets/                    # packaged images/static assets
    ├── components/                # shared and large feature components
    │   └── settings/              # one component per settings area
    ├── composables/               # reusable stateful UI logic (`use*`)
    ├── models/                    # pure state-transition/domain models
    ├── services/                  # non-UI service wrappers
    ├── stores/                    # Pinia stores
    ├── types/index.ts             # broadly shared domain/API types
    ├── utils/                     # pure helpers
    └── views/                     # page-level views
```

## Placement

- Keep backend communication in `src/api/index.ts` or an adjacent API module, not as ad hoc `fetch` calls throughout components. Direct `fetch` remains appropriate for multipart upload or specialized streaming, following existing API helpers.
- Put cross-component application state in `stores/`; put reusable stateful behavior in `composables/use*.ts`.
- Put pure, independently testable transition logic in `models/`. `messageQueue.ts`, `runtimeTask.ts`, `collaborationState.ts`, and `workspaceSelection.ts` are exercised by Node scripts.
- Settings screens belong in `components/settings/` and are composed by `SettingsPanel.vue`.
- Keep types local to a component/module when they have one consumer; promote broadly used contracts to `types/index.ts` or export them from `api/index.ts`.

## Naming

- Vue component files use `PascalCase.vue` (`ChatPanel.vue`, `MobileSettings.vue`).
- TypeScript modules use descriptive `camelCase.ts`; composables begin with `use`.
- Variables/functions use `camelCase`, types/interfaces use `PascalCase`, constants use `UPPER_SNAKE_CASE` when truly constant.
- CSS classes use kebab-case and are usually feature-oriented (`settings-shell`, `pairing-view`).
- Import source files with `@/` for cross-directory imports; relative imports are common for closely related modules.

Representative modules: `components/settings/MobileSettings.vue`, `stores/settings.ts`, `composables/useMessageQueue.ts`, and `models/workspaceSelection.ts`.
