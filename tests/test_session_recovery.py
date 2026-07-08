from types import SimpleNamespace

from open_agent.app.runner.manager import ChatManager
from open_agent.app.runner.models import Message
from open_agent.app.runner.runner import AgentRunner
from open_agent.control_plane import ControlPlane
from open_agent.schema import Message as AgentMessage


def test_restore_agent_history_recovers_assistant_from_runtime_events(tmp_path):
    manager = ChatManager(storage_dir=tmp_path / "sessions")
    manager.replace_messages(
        "session-recover",
        [Message(id="u1", role="user", content="hello")],
    )
    agent = SimpleNamespace(
        system_prompt="system",
        messages=[AgentMessage(role="system", content="system")],
    )

    AgentRunner()._restore_agent_history(
        agent,
        "session-recover",
        manager,
        runtime_events=[
            {
                "event_type": "message",
                "payload": {"content": "partial "},
                "turn_id": "turn_1",
            },
            {
                "event_type": "message",
                "payload": {"content": "answer"},
                "turn_id": "turn_1",
            },
        ],
    )

    assert [message.role for message in agent.messages] == [
        "system",
        "user",
        "assistant",
    ]
    assert agent.messages[-1].content == "partial answer"


def test_restore_agent_history_does_not_duplicate_persisted_assistant(tmp_path):
    manager = ChatManager(storage_dir=tmp_path / "sessions")
    manager.replace_messages(
        "session-no-duplicate",
        [
            Message(id="u1", role="user", content="hello"),
            Message(id="a1", role="assistant", content="done"),
        ],
    )
    agent = SimpleNamespace(
        system_prompt="system",
        messages=[AgentMessage(role="system", content="system")],
    )

    AgentRunner()._restore_agent_history(
        agent,
        "session-no-duplicate",
        manager,
        runtime_events=[
            {
                "event_type": "complete",
                "payload": {"content": "done"},
                "turn_id": "turn_1",
            }
        ],
    )

    assert [message.role for message in agent.messages] == [
        "system",
        "user",
        "assistant",
    ]


def test_latest_runtime_events_for_session_returns_only_latest_turn(tmp_path):
    control_plane = ControlPlane(tmp_path / "control")
    try:
        thread = control_plane.create_runtime_thread(
            session_id="session-latest",
            user_id="user",
            title="latest",
        )
        old_turn = control_plane.start_runtime_turn(
            thread["thread_id"],
            user_input="old",
            turn_id="turn_old",
        )
        control_plane.append_runtime_event(
            thread["thread_id"],
            turn_id=old_turn["turn_id"],
            event_type="message",
            payload={"content": "old"},
        )
        latest_turn = control_plane.start_runtime_turn(
            thread["thread_id"],
            user_input="new",
            turn_id="turn_new",
        )
        control_plane.append_runtime_event(
            thread["thread_id"],
            turn_id=latest_turn["turn_id"],
            event_type="message",
            payload={"content": "new"},
        )

        events = AgentRunner()._latest_runtime_events_for_session(
            control_plane,
            "session-latest",
        )
    finally:
        control_plane.close()

    assert [event["turn_id"] for event in events] == ["turn_new"]
    assert events[0]["payload"]["content"] == "new"
