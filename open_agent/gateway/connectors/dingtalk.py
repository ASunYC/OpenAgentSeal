from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import quote_plus

from .base import BaseGatewayConnector
from .contracts import ConnectorProtocolError
from .transport import decode_gateway_frame


class DingTalkStreamConnector(BaseGatewayConnector):
    """DingTalk Stream client matching open-dingtalk's official SDK."""

    kind = "dingtalk"
    OPEN_URL = "https://api.dingtalk.com/v1.0/gateway/connections/open"
    API_HOSTS = frozenset({"api.dingtalk.com"})
    STREAM_HOSTS = frozenset({
        "wss-open-connection.dingtalk.com", "open-connection.dingtalk.com",
        "wss-gw.dingtalk.com",
    })
    MESSAGE_TOPIC = "/v1.0/im/bot/messages/get"

    async def _run_session(self) -> None:
        opened = await self._http_json(
            "POST", self.OPEN_URL,
            headers={"content-type": "application/json", "accept": "application/json"},
            body={
                "clientId": self.credential["client_id"],
                "clientSecret": self.credential["client_secret"],
                "subscriptions": [{"type": "CALLBACK", "topic": self.MESSAGE_TOPIC}],
                "ua": "open-agent-seal/1.0",
            },
            allowed_hosts=self.API_HOSTS,
        )
        endpoint, ticket = opened.get("endpoint"), opened.get("ticket")
        if not isinstance(endpoint, str) or not isinstance(ticket, str) or not ticket:
            raise ConnectorProtocolError("DingTalk connection response is incomplete")
        url = f"{endpoint}?ticket={quote_plus(ticket)}"
        self._socket = await self.network.connect(
            url, allowed_hosts=self.STREAM_HOSTS,
            max_frame_bytes=self.limits.max_frame_bytes,
        )
        fallback_session = f"stream-{self.connector_id}"
        self._mark_authenticated(fallback_session, resumable=False)
        sequence = int(self._expected.get("gateway_sequence") or 0)
        while True:
            frame = decode_gateway_frame(await self._socket.recv(), self.limits)
            headers = frame.get("headers")
            if not isinstance(headers, Mapping):
                raise ConnectorProtocolError("DingTalk frame headers are missing")
            message_type = frame.get("type")
            if message_type == "SYSTEM":
                await self._send_ack(headers, 200, "OK")
                if headers.get("topic") == "disconnect":
                    raise EOFError("DingTalk requested disconnect")
                continue
            if message_type != "CALLBACK" or headers.get("topic") != self.MESSAGE_TOPIC:
                continue
            message_id = headers.get("messageId")
            if not isinstance(message_id, str) or not message_id or len(message_id) > 512:
                raise ConnectorProtocolError("DingTalk callback messageId is invalid")
            data = frame.get("data")
            if isinstance(data, str):
                if len(data.encode()) > self.limits.max_decompressed_bytes:
                    raise ConnectorProtocolError("DingTalk callback data exceeds the limit")
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    raise ConnectorProtocolError("DingTalk callback data is invalid") from None
            if not isinstance(data, Mapping):
                raise ConnectorProtocolError("DingTalk callback data must be an object")
            session_id = headers.get("connectionId")
            if not isinstance(session_id, str) or not session_id:
                session_id = fallback_session
            if self._session_id != session_id:
                self._remove_capability()
                self._mark_authenticated(session_id, resumable=False)
                sequence = 0
            sequence += 1
            event = self._normalize(data)
            self._accept(event, session_id=session_id, sequence=sequence)
            await self._send_ack(headers, 200, "OK")

    async def _send_ack(self, headers: Mapping[str, Any], code: int, message: str) -> None:
        allowed = {
            str(key): value for key, value in headers.items()
            if isinstance(key, str) and len(key) <= 128
            and isinstance(value, (str, int, bool)) and len(str(value)) <= 1024
        }
        payload = {"code": code, "headers": allowed, "message": message, "data": ""}
        await self._socket.send(json.dumps(payload, separators=(",", ":")))


__all__ = ["DingTalkStreamConnector"]
