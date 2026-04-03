"""
Data models for Chat and Session management.

Following CoPaw's architecture pattern for session management.
"""

from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field
import uuid


class ChatSpec(BaseModel):
    """Chat session metadata - persisted to JSON"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = Field(default="New Chat", description="Display name for the chat")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: str = Field(default="default", description="User identifier")
    channel: str = Field(default="web", description="Channel: web, cli, api")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    def touch(self):
        """Update the updated_at timestamp"""
        self.updated_at = datetime.now()


class ContentItem(BaseModel):
    """A single content item in a message"""
    type: str = "text"  # text, image, tool_call, tool_result
    text: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    success: Optional[bool] = None


class Message(BaseModel):
    """A single message in the conversation"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    role: str  # user, assistant, system, tool
    type: str = "message"
    content: List[ContentItem] | str
    timestamp: datetime = Field(default_factory=datetime.now)
    
    def to_api_format(self) -> Dict[str, Any]:
        """Convert to API response format"""
        if isinstance(self.content, str):
            return {
                "id": self.id,
                "role": self.role,
                "type": self.type,
                "content": self.content,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None
            }
        else:
            return {
                "id": self.id,
                "role": self.role,
                "type": self.type,
                "content": [c.model_dump(exclude_none=True) for c in self.content],
                "timestamp": self.timestamp.isoformat() if self.timestamp else None
            }


class ChatHistory(BaseModel):
    """Chat history with messages"""
    chat_id: str
    messages: List[Message] = Field(default_factory=list)
    total: int = 0


class AgentRequest(BaseModel):
    """Request to process a message through the agent"""
    session_id: str
    user_id: str = "default"
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    stream: bool = True
    meta: Dict[str, Any] = Field(default_factory=dict)


class AgentEvent(BaseModel):
    """Event emitted during agent processing"""
    event: str  # step_start, thinking, tool_call, tool_result, step_end, complete, error
    session_id: str
    step: Optional[int] = None
    content: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    success: Optional[bool] = None
    error: Optional[str] = None
    status: Optional[str] = None
    max_steps: Optional[int] = None


# Chat file storage format
class ChatFile(BaseModel):
    """Format for chats.json file"""
    chats: List[ChatSpec] = Field(default_factory=list)