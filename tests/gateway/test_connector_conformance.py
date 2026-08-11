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
    ConnectorManager,
    ConnectorLimits,
    ConnectorProtocolError,
    ConnectorSnapshot,
    DingTalkStreamConnector,
    DiscordGatewayConnector,
    QQGatewayConnector,
    WeComAIBotConnector,
    decode_gateway_frame,
    parse_connector_credential,
)
from open_agent.gateway.connectors.contracts import ConnectorAuthenticationError
from open_agent.gateway.connectors.transport import _official_url
from open_agent.gateway.credentials import CredentialStore, MemoryCredentialBackend
from open_agent.gateway.contracts import GatewayConnectorCapability, NormalizedInboundEvent
from open_agent.durable_runtime.models import InboxEvent


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
    async def no_wait(): pass
    connector._wait_invalid_session = no_wait
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


def test_official_websocket_allowlist_rejects_credentials_redirect_hosts_and_ports():
    _official_url("wss://gateway.discord.gg/", frozenset({"gateway.discord.gg"}), "wss")
    _official_url("wss://gateway-us-east1-b.discord.gg/", frozenset({"gateway-*.discord.gg"}), "wss")
    for value in (
        "ws://gateway.discord.gg/", "wss://evil.example/",
        "wss://user:pass@gateway.discord.gg/", "wss://gateway.discord.gg:8443/",
    ):
        with pytest.raises(ConnectorProtocolError, match="allowlist"):
            _official_url(value, frozenset({"gateway.discord.gg"}), "wss")


def test_gateway_capability_cannot_authenticate_another_account():
    capability = GatewayConnectorCapability("connector", "discord", "account-1")
    event = NormalizedInboundEvent(
        "event", "discord", "account-2", "chat", "sender", "dm", "hello"
    )
    with pytest.raises(ValueError, match="identity"):
        capability.authenticate(event, gateway_session_id="session", gateway_sequence=1)


def test_retained_checkpoint_claim_can_commit_then_renew_without_owner_gap(tmp_path):
    repo = _repository(tmp_path, "discord")
    token = _claim(repo)
    event = InboxEvent(
        event_id="event-1", event_key="message-1", account_id="account-1",
        conversation_id="conversation-1",
        payload={"transport_mode": "gateway", "transport_position": {
            "gateway_session_id": "session-1", "gateway_sequence": 7,
        }},
        created_at=NOW, updated_at=NOW,
    )
    repo.enqueue_polled_inbox(
        event, transport_mode="gateway", token=token, now=NOW,
    )
    committed = repo.commit_ingress_checkpoint(
        account_id="account-1", transport_mode="gateway", now=NOW,
        token=token,
        expected_previous={"gateway_session_id": None, "gateway_sequence": None},
        gateway_session_id="session-1", gateway_sequence=7,
        processed_event_key="message-1", release_claim=False,
    )
    assert committed["claim_owner"] == "connector-1"
    renewed = repo.renew_ingress_checkpoint_claim(
        account_id="account-1", transport_mode="gateway", token=token,
        now=NOW + timedelta(seconds=10), expires_at=NOW + timedelta(minutes=3),
    )
    assert renewed.generation == token.generation


@pytest.mark.asyncio
async def test_duplicate_discord_sequence_is_not_admitted_twice(tmp_path):
    repo = _repository(tmp_path, "discord")
    ingress = FakeIngress(repo)
    message = {"op": 0, "t": "MESSAGE_CREATE", "s": 2, "d": {"id": "m1", "channel_id": "c1", "content": "hello", "author": {"id": "u1", "bot": False}, "mentions": [{"id": "999"}]}}
    socket = FakeSocket([
        {"op": 10, "d": {"heartbeat_interval": 60000}},
        {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "sess-1", "user": {"id": "999"}}},
        message, message, EOFError(),
    ])
    connector = DiscordGatewayConnector(
        account_id="account-1", adapter=DiscordAdapter(account_id="account-1", transport=FakeHttp({}), bot_token="token", application_id="999"),
        ingress=ingress, repository=repo, network=FakeNetwork(socket),
        http=FakeHttp({"url": "wss://gateway.discord.gg/"}),
        credential=parse_connector_credential("discord", '{"bot_token":"token","application_id":"999","intents":33281}'), now=lambda: NOW,
    )
    await connector.run_once()
    assert len(ingress.accepted) == 1


@pytest.mark.asyncio
async def test_failed_durable_admission_does_not_advance_resume_sequence(tmp_path):
    repo = _repository(tmp_path, "discord")
    ingress = FakeIngress(repo, fail=True)
    socket = FakeSocket([
        {"op": 10, "d": {"heartbeat_interval": 60000}},
        {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "sess-1", "user": {"id": "999"}}},
        {"op": 0, "t": "MESSAGE_CREATE", "s": 2, "d": {"id": "m1", "channel_id": "c1", "content": "hello", "author": {"id": "u1", "bot": False}}},
    ])
    connector = DiscordGatewayConnector(
        account_id="account-1", adapter=DiscordAdapter(account_id="account-1", transport=FakeHttp({}), bot_token="token", application_id="999"),
        ingress=ingress, repository=repo, network=FakeNetwork(socket),
        http=FakeHttp({"url": "wss://gateway.discord.gg/"}),
        credential=parse_connector_credential("discord", '{"bot_token":"token","application_id":"999","intents":33281}'), now=lambda: NOW,
    )
    with pytest.raises(StateConflictError):
        await connector.run_once()
    assert connector._sequence == 1


def test_gateway_seen_session_history_is_bounded():
    from open_agent.durable_runtime.repository import _bounded_gateway_sessions
    sessions = [f"session-{index}" for index in range(1000)]
    bounded = _bounded_gateway_sessions(sessions, "current")
    assert len(bounded) <= 256
    assert bounded[-1] == "current"
    assert len(json.dumps(bounded).encode()) <= 132_000


class ClosedWithCode(Exception):
    def __init__(self, code):
        self.code = code


@pytest.mark.asyncio
async def test_terminal_gateway_close_code_invalidates_and_is_sanitized(tmp_path):
    repo = _repository(tmp_path, "discord")
    socket = FakeSocket([
        {"op": 10, "d": {"heartbeat_interval": 60000}}, ClosedWithCode(4004),
    ])
    connector = DiscordGatewayConnector(
        account_id="account-1", adapter=DiscordAdapter(account_id="account-1", transport=FakeHttp({}), bot_token="very-secret", application_id="999"),
        ingress=FakeIngress(repo), repository=repo, network=FakeNetwork(socket),
        http=FakeHttp({"url": "wss://gateway.discord.gg/"}),
        credential=parse_connector_credential("discord", '{"bot_token":"very-secret","application_id":"999","intents":33281}'), now=lambda: NOW,
    )
    with pytest.raises(ConnectorAuthenticationError):
        await connector.run_once()
    assert connector.snapshot().last_error == "ConnectorAuthenticationError"
    assert "very-secret" not in repr(connector)


class StubRegistry:
    def __init__(self): self._adapters = {}


@pytest.mark.asyncio
async def test_manager_hydrates_protected_account_and_drains_children(tmp_path):
    repo = _repository(tmp_path, "discord")
    store = CredentialStore(MemoryCredentialBackend())
    ref = store.put("account-1", '{"bot_token":"protected","application_id":"999","intents":33281}')
    with repo.control_plane._get_conn() as conn:
        conn.execute("UPDATE channel_accounts SET credential_ref=? WHERE account_id='account-1'", (ref,))
    adapters, registry = {}, StubRegistry()
    manager = ConnectorManager(repo, FakeIngress(repo), store, adapters, registry)
    row = repo.get_channel_account("account-1")
    connector, adapter = manager._build(row)
    assert isinstance(connector, DiscordGatewayConnector)
    assert adapter.account_id == "account-1"
    assert "protected" not in repr(connector)
    manager._build = lambda _row: (connector, adapter)
    connector.run_once = lambda: asyncio.Event().wait()
    await manager.reconcile()
    assert "account-1" in adapters and manager.snapshot("account-1")["state"] == "idle"
    await manager.close()
    assert adapters == {} and registry._adapters == {}
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("gateway-connector:") and not task.done()]


@pytest.mark.parametrize(
    ("kind", "secret", "connector_type"),
    [
        ("qq", '{"access_token":"token","app_id":"app","intents":1}', QQGatewayConnector),
        ("dingtalk", '{"client_id":"cid","client_secret":"secret","access_token":"token","robot_code":"robot"}', DingTalkStreamConnector),
        ("wecom", '{"bot_id":"bot","secret":"secret"}', WeComAIBotConnector),
    ],
)
def test_manager_hydrates_each_official_connector(tmp_path, kind, secret, connector_type):
    repo = _repository(tmp_path, kind)
    store = CredentialStore(MemoryCredentialBackend())
    ref = store.put("account-1", secret)
    with repo.control_plane._get_conn() as conn:
        conn.execute("UPDATE channel_accounts SET credential_ref=? WHERE account_id='account-1'", (ref,))
    manager = ConnectorManager(repo, FakeIngress(repo), store, {}, StubRegistry())
    connector, adapter = manager._build(repo.get_channel_account("account-1"))
    assert isinstance(connector, connector_type)
    assert adapter.kind == kind
    assert secret not in repr(connector)


@pytest.mark.asyncio
async def test_manager_forever_loop_is_cancellation_safe(tmp_path):
    repo = _repository(tmp_path, "telegram")
    manager = ConnectorManager(
        repo, FakeIngress(repo), CredentialStore(MemoryCredentialBackend()), {}, StubRegistry(),
        scan_interval=0.01,
    )
    task = asyncio.create_task(manager.run_forever())
    await asyncio.sleep(0.03)
    manager.wake()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_manager_stops_retrying_terminal_authentication_error(tmp_path):
    repo = _repository(tmp_path, "discord")
    manager = ConnectorManager(
        repo, FakeIngress(repo), CredentialStore(MemoryCredentialBackend()), {}, StubRegistry(),
    )
    class Terminal:
        account_id = "account-1"
        async def run_once(self): raise ConnectorAuthenticationError("redacted")
        def snapshot(self): return type("S", (), {"last_error": "ConnectorAuthenticationError"})()
    await manager._run_connector(Terminal())


@pytest.mark.asyncio
async def test_opcode_heartbeat_timeout_closes_socket(tmp_path):
    repo = _repository(tmp_path, "discord")
    socket = FakeSocket([])
    connector = DiscordGatewayConnector(
        account_id="account-1", adapter=DiscordAdapter(account_id="account-1", transport=FakeHttp({}), bot_token="token", application_id="999"),
        ingress=FakeIngress(repo), repository=repo, network=FakeNetwork(socket),
        http=FakeHttp({"url": "wss://gateway.discord.gg/"}),
        credential=parse_connector_credential("discord", '{"bot_token":"token","application_id":"999","intents":1}'), now=lambda: NOW,
    )
    connector._socket = socket
    with pytest.raises(ConnectorProtocolError, match="heartbeat"):
        await connector._heartbeat_loop(0.001, asyncio.Event())
    assert socket.closed is True


@pytest.mark.asyncio
async def test_dingtalk_system_disconnect_is_acknowledged_and_drained(tmp_path):
    repo = _repository(tmp_path, "dingtalk")
    socket = FakeSocket([
        {"type": "SYSTEM", "headers": {"topic": "disconnect", "messageId": "system-1"}},
    ])
    http = FakeHttp({"endpoint": "wss://wss-open-connection.dingtalk.com/connect", "ticket": "ticket"})
    connector = DingTalkStreamConnector(
        account_id="account-1", adapter=DingTalkAdapter(account_id="account-1", transport=http, access_token="token", robot_code="robot"),
        ingress=FakeIngress(repo), repository=repo, network=FakeNetwork(socket), http=http,
        credential=parse_connector_credential("dingtalk", '{"client_id":"cid","client_secret":"secret","access_token":"token","robot_code":"robot"}'), now=lambda: NOW,
    )
    await connector.run_once()
    assert socket.sent[-1]["code"] == 200 and socket.closed


@pytest.mark.asyncio
async def test_wecom_reply_is_serialized_and_waits_for_matching_ack(tmp_path):
    repo = _repository(tmp_path, "wecom")
    socket = FakeSocket([])
    async def sender(*_): return {"errcode": 0}
    connector = WeComAIBotConnector(
        account_id="account-1", adapter=WeComAdapter(account_id="account-1", bot_id="bot", gateway_sender=sender),
        ingress=FakeIngress(repo), repository=repo, network=FakeNetwork(socket),
        credential=parse_connector_credential("wecom", '{"bot_id":"bot","secret":"secret"}'), now=lambda: NOW,
    )
    connector._socket = socket
    connector._mark_authenticated("session", resumable=False)
    pending = asyncio.create_task(connector.send_reply("req-1", "answer", "delivery-1"))
    await asyncio.sleep(0)
    assert socket.sent[-1]["cmd"] == "aibot_respond_msg"
    connector._pending["req-1"].set_result({"headers": {"req_id": "req-1"}, "errcode": 0})
    assert (await pending)["errcode"] == 0
    connector._remove_capability()


@pytest.mark.asyncio
async def test_invalid_session_true_preserves_resume_state(tmp_path):
    repo = _repository(tmp_path, "discord")
    socket = FakeSocket([
        {"op": 10, "d": {"heartbeat_interval": 60000}},
        {"op": 9, "d": True},
    ])
    connector = DiscordGatewayConnector(
        account_id="account-1", adapter=DiscordAdapter(account_id="account-1", transport=FakeHttp({}), bot_token="token", application_id="999"),
        ingress=FakeIngress(repo), repository=repo, network=FakeNetwork(socket),
        http=FakeHttp({"url": "wss://gateway.discord.gg/"}),
        credential=parse_connector_credential("discord", '{"bot_token":"token","application_id":"999","intents":1}'), now=lambda: NOW,
    )
    connector.restore_for_test(session_id="resume-me", sequence=8, resume_url="wss://gateway.discord.gg/")
    waited = []
    async def wait_invalid_session(): waited.append(True)
    connector._wait_invalid_session = wait_invalid_session
    await connector.run_once()
    assert connector.snapshot().session_resumable is True
    assert waited == [True]


@pytest.mark.asyncio
async def test_cancelled_connector_reaps_session_and_lease_children(tmp_path):
    class BlockingSocket(FakeSocket):
        async def recv(self):
            await asyncio.Event().wait()

    repo = _repository(tmp_path, "dingtalk")
    socket = BlockingSocket([])
    connector = DingTalkStreamConnector(
        account_id="account-1", adapter=DingTalkAdapter(account_id="account-1", transport=FakeHttp({}), access_token="token", robot_code="robot"),
        ingress=FakeIngress(repo), repository=repo, network=FakeNetwork(socket),
        http=FakeHttp({"endpoint": "wss://wss-gw.dingtalk.com/connect", "ticket": "memory-only"}),
        credential=parse_connector_credential("dingtalk", '{"client_id":"cid","client_secret":"secret","access_token":"token","robot_code":"robot"}'), now=lambda: NOW,
    )
    parent = asyncio.create_task(connector.run_once())
    for _ in range(20):
        await asyncio.sleep(0)
        if connector.snapshot().authenticated:
            break
    parent.cancel()
    await asyncio.gather(parent, return_exceptions=True)
    await asyncio.sleep(0)
    leaked = {
        task.get_name() for task in asyncio.all_tasks()
        if not task.done() and task.get_name().startswith("connector-")
    }
    assert leaked == set()


def test_discord_resume_allowlist_rejects_non_gateway_subdomains():
    allowed = frozenset({"gateway.discord.gg", "gateway-*.discord.gg"})
    _official_url("wss://gateway-us-east1-b.discord.gg/", allowed, "wss")
    for value in (
        "wss://cdn.discord.gg/", "wss://support.discord.gg/",
        "wss://gateway-a.b.discord.gg/", "wss://gateway-.discord.gg/",
    ):
        with pytest.raises(ConnectorProtocolError):
            _official_url(value, allowed, "wss")


@pytest.mark.asyncio
async def test_discord_invalid_session_wait_is_within_official_range(monkeypatch):
    delays = []
    async def record(delay): delays.append(delay)
    monkeypatch.setattr("open_agent.gateway.connectors.discord.asyncio.sleep", record)
    values = iter((0, 4000))
    monkeypatch.setattr(
        "open_agent.gateway.connectors.discord.secrets.randbelow", lambda _: next(values)
    )
    await DiscordGatewayConnector._wait_invalid_session(None)
    await DiscordGatewayConnector._wait_invalid_session(None)
    assert delays == [1.0, 5.0]


@pytest.mark.asyncio
async def test_manager_invalidation_restarts_same_credential_reference(tmp_path):
    repo = _repository(tmp_path, "discord")
    store = CredentialStore(MemoryCredentialBackend())
    ref = store.put("account-1", '{"bot_token":"old","application_id":"999","intents":1}')
    with repo.control_plane._get_conn() as conn:
        conn.execute("UPDATE channel_accounts SET credential_ref=? WHERE account_id='account-1'", (ref,))
    adapters, registry = {}, StubRegistry()
    manager = ConnectorManager(repo, FakeIngress(repo), store, adapters, registry)
    created = []
    class Waiting:
        account_id = "account-1"
        def __init__(self): self.value = ConnectorSnapshot("account-1", "discord")
        async def run_once(self): await asyncio.Event().wait()
        def snapshot(self): return self.value
    def build(_row):
        connector = Waiting(); created.append(connector)
        return connector, type("Adapter", (), {"account_id": "account-1"})()
    manager._build = build
    await manager.reconcile()
    manager.invalidate("account-1")
    await manager.reconcile()
    assert len(created) == 2
    await manager.close()


@pytest.mark.asyncio
async def test_cancel_on_stop_long_worker_does_not_wait_for_drain_timeout():
    from open_agent.durable_runtime.supervisor import DurableRuntimeSupervisor, WorkerSpec
    started = asyncio.Event()
    async def forever():
        started.set()
        await asyncio.Event().wait()
    supervisor = DurableRuntimeSupervisor(
        [WorkerSpec("connector", forever, required=False, cancel_on_stop=True)],
        drain_timeout=2,
    )
    await supervisor.start(); await started.wait()
    await asyncio.wait_for(supervisor.stop(), timeout=0.2)
    assert supervisor.snapshot().running is False
