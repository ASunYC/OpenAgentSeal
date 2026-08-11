from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from open_agent.app.runner.models import AgentEvent
from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import DurableRuntimeRepository
from open_agent.durable_runtime.delivery import DeliveryWorker
from open_agent.goal_mode import JudgeResult
from open_agent.goal_runtime import (
    GoalAcceptance,
    GoalBudget,
    GoalConfiguration,
    GoalRunner,
    PricingSnapshot,
)


NOW = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)


def criteria_evidence(*, complete: bool = False):
    return {
        "tests pass": {"satisfied": complete, "evidence": "tests evidence"},
        "report exists": {"satisfied": complete, "evidence": "report evidence"},
    }


class FakeRunner:
    def __init__(self, events: list[AgentEvent]):
        self.events = events
        self.requests = []

    async def run_stream(self, request, *, runtime_turn=None):
        self.requests.append((request, runtime_turn))
        for event in self.events:
            emitted = event
            if event.event in {"complete", "error", "cancelled"}:
                cp = request.meta["_runtime_control_plane"]
                status = {"complete": "completed", "error": "error", "cancelled": "cancelled"}[event.event]
                stored = cp.complete_runtime_turn_with_event(
                    thread_id=runtime_turn["thread_id"], turn_id=runtime_turn["turn_id"],
                    session_id=request.session_id, event_type=event.event,
                    payload=event.model_dump(exclude_none=True), status=status,
                    result={"content": event.content, **(event.result or {})}, error=event.error,
                )
                emitted = event.model_copy(update={"thread_id": runtime_turn["thread_id"], "turn_id": runtime_turn["turn_id"], "seq": stored["seq"]})
            yield emitted


class FakeJudge:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    async def judge(self, *, goal, iteration, content):
        self.calls.append((goal, iteration, content))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def runtime(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    return cp, DurableRuntimeRepository(cp)


def config(*, max_iterations=4, max_tokens=1000, max_cost=2.0, max_seconds=300.0):
    return GoalConfiguration(
        acceptance=GoalAcceptance(criteria=("tests pass", "report exists"), confidence_threshold=0.8),
        budget=GoalBudget(
            max_iterations=max_iterations,
            max_tokens=max_tokens,
            max_estimated_cost=max_cost,
            max_active_seconds=max_seconds,
        ),
        pricing=PricingSnapshot(version="prices-2026-08", currency="USD", cost_per_token=0.001),
        judge_schema_version="judge-schema-2",
        judge_prompt_version="judge-prompt-3",
    )


def test_contracts_are_immutable_and_reject_non_finite_or_unpriced_cost():
    with pytest.raises(ValueError):
        GoalAcceptance(criteria=("x",), confidence_threshold=float("nan"))
    with pytest.raises(ValueError):
        GoalBudget(max_iterations=1, max_tokens=2, max_estimated_cost=float("inf"), max_active_seconds=3)
    with pytest.raises(ValueError, match="pricing"):
        GoalConfiguration(
            acceptance=GoalAcceptance(criteria=("x",)),
            budget=GoalBudget(max_iterations=1, max_tokens=2, max_estimated_cost=1, max_active_seconds=3),
        )
    value = config()
    with pytest.raises(Exception):
        value.budget = replace(value.budget, max_tokens=9)


def test_start_persists_configuration_and_first_iteration_atomically(runtime):
    cp, repo = runtime
    created = repo.create_goal_with_first_iteration(
        session_id="session-1", goal_text="Ship", configuration=config().to_record(), now=NOW
    )
    goal = cp.get_goal(created.goal_id)
    assert goal["acceptance_criteria"] == ["tests pass", "report exists"]
    assert goal["judge_schema_version"] == "judge-schema-2"
    assert goal["pricing_version"] == "prices-2026-08"
    assert repo.list_goal_iterations(created.goal_id)[0].sequence == 1


def test_judge_done_requires_exact_criteria_and_threshold():
    acceptance = config().acceptance
    with pytest.raises(ValueError, match="criteria"):
        acceptance.validate_judge(
            JudgeResult(True, 0.95, "done", "", criterion_evidence={"tests pass": {"satisfied": True, "evidence": "ok"}})
        )
    with pytest.raises(ValueError, match="confidence"):
        acceptance.validate_judge(
            JudgeResult(True, 0.79, "done", "", criterion_evidence={"tests pass": {"satisfied": True, "evidence": "ok"}, "report exists": {"satisfied": True, "evidence": "ok"}})
        )


@pytest.mark.asyncio
async def test_runner_executes_one_authoritative_turn_and_hands_off(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(
        session_id="session-1", goal_text="Ship", configuration=config().to_record(), now=NOW
    )
    runner = FakeRunner([
        AgentEvent(event="complete", session_id="session-1", content="iteration output", status="idle", result={"usage": {"total_tokens": 25}})
    ])
    judge = FakeJudge([JudgeResult(False, 0.9, "more", "write report", criterion_evidence=criteria_evidence())])
    service = GoalRunner(repo, runner, judge, owner_id="worker", clock=lambda: NOW + timedelta(seconds=5))

    completed = await service.run_iteration(goal.goal_id)

    assert completed is not None and completed.state == "completed"
    stored = cp.get_goal(goal.goal_id)
    assert stored["consumed_tokens"] == 25
    assert stored["consumed_estimated_cost"] == pytest.approx(0.025)
    assert stored["active_step"] == "write report"
    assert len(repo.list_goal_iterations(goal.goal_id)) == 2
    request, turn = runner.requests[0]
    assert request.meta["source_event_key"] == f"goal:{goal.goal_id}:iteration:1"
    assert turn["turn_id"] == f"goal:{goal.goal_id}:iteration:1:turn"


@pytest.mark.asyncio
async def test_completion_emits_terminal_result_exactly_once(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(
        session_id="session-1", goal_text="Ship", configuration=config().to_record(), now=NOW,
        destination="local_session",
    )
    runner = FakeRunner([AgentEvent(event="complete", session_id="session-1", content="done", result={"usage": {"total_tokens": 4}})])
    done = JudgeResult(True, 0.9, "accepted", "", criterion_evidence={"tests pass": {"satisfied": True, "evidence": "yes"}, "report exists": {"satisfied": True, "evidence": "yes"}})
    service = GoalRunner(repo, runner, FakeJudge([done]), owner_id="worker", clock=lambda: NOW + timedelta(seconds=2))

    await service.run_iteration(goal.goal_id)
    await service.run_iteration(goal.goal_id)

    assert cp.get_goal(goal.goal_id)["status"] == "completed"
    obligations = [item for item in repo.list_outbox() if item.destination == "local_session"]
    assert len(obligations) == 1
    assert obligations[0].idempotency_key == f"goal:{goal.goal_id}:terminal:v1"


@pytest.mark.asyncio
async def test_budget_boundary_pauses_without_inventing_success(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(
        session_id="s", goal_text="Ship", configuration=config(max_tokens=10).to_record(), now=NOW
    )
    runner = FakeRunner([AgentEvent(event="complete", session_id="s", content="partial", result={"usage": {"total_tokens": 11}})])
    judge = FakeJudge([JudgeResult(False, 0.2, "not done", "continue", criterion_evidence=criteria_evidence())])
    service = GoalRunner(repo, runner, judge, owner_id="worker", clock=lambda: NOW + timedelta(seconds=1))

    await service.run_iteration(goal.goal_id)

    stored = cp.get_goal(goal.goal_id)
    assert stored["status"] == "paused"
    assert "token" in stored["last_judge_result"]["reason"].lower()
    iterations = repo.list_goal_iterations(goal.goal_id)
    assert len(iterations) == 2 and iterations[1].state == "pending"


def test_pause_resume_excludes_pause_but_counts_precrash_active_time(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    paused = repo.transition_goal(goal.goal_id, expected_version=0, action="pause", now=NOW + timedelta(seconds=10), reason="user")
    assert paused["consumed_active_seconds"] == 10
    resumed = repo.transition_goal(goal.goal_id, expected_version=1, action="resume", now=NOW + timedelta(seconds=110), reason="user")
    assert resumed["consumed_active_seconds"] == 10
    assert resumed["active_started_at"] == (NOW + timedelta(seconds=110)).isoformat()


def test_cancel_cas_prevents_stale_iteration_handoff(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    claimed = repo.claim_next_goal_iteration("worker", NOW, NOW + timedelta(seconds=30), goal_id=goal.goal_id)
    assert claimed and claimed.claim
    repo.transition_goal(goal.goal_id, expected_version=0, action="cancel", now=NOW + timedelta(seconds=1), reason="stop")
    with pytest.raises(Exception):
        repo.finish_goal_iteration(
            claimed.iteration_id, claimed.claim,
            judge_result={"done": False, "confidence": 0, "reason": "", "next_action": "x", "criterion_evidence": {}},
            budget_delta={"tokens": 0, "estimated_cost": 0, "active_seconds": 1},
            expected_goal_version=0, now=NOW + timedelta(seconds=2), continue_running=True,
        )


def test_guidance_is_monotonic_and_applied_once(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    one = repo.append_goal_guidance(goal.goal_id, "first", now=NOW)
    two = repo.append_goal_guidance(goal.goal_id, "second", now=NOW)
    assert [item["sequence"] for item in repo.list_goal_guidance(goal.goal_id)] == [1, 2]
    assert two == 2 and one == 1


@pytest.mark.asyncio
async def test_transient_failures_are_bounded_then_blocked(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    failing = FakeRunner([AgentEvent(event="error", session_id="s", error="provider unavailable")])
    current = [NOW]
    service = GoalRunner(repo, failing, FakeJudge([]), owner_id="worker", clock=lambda: current[0], max_transient_failures=2)
    await service.run_iteration(goal.goal_id)
    current[0] += timedelta(seconds=2)
    await service.run_iteration(goal.goal_id)
    assert cp.get_goal(goal.goal_id)["status"] == "blocked"


def test_recover_returns_only_due_runnable_iterations(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    claimed = repo.claim_next_goal_iteration("dead", NOW, NOW + timedelta(seconds=1), goal_id=goal.goal_id)
    service = GoalRunner(repo, FakeRunner([]), FakeJudge([]), owner_id="worker", clock=lambda: NOW + timedelta(seconds=2))
    assert service.recover(NOW + timedelta(seconds=2)) == [goal.goal_id]


def satisfied():
    return {
        "tests pass": {"satisfied": True, "evidence": "pytest passed"},
        "report exists": {"satisfied": True, "evidence": "report path"},
    }


def test_strict_evidence_rejects_legacy_strings_unknown_fields_and_false_satisfaction():
    acceptance = config().acceptance
    for evidence in (
        {"tests pass": "yes", "report exists": "yes"},
        {**satisfied(), "unknown": {"satisfied": True, "evidence": "x"}},
        {**satisfied(), "tests pass": {"satisfied": False, "evidence": "failed"}},
    ):
        with pytest.raises(ValueError):
            acceptance.validate_judge(JudgeResult(True, 0.9, "done", "", criterion_evidence=evidence))


def test_invalid_configuration_has_no_session_or_goal_side_effect(runtime):
    cp, repo = runtime
    with pytest.raises(ValueError):
        repo.create_goal_with_first_iteration(
            session_id="never-created", goal_text="Ship",
            configuration={**dict(config().to_record()), "max_tokens": float("nan")}, now=NOW,
        )
    assert cp.get_session("never-created") is None
    assert cp.list_goals() == []


@pytest.mark.asyncio
async def test_recovered_completed_turn_uses_persisted_content_and_usage_without_agent_rerun(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    claimed = repo.claim_next_goal_iteration("dead", NOW, NOW + timedelta(seconds=1), goal_id=first.goal_id)
    turn = cp._get_conn().execute("SELECT * FROM runtime_turns WHERE turn_id = ?", (claimed.turn_id,)).fetchone()
    cp.complete_runtime_turn_with_event(
        thread_id=turn["thread_id"], turn_id=turn["turn_id"], session_id="s",
        event_type="complete", payload={"event": "complete", "content": "persisted"},
        status="completed", result={"content": "persisted", "usage": {"total_tokens": 7}},
    )
    runner = FakeRunner([])
    judge = FakeJudge([JudgeResult(False, 0.5, "more", "next", criterion_evidence=criteria_evidence())])
    service = GoalRunner(repo, runner, judge, owner_id="new", clock=lambda: NOW + timedelta(seconds=2))
    await service.run_iteration(first.goal_id)
    assert runner.requests == []
    assert judge.calls[0][2] == "persisted"
    assert cp.get_goal(first.goal_id)["consumed_tokens"] == 7


@pytest.mark.asyncio
async def test_stream_event_cannot_override_authoritative_persisted_result(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)

    class ForgingRunner(FakeRunner):
        async def run_stream(self, request, *, runtime_turn=None):
            cp.complete_runtime_turn_with_event(
                thread_id=runtime_turn["thread_id"], turn_id=runtime_turn["turn_id"], session_id="s",
                event_type="complete", payload={"event": "complete", "content": "real"}, status="completed",
                result={"content": "real", "usage": {"total_tokens": 3}},
            )
            yield AgentEvent(event="complete", session_id="s", turn_id=runtime_turn["turn_id"], content="forged", result={"usage": {"total_tokens": 999}})

    judge = FakeJudge([JudgeResult(False, 0.5, "more", "next", criterion_evidence=criteria_evidence())])
    await GoalRunner(repo, ForgingRunner([]), judge, owner_id="w", clock=lambda: NOW + timedelta(seconds=1)).run_iteration(first.goal_id)
    assert judge.calls[0][2] == "real"
    assert cp.get_goal(first.goal_id)["consumed_tokens"] == 3


@pytest.mark.asyncio
async def test_budget_pause_uses_progress_obligation_and_later_completion_keeps_terminal_key(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config(max_tokens=10).to_record(), now=NOW)
    partial = FakeRunner([AgentEvent(event="complete", session_id="s", content="partial", result={"usage": {"total_tokens": 10}})])
    judge = FakeJudge([JudgeResult(False, 0.1, "more", "next", criterion_evidence=criteria_evidence())])
    await GoalRunner(repo, partial, judge, owner_id="w", clock=lambda: NOW + timedelta(seconds=1)).run_iteration(first.goal_id)
    keys = [item.idempotency_key for item in repo.list_outbox()]
    assert keys == [f"goal:{first.goal_id}:progress:budget:1:v1"]


@pytest.mark.asyncio
async def test_goal_obligation_is_deliverable_and_acknowledged_once(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    done = FakeRunner([AgentEvent(event="complete", session_id="s", content="done", result={"usage": {"total_tokens": 1}})])
    judge = FakeJudge([JudgeResult(True, 1, "done", "", criterion_evidence=satisfied())])
    await GoalRunner(repo, done, judge, owner_id="g", clock=lambda: NOW + timedelta(seconds=1)).run_iteration(first.goal_id)
    delivered = []

    class Destination:
        async def deliver(self, obligation, claim):
            delivered.append(obligation)
            assert obligation.destination == "local_session"
            for key in ("session_id", "content", "task_id", "profile_id", "status", "source_session_id"):
                assert obligation.payload[key]
            return {"message_id": obligation.obligation_id}

    worker = DeliveryWorker(repo, {"local_session": Destination()}, owner_id="d", clock=lambda: NOW + timedelta(seconds=2))
    await worker.run_once(NOW + timedelta(seconds=2))
    await worker.run_once(NOW + timedelta(seconds=3))
    assert len(delivered) == 1 and repo.list_outbox()[0].state == "acknowledged"


@pytest.mark.asyncio
async def test_external_cancellation_cleans_runner_child(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    child_cancelled = pytest.importorskip("asyncio").Event()

    class SlowRunner:
        async def run_stream(self, request, *, runtime_turn=None):
            try:
                await pytest.importorskip("asyncio").sleep(60)
                yield
            finally:
                child_cancelled.set()

    task = pytest.importorskip("asyncio").create_task(GoalRunner(repo, SlowRunner(), FakeJudge([]), owner_id="w", clock=lambda: NOW).run_iteration(first.goal_id))
    await pytest.importorskip("asyncio").sleep(0)
    task.cancel()
    with pytest.raises(pytest.importorskip("asyncio").CancelledError):
        await task
    assert child_cancelled.is_set()


@pytest.mark.asyncio
async def test_external_cancellation_cleans_judge_child(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    child_cancelled = pytest.importorskip("asyncio").Event()

    class SlowJudge:
        async def judge(self, **kwargs):
            try:
                await pytest.importorskip("asyncio").sleep(60)
            finally:
                child_cancelled.set()

    task = pytest.importorskip("asyncio").create_task(GoalRunner(repo, FakeRunner([AgentEvent(event="complete", session_id="s", content="x", result={"usage": {"total_tokens": 1}})]), SlowJudge(), owner_id="w", clock=lambda: NOW).run_iteration(first.goal_id))
    await pytest.importorskip("asyncio").sleep(0.05)
    task.cancel()
    with pytest.raises(pytest.importorskip("asyncio").CancelledError):
        await task
    assert child_cancelled.is_set()


def test_blocked_resume_requires_explicit_operator_reset(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    with cp._get_conn() as conn:
        conn.execute("UPDATE goals SET status='blocked', transient_failure_count=3 WHERE goal_id=?", (first.goal_id,))
    with pytest.raises(Exception):
        repo.transition_goal(first.goal_id, expected_version=0, action="resume", now=NOW, reason="try")
    resumed = repo.transition_goal(first.goal_id, expected_version=0, action="resume", now=NOW, reason="operator", operator_decision="reset_failures")
    assert resumed["transient_failure_count"] == 0


def test_budget_resume_requires_atomic_budget_increase(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config(max_tokens=10).to_record(), now=NOW)
    with cp._get_conn() as conn:
        conn.execute("UPDATE goals SET status='paused', consumed_tokens=10, metadata=? WHERE goal_id=?", ('{"pause_kind":"budget"}', first.goal_id))
    with pytest.raises(Exception):
        repo.transition_goal(first.goal_id, expected_version=0, action="resume", now=NOW, reason="try")
    resumed = repo.transition_goal(first.goal_id, expected_version=0, action="resume", now=NOW, reason="operator", operator_decision="increase_budget", budget_updates={"max_tokens": 20})
    assert resumed["max_tokens"] == 20


def test_goal_state_is_deeply_immutable(runtime):
    from dataclasses import FrozenInstanceError
    from open_agent.goal_mode import GoalState
    state = GoalState.from_record({"goal_id": "g", "session_id": "s", "goal_text": "x", "status": "running", "metadata": {"nested": {"x": 1}}})
    with pytest.raises(FrozenInstanceError):
        state.status = "paused"
    with pytest.raises(TypeError):
        state.metadata["nested"]["x"] = 2


def test_retry_persists_due_time_and_uses_latest_claim(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    claimed = repo.claim_next_goal_iteration("w", NOW, NOW + timedelta(seconds=30), goal_id=first.goal_id)
    latest = repo.renew_claim("goal_iteration", claimed.iteration_id, claimed.claim, NOW + timedelta(seconds=1), NOW + timedelta(seconds=40))
    failed = repo.fail_goal_iteration(claimed.iteration_id, latest, error="transient", now=NOW + timedelta(seconds=2), max_transient_failures=3, expected_goal_version=0)
    row = cp._get_conn().execute("SELECT * FROM goal_iterations WHERE iteration_id=?", (failed.iteration_id,)).fetchone()
    assert row["next_attempt_at"] > (NOW + timedelta(seconds=2)).isoformat()
    assert repo.claim_next_goal_iteration("early", NOW + timedelta(milliseconds=2500), NOW + timedelta(seconds=30), goal_id=first.goal_id) is None


def test_failure_settlement_cannot_overwrite_concurrent_cancel(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    claimed = repo.claim_next_goal_iteration("w", NOW, NOW + timedelta(seconds=30), goal_id=first.goal_id)
    repo.transition_goal(first.goal_id, expected_version=0, action="cancel", now=NOW + timedelta(seconds=1), reason="stop")
    with pytest.raises(Exception):
        repo.fail_goal_iteration(claimed.iteration_id, claimed.claim, error="late", now=NOW + timedelta(seconds=2), max_transient_failures=3, expected_goal_version=0)
    assert cp.get_goal(first.goal_id)["status"] == "cancelled"


def test_controller_start_is_atomic_with_start_message(runtime):
    from open_agent.goal_mode import GoalController
    cp, repo = runtime
    cp._get_conn().execute("CREATE TRIGGER fail_goal_message BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT, 'disk full'); END")
    with pytest.raises(Exception):
        GoalController(cp).start_goal("s", "Ship", configuration=config())
    assert cp.list_goals() == []
    assert repo.list_goal_iterations() == []


@pytest.mark.parametrize("field,value", [
    ("goal_id", "g" * 300), ("goal_text", "x" * 100_001),
    ("plan", "x" * 100_001),
], ids=["goal-id", "goal-text", "plan"])
def test_goal_start_bounds_fail_before_any_write(runtime, field, value):
    cp, repo = runtime
    kwargs = {"session_id": "s", "goal_text": "Ship", "configuration": config().to_record(), "now": NOW, field: value}
    with pytest.raises(ValueError):
        repo.create_goal_with_first_iteration(**kwargs)
    assert cp.get_session("s") is None and cp.list_goals() == []


def test_evidence_dto_rejects_unknown_fields_and_aggregate_overflow():
    with pytest.raises(ValueError):
        config().acceptance.validate_judge(JudgeResult(True, 1, "done", "", criterion_evidence={
            "tests pass": {"satisfied": True, "evidence": "ok", "extra": "no"},
            "report exists": {"satisfied": True, "evidence": "ok"},
        }))
    with pytest.raises(ValueError):
        JudgeResult(False, 0, "x" * 20_000, "", criterion_evidence={})


def test_terminal_outbox_identity_conflict_rolls_back_goal_settlement(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    claimed = repo.claim_next_goal_iteration("w", NOW, NOW + timedelta(seconds=30), goal_id=first.goal_id)
    from open_agent.durable_runtime.models import OutboxObligation
    repo.enqueue_outbox(OutboxObligation(
        obligation_id=f"goal:{first.goal_id}:terminal:v1", idempotency_key=f"goal:{first.goal_id}:terminal:v1",
        destination="local_session", payload={"conflict": True}, created_at=NOW, updated_at=NOW,
    ))
    obligation = GoalRunner(repo, FakeRunner([]), FakeJudge([]), owner_id="builder")._result_obligation(cp.get_goal(first.goal_id), "done", JudgeResult(True, 1, "done", "", criterion_evidence=satisfied()), NOW, status="completed", sequence=1)
    with pytest.raises(Exception):
        repo.finish_goal_iteration(claimed.iteration_id, claimed.claim, judge_result=JudgeResult(True, 1, "done", "", criterion_evidence=satisfied()).to_dict(), budget_delta={}, continue_running=False, goal_status="completed", expected_goal_version=0, terminal_obligation=obligation, now=NOW + timedelta(seconds=1))
    assert repo.get_goal_iteration(first.iteration_id).state == "running"


def test_destination_kind_is_validated_at_goal_creation(runtime):
    cp, repo = runtime
    with pytest.raises(ValueError):
        repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW, destination="mystery:x")
    with pytest.raises(ValueError):
        repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW, destination="channel:a", metadata={})
    assert cp.list_goals() == []


def test_cancel_also_fences_retry_wait_iteration(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    with cp._get_conn() as conn:
        conn.execute("UPDATE goal_iterations SET state='retry_wait', next_attempt_at=? WHERE iteration_id=?", ((NOW + timedelta(seconds=5)).isoformat(), first.iteration_id))
    repo.transition_goal(first.goal_id, expected_version=0, action="cancel", now=NOW, reason="stop")
    assert repo.get_goal_iteration(first.iteration_id).state == "cancelled"


def test_budget_updates_rejected_for_normal_pause(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    repo.transition_goal(first.goal_id, expected_version=0, action="pause", now=NOW, reason="user")
    with pytest.raises(Exception):
        repo.transition_goal(first.goal_id, expected_version=1, action="resume", now=NOW, reason="user", budget_updates={"max_tokens": 2000})


@pytest.mark.parametrize("owner,lease", [("", timedelta(seconds=30)), ("w", timedelta(0)), ("w", timedelta(days=2))])
def test_goal_runner_validates_worker_and_lease(runtime, owner, lease):
    cp, repo = runtime
    with pytest.raises(ValueError):
        GoalRunner(repo, FakeRunner([]), FakeJudge([]), owner_id=owner, lease_duration=lease)


@pytest.mark.asyncio
async def test_completed_turn_binding_metadata_is_verified(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    claimed = repo.claim_next_goal_iteration("dead", NOW, NOW + timedelta(seconds=1), goal_id=first.goal_id)
    cp.complete_runtime_turn(claimed.turn_id, result={"content": "x", "usage": {"total_tokens": 1}}, metadata={"goal_id": "other", "goal_iteration": 99, "source_event_key": "other"})
    with pytest.raises(Exception):
        repo.claim_next_goal_iteration("new", NOW + timedelta(seconds=2), NOW + timedelta(seconds=30), goal_id=first.goal_id)


def test_configured_transition_message_and_state_are_atomic(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    repo.transition_goal(first.goal_id, expected_version=0, action="pause", now=NOW, reason="review")
    messages = cp.list_messages("s")
    assert any(item["metadata"].get("goal_event") == "paused" for item in messages)


@pytest.mark.asyncio
async def test_malformed_slow_judge_settles_with_latest_renewed_claim(runtime):
    import asyncio
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)

    class MalformedSlowJudge:
        async def judge(self, **kwargs):
            await asyncio.sleep(0.4)
            return {"malformed": True}

    ticks = [0]
    def clock():
        ticks[0] += 0.2
        return NOW + timedelta(seconds=ticks[0])

    result = await GoalRunner(
        repo, FakeRunner([AgentEvent(event="complete", session_id="s", content="x", result={"usage": {"total_tokens": 1}})]),
        MalformedSlowJudge(), owner_id="w", clock=clock, lease_duration=timedelta(seconds=1),
    ).run_iteration(first.goal_id)
    assert result.state == "retry_wait" and result.claim is None


@pytest.mark.asyncio
async def test_channel_goal_uses_channel_destination_payload(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(
        session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW,
        destination="channel:account-1",
        metadata={"account_id": "account-1", "conversation_id": "conversation-1"},
    )
    await GoalRunner(
        repo, FakeRunner([AgentEvent(event="complete", session_id="s", content="done", result={"usage": {"total_tokens": 1}})]),
        FakeJudge([JudgeResult(True, 1, "done", "", criterion_evidence=satisfied())]),
        owner_id="w", clock=lambda: NOW + timedelta(seconds=1),
    ).run_iteration(first.goal_id)
    obligation = repo.list_outbox()[0]
    assert obligation.destination == "channel:account-1"
    assert obligation.payload["account_id"] == "account-1"
    assert obligation.payload["conversation_id"] == "conversation-1"
    assert obligation.payload["source_event_key"] == obligation.idempotency_key


@pytest.mark.asyncio
async def test_slow_none_judge_settles_with_latest_renewed_claim(runtime):
    import asyncio
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)

    class NoneJudge:
        async def judge(self, **kwargs):
            await asyncio.sleep(0.4)
            return None

    ticks = [0]
    def clock():
        ticks[0] += 0.2
        return NOW + timedelta(seconds=ticks[0])

    result = await GoalRunner(
        repo, FakeRunner([AgentEvent(event="complete", session_id="s", content="x", result={"usage": {"total_tokens": 1}})]),
        NoneJudge(), owner_id="w", clock=clock, lease_duration=timedelta(seconds=1),
    ).run_iteration(first.goal_id)
    assert result.state == "retry_wait" and repo.get_goal_iteration(first.iteration_id).state == "retry_wait"


def test_destination_and_channel_account_are_bounded_before_write(runtime):
    cp, repo = runtime
    for destination, metadata in (
        ("channel:" + "a" * 129, {"conversation_id": "c"}),
        ("channel:a" + "x" * 300, {"conversation_id": "c"}),
    ):
        with pytest.raises(ValueError):
            repo.create_goal_with_first_iteration(
                session_id="s", goal_text="Ship", configuration=config().to_record(),
                now=NOW, destination=destination, metadata=metadata,
            )
    assert cp.get_session("s") is None and cp.list_goals() == []


def test_judge_from_json_requires_exact_typed_object():
    valid = {"done": False, "confidence": 0.5, "reason": "more", "next_action": "next", "criterion_evidence": {}}
    assert JudgeResult.from_json(valid).reason == "more"
    for invalid in (
        [], {**valid, "extra": 1}, {key: value for key, value in valid.items() if key != "reason"},
        {**valid, "reason": 7}, {**valid, "criterion_evidence": []},
    ):
        with pytest.raises(ValueError):
            JudgeResult.from_json(invalid)


def test_goal_acceptance_rejects_string_coercion_and_bounds():
    with pytest.raises(ValueError):
        GoalAcceptance(criteria="not-a-sequence-of-criteria")
    with pytest.raises(ValueError):
        GoalAcceptance(criteria=(123,))
    with pytest.raises(ValueError):
        GoalAcceptance(criteria=("x" * 4097,))
    with pytest.raises(ValueError):
        GoalAcceptance(criteria=tuple(str(index) for index in range(101)))


@pytest.mark.asyncio
async def test_non_main_goal_uses_scoped_parent_profile_and_real_local_delivery(runtime, tmp_path, monkeypatch):
    from open_agent.app.runner.manager import ChatManager
    from open_agent.durable_runtime.delivery import LocalSessionDestination
    cp, repo = runtime
    manager = ChatManager(storage_dir=tmp_path / "profile-a")
    await manager.create_chat(session_id="s")
    monkeypatch.setattr("open_agent.durable_runtime.delivery.get_chat_manager", lambda profile: manager if profile == "profile-a" else None)
    first = repo.create_goal_with_first_iteration(
        session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW,
        metadata={"profile_id": "profile-a", "parent_profile_id": "profile-a"},
    )
    await GoalRunner(
        repo, FakeRunner([AgentEvent(event="complete", session_id="s", content="done", result={"usage": {"total_tokens": 1}})]),
        FakeJudge([JudgeResult(True, 1, "done", "", criterion_evidence=satisfied())]),
        owner_id="g", clock=lambda: NOW + timedelta(seconds=1),
    ).run_iteration(first.goal_id)
    destination = LocalSessionDestination(repo, clock=lambda: NOW + timedelta(seconds=2))
    worker = DeliveryWorker(repo, {"local_session": destination}, owner_id="d", clock=lambda: NOW + timedelta(seconds=2))
    await worker.run_once(NOW + timedelta(seconds=2))
    assert repo.list_outbox()[0].state == "acknowledged"
    assert len(manager.message_repo.list_messages("s")) == 1


def test_goal_destination_is_derived_from_persisted_session_principal(runtime):
    cp, repo = runtime
    cp.create_session(
        "scoped", channel="web", user_id="user-a",
        metadata={"profile_id": "profile-a", "parent_profile_id": "profile-a"},
    )
    with pytest.raises(PermissionError):
        repo.create_goal_with_first_iteration(
            session_id="scoped", goal_text="Ship", configuration=config().to_record(), now=NOW,
            metadata={"profile_id": "profile-b", "parent_profile_id": "profile-b"},
        )
    cp.create_session(
        "channel", channel="telegram", user_id="user-a",
        metadata={"account_id": "account-a", "conversation_id": "conversation-a"},
    )
    with pytest.raises(PermissionError):
        repo.create_goal_with_first_iteration(
            session_id="channel", goal_text="Ship", configuration=config().to_record(), now=NOW,
            destination="channel:account-b",
            metadata={"account_id": "account-b", "conversation_id": "conversation-a"},
        )
    assert cp.list_goals() == []


def test_sensitive_resume_consumes_persisted_operator_approval(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(
        session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW
    )
    with cp._get_conn() as conn:
        conn.execute(
            "UPDATE goals SET status='blocked', transient_failure_count=3 WHERE goal_id=?",
            (first.goal_id,),
        )
    with pytest.raises(PermissionError):
        repo.transition_goal(
            first.goal_id, expected_version=0, action="resume", now=NOW, reason="model",
            operator_decision="reset_failures", operator_principal="default", approval_id="missing",
        )
    repo.issue_goal_operator_approval(
        first.goal_id, approval_id="approval-1", principal_id="default",
        decision="reset_failures", now=NOW,
    )
    resumed = repo.transition_goal(
        first.goal_id, expected_version=0, action="resume", now=NOW, reason="approved",
        operator_decision="reset_failures", operator_principal="default", approval_id="approval-1",
    )
    assert resumed["status"] == "running"
    audit = cp._get_conn().execute(
        "SELECT consumed_at FROM goal_operator_approvals WHERE approval_id='approval-1'"
    ).fetchone()
    assert audit["consumed_at"] is not None


def test_guidance_enforces_atomic_pending_quota_and_bounded_pages(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(
        session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW
    )
    for index in range(100):
        repo.append_goal_guidance(first.goal_id, f"item-{index}", now=NOW)
    with pytest.raises(ValueError):
        repo.append_goal_guidance(first.goal_id, "overflow", now=NOW)
    with pytest.raises(ValueError):
        repo.append_goal_guidance(first.goal_id, "x" * 4097, now=NOW)
    assert len(repo.list_goal_guidance(first.goal_id, limit=25)) == 25
    assert cp._get_conn().execute(
        "SELECT COUNT(*) FROM goal_guidance WHERE goal_id=?", (first.goal_id,)
    ).fetchone()[0] == 100


@pytest.mark.asyncio
async def test_authoritative_agent_output_rejects_oversized_or_malformed_usage(runtime):
    cp, repo = runtime
    first = repo.create_goal_with_first_iteration(
        session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW
    )
    runner = FakeRunner([
        AgentEvent(event="complete", session_id="s", content="x" * 65_537,
                   result={"usage": {"total_tokens": 1}})
    ])
    result = await GoalRunner(
        repo, runner, FakeJudge([]), owner_id="w", clock=lambda: NOW + timedelta(seconds=1)
    ).run_iteration(first.goal_id)
    assert result.state == "retry_wait"


@pytest.mark.asyncio
async def test_delivery_worker_does_not_persist_exception_secrets(runtime):
    from open_agent.durable_runtime.models import OutboxObligation

    class SecretDestination:
        async def deliver(self, obligation, claim):
            raise RuntimeError("api_key=top-secret-value")

    _, repo = runtime
    repo.enqueue_outbox(OutboxObligation(
        obligation_id="secret-error", idempotency_key="secret-error",
        destination="test", payload={}, created_at=NOW, updated_at=NOW,
    ))
    worker = DeliveryWorker(
        repo, {"test": SecretDestination()}, owner_id="d", clock=lambda: NOW,
    )
    await worker.run_once(NOW)
    stored = repo.get_outbox("secret-error")
    assert "top-secret-value" not in (stored.last_error or "")
    assert stored.last_error == "delivery_error"
