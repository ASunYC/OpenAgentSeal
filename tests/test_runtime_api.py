import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_agent.app.runner.api import router
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
            events_response = self.client.get(
                f"/api/runtime/threads/{thread['thread_id']}/events",
                params={"since_seq": 1},
            )

        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["thread_id"], thread["thread_id"])
        self.assertEqual(events_response.status_code, 200)
        self.assertEqual(len(events_response.json()["events"]), 1)
        self.assertEqual(events_response.json()["events"][0]["event_type"], "complete")


if __name__ == "__main__":
    unittest.main()
