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

## Formal review fix round 4

### RED / GREEN

- Initial RED checkpoint: 21 fencing/authentication regressions failed while 28 prior
  tests passed. The failures covered tampered due/dead rows, same-path stale workers,
  immutable file identity, authenticated CAS accounting, active/dead ambiguity, legacy
  migration, and historical-key failure. The tests were preserved in commit `88e53e0`.
- Review RED checkpoint: two focused tests reproduced an expired five-minute claim still
  authorizing/completing work and `apply_retention_batch` returning a claim for an
  authenticated active+dead overlap (`2 failed, 52 deselected`). The strengthened tests
  were preserved in commit `5fd3adc` before the implementation fix.
- GREEN focused run: `tests/test_runtime_retention.py` — 75 passed, 2 POSIX-only
  tests skipped on Windows and executed separately under WSL/ext4.
- GREEN repository/credential compatibility run — 142 passed, 2 skipped.
- GREEN security-focused run (`gateway_security`, `gateway_credentials`, and
  `runtime_retention`) — 159 passed, 2 skipped.
- GREEN Tasks 1-5 compatibility/coverage run — 318 passed, 2 skipped, with one upstream
  `python_multipart` deprecation warning. Coverage was 88% for `repository.py`, 86% for
  `retention.py`, 82% for `credentials.py`, and 87% combined.

### Authenticated occurrence and claim fencing

- Every active occurrence now has independent random `work_id` and `generation` values;
  queue/dead identifiers authenticate the domain, kind, `key_id`, work ID, generation,
  and storage path. A row is authenticated before its path is placed in a filesystem
  claim, so a path/key/ID/work/generation mutation fails closed before exposure.
- Claiming is a serialized compare-and-swap that returns the complete owner, random
  token, monotonically increasing claim generation, exact expiry, and occurrence
  identity. Authorization and completion require all claim fields plus the persisted
  expiry to match and require the lease to remain unexpired. An expired or superseded
  worker is counted as stale and cannot delete, retry, quarantine, or acknowledge the
  current occurrence.
- Completion removes or changes an active row only when its authenticated claim CAS
  affects exactly one row. Successful deleted/missing/rejected/failed/quarantined counts
  are incremented only after that transition; stale and absent/no-op outcomes have
  separate counters and audit fields.

### Immutable filesystem-object fencing

- The filesystem worker opens the target without following links/reparse points, checks
  that the opened regular object stays below the managed root, and derives a versioned
  identity from the opened handle (`device/inode/ctime/mtime/size` on POSIX; volume/file
  index/write version/size on Windows).
- The repository binds that identity to the authenticated occurrence with a separate
  HMAC tag and moves the claim to the fail-closed `deleting` state before filesystem
  deletion. The worker re-reads the opened identity (and the POSIX named entry) before
  deleting. A replacement object or identity/tag mutation is rejected without deleting
  or acknowledging it.
- `deleting` claims are deliberately not auto-reclaimed after expiry: an older process
  may still hold the authorized handle, so automatic same-path reuse would make a later
  occurrence unsafe. A crash after authorization therefore requires explicit operator
  repair rather than a destructive guess.

### Dead-letter rotation and state migration

- Dead-letter listing and requeue authenticate the dead-letter identifier against its
  path, `key_id`, work ID, generation, and optional file-identity tag. Missing historical
  keys abort before mutation. A successful K1-to-K2 requeue registers K2 in the same
  transaction, revalidates the key registry, creates a brand-new work ID/generation,
  inserts the K2 active occurrence, and deletes exactly the authenticated K1 dead row.
- A path cannot be active and dead simultaneously. Repository initialization, batch
  ingress, claiming, authorization, completion, and requeue assert this invariant inside
  their write transaction. Legacy path-only rows, missing immutable identity, ambiguous
  active+dead state, partial version metadata, or unavailable keys require explicit
  operator migration and fail without changing either row.

### Verification

- Final security review: **APPROVE, 0 Critical / 0 High / 0 Medium**. It independently
  exercised real POSIX deletion/race cases and a concurrent key-registry serialization
  reproduction.
- A final quick security gate for the stricter unsigned-legacy-source handling also
  returned **APPROVE, 0 Critical / 0 High / 0 Medium** after 15 relevant tests.
- Final code review: **APPROVE, 0 Critical / 0 High / 0 Medium** after independently
  rerunning the focused retention suite (75 passed, 2 skipped).

### Adversarial RED checkpoints and final closure

- Commit `ad787a8` preserves ten additional security-gate REDs for unsigned backlog
  laundering, recursive raw-path trust, a frozen operation clock, pre-open replacement,
  missing POSIX quarantine, and cross-platform path aliases.
- A later focused RED showed that replacing A with B after durable source ingest but
  before queue creation still deleted B (`1 failed, 1 passed`). The final design now
  captures A's OS identity at source ingest and includes it in a version-2 HMAC manifest;
  queue creation never rebinds whichever object currently occupies the path.
- The final gate caught two last defects with live checks. Claim CAS omitted the
  authenticated file identity/tag, and a normal POSIX rename changed `ctime`, causing a
  valid deletion to fence. A deterministic between-auth/CAS mutation regression and
  actual-module WSL/ext4 deletion/race tests now cover both fixes.
- Final code review also found that a pre-Round4 source row with nonempty unsigned
  attachments could be redacted without queueing its file. Startup migration and the
  batch transaction now stop before redaction, preserve the sole payload/path reference,
  and require explicit authenticated migration. Dedicated startup and late-tamper
  regressions prove both paths fail closed without losing the file reference.

### End-to-end attachment trust chain

- Only the exact top-level `attachments` container is trusted. Paths must already equal
  one lowercase ASCII, forward-slash canonical grammar. Duplicate separators, dot
  segments, backslashes, case variants, trailing dots, and Windows reserved names fail
  at ingress; persisted active/dead paths are rechecked before any claim exposure.
- Source HMAC manifests cover source kind/ID, key ID, canonical path, and the original
  file identity (or explicit `missing`/`rejected` sentinel). Raw payload edits cannot
  select a victim path, and source-manifest edits fail before filesystem work.
- Signed backlog pages carry the same path/identity occurrence and authenticate backlog
  ID, key ID, random generation, and exact canonical JSON. Authentication precedes
  split/promotion/update/deletion; every remainder receives a fresh ID/generation/tag.
  The K1-backlog/K2 regression proves promotion requires K1 history and emits K2 work.
- Active/dead identifiers authenticate domain/kind, key ID, random work ID, random
  generation, and path; a second HMAC covers immutable file identity. Fresh and additive
  schemas enforce unique active paths and work IDs.

### Lease, CAS, audit, and filesystem evidence

- Due claim, authorization, and completion compare the complete authenticated
  occurrence, file identity/tag, owner, random token, increasing claim generation, and
  exact live expiry. The worker derives fresh operation time from an injected monotonic
  clock; non-finite or backwards clocks fail closed.
- Completion records successful deleted/missing/rejected/retry/quarantine counts only
  after a full CAS changes exactly one row. Stale, fenced, and absent/no-op outcomes are
  separate. Once state is `deleting`, any non-deleted outcome remains fenced and cannot
  release the occurrence for same-path reuse.
- Windows deletes the verified opened handle after checking reparse/directory status,
  final managed-root location, volume/file index, size, creation version, and write
  version against the signed source occurrence.
- POSIX walks held directory descriptors with `O_NOFOLLOW`, authorizes the verified
  source object, then atomically renames the candidate into a unique slot under a
  mode-`0700` private directory. It compares the still-held original descriptor with the
  quarantined descriptor before unlink. A pre-rename replacement is preserved in the
  private quarantine and fences the row; after rename, the private name cannot be
  replaced by an untrusted directory writer.

### Operational concern

Post-authorization uncertainty deliberately favors preservation: a row remains
`deleting`, and a deterministic private quarantine slot may require explicit operator
repair. The system never automatically reclaims that fence or invents a legacy identity
from whichever object happens to occupy the path.
