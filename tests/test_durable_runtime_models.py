"""Contract tests for immutable durable-runtime records and lease helpers."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from open_agent.durable_runtime.leases import lease_is_valid, next_backoff
from open_agent.durable_runtime.models import (
    ClaimToken,
    GoalIteration,
    InboxEvent,
    OutboxObligation,
    SchedulerRun,
    to_json_value,
)


UTC_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def test_claim_token_is_frozen_and_requires_an_aware_expiry() -> None:
    """Changing a fencing generation would allow a stale worker to win."""
    token = ClaimToken("worker-a", 1, UTC_NOW + timedelta(minutes=1))

    with pytest.raises(FrozenInstanceError):
        token.generation = 2  # type: ignore[misc]

    with pytest.raises(ValueError, match="timezone-aware"):
        ClaimToken("worker-a", 1, UTC_NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        (InboxEvent, {"event_id": "inbox-1", "event_key": "telegram:1", "account_id": "acct", "conversation_id": "chat", "payload": {}}),
        (OutboxObligation, {"obligation_id": "outbox-1", "idempotency_key": "reply:1", "destination": "chat", "payload": {}}),
        (SchedulerRun, {"run_id": "run-1", "job_id": "job-1", "scheduled_at": UTC_NOW}),
        (GoalIteration, {"iteration_id": "iteration-1", "goal_id": "goal-1", "sequence": 1}),
    ],
)
def test_runtime_records_are_frozen(factory: object, kwargs: dict[str, object]) -> None:
    """Persisted records must not be mutated outside repository transitions."""
    record = factory(created_at=UTC_NOW, updated_at=UTC_NOW, **kwargs)  # type: ignore[operator]

    with pytest.raises(FrozenInstanceError):
        record.state = "failed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        (InboxEvent, {"event_id": "inbox-1", "event_key": "event", "account_id": "acct", "conversation_id": "chat", "payload": {}, "state": "completed"}),
        (OutboxObligation, {"obligation_id": "outbox-1", "idempotency_key": "key", "destination": "chat", "payload": {}, "state": "sent"}),
        (SchedulerRun, {"run_id": "run-1", "job_id": "job-1", "scheduled_at": UTC_NOW, "state": "claimed"}),
        (GoalIteration, {"iteration_id": "iteration-1", "goal_id": "goal-1", "sequence": 1, "state": "paused"}),
    ],
)
def test_runtime_records_reject_invalid_states(factory: object, kwargs: dict[str, object]) -> None:
    """Invalid state strings must not enter durable storage."""
    with pytest.raises(ValueError, match="invalid state"):
        factory(created_at=UTC_NOW, updated_at=UTC_NOW, **kwargs)  # type: ignore[operator]


def test_runtime_records_reject_naive_timestamps() -> None:
    """Naive timestamps make cross-worker ordering ambiguous."""
    with pytest.raises(ValueError, match="timezone-aware"):
        OutboxObligation(
            obligation_id="outbox-1",
            idempotency_key="reply:1",
            destination="chat",
            payload={},
            created_at=UTC_NOW.replace(tzinfo=None),
            updated_at=UTC_NOW,
        )


def test_payloads_are_detached_from_nested_mutable_input() -> None:
    """A later caller mutation must not rewrite an immutable durable record."""
    original_payload = {"messages": [{"text": "first"}]}
    event = InboxEvent(
        event_id="inbox-1",
        event_key="telegram:1",
        account_id="acct",
        conversation_id="chat",
        payload=original_payload,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    original_payload["messages"][0]["text"] = "rewritten"

    assert event.payload["messages"][0]["text"] == "first"


def test_to_json_value_recursively_thaws_an_immutable_payload() -> None:
    """Repositories can serialize immutable nested payloads without sharing them."""
    event = InboxEvent(
        event_id="inbox-1",
        event_key="telegram:1",
        account_id="acct",
        conversation_id="chat",
        payload={"messages": [{"text": "first"}]},
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )

    assert to_json_value(event.payload) == {"messages": [{"text": "first"}]}


@pytest.mark.parametrize("invalid_value", [True, 1.5])
def test_integer_contract_fields_reject_booleans_and_fractions(invalid_value: object) -> None:
    """Fencing generations and retries must stay integral for durable ordering."""
    with pytest.raises(ValueError, match="integer"):
        ClaimToken("worker-a", invalid_value, UTC_NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="integer"):
        next_backoff(invalid_value, 2.0, 30.0, 0.0)  # type: ignore[arg-type]


def test_zero_jitter_backoff_is_deterministic() -> None:
    """A disabled jitter option produces the unmodified exponential delay."""
    assert next_backoff(3, base_seconds=2.0, cap_seconds=60.0, jitter=0.0) == 16.0


def test_backoff_never_exceeds_cap_after_jitter() -> None:
    """A random high jitter draw cannot delay a retry beyond its configured cap."""
    assert next_backoff(10, 2.0, 30.0, 0.5, random_source=lambda: 1.0) == 30.0


def test_backoff_rejects_non_zero_jitter_without_an_injected_random_source() -> None:
    """Retry timing must not depend on hidden process-global random state."""
    with pytest.raises(ValueError, match="random_source"):
        next_backoff(1, 2.0, 30.0, 0.25)


def test_lease_is_invalid_at_expiry_and_valid_before_expiry() -> None:
    """An expiry boundary must prevent a stale claimant from issuing a side effect."""
    token = ClaimToken("worker-a", 3, UTC_NOW + timedelta(seconds=30))

    assert lease_is_valid(token, UTC_NOW + timedelta(seconds=29)) is True
    assert lease_is_valid(token, UTC_NOW + timedelta(seconds=30)) is False
