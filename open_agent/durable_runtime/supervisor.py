"""Lifecycle supervision for the durable autonomous runtime."""

from __future__ import annotations

import asyncio
import inspect
import random
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isfinite
from typing import Awaitable, Callable


Poll = Callable[[], object | Awaitable[object]]


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    """Immutable configuration for one independently supervised worker family."""

    name: str
    poll: Poll
    interval: float = 1.0
    required: bool = True
    backoff_base: float = 0.25
    backoff_cap: float = 30.0
    jitter: float = 0.1
    cancel_on_stop: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 64:
            raise ValueError("worker name must be a bounded non-empty string")
        if not callable(self.poll):
            raise TypeError("worker poll must be callable")
        for value, label in (
            (self.interval, "interval"),
            (self.backoff_base, "backoff_base"),
            (self.backoff_cap, "backoff_cap"),
            (self.jitter, "jitter"),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(f"{label} must be finite")
        if self.interval <= 0 or self.backoff_base <= 0 or self.backoff_cap < self.backoff_base:
            raise ValueError("worker timing values must be positive and bounded")
        if not 0 <= self.jitter <= 1:
            raise ValueError("jitter must be between zero and one")
        if type(self.cancel_on_stop) is not bool:
            raise TypeError("cancel_on_stop must be a boolean")


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    name: str
    running: bool = False
    first_poll_succeeded: bool = False
    poll_count: int = 0
    restart_count: int = 0
    last_success_at: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeHealthSnapshot:
    running: bool
    ready: bool
    workers: tuple[WorkerHealth, ...]


class DurableRuntimeSupervisor:
    """Own one crash-isolated loop per durable worker kind."""

    def __init__(
        self,
        workers: list[WorkerSpec] | tuple[WorkerSpec, ...],
        *,
        drain_timeout: float = 10.0,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        specs = tuple(workers)
        names = [spec.name for spec in specs]
        if len(names) != len(set(names)):
            raise ValueError("worker names must be unique")
        if (
            isinstance(drain_timeout, bool)
            or not isinstance(drain_timeout, (int, float))
            or not isfinite(drain_timeout)
            or drain_timeout <= 0
        ):
            raise ValueError("drain_timeout must be positive and finite")
        self._specs = {spec.name: spec for spec in specs}
        self._health = {spec.name: WorkerHealth(spec.name) for spec in specs}
        self._wake = {spec.name: asyncio.Event() for spec in specs}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._ready = asyncio.Event()
        self._drain_timeout = float(drain_timeout)
        self._random = random_source
        self._lifecycle_lock = asyncio.Lock()
        self._running = False

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._running:
                return
            self._running = True
            self._ready.clear()
            if not any(spec.required for spec in self._specs.values()):
                self._ready.set()
            for name, spec in self._specs.items():
                self._health[name] = replace(
                    self._health[name], running=True, first_poll_succeeded=False
                )
                self._tasks[name] = asyncio.create_task(
                    self._worker_loop(spec), name=f"durable-runtime:{name}"
                )
            # Let every worker enter its startup recovery poll before start returns.
            await asyncio.sleep(0)

    def wake(self, name: str) -> None:
        event = self._wake.get(name)
        if event is None:
            raise KeyError(f"unknown worker: {name}")
        event.set()

    async def wait_ready(self, *, timeout: float | None = None) -> None:
        if timeout is None:
            await self._ready.wait()
        else:
            await asyncio.wait_for(self._ready.wait(), timeout)

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if not self._running and not self._tasks:
                return
            self._running = False
            for event in self._wake.values():
                event.set()
            tasks = tuple(self._tasks.values())
            if tasks:
                for name, task in self._tasks.items():
                    if self._specs[name].cancel_on_stop:
                        task.cancel()
                _, pending = await asyncio.wait(tasks, timeout=self._drain_timeout)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            self._tasks.clear()
            for name, health in tuple(self._health.items()):
                self._health[name] = replace(health, running=False)
            self._ready.clear()

    def snapshot(self) -> RuntimeHealthSnapshot:
        workers = tuple(self._health[name] for name in sorted(self._health))
        ready = self._running and all(
            not self._specs[health.name].required or health.first_poll_succeeded
            for health in workers
        )
        return RuntimeHealthSnapshot(self._running, ready, workers)

    async def _worker_loop(self, spec: WorkerSpec) -> None:
        failures = 0
        wake = self._wake[spec.name]
        try:
            while self._running:
                # Clear before polling: a wake that arrives during the poll remains
                # set and causes an immediate second pass.
                wake.clear()
                try:
                    result = spec.poll()
                    if inspect.isawaitable(result):
                        await result
                    now = datetime.now(timezone.utc)
                    current = self._health[spec.name]
                    self._health[spec.name] = replace(
                        current,
                        first_poll_succeeded=True,
                        poll_count=current.poll_count + 1,
                        last_success_at=now,
                    )
                    failures = 0
                    self._update_ready()
                    delay = spec.interval
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    failures += 1
                    current = self._health[spec.name]
                    self._health[spec.name] = replace(
                        current,
                        restart_count=current.restart_count + 1,
                        last_error=type(exc).__name__,
                    )
                    raw = min(spec.backoff_cap, spec.backoff_base * (2 ** min(failures - 1, 20)))
                    factor = 1 + ((self._random() * 2) - 1) * spec.jitter
                    delay = max(0.001, raw * factor)
                if self._running and not wake.is_set():
                    try:
                        await asyncio.wait_for(wake.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
        finally:
            current = self._health[spec.name]
            self._health[spec.name] = replace(current, running=False)

    def _update_ready(self) -> None:
        if all(
            not spec.required or self._health[name].first_poll_succeeded
            for name, spec in self._specs.items()
        ):
            self._ready.set()

__all__ = [
    "DurableRuntimeSupervisor",
    "RuntimeHealthSnapshot",
    "WorkerHealth",
    "WorkerSpec",
]
