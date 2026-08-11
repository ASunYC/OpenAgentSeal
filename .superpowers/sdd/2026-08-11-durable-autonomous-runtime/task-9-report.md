# Task 9 Report: Continuous goal execution

## Outcome

Implemented a crash-safe continuous Goal runtime that reuses the authoritative
`AgentRunner` stream, persists every execution and judging boundary, and continues
until every acceptance criterion is evidenced above the configured confidence or a
bounded operational state is reached.

## Delivered behavior

- Immutable, bounded acceptance, pricing, budget, evidence and judge contracts.
- Atomic Goal creation, first iteration, visible start message, deterministic
  thread/turn binding and stable source-event/tool-effect fencing.
- Lease-fenced claim, renewal, judging, retry, restart recovery and concurrent
  pause/resume/cancel settlement with active-time accounting.
- Four fail-closed budgets: iterations, tokens, versioned estimated cost and active
  seconds. Budget and failure resumes require one-use, version-bound, expiring
  operator approvals with canonical approved deltas and durable issuer/consumer audit.
- Persisted bounded guidance with monotonic watermark, pending count/byte quotas,
  bounded pagination and prompt byte/estimated-token limits.
- Strict authoritative Agent terminal/result/usage validation before any terminal
  database write. Goal completion trusts only the persisted runtime turn.
- Atomic judge result, budget usage, guidance watermark, continuation iteration or
  exactly-once terminal/progress outbox settlement.
- Real local-session and channel payload protocols, second-hop ACL checks, sanitized
  delivery errors, and delivery-worker acknowledgement/reconciliation coverage.
- Opaque immutable request/operator principal capabilities with exact minted-object
  provenance, tenant/owner-scoped create/read/list/guide/transition/recovery/claim,
  and weak registries that cannot grow without bound.

## TDD and review

- RED checkpoints: `8392d7a`, `e79374e`, `30f35b3`, `7651724`, `e471e6d`,
  `89a5812`, `ea9ba85`, `28ccc65`, and `c2bc7a9`.
- Formal code and security reviews iterated through concurrency, delivery, parsing,
  budget, confused-deputy, approval, quota, terminal-schema and capability-model
  findings. Final gates approved with `0 Critical / 0 High / 0 Medium`.

## Verification

- Final Goal/auth focused gate: 61 tests passed.
- Related Goal, scheduler, gateway and recovery focused gate: 132 tests passed before
  the final capability hardening; focused auth delta: 9 tests passed.
- Final expanded Tasks 1-9 compatibility gate: 506 passed, 2 skipped.
- `open_agent.goal_runtime` line coverage: 85%.
- `compileall`, `git diff --check`, and secret-pattern scan passed.

## Remaining integration concerns

- Task 10 owns supervisor lifecycle, health, shutdown draining and worker scheduling.
- Task 11 owns public API/auth-boundary wiring. Configured Goal calls now intentionally
  require trusted request and operator capability contexts; callers must not fall back
  to caller-supplied identity strings.
