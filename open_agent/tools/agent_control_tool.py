"""Tools for coordinating isolated agent profiles."""

from __future__ import annotations

import json
from typing import Any

from open_agent.agent_control import (
    cancel_agent_task,
    get_agent_task,
    list_agent_profiles,
    start_agent_task,
)

from .base import Tool, ToolResult


class ListAgentProfilesTool(Tool):
    @property
    def name(self) -> str:
        return "list_agent_profiles"

    @property
    def description(self) -> str:
        return (
            "List available agent profiles. Use this before delegating work to a sub-agent "
            "or when the user asks which roles/agents are available."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_disabled": {
                    "type": "boolean",
                    "description": "Whether to include disabled profiles.",
                    "default": False,
                }
            },
        }

    async def execute(self, include_disabled: bool = False) -> ToolResult:
        agents = list_agent_profiles(include_disabled=include_disabled)
        visible = [
            {
                "id": agent.get("id"),
                "name": agent.get("name"),
                "description": agent.get("description"),
                "model_id": agent.get("model_id"),
                "enabled": agent.get("enabled", True),
                "allow_delegation": agent.get("allow_delegation", False),
            }
            for agent in agents
        ]
        return ToolResult(success=True, content=json.dumps(visible, ensure_ascii=False, indent=2))


class StartAgentTaskTool(Tool):
    def __init__(self, parent_session_id: str | None = None, parent_profile_id: str | None = None):
        self.parent_session_id = parent_session_id
        self.parent_profile_id = parent_profile_id

    @property
    def name(self) -> str:
        return "start_agent_task"

    @property
    def description(self) -> str:
        return (
            "Start an asynchronous task for a specific sub-agent profile. "
            "Use this when the user asks a role/agent to handle part of the work."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "profile_id": {
                    "type": "string",
                    "description": "The target sub-agent profile id. Use list_agent_profiles if unsure.",
                },
                "instruction": {
                    "type": "string",
                    "description": "The complete instruction for the sub-agent.",
                },
                "parent_session_id": {
                    "type": "string",
                    "description": "Optional parent session id for traceability.",
                },
                "tool_access_mode": {
                    "type": "string",
                    "enum": ["default", "full"],
                    "description": "Permission mode for this delegated task.",
                    "default": "default",
                },
            },
            "required": ["profile_id", "instruction"],
        }

    async def execute(
        self,
        profile_id: str,
        instruction: str,
        parent_session_id: str | None = None,
        tool_access_mode: str = "default",
    ) -> ToolResult:
        try:
            task = await start_agent_task(
                profile_id=profile_id,
                instruction=instruction,
                parent_session_id=parent_session_id or self.parent_session_id,
                parent_profile_id=self.parent_profile_id,
                tool_access_mode=tool_access_mode,
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), content=str(exc))
        return ToolResult(success=True, content=json.dumps(task, ensure_ascii=False, indent=2))


class GetAgentTaskTool(Tool):
    @property
    def name(self) -> str:
        return "get_agent_task"

    @property
    def description(self) -> str:
        return "Get the current status, events, and result of a delegated sub-agent task."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task id returned by start_agent_task.",
                }
            },
            "required": ["task_id"],
        }

    async def execute(self, task_id: str) -> ToolResult:
        task = get_agent_task(task_id)
        if not task:
            return ToolResult(success=False, error="Agent task not found", content="Agent task not found")
        return ToolResult(success=True, content=json.dumps(task, ensure_ascii=False, indent=2))


class CancelAgentTaskTool(Tool):
    @property
    def name(self) -> str:
        return "cancel_agent_task"

    @property
    def description(self) -> str:
        return "Cancel a running delegated sub-agent task."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task id returned by start_agent_task.",
                }
            },
            "required": ["task_id"],
        }

    async def execute(self, task_id: str) -> ToolResult:
        task = await cancel_agent_task(task_id)
        if not task:
            return ToolResult(success=False, error="Agent task not found", content="Agent task not found")
        return ToolResult(success=True, content=json.dumps(task, ensure_ascii=False, indent=2))


def create_agent_control_tools(
    can_delegate: bool = True,
    parent_session_id: str | None = None,
    parent_profile_id: str | None = None,
) -> list[Tool]:
    tools: list[Tool] = [ListAgentProfilesTool()]
    if can_delegate:
        tools.extend(
            [
                StartAgentTaskTool(parent_session_id=parent_session_id, parent_profile_id=parent_profile_id),
                GetAgentTaskTool(),
                CancelAgentTaskTool(),
            ]
        )
    return tools
