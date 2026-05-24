import tempfile
import unittest
from pathlib import Path

from open_agent.control_plane import ControlPlane


class TestControlPlane(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ControlPlane(self.temp_dir.name)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_session_messages_and_metadata_persist(self):
        session = self.store.create_session(
            session_id="session_test",
            channel="web",
            user_id="user_1",
            metadata={"source": "test"},
        )
        self.store.append_message("session_test", "user", "hello", metadata={"turn": 1})
        self.store.set_meta("goal:abc", "status", {"value": "running"})
        self.store.close()

        reopened = ControlPlane(self.temp_dir.name)
        try:
            self.assertEqual(session["session_id"], "session_test")
            self.assertEqual(reopened.get_session("session_test")["metadata"]["source"], "test")
            messages = reopened.list_messages("session_test")
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["content"], "hello")
            self.assertEqual(messages[0]["metadata"]["turn"], 1)
            self.assertEqual(reopened.get_meta("goal:abc", "status"), {"value": "running"})
        finally:
            reopened.close()

    def test_goal_lifecycle_and_tool_call_recording(self):
        self.store.create_session(session_id="session_goal")
        goal = self.store.create_goal("session_goal", "ship durable goals", status="running")
        updated = self.store.update_goal(
            goal["goal_id"],
            plan="1. implement\n2. verify",
            active_step="implement",
            todo_items=[{"content": "implement", "status": "in_progress"}],
            attempt_count=1,
            last_judge_result={"done": False, "next_action": "verify"},
        )

        tool_call = self.store.record_tool_call(
            "session_goal",
            "read_file",
            {"path": "README.md"},
            goal_id=goal["goal_id"],
        )
        completed = self.store.complete_tool_call(tool_call["tool_call_id"], True, result={"ok": True})

        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["todo_items"][0]["status"], "in_progress")
        self.assertFalse(updated["last_judge_result"]["done"])
        self.assertTrue(completed["success"])
        self.assertEqual(completed["result"], {"ok": True})
        self.assertEqual(self.store.list_goals("session_goal")[0]["goal_id"], goal["goal_id"])

    def test_scheduler_job_records_goal_link(self):
        self.store.create_session(session_id="session_job")
        goal = self.store.create_goal("session_job", "run every day")
        job = self.store.create_scheduler_job(
            schedule="0 9 * * *",
            prompt="daily summary",
            goal_id=goal["goal_id"],
            next_run_at="2026-05-25T09:00:00",
        )

        self.assertEqual(job["goal_id"], goal["goal_id"])
        self.assertEqual(job["status"], "active")
        self.assertEqual(Path(self.temp_dir.name, "control_plane.db").exists(), True)


if __name__ == "__main__":
    unittest.main()
