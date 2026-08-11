"""Durable local control plane for agent runtime state."""

import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
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
                retention_attachment_paths TEXT,
                retention_attachment_key_id TEXT,
                retention_attachment_tag TEXT,
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
                retention_attachment_paths TEXT,
                retention_attachment_key_id TEXT,
                retention_attachment_tag TEXT,
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
                key_id TEXT NOT NULL,
                work_id TEXT NOT NULL UNIQUE,
                generation TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                queued_at TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT,
                claim_owner TEXT,
                claim_token TEXT,
                claim_generation INTEGER NOT NULL DEFAULT 0,
                claim_expires_at TEXT,
                file_identity TEXT NOT NULL,
                file_identity_tag TEXT NOT NULL,
                tenant_id TEXT,
                owner_actor_id TEXT
            );

            CREATE TABLE IF NOT EXISTS retention_attachment_backlog (
                backlog_id TEXT PRIMARY KEY,
                storage_paths TEXT NOT NULL,
                key_id TEXT NOT NULL,
                generation TEXT NOT NULL,
                backlog_tag TEXT NOT NULL,
                queued_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS retention_attachment_dead_letters (
                dead_letter_id TEXT PRIMARY KEY,
                storage_path TEXT NOT NULL UNIQUE,
                key_id TEXT NOT NULL,
                work_id TEXT NOT NULL UNIQUE,
                generation TEXT NOT NULL,
                file_identity TEXT NOT NULL,
                file_identity_tag TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                last_error TEXT NOT NULL,
                quarantined_at TEXT NOT NULL,
                tenant_id TEXT,
                owner_actor_id TEXT
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
            CREATE TABLE IF NOT EXISTS runtime_operational_ownership (
                entity_kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                owner_actor_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(entity_kind, entity_id)
            );
            CREATE INDEX IF NOT EXISTS idx_runtime_operational_owner
                ON runtime_operational_ownership(
                    tenant_id, owner_actor_id, entity_kind, entity_id
                );
            CREATE TABLE IF NOT EXISTS runtime_retention_requests (
                request_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                owner_actor_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS runtime_retention_policy (
                tenant_id TEXT PRIMARY KEY,
                inbox_days INTEGER NOT NULL,
                outbox_days INTEGER NOT NULL,
                audit_days INTEGER NOT NULL,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_credential_cleanup (
                cleanup_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                credential_ref TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                completed_at TEXT,
                last_error TEXT
            );
            """
        )
        for definition in (
            "attempt INTEGER NOT NULL DEFAULT 0",
            "next_attempt_at TEXT",
        ):
            self._ensure_column(conn, "goal_iterations", definition)

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
            "pricing_version TEXT",
            "pricing_currency TEXT",
            "pricing_cost_per_token REAL",
            "transient_failure_count INTEGER NOT NULL DEFAULT 0",
            "terminal_destination TEXT",
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
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS goal_guidance (
                goal_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(goal_id, sequence),
                FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS goal_operator_approvals (
                approval_id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                issuer_id TEXT NOT NULL,
                issuer_tenant_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                expected_goal_version INTEGER NOT NULL,
                approved_budget_updates TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                consumer_id TEXT,
                FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_goal_operator_approval_lookup
                ON goal_operator_approvals(goal_id, principal_id, decision, consumed_at);
            """
        )
        for definition in (
            "tenant_id TEXT NOT NULL DEFAULT ''",
            "issuer_id TEXT NOT NULL DEFAULT ''",
            "issuer_tenant_id TEXT NOT NULL DEFAULT ''",
            "expected_goal_version INTEGER NOT NULL DEFAULT 0",
            "approved_budget_updates TEXT NOT NULL DEFAULT '{}'",
            "expires_at TEXT NOT NULL DEFAULT ''",
            "consumer_id TEXT",
        ):
            self._ensure_column(conn, "goal_operator_approvals", definition)
        for definition in scheduler_columns:
            self._ensure_column(conn, "scheduler_jobs", definition)
        migration = conn.execute(
            """SELECT 1 FROM metadata
               WHERE namespace = 'migrations' AND key = 'scheduler_cursor_utc_v1'"""
        ).fetchone()
        if migration is None:
            # CAS prevents a concurrent worker advance from being overwritten by
            # a second process performing this one-time legacy normalization.
            for scheduler_row in conn.execute(
                "SELECT job_id, next_run_at FROM scheduler_jobs WHERE next_run_at IS NOT NULL"
            ).fetchall():
                raw_cursor = scheduler_row["next_run_at"]
                try:
                    normalized = raw_cursor[:-1] + "+00:00" if raw_cursor.endswith("Z") else raw_cursor
                    parsed_cursor = datetime.fromisoformat(normalized)
                    if parsed_cursor.tzinfo is None or parsed_cursor.utcoffset() is None:
                        raise ValueError("naive scheduler cursor")
                except (AttributeError, TypeError, ValueError):
                    conn.execute(
                        """UPDATE scheduler_jobs SET status = 'paused'
                           WHERE job_id = ? AND next_run_at = ?""",
                        (scheduler_row["job_id"], raw_cursor),
                    )
                else:
                    conn.execute(
                        """UPDATE scheduler_jobs SET next_run_at = ?
                           WHERE job_id = ? AND next_run_at = ?""",
                        (
                            parsed_cursor.astimezone(timezone.utc).isoformat(),
                            scheduler_row["job_id"],
                            raw_cursor,
                        ),
                    )
            conn.execute(
                """INSERT INTO metadata (namespace, key, value, updated_at)
                   VALUES ('migrations', 'scheduler_cursor_utc_v1', 'true', ?)
                   ON CONFLICT(namespace, key) DO NOTHING""",
                (datetime.now(timezone.utc).isoformat(),),
            )
        self._ensure_column(conn, "inbox_events", "retained_at TEXT")
        self._ensure_column(conn, "outbox_obligations", "retained_at TEXT")
        for table in ("inbox_events", "outbox_obligations"):
            for definition in (
                "retention_attachment_paths TEXT",
                "retention_attachment_key_id TEXT",
                "retention_attachment_tag TEXT",
            ):
                self._ensure_column(conn, table, definition)
        self._ensure_column(conn, "runtime_retention_tombstones", "key_id TEXT")
        self._ensure_column(conn, "retention_attachment_queue", "next_attempt_at TEXT")
        for definition in (
            "key_id TEXT",
            "work_id TEXT",
            "generation TEXT",
            "state TEXT NOT NULL DEFAULT 'pending'",
            "claim_owner TEXT",
            "claim_token TEXT",
            "claim_generation INTEGER NOT NULL DEFAULT 0",
            "claim_expires_at TEXT",
            "file_identity TEXT",
            "file_identity_tag TEXT",
            "tenant_id TEXT",
            "owner_actor_id TEXT",
        ):
            self._ensure_column(conn, "retention_attachment_queue", definition)
        for definition in (
            "key_id TEXT",
            "work_id TEXT",
            "generation TEXT",
            "file_identity TEXT",
            "file_identity_tag TEXT",
            "tenant_id TEXT",
            "owner_actor_id TEXT",
        ):
            self._ensure_column(
                conn, "retention_attachment_dead_letters", definition
            )
        for definition in (
            "key_id TEXT",
            "generation TEXT",
            "backlog_tag TEXT",
        ):
            self._ensure_column(conn, "retention_attachment_backlog", definition)
        conn.execute(
            """UPDATE retention_attachment_queue SET next_attempt_at = queued_at
               WHERE next_attempt_at IS NULL"""
        )
        conn.execute("DROP INDEX IF EXISTS idx_attachment_retention_due")
        conn.execute("DROP INDEX IF EXISTS idx_attachment_retention_work")
        conn.execute("DROP INDEX IF EXISTS idx_attachment_dead_letter_work")
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
                ON retention_attachment_queue(
                    state, next_attempt_at, claim_expires_at, queue_id
                );
            CREATE INDEX IF NOT EXISTS idx_attachment_retention_path
                ON retention_attachment_queue(storage_path);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_attachment_retention_work
                ON retention_attachment_queue(work_id);
            CREATE INDEX IF NOT EXISTS idx_attachment_dead_letter_time
                ON retention_attachment_dead_letters(quarantined_at, dead_letter_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_attachment_dead_letter_work
                ON retention_attachment_dead_letters(work_id);
            CREATE INDEX IF NOT EXISTS idx_retention_tombstone_key_id
                ON runtime_retention_tombstones(key_id);
            """
        )
        self._ensure_column(conn, "runtime_turns", "source_event_key TEXT")
        self._ensure_column(conn, "inbox_events", "runtime_turn_id TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_turns_source_event_key
            ON runtime_turns(source_event_key) WHERE source_event_key IS NOT NULL
            """
        )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS webhook_nonce_receipts (
                account_id TEXT NOT NULL,
                nonce TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(account_id, nonce)
            );
            CREATE INDEX IF NOT EXISTS idx_webhook_nonce_expiry
                ON webhook_nonce_receipts(expires_at);
            CREATE TABLE IF NOT EXISTS inbox_attachment_staging (
                event_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                attachments TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        for definition in (
            "turn_id TEXT",
            "source_event_key TEXT",
            "platform_tool_call_id TEXT",
            "invocation_id TEXT",
            "idempotency_key TEXT",
            "idempotency_mode TEXT NOT NULL DEFAULT 'non_idempotent'",
            "state TEXT NOT NULL DEFAULT 'completed'",
            "claim_owner TEXT",
            "claim_generation INTEGER NOT NULL DEFAULT 0",
            "claim_expires_at TEXT",
            "reconciliation TEXT",
        ):
            self._ensure_column(conn, "tool_calls", definition)
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_effect_idempotency
               ON tool_calls(idempotency_key) WHERE idempotency_key IS NOT NULL"""
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

    @staticmethod
    def _validate_terminal_common(
        event_type: str, status: str, result: Any, error: str | None
    ) -> str | None:
        expected = {"complete": "completed", "cancelled": "cancelled", "error": "error"}
        if event_type not in expected or status != expected[event_type]:
            raise ValueError("runtime terminal event and status disagree")
        if error is not None and (not isinstance(error, str) or len(error.encode("utf-8")) > 4096):
            raise ValueError("runtime terminal error is invalid or too large")
        if event_type != "complete":
            if result is not None:
                raise ValueError("non-complete terminal events cannot persist a result")
            return None
        if not isinstance(result, dict) or set(result) - {"content", "usage", "agent_result"} or not {"content", "usage"}.issubset(result):
            raise ValueError("authoritative runtime result schema is invalid")
        content, usage = result.get("content"), result.get("usage")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 65_536:
            raise ValueError("authoritative runtime content is invalid or too large")
        if not isinstance(usage, dict) or "total_tokens" not in usage or set(usage) - {"total_tokens", "prompt_tokens", "completion_tokens"}:
            raise ValueError("authoritative runtime usage schema is invalid")
        if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 9_000_000_000_000_000 for value in usage.values()):
            raise ValueError("authoritative runtime usage is invalid")
        if usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0) > usage["total_tokens"]:
            raise ValueError("authoritative runtime usage aggregate is inconsistent")
        agent_result = result.get("agent_result")
        if agent_result is not None and (not isinstance(agent_result, str) or len(agent_result.encode("utf-8")) > 65_536):
            raise ValueError("authoritative runtime agent_result is invalid or too large")
        result_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(result_json.encode("utf-8")) > 131_072:
            raise ValueError("authoritative runtime result exceeds the byte limit")
        return result_json

    def complete_runtime_turn(
        self,
        turn_id: str,
        status: str = "completed",
        result: Any = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        terminal_event = {"completed": "complete", "cancelled": "cancelled", "error": "error"}.get(status)
        validated_result = (
            self._validate_terminal_common(terminal_event, status, result, error)
            if terminal_event is not None else None
        )
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
                    validated_result if terminal_event is not None else (
                        json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
                    ),
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

    def complete_runtime_turn_with_event(
        self,
        *,
        thread_id: str,
        turn_id: str,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        status: str,
        result: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist the sole terminal event and authoritative turn state."""
        if event_type not in {"complete", "cancelled", "error"}:
            raise ValueError("runtime terminal event type is invalid")
        if status not in {"completed", "cancelled", "error"}:
            raise ValueError("runtime terminal status is invalid")
        common_result_json = self._validate_terminal_common(
            event_type, status, result, error
        )
        expected_status = {"complete": "completed", "cancelled": "cancelled", "error": "error"}[event_type]
        if status != expected_status:
            raise ValueError("runtime terminal event and status disagree")
        if not isinstance(payload, dict):
            raise ValueError("runtime terminal payload must be an object")
        try:
            payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("runtime terminal payload is not JSON-compatible") from exc
        if len(payload_json.encode("utf-8")) > 131_072:
            raise ValueError("runtime terminal payload exceeds the byte limit")
        if error is not None and (not isinstance(error, str) or len(error.encode("utf-8")) > 4096):
            raise ValueError("runtime terminal error is invalid or too large")
        result_json = None
        if event_type == "complete":
            if not isinstance(result, dict) or set(result) - {"content", "usage", "agent_result"} or not {"content", "usage"}.issubset(result):
                raise ValueError("authoritative runtime result schema is invalid")
            content = result.get("content")
            usage = result.get("usage")
            if not isinstance(content, str) or len(content.encode("utf-8")) > 65_536:
                raise ValueError("authoritative runtime content is invalid or too large")
            if not isinstance(usage, dict) or "total_tokens" not in usage or set(usage) - {"total_tokens", "prompt_tokens", "completion_tokens"}:
                raise ValueError("authoritative runtime usage schema is invalid")
            for value in usage.values():
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 9_000_000_000_000_000:
                    raise ValueError("authoritative runtime usage is invalid")
            if usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0) > usage["total_tokens"]:
                raise ValueError("authoritative runtime usage aggregate is inconsistent")
            agent_result = result.get("agent_result")
            if agent_result is not None and (not isinstance(agent_result, str) or len(agent_result.encode("utf-8")) > 65_536):
                raise ValueError("authoritative runtime agent_result is invalid or too large")
            result_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            if len(result_json.encode("utf-8")) > 131_072:
                raise ValueError("authoritative runtime result exceeds the byte limit")
        elif result is not None:
            raise ValueError("non-complete terminal events cannot persist a result")
        result_json = common_result_json
        now = datetime.now().isoformat()
        event_id = f"event_{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            turn = conn.execute(
                """SELECT * FROM runtime_turns
                   WHERE turn_id = ? AND thread_id = ? AND session_id = ?""",
                (turn_id, thread_id, session_id),
            ).fetchone()
            if turn is None:
                raise KeyError(f"Runtime turn not found: {turn_id}")
            if turn["status"] != "running":
                existing = conn.execute(
                    """SELECT * FROM runtime_events
                       WHERE turn_id = ? AND event_type IN ('complete', 'cancelled', 'error')
                       ORDER BY seq DESC LIMIT 1""",
                    (turn_id,),
                ).fetchone()
                if existing is None or turn["status"] != status:
                    raise RuntimeError("runtime turn already has a different terminal state")
                return self._row_to_dict(existing)
            thread = conn.execute(
                "SELECT latest_event_seq FROM runtime_threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if thread is None:
                raise KeyError(f"Runtime thread not found: {thread_id}")
            seq = int(thread["latest_event_seq"]) + 1
            conn.execute(
                """INSERT INTO runtime_events (
                    event_id, thread_id, turn_id, session_id, seq, event_type,
                    payload, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')""",
                (
                    event_id, thread_id, turn_id, session_id, seq, event_type,
                    payload_json, now,
                ),
            )
            conn.execute(
                """UPDATE runtime_turns SET status = ?, result = ?, error = ?,
                   completed_at = ? WHERE turn_id = ? AND status = 'running'""",
                (
                    status,
                    result_json,
                    error, now, turn_id,
                ),
            )
            conn.execute(
                """UPDATE runtime_threads SET latest_event_seq = ?, updated_at = ?
                   WHERE thread_id = ?""",
                (seq, now, thread_id),
            )
            stored = conn.execute(
                "SELECT * FROM runtime_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._row_to_dict(stored)

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

    def claim_tool_effect(
        self,
        *,
        session_id: str,
        turn_id: str,
        source_event_key: str,
        platform_tool_call_id: str,
        invocation_id: str | None = None,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_mode: str,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> dict[str, Any]:
        """Persist and fence a tool effect before the external side effect."""
        from open_agent.durable_runtime.models import ClaimToken

        if idempotency_mode not in {"idempotent", "non_idempotent"}:
            raise ValueError("unsupported tool idempotency mode")
        if now.tzinfo is None or expires_at.tzinfo is None or expires_at <= now:
            raise ValueError("tool effect lease must be a positive aware interval")
        stable_invocation_id = invocation_id or platform_tool_call_id
        identity = json.dumps(
            [source_event_key, stable_invocation_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        effect_key = f"tool-effect:{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"
        tool_call_id = f"tool_{uuid.uuid5(uuid.NAMESPACE_URL, effect_key).hex}"
        arguments_json = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        now_value = now.astimezone(timezone.utc).isoformat()
        expires_value = expires_at.astimezone(timezone.utc).isoformat()
        conn = self._get_conn()
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM tool_calls WHERE idempotency_key = ?", (effect_key,)
            ).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO tool_calls (
                        tool_call_id, session_id, tool_name, arguments, created_at,
                        metadata, turn_id, source_event_key, platform_tool_call_id,
                        invocation_id,
                        idempotency_key, idempotency_mode, state, claim_owner,
                        claim_generation, claim_expires_at
                    ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, 'executing', ?, 1, ?)""",
                    (
                        tool_call_id, session_id, tool_name, arguments_json, now_value,
                        turn_id, source_event_key, platform_tool_call_id,
                        stable_invocation_id, effect_key,
                        idempotency_mode, owner_id, expires_value,
                    ),
                )
                disposition = "execute"
            else:
                if (
                    row["session_id"] != session_id
                    or row["source_event_key"] != source_event_key
                    or row["invocation_id"] != stable_invocation_id
                    or row["tool_name"] != tool_name
                    or row["arguments"] != arguments_json
                    or row["idempotency_mode"] != idempotency_mode
                ):
                    raise RuntimeError("tool effect idempotency identity conflict")
                if row["state"] == "completed":
                    disposition = "replay"
                elif row["state"] == "delivery_unknown":
                    disposition = "manual_reconciliation"
                elif row["claim_expires_at"] > now_value:
                    raise RuntimeError("tool effect is owned by a live worker")
                elif idempotency_mode == "non_idempotent":
                    conn.execute(
                        """UPDATE tool_calls SET state = 'delivery_unknown',
                           reconciliation = 'manual_required', claim_owner = NULL,
                           claim_expires_at = NULL WHERE tool_call_id = ?""",
                        (row["tool_call_id"],),
                    )
                    disposition = "manual_reconciliation"
                else:
                    conn.execute(
                        """UPDATE tool_calls SET state = 'executing', claim_owner = ?,
                           claim_generation = claim_generation + 1, claim_expires_at = ?
                           WHERE tool_call_id = ?""",
                        (owner_id, expires_value, row["tool_call_id"]),
                    )
                    disposition = "execute"
            stored = conn.execute(
                "SELECT * FROM tool_calls WHERE idempotency_key = ?", (effect_key,)
            ).fetchone()
        value = self._row_to_dict(stored)
        value["disposition"] = disposition
        if value.get("claim_owner") and value.get("claim_expires_at"):
            value["claim"] = ClaimToken(
                value["claim_owner"],
                int(value["claim_generation"]),
                datetime.fromisoformat(value["claim_expires_at"]),
            )
        else:
            value["claim"] = None
        return value

    def complete_tool_effect(
        self,
        tool_call_id: str,
        claim: Any,
        *,
        success: bool,
        result: Any,
        now: datetime,
        error: str | None = None,
    ) -> dict[str, Any]:
        from open_agent.durable_runtime.repository import StaleClaimError

        now_value = now.astimezone(timezone.utc).isoformat()
        conn = self._get_conn()
        with conn:
            row = conn.execute(
                """UPDATE tool_calls SET state = 'completed', success = ?, result = ?,
                   error = ?, completed_at = ?, claim_owner = NULL, claim_expires_at = NULL
                   WHERE tool_call_id = ? AND state = 'executing'
                     AND claim_owner = ? AND claim_generation = ?
                     AND claim_expires_at = ? AND claim_expires_at > ?
                   RETURNING *""",
                (
                    int(success), json.dumps(result, ensure_ascii=False), error, now_value,
                    tool_call_id, claim.owner_id, claim.generation,
                    claim.expires_at.astimezone(timezone.utc).isoformat(), now_value,
                ),
            ).fetchone()
        if row is None:
            raise StaleClaimError(f"stale tool effect claim: {tool_call_id}")
        return self._row_to_dict(row)

    def mark_tool_effect_delivery_unknown(
        self,
        tool_call_id: str,
        claim: Any,
        *,
        now: datetime,
        reason: str,
    ) -> dict[str, Any]:
        """Fence an ambiguous claimed effect into manual reconciliation."""
        from open_agent.durable_runtime.repository import StaleClaimError

        now_value = now.astimezone(timezone.utc).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                """UPDATE tool_calls SET state = 'delivery_unknown',
                   reconciliation = 'manual_required', error = ?, completed_at = ?,
                   claim_owner = NULL, claim_expires_at = NULL
                   WHERE tool_call_id = ? AND state = 'executing'
                     AND claim_owner = ? AND claim_generation = ?
                     AND claim_expires_at = ? AND claim_expires_at > ?
                   RETURNING *""",
                (
                    str(reason)[:500], now_value, tool_call_id, claim.owner_id,
                    claim.generation,
                    claim.expires_at.astimezone(timezone.utc).isoformat(), now_value,
                ),
            ).fetchone()
        if row is None:
            raise StaleClaimError(f"stale tool effect claim: {tool_call_id}")
        return self._row_to_dict(row)

    def prepare_tool_effect_retry(self, source_event_key: str, *, now: datetime) -> bool:
        """Atomically classify orphaned effects before an inbox retry."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("tool retry time must be timezone-aware")
        now_value = now.astimezone(timezone.utc).isoformat()
        conn = self._get_conn()
        blocked_reason = None
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE tool_calls SET state = 'delivery_unknown',
                   reconciliation = 'manual_required', claim_owner = NULL,
                   claim_expires_at = NULL,
                   error = COALESCE(error, 'non-idempotent effect lease expired')
                   WHERE source_event_key = ? AND state = 'executing'
                     AND idempotency_mode = 'non_idempotent'
                     AND claim_expires_at <= ?""",
                (source_event_key, now_value),
            )
            unknown = conn.execute(
                """SELECT 1 FROM tool_calls WHERE source_event_key = ?
                   AND state = 'delivery_unknown' LIMIT 1""",
                (source_event_key,),
            ).fetchone()
            if unknown is not None:
                blocked_reason = "tool effect requires manual reconciliation"
            else:
                live = conn.execute(
                    """SELECT 1 FROM tool_calls WHERE source_event_key = ?
                       AND state = 'executing' AND claim_expires_at > ? LIMIT 1""",
                    (source_event_key, now_value),
                ).fetchone()
                if live is not None:
                    blocked_reason = "live executing tool effect blocks Agent retry"
        if blocked_reason is not None:
            raise RuntimeError(blocked_reason)
        return True

    def get_tool_effect(self, tool_call_id: str) -> dict[str, Any]:
        row = self._get_conn().execute(
            "SELECT * FROM tool_calls WHERE tool_call_id = ?", (tool_call_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Tool effect not found: {tool_call_id}")
        return self._row_to_dict(row)

    def tool_effects_resolved(self, source_event_key: str) -> bool:
        row = self._get_conn().execute(
            """SELECT 1 FROM tool_calls
               WHERE source_event_key = ? AND state != 'completed' LIMIT 1""",
            (source_event_key,),
        ).fetchone()
        return row is None

    def has_unresolved_tool_effect(self, source_event_key: str) -> bool:
        return not self.tool_effects_resolved(source_event_key)

    def create_scheduler_job(
        self,
        schedule: str,
        prompt: str,
        goal_id: str | None = None,
        job_id: str | None = None,
        next_run_at: str | None = None,
        timezone_name: str = "Asia/Shanghai",
        max_retries: int = 5,
        destination: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from open_agent.scheduler_runtime import CronSchedule

        if not isinstance(schedule, str):
            raise ValueError("schedule must be a string")
        parsed_schedule = CronSchedule.parse(schedule, timezone_name)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100_000:
            raise ValueError("prompt must be a non-empty string of at most 100000 characters")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 100:
            raise ValueError("max_retries must be between 0 and 100")
        if destination is not None and (
            not isinstance(destination, str) or not destination.strip() or len(destination) > 512
        ):
            raise ValueError("destination must be a non-empty string of at most 512 characters")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        metadata_value = metadata or {}
        for identity_name in ("profile_id", "user_id", "conversation_id"):
            identity = metadata_value.get(identity_name)
            if identity is not None and (
                not isinstance(identity, str) or not identity.strip() or len(identity) > 256
            ):
                raise ValueError(f"metadata.{identity_name} must be a bounded identifier")
        encoded_metadata = json.dumps(metadata_value, ensure_ascii=False)
        if len(encoded_metadata.encode("utf-8")) > 262_144:
            raise ValueError("metadata must not exceed 256 KiB")
        if job_id is not None and (
            not isinstance(job_id, str) or not job_id.strip() or len(job_id) > 256
        ):
            raise ValueError("job_id must be a bounded identifier")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        if next_run_at is None:
            next_run_at = parsed_schedule.next_occurrence(now_dt).astimezone(timezone.utc).isoformat()
        else:
            try:
                cursor = datetime.fromisoformat(next_run_at.replace("Z", "+00:00"))
            except (AttributeError, ValueError) as exc:
                raise ValueError("next_run_at must be a timezone-aware ISO datetime") from exc
            if cursor.tzinfo is None or cursor.utcoffset() is None:
                raise ValueError("next_run_at must be a timezone-aware ISO datetime")
            next_run_at = cursor.astimezone(timezone.utc).isoformat()
        job_id = job_id or f"job_{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO scheduler_jobs (
                    job_id, goal_id, schedule, prompt, next_run_at, timezone,
                    max_retries, destination, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, goal_id, schedule, prompt, next_run_at, timezone_name,
                    max_retries, destination, now, now,
                    encoded_metadata,
                ),
            )
        return self._row_to_dict(conn.execute("SELECT * FROM scheduler_jobs WHERE job_id = ?", (job_id,)).fetchone())

    def update_scheduler_job_status(self, job_id: str, status: str) -> dict[str, Any]:
        if status not in {"active", "paused", "deleted"}:
            raise ValueError("invalid scheduler job status")
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

    def get_scheduler_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM scheduler_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_due_scheduler_jobs(self, now: datetime, limit: int = 100) -> list[dict[str, Any]]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        rows = self._get_conn().execute(
            """SELECT * FROM scheduler_jobs
               WHERE status = 'active' AND next_run_at IS NOT NULL
                 AND next_run_at <= ?
               ORDER BY next_run_at, job_id LIMIT ?""",
            (now.astimezone(timezone.utc).isoformat(), limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

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
        for key in ("metadata", "todo_items", "last_judge_result", "acceptance_criteria", "judge_result", "budget_delta", "arguments", "result", "payload", "decision", "events"):
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
