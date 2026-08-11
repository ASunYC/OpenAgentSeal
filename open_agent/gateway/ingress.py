"""Authenticated, durable channel ingress and replay-safe Agent dispatch."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from open_agent.app.runner.models import AgentRequest
from open_agent.durable_runtime.models import InboxEvent, to_json_value
from open_agent.durable_runtime.repository import DurableRuntimeRepository

from .contracts import ChannelAdapter, NormalizedInboundEvent
from .router import GatewayRouter
from .security import (
    IngressContext,
    IngressGuard,
    QuotaLedger,
    QuotaSnapshot,
    ResourceQuotaPolicy,
    SecurityViolation,
)


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class IngressReceipt:
    """The acknowledgement-safe identity of a durably stored event."""

    event_id: str
    event_key: str
    account_id: str


@dataclass(frozen=True, slots=True)
class IngressRunSummary:
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0


class IngressService:
    """Authenticate/normalize/admit/enqueue without running an Agent inline."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        router: GatewayRouter,
        *,
        ingress_guard: IngressGuard,
        quota_policy: ResourceQuotaPolicy,
        quota_ledger: QuotaLedger,
        quota_snapshot: Callable[[NormalizedInboundEvent], QuotaSnapshot],
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._router = router
        self._ingress_guard = ingress_guard
        self._quota_policy = quota_policy
        self._quota_ledger = quota_ledger
        self._quota_snapshot = quota_snapshot
        self._now = now

    def accept_webhook(
        self,
        adapter: ChannelAdapter,
        raw_body: bytes,
        headers: Mapping[str, str],
        *,
        account_id: str,
        remote_ip: str,
    ) -> IngressReceipt:
        """Return only after untouched bytes authenticate and the inbox commit succeeds."""
        if not isinstance(raw_body, bytes):
            raise TypeError("raw_body must be bytes")
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("account_id must be a non-empty string")
        if not isinstance(remote_ip, str) or not remote_ip.strip():
            raise ValueError("remote_ip must be a non-empty string")
        context = IngressContext(remote_ip, adapter.kind, account_id)
        event = self._ingress_guard.process(
            raw_body,
            headers,
            context,
            adapter.normalize,
            self._now(),
        )
        return self._accept_event(
            event,
            transport_mode="webhook",
            adapter=adapter,
            expected_account_id=account_id,
        )

    def accept_polled_event(
        self,
        event: NormalizedInboundEvent,
        *,
        transport_mode: str = "polling",
    ) -> IngressReceipt:
        """Durably store a normalized poll/gateway event before a cursor is advanced."""
        if transport_mode not in {"polling", "gateway"}:
            raise ValueError("polled transport_mode must be polling or gateway")
        return self._accept_event(event, transport_mode=transport_mode)

    def _accept_event(
        self,
        event: NormalizedInboundEvent,
        *,
        transport_mode: str,
        adapter: ChannelAdapter | None = None,
        expected_account_id: str | None = None,
    ) -> IngressReceipt:
        if not isinstance(event, NormalizedInboundEvent):
            raise TypeError("adapter must return a NormalizedInboundEvent")
        if adapter is not None and event.adapter_kind != adapter.kind:
            raise SecurityViolation("normalized adapter kind mismatch")
        if expected_account_id is not None and event.account_id != expected_account_id:
            raise SecurityViolation("normalized webhook account mismatch")
        snapshot = self._quota_snapshot(event)
        if not isinstance(snapshot, QuotaSnapshot):
            raise TypeError("quota_snapshot must return QuotaSnapshot")
        with self._quota_policy.reserve(
            self._quota_ledger,
            snapshot,
            conversation_id=event.conversation_id,
        ):
            event_id = self._event_id(event.account_id, event.event_key)
            existing = self._repository.get_inbox(event_id)
            if existing is not None:
                return IngressReceipt(
                    existing.event_id, existing.event_key, existing.account_id
                )
            route = self._router.resolve(event)
            if route.account_id != event.account_id:
                raise SecurityViolation("resolved route account mismatch")
            proposed = InboxEvent(
                event_id=event_id,
                event_key=event.event_key,
                account_id=event.account_id,
                conversation_id=event.conversation_id,
                payload={
                    "normalized_event": self._serialize_event(event),
                    "route": {
                        "route_id": route.route_id,
                        "profile_id": route.profile_id,
                        "session_id": route.session_id,
                        "thread_id": route.thread_id,
                        "trigger_policy": route.trigger_policy,
                        "should_dispatch": route.should_dispatch,
                    },
                    "transport_mode": transport_mode,
                },
                created_at=self._now(),
                updated_at=self._now(),
            )
            stored = self._repository.enqueue_inbox(proposed)
        return IngressReceipt(stored.event_id, stored.event_key, stored.account_id)

    def commit_checkpoint(
        self,
        account_id: str,
        transport_mode: str,
        *,
        cursor: str | None = None,
        gateway_session_id: str | None = None,
        gateway_sequence: int | None = None,
        replay_state: Mapping[str, Any] | None = None,
        reconnect_metadata: Mapping[str, Any] | None = None,
        processed_event_key: str | None = None,
    ) -> dict[str, Any]:
        return self._repository.commit_ingress_checkpoint(
            account_id=account_id,
            transport_mode=transport_mode,
            cursor=cursor,
            gateway_session_id=gateway_session_id,
            gateway_sequence=gateway_sequence,
            replay_state=replay_state,
            reconnect_metadata=reconnect_metadata,
            processed_event_key=processed_event_key,
            now=self._now(),
        )

    def get_checkpoint(self, account_id: str, transport_mode: str) -> dict[str, Any] | None:
        return self.get_persisted_checkpoint(self._repository, account_id, transport_mode)

    @staticmethod
    def get_persisted_checkpoint(
        repository: DurableRuntimeRepository,
        account_id: str,
        transport_mode: str,
    ) -> dict[str, Any] | None:
        return repository.get_ingress_checkpoint(account_id, transport_mode)

    @staticmethod
    def _event_id(account_id: str, event_key: str) -> str:
        identity = json.dumps(
            [account_id, event_key], ensure_ascii=False, separators=(",", ":")
        )
        return f"inbox_{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"

    @staticmethod
    def _serialize_event(event: NormalizedInboundEvent) -> dict[str, Any]:
        return {
            "event_key": event.event_key,
            "adapter_kind": event.adapter_kind,
            "account_id": event.account_id,
            "conversation_id": event.conversation_id,
            "sender_id": event.sender_id,
            "conversation_kind": event.conversation_kind,
            "text": event.text,
            "mentioned_bot": event.mentioned_bot,
            "replies_to_bot": event.replies_to_bot,
            "attachments": to_json_value(event.attachments),
            "metadata": to_json_value(event.metadata),
        }


class IngressWorker:
    """Claim inbox work with leases and reuse the existing Agent execution loop."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        router: GatewayRouter,
        runner: Any,
        *,
        worker_id: str,
        lease_duration: timedelta = timedelta(minutes=5),
        batch_size: int = 10,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be a non-empty string")
        if not timedelta(0) < lease_duration <= timedelta(hours=1):
            raise ValueError("lease_duration must be between zero and one hour")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be an integer between 1 and 100")
        self._repository = repository
        self._router = router
        self._runner = runner
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._batch_size = batch_size
        self._now = now

    async def run_once(self) -> IngressRunSummary:
        now = self._now()
        claims = self._repository.claim_due_inbox(
            self._worker_id,
            now,
            now + self._lease_duration,
            limit=self._batch_size,
        )
        succeeded = 0
        failed = 0
        for event in claims:
            try:
                await self._dispatch(event)
                succeeded += 1
            except Exception:
                # The live claim remains as the recovery fence. A restarted worker
                # may reclaim it only after expiry and will reuse the mapped turn.
                logger.warning(
                    "Inbox dispatch failed for event %s; lease recovery remains active",
                    event.event_id,
                    exc_info=True,
                )
                failed += 1
        return IngressRunSummary(len(claims), succeeded, failed)

    async def _dispatch(self, event: InboxEvent) -> None:
        if event.claim is None:
            raise RuntimeError("claimed inbox event has no fencing token")
        payload = to_json_value(event.payload)
        normalized = NormalizedInboundEvent(**payload["normalized_event"])
        route = payload["route"]
        if not bool(route["should_dispatch"]):
            self._repository.complete_inbox(event.event_id, event.claim, self._now())
            return
        if not route["session_id"] or not route["thread_id"]:
            raise RuntimeError("dispatchable route has no durable session mapping")

        # Re-resolve before a fresh dispatch to fail closed if the account was
        # disabled. Once dispatched, the persisted mapping is authoritative.
        if event.state != "dispatched":
            current_route = self._router.resolve(normalized)
            if (
                current_route.session_id != route["session_id"]
                or current_route.thread_id != route["thread_id"]
                or current_route.profile_id != route["profile_id"]
            ):
                raise RuntimeError("channel route changed before durable dispatch")

        source_event_key = json.dumps(
            [event.account_id, event.event_key],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        turn = self._repository.dispatch_inbox_with_turn(
            event.event_id,
            event.claim,
            thread_id=route["thread_id"],
            session_id=route["session_id"],
            user_input=normalized.text,
            metadata={
                "source_event_key": source_event_key,
                "profile_id": route["profile_id"],
                "transport": payload["transport_mode"],
            },
            now=self._now(),
        )
        if turn["status"] == "completed":
            self._repository.complete_inbox(event.event_id, event.claim, self._now())
            return
        session = self._repository.control_plane.get_session(route["session_id"])
        request = AgentRequest(
            session_id=route["session_id"],
            user_id=session["user_id"] if session is not None else "default",
            messages=[
                {
                    "role": "user",
                    "content": normalized.text,
                    "attachments": payload["normalized_event"]["attachments"],
                }
            ],
            meta={
                "profile_id": route["profile_id"],
                "source_event_key": source_event_key,
                "source_inbox_event_id": event.event_id,
                "channel_adapter": normalized.adapter_kind,
            },
        )
        current_claim = event.claim

        async def consume_stream() -> None:
            async for emitted in self._runner.run_stream(request, runtime_turn=turn):
                if getattr(emitted, "event", None) == "error":
                    raise RuntimeError(
                        getattr(emitted, "error", None) or "Agent execution failed"
                    )

        runner_task = asyncio.create_task(consume_stream())
        heartbeat_seconds = min(30.0, self._lease_duration.total_seconds() / 3)
        try:
            while not runner_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(runner_task), timeout=heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    heartbeat_now = self._now()
                    current_claim = self._repository.renew_claim(
                        "inbox",
                        event.event_id,
                        current_claim,
                        heartbeat_now,
                        heartbeat_now + self._lease_duration,
                    )
            await runner_task
        except BaseException:
            runner_task.cancel()
            with suppress(asyncio.CancelledError):
                await runner_task
            raise
        self._repository.complete_inbox(event.event_id, current_claim, self._now())


__all__ = [
    "IngressReceipt",
    "IngressRunSummary",
    "IngressService",
    "IngressWorker",
]
