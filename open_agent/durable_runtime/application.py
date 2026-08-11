"""Canonical application composition for durable runtime workers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
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
from open_agent.gateway.ingress import IngressLimits, IngressService
from open_agent.gateway.router import GatewayRouter
from open_agent.gateway.security import (
    HierarchicalIngressLimiter, IngressGuard, LimitRule, QuotaSnapshot,
    ResourceQuotaPolicy, WebhookAuthenticator,
)
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


class _NonceStore:
    """Fallback nonce claim for custom HMAC adapters; official adapters use durable receipts."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], datetime] = {}
        self._lock = threading.Lock()

    def claim(self, account_id: str, nonce: str, expires_at: datetime) -> bool:
        now = _now()
        key = (account_id, nonce)
        with self._lock:
            values = {item: expiry for item, expiry in self._values.items() if expiry > now}
            if key in values:
                return False
            values[key] = expires_at
            self._values = values
        return True


class _QuotaLedger:
    def __init__(self) -> None:
        self._tokens: frozenset[str] = frozenset()
        self._lock = threading.Lock()

    def try_reserve(self, policy, request, conversation_id):
        del policy, request, conversation_id
        token = uuid.uuid4().hex
        with self._lock:
            if len(self._tokens) >= 100:
                return None
            self._tokens = self._tokens | {token}
        return token

    def release(self, token):
        with self._lock:
            self._tokens = self._tokens - {token}


@dataclass(slots=True)
class RuntimeComposition:
    repository: DurableRuntimeRepository
    supervisor: DurableRuntimeSupervisor
    adapters: dict[str, Any]
    _destination_registry: ChannelDestinationRegistry
    goal_capability: object
    operator_capability: object
    operational_auth: Any
    credential_store: Any = None
    ingress_service: Any = None
    public_webhook_limiter: Any = None
    retention_policy: RetentionPolicy | None = None
    retention_worker: RetentionWorker | None = None

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
    operator_capability = object()
    retention_key = _load_retention_key(data_dir)
    control = get_control_plane(get_agent_profile_manager().get_agent_home(None))
    repository = DurableRuntimeRepository(
        control,
        retention_hmac_key=retention_key,
        goal_authority_capability=capability,
        operator_authority_capability=operator_capability,
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
    limiter_rules = {
        "global": LimitRule(600, timedelta(minutes=1), 100),
        "ip": LimitRule(120, timedelta(minutes=1), 20),
        "adapter": LimitRule(300, timedelta(minutes=1), 50),
        "account": LimitRule(180, timedelta(minutes=1), 30),
    }
    public_webhook_limiter = HierarchicalIngressLimiter(limiter_rules, now=_now)
    ingress_service = IngressService(
        repository,
        GatewayRouter(repository),
        ingress_guard=IngressGuard(
            WebhookAuthenticator(
                secret_lookup=lambda _account: None,
                nonce_store=_NonceStore(),
                max_age=timedelta(minutes=5),
            ),
            HierarchicalIngressLimiter(limiter_rules, now=_now),
        ),
        quota_policy=ResourceQuotaPolicy(
            max_queue_depth=10_000,
            max_database_bytes=4 * 1024**3,
            min_disk_free_bytes=256 * 1024**2,
            max_attachment_bytes=2 * 1024**2,
            max_agents_per_conversation=1,
        ),
        quota_ledger=_QuotaLedger(),
        quota_snapshot=lambda _event: _quota_snapshot(control, data_dir),
        limits=IngressLimits(max_body_bytes=1024 * 1024),
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
    persisted_policy = control._get_conn().execute(
        """SELECT inbox_days, outbox_days, audit_days
             FROM runtime_retention_policy WHERE tenant_id='__global__'"""
    ).fetchone() if control._get_conn().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_retention_policy'"
    ).fetchone() else None
    retention_policy = RetentionPolicy(
        inbox_payload_ttl=timedelta(days=int(persisted_policy["inbox_days"]) if persisted_policy else 30),
        outbox_delivery_ttl=timedelta(days=int(persisted_policy["outbox_days"]) if persisted_policy else 30),
        audit_ttl=timedelta(days=int(persisted_policy["audit_days"]) if persisted_policy else 90),
    )
    retention = RetentionWorker(
        repository,
        retention_policy,
        attachments,
    )
    def run_retention_once():
        summary = retention.run_once(_now())
        completed_at = _now().isoformat()
        with control._get_conn() as conn:
            conn.execute(
                """UPDATE runtime_retention_requests
                     SET state='completed', completed_at=? WHERE state='pending'""",
                (completed_at,),
            )
        return summary

    from open_agent.app.runner.auth import OperationalAuthStore
    from open_agent.gateway.credentials import CredentialStore

    credential_store = None
    if os.name == "nt":
        try:
            from open_agent.gateway.credentials import WindowsCredentialBackend

            credential_store = CredentialStore(
                WindowsCredentialBackend(target_prefix="OpenAgentSeal/Channels/")
            )
        except RuntimeError:
            credential_store = None

    def run_credential_cleanup_once():
        if credential_store is None:
            return 0
        now = _now()
        conn = control._get_conn()
        rows = conn.execute(
            """SELECT * FROM runtime_credential_cleanup
                 WHERE state='pending' AND next_attempt_at<=?
                 ORDER BY created_at, cleanup_id LIMIT 10""",
            (now.isoformat(),),
        ).fetchall()
        completed = 0
        for row in rows:
            try:
                credential_store.delete_for_account(row["account_id"], row["credential_ref"])
            except Exception as exc:
                attempt = int(row["attempt"]) + 1
                state = "dead_letter" if attempt >= 10 else "pending"
                retry_at = now + timedelta(seconds=min(3600, 2 ** min(attempt, 12)))
                with conn:
                    conn.execute(
                        """UPDATE runtime_credential_cleanup SET state=?, attempt=?,
                             next_attempt_at=?, last_error=? WHERE cleanup_id=? AND state='pending'""",
                        (state, attempt, retry_at.isoformat(), exc.__class__.__name__, row["cleanup_id"]),
                    )
            else:
                with conn:
                    conn.execute(
                        """UPDATE runtime_credential_cleanup SET state='completed',
                             completed_at=?, last_error=NULL WHERE cleanup_id=? AND state='pending'""",
                        (now.isoformat(), row["cleanup_id"]),
                    )
                completed += 1
        return completed

    supervisor = DurableRuntimeSupervisor(
        [
            WorkerSpec("inbox", inbox.run_once, interval=0.5),
            WorkerSpec("scheduler", scheduler.run_once, interval=1.0),
            WorkerSpec("goal", goal.run_once, interval=1.0),
            WorkerSpec("outbox", lambda: outbox.run_once(_now()), interval=0.5),
            WorkerSpec(
                "retention",
                run_retention_once,
                interval=3600,
            ),
            WorkerSpec(
                "credential_cleanup", run_credential_cleanup_once,
                interval=30, required=False,
            ),
        ]
    )
    return RuntimeComposition(
        repository, supervisor, adapters, registry, capability, operator_capability,
        OperationalAuthStore(
            signing_key=hmac.new(
                retention_key, b"operational-auth-v1", hashlib.sha256
            ).digest(),
            trusted_origins=tuple(
                origin.strip()
                for origin in os.environ.get(
                    "OPEN_AGENT_ALLOWED_ORIGINS",
                    "http://127.0.0.1:8088,http://localhost:8088,http://tauri.localhost",
                ).split(",")
                if origin.strip()
            ),
            bootstrap_token=os.environ.get("OPEN_AGENT_OPERATIONAL_BOOTSTRAP_TOKEN") or None,
        ),
        credential_store=credential_store,
        ingress_service=ingress_service,
        public_webhook_limiter=public_webhook_limiter,
        retention_policy=retention_policy,
        retention_worker=retention,
    )


def _quota_snapshot(control: Any, data_dir: Path) -> QuotaSnapshot:
    conn = control._get_conn()
    queue_depth = int(conn.execute(
        "SELECT COUNT(*) FROM inbox_events WHERE state IN ('pending','claimed','dispatched','retry_wait')"
    ).fetchone()[0])
    try:
        database_bytes = control.db_path.stat().st_size
    except OSError:
        database_bytes = 4 * 1024**3 + 1
    try:
        disk_free = shutil.disk_usage(data_dir).free
    except OSError:
        disk_free = 0
    return QuotaSnapshot(
        queue_depth=queue_depth,
        database_bytes=database_bytes,
        disk_free_bytes=disk_free,
        attachment_bytes=0,
        conversation_agents=0,
    )


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
