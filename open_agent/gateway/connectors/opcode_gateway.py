"""Discord/QQ opcode gateway lifecycle with durable resume checkpoints."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, Mapping
from urllib.parse import urlencode

from .base import BaseGatewayConnector
from .contracts import ConnectorAuthenticationError, ConnectorProtocolError
from .transport import decode_gateway_frame


class OpcodeGatewayConnector(BaseGatewayConnector):
    api_version = 10
    gateway_api_url = ""
    gateway_api_hosts: frozenset[str] = frozenset()
    gateway_hosts: frozenset[str] = frozenset()

    async def _run_session(self) -> None:
        url = self._resume_url or await self._discover_gateway_url()
        if "?" not in url:
            url = url.rstrip("/") + "/"
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode({'v': self.api_version, 'encoding': 'json'})}"
        self._socket = await self.network.connect(
            url, allowed_hosts=self.gateway_hosts,
            max_frame_bytes=self.limits.max_frame_bytes,
        )
        hello = await self._recv_frame()
        if hello.get("op") != 10:
            raise ConnectorProtocolError("gateway did not begin with HELLO")
        data = hello.get("d")
        if not isinstance(data, Mapping):
            raise ConnectorProtocolError("gateway HELLO payload is invalid")
        interval_ms = data.get("heartbeat_interval")
        if type(interval_ms) not in {int, float} or not 1000 <= interval_ms <= 300000:
            raise ConnectorProtocolError("gateway heartbeat interval is invalid")
        heartbeat_ack = asyncio.Event()
        heartbeat_ack.set()
        heartbeat = asyncio.create_task(
            self._heartbeat_loop(float(interval_ms) / 1000, heartbeat_ack),
            name=f"connector-heartbeat:{self.account_id}",
        )
        receiver = asyncio.create_task(
            self._receive_loop(heartbeat_ack),
            name=f"connector-receive:{self.account_id}",
        )
        try:
            if self._session_id and self._sequence is not None:
                await self._send(self._resume_payload())
            else:
                await self._send(self._identify_payload())
            done, pending = await asyncio.wait(
                (heartbeat, receiver), return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await next(iter(done))
        finally:
            heartbeat.cancel()
            receiver.cancel()
            await asyncio.gather(heartbeat, receiver, return_exceptions=True)

    async def _receive_loop(self, heartbeat_ack: asyncio.Event) -> None:
        while True:
            frame = await self._recv_frame()
            op = frame.get("op")
            if op == 11:
                heartbeat_ack.set()
                continue
            if op == 1:
                heartbeat_ack.clear()
                await self._send({"op": 1, "d": self._sequence})
                continue
            if op == 7:
                raise EOFError("provider requested reconnect")
            if op == 9:
                if frame.get("d") is not True or not self._session_id:
                    self._invalidate_session()
                await self._wait_invalid_session()
                raise EOFError("provider invalidated session")
            if op != 0:
                continue
            self._handle_dispatch(frame)

    async def _wait_invalid_session(self) -> None:
        """Provider hook for INVALID_SESSION reconnect throttling."""

    async def _discover_gateway_url(self) -> str:
        payload = await self._http_json(
            "GET", self.gateway_api_url, headers=self._gateway_headers(), body=None,
            allowed_hosts=self.gateway_api_hosts,
        )
        value = payload.get("url")
        if not isinstance(value, str) or not value.startswith("wss://") or len(value) > 2048:
            raise ConnectorProtocolError("provider returned an invalid gateway URL")
        limit = payload.get("session_start_limit")
        if isinstance(limit, Mapping) and type(limit.get("remaining")) is int and limit["remaining"] < 1:
            raise ConnectorProtocolError("provider session start limit is exhausted")
        return value

    async def _recv_frame(self) -> Mapping[str, Any]:
        try:
            raw = await self._socket.recv()
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code in {4004, 4010, 4011, 4012, 4013, 4014, 9001, 9005}:
                self._invalidate_session()
                raise ConnectorAuthenticationError("gateway closed with a terminal configuration code") from None
            if code in {4007, 4009}:
                self._invalidate_session()
                raise EOFError("gateway session is no longer resumable") from None
            raise
        return decode_gateway_frame(raw, self.limits)

    def _gateway_headers(self) -> Mapping[str, str]:
        raise NotImplementedError

    def _identify_payload(self) -> Mapping[str, Any]:
        raise NotImplementedError

    def _resume_payload(self) -> Mapping[str, Any]:
        return {
            "op": 6,
            "d": {
                "token": self._gateway_token(), "session_id": self._session_id,
                "seq": self._sequence,
            },
        }

    def _gateway_token(self) -> str:
        raise NotImplementedError

    def _handle_dispatch(self, frame: Mapping[str, Any]) -> None:
        sequence = frame.get("s")
        if type(sequence) is not int or sequence < 0:
            raise ConnectorProtocolError("dispatch sequence is invalid")
        event_type = frame.get("t")
        data = frame.get("d")
        if not isinstance(event_type, str) or not isinstance(data, Mapping):
            raise ConnectorProtocolError("dispatch payload is invalid")
        if event_type == "READY":
            session_id = data.get("session_id")
            if not isinstance(session_id, str):
                raise ConnectorAuthenticationError("READY omitted session identity")
            resume_url = data.get("resume_gateway_url")
            if isinstance(resume_url, str) and resume_url.startswith("wss://"):
                self._resume_url = resume_url
            self._sequence = sequence
            self._mark_authenticated(session_id, resumable=True)
            return
        if event_type == "RESUMED":
            if not self._session_id:
                raise ConnectorAuthenticationError("RESUMED has no local session")
            self._sequence = sequence
            self._mark_authenticated(self._session_id, resumable=True)
            return
        if self._capability is None or self._session_id is None:
            raise ConnectorAuthenticationError("dispatch arrived before session authentication")
        if self._sequence is not None and sequence <= self._sequence:
            return
        if not self._is_message_event(event_type):
            self._sequence = sequence
            return
        if self._is_self_or_bot(data):
            self._sequence = sequence
            return
        event = self._normalize(frame)
        self._accept(event, session_id=self._session_id, sequence=sequence)

    def _is_message_event(self, event_type: str) -> bool:
        raise NotImplementedError

    def _is_self_or_bot(self, data: Mapping[str, Any]) -> bool:
        author = data.get("author")
        return isinstance(author, Mapping) and author.get("bot") is True

    async def _send(self, payload: Mapping[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":"))
        if len(raw.encode()) > 4096:
            raise ConnectorProtocolError("gateway outbound frame exceeds the provider limit")
        await self._socket.send(raw)

    async def _heartbeat_loop(self, interval: float, acknowledged: asyncio.Event) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                if not acknowledged.is_set():
                    await self._socket.close(code=4000, reason="heartbeat timeout")
                    raise ConnectorProtocolError("gateway heartbeat acknowledgement timed out")
                acknowledged.clear()
                await self._send({"op": 1, "d": self._sequence})
        except asyncio.CancelledError:
            raise

    def _invalidate_session(self) -> None:
        self._session_id = None
        self._sequence = None
        self._resume_url = None
        self._remove_capability()
        self._snapshot = replace(
            self._snapshot, authenticated=False, session_resumable=False,
            last_sequence=None,
        )


__all__ = ["OpcodeGatewayConnector"]
