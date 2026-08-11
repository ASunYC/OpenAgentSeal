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
