# Vue Component Guidelines

## SFC structure

Existing components normally use this order:

```vue
<template>
  <section class="feature-panel">...</section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
// typed state, computed values, handlers, lifecycle
</script>

<style scoped>
/* feature styles */
</style>
```

Some shell/root components use unscoped shared CSS. Preserve the style scope of the component being edited.

## Props and events

- Use typed `defineProps` and `defineEmits` in `<script setup>`.
- Keep a component-only interface beside the component, as `LogFile` and `TaskRecord` are defined in their settings components.
- Use shared types from `@/types` or exported API contracts when data crosses several modules.
- Parent-owned state is changed through emitted events; do not mutate props.

## UI logic

- Use `ref` for mutable local state and `computed` for derived views/filtering.
- Async loaders set a loading flag, clear the previous error, use `try/catch/finally`, and start from `onMounted` with `void load...()`.
- Normalize unknown errors consistently:

```ts
} catch (err) {
  error.value = err instanceof Error ? err.message : String(err)
} finally {
  loading.value = false
}
```

- The desktop settings UI is bilingual. Components commonly define `t(zh, en)` as a small wrapper over `settingsStore.t`; keep both strings when adding labels/messages in those screens.
- Runtime-specific operations are feature-detected or dynamically imported, e.g. Tauri's `invoke` in `LogsSettings.vue` and Capacitor checks in `api/index.ts`.

## Styling and accessibility in current code

- Styles are handwritten CSS with semantic, feature-specific classes. Reuse existing CSS variables and shared settings classes before creating new visual systems.
- Buttons set `type="button"` when inside forms unless submission is intended.
- Inputs are normally paired with visible text/labels and disabled while their action is busy.
- Destructive actions ask for confirmation in existing settings screens.
- Icon-only controls should retain an accessible `title`/label if neighboring controls use one. The codebase does not currently enforce a formal a11y test suite, so do not claim one.

Examples: `components/settings/PluginsSettings.vue`, `MobileSettings.vue`, `LogsSettings.vue`, and `TasksSettings.vue`.
