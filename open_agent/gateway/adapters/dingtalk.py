from __future__ import annotations

import json
from typing import Mapping

from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage
from .base_http import AdapterAuthenticationError, AdapterRejected, HttpTransport, classify_response, delivery_id, parse_object, platform_message_id, required_identifier, required_string


class DingTalkAdapter:
    kind="dingtalk"
    capabilities=ChannelCapabilities(max_message_chars=20000,acknowledgement_deadline_seconds=10)
    def __init__(self,*,account_id:str,transport:HttpTransport,access_token:str,robot_code:str)->None:
        self.account_id,self.transport=required_string(account_id,"account_id"),transport; self._token=required_string(access_token,"access_token"); self._bot_id=required_string(robot_code,"robot_code")
    def verify_webhook(self,raw_body:bytes,headers:Mapping[str,str],**_:object)->bool:
        del raw_body, headers
        raise AdapterAuthenticationError("DingTalk adapter uses authenticated Stream transport, not webhooks")
    def challenge_response(self,raw_body:bytes,**_:object): del raw_body; return None
    def normalize(self,raw_payload:bytes)->NormalizedInboundEvent:
        p=parse_object(raw_payload); text=p.get("text") or {}
        message_id=required_identifier(p.get("msgId"),"msgId")
        return NormalizedInboundEvent(event_key=message_id,adapter_kind=self.kind,account_id=self.account_id,conversation_id=required_identifier(p.get("conversationId"),"conversationId"),sender_id=required_identifier(p.get("senderId"),"senderId"),conversation_kind="dm" if str(p.get("conversationType"))=="1" else "group",text=str(text.get("content") or ""),mentioned_bot=p.get("isInAtList") is True,replies_to_bot=False,metadata={"message_id":message_id})
    async def send(self,message:OutboundMessage):
        identifier=delivery_id(message); body={"openConversationIds":[message.conversation_id],"robotCode":self._bot_id,"msgType":"text","msgContent":json.dumps({"content":message.content},ensure_ascii=False),"atAll":False}
        response=await self.transport.request("POST","https://api.dingtalk.com/v1.0/im/interconnections/robotMessages/send",headers={"x-acs-dingtalk-access-token":self._token,"content-type":"application/json"},json_body=body,allowed_hosts=frozenset({"api.dingtalk.com"}))
        payload=classify_response(response)
        if payload.get("success") is False or payload.get("errcode") not in (None,0): raise AdapterRejected("DingTalk rejected delivery")
        return {"platform_message_id":platform_message_id(payload),"delivery_id":identifier}
