"""Immutable records shared by durable-runtime repositories and workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Literal, Mapping, TypeAlias


InboxState: TypeAlias = Literal[
    "pending", "claimed", "dispatched", "succeeded", "retry_wait", "dead_letter"
]
OutboxState: TypeAlias = Literal[
    "pending", "claimed", "acknowledged", "retry_wait", "dead_letter", "delivery_unknown"
]
SchedulerRunState: TypeAlias = Literal[
    "pending", "running", "completed", "retry_wait", "failed", "cancelled", "skipped"
]
GoalIterationState: TypeAlias = Literal[
    "pending", "running", "judging", "completed", "failed", "cancelled"
]

_INBOX_STATES = frozenset(InboxState.__args__)
_OUTBOX_STATES = frozenset(OutboxState.__args__)
_SCHEDULER_RUN_STATES = frozenset(SchedulerRunState.__args__)
_GOAL_ITERATION_STATES = frozenset(GoalIterationState.__args__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_state(value: str, allowed: frozenset[str]) -> None:
    if value not in allowed:
        raise ValueError(f"invalid state: {value}")


def _freeze_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _freeze_value(value) for key, value in payload.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_payload(value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value


def to_json_value(value: Any) -> Any:
    """Recursively convert an immutable payload into JSON-compatible containers."""
    if isinstance(value, Mapping):
        return {key: to_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [to_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ClaimToken:
    """A fencing token proving the caller owns an unexpired runtime claim."""

    owner_id: str
    generation: int
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.owner_id, "owner_id")
        _require_integer(self.generation, "generation")
        if self.generation < 1:
            raise ValueError("generation must be at least 1")
        _require_aware(self.expires_at, "expires_at")


@dataclass(frozen=True, slots=True)
class InboxEvent:
    """A normalized inbound event awaiting or completing durable dispatch."""

    event_id: str
    event_key: str
    account_id: str
    conversation_id: str
    payload: Mapping[str, Any]
    state: InboxState = "pending"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    claim: ClaimToken | None = None
    attempt: int = 0
    last_error: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "event_key", "account_id", "conversation_id"):
            _require_identifier(getattr(self, name), name)
        _require_state(self.state, _INBOX_STATES)
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        _require_integer(self.attempt, "attempt")
        if self.attempt < 0:
            raise ValueError("attempt must not be negative")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))


@dataclass(frozen=True, slots=True)
class OutboxObligation:
    """A durable, idempotent request to deliver a normalized payload."""

    obligation_id: str
    idempotency_key: str
    destination: str
    payload: Mapping[str, Any]
    state: OutboxState = "pending"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    next_attempt_at: datetime | None = None
    claim: ClaimToken | None = None
    attempt: int = 0
    last_error: str | None = None
    acknowledgement: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("obligation_id", "idempotency_key", "destination"):
            _require_identifier(getattr(self, name), name)
        _require_state(self.state, _OUTBOX_STATES)
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.next_attempt_at is not None:
            _require_aware(self.next_attempt_at, "next_attempt_at")
        _require_integer(self.attempt, "attempt")
        if self.attempt < 0:
            raise ValueError("attempt must not be negative")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))
        if self.acknowledgement is not None:
            object.__setattr__(self, "acknowledgement", _freeze_payload(self.acknowledgement))


@dataclass(frozen=True, slots=True)
class SchedulerRun:
    """One durable occurrence of a scheduler job."""

    run_id: str
    job_id: str
    scheduled_at: datetime
    state: SchedulerRunState = "pending"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    claim: ClaimToken | None = None
    attempt: int = 0
    next_attempt_at: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.run_id, "run_id")
        _require_identifier(self.job_id, "job_id")
        _require_state(self.state, _SCHEDULER_RUN_STATES)
        for name in ("scheduled_at", "created_at", "updated_at"):
            _require_aware(getattr(self, name), name)
        if self.next_attempt_at is not None:
            _require_aware(self.next_attempt_at, "next_attempt_at")
        _require_integer(self.attempt, "attempt")
        if self.attempt < 0:
            raise ValueError("attempt must not be negative")


@dataclass(frozen=True, slots=True)
class GoalIteration:
    """One immutable execution-and-judgement iteration for a durable goal."""

    iteration_id: str
    goal_id: str
    sequence: int
    state: GoalIterationState = "pending"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    claim: ClaimToken | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.iteration_id, "iteration_id")
        _require_identifier(self.goal_id, "goal_id")
        _require_integer(self.sequence, "sequence")
        if self.sequence < 1:
            raise ValueError("sequence must be at least 1")
        _require_state(self.state, _GOAL_ITERATION_STATES)
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
