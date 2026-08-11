from __future__ import annotations

import hashlib
import hmac
import json
from typing import Mapping

from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage
from .base_http import AdapterAuthenticationError, AdapterRejected, HttpTransport, classify_response, delivery_id, parse_object, platform_message_id, required_identifier, required_string


class FeishuAdapter:
    kind = "feishu"
    capabilities = ChannelCapabilities(supports_webhook=True, max_message_chars=30000, acknowledgement_deadline_seconds=3)
    def __init__(self, *, account_id: str, transport: HttpTransport, tenant_access_token: str, verification_token: str, encrypt_key: str, bot_open_id: str) -> None:
        self.account_id, self.transport = required_string(account_id,"account_id"), transport
        self._access_token, self._verification_token, self._encrypt_key, self._bot_id = required_string(tenant_access_token,"tenant_access_token"), required_string(verification_token,"verification_token"), required_string(encrypt_key,"encrypt_key"), required_string(bot_open_id,"bot_open_id")
    def verify_webhook(self, raw_body: bytes, headers: Mapping[str,str], **_: object) -> bool:
        payload = parse_object(raw_body); header = payload.get("header") or {}
        if isinstance(header, Mapping) and hmac.compare_digest(str(header.get("token") or payload.get("token") or ""), self._verification_token): return True
        normalized={k.lower():v for k,v in headers.items()}; stamp=normalized.get("x-lark-request-timestamp",""); nonce=normalized.get("x-lark-request-nonce","")
        expected=hashlib.sha256((stamp+nonce+self._encrypt_key).encode()+raw_body).hexdigest()
        if not hmac.compare_digest(normalized.get("x-lark-signature", ""),expected): raise AdapterAuthenticationError("invalid Feishu callback signature")
        return True
    def challenge_response(self, raw_body: bytes, **_: object):
        payload=parse_object(raw_body); return {"challenge":payload["challenge"]} if isinstance(payload.get("challenge"),str) else None
    def normalize(self, raw_payload: bytes) -> NormalizedInboundEvent:
        outer=parse_object(raw_payload); header=outer.get("header") or {}; event=outer.get("event") or {}; message=event.get("message") or {}; sender=event.get("sender") or {}; sender_id=sender.get("sender_id") or {}
        try: content=json.loads(message.get("content") or "{}")
        except json.JSONDecodeError: content={}
        mentions=message.get("mentions") or ()
        return NormalizedInboundEvent(event_key=required_identifier(header.get("event_id"),"header.event_id"),adapter_kind=self.kind,account_id=self.account_id,conversation_id=required_identifier(message.get("chat_id"),"message.chat_id"),sender_id=required_identifier(sender_id.get("open_id"),"sender.open_id"),conversation_kind="dm" if message.get("chat_type")=="p2p" else "group",text=str(content.get("text") or ""),mentioned_bot=any(isinstance(x,Mapping) and str((x.get("id") or {}).get("open_id"))==self._bot_id for x in mentions),replies_to_bot=bool(message.get("parent_id")),metadata={"message_id":required_identifier(message.get("message_id"),"message.message_id"),"parent_id":message.get("parent_id")})
    async def send(self,message:OutboundMessage):
        body={"receive_id":message.conversation_id,"msg_type":"text","content":json.dumps({"text":message.content},ensure_ascii=False)}
        response=await self.transport.request("POST","https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",headers={"authorization":f"Bearer {self._access_token}","content-type":"application/json"},json_body=body,allowed_hosts=frozenset({"open.feishu.cn"}))
        payload=classify_response(response)
        if payload.get("code") not in (None,0): raise AdapterRejected("Feishu rejected delivery")
        return {"platform_message_id":platform_message_id(payload),"delivery_id":delivery_id(message)}
