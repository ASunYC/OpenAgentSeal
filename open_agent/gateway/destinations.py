"""Origin-scoped durable destinations for official messaging accounts."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Callable, Mapping

from open_agent.durable_runtime.delivery import (
    DeliveryOutcomeUnknown,
    PermanentDeliveryError,
    RetryableDeliveryError,
)
from open_agent.durable_runtime.models import ClaimToken, OutboxObligation
from open_agent.durable_runtime.repository import DurableRuntimeRepository, StaleClaimError

from .adapters.base_http import AdapterOutcomeUnknown
from .contracts import ChannelAdapter, OutboundMessage


CHANNEL_DESTINATION_PREFIX = "channel:"


def _required(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PermanentDeliveryError(f"payload.{name} must be a non-empty string")
    return value


def channel_obligation(
    *,
    account_id: str,
    conversation_id: str,
    content: str,
    source_event_key: str,
    now: datetime,
    metadata: Mapping[str, object] | None = None,
) -> OutboxObligation:
    """Build one deterministic reply obligation scoped to its origin account."""
    for value, name in (
        (account_id, "account_id"),
        (conversation_id, "conversation_id"),
        (source_event_key, "source_event_key"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    identity = json.dumps([account_id, source_event_key], separators=(",", ":"))
    obligation_id = f"delivery:channel:{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"
    return OutboxObligation(
        obligation_id=obligation_id,
        idempotency_key=f"channel-reply:{source_event_key}",
        destination=f"{CHANNEL_DESTINATION_PREFIX}{account_id}",
        payload={
            "account_id": account_id,
            "conversation_id": conversation_id,
            "content": content,
            "source_event_key": source_event_key,
            "metadata": dict(metadata or {}),
        },
        created_at=now,
        updated_at=now,
    )


class ChannelDestination:
    def __init__(
        self,
        repository: DurableRuntimeRepository,
        adapter: ChannelAdapter,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._adapter = adapter
        self._clock = clock

    @property
    def timeout_is_retryable(self) -> bool:
        return self._adapter.capabilities.supports_idempotency

    def _fence(self, obligation_id: str, claim: ClaimToken) -> None:
        now = self._clock()
        if claim.expires_at <= now:
            raise StaleClaimError(f"expired outbox claim: {obligation_id}")
        self._repository.renew_claim(
            "outbox", obligation_id, claim, now, claim.expires_at
        )

    async def deliver(self, obligation: OutboxObligation, claim: ClaimToken):
        expected = f"{CHANNEL_DESTINATION_PREFIX}{self._adapter.account_id}"
        if obligation.destination != expected:
            raise PermanentDeliveryError("channel destination/account mismatch")
        account = self._repository.get_channel_account(self._adapter.account_id)
        if account is None or not account["enabled"]:
            raise PermanentDeliveryError("channel account is missing or disabled")
        if account["adapter_kind"] != self._adapter.kind:
            raise PermanentDeliveryError("channel account adapter changed")
        payload = obligation.payload
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping):
            raise PermanentDeliveryError("payload.metadata must be an object")
        outbound_metadata = dict(metadata)
        outbound_metadata["delivery_id"] = obligation.obligation_id
        message = OutboundMessage(
            account_id=_required(payload, "account_id"),
            conversation_id=_required(payload, "conversation_id"),
            content=_required(payload, "content"),
            reply_to_event_key=_required(payload, "source_event_key"),
            metadata=outbound_metadata,
        )
        maximum = self._adapter.capabilities.max_message_chars
        if maximum is not None and len(message.content) > maximum:
            raise PermanentDeliveryError("outbound message exceeds the adapter limit")
        if message.attachments and not self._adapter.capabilities.supports_attachments:
            raise PermanentDeliveryError("adapter does not support outbound attachments")
        self._fence(obligation.obligation_id, claim)
        try:
            result = await asyncio.wait_for(
                self._adapter.send(message),
                timeout=self._adapter.capabilities.acknowledgement_deadline_seconds,
            )
        except asyncio.TimeoutError as exc:
            if self._adapter.capabilities.supports_idempotency:
                raise RetryableDeliveryError("idempotent provider acknowledgement timed out") from exc
            raise DeliveryOutcomeUnknown("provider acknowledgement timed out") from exc
        except AdapterOutcomeUnknown as exc:
            if self._adapter.capabilities.supports_idempotency:
                raise RetryableDeliveryError("idempotent provider delivery can be retried") from exc
            raise DeliveryOutcomeUnknown("provider delivery outcome is ambiguous") from exc
        if not isinstance(result, Mapping):
            raise RetryableDeliveryError("adapter acknowledgement is malformed")
        return dict(result)


class ChannelDestinationRegistry:
    """Resolve enabled persisted accounts to their configured adapter instance."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        adapters: Mapping[str, ChannelAdapter],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._adapters = dict(adapters)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def resolve(self, account_id: str) -> ChannelDestination:
        account = self._repository.get_channel_account(account_id)
        adapter = self._adapters.get(account_id)
        if account is None or adapter is None:
            raise KeyError(f"channel destination is not configured: {account_id}")
        if not account["enabled"] or account["adapter_kind"] != adapter.kind:
            raise KeyError(f"channel destination is unavailable: {account_id}")
        if getattr(adapter, "account_id", None) != account_id:
            raise KeyError("channel adapter account identity mismatch")
        return ChannelDestination(self._repository, adapter, clock=self._clock)


__all__ = [
    "CHANNEL_DESTINATION_PREFIX",
    "ChannelDestination",
    "ChannelDestinationRegistry",
    "channel_obligation",
]
