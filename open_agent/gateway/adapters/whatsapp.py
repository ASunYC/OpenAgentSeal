from __future__ import annotations

import hashlib
import hmac
from typing import Mapping
from urllib.parse import quote

from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage

from .base_http import AdapterAuthenticationError, HttpTransport, classify_response, delivery_id, parse_object, platform_message_id, required_identifier, required_string


class WhatsAppAdapter:
    kind = "whatsapp"
    capabilities = ChannelCapabilities(supports_webhook=True, max_message_chars=4096, acknowledgement_deadline_seconds=10)

    def __init__(self, *, account_id: str, transport: HttpTransport, access_token: str, app_secret: str, phone_number_id: str, verify_token: str, graph_version: str = "v23.0") -> None:
        self.account_id, self.transport = required_string(account_id, "account_id"), transport
        self._token, self._secret = required_string(access_token, "access_token"), required_string(app_secret, "app_secret").encode()
        self._phone_id, self._verify_token, self._version = required_string(phone_number_id, "phone_number_id"), required_string(verify_token, "verify_token"), required_string(graph_version, "graph_version")

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str], **_: object) -> bool:
        supplied = next((v for k, v in headers.items() if k.lower() == "x-hub-signature-256"), "")
        expected = "sha256=" + hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected): raise AdapterAuthenticationError("invalid WhatsApp signature")
        return True

    def challenge_response(self, raw_body: bytes, *, query: Mapping[str, str] | None = None, **_: object):
        del raw_body; query = query or {}
        if query.get("hub.mode") == "subscribe" and hmac.compare_digest(query.get("hub.verify_token", ""), self._verify_token): return query.get("hub.challenge")
        raise AdapterAuthenticationError("invalid WhatsApp verification challenge")

    def normalize(self, raw_payload: bytes) -> NormalizedInboundEvent:
        payload = parse_object(raw_payload)
        try: value = payload["entry"][0]["changes"][0]["value"]; message = value["messages"][0]
        except (KeyError, IndexError, TypeError) as exc: raise ValueError("WhatsApp message callback is missing") from exc
        return self._normalize_message(value,message)

    def normalize_many(self, raw_payload: bytes) -> tuple[NormalizedInboundEvent, ...]:
        payload=parse_object(raw_payload); normalized=[]
        entries=payload.get("entry")
        if not isinstance(entries,list): raise ValueError("WhatsApp entry batch is missing")
        for entry in entries:
            changes=entry.get("changes") if isinstance(entry,Mapping) else None
            if not isinstance(changes,list): continue
            for change in changes:
                value=change.get("value") if isinstance(change,Mapping) else None
                messages=value.get("messages") if isinstance(value,Mapping) else None
                if isinstance(messages,list):
                    for message in messages:
                        if len(normalized)>=100: raise ValueError("WhatsApp event batch exceeds 100 messages")
                        if isinstance(message,Mapping): normalized.append(self._normalize_message(value,message))
        if not normalized: raise ValueError("WhatsApp message callback is missing")
        return tuple(normalized)

    def _normalize_message(self,value:Mapping[str,object],message:Mapping[str,object])->NormalizedInboundEvent:
        content = message.get("text") if isinstance(message.get("text"), Mapping) else {}
        context = message.get("context") if isinstance(message.get("context"), Mapping) else {}
        sender = required_identifier(message.get("from"), "message.from")
        message_id = required_identifier(message.get("id"), "message.id")
        phone_id = required_identifier(value.get("metadata", {}).get("phone_number_id"), "metadata.phone_number_id")
        if phone_id != self._phone_id:
            raise ValueError("WhatsApp callback phone number does not match account")
        return NormalizedInboundEvent(event_key=message_id, adapter_kind=self.kind, account_id=self.account_id, conversation_id=sender, sender_id=sender, conversation_kind="dm", text=str(content.get("body") or ""), replies_to_bot=bool(context.get("id")), metadata={"message_id": message_id, "phone_number_id": phone_id})

    async def send(self, message: OutboundMessage):
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": message.conversation_id, "type": "text", "text": {"preview_url": False, "body": message.content}}
        response = await self.transport.request("POST", f"https://graph.facebook.com/{quote(self._version, safe='')}/{quote(self._phone_id, safe='')}/messages", headers={"authorization": f"Bearer {self._token}", "content-type": "application/json"}, json_body=body, allowed_hosts=frozenset({"graph.facebook.com"}))
        payload = classify_response(response); messages = payload.get("messages")
        result = messages[0] if isinstance(messages, list) and messages and isinstance(messages[0], Mapping) else payload
        return {"platform_message_id": platform_message_id(result), "delivery_id": delivery_id(message)}
