# Autonomous runtime operations

This runbook covers the durable message gateway, scheduler, Goal runner,
delivery reconciliation, retention, and process supervision. The runtime uses
one SQLite control-plane database; an HTTP acknowledgement is returned only
after inbound work is committed. Agent results and outbound sends are separate
durable obligations.

## Channel capability matrix

Only the transport modes below are implemented. An adapter marked “connector”
parses authenticated frames supplied by an operator-managed provider connector;
OpenAgentSeal does **not** yet open, authenticate, or supervise that provider's
long-lived socket/stream itself.

| Channel | Inbound mode | Outbound mode | Important limitation |
|---|---|---|---|
| Telegram | authenticated webhook | Bot API HTTPS | webhook secret token required |
| Discord | connector (Gateway frame) | REST HTTPS | no built-in Gateway socket/resume loop |
| Slack | signed webhook | Web API HTTPS | signing timestamp and signature required |
| WhatsApp Cloud | signed webhook | Graph API HTTPS | app-secret signature required |
| Feishu | verified/encrypted webhook | Open API HTTPS | verification/encryption configuration required |
| DingTalk | connector (Stream frame) | Open API HTTPS | no built-in Stream client |
| LINE | signed webhook | Messaging API HTTPS | batch webhook signature required |
| QQ Bot | connector (Gateway frame) | Open API HTTPS | no built-in Gateway socket/resume loop |
| WeCom AI Bot | connector (WebSocket frame) | originating connector callback | reply must retain its request/frame identity; no built-in WebSocket client |

Never expose a connector-only account as a public webhook. Provider challenge
responses, raw-body authentication, batch limits, replay/deduplication, tenant
routes, and destination account identity are enforced at the gateway boundary.

## Credentials and rotation

Channel records contain opaque credential references, never secret values. On
Windows, secrets are stored through Windows Credential Manager. Production
deployments must provide the operational bootstrap token and a stable
`OPEN_AGENT_RETENTION_HMAC_KEY` (URL-safe base64, at least 32 decoded bytes), or
use the platform-protected generated retention key. Do not copy credentials into
SQLite, logs, fixtures, environment dumps, or support bundles.

Rotate a channel credential by creating a new protected credential, testing it,
then atomically updating the account's expected version/reference through the
authenticated operations API. Reauthenticate immediately before credential
create/rotate/delete. Keep the old credential until the update is committed;
then revoke it at the provider and allow the durable credential-cleanup worker
to remove the obsolete local reference. A failed cleanup is retried and becomes
an operator-visible dead letter rather than silently disappearing.

## Scheduler

Schedules are strict five-field cron expressions. The default timezone is
`Asia/Shanghai`; persist an IANA timezone explicitly for portable behavior.
Spring DST gaps are skipped, while both distinct fall-back folds are eligible.
The scanner uses latest-only catch-up and persists the cursor and occurrence
identity atomically, so restart does not duplicate a cron occurrence. Overlap
policy may skip an occurrence while still advancing the cursor.

Failures use bounded exponential backoff and the job's retry budget. A run whose
external tool effect is ambiguous is fenced for manual reconciliation. Pausing
prevents queued automatic occurrences from starting; deleting also prevents
manual runs. A manual request ID is idempotent and never advances the cron
cursor. When a destination is configured, an empty Agent result is a failure,
and completion is not delivery: confirm the origin outbox reaches
`acknowledged`.

## Goals, budgets, guidance, approvals, and cancellation

Each Goal persists exact acceptance criteria, confidence threshold, judge schema
and prompt versions, pricing snapshot, and iteration/token/cost/active-time
budgets. The judge runs on a dedicated tool-free, non-persisting model path.
Every criterion requires typed evidence; `done` is accepted only when all are
satisfied and confidence reaches the threshold.

Guidance is bounded, ordered, and consumed at a persisted watermark. Pause,
resume, cancel, and budget changes use exact version compare-and-swap. Sensitive
resume/budget changes require a short-lived operator approval bound to tenant,
principal, Goal version, decision, and expiry. Cancellation is terminal for new
iterations; an already claimed worker must settle through the same fenced state
transition. Budget exhaustion pauses the Goal and emits an origin result rather
than continuing indefinitely.

## Health and shutdown

Readiness is true only after every required worker has completed a successful
first recovery poll. Monitor each worker's poll count, restart count, last
success, and sanitized error class. Optional connector/credential workers do not
block readiness. During shutdown, stop accepting traffic, invoke supervisor
drain, and wait for the configured deadline. The supervisor cancels work that
cannot drain; leases make it restart-eligible without two live owners.

## Dead letters and `delivery_unknown`

`retry_wait` means the operation is safe to retry. `dead_letter` requires a
payload/configuration/credential correction and an explicit operator action.
`delivery_unknown` means the provider may have accepted the remote side effect;
it is deliberately excluded from automatic claims after restart.

Before manually resending `delivery_unknown`, reconcile using provider message
history or the provider's idempotency key where available. Reauthenticate, state
the duplicate risk explicitly, use acknowledgement schema version `1`, and let
the runtime create a new obligation plus immutable audit entry. Never rewrite or
requeue the original row. Tool-effect unknowns follow the same rule.

## Retention and redaction

Retention cutoffs apply independently to inbox payloads, delivered outbox data,
and audit records. Runs are bounded and idempotent. Attachment deletion uses a
signed occurrence manifest, ownership token, file identity checks, and quarantine
states so a stale cleanup cannot delete a replacement file. Restart resumes the
durable queue. Invalid/legacy unsigned attachment sources fail closed and require
an explicit migration.

Logs, API responses, health snapshots, and stored errors must contain only stable
error codes/classes—not tokens, webhook bodies, credentials, Goal guidance from
another tenant, or provider URLs containing secrets. Treat the retention HMAC
key as backup-critical: losing it prevents authenticated deletion of old
attachment occurrences.

## Backup and restore

Take a **consistent set** while ingress/workers are stopped and SQLite is
checkpointed:

1. back up the SQLite database (using SQLite's online backup API or a stopped,
   checkpointed copy), attachment tree, protected credential store, retention
   HMAC key, and non-secret account/provider configuration;
2. record application/schema version and verify file hashes;
3. restore all parts together into an isolated host with identical filesystem
   permissions and protected-secret ownership;
4. start with outbound delivery disabled, run migrations and integrity checks,
   inspect `delivery_unknown`, executing tool effects, dead letters, scheduler
   cursors, and active Goal leases;
5. re-enable ingress, then workers, then outbound delivery after reconciliation.

Never restore only SQLite or only attachments: their occurrence identities and
retention fences are coupled. Never export plaintext credentials as a shortcut.

## Migration and rollback

Database initialization is idempotent and the current schema tolerates tested
concurrent first startup. Individual compatibility changes are guarded and
repeatable, but the complete multi-phase migration is not one all-or-nothing
transaction. Keep traffic and workers stopped while upgrading, and do not run
mixed application versions against the same database. Take the consistent backup
above before upgrading.
Schema rollback is **forward-only**: deploy a corrective migration or restore the
entire pre-upgrade backup into the previous application version. Do not manually
drop columns/tables or run an older binary against a newer schema. If startup
migration fails, keep traffic and workers stopped, preserve the original files,
and recover from the verified backup or a corrective build.

## Verification without production side effects

Run the deterministic SQLite/provider-mock suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e/test_autonomous_runtime.py -v
```

Then run the full Python, Web model/build, mobile/packaging entrypoint, release
manifest, and desktop packaging tests described by the repository. These checks
must use sanitized fixtures and must not read system credentials or contact the
nine providers.
