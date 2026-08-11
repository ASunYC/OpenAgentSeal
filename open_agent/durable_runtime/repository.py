"""Atomic SQLite repository for the durable autonomous runtime."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, TYPE_CHECKING

from .models import (
    ClaimToken,
    GoalIteration,
    InboxEvent,
    OutboxObligation,
    SchedulerRun,
    to_json_value,
)

if TYPE_CHECKING:
    from open_agent.control_plane import ControlPlane


class StaleClaimError(RuntimeError):
    """The supplied lease no longer owns a state transition."""


class StateConflictError(RuntimeError):
    """The requested transition is illegal from persisted state."""


_CLAIM_TARGETS = {
    "inbox": ("inbox_events", "event_id", "claimed"),
    "outbox": ("outbox_obligations", "obligation_id", "claimed"),
    "scheduler_run": ("scheduler_runs", "run_id", "running"),
    "goal_iteration": ("goal_iterations", "iteration_id", "running"),
}


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000")


def _iso(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(to_json_value(value), ensure_ascii=False, separators=(",", ":"))


def _claim_from_row(row: sqlite3.Row) -> ClaimToken | None:
    if row["claim_owner"] is None or row["claim_expires_at"] is None:
        return None
    return ClaimToken(row["claim_owner"], row["claim_generation"], datetime.fromisoformat(row["claim_expires_at"]))


class DurableRuntimeRepository:
    """The sole transactional state boundary for durable-runtime workers."""

    def __init__(self, control_plane: ControlPlane):
        self.control_plane = control_plane

    @property
    def _conn(self) -> sqlite3.Connection:
        return self.control_plane._get_conn()

    def enqueue_inbox(self, event: InboxEvent) -> InboxEvent:
        if event.state != "pending" or event.claim is not None:
            raise ValueError("new inbox events must be pending and unclaimed")
        conn = self._conn
        with conn:
            conn.execute(
                """
                INSERT INTO inbox_events (
                    event_id, event_key, account_id, conversation_id, payload, state,
                    attempt, next_attempt_at, last_error, claim_owner,
                    claim_generation, claim_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, event_key) DO NOTHING
                """,
                (
                    event.event_id,
                    event.event_key,
                    event.account_id,
                    event.conversation_id,
                    _json(event.payload),
                    event.state,
                    event.attempt,
                    None,
                    event.last_error,
                    event.claim.owner_id if event.claim else None,
                    event.claim.generation if event.claim else 0,
                    _iso(event.claim.expires_at) if event.claim else None,
                    _iso(event.created_at),
                    _iso(event.updated_at),
                ),
            )
            row = conn.execute(
                "SELECT * FROM inbox_events WHERE account_id = ? AND event_key = ?",
                (event.account_id, event.event_key),
            ).fetchone()
        return self._inbox(row)

    def get_inbox(self, event_id: str) -> InboxEvent | None:
        row = self._conn.execute(
            "SELECT * FROM inbox_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return self._inbox(row) if row else None

    def list_inbox(self, state: str | None = None, limit: int = 100) -> list[InboxEvent]:
        _require_limit(limit)
        query = "SELECT * FROM inbox_events"
        params: list[Any] = []
        if state is not None:
            query += " WHERE state = ?"
            params.append(state)
        query += " ORDER BY created_at, event_id LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._inbox(row) for row in rows]

    def claim_inbox(
        self,
        event_id: str,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> InboxEvent | None:
        self._validate_lease_window(now, expires_at)
        _require_identifier(owner_id, "owner_id")
        conn = self._conn
        with conn:
            row = conn.execute(
                """
                UPDATE inbox_events
                SET state = 'claimed', claim_owner = ?,
                    claim_generation = claim_generation + 1, claim_expires_at = ?,
                    attempt = attempt + 1, updated_at = ?
                WHERE event_id = ?
                  AND (
                        state IN ('pending', 'retry_wait')
                        OR (state = 'claimed' AND claim_expires_at <= ?)
                  )
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                RETURNING *
                """,
                (owner_id, _iso(expires_at), _iso(now), event_id, _iso(now), _iso(now)),
            ).fetchone()
        return self._inbox(row) if row else None

    def dispatch_inbox_with_turn(
        self,
        event_id: str,
        token: ClaimToken,
        *,
        thread_id: str,
        session_id: str,
        user_input: str,
        turn_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        now: datetime,
    ) -> dict[str, Any]:
        now_value = _iso(now)
        turn_id = turn_id or f"turn_{uuid.uuid4().hex[:8]}"
        conn = self._conn
        with conn:
            event_row = conn.execute(
                """
                UPDATE inbox_events
                SET state = 'dispatched', claim_owner = NULL, claim_expires_at = NULL,
                    updated_at = ?
                WHERE event_id = ? AND state = 'claimed'
                  AND claim_owner = ? AND claim_generation = ?
                  AND claim_expires_at = ? AND claim_expires_at > ?
                RETURNING *
                """,
                (
                    now_value,
                    event_id,
                    token.owner_id,
                    token.generation,
                    _iso(token.expires_at),
                    now_value,
                ),
            ).fetchone()
            if event_row is None:
                raise StaleClaimError(f"stale inbox claim: {event_id}")
            source_event_key = _json([event_row["account_id"], event_row["event_key"]])
            turn_metadata = dict(to_json_value(metadata or {}))
            turn_metadata.update(
                {"source_inbox_event_id": event_id, "source_event_key": source_event_key}
            )
            inserted = conn.execute(
                """
                INSERT INTO runtime_turns (
                    turn_id, thread_id, session_id, user_input, status, started_at,
                    metadata, source_event_key
                )
                SELECT ?, thread_id, session_id, ?, 'running', ?, ?, ?
                FROM runtime_threads
                WHERE thread_id = ? AND session_id = ?
                """,
                (
                    turn_id,
                    user_input,
                    now_value,
                    _json(turn_metadata),
                    source_event_key,
                    thread_id,
                    session_id,
                ),
            )
            if inserted.rowcount != 1:
                raise StateConflictError(
                    f"thread {thread_id} does not belong to session {session_id}"
                )
            conn.execute(
                "UPDATE runtime_threads SET status = 'active', updated_at = ? WHERE thread_id = ?",
                (now_value, thread_id),
            )
            turn_row = conn.execute(
                "SELECT * FROM runtime_turns WHERE turn_id = ?", (turn_id,)
            ).fetchone()
        return self.control_plane._row_to_dict(turn_row)

    def enqueue_outbox(self, obligation: OutboxObligation) -> OutboxObligation:
        if obligation.state != "pending" or obligation.claim is not None:
            raise ValueError("new outbox obligations must be pending and unclaimed")
        conn = self._conn
        with conn:
            conn.execute(
                """
                INSERT INTO outbox_obligations (
                    obligation_id, idempotency_key, destination, payload, state,
                    attempt, next_attempt_at, last_error, acknowledgement,
                    claim_owner, claim_generation, claim_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(destination, idempotency_key) DO NOTHING
                """,
                (
                    obligation.obligation_id,
                    obligation.idempotency_key,
                    obligation.destination,
                    _json(obligation.payload),
                    obligation.state,
                    obligation.attempt,
                    _iso(obligation.next_attempt_at) if obligation.next_attempt_at else None,
                    obligation.last_error,
                    _json(obligation.acknowledgement) if obligation.acknowledgement else None,
                    obligation.claim.owner_id if obligation.claim else None,
                    obligation.claim.generation if obligation.claim else 0,
                    _iso(obligation.claim.expires_at) if obligation.claim else None,
                    _iso(obligation.created_at),
                    _iso(obligation.updated_at),
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM outbox_obligations
                WHERE destination = ? AND idempotency_key = ?
                """,
                (obligation.destination, obligation.idempotency_key),
            ).fetchone()
        return self._outbox(row)

    def get_outbox(self, obligation_id: str) -> OutboxObligation | None:
        row = self._conn.execute(
            "SELECT * FROM outbox_obligations WHERE obligation_id = ?", (obligation_id,)
        ).fetchone()
        return self._outbox(row) if row else None

    def list_outbox(self, state: str | None = None, limit: int = 100) -> list[OutboxObligation]:
        _require_limit(limit)
        query = "SELECT * FROM outbox_obligations"
        params: list[Any] = []
        if state is not None:
            query += " WHERE state = ?"
            params.append(state)
        query += " ORDER BY created_at, obligation_id LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._outbox(row) for row in rows]

    def claim_due_outbox(
        self,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
        *,
        limit: int = 1,
    ) -> list[OutboxObligation]:
        self._validate_lease_window(now, expires_at)
        _require_identifier(owner_id, "owner_id")
        _require_limit(limit)
        claimed: list[OutboxObligation] = []
        conn = self._conn
        with conn:
            for _ in range(limit):
                row = conn.execute(
                    """
                    UPDATE outbox_obligations
                    SET state = 'claimed', claim_owner = ?,
                        claim_generation = claim_generation + 1, claim_expires_at = ?,
                        attempt = attempt + 1, updated_at = ?
                    WHERE obligation_id = (
                        SELECT obligation_id FROM outbox_obligations
                        WHERE (
                            state IN ('pending', 'retry_wait')
                            OR (state = 'claimed' AND claim_expires_at <= ?)
                        )
                        AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                        ORDER BY COALESCE(next_attempt_at, created_at), created_at, obligation_id
                        LIMIT 1
                    )
                    RETURNING *
                    """,
                    (owner_id, _iso(expires_at), _iso(now), _iso(now), _iso(now)),
                ).fetchone()
                if row is None:
                    break
                claimed.append(self._outbox(row))
        return claimed

    def renew_claim(
        self,
        kind: str,
        record_id: str,
        token: ClaimToken,
        now: datetime,
        expires_at: datetime,
    ) -> ClaimToken:
        self._validate_lease_window(now, expires_at)
        try:
            table, id_column, active_state = _CLAIM_TARGETS[kind]
        except KeyError as exc:
            raise ValueError(f"unsupported claim kind: {kind}") from exc
        conn = self._conn
        with conn:
            row = conn.execute(
                f"""
                UPDATE {table}
                SET claim_expires_at = ?, updated_at = ?
                WHERE {id_column} = ? AND state = ?
                  AND claim_owner = ? AND claim_generation = ?
                  AND claim_expires_at = ? AND claim_expires_at > ?
                RETURNING claim_owner, claim_generation, claim_expires_at
                """,
                (
                    _iso(expires_at),
                    _iso(now),
                    record_id,
                    active_state,
                    token.owner_id,
                    token.generation,
                    _iso(token.expires_at),
                    _iso(now),
                ),
            ).fetchone()
        if row is None:
            raise StaleClaimError(f"stale {kind} claim: {record_id}")
        return ClaimToken(row["claim_owner"], row["claim_generation"], datetime.fromisoformat(row["claim_expires_at"]))

    def ack_outbox(
        self,
        obligation_id: str,
        token: ClaimToken,
        acknowledgement: Mapping[str, Any],
        now: datetime,
    ) -> OutboxObligation:
        return self._finish_outbox(
            obligation_id,
            token,
            now,
            state="acknowledged",
            acknowledgement=_json(acknowledgement),
        )

    def retry_outbox(
        self,
        obligation_id: str,
        token: ClaimToken,
        error: str,
        next_attempt_at: datetime,
        now: datetime,
        *,
        dead_letter: bool = False,
    ) -> OutboxObligation:
        _require_aware(next_attempt_at, "next_attempt_at")
        return self._finish_outbox(
            obligation_id,
            token,
            now,
            state="dead_letter" if dead_letter else "retry_wait",
            error=error,
            next_attempt_at=_iso(next_attempt_at),
        )

    def mark_delivery_unknown(
        self,
        obligation_id: str,
        token: ClaimToken,
        error: str,
        now: datetime,
    ) -> OutboxObligation:
        return self._finish_outbox(
            obligation_id, token, now, state="delivery_unknown", error=error
        )

    def create_due_scheduler_run(
        self,
        job_id: str,
        scheduled_at: datetime,
        next_run_at: datetime,
        *,
        run_id: str | None = None,
        now: datetime,
    ) -> SchedulerRun | None:
        scheduled_value = _iso(scheduled_at)
        next_value = _iso(next_run_at)
        now_value = _iso(now)
        run_id = run_id or f"{job_id}:{scheduled_value}"
        conn = self._conn
        with conn:
            advanced = conn.execute(
                """
                UPDATE scheduler_jobs
                SET next_run_at = ?, last_run_at = ?, updated_at = ?,
                    runtime_version = runtime_version + 1
                WHERE job_id = ? AND status = 'active'
                  AND julianday(next_run_at) = julianday(?)
                  AND julianday(next_run_at) <= julianday(?)
                RETURNING job_id
                """,
                (next_value, scheduled_value, now_value, job_id, scheduled_value, now_value),
            ).fetchone()
            if advanced is None:
                existing = conn.execute(
                    "SELECT * FROM scheduler_runs WHERE job_id = ? AND scheduled_at = ?",
                    (job_id, scheduled_value),
                ).fetchone()
                return self._scheduler_run(existing) if existing else None
            conn.execute(
                """
                INSERT INTO scheduler_runs (
                    run_id, job_id, scheduled_at, state, attempt,
                    claim_generation, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', 0, 0, ?, ?)
                """,
                (run_id, job_id, scheduled_value, now_value, now_value),
            )
            row = conn.execute(
                "SELECT * FROM scheduler_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._scheduler_run(row)

    def get_scheduler_run(self, run_id: str) -> SchedulerRun | None:
        row = self._conn.execute(
            "SELECT * FROM scheduler_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return self._scheduler_run(row) if row else None

    def list_scheduler_runs(self, job_id: str | None = None, limit: int = 100) -> list[SchedulerRun]:
        _require_limit(limit)
        query = "SELECT * FROM scheduler_runs"
        params: list[Any] = []
        if job_id is not None:
            query += " WHERE job_id = ?"
            params.append(job_id)
        query += " ORDER BY scheduled_at, run_id LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._scheduler_run(row) for row in rows]

    def create_goal_iteration(self, iteration: GoalIteration) -> GoalIteration:
        if iteration.state != "pending" or iteration.claim is not None:
            raise ValueError("new goal iterations must be pending and unclaimed")
        conn = self._conn
        with conn:
            conn.execute(
                """
                INSERT INTO goal_iterations (
                    iteration_id, goal_id, sequence, state, claim_owner,
                    claim_generation, claim_expires_at, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(goal_id, sequence) DO NOTHING
                """,
                (
                    iteration.iteration_id,
                    iteration.goal_id,
                    iteration.sequence,
                    iteration.state,
                    iteration.claim.owner_id if iteration.claim else None,
                    iteration.claim.generation if iteration.claim else 0,
                    _iso(iteration.claim.expires_at) if iteration.claim else None,
                    iteration.last_error,
                    _iso(iteration.created_at),
                    _iso(iteration.updated_at),
                ),
            )
            row = conn.execute(
                "SELECT * FROM goal_iterations WHERE goal_id = ? AND sequence = ?",
                (iteration.goal_id, iteration.sequence),
            ).fetchone()
        return self._goal_iteration(row)

    def claim_goal_iteration(
        self,
        iteration_id: str,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> GoalIteration | None:
        self._validate_lease_window(now, expires_at)
        _require_identifier(owner_id, "owner_id")
        conn = self._conn
        with conn:
            row = conn.execute(
                """
                UPDATE goal_iterations
                SET state = 'running', claim_owner = ?,
                    claim_generation = claim_generation + 1, claim_expires_at = ?, updated_at = ?
                WHERE iteration_id = ?
                  AND (state = 'pending' OR (state = 'running' AND claim_expires_at <= ?))
                  AND EXISTS (SELECT 1 FROM goals WHERE goals.goal_id = goal_iterations.goal_id
                              AND goals.status IN ('running', 'runnable'))
                RETURNING *
                """,
                (owner_id, _iso(expires_at), _iso(now), iteration_id, _iso(now)),
            ).fetchone()
        return self._goal_iteration(row) if row else None

    def get_goal_iteration(self, iteration_id: str) -> GoalIteration | None:
        row = self._conn.execute(
            "SELECT * FROM goal_iterations WHERE iteration_id = ?", (iteration_id,)
        ).fetchone()
        return self._goal_iteration(row) if row else None

    def list_goal_iterations(self, goal_id: str | None = None, limit: int = 100) -> list[GoalIteration]:
        _require_limit(limit)
        query = "SELECT * FROM goal_iterations"
        params: list[Any] = []
        if goal_id is not None:
            query += " WHERE goal_id = ?"
            params.append(goal_id)
        query += " ORDER BY goal_id, sequence LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._goal_iteration(row) for row in rows]

    def complete_goal_iteration_and_continue(
        self,
        iteration_id: str,
        token: ClaimToken,
        *,
        judge_result: Mapping[str, Any],
        budget_delta: Mapping[str, int | float],
        continue_running: bool,
        next_iteration_id: str | None = None,
        goal_status: str | None = None,
        now: datetime,
    ) -> tuple[GoalIteration, GoalIteration | None]:
        if not isinstance(continue_running, bool):
            raise ValueError("continue_running must be a boolean")
        status = goal_status or ("running" if continue_running else "completed")
        allowed_statuses = {"running", "runnable", "completed", "paused", "blocked", "failed", "cancelled"}
        if status not in allowed_statuses or continue_running != (status in {"running", "runnable"}):
            raise ValueError("goal_status must agree with continue_running")
        increments = self._budget_increments(budget_delta)
        now_value = _iso(now)
        conn = self._conn
        with conn:
            completed_row = conn.execute(
                """
                UPDATE goal_iterations
                SET state = 'completed', judge_result = ?, budget_delta = ?,
                    claim_owner = NULL, claim_expires_at = NULL, updated_at = ?
                WHERE iteration_id = ? AND state IN ('running', 'judging')
                  AND claim_owner = ? AND claim_generation = ?
                  AND claim_expires_at = ? AND claim_expires_at > ?
                RETURNING *
                """,
                (
                    _json(judge_result),
                    _json(budget_delta),
                    now_value,
                    iteration_id,
                    token.owner_id,
                    token.generation,
                    _iso(token.expires_at),
                    now_value,
                ),
            ).fetchone()
            if completed_row is None:
                raise StaleClaimError(f"stale goal iteration claim: {iteration_id}")

            goal = conn.execute(
                "SELECT runtime_version FROM goals WHERE goal_id = ?",
                (completed_row["goal_id"],),
            ).fetchone()
            if goal is None:
                raise StateConflictError(f"missing goal: {completed_row['goal_id']}")
            next_action = str(judge_result.get("next_action", "")) if continue_running else ""
            updated = conn.execute(
                """
                UPDATE goals
                SET status = ?, active_step = ?, attempt_count = attempt_count + 1,
                    last_judge_result = ?, consumed_iterations = consumed_iterations + 1,
                    consumed_tokens = consumed_tokens + ?,
                    consumed_estimated_cost = consumed_estimated_cost + ?,
                    consumed_active_seconds = consumed_active_seconds + ?,
                    runtime_version = runtime_version + 1, updated_at = ?
                WHERE goal_id = ? AND runtime_version = ?
                  AND status IN ('running', 'runnable')
                """,
                (
                    status,
                    next_action,
                    _json(judge_result),
                    increments["tokens"],
                    increments["estimated_cost"],
                    increments["active_seconds"],
                    now_value,
                    completed_row["goal_id"],
                    goal["runtime_version"],
                ),
            )
            if updated.rowcount != 1:
                raise StateConflictError(f"concurrent goal update: {completed_row['goal_id']}")

            continuation_row = None
            if continue_running:
                next_sequence = completed_row["sequence"] + 1
                continuation_id = next_iteration_id or f"{completed_row['goal_id']}:iteration:{next_sequence}"
                conn.execute(
                    """
                    INSERT INTO goal_iterations (
                        iteration_id, goal_id, sequence, state, claim_generation,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', 0, ?, ?)
                    """,
                    (
                        continuation_id,
                        completed_row["goal_id"],
                        next_sequence,
                        now_value,
                        now_value,
                    ),
                )
                continuation_row = conn.execute(
                    "SELECT * FROM goal_iterations WHERE iteration_id = ?",
                    (continuation_id,),
                ).fetchone()
        continuation = self._goal_iteration(continuation_row) if continuation_row else None
        return self._goal_iteration(completed_row), continuation

    def _finish_outbox(
        self,
        obligation_id: str,
        token: ClaimToken,
        now: datetime,
        *,
        state: str,
        error: str | None = None,
        next_attempt_at: str | None = None,
        acknowledgement: str | None = None,
    ) -> OutboxObligation:
        now_value = _iso(now)
        conn = self._conn
        with conn:
            row = conn.execute(
                """
                UPDATE outbox_obligations
                SET state = ?, last_error = ?, next_attempt_at = ?, acknowledgement = ?,
                    claim_owner = NULL, claim_expires_at = NULL, updated_at = ?
                WHERE obligation_id = ? AND state = 'claimed'
                  AND claim_owner = ? AND claim_generation = ?
                  AND claim_expires_at = ? AND claim_expires_at > ?
                RETURNING *
                """,
                (
                    state,
                    error,
                    next_attempt_at,
                    acknowledgement,
                    now_value,
                    obligation_id,
                    token.owner_id,
                    token.generation,
                    _iso(token.expires_at),
                    now_value,
                ),
            ).fetchone()
        if row is None:
            raise StaleClaimError(f"stale outbox claim: {obligation_id}")
        return self._outbox(row)

    @staticmethod
    def _validate_lease_window(now: datetime, expires_at: datetime) -> None:
        _require_aware(now, "now")
        _require_aware(expires_at, "expires_at")
        if expires_at <= now:
            raise ValueError("expires_at must be after now")

    @staticmethod
    def _budget_increments(delta: Mapping[str, int | float]) -> dict[str, int | float]:
        allowed = {"tokens", "estimated_cost", "active_seconds"}
        unknown = set(delta) - allowed
        if unknown:
            raise ValueError(f"unsupported budget delta: {sorted(unknown)}")
        values: dict[str, int | float] = {
            name: delta.get(name, 0) for name in ("tokens", "estimated_cost", "active_seconds")
        }
        for name, value in values.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative number")
        if not isinstance(values["tokens"], int):
            raise ValueError("tokens must be an integer")
        return values

    @staticmethod
    def _inbox(row: sqlite3.Row) -> InboxEvent:
        return InboxEvent(
            event_id=row["event_id"],
            event_key=row["event_key"],
            account_id=row["account_id"],
            conversation_id=row["conversation_id"],
            payload=json.loads(row["payload"]),
            state=row["state"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            claim=_claim_from_row(row),
            attempt=row["attempt"],
            last_error=row["last_error"],
        )

    @staticmethod
    def _outbox(row: sqlite3.Row) -> OutboxObligation:
        return OutboxObligation(
            obligation_id=row["obligation_id"],
            idempotency_key=row["idempotency_key"],
            destination=row["destination"],
            payload=json.loads(row["payload"]),
            state=row["state"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            next_attempt_at=(datetime.fromisoformat(row["next_attempt_at"]) if row["next_attempt_at"] else None),
            claim=_claim_from_row(row),
            attempt=row["attempt"],
            last_error=row["last_error"],
            acknowledgement=(
                json.loads(row["acknowledgement"]) if row["acknowledgement"] else None
            ),
        )

    @staticmethod
    def _scheduler_run(row: sqlite3.Row) -> SchedulerRun:
        return SchedulerRun(
            run_id=row["run_id"],
            job_id=row["job_id"],
            scheduled_at=datetime.fromisoformat(row["scheduled_at"]),
            state=row["state"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            claim=_claim_from_row(row),
            attempt=row["attempt"],
            next_attempt_at=(datetime.fromisoformat(row["next_attempt_at"]) if row["next_attempt_at"] else None),
            last_error=row["last_error"],
        )

    @staticmethod
    def _goal_iteration(row: sqlite3.Row) -> GoalIteration:
        return GoalIteration(
            iteration_id=row["iteration_id"],
            goal_id=row["goal_id"],
            sequence=row["sequence"],
            state=row["state"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            claim=_claim_from_row(row),
            last_error=row["last_error"],
        )
