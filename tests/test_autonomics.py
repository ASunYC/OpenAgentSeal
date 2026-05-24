import tempfile
import threading
import unittest

from open_agent.autonomics import (
    DelegationController,
    DelegationSpec,
    GoalReplay,
    MemoryProvenance,
    ObservabilitySnapshot,
    SchedulerController,
    SchedulerJobSpec,
    export_memory_vault,
)
from open_agent.control_plane import ControlPlane
from open_agent.goal_mode import GoalController, JudgeResult


class TestAutonomics(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.control_plane = ControlPlane(self.temp_dir.name)

    def tearDown(self):
        self.control_plane.close()
        self.temp_dir.cleanup()

    def test_memory_provenance_exports_markdown_vault(self):
        provenance = MemoryProvenance(source="goal", session_id="s1", goal_id="g1", confidence=0.9)
        paths = export_memory_vault(
            [{"content": "User prefers visible autonomy", "provenance": provenance.to_dict()}],
            f"{self.temp_dir.name}/vault",
        )

        self.assertEqual(len(paths), 1)
        text = paths[0].read_text(encoding="utf-8")
        self.assertIn("source: goal", text)
        self.assertIn("User prefers visible autonomy", text)

    def test_scheduler_controller_lifecycle(self):
        scheduler = SchedulerController(self.control_plane)
        job = scheduler.create_job(SchedulerJobSpec(schedule="0 9 * * *", prompt="daily run"))
        paused = scheduler.pause_job(job["job_id"])
        resumed = scheduler.resume_job(job["job_id"])
        deleted = scheduler.delete_job(job["job_id"])

        self.assertEqual(job["status"], "active")
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(resumed["status"], "active")
        self.assertEqual(deleted["status"], "deleted")

    def test_delegation_controller_bounds_work(self):
        controller = DelegationController(max_delegates=1, max_depth=1)
        accepted = controller.submit(DelegationSpec(parent_goal_id="g1", user_input="research", role="researcher"))
        rejected_capacity = controller.submit(DelegationSpec(parent_goal_id="g1", user_input="more", role="researcher"))
        completed = controller.complete(accepted.delegation_id, "done")
        rejected_depth = controller.submit(DelegationSpec(parent_goal_id="g1", user_input="deep", role="researcher", max_depth=2))

        self.assertEqual(accepted.status, "queued")
        self.assertEqual(rejected_capacity.status, "rejected")
        self.assertEqual(completed.status, "completed")
        self.assertEqual(rejected_depth.status, "rejected")

    def test_delegation_capacity_is_thread_safe(self):
        controller = DelegationController(max_delegates=1, max_depth=1)
        results = []
        lock = threading.Lock()

        def submit():
            result = controller.submit(DelegationSpec(parent_goal_id="g1", user_input="research", role="researcher"))
            with lock:
                results.append(result.status)

        threads = [threading.Thread(target=submit) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results.count("queued"), 1)
        self.assertEqual(results.count("rejected"), 7)

    def test_observability_snapshot_and_replay(self):
        goals = GoalController(self.control_plane)
        goal = goals.start_goal("session_obs", "observe me")
        goals.apply_judge_result(goal.goal_id, JudgeResult(done=True, confidence=1, reason="done", next_action=""))
        other_goal = goals.start_goal("session_other", "do not leak")
        SchedulerController(self.control_plane).create_job(SchedulerJobSpec(schedule="once", prompt="run", goal_id=goal.goal_id))
        SchedulerController(self.control_plane).create_job(SchedulerJobSpec(schedule="once", prompt="other", goal_id=other_goal.goal_id))

        snapshot = ObservabilitySnapshot(self.control_plane).build("session_obs")
        replay = GoalReplay(self.control_plane)

        self.assertEqual(snapshot["goals"][0]["goal_id"], goal.goal_id)
        self.assertEqual(len(snapshot["scheduler_jobs"]), 1)
        self.assertEqual(snapshot["scheduler_jobs"][0]["goal_id"], goal.goal_id)
        self.assertTrue(replay.assert_goal_status(goal.goal_id, "completed"))
        self.assertGreaterEqual(len(replay.export_trajectory("session_obs")), 2)


if __name__ == "__main__":
    unittest.main()
