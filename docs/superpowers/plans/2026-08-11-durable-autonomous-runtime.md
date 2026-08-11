# Durable Autonomous Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a restart-safe messaging gateway, transactional delivery outbox, executable cron scheduler, and continuous Goal Runner on the existing SQLite control plane and AgentRunner.

**Architecture:** Add focused repositories and immutable domain records beside `ControlPlane`, then run bounded lease-based workers under one application supervisor. All ingress, execution, and delivery identities are persisted before side effects; the nine official channel adapters implement one conformance contract and never own retry policy.

**Tech Stack:** Python 3.10+, SQLite/WAL, asyncio, FastAPI, Pydantic, Vue 3/TypeScript, pytest, Vitest/Node model tests, Tauri desktop packaging.

## Global Constraints

- Single local backend process; resume from SQLite after application restart.
- Official APIs only: Telegram, Discord, Slack, WhatsApp Cloud, Feishu, DingTalk, LINE, QQ Bot, and WeCom.
- Standard five-field cron with IANA timezone; default `Asia/Shanghai`; latest-only catch-up; no overlapping run.
- Initial attempt plus at most five retries with capped exponential backoff and jitter.
- Remote delivery is never retried from an ambiguous outcome when the platform has neither idempotency nor reconciliation.
- Webhooks fail closed; verify untouched bytes, timestamp, nonce, and replay window before parsing.
- New runtime code requires unit, integration, and critical E2E coverage with at least 80% coverage.
- Preserve existing CLI, Web, desktop, mobile companion, AgentRunner, GoalController, and task behavior.

## File Map

- `open_agent/durable_runtime/models.py`: immutable inbox, outbox, claim, run, route, and delivery records.
- `open_agent/durable_runtime/repository.py`: SQLite schema and atomic compare-and-set transitions.
- `open_agent/durable_runtime/leases.py`: lease/fencing and backoff calculations.
- `open_agent/durable_runtime/supervisor.py`: worker lifecycle, wakeups, startup recovery, shutdown.
- `open_agent/gateway/contracts.py`: normalized channel DTOs and `ChannelAdapter` protocol.
- `open_agent/gateway/security.py`: authentication, replay and outbound URL/attachment policy.
- `open_agent/gateway/router.py`: account/conversation route and durable session resolution.
- `open_agent/gateway/adapters/*.py`: one official protocol adapter per channel.
- `open_agent/scheduler_runtime.py`: cron calculation, scan, claim, execute and retry orchestration.
- `open_agent/goal_runtime.py`: leased multi-iteration AgentRunner/Judge orchestration.
- `open_agent/app/runner/gateway_api.py`: gateway/admin/webhook endpoints.
- `open_agent/app/runner/autonomics_api.py`: scheduler, delivery and Goal operational endpoints.
- `open_agent/app/web/src/api/autonomics.ts`: typed frontend API boundary.
- `open_agent/app/web/src/components/settings/ChannelsSettings.vue`: account and route administration.
- `open_agent/app/web/src/components/settings/AutonomicsSettings.vue`: runs, goals and delivery failures.

---

### Task 1: Immutable runtime contracts and lease calculations

**Files:**
- Create: `open_agent/durable_runtime/__init__.py`
- Create: `open_agent/durable_runtime/models.py`
- Create: `open_agent/durable_runtime/leases.py`
- Test: `tests/test_durable_runtime_models.py`

**Interfaces:**
- Produces: `ClaimToken(owner_id: str, generation: int, expires_at: datetime)`, `InboxEvent`, `OutboxObligation`, `SchedulerRun`, `GoalIteration`, `next_backoff(attempt: int, base_seconds: float, cap_seconds: float, jitter: float) -> float`, and `lease_is_valid(token, now) -> bool`.

- [ ] **Step 1: Write failing tests** for frozen dataclasses, timezone-aware timestamps, invalid states, deterministic zero-jitter backoff, cap enforcement, and lease expiry.
- [ ] **Step 2: Run** `pytest tests/test_durable_runtime_models.py -v` and verify import failures.
- [ ] **Step 3: Implement minimal frozen records**, state `Literal` aliases, validation constructors, and pure lease/backoff functions; use injected randomness rather than global random state.
- [ ] **Step 4: Run** `pytest tests/test_durable_runtime_models.py -v --cov=open_agent.durable_runtime --cov-report=term-missing` and reach 80% for these modules.
- [ ] **Step 5: Commit** `git commit -m "feat: add durable runtime contracts"` with only Task 1 files.

### Task 2: Atomic SQLite durable-runtime repository

**Files:**
- Create: `open_agent/durable_runtime/repository.py`
- Modify: `open_agent/control_plane.py`
- Test: `tests/test_durable_runtime_repository.py`

**Interfaces:**
- Consumes: Task 1 records and `ClaimToken`.
- Produces: `DurableRuntimeRepository.enqueue_inbox`, `dispatch_inbox_with_turn`, `enqueue_outbox`, `claim_due_outbox`, `renew_claim`, `ack_outbox`, `retry_outbox`, `mark_delivery_unknown`, `create_due_scheduler_run`, `complete_goal_iteration_and_continue`, and read/list methods.

- [ ] **Step 1: Write failing temporary-SQLite tests** proving unique inbox keys, scoped outbox idempotency, atomic inbox-to-turn dispatch, stale-token rejection, expired-lease reclaim, scheduler occurrence/create-and-advance atomicity, and goal-iteration handoff.
- [ ] **Step 2: Run** `pytest tests/test_durable_runtime_repository.py -v` and verify missing schema/API failures.
- [ ] **Step 3: Add additive `CREATE TABLE IF NOT EXISTS` migrations** for channel accounts/routes/checkpoints, inbox, outbox, scheduler runs, goal iterations and audit events; extend goals and scheduler jobs through idempotent column migration helpers.
- [ ] **Step 4: Implement each transition as one `with conn:` transaction** with database unique constraints and compare-and-set predicates containing owner, generation and lease.
- [ ] **Step 5: Run** `pytest tests/test_durable_runtime_repository.py tests/test_goal_mode.py tests/test_autonomics.py -v`.
- [ ] **Step 6: Commit** `git commit -m "feat: persist durable runtime state"`.

### Task 3: Reliable internal delivery and crash recovery

**Files:**
- Create: `open_agent/durable_runtime/delivery.py`
- Modify: `open_agent/agent_control.py`
- Test: `tests/test_reliable_delivery.py`
- Test: `tests/test_agent_profiles.py`

**Interfaces:**
- Produces: `DeliveryDestination` protocol, `LocalSessionDestination.deliver(obligation, claim)`, and `DeliveryWorker.run_once(now) -> int`.

- [ ] **Step 1: Write failing tests** for parent-session result insertion, duplicate producer calls, crash after insert before ack, retryable failure, `delivery_unknown`, dead-letter, manual resend audit, and lease loss before a side effect.
- [ ] **Step 2: Run** `pytest tests/test_reliable_delivery.py -v` and verify failures.
- [ ] **Step 3: Implement local delivery** using outbox ID as the stable message ID and replace direct best-effort task backfill with transactional outbox production.
- [ ] **Step 4: Implement delivery worker** with claim renewal, fenced pre-send checks, deadlines, classified errors, retry schedule, unknown outcome and audit records.
- [ ] **Step 5: Run** `pytest tests/test_reliable_delivery.py tests/test_agent_profiles.py -v --cov=open_agent.durable_runtime.delivery --cov-report=term-missing`.
- [ ] **Step 6: Commit** `git commit -m "feat: add crash-safe result delivery"`.

### Task 4: Gateway contracts, routing and ingress security

**Files:**
- Create: `open_agent/gateway/__init__.py`
- Create: `open_agent/gateway/contracts.py`
- Create: `open_agent/gateway/router.py`
- Create: `open_agent/gateway/security.py`
- Test: `tests/test_gateway_core.py`
- Test: `tests/test_gateway_security.py`

**Interfaces:**
- Produces: `ChannelAdapter` protocol; `NormalizedInboundEvent`; `OutboundMessage`; `ChannelCapabilities`; `GatewayRouter.resolve(event) -> ResolvedRoute`; `WebhookAuthenticator.verify(raw_body, headers, now)`; `OutboundUrlPolicy.validate(url)`.

- [ ] **Step 1: Write failing contract tests** for immutable normalized IDs, DM/group mention/reply triggers, account default profile, route override, and stable local session mapping.
- [ ] **Step 2: Write failing security tests** for missing/invalid/stale signatures; nonce replay; IP/adapter/account/global request and concurrency limits before parsing; queue/database/disk quotas; per-conversation Agent limits; HTTPS/host allowlists; redirect revalidation; private/loopback/link-local/metadata IP rejection; DNS rebinding; attachment count, aggregate/decompressed size and stream-time limits; magic-byte mismatch; archive bombs; path traversal and symlinks; isolated random non-executable paths; expiry cleanup; and inability to bypass tool approval.
- [ ] **Step 3: Run** `pytest tests/test_gateway_core.py tests/test_gateway_security.py -v`.
- [ ] **Step 4: Implement shared contracts and router**, keeping platform payload parsing outside routing.
- [ ] **Step 5: Implement fail-closed security primitives** with dependency-injected DNS/time/secret lookup so tests never use the network.
- [ ] **Step 6: Run** the two test files with coverage and commit `feat: add secure messaging gateway core`.

### Task 5: Credential store and data retention

**Files:**
- Create: `open_agent/gateway/credentials.py`
- Create: `open_agent/durable_runtime/retention.py`
- Test: `tests/test_gateway_credentials.py`
- Test: `tests/test_runtime_retention.py`

**Interfaces:**
- Produces: `CredentialStore.put(account_id, secret) -> secret_ref`, `resolve(secret_ref)`, `rotate(secret_ref, replacement)`, `revoke(secret_ref)`, `delete(secret_ref)` and `RetentionWorker.run_once(now) -> RetentionSummary`.

- [ ] **Step 1: Write failing credential tests** proving SQLite stores only opaque references, Windows Credential Manager or an equivalently separated encrypted test backend owns secret bytes, encryption keys never share the SQLite store, account scopes are isolated, diagnostics are redacted, and rotate/revoke/delete immediately affect resolution.
- [ ] **Step 2: Write failing retention tests** for configured expiry and deletion of inbox payloads, PII, attachments, delivery details and audit data while retaining non-sensitive state needed for idempotency and compliance.
- [ ] **Step 3: Run** `pytest tests/test_gateway_credentials.py tests/test_runtime_retention.py -v` and verify missing APIs.
- [ ] **Step 4: Implement the credential abstraction and Windows backend** with restrictive permissions, protected-backup semantics and a memory backend for tests; migrate any legacy inline secret by storing it once then replacing it with an opaque reference.
- [ ] **Step 5: Implement retention as bounded, audited batches** and ensure symlink-safe attachment deletion never escapes the managed attachment root.
- [ ] **Step 6: Run** both test files with coverage and commit `feat: secure channel credentials and retention`.

### Task 6: Webhook/polling ingress and AgentRunner dispatch

**Files:**
- Create: `open_agent/gateway/ingress.py`
- Modify: `open_agent/app/runner/runner.py`
- Test: `tests/test_gateway_ingress.py`
- Test: `tests/test_runtime_api.py`

**Interfaces:**
- Produces: `IngressService.accept_webhook`, `accept_polled_event`, `commit_checkpoint`, and `IngressWorker.run_once`; consumes `GatewayRouter` and existing `AgentRunner.run_stream()`.

- [ ] **Step 1: Write failing tests** for authenticate-before-parse, enqueue-before-webhook-ack, duplicate event suppression, cursor commit, gateway resume checkpoint, atomic source-event turn mapping, and restart after dispatch.
- [ ] **Step 2: Run** `pytest tests/test_gateway_ingress.py -v`.
- [ ] **Step 3: Implement ingress service and worker**; add `source_event_key` metadata to existing runtime turns without creating a second Agent loop.
- [ ] **Step 4: Run** `pytest tests/test_gateway_ingress.py tests/test_runtime_api.py tests/test_session_recovery.py -v`.
- [ ] **Step 5: Commit** `git commit -m "feat: dispatch durable channel ingress"`.

### Task 7: Nine official channel adapters

**Files:**
- Create: `open_agent/gateway/adapters/base_http.py`
- Create: `open_agent/gateway/adapters/telegram.py`
- Create: `open_agent/gateway/adapters/discord.py`
- Create: `open_agent/gateway/adapters/slack.py`
- Create: `open_agent/gateway/adapters/whatsapp.py`
- Create: `open_agent/gateway/adapters/feishu.py`
- Create: `open_agent/gateway/adapters/dingtalk.py`
- Create: `open_agent/gateway/adapters/line.py`
- Create: `open_agent/gateway/adapters/qq.py`
- Create: `open_agent/gateway/adapters/wecom.py`
- Create: `open_agent/gateway/destinations.py`
- Test: `tests/gateway/test_adapter_conformance.py`
- Test: `tests/gateway/fixtures/*.json`

**Interfaces:**
- Each adapter implements Task 4 `ChannelAdapter` and declares truthful text, attachment, reply, idempotency, reconciliation, polling/webhook and gateway-resume capabilities. `ChannelDestinationRegistry.resolve(account_id)` provides the external destination consumed by the shared delivery worker.

- [ ] **Step 1: Add sanitized fixtures and a parameterized failing conformance suite** covering authentication/challenge, normalization, mention/reply detection, send request shape, rate-limit classification, acknowledgement deadline and redaction for all nine adapters; add an integration case where a completed channel Agent turn creates one outbox obligation, resolves the originating adapter destination, sends once and records acknowledgement.
- [ ] **Step 2: Run** `pytest tests/gateway/test_adapter_conformance.py -v` and verify all adapters are missing.
- [ ] **Step 3: Implement shared bounded HTTP transport**, official-host allowlists and error taxonomy.
- [ ] **Step 4: Implement adapters one at a time**, running the adapter's conformance case after each implementation; register external destinations and make Agent completion produce an origin-scoped outbox obligation; never claim idempotency when the official API lacks it.
- [ ] **Step 5: Run** `pytest tests/gateway -v --cov=open_agent.gateway.adapters --cov-report=term-missing` and the full gateway tests.
- [ ] **Step 6: Commit** `git commit -m "feat: add official messaging channel adapters"`.

### Task 8: Executable cron scheduler

**Files:**
- Create: `open_agent/scheduler_runtime.py`
- Modify: `open_agent/autonomics.py`
- Test: `tests/test_scheduler_runtime.py`
- Test: `tests/test_autonomics.py`

**Interfaces:**
- Produces: `CronSchedule.parse(expression, timezone)`, `next_occurrence(after)`, `SchedulerWorker.scan_once(now)`, and `execute_run(run_id)`.

- [ ] **Step 1: Write failing tests** for five-field validation, DST transitions, `Asia/Shanghai` default, due creation, latest-only catch-up, overlap skip, atomic cursor advancement, manual IDs, pause/resume/delete, initial-plus-five retries and origin outbox delivery.
- [ ] **Step 2: Run** `pytest tests/test_scheduler_runtime.py -v`.
- [ ] **Step 3: Implement cron parsing/calculation** with `croniter>=6.0,<7`, add that bounded dependency to `pyproject.toml`, and normalize all calculations through timezone-aware datetimes.
- [ ] **Step 4: Implement scanner/executor** through existing AgentRunner or Goal runtime interfaces and durable repository transitions.
- [ ] **Step 5: Run** `pytest tests/test_scheduler_runtime.py tests/test_autonomics.py tests/test_runtime_api.py -v`.
- [ ] **Step 6: Commit** `git commit -m "feat: execute durable scheduled jobs"`.

### Task 9: Continuous Goal Runner

**Files:**
- Create: `open_agent/goal_runtime.py`
- Modify: `open_agent/goal_mode.py`
- Test: `tests/test_goal_runtime.py`
- Test: `tests/test_goal_mode.py`

**Interfaces:**
- Produces: `GoalBudget`, `GoalAcceptance`, `GoalRunner.run_iteration(goal_id)`, `GoalRunner.recover(now)`, and structured `GoalJudge` protocol returning existing `JudgeResult`.

- [ ] **Step 1: Write failing tests** for persisted acceptance criteria/Judge version, confidence threshold, next action, atomic iteration handoff, token/cost/active-time/iteration budgets, pause time exclusion, lease expiry, guidance sequence, transient retries, repeated-failure block, cancel race and one terminal outbox result.
- [ ] **Step 2: Run** `pytest tests/test_goal_runtime.py -v`.
- [ ] **Step 3: Extend GoalController immutably** to validate and expose durable goal configuration without changing existing call defaults.
- [ ] **Step 4: Implement one-turn-at-a-time execution** through AgentRunner and the structured Judge, persisting every boundary before continuing.
- [ ] **Step 5: Run** `pytest tests/test_goal_runtime.py tests/test_goal_mode.py tests/test_agent.py tests/test_session_recovery.py -v`.
- [ ] **Step 6: Commit** `git commit -m "feat: run goals continuously to acceptance"`.

### Task 10: Supervisor lifecycle and application wiring

**Files:**
- Create: `open_agent/durable_runtime/supervisor.py`
- Modify: `open_agent/app/runner/api.py`
- Modify: `open_agent/app/_app.py`
- Test: `tests/test_durable_runtime_supervisor.py`

**Interfaces:**
- Produces: `DurableRuntimeSupervisor.start()`, `wake(kind)`, `stop(drain_timeout)`, and health snapshot.

- [ ] **Step 1: Write failing tests** for start-after-services, one worker per kind, missed wakeup recovery by polling, bounded concurrency, heartbeat cancellation, expired-lease recovery, graceful drain and idempotent stop.
- [ ] **Step 2: Run** `pytest tests/test_durable_runtime_supervisor.py -v`.
- [ ] **Step 3: Implement supervisor and wire it into FastAPI/app lifecycle**, ensuring imports do not start background work during tests.
- [ ] **Step 4: Run** supervisor, runtime API and session recovery tests.
- [ ] **Step 5: Commit** `git commit -m "feat: supervise autonomous runtime workers"`.

### Task 11: Authenticated operational APIs

**Files:**
- Create: `open_agent/app/runner/gateway_api.py`
- Create: `open_agent/app/runner/autonomics_api.py`
- Modify: `open_agent/app/runner/api.py`
- Modify: `open_agent/app/runner/models.py`
- Test: `tests/test_autonomous_runtime_api.py`

**Interfaces:**
- Produces typed CRUD/diagnostic/webhook, inbox/outbox/dead-letter, scheduler/run, Goal/control/guidance and audit endpoints.

- [ ] **Step 1: Write failing API tests** for authentication, RBAC, CSRF, resource ownership, webhook bypass only through adapter authentication, re-authentication for secret/route changes and manual resend, secret masking with no credential reveal, default redaction of message bodies/attachment URLs/user IDs/temporary tokens/platform responses, privileged reveal of non-credential content with audit, retention configuration/deletion, pagination and invalid state errors.
- [ ] **Step 2: Run** `pytest tests/test_autonomous_runtime_api.py -v`.
- [ ] **Step 3: Implement Pydantic request/response models and routers** using repository/services only; never return raw rows or credentials.
- [ ] **Step 4: Run** API, gateway and runtime integration tests.
- [ ] **Step 5: Commit** `git commit -m "feat: expose autonomous runtime operations"`.

### Task 12: Web administration UI

**Files:**
- Create: `open_agent/app/web/src/api/autonomics.ts`
- Create: `open_agent/app/web/src/models/autonomics.ts`
- Create: `open_agent/app/web/src/components/settings/ChannelsSettings.vue`
- Create: `open_agent/app/web/src/components/settings/AutonomicsSettings.vue`
- Modify: `open_agent/app/web/src/components/SettingsModal.vue`
- Test: `open_agent/app/web/scripts/test-autonomics-model.mjs`

**Interfaces:**
- Consumes Task 11 APIs; produces typed projections for channel health/routes, delivery states, scheduler runs and Goal iterations.

- [ ] **Step 1: Write failing pure-model tests** for status projection, redacted secret fields, delivery-unknown warning, run attempts, budget progress and legal actions.
- [ ] **Step 2: Run** `npm run test:autonomics` from `open_agent/app/web` after adding the package script and verify failure.
- [ ] **Step 3: Implement typed API/models and settings components** with redacted values, explicit destructive confirmations and accessible loading/error/empty states.
- [ ] **Step 4: Run** `npm run test:autonomics && npm run build:check`.
- [ ] **Step 5: Commit** `git commit -m "feat: administer channels and autonomous runs"`.

### Task 13: Cross-system E2E, security and packaging verification

**Files:**
- Create: `tests/e2e/test_autonomous_runtime.py`
- Create: `docs/autonomous-runtime-operations.md`
- Modify: `README.md`

**Interfaces:**
- Verifies the complete contracts from Tasks 1 through 12; adds no alternate runtime path.

- [ ] **Step 1: Add failing E2E scenarios** for one inbound event/one reply, restart between send/ack, cron origin delivery, multi-turn Goal restart/completion, invalid signature, replay, exhausted budget, ambiguous delivery and cancellation.
- [ ] **Step 2: Run** `pytest tests/e2e/test_autonomous_runtime.py -v` and verify failures expose integration gaps.
- [ ] **Step 3: Fix only integration defects in owning modules**, preserving centralized state transitions and shared decoders.
- [ ] **Step 4: Document configuration, official webhook setup, credential storage, recovery, dead-letter/manual reconciliation, backup and rollback procedures.**
- [ ] **Step 5: Run** `pytest -v --cov=open_agent --cov-report=term-missing`, `npm run test:autonomics && npm run build:check` in `open_agent/app/web`, and `node --test scripts/tests/package-release.test.mjs`.
- [ ] **Step 6: Run security review and language-specific code review**, resolve all CRITICAL/HIGH findings, then rerun focused and full verification.
- [ ] **Step 7: Commit** `git commit -m "test: verify autonomous runtime end to end"`.

## Final Verification

- [ ] `pytest -v --cov=open_agent --cov-report=term-missing` passes and new modules meet 80% coverage.
- [ ] `npm run test:autonomics && npm run build:check` passes in `open_agent/app/web`.
- [ ] Every adapter passes the shared conformance suite with sanitized fixtures.
- [ ] Restart tests prove no committed inbox, outbox, scheduler run, or Goal iteration is lost.
- [ ] Duplicate ingress and producer calls create no duplicate Agent turn or local message.
- [ ] Git diff contains no credentials, fixture PII, unrelated user changes, or untracked build artifacts.
