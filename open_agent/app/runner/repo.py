"""
Repository implementations for chat storage.

Provides JSON-based persistence for chat sessions.
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import asyncio
from threading import Lock

from open_agent.app.runner.models import ChatSpec, ChatFile

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
    JSON file-based chat repository.
    
    Stores chats in ~/.open-agent/chats.json following CoPaw's pattern.
    """
    
    def __init__(self, storage_dir: Path = None):
        if storage_dir is None:
            storage_dir = Path.home() / ".open-agent"
        
        self.storage_dir = storage_dir
        self.chats_file = storage_dir / "chats.json"
        self._lock = Lock()
        self._cache: Optional[ChatFile] = None
        
        # Ensure directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_chats(self) -> ChatFile:
        """Load chats from JSON file"""
        with self._lock:
            if self._cache is not None:
                return self._cache
            
            if not self.chats_file.exists():
                self._cache = ChatFile(chats=[])
                return self._cache
            
            try:
                with open(self.chats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._cache = ChatFile(**data)
                    return self._cache
            except Exception as e:
                logger.error(f"Failed to load chats: {e}")
                self._cache = ChatFile(chats=[])
                return self._cache
    
    def _save_chats(self, chat_file: ChatFile):
        """Save chats to JSON file"""
        with self._lock:
            self._cache = chat_file
            
            # Convert to dict for JSON serialization
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
            
            with open(self.chats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    
    async def list_chats(self, user_id: str = None) -> List[ChatSpec]:
        """List all chats"""
        chat_file = self._load_chats()
        chats = chat_file.chats
        
        if user_id:
            chats = [c for c in chats if c.user_id == user_id]
        
        # Sort by updated_at descending
        chats = sorted(chats, key=lambda c: c.updated_at, reverse=True)
        return chats
    
    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Get a specific chat by ID"""
        chat_file = self._load_chats()
        for chat in chat_file.chats:
            if chat.id == chat_id:
                return chat
        return None
    
    async def create_chat(self, chat: ChatSpec) -> ChatSpec:
        """Create a new chat"""
        chat_file = self._load_chats()
        chat_file.chats.append(chat)
        self._save_chats(chat_file)
        logger.info(f"Created chat: {chat.id}")
        return chat
    
    async def update_chat(self, chat: ChatSpec) -> ChatSpec:
        """Update an existing chat"""
        chat_file = self._load_chats()
        
        for i, c in enumerate(chat_file.chats):
            if c.id == chat.id:
                chat.touch()
                chat_file.chats[i] = chat
                self._save_chats(chat_file)
                logger.info(f"Updated chat: {chat.id}")
                return chat
        
        # If not found, create it
        return await self.create_chat(chat)
    
    async def delete_chats(self, chat_ids: List[str]) -> bool:
        """Delete chats by IDs"""
        chat_file = self._load_chats()
        original_count = len(chat_file.chats)
        
        chat_file.chats = [c for c in chat_file.chats if c.id not in chat_ids]
        self._save_chats(chat_file)
        
        deleted = len(chat_file.chats) < original_count
        if deleted:
            logger.info(f"Deleted {len(chat_ids)} chat(s)")
        return deleted
    
    async def find_by_session_id(self, session_id: str) -> Optional[ChatSpec]:
        """Find chat by session ID"""
        chat_file = self._load_chats()
        for chat in chat_file.chats:
            if chat.session_id == session_id:
                return chat
        return None
    
    def invalidate_cache(self):
        """Clear the in-memory cache"""
        with self._lock:
            self._cache = None