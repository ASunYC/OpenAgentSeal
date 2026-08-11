"""Crash-safe base lifecycle for one official provider connector."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from open_agent.durable_runtime.models import ClaimToken
from open_agent.durable_runtime.repository import StaleClaimError
from open_agent.gateway.contracts import GatewayConnectorCapability, NormalizedInboundEvent

from .contracts import (
    ConnectorAuthenticationError,
    ConnectorCredential,
    ConnectorLimits,
    ConnectorProtocolError,
    ConnectorSnapshot,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BaseGatewayConnector:
    kind = "base"

    def __init__(
        self,
        *,
        account_id: str,
        adapter: Any,
        ingress: Any,
        repository: Any,
        network: Any,
        credential: ConnectorCredential,
        http: Any | None = None,
        limits: ConnectorLimits = ConnectorLimits(),
        now=utc_now,
        connector_id: str | None = None,
    ) -> None:
        if not isinstance(account_id, str) or not account_id.strip() or len(account_id) > 256:
            raise ValueError("account_id must be a bounded non-empty string")
        if getattr(adapter, "kind", None) != self.kind:
            raise ValueError("adapter kind does not match connector")
        self.account_id = account_id
        self.adapter = adapter
        self.ingress = ingress
        self.repository = repository
        self.network = network
        self.http = http
        self.credential = credential
        self.limits = limits
        self.now = now
        self.connector_id = connector_id or f"{self.kind}-{uuid.uuid4().hex}"
        self._snapshot = ConnectorSnapshot(account_id, self.kind)
        self._claim: ClaimToken | None = None
        self._expected: dict[str, Any] = {
            "gateway_session_id": None, "gateway_sequence": None,
        }
        self._session_id: str | None = None
        self._sequence: int | None = None
        self._resume_url: str | None = None
        self._capability: GatewayConnectorCapability | None = None
        self._socket: Any | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}(account_id={self.account_id!r}, state={self._snapshot.state!r})"

    def snapshot(self) -> ConnectorSnapshot:
        return self._snapshot

    def restore_for_test(
        self, *, session_id: str, sequence: int, resume_url: str | None = None
    ) -> None:
        self._session_id, self._sequence, self._resume_url = session_id, sequence, resume_url
        self._snapshot = replace(
            self._snapshot, session_resumable=True, last_sequence=sequence,
        )

    async def run_once(self) -> None:
        claimed = self.repository.claim_ingress_checkpoint(
            account_id=self.account_id,
            transport_mode="gateway",
            owner_id=self.connector_id,
            now=self.now(),
            expires_at=self.now() + timedelta(seconds=self.limits.lease_seconds),
        )
        self._claim = claimed["claim"]
        self._restore_claimed_checkpoint(claimed)
        self._snapshot = replace(self._snapshot, state="connecting", last_error=None)
        session: asyncio.Task[None] | None = None
        lease: asyncio.Task[None] | None = None
        try:
            session = asyncio.create_task(
                self._run_session(), name=f"connector-session:{self.account_id}"
            )
            lease = asyncio.create_task(
                self._lease_renewal_loop(), name=f"connector-lease:{self.account_id}"
            )
            done, pending = await asyncio.wait(
                (session, lease), return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if lease in done and not lease.cancelled() and lease.exception() is not None:
                await lease
            await session
        except EOFError:
            self._snapshot = replace(self._snapshot, state="disconnected")
        except asyncio.CancelledError:
            self._snapshot = replace(self._snapshot, state="stopping")
            raise
        except Exception as exc:
            self._snapshot = replace(
                self._snapshot,
                state="error",
                reconnect_count=self._snapshot.reconnect_count + 1,
                last_error=type(exc).__name__,
            )
            raise
        finally:
            children = tuple(task for task in (session, lease) if task is not None)
            for task in children:
                if not task.done():
                    task.cancel()
            if children:
                await asyncio.gather(*children, return_exceptions=True)
            await self._close_socket()
            self._remove_capability()
            self._release_claim()

    async def _run_session(self) -> None:
        raise NotImplementedError

    def _restore_claimed_checkpoint(self, claimed: Mapping[str, Any]) -> None:
        if self._session_id is None:
            self._session_id = claimed.get("gateway_session_id")
            self._sequence = claimed.get("gateway_sequence")
            metadata = claimed.get("reconnect_metadata") or {}
            self._resume_url = metadata.get("resume_url")
        self._expected = {
            "gateway_session_id": claimed.get("gateway_session_id"),
            "gateway_sequence": claimed.get("gateway_sequence"),
        }

    def _mark_authenticated(self, session_id: str, *, resumable: bool) -> None:
        if not isinstance(session_id, str) or not session_id or len(session_id) > 512:
            raise ConnectorAuthenticationError("provider returned an invalid session")
        self._session_id = session_id
        capability = GatewayConnectorCapability(
            self.connector_id, self.kind, self.account_id
        )
        install = getattr(self.ingress, "install_gateway_capability", None)
        if callable(install):
            install(self.account_id, capability)
        self._capability = capability
        self._snapshot = replace(
            self._snapshot, state="connected", authenticated=True,
            session_resumable=resumable,
        )

    def _remove_capability(self) -> None:
        if self._capability is None:
            return
        remove = getattr(self.ingress, "remove_gateway_capability", None)
        if callable(remove):
            remove(self.account_id, self._capability)
        self._capability = None

    def _release_claim(self) -> None:
        token, self._claim = self._claim, None
        if token is None:
            return
        try:
            self.repository.release_ingress_checkpoint_claim(
                account_id=self.account_id, transport_mode="gateway",
                token=token, now=self.now(),
            )
        except StaleClaimError:
            pass

    async def _close_socket(self) -> None:
        socket, self._socket = self._socket, None
        if socket is None:
            return
        try:
            await socket.close(code=1000, reason="connector shutdown")
        except Exception:
            pass

    def _renew_claim_if_needed(self) -> None:
        token = self._claim
        if token is None:
            raise StaleClaimError("connector has no ingress claim")
        now = self.now()
        if token.expires_at - now > timedelta(seconds=self.limits.lease_seconds // 2):
            return
        self._claim = self.repository.renew_ingress_checkpoint_claim(
            account_id=self.account_id, transport_mode="gateway", token=token,
            now=now, expires_at=now + timedelta(seconds=self.limits.lease_seconds),
        )

    async def _lease_renewal_loop(self) -> None:
        delay = max(1.0, self.limits.lease_seconds / 3)
        while True:
            await asyncio.sleep(delay)
            token = self._claim
            if token is None:
                raise StaleClaimError("connector has no ingress claim")
            now = self.now()
            self._claim = self.repository.renew_ingress_checkpoint_claim(
                account_id=self.account_id, transport_mode="gateway", token=token,
                now=now,
                expires_at=now + timedelta(seconds=self.limits.lease_seconds),
            )

    def _normalize(self, payload: Mapping[str, Any]) -> NormalizedInboundEvent:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) > self.limits.max_decompressed_bytes:
            raise ConnectorProtocolError("normalized provider frame exceeds the limit")
        event = self.adapter.normalize(raw)
        if event.account_id != self.account_id or event.adapter_kind != self.kind:
            raise ConnectorProtocolError("normalized provider identity mismatch")
        return event

    def _accept(self, event: NormalizedInboundEvent, *, session_id: str, sequence: int) -> bool:
        if self._capability is None or self._claim is None:
            raise ConnectorAuthenticationError("connector session is not authenticated")
        if type(sequence) is not int or sequence < 0:
            raise ConnectorProtocolError("provider sequence must be a non-negative integer")
        self._renew_claim_if_needed()
        assert self._claim is not None
        frame = self._capability.authenticate(
            event, gateway_session_id=session_id, gateway_sequence=sequence,
        )
        receipt = self.ingress.accept_polled_event(
            frame, transport_mode="gateway", gateway_session_id=session_id,
            gateway_sequence=sequence, claim=self._claim,
        )
        event_id = getattr(receipt, "event_id", None)
        if isinstance(event_id, str):
            stored = self.repository.get_inbox(event_id)
            if stored is not None:
                prior = stored.payload.get("transport_position") or {}
                if (
                    prior.get("gateway_session_id") != session_id
                    or prior.get("gateway_sequence") != sequence
                ):
                    # Provider replay of an already durable logical message. It is
                    # safe to acknowledge, but it cannot move a different cursor.
                    return False
        reconnect = {"resume_url": self._resume_url} if self._resume_url else {}
        committed = self.ingress.commit_checkpoint(
            self.account_id, "gateway", claim=self._claim,
            expected_previous=dict(self._expected), gateway_session_id=session_id,
            gateway_sequence=sequence, reconnect_metadata=reconnect,
            processed_event_key=receipt.event_key, retain_claim=True,
        )
        self._expected = {
            "gateway_session_id": committed.get("gateway_session_id", session_id),
            "gateway_sequence": committed.get("gateway_sequence", sequence),
        }
        self._session_id, self._sequence = session_id, sequence
        self._snapshot = replace(self._snapshot, last_sequence=sequence)
        return True

    async def _http_json(
        self, method: str, url: str, *, headers: Mapping[str, str],
        body: Mapping[str, Any] | None, allowed_hosts: frozenset[str],
    ) -> Mapping[str, Any]:
        if self.http is None:
            raise ConnectorProtocolError("official HTTPS transport is unavailable")
        response = await self.http.request(
            method, url, headers=headers, json_body=body, allowed_hosts=allowed_hosts,
        )
        if response.status_code in {401, 403}:
            raise ConnectorAuthenticationError("provider rejected connector credentials")
        if response.status_code < 200 or response.status_code >= 300:
            raise ConnectorProtocolError("provider endpoint request failed")
        if len(response.content) > self.limits.max_frame_bytes:
            raise ConnectorProtocolError("provider endpoint response exceeds the limit")
        try:
            payload = response.json()
        except Exception:
            raise ConnectorProtocolError("provider endpoint response is invalid") from None
        if not isinstance(payload, Mapping):
            raise ConnectorProtocolError("provider endpoint response must be an object")
        return payload


__all__ = ["BaseGatewayConnector"]
