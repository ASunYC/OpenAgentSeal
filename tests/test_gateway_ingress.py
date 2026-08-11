from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.models import InboxEvent
from open_agent.durable_runtime.repository import (
    DurableRuntimeRepository,
    StaleClaimError,
    StateConflictError,
)
from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent
from open_agent.gateway.ingress import IngressLimits, IngressService, IngressWorker
from open_agent.gateway.router import GatewayRouter
from open_agent.gateway.security import (
    HierarchicalIngressLimiter,
    IngressGuard,
    LimitRule,
    QuotaSnapshot,
    ResourceQuotaPolicy,
    SecurityViolation,
    StoredAttachment,
    WebhookAuthenticator,
)


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
SECRET = b"test-webhook-secret"


class Nonces:
    def __init__(self) -> None:
        self.values: set[tuple[str, str]] = set()

    def claim(self, account_id, nonce, expires_at):
        key = (account_id, nonce)
        if key in self.values:
            return False
        self.values.add(key)
        return True


class Ledger:
    def __init__(self, order: list[str] | None = None) -> None:
        self.order = order
        self.released: list[str] = []

    def try_reserve(self, policy, request, conversation_id):
        if self.order is not None:
            self.order.append("quota")
        return f"quota:{conversation_id}"

    def release(self, token):
        self.released.append(token)


class Adapter:
    kind = "test"
    capabilities = ChannelCapabilities()

    def __init__(self, event: NormalizedInboundEvent, order: list[str] | None = None):
        self.event = event
        self.order = order
        self.normalize_calls = 0

    def normalize(self, raw_payload: bytes) -> NormalizedInboundEvent:
        self.normalize_calls += 1
        if self.order is not None:
            self.order.append("parse")
        assert raw_payload == b'{"text":"hello"}'
        return self.event

    async def send(self, message):  # pragma: no cover - outbound contract only
        raise AssertionError("ingress must not send")


class RecordingRunner:
    def __init__(self, control_plane=None, *, mode: str = "complete", fail_before_stream: bool = False) -> None:
        self.calls = []
        self.control_plane = control_plane
        self.mode = mode
        self.fail_before_stream = fail_before_stream

    async def run_stream(self, request, *, runtime_turn):
        self.calls.append((request, runtime_turn))
        if self.fail_before_stream:
            raise RuntimeError("simulated crash before Agent execution")
        if self.mode == "complete":
            if self.control_plane is not None:
                self.control_plane.complete_runtime_turn(runtime_turn["turn_id"], status="completed")
            yield SimpleNamespace(event="complete", error=None)
        elif self.mode == "cancelled":
            if self.control_plane is not None:
                self.control_plane.complete_runtime_turn(runtime_turn["turn_id"], status="cancelled")
            yield SimpleNamespace(event="cancelled", error=None)
        elif self.mode == "error":
            if self.control_plane is not None:
                self.control_plane.complete_runtime_turn(runtime_turn["turn_id"], status="error")
            yield SimpleNamespace(event="error", error="failed")
        elif False:  # keep this method an async generator for the silent case
            yield None


@pytest.fixture
def runtime(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    repository.upsert_channel_account(
        account_id="account-1",
        adapter_kind="test",
        default_profile_id="main",
        now=NOW,
    )
    try:
        yield control_plane, repository
    finally:
        control_plane.close()


def inbound(**changes) -> NormalizedInboundEvent:
    values = {
        "event_key": "platform-event-1",
        "adapter_kind": "test",
        "account_id": "account-1",
        "conversation_id": "conversation-1",
        "sender_id": "sender-1",
        "conversation_kind": "dm",
        "text": "hello",
        "metadata": {"transport_id": "opaque-1"},
    }
    values.update(changes)
    return NormalizedInboundEvent(**values)


def signed_headers(raw_body: bytes, *, nonce: str = "nonce-1") -> dict[str, str]:
    timestamp = str(int(NOW.timestamp()))
    signature = hmac.new(
        SECRET,
        timestamp.encode() + b"." + nonce.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-account-id": "account-1",
        "x-webhook-timestamp": timestamp,
        "x-webhook-nonce": nonce,
        "x-webhook-signature": f"sha256={signature}",
    }


def ingress_service(repository, *, order=None, now=lambda: NOW, limits=None, **changes):
    def secret_lookup(account_id):
        if order is not None:
            order.append("auth")
        return SECRET if account_id == "account-1" else None

    rules = {
        dimension: LimitRule(100, timedelta(minutes=1), 10)
        for dimension in HierarchicalIngressLimiter.DIMENSIONS
    }
    guard = IngressGuard(
        WebhookAuthenticator(
            secret_lookup=secret_lookup,
            nonce_store=Nonces(),
            max_age=timedelta(minutes=5),
        ),
        HierarchicalIngressLimiter(rules, now=now),
    )
    ledger = Ledger(order)
    quota_snapshot = changes.pop(
        "quota_snapshot", lambda event: QuotaSnapshot(attachment_bytes=0)
    )
    service = IngressService(
        repository,
        GatewayRouter(repository, now=now),
        ingress_guard=guard,
        quota_policy=ResourceQuotaPolicy(
            max_queue_depth=100,
            max_database_bytes=2**30,
            min_disk_free_bytes=0,
            max_attachment_bytes=2**20,
            max_agents_per_conversation=1,
        ),
        quota_ledger=ledger,
        quota_snapshot=quota_snapshot,
        now=now,
        limits=limits or IngressLimits(),
        **changes,
    )
    return service, ledger


def test_webhook_authenticates_raw_bytes_then_admits_quota_then_enqueues_before_ack(runtime):
    _, repository = runtime
    order: list[str] = []
    service, ledger = ingress_service(repository, order=order)
    adapter = Adapter(inbound(), order)
    original_enqueue = repository.enqueue_inbox_with_nonce

    def recording_enqueue(event, **kwargs):
        order.append("enqueue")
        return original_enqueue(event, **kwargs)

    repository.enqueue_inbox_with_nonce = recording_enqueue
    body = b'{"text":"hello"}'

    receipt = service.accept_webhook(
        adapter,
        body,
        signed_headers(body),
        account_id="account-1",
        remote_ip="203.0.113.7",
    )
    order.append("ack")

    assert order == ["auth", "parse", "quota", "enqueue", "ack"]
    assert repository.get_inbox(receipt.event_id) is not None
    assert ledger.released == ["quota:conversation-1"]


def test_invalid_webhook_never_parses_or_enqueues(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    adapter = Adapter(inbound())
    body = b'{"text":"hello"}'
    headers = signed_headers(body)
    headers["x-webhook-signature"] = "sha256=invalid"

    with pytest.raises(SecurityViolation, match="signature"):
        service.accept_webhook(
            adapter,
            body,
            headers,
            account_id="account-1",
            remote_ip="203.0.113.7",
        )

    assert adapter.normalize_calls == 0
    assert repository.list_inbox() == []


def test_authenticated_account_cannot_be_rebound_by_normalized_payload(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    adapter = Adapter(inbound(account_id="another-account"))
    body = b'{"text":"hello"}'

    with pytest.raises(SecurityViolation, match="account mismatch"):
        service.accept_webhook(
            adapter,
            body,
            signed_headers(body),
            account_id="account-1",
            remote_ip="203.0.113.7",
        )

    assert repository.list_inbox() == []


def test_webhook_does_not_ack_when_durable_enqueue_fails(runtime):
    _, repository = runtime
    service, ledger = ingress_service(repository)
    adapter = Adapter(inbound())
    repository.enqueue_inbox_with_nonce = lambda event, **kwargs: (_ for _ in ()).throw(OSError("disk full"))
    body = b'{"text":"hello"}'

    with pytest.raises(OSError, match="disk full"):
        service.accept_webhook(
            adapter,
            body,
            signed_headers(body),
            account_id="account-1",
            remote_ip="203.0.113.7",
        )

    assert ledger.released == ["quota:conversation-1"]


def test_same_nonce_and_digest_resumes_after_transient_enqueue_failure(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    adapter = Adapter(inbound())
    body = b'{"text":"hello"}'
    original = repository.enqueue_inbox_with_nonce
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("transient database failure")
        return original(*args, **kwargs)

    repository.enqueue_inbox_with_nonce = fail_once
    with pytest.raises(OSError, match="transient"):
        service.accept_webhook(
            adapter, body, signed_headers(body),
            account_id="account-1", remote_ip="203.0.113.7",
        )

    receipt = service.accept_webhook(
        adapter, body, signed_headers(body),
        account_id="account-1", remote_ip="203.0.113.7",
    )
    assert repository.get_inbox(receipt.event_id) is not None


def test_same_nonce_with_different_authenticated_digest_is_rejected(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    body = b'{"text":"hello"}'
    service.accept_webhook(
        Adapter(inbound()), body, signed_headers(body),
        account_id="account-1", remote_ip="203.0.113.7",
    )
    changed = b'{"text":"other"}'

    with pytest.raises(SecurityViolation, match="nonce"):
        service.accept_webhook(
            Adapter(inbound(text="other")), changed, signed_headers(changed),
            account_id="account-1", remote_ip="203.0.113.7",
        )


def test_body_and_header_limits_run_before_authentication_or_parsing(runtime):
    _, repository = runtime
    order = []
    service, _ = ingress_service(
        repository,
        order=order,
        limits=IngressLimits(max_body_bytes=8, max_header_count=4),
    )
    adapter = Adapter(inbound(), order)

    with pytest.raises(SecurityViolation, match="body size"):
        service.accept_webhook(
            adapter, b"x" * 9, {}, account_id="account-1", remote_ip="203.0.113.7"
        )
    assert order == []
    assert adapter.normalize_calls == 0


@pytest.mark.parametrize(
    ("event", "limits", "message"),
    [
        (inbound(event_key="12345"), IngressLimits(max_identifier_chars=4), "identifier"),
        (inbound(text="12345"), IngressLimits(max_text_chars=4), "text"),
        (
            inbound(metadata={"a": {"b": {"c": 1}}}),
            IngressLimits(max_nesting_depth=2),
            "depth",
        ),
        (
            inbound(attachments=({"content": b"one"}, {"content": b"two"})),
            IngressLimits(max_attachment_count=1),
            "count",
        ),
    ],
)
def test_normalized_input_limits_fail_before_route_or_enqueue(runtime, event, limits, message):
    _, repository = runtime
    service, _ = ingress_service(repository, limits=limits)

    with pytest.raises(SecurityViolation, match=message):
        service.accept_polled_event(event)

    assert repository.list_inbox() == []


def test_duplicate_platform_event_is_one_durable_inbox_item(runtime):
    _, repository = runtime
    first_service, _ = ingress_service(repository)
    second_service, _ = ingress_service(repository)
    body = b'{"text":"hello"}'

    first = first_service.accept_webhook(
        Adapter(inbound()), body, signed_headers(body, nonce="nonce-1"),
        account_id="account-1", remote_ip="203.0.113.7",
    )
    second = second_service.accept_webhook(
        Adapter(inbound()), body, signed_headers(body, nonce="nonce-2"),
        account_id="account-1", remote_ip="203.0.113.7",
    )

    assert second.event_id == first.event_id
    assert len(repository.list_inbox()) == 1
    changed = b'{"text":"other"}'
    with pytest.raises(SecurityViolation, match="nonce"):
        second_service.accept_webhook(
            Adapter(inbound(text="other")), changed,
            signed_headers(changed, nonce="nonce-2"),
            account_id="account-1", remote_ip="203.0.113.7",
        )


def test_polling_cursor_is_committed_only_after_event_is_durable_and_survives_restart(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    repository.upsert_channel_account(
        account_id="account-1", adapter_kind="test", default_profile_id="main", now=NOW
    )
    service, _ = ingress_service(repository)

    receipt = service.accept_polled_event(inbound(), cursor="cursor-42")
    assert service.get_checkpoint("account-1", "polling") is None
    claim = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller-1", lease_duration=timedelta(seconds=30)
    )
    service.commit_checkpoint(
        "account-1", "polling", claim=claim, expected_previous={"cursor": None},
        cursor="cursor-42", processed_event_key=receipt.event_key
    )
    control_plane.close()

    reopened = ControlPlane(tmp_path)
    try:
        resumed = IngressService.get_persisted_checkpoint(
            DurableRuntimeRepository(reopened), "account-1", "polling"
        )
        assert resumed["cursor"] == "cursor-42"
        assert resumed["claim_owner"] is None
    finally:
        reopened.close()


def test_checkpoint_cannot_advance_before_referenced_event_is_durable(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)

    claim = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller-1", lease_duration=timedelta(seconds=30)
    )
    with pytest.raises(StateConflictError, match="before its event is durable"):
        service.commit_checkpoint(
            "account-1",
            "polling",
            claim=claim,
            expected_previous={"cursor": None},
            cursor="cursor-too-early",
            processed_event_key="missing-event",
        )

    assert service.get_checkpoint("account-1", "polling")["cursor"] is None


def test_gateway_resume_checkpoint_is_persistent_and_sequence_cannot_regress(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(
        inbound(), transport_mode="gateway", gateway_session_id="discord-session-1",
        gateway_sequence=41,
    )
    claim = service.claim_checkpoint(
        "account-1", "gateway", owner_id="gateway-1", lease_duration=timedelta(seconds=30)
    )

    service.commit_checkpoint(
        "account-1",
        "gateway",
        claim=claim,
        expected_previous={"gateway_session_id": None, "gateway_sequence": None},
        gateway_session_id="discord-session-1",
        gateway_sequence=41,
        replay_state={"resume_url": "wss://gateway.example.invalid"},
        processed_event_key=receipt.event_key,
    )
    checkpoint = service.get_checkpoint("account-1", "gateway")

    assert checkpoint["gateway_session_id"] == "discord-session-1"
    assert checkpoint["gateway_sequence"] == 41
    assert checkpoint["replay_state"]["resume_url"].startswith("wss://")
    with pytest.raises(ValueError, match="regress"):
        next_claim = service.claim_checkpoint(
            "account-1", "gateway", owner_id="gateway-1", lease_duration=timedelta(seconds=30)
        )
        service.commit_checkpoint(
            "account-1",
            "gateway",
            claim=next_claim,
            expected_previous={"gateway_session_id": "discord-session-1", "gateway_sequence": 41},
            gateway_session_id="discord-session-1",
            gateway_sequence=40,
            processed_event_key=receipt.event_key,
        )


def test_checkpoint_requires_event_proof_expected_state_and_current_owner(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound(), cursor="cursor-1")
    first = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller-1", lease_duration=timedelta(seconds=10)
    )
    with pytest.raises(ValueError, match="processed_event_key"):
        service.commit_checkpoint(
            "account-1", "polling", claim=first,
            expected_previous={"cursor": None}, cursor="cursor-1",
        )
    with pytest.raises(StateConflictError, match="expected"):
        service.commit_checkpoint(
            "account-1", "polling", claim=first,
            expected_previous={"cursor": "wrong"}, cursor="cursor-1",
            processed_event_key=receipt.event_key,
        )


def test_checkpoint_rejects_historical_position_and_stale_owner(runtime):
    _, repository = runtime
    now = [NOW]
    service, _ = ingress_service(repository, now=lambda: now[0])
    old = service.accept_polled_event(inbound(event_key="old"), cursor="cursor-old")
    fresh = service.accept_polled_event(inbound(event_key="fresh"), cursor="cursor-new")
    first = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller-1", lease_duration=timedelta(seconds=10)
    )
    with pytest.raises(StateConflictError, match="position"):
        service.commit_checkpoint(
            "account-1", "polling", claim=first, expected_previous={"cursor": None},
            cursor="cursor-new", processed_event_key=old.event_key,
        )
    now[0] += timedelta(seconds=10)
    second = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller-2", lease_duration=timedelta(seconds=20)
    )
    with pytest.raises(StaleClaimError):
        service.commit_checkpoint(
            "account-1", "polling", claim=first, expected_previous={"cursor": None},
            cursor="cursor-new", processed_event_key=fresh.event_key,
        )
    service.commit_checkpoint(
        "account-1", "polling", claim=second, expected_previous={"cursor": None},
        cursor="cursor-new", processed_event_key=fresh.event_key,
    )


def test_webhook_and_polling_ownership_are_mutually_exclusive(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    service.claim_checkpoint(
        "account-1", "webhook", owner_id="webhook-server", lease_duration=timedelta(seconds=30)
    )
    with pytest.raises(StateConflictError, match="transport"):
        service.claim_checkpoint(
            "account-1", "polling", owner_id="poller", lease_duration=timedelta(seconds=30)
        )


def test_durable_webhook_receipt_claims_transport_before_ack(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    body = b'{"text":"hello"}'

    service.accept_webhook(
        Adapter(inbound()), body, signed_headers(body),
        account_id="account-1", remote_ip="203.0.113.7",
    )

    with pytest.raises(StateConflictError, match="transport"):
        service.claim_checkpoint(
            "account-1", "polling", owner_id="poller", lease_duration=timedelta(seconds=30)
        )


def test_retention_waits_for_live_nonce_receipt_then_redacts_safely(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(
        control_plane, retention_hmac_key=b"task6-retention-hmac-key-at-least-32-bytes"
    )
    repository.upsert_channel_account(
        account_id="account-1", adapter_kind="test", default_profile_id="main", now=NOW
    )
    try:
        service, _ = ingress_service(repository)
        body = b'{"text":"hello"}'
        receipt = service.accept_webhook(
            Adapter(inbound()), body, signed_headers(body),
            account_id="account-1", remote_ip="203.0.113.7",
        )
        claimed = repository.claim_due_inbox(
            "retention-worker", NOW, NOW + timedelta(seconds=30), limit=1
        )[0]
        repository.complete_inbox(claimed.event_id, claimed.claim, NOW)

        repository.apply_retention_batch(
            now=NOW, inbox_before=NOW, outbox_before=NOW,
            audit_before=NOW, limit=10,
        )
        assert control_plane._get_conn().execute(
            "SELECT retained_at FROM inbox_events WHERE event_id = ?", (receipt.event_id,)
        ).fetchone()["retained_at"] is None
        assert repository.get_webhook_nonce_receipt("account-1", "nonce-1") is not None

        repository.apply_retention_batch(
            now=NOW + timedelta(minutes=6), inbox_before=NOW + timedelta(minutes=6),
            outbox_before=NOW + timedelta(minutes=6),
            audit_before=NOW + timedelta(minutes=6), limit=10,
        )
        assert repository.get_webhook_nonce_receipt("account-1", "nonce-1") is None
        assert control_plane._get_conn().execute(
            "SELECT retained_at FROM inbox_events"
        ).fetchone()["retained_at"] is not None
    finally:
        control_plane.close()


def test_gateway_checkpoint_rejects_incomplete_expected_state_and_session_rollback(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    first = service.accept_polled_event(
        inbound(event_key="session-a"), transport_mode="gateway",
        gateway_session_id="session-a", gateway_sequence=1,
    )
    claim = service.claim_checkpoint(
        "account-1", "gateway", owner_id="gateway", lease_duration=timedelta(seconds=30)
    )
    with pytest.raises(ValueError, match="incomplete"):
        service.commit_checkpoint(
            "account-1", "gateway", claim=claim,
            expected_previous={"gateway_sequence": None},
            gateway_session_id="session-a", gateway_sequence=1,
            processed_event_key=first.event_key,
        )
    with pytest.raises(ValueError, match="session.*sequence"):
        service.commit_checkpoint(
            "account-1", "gateway", claim=claim,
            expected_previous={"gateway_session_id": None, "gateway_sequence": None},
            processed_event_key=first.event_key,
        )
    service.commit_checkpoint(
        "account-1", "gateway", claim=claim,
        expected_previous={"gateway_session_id": None, "gateway_sequence": None},
        gateway_session_id="session-a", gateway_sequence=1,
        processed_event_key=first.event_key,
    )
    second = service.accept_polled_event(
        inbound(event_key="session-b"), transport_mode="gateway",
        gateway_session_id="session-b", gateway_sequence=1,
    )
    claim = service.claim_checkpoint(
        "account-1", "gateway", owner_id="gateway", lease_duration=timedelta(seconds=30)
    )
    service.commit_checkpoint(
        "account-1", "gateway", claim=claim,
        expected_previous={"gateway_session_id": "session-a", "gateway_sequence": 1},
        gateway_session_id="session-b", gateway_sequence=1,
        processed_event_key=second.event_key,
    )
    rollback = service.accept_polled_event(
        inbound(event_key="session-a-again"), transport_mode="gateway",
        gateway_session_id="session-a", gateway_sequence=2,
    )
    claim = service.claim_checkpoint(
        "account-1", "gateway", owner_id="gateway", lease_duration=timedelta(seconds=30)
    )
    with pytest.raises(StateConflictError, match="roll back"):
        service.commit_checkpoint(
            "account-1", "gateway", claim=claim,
            expected_previous={"gateway_session_id": "session-b", "gateway_sequence": 1},
            gateway_session_id="session-a", gateway_sequence=2,
            processed_event_key=rollback.event_key,
        )


@pytest.mark.asyncio
async def test_attachments_are_guarded_and_only_managed_references_reach_runner(runtime):
    control_plane, repository = runtime

    class RecordingAttachmentGuard:
        def __init__(self):
            self.uploads = ()

        def ingest(self, uploads):
            self.uploads = tuple(uploads)
            assert self.uploads[0].chunks.read(1024, 0) == b"%PDF-safe"
            assert self.uploads[0].chunks.read(1024, 0) is None
            return (StoredAttachment("managed/attachment-1", 9, NOW + timedelta(days=1)),)

    attachment_guard = RecordingAttachmentGuard()
    service, _ = ingress_service(repository, attachment_guard=attachment_guard)
    receipt = service.accept_polled_event(
        inbound(attachments=({
            "filename": "evidence.pdf",
            "claimed_content_type": "application/pdf",
            "content": b"%PDF-safe",
        },))
    )
    stored = repository.get_inbox(receipt.event_id)
    managed = stored.payload["normalized_event"]["attachments"][0]
    assert managed == {
        "storage_path": "managed/attachment-1",
        "size": 9,
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
    }
    runner = RecordingRunner(control_plane)
    worker = IngressWorker(
        repository, GatewayRouter(repository, now=lambda: NOW), runner,
        worker_id="attachment-worker", lease_duration=timedelta(seconds=30), now=lambda: NOW,
    )
    assert (await worker.run_once()).succeeded == 1
    assert runner.calls[0][0].messages[0]["attachments"] == [managed]


@pytest.mark.asyncio
async def test_worker_dispatches_one_event_to_one_atomic_runtime_turn(runtime):
    control_plane, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())
    runner = RecordingRunner(control_plane)
    worker = IngressWorker(
        repository,
        GatewayRouter(repository, now=lambda: NOW),
        runner,
        worker_id="inbox-worker-1",
        lease_duration=timedelta(seconds=30),
        now=lambda: NOW,
    )

    summary = await worker.run_once()

    stored = repository.get_inbox(receipt.event_id)
    turns = control_plane.list_runtime_turns(runner.calls[0][1]["thread_id"])
    assert summary.claimed == summary.succeeded == 1
    assert stored.state == "succeeded"
    assert len(turns) == 1
    assert turns[0]["source_event_key"] == '["account-1","platform-event-1"]'
    assert runner.calls[0][1]["turn_id"] == turns[0]["turn_id"]


@pytest.mark.asyncio
async def test_restart_recovers_expired_dispatch_claim_and_reuses_existing_turn(runtime):
    control_plane, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())
    crashing = RecordingRunner(control_plane, fail_before_stream=True)
    first = IngressWorker(
        repository,
        GatewayRouter(repository, now=lambda: NOW),
        crashing,
        worker_id="worker-before-crash",
        lease_duration=timedelta(seconds=10),
        now=lambda: NOW,
    )

    first_summary = await first.run_once()
    dispatched = repository.get_inbox(receipt.event_id)
    first_turn = control_plane.list_runtime_turns(dispatched.payload["route"]["thread_id"])[0]
    assert first_summary.failed == 1
    assert dispatched.state == "dispatched"

    recovered_runner = RecordingRunner(control_plane)
    restart_now = NOW + timedelta(seconds=10)
    restarted = IngressWorker(
        repository,
        GatewayRouter(repository, now=lambda: restart_now),
        recovered_runner,
        worker_id="worker-after-restart",
        lease_duration=timedelta(seconds=30),
        now=lambda: restart_now,
    )
    second_summary = await restarted.run_once()

    turns = control_plane.list_runtime_turns(first_turn["thread_id"])
    assert second_summary.succeeded == 1
    assert repository.get_inbox(receipt.event_id).state == "succeeded"
    assert len(turns) == 1
    assert recovered_runner.calls[0][1]["turn_id"] == first_turn["turn_id"]


@pytest.mark.asyncio
async def test_restart_after_completed_agent_turn_only_finishes_inbox(runtime):
    control_plane, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())
    claimed = repository.claim_due_inbox(
        "worker-before-crash", NOW, NOW + timedelta(seconds=10), limit=1
    )[0]
    route = claimed.payload["route"]
    turn = repository.dispatch_inbox_with_turn(
        claimed.event_id,
        claimed.claim,
        thread_id=route["thread_id"],
        session_id=route["session_id"],
        user_input="hello",
        now=NOW,
    )
    control_plane.complete_runtime_turn(turn["turn_id"], status="completed")

    runner = RecordingRunner(control_plane)
    restart_now = NOW + timedelta(seconds=10)
    worker = IngressWorker(
        repository,
        GatewayRouter(repository, now=lambda: restart_now),
        runner,
        worker_id="worker-after-crash",
        now=lambda: restart_now,
    )

    summary = await worker.run_once()

    assert summary.succeeded == 1
    assert repository.get_inbox(receipt.event_id).state == "succeeded"
    assert runner.calls == []
    assert len(control_plane.list_runtime_turns(turn["thread_id"])) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancelled", "silent"])
async def test_worker_retries_cancelled_or_silent_agent_stream(runtime, mode):
    control_plane, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())
    worker = IngressWorker(
        repository,
        GatewayRouter(repository, now=lambda: NOW),
        RecordingRunner(control_plane, mode=mode),
        worker_id="worker-terminal-check",
        now=lambda: NOW,
    )

    summary = await worker.run_once()

    stored = repository.get_inbox(receipt.event_id)
    assert summary.failed == 1
    assert stored.state == "dispatched"
    assert stored.last_error is not None


@pytest.mark.asyncio
async def test_cancelled_turn_retry_uses_a_new_attempt_without_overwriting_terminal(runtime):
    control_plane, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())
    cancelled = IngressWorker(
        repository, GatewayRouter(repository, now=lambda: NOW),
        RecordingRunner(control_plane, mode="cancelled"),
        worker_id="cancelled-worker", now=lambda: NOW,
    )
    assert (await cancelled.run_once()).failed == 1

    completed = IngressWorker(
        repository, GatewayRouter(repository, now=lambda: NOW),
        RecordingRunner(control_plane), worker_id="retry-worker", now=lambda: NOW,
    )
    assert (await completed.run_once()).succeeded == 1

    route = repository.get_inbox(receipt.event_id).payload["route"]
    turns = control_plane.list_runtime_turns(route["thread_id"])
    assert {turn["status"] for turn in turns} == {"cancelled", "completed"}
    assert turns[0]["turn_id"] != turns[1]["turn_id"]
    assert turns[0]["source_event_key"] != turns[1]["source_event_key"]


@pytest.mark.asyncio
async def test_manual_tool_reconciliation_blocks_a_new_agent_attempt(runtime):
    control_plane, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())
    source_event_key = json.dumps(
        [receipt.account_id, receipt.event_key], separators=(",", ":")
    )
    effect = control_plane.claim_tool_effect(
        session_id=repository.get_inbox(receipt.event_id).payload["route"]["session_id"],
        turn_id="turn-before-crash", source_event_key=source_event_key,
        platform_tool_call_id="provider-call", invocation_id="step:1:tool:1",
        tool_name="external_write", arguments={"value": 1},
        idempotency_mode="non_idempotent", owner_id="crashed-worker",
        now=NOW, expires_at=NOW + timedelta(seconds=30),
    )
    control_plane.mark_tool_effect_delivery_unknown(
        effect["tool_call_id"], effect["claim"], now=NOW + timedelta(seconds=1),
        reason="crash after delivery",
    )
    runner = RecordingRunner(control_plane)
    worker = IngressWorker(
        repository, GatewayRouter(repository, now=lambda: NOW + timedelta(seconds=1)),
        runner, worker_id="recovery-worker", now=lambda: NOW + timedelta(seconds=1),
    )

    summary = await worker.run_once()

    assert summary.failed == 1
    assert runner.calls == []


def test_runtime_terminal_event_and_status_are_one_idempotent_commit(runtime):
    control_plane, _ = runtime
    control_plane.create_session("terminal-session")
    control_plane.create_runtime_thread(
        session_id="terminal-session", thread_id="terminal-thread", user_id="user"
    )
    control_plane.start_runtime_turn(
        "terminal-thread", session_id="terminal-session",
        turn_id="terminal-turn", user_input="hello",
    )
    first = control_plane.complete_runtime_turn_with_event(
        thread_id="terminal-thread", turn_id="terminal-turn",
        session_id="terminal-session", event_type="complete",
        payload={"event": "complete"}, status="completed",
        result={"content": "done"},
    )
    replay = control_plane.complete_runtime_turn_with_event(
        thread_id="terminal-thread", turn_id="terminal-turn",
        session_id="terminal-session", event_type="complete",
        payload={"event": "complete"}, status="completed",
        result={"content": "done"},
    )

    assert replay["event_id"] == first["event_id"]
    assert control_plane.list_runtime_turns("terminal-thread")[0]["status"] == "completed"
    terminal_events = [
        event for event in control_plane.list_runtime_events("terminal-thread")
        if event["event_type"] in {"complete", "cancelled", "error"}
    ]
    assert len(terminal_events) == 1


def test_polled_enqueue_requires_live_matching_transport_claim(runtime):
    _, repository = runtime
    now = [NOW]
    service, _ = ingress_service(repository, now=lambda: now[0])

    with pytest.raises((TypeError, ValueError), match="claim"):
        service.accept_polled_event(inbound(), cursor="cursor-1")

    claim = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller", lease_duration=timedelta(seconds=10)
    )
    receipt = service.accept_polled_event(
        inbound(), cursor="cursor-1", claim=claim
    )
    assert repository.get_inbox(receipt.event_id) is not None

    now[0] += timedelta(seconds=10)
    with pytest.raises(StaleClaimError):
        service.accept_polled_event(
            inbound(event_key="stale"), cursor="cursor-2", claim=claim
        )


def test_gateway_enqueue_rejects_polling_claim_mode_mismatch(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    polling_claim = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller", lease_duration=timedelta(seconds=30)
    )

    with pytest.raises(StateConflictError, match="transport"):
        service.accept_polled_event(
            inbound(), transport_mode="gateway", gateway_session_id="session-1",
            gateway_sequence=1, claim=polling_claim,
        )


def test_duplicate_and_quota_rejection_do_not_write_attachments(runtime, tmp_path):
    _, repository = runtime

    class Guard:
        def __init__(self):
            self.ingest_calls = 0

        def ingest(self, uploads, on_staging=None):
            self.ingest_calls += 1
            stored = (StoredAttachment("quarantine/attachment-1", 9, NOW + timedelta(days=1)),)
            if on_staging:
                on_staging(stored)
            return stored

        def rollback(self, stored):
            raise AssertionError("preflight rejection must not need attachment rollback")

    body = b'{"text":"hello"}'
    first, _ = ingress_service(repository)
    first.accept_webhook(
        Adapter(inbound()), body, signed_headers(body, nonce="first"),
        account_id="account-1", remote_ip="203.0.113.7",
    )
    guard = Guard()
    duplicate, _ = ingress_service(repository, attachment_guard=guard)
    duplicate.accept_webhook(
        Adapter(inbound(attachments=({
            "filename": "evidence.pdf", "claimed_content_type": "application/pdf",
            "content": b"%PDF-safe",
        },))), body, signed_headers(body, nonce="second"),
        account_id="account-1", remote_ip="203.0.113.7",
    )
    assert guard.ingest_calls == 0

    control_plane = ControlPlane(tmp_path / "quota-case")
    quota_repository = DurableRuntimeRepository(control_plane)
    quota_repository.upsert_channel_account(
        account_id="account-1", adapter_kind="test", default_profile_id="main", now=NOW
    )
    try:
        quota_guard = Guard()
        rejected, _ = ingress_service(
            quota_repository, attachment_guard=quota_guard,
            quota_snapshot=lambda event: QuotaSnapshot(attachment_bytes=2**21),
        )
        with pytest.raises(SecurityViolation, match="attachment quota"):
            rejected.accept_webhook(
                Adapter(inbound(attachments=({
                    "filename": "evidence.pdf",
                    "claimed_content_type": "application/pdf",
                    "content": b"%PDF-safe",
                },))), body, signed_headers(body),
                account_id="account-1", remote_ip="203.0.113.7",
            )
        assert quota_guard.ingest_calls == 0
    finally:
        control_plane.close()


def test_attachment_staging_rolls_back_db_failure_and_crash_retry(runtime):
    _, repository = runtime

    class StagingGuard:
        def __init__(self):
            self.counter = 0
            self.rolled_back = []

        def ingest(self, uploads, on_staging=None):
            tuple(uploads)
            self.counter += 1
            stored = (StoredAttachment(
                f"quarantine/attachment-{self.counter}", 9, NOW + timedelta(days=1)
            ),)
            if on_staging:
                on_staging(stored)
            return stored

        def rollback(self, stored):
            self.rolled_back.append(tuple(item.storage_path for item in stored))

    guard = StagingGuard()
    service, _ = ingress_service(repository, attachment_guard=guard)
    claim = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller", lease_duration=timedelta(seconds=30)
    )
    original = repository.enqueue_inbox

    def crash_after_storage(*args, **kwargs):
        raise SystemExit("simulated process death")

    repository.enqueue_inbox = crash_after_storage
    event = inbound(attachments=({
        "filename": "evidence.pdf", "claimed_content_type": "application/pdf",
        "content": b"%PDF-safe",
    },))
    with pytest.raises(SystemExit):
        service.accept_polled_event(event, cursor="cursor-1", claim=claim)

    repository.enqueue_inbox = original
    receipt = service.accept_polled_event(event, cursor="cursor-1", claim=claim)

    assert guard.rolled_back == [("quarantine/attachment-1",)]
    assert repository.get_inbox(receipt.event_id).payload["normalized_event"]["attachments"][0][
        "storage_path"
    ] == "quarantine/attachment-2"


@pytest.mark.asyncio
async def test_inbox_cannot_succeed_with_executing_tool_effect(runtime):
    control_plane, repository = runtime
    service, _ = ingress_service(repository)
    claim = service.claim_checkpoint(
        "account-1", "polling", owner_id="poller", lease_duration=timedelta(seconds=30)
    )
    receipt = service.accept_polled_event(inbound(), cursor="cursor-1", claim=claim)

    class RunnerWithOrphanedEffect(RecordingRunner):
        async def run_stream(self, request, *, runtime_turn):
            source_key = request.meta["source_event_key"]
            control_plane.claim_tool_effect(
                session_id=request.session_id, turn_id=runtime_turn["turn_id"],
                source_event_key=source_key, platform_tool_call_id="provider-call",
                invocation_id="step:1:tool:1", tool_name="external_write",
                arguments={"value": 1}, idempotency_mode="non_idempotent",
                owner_id="effect-worker", now=NOW,
                expires_at=NOW + timedelta(seconds=30),
            )
            control_plane.complete_runtime_turn(runtime_turn["turn_id"], status="completed")
            yield SimpleNamespace(event="complete", error=None)

    worker = IngressWorker(
        repository, GatewayRouter(repository, now=lambda: NOW),
        RunnerWithOrphanedEffect(control_plane), worker_id="inbox-worker", now=lambda: NOW,
    )

    assert (await worker.run_once()).failed == 1
    assert repository.get_inbox(receipt.event_id).state == "dispatched"


def test_stale_dispatch_owner_cannot_complete_after_recovery(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())
    first = repository.claim_due_inbox(
        "worker-1", NOW, NOW + timedelta(seconds=10), limit=1
    )[0]
    route = first.payload["route"]
    repository.dispatch_inbox_with_turn(
        first.event_id,
        first.claim,
        thread_id=route["thread_id"],
        session_id=route["session_id"],
        user_input="hello",
        now=NOW,
    )
    second = repository.claim_due_inbox(
        "worker-2",
        NOW + timedelta(seconds=10),
        NOW + timedelta(seconds=40),
        limit=1,
    )[0]

    with pytest.raises(StaleClaimError):
        repository.complete_inbox(receipt.event_id, first.claim, NOW + timedelta(seconds=10))
    repository.complete_inbox(receipt.event_id, second.claim, NOW + timedelta(seconds=11))
