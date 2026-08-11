"""Crash-safe delivery of durable outbox obligations."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, Callable, Protocol

from open_agent.agent_profiles import MAIN_AGENT_ID
from open_agent.app.runner.manager import get_chat_manager
from open_agent.app.runner.models import Message

from .leases import next_backoff
from .models import ClaimToken, OutboxObligation
from .repository import DurableRuntimeRepository, StaleClaimError


LOCAL_SESSION_DESTINATION = "local_session"


class RetryableDeliveryError(RuntimeError):
    """The delivery did not occur and may be retried safely."""


class PermanentDeliveryError(RuntimeError):
    """The delivery cannot succeed without changing its payload or destination."""


class DeliveryOutcomeUnknown(RuntimeError):
    """The side effect may have happened, so automatic retry is unsafe."""


class DeliveryDestination(Protocol):
    """A fenced destination capable of delivering one outbox obligation."""

    async def deliver(
        self, obligation: OutboxObligation, claim: ClaimToken
    ) -> Mapping[str, Any]: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PermanentDeliveryError(f"payload.{name} must be a non-empty string")
    return value


class LocalSessionDestination:
    """Idempotently inserts an outbox result into a local parent session."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self._clock = clock

    def _fence(self, obligation_id: str, claim: ClaimToken) -> None:
        now = self._clock()
        if claim.expires_at <= now:
            raise StaleClaimError(f"expired outbox claim: {obligation_id}")
        self.repository.renew_claim(
            "outbox", obligation_id, claim, now, claim.expires_at
        )

    async def deliver(
        self, obligation: OutboxObligation, claim: ClaimToken
    ) -> Mapping[str, Any]:
        if obligation.destination != LOCAL_SESSION_DESTINATION:
            raise PermanentDeliveryError(
                f"unsupported local destination: {obligation.destination}"
            )
        payload = obligation.payload
        session_id = _required_text(payload, "session_id")
        content = _required_text(payload, "content")
        task_id = _required_text(payload, "task_id")
        profile_id = _required_text(payload, "profile_id")
        status = _required_text(payload, "status")
        if status not in {"completed", "failed", "cancelled"}:
            raise PermanentDeliveryError("payload.status must be terminal")
        source_session_id = _required_text(payload, "source_session_id")
        parent_profile_id = payload.get("parent_profile_id")
        if parent_profile_id is not None and not isinstance(parent_profile_id, str):
            raise PermanentDeliveryError("payload.parent_profile_id must be a string")
        parent_key = (
            None
            if not parent_profile_id or parent_profile_id == MAIN_AGENT_ID
            else parent_profile_id
        )
        manager = get_chat_manager(parent_key)
        chat = await manager.repo.find_by_session_id(session_id)
        if chat is None:
            raise RetryableDeliveryError(f"parent session is unavailable: {session_id}")

        persisted_messages = manager.message_repo.list_messages(session_id)
        reconciled = any(
            message.id == obligation.obligation_id for message in persisted_messages
        )
        if not reconciled:
            self._fence(obligation.obligation_id, claim)
            manager.message_repo.add_message(
                session_id,
                Message(
                    id=obligation.obligation_id,
                    role="assistant",
                    content=content,
                    timestamp=obligation.created_at,
                ),
            )
        messages = manager.get_messages(session_id)
        if not any(message.id == obligation.obligation_id for message in messages):
            messages.append(
                Message(
                    id=obligation.obligation_id,
                    role="assistant",
                    content=content,
                    timestamp=obligation.created_at,
                )
            )

        result = {
            "delivery_obligation_id": obligation.obligation_id,
            "profile_id": profile_id,
            "session_id": source_session_id,
            "status": status,
            "task_id": task_id,
        }
        existing_results = list(chat.meta.get("agent_task_results", []))
        if not any(
            isinstance(item, Mapping)
            and item.get("delivery_obligation_id") == obligation.obligation_id
            for item in existing_results
        ):
            self._fence(obligation.obligation_id, claim)
            updated_chat = chat.model_copy(
                update={"meta": {**chat.meta, "agent_task_results": [*existing_results, result]}}
            )
            await manager.update_chat(updated_chat)

        return {
            "message_id": obligation.obligation_id,
            "session_id": session_id,
            "reconciled": reconciled,
        }


class DeliveryWorker:
    """Claims, fences, delivers, and settles due outbox obligations."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        destinations: Mapping[str, DeliveryDestination],
        *,
        owner_id: str,
        lease_duration: timedelta = timedelta(seconds=30),
        delivery_timeout: float = 20.0,
        retry_base: timedelta = timedelta(seconds=5),
        retry_cap: timedelta = timedelta(minutes=5),
        max_attempts: int = 5,
        batch_size: int = 10,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id must be a non-empty string")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if (
            isinstance(delivery_timeout, bool)
            or not isinstance(delivery_timeout, (int, float))
            or delivery_timeout <= 0
        ):
            raise ValueError("delivery_timeout must be positive")
        if delivery_timeout >= lease_duration.total_seconds():
            raise ValueError("delivery_timeout must be shorter than the lease")
        if retry_base <= timedelta(0) or retry_cap <= timedelta(0):
            raise ValueError("retry delays must be positive")
        if retry_cap < retry_base:
            raise ValueError("retry_cap must be at least retry_base")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or not 1 <= batch_size <= 1000
        ):
            raise ValueError("batch_size must be between 1 and 1000")
        self.repository = repository
        self.destinations = dict(destinations)
        self.owner_id = owner_id
        self.lease_duration = lease_duration
        self.delivery_timeout = delivery_timeout
        self.retry_base = retry_base
        self.retry_cap = retry_cap
        self.max_attempts = max_attempts
        self.batch_size = batch_size
        self._clock = clock
        self._monotonic = monotonic_clock

    def _retry_at(self, obligation: OutboxObligation, now: datetime) -> datetime:
        delay_seconds = next_backoff(
            max(0, obligation.attempt - 1),
            self.retry_base.total_seconds(),
            self.retry_cap.total_seconds(),
            0.0,
        )
        return now + timedelta(seconds=delay_seconds)

    async def run_once(self, now: datetime) -> int:
        started = self._monotonic()

        def current_time() -> datetime:
            if self._clock is not None:
                return self._clock()
            return now + timedelta(seconds=self._monotonic() - started)

        processed = 0
        for _ in range(self.batch_size):
            claim_now = current_time()
            claims = self.repository.claim_due_outbox(
                self.owner_id,
                claim_now,
                claim_now + self.lease_duration,
                limit=1,
                destinations=self.destinations,
            )
            if not claims:
                break
            obligation = claims[0]
            processed += 1
            claim = obligation.claim
            if claim is None:
                continue
            try:
                renewal_now = current_time()
                claim = self.repository.renew_claim(
                    "outbox",
                    obligation.obligation_id,
                    claim,
                    renewal_now,
                    renewal_now + self.lease_duration,
                )
                destination = self.destinations.get(obligation.destination)
                if destination is None:
                    raise PermanentDeliveryError(
                        f"unsupported destination: {obligation.destination}"
                    )
                acknowledgement = await asyncio.wait_for(
                    destination.deliver(obligation, claim),
                    timeout=self.delivery_timeout,
                )
                settlement_now = current_time()
                self.repository.ack_outbox(
                    obligation.obligation_id, claim, acknowledgement, settlement_now
                )
            except StaleClaimError:
                continue
            except (DeliveryOutcomeUnknown, asyncio.TimeoutError) as exc:
                error = str(exc) or "delivery deadline expired with an unknown outcome"
                try:
                    self.repository.mark_delivery_unknown(
                        obligation.obligation_id, claim, error, current_time()
                    )
                except StaleClaimError:
                    continue
            except PermanentDeliveryError as exc:
                try:
                    settlement_now = current_time()
                    self.repository.retry_outbox(
                        obligation.obligation_id,
                        claim,
                        str(exc),
                        settlement_now,
                        settlement_now,
                        dead_letter=True,
                    )
                except StaleClaimError:
                    continue
            except Exception as exc:
                exhausted = obligation.attempt >= self.max_attempts
                try:
                    settlement_now = current_time()
                    self.repository.retry_outbox(
                        obligation.obligation_id,
                        claim,
                        str(exc),
                        self._retry_at(obligation, settlement_now),
                        settlement_now,
                        dead_letter=exhausted,
                    )
                except StaleClaimError:
                    continue
        return processed

    def manual_resend(
        self,
        obligation_id: str,
        *,
        actor_id: str,
        now: datetime,
        resend_id: str | None = None,
    ) -> OutboxObligation:
        source = self.repository.get_outbox(obligation_id)
        if source is None:
            raise ValueError(f"unknown outbox obligation: {obligation_id}")
        new_id = resend_id or f"delivery-{uuid.uuid4().hex}"
        resend = OutboxObligation(
            obligation_id=new_id,
            idempotency_key=f"manual-resend:{obligation_id}:{new_id}",
            destination=source.destination,
            payload=source.payload,
            created_at=now,
            updated_at=now,
        )
        return self.repository.manual_resend_outbox(
            obligation_id, resend, actor_id=actor_id, now=now
        )


def parent_session_result_obligation(
    task: Mapping[str, Any],
    *,
    content: str,
    now: datetime | None = None,
) -> OutboxObligation:
    """Build the stable local-session obligation for one terminal agent task."""
    timestamp = now or _utc_now()
    task_id = _required_text(task, "task_id")
    obligation_id = f"delivery:agent-task:{task_id}"
    return OutboxObligation(
        obligation_id=obligation_id,
        idempotency_key=f"agent-task:{task_id}:result",
        destination=LOCAL_SESSION_DESTINATION,
        payload={
            "session_id": _required_text(task, "parent_session_id"),
            "parent_profile_id": task.get("metadata", {}).get("parent_profile_id"),
            "profile_id": _required_text(task, "profile_id"),
            "task_id": task_id,
            "status": _required_text(task, "status"),
            "source_session_id": _required_text(task, "session_id"),
            "content": content,
        },
        created_at=timestamp,
        updated_at=timestamp,
    )


def enqueue_parent_session_result(
    repository: DurableRuntimeRepository,
    task: Mapping[str, Any],
    *,
    content: str,
    now: datetime | None = None,
) -> OutboxObligation:
    """Compatibility producer for callers that do not own task persistence."""
    obligation = parent_session_result_obligation(task, content=content, now=now)
    return repository.enqueue_outbox(obligation)


__all__ = [
    "DeliveryDestination",
    "DeliveryOutcomeUnknown",
    "DeliveryWorker",
    "LocalSessionDestination",
    "PermanentDeliveryError",
    "RetryableDeliveryError",
    "enqueue_parent_session_result",
    "parent_session_result_obligation",
]
