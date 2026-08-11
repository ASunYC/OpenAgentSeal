from __future__ import annotations

from typing import Any, Mapping

from .opcode_gateway import OpcodeGatewayConnector


class QQGatewayConnector(OpcodeGatewayConnector):
    """Tencent QQ Bot Gateway protocol implemented by official BotPy."""

    kind = "qq"
    api_version = 1
    gateway_api_url = "https://api.sgroup.qq.com/gateway/bot"
    gateway_api_hosts = frozenset({"api.sgroup.qq.com"})
    gateway_hosts = frozenset({"api.sgroup.qq.com", "sandbox.api.sgroup.qq.com"})

    def _gateway_headers(self) -> Mapping[str, str]:
        return {
            "authorization": f"QQBot {self.credential['access_token']}",
            "x-union-appid": str(self.credential["app_id"]),
        }

    def _gateway_token(self) -> str:
        return str(self.credential["access_token"])

    def _identify_payload(self) -> Mapping[str, Any]:
        return {
            "op": 2,
            "d": {
                "token": self._gateway_token(),
                "intents": self.credential["intents"],
                "shard": [0, 1],
            },
        }

    def _is_message_event(self, event_type: str) -> bool:
        return event_type in {
            "AT_MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE",
            "GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE", "MESSAGE_CREATE",
        }


__all__ = ["QQGatewayConnector"]
