# Composable Guidelines

Vue calls these modules composables rather than hooks. Current reusable composables live in `src/composables/` and use a `use*` name, for example `useMessageQueue.ts` and `useWorkspaceManager.ts`.

## When to create a composable

Use one when stateful behavior is reused or when a large component has a coherent lifecycle/state subsystem. Keep one-off view state inside its component. Pure state transitions without Vue dependencies fit better under `src/models/`.

## Shape

- Create refs/computed values and private helpers inside the `use...` function.
- Return the state and operations the component actually consumes.
- Type arguments, return-bearing operations, stored records, and callbacks.
- Keep storage keys and normalization/serialization helpers close to the composable or in the matching model.
- Register browser listeners/timers through Vue lifecycle hooks and remove/clear them on unmount.

## Data fetching

There is no React Query/SWR equivalent. Components and stores call typed functions from `@/api`, store returned data in refs, and explicitly refresh after mutations.

```ts
loading.value = true
try {
  const data = await logsApi.list()
  files.value = data.files
} catch (err) {
  error.value = err instanceof Error ? err.message : String(err)
} finally {
  loading.value = false
}
```

Do not invent cache invalidation or retry semantics. If polling, timers, or reconnection are needed, follow the owning feature's explicit lifecycle and clean them up.

## Persistence

`useMessageQueue` demonstrates the established local-storage pattern: scope keys by agent/session, parse defensively, migrate legacy keys, persist after mutations, and guard for environments where `localStorage` is unavailable.

Avoid naming Vue composables `hook`, mutating unrelated store state as a hidden side effect, or leaving timers/listeners active after the consumer unmounts.
