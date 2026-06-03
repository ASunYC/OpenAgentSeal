"""
Chat Manager for managing chat sessions and coordinating with Agent.

Following CoPaw's ChatManager pattern.
"""

import asyncio
import logging
import uuid
from typing import Optional, List, Dict, Any, Callable, Awaitable

from open_agent.app.runner.models import ChatSpec, Message, ChatHistory, AgentEvent
from open_agent.app.runner.repo import ChatRepository, JsonChatRepository, MonthlyMessageRepository

logger = logging.getLogger(__name__)


class ChatManager:
    """
    Manages chat sessions and coordinates with the Agent system.
    
    Responsibilities:
    - Create/update/delete chat sessions
    - Coordinate with AgentService for message processing
    - Persist chat metadata to JSON
    - Broadcast events to connected clients (SSE)
    """
    
    def __init__(self, repo: ChatRepository = None, storage_dir=None):
        self.repo = repo or JsonChatRepository(storage_dir=storage_dir)
        self.message_repo = MonthlyMessageRepository(storage_dir=storage_dir)
        self._session_messages: Dict[str, List[Message]] = {}
        self._session_agents: Dict[str, str] = {}  # session_id -> agent_id
        self._event_subscribers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []

    def _ensure_session_messages(self, session_id: str) -> List[Message]:
        if session_id not in self._session_messages:
            self._session_messages[session_id] = self.message_repo.list_messages(session_id)
        return self._session_messages[session_id]
    
    async def list_chats(self, user_id: str = None) -> List[ChatSpec]:
        """List all chats"""
        return await self.repo.list_chats(user_id)
    
    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Get a specific chat"""
        return await self.repo.get_chat(chat_id)
    
    async def create_chat(
        self,
        name: str = "New Chat",
        user_id: str = "default",
        channel: str = "web",
        session_id: str = None,
    ) -> ChatSpec:
        """Create a new chat session"""
        chat = ChatSpec(
            id=str(uuid.uuid4())[:8],
            name=name,
            session_id=session_id or str(uuid.uuid4())[:8],
            user_id=user_id,
            channel=channel,
        )
        
        # Initialize message storage for this session
        self._session_messages[chat.session_id] = []
        
        await self.repo.create_chat(chat)
        logger.info(f"Created chat: {chat.id} (session: {chat.session_id})")
        return chat

    def _derive_fork_session_id(self, source_session_id: str) -> str:
        """Create a new session id that keeps the source agent routing when possible."""
        if source_session_id.startswith("session_main_"):
            return f"session_main_{uuid.uuid4().hex[:8]}"
        if source_session_id.startswith("session_"):
            agent_part = source_session_id[len("session_"):]
            if "_" in agent_part:
                agent_id = agent_part.rsplit("_", 1)[0]
                if agent_id and agent_id != "main":
                    return f"session_{agent_id}_{uuid.uuid4().hex[:8]}"
        return f"{source_session_id}_fork_{uuid.uuid4().hex[:8]}"

    async def fork_chat(
        self,
        source_session_id: str,
        name: str | None = None,
        user_id: str = "default",
        channel: str = "web",
    ) -> tuple[Optional[ChatSpec], int]:
        """Fork an existing chat session into a new task with copied messages."""
        source_chat = await self.repo.find_by_session_id(source_session_id)
        if not source_chat:
            return None, 0

        new_session_id = self._derive_fork_session_id(source_chat.session_id)
        forked_chat = ChatSpec(
            name=name or f"{source_chat.name} Copy",
            session_id=new_session_id,
            user_id=source_chat.user_id or user_id,
            channel=source_chat.channel or channel,
            meta={
                **source_chat.meta,
                "forked_from_chat_id": source_chat.id,
                "forked_from_session_id": source_chat.session_id,
            },
        )

        await self.repo.create_chat(forked_chat)

        source_messages = self._ensure_session_messages(source_chat.session_id)
        self._session_messages[forked_chat.session_id] = [
            message.model_copy(deep=True) for message in source_messages
        ]
        self.message_repo.replace_messages(forked_chat.session_id, self._session_messages[forked_chat.session_id])

        source_agent_id = self._session_agents.get(source_chat.session_id)
        if source_agent_id:
            self._session_agents[forked_chat.session_id] = source_agent_id

        logger.info(
            "Forked chat %s -> %s (session: %s -> %s, messages=%d)",
            source_chat.id,
            forked_chat.id,
            source_chat.session_id,
            forked_chat.session_id,
            len(source_messages),
        )
        return forked_chat, len(source_messages)
    
    async def get_or_create_chat(
        self,
        session_id: str,
        user_id: str = "default",
        channel: str = "web",
        name: str = "New Chat",
    ) -> ChatSpec:
        """Get existing chat or create new one"""
        chat = await self.repo.find_by_session_id(session_id)
        if not chat:
            chat = await self.create_chat(
                name=name,
                user_id=user_id,
                channel=channel,
                session_id=session_id,
            )
        
        # Ensure message storage exists
        self._ensure_session_messages(chat.session_id)
        
        return chat
    
    async def update_chat(self, chat: ChatSpec) -> ChatSpec:
        """Update chat metadata"""
        return await self.repo.update_chat(chat)
    
    async def delete_chats(self, chat_ids: List[str]) -> bool:
        """Delete chats by IDs"""
        # Also clean up session messages
        for chat_id in chat_ids:
            chat = await self.repo.get_chat(chat_id)
            if chat:
                if chat.session_id in self._session_messages:
                    del self._session_messages[chat.session_id]
                self.message_repo.delete_session_messages(chat.session_id)
        
        return await self.repo.delete_chats(chat_ids)
    
    async def get_history(self, chat_id: str) -> Optional[ChatHistory]:
        """Get chat history with messages"""
        chat = await self.repo.get_chat(chat_id)
        if not chat:
            return None
        
        messages = self._ensure_session_messages(chat.session_id)
        return ChatHistory(
            chat_id=chat_id,
            messages=messages,
            total=len(messages),
        )
    
    def add_message(self, session_id: str, message: Message):
        """Add a message to session history"""
        messages = self._ensure_session_messages(session_id)
        messages.append(message)
        self.message_repo.add_message(session_id, message)
    
    def get_messages(self, session_id: str) -> List[Message]:
        """Get messages for a session"""
        return self._ensure_session_messages(session_id)
    
    def clear_messages(self, session_id: str):
        """Clear messages for a session"""
        self._session_messages[session_id] = []
        self.message_repo.delete_session_messages(session_id)

    def replace_messages(self, session_id: str, messages: List[Message]):
        """Replace all messages for a session."""
        self._session_messages[session_id] = messages
        self.message_repo.replace_messages(session_id, messages)
    
    def set_session_agent(self, session_id: str, agent_id: str):
        """Associate an agent with a session"""
        self._session_agents[session_id] = agent_id
    
    def get_session_agent(self, session_id: str) -> Optional[str]:
        """Get agent ID for a session"""
        return self._session_agents.get(session_id)
    
    # ==================== 事件广播 ====================
    
    def subscribe_events(self, callback: Callable[[Dict[str, Any]], Awaitable[None]]):
        """订阅事件广播"""
        self._event_subscribers.append(callback)
    
    def unsubscribe_events(self, callback: Callable[[Dict[str, Any]], Awaitable[None]]):
        """取消订阅事件广播"""
        if callback in self._event_subscribers:
            self._event_subscribers.remove(callback)
    
    async def broadcast_event(self, event_data: Dict[str, Any]):
        """广播事件给所有订阅者
        
        用于小组消息、任务状态变更等实时通知
        """
        for callback in self._event_subscribers:
            try:
                await callback(event_data)
            except Exception as e:
                logger.error(f"Event callback error: {e}")
        
        logger.debug(f"Broadcasted event to {len(self._event_subscribers)} subscribers: {event_data.get('type', 'unknown')}")


# Singleton instance
_chat_manager: Optional[ChatManager] = None
_scoped_chat_managers: Dict[str, ChatManager] = {}


def _manager_key(profile_id: str | None = None) -> str:
    return profile_id or "main"


def _manager_storage_dir(profile_id: str | None = None):
    from open_agent.agent_profiles import MAIN_AGENT_ID, get_agent_profile_manager

    manager = get_agent_profile_manager()
    agent_home = manager.get_agent_home(None if not profile_id or profile_id == MAIN_AGENT_ID else profile_id)
    return agent_home / "sessions"


def get_chat_manager(profile_id: str | None = None) -> ChatManager:
    """Get the global ChatManager instance"""
    global _chat_manager
    if profile_id is None:
        if _chat_manager is None:
            _chat_manager = ChatManager(storage_dir=_manager_storage_dir(None))
        return _chat_manager

    key = _manager_key(profile_id)
    if key not in _scoped_chat_managers:
        _scoped_chat_managers[key] = ChatManager(storage_dir=_manager_storage_dir(profile_id))
    return _scoped_chat_managers[key]


def init_chat_manager(repo: ChatRepository = None) -> ChatManager:
    """Initialize the global ChatManager"""
    global _chat_manager
    _chat_manager = ChatManager(repo)
    return _chat_manager
