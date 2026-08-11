"""Authenticated operational API for scheduler, goals, retention and supervision."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field, field_validator

from open_agent.app.runner.auth import (
    Authenticated, OperationalPrincipal, RecentPrincipal, require_role,
)
from open_agent.app.runner.gateway_api import _ok, _redact
from open_agent.app.runner.models import StrictOperationalModel
from open_agent.durable_runtime.models import SchedulerRun
from open_agent.durable_runtime.repository import GoalOperatorService, StateConflictError
from open_agent.scheduler_runtime import CronSchedule


router = APIRouter(prefix="/api/operations", tags=["autonomous-runtime-operations"])


class SchedulerJobCreate(StrictOperationalModel):
    job_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    schedule: str = Field(min_length=1, max_length=256)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=100000)
    max_retries: int = Field(default=5, ge=0, le=100)
    destination: str | None = Field(default=None, max_length=256)


class SchedulerJobUpdate(StrictOperationalModel):
    status: Literal["active", "paused", "deleted"]
    expected_version: int = Field(ge=0)


class GoalCreate(StrictOperationalModel):
    goal_id: str | None = Field(default=None, max_length=128)
    session_id: str = Field(min_length=1, max_length=256)
    goal_text: str = Field(min_length=1, max_length=100000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=100)
    max_iterations: int = Field(default=20, ge=1)
    max_tokens: int = Field(default=200000, ge=1)
    max_estimated_cost: float = Field(default=100.0, gt=0)
    max_active_seconds: float = Field(default=86400.0, gt=0)
    destination: str = Field(default="local_session", max_length=256)
    profile_id: str = Field(default="main", min_length=1, max_length=128)

    @field_validator("goal_id", "session_id")
    @classmethod
    def bounded_client_reference(cls, value: str | None) -> str | None:
        return _validate_client_reference(value)


class GoalGuidance(StrictOperationalModel):
    content: str = Field(min_length=1, max_length=4096)

    @field_validator("content")
    @classmethod
    def bounded_utf8(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 4096:
            raise ValueError("guidance exceeds 4096 UTF-8 bytes")
        return value


class GoalControl(StrictOperationalModel):
    action: Literal["pause", "resume", "cancel"]
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=4096)
    approval_id: str | None = Field(default=None, max_length=128)
    operator_decision: Literal["increase_budget", "reset_failures"] | None = None
    budget_updates: dict[str, int | float] = Field(default_factory=dict)


class ApprovalRequest(StrictOperationalModel):
    approval_id: str = Field(min_length=1, max_length=128)
    decision: Literal["increase_budget", "reset_failures"]
    expected_goal_version: int = Field(ge=0)
    budget_updates: dict[str, int | float] = Field(default_factory=dict)
    expires_in_seconds: int = Field(default=300, ge=30, le=900)

    @field_validator("approval_id")
    @classmethod
    def bounded_client_reference(cls, value: str) -> str:
        return _validate_client_reference(value)


def _validate_client_reference(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or len(value.encode("utf-8")) > 128:
        raise ValueError("client reference must contain at most 128 UTF-8 bytes")
    return value


class RetentionPolicyWrite(StrictOperationalModel):
    inbox_days: int = Field(ge=1, le=3650)
    outbox_days: int = Field(ge=1, le=3650)
    audit_days: int = Field(ge=1, le=3650)
    expected_version: int = Field(ge=0)


def _composition(request: Request):
    composition = getattr(request.app.state, "runtime_composition", None)
    if composition is None:
        raise _http(503, "runtime_unavailable", "The durable runtime is unavailable")
    return composition


def _ids(request, principal, kind, limit, cursor, *, shared=False):
    store = request.app.state.operational_auth
    after = ""
    if cursor:
        try:
            after = store.verify_cursor(principal, kind, cursor)
        except ValueError:
            raise _http(422, "invalid_cursor", "The pagination cursor is invalid") from None
    repo = _composition(request).repository
    values = repo.list_operational_ids(
        entity_kind=kind, tenant_id=principal.tenant_id,
        owner_actor_id=None if shared else principal.actor_id,
        after=after, limit=limit + 1,
    )
    page = values[:limit]
    return page, store.sign_cursor(principal, kind, page[-1]) if len(values) > limit and page else None


def _owned(repo, kind, entity_id, principal, *, shared=False):
    return repo.operational_owner_matches(
        kind, entity_id, principal.tenant_id, None if shared else principal.actor_id
    )


@router.post("/scheduler/jobs", status_code=201)
async def create_scheduler_job(body: SchedulerJobCreate, request: Request, principal: RecentPrincipal):
    if "operator" not in principal.roles:
        raise _http(403, "role_required", "Operator role is required")
    parsed = CronSchedule.parse(body.schedule, body.timezone)
    now = datetime.now(timezone.utc)
    next_run = parsed.next_occurrence(now).astimezone(timezone.utc)
    repo = _composition(request).repository
    job_id = request.app.state.operational_auth.mint_resource_id(
        principal, "scheduler_job", body.job_id
    )
    conn = repo.control_plane._get_conn()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM scheduler_jobs WHERE job_id=?", (job_id,)).fetchone():
            raise _http(409, "already_exists", "Scheduler job already exists")
        conn.execute(
            """INSERT INTO scheduler_jobs (
                   job_id, schedule, prompt, status, next_run_at, timezone, max_retries,
                   destination, runtime_version, created_at, updated_at, metadata
               ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, 0, ?, ?, '{}')""",
            (job_id, body.schedule, body.prompt, next_run.isoformat(), body.timezone,
             body.max_retries, body.destination, now.isoformat(), now.isoformat()),
        )
        _insert_owner(conn, "scheduler_job", job_id, principal, now)
    _composition(request).supervisor.wake("scheduler")
    return _ok(_scheduler_job_view(conn.execute("SELECT * FROM scheduler_jobs WHERE job_id=?", (job_id,)).fetchone()))


@router.get("/scheduler/jobs")
async def list_scheduler_jobs(request: Request, principal: Authenticated, limit: Annotated[int, Query(ge=1, le=100)] = 100, cursor: str | None = None):
    ids, next_cursor = _ids(request, principal, "scheduler_job", limit, cursor)
    repo = _composition(request).repository
    rows = [repo.control_plane.get_scheduler_job(entity_id) for entity_id in ids]
    return _ok([_scheduler_job_view(row) for row in rows if row], next_cursor)


@router.get("/scheduler/jobs/{job_id}")
async def get_scheduler_job(job_id: str, request: Request, principal: Authenticated):
    repo = _composition(request).repository
    if not _owned(repo, "scheduler_job", job_id, principal):
        raise _http(404, "not_found", "Resource not found")
    row = repo.control_plane.get_scheduler_job(job_id)
    if row is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok(_scheduler_job_view(row))


@router.patch("/scheduler/jobs/{job_id}")
async def update_scheduler_job(job_id: str, body: SchedulerJobUpdate, request: Request, principal: RecentPrincipal):
    _require_operator(principal)
    repo = _composition(request).repository
    conn = repo.control_plane._get_conn()
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        row = conn.execute(
            """UPDATE scheduler_jobs SET status=?, runtime_version=runtime_version+1, updated_at=?
               WHERE job_id=? AND runtime_version=? AND EXISTS (
                 SELECT 1 FROM runtime_operational_ownership o WHERE
                   o.entity_kind='scheduler_job' AND o.entity_id=scheduler_jobs.job_id
                   AND o.tenant_id=? AND o.owner_actor_id=?
               ) RETURNING *""",
            (body.status, now, job_id, body.expected_version, principal.tenant_id, principal.actor_id),
        ).fetchone()
    if row is None:
        if not _owned(repo, "scheduler_job", job_id, principal):
            raise _http(404, "not_found", "Resource not found")
        raise _http(409, "version_conflict", "The resource changed concurrently")
    _composition(request).supervisor.wake("scheduler")
    return _ok(_scheduler_job_view(row))


@router.post("/scheduler/jobs/{job_id}/trigger", status_code=202)
async def trigger_scheduler_job(job_id: str, request: Request, principal: RecentPrincipal):
    _require_operator(principal)
    repo = _composition(request).repository
    if not _owned(repo, "scheduler_job", job_id, principal):
        raise _http(404, "not_found", "Resource not found")
    now = datetime.now(timezone.utc)
    run = repo.create_manual_scheduler_run(
        job_id, request_id=f"operator:{principal.actor_id}:{uuid.uuid4().hex}", now=now
    )
    repo.bind_operational_owner(
        entity_kind="scheduler_run", entity_id=run.run_id,
        tenant_id=principal.tenant_id, owner_actor_id=principal.actor_id,
    )
    _composition(request).supervisor.wake("scheduler")
    return _ok(_scheduler_run_view(run))


@router.get("/scheduler/runs")
async def list_scheduler_runs(request: Request, principal: Authenticated, limit: Annotated[int, Query(ge=1, le=100)] = 100, cursor: str | None = None):
    ids, next_cursor = _ids(request, principal, "scheduler_run", limit, cursor)
    repo = _composition(request).repository
    rows = [repo.get_scheduler_run(entity_id) for entity_id in ids]
    return _ok([_scheduler_run_view(row) for row in rows if row], next_cursor)


@router.get("/scheduler/runs/{run_id}")
async def get_scheduler_run(run_id: str, request: Request, principal: Authenticated):
    repo = _composition(request).repository
    if not _owned(repo, "scheduler_run", run_id, principal):
        raise _http(404, "not_found", "Resource not found")
    row = repo.get_scheduler_run(run_id)
    if row is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok(_scheduler_run_view(row))


@router.post("/goals", status_code=201)
async def create_goal(body: GoalCreate, request: Request, principal: RecentPrincipal):
    _require_operator(principal)
    composition = _composition(request)
    capability = getattr(composition, "goal_capability", None)
    if capability is None:
        raise _http(503, "goal_authority_unavailable", "Goal authority is unavailable")
    trusted = composition.repository.mint_goal_principal(
        actor_id=principal.actor_id, tenant_id=principal.tenant_id, capability=capability
    )
    goal_id = request.app.state.operational_auth.mint_resource_id(
        principal, "goal", body.goal_id or uuid.uuid4().hex
    )
    session_id = request.app.state.operational_auth.mint_resource_id(
        principal, "goal_session", body.session_id
    )
    try:
        iteration = composition.repository.create_goal_with_first_iteration(
            session_id=session_id, goal_text=body.goal_text,
            goal_id=goal_id,
            configuration={
                "acceptance_criteria": list(body.acceptance_criteria),
                "judge_schema_version": "1", "judge_prompt_version": "1",
                "judge_confidence_threshold": 1.0,
                "max_iterations": body.max_iterations, "max_tokens": body.max_tokens,
                "max_estimated_cost": body.max_estimated_cost,
                "max_active_seconds": body.max_active_seconds,
                "pricing_version": "operator-v1", "pricing_currency": "USD",
                "pricing_cost_per_token": 0.0,
            },
            destination=body.destination, metadata={"profile_id": body.profile_id},
            now=datetime.now(timezone.utc), principal=trusted,
        )
    except sqlite3.IntegrityError:
        raise _http(409, "already_exists", "Goal already exists") from None
    except ValueError:
        raise _http(422, "invalid_goal", "Goal configuration is invalid") from None
    composition.repository.bind_operational_owner(
        entity_kind="goal", entity_id=iteration.goal_id,
        tenant_id=principal.tenant_id, owner_actor_id=principal.actor_id,
    )
    composition.supervisor.wake("goal")
    return _ok(_goal_view(composition.repository.control_plane.get_goal(iteration.goal_id)))


@router.get("/goals")
async def list_goals(request: Request, principal: Authenticated, limit: Annotated[int, Query(ge=1, le=100)] = 100, cursor: str | None = None):
    ids, next_cursor = _ids(request, principal, "goal", limit, cursor)
    repo = _composition(request).repository
    capability = getattr(_composition(request), "goal_capability", None)
    if capability is None:
        raise _http(503, "goal_authority_unavailable", "Goal authority is unavailable")
    trusted = repo.mint_goal_principal(actor_id=principal.actor_id, tenant_id=principal.tenant_id, capability=capability)
    rows = [repo.get_goal_for_principal(item_id, trusted, conceal=True) for item_id in ids]
    return _ok([_goal_view(row) for row in rows if row is not None], next_cursor)


@router.get("/goals/{goal_id}")
async def get_goal(goal_id: str, request: Request, principal: Authenticated):
    repo = _composition(request).repository
    if not _owned(repo, "goal", goal_id, principal):
        raise _http(404, "not_found", "Resource not found")
    trusted = _goal_principal(request, principal)
    row = repo.get_goal_for_principal(goal_id, trusted, conceal=True)
    if row is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok(_goal_view(row))


@router.get("/goals/{goal_id}/iterations")
async def goal_iterations(goal_id: str, request: Request, principal: Authenticated, limit: Annotated[int, Query(ge=1, le=100)] = 100):
    repo = _composition(request).repository
    if repo.get_goal_for_principal(
        goal_id, _goal_principal(request, principal), conceal=True
    ) is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok([_iteration_view(item) for item in repo.list_goal_iterations(goal_id, limit)])


@router.post("/goals/{goal_id}/guidance", status_code=202)
async def append_guidance(goal_id: str, body: GoalGuidance, request: Request, principal: RecentPrincipal):
    _require_operator(principal)
    repo = _composition(request).repository
    try:
        sequence = repo.append_goal_guidance(
            goal_id, body.content, now=datetime.now(timezone.utc),
            principal=_goal_principal(request, principal),
        )
    except (KeyError, PermissionError):
        raise _http(404, "not_found", "Resource not found") from None
    except ValueError:
        raise _http(422, "invalid_guidance", "Guidance is invalid") from None
    _composition(request).supervisor.wake("goal")
    return _ok({"goal_id": goal_id, "sequence": sequence})


@router.get("/goals/{goal_id}/guidance")
async def list_guidance(
    goal_id: str, request: Request, principal: Authenticated,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    try:
        rows = _composition(request).repository.list_goal_guidance(
            goal_id, after_sequence=after_sequence, limit=limit,
            principal=_goal_principal(request, principal),
        )
    except (KeyError, PermissionError):
        raise _http(404, "not_found", "Resource not found") from None
    return _ok([_redact(row) for row in rows])


@router.post("/goals/{goal_id}/control")
async def control_goal(goal_id: str, body: GoalControl, request: Request, principal: RecentPrincipal):
    _require_operator(principal)
    repo = _composition(request).repository
    try:
        row = repo.transition_goal(
            goal_id, expected_version=body.expected_version, action=body.action,
            now=datetime.now(timezone.utc), reason=body.reason,
            principal=_goal_principal(request, principal),
            operator_decision=body.operator_decision, approval_id=body.approval_id,
            budget_updates=body.budget_updates,
        )
    except KeyError:
        raise _http(404, "not_found", "Resource not found") from None
    except StateConflictError:
        raise _http(409, "version_conflict", "The goal changed concurrently") from None
    _composition(request).supervisor.wake("goal")
    return _ok(_goal_view(row))


@router.post("/goals/{goal_id}/approvals", status_code=201)
async def approve_goal(
    goal_id: str, body: ApprovalRequest, request: Request,
    principal: Annotated[OperationalPrincipal, Depends(require_role("operator"))],
    recent: RecentPrincipal,
):
    del recent
    composition = _composition(request)
    capability = getattr(composition, "operator_capability", None)
    if capability is None:
        raise _http(503, "operator_authority_unavailable", "Operator authority is unavailable")
    subject = _goal_principal(request, principal)
    approval_id = request.app.state.operational_auth.mint_resource_id(
        principal, "goal_approval", body.approval_id
    )
    GoalOperatorService(
        composition.repository, capability,
        issuer_id=principal.actor_id, tenant_id=principal.tenant_id,
    ).approve(
        subject, goal_id, approval_id=approval_id, decision=body.decision,
        expected_goal_version=body.expected_goal_version,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=body.expires_in_seconds),
        now=datetime.now(timezone.utc), budget_updates=body.budget_updates,
    )
    return _ok({"approval_id": approval_id, "issued": True})


@router.get("/supervisor/health")
async def supervisor_health(request: Request, principal: Authenticated):
    del principal
    snapshot = _composition(request).supervisor.snapshot()
    value = asdict(snapshot) if is_dataclass(snapshot) else {
        key: getattr(snapshot, key) for key in ("running", "ready", "workers") if hasattr(snapshot, key)
    }
    return _ok(_redact(value))


@router.get("/retention/policy")
async def get_retention_policy(request: Request, principal: Authenticated):
    row = _retention_row(_composition(request).repository, "__global__")
    return _ok(row or {"inbox_days": 30, "outbox_days": 30, "audit_days": 90, "version": 0})


@router.put("/retention/policy")
async def set_retention_policy(body: RetentionPolicyWrite, request: Request, principal: RecentPrincipal):
    _require_system_operator(principal)
    repo = _composition(request).repository
    conn = repo.control_plane._get_conn()
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS runtime_retention_policy (
                 tenant_id TEXT PRIMARY KEY, inbox_days INTEGER NOT NULL,
                 outbox_days INTEGER NOT NULL, audit_days INTEGER NOT NULL,
                 version INTEGER NOT NULL, updated_at TEXT NOT NULL)"""
        )
        current = conn.execute("SELECT version FROM runtime_retention_policy WHERE tenant_id='__global__'").fetchone()
        version = int(current["version"]) if current else 0
        if version != body.expected_version:
            raise _http(409, "version_conflict", "The retention policy changed concurrently")
        conn.execute(
            """INSERT INTO runtime_retention_policy VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id) DO UPDATE SET inbox_days=excluded.inbox_days,
               outbox_days=excluded.outbox_days, audit_days=excluded.audit_days,
               version=excluded.version, updated_at=excluded.updated_at""",
            ("__global__", body.inbox_days, body.outbox_days, body.audit_days, version + 1, now),
        )
    composition = _composition(request)
    from open_agent.durable_runtime.retention import RetentionPolicy

    policy = RetentionPolicy(
        inbox_payload_ttl=timedelta(days=body.inbox_days),
        outbox_delivery_ttl=timedelta(days=body.outbox_days),
        audit_ttl=timedelta(days=body.audit_days),
    )
    worker = getattr(composition, "retention_worker", None)
    if worker is None:
        raise _http(503, "retention_unavailable", "Retention worker is unavailable")
    worker.set_policy(policy)
    composition.retention_policy = policy
    composition.supervisor.wake("retention")
    return _ok({"inbox_days": body.inbox_days, "outbox_days": body.outbox_days, "audit_days": body.audit_days, "version": version + 1})


@router.post("/retention/run", status_code=202)
async def run_retention(request: Request, principal: RecentPrincipal):
    _require_system_operator(principal)
    request_id = f"retention:{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).isoformat()
    conn = _composition(request).repository.control_plane._get_conn()
    with conn:
        conn.execute(
            """INSERT INTO runtime_retention_requests (
                 request_id, tenant_id, owner_actor_id, state, created_at
               ) VALUES (?, ?, ?, 'pending', ?)""",
            (request_id, "__global__", principal.actor_id, now),
        )
    _composition(request).supervisor.wake("retention")
    return _ok({"request_id": request_id, "queued": True})


@router.get("/retention/dead-letters")
async def retention_dead_letters(
    request: Request,
    principal: Annotated[OperationalPrincipal, Depends(require_role("operator", "auditor"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    repo = _composition(request).repository
    ids = repo.list_operational_ids(
        entity_kind="retention_dead_letter", tenant_id=principal.tenant_id,
        owner_actor_id=None, limit=limit,
    )
    rows = repo.get_retention_attachment_dead_letters(ids)
    return _ok([_redact(row) for row in rows])


@router.post("/retention/dead-letters/{dead_letter_id}/requeue", status_code=202)
async def requeue_retention_dead_letter(
    dead_letter_id: str, request: Request, principal: RecentPrincipal,
):
    if "operator" not in principal.roles:
        raise _http(403, "role_required", "Operator role is required")
    repo = _composition(request).repository
    if not repo.operational_owner_matches(
        "retention_dead_letter", dead_letter_id, principal.tenant_id, None
    ):
        raise _http(404, "not_found", "Resource not found")
    changed = repo.requeue_retention_attachment(
        dead_letter_id, actor_id=principal.actor_id, now=datetime.now(timezone.utc)
    )
    if not changed:
        raise _http(404, "not_found", "Resource not found")
    _composition(request).supervisor.wake("retention")
    return _ok({"dead_letter_id": dead_letter_id, "queued": True})


def _goal_principal(request, principal):
    composition = _composition(request)
    capability = getattr(composition, "goal_capability", None)
    if capability is None:
        raise _http(503, "goal_authority_unavailable", "Goal authority is unavailable")
    return composition.repository.mint_goal_principal(
        actor_id=principal.actor_id, tenant_id=principal.tenant_id, capability=capability
    )


def _require_operator(principal: OperationalPrincipal) -> None:
    if "operator" not in principal.roles:
        raise _http(403, "role_required", "Operator role is required")


def _require_system_operator(principal: OperationalPrincipal) -> None:
    if "system_operator" not in principal.roles:
        raise _http(403, "role_required", "System operator role is required")


def _insert_owner(conn, kind, entity_id, principal, now):
    conn.execute(
        """INSERT INTO runtime_operational_ownership (
             entity_kind, entity_id, tenant_id, owner_actor_id, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (kind, entity_id, principal.tenant_id, principal.actor_id, now.isoformat(), now.isoformat()),
    )


def _scheduler_job_view(row):
    if row is None:
        return None
    value = dict(row)
    return {key: value.get(key) for key in (
        "job_id", "schedule", "status", "next_run_at", "last_run_at", "timezone",
        "max_retries", "destination", "runtime_version", "created_at", "updated_at",
    )}


def _scheduler_run_view(row: SchedulerRun):
    return {
        "run_id": row.run_id, "job_id": row.job_id, "scheduled_at": row.scheduled_at,
        "state": row.state, "attempt": row.attempt, "next_attempt_at": row.next_attempt_at,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _goal_view(row):
    if row is None:
        return None
    return _redact({key: row.get(key) for key in (
        "goal_id", "session_id", "goal_text", "status", "plan", "active_step",
        "attempt_count", "acceptance_criteria", "max_iterations", "max_tokens",
        "max_estimated_cost", "max_wall_clock_seconds", "consumed_iterations",
        "consumed_tokens", "consumed_estimated_cost", "consumed_active_seconds",
        "last_guidance_sequence", "transient_failure_count", "runtime_version",
        "created_at", "updated_at",
    )})


def _iteration_view(row):
    return _redact({
        "iteration_id": row.iteration_id, "goal_id": row.goal_id, "sequence": row.sequence,
        "state": row.state, "attempt": row.attempt, "judge_result": row.judge_result,
        "budget_delta": row.budget_delta, "created_at": row.created_at, "updated_at": row.updated_at,
    })


def _retention_row(repo, tenant_id):
    conn = repo.control_plane._get_conn()
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_retention_policy'").fetchone()
    if not exists:
        return None
    row = conn.execute(
        "SELECT inbox_days, outbox_days, audit_days, version FROM runtime_retention_policy WHERE tenant_id=?",
        (tenant_id,),
    ).fetchone()
    return dict(row) if row else None


def _http(status, code, message):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


__all__ = ["router"]
