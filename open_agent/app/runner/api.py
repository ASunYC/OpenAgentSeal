"""
Chat API Routes following CoPaw's REST API pattern.

Provides endpoints for:
- GET /api/chats - List all chats
- POST /api/chats - Create a new chat
- GET /api/chats/{chat_id} - Get a specific chat
- DELETE /api/chats/{chat_id} - Delete a chat
- GET /api/chats/{chat_id}/history - Get chat history
- POST /api/run - Run agent with streaming (SSE)
"""

import json
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from open_agent.app.runner.models import ChatSpec, ChatHistory, AgentRequest, AgentEvent
from open_agent.app.runner.manager import get_chat_manager
from open_agent.app.runner.runner import get_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


# Request/Response models
class CreateChatRequest(BaseModel):
    name: str = "New Chat"
    user_id: str = "default"
    channel: str = "web"


class DeleteChatsRequest(BaseModel):
    chat_ids: List[str]


class RunRequest(BaseModel):
    session_id: str
    user_id: str = "default"
    messages: List[dict] = []
    stream: bool = True


# Chat endpoints
@router.get("/chats")
async def list_chats(user_id: str = Query(None)) -> List[dict]:
    """List all chats"""
    manager = get_chat_manager()
    chats = await manager.list_chats(user_id)
    return [
        {
            "id": c.id,
            "name": c.name,
            "session_id": c.session_id,
            "user_id": c.user_id,
            "channel": c.channel,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in chats
    ]


@router.post("/chats")
async def create_chat(request: CreateChatRequest) -> dict:
    """Create a new chat"""
    manager = get_chat_manager()
    chat = await manager.create_chat(
        name=request.name,
        user_id=request.user_id,
        channel=request.channel,
    )
    return {
        "id": chat.id,
        "name": chat.name,
        "session_id": chat.session_id,
        "user_id": chat.user_id,
        "channel": chat.channel,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: str) -> dict:
    """Get a specific chat"""
    manager = get_chat_manager()
    chat = await manager.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    return {
        "id": chat.id,
        "name": chat.name,
        "session_id": chat.session_id,
        "user_id": chat.user_id,
        "channel": chat.channel,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str) -> dict:
    """Delete a chat"""
    manager = get_chat_manager()
    success = await manager.delete_chats([chat_id])
    if not success:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"success": True, "deleted_id": chat_id}


@router.post("/chats/delete")
async def delete_chats(request: DeleteChatsRequest) -> dict:
    """Delete multiple chats"""
    manager = get_chat_manager()
    success = await manager.delete_chats(request.chat_ids)
    return {"success": success, "deleted_count": len(request.chat_ids)}


@router.get("/chats/{chat_id}/history")
async def get_chat_history(chat_id: str) -> dict:
    """Get chat history with messages"""
    manager = get_chat_manager()
    history = await manager.get_history(chat_id)
    if not history:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    return {
        "chat_id": history.chat_id,
        "total": history.total,
        "messages": [m.to_api_format() for m in history.messages],
    }


# Run endpoint with SSE streaming
@router.post("/run")
async def run_agent(request: RunRequest):
    """Run agent with SSE streaming response"""
    runner = get_runner()
    
    agent_request = AgentRequest(
        session_id=request.session_id,
        user_id=request.user_id,
        messages=request.messages,
        stream=request.stream,
    )
    
    if not request.stream:
        # Non-streaming response
        events = []
        async for event in runner.process_message(agent_request):
            events.append(event)
        
        # Return last event
        if events:
            last = events[-1]
            return last.model_dump()
        return {"event": "error", "error": "No response"}
    
    # SSE streaming response
    async def event_generator():
        try:
            async for event in runner.process_message(agent_request):
                # Format as SSE
                data = json.dumps(event.model_dump(exclude_none=True), ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception as e:
            logger.error(f"Error in event stream: {e}")
            error_event = AgentEvent(
                event="error",
                session_id=request.session_id,
                error=str(e),
                status="error",
            )
            data = json.dumps(error_event.model_dump(exclude_none=True), ensure_ascii=False)
            yield f"data: {data}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Cancel endpoint
@router.post("/cancel")
async def cancel_session(session_id: str = Query(...)) -> dict:
    """Cancel a running session"""
    runner = get_runner()
    success = await runner.cancel_session(session_id)
    return {"success": success, "session_id": session_id}