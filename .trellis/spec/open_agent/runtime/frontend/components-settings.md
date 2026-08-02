# Components and Settings Surfaces

## Ownership

- `ChatPanel.vue`, `DualChatPanel.vue`, `ThinkingProcess.vue`: primary conversation and execution display.
- `Sidebar.vue`: chat/navigation surface.
- `SettingsPanel.vue`: settings navigation and composition.
- `components/settings/*Settings.vue`: one settings feature per file.
- `SandboxPanel.vue`: terminal session UI.
- `views/WorkspaceManager.vue`: resource-manager page.

## Settings convention

Settings components normally load on mount, expose loading/error/busy state, call a typed API group, and reload after mutations. Desktop settings copy is bilingual through `settingsStore.t(zh, en)`; add both strings.

Plugin, MCP, model, provider and web-search screens expose configuration that may contain credentials. Keep masked values masked and do not put secret values into generic component logs or alerts.

## Styling

Components use Vue SFCs and mostly scoped handwritten CSS. Reuse shared settings classes/CSS variables and neighboring visual language. Tailwind is installed but is not the prevailing component convention.

See the detailed component, state, type and quality guides under `../../skills/frontend/`. There is no formal component-test or accessibility gate; retain labels, button types, disabled states and destructive confirmations present in the surrounding UI.
