# Task 8 Report: Executable cron scheduler

## Outcome

Implemented an explicit, supervisor-neutral scheduler runtime that validates strict
five-field cron expressions, calculates timezone-aware occurrences, scans durable
jobs with latest-only catch-up, and executes each claimed occurrence through the
existing `AgentRunner.run_stream` loop. Scheduler runs, retry state, deterministic
turn bindings, fencing claims, and origin delivery obligations survive restart.

## TDD and dependencies

- RED checkpoint: `7637a72 test: define executable scheduler runtime`.
- Added bounded `croniter>=6.0,<7` to `pyproject.toml` and regenerated `uv.lock`.
- `CronSchedule` defaults to `Asia/Shanghai`, accepts only valid IANA zones, skips
  nonexistent spring-gap wall times, and emits both fall-fold occurrences.

## Delivered behavior

- Scanner cursor CAS separates the persisted expected cursor, the latest missed
  `scheduled_at`, and the next future cursor in one SQLite transaction.
- Latest-only catch-up uses a direct previous-occurrence calculation instead of
  replaying every missed minute; invalid legacy jobs are quarantined as paused so
  they cannot starve healthy jobs.
- Non-overlap is enforced both while materializing occurrences and while claiming
  concurrent pending/manual work. Paused automatic jobs cannot begin; explicit
  request-ID-idempotent manual runs do not advance cron cursors.
- A claim atomically binds each run to deterministic scheduler session, thread and
  turn identities. Expired leases are recoverable and stale workers are fenced.
- Every retry uses the stable `scheduler:<run_id>` tool-effect key and the existing
  durable effect reconciliation boundary. Ambiguous non-idempotent effects stop in
  failed/manual-reconciliation state instead of rerunning.
- A completed persisted Agent turn is recovered and delivered without invoking the
  model again after a scheduler-boundary crash.
- Failures use durable exponential backoff for the initial attempt plus five
  retries by default. Completion and optional origin outbox insertion commit in a
  single transaction; silent completion is accepted only when no destination is
  configured. `channel:<account>` destinations use Task 7's origin-scoped channel
  obligation contract.
- `SchedulerWorker` is only explicitly callable. It does not create a background
  thread, lifespan hook, or second Agent loop; Task 10 remains the supervisor owner.

## Verification

- Focused scheduler/autonomics/repository gate: `88 passed`.
- Scheduler/autonomics/repository/runtime API compatibility gate before final
  review fixes: `83 passed`; the focused post-fix set covers all changed scheduler
  transitions.
- Expanded Tasks 1-8 durable runtime, delivery, gateway, security, credentials,
  retention, adapters, scheduler and runtime API gate: `437 passed, 2 skipped`.
- New `open_agent.scheduler_runtime` line coverage: `85%`.
- `compileall` and `git diff --check` passed.

## Review fixes

- Formal code review fix rounds closed tool-effect retry fencing, completed-turn
  crash recovery, paused/deleted claim gating, legacy-row scan isolation, a
  cross-process cursor-migration rewind race, and timezone error normalization.
- Independent security fix rounds additionally bounded persistence inputs, retry
  arithmetic and due-scan work, pinned execution identity, fenced deleted manual
  runs, and normalized cursor storage. Final code and security gates both approved
  with `0 Critical / 0 High / 0 Medium`.

## Remaining integration concerns

- Recurring process lifecycle, health reporting, shutdown draining, and worker
  supervision intentionally remain Task 10 scope.
- Task 11 owns public scheduler APIs; direct low-level `ControlPlane` calls remain
  an internal compatibility surface while `SchedulerController` is the validated
  creation/lifecycle facade.
