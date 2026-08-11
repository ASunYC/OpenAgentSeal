from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Mapping

from .base import BaseGatewayConnector
from .contracts import ConnectorAuthenticationError, ConnectorProtocolError
from .transport import decode_gateway_frame


class WeComAIBotConnector(BaseGatewayConnector):
    """Official WeCom AI Bot long connection protocol."""

    kind = "wecom"
    WS_URL = "wss://openws.work.weixin.qq.com"
    WS_HOSTS = frozenset({"openws.work.weixin.qq.com"})

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pending: dict[str, asyncio.Future[Mapping[str, Any]]] = {}

    async def _run_session(self) -> None:
        self._socket = await self.network.connect(
            self.WS_URL, allowed_hosts=self.WS_HOSTS,
            max_frame_bytes=self.limits.max_frame_bytes,
        )
        auth_id = f"aibot_subscribe-{uuid.uuid4().hex}"
        await self._send({
            "cmd": "aibot_subscribe", "headers": {"req_id": auth_id},
            "body": {"bot_id": self.credential["bot_id"], "secret": self.credential["secret"]},
        })
        auth = decode_gateway_frame(await self._socket.recv(), self.limits)
        ack_id = (auth.get("headers") or {}).get("req_id")
        if auth.get("errcode") != 0 or not isinstance(ack_id, str) or not ack_id.startswith("aibot_subscribe"):
            raise ConnectorAuthenticationError("WeCom rejected connector credentials")
        session_id = f"wecom-{self.connector_id}"
        self._mark_authenticated(session_id, resumable=False)
        sequence = int(self._expected.get("gateway_sequence") or 0)
        while True:
            frame = decode_gateway_frame(await self._socket.recv(), self.limits)
            headers = frame.get("headers")
            request_id = headers.get("req_id") if isinstance(headers, Mapping) else None
            if isinstance(request_id, str) and request_id in self._pending:
                future = self._pending.pop(request_id)
                if not future.done():
                    future.set_result(frame)
                continue
            command = frame.get("cmd")
            if command not in {"aibot_msg_callback", "aibot_event_callback"}:
                continue
            if not isinstance(request_id, str) or not request_id or len(request_id) > 512:
                raise ConnectorProtocolError("WeCom callback req_id is invalid")
            body = frame.get("body")
            if not isinstance(body, Mapping):
                raise ConnectorProtocolError("WeCom callback body is invalid")
            if command == "aibot_event_callback" and body.get("eventtype") != "enter_chat":
                continue
            sequence += 1
            event = self._normalize(frame)
            self._accept(event, session_id=session_id, sequence=sequence)

    async def send_reply(
        self, request_id: str, content: str, delivery_key: str
    ) -> Mapping[str, Any]:
        del delivery_key
        if self._socket is None or not self._snapshot.authenticated:
            raise ConnectorProtocolError("WeCom connector is not available")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 512:
            raise ValueError("request_id must be bounded")
        if not isinstance(content, str) or len(content) > 2048:
            raise ValueError("content exceeds WeCom reply limit")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Mapping[str, Any]] = loop.create_future()
        if request_id in self._pending:
            raise ConnectorProtocolError("WeCom request already has an in-flight reply")
        self._pending[request_id] = future
        try:
            await self._send({
                "cmd": "aibot_respond_msg", "headers": {"req_id": request_id},
                "body": {"msgtype": "stream", "stream": {
                    "id": f"oas-{uuid.uuid4().hex}", "finish": True, "content": content,
                }},
            })
            return await asyncio.wait_for(future, timeout=5)
        finally:
            self._pending.pop(request_id, None)

    async def _send(self, payload: Mapping[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode()) > self.limits.max_frame_bytes:
            raise ConnectorProtocolError("WeCom outbound frame exceeds the limit")
        await self._socket.send(raw)

    async def _close_socket(self) -> None:
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(ConnectorProtocolError("WeCom connector closed"))
        self._pending.clear()
        await super()._close_socket()


__all__ = ["WeComAIBotConnector"]
