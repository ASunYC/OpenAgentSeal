"""Canonical application composition for durable runtime workers."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from open_agent.durable_runtime.delivery import DeliveryWorker, LocalSessionDestination
from open_agent.durable_runtime.repository import DurableRuntimeRepository
from open_agent.durable_runtime.retention import RetentionPolicy, RetentionWorker
from open_agent.gateway.destinations import (
    CHANNEL_DESTINATION_PREFIX,
    ChannelDestinationRegistry,
)
from open_agent.gateway.ingress import IngressWorker
from open_agent.gateway.router import GatewayRouter
from open_agent.goal_mode import JudgeResult
from open_agent.goal_runtime import GoalRunner
from open_agent.scheduler_runtime import SchedulerWorker

from .supervisor import DurableRuntimeSupervisor, WorkerSpec


_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class _AgentGoalJudge:
    def __init__(self, runner: Any) -> None:
        self._runner = runner

    async def judge(self, *, goal, iteration, content: str) -> JudgeResult:
        criteria = tuple(goal.get("acceptance_criteria") or ())
        prompt = (
            "Judge the prior autonomous result against every acceptance criterion. "
            "Return JSON only with exactly: done, confidence, reason, next_action, "
            "criterion_evidence. criterion_evidence must contain every criterion as a key "
            "with {satisfied:boolean,evidence:string}.\n"
            f"Goal: {goal.get('goal_text', '')}\nCriteria: {json.dumps(criteria, ensure_ascii=False)}\n"
            f"Result: {content}"
        )
        result_text = await self._runner.generate_judge_json(prompt)
        return JudgeResult.from_json(_JSON_FENCE.sub("", result_text.strip()))


class _GoalWorker:
    def __init__(self, repository, runner, capability: object) -> None:
        self._repository = repository
        self._runner = runner
        self._judge = _AgentGoalJudge(runner)
        self._capability = capability

    async def run_once(self) -> None:
        row = self._repository.control_plane._get_conn().execute(
            """SELECT g.goal_id, s.user_id,
                      COALESCE(json_extract(s.metadata, '$.tenant_id'), 'default') AS tenant_id
               FROM goals g JOIN sessions s ON s.session_id = g.session_id
               JOIN goal_iterations gi ON gi.goal_id = g.goal_id
               WHERE g.status IN ('running', 'runnable')
                 AND (gi.state IN ('pending', 'retry_wait')
                      OR (gi.state IN ('running', 'judging') AND gi.claim_expires_at <= ?))
                 AND (gi.next_attempt_at IS NULL OR gi.next_attempt_at <= ?)
               ORDER BY gi.created_at, gi.iteration_id LIMIT 1""",
            (_now().isoformat(), _now().isoformat()),
        ).fetchone()
        if row is None:
            return
        principal = self._repository.mint_goal_principal(
            actor_id=str(row["user_id"]),
            tenant_id=str(row["tenant_id"]),
            capability=self._capability,
        )
        worker = GoalRunner(
            self._repository,
            self._runner,
            self._judge,
            owner_id=f"goal-supervisor-{uuid.uuid4().hex[:12]}",
            request_principal=principal,
        )
        await worker.run_iteration(str(row["goal_id"]))


@dataclass(slots=True)
class RuntimeComposition:
    repository: DurableRuntimeRepository
    supervisor: DurableRuntimeSupervisor
    adapters: dict[str, Any]
    _destination_registry: ChannelDestinationRegistry

    def register_adapter(self, account_id: str, adapter: Any) -> None:
        if getattr(adapter, "account_id", None) != account_id:
            raise ValueError("adapter account identity mismatch")
        self.adapters[account_id] = adapter
        self._destination_registry._adapters[account_id] = adapter
        self.supervisor.wake("outbox")


_composition: RuntimeComposition | None = None
_composition_lock = threading.Lock()


def get_runtime_composition() -> RuntimeComposition:
    """Build once, without starting background work."""
    global _composition
    with _composition_lock:
        if _composition is None:
            _composition = _build_runtime_composition()
        return _composition


def _build_runtime_composition() -> RuntimeComposition:
    from open_agent.agent_profiles import get_agent_profile_manager
    from open_agent.app.runner.runner import get_runner
    from open_agent.control_plane import get_control_plane
    from open_agent.utils.path_utils import get_data_dir

    data_dir = get_data_dir()
    attachments = data_dir / "gateway" / "attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    capability = object()
    control = get_control_plane(get_agent_profile_manager().get_agent_home(None))
    repository = DurableRuntimeRepository(
        control,
        retention_hmac_key=_load_retention_key(data_dir),
        goal_authority_capability=capability,
    )
    runner = get_runner()
    adapters: dict[str, Any] = {}
    registry = ChannelDestinationRegistry(repository, adapters)

    def resolve_destination(name: str):
        if name == "local_session":
            return LocalSessionDestination(repository)
        if name.startswith(CHANNEL_DESTINATION_PREFIX):
            return registry.resolve(name.removeprefix(CHANNEL_DESTINATION_PREFIX))
        raise KeyError(name)

    def destination_names() -> tuple[str, ...]:
        enabled = []
        for account_id in tuple(adapters):
            account = repository.get_channel_account(account_id)
            if account is not None and account["enabled"]:
                enabled.append(f"{CHANNEL_DESTINATION_PREFIX}{account_id}")
        return ("local_session", *enabled)

    inbox = IngressWorker(
        repository, GatewayRouter(repository), runner,
        worker_id=f"inbox-{uuid.uuid4().hex[:12]}",
    )
    scheduler = SchedulerWorker(
        repository, runner, owner_id=f"scheduler-{uuid.uuid4().hex[:12]}"
    )
    goal = _GoalWorker(repository, runner, capability)
    outbox = DeliveryWorker(
        repository,
        {},
        owner_id=f"outbox-{uuid.uuid4().hex[:12]}",
        destination_resolver=resolve_destination,
        destination_names=destination_names,
    )
    retention = RetentionWorker(
        repository,
        RetentionPolicy(
            inbox_payload_ttl=timedelta(days=30),
            outbox_delivery_ttl=timedelta(days=30),
            audit_ttl=timedelta(days=90),
        ),
        attachments,
    )
    supervisor = DurableRuntimeSupervisor(
        [
            WorkerSpec("inbox", inbox.run_once, interval=0.5),
            WorkerSpec("scheduler", scheduler.run_once, interval=1.0),
            WorkerSpec("goal", goal.run_once, interval=1.0),
            WorkerSpec("outbox", lambda: outbox.run_once(_now()), interval=0.5),
            WorkerSpec(
                "retention",
                lambda: retention.run_once(_now()),
                interval=3600,
            ),
        ]
    )
    return RuntimeComposition(repository, supervisor, adapters, registry)


def _load_retention_key(data_dir: Path) -> bytes:
    encoded = os.environ.get("OPEN_AGENT_RETENTION_HMAC_KEY")
    if encoded:
        try:
            key = base64.urlsafe_b64decode(encoded.encode("ascii"))
        except Exception as exc:
            raise RuntimeError("OPEN_AGENT_RETENTION_HMAC_KEY is invalid") from exc
        if len(key) < 32:
            raise RuntimeError("OPEN_AGENT_RETENTION_HMAC_KEY is too short")
        return key
    if os.name == "nt":
        from open_agent.gateway.credentials import (
            CredentialNotFoundError,
            StoredCredential,
            WindowsCredentialBackend,
        )

        backend = WindowsCredentialBackend(target_prefix="OpenAgentSeal/Runtime/")
        target = "retention-hmac-v1"
        try:
            secret = backend.resolve(target).secret
        except CredentialNotFoundError:
            secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
            backend.put(target, StoredCredential("runtime", secret))
        return base64.urlsafe_b64decode(secret.encode("ascii"))
    path = data_dir / ".retention-hmac-v1"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(base64.urlsafe_b64encode(secrets.token_bytes(32)))
    if path.stat().st_mode & 0o077:
        raise RuntimeError("retention key file permissions are too broad")
    return base64.urlsafe_b64decode(path.read_bytes())


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["RuntimeComposition", "get_runtime_composition"]
