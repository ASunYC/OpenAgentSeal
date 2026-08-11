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

## Formal review fix round 1

### RED / GREEN

- RED reproduced all four review findings with seven failures: normal account upsert
  accepted inline/malformed credential values, retained primary and account identifiers
  remained enumerable, a stale K1 repository missed the K2 registry update, and an
  80-item attachment batch attempted all 80 deletions.
- GREEN focused run: 37 passed; `credentials.py` 82%, `retention.py` 93%, combined 86%.
- Tasks 1-5 compatibility run: 257 passed with one upstream
  `python_multipart` deprecation warning.
- Security-focused run (`gateway_security`, `gateway_credentials`, and
  `runtime_retention`): 108 passed.

### Fixes

- Normal `upsert_channel_account` now accepts only `None` or the exact generated
  `oas-cred:<32 lowercase hex>` opaque-reference form. Tests model pre-existing inline
  secrets by isolated direct legacy fixture state; only the serialized migration API
  can replace that state with a validated opaque reference.
- Retention now applies domain-separated HMAC tokens to inbox primary ID, account ID,
  event key, outbox primary ID, destination, idempotency key, and tombstone record ID.
  Tests prove representative email, phone, raw primary IDs, account IDs, payloads, and
  keys are absent from both SQLite and WAL after the secure checkpoint while duplicate
  enqueue still resolves to the tokenized retained row.
- Every tombstone lookup and write is guarded by `BEGIN IMMEDIATE` and revalidates the
  persisted HMAC key registry inside that transaction. A repository initialized with K1
  now fails closed if a rolling K2 repository registers K2 before a later K1 dedupe.
- Attachment enqueue and due selection both use `min(batch_limit, 64)`. Excess supported
  paths are persisted in bounded 64-path backlog pages, audited as deferred, and drained
  over later runs without retaining the original payload or exceeding the per-run queue
  cap. Oversized corrupt payload overflow remains explicitly audited.

### Deferred minor

- The formal reviewer classified the `put_async` ledger concern as deferred and outside
  this fix loop; no behavior change was made for it in round 1.

## Formal review fix round 2

- RED: after a first run filled 64 queue rows with failed deletions and deferred 16
  paths, a second invocation drained the backlog into the already-full queue. The
  regression observed 80 live queue rows instead of the promised global cap of 64.
- GREEN: while holding the existing `BEGIN IMMEDIATE` transaction, retention now counts
  all live deletion queue rows and computes its enqueue budget as the minimum of the
  requested batch limit, 64, and the remaining global occupancy slots. A full queue
  leaves the 16 paths in bounded backlog storage; after acknowledgement removes the 64
  rows, the next run moves all 16 paths into the queue with no loss or duplication.
- The required security suite exposed an existing concurrent migration checkpoint race:
  two successful migrators could concurrently receive SQLite `busy` from WAL truncate.
  `secure_checkpoint` now performs a bounded one-second retry, retaining fail-closed
  behavior if checkpoint contention does not clear.
- Final focused run: 38 passed; `credentials.py` 82%, `retention.py` 93%, combined 86%.
- Final Tasks 1-5 compatibility run: 258 passed with one upstream
  `python_multipart` deprecation warning.
- Final security-focused run: 109 passed.

## Formal review fix round 3

- RED: 64 deletion failures remained active indefinitely, kept global occupancy at 64,
  and prevented the 16-path bounded backlog from ever advancing.
- GREEN: `RetentionPolicy.attachment_max_attempts` now defaults to a finite 5 and is
  validated as an integer from 1 through 100. The worker passes it to repository outcome
  completion; attempts and exponential `next_attempt_at` remain persisted in the active
  queue.
- When the limit is reached, the active row moves atomically into
  `retention_attachment_dead_letters` with its HMAC identifier, recoverable managed path,
  terminal attempt, sanitized error, and quarantine timestamp. The active row is deleted
  only after the quarantine insert succeeds, and the attachment audit records the
  quarantine count. Operator listing is indexed and bounded.
- `requeue_retention_attachment` requires a strict HMAC dead-letter identifier and actor,
  revalidates HMAC keys, serializes with `BEGIN IMMEDIATE`, rejects duplicates, and
  inserts only when global active occupancy is below 64. Success, capacity refusal,
  duplicate, and not-found outcomes are audited without copying the deletion path into
  audit data.
- The regression drives 64 paths through the configured two-attempt limit, proves the
  16-path backlog then fills released slots without loss, fills active occupancy back to
  64 through explicit operator requeue, proves capacity refusal, releases one slot, and
  proves exactly one idempotent requeue succeeds.
- Final focused run: 43 passed; `credentials.py` 82%, `retention.py` 93%, combined 86%.
- Final Tasks 1-5 compatibility run: 263 passed with one upstream
  `python_multipart` deprecation warning.
- Final security-focused run: 114 passed.
