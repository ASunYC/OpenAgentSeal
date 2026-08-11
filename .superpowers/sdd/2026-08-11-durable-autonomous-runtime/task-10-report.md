# Task 10 — durable runtime supervisor

## Delivered

- Immutable worker specifications and health snapshots.
- One crash-isolated loop each for inbox, scheduler, Goal, outbox, and retention.
- Startup recovery poll/readiness, wake-without-loss, bounded jitter/backoff, restart counters, sanitized failures, idempotent lifecycle, and cancellation cleanup.
- Canonical repository/composition with stable retention HMAC key, automatic retention, dynamic enabled-account destination resolution, and adapter wake hook.
- FastAPI lifespan ownership after chat/MCP initialization; no import/create-app runtime start side effect.
- Atomic scheduler `execute_next`/`run_once`, including retry/stale-lease/manual handling and child cancellation cleanup.
- A common bounded per-session AgentRunner gate (32 waiters, 30 second acquisition timeout) covering web and durable callers.
- Dedicated Goal judge model invocation with no tools, enrichment, history, chat/runtime persistence, or web/memory prefetch; strict structured result validation remains fail-closed.
- Idempotent ChatManager initialization and a sanitized read-only supervisor health endpoint.

## Verification

- RED commit: `b4c4724 test: define autonomous runtime supervision`.
- Supervisor focused: 9 passed, 94% line coverage.
- Scheduler/supervisor/delivery focused: 61 passed.
- Expanded runtime compatibility: 242 passed, 2 skipped.
- `compileall` and `git diff --check`: clean.
- Final security review: APPROVED, 0 Critical / 0 High / 0 Medium.
- Initial code review findings (3 High, 2 Medium) were addressed: common-boundary session gating, atomic eligible scheduler claim, removal of unauthenticated wake API, protected lifespan startup, and bounded synchronous retention polling. Final review's two non-blocking Medium findings were also removed by constructing only an LLM client for judging and eliminating non-cancellable thread polling.

## Operational notes

- Channel adapters are registered into the canonical composition only after their persisted account is configured. Unregistered or disabled destinations remain pending and are not dead-lettered by startup.
- Provider connector loops are not advertised because the current adapter contracts do not expose an authenticated long-lived polling/gateway connector implementation. The internal registration wake hook is ready for that future worker family.
