# Frontend State Management

## State categories in this application

- **Component state:** `ref`/`reactive` inside SFCs for loading, errors, selected rows, form values, and transient UI state.
- **Derived state:** `computed`, e.g. filtered marketplaces and selected agents.
- **Application state:** Pinia stores in `src/stores/` for agents, chats, settings, and sandbox state.
- **Reusable feature state:** composables such as `useMessageQueue` and `useWorkspaceManager`.
- **Persistent browser state:** explicit `localStorage` keys for language, mobile server/token/agent, and message queues.
- **Server state:** fetched explicitly through `src/api/index.ts`; there is no generic client cache.

## Choosing a home

Keep state local until multiple components or runtime shells need it. Use a Pinia store when the state represents an application domain and has shared actions/getters, as in `stores/chat.ts` and `stores/settings.ts`. Use a composable when the shared unit is behavior/lifecycle rather than a global domain singleton.

Stores use the Pinia style already present in the target file; the repository includes setup-style stores with refs/computed/actions. Components should call store actions rather than duplicate domain synchronization logic.

## Mutation and derived data

The application is not immutable by convention. Vue refs, arrays, queue items, and store records are mutated where reactivity benefits from it. Existing code also uses replacement/map/filter when changing collections. Match the local model and ensure persistence is triggered after mutable queue edits.

Do not store a derived filtered list separately unless it must have an independent lifecycle; use `computed`:

```ts
const pluginCount = computed(() =>
  marketplaces.value.reduce((count, item) => count + item.plugins.length, 0),
)
```

## Server synchronization

- Load explicitly on mount or through a store action.
- After a successful mutation, update local state or reload through the feature's existing `load...` function.
- Represent request progress and user-facing errors explicitly.
- Do not assume API responses share one envelope; use the declared endpoint type.

## Storage compatibility

Read local storage defensively, namespace keys, and preserve migrations when changing formats. `models/messageQueue.ts` plus `composables/useMessageQueue.ts` are the reference for parsing and migrating persisted UI state.
