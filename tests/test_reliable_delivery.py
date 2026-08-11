from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.delivery import (
    DeliveryOutcomeUnknown,
    DeliveryWorker,
    LocalSessionDestination,
    PermanentDeliveryError,
    RetryableDeliveryError,
)
from open_agent.durable_runtime.models import OutboxObligation
from open_agent.durable_runtime.repository import DurableRuntimeRepository, StaleClaimError


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)


def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))

    import open_agent.agent_profiles as agent_profiles
    import open_agent.app.runner.manager as chat_manager
    import open_agent.control_plane as control_plane

    agent_profiles._profile_manager = None
    chat_manager._chat_manager = None
    chat_manager._scoped_chat_managers.clear()
    control_plane._control_planes.clear()
    return agent_profiles


@pytest.fixture
async def delivery_runtime(monkeypatch, tmp_path):
    profiles = _isolate_home(monkeypatch, tmp_path)
    profile_manager = profiles.get_agent_profile_manager()
    control_plane = ControlPlane(profile_manager.get_agent_home(None))
    repository = DurableRuntimeRepository(control_plane)

    from open_agent.app.runner.manager import get_chat_manager

    chat_manager = get_chat_manager()
    await chat_manager.create_chat(
        name="Parent", user_id="default", channel="web", session_id="session-parent"
    )
    try:
        yield repository, chat_manager
    finally:
        control_plane.close()


def _obligation(
    obligation_id: str = "delivery-1",
    *,
    destination: str = "local_session",
) -> OutboxObligation:
    return OutboxObligation(
        obligation_id=obligation_id,
        idempotency_key=f"agent-task:{obligation_id}:result",
        destination=destination,
        payload={
            "session_id": "session-parent",
            "profile_id": "writer",
            "task_id": "task-1",
            "status": "completed",
            "source_session_id": "session-child",
            "content": "Writer result",
        },
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_local_destination_inserts_parent_result_once(delivery_runtime):
    repository, chat_manager = delivery_runtime
    stored = repository.enqueue_outbox(_obligation())
    claimed = repository.claim_due_outbox("worker", NOW, NOW + timedelta(seconds=30))[0]
    destination = LocalSessionDestination(repository, clock=lambda: NOW)

    acknowledgement = await destination.deliver(claimed, claimed.claim)
    repository.ack_outbox(stored.obligation_id, claimed.claim, acknowledgement, NOW)

    messages = chat_manager.get_messages("session-parent")
    chat = await chat_manager.repo.find_by_session_id("session-parent")
    assert [(message.id, message.content) for message in messages] == [
        (stored.obligation_id, "Writer result")
    ]
    assert chat.meta["agent_task_results"] == [
        {
            "delivery_obligation_id": stored.obligation_id,
            "profile_id": "writer",
            "session_id": "session-child",
            "status": "completed",
            "task_id": "task-1",
        }
    ]


@pytest.mark.asyncio
async def test_duplicate_producer_calls_create_one_obligation(monkeypatch, tmp_path):
    profiles = _isolate_home(monkeypatch, tmp_path)
    profiles.get_agent_profile_manager().create_profile({"id": "writer", "name": "Writer"})

    from open_agent.agent_control import _backfill_parent_session
    from open_agent.app.runner.manager import get_chat_manager

    parent_manager = get_chat_manager()
    await parent_manager.create_chat(
        name="Parent", user_id="default", channel="web", session_id="session-parent"
    )
    task = {
        "task_id": "task-1",
        "profile_id": "writer",
        "session_id": "session-child",
        "parent_session_id": "session-parent",
        "status": "completed",
        "result": "Writer result",
        "error": None,
        "events": [],
        "instruction": "Write",
        "metadata": {"parent_profile_id": "main"},
    }

    await _backfill_parent_session(task)
    task["metadata"].pop("parent_backfilled", None)
    await _backfill_parent_session(task)

    agent_control = __import__("open_agent.agent_control", fromlist=["_task_control_plane"])
    control_plane = agent_control._task_control_plane()
    repository = DurableRuntimeRepository(control_plane)
    assert len(repository.list_outbox()) == 1
    assert len(parent_manager.get_messages("session-parent")) == 1


@pytest.mark.asyncio
async def test_crash_after_insert_before_ack_reconciles_without_duplicate(delivery_runtime):
    repository, chat_manager = delivery_runtime
    repository.enqueue_outbox(_obligation())
    first = repository.claim_due_outbox("worker-a", NOW, NOW + timedelta(seconds=10))[0]
    current_time = [NOW]
    destination = LocalSessionDestination(repository, clock=lambda: current_time[0])

    await destination.deliver(first, first.claim)  # process crashes before outbox ack
    current_time[0] = NOW + timedelta(seconds=10)
    worker = DeliveryWorker(
        repository,
        {"local_session": destination},
        owner_id="worker-b",
        lease_duration=timedelta(seconds=30),
        clock=lambda: current_time[0],
    )
    processed = await worker.run_once(current_time[0])

    stored = repository.get_outbox("delivery-1")
    chat = await chat_manager.repo.find_by_session_id("session-parent")
    assert processed == 1
    assert stored.state == "acknowledged"
    assert len(chat_manager.get_messages("session-parent")) == 1
    assert len(chat.meta["agent_task_results"]) == 1


class _FailingDestination:
    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    async def deliver(self, obligation, claim):
        self.calls += 1
        raise self.error


class _RecordingDestination:
    def __init__(self):
        self.claim = None

    async def deliver(self, obligation, claim):
        self.claim = claim
        return {"message_id": obligation.obligation_id}


class _SlowDestination:
    async def deliver(self, obligation, claim):
        await asyncio.sleep(0.05)
        return {"message_id": obligation.obligation_id}


@pytest.mark.asyncio
async def test_retryable_failure_uses_bounded_backoff(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation())
    destination = _FailingDestination(RetryableDeliveryError("chat store busy"))
    worker = DeliveryWorker(
        repository,
        {"local_session": destination},
        owner_id="worker",
        retry_base=timedelta(seconds=5),
        retry_cap=timedelta(seconds=12),
        clock=lambda: NOW,
    )

    assert await worker.run_once(NOW) == 1
    stored = repository.get_outbox("delivery-1")
    assert stored.state == "retry_wait"
    assert stored.next_attempt_at == NOW + timedelta(seconds=5)
    assert stored.last_error == "chat store busy"


@pytest.mark.asyncio
async def test_ambiguous_outcome_is_not_automatically_retried(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation())
    destination = _FailingDestination(DeliveryOutcomeUnknown("timed out after send"))
    worker = DeliveryWorker(
        repository,
        {"local_session": destination},
        owner_id="worker",
        clock=lambda: NOW,
    )

    await worker.run_once(NOW)

    stored = repository.get_outbox("delivery-1")
    assert stored.state == "delivery_unknown"
    assert stored.last_error == "timed out after send"
    assert await worker.run_once(NOW + timedelta(hours=1)) == 0
    assert destination.calls == 1


@pytest.mark.asyncio
async def test_delivery_deadline_is_classified_as_unknown(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation())
    worker = DeliveryWorker(
        repository,
        {"local_session": _SlowDestination()},
        owner_id="worker",
        delivery_timeout=0.001,
        clock=lambda: NOW,
    )

    await worker.run_once(NOW)

    stored = repository.get_outbox("delivery-1")
    assert stored.state == "delivery_unknown"
    assert "deadline" in stored.last_error


@pytest.mark.asyncio
async def test_worker_renews_claim_before_destination_call(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation())
    destination = _RecordingDestination()
    worker = DeliveryWorker(
        repository,
        {"local_session": destination},
        owner_id="worker",
        lease_duration=timedelta(seconds=45),
        clock=lambda: NOW,
    )

    await worker.run_once(NOW)

    assert destination.claim.expires_at == NOW + timedelta(seconds=45)
    assert repository.get_outbox("delivery-1").state == "acknowledged"


@pytest.mark.asyncio
async def test_local_worker_does_not_claim_unconfigured_destinations(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation("external-1", destination="future_adapter"))
    repository.enqueue_outbox(_obligation("delivery-1"))
    destination = _RecordingDestination()
    worker = DeliveryWorker(
        repository,
        {"local_session": destination},
        owner_id="worker",
        clock=lambda: NOW,
    )

    assert await worker.run_once(NOW) == 1
    assert repository.get_outbox("delivery-1").state == "acknowledged"
    assert repository.get_outbox("external-1").state == "pending"


@pytest.mark.asyncio
async def test_each_batch_item_gets_a_fresh_lease(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation("delivery-1"))
    repository.enqueue_outbox(_obligation("delivery-2"))
    current_time = [NOW]
    expiries = []

    class AdvancingDestination:
        async def deliver(self, obligation, claim):
            expiries.append(claim.expires_at)
            current_time[0] += timedelta(seconds=20)
            return {"message_id": obligation.obligation_id}

    worker = DeliveryWorker(
        repository,
        {"local_session": AdvancingDestination()},
        owner_id="worker",
        batch_size=2,
        clock=lambda: current_time[0],
    )

    assert await worker.run_once(NOW) == 2
    assert expiries == [
        NOW + timedelta(seconds=30),
        NOW + timedelta(seconds=50),
    ]


@pytest.mark.asyncio
async def test_failed_message_write_cannot_be_reconciled_from_memory(
    delivery_runtime, monkeypatch
):
    repository, chat_manager = delivery_runtime
    repository.enqueue_outbox(_obligation())
    current_time = [NOW]
    destination = LocalSessionDestination(repository, clock=lambda: current_time[0])
    original_add = chat_manager.message_repo.add_message
    attempts = 0

    def flaky_add(session_id, message):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("sqlite busy")
        return original_add(session_id, message)

    monkeypatch.setattr(chat_manager.message_repo, "add_message", flaky_add)
    worker = DeliveryWorker(
        repository,
        {"local_session": destination},
        owner_id="worker",
        retry_base=timedelta(seconds=1),
        clock=lambda: current_time[0],
    )

    await worker.run_once(NOW)
    assert chat_manager.get_messages("session-parent") == []
    assert repository.get_outbox("delivery-1").state == "retry_wait"

    current_time[0] += timedelta(seconds=1)
    await worker.run_once(current_time[0])

    assert repository.get_outbox("delivery-1").state == "acknowledged"
    assert [
        message.id
        for message in chat_manager.message_repo.list_messages("session-parent")
    ] == ["delivery-1"]


@pytest.mark.asyncio
async def test_permanent_failure_is_dead_lettered(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation())
    worker = DeliveryWorker(
        repository,
        {"local_session": _FailingDestination(PermanentDeliveryError("invalid payload"))},
        owner_id="worker",
        clock=lambda: NOW,
    )

    await worker.run_once(NOW)

    stored = repository.get_outbox("delivery-1")
    assert stored.state == "dead_letter"
    assert stored.last_error == "invalid payload"


@pytest.mark.asyncio
async def test_retry_exhaustion_is_dead_lettered(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation())
    destination = _FailingDestination(RetryableDeliveryError("still unavailable"))
    current_time = [NOW]
    worker = DeliveryWorker(
        repository,
        {"local_session": destination},
        owner_id="worker",
        max_attempts=2,
        retry_base=timedelta(seconds=1),
        clock=lambda: current_time[0],
    )

    await worker.run_once(NOW)
    current_time[0] = NOW + timedelta(seconds=1)
    await worker.run_once(NOW + timedelta(seconds=1))

    assert repository.get_outbox("delivery-1").state == "dead_letter"
    assert destination.calls == 2


@pytest.mark.asyncio
async def test_manual_resend_creates_new_obligation_and_audit(delivery_runtime):
    repository, _ = delivery_runtime
    repository.enqueue_outbox(_obligation())
    claimed = repository.claim_due_outbox("worker", NOW, NOW + timedelta(seconds=30))[0]
    repository.mark_delivery_unknown(
        claimed.obligation_id, claimed.claim, "ambiguous", NOW
    )
    worker = DeliveryWorker(repository, {}, owner_id="worker")

    resent = worker.manual_resend(
        "delivery-1", actor_id="operator-7", now=NOW + timedelta(minutes=1), resend_id="resend-1"
    )

    assert resent.obligation_id == "resend-1"
    assert resent.idempotency_key == "manual-resend:delivery-1:resend-1"
    assert repository.get_outbox("delivery-1").state == "delivery_unknown"
    assert repository.list_audit_events("outbox", "delivery-1") == [
        {
            "audit_id": "audit:resend-1",
            "entity_kind": "outbox",
            "entity_id": "delivery-1",
            "action": "manual_resend",
            "actor_id": "operator-7",
            "payload": {"resend_obligation_id": "resend-1"},
            "created_at": NOW + timedelta(minutes=1),
        }
    ]


@pytest.mark.asyncio
async def test_lease_loss_is_detected_before_local_side_effect(delivery_runtime):
    repository, chat_manager = delivery_runtime
    repository.enqueue_outbox(_obligation())
    claimed = repository.claim_due_outbox("worker", NOW, NOW + timedelta(seconds=5))[0]
    destination = LocalSessionDestination(
        repository, clock=lambda: NOW + timedelta(seconds=5)
    )

    with pytest.raises(StaleClaimError):
        await destination.deliver(claimed, claimed.claim)

    chat = await chat_manager.repo.find_by_session_id("session-parent")
    assert chat_manager.get_messages("session-parent") == []
    assert chat.meta.get("agent_task_results", []) == []
