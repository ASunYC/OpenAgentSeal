# Task 11 — authenticated operational APIs

## Delivered

- Server-minted immutable operational principals with scoped bearer/cookie sessions,
  role checks, recent reauthentication, exact Origin/Host plus CSRF enforcement for
  ambient cookie mutations, bounded per-session rate limiting, and signed
  tenant/actor/resource-bound pagination cursors.
- Authoritative immutable tenant and actor ownership for channel accounts, routes,
  inbox/outbox records, scheduler jobs/runs, Goals, audit records, and retention
  dead letters. Cross-tenant reads are concealed and mutations use owned CAS paths.
- Channel account, opaque credential rotation, route CRUD, diagnostics, bounded
  webhook ingress, inbox/outbox inspection, manual resend, audit redaction/reveal,
  scheduler job/run/manual trigger, Goal lifecycle/guidance/approval, retention,
  and supervisor-health operational endpoints.
- Canonical Task 10 composition reuse: production ingress, credential cleanup,
  scheduler, Goal, delivery, retention, and supervisor services are not duplicated.
- Compensating credential publication/rotation, durable bounded cleanup retries,
  global versioned retention policy hydration, request-driven retention runs, and
  tenant-owned dead-letter requeue.
- Recursive response redaction, credential reveal prohibition, auditor plus recent
  reauthentication for classified noncredential reveal, and audit-before-return.
- Signed per-occurrence tenant/actor ownership through retention source, overflow
  backlog, retry queue, dead-letter quarantine, exact tenant listing, and requeue;
  legacy two-field backlog manifests fail closed for explicit migration.
- Server-minted HMAC opaque IDs bind channel accounts, scheduler jobs, Goals,
  Goal sessions, and operator approvals to tenant, actor, resource kind, and client
  reference, removing global identifier probing and cross-tenant namespace squatting.

## Verification

- RED commit: `4f15db9 test: define authenticated autonomous runtime operations`.
- API and retention focused: 96 passed, 2 skipped.
- Expanded runtime/gateway compatibility: 461 passed, 2 skipped.
- New operational API modules: 81% combined line coverage (`auth` 86%,
  `autonomics_api` 86%, `gateway_api` 76%).
- `compileall` and `git diff --check`: clean.
- Final code review: APPROVED, 0 Critical / 0 High / 0 Medium / 0 Low.
- Final security review: APPROVED, 0 Critical / 0 High / 0 Medium / 0 Low.

## Review remediation

- Closed the initial 4 High and 3 Medium code findings covering production ingress,
  retention execution/tenant boundaries, credential CAS/cleanup, exact Goal paging,
  stable domain errors, and audit ownership.
- Closed the second 3 High and 2 Medium findings covering global retention policy
  semantics and startup hydration, dead-letter ownership, cleanup/reconciliation,
  guidance concealment, and direct retention audit ownership.
- Closed the final High finding with authenticated per-occurrence ownership in
  overflow backlog manifests and a 65-record fault-injection regression.
- Closed security findings covering recursive audit classification/redaction,
  public webhook pre-limiting, atomic owned deletion, crash-durable credential
  cleanup, canonical configured CSRF origins, and opaque tenant namespaces.

## Operational notes

- Retention policy is intentionally system-global; only a recently reauthenticated
  `system_operator` may mutate it or request a manual run.
- The only unauthenticated application route introduced here is the exact gateway
  webhook path. It enforces a raw-body size bound and adapter signature validation
  before parsing or enqueueing.
- Credential API responses contain opaque references only; secret resolve/reveal is
  never exposed through operational endpoints.
