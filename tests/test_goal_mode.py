import tempfile
import unittest

from open_agent.control_plane import ControlPlane
from open_agent.goal_mode import GoalController, JudgeResult


class TestGoalMode(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.control_plane = ControlPlane(self.temp_dir.name)
        self.controller = GoalController(self.control_plane)

    def tearDown(self):
        self.control_plane.close()
        self.temp_dir.cleanup()

    def test_start_pause_resume_cancel_goal(self):
        goal = self.controller.start_goal(
            "session_goal",
            "Build durable goals",
            plan="1. create state\n2. verify",
            todo_items=[{"content": "create state", "status": "pending"}],
        )

        self.assertEqual(goal.status, "running")
        self.assertEqual(goal.todo_items[0]["content"], "create state")
        self.assertIn("resume_", goal.resume_token)

        paused = self.controller.pause_goal(goal.goal_id, "Need review")
        self.assertEqual(paused.status, "paused")
        self.assertEqual(paused.metadata["last_transition_reason"], "Need review")

        resumed = self.controller.resume_goal(goal.goal_id)
        self.assertEqual(resumed.status, "running")

        cancelled = self.controller.cancel_goal(goal.goal_id)
        self.assertEqual(cancelled.status, "cancelled")

    def test_judge_result_adds_visible_continuation(self):
        goal = self.controller.start_goal("session_judge", "Finish a roadmap")
        updated = self.controller.apply_judge_result(
            goal.goal_id,
            {"done": False, "confidence": 0.8, "reason": "Needs verification", "next_action": "Run checks"},
        )

        self.assertEqual(updated.status, "running")
        self.assertEqual(updated.active_step, "Run checks")
        self.assertEqual(updated.attempt_count, 1)

        messages = self.control_plane.list_messages("session_judge")
        self.assertTrue(any(m["metadata"].get("goal_event") == "judge" for m in messages))
        continuation = [m for m in messages if m["metadata"].get("goal_event") == "continue"]
        self.assertEqual(len(continuation), 1)
        self.assertIn("Next action: Run checks", continuation[0]["content"])

    def test_judge_result_can_complete_goal(self):
        goal = self.controller.start_goal("session_done", "Complete this")
        result = JudgeResult.from_json('{"done": true, "confidence": 1, "reason": "Done", "next_action": ""}')
        completed = self.controller.apply_judge_result(goal.goal_id, result)

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.active_step, "")
        self.assertTrue(completed.last_judge_result["done"])

    def test_judge_result_requires_boolean_done(self):
        with self.assertRaises(ValueError):
            JudgeResult.from_json('{"done": "false", "confidence": 1, "reason": "", "next_action": ""}')

    def test_judge_result_requires_confidence_range(self):
        with self.assertRaises(ValueError):
            JudgeResult.from_json({"done": False, "confidence": 2, "reason": "", "next_action": ""})


if __name__ == "__main__":
    unittest.main()
