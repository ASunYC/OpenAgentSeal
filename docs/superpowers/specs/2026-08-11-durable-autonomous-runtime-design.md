# Durable Autonomous Runtime Design

## Purpose

OpenAgentSeal will gain four integrated production capabilities:

1. A unified messaging gateway for Telegram, Discord, Slack, WhatsApp Cloud API, Feishu, DingTalk, LINE, QQ Bot, and WeCom.
2. Crash-safe, idempotent delivery for channel replies and internal result backfill.
3. An executable cron scheduler with durable runs, retry, and restart recovery.
4. A continuous Goal Runner that executes and judges work until acceptance or a configured budget boundary.

The first deployment target is a single local backend process. Work continues while that process is running and resumes from SQLite after application restart. Windows Service installation, multi-node coordination, and unofficial personal-account protocols are outside this design.

## Architectural Decision

Extend the existing SQLite-backed `ControlPlane` with a durable runtime. SQLite is the source of truth; in-memory tasks are only wake-up hints and must never be required for recovery.

```text
official channel adapters -> durable inbox -> route/session resolver
                                            -> Agent / Goal Runner
cron scheduler ----------------------------> Agent / Goal Runner
Agent, Goal and sub-agent results -> transactional outbox
transactional outbox -> delivery worker -> channel adapter or local parent session
```

All background work is claimed with expiring leases. Startup recovery makes expired claims eligible again. Every externally visible side effect has an idempotency key.

## Module Boundaries

### Durable runtime repository

The control-plane persistence layer owns atomic state transitions for inbox entries, outbox obligations, schedule runs, and goal runs. Runtime services do not issue ad-hoc SQL.

The repository exposes immutable domain records and compare-and-set transitions. Claims include an owner ID, lease expiry, and monotonically increasing attempt number. Completion and acknowledgement require the current claim token so a stale worker cannot overwrite newer work.

Claims are renewable. Workers heartbeat at no more than one third of the lease duration, use bounded operation deadlines shorter than the remaining lease, and verify the fencing token immediately before every local or remote side effect. Failure to renew cancels the owned Agent/tool operation where possible and forbids further side effects.

### Messaging gateway

`ChannelAdapter` defines channel-neutral operations:

- validate configuration and report capability flags;
- normalize incoming webhook or polling payloads;
- send text, supported attachments, and structured replies;
- derive stable event, account, conversation, sender, and reply identifiers;
- verify webhook authenticity and persist ingress transport checkpoints such as polling cursors and Discord Gateway sequence/session data.

Adapters contain protocol conversion only. Routing, retries, secrets masking, persistence, and Agent execution remain in shared services.

The initial adapter set is:

- Telegram Bot API
- Discord Bot/Gateway
- Slack App Events API
- WhatsApp Cloud API
- Feishu Open Platform
- DingTalk application/robot APIs
- LINE Messaging API
- QQ Open Platform Bot
- WeCom application/customer-service APIs

Unofficial personal WeChat/QQ hooks, simulated login, and reverse-engineered protocols are explicitly excluded.

Every webhook adapter must use the official platform authentication mechanism and fail closed when credentials are absent, the algorithm is unknown, timestamps are stale, or verification fails. Signatures are verified against untouched request bytes before parsing. Timestamp and nonce replay data is retained for the platform replay window. Webhook handlers authenticate, durably enqueue, and acknowledge within the platform deadline. Polling cursors and stateful gateway resume checkpoints are committed durably; webhook and polling ownership are mutually exclusive per account.

### Route and session resolver

Each configured channel account has a default Agent Profile. A route override may select a different profile for a specific contact or group. Stable channel conversation identities map to durable local chat/session/thread identities.

Direct messages trigger normally. Group messages trigger only when the bot is mentioned or the message replies to the bot, unless an administrator changes that route policy. Duplicate inbound platform events resolve to the same inbox record and never create a second Agent turn.

Each dispatched turn has a unique `source_event_key` referencing its inbox event. Creating the turn/dispatch record and moving the inbox item to dispatched state occur in one SQLite transaction. Recovery checks this mapping before execution.

### Reliable delivery worker

Every result becomes an outbox obligation before it is considered delivered. Producers include normal channel replies, sub-agent parent-session backfill, scheduler results, Goal progress, Goal terminal results, and budget/block notifications.

An obligation has a stable idempotency key, destination, normalized payload, status, attempt count, next-attempt time, lease, last error, acknowledgement metadata, and timestamps. The delivery worker claims due obligations, invokes the destination adapter, records the platform message ID, and acknowledges atomically.

Failures use capped exponential backoff with jitter. Permanent protocol errors move to a dead-letter state. Operators can inspect and retry dead letters. If a process stops after a remote API accepted a message but before local acknowledgement, the same idempotency key is reused; adapters use platform idempotency facilities when available and otherwise reconcile using the stored client reference where the platform permits it. If neither exists, an ambiguous timeout enters `delivery_unknown` for audited manual reconciliation and is never automatically resent. Manual resend requires an explicit duplicate-delivery acknowledgement. At-least-once transport is guaranteed only where safe retry exists; effectively-once visible delivery cannot be promised for platforms without idempotency or reconciliation.

Outbox idempotency keys include producer kind and logical producer ID, account, destination conversation, message purpose, and payload schema version. A database unique constraint and atomic insert-on-conflict enforce this contract.

Internal parent-session delivery uses the same obligation model and a unique message key, providing effectively-once insertion into local history.

### Executable scheduler

Schedules use validated five-field cron expressions and an IANA timezone, defaulting to `Asia/Shanghai`. A scheduler scanner computes due work from persisted `next_run_at`. Each scheduled firing has an identity derived from job ID and scheduled time. One compare-and-set transaction creates or skips the occurrence and advances `next_run_at`. Manual triggers use a unique request ID and do not advance the cron cursor; retries retain the original run identity.

One active run per job is allowed. If a previous run is still active, the new occurrence is recorded as skipped. After downtime, only the most recent missed occurrence is created. Failures receive the initial attempt plus at most five retries using exponential backoff with jitter. Each attempt and terminal outcome is persisted.

A run invokes the existing Agent execution path rather than implementing another tool loop. It may target a standalone prompt or an existing Goal. Results can be silent or delivered to the originating conversation through the outbox.

Pause prevents new runs but does not silently cancel an already claimed run. Delete is a recoverable logical deletion. Resume recomputes the next occurrence from the current time.

### Continuous Goal Runner

The existing durable `GoalController` remains the owner of goal state and budgets. A new runner claims runnable goals with leases and executes one existing Agent turn at a time. After every turn, a structured Judge evaluates the persisted objective and acceptance criteria.

Goal-level persistence contains normalized acceptance criteria; Judge schema/prompt version and confidence threshold; iteration, token, estimated-cost and wall-clock limits; cumulative counters; cost model/currency; active-time baseline; and last applied guidance sequence. Paused time does not consume wall-clock budget, while running time before a crash does. Updates use compare-and-set versioning.

The Judge may complete a goal only when all acceptance criteria are satisfied and its confidence meets the configured threshold. Otherwise it persists the reason, progress, and `next_action` before scheduling the next iteration.

Budgets cover maximum iterations, tokens, estimated cost, and wall-clock duration. Reaching any boundary pauses the goal and emits a notification; it does not invent a successful completion. Transient model/tool failures retry. Repeated failures transition the goal to `blocked` with an actionable reason. Users can pause, resume, cancel, or append guidance at any time.

On restart, expired running leases become claimable. Completed, failed, cancelled, and paused goals never resume automatically. Every iteration has a deterministic identity so recovery cannot append the same result twice. Goal state and iteration state are separate: an immutable iteration moves `pending -> running -> judging -> completed/failed/cancelled`; one transaction persists Judge output and budget deltas, completes iteration N, updates the goal, and creates iteration N+1 when the goal remains runnable.

## Persistent Data Model

The migration adds logically separate tables; exact column names may follow existing control-plane conventions:

- `channel_accounts`: adapter kind, enabled state, encrypted/indirect credential references, default profile, capability metadata.
- `channel_ingress_checkpoints`: transport mode, cursor or gateway session/sequence, replay window, lease and reconnect metadata.
- `channel_routes`: account plus conversation/sender match, profile override, trigger policy, local session mapping.
- `inbox_events`: normalized inbound event, unique channel event key, processing state, lease, attempt and error data.
- `outbox_obligations`: destination, payload, unique idempotency key, delivery state, lease, retry, acknowledgement and dead-letter data.
- `scheduler_jobs`: extend the existing record with parsed timezone, retry/misfire/overlap policy and destination.
- `scheduler_runs`: unique job/scheduled-time identity, attempts, lease, timing, terminal state and linked turn/goal.
- `goals`: extend existing durable goal data with acceptance criteria, Judge configuration, budget limits/counters, active-time accounting and version.
- `goal_runs`: immutable goal iteration identity, lease, linked turn, judge result, budget deltas and terminal state.

Credentials are never stored in event payloads, logs, API responses, or delivery errors. Account records store opaque references to an OS credential store or an equivalently separated encrypted secret store; encryption keys never reside in SQLite beside ciphertext. The implementation defines least-privilege scopes, restrictive file permissions, rotation, protected backups, revocation, and secure deletion. Secrets are redacted in diagnostics.

## State Machines

Inbox and outbox share the auditable progression:

```text
pending -> claimed -> succeeded/acknowledged
                   -> retry_wait -> claimed
                   -> dead_letter
                   -> delivery_unknown
```

Scheduler runs use:

```text
pending -> running -> completed
                   -> retry_wait -> running
                   -> failed/cancelled
pending -> skipped
```

Goals use:

```text
runnable -> running -> runnable/completed
                    -> paused/blocked/failed/cancelled
```

Immutable goal iterations use:

```text
pending -> running -> judging -> completed/failed/cancelled
```

All transitions are centralized and reject illegal or stale-lease updates.

## Lifecycle and Concurrency

The application starts one durable-runtime supervisor after persistence and Agent services are ready. It starts bounded workers for inbox processing, schedule scanning, Goal execution, and outbox delivery. Workers use short wake-up events plus database polling, so missed in-memory notifications do not lose work.

Shutdown stops new claims, allows a bounded drain period, then releases or lets leases expire. Startup recovery does not rewrite records eagerly; it treats expired leases as claimable, preserving the audit trail.

Although the first target is one process, lease and compare-and-set semantics prevent accidental duplicate workers within that process and leave a clean path to future multi-process support.

## API and Operator Surface

Backend APIs will support:

- authenticated channel account configuration, validation, enable/disable, route management, and webhook endpoints;
- gateway health and per-adapter diagnostics with redacted secrets;
- inbox/outbox status, retry, dead-letter inspection, and acknowledgement history;
- scheduler job CRUD, pause/resume/delete, run history, trigger-now, and retry;
- Goal start/pause/resume/cancel/guidance, iteration history, budgets, and recovery status.

Existing API response conventions are preserved per endpoint family. Python DTOs and TypeScript mirrors are updated together. The settings UI will expose channel accounts/routes, scheduler runs, delivery failures, and Goal progress without reading raw persistence records.

Administrative APIs require strong authentication, resource-level roles, CSRF protection for browser sessions, re-authentication for secret/route changes and manual resend, and an append-only audit trail. Operator views redact message bodies, attachment URLs, user identifiers, temporary tokens, and platform responses by default. Retention/deletion policies cover payloads, PII, attachments, delivery records, and audit data.

## Error and Security Handling

- Validate cron syntax, timezone, adapter settings, webhook signatures, payload size, MIME type, and normalized identifiers at boundaries.
- Apply IP, adapter, account and global request/concurrency limits before body parsing and persistence; enforce queue, database and disk quotas. Apply per-conversation limits before Agent execution.
- Reject replayed inbound events through unique event keys.
- Escape or structure outbound content according to each channel's formatting rules.
- Never log tokens, signing secrets, complete authorization headers, or raw sensitive webhook payloads.
- Use request timeouts and bounded response sizes for every remote adapter.
- Separate retryable failures, rate limits, authentication failures, invalid destinations, and permanent payload errors.
- Treat channel text and attachments as untrusted user input governed by the existing tool safety policy.
- Restrict downloads to HTTPS and official per-adapter host allowlists; resolve and pin public IPs, block loopback/private/link-local/metadata ranges, revalidate every redirect, and prevent DNS rebinding.
- Stream attachments through byte/time limits; cap count, aggregate and decompressed sizes; validate magic bytes; use isolated non-executable random paths; reject traversal and symlinks; prevent archive bombs; expire temporary files; and never let attachment content bypass tool approval.

## Testing Strategy

Development follows TDD.

Unit coverage includes cron/timezone/misfire calculations, state transitions, lease expiry, backoff, idempotency keys, route selection, trigger policy, adapter normalization, signature validation, Judge parsing, and budget accounting.

Integration coverage uses temporary SQLite databases to verify atomic claims, duplicate ingress, duplicate outbox production, crash between claim/send/ack, expired-lease recovery, scheduler restart catch-up, non-overlap, Goal restart, pause/cancel races, and internal parent-session exactly-once insertion.

Adapter contract tests use recorded sanitized fixtures and mocked official APIs. Live credential tests remain opt-in. Every adapter must pass the same conformance suite.

End-to-end coverage proves:

1. an inbound channel event creates exactly one Agent turn and one acknowledged reply;
2. a process restart resumes pending delivery without duplicating local history;
3. a cron firing runs once, records attempts, and returns the result to its origin channel;
4. a Goal executes multiple turns, survives restart, satisfies its Judge contract, and emits one terminal result;
5. invalid signatures, replayed events, exhausted budgets, permanent delivery failures, and cancellation have visible, recoverable outcomes.

The project target remains at least 80% coverage for new runtime code, with unit, integration, and critical E2E tests all required.

## Delivery Order

1. Durable inbox/outbox repository, leases, idempotency, supervisor, and internal-session delivery.
2. Unified gateway contracts, routing, shared security, then the nine official adapters.
3. Executable scheduler and run-history APIs/UI.
4. Continuous Goal Runner and Judge/budget/recovery APIs/UI.
5. Cross-system E2E, packaging verification, operational documentation, and migration/recovery tests.

Each phase must leave existing CLI, Web, desktop, mobile companion, and agent-task behavior backward compatible.

## Acceptance Criteria

- Restarting the application cannot lose a committed inbound event, outbox obligation, scheduled run, or Goal iteration.
- Duplicate channel events and duplicate producer calls do not create duplicate Agent turns or local messages.
- All nine official adapters implement the shared conformance contract and expose truthful capability flags.
- Cron jobs honor timezone, non-overlap, latest-only catch-up, five retries, run history, pause/resume, and origin-channel delivery.
- Goals iterate through the existing AgentRunner, use structured judgment, enforce four budgets, recover expired leases, and stop only in a documented terminal or user-controlled state.
- Operators can inspect and retry failed deliveries and runs without editing SQLite manually.
- Secrets remain redacted, inbound authenticity is verified where supported, and new runtime code meets the project's test requirements.

## Explicit Non-Goals

- Unofficial personal WeChat or QQ automation.
- Execution while the computer and backend process are stopped.
- Multi-node or distributed database coordination.
- Guaranteed exactly-once remote delivery where an official platform provides no idempotency or reconciliation mechanism.
- Replacing the existing Agent tool loop, GoalController, chat repositories, or task queue wholesale.
