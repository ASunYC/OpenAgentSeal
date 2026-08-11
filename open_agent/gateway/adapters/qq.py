from __future__ import annotations

from typing import Mapping
from urllib.parse import quote
from open_agent.gateway.contracts import ChannelCapabilities, NormalizedInboundEvent, OutboundMessage
from .base_http import AdapterAuthenticationError, HttpTransport, classify_response, delivery_id, parse_object, platform_message_id, required_identifier, required_string


class QQAdapter:
    kind="qq"
    capabilities=ChannelCapabilities(supports_replies=True,max_message_chars=2000,acknowledgement_deadline_seconds=5)
    def __init__(self,*,account_id:str,transport:HttpTransport,access_token:str,app_id:str)->None:
        self.account_id,self.transport=required_string(account_id,"account_id"),transport; self._token=required_string(access_token,"access_token"); self._app_id=required_string(app_id,"app_id")
    def verify_webhook(self,raw_body:bytes,headers:Mapping[str,str],**_:object)->bool:
        del raw_body, headers
        raise AdapterAuthenticationError("QQ adapter uses authenticated Gateway transport, not webhooks")
    def challenge_response(self,raw_body:bytes,**_:object): del raw_body; return None
    def normalize(self,raw_payload:bytes)->NormalizedInboundEvent:
        outer=parse_object(raw_payload); p=outer.get("d") if isinstance(outer.get("d"),Mapping) else outer; author=p.get("author") or {}; event_type=str(outer.get("t") or "")
        conversation=p.get("group_openid") or p.get("channel_id") or author.get("user_openid")
        sender=author.get("member_openid") or author.get("user_openid") or author.get("id")
        destination_kind="c2c" if "C2C" in event_type else ("group" if p.get("group_openid") else "channel")
        return NormalizedInboundEvent(event_key=required_identifier(outer.get("id") or p.get("id"),"event.id"),adapter_kind=self.kind,account_id=self.account_id,conversation_id=required_identifier(conversation,"conversation"),sender_id=required_identifier(sender,"author"),conversation_kind="dm" if destination_kind=="c2c" else "group",text=str(p.get("content") or ""),mentioned_bot="AT_MESSAGE" in event_type or self._app_id in str(p.get("content") or ""),replies_to_bot=bool(p.get("message_reference")),metadata={"message_id":required_identifier(p.get("id"),"message.id"),"event_type":event_type,"qq_destination_kind":destination_kind,"gateway_sequence":outer.get("s")})
    async def send(self,message:OutboundMessage):
        kind=message.metadata.get("qq_destination_kind","group"); encoded=quote(message.conversation_id,safe="")
        if kind=="c2c": url=f"https://api.sgroup.qq.com/v2/users/{encoded}/messages"
        elif kind=="channel": url=f"https://api.sgroup.qq.com/channels/{encoded}/messages"
        else: url=f"https://api.sgroup.qq.com/v2/groups/{encoded}/messages"
        body={"content":message.content,"msg_type":0}
        if message.metadata.get("reply_message_id"): body["msg_id"]=message.metadata["reply_message_id"]
        response=await self.transport.request("POST",url,headers={"authorization":f"QQBot {self._token}","x-union-appid":self._app_id,"content-type":"application/json"},json_body=body,allowed_hosts=frozenset({"api.sgroup.qq.com"}))
        payload=classify_response(response); return {"platform_message_id":platform_message_id(payload),"delivery_id":delivery_id(message)}
