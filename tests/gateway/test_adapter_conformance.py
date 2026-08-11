from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.delivery import DeliveryWorker
from open_agent.durable_runtime.models import ClaimToken, OutboxObligation
from open_agent.durable_runtime.repository import DurableRuntimeRepository
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
    AdapterRateLimited,
    HttpResponse,
)
from open_agent.gateway.contracts import OutboundMessage
from open_agent.gateway.destinations import ChannelDestinationRegistry, channel_obligation


NOW = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures"


class RecordingTransport:
    def __init__(self, response: HttpResponse | None = None) -> None:
        self.response = response or HttpResponse(200, {}, b'{"ok":true,"id":"sent-1"}')
        self.calls: list[dict] = []

    async def request(self, method, url, *, headers=None, json_body=None, allowed_hosts):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "json": json_body, "allowed_hosts": frozenset(allowed_hosts)})
        return self.response


def _body(kind: str) -> bytes:
    return (FIXTURES / f"{kind}.json").read_bytes()


def _adapter(kind: str, transport: RecordingTransport | None = None):
    transport = transport or RecordingTransport()
    common = {"account_id": "account-1", "transport": transport}
    return {
        "telegram": TelegramAdapter(**common, bot_token="token", webhook_secret="hook", bot_id="999", bot_username="seal"),
        "discord": DiscordAdapter(**common, bot_token="token", application_id="999", webhook_verifier=lambda *_: True),
        "slack": SlackAdapter(**common, bot_token="token", signing_secret="secret", bot_user_id="B1"),
        "whatsapp": WhatsAppAdapter(**common, access_token="token", app_secret="secret", phone_number_id="P1", verify_token="verify"),
        "feishu": FeishuAdapter(**common, tenant_access_token="token", verification_token="verify-token", encrypt_key="secret", bot_open_id="ou-bot"),
        "dingtalk": DingTalkAdapter(**common, access_token="token", signing_secret="secret", robot_code="ding-bot"),
        "line": LineAdapter(**common, channel_access_token="token", channel_secret="secret", bot_user_id="line-bot"),
        "qq": QQAdapter(**common, access_token="token", app_id="qq-bot"),
        "wecom": WeComAdapter(**common, access_token="token", token="secret", agent_id="1001", corp_id="corp-1", bot_id="wx-bot"),
    }[kind]


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
    assert event.replies_to_bot is isinstance(event.replies_to_bot, bool)
    assert "token" not in json.dumps(dict(event.metadata)).lower()


@pytest.mark.parametrize("kind", KINDS)
def test_capabilities_are_truthful_and_bounded(kind):
    capabilities = _adapter(kind).capabilities
    assert capabilities.supports_text is True
    assert capabilities.max_message_chars and capabilities.max_message_chars > 0
    assert 1 <= capabilities.acknowledgement_deadline_seconds <= 30
    assert capabilities.supports_idempotency is (kind in {"discord", "dingtalk", "line"})
    assert capabilities.supports_reconciliation is (kind == "discord")
    assert capabilities.supports_gateway_resume is (kind in {"discord", "qq", "wecom"})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_send_uses_only_official_https_host_and_stable_key(kind):
    transport = RecordingTransport()
    adapter = _adapter(kind, transport)
    result = await adapter.send(OutboundMessage("account-1", "conversation-1", "answer", "event-1", metadata={"delivery_id": "out-1"}))
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].startswith("https://")
    assert call["url"].split("/", 3)[2] in call["allowed_hosts"]
    assert "token" not in call["url"].lower()
    assert result["platform_message_id"]
    serialized = json.dumps(call["json"])
    if adapter.capabilities.supports_idempotency:
        assert "out-1" in serialized or "out-1" in json.dumps(call["headers"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
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
