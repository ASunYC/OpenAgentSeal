"""Shared service for controlling isolated agent profiles."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from open_agent.agent_profiles import MAIN_AGENT_ID, get_agent_profile_manager
from open_agent.app.runner.manager import get_chat_manager
from open_agent.app.runner.models import AgentRequest, Message


_agent_tasks: dict[str, dict[str, Any]] = {}


def _manager_profile_id(profile_id: str | None) -> str | None:
    if not profile_id or profile_id == MAIN_AGENT_ID:
        return None
    return profile_id


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in task.items() if key != "task"}


def _task_control_plane():
    from open_agent.control_plane import get_control_plane

    manager = get_agent_profile_manager()
    return get_control_plane(manager.get_agent_home(None))


def _persist_task(task: dict[str, Any]) -> dict[str, Any]:
    persisted = _task_control_plane().upsert_agent_task(
        task_id=task["task_id"],
        profile_id=task["profile_id"],
        session_id=task["session_id"],
        parent_session_id=task.get("parent_session_id"),
        status=task.get("status", "queued"),
        instruction=task.get("instruction", ""),
        result=task.get("result"),
        error=task.get("error"),
        events=task.get("events", []),
        metadata=task.get("metadata", {}),
    )
    task.update(persisted)
    return task


async def _backfill_parent_session(task: dict[str, Any]) -> None:
    parent_session_id = task.get("parent_session_id")
    if not parent_session_id or task.get("metadata", {}).get("parent_backfilled"):
        return

    parent_profile_id = task.get("metadata", {}).get("parent_profile_id")
    parent_key = None if not parent_profile_id or parent_profile_id == MAIN_AGENT_ID else parent_profile_id
    status = task.get("status")
    result = task.get("result") or ""
    error = task.get("error") or ""
    profile_id = task.get("profile_id")
    task_id = task.get("task_id")

    if status == "completed":
        content = (
            f"子智能体任务已完成。\n\n"
            f"- 角色: {profile_id}\n"
            f"- 任务: {task_id}\n\n"
            f"{result}"
        )
    elif status == "failed":
        content = (
            f"子智能体任务执行失败。\n\n"
            f"- 角色: {profile_id}\n"
            f"- 任务: {task_id}\n"
            f"- 错误: {error}"
        )
    elif status == "cancelled":
        content = (
            f"子智能体任务已取消。\n\n"
            f"- 角色: {profile_id}\n"
            f"- 任务: {task_id}"
        )
    else:
        return

    manager = get_chat_manager(parent_key)
    chat = await manager.repo.find_by_session_id(parent_session_id)
    if not chat:
        return
    manager.add_message(parent_session_id, Message(role="assistant", content=content))
    chat.meta.setdefault("agent_task_results", [])
    chat.meta["agent_task_results"].append(
        {
            "task_id": task_id,
            "profile_id": profile_id,
            "status": status,
            "session_id": task.get("session_id"),
        }
    )
    await manager.update_chat(chat)
    task.setdefault("metadata", {})["parent_backfilled"] = True
    _persist_task(task)


def list_agent_profiles(include_disabled: bool = False) -> list[dict[str, Any]]:
    manager = get_agent_profile_manager()
    agents = [manager.get_main_agent(), *manager.list_profiles(include_disabled=include_disabled)]
    return [agent.to_dict() for agent in agents if include_disabled or agent.enabled]


async def create_agent_session(
    profile_id: str | None = None,
    name: str = "New Chat",
    user_id: str = "default",
    parent_session_id: str | None = None,
    parent_task_id: str | None = None,
) -> dict[str, Any]:
    manager = get_agent_profile_manager()
    profile_key = _manager_profile_id(profile_id)
    config = manager.get_agent_config(profile_key)
    if not config or not config.enabled:
        raise ValueError(f"Agent profile is not available: {profile_id or MAIN_AGENT_ID}")

    session_prefix = "session_main" if profile_key is None else f"session_{profile_key}"
    session_id = f"{session_prefix}_{uuid.uuid4().hex[:12]}"
    chat_manager = get_chat_manager(profile_key)
    chat = await chat_manager.create_chat(
        name=name,
        user_id=user_id,
        channel="agent-profile",
        session_id=session_id,
    )
    chat.meta.update(
        {
            "profile_id": profile_id or MAIN_AGENT_ID,
            "parent_session_id": parent_session_id,
            "parent_task_id": parent_task_id,
        }
    )
    await chat_manager.update_chat(chat)
    return {
        "id": chat.id,
        "name": chat.name,
        "session_id": chat.session_id,
        "profile_id": profile_id or MAIN_AGENT_ID,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
        "meta": chat.meta,
    }


async def _consume_agent_task(task_id: str, request: AgentRequest) -> None:
    from open_agent.app.runner.runner import get_runner

    runner = get_runner()
    task_state = _agent_tasks[task_id]
    task_state["status"] = "running"
    task_state["events"] = []
    _persist_task(task_state)
    try:
        async for event in runner.process_message(request):
            payload = event.model_dump(exclude_none=True)
            task_state["events"].append(payload)
            if event.event == "complete":
                task_state["result"] = event.content
            _persist_task(task_state)
        if task_state.get("status") != "cancelled":
            task_state["status"] = "completed"
            _persist_task(task_state)
            await _backfill_parent_session(task_state)
    except asyncio.CancelledError:
        task_state["status"] = "cancelled"
        await runner.cancel_session(request.session_id)
        _persist_task(task_state)
        await _backfill_parent_session(task_state)
    except Exception as exc:
        task_state["status"] = "failed"
        task_state["error"] = str(exc)
        _persist_task(task_state)
        await _backfill_parent_session(task_state)


async def start_agent_task(
    profile_id: str,
    instruction: str,
    user_id: str = "default",
    parent_session_id: str | None = None,
    parent_profile_id: str | None = None,
    workspace_sources: list[dict[str, Any]] | None = None,
    selected_workspace_paths: list[str] | None = None,
    tool_access_mode: str = "default",
) -> dict[str, Any]:
    profile_key = _manager_profile_id(profile_id)
    if profile_key is None:
        raise ValueError("Sub-agent task requires a profile_id, not main")

    manager = get_agent_profile_manager()
    config = manager.get_agent_config(profile_key)
    if not config or not config.enabled:
        raise ValueError(f"Agent profile is not available: {profile_id}")

    task_id = f"task_{uuid.uuid4().hex[:12]}"
    session_id = f"session_{profile_key}_{uuid.uuid4().hex[:12]}"
    chat_manager = get_chat_manager(profile_key)
    chat = await chat_manager.create_chat(
        name=instruction[:48] or "Agent Task",
        user_id=user_id,
        channel="agent-task",
        session_id=session_id,
    )
    chat.meta.update(
        {
            "profile_id": profile_key,
            "parent_session_id": parent_session_id,
            "parent_task_id": task_id,
            "created_by": "main-agent" if parent_session_id else "user",
            "status": "queued",
        }
    )
    await chat_manager.update_chat(chat)

    request = AgentRequest(
        session_id=session_id,
        user_id=user_id,
        messages=[{"role": "user", "content": instruction}],
        stream=False,
        meta={
            "workspace_sources": workspace_sources or [],
            "selected_workspace_paths": selected_workspace_paths or [],
            "tool_access_mode": "full" if tool_access_mode == "full" else "default",
            "profile_id": profile_key,
            "parent_session_id": parent_session_id,
            "task_id": task_id,
        },
    )
    _agent_tasks[task_id] = {
        "task_id": task_id,
        "session_id": session_id,
        "profile_id": profile_key,
        "parent_session_id": parent_session_id,
        "instruction": instruction,
        "status": "queued",
        "result": None,
        "error": None,
        "events": [],
        "metadata": {
            "parent_profile_id": parent_profile_id or MAIN_AGENT_ID,
            "tool_access_mode": "full" if tool_access_mode == "full" else "default",
        },
    }
    _persist_task(_agent_tasks[task_id])
    _agent_tasks[task_id]["task"] = asyncio.create_task(_consume_agent_task(task_id, request))
    return _public_task(_agent_tasks[task_id])


def get_agent_task(task_id: str) -> dict[str, Any] | None:
    task = _agent_tasks.get(task_id)
    if task:
        return _public_task(task)
    return _task_control_plane().get_agent_task(task_id)


def list_agent_tasks(
    profile_id: str | None = None,
    parent_session_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return _task_control_plane().list_agent_tasks(
        profile_id=profile_id,
        parent_session_id=parent_session_id,
        limit=limit,
    )


async def cancel_agent_task(task_id: str) -> dict[str, Any] | None:
    from open_agent.app.runner.runner import get_runner

    task = _agent_tasks.get(task_id)
    if not task:
        persisted = _task_control_plane().get_agent_task(task_id)
        if not persisted:
            return None
        if persisted.get("status") not in {"queued", "running"}:
            return persisted
        persisted["status"] = "cancelled"
        return _task_control_plane().upsert_agent_task(
            task_id=persisted["task_id"],
            profile_id=persisted["profile_id"],
            session_id=persisted["session_id"],
            parent_session_id=persisted.get("parent_session_id"),
            status="cancelled",
            instruction=persisted.get("instruction", ""),
            result=persisted.get("result"),
            error=persisted.get("error"),
            events=persisted.get("events", []),
            metadata=persisted.get("metadata", {}),
        )
    task["status"] = "cancelled"
    await get_runner().cancel_session(task["session_id"])
    async_task = task.get("task")
    if async_task and not async_task.done():
        async_task.cancel()
    _persist_task(task)
    await _backfill_parent_session(task)
    return _public_task(task)
