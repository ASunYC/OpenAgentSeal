"""Authenticated, durable channel ingress and replay-safe Agent dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from open_agent.app.runner.models import AgentRequest
from open_agent.durable_runtime.models import ClaimToken, InboxEvent, to_json_value
from open_agent.durable_runtime.repository import (
    DurableRuntimeRepository,
    StateConflictError,
)

from .contracts import AuthenticatedGatewayFrame, ChannelAdapter, GatewayConnectorCapability, NormalizedInboundEvent
from .destinations import channel_obligation
from .router import GatewayRouter
from .security import (
    AttachmentGuard,
    AttachmentUpload,
    IngressContext,
    IngressGuard,
    OutboundUrlPolicy,
    QuotaLedger,
    QuotaSnapshot,
    ResourceQuotaPolicy,
    SecurityViolation,
    StoredAttachment,
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


@dataclass(frozen=True, slots=True)
class IngressLimits:
    max_body_bytes: int = 1024 * 1024
    max_header_count: int = 64
    max_header_name_chars: int = 128
    max_header_value_chars: int = 4096
    max_identifier_chars: int = 256
    max_text_chars: int = 20000
    max_metadata_bytes: int = 65536
    max_nesting_depth: int = 8
    max_attachment_count: int = 16
    max_attachment_name_chars: int = 256
    max_attachment_url_chars: int = 2048

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


class _BytesStream:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0

    def read(self, max_bytes: int, deadline: float) -> bytes | None:
        del deadline
        if self._offset >= len(self._content):
            return None
        end = min(self._offset + max_bytes, len(self._content))
        chunk = self._content[self._offset:end]
        self._offset = end
        return chunk


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
        limits: IngressLimits = IngressLimits(),
        attachment_guard: AttachmentGuard | None = None,
        url_policy: OutboundUrlPolicy | None = None,
        attachment_fetcher: Callable[[Any], AttachmentUpload] | None = None,
        gateway_capabilities: Mapping[str, GatewayConnectorCapability] | None = None,
    ) -> None:
        self._repository = repository
        self._router = router
        self._ingress_guard = ingress_guard
        self._quota_policy = quota_policy
        self._quota_ledger = quota_ledger
        self._quota_snapshot = quota_snapshot
        self._now = now
        self._limits = limits
        self._attachment_guard = attachment_guard
        self._url_policy = url_policy
        self._attachment_fetcher = attachment_fetcher
        self._gateway_capabilities = dict(gateway_capabilities or {})

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
        self._validate_envelope(raw_body, headers)
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("account_id must be a non-empty string")
        if not isinstance(remote_ip, str) or not remote_ip.strip():
            raise ValueError("remote_ip must be a non-empty string")
        if (
            len(account_id) > self._limits.max_identifier_chars
            or len(remote_ip) > self._limits.max_identifier_chars
            or len(adapter.kind) > self._limits.max_identifier_chars
        ):
            raise SecurityViolation("webhook context identifier length limit exceeded")
        context = IngressContext(remote_ip, adapter.kind, account_id)
        request_digest = hashlib.sha256(raw_body).hexdigest()

        official_verifier = getattr(adapter, "verify_webhook", None)
        if adapter.capabilities.supports_webhook and callable(official_verifier):
            def verify_official(untouched_body: bytes) -> None:
                try:
                    verified = official_verifier(untouched_body, headers, now=self._now())
                except Exception as exc:
                    raise SecurityViolation("official webhook authentication failed") from exc
                if verified is not True:
                    raise SecurityViolation("official webhook authentication failed")

            def accept_official(untouched_body: bytes) -> IngressReceipt:
                normalizer = getattr(adapter, "normalize_many", None)
                events = (
                    tuple(normalizer(untouched_body))
                    if callable(normalizer)
                    else (adapter.normalize(untouched_body),)
                )
                if not 1 <= len(events) <= 100:
                    raise SecurityViolation("webhook event batch size is invalid")
                receipts = tuple(
                    self._accept_event(
                        event,
                        transport_mode="webhook",
                        adapter=adapter,
                        expected_account_id=account_id,
                    )
                    for event in events
                )
                return receipts[0]

            return self._ingress_guard.process_authenticated(
                raw_body, context, verify_official, accept_official
            )

        def accept_verified(verified, untouched_body):
            receipt = self._repository.get_webhook_nonce_receipt(
                verified.account_id, verified.nonce
            )
            if receipt is not None:
                if receipt["request_digest"] != request_digest:
                    raise SecurityViolation("webhook nonce digest mismatch")
                stored = self._repository.get_inbox(receipt["event_id"])
                if stored is None:
                    raise SecurityViolation("webhook nonce receipt is orphaned")
                return IngressReceipt(stored.event_id, stored.event_key, stored.account_id)
            event = adapter.normalize(untouched_body)
            return self._accept_event(
                event,
                transport_mode="webhook",
                adapter=adapter,
                expected_account_id=account_id,
                nonce=verified.nonce,
                request_digest=request_digest,
                nonce_expires_at=verified.expires_at,
            )

        return self._ingress_guard.process_durable(
            raw_body,
            headers,
            context,
            accept_verified,
            self._now(),
        )

    def accept_polled_event(
        self,
        event: NormalizedInboundEvent | AuthenticatedGatewayFrame,
        *,
        transport_mode: str = "polling",
        cursor: str | None = None,
        gateway_session_id: str | None = None,
        gateway_sequence: int | None = None,
        claim: ClaimToken | None = None,
    ) -> IngressReceipt:
        """Durably store a normalized poll/gateway event before a cursor is advanced."""
        if transport_mode not in {"polling", "gateway"}:
            raise ValueError("polled transport_mode must be polling or gateway")
        if claim is None:
            raise ValueError("transport claim is required")
        if transport_mode == "gateway":
            if not isinstance(event, AuthenticatedGatewayFrame):
                raise SecurityViolation("gateway ingress requires an authenticated connector frame")
            capability = self._gateway_capabilities.get(event.event.account_id)
            if capability is None or not capability.verifies(event):
                raise SecurityViolation("gateway connector proof is invalid")
            if gateway_session_id not in (None, event.gateway_session_id):
                raise SecurityViolation("gateway session does not match authenticated frame")
            if gateway_sequence not in (None, event.gateway_sequence):
                raise SecurityViolation("gateway sequence does not match authenticated frame")
            gateway_session_id = event.gateway_session_id
            gateway_sequence = event.gateway_sequence
            event = event.event
        elif isinstance(event, AuthenticatedGatewayFrame):
            raise SecurityViolation("authenticated gateway frames require gateway transport")
        return self._accept_event(
            event,
            transport_mode=transport_mode,
            transport_position={
                "cursor": cursor,
                "gateway_session_id": gateway_session_id,
                "gateway_sequence": gateway_sequence,
            },
            transport_claim=claim,
        )

    def _accept_event(
        self,
        event: NormalizedInboundEvent,
        *,
        transport_mode: str,
        adapter: ChannelAdapter | None = None,
        expected_account_id: str | None = None,
        nonce: str | None = None,
        request_digest: str | None = None,
        nonce_expires_at: datetime | None = None,
        transport_position: Mapping[str, Any] | None = None,
        transport_claim: ClaimToken | None = None,
    ) -> IngressReceipt:
        if not isinstance(event, NormalizedInboundEvent):
            raise TypeError("adapter must return a NormalizedInboundEvent")
        if adapter is not None and event.adapter_kind != adapter.kind:
            raise SecurityViolation("normalized adapter kind mismatch")
        if expected_account_id is not None and event.account_id != expected_account_id:
            raise SecurityViolation("normalized webhook account mismatch")
        attachment_bytes = self._validate_event(event)
        if transport_mode in {"polling", "gateway"}:
            if transport_claim is None:
                raise ValueError("transport claim is required")
            self._repository.validate_ingress_claim(
                account_id=event.account_id, transport_mode=transport_mode,
                token=transport_claim, now=self._now(),
            )
        event_id = self._event_id(event.account_id, event.event_key)
        self._recover_staged_attachments(event_id)
        existing = self._repository.get_inbox(event_id)
        if existing is not None:
            replay = InboxEvent(
                event_id=existing.event_id,
                event_key=existing.event_key,
                account_id=existing.account_id,
                conversation_id=existing.conversation_id,
                payload=existing.payload,
                created_at=self._now(),
                updated_at=self._now(),
            )
            if nonce is not None:
                stored = self._repository.enqueue_inbox_with_nonce(
                    replay, nonce=nonce, request_digest=request_digest,
                    nonce_expires_at=nonce_expires_at,
                )
            elif transport_mode in {"polling", "gateway"}:
                if transport_claim is None:
                    raise ValueError("transport claim is required")
                stored = self._repository.enqueue_polled_inbox(
                    replay, transport_mode=transport_mode, token=transport_claim,
                    now=self._now(),
                )
            else:
                stored = existing
            return IngressReceipt(stored.event_id, stored.event_key, stored.account_id)
        snapshot = self._quota_snapshot(event)
        if not isinstance(snapshot, QuotaSnapshot):
            raise TypeError("quota_snapshot must return QuotaSnapshot")
        snapshot = replace(
            snapshot, attachment_bytes=max(snapshot.attachment_bytes, attachment_bytes)
        )
        with self._quota_policy.reserve(
            self._quota_ledger,
            snapshot,
            conversation_id=event.conversation_id,
        ):
            route = self._router.resolve(event)
            if route.account_id != event.account_id:
                raise SecurityViolation("resolved route account mismatch")
            staged: tuple[StoredAttachment, ...] = ()
            actual_quota_lease = None
            adopted = False
            try:
                if event.attachments:
                    event, staged, actual_quota_lease = self._ingest_event_attachments(
                        event, event_id, snapshot
                    )
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
                        "transport_position": dict(transport_position or {}),
                    },
                    created_at=self._now(),
                    updated_at=self._now(),
                )
                stage_id = event_id if staged else None
                if nonce is None:
                    if transport_mode in {"polling", "gateway"}:
                        if transport_claim is None:
                            raise ValueError("transport claim is required")
                        stored = self._repository.enqueue_polled_inbox(
                            proposed, transport_mode=transport_mode,
                            token=transport_claim, now=self._now(),
                            attachment_stage_event_id=stage_id,
                        )
                    else:
                        stored = self._repository.enqueue_inbox(proposed)
                else:
                    stored = self._repository.enqueue_inbox_with_nonce(
                        proposed, nonce=nonce, request_digest=request_digest,
                        nonce_expires_at=nonce_expires_at,
                        attachment_stage_event_id=stage_id,
                    )
                adopted = True
            except Exception:
                if staged and not adopted:
                    self._attachment_guard.rollback(staged)
                    self._repository.clear_staged_inbox_attachments(event_id)
                raise
            finally:
                if actual_quota_lease is not None:
                    actual_quota_lease.__exit__(None, None, None)
        return IngressReceipt(stored.event_id, stored.event_key, stored.account_id)

    def claim_checkpoint(
        self,
        account_id: str,
        transport_mode: str,
        *,
        owner_id: str,
        lease_duration: timedelta,
    ) -> ClaimToken:
        now = self._now()
        claimed = self._repository.claim_ingress_checkpoint(
            account_id=account_id,
            transport_mode=transport_mode,
            owner_id=owner_id,
            now=now,
            expires_at=now + lease_duration,
        )
        return claimed["claim"]

    def commit_checkpoint(
        self,
        account_id: str,
        transport_mode: str,
        *,
        claim: ClaimToken,
        expected_previous: Mapping[str, Any],
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
            token=claim,
            expected_previous=expected_previous,
            cursor=cursor,
            gateway_session_id=gateway_session_id,
            gateway_sequence=gateway_sequence,
            replay_state=replay_state,
            reconnect_metadata=reconnect_metadata,
            processed_event_key=processed_event_key,
            now=self._now(),
        )

    def _validate_envelope(self, raw_body: bytes, headers: Mapping[str, str]) -> None:
        if len(raw_body) > self._limits.max_body_bytes:
            raise SecurityViolation("webhook body size limit exceeded")
        if not isinstance(headers, Mapping) or len(headers) > self._limits.max_header_count:
            raise SecurityViolation("webhook header count limit exceeded")
        for name, value in headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise SecurityViolation("webhook headers must be strings")
            if len(name) > self._limits.max_header_name_chars:
                raise SecurityViolation("webhook header name limit exceeded")
            if len(value) > self._limits.max_header_value_chars:
                raise SecurityViolation("webhook header value limit exceeded")

    def _validate_event(self, event: NormalizedInboundEvent) -> int:
        identifiers = (
            event.event_key, event.adapter_kind, event.account_id,
            event.conversation_id, event.sender_id,
        )
        if any(len(value) > self._limits.max_identifier_chars for value in identifiers):
            raise SecurityViolation("normalized identifier length limit exceeded")
        if len(event.text) > self._limits.max_text_chars:
            raise SecurityViolation("normalized text length limit exceeded")
        metadata_value = to_json_value(event.metadata)
        if self._value_depth(metadata_value) > self._limits.max_nesting_depth:
            raise SecurityViolation("normalized metadata depth limit exceeded")
        encoded = json.dumps(metadata_value, ensure_ascii=False).encode("utf-8")
        if len(encoded) > self._limits.max_metadata_bytes:
            raise SecurityViolation("normalized metadata size limit exceeded")
        if not event.attachments:
            return 0
        if len(event.attachments) > self._limits.max_attachment_count:
            raise SecurityViolation("attachment count limit exceeded")
        if self._attachment_guard is None:
            raise SecurityViolation("attachment guard is required")
        attachment_bytes = 0
        has_url_attachment = False
        for raw in event.attachments:
            value = to_json_value(raw)
            if not isinstance(value, Mapping):
                raise SecurityViolation("invalid attachment descriptor")
            if value.get("url"):
                if not isinstance(value["url"], str):
                    raise SecurityViolation("attachment URL must be a string")
                if len(value["url"]) > self._limits.max_attachment_url_chars:
                    raise SecurityViolation("attachment URL length limit exceeded")
                if self._url_policy is None or self._attachment_fetcher is None:
                    raise SecurityViolation("URL attachment policy is unavailable")
                declared_size = value.get("size")
                if (
                    isinstance(declared_size, bool)
                    or not isinstance(declared_size, int)
                    or declared_size < 0
                ):
                    raise SecurityViolation("URL attachment requires a declared size")
                attachment_bytes += declared_size
                has_url_attachment = True
                continue
            content = value.get("content")
            if not isinstance(content, bytes):
                raise SecurityViolation("attachment content must be guarded bytes")
            filename = value.get("filename") or "attachment"
            claimed_content_type = value.get("claimed_content_type") or ""
            if not isinstance(filename, str) or not isinstance(claimed_content_type, str):
                raise SecurityViolation("attachment names and content types must be strings")
            if (
                len(filename) > self._limits.max_attachment_name_chars
                or len(claimed_content_type) > self._limits.max_header_name_chars
            ):
                raise SecurityViolation("attachment descriptor length limit exceeded")
            attachment_bytes += len(content)
        if has_url_attachment:
            return self._quota_policy.max_attachment_bytes
        return attachment_bytes

    def _ingest_event_attachments(
        self,
        event: NormalizedInboundEvent,
        event_id: str,
        quota_snapshot: QuotaSnapshot,
    ) -> tuple[NormalizedInboundEvent, tuple[StoredAttachment, ...], Any]:
        uploads: list[AttachmentUpload] = []
        for raw in event.attachments:
            value = to_json_value(raw)
            if value.get("url"):
                validated = self._url_policy.validate(value["url"])
                uploads.append(self._attachment_fetcher(validated))
                continue
            content = value["content"]
            uploads.append(
                AttachmentUpload(
                    filename=value.get("filename") or "attachment",
                    claimed_content_type=value.get("claimed_content_type") or "",
                    chunks=_BytesStream(content),
                )
            )
        staged_holder: list[StoredAttachment] = []
        actual_quota_lease = None

        def record_staging(items: tuple[StoredAttachment, ...]) -> None:
            self._repository.stage_inbox_attachments(
                event_id=event_id, account_id=event.account_id,
                attachments=items, now=self._now(),
            )
            staged_holder.extend(items)

        def reserve_actual_before_storage(items: tuple[StoredAttachment, ...]) -> None:
            nonlocal actual_quota_lease
            expected_bytes = 0
            has_url = False
            for raw in event.attachments:
                value = to_json_value(raw)
                if value.get("url"):
                    has_url = True
                    expected_bytes += int(value["size"])
                else:
                    expected_bytes += len(value["content"])
            actual_bytes = sum(item.size for item in items)
            if actual_bytes != expected_bytes:
                raise SecurityViolation(
                    "attachment size does not match preflight declaration"
                )
            if has_url:
                actual_quota_lease = self._quota_policy.reserve(
                    self._quota_ledger,
                    replace(quota_snapshot, attachment_bytes=actual_bytes),
                    conversation_id=event.conversation_id,
                )
                actual_quota_lease.__enter__()

        try:
            stored = self._attachment_guard.ingest(
                uploads,
                on_staging=record_staging,
                before_storage=reserve_actual_before_storage,
            )
        except Exception:
            if staged_holder:
                self._attachment_guard.rollback(tuple(staged_holder))
                self._repository.clear_staged_inbox_attachments(event_id)
            if actual_quota_lease is not None:
                actual_quota_lease.__exit__(None, None, None)
            raise
        managed = tuple(
            {
                "storage_path": item.storage_path,
                "size": item.size,
                "expires_at": item.expires_at.isoformat(),
            }
            for item in stored
        )
        return replace(event, attachments=managed), stored, actual_quota_lease

    def _recover_staged_attachments(self, event_id: str) -> None:
        manifest = self._repository.get_staged_inbox_attachments(event_id)
        if not manifest:
            return
        stored = tuple(
            StoredAttachment(
                item["storage_path"], int(item["size"]),
                datetime.fromisoformat(item["expires_at"]),
                item.get("ownership_token", ""),
            )
            for item in manifest
        )
        if any(
            re.fullmatch(r"quarantine/[A-Za-z0-9_-]{16,128}", item.storage_path)
            is None
            for item in stored
        ):
            raise SecurityViolation("unsafe staged attachment path")
        self._attachment_guard.rollback(stored)
        self._repository.clear_staged_inbox_attachments(event_id)

    @staticmethod
    def _value_depth(value: Any) -> int:
        maximum = 0
        pending = [(value, 0)]
        while pending:
            current, depth = pending.pop()
            maximum = max(maximum, depth)
            if isinstance(current, Mapping):
                pending.extend((item, depth + 1) for item in current.values())
            elif isinstance(current, (list, tuple)):
                pending.extend((item, depth + 1) for item in current)
        return maximum

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
        self._repository.control_plane.prepare_tool_effect_retry(
            source_event_key, now=self._now()
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
            try:
                turn_result = turn.get("result")
                recovered_content = (
                    str(turn_result.get("content") or "")
                    if isinstance(turn_result, Mapping)
                    else ""
                )
                self._repository.complete_inbox_after_agent(
                    event.event_id, event.claim,
                    source_event_key=source_event_key, now=self._now(),
                    reply_obligation=self._reply_obligation(
                        normalized, recovered_content, source_event_key
                    ),
                )
            except StateConflictError as exc:
                self._repository.retry_dispatched_inbox(
                    event.event_id, event.claim, self._now(),
                    error="Completed turn has unresolved durable tool effects",
                )
                raise RuntimeError(
                    "Completed turn has unresolved durable tool effects"
                ) from exc
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
                "_runtime_control_plane": self._repository.control_plane,
            },
        )
        current_claim = event.claim

        saw_complete = False
        complete_content = ""

        async def consume_stream() -> None:
            nonlocal saw_complete, complete_content
            async for emitted in self._runner.run_stream(request, runtime_turn=turn):
                event_name = getattr(emitted, "event", None)
                if event_name == "complete":
                    saw_complete = True
                    emitted_content = getattr(emitted, "content", None)
                    if isinstance(emitted_content, str):
                        complete_content = emitted_content
                elif event_name in {"error", "cancelled"}:
                    raise RuntimeError(
                        getattr(emitted, "error", None)
                        or f"Agent stream terminated with {event_name}"
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
            with suppress(asyncio.CancelledError, Exception):
                await runner_task
            self._repository.retry_dispatched_inbox(
                event.event_id,
                current_claim,
                self._now(),
                error="Agent stream failed before authoritative completion",
            )
            raise
        authoritative = self._repository.control_plane._get_conn().execute(
            "SELECT status FROM runtime_turns WHERE turn_id = ?", (turn["turn_id"],)
        ).fetchone()
        if (
            not saw_complete
            or authoritative is None
            or authoritative["status"] != "completed"
        ):
            self._repository.retry_dispatched_inbox(
                event.event_id,
                current_claim,
                self._now(),
                error="Agent stream ended without an authoritative complete event",
            )
            raise RuntimeError("Agent stream ended without authoritative completion")
        try:
            self._repository.complete_inbox_after_agent(
                event.event_id, current_claim,
                source_event_key=source_event_key, now=self._now(),
                reply_obligation=self._reply_obligation(
                    normalized, complete_content, source_event_key
                ),
            )
        except StateConflictError as exc:
            self._repository.retry_dispatched_inbox(
                event.event_id, current_claim, self._now(),
                error="Agent completed with unresolved durable tool effects",
            )
            raise RuntimeError(
                "Agent completed with unresolved durable tool effects"
            ) from exc

    def _reply_obligation(
        self,
        event: NormalizedInboundEvent,
        content: str,
        source_event_key: str,
    ):
        if not content.strip():
            return None
        return channel_obligation(
            account_id=event.account_id,
            conversation_id=event.conversation_id,
            content=content,
            source_event_key=source_event_key,
            now=self._now(),
            metadata={
                "reply_message_id": event.metadata.get("message_id"),
                "thread_ts": event.metadata.get("thread_ts"),
                "qq_destination_kind": event.metadata.get("qq_destination_kind"),
                "wecom_transport": event.metadata.get("wecom_transport"),
                "wecom_request_id": event.metadata.get("wecom_request_id"),
            },
        )


__all__ = [
    "IngressReceipt",
    "IngressLimits",
    "IngressRunSummary",
    "IngressService",
    "IngressWorker",
]
