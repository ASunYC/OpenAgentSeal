from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.models import GoalIteration, InboxEvent, OutboxObligation
from open_agent.durable_runtime.repository import (
    DurableRuntimeRepository,
    StateConflictError,
    StaleClaimError,
)


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def repository(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repo = DurableRuntimeRepository(control_plane)
    try:
        yield control_plane, repo
    finally:
        control_plane.close()


def test_migration_is_additive_and_idempotent(tmp_path):
    control_plane = ControlPlane(tmp_path)
    control_plane.close()
    reopened = ControlPlane(tmp_path)
    try:
        conn = reopened._get_conn()
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "channel_accounts",
            "channel_routes",
            "channel_ingress_checkpoints",
            "inbox_events",
            "outbox_obligations",
            "scheduler_runs",
            "goal_iterations",
            "runtime_audit_events",
        } <= tables
        goal_columns = {row[1] for row in conn.execute("PRAGMA table_info(goals)")}
        job_columns = {row[1] for row in conn.execute("PRAGMA table_info(scheduler_jobs)")}
        assert {"acceptance_criteria", "consumed_iterations", "runtime_version"} <= goal_columns
        assert {"timezone", "max_retries", "overlap_policy"} <= job_columns
    finally:
        reopened.close()


def test_legacy_column_migration_tolerates_concurrent_startup(tmp_path):
    conn = sqlite3.connect(tmp_path / "runtime.db")
    conn.executescript(
        """
        CREATE TABLE runtime_turns (
            turn_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, session_id TEXT NOT NULL,
            user_input TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'running',
            started_at TEXT NOT NULL, completed_at TEXT, result TEXT, error TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE goals (
            goal_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, goal_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft', plan TEXT NOT NULL DEFAULT '',
            active_step TEXT NOT NULL DEFAULT '', todo_items TEXT NOT NULL DEFAULT '[]',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_judge_result TEXT NOT NULL DEFAULT '{}', resume_token TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE scheduler_jobs (
            job_id TEXT PRIMARY KEY, goal_id TEXT, schedule TEXT NOT NULL, prompt TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active', next_run_at TEXT, last_run_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    conn.close()
    barrier = threading.Barrier(8)
    errors: list[Exception] = []

    def open_control_plane():
        barrier.wait()
        try:
            control_plane = ControlPlane(tmp_path)
            control_plane.close()
        except Exception as exc:  # surfaced below with full repr
            errors.append(exc)

    threads = [threading.Thread(target=open_control_plane) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_enqueue_inbox_enforces_account_scoped_event_key(repository):
    _, repo = repository
    first = InboxEvent("event-1", "platform-42", "account-a", "chat-1", {"nested": [1, 2]})
    duplicate = InboxEvent("event-2", "platform-42", "account-a", "chat-1", {"nested": [9]})
    other_account = InboxEvent("event-3", "platform-42", "account-b", "chat-1", {})

    assert repo.enqueue_inbox(first).event_id == "event-1"
    assert repo.enqueue_inbox(duplicate).event_id == "event-1"
    assert repo.enqueue_inbox(other_account).event_id == "event-3"
    assert len(repo.list_inbox()) == 2
    assert repo.get_inbox("event-1").payload["nested"] == (1, 2)


def test_enqueue_outbox_scopes_idempotency_to_destination(repository):
    _, repo = repository
    first = OutboxObligation("out-1", "producer-7", "session:one", {"text": "first"})
    duplicate = OutboxObligation("out-2", "producer-7", "session:one", {"text": "changed"})
    other_destination = OutboxObligation("out-3", "producer-7", "session:two", {"text": "second"})

    assert repo.enqueue_outbox(first).obligation_id == "out-1"
    assert repo.enqueue_outbox(duplicate).obligation_id == "out-1"
    assert repo.enqueue_outbox(other_destination).obligation_id == "out-3"
    assert [item.obligation_id for item in repo.list_outbox()] == ["out-1", "out-3"]


@pytest.mark.parametrize(
    ("record", "enqueue"),
    [
        (
            InboxEvent("event-claimed", "key", "account", "chat", {}, state="claimed"),
            "enqueue_inbox",
        ),
        (
            OutboxObligation("out-claimed", "key", "session:one", {}, state="claimed"),
            "enqueue_outbox",
        ),
        (
            GoalIteration("iteration-running", "goal-1", 1, state="running"),
            "create_goal_iteration",
        ),
    ],
)
def test_producers_cannot_persist_unclaimable_active_records(repository, record, enqueue):
    control_plane, repo = repository
    if isinstance(record, GoalIteration):
        control_plane.create_goal("session-1", "Goal", goal_id="goal-1", status="running")
    with pytest.raises(ValueError, match="pending"):
        getattr(repo, enqueue)(record)


@pytest.mark.parametrize(
    "method", ["list_inbox", "list_outbox", "list_scheduler_runs", "list_goal_iterations"]
)
@pytest.mark.parametrize("limit", [True, 0, -1, 1001])
def test_list_limits_remain_bounded(repository, method, limit):
    _, repo = repository
    with pytest.raises(ValueError, match="limit"):
        getattr(repo, method)(limit=limit)


def test_dispatch_inbox_and_create_turn_are_one_transaction(repository):
    control_plane, repo = repository
    control_plane.create_session("session-1")
    control_plane.create_runtime_thread(session_id="session-1", thread_id="thread-1")
    repo.enqueue_inbox(InboxEvent("event-1", "key-1", "account-1", "chat-1", {"text": "hello"}))
    claimed = repo.claim_inbox("event-1", "worker-a", NOW, NOW + timedelta(seconds=30))
    assert claimed is not None and claimed.claim is not None

    with pytest.raises(StateConflictError):
        repo.dispatch_inbox_with_turn(
            "event-1",
            claimed.claim,
            thread_id="missing-thread",
            session_id="session-1",
            user_input="hello",
            turn_id="turn-bad",
            now=NOW,
        )

    assert repo.get_inbox("event-1").state == "claimed"
    assert control_plane._get_conn().execute(
        "SELECT 1 FROM runtime_turns WHERE turn_id = ?", ("turn-bad",)
    ).fetchone() is None

    turn = repo.dispatch_inbox_with_turn(
        "event-1",
        claimed.claim,
        thread_id="thread-1",
        session_id="session-1",
        user_input="hello",
        turn_id="turn-1",
        metadata={"transport": "webhook"},
        now=NOW,
    )
    assert turn["source_event_key"] == '["account-1","key-1"]'
    assert turn["metadata"]["transport"] == "webhook"
    assert repo.get_inbox("event-1").state == "dispatched"


def test_dispatch_source_keys_cannot_collide_on_identifier_delimiters(repository):
    control_plane, repo = repository
    for suffix in ("one", "two"):
        control_plane.create_session(f"session-{suffix}")
        control_plane.create_runtime_thread(
            session_id=f"session-{suffix}", thread_id=f"thread-{suffix}"
        )
    repo.enqueue_inbox(InboxEvent("event-1", "c", "a:b", "chat", {}))
    repo.enqueue_inbox(InboxEvent("event-2", "b:c", "a", "chat", {}))

    first = repo.claim_inbox("event-1", "worker", NOW, NOW + timedelta(seconds=30))
    second = repo.claim_inbox("event-2", "worker", NOW, NOW + timedelta(seconds=30))
    assert first is not None and first.claim is not None
    assert second is not None and second.claim is not None
    turn_one = repo.dispatch_inbox_with_turn(
        "event-1",
        first.claim,
        thread_id="thread-one",
        session_id="session-one",
        user_input="one",
        now=NOW,
    )
    turn_two = repo.dispatch_inbox_with_turn(
        "event-2",
        second.claim,
        thread_id="thread-two",
        session_id="session-two",
        user_input="two",
        now=NOW,
    )
    assert turn_one["source_event_key"] != turn_two["source_event_key"]


def test_dispatch_rejects_thread_from_another_session_and_rolls_back(repository):
    control_plane, repo = repository
    control_plane.create_session("session-one")
    control_plane.create_session("session-two")
    control_plane.create_runtime_thread(session_id="session-one", thread_id="thread-one")
    repo.enqueue_inbox(InboxEvent("event-1", "key-1", "account", "chat", {}))
    claimed = repo.claim_inbox("event-1", "worker", NOW, NOW + timedelta(seconds=30))
    assert claimed is not None and claimed.claim is not None

    with pytest.raises(StateConflictError):
        repo.dispatch_inbox_with_turn(
            "event-1",
            claimed.claim,
            thread_id="thread-one",
            session_id="session-two",
            user_input="wrong session",
            now=NOW,
        )

    assert repo.get_inbox("event-1").state == "claimed"
    assert control_plane.list_runtime_turns("thread-one") == []


def test_expired_outbox_claim_is_reclaimed_and_stale_token_is_rejected(repository):
    _, repo = repository
    repo.enqueue_outbox(OutboxObligation("out-1", "key-1", "session:one", {"text": "hi"}))

    first = repo.claim_due_outbox("worker-a", NOW, NOW + timedelta(seconds=10))[0]
    second = repo.claim_due_outbox(
        "worker-b",
        NOW + timedelta(seconds=10),
        NOW + timedelta(seconds=40),
    )[0]
    assert first.claim is not None and second.claim is not None
    assert second.claim.owner_id == "worker-b"
    assert second.claim.generation == first.claim.generation + 1

    with pytest.raises(StaleClaimError):
        repo.ack_outbox("out-1", first.claim, {"message_id": "remote-1"}, NOW + timedelta(seconds=10))

    acknowledged = repo.ack_outbox(
        "out-1", second.claim, {"message_id": "remote-1"}, NOW + timedelta(seconds=11)
    )
    assert acknowledged.state == "acknowledged"
    assert acknowledged.acknowledgement == {"message_id": "remote-1"}


def test_renew_claim_uses_the_complete_fencing_token(repository):
    _, repo = repository
    repo.enqueue_outbox(OutboxObligation("out-1", "key-1", "session:one", {}))
    claimed = repo.claim_due_outbox("worker-a", NOW, NOW + timedelta(seconds=10))[0]
    assert claimed.claim is not None

    forged_expiry = type(claimed.claim)(
        claimed.claim.owner_id,
        claimed.claim.generation,
        claimed.claim.expires_at + timedelta(seconds=1),
    )
    with pytest.raises(StaleClaimError):
        repo.renew_claim("outbox", "out-1", forged_expiry, NOW, NOW + timedelta(seconds=20))

    renewed = repo.renew_claim(
        "outbox", "out-1", claimed.claim, NOW, NOW + timedelta(seconds=20)
    )
    assert renewed.expires_at == NOW + timedelta(seconds=20)


def test_retry_and_delivery_unknown_are_fenced(repository):
    _, repo = repository
    repo.enqueue_outbox(OutboxObligation("retry", "key-r", "session:one", {}))
    repo.enqueue_outbox(OutboxObligation("unknown", "key-u", "session:one", {}))
    retry_claim = repo.claim_due_outbox("worker", NOW, NOW + timedelta(seconds=30), limit=1)[0]
    unknown_claim = repo.claim_due_outbox("worker", NOW, NOW + timedelta(seconds=30), limit=1)[0]
    assert retry_claim.claim is not None and unknown_claim.claim is not None

    retried = repo.retry_outbox(
        retry_claim.obligation_id,
        retry_claim.claim,
        "temporary",
        NOW + timedelta(seconds=60),
        NOW,
    )
    unknown = repo.mark_delivery_unknown(
        unknown_claim.obligation_id,
        unknown_claim.claim,
        "ambiguous timeout",
        NOW,
    )
    assert retried.state == "retry_wait"
    assert retried.next_attempt_at == NOW + timedelta(seconds=60)
    assert unknown.state == "delivery_unknown"


def test_scheduler_occurrence_and_cursor_advance_are_atomic(repository):
    control_plane, repo = repository
    scheduled_at = NOW - timedelta(minutes=1)
    next_run_at = NOW + timedelta(hours=1)
    control_plane.create_scheduler_job(
        "* * * * *", "run", job_id="job-1", next_run_at=scheduled_at.isoformat()
    )
    run = repo.create_due_scheduler_run(
        "job-1", scheduled_at, next_run_at, run_id="run-1", now=NOW
    )
    duplicate = repo.create_due_scheduler_run(
        "job-1", scheduled_at, next_run_at, run_id="run-other", now=NOW
    )

    assert run is not None and run.run_id == "run-1"
    assert duplicate is not None and duplicate.run_id == "run-1"
    assert control_plane.list_scheduler_jobs()[0]["next_run_at"] == next_run_at.isoformat()
    assert len(repo.list_scheduler_runs("job-1")) == 1

    control_plane.create_scheduler_job(
        "* * * * *", "other", job_id="job-2", next_run_at=scheduled_at.isoformat()
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_due_scheduler_run(
            "job-2", scheduled_at, next_run_at, run_id="run-1", now=NOW
        )
    job_two = next(job for job in control_plane.list_scheduler_jobs() if job["job_id"] == "job-2")
    assert job_two["next_run_at"] == scheduled_at.isoformat()


def test_scheduler_cas_compares_equivalent_aware_instants(repository):
    control_plane, repo = repository
    china = timezone(timedelta(hours=8))
    stored_due = NOW.astimezone(china)
    control_plane.create_scheduler_job(
        "* * * * *", "run", job_id="job-offset", next_run_at=stored_due.isoformat()
    )

    run = repo.create_due_scheduler_run(
        "job-offset",
        NOW,
        NOW + timedelta(hours=1),
        run_id="run-offset",
        now=NOW,
    )
    assert run is not None and run.run_id == "run-offset"


def test_scheduler_cas_preserves_sub_millisecond_cursor_precision(repository):
    control_plane, repo = repository
    stored_due = NOW + timedelta(microseconds=100)
    control_plane.create_scheduler_job(
        "* * * * *", "run", job_id="job-precise", next_run_at=stored_due.isoformat()
    )

    run = repo.create_due_scheduler_run(
        "job-precise",
        NOW,
        NOW + timedelta(hours=1),
        run_id="run-wrong-instant",
        now=NOW + timedelta(seconds=1),
    )
    assert run is None
    assert control_plane.list_scheduler_jobs()[0]["next_run_at"] == stored_due.isoformat()
    assert repo.list_scheduler_runs("job-precise") == []


@pytest.mark.parametrize("delta", [timedelta(0), -timedelta(microseconds=1)])
def test_scheduler_rejects_non_forward_next_cursor(repository, delta):
    control_plane, repo = repository
    control_plane.create_scheduler_job(
        "* * * * *", "run", job_id="job-stuck", next_run_at=NOW.isoformat()
    )

    with pytest.raises(ValueError, match="next_run_at"):
        repo.create_due_scheduler_run(
            "job-stuck", NOW, NOW + delta, run_id="run-stuck", now=NOW
        )
    assert control_plane.list_scheduler_jobs()[0]["next_run_at"] == NOW.isoformat()
    assert repo.list_scheduler_runs("job-stuck") == []


def test_scheduler_accepts_forward_progress_across_dst_fall_back(repository):
    control_plane, repo = repository
    new_york = ZoneInfo("America/New_York")
    scheduled_at = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=0)
    next_run_at = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=1)
    control_plane.create_scheduler_job(
        "30 1 * * *", "run", job_id="job-fold", next_run_at=scheduled_at.isoformat()
    )

    run = repo.create_due_scheduler_run(
        "job-fold", scheduled_at, next_run_at, run_id="run-fold", now=next_run_at
    )
    assert run is not None and run.run_id == "run-fold"


def test_scheduler_accepts_rfc3339_z_cursor(repository):
    control_plane, repo = repository
    z_cursor = NOW.isoformat().replace("+00:00", "Z")
    control_plane.create_scheduler_job(
        "* * * * *", "run", job_id="job-z", next_run_at=z_cursor
    )

    run = repo.create_due_scheduler_run(
        "job-z", NOW, NOW + timedelta(minutes=1), run_id="run-z", now=NOW
    )
    assert run is not None and run.run_id == "run-z"


def test_concurrent_scheduler_scanners_return_the_same_occurrence(repository):
    control_plane, _ = repository
    control_plane.create_scheduler_job(
        "* * * * *", "run", job_id="job-race", next_run_at=NOW.isoformat()
    )
    barrier = threading.Barrier(2)

    class SynchronizedConnection:
        def __init__(self):
            self.conn = sqlite3.connect(control_plane.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row

        def execute(self, sql, params=()):
            cursor = self.conn.execute(sql, params)
            if "SELECT status, next_run_at FROM scheduler_jobs" in sql:
                barrier.wait()
            return cursor

        def __enter__(self):
            self.conn.__enter__()
            return self

        def __exit__(self, *args):
            return self.conn.__exit__(*args)

    class TestControlPlane:
        def __init__(self, conn):
            self.conn = conn

        def _get_conn(self):
            return self.conn

    connections = [SynchronizedConnection(), SynchronizedConnection()]
    repos = [DurableRuntimeRepository(TestControlPlane(conn)) for conn in connections]
    results: list[str | None] = []
    errors: list[Exception] = []

    def scan(index):
        try:
            run = repos[index].create_due_scheduler_run(
                "job-race",
                NOW,
                NOW + timedelta(minutes=1),
                run_id=f"run-{index}",
                now=NOW,
            )
            results.append(run.run_id if run else None)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=scan, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for connection in connections:
        connection.conn.close()

    assert errors == []
    assert len(results) == 2
    assert results[0] == results[1]
    assert len(DurableRuntimeRepository(control_plane).list_scheduler_runs("job-race")) == 1


def test_goal_iteration_completion_hands_off_atomically(repository):
    control_plane, repo = repository
    control_plane.create_goal("session-1", "Ship it", goal_id="goal-1", status="running")
    first = repo.create_goal_iteration(GoalIteration("iteration-1", "goal-1", 1))
    claimed = repo.claim_goal_iteration(
        first.iteration_id, "goal-worker", NOW, NOW + timedelta(seconds=30)
    )
    assert claimed is not None and claimed.claim is not None

    completed, continuation = repo.complete_goal_iteration_and_continue(
        "iteration-1",
        claimed.claim,
        judge_result={"done": False, "reason": "more", "next_action": "verify"},
        budget_delta={"tokens": 12, "estimated_cost": 0.25, "active_seconds": 3.5},
        continue_running=True,
        next_iteration_id="iteration-2",
        now=NOW + timedelta(seconds=1),
    )
    goal = control_plane.get_goal("goal-1")

    assert completed.state == "completed"
    assert continuation is not None and continuation.sequence == 2
    assert goal is not None
    assert goal["attempt_count"] == 1
    assert goal["consumed_iterations"] == 1
    assert goal["consumed_tokens"] == 12
    assert goal["consumed_estimated_cost"] == 0.25
    assert goal["consumed_active_seconds"] == 3.5
    assert goal["active_step"] == "verify"
    assert goal["runtime_version"] == 1

    with pytest.raises(StaleClaimError):
        repo.complete_goal_iteration_and_continue(
            "iteration-1",
            claimed.claim,
            judge_result={"done": False},
            budget_delta={},
            continue_running=True,
            now=NOW + timedelta(seconds=2),
        )
    assert len(repo.list_goal_iterations("goal-1")) == 2


def test_goal_iteration_cannot_revive_a_cancelled_goal(repository):
    control_plane, repo = repository
    control_plane.create_goal("session-1", "Stop safely", goal_id="goal-1", status="running")
    repo.create_goal_iteration(GoalIteration("iteration-1", "goal-1", 1))
    claimed = repo.claim_goal_iteration(
        "iteration-1", "goal-worker", NOW, NOW + timedelta(seconds=30)
    )
    assert claimed is not None and claimed.claim is not None
    control_plane.update_goal("goal-1", status="cancelled")

    with pytest.raises(StateConflictError):
        repo.complete_goal_iteration_and_continue(
            "iteration-1",
            claimed.claim,
            judge_result={"done": False, "next_action": "must not run"},
            budget_delta={},
            continue_running=True,
            now=NOW + timedelta(seconds=1),
        )

    assert control_plane.get_goal("goal-1")["status"] == "cancelled"
    assert repo.get_goal_iteration("iteration-1").state == "running"
    assert len(repo.list_goal_iterations("goal-1")) == 1


def test_goal_iteration_cannot_be_claimed_after_goal_cancellation(repository):
    control_plane, repo = repository
    control_plane.create_goal("session-1", "Stop", goal_id="goal-1", status="running")
    repo.create_goal_iteration(GoalIteration("iteration-1", "goal-1", 1))
    control_plane.update_goal("goal-1", status="cancelled")

    claimed = repo.claim_goal_iteration(
        "iteration-1", "goal-worker", NOW, NOW + timedelta(seconds=30)
    )
    assert claimed is None
    assert repo.get_goal_iteration("iteration-1").state == "pending"


@pytest.mark.parametrize(
    ("continue_running", "goal_status"),
    [(True, "completed"), (False, "running"), (False, "invented")],
)
def test_goal_handoff_rejects_contradictory_status(repository, continue_running, goal_status):
    control_plane, repo = repository
    control_plane.create_goal("session-1", "Consistent", goal_id="goal-1", status="running")
    repo.create_goal_iteration(GoalIteration("iteration-1", "goal-1", 1))
    claimed = repo.claim_goal_iteration(
        "iteration-1", "goal-worker", NOW, NOW + timedelta(seconds=30)
    )
    assert claimed is not None and claimed.claim is not None

    with pytest.raises(ValueError, match="goal_status"):
        repo.complete_goal_iteration_and_continue(
            "iteration-1",
            claimed.claim,
            judge_result={"done": not continue_running},
            budget_delta={},
            continue_running=continue_running,
            goal_status=goal_status,
            now=NOW + timedelta(seconds=1),
        )
    assert repo.get_goal_iteration("iteration-1").state == "running"


@pytest.mark.parametrize(
    ("done", "continue_running"), [(True, True), (False, False), ("true", False)]
)
def test_goal_handoff_rejects_judge_done_contradictions(
    repository, done, continue_running
):
    control_plane, repo = repository
    control_plane.create_goal("session-1", "Judge safely", goal_id="goal-1", status="running")
    repo.create_goal_iteration(GoalIteration("iteration-1", "goal-1", 1))
    claimed = repo.claim_goal_iteration(
        "iteration-1", "goal-worker", NOW, NOW + timedelta(seconds=30)
    )
    assert claimed is not None and claimed.claim is not None

    with pytest.raises(ValueError, match="done"):
        repo.complete_goal_iteration_and_continue(
            "iteration-1",
            claimed.claim,
            judge_result={"done": done, "next_action": "continue"},
            budget_delta={},
            continue_running=continue_running,
            now=NOW + timedelta(seconds=1),
        )
    assert control_plane.get_goal("goal-1")["status"] == "running"
    assert repo.get_goal_iteration("iteration-1").state == "running"
    assert len(repo.list_goal_iterations("goal-1")) == 1


class FlippingJudge(Mapping[str, Any]):
    def __getitem__(self, key):
        return True if key == "done" else "continue"

    def __iter__(self) -> Iterator[str]:
        return iter(("done", "next_action"))

    def __len__(self):
        return 2

    def get(self, key, default=None):
        return False if key == "done" else super().get(key, default)


class DivergentBudget(Mapping[str, int]):
    def __getitem__(self, key):
        if key == "tokens":
            return 999
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(("tokens",))

    def __len__(self):
        return 1

    def get(self, key, default=None):
        return 1 if key == "tokens" else default


def test_goal_handoff_validates_one_judge_snapshot(repository):
    control_plane, repo = repository
    control_plane.create_goal("session-1", "Snapshot", goal_id="goal-1", status="running")
    repo.create_goal_iteration(GoalIteration("iteration-1", "goal-1", 1))
    claimed = repo.claim_goal_iteration(
        "iteration-1", "goal-worker", NOW, NOW + timedelta(seconds=30)
    )
    assert claimed is not None and claimed.claim is not None

    with pytest.raises(ValueError, match="done"):
        repo.complete_goal_iteration_and_continue(
            "iteration-1",
            claimed.claim,
            judge_result=FlippingJudge(),
            budget_delta={},
            continue_running=True,
            now=NOW + timedelta(seconds=1),
        )
    assert repo.get_goal_iteration("iteration-1").state == "running"


def test_goal_handoff_applies_and_persists_one_budget_snapshot(repository):
    control_plane, repo = repository
    control_plane.create_goal("session-1", "Budget", goal_id="goal-1", status="running")
    repo.create_goal_iteration(GoalIteration("iteration-1", "goal-1", 1))
    claimed = repo.claim_goal_iteration(
        "iteration-1", "goal-worker", NOW, NOW + timedelta(seconds=30)
    )
    assert claimed is not None and claimed.claim is not None

    repo.complete_goal_iteration_and_continue(
        "iteration-1",
        claimed.claim,
        judge_result={"done": False, "next_action": "continue"},
        budget_delta=DivergentBudget(),
        continue_running=True,
        now=NOW + timedelta(seconds=1),
    )
    goal = control_plane.get_goal("goal-1")
    stored_delta = control_plane._get_conn().execute(
        "SELECT budget_delta FROM goal_iterations WHERE iteration_id = 'iteration-1'"
    ).fetchone()[0]
    assert goal["consumed_tokens"] == 999
    assert stored_delta == '{"tokens":999}'
