"""Local reversible context block storage."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from open_agent.utils.path_utils import get_data_dir


@dataclass
class ContextBlock:
    ref_id: str
    session_id: str
    profile_id: str
    through_message_id: str
    message_ids: list[str]
    kind: str
    original_text: str
    compressed_text: str
    token_before: int
    token_after: int
    created_at: str


class ContextBlockStore:
    """SQLite-backed store for CCR-style compressed context blocks."""

    def __init__(self, db_path: str | Path | None = None):
        root = get_data_dir() / "context"
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else root / "context_blocks.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS context_blocks (
                    ref_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL DEFAULT '',
                    through_message_id TEXT NOT NULL DEFAULT '',
                    message_ids TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'chat',
                    original_text TEXT NOT NULL,
                    compressed_text TEXT NOT NULL,
                    token_before INTEGER NOT NULL DEFAULT 0,
                    token_after INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_context_blocks_session "
                "ON context_blocks(session_id, created_at)"
            )

    def create_ref_id(self, session_id: str) -> str:
        safe_session = re.sub(r"[^a-zA-Z0-9_-]+", "_", session_id or "session")
        return f"ctx://{safe_session}/{uuid.uuid4().hex[:12]}"

    def put_block(
        self,
        *,
        session_id: str,
        profile_id: str | None,
        through_message_id: str,
        message_ids: list[str],
        original_text: str,
        compressed_text: str,
        token_before: int,
        token_after: int,
        kind: str = "chat",
        ref_id: str | None = None,
    ) -> ContextBlock:
        block = ContextBlock(
            ref_id=ref_id or self.create_ref_id(session_id),
            session_id=session_id,
            profile_id=profile_id or "main",
            through_message_id=through_message_id,
            message_ids=message_ids,
            kind=kind,
            original_text=original_text,
            compressed_text=compressed_text,
            token_before=int(token_before or 0),
            token_after=int(token_after or 0),
            created_at=datetime.now().isoformat(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO context_blocks (
                    ref_id, session_id, profile_id, through_message_id,
                    message_ids, kind, original_text, compressed_text,
                    token_before, token_after, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    block.ref_id,
                    block.session_id,
                    block.profile_id,
                    block.through_message_id,
                    json.dumps(block.message_ids, ensure_ascii=False),
                    block.kind,
                    block.original_text,
                    block.compressed_text,
                    block.token_before,
                    block.token_after,
                    block.created_at,
                ),
            )
        return block

    def get_block(self, ref_id: str, session_id: str | None = None) -> ContextBlock | None:
        query = "SELECT * FROM context_blocks WHERE ref_id = ?"
        params: list[Any] = [ref_id]
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return self._row_to_block(row) if row else None

    def list_blocks(self, session_id: str, limit: int = 100) -> list[ContextBlock]:
        safe_limit = max(1, min(int(limit or 100), 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM context_blocks
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, safe_limit),
            ).fetchall()
        return [self._row_to_block(row) for row in rows]

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM context_blocks WHERE session_id = ?", (session_id,))

    def _row_to_block(self, row: sqlite3.Row) -> ContextBlock:
        try:
            message_ids = json.loads(row["message_ids"] or "[]")
        except Exception:
            message_ids = []
        return ContextBlock(
            ref_id=row["ref_id"],
            session_id=row["session_id"],
            profile_id=row["profile_id"],
            through_message_id=row["through_message_id"],
            message_ids=[str(item) for item in message_ids],
            kind=row["kind"],
            original_text=row["original_text"],
            compressed_text=row["compressed_text"],
            token_before=int(row["token_before"] or 0),
            token_after=int(row["token_after"] or 0),
            created_at=row["created_at"],
        )


_store: ContextBlockStore | None = None


def get_context_block_store() -> ContextBlockStore:
    global _store
    if _store is None:
        _store = ContextBlockStore()
    return _store
