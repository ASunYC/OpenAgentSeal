from __future__ import annotations

import hmac
from typing import Mapping

from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage

from .base_http import AdapterAuthenticationError, AdapterRejected, HttpTransport, classify_response, delivery_id, parse_object, platform_message_id, required_identifier, required_string


class TelegramAdapter:
    kind = "telegram"
    capabilities = ChannelCapabilities(supports_replies=True, supports_webhook=True, max_message_chars=4096, acknowledgement_deadline_seconds=10)

    def __init__(self, *, account_id: str, transport: HttpTransport, bot_token: str, webhook_secret: str, bot_id: str, bot_username: str) -> None:
        self.account_id = required_string(account_id, "account_id")
        self.transport = transport
        self._bot_token = required_string(bot_token, "bot_token")
        self._webhook_secret = required_string(webhook_secret, "webhook_secret")
        self._bot_id = required_string(bot_id, "bot_id")
        self._bot_username = required_string(bot_username, "bot_username").lstrip("@").lower()

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str], **_: object) -> bool:
        del raw_body
        supplied = next((v for k, v in headers.items() if k.lower() == "x-telegram-bot-api-secret-token"), "")
        if not hmac.compare_digest(supplied, self._webhook_secret):
            raise AdapterAuthenticationError("invalid Telegram webhook secret")
        return True

    def challenge_response(self, raw_body: bytes, **_: object):
        del raw_body
        return None

    def normalize(self, raw_payload: bytes) -> NormalizedInboundEvent:
        payload = parse_object(raw_payload)
        message = payload.get("message") or payload.get("edited_message") or payload.get("channel_post")
        if not isinstance(message, Mapping):
            raise ValueError("Telegram update has no supported message")
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, Mapping) or not isinstance(sender, Mapping):
            raise ValueError("Telegram message identity is incomplete")
        text = str(message.get("text") or message.get("caption") or "")
        entities = message.get("entities") or message.get("caption_entities") or ()
        mentioned = f"@{self._bot_username}" in text.lower() or any(
            isinstance(item, Mapping) and item.get("type") == "text_mention" and str((item.get("user") or {}).get("id")) == self._bot_id
            for item in entities if isinstance(entities, (list, tuple))
        )
        reply = message.get("reply_to_message")
        reply_sender = reply.get("from") if isinstance(reply, Mapping) else None
        return NormalizedInboundEvent(
            event_key=required_identifier(payload.get("update_id"), "update_id"), adapter_kind=self.kind, account_id=self.account_id,
            conversation_id=required_identifier(chat.get("id"), "chat.id"), sender_id=required_identifier(sender.get("id"), "from.id"),
            conversation_kind="dm" if chat.get("type") == "private" else "group", text=text,
            mentioned_bot=mentioned, replies_to_bot=isinstance(reply_sender, Mapping) and (str(reply_sender.get("id")) == self._bot_id or reply_sender.get("is_bot") is True),
            metadata={"message_id": str(message.get("message_id")), "sender_is_bot": sender.get("is_bot") is True or str(sender.get("id")) == self._bot_id},
        )

    async def send(self, message: OutboundMessage):
        body = {"chat_id": message.conversation_id, "text": message.content}
        if message.reply_to_event_key:
            reply_id = message.metadata.get("reply_message_id")
            if reply_id is not None:
                body["reply_parameters"] = {"message_id": reply_id}
        response = await self.transport.request("POST", f"https://api.telegram.org/bot{self._bot_token}/sendMessage", headers={"content-type": "application/json"}, json_body=body, allowed_hosts=frozenset({"api.telegram.org"}))
        payload = classify_response(response)
        if payload.get("ok") is False:
            raise AdapterRejected("Telegram rejected delivery")
        result = payload.get("result") if isinstance(payload.get("result"), Mapping) else payload
        return {"platform_message_id": platform_message_id(result), "delivery_id": delivery_id(message)}
