import asyncio
from dataclasses import FrozenInstanceError

import pytest

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


async def _until(predicate):
    while not predicate():
        await asyncio.sleep(0)
