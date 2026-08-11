from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from open_agent.app.runner.models import AgentEvent
from open_agent.autonomics import SchedulerController, SchedulerJobSpec
from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import DurableRuntimeRepository, StaleClaimError
from open_agent.scheduler_runtime import CronSchedule, SchedulerWorker


NOW = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def runtime(tmp_path):
    control = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control)
    yield control, repository
    control.close()


class FakeRunner:
    def __init__(self, events=None):
        self.events = events or [AgentEvent(event="complete", session_id="unused", content="done")]
        self.requests = []

    async def run_stream(self, request, *, runtime_turn=None):
        self.requests.append((request, runtime_turn))
        for event in self.events:
            yield event.model_copy(update={"session_id": request.session_id})


@pytest.mark.parametrize(
    "expression",
    ["* * * *", "* * * * * *", "@daily", "once", "60 * * * *", "* * * * * trailing"],
)
def test_cron_requires_strict_five_field_expression(expression):
    with pytest.raises(ValueError):
        CronSchedule.parse(expression)


def test_cron_defaults_to_asia_shanghai_and_rejects_unknown_zone():
    schedule = CronSchedule.parse("0 9 * * *")
    assert schedule.timezone.key == "Asia/Shanghai"
    assert schedule.next_occurrence(datetime(2026, 8, 12, 0, 59, tzinfo=timezone.utc)) == datetime(
        2026, 8, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    with pytest.raises(ValueError, match="timezone"):
        CronSchedule.parse("0 9 * * *", "Mars/Olympus")


def test_cron_skips_spring_gap_and_returns_both_fall_fold_occurrences():
    zone = ZoneInfo("America/New_York")
    spring = CronSchedule.parse("30 2 * * *", zone.key)
    assert spring.next_occurrence(datetime(2026, 3, 7, 3, 0, tzinfo=zone)) == datetime(
        2026, 3, 9, 2, 30, tzinfo=zone
    )

    fall = CronSchedule.parse("30 1 * * *", zone.key)
    first = fall.next_occurrence(datetime(2026, 11, 1, 0, 0, tzinfo=zone))
    second = fall.next_occurrence(first)
    assert first.fold == 0
    assert second.fold == 1
    assert first.astimezone(timezone.utc) < second.astimezone(timezone.utc)


def test_controller_validates_and_initializes_next_cursor(runtime):
    control, _ = runtime
    controller = SchedulerController(control, clock=lambda: NOW)
    job = controller.create_job(SchedulerJobSpec(schedule="0 9 * * *", prompt="daily"))
    assert job["timezone"] == "Asia/Shanghai"
    assert datetime.fromisoformat(job["next_run_at"]) > NOW
    with pytest.raises(ValueError):
        controller.create_job(SchedulerJobSpec(schedule="bad", prompt="no"))


def test_scan_latest_only_catchup_advances_to_future_cursor(runtime):
    control, repository = runtime
    due = NOW - timedelta(minutes=4)
    control.create_scheduler_job("* * * * *", "run", job_id="catchup", next_run_at=due.isoformat())
    worker = SchedulerWorker(repository, FakeRunner(), clock=lambda: NOW, owner_id="scanner")
    runs = worker.scan_once(NOW)
    assert len(runs) == 1
    assert runs[0].scheduled_at == NOW
    job = next(item for item in control.list_scheduler_jobs() if item["job_id"] == "catchup")
    assert datetime.fromisoformat(job["next_run_at"]) == NOW + timedelta(minutes=1)


def test_scan_skips_overlap_but_advances_cursor(runtime):
    control, repository = runtime
    due = NOW - timedelta(minutes=1)
    control.create_scheduler_job("* * * * *", "run", job_id="overlap", next_run_at=due.isoformat())
    first = repository.create_due_scheduler_run(
        "overlap", due - timedelta(minutes=1), due, run_id="existing", now=due
    )
    claimed = repository.claim_due_scheduler_runs("busy", due, due + timedelta(hours=1))[0]
    assert first is not None and claimed.state == "running"
    runs = SchedulerWorker(repository, FakeRunner(), clock=lambda: NOW).scan_once(NOW)
    assert runs[0].state == "skipped"
    assert datetime.fromisoformat(control.list_scheduler_jobs()[0]["next_run_at"]) > NOW


def test_pause_resume_delete_semantics(runtime):
    control, repository = runtime
    controller = SchedulerController(control, clock=lambda: NOW)
    job = controller.create_job(SchedulerJobSpec("* * * * *", "run"))
    controller.pause_job(job["job_id"])
    assert SchedulerWorker(repository, FakeRunner()).scan_once(NOW + timedelta(minutes=1)) == []
    resumed = controller.resume_job(job["job_id"])
    assert datetime.fromisoformat(resumed["next_run_at"]) > NOW
    controller.delete_job(job["job_id"])
    with pytest.raises(ValueError, match="deleted"):
        controller.resume_job(job["job_id"])


def test_manual_request_id_is_idempotent_and_does_not_advance_cursor(runtime):
    control, repository = runtime
    control.create_scheduler_job("* * * * *", "run", job_id="manual", next_run_at=(NOW + timedelta(hours=1)).isoformat())
    worker = SchedulerWorker(repository, FakeRunner(), clock=lambda: NOW)
    first = worker.request_manual_run("manual", "request-123", NOW)
    duplicate = worker.request_manual_run("manual", "request-123", NOW + timedelta(minutes=1))
    assert duplicate.run_id == first.run_id
    assert control.list_scheduler_jobs()[0]["next_run_at"] == (NOW + timedelta(hours=1)).isoformat()


@pytest.mark.asyncio
async def test_execute_reuses_agent_runner_and_atomically_enqueues_origin_outbox(runtime):
    control, repository = runtime
    control.create_scheduler_job(
        "* * * * *", "say hello", job_id="deliver", next_run_at=NOW.isoformat(),
        metadata={"profile_id": "main", "user_id": "owner"},
    )
    control._get_conn().execute("UPDATE scheduler_jobs SET destination = ? WHERE job_id = ?", ("local:test", "deliver"))
    run = repository.create_due_scheduler_run("deliver", NOW, NOW + timedelta(minutes=1), now=NOW)
    runner = FakeRunner([AgentEvent(event="complete", session_id="unused", content="hello")])
    worker = SchedulerWorker(repository, runner, clock=lambda: NOW, owner_id="worker")
    completed = await worker.execute_run(run.run_id)
    assert completed.state == "completed"
    assert runner.requests[0][0].messages == [{"role": "user", "content": "say hello"}]
    assert runner.requests[0][0].session_id == f"scheduler:{run.job_id}"
    assert runner.requests[0][1]["turn_id"] == f"turn:scheduler:{run.run_id}"
    obligation = repository.list_outbox()[0]
    assert obligation.destination == "local:test"
    assert obligation.payload["content"] == "hello"


@pytest.mark.asyncio
async def test_destination_disallows_silent_completion(runtime):
    control, repository = runtime
    control.create_scheduler_job("* * * * *", "run", job_id="silent", next_run_at=NOW.isoformat())
    control._get_conn().execute("UPDATE scheduler_jobs SET destination = ? WHERE job_id = ?", ("local:test", "silent"))
    run = repository.create_due_scheduler_run("silent", NOW, NOW + timedelta(minutes=1), now=NOW)
    worker = SchedulerWorker(repository, FakeRunner([AgentEvent(event="complete", session_id="x", content="")]), clock=lambda: NOW)
    result = await worker.execute_run(run.run_id)
    assert result.state == "retry_wait"
    assert repository.list_outbox() == []


@pytest.mark.asyncio
async def test_initial_attempt_plus_five_retries_and_restart_recovery(runtime):
    control, repository = runtime
    control.create_scheduler_job("* * * * *", "run", job_id="retry", next_run_at=NOW.isoformat())
    run = repository.create_due_scheduler_run("retry", NOW, NOW + timedelta(minutes=1), now=NOW)
    failing = FakeRunner([AgentEvent(event="error", session_id="x", error="provider failed")])
    now = NOW
    for expected_attempt in range(1, 7):
        worker = SchedulerWorker(repository, failing, clock=lambda now=now: now, owner_id=f"worker-{expected_attempt}")
        result = await worker.execute_run(run.run_id)
        assert result.attempt == expected_attempt
        if expected_attempt < 6:
            assert result.state == "retry_wait"
            now = result.next_attempt_at
        else:
            assert result.state == "failed"


@pytest.mark.asyncio
async def test_expired_claim_is_recovered_and_stale_worker_is_fenced(runtime):
    control, repository = runtime
    control.create_scheduler_job("* * * * *", "run", job_id="recover", next_run_at=NOW.isoformat())
    run = repository.create_due_scheduler_run("recover", NOW, NOW + timedelta(minutes=1), now=NOW)
    stale = repository.claim_due_scheduler_runs("dead", NOW, NOW + timedelta(seconds=1))[0]
    recovered = repository.claim_due_scheduler_runs("live", NOW + timedelta(seconds=2), NOW + timedelta(minutes=1))[0]
    with pytest.raises(StaleClaimError):
        repository.complete_scheduler_run(stale.run_id, stale.claim, content="late", now=NOW + timedelta(seconds=2))
    assert recovered.claim.generation > stale.claim.generation
