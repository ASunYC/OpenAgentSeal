"""
Repository implementations for chat storage.

Provides JSON-based persistence for chat sessions.
"""

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import asyncio
from threading import Lock

from open_agent.app.runner.models import ChatSpec, ChatFile, Message
from open_agent.utils.path_utils import get_data_dir

logger = logging.getLogger(__name__)


class ChatRepository(ABC):
    """Abstract base class for chat storage"""
    
    @abstractmethod
    async def list_chats(self, user_id: str = None) -> List[ChatSpec]:
        """List all chats, optionally filtered by user"""
        pass
    
    @abstractmethod
    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Get a specific chat by ID"""
        pass
    
    @abstractmethod
    async def create_chat(self, chat: ChatSpec) -> ChatSpec:
        """Create a new chat"""
        pass
    
    @abstractmethod
    async def update_chat(self, chat: ChatSpec) -> ChatSpec:
        """Update an existing chat"""
        pass
    
    @abstractmethod
    async def delete_chats(self, chat_ids: List[str]) -> bool:
        """Delete chats by IDs"""
        pass
    
    @abstractmethod
    async def find_by_session_id(self, session_id: str) -> Optional[ChatSpec]:
        """Find chat by session ID"""
        pass


class JsonChatRepository(ChatRepository):
    """
    Monthly JSON file-based chat metadata repository.
    
    Stores chat metadata in ~/.open-agent/data/sessions/chat_YYYYMM.json.
    Message bodies live in monthly SQLite databases handled by
    MonthlyMessageRepository.
    """
    
    def __init__(self, storage_dir: Path = None):
        use_default_storage = storage_dir is None
        if storage_dir is None:
            storage_dir = get_data_dir() / "sessions"
        
        self.storage_dir = storage_dir
        self.legacy_chats_file = Path.home() / ".open-agent" / "chats.json"
        self._lock = Lock()
        self._cache: Optional[List[ChatSpec]] = None
        
        # Ensure directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        if use_default_storage:
            self._migrate_legacy_session_dir()
            self._migrate_legacy_chats()

    def _migrate_legacy_session_dir(self):
        legacy_dir = get_data_dir() / "会话"
        if not legacy_dir.exists() or legacy_dir.resolve() == self.storage_dir.resolve():
            return
        for item in legacy_dir.iterdir():
            target = self.storage_dir / item.name
            if target.exists():
                continue
            if item.is_dir():
                import shutil

                shutil.copytree(item, target)
            else:
                import shutil

                shutil.copy2(item, target)

    def _month_key(self, value: datetime | str | None = None) -> str:
        if value is None:
            dt = datetime.now()
        elif isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value))
        return dt.strftime("%Y%m")

    def _chat_file(self, month_key: str) -> Path:
        return self.storage_dir / f"chat_{month_key}.json"

    def _load_file(self, path: Path) -> ChatFile:
        if not path.exists():
            return ChatFile(chats=[])
        try:
            with open(path, "r", encoding="utf-8") as f:
                return ChatFile(**json.load(f))
        except Exception as e:
            logger.error("Failed to load chats from %s: %s", path, e)
            return ChatFile(chats=[])

    def _save_file(self, path: Path, chat_file: ChatFile):
        data = {
            "chats": [
                {
                    "id": c.id,
                    "name": c.name,
                    "session_id": c.session_id,
                    "user_id": c.user_id,
                    "channel": c.channel,
                    "meta": c.meta,
                    "created_at": c.created_at.isoformat() if isinstance(c.created_at, datetime) else c.created_at,
                    "updated_at": c.updated_at.isoformat() if isinstance(c.updated_at, datetime) else c.updated_at,
                }
                for c in chat_file.chats
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _migrate_legacy_chats(self):
        if not self.legacy_chats_file.exists():
            return

        existing_ids = {
            chat.id
            for path in self.storage_dir.glob("chat_*.json")
            for chat in self._load_file(path).chats
        }
        legacy = self._load_file(self.legacy_chats_file)
        migrated = 0
        for chat in legacy.chats:
            if chat.id in existing_ids:
                continue
            self._upsert_chat(chat, touch=False)
            migrated += 1
        if migrated:
            logger.info("Migrated %d legacy chat metadata records into %s", migrated, self.storage_dir)
    
    def _load_chats(self) -> List[ChatSpec]:
        """Load chats from monthly JSON files"""
        with self._lock:
            if self._cache is not None:
                return self._cache

            chats: list[ChatSpec] = []
            for path in sorted(self.storage_dir.glob("chat_*.json")):
                chats.extend(self._load_file(path).chats)
            self._cache = chats
            return self._cache

    def _upsert_chat(self, chat: ChatSpec, touch: bool = True) -> ChatSpec:
        if touch:
            chat.touch()

        month_key = self._month_key(chat.created_at)
        path = self._chat_file(month_key)
        chat_file = self._load_file(path)
        for i, existing in enumerate(chat_file.chats):
            if existing.id == chat.id:
                chat_file.chats[i] = chat
                break
        else:
            chat_file.chats.append(chat)
        self._save_file(path, chat_file)
        self._cache = None
        return chat
    
    async def list_chats(self, user_id: str = None) -> List[ChatSpec]:
        """List all chats"""
        chats = self._load_chats()
        
        if user_id:
            chats = [c for c in chats if c.user_id == user_id]
        
        # Sort by updated_at descending
        chats = sorted(chats, key=lambda c: c.updated_at, reverse=True)
        return chats
    
    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Get a specific chat by ID"""
        for chat in self._load_chats():
            if chat.id == chat_id:
                return chat
        return None
    
    async def create_chat(self, chat: ChatSpec) -> ChatSpec:
        """Create a new chat"""
        self._upsert_chat(chat, touch=False)
        logger.info(f"Created chat: {chat.id}")
        return chat
    
    async def update_chat(self, chat: ChatSpec) -> ChatSpec:
        """Update an existing chat"""
        updated = self._upsert_chat(chat, touch=True)
        logger.info(f"Updated chat: {chat.id}")
        return updated
    
    async def delete_chats(self, chat_ids: List[str]) -> bool:
        """Delete chats by IDs"""
        deleted = False
        ids = set(chat_ids)
        for path in self.storage_dir.glob("chat_*.json"):
            chat_file = self._load_file(path)
            original_count = len(chat_file.chats)
            chat_file.chats = [c for c in chat_file.chats if c.id not in ids]
            if len(chat_file.chats) < original_count:
                self._save_file(path, chat_file)
                deleted = True
        self._cache = None
        if deleted:
            logger.info(f"Deleted {len(chat_ids)} chat(s)")
        return deleted
    
    async def find_by_session_id(self, session_id: str) -> Optional[ChatSpec]:
        """Find chat by session ID"""
        for chat in self._load_chats():
            if chat.session_id == session_id:
                return chat
        return None
    
    def invalidate_cache(self):
        """Clear the in-memory cache"""
        with self._lock:
            self._cache = None


class MonthlyMessageRepository:
    """Monthly SQLite repository for persisted chat messages."""

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or get_data_dir() / "sessions"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _month_key(self, value: datetime | str | None = None) -> str:
        if value is None:
            dt = datetime.now()
        elif isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value))
        return dt.strftime("%Y%m")

    def _db_path(self, month_key: str) -> Path:
        return self.storage_dir / f"session_{month_key}.db"

    def _connect(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (session_id, message_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_time ON messages(session_id, timestamp)")
        return conn

    def add_message(self, session_id: str, message: Message) -> None:
        payload = message.model_dump(mode="json")
        timestamp = payload.get("timestamp") or datetime.now().isoformat()
        month_key = self._month_key(timestamp)
        with self._lock:
            conn = self._connect(self._db_path(month_key))
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO messages (message_id, session_id, timestamp, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(payload.get("id") or message.id),
                        session_id,
                        timestamp,
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_messages(self, session_id: str) -> List[Message]:
        rows: list[dict] = []
        with self._lock:
            for path in sorted(self.storage_dir.glob("session_*.db")):
                conn = None
                try:
                    conn = self._connect(path)
                    cursor = conn.execute(
                        "SELECT timestamp, payload FROM messages WHERE session_id = ? ORDER BY timestamp ASC",
                        (session_id,),
                    )
                    rows.extend(dict(row) for row in cursor.fetchall())
                except sqlite3.DatabaseError as exc:
                    logger.error("Failed to read messages from %s: %s", path, exc)
                finally:
                    if conn is not None:
                        conn.close()

        messages: list[Message] = []
        for row in sorted(rows, key=lambda item: item["timestamp"]):
            try:
                messages.append(Message.model_validate(json.loads(row["payload"])))
            except Exception as exc:
                logger.error("Failed to parse persisted message for %s: %s", session_id, exc)
        return messages

    def replace_messages(self, session_id: str, messages: List[Message]) -> None:
        self.delete_session_messages(session_id)
        for message in messages:
            self.add_message(session_id, message)

    def delete_session_messages(self, session_id: str) -> None:
        with self._lock:
            for path in self.storage_dir.glob("session_*.db"):
                conn = None
                try:
                    conn = self._connect(path)
                    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                    conn.commit()
                except sqlite3.DatabaseError as exc:
                    logger.error("Failed to delete messages from %s: %s", path, exc)
                finally:
                    if conn is not None:
                        conn.close()
