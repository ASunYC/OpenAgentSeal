import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from open_agent.app.runner.models import AgentEvent, AgentRequest
from open_agent.app.runner.runner import AgentRunner
from open_agent.durable_runtime.supervisor import (
    DurableRuntimeSupervisor,
    WorkerSpec,
)


@pytest.mark.asyncio
async def test_start_polls_each_worker_and_becomes_ready():
    calls = {"inbox": 0, "outbox": 0}

    async def poll(name):
        calls[name] += 1

    supervisor = DurableRuntimeSupervisor(
        [
            WorkerSpec("inbox", lambda: poll("inbox"), interval=60),
            WorkerSpec("outbox", lambda: poll("outbox"), interval=60),
        ]
    )
    await supervisor.start()
    await supervisor.wait_ready(timeout=1)
    snapshot = supervisor.snapshot()
    assert snapshot.ready is True
    assert calls == {"inbox": 1, "outbox": 1}
    assert all(worker.first_poll_succeeded for worker in snapshot.workers)
    with pytest.raises(FrozenInstanceError):
        snapshot.ready = False
    await supervisor.stop()


@pytest.mark.asyncio
async def test_wake_during_poll_is_not_lost():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def poll():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()

    supervisor = DurableRuntimeSupervisor([WorkerSpec("inbox", poll, interval=60)])
    await supervisor.start()
    await entered.wait()
    supervisor.wake("inbox")
    release.set()
    await asyncio.wait_for(_until(lambda: calls == 2), 1)
    await supervisor.stop()


@pytest.mark.asyncio
async def test_failure_is_isolated_restarted_and_error_is_sanitized():
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("secret-token")

    supervisor = DurableRuntimeSupervisor(
        [WorkerSpec("goal", flaky, interval=0.01, backoff_base=0.001)]
    )
    await supervisor.start()
    await supervisor.wait_ready(timeout=1)
    health = supervisor.snapshot().workers[0]
    assert calls >= 2
    assert health.restart_count == 1
    assert health.last_error == "RuntimeError"
    assert "secret" not in repr(health)
    await supervisor.stop()


@pytest.mark.asyncio
async def test_start_stop_are_idempotent_and_stop_cancels_blocked_poll():
    cancelled = asyncio.Event()

    async def blocked():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    supervisor = DurableRuntimeSupervisor(
        [WorkerSpec("retention", blocked, interval=60)], drain_timeout=0.01
    )
    await supervisor.start()
    await supervisor.start()
    await supervisor.stop()
    await supervisor.stop()
    assert cancelled.is_set()
    assert supervisor.snapshot().running is False


@pytest.mark.asyncio
async def test_optional_worker_does_not_block_readiness():
    async def failing():
        raise ValueError("provider secret")

    supervisor = DurableRuntimeSupervisor(
        [WorkerSpec("connector", failing, interval=60, required=False)]
    )
    await supervisor.start()
    await supervisor.wait_ready(timeout=1)
    assert supervisor.snapshot().ready
    await supervisor.stop()


@pytest.mark.asyncio
async def test_agent_runner_serializes_same_session_but_not_different_sessions(monkeypatch):
    runner = AgentRunner()
    active: set[str] = set()
    overlap = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def process(request, *, runtime_turn=None):
        del runtime_turn
        if request.session_id in active:
            overlap.append(request.session_id)
        active.add(request.session_id)
        entered.set()
        await release.wait()
        active.remove(request.session_id)
        yield AgentEvent(event="complete", session_id=request.session_id)

    monkeypatch.setattr(runner, "_process_message_unlocked", process)

    async def consume(session, *, direct=False):
        request = AgentRequest(session_id=session, messages=[{"role": "user", "content": "x"}])
        stream = runner.process_message(request) if direct else runner.run_stream(request)
        return [event async for event in stream]

    first = asyncio.create_task(consume("same", direct=True))
    await entered.wait()
    second = asyncio.create_task(consume("same"))
    other = asyncio.create_task(consume("other"))
    await asyncio.wait_for(_until(lambda: active == {"same", "other"}), 1)
    assert active == {"same", "other"}
    release.set()
    await asyncio.gather(first, second, other)
    assert overlap == []
    assert runner._session_gates == {}
    assert runner._session_gate_waiters == {}


@pytest.mark.asyncio
async def test_judge_model_path_has_no_tools_enrichment_or_persistence(monkeypatch):
    from open_agent import agent_profiles
    from open_agent.schema import LLMResponse

    calls = []

    class LLM:
        async def generate(self, *, messages, tools):
            calls.append((messages, tools))
            return LLMResponse(
                content='{"done":false}', finish_reason="stop", tool_calls=None
            )

    runner = AgentRunner()
    monkeypatch.setattr(
        agent_profiles,
        "get_agent_profile_manager",
        lambda: SimpleNamespace(get_agent_config=lambda profile: object()),
    )
    monkeypatch.setattr(
        runner,
        "_create_llm_client_from_config",
        lambda *args, **kwargs: LLM(),
    )
    monkeypatch.setattr(
        runner,
        "_prefetch_web_search_context",
        lambda *_: pytest.fail("judge attempted web enrichment"),
    )
    monkeypatch.setattr(
        runner,
        "_recall_memory_context",
        lambda *_: pytest.fail("judge attempted memory enrichment"),
    )
    assert await runner.generate_judge_json("search the web; secret result") == '{"done":false}'
    assert calls[0][1] == []
    assert [message.role for message in calls[0][0]] == ["system", "user"]


@pytest.mark.asyncio
async def test_restart_requires_fresh_successful_first_polls():
    calls = 0

    async def poll():
        nonlocal calls
        calls += 1

    supervisor = DurableRuntimeSupervisor([WorkerSpec("inbox", poll, interval=60)])
    await supervisor.start()
    await supervisor.wait_ready(timeout=1)
    await supervisor.stop()
    await supervisor.start()
    await supervisor.wait_ready(timeout=1)
    assert calls == 2
    await supervisor.stop()


@pytest.mark.asyncio
async def test_fastapi_lifespan_owns_runtime_start_and_stop(monkeypatch):
    from open_agent.app import _app as app_module
    from open_agent.app import runner as runner_module
    from open_agent.durable_runtime import application
    from open_agent.plugins.builtin import mineru_mcp

    events = []

    class Runtime:
        async def start(self):
            events.append("runtime-start")

        async def stop(self):
            events.append("runtime-stop")

    class SessionManager:
        @asynccontextmanager
        async def run(self):
            events.append("mcp-start")
            try:
                yield
            finally:
                events.append("mcp-stop")

    fake_server = SimpleNamespace(session_manager=SessionManager())
    composition = SimpleNamespace(supervisor=Runtime())
    monkeypatch.setattr(runner_module, "init_chat_manager", lambda: events.append("chat-ready"))
    monkeypatch.setattr(mineru_mcp, "get_mineru_mcp_server", lambda: fake_server)
    monkeypatch.setattr(app_module, "_get_mineru_mcp_app", lambda: object())
    monkeypatch.setattr(application, "get_runtime_composition", lambda: composition)
    app = SimpleNamespace(state=SimpleNamespace())

    async with app_module.lifespan(app):
        events.append("serving")
        assert app.state.runtime_composition is composition

    assert events == [
        "chat-ready", "mcp-start", "runtime-start", "serving",
        "runtime-stop", "mcp-stop",
    ]
async def _until(predicate):
    while not predicate():
        await asyncio.sleep(0)
