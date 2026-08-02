# Workspace, Sandbox and Mobile Boundaries

## Workspace resource manager

`app/runner/workspace_api.py` owns workspace CRUD, file listing/read/write/delete, mkdir/rename/upload/import, search and glob. Workspace metadata is JSON; content operations resolve beneath the selected workspace root.

- Use `safe_join` for client-controlled relative paths.
- Validate rename/upload entry names independently.
- Keep document extraction through existing `doc_extract` helpers.
- Return imported/rejected lists for partial local imports rather than losing per-file reasons.
- Preserve recycle-bin deletion and its `trashed` response.

## Workspace sources and attachments

`app/runner/api.py` separately manages selected source files/directories passed into agent context. This is not the same as resource-manager workspace CRUD. Sanitize and refresh sources through existing helpers before persisting them.

## Sandbox terminal

`app/sandbox.py` creates provider-specific CLI sessions and exposes terminal I/O over `/api/sandbox/sessions/{id}/ws`. Windows terminal support depends on optional `pywinpty`; unsupported platforms/providers return explicit errors. Session cleanup must terminate processes and remove registry state.

## Mobile

`app/mobile.py` owns local pairing, device authorization, mobile summary/chat/history/run APIs and revocation. Pairing creation is restricted to local requests. Bearer tokens authorize mobile requests; browser/Tauri endpoints do not substitute for this check.

Reference tests: `test_workspace_api.py`, `test_safe_join.py`, `test_sandbox.py`, `test_mobile.py`, `test_runtime_capabilities.py`, and `test_doc_extract.py`.
