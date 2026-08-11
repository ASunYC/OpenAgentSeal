# Task 5 Report: Credential Store and Retention

## Outcome

Implemented an opaque-reference credential store with a Windows Credential Manager
backend and a bounded, audited retention worker. SQLite never stores credential secret
bytes, credential ciphertext, credential encryption keys, or retention HMAC key bytes.

## RED / GREEN evidence

- RED: `pytest tests/test_gateway_credentials.py tests/test_runtime_retention.py -v`
  failed during collection because `open_agent.gateway.credentials` and
  `open_agent.durable_runtime.retention` did not exist.
- GREEN focused run:
  `pytest tests/test_gateway_credentials.py tests/test_runtime_retention.py -q
  --cov=open_agent.gateway.credentials --cov=open_agent.durable_runtime.retention
  --cov-report=term-missing`
  completed with 31 passed; `credentials.py` 82%, `retention.py` 93%, combined 86%.
- Compatibility run across Tasks 1-5 completed with 251 passed and one upstream
  `python_multipart` deprecation warning.

## Credential backend and mock contract

- `CredentialStore` exposes opaque `oas-cred:<uuid>` references and supports put,
  resolve, rotate, revoke, delete, legacy migration, and account-bound sync/async APIs.
- `AccountCredentialStore` is the account-bound facade intended for integrations; it
  prevents resolving or mutating another account's reference.
- `MemoryCredentialBackend` is test-only and keeps secret ownership outside SQLite.
- The Windows backend mock verifies the pywin32 generic credential contract:
  `CredWrite(dict, Flags=0)`, `CredRead(TargetName, CRED_TYPE_GENERIC, Flags=0)`, and
  `CredDelete(TargetName, CRED_TYPE_GENERIC, Flags=0)`, with
  `CRED_PERSIST_ENTERPRISE`, `TargetName`, string `CredentialBlob`, and `UserName`.
- Both `OSError` and real `pywintypes.error` failures are translated to redacted domain
  errors without chaining a backend message that can disclose an opaque target.
- Blocking Windows operations and all async credential operations are moved to worker
  threads with `asyncio.to_thread`.

## Migration, rotation, revocation, and deletion

- Legacy inline secrets are written to the external backend and replaced atomically by
  an opaque reference. A `BEGIN IMMEDIATE` serialization boundary prevents a stale
  concurrent migrator from overwriting a later rotation.
- Rotation immediately replaces the backend value. Revocation makes resolution fail
  closed, and deletion removes the external secret.
- Tests cover sequential and concurrent legacy migration, immediate lifecycle effects,
  redacted diagnostics, async thread offload, and account isolation.

## Retention and attachment safety

- Terminal inbox payloads, outbox delivery details/destinations, and expired audit rows
  are processed in indexed, bounded transactions. Raw idempotency and scope values are
  replaced while HMAC tombstones preserve replay/idempotency semantics.
- Retention HMAC keys come from an external credential provider. SQLite stores only a
  key identifier; startup fails closed if a historical key is unavailable. Current and
  bounded previous keys support rotation and acknowledgement of existing attachment
  queue entries.
- Attachment paths enter a persistent retry queue before payload redaction. Deletion
  results are audited; failures receive exponential backoff so one bad path cannot
  starve newer work. Queue queries use the due-work index and a hard limit.
- Normal ingress is capped at 64 attachments. Oversized/deep corrupt payloads are
  bounded to 64 extracted paths, immediately redacted/tombstoned, and explicitly
  audited as overflow rather than becoming a retention poison pill.
- Windows deletion opens the target with `FILE_FLAG_OPEN_REPARSE_POINT`, rejects
  reparse points/directories, validates `GetFinalPathNameByHandle` beneath the managed
  root, and deletes the verified handle with `FileDispositionInfo`.
- POSIX deletion traverses from a managed-root directory descriptor using
  `openat`/`dir_fd` plus `O_NOFOLLOW`, verifies the opened regular file, and unlinks via
  its verified parent descriptor. Tests cover traversal, absolute paths, symlinks,
  missing files, retries, and Windows path normalization.
- `PRAGMA secure_delete=ON` plus `wal_checkpoint(TRUNCATE)` ensures deleted/redacted PII
  is absent from both the database and WAL before a successful run returns.

## Repository and schema extensions

The repository was minimally extended with retention batch, attachment queue,
tombstone, HMAC key registry, credential migration, audit, and secure checkpoint APIs.
The control-plane schema adds additive retention columns/tables/indexes; migration tests
prove old databases add columns before indexes that reference them. `retention.py`
contains no ad-hoc SQL.

## Review and verification

- Final code review: APPROVE, 0 Critical / 0 High.
- Final security review: PASS, 0 Critical / 0 High; reviewer independently ran 102
  credential/retention/gateway-security tests successfully.
- `python -m compileall -q` passed for all modified runtime modules.
- `git diff --check` passed (line-ending conversion warnings only).

## Commit

Planned conventional commit: `feat: secure channel credentials and retention`.

## Concerns / follow-up

- The unscoped lifecycle methods remain for the Task 5 public interface and migration
  capability; production integrations should expose only `AccountCredentialStore`.
- Retention HMAC key history is deliberately bounded. Operators must retain every key
  identifier still registered by SQLite during rotation; missing historical keys fail
  startup rather than silently losing tombstone matches.
- Overflow attachment auditing is a corruption/security fallback. Supported ingress is
  constrained to the same 64-path retention bound, so integrations must not bypass the
  attachment policy when constructing durable payloads.
