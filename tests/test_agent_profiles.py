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


@pytest.mark.asyncio
async def test_delivery_failure_cannot_reclassify_successful_agent_execution(
    monkeypatch, tmp_path
):
    _isolate_home(monkeypatch, tmp_path)

    import open_agent.agent_control as agent_control
    from open_agent.app.runner.models import AgentEvent, AgentRequest
    import open_agent.app.runner.runner as runner_module

    task_id = "task_delivery_failure"
    task = {
        "task_id": task_id,
        "profile_id": "writer",
        "session_id": "session_writer_child",
        "parent_session_id": "session_main_parent",
        "status": "queued",
        "result": None,
        "error": None,
        "events": [],
        "instruction": "Write",
        "metadata": {"parent_profile_id": "main"},
    }
    agent_control._agent_tasks[task_id] = task

    class Runner:
        async def process_message(self, request):
            yield AgentEvent(
                event="complete", session_id=request.session_id, content="Done"
            )

    observed_statuses = []

    async def failing_delivery(task_state):
        observed_statuses.append(task_state["status"])
        raise RuntimeError("delivery database unavailable")

    monkeypatch.setattr(runner_module, "get_runner", lambda: Runner())
    monkeypatch.setattr(agent_control, "_persist_task", lambda state: state)
    monkeypatch.setattr(agent_control, "_backfill_parent_session", failing_delivery)

    await agent_control._consume_agent_task(
        task_id,
        AgentRequest(session_id=task["session_id"], messages=[]),
    )

    assert task["status"] == "completed"
    assert task["result"] == "Done"
    assert task["error"] is None
    assert observed_statuses == ["completed"]


@pytest.mark.asyncio
async def test_post_commit_delivery_failure_leaves_completed_task_and_outbox(
    monkeypatch, tmp_path
):
    profiles = _isolate_home(monkeypatch, tmp_path)
    profiles.get_agent_profile_manager().create_profile({"id": "writer", "name": "Writer"})

    import open_agent.agent_control as agent_control
    from open_agent.app.runner.manager import get_chat_manager
    from open_agent.app.runner.models import AgentEvent, AgentRequest
    import open_agent.app.runner.runner as runner_module
    from open_agent.durable_runtime.delivery import DeliveryWorker
    from open_agent.durable_runtime.repository import DurableRuntimeRepository

    parent_manager = get_chat_manager()
    await parent_manager.create_chat(
        name="Parent",
        user_id="default",
        channel="web",
        session_id="session_main_parent",
    )
    task_id = "task_post_commit_delivery_failure"
    task = {
        "task_id": task_id,
        "profile_id": "writer",
        "session_id": "session_writer_child",
        "parent_session_id": "session_main_parent",
        "status": "queued",
        "result": None,
        "error": None,
        "events": [],
        "instruction": "Write",
        "metadata": {"parent_profile_id": "main"},
    }
    agent_control._agent_tasks[task_id] = task

    class Runner:
        async def process_message(self, request):
            yield AgentEvent(
                event="complete", session_id=request.session_id, content="Done"
            )

    async def fail_after_terminal_commit(self, now):
        raise RuntimeError("delivery worker unavailable")

    monkeypatch.setattr(runner_module, "get_runner", lambda: Runner())
    monkeypatch.setattr(DeliveryWorker, "run_once", fail_after_terminal_commit)

    await agent_control._consume_agent_task(
        task_id,
        AgentRequest(session_id=task["session_id"], messages=[]),
    )

    control_plane = agent_control._task_control_plane()
    stored_task = control_plane.get_agent_task(task_id)
    repository = DurableRuntimeRepository(control_plane)
    assert stored_task["status"] == "completed"
    assert stored_task["error"] is None
    assert repository.list_outbox()[0].state == "pending"
