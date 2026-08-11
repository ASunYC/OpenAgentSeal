# Task 7 Report: Official messaging channel adapters

## Outcome

Implemented a production-bounded messaging adapter layer for Telegram, Discord,
Slack, WhatsApp Cloud, Feishu, DingTalk, LINE, QQ Bot, and WeCom. Channel replies
now flow from the completed Agent turn into an origin-scoped durable outbox,
through a persisted account destination, then to the official provider transport
with acknowledgement, retry, and ambiguous-outcome semantics that match each
provider's actual capabilities.

## Research and TDD evidence

- RED checkpoint: `66c5e2f test: define official messaging adapter conformance`.
  The conformance suite initially failed during collection because the adapter
  package did not exist.
- Current official protocol documentation was resolved through Context7 for
  Telegram, Discord, Slack, Feishu, DingTalk, LINE, QQ Bot, and WeCom. Meta's
  official WhatsApp pages returned HTTP 429, so the implementation deliberately
  uses the narrow Cloud API text-message contract and makes no unsupported
  idempotency or reconciliation claim.
- Sanitized provider fixtures contain no real account identifiers, tokens, keys,
  signatures, or message content.

## Delivered behavior

- A shared async HTTP transport enforces HTTPS, exact official-host allowlists,
  redirect refusal, request and streamed-response size caps, bounded timeouts,
  typed rate-limit/retry/ambiguous-delivery errors, and URL/query/path diagnostic
  redaction. Network causes are suppressed at the logging boundary.
- Adapter capability declarations are truthful. Discord uses provider nonce with
  nonce enforcement and LINE uses the official retry-key header; adapters whose
  APIs do not provide an equivalent guarantee do not claim idempotency.
- Telegram, Slack, Feishu, LINE, WhatsApp Cloud, and Discord/QQ/WeCom/DingTalk
  transport-specific boundaries reject unauthenticated or mismatched input.
  Unsupported polling, webhook, and gateway-resume modes remain declared false.
- LINE and WhatsApp accept complete webhook batches atomically before returning
  an acknowledgement, reject a 101st event before unbounded normalization, and
  do not silently discard later events.
- Bot-authored Telegram, Discord, and Slack messages are marked at normalization
  and never dispatched, preventing direct-message reply loops.
- Gateway-only providers require an `AuthenticatedGatewayFrame` minted by the
  configured `GatewayConnectorCapability`; raw decoded events, wrong sessions,
  capabilities, or sequences fail closed.
- WeCom AIBot group replies reuse the authenticated origin request through an
  injected gateway sender instead of misrouting a group chat identifier as a
  corporate-app user identifier.
- Agent completion, reply-obligation insertion, and inbox completion share the
  repository transaction. A stale completion fence rolls back the reply, and a
  restart can recover the authoritative completed-turn content without rerunning
  the Agent.
- Delivery honors provider `Retry-After`, retries safe idempotent timeouts, and
  marks non-idempotent ambiguous outcomes `delivery_unknown/manual_required`.

## Verification

- Focused adapter/ingress/router/delivery coverage command:
  `.venv\Scripts\python.exe -m pytest tests/gateway/test_adapter_conformance.py tests/test_gateway_ingress.py tests/test_gateway_core.py tests/test_reliable_delivery.py -q --cov=open_agent.gateway.adapters --cov=open_agent.gateway.destinations --cov-report=term`
  -> `149 passed`; adapters plus destinations line coverage `88%`.
- Expanded gateway, security, credentials, ingress, adapter, delivery, durable
  repository, and retention compatibility selection -> `373 passed, 2 skipped`.
- Independent code-review runs -> `114 passed` focused and `231 passed` expanded;
  final code gate `0 Critical / 0 High`.
- Independent security review -> `186 passed`; the final hardening delta added
  token-path redaction, pre-materialization batch caps, and authenticated gateway
  frame proofs. Delta verification -> `6 passed`; final security gate
  `0 Critical / 0 High / 0 Medium`.
- `.venv\Scripts\python.exe -m compileall -q open_agent\gateway open_agent\durable_runtime`
  and `git diff --check` passed.
- The complete repository suite was attempted twice and exceeded the tool limit
  at 124 seconds and 304 seconds without emitting a test failure. Per the plan,
  it was not rerun indefinitely; the relevant 373/2 compatibility gate above is
  the Task 7 merge evidence.

## Review fix rounds

- Round 1 closed five HIGH findings: webhook batch loss, bot reply loops,
  response buffering before its cap, incomplete authentication boundaries, and
  an invalid WeCom group-reply model. It also closed unsupported capability
  claims, provider retry-delay handling, and unused query-secret exposure.
- Round 2 separated Discord interaction webhooks from Gateway message frames,
  removed unused DingTalk/WeCom secret-bearing configuration, and made every
  gateway-only ingress path explicitly authenticated.
- Security hardening redacts Telegram tokens from owned HTTP logs and exceptions,
  rejects oversized provider batches before mass allocation, and makes capability
  proof mandatory for decoded gateway frames. Final independent review approved
  the result with no open Critical, High, or Medium issue.

## Remaining integration concerns

- Long-lived provider polling, Stream, and Gateway connector processes are future
  supervisor/wiring work. Their capabilities remain false until those drivers
  exist; this adapter task does not overstate support.
- The adapters intentionally expose text output only; attachment capability is
  false until provider-specific upload lifecycles are implemented and tested.
- `ChannelDestinationRegistry` account/credential composition belongs to the
  planned runtime wiring tasks. Current tests exercise it with persisted account
  resolution and injected official adapters.
- Recheck Meta's official WhatsApp documentation when its documentation endpoint
  is available; the current conservative contract has no unsafe optimistic claim.
