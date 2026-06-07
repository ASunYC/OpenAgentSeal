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
import base64
import mimetypes
import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from open_agent.app.runner.models import ChatSpec, ChatHistory, AgentRequest, AgentEvent, Message
from open_agent.app.runner.manager import get_chat_manager
from open_agent.app.runner.runner import get_runner
from open_agent.app.runner.file_parser import MAX_FILE_BYTES
from open_agent.app.runner.context_compaction import (
    COMPACTION_META_KEY,
    build_effective_history,
    estimate_messages_tokens,
)
from open_agent.utils.path_utils import get_data_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


# Request/Response models
class CreateChatRequest(BaseModel):
    name: str = "New Chat"
    user_id: str = "default"
    channel: str = "web"


class DeleteChatsRequest(BaseModel):
    chat_ids: List[str]


class ForkChatRequest(BaseModel):
    session_id: str
    name: Optional[str] = None
    user_id: str = "default"
    channel: str = "web"
    profile_id: Optional[str] = None


class RunRequest(BaseModel):
    session_id: str
    user_id: str = "default"
    messages: List[dict] = []
    stream: bool = True
    workspace_sources: List[dict] = []
    selected_workspace_paths: List[str] = []
    tool_access_mode: str = "default"
    profile_id: Optional[str] = None


class CreateAgentSessionRequest(BaseModel):
    profile_id: Optional[str] = None
    name: str = "New Chat"
    user_id: str = "default"
    parent_session_id: Optional[str] = None
    parent_task_id: Optional[str] = None


class AgentSessionMessageRequest(BaseModel):
    profile_id: Optional[str] = None
    messages: List[dict] = []
    user_id: str = "default"
    stream: bool = True
    workspace_sources: List[dict] = []
    selected_workspace_paths: List[str] = []
    tool_access_mode: str = "default"


class AgentTaskRequest(BaseModel):
    profile_id: str
    instruction: str
    user_id: str = "default"
    parent_session_id: Optional[str] = None
    workspace_sources: List[dict] = []
    selected_workspace_paths: List[str] = []
    tool_access_mode: str = "default"


class LocalAttachmentRequest(BaseModel):
    paths: List[str]


class WorkspaceSourceRequest(BaseModel):
    paths: List[str]


class WorkspaceSourceState(BaseModel):
    sources: List[dict] = Field(default_factory=list)
    selected_paths: List[str] = Field(default_factory=list)
    expanded_paths: List[str] = Field(default_factory=list)


class PersistMessagesRequest(BaseModel):
    messages: List[dict] = []


def _get_control_plane():
    from open_agent.agent_profiles import get_agent_profile_manager
    from open_agent.control_plane import get_control_plane

    return get_control_plane(get_agent_profile_manager().get_agent_home(None))


def _get_control_plane_for_profile(profile_id: str | None):
    from open_agent.agent_profiles import get_agent_profile_manager
    from open_agent.control_plane import get_control_plane

    home = get_agent_profile_manager().get_agent_home(None if not profile_id or profile_id == "main" else profile_id)
    return get_control_plane(home)


def _workspace_state_path() -> Path:
    return get_data_dir() / "workspace_sources.json"


def _chat_manager_for_profile(profile_id: str | None):
    return get_chat_manager(None if not profile_id or profile_id == "main" else profile_id)


def _sanitize_workspace_state(state: WorkspaceSourceState) -> WorkspaceSourceState:
    available_paths = {
        str(source.get("path"))
        for source in state.sources
        if isinstance(source, dict) and source.get("path")
    }
    return WorkspaceSourceState(
        sources=state.sources[:50],
        selected_paths=[path for path in state.selected_paths if path in available_paths],
        expanded_paths=state.expanded_paths[:500],
    )


def _refresh_workspace_source(source: dict) -> dict | None:
    source_type = source.get("type")
    if source_type == "web":
        return source

    raw_path = source.get("path")
    if not raw_path:
        return None

    path = Path(str(raw_path))
    if not path.exists():
        return source

    refreshed = _workspace_source_from_path(path)
    if source.get("id"):
        refreshed["id"] = source["id"]
    return refreshed


def _read_workspace_source_state() -> WorkspaceSourceState:
    path = _workspace_state_path()
    if not path.exists():
        return WorkspaceSourceState()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        state = WorkspaceSourceState(**raw)
    except Exception as exc:
        logger.error("Failed to read workspace source state from %s: %s", path, exc)
        return WorkspaceSourceState()

    refreshed_sources = []
    for source in state.sources:
        if not isinstance(source, dict):
            continue
        refreshed = _refresh_workspace_source(source)
        if refreshed:
            refreshed_sources.append(refreshed)
    state.sources = refreshed_sources
    return _sanitize_workspace_state(state)


def _write_workspace_source_state(state: WorkspaceSourceState) -> WorkspaceSourceState:
    state = _sanitize_workspace_state(state)
    path = _workspace_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return state


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
            "meta": c.meta,
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
        "meta": chat.meta,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }


@router.get("/chats/runner-channel/{session_id}")
@router.get("/chats/session/{session_id}")
async def get_chat_by_session(session_id: str, profile_id: str = Query(None)) -> dict:
    """Get chat metadata by session id."""
    manager = _chat_manager_for_profile(profile_id)
    chat = await manager.repo.find_by_session_id(session_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    return {
        "id": chat.id,
        "name": chat.name,
        "session_id": chat.session_id,
        "user_id": chat.user_id,
        "channel": chat.channel,
        "meta": chat.meta,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: str, profile_id: str = Query(None)) -> dict:
    """Get a specific chat"""
    manager = _chat_manager_for_profile(profile_id)
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
async def delete_chat(chat_id: str, profile_id: str = Query(None)) -> dict:
    """Delete a chat"""
    manager = _chat_manager_for_profile(profile_id)
    success = await manager.delete_chats([chat_id])
    if not success:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"success": True, "deleted_id": chat_id}


@router.post("/chats/delete")
async def delete_chats(request: DeleteChatsRequest, profile_id: str = Query(None)) -> dict:
    """Delete multiple chats"""
    manager = _chat_manager_for_profile(profile_id)
    success = await manager.delete_chats(request.chat_ids)
    return {"success": success, "deleted_count": len(request.chat_ids)}


@router.get("/chats/{chat_id}/history")
async def get_chat_history(chat_id: str, profile_id: str = Query(None)) -> dict:
    """Get chat history with messages"""
    manager = _chat_manager_for_profile(profile_id)
    history = await manager.get_history(chat_id)
    if not history:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    return {
        "chat_id": history.chat_id,
        "total": history.total,
        "messages": [m.to_api_format() for m in history.messages],
    }


@router.get("/chats/session/{session_id}/context-status")
async def get_chat_context_status(session_id: str, profile_id: str = Query(None)) -> dict:
    """Return the active model-context usage for a persisted chat session."""
    from open_agent.agent_profiles import get_agent_profile_manager
    from open_agent.user_config import (
        get_user_config,
        model_auto_compact_token_limit,
        resolve_model_context_window,
    )

    manager = _chat_manager_for_profile(profile_id)
    chat = await manager.repo.find_by_session_id(session_id)
    config_manager = get_user_config()
    settings = config_manager.get_settings()
    model_id = chat.meta.get("context_model_id") if chat else None
    if not model_id:
        profile = get_agent_profile_manager().get_agent_config(profile_id)
        model_id = profile.model_id if profile else None
    model_config = (
        config_manager.get_model(model_id) if model_id else None
    ) or config_manager.get_default_model()
    context_window, context_window_source = resolve_model_context_window(
        model_config,
        getattr(settings, "context_compaction_token_limit", 60_000),
    )
    token_limit = model_auto_compact_token_limit(context_window)
    enabled = bool(getattr(settings, "auto_context_compaction", True))

    if not chat:
        return {
            "session_id": session_id,
            "enabled": enabled,
            "used_tokens": 0,
            "token_limit": token_limit,
            "context_window": context_window,
            "context_window_source": context_window_source,
            "model_id": model_config.id if model_config else model_id,
            "model_name": model_config.name if model_config else "",
            "usage_percent": 0,
            "compacted": False,
            "compaction_count": 0,
            "updated_at": None,
        }

    state = chat.meta.get(COMPACTION_META_KEY)
    state = state if isinstance(state, dict) else {}
    effective_history = build_effective_history(
        manager.get_messages(session_id),
        state,
    )
    used_tokens = estimate_messages_tokens(effective_history)
    usage_percent = min(100, max(0, round(used_tokens / context_window * 100)))

    return {
        "session_id": session_id,
        "enabled": enabled,
        "used_tokens": used_tokens,
        "token_limit": token_limit,
        "context_window": context_window,
        "context_window_source": context_window_source,
        "model_id": model_config.id if model_config else model_id,
        "model_name": model_config.name if model_config else "",
        "usage_percent": usage_percent,
        "compacted": bool(state.get("summary")),
        "compaction_count": int(state.get("compaction_count") or 0),
        "updated_at": state.get("updated_at"),
    }


@router.delete("/chats/session/{session_id}/messages")
async def clear_chat_messages(session_id: str, profile_id: str = Query(None)) -> dict:
    """Clear persisted messages for a chat session while keeping chat metadata."""
    manager = _chat_manager_for_profile(profile_id)
    chat = await manager.repo.find_by_session_id(session_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    manager.clear_messages(session_id)
    chat.meta.pop("context_compaction", None)
    await manager.update_chat(chat)
    return {"success": True, "session_id": session_id}


@router.post("/chats/session/{session_id}/messages")
async def persist_chat_messages(
    session_id: str,
    request: PersistMessagesRequest,
    profile_id: str = Query(None),
) -> dict:
    """Persist an imported message history for a chat session."""
    manager = _chat_manager_for_profile(profile_id)
    chat = await manager.repo.find_by_session_id(session_id)
    if not chat:
        chat = await manager.create_chat(
            name="Imported Chat",
            user_id="default",
            channel="web",
            session_id=session_id,
        )
    messages = [Message.model_validate(message) for message in request.messages]
    manager.replace_messages(session_id, messages)
    chat.meta.pop("context_compaction", None)
    await manager.update_chat(chat)
    return {"success": True, "session_id": session_id, "count": len(messages)}


@router.post("/files/local-attachments")
async def create_local_attachments(request: LocalAttachmentRequest) -> dict:
    """Read local files dropped into the Tauri webview and return chat attachments."""
    attachments = []
    rejected = []

    for raw_path in request.paths[:20]:
        path = Path(raw_path)
        try:
            if not path.exists() or not path.is_file():
                rejected.append({"path": raw_path, "reason": "not a file"})
                continue

            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                rejected.append({"path": raw_path, "reason": "file larger than 10MB"})
                continue

            data = path.read_bytes()
            mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            attachments.append(
                {
                    "id": f"att_{uuid.uuid4().hex[:12]}",
                    "name": path.name,
                    "mime_type": mime_type,
                    "data": base64.b64encode(data).decode("ascii"),
                    "size": size,
                }
            )
        except Exception as exc:
            rejected.append({"path": raw_path, "reason": str(exc)})

    return {"attachments": attachments, "rejected": rejected}


@router.post("/workspace/local-sources")
async def create_workspace_sources(request: WorkspaceSourceRequest) -> dict:
    """Create workspace source descriptors from local files or directories."""
    sources = []
    rejected = []
    for raw_path in request.paths[:20]:
        path = Path(raw_path)
        try:
            if not path.exists():
                rejected.append({"path": raw_path, "reason": "path does not exist"})
                continue
            sources.append(_workspace_source_from_path(path))
        except Exception as exc:
            rejected.append({"path": raw_path, "reason": str(exc)})
    return {"sources": sources, "rejected": rejected}


@router.get("/workspace/sources")
async def get_workspace_sources() -> dict:
    """Get persisted library source state."""
    state = _read_workspace_source_state()
    return state.model_dump()


@router.post("/workspace/sources")
async def save_workspace_sources(state: WorkspaceSourceState) -> dict:
    """Persist library source state under the user data directory."""
    saved = _write_workspace_source_state(state)
    return saved.model_dump()


@router.get("/agent-profiles/{profile_id}/sessions")
async def list_profile_sessions(
    profile_id: str,
    user_id: str = Query(None),
) -> dict:
    """List chat sessions for an isolated sub-agent profile."""
    manager = _chat_manager_for_profile(profile_id)
    chats = await manager.list_chats(user_id)
    return {
        "profile_id": profile_id,
        "sessions": [
            {
                "id": c.id,
                "name": c.name,
                "session_id": c.session_id,
                "user_id": c.user_id,
                "channel": c.channel,
                "meta": c.meta,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in chats
        ],
    }


@router.get("/agent-profiles/{profile_id}/runtime-events")
async def list_profile_runtime_events(
    profile_id: str,
    session_id: str = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    """List runtime events from an isolated sub-agent profile."""
    control_plane = _get_control_plane_for_profile(profile_id)
    if session_id:
        thread = control_plane.get_runtime_thread_by_session(session_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Runtime thread not found")
        events = control_plane.list_runtime_events(thread["thread_id"], limit=limit)
    else:
        threads = control_plane.list_runtime_threads(limit=20)
        events = []
        for thread in threads:
            events.extend(control_plane.list_runtime_events(thread["thread_id"], limit=limit))
        events = sorted(events, key=lambda item: item.get("created_at", ""))[-limit:]
    return {"profile_id": profile_id, "events": events}


def _workspace_source_from_path(path: Path) -> dict:
    is_dir = path.is_dir()
    stat = path.stat()
    children = _workspace_children(path) if is_dir else []
    return {
        "id": f"src_{uuid.uuid4().hex[:12]}",
        "name": path.name or str(path),
        "path": str(path),
        "type": "directory" if is_dir else "file",
        "mime_type": None if is_dir else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
        "size": None if is_dir else stat.st_size,
        "modified_at": stat.st_mtime,
        "children": children,
        "children_count": _workspace_node_count(children),
    }


def _workspace_children(path: Path, limit: int = 200) -> list[dict]:
    remaining = {"count": limit}
    return _workspace_children_nested(path, path, remaining)


def _workspace_children_nested(path: Path, root: Path, remaining: dict) -> list[dict]:
    children = []
    try:
        entries = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError:
        return children

    for child in entries:
        if remaining["count"] <= 0:
            break
        try:
            remaining["count"] -= 1
            if child.is_dir():
                nested = _workspace_children_nested(child, root, remaining)
                child_payload = {
                    "name": child.name,
                    "path": str(child),
                    "type": "directory",
                    "mime_type": None,
                    "size": None,
                    "modified_at": child.stat().st_mtime,
                    "relative_path": str(child.relative_to(root)),
                    "children": nested,
                    "children_count": _workspace_node_count(nested),
                }
            else:
                stat = child.stat()
                child_payload = {
                    "name": child.name,
                    "path": str(child),
                    "type": "file",
                    "mime_type": mimetypes.guess_type(child.name)[0] or "application/octet-stream",
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "relative_path": str(child.relative_to(root)),
                }
            children.append(child_payload)
        except OSError:
            continue
    return children


def _workspace_node_count(nodes: list[dict]) -> int:
    return sum(1 + _workspace_node_count(node.get("children") or []) for node in nodes)


@router.post("/chats/fork")
async def fork_chat(request: ForkChatRequest) -> dict:
    """Fork an existing chat session into a new task."""
    manager = _chat_manager_for_profile(request.profile_id)
    chat, copied_message_count = await manager.fork_chat(
        source_session_id=request.session_id,
        name=request.name,
        user_id=request.user_id,
        channel=request.channel,
    )

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    return {
        "chat": {
            "id": chat.id,
            "name": chat.name,
            "session_id": chat.session_id,
            "user_id": chat.user_id,
            "channel": chat.channel,
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat(),
            "meta": chat.meta,
        },
        "source_session_id": request.session_id,
        "copied_message_count": copied_message_count,
    }


@router.get("/runtime/threads")
async def list_runtime_threads(
    user_id: str = Query(None),
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """List durable runtime threads."""
    control_plane = _get_control_plane()
    return {
        "threads": control_plane.list_runtime_threads(
            user_id=user_id,
            include_archived=include_archived,
            limit=limit,
        )
    }


@router.get("/runtime/threads/session/{session_id}")
async def get_runtime_thread_by_session(session_id: str) -> dict:
    """Get the latest durable runtime thread for a chat session."""
    control_plane = _get_control_plane()
    thread = control_plane.get_runtime_thread_by_session(session_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Runtime thread not found")
    return thread


@router.get("/runtime/threads/{thread_id}")
async def get_runtime_thread(thread_id: str) -> dict:
    """Get durable runtime thread metadata."""
    control_plane = _get_control_plane()
    thread = control_plane.get_runtime_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Runtime thread not found")
    return thread


@router.get("/runtime/threads/{thread_id}/turns")
async def list_runtime_turns(
    thread_id: str,
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """List durable turns for a runtime thread."""
    control_plane = _get_control_plane()
    if not control_plane.get_runtime_thread(thread_id):
        raise HTTPException(status_code=404, detail="Runtime thread not found")
    return {"turns": control_plane.list_runtime_turns(thread_id, limit=limit)}


@router.get("/runtime/threads/{thread_id}/events")
async def list_runtime_events(
    thread_id: str,
    since_seq: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> dict:
    """Replay durable runtime events after a sequence number."""
    control_plane = _get_control_plane()
    if not control_plane.get_runtime_thread(thread_id):
        raise HTTPException(status_code=404, detail="Runtime thread not found")
    return {
        "events": control_plane.list_runtime_events(
            thread_id,
            since_seq=since_seq,
            limit=limit,
        )
    }


@router.post("/agent-sessions")
async def create_agent_session(request: CreateAgentSessionRequest) -> dict:
    """Create a chat session for the main agent or an isolated sub-agent profile."""
    from open_agent.agent_control import create_agent_session as create_profile_session

    try:
        return await create_profile_session(
            profile_id=request.profile_id,
            name=request.name,
            user_id=request.user_id,
            parent_session_id=request.parent_session_id,
            parent_task_id=request.parent_task_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agent-sessions/{session_id}/messages")
async def send_agent_session_message(session_id: str, request: AgentSessionMessageRequest):
    """Send a message to the main agent or a sub-agent profile session."""
    profile_id = request.profile_id if hasattr(request, "profile_id") else None
    if profile_id is None:
        profile_id = "main"
    run_request = RunRequest(
        session_id=session_id,
        user_id=request.user_id,
        messages=request.messages,
        stream=request.stream,
        workspace_sources=request.workspace_sources,
        selected_workspace_paths=request.selected_workspace_paths,
        tool_access_mode=request.tool_access_mode,
        profile_id=profile_id,
    )
    return await run_agent(run_request)


@router.post("/agent-tasks")
async def create_agent_task(request: AgentTaskRequest) -> dict:
    """Start an asynchronous task for a sub-agent profile."""
    from open_agent.agent_control import start_agent_task

    try:
        return await start_agent_task(
            profile_id=request.profile_id,
            instruction=request.instruction,
            user_id=request.user_id,
            parent_session_id=request.parent_session_id,
            workspace_sources=request.workspace_sources,
            selected_workspace_paths=request.selected_workspace_paths,
            tool_access_mode=request.tool_access_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agent-tasks")
async def list_agent_tasks(
    profile_id: str = Query(None),
    parent_session_id: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    from open_agent.agent_control import list_agent_tasks as list_profile_tasks

    return {
        "tasks": list_profile_tasks(
            profile_id=profile_id,
            parent_session_id=parent_session_id,
            limit=limit,
        )
    }


@router.get("/agent-tasks/{task_id}")
async def get_agent_task(task_id: str) -> dict:
    from open_agent.agent_control import get_agent_task as get_profile_task

    task = get_profile_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Agent task not found")
    return task


@router.post("/agent-tasks/{task_id}/cancel")
async def cancel_agent_task(task_id: str) -> dict:
    from open_agent.agent_control import cancel_agent_task as cancel_profile_task

    task = await cancel_profile_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Agent task not found")
    return task


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
        meta={
            "workspace_sources": request.workspace_sources,
            "selected_workspace_paths": request.selected_workspace_paths,
            "tool_access_mode": "full" if request.tool_access_mode == "full" else "default",
            "profile_id": request.profile_id or "main",
        },
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
