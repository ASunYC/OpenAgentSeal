from __future__ import annotations

import asyncio
import json
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import DurableRuntimeRepository, StateConflictError
from open_agent.gateway.adapters import DingTalkAdapter, DiscordAdapter, QQAdapter, WeComAdapter
from open_agent.gateway.adapters.base_http import HttpResponse
from open_agent.gateway.connectors import (
    ConnectorLimits,
    ConnectorProtocolError,
    DingTalkStreamConnector,
    DiscordGatewayConnector,
    QQGatewayConnector,
    WeComAIBotConnector,
    decode_gateway_frame,
    parse_connector_credential,
)


NOW = datetime(2026, 8, 12, 8, tzinfo=timezone.utc)


class FakeHttp:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def request(self, method, url, *, headers=None, json_body=None, allowed_hosts):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "json": json_body, "allowed_hosts": allowed_hosts})
        return HttpResponse(200, {}, json.dumps(self.payload).encode())


class FakeSocket:
    def __init__(self, frames: list[object]) -> None:
        self.frames = list(frames)
        self.sent: list[dict] = []
        self.closed = False
        self.pings = 0

    async def recv(self):
        if not self.frames:
            raise EOFError("test socket exhausted")
        value = self.frames.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def send(self, value):
        self.sent.append(json.loads(value) if isinstance(value, str) else value)

    async def ping(self):
        self.pings += 1

    async def close(self, code=1000, reason=""):
        self.closed = True


class FakeNetwork:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket
        self.urls: list[str] = []

    async def connect(self, url, *, allowed_hosts, max_frame_bytes):
        self.urls.append(url)
        assert url.startswith("wss://")
        assert url.split("/", 3)[2].split(":", 1)[0] in allowed_hosts
        assert max_frame_bytes <= 1024 * 1024
        return self.socket


class FakeIngress:
    def __init__(self, repository: DurableRuntimeRepository, *, fail=False) -> None:
        self.repository = repository
        self.fail = fail
        self.accepted = []
        self.committed = []

    def accept_polled_event(self, frame, *, transport_mode, gateway_session_id, gateway_sequence, claim, **_):
        if self.fail:
            raise StateConflictError("stale lease")
        assert transport_mode == "gateway"
        assert frame.gateway_session_id == gateway_session_id
        assert frame.gateway_sequence == gateway_sequence
        self.accepted.append(frame)
        return type("Receipt", (), {"event_key": frame.event.event_key})()

    def commit_checkpoint(self, account_id, transport_mode, **kwargs):
        self.committed.append((account_id, transport_mode, kwargs))
        return {
            "gateway_session_id": kwargs["gateway_session_id"],
            "gateway_sequence": kwargs["gateway_sequence"],
        }


def _repository(tmp_path: Path, kind: str) -> DurableRuntimeRepository:
    repo = DurableRuntimeRepository(ControlPlane(tmp_path / f"{kind}.db"))
    repo.upsert_channel_account(
        account_id="account-1", adapter_kind=kind, default_profile_id="main", now=NOW
    )
    return repo


def _claim(repo: DurableRuntimeRepository):
    return repo.claim_ingress_checkpoint(
        account_id="account-1", transport_mode="gateway", owner_id="connector-1",
        now=NOW, expires_at=NOW + timedelta(minutes=2),
    )["claim"]


def test_connector_credentials_are_strict_immutable_and_redacted():
    credential = parse_connector_credential(
        "discord", json.dumps({"bot_token": "secret-token", "application_id": "999", "intents": 33281})
    )
    assert credential["application_id"] == "999"
    assert credential["intents"] == 33281
    assert "secret-token" not in repr(credential)
    with pytest.raises(ValueError):
        parse_connector_credential("discord", '{"bot_token":"x","application_id":"1","extra":true}')


def test_decode_bounds_text_binary_and_decompression_bombs():
    assert decode_gateway_frame('{"op":10,"d":{}}', ConnectorLimits())["op"] == 10
    compressed = zlib.compress(b'{"op":10,"d":{}}')
    assert decode_gateway_frame(compressed, ConnectorLimits())["op"] == 10
    with pytest.raises(ConnectorProtocolError, match="limit"):
        decode_gateway_frame("x" * 100, ConnectorLimits(max_frame_bytes=32))
    bomb = zlib.compress(b"x" * 4096)
    with pytest.raises(ConnectorProtocolError, match="decompressed"):
        decode_gateway_frame(bomb, ConnectorLimits(max_frame_bytes=1024, max_decompressed_bytes=128))


@pytest.mark.asyncio
async def test_discord_identifies_then_durably_commits_dispatch(tmp_path):
    repo = _repository(tmp_path, "discord")
    ingress = FakeIngress(repo)
    socket = FakeSocket([
        {"op": 10, "d": {"heartbeat_interval": 60000}},
        {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "sess-1", "resume_gateway_url": "wss://gateway.discord.gg", "user": {"id": "999"}}},
        {"op": 0, "t": "MESSAGE_CREATE", "s": 2, "d": {"id": "m1", "channel_id": "c1", "content": "hello", "author": {"id": "u1", "bot": False}, "mentions": [{"id": "999"}]}},
        EOFError(),
    ])
    connector = DiscordGatewayConnector(
        account_id="account-1", adapter=DiscordAdapter(account_id="account-1", transport=FakeHttp({}), bot_token="secret-token", application_id="999"),
        ingress=ingress, repository=repo, network=FakeNetwork(socket), http=FakeHttp({"url": "wss://gateway.discord.gg", "shards": 1, "session_start_limit": {"remaining": 1, "max_concurrency": 1}}),
        credential=parse_connector_credential("discord", '{"bot_token":"secret-token","application_id":"999","intents":33281}'),
        now=lambda: NOW,
    )
    await connector.run_once()
    assert socket.sent[0]["op"] == 2
    assert socket.sent[0]["d"]["intents"] == 33281
    assert ingress.accepted[0].event.event_key == "m1"
    assert ingress.committed[0][2]["gateway_sequence"] == 2
    assert "secret-token" not in json.dumps(connector.snapshot().as_dict())


@pytest.mark.asyncio
async def test_discord_resumes_from_checkpoint_and_invalid_session_discards_resume(tmp_path):
    repo = _repository(tmp_path, "discord")
    ingress = FakeIngress(repo)
    socket = FakeSocket([
        {"op": 10, "d": {"heartbeat_interval": 60000}},
        {"op": 9, "d": False},
        EOFError(),
    ])
    connector = DiscordGatewayConnector(
        account_id="account-1", adapter=DiscordAdapter(account_id="account-1", transport=FakeHttp({}), bot_token="token", application_id="999"),
        ingress=ingress, repository=repo, network=FakeNetwork(socket), http=FakeHttp({"url": "wss://gateway.discord.gg"}),
        credential=parse_connector_credential("discord", '{"bot_token":"token","application_id":"999","intents":33281}'), now=lambda: NOW,
    )
    connector.restore_for_test(session_id="old-session", sequence=41, resume_url="wss://gateway.discord.gg")
    await connector.run_once()
    assert socket.sent[0]["op"] == 6
    assert socket.sent[0]["d"]["seq"] == 41
    assert connector.snapshot().session_resumable is False


@pytest.mark.asyncio
async def test_qq_uses_official_gateway_and_resume_opcodes(tmp_path):
    repo = _repository(tmp_path, "qq")
    ingress = FakeIngress(repo)
    socket = FakeSocket([
        {"op": 10, "d": {"heartbeat_interval": 60000}},
        {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "qq-session", "user": {"id": "qq-bot"}, "shard": [0, 1]}},
        {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "s": 2, "id": "e1", "d": {"id": "m1", "group_openid": "g1", "content": "@bot hi", "author": {"member_openid": "u1"}}},
        EOFError(),
    ])
    http = FakeHttp({"url": "wss://api.sgroup.qq.com/websocket", "shards": 1, "session_start_limit": {"remaining": 1, "max_concurrency": 1}})
    connector = QQGatewayConnector(
        account_id="account-1", adapter=QQAdapter(account_id="account-1", transport=http, access_token="token", app_id="qq-bot"),
        ingress=ingress, repository=repo, network=FakeNetwork(socket), http=http,
        credential=parse_connector_credential("qq", '{"access_token":"token","app_id":"qq-bot","intents":1073741824}'), now=lambda: NOW,
    )
    await connector.run_once()
    assert http.calls[0]["url"] == "https://api.sgroup.qq.com/gateway/bot"
    assert socket.sent[0]["op"] == 2
    assert ingress.committed[0][2]["gateway_sequence"] == 2


@pytest.mark.asyncio
async def test_dingtalk_ack_is_sent_only_after_durable_enqueue(tmp_path):
    repo = _repository(tmp_path, "dingtalk")
    ingress = FakeIngress(repo)
    callback = {"specVersion": "1.0", "type": "CALLBACK", "headers": {"messageId": "mid-1", "topic": "/v1.0/im/bot/messages/get", "connectionId": "ding-session"}, "data": json.dumps({"msgId": "msg-1", "conversationId": "conv-1", "senderId": "user-1", "conversationType": "2", "text": {"content": "hello"}, "isInAtList": True})}
    socket = FakeSocket([callback, EOFError()])
    http = FakeHttp({"endpoint": "wss://wss-open-connection.dingtalk.com/connect", "ticket": "ephemeral-ticket"})
    connector = DingTalkStreamConnector(
        account_id="account-1", adapter=DingTalkAdapter(account_id="account-1", transport=http, access_token="token", robot_code="robot"),
        ingress=ingress, repository=repo, network=FakeNetwork(socket), http=http,
        credential=parse_connector_credential("dingtalk", '{"client_id":"cid","client_secret":"secret","access_token":"token","robot_code":"robot"}'), now=lambda: NOW,
    )
    await connector.run_once()
    assert ingress.accepted and socket.sent
    assert socket.sent[-1]["code"] == 200
    assert socket.sent[-1]["headers"]["messageId"] == "mid-1"
    assert "ephemeral-ticket" not in json.dumps(connector.snapshot().as_dict())


@pytest.mark.asyncio
async def test_dingtalk_never_acks_when_durable_admission_fails(tmp_path):
    repo = _repository(tmp_path, "dingtalk")
    ingress = FakeIngress(repo, fail=True)
    callback = {"type": "CALLBACK", "headers": {"messageId": "mid-1", "topic": "/v1.0/im/bot/messages/get", "connectionId": "ding-session"}, "data": json.dumps({"msgId": "msg-1", "conversationId": "conv-1", "senderId": "user-1", "conversationType": "1", "text": {"content": "hello"}})}
    socket = FakeSocket([callback])
    http = FakeHttp({"endpoint": "wss://wss-open-connection.dingtalk.com/connect", "ticket": "ticket"})
    connector = DingTalkStreamConnector(account_id="account-1", adapter=DingTalkAdapter(account_id="account-1", transport=http, access_token="token", robot_code="robot"), ingress=ingress, repository=repo, network=FakeNetwork(socket), http=http, credential=parse_connector_credential("dingtalk", '{"client_id":"cid","client_secret":"secret","access_token":"token","robot_code":"robot"}'), now=lambda: NOW)
    with pytest.raises(StateConflictError):
        await connector.run_once()
    assert socket.sent == []


@pytest.mark.asyncio
async def test_wecom_authenticates_and_durably_accepts_callback(tmp_path):
    repo = _repository(tmp_path, "wecom")
    ingress = FakeIngress(repo)
    socket = FakeSocket([
        {"headers": {"req_id": "aibot_subscribe-1"}, "errcode": 0},
        {"cmd": "aibot_msg_callback", "headers": {"req_id": "req-1"}, "body": {"msgid": "m1", "chatid": "c1", "chattype": "single", "from": {"userid": "u1"}, "text": {"content": "hello"}}},
        EOFError(),
    ])
    async def sender(*_): return {"errcode": 0}
    connector = WeComAIBotConnector(
        account_id="account-1", adapter=WeComAdapter(account_id="account-1", bot_id="bot-1", gateway_sender=sender),
        ingress=ingress, repository=repo, network=FakeNetwork(socket),
        credential=parse_connector_credential("wecom", '{"bot_id":"bot-1","secret":"secret"}'), now=lambda: NOW,
    )
    await connector.run_once()
    assert socket.sent[0]["cmd"] == "aibot_subscribe"
    assert socket.sent[0]["body"] == {"bot_id": "bot-1", "secret": "secret"}
    assert ingress.accepted[0].event.event_key == "m1"
    assert connector.snapshot().authenticated is True


def test_repository_allows_only_one_live_connector_owner(tmp_path):
    repo = _repository(tmp_path, "discord")
    first = _claim(repo)
    with pytest.raises(StateConflictError, match="live owner"):
        repo.claim_ingress_checkpoint(account_id="account-1", transport_mode="gateway", owner_id="connector-2", now=NOW, expires_at=NOW + timedelta(minutes=2))
    renewed = repo.renew_ingress_checkpoint_claim(account_id="account-1", transport_mode="gateway", token=first, now=NOW + timedelta(seconds=10), expires_at=NOW + timedelta(minutes=3))
    assert renewed.generation == first.generation
    repo.release_ingress_checkpoint_claim(account_id="account-1", transport_mode="gateway", token=renewed, now=NOW + timedelta(seconds=11))
    second = repo.claim_ingress_checkpoint(account_id="account-1", transport_mode="gateway", owner_id="connector-2", now=NOW + timedelta(seconds=12), expires_at=NOW + timedelta(minutes=3))["claim"]
    assert second.owner_id == "connector-2"
