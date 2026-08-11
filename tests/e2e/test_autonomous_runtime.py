"""Deterministic cross-system verification for the durable autonomous runtime.

These tests deliberately use a real temporary SQLite database and reopen it at
crash boundaries.  Provider I/O, time, Agent output and Goal judgement remain
scripted so the suite never sleeps, reaches the network or reads host secrets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from open_agent.app.runner.models import AgentEvent
from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.delivery import DeliveryWorker
from open_agent.durable_runtime.repository import DurableRuntimeRepository, GoalOperatorService
from open_agent.durable_runtime.supervisor import DurableRuntimeSupervisor, WorkerSpec
from open_agent.gateway.adapters.base_http import HttpResponse
from open_agent.gateway.adapters.telegram import TelegramAdapter
from open_agent.gateway.destinations import ChannelDestinationRegistry, channel_obligation
from open_agent.gateway.ingress import IngressService, IngressWorker
from open_agent.gateway.router import GatewayRouter
from open_agent.gateway.security import (
    HierarchicalIngressLimiter,
    IngressGuard,
    LimitRule,
    QuotaSnapshot,
    ResourceQuotaPolicy,
    WebhookAuthenticator,
)
from open_agent.goal_mode import JudgeResult
from open_agent.goal_runtime import (
    GoalAcceptance,
    GoalBudget,
    GoalConfiguration,
    GoalRunner,
    PricingSnapshot,
)
from open_agent.scheduler_runtime import SchedulerWorker


START = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)


@dataclass
class Clock:
    value: datetime = START

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> datetime:
        self.value += timedelta(**kwargs)
        return self.value


class Nonces:
    def claim(self, account_id, nonce, expires_at):
        del account_id, nonce, expires_at
        return True


class Ledger:
    def try_reserve(self, policy, request, conversation_id):
        del policy, request
        return f"quota:{conversation_id}"

    def release(self, token):
        del token


class ScriptedRunner:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.requests = []

    async def run_stream(self, request, *, runtime_turn=None):
        self.requests.append(request)
        script = self.scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        event = AgentEvent(
            event="complete", session_id=request.session_id, content=script,
            result={"usage": {"total_tokens": 1}},
        )
        control = request.meta["_runtime_control_plane"]
        stored = control.complete_runtime_turn_with_event(
            thread_id=runtime_turn["thread_id"],
            turn_id=runtime_turn["turn_id"],
            session_id=request.session_id,
            event_type="complete",
            payload=event.model_dump(exclude_none=True),
            status="completed",
            result={"content": script, "usage": {"total_tokens": 1}},
        )
        yield event.model_copy(
            update={
                "thread_id": runtime_turn["thread_id"],
                "turn_id": runtime_turn["turn_id"],
                "seq": stored["seq"],
            }
        )


class ScriptedJudge:
    def __init__(self, results):
        self.results = iter(results)

    async def judge(self, *, goal, iteration, content):
        del goal, iteration, content
        return next(self.results)


class MockTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _telegram(transport):
    return TelegramAdapter(
        account_id="telegram-main",
        transport=transport,
        bot_token="test-only-token",
        webhook_secret="test-only-webhook",
        bot_id="99",
        bot_username="openagentseal",
    )


def _service(repository, clock):
    rules = {
        dimension: LimitRule(100, timedelta(minutes=1), 10)
        for dimension in HierarchicalIngressLimiter.DIMENSIONS
    }
    return IngressService(
        repository,
        GatewayRouter(repository, now=clock),
        ingress_guard=IngressGuard(
            WebhookAuthenticator(
                secret_lookup=lambda _account: b"unused",
                nonce_store=Nonces(),
                max_age=timedelta(minutes=5),
            ),
            HierarchicalIngressLimiter(rules, now=clock),
        ),
        quota_policy=ResourceQuotaPolicy(100, 2**30, 0, 2**20, 1),
        quota_ledger=Ledger(),
        quota_snapshot=lambda _event: QuotaSnapshot(),
        now=clock,
    )


def _telegram_update(update_id=1):
    return json.dumps(
        {
            "update_id": update_id,
            "message": {
                "message_id": 7,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 5, "is_bot": False},
                "text": "hello",
            },
        }
    ).encode()


def _open(path, *, goal=False):
    control = ControlPlane(path)
    if not goal:
        return control, DurableRuntimeRepository(control)
    goal_capability = object()
    operator_capability = object()
    raw = DurableRuntimeRepository(
        control,
        goal_authority_capability=goal_capability,
        operator_authority_capability=operator_capability,
    )
    principal = raw.mint_goal_principal(
        actor_id="default", tenant_id="local", capability=goal_capability
    )
    return control, raw, principal, GoalOperatorService(
        raw, operator_capability, issuer_id="operator-console", tenant_id="local"
    )


@pytest.mark.asyncio
async def test_authenticated_webhook_agent_origin_reply_is_exactly_once_across_replay(tmp_path):
    clock = Clock()
    control, repository = _open(tmp_path)
    repository.upsert_channel_account(
        account_id="telegram-main", adapter_kind="telegram",
        default_profile_id="main", now=clock(),
    )
    transport = MockTransport(
        [HttpResponse(200, {}, b'{"ok":true,"result":{"message_id":88}}')]
    )
    adapter = _telegram(transport)
    service = _service(repository, clock)
    body = _telegram_update()
    headers = {"x-telegram-bot-api-secret-token": "test-only-webhook"}

    first = service.accept_webhook(
        adapter, body, headers, account_id="telegram-main", remote_ip="203.0.113.10"
    )
    replay = service.accept_webhook(
        adapter, body, headers, account_id="telegram-main", remote_ip="203.0.113.10"
    )
    assert replay.event_id == first.event_id
    assert len(repository.list_inbox()) == 1

    ingress = IngressWorker(
        repository, GatewayRouter(repository, now=clock),
        ScriptedRunner(["reply"]), worker_id="inbox-e2e", now=clock,
    )
    summary = await ingress.run_once()
    assert (summary.claimed, summary.succeeded, summary.failed) == (1, 1, 0)

    registry = ChannelDestinationRegistry(
        repository, {"telegram-main": adapter}, clock=clock
    )
    delivery = DeliveryWorker(
        repository, {}, owner_id="delivery-e2e", clock=clock,
        destination_resolver=lambda name: registry.resolve(name.removeprefix("channel:")),
        destination_names=lambda: ("channel:telegram-main",),
    )
    assert await delivery.run_once(clock()) == 1
    assert await delivery.run_once(clock()) == 0
    assert len(transport.requests) == 1
    assert repository.list_outbox()[0].state == "acknowledged"
    control.close()


@pytest.mark.asyncio
async def test_ambiguous_remote_send_survives_restart_and_requires_manual_duplicate_risk_ack(tmp_path):
    clock = Clock()
    control, repository = _open(tmp_path)
    repository.upsert_channel_account(
        account_id="telegram-main", adapter_kind="telegram",
        default_profile_id="main", now=clock(),
    )
    repository.enqueue_outbox(
        channel_obligation(
            account_id="telegram-main", conversation_id="42", content="reply",
            source_event_key="event-ambiguous", now=clock(),
        )
    )
    transport = MockTransport([HttpResponse(500, {}, b'{"error":"unknown"}')])
    registry = ChannelDestinationRegistry(repository, {"telegram-main": _telegram(transport)}, clock=clock)
    worker = DeliveryWorker(
        repository, {}, owner_id="before-crash", clock=clock,
        destination_resolver=lambda name: registry.resolve(name.removeprefix("channel:")),
        destination_names=lambda: ("channel:telegram-main",),
    )
    assert await worker.run_once(clock()) == 1
    original = repository.list_outbox()[0]
    assert original.state == "delivery_unknown"
    control.close()

    control, repository = _open(tmp_path)
    recording = MockTransport([])
    registry = ChannelDestinationRegistry(repository, {"telegram-main": _telegram(recording)}, clock=clock)
    recovered = DeliveryWorker(
        repository, {}, owner_id="after-crash", clock=clock,
        destination_resolver=lambda name: registry.resolve(name.removeprefix("channel:")),
        destination_names=lambda: ("channel:telegram-main",),
    )
    assert await recovered.run_once(clock()) == 0
    assert recording.requests == []
    with pytest.raises(ValueError, match="duplicate risk"):
        recovered.manual_resend(
            original.obligation_id, actor_id="operator", duplicate_risk_acknowledged=False,
            acknowledgement_version="delivery-risk-v1", now=clock(), resend_id="manual-1",
        )
    resent = recovered.manual_resend(
        original.obligation_id, actor_id="operator", duplicate_risk_acknowledged=True,
        acknowledgement_version="delivery-risk-v1", now=clock(), resend_id="manual-1",
    )
    assert resent.state == "pending"
    audit = control._get_conn().execute(
        "SELECT action, actor_id FROM runtime_audit_log WHERE subject_id=?", (original.obligation_id,)
    ).fetchone()
    assert tuple(audit) == ("manual_resend", "operator")
    control.close()


@pytest.mark.asyncio
async def test_scheduler_failure_backoff_reopen_success_and_origin_ack(tmp_path):
    clock = Clock()
    control, repository = _open(tmp_path)
    control.create_scheduler_job(
        "* * * * *", "scheduled work", job_id="e2e-job", next_run_at=clock().isoformat(),
        destination="channel:telegram-main", max_retries=2,
        metadata={"conversation_id": "42"},
    )
    repository.upsert_channel_account(
        account_id="telegram-main", adapter_kind="telegram", default_profile_id="main", now=clock()
    )
    worker = SchedulerWorker(repository, ScriptedRunner([RuntimeError("transient")]), clock=clock)
    run = worker.scan_once(clock())[0]
    failed = await worker.execute_run(run.run_id)
    assert failed.state == "retry_wait"
    retry_at = failed.next_attempt_at
    control.close()

    clock.value = retry_at + timedelta(seconds=1)
    control, repository = _open(tmp_path)
    completed = await SchedulerWorker(
        repository, ScriptedRunner(["scheduled reply"]), clock=clock, owner_id="reopened"
    ).execute_run(run.run_id)
    assert completed.state == "completed"
    assert len(repository.list_outbox()) == 1
    transport = MockTransport([HttpResponse(200, {}, b'{"ok":true,"result":{"message_id":91}}')])
    registry = ChannelDestinationRegistry(repository, {"telegram-main": _telegram(transport)}, clock=clock)
    delivery = DeliveryWorker(
        repository, {}, owner_id="scheduler-delivery", clock=clock,
        destination_resolver=lambda name: registry.resolve(name.removeprefix("channel:")),
        destination_names=lambda: ("channel:telegram-main",),
    )
    assert await delivery.run_once(clock()) == 1
    assert await delivery.run_once(clock()) == 0
    assert len(transport.requests) == 1
    control.close()


@pytest.mark.asyncio
async def test_goal_continues_after_restart_then_completes_with_strict_evidence_and_budget(tmp_path):
    clock = Clock()
    control, raw, principal, operator = _open(tmp_path, goal=True)
    configuration = GoalConfiguration(
        acceptance=GoalAcceptance(("tests pass",), confidence_threshold=0.8),
        budget=GoalBudget(3, 10, 1.0, 300),
        pricing=PricingSnapshot("2026-08", "USD", 0.01),
    )
    first = raw.create_goal_with_first_iteration(
        session_id="goal-session", goal_text="finish", configuration=configuration.to_record(),
        now=clock(), principal=principal,
    )
    not_done = JudgeResult(
        False, 0.6, "continue", "run again",
        criterion_evidence={"tests pass": {"satisfied": False, "evidence": "pending"}},
    )
    iteration = await GoalRunner(
        raw, ScriptedRunner(["draft"]), ScriptedJudge([not_done]), owner_id="goal-1",
        clock=clock, request_principal=principal,
    ).run_iteration(first.goal_id)
    assert iteration.state == "completed"
    assert control.get_goal(first.goal_id)["status"] == "running"
    control.close()

    clock.advance(seconds=1)
    control, raw, principal, operator = _open(tmp_path, goal=True)
    done = JudgeResult(
        True, 1.0, "accepted", "",
        criterion_evidence={"tests pass": {"satisfied": True, "evidence": "pytest passed"}},
    )
    runner = GoalRunner(
        raw, ScriptedRunner(["final"]), ScriptedJudge([done]), owner_id="goal-2",
        clock=clock, request_principal=principal,
    )
    assert runner.recover(clock()) == [first.goal_id]
    terminal = await runner.run_iteration(first.goal_id)
    assert terminal.state == "completed"
    goal = control.get_goal(first.goal_id)
    assert goal["status"] == "completed"
    assert goal["used_iterations"] == 2
    assert goal["used_tokens"] == 2
    repository_states = [item.state for item in raw.list_outbox()]
    assert repository_states
    assert repository_states == ["pending"]
    control.close()


@pytest.mark.asyncio
async def test_supervisor_readiness_one_poll_and_drain_has_no_live_runtime_tasks():
    calls = []

    async def poll():
        calls.append("poll")

    supervisor = DurableRuntimeSupervisor(
        [WorkerSpec("e2e", poll, interval=60)], drain_timeout=0.1
    )
    await supervisor.start()
    await supervisor.wait_ready(timeout=1)
    assert calls == ["poll"]
    assert supervisor.snapshot().ready is True
    await supervisor.stop()
    assert supervisor.snapshot().running is False
    assert supervisor._tasks == {}


def test_operations_runbook_and_readme_are_published():
    root = Path(__file__).resolve().parents[2]
    runbook = root / "docs" / "autonomous-runtime-operations.md"
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert runbook.is_file()
    text = runbook.read_text(encoding="utf-8")
    for required in (
        "Telegram", "Discord", "Slack", "WhatsApp", "Feishu", "DingTalk",
        "LINE", "QQ", "WeCom", "delivery_unknown", "retention", "backup",
        "restore", "DST", "approval", "forward-only",
    ):
        assert required.casefold() in text.casefold()
    assert "docs/autonomous-runtime-operations.md" in readme
