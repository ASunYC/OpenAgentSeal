# Frontend API, State and Events

## API ownership

`src/api/index.ts` currently owns typed HTTP clients, SSE readers, WebSocket URL construction, platform-specific base URLs, and the unified API object consumed by stores. It is large but authoritative; do not add direct component fetches for ordinary JSON endpoints.

Exceptions already present are multipart uploads and streaming, which still belong in the API layer.

## Chat state flow

```text
ChatPanel -> stores/chat.ts::sendMessage()
  -> runAgentStream(session, messages, ...)
  -> AgentEvent loop
  -> message/thinking/tool/error/terminal branches
  -> explicit chat/history persistence and UI state reset
```

`complete` or `status === 'idle'` terminates a normal run; `error` surfaces an error. Cancellation and newer runtime events must leave loading/running state consistent.

## State ownership

- Pinia stores: agent, chat, settings and sandbox application domains.
- Component refs: transient form/loading/selection state.
- Composables: reusable behavior such as message queue and workspace manager.
- Pure models: message queue, runtime task, collaboration and workspace selection transitions.
- `localStorage`: scoped queue migration and a small set of user/runtime choices.

Do not duplicate server state in multiple stores without an explicit synchronization path. After mutations, follow the feature's existing local update or reload pattern.

## Tests

Run `npm run build:check` for TypeScript/template changes. Update the matching Node script for pure model changes. Backend event/API changes require Python producer tests as well.
