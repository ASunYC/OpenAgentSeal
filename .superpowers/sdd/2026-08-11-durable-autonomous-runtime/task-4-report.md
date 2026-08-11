# Task 4: Gateway contracts, routing and ingress security

## Status

DONE

## Modified files

- `open_agent/gateway/__init__.py`
- `open_agent/gateway/contracts.py`
- `open_agent/gateway/router.py`
- `open_agent/gateway/security.py`
- `open_agent/durable_runtime/repository.py`
- `tests/test_gateway_core.py`
- `tests/test_gateway_security.py`

The repository extension is intentionally limited to typed channel-account upsert/read,
channel-route upsert/resolution, and atomic route/session/thread provisioning. Router and
security code contain no SQL.

## RED verification

Initial contract/security command:

```powershell
pytest tests/test_gateway_core.py tests/test_gateway_security.py -q
```

Expected result: collection failed with two `ModuleNotFoundError` errors because
`open_agent.gateway` did not exist.

The review-hardening RED cycles then reproduced, before their fixes:

- 15 failures for non-boolean triggers, ignored-event state creation, shared-route
  attribution, nonce consumption on rate rejection, racy lease release, unpruned limiter
  keys, caller-trusted archive metadata, unsafe storage names, and invalid policies.
- 2 failures proving route validation was outside an explicit SQLite transaction and
  invalid-signature traffic bypassed pre-auth admission limits.
- 8 failures proving matching/predictable persistence collisions, CGNAT SSRF, missing
  transport deadlines, and non-boolean approval inputs.
- 1 failure proving a matching-field predictable-ID precreation was accepted.
- 2 failures proving forged ZIP expanded sizes were trusted and multi-file storage used
  non-atomic sequential writes.
- 1 failure proving each archive received a fresh decompression budget instead of the
  request-wide remaining budget (38 bytes expanded before rejection versus a 25-byte
  maximum including the required sentinel byte).

Every production change above was applied only after its regression failed for the
expected reason, then the focused regression and full gateway suite were rerun GREEN.

## GREEN verification

Focused coverage command:

```powershell
pytest tests/test_gateway_core.py tests/test_gateway_security.py -q --cov=open_agent.gateway --cov-report=term-missing
```

Final result: 71 passed; gateway package statement coverage is 88%, above the required
80%.

Task 1-3 compatibility command:

```powershell
pytest tests/test_durable_runtime_models.py tests/test_durable_runtime_repository.py tests/test_reliable_delivery.py tests/test_goal_mode.py tests/test_autonomics.py tests/test_agent_profiles.py -q
```

Final result: 126 passed with one existing Starlette `python_multipart` deprecation
warning.

Additional verification:

```powershell
python -m compileall -q open_agent/gateway open_agent/durable_runtime/repository.py
git diff --check
```

Both commands completed successfully.

## Routing and contract coverage

- Frozen normalized inbound IDs and recursively immutable metadata/attachments.
- Strict DM/group kind and exact-boolean mention/reply trigger inputs.
- Default DM, group mention, and group reply trigger behavior; ignored group events do
  not create routes, sessions, or threads.
- Account default profile, conversation override, sender override, and adapter/account
  binding.
- Stable durable local session/thread mapping through Task 2 tables.
- Explicit `BEGIN IMMEDIATE` covers account authorization, route lookup, dispatch
  decision, and provisioning in one transaction.
- Shared conversation routes use an account/conversation principal rather than the first
  sender.
- Newly allocated predictable IDs require exclusive inserts; any precreation conflict,
  including matching forged ownership fields, rolls back.

## Security-boundary coverage

| Boundary | Fail-closed evidence |
|---|---|
| Webhook authenticity | Missing, invalid, unknown-secret, stale, future, and replayed requests reject; HMAC covers timestamp, nonce, and raw bytes; secret and atomic nonce stores are injected. |
| Pre-parse admission | Global/IP/adapter limits run before secret lookup/HMAC; authenticated account limits run before nonce claim and parsing; request and concurrency limits, idempotent cross-thread release, expiry pruning, and retryable rejected nonces are covered. |
| Resource quotas | Queue, database, free-disk, attachment, and per-conversation Agent thresholds reject; authoritative quota reservation is delegated atomically through an injected ledger and idempotent lease. |
| Outbound URL/SSRF | HTTPS, credential, port, and exact-host allowlists; empty/failed DNS; every non-global IPv4/IPv6 result including private, loopback, link-local, metadata, and CGNAT; redirect revalidation; and peer-IP pinning against DNS rebinding are covered. |
| Attachments | Bounded upload count and bytes while streaming; transport-enforced injected deadline; aggregate actual ZIP decompression with entry-count/ratio/CRC/size checks; magic bytes; traversal, drive paths, control characters, symlinks, and encrypted archives; injected malware scanner; safe random non-executable quarantine names; exclusive atomic batch storage; expiry cleanup. |
| Tool approval | Ingress metadata is ignored for approval; malformed non-boolean policy inputs reject; only the trusted control-plane approval boolean authorizes a required tool. |

Tests are offline: DNS, wall/monotonic time, secret lookup, nonce replay, quota ledger,
attachment scanning, random naming, and storage are injected fakes. No platform payload
parser or FastAPI endpoint was added.

## Commit

`feat: add secure messaging gateway core` (this commit)

## Self-review

- Confirmed Router and security modules contain no `_get_conn`, SQL, FastAPI, platform
  payload parsing, socket, or network-client calls.
- Confirmed dynamic SQL is not introduced; all repository values use parameterized SQL.
- Confirmed failed account, trigger, profile, predictable-ID, and ownership transitions
  roll back the explicit route transaction.
- Confirmed archive content is actually decompressed within bounded output/deadline limits
  instead of trusting adapter-supplied metadata.
- General code review and final security review reported no remaining HIGH/CRITICAL
  findings. Python review's forged-ZIP, atomic-batch, and aggregate remaining-budget
  findings were each reproduced RED and fixed; the targeted final re-review approved the
  result with no remaining HIGH/CRITICAL findings.

## Concerns

Endpoint/platform tasks must supply production implementations that honor the injected
contracts: nonce claim and quota reservation must be atomic across workers; attachment
streams must enforce the passed absolute deadline; attachment `put_batch` must be
exclusive and all-or-nothing; outbound clients must connect to and verify the pinned peer
IP. Those integrations are intentionally outside this channel-neutral core task.

## Fix round 1/5: unambiguous identities and strict contracts/limits

Status: DONE.

### Findings addressed

- Replaced delimiter-based route/session/thread IDs and shared principals with UUIDv5 over
  canonical JSON arrays, so delimiter and control characters cannot alias distinct tuples.
  Added collision regressions for both durable IDs and shared conversation principals.
- Added an atomic compatibility migration for already-persisted shared routes using the
  legacy principal. Migration requires exact session/thread route ownership metadata and
  updates both principals inside the existing `BEGIN IMMEDIATE` transaction; forged or
  partially bound records still fail closed.
- Restricted contract metadata/attachments to recursively immutable JSON-like values:
  exact string keys, finite scalar values, immutable tuples/mapping proxies, and copied
  `bytearray` values. `None`, custom mutable objects, sets, non-string/string-subclass keys,
  and invalid attachment containers reject at construction.
- Enforced exact booleans for channel capability and trigger fields, and exact positive
  non-boolean integers for message limits.
- Enforced bounded exact positive non-boolean integers for request/concurrency limits and
  a bounded positive `timedelta` window; floats, booleans, NaN, infinity, and excessive
  values reject before limiter state can be created.

### RED evidence

- Identity/contract/limit regression selection: 23 failed, 2 passed before implementation.
- Exact-string-key regression: 1 failed, 7 passed before tightening key type validation.
- Legacy shared-principal compatibility regression: 1 failed before adding the atomic
  ownership-checked migration.
- Earlier Python-review HIGH findings were independently reproduced RED: forged ZIP
  declarations exceeded the actual decompression budget, and failure of a later attachment
  left earlier writes committed. They remain fixed by bounded actual decompression and the
  exclusive all-or-nothing `put_batch` contract, respectively.

### GREEN and compatibility evidence

- `pytest tests/test_gateway_core.py tests/test_gateway_security.py -q --cov=open_agent.gateway --cov-report=term-missing`: 102 passed; gateway coverage 90%.
- Tasks 1-3 compatibility union (`test_durable_runtime_models.py`,
  `test_durable_runtime_repository.py`, `test_reliable_delivery.py`, `test_goal_mode.py`,
  `test_autonomics.py`, `test_agent_profiles.py`): 126 passed, 1 third-party deprecation
  warning.
- `python -m compileall -q open_agent/gateway open_agent/durable_runtime/repository.py`:
  passed.
- `git diff --check`: passed.

### Targeted re-review

Code and Python reviewers re-reviewed the current worktree after the compatibility fix.
Both reported no remaining HIGH/CRITICAL findings; the Python reviewer confirmed the
forged-ZIP and multi-attachment rollback fixes are present in the reviewed version.

### Fix commit

`fix: harden gateway identity and contracts` (this fix commit)

### Remaining concerns

Production integration contracts remain as above. Repository file-size refactoring is
ledger-deferred by the formal review and intentionally not included in this fix round.
