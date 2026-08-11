from __future__ import annotations

import hashlib
import hmac
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
from open_agent.gateway.ingress import IngressService, IngressWorker
from open_agent.gateway.router import GatewayRouter
from open_agent.gateway.security import (
    HierarchicalIngressLimiter,
    IngressGuard,
    LimitRule,
    QuotaSnapshot,
    ResourceQuotaPolicy,
    SecurityViolation,
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
    def __init__(self, *, fail_before_stream: bool = False) -> None:
        self.calls = []
        self.fail_before_stream = fail_before_stream

    async def run_stream(self, request, *, runtime_turn):
        self.calls.append((request, runtime_turn))
        if self.fail_before_stream:
            raise RuntimeError("simulated crash before Agent execution")
        yield SimpleNamespace(event="complete", error=None)


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


def ingress_service(repository, *, order=None, now=lambda: NOW):
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
        quota_snapshot=lambda event: QuotaSnapshot(attachment_bytes=0),
        now=now,
    )
    return service, ledger


def test_webhook_authenticates_raw_bytes_then_admits_quota_then_enqueues_before_ack(runtime):
    _, repository = runtime
    order: list[str] = []
    service, ledger = ingress_service(repository, order=order)
    adapter = Adapter(inbound(), order)
    original_enqueue = repository.enqueue_inbox

    def recording_enqueue(event):
        order.append("enqueue")
        return original_enqueue(event)

    repository.enqueue_inbox = recording_enqueue
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
    repository.enqueue_inbox = lambda event: (_ for _ in ()).throw(OSError("disk full"))
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


def test_polling_cursor_is_committed_only_after_event_is_durable_and_survives_restart(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    repository.upsert_channel_account(
        account_id="account-1", adapter_kind="test", default_profile_id="main", now=NOW
    )
    service, _ = ingress_service(repository)

    receipt = service.accept_polled_event(inbound())
    assert service.get_checkpoint("account-1", "polling") is None
    service.commit_checkpoint(
        "account-1", "polling", cursor="cursor-42", processed_event_key=receipt.event_key
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

    with pytest.raises(StateConflictError, match="before its event is durable"):
        service.commit_checkpoint(
            "account-1",
            "polling",
            cursor="cursor-too-early",
            processed_event_key="missing-event",
        )

    assert service.get_checkpoint("account-1", "polling") is None


def test_gateway_resume_checkpoint_is_persistent_and_sequence_cannot_regress(runtime):
    _, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())

    service.commit_checkpoint(
        "account-1",
        "gateway",
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
        service.commit_checkpoint(
            "account-1",
            "gateway",
            gateway_session_id="discord-session-1",
            gateway_sequence=40,
            processed_event_key=receipt.event_key,
        )


@pytest.mark.asyncio
async def test_worker_dispatches_one_event_to_one_atomic_runtime_turn(runtime):
    control_plane, repository = runtime
    service, _ = ingress_service(repository)
    receipt = service.accept_polled_event(inbound())
    runner = RecordingRunner()
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
    crashing = RecordingRunner(fail_before_stream=True)
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

    recovered_runner = RecordingRunner()
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

    runner = RecordingRunner()
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
