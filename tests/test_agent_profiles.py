import json
from pathlib import Path

import pytest


def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    import open_agent.agent_profiles as agent_profiles
    import open_agent.app.runner.manager as chat_manager
    import open_agent.control_plane as control_plane

    agent_profiles._profile_manager = None
    chat_manager._chat_manager = None
    chat_manager._scoped_chat_managers.clear()
    control_plane._control_planes.clear()
    return agent_profiles


def test_agent_profile_manager_creates_isolated_main_and_profile_homes(monkeypatch, tmp_path):
    agent_profiles = _isolate_home(monkeypatch, tmp_path)

    manager = agent_profiles.AgentProfileManager()
    profile = manager.create_profile({"id": "researcher", "name": "Researcher"})

    main_home = tmp_path / ".open-agent" / "data" / "main-agent"
    profile_home = tmp_path / ".open-agent" / "data" / "agents" / "profiles" / "researcher"

    assert manager.get_agent_home(None) == main_home
    assert manager.get_agent_home("researcher") == profile_home
    assert manager.get_main_agent().allow_delegation is True
    assert profile.allow_delegation is False
    for child in ("memory", "sessions", "logs", "workspace", "artifacts", "skills"):
        assert (main_home / child).is_dir()
        assert (profile_home / child).is_dir()


def test_scoped_chat_managers_write_to_agent_session_dirs(monkeypatch, tmp_path):
    _isolate_home(monkeypatch, tmp_path)

    from open_agent.app.runner.manager import get_chat_manager

    main_manager = get_chat_manager()
    profile_manager = get_chat_manager("researcher")

    assert main_manager.repo.storage_dir == tmp_path / ".open-agent" / "data" / "main-agent" / "sessions"
    assert profile_manager.repo.storage_dir == tmp_path / ".open-agent" / "data" / "agents" / "profiles" / "researcher" / "sessions"


@pytest.mark.asyncio
async def test_agent_control_tools_list_profiles_from_profile_manager(monkeypatch, tmp_path):
    agent_profiles = _isolate_home(monkeypatch, tmp_path)
    manager = agent_profiles.get_agent_profile_manager()
    manager.create_profile({"id": "writer", "name": "Writer", "description": "Drafts text"})

    from open_agent.tools.agent_control_tool import ListAgentProfilesTool

    result = await ListAgentProfilesTool().execute()
    payload = json.loads(result.content)

    assert result.success is True
    assert [item["id"] for item in payload] == ["main", "writer"]
    assert payload[0]["allow_delegation"] is True
    assert payload[1]["allow_delegation"] is False


def test_agent_task_index_is_persisted_in_main_runtime_db(monkeypatch, tmp_path):
    agent_profiles = _isolate_home(monkeypatch, tmp_path)
    manager = agent_profiles.get_agent_profile_manager()
    manager.create_profile({"id": "writer", "name": "Writer"})

    from open_agent.control_plane import get_control_plane

    control_plane = get_control_plane(manager.get_agent_home(None))
    saved = control_plane.upsert_agent_task(
        task_id="task_test",
        profile_id="writer",
        session_id="session_writer_test",
        parent_session_id="session_main_parent",
        instruction="Draft a summary",
        status="completed",
        result="Done",
        events=[{"event": "complete", "content": "Done"}],
        metadata={"parent_profile_id": "main"},
    )
    loaded = control_plane.get_agent_task("task_test")

    assert saved["task_id"] == "task_test"
    assert loaded["status"] == "completed"
    assert loaded["events"][0]["event"] == "complete"
    assert (manager.get_agent_home(None) / "runtime.db").exists()


@pytest.mark.asyncio
async def test_completed_agent_task_backfills_parent_session(monkeypatch, tmp_path):
    agent_profiles = _isolate_home(monkeypatch, tmp_path)
    manager = agent_profiles.get_agent_profile_manager()
    manager.create_profile({"id": "writer", "name": "Writer"})

    from open_agent.agent_control import _backfill_parent_session
    from open_agent.app.runner.manager import get_chat_manager

    parent_manager = get_chat_manager()
    await parent_manager.create_chat(
        name="Parent",
        user_id="default",
        channel="web",
        session_id="session_main_parent",
    )
    task = {
        "task_id": "task_writer_done",
        "profile_id": "writer",
        "session_id": "session_writer_child",
        "parent_session_id": "session_main_parent",
        "status": "completed",
        "result": "Writer result",
        "error": None,
        "events": [],
        "instruction": "Write",
        "metadata": {"parent_profile_id": "main"},
    }

    await _backfill_parent_session(task)
    messages = parent_manager.get_messages("session_main_parent")

    assert messages[-1].role == "assistant"
    assert "Writer result" in messages[-1].content
    assert task["metadata"]["parent_backfilled"] is True
