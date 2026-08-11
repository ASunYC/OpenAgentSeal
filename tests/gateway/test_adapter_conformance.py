from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import httpx

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.delivery import DeliveryWorker
from open_agent.durable_runtime.models import ClaimToken, InboxEvent, OutboxObligation
from open_agent.durable_runtime.repository import DurableRuntimeRepository, StaleClaimError
from open_agent.gateway.adapters import (
    DingTalkAdapter,
    DiscordAdapter,
    FeishuAdapter,
    LineAdapter,
    QQAdapter,
    SlackAdapter,
    TelegramAdapter,
    WeComAdapter,
    WhatsAppAdapter,
)
from open_agent.gateway.adapters.base_http import (
    AdapterAuthenticationError,
    AdapterOutcomeUnknown,
    AdapterRejected,
    AdapterRateLimited,
    BoundedHttpTransport,
    HttpResponse,
    classify_response,
    sanitize_error,
)
from open_agent.gateway.contracts import OutboundMessage
from open_agent.gateway.destinations import ChannelDestinationRegistry, channel_obligation
from open_agent.gateway.router import GatewayRouter


NOW = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures"


class RecordingTransport:
    def __init__(self, response: HttpResponse | None = None) -> None:
        self.response = response or HttpResponse(200, {}, b'{"ok":true,"id":"sent-1"}')
        self.calls: list[dict] = []

    async def request(self, method, url, *, headers=None, json_body=None, allowed_hosts):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "json": json_body, "allowed_hosts": frozenset(allowed_hosts)})
        return self.response


class RecordingGatewaySender:
    def __init__(self) -> None:
        self.calls = []
    async def __call__(self, request_id, content, delivery_key):
        self.calls.append((request_id, content, delivery_key))
        return {"errcode": 0, "msgid": "wecom-sent-1"}


def _body(kind: str) -> bytes:
    return (FIXTURES / f"{kind}.json").read_bytes()


def _adapter(kind: str, transport: RecordingTransport | None = None):
    transport = transport or RecordingTransport()
    common = {"account_id": "account-1", "transport": transport}
    gateway_sender = RecordingGatewaySender()
    adapter = {
        "telegram": TelegramAdapter(**common, bot_token="token", webhook_secret="hook", bot_id="999", bot_username="seal"),
        "discord": DiscordAdapter(**common, bot_token="token", application_id="999"),
        "slack": SlackAdapter(**common, bot_token="token", signing_secret="secret", bot_user_id="B1"),
        "whatsapp": WhatsAppAdapter(**common, access_token="token", app_secret="secret", phone_number_id="P1", verify_token="verify"),
        "feishu": FeishuAdapter(**common, tenant_access_token="token", verification_token="verify-token", encrypt_key="secret", bot_open_id="ou-bot"),
        "dingtalk": DingTalkAdapter(**common, access_token="token", robot_code="ding-bot"),
        "line": LineAdapter(**common, channel_access_token="token", channel_secret="secret", bot_user_id="line-bot"),
        "qq": QQAdapter(**common, access_token="token", app_id="qq-bot"),
        "wecom": WeComAdapter(account_id="account-1", bot_id="wx-bot", gateway_sender=gateway_sender),
    }[kind]
    if kind == "wecom":
        adapter.test_gateway_sender = gateway_sender
    return adapter


KINDS = ("telegram", "discord", "slack", "whatsapp", "feishu", "dingtalk", "line", "qq", "wecom")


@pytest.mark.parametrize("kind", KINDS)
def test_normalizes_sanitized_official_fixture(kind):
    adapter = _adapter(kind)
    event = adapter.normalize(_body(kind))
    assert event.adapter_kind == kind
    assert event.account_id == "account-1"
    assert event.event_key and event.conversation_id and event.sender_id
    assert event.text.strip()
    assert event.conversation_kind in {"dm", "group"}
    assert event.mentioned_bot or event.conversation_kind == "dm"
    assert isinstance(event.replies_to_bot, bool)
    assert "token" not in json.dumps(dict(event.metadata)).lower()


@pytest.mark.parametrize("kind", KINDS)
def test_capabilities_are_truthful_and_bounded(kind):
    capabilities = _adapter(kind).capabilities
    assert capabilities.supports_text is True
    assert capabilities.max_message_chars and capabilities.max_message_chars > 0
    assert 1 <= capabilities.acknowledgement_deadline_seconds <= 30
    assert capabilities.supports_idempotency is (kind in {"discord", "line"})
    assert capabilities.supports_reconciliation is False
    assert capabilities.supports_gateway_resume is (kind in {"discord", "qq"})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_send_uses_only_official_https_host_and_stable_key(kind):
    transport = RecordingTransport()
    adapter = _adapter(kind, transport)
    metadata = {"delivery_id": "out-1"}
    if kind == "wecom":
        metadata.update({"wecom_transport": "aibot_gateway", "wecom_request_id": "req-1"})
    result = await adapter.send(OutboundMessage("account-1", "conversation-1", "answer", "event-1", metadata=metadata))
    if kind == "wecom":
        assert transport.calls == []
        assert adapter.test_gateway_sender.calls == [("req-1", "answer", "out-1")]
        assert result["platform_message_id"] == "wecom-sent-1"
        return
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].startswith("https://")
    assert call["url"].split("/", 3)[2] in call["allowed_hosts"]
    assert result["platform_message_id"]
    if adapter.capabilities.supports_idempotency:
        if kind == "discord":
            assert call["json"]["enforce_nonce"] is True
            assert len(call["json"]["nonce"]) <= 25
        elif kind == "line":
            uuid.UUID(call["headers"]["x-line-retry-key"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", tuple(kind for kind in KINDS if kind != "wecom"))
async def test_rate_limits_are_classified_without_secret_leak(kind):
    transport = RecordingTransport(HttpResponse(429, {"retry-after": "3"}, b'{"error":"token=super-secret"}'))
    adapter = _adapter(kind, transport)
    with pytest.raises(AdapterRateLimited) as caught:
        await adapter.send(OutboundMessage("account-1", "conversation-1", "answer"))
    assert caught.value.retry_after == 3
    assert "super-secret" not in str(caught.value)


def test_authentication_fails_closed_and_challenges_are_explicit():
    telegram = _adapter("telegram")
    assert telegram.verify_webhook(_body("telegram"), {"x-telegram-bot-api-secret-token": "hook"})
    with pytest.raises(AdapterAuthenticationError):
        telegram.verify_webhook(_body("telegram"), {})
    slack = _adapter("slack")
    timestamp = str(int(NOW.timestamp()))
    signature = "v0=" + hmac.new(b"secret", b"v0:" + timestamp.encode() + b":" + _body("slack"), hashlib.sha256).hexdigest()
    assert slack.verify_webhook(_body("slack"), {"x-slack-request-timestamp": timestamp, "x-slack-signature": signature}, now=NOW)
    assert slack.challenge_response(b'{"type":"url_verification","challenge":"safe"}') == {"challenge": "safe"}
    whatsapp = _adapter("whatsapp")
    assert whatsapp.challenge_response(b"", query={"hub.mode": "subscribe", "hub.verify_token": "verify", "hub.challenge": "safe"}) == "safe"


def test_every_adapter_has_a_fail_closed_authentication_boundary():
    for kind in KINDS:
        adapter = _adapter(kind)
        if kind in {"discord", "dingtalk", "qq", "wecom"}:
            assert adapter.capabilities.supports_webhook is False
            with pytest.raises(AdapterAuthenticationError):
                adapter.verify_webhook(b"{}", {})
        elif kind == "feishu":
            assert adapter.verify_webhook(_body(kind), {})
            with pytest.raises(AdapterAuthenticationError):
                adapter.verify_webhook(b"{}", {})
        else:
            with pytest.raises(AdapterAuthenticationError):
                adapter.verify_webhook(_body(kind), {})


@pytest.mark.parametrize("kind", ("line", "whatsapp"))
def test_multi_event_webhooks_normalize_every_message(kind):
    payload = json.loads(_body(kind))
    if kind == "line":
        duplicate = dict(payload["events"][0])
        duplicate["webhookEventId"] = "line-2"
        duplicate["message"] = dict(duplicate["message"], id="line-msg-2")
        payload["events"].append(duplicate)
    else:
        duplicate = dict(payload["entry"][0]["changes"][0]["value"]["messages"][0])
        duplicate["id"] = "wamid.2"
        payload["entry"][0]["changes"][0]["value"]["messages"].append(duplicate)
    events = _adapter(kind).normalize_many(json.dumps(payload).encode())
    assert len(events) == 2
    assert len({event.event_key for event in events}) == 2


@pytest.mark.parametrize("kind", ("line", "whatsapp"))
def test_multi_event_webhooks_reject_101_before_normalizing_all(kind, monkeypatch):
    adapter = _adapter(kind)
    payload = json.loads(_body(kind))
    calls = []
    if kind == "line":
        payload["events"] = [dict(payload["events"][0], webhookEventId=f"line-{i}") for i in range(101)]
        monkeypatch.setattr(adapter, "_normalize_event", lambda event: calls.append(event))
    else:
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        payload["entry"][0]["changes"][0]["value"]["messages"] = [dict(message, id=f"wa-{i}") for i in range(101)]
        original = adapter._normalize_message
        def recording(value, item):
            calls.append(item)
            return original(value, item)
        monkeypatch.setattr(adapter, "_normalize_message", recording)
    with pytest.raises(ValueError, match="100"):
        adapter.normalize_many(json.dumps(payload).encode())
    assert len(calls) <= 100


@pytest.mark.parametrize("kind", ("telegram", "discord", "slack"))
def test_bot_authored_events_are_marked_non_dispatchable(kind):
    payload = json.loads(_body(kind))
    if kind == "telegram":
        payload["message"]["from"] = {"id": 999, "is_bot": True}
    elif kind == "discord":
        payload["d"]["author"] = {"id": "999", "bot": True}
    else:
        payload["event"]["user"] = "B1"
        payload["event"]["bot_id"] = "B1"
    event = _adapter(kind).normalize(json.dumps(payload).encode())
    assert event.metadata["sender_is_bot"] is True
    assert GatewayRouter._should_dispatch("always", event) is False


def test_discord_message_ingress_is_explicitly_gateway_only():
    adapter = _adapter("discord")
    assert adapter.capabilities.supports_webhook is False
    assert adapter.capabilities.supports_gateway_resume is True
    assert adapter.normalize_gateway(_body("discord")) == adapter.normalize(_body("discord"))
    with pytest.raises(AdapterAuthenticationError):
        adapter.verify_webhook(b'{"type":1}', {})
    assert adapter.challenge_response(b'{"type":1}') is None


@pytest.mark.asyncio
async def test_origin_scoped_outbox_resolves_sends_once_and_acks(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    repository.upsert_channel_account(account_id="account-1", adapter_kind="telegram", default_profile_id="main", now=NOW)
    adapter = _adapter("telegram")
    registry = ChannelDestinationRegistry(repository, {"account-1": adapter}, clock=lambda: NOW)
    obligation = repository.enqueue_outbox(channel_obligation(account_id="account-1", conversation_id="conversation-1", content="answer", source_event_key="event-1", now=NOW))
    worker = DeliveryWorker(repository, {obligation.destination: registry.resolve("account-1")}, owner_id="worker", clock=lambda: NOW, lease_duration=timedelta(seconds=30), delivery_timeout=5)
    assert await worker.run_once(NOW) == 1
    stored = repository.get_outbox(obligation.obligation_id)
    assert stored is not None and stored.state == "acknowledged"
    assert stored.acknowledgement["platform_message_id"] == "sent-1"
    assert len(adapter.transport.calls) == 1
    control_plane.close()


def test_claim_type_remains_frozen_contract():
    claim = ClaimToken("worker", 1, NOW + timedelta(seconds=30))
    assert claim.owner_id == "worker"


def test_stale_inbox_claim_rolls_back_origin_reply_outbox(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    repository.enqueue_inbox(InboxEvent("in-1", "event-1", "account-1", "conversation-1", {}, created_at=NOW, updated_at=NOW))
    claimed = repository.claim_due_inbox("worker", NOW, NOW + timedelta(seconds=5), limit=1)[0]
    thread = control_plane.create_runtime_thread(session_id="session-1", thread_id="thread-1")
    repository.dispatch_inbox_with_turn(claimed.event_id, claimed.claim, thread_id=thread["thread_id"], session_id="session-1", user_input="hello", now=NOW)
    reply = channel_obligation(account_id="account-1", conversation_id="conversation-1", content="answer", source_event_key='["account-1","event-1"]', now=NOW)

    with pytest.raises(StaleClaimError):
        repository.complete_inbox_after_agent("in-1", claimed.claim, source_event_key='["account-1","event-1"]', now=NOW + timedelta(seconds=5), reply_obligation=reply)

    assert repository.list_outbox() == []
    control_plane.close()


def test_qq_normalization_preserves_reply_destination_kind():
    event = _adapter("qq").normalize(_body("qq"))
    assert event.metadata["qq_destination_kind"] == "group"


@pytest.mark.asyncio
async def test_wecom_group_reply_uses_originating_aibot_gateway_frame():
    adapter = _adapter("wecom")
    event = adapter.normalize(_body("wecom"))
    assert event.conversation_kind == "group"
    result = await adapter.send(OutboundMessage("account-1", event.conversation_id, "answer", metadata={**dict(event.metadata), "delivery_id": "out-1"}))
    assert adapter.test_gateway_sender.calls == [("wx-1", "answer", "out-1")]
    assert result["platform_message_id"] == "wecom-sent-1"


@pytest.mark.asyncio
async def test_bounded_http_transport_enforces_host_redirect_and_body_limits():
    async def handler(request: httpx.Request):
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "https://evil.invalid"})
        return httpx.Response(200, json={"id": "ok"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = BoundedHttpTransport(client=client, max_request_bytes=64)
    response = await transport.request("POST", "https://api.telegram.org/ok", json_body={"text": "safe"}, allowed_hosts=frozenset({"api.telegram.org"}))
    assert response.json()["id"] == "ok"
    with pytest.raises(AdapterRejected):
        await transport.request("POST", "https://evil.invalid/ok", json_body={}, allowed_hosts=frozenset({"api.telegram.org"}))
    with pytest.raises(AdapterRejected):
        await transport.request("POST", "https://api.telegram.org/redirect", json_body={}, allowed_hosts=frozenset({"api.telegram.org"}))
    with pytest.raises(AdapterRejected):
        await transport.request("POST", "https://api.telegram.org/ok", json_body={"text": "x" * 100}, allowed_hosts=frozenset({"api.telegram.org"}))
    await client.aclose()


@pytest.mark.asyncio
async def test_bounded_http_transport_classifies_network_ambiguity_and_large_response():
    async def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("secret=do-not-leak", request=request)

    timeout_client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    transport = BoundedHttpTransport(client=timeout_client)
    with pytest.raises(AdapterOutcomeUnknown) as caught:
        await transport.request("POST", "https://slack.com/api/x", json_body={}, allowed_hosts=frozenset({"slack.com"}))
    assert "do-not-leak" not in str(caught.value)
    await timeout_client.aclose()

    large_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 33)))
    limited = BoundedHttpTransport(client=large_client, max_response_bytes=32)
    with pytest.raises(AdapterRejected):
        await limited.request("POST", "https://slack.com/api/x", json_body={}, allowed_hosts=frozenset({"slack.com"}))
    await large_client.aclose()


@pytest.mark.asyncio
async def test_bounded_transport_stops_streaming_at_response_limit():
    class CountingStream(httpx.AsyncByteStream):
        def __init__(self):
            self.chunks_read = 0
        async def __aiter__(self):
            for _ in range(10):
                self.chunks_read += 1
                yield b"x" * 16

    stream = CountingStream()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream)))
    transport = BoundedHttpTransport(client=client, max_response_bytes=32)
    with pytest.raises(AdapterRejected):
        await transport.request("POST", "https://slack.com/api/x", json_body={}, allowed_hosts=frozenset({"slack.com"}))
    assert stream.chunks_read == 3
    await client.aclose()


def test_shared_response_decoder_and_redaction_are_fail_closed():
    with pytest.raises(AdapterRejected):
        classify_response(HttpResponse(200, {}, b"not-json"))
    with pytest.raises(AdapterRejected):
        classify_response(HttpResponse(400, {}, b'{"error":"bad"}'))
    assert "top-secret" not in sanitize_error("Authorization: Bearer top-secret")
    assert "bot-token-value" not in sanitize_error(
        "https://api.telegram.org/botbot-token-value/sendMessage"
    )
    assert "query-token" not in sanitize_error(
        "https://example.invalid/send?access_token=query-token"
    )
