"""Atomic SQLite repository for the durable autonomous runtime."""

from __future__ import annotations

import json
import hashlib
import hmac
import re
import sqlite3
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


@dataclass(frozen=True, slots=True)
class RetentionAttachmentClaim:
    """Authenticated lease for one immutable attachment-retention occurrence."""

    queue_id: str
    storage_path: str
    key_id: str
    work_id: str
    generation: str
    claim_owner: str
    claim_token: str
    claim_generation: int
    claim_expires_at: datetime
    file_identity: str


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


_OPAQUE_CREDENTIAL_REF = re.compile(r"oas-cred:[0-9a-f]{32}\Z")
_RETENTION_DIGEST_ID = re.compile(r"[0-9a-f]{64}\Z")
_CANONICAL_ATTACHMENT_SEGMENT = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_WINDOWS_RESERVED_SEGMENTS = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_RETENTION_CLAIM_TTL = timedelta(minutes=5)


def _require_opaque_credential_ref(value: str | None) -> None:
    if value is not None and (
        not isinstance(value, str) or _OPAQUE_CREDENTIAL_REF.fullmatch(value) is None
    ):
        raise ValueError("credential_ref must be an opaque credential reference")


def _require_retention_digest_id(value: str, name: str) -> None:
    if not isinstance(value, str) or _RETENTION_DIGEST_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a retention digest identifier")


def _iso(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(to_json_value(value), ensure_ascii=False, separators=(",", ":"))


def _canonical_attachment_storage_path(value: str) -> str:
    """Require one cross-platform path spelling for SQLite identity checks."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or value != unicodedata.normalize("NFC", value)
        or value != value.lower()
        or "\\" in value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
    ):
        raise ValueError("storage_path must use the canonical managed-path grammar")
    parts = value.split("/")
    for part in parts:
        if (
            _CANONICAL_ATTACHMENT_SEGMENT.fullmatch(part) is None
            or part.endswith((".", " "))
            or part.split(".", 1)[0] in _WINDOWS_RESERVED_SEGMENTS
        ):
            raise ValueError("storage_path must use the canonical managed-path grammar")
    return value


def _claim_from_row(row: sqlite3.Row) -> ClaimToken | None:
    if row["claim_owner"] is None or row["claim_expires_at"] is None:
        return None
    return ClaimToken(row["claim_owner"], row["claim_generation"], datetime.fromisoformat(row["claim_expires_at"]))


class DurableRuntimeRepository:
    """The sole transactional state boundary for durable-runtime workers."""

    def __init__(
        self,
        control_plane: ControlPlane,
        *,
        retention_hmac_key: bytes | None = None,
        previous_retention_hmac_keys: Iterable[bytes] = (),
    ):
        retention_keys = (
            (() if retention_hmac_key is None else (retention_hmac_key,))
            + tuple(previous_retention_hmac_keys)
        )
        if any(not isinstance(key, bytes) or len(key) < 32 for key in retention_keys):
            raise ValueError("retention HMAC keys must contain at least 32 bytes")
        if len(retention_keys) > 8:
            raise ValueError("at most 8 retention HMAC keys may be active")
        key_ids = tuple(self._retention_key_id(key) for key in retention_keys)
        if len(set(key_ids)) != len(key_ids):
            raise ValueError("retention HMAC key identifiers must be unique")
        self.control_plane = control_plane
        self._retention_hmac_keys = retention_keys
        self._retention_keys_by_id = dict(zip(key_ids, retention_keys))
        self._migrate_retention_attachment_rows()

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
        _require_opaque_credential_ref(credential_ref)
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

    def migrate_channel_account_credential(
        self,
        *,
        account_id: str,
        expected_credential: str,
        credential_ref: str,
        store_secret: Callable[[str], None],
        now: datetime,
    ) -> str | None:
        """Serialize backend publication with the SQLite reference CAS."""
        for value, name in (
            (account_id, "account_id"),
            (expected_credential, "expected_credential"),
            (credential_ref, "credential_ref"),
        ):
            _require_identifier(value, name)
        _require_opaque_credential_ref(credential_ref)
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT credential_ref FROM channel_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return None
            current = row["credential_ref"]
            if current != expected_credential:
                return current
            store_secret(expected_credential)
            conn.execute(
                """UPDATE channel_accounts SET credential_ref = ?, updated_at = ?
                   WHERE account_id = ?""",
                (credential_ref, _iso(now), account_id),
            )
        return credential_ref

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

    def get_ingress_checkpoint(
        self, account_id: str, transport_mode: str
    ) -> dict[str, Any] | None:
        _require_identifier(account_id, "account_id")
        self._validate_transport_mode(transport_mode)
        row = self._conn.execute(
            """SELECT * FROM channel_ingress_checkpoints
               WHERE account_id = ? AND transport_mode = ?""",
            (account_id, transport_mode),
        ).fetchone()
        return self._ingress_checkpoint(row) if row is not None else None

    def claim_ingress_checkpoint(
        self,
        *,
        account_id: str,
        transport_mode: str,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> dict[str, Any]:
        self._validate_lease_window(now, expires_at)
        _require_identifier(account_id, "account_id")
        _require_identifier(owner_id, "owner_id")
        self._validate_transport_mode(transport_mode)
        now_value = _iso(now)
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conflicting = conn.execute(
                """SELECT transport_mode FROM channel_ingress_checkpoints
                   WHERE account_id = ? AND transport_mode != ? LIMIT 1""",
                (account_id, transport_mode),
            ).fetchone()
            if conflicting is not None:
                raise StateConflictError("channel ingress transport is already owned")
            account = conn.execute(
                "SELECT enabled FROM channel_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if account is None or not bool(account["enabled"]):
                raise StateConflictError("channel account is missing or disabled")
            conn.execute(
                """INSERT INTO channel_ingress_checkpoints (
                    account_id, transport_mode, replay_state, claim_generation,
                    reconnect_metadata, updated_at
                ) VALUES (?, ?, '{}', 0, '{}', ?)
                ON CONFLICT(account_id, transport_mode) DO NOTHING""",
                (account_id, transport_mode, now_value),
            )
            row = conn.execute(
                """UPDATE channel_ingress_checkpoints
                   SET claim_owner = ?, claim_generation = claim_generation + 1,
                       claim_expires_at = ?, updated_at = ?
                   WHERE account_id = ? AND transport_mode = ?
                     AND (claim_owner IS NULL OR claim_expires_at <= ?)
                   RETURNING *""",
                (
                    owner_id, _iso(expires_at), now_value,
                    account_id, transport_mode, now_value,
                ),
            ).fetchone()
        if row is None:
            raise StateConflictError("ingress checkpoint has a live owner")
        value = self._ingress_checkpoint(row)
        value["claim"] = ClaimToken(
            row["claim_owner"], int(row["claim_generation"]),
            datetime.fromisoformat(row["claim_expires_at"]),
        )
        return value

    def commit_ingress_checkpoint(
        self,
        *,
        account_id: str,
        transport_mode: str,
        now: datetime,
        token: ClaimToken,
        expected_previous: Mapping[str, Any],
        cursor: str | None = None,
        gateway_session_id: str | None = None,
        gateway_sequence: int | None = None,
        replay_state: Mapping[str, Any] | None = None,
        reconnect_metadata: Mapping[str, Any] | None = None,
        processed_event_key: str,
    ) -> dict[str, Any]:
        """Persist a transport resume point after its referenced event is durable."""
        _require_identifier(account_id, "account_id")
        self._validate_transport_mode(transport_mode)
        if transport_mode == "webhook":
            raise ValueError("webhook ownership has no resumable checkpoint")
        if cursor is not None:
            _require_identifier(cursor, "cursor")
        if gateway_session_id is not None:
            _require_identifier(gateway_session_id, "gateway_session_id")
        if gateway_sequence is not None and (
            isinstance(gateway_sequence, bool)
            or not isinstance(gateway_sequence, int)
            or gateway_sequence < 0
        ):
            raise ValueError("gateway_sequence must be a non-negative integer")
        if transport_mode == "polling" and cursor is None:
            raise ValueError("polling cursor position is required")
        if transport_mode == "gateway" and (
            gateway_session_id is None or gateway_sequence is None
        ):
            raise ValueError("gateway session and sequence position are required")
        _require_identifier(processed_event_key, "processed_event_key")
        if not isinstance(expected_previous, Mapping) or not expected_previous:
            raise ValueError("expected_previous checkpoint is required")
        for value, name in (
            (replay_state, "replay_state"),
            (reconnect_metadata, "reconnect_metadata"),
        ):
            if value is not None and not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping")
        now_value = _iso(now)
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            account = conn.execute(
                "SELECT enabled FROM channel_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if account is None or not bool(account["enabled"]):
                raise StateConflictError("channel account is missing or disabled")
            durable = conn.execute(
                    """SELECT * FROM inbox_events
                       WHERE account_id = ? AND event_key = ?""",
                    (account_id, processed_event_key),
                ).fetchone()
            if durable is None:
                raise StateConflictError(
                    "checkpoint cannot advance before its event is durable"
                )
            current = conn.execute(
                """SELECT * FROM channel_ingress_checkpoints
                   WHERE account_id = ? AND transport_mode = ?""",
                (account_id, transport_mode),
            ).fetchone()
            if current is None:
                raise StateConflictError("ingress checkpoint must be claimed before commit")
            if (
                current["claim_owner"] != token.owner_id
                or int(current["claim_generation"]) != token.generation
                or current["claim_expires_at"] != _iso(token.expires_at)
                or current["claim_expires_at"] <= now_value
            ):
                raise StaleClaimError("stale ingress checkpoint claim")
            current_value = self._ingress_checkpoint(current)
            allowed_expected = {"cursor", "gateway_session_id", "gateway_sequence"}
            if any(key not in allowed_expected for key in expected_previous):
                raise ValueError("unsupported expected checkpoint field")
            required_expected = {
                "polling": {"cursor"},
                "gateway": {"gateway_session_id", "gateway_sequence"},
                "webhook": set(),
            }[transport_mode]
            if set(expected_previous) != required_expected:
                raise ValueError("expected_previous checkpoint proof is incomplete")
            if any(current_value.get(key) != value for key, value in expected_previous.items()):
                raise StateConflictError("checkpoint does not match expected previous state")
            if (
                gateway_sequence is not None
                and current["gateway_sequence"] is not None
                and current["gateway_session_id"] == gateway_session_id
                and gateway_sequence < int(current["gateway_sequence"])
            ):
                raise ValueError("gateway sequence cannot regress within a session")
            event_payload = json.loads(durable["payload"])
            proof = event_payload.get("transport_position") or {}
            proposed_position = {
                "cursor": cursor,
                "gateway_session_id": gateway_session_id,
                "gateway_sequence": gateway_sequence,
            }
            for key, value in proposed_position.items():
                if value is not None and proof.get(key) != value:
                    raise StateConflictError("checkpoint position is not bound to processed event")
            if event_payload.get("transport_mode") != transport_mode:
                raise StateConflictError("checkpoint transport does not match processed event")
            current_replay = json.loads(current["replay_state"])
            merged_replay = dict(replay_state or current_replay)
            if transport_mode == "gateway":
                seen_sessions = list(current_replay.get("seen_gateway_sessions", []))
                current_session = current["gateway_session_id"]
                if (
                    gateway_session_id != current_session
                    and gateway_session_id in seen_sessions
                ):
                    raise StateConflictError("gateway session cannot roll back")
                if current_session is not None and current_session not in seen_sessions:
                    seen_sessions.append(current_session)
                merged_replay["seen_gateway_sessions"] = seen_sessions
            replay_value = _json(merged_replay)
            reconnect_value = _json(
                reconnect_metadata
                if reconnect_metadata is not None
                else (
                    json.loads(current["reconnect_metadata"])
                    if current is not None
                    else {}
                )
            )
            row = conn.execute(
                """
                INSERT INTO channel_ingress_checkpoints (
                    account_id, transport_mode, cursor, gateway_session_id,
                    gateway_sequence, replay_state, claim_owner, claim_generation,
                    claim_expires_at, reconnect_metadata, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?, ?)
                ON CONFLICT(account_id, transport_mode) DO UPDATE SET
                    cursor=excluded.cursor,
                    gateway_session_id=excluded.gateway_session_id,
                    gateway_sequence=excluded.gateway_sequence,
                    replay_state=excluded.replay_state,
                    reconnect_metadata=excluded.reconnect_metadata,
                    claim_owner=NULL, claim_expires_at=NULL,
                    updated_at=excluded.updated_at
                RETURNING *
                """,
                (
                    account_id,
                    transport_mode,
                    cursor if cursor is not None else (current["cursor"] if current else None),
                    gateway_session_id
                    if gateway_session_id is not None
                    else (current["gateway_session_id"] if current else None),
                    gateway_sequence
                    if gateway_sequence is not None
                    else (current["gateway_sequence"] if current else None),
                    replay_value,
                    reconnect_value,
                    now_value,
                ),
            ).fetchone()
        if row is None:
            raise StateConflictError("ingress checkpoint upsert returned no row")
        return self._ingress_checkpoint(row)

    @staticmethod
    def _validate_transport_mode(transport_mode: str) -> None:
        if transport_mode not in {"webhook", "polling", "gateway"}:
            raise ValueError("unsupported ingress transport mode")

    def _ingress_checkpoint(self, row: sqlite3.Row) -> dict[str, Any]:
        value = self.control_plane._row_to_dict(row)
        for field in ("replay_state", "reconnect_metadata"):
            if isinstance(value[field], str):
                value[field] = json.loads(value[field])
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
        return self._enqueue_inbox(event)

    def stage_inbox_attachments(
        self,
        *,
        event_id: str,
        account_id: str,
        attachments: Iterable[Any],
        now: datetime,
    ) -> None:
        serialized = _json(
            [
                {
                    "storage_path": item.storage_path,
                    "size": item.size,
                    "expires_at": _iso(item.expires_at),
                    "ownership_token": item.ownership_token,
                }
                for item in attachments
            ]
        )
        with self._conn:
            self._conn.execute(
                """INSERT INTO inbox_attachment_staging (
                    event_id, account_id, attachments, created_at
                ) VALUES (?, ?, ?, ?)""",
                (event_id, account_id, serialized, _iso(now)),
            )

    def get_staged_inbox_attachments(self, event_id: str) -> tuple[dict[str, Any], ...]:
        row = self._conn.execute(
            "SELECT attachments FROM inbox_attachment_staging WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return tuple(json.loads(row["attachments"])) if row is not None else ()

    def clear_staged_inbox_attachments(self, event_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM inbox_attachment_staging WHERE event_id = ?", (event_id,)
            )

    def enqueue_polled_inbox(
        self,
        event: InboxEvent,
        *,
        transport_mode: str,
        token: ClaimToken,
        now: datetime,
        attachment_stage_event_id: str | None = None,
    ) -> InboxEvent:
        self._validate_transport_mode(transport_mode)
        if transport_mode == "webhook":
            raise ValueError("webhook inbox uses durable nonce admission")
        return self._enqueue_inbox(
            event, transport_mode=transport_mode, transport_token=token,
            transport_now=now,
            attachment_stage_event_id=attachment_stage_event_id,
        )

    def validate_ingress_claim(
        self,
        *,
        account_id: str,
        transport_mode: str,
        token: ClaimToken,
        now: datetime,
    ) -> None:
        row = self._conn.execute(
            """SELECT * FROM channel_ingress_checkpoints
               WHERE account_id = ? AND transport_mode = ?""",
            (account_id, transport_mode),
        ).fetchone()
        if row is None:
            conflicting = self._conn.execute(
                """SELECT 1 FROM channel_ingress_checkpoints
                   WHERE account_id = ? AND transport_mode != ? LIMIT 1""",
                (account_id, transport_mode),
            ).fetchone()
            if conflicting is not None:
                raise StateConflictError("channel ingress transport does not match claim")
            raise StaleClaimError("ingress transport has no claimed checkpoint")
        if (
            row["claim_owner"] != token.owner_id
            or int(row["claim_generation"]) != token.generation
            or row["claim_expires_at"] != _iso(token.expires_at)
            or row["claim_expires_at"] <= _iso(now)
        ):
            raise StaleClaimError("stale ingress transport claim")

    def get_webhook_nonce_receipt(
        self, account_id: str, nonce: str
    ) -> dict[str, Any] | None:
        _require_identifier(account_id, "account_id")
        _require_identifier(nonce, "nonce")
        row = self._conn.execute(
            """SELECT * FROM webhook_nonce_receipts
               WHERE account_id = ? AND nonce = ?""",
            (account_id, nonce),
        ).fetchone()
        return dict(row) if row is not None else None

    def enqueue_inbox_with_nonce(
        self,
        event: InboxEvent,
        *,
        nonce: str,
        request_digest: str,
        nonce_expires_at: datetime,
        attachment_stage_event_id: str | None = None,
    ) -> InboxEvent:
        _require_identifier(nonce, "nonce")
        if not re.fullmatch(r"[0-9a-f]{64}", request_digest):
            raise ValueError("request_digest must be a SHA-256 hex digest")
        _require_aware(nonce_expires_at, "nonce_expires_at")
        return self._enqueue_inbox(
            event,
            nonce=nonce,
            request_digest=request_digest,
            nonce_expires_at=nonce_expires_at,
            attachment_stage_event_id=attachment_stage_event_id,
        )

    def _enqueue_inbox(
        self,
        event: InboxEvent,
        *,
        nonce: str | None = None,
        request_digest: str | None = None,
        nonce_expires_at: datetime | None = None,
        transport_mode: str | None = None,
        transport_token: ClaimToken | None = None,
        transport_now: datetime | None = None,
        attachment_stage_event_id: str | None = None,
    ) -> InboxEvent:
        if event.state != "pending" or event.claim is not None:
            raise ValueError("new inbox events must be pending and unclaimed")
        attachment_paths, attachment_key_id, attachment_tag = (
            self._retention_attachment_source_fields(
                "inbox", event.event_id, event.payload
            )
        )
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if transport_mode is not None:
                if transport_token is None or transport_now is None:
                    raise ValueError("transport claim and time are required")
                now_value = _iso(transport_now)
                owned = conn.execute(
                    """SELECT * FROM channel_ingress_checkpoints
                       WHERE account_id = ? AND transport_mode = ?""",
                    (event.account_id, transport_mode),
                ).fetchone()
                if owned is None:
                    conflicting = conn.execute(
                        """SELECT 1 FROM channel_ingress_checkpoints
                           WHERE account_id = ? AND transport_mode != ? LIMIT 1""",
                        (event.account_id, transport_mode),
                    ).fetchone()
                    if conflicting is not None:
                        raise StateConflictError("channel ingress transport does not match claim")
                    raise StaleClaimError("ingress transport has no claimed checkpoint")
                if (
                    owned["claim_owner"] != transport_token.owner_id
                    or int(owned["claim_generation"]) != transport_token.generation
                    or owned["claim_expires_at"] != _iso(transport_token.expires_at)
                    or owned["claim_expires_at"] <= now_value
                ):
                    raise StaleClaimError("stale ingress transport claim")
            if nonce is not None:
                conflicting_transport = conn.execute(
                    """SELECT transport_mode FROM channel_ingress_checkpoints
                       WHERE account_id = ? AND transport_mode != 'webhook'
                       LIMIT 1""",
                    (event.account_id,),
                ).fetchone()
                if conflicting_transport is not None:
                    raise StateConflictError(
                        "channel account is already owned by another ingress transport"
                    )
                conn.execute(
                    """INSERT INTO channel_ingress_checkpoints (
                        account_id, transport_mode, cursor, gateway_session_id,
                        gateway_sequence, replay_state, claim_owner,
                        claim_generation, claim_expires_at, reconnect_metadata,
                        updated_at
                    ) VALUES (?, 'webhook', NULL, NULL, NULL, '{}', NULL, 0,
                              NULL, '{}', ?)
                    ON CONFLICT(account_id, transport_mode) DO NOTHING""",
                    (event.account_id, _iso(event.created_at)),
                )
                receipt = conn.execute(
                    """SELECT * FROM webhook_nonce_receipts
                       WHERE account_id = ? AND nonce = ?""",
                    (event.account_id, nonce),
                ).fetchone()
                if receipt is not None:
                    if receipt["request_digest"] != request_digest:
                        raise StateConflictError("webhook nonce digest mismatch")
                    row = conn.execute(
                        "SELECT * FROM inbox_events WHERE event_id = ?",
                        (receipt["event_id"],),
                    ).fetchone()
                    if row is None:
                        raise StateConflictError("webhook nonce receipt is orphaned")
                    return self._inbox(row)
            if attachment_stage_event_id is not None:
                staged = conn.execute(
                    """SELECT attachments FROM inbox_attachment_staging
                       WHERE event_id = ? AND account_id = ?""",
                    (attachment_stage_event_id, event.account_id),
                ).fetchone()
                if staged is None:
                    raise StateConflictError("attachment staging manifest is missing")
                expected_attachments = (
                    to_json_value(event.payload)
                    .get("normalized_event", {})
                    .get("attachments", [])
                )
                staged_references = [
                    {
                        "storage_path": item["storage_path"],
                        "size": item["size"],
                        "expires_at": item["expires_at"],
                    }
                    for item in json.loads(staged["attachments"])
                ]
                if staged_references != expected_attachments:
                    raise StateConflictError(
                        "attachment staging manifest does not match inbox"
                    )
            tombstone = self._find_retention_tombstone(
                conn, "inbox", event.account_id, event.event_key
            )
            if tombstone is not None:
                if attachment_stage_event_id is not None:
                    raise StateConflictError(
                        "retained duplicate cannot adopt new attachments"
                    )
                row = conn.execute(
                    "SELECT * FROM inbox_events WHERE event_id = ?",
                    (tombstone["record_id"],),
                ).fetchone()
                if row is None:
                    raise StateConflictError("inbox retention tombstone is orphaned")
                return self._inbox(row)
            if attachment_key_id is not None:
                self._validate_retention_key_registry(conn)
                conn.execute(
                    """INSERT INTO retention_key_registry (key_id, first_used_at)
                       VALUES (?, ?) ON CONFLICT(key_id) DO NOTHING""",
                    (attachment_key_id, _iso(event.created_at)),
                )
            conn.execute(
                """
                INSERT INTO inbox_events (
                    event_id, event_key, account_id, conversation_id, payload, state,
                    attempt, next_attempt_at, last_error, claim_owner,
                    claim_generation, claim_expires_at, created_at, updated_at,
                    retention_attachment_paths, retention_attachment_key_id,
                    retention_attachment_tag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    attachment_paths,
                    attachment_key_id,
                    attachment_tag,
                ),
            )
            row = conn.execute(
                "SELECT * FROM inbox_events WHERE account_id = ? AND event_key = ?",
                (event.account_id, event.event_key),
            ).fetchone()
            if nonce is not None:
                conn.execute(
                    """INSERT INTO webhook_nonce_receipts (
                        account_id, nonce, request_digest, event_id, event_key,
                        expires_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.account_id,
                        nonce,
                        request_digest,
                        row["event_id"],
                        row["event_key"],
                        _iso(nonce_expires_at),
                        _iso(event.created_at),
                    ),
                )
            if attachment_stage_event_id is not None:
                deleted = conn.execute(
                    "DELETE FROM inbox_attachment_staging WHERE event_id = ?",
                    (attachment_stage_event_id,),
                )
                if deleted.rowcount != 1:
                    raise StateConflictError("attachment staging adoption was lost")
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
                SET state = CASE WHEN state = 'dispatched' THEN 'dispatched' ELSE 'claimed' END,
                    claim_owner = ?,
                    claim_generation = claim_generation + 1, claim_expires_at = ?,
                    attempt = attempt + 1, updated_at = ?
                WHERE event_id = ?
                  AND (
                        state IN ('pending', 'retry_wait')
                        OR (state IN ('claimed', 'dispatched')
                            AND (claim_owner IS NULL OR claim_expires_at <= ?))
                  )
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                RETURNING *
                """,
                (owner_id, _iso(expires_at), _iso(now), event_id, _iso(now), _iso(now)),
            ).fetchone()
        return self._inbox(row) if row else None

    def claim_due_inbox(
        self,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
        *,
        limit: int = 1,
    ) -> list[InboxEvent]:
        self._validate_lease_window(now, expires_at)
        _require_identifier(owner_id, "owner_id")
        _require_limit(limit)
        claimed: list[InboxEvent] = []
        conn = self._conn
        with conn:
            for _ in range(limit):
                row = conn.execute(
                    """
                    UPDATE inbox_events
                    SET state = CASE WHEN state = 'dispatched' THEN 'dispatched' ELSE 'claimed' END,
                        claim_owner = ?, claim_generation = claim_generation + 1,
                        claim_expires_at = ?, attempt = attempt + 1, updated_at = ?
                    WHERE event_id = (
                        SELECT event_id FROM inbox_events
                        WHERE (
                            state IN ('pending', 'retry_wait')
                            OR (state IN ('claimed', 'dispatched')
                                AND (claim_owner IS NULL OR claim_expires_at <= ?))
                        )
                        AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                        ORDER BY COALESCE(next_attempt_at, created_at), created_at, event_id
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
                    ),
                ).fetchone()
                if row is None:
                    break
                claimed.append(self._inbox(row))
        return claimed

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
                SELECT * FROM inbox_events
                WHERE event_id = ? AND state IN ('claimed', 'dispatched')
                  AND claim_owner = ? AND claim_generation = ?
                  AND claim_expires_at = ? AND claim_expires_at > ?
                """,
                (
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
            if event_row["state"] == "dispatched":
                turn_row = None
                if event_row["runtime_turn_id"] is not None:
                    turn_row = conn.execute(
                        "SELECT * FROM runtime_turns WHERE turn_id = ?",
                        (event_row["runtime_turn_id"],),
                    ).fetchone()
                if turn_row is None:
                    turn_row = conn.execute(
                        "SELECT * FROM runtime_turns WHERE source_event_key = ?",
                        (source_event_key,),
                    ).fetchone()
                if turn_row is None:
                    raise StateConflictError("dispatched inbox event has no runtime turn")
                if (
                    turn_row["thread_id"] != thread_id
                    or turn_row["session_id"] != session_id
                    or turn_row["user_input"] != user_input
                ):
                    raise StateConflictError("replayed dispatch does not match its runtime turn")
                if turn_row["status"] not in {"error", "cancelled"}:
                    return self.control_plane._row_to_dict(turn_row)
                source_event_key = _json(
                    [
                        event_row["account_id"], event_row["event_key"],
                        "attempt", int(event_row["attempt"]),
                    ]
                )
            updated = conn.execute(
                """
                UPDATE inbox_events SET state = 'dispatched', updated_at = ?
                WHERE event_id = ? AND state IN ('claimed', 'dispatched')
                  AND claim_owner = ? AND claim_generation = ?
                  AND claim_expires_at = ? AND claim_expires_at > ?
                """,
                (
                    now_value,
                    event_id,
                    token.owner_id,
                    token.generation,
                    _iso(token.expires_at),
                    now_value,
                ),
            )
            if updated.rowcount != 1:
                raise StaleClaimError(f"stale inbox claim: {event_id}")
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
                """UPDATE inbox_events SET runtime_turn_id = ?
                   WHERE event_id = ? AND claim_owner = ? AND claim_generation = ?""",
                (turn_id, event_id, token.owner_id, token.generation),
            )
            conn.execute(
                "UPDATE runtime_threads SET status = 'active', updated_at = ? WHERE thread_id = ?",
                (now_value, thread_id),
            )
            turn_row = conn.execute(
                "SELECT * FROM runtime_turns WHERE turn_id = ?", (turn_id,)
            ).fetchone()
        return self.control_plane._row_to_dict(turn_row)

    def complete_inbox(
        self,
        event_id: str,
        token: ClaimToken,
        now: datetime,
    ) -> InboxEvent:
        """Complete an inbox item only while the caller owns its live fence."""
        now_value = _iso(now)
        with self._conn:
            row = self._conn.execute(
                """
                UPDATE inbox_events
                SET state = 'succeeded', claim_owner = NULL, claim_expires_at = NULL,
                    next_attempt_at = NULL, last_error = NULL, updated_at = ?
                WHERE event_id = ? AND state IN ('claimed', 'dispatched')
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
            if row is None:
                raise StaleClaimError(f"stale inbox claim: {event_id}")
        return self._inbox(row)

    def complete_inbox_after_agent(
        self,
        event_id: str,
        token: ClaimToken,
        *,
        source_event_key: str,
        now: datetime,
        reply_obligation: OutboxObligation | None = None,
    ) -> InboxEvent:
        """Atomically require every durable effect resolved before inbox success."""
        if reply_obligation is not None:
            if reply_obligation.state != "pending" or reply_obligation.claim is not None:
                raise ValueError("channel reply obligation must be pending and unclaimed")
            if reply_obligation.next_attempt_at is not None or reply_obligation.attempt != 0:
                raise ValueError("channel reply obligation must not have retry state")
        now_value = _iso(now)
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            unresolved = self._conn.execute(
                """SELECT 1 FROM tool_calls WHERE source_event_key = ?
                   AND state != 'completed' LIMIT 1""",
                (source_event_key,),
            ).fetchone()
            if unresolved is not None:
                raise StateConflictError("inbox has unresolved tool effects")
            if reply_obligation is not None:
                self._conn.execute(
                    """
                    INSERT INTO outbox_obligations (
                        obligation_id, idempotency_key, destination, payload, state,
                        attempt, next_attempt_at, last_error, acknowledgement,
                        claim_owner, claim_generation, claim_expires_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL,
                              NULL, 0, NULL, ?, ?)
                    ON CONFLICT(destination, idempotency_key) DO NOTHING
                    """,
                    (
                        reply_obligation.obligation_id,
                        reply_obligation.idempotency_key,
                        reply_obligation.destination,
                        _json(reply_obligation.payload),
                        _iso(reply_obligation.created_at),
                        _iso(reply_obligation.updated_at),
                    ),
                )
                persisted = self._conn.execute(
                    """SELECT * FROM outbox_obligations
                       WHERE destination = ? AND idempotency_key = ?""",
                    (reply_obligation.destination, reply_obligation.idempotency_key),
                ).fetchone()
                if (
                    persisted is None
                    or persisted["obligation_id"] != reply_obligation.obligation_id
                    or persisted["payload"] != _json(reply_obligation.payload)
                ):
                    raise StateConflictError("channel reply idempotency conflict")
            row = self._conn.execute(
                """UPDATE inbox_events
                   SET state = 'succeeded', claim_owner = NULL,
                       claim_expires_at = NULL, next_attempt_at = NULL,
                       last_error = NULL, updated_at = ?
                   WHERE event_id = ? AND state = 'dispatched'
                     AND claim_owner = ? AND claim_generation = ?
                     AND claim_expires_at = ? AND claim_expires_at > ?
                   RETURNING *""",
                (
                    now_value, event_id, token.owner_id, token.generation,
                    _iso(token.expires_at), now_value,
                ),
            ).fetchone()
            if row is None:
                raise StaleClaimError(f"stale inbox claim: {event_id}")
        return self._inbox(row)

    def retry_dispatched_inbox(
        self,
        event_id: str,
        token: ClaimToken,
        now: datetime,
        *,
        error: str,
        next_attempt_at: datetime | None = None,
    ) -> InboxEvent:
        now_value = _iso(now)
        retry_value = _iso(next_attempt_at or now)
        safe_error = str(error or "Agent stream did not complete")[:500]
        with self._conn:
            row = self._conn.execute(
                """UPDATE inbox_events
                   SET state = 'dispatched', last_error = ?, next_attempt_at = ?,
                       claim_owner = NULL, claim_expires_at = NULL, updated_at = ?
                   WHERE event_id = ? AND state = 'dispatched'
                     AND claim_owner = ? AND claim_generation = ?
                     AND claim_expires_at = ? AND claim_expires_at > ?
                   RETURNING *""",
                (
                    safe_error, retry_value, now_value, event_id,
                    token.owner_id, token.generation, _iso(token.expires_at), now_value,
                ),
            ).fetchone()
        if row is None:
            raise StaleClaimError(f"stale inbox claim: {event_id}")
        return self._inbox(row)

    def enqueue_outbox(self, obligation: OutboxObligation) -> OutboxObligation:
        if obligation.state != "pending" or obligation.claim is not None:
            raise ValueError("new outbox obligations must be pending and unclaimed")
        attachment_paths, attachment_key_id, attachment_tag = (
            self._retention_attachment_source_fields(
                "outbox", obligation.obligation_id, obligation.payload
            )
        )
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            tombstone = self._find_retention_tombstone(
                conn, "outbox", obligation.destination, obligation.idempotency_key
            )
            if tombstone is not None:
                row = conn.execute(
                    "SELECT * FROM outbox_obligations WHERE obligation_id = ?",
                    (tombstone["record_id"],),
                ).fetchone()
                if row is None:
                    raise StateConflictError("outbox retention tombstone is orphaned")
                return self._outbox(row)
            if attachment_key_id is not None:
                self._validate_retention_key_registry(conn)
                conn.execute(
                    """INSERT INTO retention_key_registry (key_id, first_used_at)
                       VALUES (?, ?) ON CONFLICT(key_id) DO NOTHING""",
                    (attachment_key_id, _iso(obligation.created_at)),
                )
            conn.execute(
                """
                INSERT INTO outbox_obligations (
                    obligation_id, idempotency_key, destination, payload, state,
                    attempt, next_attempt_at, last_error, acknowledgement,
                    claim_owner, claim_generation, claim_expires_at, created_at, updated_at,
                    retention_attachment_paths, retention_attachment_key_id,
                    retention_attachment_tag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    attachment_paths,
                    attachment_key_id,
                    attachment_tag,
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
        attachment_paths, attachment_key_id, attachment_tag = (
            self._retention_attachment_source_fields(
                "outbox", obligation.obligation_id, obligation.payload
            )
        )
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
            conn.execute("BEGIN IMMEDIATE")
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
            tombstone = self._find_retention_tombstone(
                conn, "outbox", obligation.destination, obligation.idempotency_key
            )
            if tombstone is None:
                if attachment_key_id is not None:
                    self._validate_retention_key_registry(conn)
                    conn.execute(
                        """INSERT INTO retention_key_registry (key_id, first_used_at)
                           VALUES (?, ?) ON CONFLICT(key_id) DO NOTHING""",
                        (attachment_key_id, _iso(obligation.created_at)),
                    )
                conn.execute(
                    """
                    INSERT INTO outbox_obligations (
                        obligation_id, idempotency_key, destination, payload, state,
                        attempt, next_attempt_at, last_error, acknowledgement,
                        claim_owner, claim_generation, claim_expires_at, created_at, updated_at,
                        retention_attachment_paths, retention_attachment_key_id,
                        retention_attachment_tag
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        attachment_paths,
                        attachment_key_id,
                        attachment_tag,
                    ),
                )
                row = conn.execute(
                    """SELECT * FROM outbox_obligations
                       WHERE destination = ? AND idempotency_key = ?""",
                    (obligation.destination, obligation.idempotency_key),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM outbox_obligations WHERE obligation_id = ?",
                    (tombstone["record_id"],),
                ).fetchone()
            if row is None or (tombstone is None and (
                row["obligation_id"] != obligation.obligation_id
                or row["destination"] != obligation.destination
                or row["idempotency_key"] != obligation.idempotency_key
                or row["payload"] != _json(obligation.payload)
            )):
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

    def apply_retention_batch(
        self,
        *,
        now: datetime,
        inbox_before: datetime,
        outbox_before: datetime,
        audit_before: datetime,
        limit: int,
    ) -> dict[str, Any]:
        """Redact one bounded batch and append its compliance audit atomically."""
        _require_limit(limit)
        if not self._retention_hmac_keys:
            raise StateConflictError("retention requires an externally managed HMAC key")
        now_value = _iso(now)
        inbox_cutoff = _iso(inbox_before)
        outbox_cutoff = _iso(outbox_before)
        audit_cutoff = _iso(audit_before)
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_retention_key_registry(conn)
            self._assert_unambiguous_retention_attachment_state(conn)
            conn.execute(
                """INSERT INTO retention_key_registry (key_id, first_used_at)
                   VALUES (?, ?) ON CONFLICT(key_id) DO NOTHING""",
                (self._retention_key_id(self._retention_hmac_keys[0]), now_value),
            )
            conn.execute(
                "DELETE FROM webhook_nonce_receipts WHERE expires_at <= ?",
                (now_value,),
            )
            inbox_rows = conn.execute(
                """
                SELECT event_id, payload, account_id, event_key, state,
                       retention_attachment_paths, retention_attachment_key_id,
                       retention_attachment_tag
                FROM inbox_events
                WHERE retained_at IS NULL AND updated_at <= ?
                  AND state IN ('succeeded', 'dead_letter')
                  AND NOT EXISTS (
                      SELECT 1 FROM webhook_nonce_receipts AS receipt
                      WHERE receipt.event_id = inbox_events.event_id
                        AND receipt.expires_at > ?
                  )
                ORDER BY updated_at, event_id LIMIT ?
                """,
                (inbox_cutoff, now_value, limit),
            ).fetchall()
            remaining = limit - len(inbox_rows)
            outbox_rows = conn.execute(
                """
                SELECT obligation_id, payload, destination, idempotency_key, state,
                       retention_attachment_paths, retention_attachment_key_id,
                       retention_attachment_tag
                FROM outbox_obligations
                WHERE retained_at IS NULL AND updated_at <= ?
                  AND state IN ('acknowledged', 'dead_letter', 'delivery_unknown')
                ORDER BY updated_at, obligation_id LIMIT ?
                """,
                (outbox_cutoff, remaining),
            ).fetchall()
            remaining -= len(outbox_rows)
            audit_rows = conn.execute(
                """
                SELECT audit_id FROM runtime_audit_events
                WHERE created_at <= ?
                ORDER BY created_at, audit_id LIMIT ?
                """,
                (audit_cutoff, remaining),
            ).fetchall()

            queue_occupancy = conn.execute(
                "SELECT COUNT(*) FROM retention_attachment_queue"
            ).fetchone()[0]
            queue_limit = min(limit, 64, max(0, 64 - queue_occupancy))
            queued_attachment_occurrences: list[tuple[str, str]] = []
            queued_identities: dict[str, str] = {}
            backlog_rows = conn.execute(
                """SELECT backlog_id, storage_paths, key_id, generation, backlog_tag
                   FROM retention_attachment_backlog
                   ORDER BY queued_at, backlog_id LIMIT ?""",
                (queue_limit,),
            ).fetchall()
            for backlog_row in backlog_rows:
                occurrences = self._authenticate_retention_attachment_backlog(
                    backlog_row
                )
                remaining_occurrences: list[tuple[str, str]] = []
                for storage_path, file_identity in occurrences:
                    existing_identity = queued_identities.get(storage_path)
                    if existing_identity is not None:
                        if existing_identity != file_identity:
                            raise StateConflictError(
                                "retention attachment occurrences are ambiguous"
                            )
                        continue
                    if len(queued_attachment_occurrences) < queue_limit:
                        queued_attachment_occurrences.append(
                            (storage_path, file_identity)
                        )
                        queued_identities[storage_path] = file_identity
                    else:
                        remaining_occurrences.append((storage_path, file_identity))
                if remaining_occurrences:
                    replacement = self._new_retention_attachment_backlog_page(
                        remaining_occurrences
                    )
                    updated = conn.execute(
                        """UPDATE retention_attachment_backlog
                           SET backlog_id = ?, storage_paths = ?, key_id = ?,
                               generation = ?, backlog_tag = ?
                           WHERE backlog_id = ? AND storage_paths = ? AND key_id = ?
                             AND generation = ? AND backlog_tag = ?""",
                        (
                            *replacement,
                            backlog_row["backlog_id"],
                            backlog_row["storage_paths"],
                            backlog_row["key_id"],
                            backlog_row["generation"],
                            backlog_row["backlog_tag"],
                        ),
                    )
                    if updated.rowcount != 1:
                        raise StateConflictError(
                            "retention attachment backlog state changed"
                        )
                else:
                    deleted = conn.execute(
                        """DELETE FROM retention_attachment_backlog
                           WHERE backlog_id = ? AND storage_paths = ? AND key_id = ?
                             AND generation = ? AND backlog_tag = ?""",
                        (
                            backlog_row["backlog_id"],
                            backlog_row["storage_paths"],
                            backlog_row["key_id"],
                            backlog_row["generation"],
                            backlog_row["backlog_tag"],
                        ),
                    )
                    if deleted.rowcount != 1:
                        raise StateConflictError(
                            "retention attachment backlog state changed"
                        )

            attachment_occurrences: list[tuple[str, str]] = []
            attachment_identities: dict[str, str] = {}
            rejected_attachment_payloads = 0
            for row in inbox_rows:
                occurrences = self._authenticate_retention_attachment_source(
                    row, "inbox", "event_id"
                )
                if not occurrences and self._unsigned_attachment_source_requires_migration(
                    row["payload"]
                ):
                    raise StateConflictError(
                        "unsigned inbox attachment source requires explicit migration"
                    )
                for storage_path, file_identity in occurrences:
                    prior_identity = attachment_identities.get(storage_path)
                    if prior_identity is not None and prior_identity != file_identity:
                        raise StateConflictError(
                            "retention attachment occurrences are ambiguous"
                        )
                    if prior_identity is None:
                        attachment_occurrences.append((storage_path, file_identity))
                        attachment_identities[storage_path] = file_identity
            for row in outbox_rows:
                occurrences = self._authenticate_retention_attachment_source(
                    row, "outbox", "obligation_id"
                )
                if not occurrences and self._unsigned_attachment_source_requires_migration(
                    row["payload"]
                ):
                    raise StateConflictError(
                        "unsigned outbox attachment source requires explicit migration"
                    )
                for storage_path, file_identity in occurrences:
                    prior_identity = attachment_identities.get(storage_path)
                    if prior_identity is not None and prior_identity != file_identity:
                        raise StateConflictError(
                            "retention attachment occurrences are ambiguous"
                        )
                    if prior_identity is None:
                        attachment_occurrences.append((storage_path, file_identity))
                        attachment_identities[storage_path] = file_identity
            source_candidates: list[tuple[str, str]] = []
            for storage_path, file_identity in attachment_occurrences:
                queued_identity = queued_identities.get(storage_path)
                if queued_identity is not None:
                    if queued_identity != file_identity:
                        raise StateConflictError(
                            "retention attachment occurrences are ambiguous"
                        )
                    continue
                source_candidates.append((storage_path, file_identity))
            available = queue_limit - len(queued_attachment_occurrences)
            queued_attachment_occurrences.extend(source_candidates[:available])
            deferred_attachment_occurrences = source_candidates[available:]

            inbox_retention = [
                (
                    row,
                    self._retention_token("inbox-record", row["event_id"]),
                    self._retention_token("inbox-account", row["account_id"]),
                    self._retention_token("inbox-event-key", row["event_key"]),
                )
                for row in inbox_rows
            ]
            outbox_retention = [
                (
                    row,
                    self._retention_token("outbox-record", row["obligation_id"]),
                    self._retention_token("outbox-destination", row["destination"]),
                    self._retention_token(
                        "outbox-idempotency", row["idempotency_key"]
                    ),
                )
                for row in outbox_rows
            ]
            audit_ids = [row["audit_id"] for row in audit_rows]

            for row, retained_id, _, _ in inbox_retention:
                conn.execute(
                    """INSERT INTO runtime_retention_tombstones (
                           entity_kind, scope_digest, idempotency_digest, key_id,
                           record_id, terminal_state, retained_at
                       ) VALUES ('inbox', ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(entity_kind, scope_digest, idempotency_digest)
                       DO NOTHING""",
                    (
                        self._retention_digest(row["account_id"]),
                        self._retention_digest(row["event_key"]),
                        self._retention_key_id(self._retention_hmac_keys[0]),
                        retained_id,
                        row["state"],
                        now_value,
                    ),
                )
            for row, retained_id, _, _ in outbox_retention:
                conn.execute(
                    """INSERT INTO runtime_retention_tombstones (
                           entity_kind, scope_digest, idempotency_digest, key_id,
                           record_id, terminal_state, retained_at
                       ) VALUES ('outbox', ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(entity_kind, scope_digest, idempotency_digest)
                       DO NOTHING""",
                    (
                        self._retention_digest(row["destination"]),
                        self._retention_digest(row["idempotency_key"]),
                        self._retention_key_id(self._retention_hmac_keys[0]),
                        retained_id,
                        row["state"],
                        now_value,
                    ),
                )
            inserted_attachment_paths: list[str] = []
            for storage_path, file_identity in queued_attachment_occurrences:
                existing = conn.execute(
                    """SELECT file_identity FROM retention_attachment_queue
                       WHERE storage_path = ?
                       UNION ALL
                       SELECT file_identity FROM retention_attachment_dead_letters
                       WHERE storage_path = ? LIMIT 1""",
                    (storage_path, storage_path),
                ).fetchone()
                if existing is not None:
                    if existing["file_identity"] != file_identity:
                        raise StateConflictError(
                            "retention attachment occurrence conflicts with active state"
                        )
                    continue
                self._validate_retention_file_identity(file_identity)
                key_id, work_id, generation, queue_id = (
                    self._new_retention_attachment_identity(
                        "queue", storage_path
                    )
                )
                file_identity_tag = self._retention_file_identity_digest(
                    "queue",
                    storage_path,
                    key_id,
                    work_id,
                    generation,
                    file_identity,
                    self._retention_hmac_keys[0],
                )
                inserted = conn.execute(
                    """INSERT INTO retention_attachment_queue (
                           queue_id, storage_path, key_id, work_id, generation,
                           queued_at, next_attempt_at, file_identity,
                           file_identity_tag
                       ) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
                       WHERE NOT EXISTS (
                           SELECT 1 FROM retention_attachment_queue
                           WHERE storage_path = ?
                       ) AND NOT EXISTS (
                           SELECT 1 FROM retention_attachment_dead_letters
                           WHERE storage_path = ?
                       )
                       ON CONFLICT(queue_id) DO NOTHING""",
                    (
                        queue_id,
                        storage_path,
                        key_id,
                        work_id,
                        generation,
                        now_value,
                        now_value,
                        file_identity,
                        file_identity_tag,
                        storage_path,
                        storage_path,
                    ),
                )
                if inserted.rowcount != 1:
                    raise StateConflictError(
                        "retention attachment queue identity collision"
                    )
                inserted_attachment_paths.append(storage_path)
            for offset in range(0, len(deferred_attachment_occurrences), 64):
                page = self._new_retention_attachment_backlog_page(
                    deferred_attachment_occurrences[offset : offset + 64]
                )
                conn.execute(
                    """INSERT INTO retention_attachment_backlog (
                           backlog_id, storage_paths, key_id, generation,
                           backlog_tag, queued_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (*page, now_value),
                )

            if inbox_retention:
                conn.executemany(
                    """UPDATE inbox_events
                        SET event_id = ?, event_key = ?, account_id = ?,
                            conversation_id = 'retained',
                            payload = '{}', last_error = NULL,
                            next_attempt_at = NULL, claim_owner = NULL,
                            claim_expires_at = NULL, runtime_turn_id = NULL, retained_at = ?,
                            retention_attachment_paths = NULL,
                            retention_attachment_key_id = NULL,
                            retention_attachment_tag = NULL
                        WHERE event_id = ?""",
                    (
                        (
                            retained_id,
                            retained_event_key,
                            retained_account,
                            now_value,
                            row["event_id"],
                        )
                        for row, retained_id, retained_account, retained_event_key
                        in inbox_retention
                    ),
                )
            if outbox_retention:
                conn.executemany(
                    """UPDATE outbox_obligations
                        SET obligation_id = ?, destination = ?, idempotency_key = ?,
                            payload = '{}',
                            last_error = NULL, acknowledgement = NULL,
                            next_attempt_at = NULL, claim_owner = NULL,
                            claim_expires_at = NULL, retained_at = ?,
                            retention_attachment_paths = NULL,
                            retention_attachment_key_id = NULL,
                            retention_attachment_tag = NULL
                        WHERE obligation_id = ?""",
                    (
                        (
                            retained_id,
                            retained_destination,
                            retained_idempotency,
                            now_value,
                            row["obligation_id"],
                        )
                        for row, retained_id, retained_destination, retained_idempotency
                        in outbox_retention
                    ),
                )
            if audit_ids:
                placeholders = ",".join("?" for _ in audit_ids)
                conn.execute(
                    f"DELETE FROM runtime_audit_events WHERE audit_id IN ({placeholders})",
                    audit_ids,
                )

            result = {
                "inbox_redacted": len(inbox_retention),
                "outbox_redacted": len(outbox_retention),
                "audit_deleted": len(audit_ids),
                "attachment_paths": (),
                "attachment_claims": (),
            }
            if (
                inbox_retention
                or outbox_retention
                or audit_ids
                or rejected_attachment_payloads
                or inserted_attachment_paths
                or deferred_attachment_occurrences
            ):
                audit_payload = {
                    "inbox_redacted": result["inbox_redacted"],
                    "outbox_redacted": result["outbox_redacted"],
                    "audit_deleted": result["audit_deleted"],
                    "attachments_queued": len(inserted_attachment_paths),
                    "attachments_deferred": len(deferred_attachment_occurrences),
                    "attachment_payloads_rejected": rejected_attachment_payloads,
                }
                conn.execute(
                    """
                    INSERT INTO runtime_audit_events (
                        audit_id, entity_kind, entity_id, action, actor_id, payload, created_at
                    ) VALUES (?, 'retention', 'runtime', 'retention_batch',
                              'retention-worker', ?, ?)
                    """,
                    (f"retention:{uuid.uuid4().hex}", _json(audit_payload), now_value),
                )
            claims = self._claim_due_retention_attachments(
                conn,
                now=now,
                limit=min(limit, 64),
                claim_owner=f"retention-worker:{uuid.uuid4().hex}",
            )
        return {
            **result,
            "attachment_claims": claims,
            "attachment_paths": tuple(claim.storage_path for claim in claims),
        }

    def claim_retention_attachments(
        self,
        *,
        now: datetime,
        limit: int,
        claim_owner: str | None = None,
    ) -> tuple[RetentionAttachmentClaim, ...]:
        """Authenticate and lease due rows before revealing filesystem paths."""
        _require_limit(limit)
        owner = claim_owner or f"retention-worker:{uuid.uuid4().hex}"
        _require_identifier(owner, "claim_owner")
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_retention_key_registry(conn)
            self._assert_unambiguous_retention_attachment_state(conn)
            return self._claim_due_retention_attachments(
                conn, now=now, limit=min(limit, 64), claim_owner=owner
            )

    def authorize_retention_attachment_deletion(
        self,
        claim: RetentionAttachmentClaim,
        file_identity: str,
        *,
        now: datetime,
    ) -> RetentionAttachmentClaim:
        """Fence deletion and bind it to the opened object's immutable identity."""
        self._validate_retention_attachment_claim(claim)
        now_value = _iso(now)
        self._validate_retention_file_identity(file_identity)
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_retention_key_registry(conn)
            self._assert_unambiguous_retention_attachment_state(conn)
            row = conn.execute(
                """SELECT * FROM retention_attachment_queue
                   WHERE storage_path = ?""",
                (claim.storage_path,),
            ).fetchone()
            if row is None:
                raise StaleClaimError("retention attachment claim no longer exists")
            self._authenticate_retention_attachment_row(row, "queue")
            if not self._retention_claim_matches_row(claim, row, now_value=now_value):
                raise StaleClaimError("retention attachment claim is expired or stale")
            persisted_identity = row["file_identity"]
            if persisted_identity != file_identity:
                raise StateConflictError(
                    "retention attachment immutable file identity changed"
                )
            updated = conn.execute(
                """UPDATE retention_attachment_queue
                   SET state = 'deleting'
                   WHERE queue_id = ? AND storage_path = ? AND key_id = ?
                      AND work_id = ? AND generation = ? AND claim_owner = ?
                      AND claim_token = ? AND claim_generation = ?
                      AND claim_expires_at = ? AND claim_expires_at > ?
                      AND state IN ('claimed', 'deleting')
                      AND file_identity = ?""",
                (
                    claim.queue_id,
                    claim.storage_path,
                    claim.key_id,
                    claim.work_id,
                    claim.generation,
                    claim.claim_owner,
                    claim.claim_token,
                    claim.claim_generation,
                    _iso(claim.claim_expires_at),
                    now_value,
                    file_identity,
                ),
            )
            if updated.rowcount != 1:
                raise StaleClaimError("retention attachment claim changed")
            return RetentionAttachmentClaim(
                queue_id=claim.queue_id,
                storage_path=claim.storage_path,
                key_id=claim.key_id,
                work_id=claim.work_id,
                generation=claim.generation,
                claim_owner=claim.claim_owner,
                claim_token=claim.claim_token,
                claim_generation=claim.claim_generation,
                claim_expires_at=claim.claim_expires_at,
                file_identity=file_identity,
            )

    def complete_retention_attachments(
        self,
        outcomes: Mapping[RetentionAttachmentClaim, str],
        *,
        now: datetime,
        max_attempts: int = 5,
    ) -> dict[str, int]:
        """CAS authenticated claims and audit only transitions that actually commit."""
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 100
        ):
            raise ValueError("max_attempts must be an integer between 1 and 100")
        if len(outcomes) > 1000:
            raise ValueError("attachment outcome batch exceeds 1000")
        allowed = {"deleted", "missing", "rejected", "failed", "stale", "fenced"}
        if any(outcome not in allowed for outcome in outcomes.values()):
            raise ValueError("unsupported attachment retention outcome")
        if any(
            not isinstance(claim, RetentionAttachmentClaim) for claim in outcomes
        ):
            raise ValueError("attachment outcomes require authenticated claims")
        now_value = _iso(now)
        counts = {
            name: 0
            for name in (
                "deleted",
                "missing",
                "rejected",
                "failed",
                "quarantined",
                "stale",
                "fenced",
                "no_op",
            )
        }
        if not outcomes:
            return counts
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_retention_key_registry(conn)
            self._assert_unambiguous_retention_attachment_state(conn)
            for claim, outcome in outcomes.items():
                self._validate_retention_attachment_claim(claim)
                row = conn.execute(
                    """SELECT * FROM retention_attachment_queue
                       WHERE storage_path = ?""",
                    (claim.storage_path,),
                ).fetchone()
                if row is None:
                    dead_row = conn.execute(
                        """SELECT * FROM retention_attachment_dead_letters
                           WHERE storage_path = ?""",
                        (claim.storage_path,),
                    ).fetchone()
                    if dead_row is None:
                        counts["no_op"] += 1
                    else:
                        self._authenticate_retention_attachment_row(
                            dead_row, "dead-letter"
                        )
                        counts["stale"] += 1
                    continue
                self._authenticate_retention_attachment_row(row, "queue")
                if not self._retention_claim_matches_row(
                    claim, row, now_value=now_value
                ):
                    counts["stale"] += 1
                    continue
                if outcome == "stale":
                    counts["stale"] += 1
                    continue
                if outcome == "fenced":
                    counts["fenced"] += 1
                    continue
                if row["state"] == "deleting" and outcome != "deleted":
                    counts["fenced"] += 1
                    continue
                if outcome == "deleted" and row["state"] != "deleting":
                    raise StateConflictError(
                        "retention attachment deletion was not authorized"
                    )

                claim_where = """queue_id = ? AND storage_path = ? AND key_id = ?
                    AND work_id = ? AND generation = ? AND claim_owner = ?
                    AND claim_token = ? AND claim_generation = ?
                    AND claim_expires_at = ? AND claim_expires_at > ?
                    AND state IN ('claimed', 'deleting') AND file_identity = ?"""
                claim_values = (
                    claim.queue_id,
                    claim.storage_path,
                    claim.key_id,
                    claim.work_id,
                    claim.generation,
                    claim.claim_owner,
                    claim.claim_token,
                    claim.claim_generation,
                    _iso(claim.claim_expires_at),
                    now_value,
                    claim.file_identity,
                )
                if outcome == "failed":
                    attempt = int(row["attempt"]) + 1
                    if attempt >= max_attempts:
                        current_key_id = self._retention_key_id(
                            self._retention_hmac_keys[0]
                        )
                        conn.execute(
                            """INSERT INTO retention_key_registry (key_id, first_used_at)
                               VALUES (?, ?) ON CONFLICT(key_id) DO NOTHING""",
                            (current_key_id, now_value),
                        )
                        dead_letter_id = self._retention_attachment_digest(
                            "dead-letter",
                            claim.storage_path,
                            current_key_id,
                            claim.work_id,
                            claim.generation,
                            self._retention_hmac_keys[0],
                        )
                        dead_identity_tag = (
                            None
                            if row["file_identity"] is None
                            else self._retention_file_identity_digest(
                                "dead-letter",
                                claim.storage_path,
                                current_key_id,
                                claim.work_id,
                                claim.generation,
                                row["file_identity"],
                                self._retention_hmac_keys[0],
                            )
                        )
                        inserted = conn.execute(
                            """INSERT INTO retention_attachment_dead_letters (
                                   dead_letter_id, storage_path, key_id, work_id,
                                   generation, file_identity, file_identity_tag,
                                   attempt, last_error, quarantined_at
                               ) SELECT ?, ?, ?, ?, ?, ?, ?, ?, 'delete_failed', ?
                               WHERE NOT EXISTS (
                                   SELECT 1 FROM retention_attachment_dead_letters
                                   WHERE storage_path = ?
                               )""",
                            (
                                dead_letter_id,
                                claim.storage_path,
                                current_key_id,
                                claim.work_id,
                                claim.generation,
                                row["file_identity"],
                                dead_identity_tag,
                                attempt,
                                now_value,
                                claim.storage_path,
                            ),
                        )
                        if inserted.rowcount != 1:
                            raise StateConflictError(
                                "retention attachment dead-letter state changed"
                            )
                        deleted = conn.execute(
                            f"DELETE FROM retention_attachment_queue WHERE {claim_where}",
                            claim_values,
                        )
                        if deleted.rowcount != 1:
                            raise StateConflictError(
                                "retention attachment claim changed during quarantine"
                            )
                        counts["failed"] += 1
                        counts["quarantined"] += 1
                        continue
                    retry_at = _iso(now + timedelta(seconds=min(2**attempt, 3600)))
                    updated = conn.execute(
                        f"""UPDATE retention_attachment_queue
                            SET state = 'pending', attempt = ?,
                                last_error = 'delete_failed', next_attempt_at = ?,
                                claim_owner = NULL, claim_token = NULL,
                                claim_expires_at = NULL
                            WHERE {claim_where}""",
                        (attempt, retry_at, *claim_values),
                    )
                    if updated.rowcount != 1:
                        raise StateConflictError(
                            "retention attachment claim changed during retry"
                        )
                    counts["failed"] += 1
                else:
                    deleted = conn.execute(
                        f"DELETE FROM retention_attachment_queue WHERE {claim_where}",
                        claim_values,
                    )
                    if deleted.rowcount != 1:
                        counts["stale"] += 1
                        continue
                    counts[outcome] += 1
            conn.execute(
                """INSERT INTO runtime_audit_events (
                       audit_id, entity_kind, entity_id, action, actor_id, payload, created_at
                   ) VALUES (?, 'retention', 'runtime', 'attachment_retention',
                             'retention-worker', ?, ?)""",
                (
                    f"retention-attachments:{uuid.uuid4().hex}",
                    _json({f"attachments_{key}": counts[key] for key in sorted(counts)}),
                    now_value,
                ),
            )
        return counts

    def list_retention_attachment_dead_letters(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return only authenticated terminal attachment deletion failures."""
        _require_limit(limit)
        conn = self._conn
        with conn:
            conn.execute("BEGIN")
            self._validate_retention_key_registry(conn)
            self._assert_unambiguous_retention_attachment_state(conn)
            rows = conn.execute(
                """SELECT * FROM retention_attachment_dead_letters
                   ORDER BY quarantined_at, dead_letter_id LIMIT ?""",
                (limit,),
            ).fetchall()
            for row in rows:
                self._authenticate_retention_attachment_row(row, "dead-letter")
        return [
            {
                "dead_letter_id": row["dead_letter_id"],
                "storage_path": row["storage_path"],
                "attempt": row["attempt"],
                "last_error": row["last_error"],
                "quarantined_at": datetime.fromisoformat(row["quarantined_at"]),
            }
            for row in rows
        ]

    def requeue_retention_attachment(
        self,
        dead_letter_id: str,
        *,
        actor_id: str,
        now: datetime,
    ) -> bool:
        """Explicitly move one quarantined deletion back to the capped active queue."""
        _require_retention_digest_id(dead_letter_id, "dead_letter_id")
        _require_identifier(actor_id, "actor_id")
        now_value = _iso(now)
        conn = self._conn
        result = "not_found"
        prior_attempt: int | None = None
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_retention_key_registry(conn)
            self._assert_unambiguous_retention_attachment_state(conn)
            row = conn.execute(
                """SELECT * FROM retention_attachment_dead_letters
                   WHERE dead_letter_id = ?""",
                (dead_letter_id,),
            ).fetchone()
            if row is not None:
                self._authenticate_retention_attachment_row(row, "dead-letter")
                conn.execute(
                    """INSERT INTO retention_key_registry (key_id, first_used_at)
                       VALUES (?, ?) ON CONFLICT(key_id) DO NOTHING""",
                    (row["key_id"], now_value),
                )
                prior_attempt = int(row["attempt"])
                storage_path = row["storage_path"]
                if not self._retention_hmac_keys:
                    raise StateConflictError("retention HMAC key is unavailable")
                occupancy = conn.execute(
                    "SELECT COUNT(*) FROM retention_attachment_queue"
                ).fetchone()[0]
                if occupancy >= 64:
                    result = "capacity_full"
                else:
                    key_id, work_id, generation, queue_id = (
                        self._new_retention_attachment_identity(
                            "queue", storage_path
                        )
                    )
                    queue_identity_tag = (
                        None
                        if row["file_identity"] is None
                        else self._retention_file_identity_digest(
                            "queue",
                            storage_path,
                            key_id,
                            work_id,
                            generation,
                            row["file_identity"],
                            self._retention_hmac_keys[0],
                        )
                    )
                    conn.execute(
                        """INSERT INTO retention_key_registry (key_id, first_used_at)
                           VALUES (?, ?) ON CONFLICT(key_id) DO NOTHING""",
                        (key_id, now_value),
                    )
                    inserted = conn.execute(
                        """INSERT INTO retention_attachment_queue (
                               queue_id, storage_path, key_id, work_id, generation,
                               queued_at, next_attempt_at, file_identity,
                               file_identity_tag
                           ) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
                           WHERE EXISTS (
                               SELECT 1 FROM retention_attachment_dead_letters
                               WHERE dead_letter_id = ? AND storage_path = ?
                                 AND key_id = ? AND work_id = ? AND generation = ?
                           ) AND NOT EXISTS (
                               SELECT 1 FROM retention_attachment_queue
                               WHERE storage_path = ?
                           )""",
                        (
                            queue_id,
                            storage_path,
                            key_id,
                            work_id,
                            generation,
                            now_value,
                            now_value,
                            row["file_identity"],
                            queue_identity_tag,
                            dead_letter_id,
                            storage_path,
                            row["key_id"],
                            row["work_id"],
                            row["generation"],
                            storage_path,
                        ),
                    )
                    if inserted.rowcount != 1:
                        raise StateConflictError(
                            "retention attachment requeue state changed"
                        )
                    deleted = conn.execute(
                        """DELETE FROM retention_attachment_dead_letters
                           WHERE dead_letter_id = ? AND storage_path = ?
                             AND key_id = ? AND work_id = ? AND generation = ?""",
                        (
                            dead_letter_id,
                            storage_path,
                            row["key_id"],
                            row["work_id"],
                            row["generation"],
                        ),
                    )
                    if deleted.rowcount != 1:
                        raise StateConflictError(
                            "retention attachment dead-letter state changed"
                        )
                    result = "requeued"
            audit_payload: dict[str, Any] = {"result": result}
            if prior_attempt is not None:
                audit_payload["prior_attempt"] = prior_attempt
            conn.execute(
                """INSERT INTO runtime_audit_events (
                       audit_id, entity_kind, entity_id, action, actor_id, payload, created_at
                   ) VALUES (?, 'retention_attachment_dead_letter', ?,
                             'retention_attachment_requeue', ?, ?, ?)""",
                (
                    f"retention-requeue:{uuid.uuid4().hex}",
                    dead_letter_id,
                    actor_id,
                    _json(audit_payload),
                    now_value,
                ),
            )
        return result == "requeued"

    def secure_checkpoint(self) -> None:
        """Remove securely-deleted content from WAL before reporting retention complete."""
        for _ in range(100):
            row = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if row is not None and row[0] == 0:
                return
            time.sleep(0.01)
        raise StateConflictError("secure WAL checkpoint is busy")

    @staticmethod
    def _attachment_paths(payload: Any, *, limit: int) -> tuple[list[str], bool]:
        """Read only the exact trusted attachment container, never nested metadata."""
        if not isinstance(payload, Mapping) or "attachments" not in payload:
            return [], False
        attachments = payload["attachments"]
        if not isinstance(attachments, (list, tuple)):
            raise ValueError("attachments must be a bounded sequence")
        paths: list[str] = []
        for item in attachments:
            if not isinstance(item, Mapping):
                raise ValueError("attachment entries must be objects")
            storage_path = item.get("storage_path")
            if not isinstance(storage_path, str):
                raise ValueError("attachment storage_path is required")
            paths.append(_canonical_attachment_storage_path(storage_path))
            if len(paths) > limit:
                return paths[:limit], True
        return paths, False

    @staticmethod
    def _unsigned_attachment_source_requires_migration(payload_value: str) -> bool:
        try:
            payload = json.loads(payload_value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise StateConflictError("durable source payload is invalid") from exc
        if not isinstance(payload, Mapping) or "attachments" not in payload:
            return False
        attachments = payload["attachments"]
        return not isinstance(attachments, list) or bool(attachments)

    @staticmethod
    def _retention_attachment_source_digest(
        kind: str,
        source_id: str,
        key_id: str,
        occurrences_value: str,
        key: bytes,
    ) -> str:
        authenticated = _json(
            [
                "retention-attachment-source-v2",
                kind,
                source_id,
                key_id,
                occurrences_value,
            ]
        )
        return DurableRuntimeRepository._retention_digest_with_key(
            authenticated, key
        )

    @staticmethod
    def _retention_attachment_occurrences_value(
        occurrences: Iterable[tuple[str, str]],
    ) -> str:
        return _json(
            [
                {"storage_path": storage_path, "file_identity": file_identity}
                for storage_path, file_identity in occurrences
            ]
        )

    def _snapshot_retention_attachment_source(self, storage_path: str) -> str:
        from .retention import snapshot_managed_attachment

        identity = snapshot_managed_attachment(
            self.control_plane.data_dir / "attachments", storage_path
        )
        self._validate_retention_file_identity(identity)
        return identity

    def _retention_attachment_source_fields(
        self,
        kind: str,
        source_id: str,
        payload: Any,
    ) -> tuple[str | None, str | None, str | None]:
        paths, overflow = self._attachment_paths(payload, limit=64)
        if overflow:
            raise ValueError("attachment source exceeds the retention safety bound of 64")
        if not paths:
            return None, None, None
        if not self._retention_hmac_keys:
            raise StateConflictError(
                "attachment sources require an externally managed retention HMAC key"
            )
        occurrences = tuple(
            (storage_path, self._snapshot_retention_attachment_source(storage_path))
            for storage_path in dict.fromkeys(paths)
        )
        occurrences_value = self._retention_attachment_occurrences_value(occurrences)
        key = self._retention_hmac_keys[0]
        key_id = self._retention_key_id(key)
        tag = self._retention_attachment_source_digest(
            kind, source_id, key_id, occurrences_value, key
        )
        return occurrences_value, key_id, tag

    def _authenticate_retention_attachment_source(
        self,
        row: sqlite3.Row,
        kind: str,
        source_id_column: str,
    ) -> tuple[tuple[str, str], ...]:
        occurrences_value = row["retention_attachment_paths"]
        key_id = row["retention_attachment_key_id"]
        tag = row["retention_attachment_tag"]
        if occurrences_value is None and key_id is None and tag is None:
            return ()
        if not all(
            isinstance(value, str) and value
            for value in (occurrences_value, key_id, tag)
        ):
            raise StateConflictError(
                "retention attachment source manifest requires explicit migration"
            )
        key = self._retention_keys_by_id.get(key_id)
        if key is None:
            raise StateConflictError(
                "retention attachment source requires an unavailable historical HMAC key"
            )
        expected = self._retention_attachment_source_digest(
            kind, row[source_id_column], key_id, occurrences_value, key
        )
        if not hmac.compare_digest(tag, expected):
            raise StateConflictError(
                "retention attachment source manifest failed to authenticate"
            )
        try:
            encoded_occurrences = json.loads(occurrences_value)
        except json.JSONDecodeError as exc:
            raise StateConflictError(
                "retention attachment source manifest is invalid"
            ) from exc
        if (
            not isinstance(encoded_occurrences, list)
            or not 1 <= len(encoded_occurrences) <= 64
        ):
            raise StateConflictError("retention attachment source manifest is invalid")
        try:
            occurrences = tuple(
                (
                    _canonical_attachment_storage_path(item["storage_path"]),
                    item["file_identity"],
                )
                for item in encoded_occurrences
                if isinstance(item, dict)
                and set(item) == {"storage_path", "file_identity"}
            )
            if len(occurrences) != len(encoded_occurrences):
                raise ValueError("invalid occurrence shape")
            for _, file_identity in occurrences:
                self._validate_retention_file_identity(file_identity)
        except (KeyError, TypeError, ValueError) as exc:
            raise StateConflictError(
                "retention attachment source manifest is not canonical"
            ) from exc
        if (
            len({storage_path for storage_path, _ in occurrences}) != len(occurrences)
            or self._retention_attachment_occurrences_value(occurrences)
            != occurrences_value
        ):
            raise StateConflictError("retention attachment source manifest is invalid")
        return occurrences

    @staticmethod
    def _retention_attachment_backlog_digest(
        backlog_id: str,
        key_id: str,
        generation: str,
        occurrences_value: str,
        key: bytes,
    ) -> str:
        authenticated = _json(
            [
                "retention-attachment-backlog-v2",
                backlog_id,
                key_id,
                generation,
                occurrences_value,
            ]
        )
        return DurableRuntimeRepository._retention_digest_with_key(
            authenticated, key
        )

    def _new_retention_attachment_backlog_page(
        self, occurrences: Iterable[tuple[str, str]]
    ) -> tuple[str, str, str, str, str]:
        canonical = tuple(
            (_canonical_attachment_storage_path(storage_path), file_identity)
            for storage_path, file_identity in occurrences
        )
        for _, file_identity in canonical:
            self._validate_retention_file_identity(file_identity)
        if (
            not 1 <= len(canonical) <= 64
            or len({storage_path for storage_path, _ in canonical}) != len(canonical)
        ):
            raise ValueError("retention attachment backlog page is invalid")
        if not self._retention_hmac_keys:
            raise StateConflictError("retention HMAC key is unavailable")
        occurrences_value = self._retention_attachment_occurrences_value(canonical)
        backlog_id = f"backlog:{uuid.uuid4().hex}"
        generation = uuid.uuid4().hex
        key = self._retention_hmac_keys[0]
        key_id = self._retention_key_id(key)
        tag = self._retention_attachment_backlog_digest(
            backlog_id, key_id, generation, occurrences_value, key
        )
        return backlog_id, occurrences_value, key_id, generation, tag

    def _authenticate_retention_attachment_backlog(
        self, row: sqlite3.Row
    ) -> tuple[tuple[str, str], ...]:
        backlog_id = row["backlog_id"]
        occurrences_value = row["storage_paths"]
        key_id = row["key_id"]
        generation = row["generation"]
        tag = row["backlog_tag"]
        if not all(
            isinstance(value, str) and value
            for value in (backlog_id, occurrences_value, key_id, generation, tag)
        ):
            raise StateConflictError(
                "retention attachment backlog requires explicit migration"
            )
        key = self._retention_keys_by_id.get(key_id)
        if key is None:
            raise StateConflictError(
                "retention attachment backlog requires an unavailable historical HMAC key"
            )
        expected = self._retention_attachment_backlog_digest(
            backlog_id, key_id, generation, occurrences_value, key
        )
        if not hmac.compare_digest(tag, expected):
            raise StateConflictError(
                "retention attachment backlog failed to authenticate"
            )
        try:
            encoded_occurrences = json.loads(occurrences_value)
        except json.JSONDecodeError as exc:
            raise StateConflictError(
                "retention attachment backlog is invalid"
            ) from exc
        if (
            not isinstance(encoded_occurrences, list)
            or not 1 <= len(encoded_occurrences) <= 64
        ):
            raise StateConflictError("retention attachment backlog is invalid")
        try:
            occurrences = tuple(
                (
                    _canonical_attachment_storage_path(item["storage_path"]),
                    item["file_identity"],
                )
                for item in encoded_occurrences
                if isinstance(item, dict)
                and set(item) == {"storage_path", "file_identity"}
            )
            if len(occurrences) != len(encoded_occurrences):
                raise ValueError("invalid occurrence shape")
            for _, file_identity in occurrences:
                self._validate_retention_file_identity(file_identity)
        except (KeyError, TypeError, ValueError) as exc:
            raise StateConflictError(
                "retention attachment backlog is not canonical"
            ) from exc
        if (
            len({storage_path for storage_path, _ in occurrences}) != len(occurrences)
            or self._retention_attachment_occurrences_value(occurrences)
            != occurrences_value
        ):
            raise StateConflictError("retention attachment backlog is invalid")
        return occurrences

    @staticmethod
    def _retention_digest_with_key(value: str, key: bytes) -> str:
        return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _retention_key_id(key: bytes) -> str:
        return hashlib.sha256(key).hexdigest()[:16]

    def _retention_digest(self, value: str) -> str:
        if not self._retention_hmac_keys:
            raise StateConflictError("retention HMAC key is unavailable")
        return self._retention_digest_with_key(value, self._retention_hmac_keys[0])

    def _retention_token(self, domain: str, value: str) -> str:
        return f"retained:{self._retention_digest(f'{domain}:{value}')}"

    @staticmethod
    def _retention_attachment_digest(
        kind: str,
        storage_path: str,
        key_id: str,
        work_id: str,
        generation: str,
        key: bytes,
    ) -> str:
        authenticated = _json(
            [
                "retention-attachment-v1",
                kind,
                key_id,
                work_id,
                generation,
                storage_path,
            ]
        )
        return DurableRuntimeRepository._retention_digest_with_key(
            authenticated, key
        )

    def _new_retention_attachment_identity(
        self, kind: str, storage_path: str
    ) -> tuple[str, str, str, str]:
        if not self._retention_hmac_keys:
            raise StateConflictError("retention HMAC key is unavailable")
        key = self._retention_hmac_keys[0]
        key_id = self._retention_key_id(key)
        work_id = uuid.uuid4().hex
        generation = uuid.uuid4().hex
        digest = self._retention_attachment_digest(
            kind, storage_path, key_id, work_id, generation, key
        )
        return key_id, work_id, generation, digest

    @staticmethod
    def _retention_file_identity_digest(
        kind: str,
        storage_path: str,
        key_id: str,
        work_id: str,
        generation: str,
        file_identity: str,
        key: bytes,
    ) -> str:
        authenticated = _json(
            [
                "retention-attachment-file-v1",
                kind,
                key_id,
                work_id,
                generation,
                storage_path,
                file_identity,
            ]
        )
        return DurableRuntimeRepository._retention_digest_with_key(
            authenticated, key
        )

    def _authenticate_retention_attachment_row(
        self, row: sqlite3.Row, kind: str
    ) -> None:
        id_column = "queue_id" if kind == "queue" else "dead_letter_id"
        key_id = row["key_id"]
        work_id = row["work_id"]
        generation = row["generation"]
        identifier = row[id_column]
        try:
            canonical_path = _canonical_attachment_storage_path(row["storage_path"])
        except ValueError as exc:
            raise StateConflictError(
                "retention attachment path is not canonical"
            ) from exc
        if not all(
            isinstance(value, str) and value
            for value in (key_id, work_id, generation, canonical_path)
        ) or not isinstance(identifier, str):
            raise StateConflictError(
                "retention attachment identity requires explicit migration"
            )
        key = self._retention_keys_by_id.get(key_id)
        if key is None:
            raise StateConflictError(
                "retention attachment requires an unavailable historical HMAC key"
            )
        expected = self._retention_attachment_digest(
            kind,
            canonical_path,
            key_id,
            work_id,
            generation,
            key,
        )
        if not hmac.compare_digest(identifier, expected):
            raise StateConflictError(
                "retention attachment row failed to authenticate"
            )
        file_identity = row["file_identity"]
        file_identity_tag = row["file_identity_tag"]
        try:
            self._validate_retention_file_identity(file_identity)
        except ValueError as exc:
            raise StateConflictError(
                "retention attachment file identity requires explicit migration"
            ) from exc
        if not isinstance(file_identity_tag, str):
            raise StateConflictError(
                "retention attachment file identity failed to authenticate"
            )
        expected_tag = self._retention_file_identity_digest(
            kind,
            canonical_path,
            key_id,
            work_id,
            generation,
            file_identity,
            key,
        )
        if not hmac.compare_digest(file_identity_tag, expected_tag):
            raise StateConflictError(
                "retention attachment file identity failed to authenticate"
            )

    @staticmethod
    def _assert_unambiguous_retention_attachment_state(
        conn: sqlite3.Connection,
    ) -> None:
        paths = conn.execute(
            """SELECT storage_path FROM retention_attachment_queue
               UNION ALL
               SELECT storage_path FROM retention_attachment_dead_letters"""
        ).fetchall()
        try:
            for row in paths:
                _canonical_attachment_storage_path(row["storage_path"])
        except ValueError as exc:
            raise StateConflictError(
                "retention attachment state contains a non-canonical path"
            ) from exc
        duplicate = conn.execute(
            """SELECT storage_path FROM retention_attachment_queue
               GROUP BY storage_path HAVING COUNT(*) > 1 LIMIT 1"""
        ).fetchone()
        overlap = conn.execute(
            """SELECT q.storage_path
               FROM retention_attachment_queue AS q
               JOIN retention_attachment_dead_letters AS d
                 ON d.storage_path = q.storage_path
               LIMIT 1"""
        ).fetchone()
        if duplicate is not None or overlap is not None:
            raise StateConflictError(
                "ambiguous retention attachment active/dead state requires migration"
            )

    def _claim_due_retention_attachments(
        self,
        conn: sqlite3.Connection,
        *,
        now: datetime,
        limit: int,
        claim_owner: str,
    ) -> tuple[RetentionAttachmentClaim, ...]:
        self._assert_unambiguous_retention_attachment_state(conn)
        now_value = _iso(now)
        invalid_lease = conn.execute(
            """SELECT 1 FROM retention_attachment_queue
               WHERE state IN ('claimed', 'deleting')
                 AND claim_expires_at IS NULL LIMIT 1"""
        ).fetchone()
        if invalid_lease is not None:
            raise StateConflictError(
                "retention attachment claim lease is incomplete"
            )
        # A claim may be recovered after its lease expires only until deletion is
        # authorized.  `deleting` is a fail-closed fence: reclaiming it could let
        # the old handle delete a later same-path occurrence after requeue.
        rows = tuple(
            conn.execute(
                """SELECT * FROM retention_attachment_queue
                   WHERE (state = 'pending' AND next_attempt_at <= ?)
                      OR (state = 'claimed'
                          AND claim_expires_at <= ?)
                   ORDER BY
                       CASE WHEN state = 'pending'
                            THEN next_attempt_at ELSE claim_expires_at END,
                       queue_id
                   LIMIT ?""",
                (now_value, now_value, limit),
            ).fetchall()
        )
        for row in rows:
            self._authenticate_retention_attachment_row(row, "queue")
            conn.execute(
                """INSERT INTO retention_key_registry (key_id, first_used_at)
                   VALUES (?, ?) ON CONFLICT(key_id) DO NOTHING""",
                (row["key_id"], now_value),
            )

        expires_at = now + _RETENTION_CLAIM_TTL
        expires_value = _iso(expires_at)
        claims: list[RetentionAttachmentClaim] = []
        for row in rows:
            token = uuid.uuid4().hex
            claim_generation = int(row["claim_generation"]) + 1
            updated = conn.execute(
                """UPDATE retention_attachment_queue
                   SET state = 'claimed', claim_owner = ?, claim_token = ?,
                       claim_generation = ?, claim_expires_at = ?
                   WHERE queue_id = ? AND storage_path = ? AND key_id = ?
                      AND work_id = ? AND generation = ?
                      AND file_identity = ? AND file_identity_tag = ?
                      AND ((state = 'pending' AND next_attempt_at <= ?)
                        OR (state = 'claimed'
                           AND claim_expires_at <= ?))""",
                (
                    claim_owner,
                    token,
                    claim_generation,
                    expires_value,
                    row["queue_id"],
                    row["storage_path"],
                    row["key_id"],
                    row["work_id"],
                    row["generation"],
                    row["file_identity"],
                    row["file_identity_tag"],
                    now_value,
                    now_value,
                ),
            )
            if updated.rowcount != 1:
                raise StateConflictError(
                    "retention attachment claim compare-and-swap failed"
                )
            claims.append(
                RetentionAttachmentClaim(
                    queue_id=row["queue_id"],
                    storage_path=row["storage_path"],
                    key_id=row["key_id"],
                    work_id=row["work_id"],
                    generation=row["generation"],
                    claim_owner=claim_owner,
                    claim_token=token,
                    claim_generation=claim_generation,
                    claim_expires_at=expires_at,
                    file_identity=row["file_identity"],
                )
            )
        return tuple(claims)

    @staticmethod
    def _validate_retention_file_identity(file_identity: str) -> None:
        if (
            not isinstance(file_identity, str)
            or not file_identity
            or len(file_identity) > 512
        ):
            raise ValueError("file_identity must be a bounded non-empty string")

    @staticmethod
    def _validate_retention_attachment_claim(
        claim: RetentionAttachmentClaim,
    ) -> None:
        if not isinstance(claim, RetentionAttachmentClaim):
            raise ValueError("attachment claim is invalid")
        _require_retention_digest_id(claim.queue_id, "queue_id")
        for value, name in (
            (claim.storage_path, "storage_path"),
            (claim.key_id, "key_id"),
            (claim.work_id, "work_id"),
            (claim.generation, "generation"),
            (claim.claim_owner, "claim_owner"),
            (claim.claim_token, "claim_token"),
        ):
            _require_identifier(value, name)
        if (
            isinstance(claim.claim_generation, bool)
            or not isinstance(claim.claim_generation, int)
            or claim.claim_generation < 1
        ):
            raise ValueError("claim_generation must be positive")
        _require_aware(claim.claim_expires_at, "claim_expires_at")
        DurableRuntimeRepository._validate_retention_file_identity(
            claim.file_identity
        )

    @staticmethod
    def _retention_claim_matches_row(
        claim: RetentionAttachmentClaim,
        row: sqlite3.Row,
        *,
        now_value: str,
    ) -> bool:
        claim_expires_at = _iso(claim.claim_expires_at)
        return (
            row["queue_id"] == claim.queue_id
            and row["storage_path"] == claim.storage_path
            and row["key_id"] == claim.key_id
            and row["work_id"] == claim.work_id
            and row["generation"] == claim.generation
            and row["claim_owner"] == claim.claim_owner
            and row["claim_token"] == claim.claim_token
            and int(row["claim_generation"]) == claim.claim_generation
            and row["claim_expires_at"] == claim_expires_at
            and row["claim_expires_at"] > now_value
            and row["state"] in {"claimed", "deleting"}
            and row["file_identity"] == claim.file_identity
        )

    def _migrate_retention_attachment_rows(self) -> None:
        """Authenticate legacy IDs, then assign versioned identities atomically."""
        conn = self._conn
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_retention_key_registry(conn)
            self._assert_unambiguous_retention_attachment_state(conn)
            for kind, table, source_id_column in (
                ("inbox", "inbox_events", "event_id"),
                ("outbox", "outbox_obligations", "obligation_id"),
            ):
                for source_row in conn.execute(f"SELECT * FROM {table}").fetchall():
                    source_fields = (
                        source_row["retention_attachment_paths"],
                        source_row["retention_attachment_key_id"],
                        source_row["retention_attachment_tag"],
                    )
                    if all(value is None for value in source_fields):
                        if self._unsigned_attachment_source_requires_migration(
                            source_row["payload"]
                        ):
                            raise StateConflictError(
                                f"unsigned {kind} attachment source requires explicit migration"
                            )
                        continue
                    self._authenticate_retention_attachment_source(
                        source_row, kind, source_id_column
                    )
            for backlog_row in conn.execute(
                "SELECT * FROM retention_attachment_backlog"
            ).fetchall():
                self._authenticate_retention_attachment_backlog(backlog_row)
            for kind, table in (
                ("queue", "retention_attachment_queue"),
                ("dead-letter", "retention_attachment_dead_letters"),
            ):
                rows = tuple(conn.execute(f"SELECT * FROM {table}").fetchall())
                for row in rows:
                    if row["file_identity"] is None or row["file_identity_tag"] is None:
                        raise StateConflictError(
                            "retention attachment immutable identity requires explicit migration"
                        )
                    identity = (row["key_id"], row["work_id"], row["generation"])
                    if not all(value is not None for value in identity):
                        raise StateConflictError(
                            "retention attachment identity requires explicit migration"
                        )
                    self._authenticate_retention_attachment_row(row, kind)
            self._assert_unambiguous_retention_attachment_state(conn)
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_attachment_queue_unique_path
                   ON retention_attachment_queue(storage_path)"""
            )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_attachment_queue_unique_work
                   ON retention_attachment_queue(work_id)"""
            )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_attachment_dead_unique_work
                   ON retention_attachment_dead_letters(work_id)"""
            )

    def _validate_retention_key_registry(self, conn: sqlite3.Connection) -> None:
        stored_key_ids = {
            row[0]
            for row in conn.execute(
                "SELECT key_id FROM retention_key_registry LIMIT 9"
            ).fetchall()
        }
        configured_key_ids = {
            self._retention_key_id(key) for key in self._retention_hmac_keys
        }
        if not stored_key_ids <= configured_key_ids:
            raise StateConflictError(
                "retention tombstones require unavailable historical HMAC keys"
            )

    def _find_retention_tombstone(
        self,
        conn: sqlite3.Connection,
        entity_kind: str,
        scope: str,
        idempotency_key: str,
    ) -> sqlite3.Row | None:
        self._validate_retention_key_registry(conn)
        if not self._retention_hmac_keys:
            existing = conn.execute(
                "SELECT 1 FROM runtime_retention_tombstones LIMIT 1"
            ).fetchone()
            if existing is not None:
                raise StateConflictError("retention HMAC key is required to verify tombstones")
            return None
        for key in self._retention_hmac_keys:
            row = conn.execute(
                """SELECT record_id FROM runtime_retention_tombstones
                   WHERE entity_kind = ? AND scope_digest = ?
                     AND idempotency_digest = ?""",
                (
                    entity_kind,
                    self._retention_digest_with_key(scope, key),
                    self._retention_digest_with_key(idempotency_key, key),
                ),
            ).fetchone()
            if row is not None:
                return row
        return None

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
        state_predicate = (
            "state IN ('claimed', 'dispatched')" if kind == "inbox" else "state = ?"
        )
        state_values: tuple[str, ...] = () if kind == "inbox" else (active_state,)
        conn = self._conn
        with conn:
            row = conn.execute(
                f"""
                UPDATE {table}
                SET claim_expires_at = ?, updated_at = ?
                WHERE {id_column} = ? AND {state_predicate}
                  AND claim_owner = ? AND claim_generation = ?
                  AND claim_expires_at = ? AND claim_expires_at > ?
                RETURNING claim_owner, claim_generation, claim_expires_at
                """,
                (
                    _iso(expires_at),
                    _iso(now),
                    record_id,
                    *state_values,
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
