# Task 6 Report: Webhook/polling ingress and AgentRunner dispatch

## Outcome

Implemented authenticated durable ingress, polling/gateway checkpoints, and a
lease-fenced inbox worker that reuses `AgentRunner.run_stream()` and the existing
Agent loop. Webhook acceptance performs raw-byte authentication before parsing,
quota admission before route/session persistence, durable inbox enqueue before
returning an acknowledgement-safe receipt, and never executes the Agent inline.

## TDD evidence

- RED checkpoint: `3429687 test: reproduce durable gateway ingress dispatch`
  - Command: `.venv\Scripts\python.exe -m pytest tests/test_gateway_ingress.py -v`
  - Expected failure: collection failed because `open_agent.gateway.ingress` did
    not exist. This was a compile-time RED caused by the missing Task 6 feature.
- GREEN checkpoint: `22a2832 feat: dispatch durable channel ingress`
  - Task 6 command:
    `.venv\Scripts\python.exe -m pytest tests/test_gateway_ingress.py tests/test_runtime_api.py tests/test_session_recovery.py -q`
  - Result: `20 passed`.
  - Compatibility command covered Tasks 1-5 durable models/repository,
    capabilities, delivery, gateway core/security/credentials, retention, and
    session recovery.
  - Result: `307 passed, 2 skipped`.
  - Coverage command:
    `.venv\Scripts\python.exe -m pytest tests/test_gateway_ingress.py --cov=open_agent.gateway.ingress --cov-report=term-missing -q`
  - Result: `12 passed`; `open_agent.gateway.ingress` line coverage `87%`.

## Required behavioral evidence

- Authentication and acknowledgement deadline:
  `test_webhook_authenticates_raw_bytes_then_admits_quota_then_enqueues_before_ack`
  proves ordering `auth -> parse -> quota -> enqueue -> ack`; invalid signatures
  never invoke the parser, enqueue failures never return a receipt, and Agent
  execution is owned exclusively by the asynchronous worker.
- Authenticated identity binding:
  `test_authenticated_account_cannot_be_rebound_by_normalized_payload` proves an
  adapter cannot replace the authenticated account through parsed content.
- Duplicate suppression:
  `test_duplicate_platform_event_is_one_durable_inbox_item` proves stable
  `(account_id, event_key)` identity returns one inbox record. The runtime-turn
  partial unique index plus transactional dispatch prevents a second turn.
- Cursor/checkpoint durability:
  `test_polling_cursor_is_committed_only_after_event_is_durable_and_survives_restart`
  proves an event is durable before cursor advancement and the cursor survives a
  new `ControlPlane` instance. `test_checkpoint_cannot_advance_before_referenced_event_is_durable`
  proves fail-closed ordering.
- Gateway resume checkpoint:
  `test_gateway_resume_checkpoint_is_persistent_and_sequence_cannot_regress`
  proves durable session/sequence/replay data and same-session sequence monotonicity.
- Atomic turn mapping:
  `test_worker_dispatches_one_event_to_one_atomic_runtime_turn` proves the inbox
  moves to dispatched and creates a single turn with canonical
  `source_event_key` in one repository transaction. Existing Task 2 rollback tests
  remain green.
- Crash/restart recovery:
  `test_restart_recovers_expired_dispatch_claim_and_reuses_existing_turn` proves a
  crash after dispatch is recovered through an expired lease without creating a
  new turn. `test_restart_after_completed_agent_turn_only_finishes_inbox` proves a
  crash after Agent completion does not run the Agent twice.
- Lease/fencing:
  `test_stale_dispatch_owner_cannot_complete_after_recovery` proves the old owner
  cannot complete after reclaim. Active Agent streams renew their inbox lease no
  less often than one third of the lease interval (capped at 30 seconds); renewal
  failure cancels the consumer before further processing.
- Existing loop reuse:
  `test_run_stream_reuses_process_message_instead_of_creating_an_agent_loop` proves
  `run_stream()` delegates to `process_message()` with the pre-created runtime turn.

## Security and code review

- Raw webhook bytes and authentication headers are not logged or persisted.
- Quota is reserved before route/session writes and released idempotently after
  enqueue or failure.
- Adapter kind and authenticated account must match normalized identifiers.
- Checkpoint inputs are validated; gateway sequence regression and pre-durability
  advancement fail closed.
- All execution/completion transitions require the full owner/generation/expiry
  fencing token, and replay resolves the existing canonical source-event turn.
- `python -m compileall` and `git diff --check` passed. Ruff is not installed in
  the project venv and is not configured as a project validation command.

## Concerns

- No Task 6 functional blocker remains.
- The Windows worktree venv initially lacked the `tzdata` wheel required by one
  pre-existing DST repository test. Installing `tzdata==2026.3` in that venv made
  the complete Tasks 1-5 compatibility selection green; no dependency file was
  changed because scheduler dependency ownership belongs to its planned task.

## Formal review fix round 1

- RED checkpoint: `c8e13be test: reproduce ingress review safety gaps`.
  Further review REDs reproduced omitted gateway position, cross-attempt tool
  replay, uncertain post-claim effects, terminal turn overwrite, and nonce-aware
  retention before their fixes.
- Checkpoints now require an account/transport lease generation and exact expiry
  fence, an exact expected-previous shape, and an event payload whose transport
  position matches the proposed cursor or gateway session/sequence. Gateway
  sessions cannot roll back, and one account cannot own webhook and polling/
  gateway ingress concurrently.
- Webhook nonce receipts are inserted in the same `BEGIN IMMEDIATE` transaction
  as the inbox event and bind `(account, nonce)` to the authenticated SHA-256
  request digest and receipt. Matching retries resume the receipt; mismatches
  fail closed. Live receipts exclude inbox rows from retention; expired receipts
  are removed before redaction, avoiding mutable inbox-PK foreign keys.
- Body/header/context/normalized identifiers/text/metadata depth and size plus
  attachment descriptor/count limits run at ingress boundaries. Attachments pass
  `AttachmentGuard`; URL sources require `OutboundUrlPolicy`; only managed path,
  size, and expiry references enter the inbox and Agent request.
- Inbox success requires both an explicit `complete` stream event and the
  authoritative completed turn status. Cancel/error terminal turns are preserved
  and a retry receives a separately identified linked turn. Silent streams remain
  retryable under the inbox fence. Terminal runtime event insertion and turn/
  thread status update now share one idempotent SQLite transaction, closing the
  crash gap between terminal event and status.
- Existing `tool_calls` rows now persist an effect intent before execution with a
  stable `(source_event_key, execution ordinal)` identity across provider call-ID
  changes and retry turns. Name/argument mismatches fail closed, completed results
  replay, stale idempotent claims fence the old worker, and ambiguous
  non-idempotent outcomes become `delivery_unknown/manual_required`. Unresolved
  effects block any new Agent attempt.

### Fix-round verification

- Focused GREEN:
  `.venv\Scripts\python.exe -m pytest tests/test_gateway_ingress.py tests/test_tool_effect_recovery.py tests/test_runtime_api.py tests/test_session_recovery.py -q`
  -> `44 passed`.
- Tasks 1-5 compatibility GREEN:
  durable models/repository, runtime capabilities, reliable delivery, gateway
  core/security/credentials, runtime retention, and session recovery
  -> `307 passed, 2 skipped`.
- Coverage:
  `.venv\Scripts\python.exe -m pytest tests/test_gateway_ingress.py tests/test_tool_effect_recovery.py --cov=open_agent.gateway.ingress --cov=open_agent.durable_runtime.repository --cov=open_agent.control_plane --cov-report=term-missing -q`
  -> `31 passed`; Task 6 ingress line coverage `85%`.
- `python -m compileall -q open_agent` and `git diff --check` passed.
- Two independent code-review passes drove six HIGH fixes. Final approval is
  recorded after the last cross-turn effect and atomic-terminal corrections.

### Remaining concerns

- The optional legacy `tests/test_agent.py` integration pair requires an
  untracked local `open_agent/config/config.yaml`; in this worktree those two
  tests fail at fixture setup. The remaining selected Agent/tool tests passed
  `19/19`, and all required Task 1-6 suites above are green.

## Formal review fix round 2

- RED checkpoint: `9c9244b test: reproduce round2 ingress recovery gaps`.
  Seven focused failures reproduced orphaned tool-effect replay, transport
  admission outside the ownership transaction, and attachment leakage across
  rejection and crash boundaries.
- A worker now classifies effects before every attempt: live `executing` claims
  block; expired non-idempotent claims become `delivery_unknown/manual_required`;
  and expired idempotent effects may be reclaimed only through the normal fenced
  claim operation. Claim/fence conflicts abort the Agent turn. Inbox completion
  checks and its fenced success transition share one transaction and reject any
  effect whose state is not `completed`.
- Polling and gateway admission require the account/transport claim and revalidate
  its owner, generation, expiry, and transport mode inside the same
  `BEGIN IMMEDIATE` transaction that inserts the inbox row. A webhook checkpoint
  remains mutually exclusive with polling/gateway ownership, and stale claims
  fail before durable admission.
- Attachment admission now performs size, quota, duplicate, and route preflight
  before storage. A durable staging manifest is adopted in the successful inbox
  transaction or recovered on retry. Every stored object carries a per-attempt
  ownership token; rollback deletes only an object with that exact token, so a
  generated-path collision cannot remove a pre-existing/adopted object.
- Staging recovery is keyed by the deterministic event ID and runs before both
  duplicate lookup and normal admission even if the retry omits attachments;
  this closes the crash/retry path that could otherwise strand a manifest and
  owned quarantine object forever.
- URL attachment descriptors reserve the policy maximum before fetch. The guard
  then exposes the fetched byte count before manifest/storage, validates it
  against the declaration, and acquires the actual-size quota lease before the
  storage commit. Only managed references are admitted to the inbox.

### Fix-round 2 verification

- Focused GREEN:
  `.venv\Scripts\python.exe -m pytest tests/test_gateway_ingress.py tests/test_tool_effect_recovery.py tests/test_gateway_security.py -q`
  -> `118 passed`.
- Required Task 6/runtime compatibility GREEN:
  `.venv\Scripts\python.exe -m pytest tests/test_gateway_ingress.py tests/test_tool_effect_recovery.py tests/test_runtime_api.py tests/test_session_recovery.py -q`
  -> `54 passed`.
- Tasks 1-5 compatibility GREEN: durable models/repository, runtime capabilities,
  reliable delivery, gateway core/security/credentials, runtime retention, and
  session recovery -> `308 passed, 2 skipped`.
- Coverage:
  `.venv\Scripts\python.exe -m pytest tests/test_gateway_ingress.py tests/test_tool_effect_recovery.py --cov=open_agent.gateway.ingress --cov-report=term-missing -q`
  -> `46 passed`; Task 6 ingress line coverage `85%`.
- `python -m compileall -q open_agent` and `git diff --check` passed. Final code
  review approved the ownership-token cleanup and pre-storage actual-byte quota
  changes; the security review recorded no Critical/High finding.

### Fix-round 2 concerns

- No Task 6 functional or security blocker remains.
