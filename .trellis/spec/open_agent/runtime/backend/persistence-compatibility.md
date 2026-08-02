# Runtime Persistence and Compatibility

OpenAgentSeal is local-first. There is no ORM or migration CLI.

## Stores

| Data | Current store |
|---|---|
| Chat metadata | `chat_YYYYMM.json` through `JsonChatRepository` |
| Messages | monthly SQLite through `MonthlyMessageRepository` |
| Runtime context/events | runner context store files/database owned by `context_store.py` |
| Workspace source selection | application-data JSON managed by runner API |
| Agent profiles/settings/plugins | application-data JSON/config stores |

Detailed query/write conventions are in `../../skills/backend/database-guidelines.md`.

## Compatibility pattern

Migration is code-based and opportunistic at store initialization. `_migrate_legacy_session_dir()` and `_migrate_legacy_chats()` copy/import legacy data while skipping existing targets. Frontend local-storage state uses the same read-old/write-new principle.

For persisted changes:

1. Identify every reader and writer.
2. Add a default/legacy parser before writing the new shape.
3. Keep migration idempotent.
4. Invalidate repository caches after writes.
5. Add a test that starts from the old shape and verifies the new runtime result.

Do not silently replace corrupted required data with success. Some metadata loaders currently log and return an empty model; follow the specific store's established recovery semantics and document any data-loss tradeoff.
