"""
Chat Manager for managing chat sessions and coordinating with Agent.

Following CoPaw's ChatManager pattern.
"""

import asyncio
import logging
import uuid
from typing import Optional, List, Dict, Any, Callable, Awaitable

from open_agent.app.runner.models import ChatSpec, Message, ChatHistory, AgentEvent
from open_agent.app.runner.repo import ChatRepository, JsonChatRepository

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
    
    def __init__(self, repo: ChatRepository = None):
        self.repo = repo or JsonChatRepository()
        self._session_messages: Dict[str, List[Message]] = {}
        self._session_agents: Dict[str, str] = {}  # session_id -> agent_id
        self._event_subscribers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
    
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
        if chat.session_id not in self._session_messages:
            self._session_messages[chat.session_id] = []
        
        return chat
    
    async def update_chat(self, chat: ChatSpec) -> ChatSpec:
        """Update chat metadata"""
        return await self.repo.update_chat(chat)
    
    async def delete_chats(self, chat_ids: List[str]) -> bool:
        """Delete chats by IDs"""
        # Also clean up session messages
        for chat_id in chat_ids:
            chat = await self.repo.get_chat(chat_id)
            if chat and chat.session_id in self._session_messages:
                del self._session_messages[chat.session_id]
        
        return await self.repo.delete_chats(chat_ids)
    
    async def get_history(self, chat_id: str) -> Optional[ChatHistory]:
        """Get chat history with messages"""
        chat = await self.repo.get_chat(chat_id)
        if not chat:
            return None
        
        messages = self._session_messages.get(chat.session_id, [])
        return ChatHistory(
            chat_id=chat_id,
            messages=messages,
            total=len(messages),
        )
    
    def add_message(self, session_id: str, message: Message):
        """Add a message to session history"""
        if session_id not in self._session_messages:
            self._session_messages[session_id] = []
        self._session_messages[session_id].append(message)
    
    def get_messages(self, session_id: str) -> List[Message]:
        """Get messages for a session"""
        return self._session_messages.get(session_id, [])
    
    def clear_messages(self, session_id: str):
        """Clear messages for a session"""
        self._session_messages[session_id] = []
    
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


def get_chat_manager() -> ChatManager:
    """Get the global ChatManager instance"""
    global _chat_manager
    if _chat_manager is None:
        _chat_manager = ChatManager()
    return _chat_manager


def init_chat_manager(repo: ChatRepository = None) -> ChatManager:
    """Initialize the global ChatManager"""
    global _chat_manager
    _chat_manager = ChatManager(repo)
    return _chat_manager