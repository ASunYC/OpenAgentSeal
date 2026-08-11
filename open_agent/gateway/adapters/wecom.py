from __future__ import annotations

from typing import Awaitable, Callable, Mapping
from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage
from .base_http import AdapterAuthenticationError, AdapterRejected, delivery_id, parse_object, platform_message_id, required_identifier, required_string


class WeComAdapter:
    kind="wecom"
    capabilities=ChannelCapabilities(supports_replies=True,max_message_chars=2048,acknowledgement_deadline_seconds=5)
    def __init__(self,*,account_id:str,bot_id:str,gateway_sender:Callable[[str,str,str],Awaitable[Mapping[str,object]]])->None:
        self.account_id=required_string(account_id,"account_id"); self._bot_id=required_string(bot_id,"bot_id"); self.gateway_sender=gateway_sender
    def verify_webhook(self,raw_body:bytes,headers:Mapping[str,str],**_:object)->bool:
        del raw_body, headers
        raise AdapterAuthenticationError("WeCom AI Bot uses authenticated WebSocket transport, not webhooks")
    def challenge_response(self,raw_body:bytes,**_:object): del raw_body; return None
    def normalize(self,raw_payload:bytes)->NormalizedInboundEvent:
        p=parse_object(raw_payload); headers=p.get("headers") or {}; body=p.get("body") or {}; sender=body.get("from") or {}; text=body.get("text") or {}; quote=body.get("quote") or {}
        message_id=required_identifier(body.get("msgid") or headers.get("req_id"),"message.id")
        request_id=required_identifier(headers.get("req_id"),"headers.req_id")
        return NormalizedInboundEvent(event_key=message_id,adapter_kind=self.kind,account_id=self.account_id,conversation_id=required_identifier(body.get("chatid") or sender.get("userid"),"conversation"),sender_id=required_identifier(sender.get("userid"),"sender.userid"),conversation_kind="dm" if body.get("chattype")=="single" else "group",text=str(text.get("content") or ""),mentioned_bot=body.get("mentioned_bot") is True or f"@{self._bot_id}" in str(text.get("content") or ""),replies_to_bot=isinstance(quote,Mapping) and quote.get("from_bot") is True,metadata={"wecom_transport":"aibot_gateway","wecom_request_id":request_id,"message_id":message_id})
    async def send(self,message:OutboundMessage):
        if message.metadata.get("wecom_transport") != "aibot_gateway": raise AdapterRejected("WeCom AI Bot requires its originating gateway frame")
        request_id=required_identifier(message.metadata.get("wecom_request_id"),"metadata.wecom_request_id")
        payload=await self.gateway_sender(request_id,message.content,delivery_id(message))
        if not isinstance(payload,Mapping) or payload.get("errcode") not in (None,0): raise AdapterRejected("WeCom rejected delivery")
        return {"platform_message_id":platform_message_id(payload),"delivery_id":delivery_id(message)}
