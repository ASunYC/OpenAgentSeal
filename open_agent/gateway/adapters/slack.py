from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Mapping

from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage

from .base_http import AdapterAuthenticationError, AdapterRejected, HttpTransport, classify_response, delivery_id, parse_object, platform_message_id, required_identifier, required_string


class SlackAdapter:
    kind = "slack"
    capabilities = ChannelCapabilities(supports_threads=True, supports_replies=True, supports_webhook=True, max_message_chars=40000, acknowledgement_deadline_seconds=3)

    def __init__(self, *, account_id: str, transport: HttpTransport, bot_token: str, signing_secret: str, bot_user_id: str) -> None:
        self.account_id, self.transport = required_string(account_id, "account_id"), transport
        self._token, self._secret, self._bot_id = required_string(bot_token, "bot_token"), required_string(signing_secret, "signing_secret").encode(), required_string(bot_user_id, "bot_user_id")

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str], *, now: datetime | None = None, **_: object) -> bool:
        normalized = {k.lower(): v for k, v in headers.items()}
        stamp, supplied = normalized.get("x-slack-request-timestamp", ""), normalized.get("x-slack-signature", "")
        try:
            sent = datetime.fromtimestamp(int(stamp), timezone.utc)
        except (ValueError, OverflowError) as exc:
            raise AdapterAuthenticationError("invalid Slack timestamp") from exc
        current = now or datetime.now(timezone.utc)
        if abs((current - sent).total_seconds()) > 300:
            raise AdapterAuthenticationError("stale Slack callback")
        expected = "v0=" + hmac.new(self._secret, b"v0:" + stamp.encode() + b":" + raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise AdapterAuthenticationError("invalid Slack signature")
        return True

    def challenge_response(self, raw_body: bytes, **_: object):
        payload = parse_object(raw_body)
        return {"challenge": payload["challenge"]} if payload.get("type") == "url_verification" and isinstance(payload.get("challenge"), str) else None

    def normalize(self, raw_payload: bytes) -> NormalizedInboundEvent:
        outer = parse_object(raw_payload); event = outer.get("event")
        if not isinstance(event, Mapping): raise ValueError("Slack event is missing")
        text = str(event.get("text") or "")
        return NormalizedInboundEvent(event_key=required_identifier(outer.get("event_id"), "event_id"), adapter_kind=self.kind, account_id=self.account_id, conversation_id=required_identifier(event.get("channel"), "event.channel"), sender_id=required_identifier(event.get("user"), "event.user"), conversation_kind="dm" if str(event.get("channel_type")) == "im" else "group", text=text, mentioned_bot=event.get("type") == "app_mention" or f"<@{self._bot_id}>" in text, replies_to_bot=event.get("parent_user_id") == self._bot_id, metadata={"message_ts": required_identifier(event.get("ts"), "event.ts"), "thread_ts": event.get("thread_ts"), "sender_is_bot": event.get("bot_id") is not None or event.get("subtype") == "bot_message" or event.get("user") == self._bot_id})

    async def send(self, message: OutboundMessage):
        body = {"channel": message.conversation_id, "text": message.content, "unfurl_links": False, "unfurl_media": False}
        if message.metadata.get("thread_ts"): body["thread_ts"] = message.metadata["thread_ts"]
        response = await self.transport.request("POST", "https://slack.com/api/chat.postMessage", headers={"authorization": f"Bearer {self._token}", "content-type": "application/json"}, json_body=body, allowed_hosts=frozenset({"slack.com"}))
        payload = classify_response(response)
        if payload.get("ok") is False: raise AdapterRejected("Slack rejected delivery")
        return {"platform_message_id": platform_message_id(payload), "delivery_id": delivery_id(message)}
