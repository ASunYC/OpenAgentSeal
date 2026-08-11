"""Durable local control plane for agent runtime state."""

import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from open_agent.utils.path_utils import get_data_dir


class ControlPlane:
    """SQLite-backed store for sessions, goals, tool calls, jobs, and metadata."""

    DB_FILE = "runtime.db"
    _schema_lock = threading.Lock()

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / self.DB_FILE
        self._migrate_legacy_db()
        self._local = threading.local()
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        with self._schema_lock:
            self._init_db()

    def _migrate_legacy_db(self) -> None:
        legacy_paths = [
            self.data_dir / "control_plane.db",
            get_data_dir() / "control_plane.db",
            Path.home() / ".open-agent" / "control_plane.db",
        ]
        legacy_path = next((path for path in legacy_paths if path.exists()), None)
        if self.db_path.exists() or legacy_path is None:
            return
        shutil.copy2(legacy_path, self.db_path)
        for suffix in ("-wal", "-shm"):
            legacy_sidecar = Path(str(legacy_path) + suffix)
            if legacy_sidecar.exists():
                shutil.copy2(legacy_sidecar, Path(str(self.db_path) + suffix))

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA secure_delete=ON")
            self._local.conn = conn
            with self._connections_lock:
                self._connections.add(conn)
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL DEFAULT 'unknown',
                    user_id TEXT NOT NULL DEFAULT 'default',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS runtime_threads (
                    thread_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    latest_event_seq INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS runtime_turns (
                    turn_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    user_input TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    result TEXT,
                    error TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(thread_id) REFERENCES runtime_threads(thread_id) ON DELETE CASCADE,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS runtime_events (
                    event_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    turn_id TEXT,
                    session_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(thread_id, seq),
                    FOREIGN KEY(thread_id) REFERENCES runtime_threads(thread_id) ON DELETE CASCADE,
                    FOREIGN KEY(turn_id) REFERENCES runtime_turns(turn_id) ON DELETE SET NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS goals (
                    goal_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    goal_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    plan TEXT NOT NULL DEFAULT '',
                    active_step TEXT NOT NULL DEFAULT '',
                    todo_items TEXT NOT NULL DEFAULT '[]',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_judge_result TEXT NOT NULL DEFAULT '{}',
                    resume_token TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS goal_steps (
                    step_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    tool_call_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    goal_id TEXT,
                    tool_name TEXT NOT NULL,
                    arguments TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    success INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                    FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    goal_id TEXT,
                    request_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload TEXT NOT NULL DEFAULT '{}',
                    decision TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                    FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS scheduler_jobs (
                    job_id TEXT PRIMARY KEY,
                    goal_id TEXT,
                    schedule TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    next_run_at TEXT,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    goal_id TEXT,
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'file',
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                    FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    parent_session_id TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    instruction TEXT NOT NULL DEFAULT '',
                    result TEXT,
                    error TEXT,
                    events TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS metadata (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(namespace, key)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_runtime_threads_session_updated ON runtime_threads(session_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_runtime_turns_thread_started ON runtime_turns(thread_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_runtime_events_thread_seq ON runtime_events(thread_id, seq);
                CREATE INDEX IF NOT EXISTS idx_goals_session_status ON goals(session_id, status);
                CREATE INDEX IF NOT EXISTS idx_tool_calls_session_created ON tool_calls(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_status_next_run ON scheduler_jobs(status, next_run_at);
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_profile_updated ON agent_tasks(profile_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_parent_updated ON agent_tasks(parent_session_id, updated_at);
                """
            )
            self._migrate_durable_runtime_schema(conn)

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
        column = definition.split(maxsplit=1)[0]
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            except sqlite3.OperationalError:
                refreshed = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column not in refreshed:
                    raise

    def _migrate_durable_runtime_schema(self, conn: sqlite3.Connection) -> None:
        """Add durable-runtime storage without replacing existing control-plane data."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS channel_accounts (
                account_id TEXT PRIMARY KEY,
                adapter_kind TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                credential_ref TEXT,
                default_profile_id TEXT,
                capabilities TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS channel_routes (
                route_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                sender_id TEXT NOT NULL DEFAULT '',
                profile_id TEXT,
                trigger_policy TEXT NOT NULL DEFAULT 'default',
                session_id TEXT,
                thread_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                UNIQUE(account_id, conversation_id, sender_id),
                FOREIGN KEY(account_id) REFERENCES channel_accounts(account_id) ON DELETE CASCADE,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE SET NULL,
                FOREIGN KEY(thread_id) REFERENCES runtime_threads(thread_id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS channel_ingress_checkpoints (
                account_id TEXT NOT NULL,
                transport_mode TEXT NOT NULL,
                cursor TEXT,
                gateway_session_id TEXT,
                gateway_sequence INTEGER,
                replay_state TEXT NOT NULL DEFAULT '{}',
                claim_owner TEXT,
                claim_generation INTEGER NOT NULL DEFAULT 0,
                claim_expires_at TEXT,
                reconnect_metadata TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(account_id, transport_mode),
                FOREIGN KEY(account_id) REFERENCES channel_accounts(account_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS inbox_events (
                event_id TEXT PRIMARY KEY,
                event_key TEXT NOT NULL,
                account_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                attempt INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                claim_owner TEXT,
                claim_generation INTEGER NOT NULL DEFAULT 0,
                claim_expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                retained_at TEXT,
                UNIQUE(account_id, event_key)
            );

            CREATE TABLE IF NOT EXISTS outbox_obligations (
                obligation_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL,
                destination TEXT NOT NULL,
                payload TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                attempt INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                acknowledgement TEXT,
                claim_owner TEXT,
                claim_generation INTEGER NOT NULL DEFAULT 0,
                claim_expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                retained_at TEXT,
                UNIQUE(destination, idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS scheduler_runs (
                run_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                attempt INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                claim_owner TEXT,
                claim_generation INTEGER NOT NULL DEFAULT 0,
                claim_expires_at TEXT,
                turn_id TEXT,
                goal_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job_id, scheduled_at),
                FOREIGN KEY(job_id) REFERENCES scheduler_jobs(job_id) ON DELETE CASCADE,
                FOREIGN KEY(turn_id) REFERENCES runtime_turns(turn_id) ON DELETE SET NULL,
                FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS goal_iterations (
                iteration_id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                claim_owner TEXT,
                claim_generation INTEGER NOT NULL DEFAULT 0,
                claim_expires_at TEXT,
                turn_id TEXT,
                judge_result TEXT,
                budget_delta TEXT NOT NULL DEFAULT '{}',
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(goal_id, sequence),
                FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE,
                FOREIGN KEY(turn_id) REFERENCES runtime_turns(turn_id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_audit_events (
                audit_id TEXT PRIMARY KEY,
                entity_kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_id TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_retention_tombstones (
                entity_kind TEXT NOT NULL,
                scope_digest TEXT NOT NULL,
                idempotency_digest TEXT NOT NULL,
                key_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                terminal_state TEXT NOT NULL,
                retained_at TEXT NOT NULL,
                PRIMARY KEY(entity_kind, scope_digest, idempotency_digest)
            );

            CREATE TABLE IF NOT EXISTS retention_key_registry (
                key_id TEXT PRIMARY KEY,
                first_used_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS retention_attachment_queue (
                queue_id TEXT PRIMARY KEY,
                storage_path TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS retention_attachment_backlog (
                backlog_id TEXT PRIMARY KEY,
                storage_paths TEXT NOT NULL,
                queued_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS retention_attachment_dead_letters (
                dead_letter_id TEXT PRIMARY KEY,
                storage_path TEXT NOT NULL UNIQUE,
                attempt INTEGER NOT NULL,
                last_error TEXT NOT NULL,
                quarantined_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_inbox_state_due
                ON inbox_events(state, next_attempt_at, created_at);
            CREATE INDEX IF NOT EXISTS idx_outbox_state_due
                ON outbox_obligations(state, next_attempt_at, created_at);
            CREATE INDEX IF NOT EXISTS idx_scheduler_runs_job_scheduled
                ON scheduler_runs(job_id, scheduled_at);
            CREATE INDEX IF NOT EXISTS idx_goal_iterations_goal_sequence
                ON goal_iterations(goal_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_runtime_audit_entity_created
                ON runtime_audit_events(entity_kind, entity_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_runtime_audit_retention
                ON runtime_audit_events(created_at, audit_id);
            """
        )

        goal_columns = (
            "acceptance_criteria TEXT NOT NULL DEFAULT '[]'",
            "judge_schema_version TEXT NOT NULL DEFAULT '1'",
            "judge_prompt_version TEXT NOT NULL DEFAULT '1'",
            "judge_confidence_threshold REAL NOT NULL DEFAULT 1.0",
            "max_iterations INTEGER",
            "max_tokens INTEGER",
            "max_estimated_cost REAL",
            "max_wall_clock_seconds REAL",
            "consumed_iterations INTEGER NOT NULL DEFAULT 0",
            "consumed_tokens INTEGER NOT NULL DEFAULT 0",
            "consumed_estimated_cost REAL NOT NULL DEFAULT 0",
            "consumed_active_seconds REAL NOT NULL DEFAULT 0",
            "active_started_at TEXT",
            "last_guidance_sequence INTEGER NOT NULL DEFAULT 0",
            "runtime_version INTEGER NOT NULL DEFAULT 0",
        )
        scheduler_columns = (
            "timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai'",
            "max_retries INTEGER NOT NULL DEFAULT 5",
            "misfire_policy TEXT NOT NULL DEFAULT 'latest'",
            "overlap_policy TEXT NOT NULL DEFAULT 'skip'",
            "destination TEXT",
            "runtime_version INTEGER NOT NULL DEFAULT 0",
        )
        for definition in goal_columns:
            self._ensure_column(conn, "goals", definition)
        for definition in scheduler_columns:
            self._ensure_column(conn, "scheduler_jobs", definition)
        self._ensure_column(conn, "inbox_events", "retained_at TEXT")
        self._ensure_column(conn, "outbox_obligations", "retained_at TEXT")
        self._ensure_column(conn, "runtime_retention_tombstones", "key_id TEXT")
        self._ensure_column(conn, "retention_attachment_queue", "next_attempt_at TEXT")
        conn.execute(
            """UPDATE retention_attachment_queue SET next_attempt_at = queued_at
               WHERE next_attempt_at IS NULL"""
        )
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_inbox_retention_due
                ON inbox_events(retained_at, updated_at, event_id)
                WHERE state IN ('succeeded', 'dead_letter');
            CREATE INDEX IF NOT EXISTS idx_outbox_retention_due
                ON outbox_obligations(
                    retained_at, updated_at, obligation_id
                )
                WHERE state IN ('acknowledged', 'dead_letter', 'delivery_unknown');
            CREATE INDEX IF NOT EXISTS idx_attachment_retention_due
                ON retention_attachment_queue(next_attempt_at, queue_id);
            CREATE INDEX IF NOT EXISTS idx_attachment_dead_letter_time
                ON retention_attachment_dead_letters(quarantined_at, dead_letter_id);
            CREATE INDEX IF NOT EXISTS idx_retention_tombstone_key_id
                ON runtime_retention_tombstones(key_id);
            """
        )
        self._ensure_column(conn, "runtime_turns", "source_event_key TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_turns_source_event_key
            ON runtime_turns(source_event_key) WHERE source_event_key IS NOT NULL
            """
        )

    def close(self) -> None:
        with self._connections_lock:
            connections = list(self._connections)
            self._connections.clear()
        for conn in connections:
            conn.close()
        if hasattr(self._local, "conn"):
            del self._local.conn

    def create_session(
        self,
        session_id: str | None = None,
        channel: str = "unknown",
        user_id: str = "default",
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, channel, user_id, status, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    channel=excluded.channel,
                    user_id=excluded.user_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    metadata=excluded.metadata
                """,
                (session_id, channel, user_id, status, now, now, metadata_json),
            )
        return self.get_session(session_id) or {}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.get_session(session_id) is None:
            self.create_session(session_id=session_id)
        now = datetime.now().isoformat()
        message_id = message_id or f"msg_{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO messages (message_id, session_id, role, content, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
        return self._row_to_dict(conn.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,)).fetchone())

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, message_id",
            (session_id,),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def create_runtime_thread(
        self,
        session_id: str | None = None,
        user_id: str = "default",
        title: str = "",
        status: str = "active",
        thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        if self.get_session(session_id) is None:
            self.create_session(session_id=session_id, channel="web", user_id=user_id)

        now = datetime.now().isoformat()
        thread_id = thread_id or f"thread_{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO runtime_threads (
                    thread_id, session_id, user_id, title, status, created_at, updated_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    user_id=excluded.user_id,
                    title=excluded.title,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    metadata=excluded.metadata
                """,
                (
                    thread_id,
                    session_id,
                    user_id,
                    title,
                    status,
                    now,
                    now,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return self.get_runtime_thread(thread_id) or {}

    def get_runtime_thread(self, thread_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM runtime_threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_runtime_thread_by_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            """
            SELECT * FROM runtime_threads
            WHERE session_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_runtime_threads(
        self,
        user_id: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if user_id:
            clauses.append("user_id = ?")
            values.append(user_id)
        if not include_archived:
            clauses.append("status != 'archived'")
        query = "SELECT * FROM runtime_threads"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        values.append(limit)
        rows = self._get_conn().execute(query, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def start_runtime_turn(
        self,
        thread_id: str,
        session_id: str | None = None,
        user_input: str = "",
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thread = self.get_runtime_thread(thread_id)
        if thread is None:
            raise KeyError(f"Runtime thread not found: {thread_id}")

        session_id = session_id or thread["session_id"]
        if self.get_session(session_id) is None:
            self.create_session(session_id=session_id)

        now = datetime.now().isoformat()
        turn_id = turn_id or f"turn_{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO runtime_turns (
                    turn_id, thread_id, session_id, user_input, status, started_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    thread_id,
                    session_id,
                    user_input,
                    "running",
                    now,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            conn.execute(
                "UPDATE runtime_threads SET status = ?, updated_at = ? WHERE thread_id = ?",
                ("active", now, thread_id),
            )
        row = conn.execute("SELECT * FROM runtime_turns WHERE turn_id = ?", (turn_id,)).fetchone()
        return self._row_to_dict(row)

    def complete_runtime_turn(
        self,
        turn_id: str,
        status: str = "completed",
        result: Any = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        conn = self._get_conn()
        current = conn.execute("SELECT * FROM runtime_turns WHERE turn_id = ?", (turn_id,)).fetchone()
        if current is None:
            raise KeyError(f"Runtime turn not found: {turn_id}")

        metadata_value = json.dumps(metadata, ensure_ascii=False) if metadata is not None else current["metadata"]
        with conn:
            conn.execute(
                """
                UPDATE runtime_turns
                SET status = ?, result = ?, error = ?, completed_at = ?, metadata = ?
                WHERE turn_id = ?
                """,
                (
                    status,
                    json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                    error,
                    now,
                    metadata_value,
                    turn_id,
                ),
            )
            conn.execute(
                "UPDATE runtime_threads SET updated_at = ? WHERE thread_id = ?",
                (now, current["thread_id"]),
            )
        row = conn.execute("SELECT * FROM runtime_turns WHERE turn_id = ?", (turn_id,)).fetchone()
        return self._row_to_dict(row)

    def append_runtime_event(
        self,
        thread_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        turn_id: str | None = None,
        session_id: str | None = None,
        event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thread = self.get_runtime_thread(thread_id)
        if thread is None:
            raise KeyError(f"Runtime thread not found: {thread_id}")

        session_id = session_id or thread["session_id"]
        now = datetime.now().isoformat()
        event_id = event_id or f"event_{uuid.uuid4().hex[:8]}"
        seq = int(thread["latest_event_seq"]) + 1
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO runtime_events (
                    event_id, thread_id, turn_id, session_id, seq, event_type, payload, created_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    thread_id,
                    turn_id,
                    session_id,
                    seq,
                    event_type,
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                    now,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                UPDATE runtime_threads
                SET latest_event_seq = ?, updated_at = ?
                WHERE thread_id = ?
                """,
                (seq, now, thread_id),
            )
        row = conn.execute("SELECT * FROM runtime_events WHERE event_id = ?", (event_id,)).fetchone()
        return self._row_to_dict(row)

    def list_runtime_events(
        self,
        thread_id: str,
        since_seq: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            """
            SELECT * FROM runtime_events
            WHERE thread_id = ? AND seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (thread_id, since_seq, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_runtime_turns(self, thread_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            """
            SELECT * FROM runtime_turns
            WHERE thread_id = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (thread_id, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def create_goal(
        self,
        session_id: str,
        goal_text: str,
        goal_id: str | None = None,
        status: str = "draft",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.get_session(session_id) is None:
            self.create_session(session_id=session_id)
        now = datetime.now().isoformat()
        goal_id = goal_id or f"goal_{uuid.uuid4().hex[:8]}"
        resume_token = f"resume_{uuid.uuid4().hex}"
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO goals (goal_id, session_id, goal_text, status, resume_token, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (goal_id, session_id, goal_text, status, resume_token, now, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
        return self.get_goal(goal_id) or {}

    def update_goal(self, goal_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"status", "plan", "active_step", "todo_items", "attempt_count", "last_judge_result", "metadata"}
        updates: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Unsupported goal field: {key}")
            if key in {"todo_items", "last_judge_result", "metadata"}:
                value = json.dumps(value, ensure_ascii=False)
            updates.append(f"{key} = ?")
            values.append(value)
        updates.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        updates.append("runtime_version = runtime_version + 1")
        values.append(goal_id)
        conn = self._get_conn()
        with conn:
            conn.execute(f"UPDATE goals SET {', '.join(updates)} WHERE goal_id = ?", values)
        goal = self.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal not found: {goal_id}")
        return goal

    def get_goal(self, goal_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_goals(self, session_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM goals"
        clauses: list[str] = []
        values: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            values.append(session_id)
        if status:
            clauses.append("status = ?")
            values.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC"
        rows = self._get_conn().execute(query, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        goal_id: str | None = None,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.get_session(session_id) is None:
            self.create_session(session_id=session_id)
        now = datetime.now().isoformat()
        tool_call_id = tool_call_id or f"tool_{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO tool_calls (tool_call_id, session_id, goal_id, tool_name, arguments, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_call_id,
                    session_id,
                    goal_id,
                    tool_name,
                    json.dumps(arguments or {}, ensure_ascii=False),
                    now,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return self._row_to_dict(conn.execute("SELECT * FROM tool_calls WHERE tool_call_id = ?", (tool_call_id,)).fetchone())

    def complete_tool_call(
        self,
        tool_call_id: str,
        success: bool,
        result: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                UPDATE tool_calls
                SET success = ?, result = ?, error = ?, completed_at = ?
                WHERE tool_call_id = ?
                """,
                (1 if success else 0, json.dumps(result, ensure_ascii=False), error, now, tool_call_id),
            )
        row = conn.execute("SELECT * FROM tool_calls WHERE tool_call_id = ?", (tool_call_id,)).fetchone()
        if row is None:
            raise KeyError(f"Tool call not found: {tool_call_id}")
        return self._row_to_dict(row)

    def create_scheduler_job(
        self,
        schedule: str,
        prompt: str,
        goal_id: str | None = None,
        job_id: str | None = None,
        next_run_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        job_id = job_id or f"job_{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO scheduler_jobs (job_id, goal_id, schedule, prompt, next_run_at, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, goal_id, schedule, prompt, next_run_at, now, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
        return self._row_to_dict(conn.execute("SELECT * FROM scheduler_jobs WHERE job_id = ?", (job_id,)).fetchone())

    def update_scheduler_job_status(self, job_id: str, status: str) -> dict[str, Any]:
        now = datetime.now().isoformat()
        conn = self._get_conn()
        with conn:
            conn.execute(
                "UPDATE scheduler_jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (status, now, job_id),
            )
        row = conn.execute("SELECT * FROM scheduler_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Scheduler job not found: {job_id}")
        return self._row_to_dict(row)

    def list_scheduler_jobs(self, session_id: str | None = None) -> list[dict[str, Any]]:
        if session_id is None:
            rows = self._get_conn().execute("SELECT * FROM scheduler_jobs ORDER BY updated_at DESC").fetchall()
        else:
            rows = self._get_conn().execute(
                """
                SELECT scheduler_jobs.*
                FROM scheduler_jobs
                JOIN goals ON scheduler_jobs.goal_id = goals.goal_id
                WHERE goals.session_id = ?
                ORDER BY scheduler_jobs.updated_at DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def set_meta(self, namespace: str, key: str, value: Any) -> None:
        now = datetime.now().isoformat()
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO metadata (namespace, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (namespace, key, json.dumps(value, ensure_ascii=False), now),
            )

    def get_meta(self, namespace: str, key: str, default: Any = None) -> Any:
        row = self._get_conn().execute(
            "SELECT value FROM metadata WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        return json.loads(row["value"]) if row else default

    def upsert_agent_task(
        self,
        task_id: str,
        profile_id: str,
        session_id: str,
        instruction: str = "",
        parent_session_id: str | None = None,
        status: str = "queued",
        result: str | None = None,
        error: str | None = None,
        events: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        if self.get_session(session_id) is None:
            self.create_session(session_id=session_id, channel="agent-task", metadata={"profile_id": profile_id})
        now = datetime.now().isoformat()
        existing = self.get_agent_task(task_id)
        created_at = existing["created_at"] if existing else now
        if completed_at is None and status in {"completed", "failed", "cancelled"}:
            completed_at = existing.get("completed_at") if existing else now
        if events is None:
            events = existing.get("events", []) if existing else []
        if metadata is None:
            metadata = existing.get("metadata", {}) if existing else {}
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, profile_id, session_id, parent_session_id, status, instruction,
                    result, error, events, created_at, updated_at, completed_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    completed_at=excluded.completed_at,
                    metadata=excluded.metadata
                """,
                (
                    task_id,
                    profile_id,
                    session_id,
                    parent_session_id,
                    status,
                    instruction,
                    result,
                    error,
                    json.dumps(events, ensure_ascii=False),
                    created_at,
                    now,
                    completed_at,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return self.get_agent_task(task_id) or {}

    def get_agent_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM agent_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_agent_tasks(
        self,
        profile_id: str | None = None,
        parent_session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if profile_id:
            clauses.append("profile_id = ?")
            params.append(profile_id)
        if parent_session_id:
            clauses.append("parent_session_id = ?")
            params.append(parent_session_id)
        query = "SELECT * FROM agent_tasks"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self._get_conn().execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("metadata", "todo_items", "last_judge_result", "arguments", "result", "payload", "decision", "events"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = json.loads(data[key])
                except json.JSONDecodeError:
                    pass
        if "success" in data and data["success"] is not None:
            data["success"] = bool(data["success"])
        return data


_control_plane: ControlPlane | None = None
_control_planes: dict[str, ControlPlane] = {}


def get_control_plane(data_dir: str | Path | None = None) -> ControlPlane:
    global _control_plane
    if data_dir is not None:
        key = str(Path(data_dir).resolve())
        if key not in _control_planes:
            _control_planes[key] = ControlPlane(data_dir=data_dir)
        return _control_planes[key]

    if _control_plane is None:
        _control_plane = ControlPlane(data_dir=data_dir)
    return _control_plane
