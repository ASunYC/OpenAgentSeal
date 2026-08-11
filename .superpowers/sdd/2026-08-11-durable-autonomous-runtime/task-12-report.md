# Task 12 — autonomous runtime administration UI

## Delivered

- Vue administration surfaces for channel accounts, routes, inbox, delivery
  reconciliation, audit, retention, supervisor health, scheduled jobs and runs,
  continuous Goals, iterations, guidance, approvals, controls, and four budgets.
- Immutable, unknown-safe TypeScript projections for redaction, capability-driven
  legal actions, delivery risk, budget consumption, and CAS mutations.
- A dedicated operational API client with structured errors, abort signals,
  pagination cursors, same-origin credentials, bearer support for Tauri, CSRF,
  recent reauthentication, `If-Match`, and 204 handling.
- Write-only credential and operational-access workflows. Secrets are never
  revealed, logged, placed in URLs, or written to browser persistence; privileged
  noncredential audit data is memory-only and cleared on close/unmount.
- Accessible confirmation and reauthentication dialogs with focus trap, Escape,
  focus restoration, typed confirmation, and live error announcements.
- Semantic keyboard-operable settings tabs and strict single-column responsive
  layouts below 720px, including desktop-shell overflow protection.
- Secure operational session bootstrap: the Tauri host generates a fresh 256-bit
  capability for every backend start/restart, injects it only into the child
  process, and retains rotated successors only in Rust memory. Browser sessions
  resume via HttpOnly cookie plus freshly rotated in-memory CSRF.

## Reliability and security remediation

- Added one-use capability validation and rotation; missing, incorrect, and
  replayed bootstrap values fail closed.
- Recent-authentication expiry now opens an explicit user-presence dialog and
  retries only the exact server-rejected mutation once.
- Load-more actions use resource-specific in-flight guards, cursor epochs, and
  abort signals to prevent duplicated pages and stale selection writes.
- Channel-account CAS versions are fetched in one bounded query rather than an
  N+1 query, while account and Goal mutations preserve authoritative versions.
- Conflict responses keep user drafts intact; high-risk delivery reconciliation
  is never automatically retried and requires typed identity plus reauthentication.

## Verification

- RED commits: `785e931`, `84e889c`, and `505770c`.
- TypeScript projection tests: passed.
- `vue-tsc --noEmit` and production Vite build: passed (206 modules; existing
  bundle-size advisory only).
- Focused autonomous operations API: 23 passed.
- Changed operational auth/API modules: 80% combined line coverage (`auth` 82%,
  `gateway_api` 80%).
- Tauri desktop unit tests: 11 passed using a test-only Tauri config that omits
  the absent packaged sidecar binary.
- `cargo fmt --check` and `git diff --check`: clean.
- Final TypeScript review: PASS, 0 Critical / 0 High / 0 Medium.
- Final code review: PASS, 0 Critical / 0 High / 0 Medium.
- Final security review: PASS, 0 Critical / 0 High / 0 Medium.

## Operational notes

- Web deployments without a valid existing cookie intentionally require an
  administrator-provisioned one-time capability. No loopback or Origin signal can
  grant a role by itself.
- Operational permissions shown in the UI are affordances only; server roles,
  capabilities, ownership, recent authentication, and CAS remain authoritative.
- A transport loss after successful one-time capability consumption intentionally
  fails closed; restarting the host/backend provisions a fresh recovery capability.
