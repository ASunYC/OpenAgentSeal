# Frontend Type Safety

## Compiler contract

`tsconfig.json` enables `strict`, `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`, `isolatedModules`, and `noEmit`. New code must pass `npm run build:check` (`vue-tsc --noEmit && vite build`).

## Type placement

- Shared domain contracts live in `src/types/index.ts`.
- API-specific request/response contracts may be exported beside clients in `src/api/index.ts`.
- Component-only records/interfaces stay in the SFC.
- Pure model types are exported from their module under `src/models/`.
- Use `import type` for type-only imports.

## Patterns used

- Type refs that start empty: `ref<ModelConfig[]>([])`, `ref<PluginDetail | null>(null)`.
- Use string-literal unions for finite UI/runtime states (`'connected' | 'checking' | 'offline'`).
- Use generics on the shared request helper: `request<WorkspaceSourceState>(...)`.
- Use `unknown` for untrusted/generic data, then narrow with `typeof`, `Array.isArray`, or `instanceof Error`.
- Use `Awaited<ReturnType<typeof apiMethod>>` when a local state shape should track a client method.
- Backend payload fields remain mostly `snake_case`; UI-only models generally use `camelCase`. Convert explicitly when an API adapter already does so, as in `dashboardApi.getStats()`.

## Runtime validation reality

The frontend has no Zod/Yup-style schema library. Runtime validation is hand-written at risky boundaries such as local-storage parsing, platform detection, and `unknown` API/config values. Do not state that compile-time types validate network or stored data; add focused guards where malformed external data is plausible.

## Exceptions already present

The codebase contains some `any`, broad records, and assertions at dynamic boundaries. Do not expand them without need, but do not claim they are forbidden. Prefer `unknown` plus narrowing for new dynamic data and isolate unavoidable assertions:

```ts
if (value && typeof value === 'object') {
  return Object.keys(value as Record<string, unknown>).length
}
```

Avoid duplicating backend DTOs with conflicting shapes, unchecked non-null assertions for asynchronous state, and casts used solely to silence a real mismatch.
