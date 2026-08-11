"""Atomic SQLite repository for the durable autonomous runtime."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Callable, Iterable, Mapping, TYPE_CHECKING

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

    def upsert_channel_account(
        self,
        *,
        account_id: str,
        adapter_kind: str,
        default_profile_id: str | None,
        now: datetime,
        enabled: bool = True,
        credential_ref: str | None = None,
        capabilities: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        for value, name in ((account_id, "account_id"), (adapter_kind, "adapter_kind")):
            _require_identifier(value, name)
        if default_profile_id is not None:
            _require_identifier(default_profile_id, "default_profile_id")
        now_value = _iso(now)
        with self._conn:
            row = self._conn.execute(
                """
                INSERT INTO channel_accounts (
                    account_id, adapter_kind, enabled, credential_ref, default_profile_id,
                    capabilities, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    adapter_kind=excluded.adapter_kind, enabled=excluded.enabled,
                    credential_ref=excluded.credential_ref,
                    default_profile_id=excluded.default_profile_id,
                    capabilities=excluded.capabilities, updated_at=excluded.updated_at,
                    metadata=excluded.metadata
                RETURNING *
                """,
                (
                    account_id,
                    adapter_kind,
                    int(enabled),
                    credential_ref,
                    default_profile_id,
                    _json(capabilities or {}),
                    now_value,
                    now_value,
                    _json(metadata or {}),
                ),
            ).fetchone()
        if row is None:
            raise StateConflictError("channel account upsert returned no row")
        return self._channel_account(row)

    def get_channel_account(self, account_id: str) -> dict[str, Any] | None:
        _require_identifier(account_id, "account_id")
        row = self._conn.execute(
            "SELECT * FROM channel_accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            return None
        return self._channel_account(row)

    def upsert_channel_route(
        self,
        *,
        account_id: str,
        conversation_id: str,
        now: datetime,
        sender_id: str = "",
        profile_id: str | None = None,
        trigger_policy: str = "default",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        for value, name in ((account_id, "account_id"), (conversation_id, "conversation_id")):
            _require_identifier(value, name)
        if not isinstance(sender_id, str):
            raise ValueError("sender_id must be a string")
        if profile_id is not None:
            _require_identifier(profile_id, "profile_id")
        if trigger_policy not in {"default", "always", "never", "mention", "reply"}:
            raise ValueError("unsupported trigger_policy")
        route_id = self._gateway_id("route", account_id, conversation_id, sender_id)
        now_value = _iso(now)
        with self._conn:
            row = self._conn.execute(
                """
                INSERT INTO channel_routes (
                    route_id, account_id, conversation_id, sender_id, profile_id,
                    trigger_policy, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, conversation_id, sender_id) DO UPDATE SET
                    profile_id=excluded.profile_id, trigger_policy=excluded.trigger_policy,
                    updated_at=excluded.updated_at, metadata=excluded.metadata
                RETURNING *
                """,
                (
                    route_id,
                    account_id,
                    conversation_id,
                    sender_id,
                    profile_id,
                    trigger_policy,
                    now_value,
                    now_value,
                    _json(metadata or {}),
                ),
            ).fetchone()
        if row is None:
            raise StateConflictError("channel route upsert returned no row")
        return self._channel_route(row, should_dispatch=False)

    def resolve_channel_route(
        self,
        *,
        account_id: str,
        conversation_id: str,
        sender_id: str,
        now: datetime,
        exact: bool = False,
        expected_adapter_kind: str | None = None,
        should_dispatch: Callable[[str], bool] | None = None,
        require_profile: bool = False,
    ) -> dict[str, Any]:
        for value, name in (
            (account_id, "account_id"),
            (conversation_id, "conversation_id"),
        ):
            _require_identifier(value, name)
        if not isinstance(sender_id, str):
            raise ValueError("sender_id must be a string")
        now_value = _iso(now)
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            account_row = conn.execute(
                "SELECT * FROM channel_accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if account_row is None:
                raise StateConflictError("channel account not found")
            if expected_adapter_kind is not None:
                _require_identifier(expected_adapter_kind, "expected_adapter_kind")
                if not bool(account_row["enabled"]):
                    raise StateConflictError("channel account is disabled")
                if account_row["adapter_kind"] != expected_adapter_kind:
                    raise StateConflictError("event adapter does not match channel account")
            row = conn.execute(
                """
                SELECT * FROM channel_routes
                WHERE account_id = ? AND conversation_id = ?
                  AND sender_id IN (?, '')
                ORDER BY CASE WHEN sender_id = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (account_id, conversation_id, sender_id, sender_id),
            ).fetchone()
            if exact and (row is None or row["sender_id"] != sender_id):
                row = None
            trigger_policy = row["trigger_policy"] if row is not None else "default"
            dispatch = True if should_dispatch is None else should_dispatch(trigger_policy)
            if not isinstance(dispatch, bool):
                raise StateConflictError("route trigger decision must be boolean")
            profile_id = (
                row["profile_id"] if row is not None and row["profile_id"] else account_row["default_profile_id"]
            )
            if require_profile and not profile_id:
                raise StateConflictError("channel account has no resolvable profile")
            if not dispatch:
                route_id = (
                    row["route_id"]
                    if row is not None
                    else self._gateway_id("route", account_id, conversation_id, sender_id if exact else "")
                )
                return {
                    "route_id": route_id,
                    "account_id": account_id,
                    "conversation_id": conversation_id,
                    "sender_id": row["sender_id"] if row is not None else (sender_id if exact else ""),
                    "profile_id": profile_id,
                    "trigger_policy": trigger_policy,
                    "session_id": None,
                    "thread_id": None,
                    "metadata": {},
                    "should_dispatch": False,
                }
            if row is None:
                route_id = self._gateway_id("route", account_id, conversation_id, sender_id if exact else "")
                route_sender = sender_id if exact else ""
                conn.execute(
                    """
                    INSERT INTO channel_routes (
                        route_id, account_id, conversation_id, sender_id,
                        trigger_policy, created_at, updated_at, metadata
                    ) VALUES (?, ?, ?, ?, 'default', ?, ?, '{}')
                    ON CONFLICT(account_id, conversation_id, sender_id) DO NOTHING
                    """,
                    (route_id, account_id, conversation_id, route_sender, now_value, now_value),
                )
                row = conn.execute(
                    """SELECT * FROM channel_routes
                       WHERE account_id = ? AND conversation_id = ? AND sender_id = ?""",
                    (account_id, conversation_id, route_sender),
                ).fetchone()
            route_id = row["route_id"]
            session_was_bound = row["session_id"] is not None
            thread_was_bound = row["thread_id"] is not None
            session_id = row["session_id"] or self._gateway_id("session", route_id)
            thread_id = row["thread_id"] or self._gateway_id("thread", route_id)
            principal = (
                row["sender_id"]
                if row["sender_id"]
                else self._gateway_id("principal", account_id, conversation_id)
            )
            if not row["sender_id"] and session_was_bound and thread_was_bound:
                legacy_principal = f"gateway:{account_id}:{conversation_id}"
                legacy_session_row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                legacy_thread_row = conn.execute(
                    "SELECT * FROM runtime_threads WHERE thread_id = ?", (thread_id,)
                ).fetchone()
                if legacy_session_row is not None and legacy_thread_row is not None:
                    legacy_session = self.control_plane._row_to_dict(legacy_session_row)
                    legacy_thread = self.control_plane._row_to_dict(legacy_thread_row)
                    if (
                        legacy_session["channel"] == "gateway"
                        and legacy_session["user_id"] == legacy_principal
                        and legacy_session["metadata"].get("route_id") == route_id
                        and legacy_thread["session_id"] == session_id
                        and legacy_thread["user_id"] == legacy_principal
                        and legacy_thread["metadata"].get("route_id") == route_id
                    ):
                        conn.execute(
                            "UPDATE sessions SET user_id = ?, updated_at = ? WHERE session_id = ?",
                            (principal, now_value, session_id),
                        )
                        conn.execute(
                            "UPDATE runtime_threads SET user_id = ?, updated_at = ? WHERE thread_id = ?",
                            (principal, now_value, thread_id),
                        )
            inserted_session = conn.execute(
                """
                INSERT INTO sessions (
                    session_id, channel, user_id, status, created_at, updated_at, metadata
                ) VALUES (?, 'gateway', ?, 'active', ?, ?, ?)
                ON CONFLICT(session_id) DO NOTHING
                RETURNING session_id
                """,
                (session_id, principal, now_value, now_value, _json({"route_id": route_id})),
            ).fetchone()
            if not session_was_bound and inserted_session is None:
                raise StateConflictError("gateway session id collision")
            session_row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            session = self.control_plane._row_to_dict(session_row)
            if (
                session["channel"] != "gateway"
                or session["user_id"] != principal
                or session["metadata"].get("route_id") != route_id
            ):
                raise StateConflictError("gateway session id collision")
            inserted_thread = conn.execute(
                """
                INSERT INTO runtime_threads (
                    thread_id, session_id, user_id, title, status,
                    created_at, updated_at, metadata
                ) VALUES (?, ?, ?, '', 'active', ?, ?, ?)
                ON CONFLICT(thread_id) DO NOTHING
                RETURNING thread_id
                """,
                (
                    thread_id,
                    session_id,
                    principal,
                    now_value,
                    now_value,
                    _json({"route_id": route_id}),
                ),
            ).fetchone()
            if not thread_was_bound and inserted_thread is None:
                raise StateConflictError("gateway thread id collision")
            thread_row = conn.execute(
                "SELECT * FROM runtime_threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            thread = self.control_plane._row_to_dict(thread_row)
            if (
                thread["session_id"] != session_id
                or thread["user_id"] != principal
                or thread["metadata"].get("route_id") != route_id
            ):
                raise StateConflictError("gateway thread id collision")
            conn.execute(
                """UPDATE channel_routes SET session_id = ?, thread_id = ?, updated_at = ?
                   WHERE route_id = ?""",
                (session_id, thread_id, now_value, route_id),
            )
            row = conn.execute(
                "SELECT * FROM channel_routes WHERE route_id = ?", (route_id,)
            ).fetchone()
        value = self._channel_route(row, should_dispatch=True)
        value["profile_id"] = profile_id
        return value

    def _channel_account(self, row: sqlite3.Row) -> dict[str, Any]:
        value = self.control_plane._row_to_dict(row)
        value["enabled"] = bool(value["enabled"])
        if isinstance(value["capabilities"], str):
            value["capabilities"] = json.loads(value["capabilities"])
        if isinstance(value["metadata"], str):
            value["metadata"] = json.loads(value["metadata"])
        return value

    def _channel_route(self, row: sqlite3.Row, *, should_dispatch: bool) -> dict[str, Any]:
        value = self.control_plane._row_to_dict(row)
        if isinstance(value["metadata"], str):
            value["metadata"] = json.loads(value["metadata"])
        value["should_dispatch"] = should_dispatch
        return value

    @staticmethod
    def _gateway_id(prefix: str, *parts: str) -> str:
        value = _json([prefix, *parts])
        return f"{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex}"

    @property
    def _conn(self) -> sqlite3.Connection:
        return self.control_plane._get_conn()

    def _list_rows(self, table: str, column: str, value: str | None, order: str, limit: int) -> list[sqlite3.Row]:
        _require_limit(limit)
        predicate = "" if value is None else f" WHERE {column} = ?"
        params: list[Any] = [] if value is None else [value]
        params.append(limit)
        query = f"SELECT * FROM {table}{predicate} ORDER BY {order} LIMIT ?"
        return self._conn.execute(query, params).fetchall()

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
        rows = self._list_rows("inbox_events", "state", state, "created_at, event_id", limit)
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

    def persist_agent_task_with_outbox(
        self,
        task: Mapping[str, Any],
        obligation: OutboxObligation,
        *,
        now: datetime,
    ) -> OutboxObligation:
        """Atomically persist one terminal agent task and its delivery obligation."""
        status = task.get("status")
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("agent task must be terminal before outbox production")
        if obligation.state != "pending" or obligation.claim is not None:
            raise ValueError("new outbox obligations must be pending and unclaimed")
        identifiers = {
            name: task.get(name) for name in ("task_id", "profile_id", "session_id")
        }
        for name, value in identifiers.items():
            _require_identifier(value, name)
        parent_session_id = task.get("parent_session_id")
        if parent_session_id is not None:
            _require_identifier(parent_session_id, "parent_session_id")
        now_value = _iso(now)
        metadata = to_json_value(task.get("metadata") or {})
        events = to_json_value(task.get("events") or [])
        conn = self._conn
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, channel, user_id, status, created_at, updated_at, metadata
                ) VALUES (?, 'agent-task', 'default', 'active', ?, ?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (
                    identifiers["session_id"],
                    now_value,
                    now_value,
                    _json({"profile_id": identifiers["profile_id"]}),
                ),
            )
            conn.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, profile_id, session_id, parent_session_id, status, instruction,
                    result, error, events, created_at, updated_at, completed_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    profile_id=excluded.profile_id,
                    session_id=excluded.session_id,
                    parent_session_id=excluded.parent_session_id,
                    status=excluded.status,
                    instruction=excluded.instruction,
                    result=excluded.result,
                    error=excluded.error,
                    events=excluded.events,
                    updated_at=excluded.updated_at,
                    completed_at=COALESCE(agent_tasks.completed_at, excluded.completed_at),
                    metadata=excluded.metadata
                """,
                (
                    identifiers["task_id"],
                    identifiers["profile_id"],
                    identifiers["session_id"],
                    parent_session_id,
                    status,
                    str(task.get("instruction") or ""),
                    task.get("result"),
                    task.get("error"),
                    _json(events),
                    now_value,
                    now_value,
                    now_value,
                    _json(metadata),
                ),
            )
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
                    None,
                    obligation.last_error,
                    None,
                    None,
                    0,
                    None,
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
            if (
                row["obligation_id"] != obligation.obligation_id
                or row["destination"] != obligation.destination
                or row["idempotency_key"] != obligation.idempotency_key
                or row["payload"] != _json(obligation.payload)
            ):
                raise StateConflictError(
                    "agent task delivery identity belongs to another obligation"
                )
        return self._outbox(row)

    def get_outbox(self, obligation_id: str) -> OutboxObligation | None:
        row = self._conn.execute(
            "SELECT * FROM outbox_obligations WHERE obligation_id = ?", (obligation_id,)
        ).fetchone()
        return self._outbox(row) if row else None

    def list_outbox(self, state: str | None = None, limit: int = 100) -> list[OutboxObligation]:
        rows = self._list_rows("outbox_obligations", "state", state, "created_at, obligation_id", limit)
        return [self._outbox(row) for row in rows]

    def append_audit_event(
        self,
        *,
        audit_id: str,
        entity_kind: str,
        entity_id: str,
        action: str,
        actor_id: str | None,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        for value, name in (
            (audit_id, "audit_id"),
            (entity_kind, "entity_kind"),
            (entity_id, "entity_id"),
            (action, "action"),
        ):
            _require_identifier(value, name)
        if actor_id is not None:
            _require_identifier(actor_id, "actor_id")
        payload_value = to_json_value(payload)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO runtime_audit_events (
                    audit_id, entity_kind, entity_id, action, actor_id, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    entity_kind,
                    entity_id,
                    action,
                    actor_id,
                    _json(payload_value),
                    _iso(now),
                ),
            )
        return {
            "audit_id": audit_id,
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "action": action,
            "actor_id": actor_id,
            "payload": payload_value,
            "created_at": datetime.fromisoformat(_iso(now)),
        }

    def list_audit_events(
        self,
        entity_kind: str,
        entity_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        _require_identifier(entity_kind, "entity_kind")
        _require_identifier(entity_id, "entity_id")
        _require_limit(limit)
        rows = self._conn.execute(
            """
            SELECT * FROM runtime_audit_events
            WHERE entity_kind = ? AND entity_id = ?
            ORDER BY created_at, audit_id
            LIMIT ?
            """,
            (entity_kind, entity_id, limit),
        ).fetchall()
        return [
            {
                "audit_id": row["audit_id"],
                "entity_kind": row["entity_kind"],
                "entity_id": row["entity_id"],
                "action": row["action"],
                "actor_id": row["actor_id"],
                "payload": json.loads(row["payload"]),
                "created_at": datetime.fromisoformat(row["created_at"]),
            }
            for row in rows
        ]

    def manual_resend_outbox(
        self,
        source_obligation_id: str,
        resend: OutboxObligation,
        *,
        actor_id: str,
        duplicate_risk_acknowledged: bool,
        acknowledgement_version: str,
        now: datetime,
    ) -> OutboxObligation:
        _require_identifier(source_obligation_id, "source_obligation_id")
        _require_identifier(actor_id, "actor_id")
        if duplicate_risk_acknowledged is not True:
            raise ValueError("manual resend requires explicit duplicate risk acknowledgement")
        _require_identifier(acknowledgement_version, "acknowledgement_version")
        if acknowledgement_version != "1":
            raise ValueError("unsupported duplicate risk acknowledgement version")
        if resend.state != "pending" or resend.claim is not None:
            raise ValueError("manual resend obligations must be pending and unclaimed")
        now_value = _iso(now)
        conn = self._conn
        with conn:
            source = conn.execute(
                "SELECT * FROM outbox_obligations WHERE obligation_id = ?",
                (source_obligation_id,),
            ).fetchone()
            if source is None:
                raise StateConflictError(f"missing outbox obligation: {source_obligation_id}")
            if source["state"] not in {"delivery_unknown", "dead_letter"}:
                raise StateConflictError(
                    f"outbox obligation is not eligible for manual resend: {source_obligation_id}"
                )
            expected_key = (
                f"manual-resend:{source_obligation_id}:{resend.obligation_id}"
            )
            source_payload = json.loads(source["payload"])
            resend_payload_value = to_json_value(resend.payload)
            resend_payload = _json(resend_payload_value)
            if (
                resend.destination != source["destination"]
                or resend.idempotency_key != expected_key
                or resend_payload_value != source_payload
            ):
                raise ValueError("manual resend must clone the source destination and payload")
            conn.execute(
                """
                INSERT INTO outbox_obligations (
                    obligation_id, idempotency_key, destination, payload, state,
                    attempt, next_attempt_at, last_error, acknowledgement,
                    claim_owner, claim_generation, claim_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, 0, NULL, ?, ?)
                ON CONFLICT(destination, idempotency_key) DO NOTHING
                """,
                (
                    resend.obligation_id,
                    resend.idempotency_key,
                    resend.destination,
                    resend_payload,
                    _iso(resend.created_at),
                    _iso(resend.updated_at),
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM outbox_obligations
                WHERE destination = ? AND idempotency_key = ?
                """,
                (resend.destination, resend.idempotency_key),
            ).fetchone()
            if (
                row["obligation_id"] != resend.obligation_id
                or row["destination"] != source["destination"]
                or row["idempotency_key"] != expected_key
                or json.loads(row["payload"]) != source_payload
            ):
                raise StateConflictError(
                    "manual resend identity belongs to another obligation"
                )
            audit_payload = _json(
                {
                    "acknowledgement_version": acknowledgement_version,
                    "duplicate_risk_acknowledged": True,
                    "resend_obligation_id": resend.obligation_id,
                }
            )
            conn.execute(
                """
                INSERT INTO runtime_audit_events (
                    audit_id, entity_kind, entity_id, action, actor_id, payload, created_at
                ) VALUES (?, 'outbox', ?, 'manual_resend', ?, ?, ?)
                ON CONFLICT(audit_id) DO NOTHING
                """,
                (
                    f"audit:{resend.obligation_id}",
                    source_obligation_id,
                    actor_id,
                    audit_payload,
                    now_value,
                ),
            )
            audit = conn.execute(
                "SELECT * FROM runtime_audit_events WHERE audit_id = ?",
                (f"audit:{resend.obligation_id}",),
            ).fetchone()
            if (
                audit["entity_kind"] != "outbox"
                or audit["entity_id"] != source_obligation_id
                or audit["action"] != "manual_resend"
                or audit["actor_id"] != actor_id
                or audit["payload"] != audit_payload
            ):
                raise StateConflictError("manual resend audit id belongs to another event")
        return self._outbox(row)

    def claim_due_outbox(
        self,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
        *,
        limit: int = 1,
        destinations: Iterable[str] | None = None,
    ) -> list[OutboxObligation]:
        self._validate_lease_window(now, expires_at)
        _require_identifier(owner_id, "owner_id")
        _require_limit(limit)
        destination_values = tuple(sorted(set(destinations or ())))
        if destinations is not None and not destination_values:
            return []
        for destination in destination_values:
            _require_identifier(destination, "destination")
        destination_clause = ""
        if destination_values:
            placeholders = ", ".join("?" for _ in destination_values)
            destination_clause = f"AND destination IN ({placeholders})"
        claimed: list[OutboxObligation] = []
        conn = self._conn
        with conn:
            for _ in range(limit):
                row = conn.execute(
                    f"""
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
                        {destination_clause}
                        ORDER BY COALESCE(next_attempt_at, created_at), created_at, obligation_id
                        LIMIT 1
                    )
                    RETURNING *
                    """,
                    (
                        owner_id,
                        _iso(expires_at),
                        _iso(now),
                        _iso(now),
                        _iso(now),
                        *destination_values,
                    ),
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
        scheduled_utc = scheduled_at.astimezone(timezone.utc)
        next_utc = next_run_at.astimezone(timezone.utc)
        now_utc = now.astimezone(timezone.utc)
        if next_utc <= scheduled_utc:
            raise ValueError("next_run_at must be after scheduled_at")
        run_id = run_id or f"{job_id}:{scheduled_value}"
        conn = self._conn
        with conn:
            existing = conn.execute("SELECT * FROM scheduler_runs WHERE job_id = ? AND scheduled_at = ?", (job_id, scheduled_value)).fetchone()
            if existing is not None:
                return self._scheduler_run(existing)
            job = conn.execute("SELECT status, next_run_at FROM scheduler_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if job is None or job["status"] != "active" or job["next_run_at"] is None:
                return None
            raw_cursor = job["next_run_at"]
            try:
                parseable_cursor = raw_cursor[:-1] + "+00:00" if raw_cursor.endswith("Z") else raw_cursor
                stored_cursor = datetime.fromisoformat(parseable_cursor)
                _require_aware(stored_cursor, "persisted scheduler cursor")
            except (TypeError, ValueError) as exc:
                raise StateConflictError(f"invalid scheduler cursor for job {job_id}") from exc
            stored_utc = stored_cursor.astimezone(timezone.utc)
            if stored_utc != scheduled_utc or stored_utc > now_utc:
                return None
            advanced = conn.execute(
                """
                UPDATE scheduler_jobs
                SET next_run_at = ?, last_run_at = ?, updated_at = ?,
                    runtime_version = runtime_version + 1
                WHERE job_id = ? AND status = 'active'
                  AND next_run_at = ?
                RETURNING job_id
                """,
                (next_value, scheduled_value, now_value, job_id, raw_cursor),
            ).fetchone()
            if advanced is None:
                existing = conn.execute("SELECT * FROM scheduler_runs WHERE job_id = ? AND scheduled_at = ?", (job_id, scheduled_value)).fetchone()
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
            row = conn.execute("SELECT * FROM scheduler_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._scheduler_run(row)

    def get_scheduler_run(self, run_id: str) -> SchedulerRun | None:
        row = self._conn.execute(
            "SELECT * FROM scheduler_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return self._scheduler_run(row) if row else None

    def list_scheduler_runs(self, job_id: str | None = None, limit: int = 100) -> list[SchedulerRun]:
        rows = self._list_rows("scheduler_runs", "job_id", job_id, "scheduled_at, run_id", limit)
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
        rows = self._list_rows("goal_iterations", "goal_id", goal_id, "goal_id, sequence", limit)
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
        judge_value = to_json_value(judge_result)
        budget_value = to_json_value(budget_delta)
        increments = self._budget_increments(budget_value)
        now_value = _iso(now)
        conn = self._conn
        with conn:
            done = judge_value.get("done")
            if not isinstance(done, bool):
                raise ValueError("judge_result.done must be a boolean")
            if (done and (continue_running or status != "completed")) or (
                not done and status == "completed"
            ):
                raise ValueError("judge_result.done contradicts the requested goal transition")
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
                    _json(judge_value),
                    _json(budget_value),
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
            next_action = str(judge_value.get("next_action", "")) if continue_running else ""
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
                    _json(judge_value),
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
