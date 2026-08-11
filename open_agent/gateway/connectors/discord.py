from __future__ import annotations

import asyncio
import secrets
from typing import Any, Mapping

from .opcode_gateway import OpcodeGatewayConnector


class DiscordGatewayConnector(OpcodeGatewayConnector):
    """Discord Gateway v10 per discord/discord-api-docs."""

    kind = "discord"
    api_version = 10
    gateway_api_url = "https://discord.com/api/v10/gateway/bot"
    gateway_api_hosts = frozenset({"discord.com"})
    gateway_hosts = frozenset({"gateway.discord.gg", "gateway-*.discord.gg"})

    async def _wait_invalid_session(self) -> None:
        # Discord Gateway requires a random 1-5 second delay before the next
        # IDENTIFY or RESUME after INVALID_SESSION.
        await asyncio.sleep(1.0 + secrets.randbelow(4001) / 1000.0)

    def _gateway_headers(self) -> Mapping[str, str]:
        return {"authorization": f"Bot {self.credential['bot_token']}"}

    def _gateway_token(self) -> str:
        return str(self.credential["bot_token"])

    def _identify_payload(self) -> Mapping[str, Any]:
        return {
            "op": 2,
            "d": {
                "token": self._gateway_token(),
                "intents": self.credential["intents"],
                "properties": {
                    "os": "windows", "browser": "open-agent-seal",
                    "device": "open-agent-seal",
                },
            },
        }

    def _is_message_event(self, event_type: str) -> bool:
        return event_type in {"MESSAGE_CREATE", "MESSAGE_UPDATE"}

    def _is_self_or_bot(self, data: Mapping[str, Any]) -> bool:
        author = data.get("author")
        return isinstance(author, Mapping) and (
            author.get("bot") is True
            or str(author.get("id")) == str(self.credential["application_id"])
        )


__all__ = ["DiscordGatewayConnector"]
