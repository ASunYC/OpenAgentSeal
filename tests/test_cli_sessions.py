from pathlib import Path

import pytest

from open_agent.cli_sessions import CliSessionController
from open_agent.schema import Message


class FakeAgent:
    def __init__(self):
        self.messages = [Message(role="system", content="system")]
        self.session_id = ""
        self.profile_id = "main"
        self.api_total_tokens = 0
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_total_tokens = 0

    def reset_session_usage(self):
        self.api_total_tokens = 0
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_total_tokens = 0


def _isolate_sessions(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    import open_agent.agent_profiles as agent_profiles
    import open_agent.app.runner.manager as chat_manager

    agent_profiles._profile_manager = None
    chat_manager._chat_manager = None
    chat_manager._scoped_chat_managers.clear()


@pytest.mark.asyncio
async def test_cli_session_restores_history_and_usage(monkeypatch, tmp_path):
    _isolate_sessions(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first_agent = FakeAgent()
    first = CliSessionController(
        profile_id="main",
        workspace=workspace,
        launch_source="test",
        prefer_api=False,
    )

    assert await first.initialize(first_agent) == 0
    original_session_id = first_agent.session_id
    first_agent.messages.append(Message(role="user", content="hello"))
    await first.persist_user("hello", first_agent)
    first_agent.messages.append(Message(role="assistant", content="welcome back"))
    first_agent.session_prompt_tokens = 100
    first_agent.session_completion_tokens = 20
    first_agent.session_total_tokens = 120
    await first.persist_assistant("welcome back", first_agent)

    second_agent = FakeAgent()
    second = CliSessionController(
        profile_id="main",
        workspace=workspace,
        launch_source="test",
        prefer_api=False,
    )

    assert await second.initialize(second_agent) == 2
    assert second_agent.session_id == original_session_id
    assert [message.content for message in second_agent.messages[1:]] == [
        "hello",
        "welcome back",
    ]
    assert second_agent.session_total_tokens == 120
    assert second_agent.session_prompt_tokens == 100
    assert second_agent.session_completion_tokens == 20


@pytest.mark.asyncio
async def test_cli_new_and_resume_manage_distinct_persisted_sessions(monkeypatch, tmp_path):
    _isolate_sessions(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = FakeAgent()
    controller = CliSessionController(
        profile_id="main",
        workspace=workspace,
        launch_source="test",
        prefer_api=False,
    )
    await controller.initialize(agent)
    original_session_id = agent.session_id
    agent.messages.append(Message(role="user", content="keep me"))
    await controller.persist_user("keep me", agent)

    new_session_id = await controller.create_new(agent)
    assert new_session_id != original_session_id
    assert len(agent.messages) == 1

    sessions = await controller.list_sessions()
    assert {item.session_id for item in sessions} == {original_session_id, new_session_id}

    restored = await controller.resume(agent, original_session_id)
    assert restored == 1
    assert agent.session_id == original_session_id
    assert agent.messages[-1].content == "keep me"


@pytest.mark.asyncio
async def test_chat_api_accepts_cli_session_identity_and_metadata(monkeypatch, tmp_path):
    _isolate_sessions(monkeypatch, tmp_path)
    from open_agent.app.runner.api import (
        CreateChatRequest,
        PersistMessagesRequest,
        create_chat,
        persist_chat_messages,
    )
    from open_agent.app.runner.manager import get_chat_manager

    created = await create_chat(
        CreateChatRequest(
            name="CLI - workspace",
            channel="cli",
            session_id="cli_main_fixed",
            profile_id="main",
            meta={"workspace_key": "d:/workspace"},
        )
    )
    assert created["session_id"] == "cli_main_fixed"
    assert created["channel"] == "cli"
    assert created["meta"]["workspace_key"] == "d:/workspace"

    result = await persist_chat_messages(
        "cli_main_fixed",
        PersistMessagesRequest(
            messages=[{"role": "user", "content": "persisted"}],
            meta={"cli_total_tokens": 42},
        ),
        profile_id="main",
    )
    chat = await get_chat_manager().repo.find_by_session_id("cli_main_fixed")

    assert result["count"] == 1
    assert chat is not None
    assert chat.meta["cli_total_tokens"] == 42
    assert get_chat_manager().get_messages("cli_main_fixed")[0].content == "persisted"
