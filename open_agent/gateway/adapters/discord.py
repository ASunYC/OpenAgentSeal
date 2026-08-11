from __future__ import annotations

from typing import Mapping
from urllib.parse import quote

from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage

from .base_http import AdapterAuthenticationError, HttpTransport, classify_response, compact_idempotency_key, delivery_id, parse_object, platform_message_id, required_identifier, required_string


class DiscordAdapter:
    kind = "discord"
    capabilities = ChannelCapabilities(supports_threads=True, supports_replies=True, supports_idempotency=True, max_message_chars=2000, acknowledgement_deadline_seconds=3)

    def __init__(self, *, account_id: str, transport: HttpTransport, bot_token: str, application_id: str) -> None:
        self.account_id, self.transport = required_string(account_id, "account_id"), transport
        self._token = required_string(bot_token, "bot_token")
        self._app_id = required_string(application_id, "application_id")

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str], **_: object) -> bool:
        del raw_body, headers
        raise AdapterAuthenticationError("Discord message ingress uses authenticated Gateway transport, not interaction webhooks")

    def challenge_response(self, raw_body: bytes, **_: object):
        del raw_body
        return None

    def normalize(self, raw_payload: bytes) -> NormalizedInboundEvent:
        return self.normalize_gateway(raw_payload)

    def normalize_gateway(self, raw_payload: bytes) -> NormalizedInboundEvent:
        """Normalize a frame received by an authenticated Discord Gateway client."""
        outer = parse_object(raw_payload)
        data = outer.get("d") if isinstance(outer.get("d"), Mapping) else outer.get("data", outer)
        if not isinstance(data, Mapping):
            raise ValueError("Discord message data is missing")
        author = data.get("author") or data.get("member", {}).get("user")
        if not isinstance(author, Mapping):
            raise ValueError("Discord author is missing")
        mentions = data.get("mentions") or ()
        referenced = data.get("referenced_message")
        return NormalizedInboundEvent(
            event_key=required_identifier(data.get("id") or outer.get("id"), "message.id"), adapter_kind=self.kind, account_id=self.account_id,
            conversation_id=required_identifier(data.get("channel_id"), "channel_id"), sender_id=required_identifier(author.get("id"), "author.id"),
            conversation_kind="group" if data.get("guild_id") else "dm", text=str(data.get("content") or ""),
            mentioned_bot=any(isinstance(item, Mapping) and str(item.get("id")) == self._app_id for item in mentions),
            replies_to_bot=isinstance(referenced, Mapping) and isinstance(referenced.get("author"), Mapping) and (str(referenced["author"].get("id")) == self._app_id or referenced["author"].get("bot") is True),
            metadata={"gateway_sequence": outer.get("s"), "message_id": str(data.get("id")), "sender_is_bot": author.get("bot") is True or str(author.get("id")) == self._app_id},
        )

    async def send(self, message: OutboundMessage):
        identifier = delivery_id(message)
        body = {"content": message.content, "nonce": compact_idempotency_key(identifier), "enforce_nonce": True, "allowed_mentions": {"parse": []}}
        if message.metadata.get("reply_message_id"):
            body["message_reference"] = {"message_id": message.metadata["reply_message_id"]}
        response = await self.transport.request("POST", f"https://discord.com/api/v10/channels/{quote(message.conversation_id, safe='')}/messages", headers={"authorization": f"Bot {self._token}", "content-type": "application/json"}, json_body=body, allowed_hosts=frozenset({"discord.com"}))
        payload = classify_response(response)
        return {"platform_message_id": platform_message_id(payload), "delivery_id": identifier}
