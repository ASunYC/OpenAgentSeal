"""Persistent CLI sessions backed by the desktop chat repository."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from open_agent.app.runner.models import Message as StoredMessage
from open_agent.schema import Message as AgentMessage


@dataclass(frozen=True)
class CliSessionSummary:
    id: str
    session_id: str
    name: str
    updated_at: str


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")


class CliSessionController:
    """Keep CLI history in the same storage and API used by desktop chats."""

    def __init__(
        self,
        *,
        profile_id: str,
        workspace: Path,
        launch_source: str,
        api_base: str | None = None,
        prefer_api: bool = True,
    ):
        self.profile_id = profile_id or "main"
        self.workspace = workspace.resolve()
        self.launch_source = launch_source or "terminal"
        self.api_base = (
            api_base
            or os.environ.get("OPEN_AGENT_API_BASE", "").strip()
            or "http://127.0.0.1:9998"
        ).rstrip("/")
        self.prefer_api = prefer_api
        self.using_desktop_api = False
        self.current_chat: dict[str, Any] | None = None
        self._stored_messages: list[StoredMessage] = []

    @property
    def session_id(self) -> str:
        return str((self.current_chat or {}).get("session_id") or "")

    @property
    def workspace_key(self) -> str:
        value = str(self.workspace)
        return value.casefold() if os.name == "nt" else value

    async def initialize(self, agent, requested_session_id: str = "") -> int:
        self.using_desktop_api = self.prefer_api and await self._desktop_api_available()
        chats = await self._list_chat_dicts()
        selected = None
        if requested_session_id:
            selected = next(
                (
                    chat
                    for chat in chats
                    if chat.get("session_id") == requested_session_id
                ),
                None,
            )
        else:
            selected = next(
                (
                    chat
                    for chat in chats
                    if chat.get("channel") == "cli"
                    and self._chat_workspace_key(chat) == self.workspace_key
                ),
                None,
            )

        if selected is None:
            selected = await self._create_chat(requested_session_id)
        return await self._activate(agent, selected)

    async def create_new(self, agent) -> str:
        chat = await self._create_chat("")
        await self._activate(agent, chat)
        agent.reset_session_usage()
        return self.session_id

    async def list_sessions(self, limit: int = 20) -> list[CliSessionSummary]:
        chats = await self._list_chat_dicts()
        matches = [
            chat
            for chat in chats
            if chat.get("channel") == "cli"
            and self._chat_workspace_key(chat) == self.workspace_key
        ][:limit]
        summaries: list[CliSessionSummary] = []
        for chat in matches:
            summaries.append(
                CliSessionSummary(
                    id=str(chat.get("id") or ""),
                    session_id=str(chat.get("session_id") or ""),
                    name=str(chat.get("name") or "CLI Session"),
                    updated_at=str(chat.get("updated_at") or ""),
                )
            )
        return summaries

    async def resume(self, agent, reference: str) -> int:
        reference = reference.strip()
        if not reference:
            raise ValueError("session id is required")
        chats = await self._list_chat_dicts()
        exact = [
            chat
            for chat in chats
            if reference in {str(chat.get("id") or ""), str(chat.get("session_id") or "")}
        ]
        candidates = exact or [
            chat
            for chat in chats
            if str(chat.get("id") or "").startswith(reference)
            or str(chat.get("session_id") or "").startswith(reference)
        ]
        candidates = [
            chat
            for chat in candidates
            if chat.get("channel") == "cli"
            and self._chat_workspace_key(chat) == self.workspace_key
        ]
        if not candidates:
            raise ValueError(f"CLI session '{reference}' was not found in this workspace")
        if len(candidates) > 1:
            raise ValueError(f"session reference '{reference}' is ambiguous")
        return await self._activate(agent, candidates[0])

    async def persist_user(self, content: str, agent) -> None:
        self._stored_messages.append(StoredMessage(role="user", content=content))
        await self._sync(agent)

    async def persist_assistant(self, content: str, agent) -> None:
        if not content:
            return
        self._stored_messages.append(StoredMessage(role="assistant", content=content))
        await self._sync(agent)

    async def replace_from_agent(self, agent) -> None:
        messages: list[StoredMessage] = []
        for message in agent.messages:
            content = _content_text(message.content)
            if message.role in {"user", "assistant"} and content:
                messages.append(StoredMessage(role=message.role, content=content))
        self._stored_messages = messages
        await self._sync(agent)

    async def _activate(self, agent, chat: dict[str, Any]) -> int:
        self.current_chat = chat
        self._stored_messages = await self._load_messages(chat)
        system_message = agent.messages[0]
        agent.messages = [system_message]
        for message in self._stored_messages:
            content = _content_text(message.content)
            if message.role in {"user", "assistant"} and content:
                agent.messages.append(AgentMessage(role=message.role, content=content))
        agent.session_id = self.session_id
        agent.profile_id = self.profile_id
        meta = chat.get("meta") if isinstance(chat.get("meta"), dict) else {}
        agent.session_prompt_tokens = max(0, int(meta.get("cli_prompt_tokens") or 0))
        agent.session_completion_tokens = max(0, int(meta.get("cli_completion_tokens") or 0))
        agent.session_total_tokens = max(0, int(meta.get("cli_total_tokens") or 0))
        agent.api_total_tokens = 0
        return len(self._stored_messages)

    async def _sync(self, agent) -> None:
        if not self.current_chat:
            return
        meta = self._session_meta(agent)
        if self.using_desktop_api:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(
                        f"{self.api_base}/api/chats/session/{self.session_id}/messages",
                        params={"profile_id": self.profile_id},
                        json={
                            "messages": [
                                message.model_dump(mode="json")
                                for message in self._stored_messages
                            ],
                            "meta": meta,
                        },
                    )
                    response.raise_for_status()
                self.current_chat.setdefault("meta", {}).update(meta)
                return
            except Exception:
                self.using_desktop_api = False

        manager = self._local_manager()
        manager.replace_messages(self.session_id, self._stored_messages)
        local_chat = await manager.repo.find_by_session_id(self.session_id)
        if local_chat:
            local_chat.meta.update(meta)
            await manager.update_chat(local_chat)
            self.current_chat = local_chat.model_dump(mode="json")

    async def _desktop_api_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=0.8) as client:
                response = await client.get(f"{self.api_base}/api/health")
            return response.is_success
        except Exception:
            return False

    async def _list_chat_dicts(self) -> list[dict[str, Any]]:
        if self.using_desktop_api:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(
                        f"{self.api_base}/api/chats",
                        params={"profile_id": self.profile_id},
                    )
                    response.raise_for_status()
                    return list(response.json())
            except Exception:
                self.using_desktop_api = False
        chats = await self._local_manager().list_chats()
        return [chat.model_dump(mode="json") for chat in chats]

    async def _create_chat(self, requested_session_id: str) -> dict[str, Any]:
        session_id = requested_session_id or f"cli_{self.profile_id}_{uuid.uuid4().hex[:12]}"
        payload = {
            "name": f"CLI - {self.workspace.name or 'Workspace'}",
            "user_id": "default",
            "channel": "cli",
            "session_id": session_id,
            "profile_id": self.profile_id,
            "meta": self._session_meta(None),
        }
        if self.using_desktop_api:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.post(f"{self.api_base}/api/chats", json=payload)
                    response.raise_for_status()
                    return dict(response.json())
            except Exception:
                self.using_desktop_api = False

        manager = self._local_manager()
        chat = await manager.create_chat(
            name=payload["name"],
            user_id="default",
            channel="cli",
            session_id=session_id,
        )
        chat.meta.update(payload["meta"])
        await manager.update_chat(chat)
        return chat.model_dump(mode="json")

    async def _load_messages(self, chat: dict[str, Any]) -> list[StoredMessage]:
        if self.using_desktop_api:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(
                        f"{self.api_base}/api/chats/{chat['id']}/history",
                        params={"profile_id": self.profile_id},
                    )
                    response.raise_for_status()
                    return [
                        StoredMessage.model_validate(message)
                        for message in response.json().get("messages", [])
                    ]
            except Exception:
                self.using_desktop_api = False
        return list(self._local_manager().get_messages(str(chat.get("session_id") or "")))

    def _session_meta(self, agent) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "workspace_key": self.workspace_key,
            "launch_source": self.launch_source,
            "profile_id": self.profile_id,
            "cli_prompt_tokens": int(getattr(agent, "session_prompt_tokens", 0) or 0),
            "cli_completion_tokens": int(
                getattr(agent, "session_completion_tokens", 0) or 0
            ),
            "cli_total_tokens": int(getattr(agent, "session_total_tokens", 0) or 0),
        }

    def _chat_workspace_key(self, chat: dict[str, Any]) -> str:
        meta = chat.get("meta") if isinstance(chat.get("meta"), dict) else {}
        key = str(meta.get("workspace_key") or meta.get("workspace") or "")
        return key.casefold() if os.name == "nt" else key

    def _local_manager(self):
        from open_agent.app.runner.manager import get_chat_manager

        return get_chat_manager(None if self.profile_id == "main" else self.profile_id)


__all__ = ["CliSessionController", "CliSessionSummary"]
