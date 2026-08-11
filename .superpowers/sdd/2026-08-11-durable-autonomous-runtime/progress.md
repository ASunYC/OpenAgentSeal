# SDD ledger — plan: docs/superpowers/plans/2026-08-11-durable-autonomous-runtime.md

Baseline: 3753211; isolated branch codex/durable-autonomous-runtime.
Baseline tests: 18 passed (`test_goal_mode`, `test_autonomics`, `test_agent_profiles`, `test_runtime_api`).
Task 1: fix round 1/5 (2 addressed, 0 open; commits e2520e6..d0ff4e1)
Task 1: complete (commits 3753211..d0ff4e1, review clean)
Task 2: fix round 1/5 (2 addressed, 0 open; commits 42e751d..203b4dc)
Task 2: complete (commits d0ff4e1..203b4dc, review clean)
Task 3: minor (deferred): Delivery retry currently uses zero jitter; final review must decide whether to require configurable injected jitter before merge.
Task 3: fix round 1/5 (3 addressed, 0 open; commits 3ff9a96..b8c2cef)
Task 3: complete (commits 203b4dc..b8c2cef, review clean)
Task 4: minor (deferred): DurableRuntimeRepository exceeds the 800-line project guideline and resolve_channel_route needs focused helper extraction without breaking its single transaction.
Task 4: fix round 1/5 (3 addressed, 0 open; commits 6117c60..43661a0)
Task 4: complete (commits 4a2ea35..43661a0, review clean)
Task 5: minor (deferred): AccountCredentialStore lacks account-bound put_async and may block an event loop during credential creation.
Task 5: fix round 1/5 (3 addressed, 1 open; commits 0f2b327..5ff6ea5)
Task 5: fix round 2/5 (1 addressed, 1 new open; commits 5ff6ea5..ed29f80)
Task 5: fix round 3/5 (1 addressed, 2 new open; commits ed29f80..cfb97c4)
Task 5: fix round 4/5 (all retention HMAC, occurrence fencing, file identity, path alias and legacy-source findings addressed; commits cfb97c4..5fcc159)
Task 5: complete (commits 43661a0..5fcc159, reviews clean; 1 deferred minor)
Task 6: minor (deferred): Same event key with a different canonical payload needs explicit conflict diagnostics beyond database uniqueness.
Task 6: minor (deferred): Profile/session/turn authority should be strengthened across per-profile control-plane selection.
Task 6: minor (deferred): Agent/provider error details require a centralized redaction boundary.
Task 6: minor (deferred): Quota release needs an idempotent noexcept compensation path.
Task 7: fix round 1/5 (5 HIGH and 3 MEDIUM addressed; batch, loop, bounded transport, authentication, WeCom routing, capability, retry-delay, and secret-surface findings closed)
Task 7: fix round 2/5 (Discord transport boundary and 3 security MEDIUM findings addressed; final code/security gates 0 Critical, 0 High, 0 Medium)
Task 7: complete (RED 66c5e2f plus implementation commit; 149 focused at 88% adapter/destination coverage, 373 passed and 2 skipped compatibility, reviews clean)
Task 8: fix round 1/5 (2 HIGH and 2 MEDIUM code findings addressed: tool-effect fencing, completed-turn recovery, pause claim gating, legacy quarantine)
Task 8: fix round 2/5 (1 HIGH, 2 MEDIUM, 1 LOW security findings addressed: deleted-manual fencing, bounded due scan/validation/backoff, pinned identity)
Task 8: fix round 3/5 (cross-process cursor migration CAS/marker and bounded timezone validation addressed)
Task 8: complete (RED 7637a72 plus implementation commit; 88 focused, 437 passed and 2 skipped compatibility, 85% scheduler coverage, code/security 0 Critical / 0 High / 0 Medium)
Task 9: fix round 1/5 (9 HIGH and 4 MEDIUM code findings addressed: recovery, authoritative results, delivery protocol, CAS settlement, cancellation, strict evidence/config, retry state, immutable Goal state, atomic start and resume decisions)
Task 9: fix round 2/5 (destination bounds, scoped local delivery, strict judge/acceptance parsing, latest-claim settlement and unified outbox conflicts addressed)
Task 9: fix round 3/5 (3 HIGH and 2 MEDIUM security findings addressed: session-derived delivery principals, operator approvals, guidance quotas, authoritative output bounds and sanitized delivery errors)
Task 9: fix round 4/5 (opaque tenant principals, versioned expiring canonical operator approval, shared pre-write terminal validator and bounded transition reason addressed)
Task 9: fix round 5/5 (principal-scoped recovery/read/list/claim, owner-bound runtime threads, immutable exact-provenance weak capability registries addressed)
Task 9: complete (nine RED checkpoints; 506 passed and 2 skipped expanded compatibility, 85% Goal runtime coverage, final code/security 0 Critical / 0 High / 0 Medium)
Task 10: fix round 1/5 (3 HIGH and 2 MEDIUM code findings addressed: common session gate, atomic eligible scheduler claiming, unauthenticated wake removal, protected lifespan startup, and bounded synchronous retention polling)
Task 10: fix round 2/5 (Goal judge prompt-injection/exfiltration HIGH and unbounded session waiter MEDIUM addressed with a dedicated tool-free non-persisting model path plus bounded acquisition)
Task 10: complete (RED b4c4724; 9 supervisor tests at 94% coverage, 242 passed and 2 skipped expanded compatibility, final code/security 0 Critical / 0 High; security 0 Medium)
Task 11: fix round 1/5 (4 HIGH and 3 MEDIUM code findings addressed: production ingress, retention execution/tenant boundaries, credential CAS, exact Goal paging, stable errors, and audit ownership)
Task 11: fix round 2/5 (3 HIGH and 2 MEDIUM code findings addressed: global retention policy hydration, dead-letter ownership, credential cleanup/reconciliation, guidance concealment, and retention audit ownership)
Task 11: fix round 3/5 (retention overflow backlog preserves authenticated per-occurrence ownership through queue, dead-letter, exact tenant lookup, and requeue)
Task 11: security fix round 1/5 (1 HIGH and 4 MEDIUM addressed: recursive audit reveal/list protection, public webhook pre-limiting, atomic owned deletion, crash-durable credential cleanup, and canonical trusted CSRF origins)
Task 11: security fix round 2/5 (global identifier probing/squatting closed with tenant/actor/resource-bound opaque account, job, Goal, session, and approval IDs)
Task 11: complete (RED 4f15db9; 96 focused and 2 skipped, 461 passed and 2 skipped expanded compatibility, 81% new API coverage, final code/security 0 Critical / 0 High / 0 Medium / 0 Low)
