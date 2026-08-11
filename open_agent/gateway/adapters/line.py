from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Mapping

from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage
from .base_http import AdapterAuthenticationError, HttpTransport, classify_response, delivery_id, parse_object, platform_message_id, required_identifier, required_string, uuid_idempotency_key


class LineAdapter:
    kind = "line"
    capabilities = ChannelCapabilities(supports_idempotency=True, supports_webhook=True, max_message_chars=5000, acknowledgement_deadline_seconds=10)
    def __init__(self, *, account_id: str, transport: HttpTransport, channel_access_token: str, channel_secret: str, bot_user_id: str) -> None:
        self.account_id,self.transport=required_string(account_id,"account_id"),transport; self._token=required_string(channel_access_token,"channel_access_token"); self._secret=required_string(channel_secret,"channel_secret").encode(); self._bot_id=required_string(bot_user_id,"bot_user_id")
    def verify_webhook(self, raw_body: bytes, headers: Mapping[str,str], **_:object)->bool:
        supplied=next((v for k,v in headers.items() if k.lower()=="x-line-signature"),""); expected=base64.b64encode(hmac.new(self._secret,raw_body,hashlib.sha256).digest()).decode()
        if not hmac.compare_digest(supplied,expected): raise AdapterAuthenticationError("invalid LINE webhook signature")
        return True
    def challenge_response(self,raw_body:bytes,**_:object): del raw_body; return None
    def normalize(self,raw_payload:bytes)->NormalizedInboundEvent:
        p=parse_object(raw_payload)
        try: event=p["events"][0]
        except (KeyError,IndexError,TypeError) as exc: raise ValueError("LINE message event is missing") from exc
        return self._normalize_event(event)
    def normalize_many(self,raw_payload:bytes)->tuple[NormalizedInboundEvent,...]:
        p=parse_object(raw_payload); events=p.get("events")
        if not isinstance(events,list) or not events: raise ValueError("LINE event batch is missing")
        if len(events)>100: raise ValueError("LINE event batch exceeds 100 messages")
        return tuple(self._normalize_event(event) for event in events)
    def _normalize_event(self,event:Mapping[str,object])->NormalizedInboundEvent:
        source=event.get("source"); message=event.get("message")
        if not isinstance(source,Mapping) or not isinstance(message,Mapping): raise ValueError("LINE message event is incomplete")
        mention=message.get("mention") or {}; mentionees=mention.get("mentionees") or ()
        conversation=source.get("groupId") or source.get("roomId") or source.get("userId")
        return NormalizedInboundEvent(event_key=required_identifier(event.get("webhookEventId"),"webhookEventId"),adapter_kind=self.kind,account_id=self.account_id,conversation_id=required_identifier(conversation,"source conversation"),sender_id=required_identifier(source.get("userId"),"source.userId"),conversation_kind="dm" if source.get("type")=="user" else "group",text=str(message.get("text") or ""),mentioned_bot=any(isinstance(x,Mapping) and (x.get("isSelf") is True or x.get("userId")==self._bot_id) for x in mentionees),replies_to_bot=bool(event.get("quotedMessageId")),metadata={"message_id":required_identifier(message.get("id"),"message.id")})
    async def send(self,message:OutboundMessage):
        identifier=delivery_id(message); body={"to":message.conversation_id,"messages":[{"type":"text","text":message.content}]}
        response=await self.transport.request("POST","https://api.line.me/v2/bot/message/push",headers={"authorization":f"Bearer {self._token}","content-type":"application/json","x-line-retry-key":uuid_idempotency_key(identifier)},json_body=body,allowed_hosts=frozenset({"api.line.me"}))
        payload=classify_response(response)
        return {"platform_message_id":platform_message_id(payload),"delivery_id":identifier}
