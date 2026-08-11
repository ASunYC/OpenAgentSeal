import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_agent.app.runner.api import router
from open_agent.app.runner.models import AgentEvent, AgentRequest
from open_agent.app.runner.runner import AgentRunner
from open_agent.control_plane import ControlPlane


class TestRuntimeApi(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.control_plane = ControlPlane(self.temp_dir.name)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.control_plane.close()
        self.temp_dir.cleanup()

    def test_runtime_thread_event_replay_endpoints(self):
        thread = self.control_plane.create_runtime_thread(
            session_id="session_api",
            user_id="user_1",
            title="API replay",
        )
        turn = self.control_plane.start_runtime_turn(thread["thread_id"], user_input="hello")
        self.control_plane.append_runtime_event(
            thread["thread_id"],
            turn_id=turn["turn_id"],
            event_type="run_start",
            payload={"status": "running"},
        )
        self.control_plane.append_runtime_event(
            thread["thread_id"],
            turn_id=turn["turn_id"],
            event_type="complete",
            payload={"status": "idle"},
        )

        with patch("open_agent.app.runner.api._get_control_plane", return_value=self.control_plane):
            session_response = self.client.get("/api/runtime/threads/session/session_api")
            threads_response = self.client.get("/api/runtime/threads")
            events_response = self.client.get(
                f"/api/runtime/threads/{thread['thread_id']}/events",
                params={"since_seq": 1},
            )

        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["thread_id"], thread["thread_id"])
        self.assertEqual(threads_response.json()["threads"][0]["latest_turn_status"], "running")
        self.assertEqual(events_response.status_code, 200)
        self.assertEqual(len(events_response.json()["events"]), 1)
        self.assertEqual(events_response.json()["events"][0]["event_type"], "complete")

    def test_runtime_turn_metadata_records_expanded_references_without_attachment_data(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            (root / "nested").mkdir()
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "nested" / "b.md").write_text("b", encoding="utf-8")
            request = AgentRequest(
                session_id="session_refs",
                messages=[{
                    "role": "user",
                    "content": "inspect",
                    "attachments": [{
                        "id": "attachment-1",
                        "name": "notes.md",
                        "mime_type": "text/markdown",
                        "size": 12,
                        "data": "c2VjcmV0",
                    }],
                }],
                meta={"selected_workspace_paths": [workspace]},
            )

            metadata = AgentRunner()._runtime_turn_metadata(
                request,
                agent_id="main",
                profile_id="main",
                tool_access_mode="default",
            )

        reference_paths = {item["path"] for item in metadata["workspace_references"]}
        self.assertEqual(reference_paths, {str(root / "a.txt"), str(root / "nested" / "b.md")})
        self.assertTrue(all(item["modified_at"] > 0 for item in metadata["workspace_references"]))
        self.assertEqual(metadata["attachments"][0]["name"], "notes.md")
        self.assertNotIn("data", metadata["attachments"][0])

    def test_memory_recall_excludes_already_injected_memories(self):
        memory_manager = Mock()
        memory_manager.recall.return_value = [
            SimpleNamespace(id=1, content="already used", category="decision", importance="high"),
            SimpleNamespace(id=2, content="use the verified route", category="knowledge", importance="normal"),
        ]

        with patch("open_agent.memory_manager.get_memory_manager", return_value=memory_manager):
            context, references = AgentRunner()._recall_memory_context("provider route", {1})

        self.assertNotIn("already used", context)
        self.assertIn("use the verified route", context)
        self.assertEqual([item["id"] for item in references], [2])

if __name__ == "__main__":
    unittest.main()


def test_runtime_turn_metadata_preserves_durable_source_event_key():
    request = AgentRequest(
        session_id="session_gateway",
        messages=[{"role": "user", "content": "hello"}],
        meta={"source_event_key": '["account-1","event-1"]'},
    )

    metadata = AgentRunner()._runtime_turn_metadata(
        request,
        agent_id="main",
        profile_id="main",
        tool_access_mode="default",
    )

    assert metadata["source_event_key"] == '["account-1","event-1"]'


async def test_run_stream_reuses_process_message_instead_of_creating_an_agent_loop():
    runner = AgentRunner()
    request = AgentRequest(
        session_id="session_gateway",
        messages=[{"role": "user", "content": "hello"}],
    )
    turn = {"turn_id": "turn-existing", "thread_id": "thread-existing"}
    observed = []

    async def fake_process_message(received, *, runtime_turn=None):
        observed.append((received, runtime_turn))
        yield AgentEvent(event="complete", session_id=received.session_id)

    runner.process_message = fake_process_message
    emitted = [event async for event in runner.run_stream(request, runtime_turn=turn)]

    assert [event.event for event in emitted] == ["complete"]
    assert observed == [(request, turn)]
