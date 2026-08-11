from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from open_agent.app.runner.models import AgentEvent
from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import DurableRuntimeRepository
from open_agent.goal_mode import JudgeResult
from open_agent.goal_runtime import (
    GoalAcceptance,
    GoalBudget,
    GoalConfiguration,
    GoalRunner,
    PricingSnapshot,
)


NOW = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)


class FakeRunner:
    def __init__(self, events: list[AgentEvent]):
        self.events = events
        self.requests = []

    async def run_stream(self, request, *, runtime_turn=None):
        self.requests.append((request, runtime_turn))
        for event in self.events:
            yield event


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
            JudgeResult(True, 0.95, "done", "", criterion_evidence={"tests pass": "ok"})
        )
    with pytest.raises(ValueError, match="confidence"):
        acceptance.validate_judge(
            JudgeResult(True, 0.79, "done", "", criterion_evidence={"tests pass": "ok", "report exists": "ok"})
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
    judge = FakeJudge([JudgeResult(False, 0.9, "more", "write report", criterion_evidence={"tests pass": "ok", "report exists": "missing"})])
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
        destination="local-session:session-1",
    )
    runner = FakeRunner([AgentEvent(event="complete", session_id="session-1", content="done", result={"usage": {"total_tokens": 4}})])
    done = JudgeResult(True, 0.9, "accepted", "", criterion_evidence={"tests pass": "yes", "report exists": "yes"})
    service = GoalRunner(repo, runner, FakeJudge([done]), owner_id="worker", clock=lambda: NOW + timedelta(seconds=2))

    await service.run_iteration(goal.goal_id)
    await service.run_iteration(goal.goal_id)

    assert cp.get_goal(goal.goal_id)["status"] == "completed"
    obligations = repo.list_outbox("local-session:session-1")
    assert len(obligations) == 1
    assert obligations[0].idempotency_key == f"goal:{goal.goal_id}:terminal:v1"


@pytest.mark.asyncio
async def test_budget_boundary_pauses_without_inventing_success(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(
        session_id="s", goal_text="Ship", configuration=config(max_tokens=10).to_record(), now=NOW
    )
    runner = FakeRunner([AgentEvent(event="complete", session_id="s", content="partial", result={"usage": {"total_tokens": 11}})])
    judge = FakeJudge([JudgeResult(False, 0.2, "not done", "continue", criterion_evidence={"tests pass": "no", "report exists": "no"})])
    service = GoalRunner(repo, runner, judge, owner_id="worker", clock=lambda: NOW + timedelta(seconds=1))

    await service.run_iteration(goal.goal_id)

    stored = cp.get_goal(goal.goal_id)
    assert stored["status"] == "paused"
    assert "token" in stored["last_judge_result"]["reason"].lower()
    assert len(repo.list_goal_iterations(goal.goal_id)) == 1


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
    service = GoalRunner(repo, failing, FakeJudge([]), owner_id="worker", clock=lambda: NOW, max_transient_failures=2)
    await service.run_iteration(goal.goal_id)
    await service.run_iteration(goal.goal_id)
    assert cp.get_goal(goal.goal_id)["status"] == "blocked"


def test_recover_returns_only_due_runnable_iterations(runtime):
    cp, repo = runtime
    goal = repo.create_goal_with_first_iteration(session_id="s", goal_text="Ship", configuration=config().to_record(), now=NOW)
    claimed = repo.claim_next_goal_iteration("dead", NOW, NOW + timedelta(seconds=1), goal_id=goal.goal_id)
    service = GoalRunner(repo, FakeRunner([]), FakeJudge([]), owner_id="worker", clock=lambda: NOW + timedelta(seconds=2))
    assert service.recover(NOW + timedelta(seconds=2)) == [goal.goal_id]
