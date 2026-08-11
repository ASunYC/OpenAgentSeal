"""Lease-fenced, one-turn-at-a-time continuous goal execution."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence
import uuid

from open_agent.app.runner.models import AgentRequest
from open_agent.durable_runtime.models import GoalIteration, OutboxObligation
from open_agent.durable_runtime.repository import (
    DurableRuntimeRepository,
    StaleClaimError,
    StateConflictError,
)
from open_agent.goal_mode import CriterionEvidence, JudgeResult


class _ClaimedGoalError(RuntimeError):
    def __init__(self, message: str, claim: Any) -> None:
        super().__init__(message)
        self.claim = claim


def _finite_non_negative(value: int | float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")


@dataclass(frozen=True, slots=True)
class GoalAcceptance:
    criteria: tuple[str, ...]
    confidence_threshold: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.criteria, (str, bytes)) or not isinstance(self.criteria, Sequence):
            raise ValueError("acceptance criteria must be a sequence of strings")
        if any(not isinstance(item, str) for item in self.criteria):
            raise ValueError("acceptance criteria must be a sequence of strings")
        normalized = tuple(item.strip() for item in self.criteria)
        if not normalized or any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("acceptance criteria must be unique non-empty strings")
        if len(normalized) > 100 or any(len(item.encode("utf-8")) > 4096 for item in normalized):
            raise ValueError("acceptance criteria exceed the count or byte limit")
        if sum(len(item.encode("utf-8")) for item in normalized) > 65_536:
            raise ValueError("acceptance criteria exceed the aggregate byte limit")
        _finite_non_negative(self.confidence_threshold, "confidence_threshold")
        if self.confidence_threshold > 1:
            raise ValueError("confidence_threshold must not exceed 1")
        object.__setattr__(self, "criteria", normalized)

    def validate_judge(self, result: JudgeResult) -> None:
        if set(result.criterion_evidence) != set(self.criteria):
            raise ValueError("judge result must address the exact acceptance criteria")
        for criterion in self.criteria:
            evidence = result.criterion_evidence[criterion]
            if not isinstance(evidence, CriterionEvidence):
                raise ValueError("judge result requires a satisfaction boolean and evidence for every criterion")
            if result.done and evidence.satisfied is not True:
                raise ValueError("judge completion requires every criterion to be satisfied")
        if not result.done:
            return
        if result.confidence < self.confidence_threshold:
            raise ValueError("judge completion confidence is below the configured threshold")


@dataclass(frozen=True, slots=True)
class GoalBudget:
    max_iterations: int
    max_tokens: int
    max_estimated_cost: float
    max_active_seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.max_iterations, bool) or not isinstance(self.max_iterations, int) or self.max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        _finite_non_negative(self.max_estimated_cost, "max_estimated_cost")
        _finite_non_negative(self.max_active_seconds, "max_active_seconds")
        if self.max_estimated_cost <= 0 or self.max_active_seconds <= 0:
            raise ValueError("cost and active-time budgets must be positive")


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    version: str
    currency: str
    cost_per_token: float

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.currency.strip():
            raise ValueError("pricing version and currency are required")
        _finite_non_negative(self.cost_per_token, "cost_per_token")


@dataclass(frozen=True, slots=True)
class GoalConfiguration:
    acceptance: GoalAcceptance
    budget: GoalBudget
    pricing: PricingSnapshot | None = None
    judge_schema_version: str = "1"
    judge_prompt_version: str = "1"

    def __post_init__(self) -> None:
        if not self.judge_schema_version.strip() or not self.judge_prompt_version.strip():
            raise ValueError("judge schema and prompt versions are required")
        if self.budget.max_estimated_cost > 0 and self.pricing is None:
            raise ValueError("a persisted pricing snapshot is required for a cost budget")

    def to_record(self) -> Mapping[str, Any]:
        pricing = self.pricing
        return MappingProxyType({
            "acceptance_criteria": self.acceptance.criteria,
            "judge_confidence_threshold": self.acceptance.confidence_threshold,
            "judge_schema_version": self.judge_schema_version,
            "judge_prompt_version": self.judge_prompt_version,
            "max_iterations": self.budget.max_iterations,
            "max_tokens": self.budget.max_tokens,
            "max_estimated_cost": self.budget.max_estimated_cost,
            "max_active_seconds": self.budget.max_active_seconds,
            "pricing_version": pricing.version if pricing else None,
            "pricing_currency": pricing.currency if pricing else None,
            "pricing_cost_per_token": pricing.cost_per_token if pricing else None,
        })


class GoalJudge(Protocol):
    async def judge(
        self, *, goal: Mapping[str, Any], iteration: GoalIteration, content: str
    ) -> JudgeResult: ...


class GoalRunner:
    """Claims and executes exactly one persisted Goal iteration per call."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        runner: Any,
        judge: GoalJudge,
        *,
        owner_id: str | None = None,
        clock: Any | None = None,
        lease_duration: timedelta = timedelta(seconds=60),
        max_transient_failures: int = 3,
        request_principal: Any | None = None,
    ) -> None:
        if owner_id is not None and (
            not isinstance(owner_id, str) or not owner_id.strip()
            or len(owner_id.encode("utf-8")) > 128
        ):
            raise ValueError("owner_id must be a bounded non-empty string")
        if not isinstance(lease_duration, timedelta) or not timedelta(seconds=1) <= lease_duration <= timedelta(hours=1):
            raise ValueError("lease_duration must be between one second and one hour")
        if isinstance(max_transient_failures, bool) or not isinstance(max_transient_failures, int) or max_transient_failures < 1 or max_transient_failures > 100:
            raise ValueError("max_transient_failures must be positive")
        self._repository = repository
        self._request_principal = request_principal or getattr(repository, "principal", None)
        repository._require_goal_principal(self._request_principal)
        self._runner = runner
        self._judge = judge
        self._owner_id = owner_id or f"goal-worker-{uuid.uuid4().hex[:12]}"
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lease_duration = lease_duration
        self._max_transient_failures = max_transient_failures

    def recover(self, now: datetime | None = None) -> list[str]:
        """List bounded, restart-eligible goals; recovery never rewrites history."""
        at = now or self._clock()
        rows = self._repository.control_plane._get_conn().execute(
            """SELECT DISTINCT gi.goal_id FROM goal_iterations gi JOIN goals g ON g.goal_id = gi.goal_id
               JOIN sessions s ON s.session_id = g.session_id
               WHERE g.status IN ('running', 'runnable') AND
                 s.user_id = ? AND json_extract(s.metadata, '$.tenant_id') = ? AND
                 (gi.state = 'pending' OR (gi.state = 'retry_wait' AND gi.next_attempt_at <= ?)
                  OR (gi.state IN ('running', 'judging') AND gi.claim_expires_at <= ?))
               ORDER BY gi.created_at LIMIT 100""",
            (self._request_principal.actor_id, self._request_principal.tenant_id,
             at.isoformat(), at.isoformat()),
        ).fetchall()
        return [str(row[0]) for row in rows]

    async def run_iteration(self, goal_id: str) -> GoalIteration | None:
        started = self._clock()
        goal = self._goal(goal_id)
        if goal is None or goal["status"] not in {"running", "runnable"}:
            return None
        exhausted = self._exhausted(goal, started)
        if exhausted:
            self._repository.transition_goal(
                goal_id, expected_version=int(goal["runtime_version"]), action="pause",
                now=started, reason=f"Goal budget exhausted: {', '.join(exhausted)}",
                principal=self._request_principal,
            )
            return None
        iteration = self._repository.claim_next_goal_iteration(
            self._owner_id, started, started + self._lease_duration, goal_id=goal_id,
            principal=self._request_principal,
        )
        if iteration is None or iteration.claim is None:
            return None
        goal = self._goal(goal_id)
        assert goal is not None
        turn = self._turn(iteration)
        source_key = f"goal:{goal_id}:iteration:{iteration.sequence}"
        try:
            self._repository.control_plane.prepare_tool_effect_retry(source_key, now=started)
        except RuntimeError as exc:
            return self._repository.fail_goal_iteration(
                iteration.iteration_id, iteration.claim, error="tool effect requires manual reconciliation",
                now=self._clock(), max_transient_failures=1,
                expected_goal_version=int(goal["runtime_version"]),
            )
        try:
            content, tokens, current_claim, guidance_sequence = await self._execute_turn(goal, iteration, turn, source_key)
            iteration = GoalIteration(
                iteration.iteration_id, iteration.goal_id, iteration.sequence,
                iteration.state, iteration.created_at, iteration.updated_at, current_claim,
                iteration.last_error,
            )
            judging = self._repository.mark_goal_iteration_judging(
                iteration.iteration_id, current_claim, now=self._clock()
            )
            judge, current_claim, judge_error = await self._judge_with_heartbeat(
                goal, judging, content, current_claim
            )
            # The renewed token becomes authoritative before inspecting any Judge
            # output. Every malformed/error settlement below must use this context.
            iteration = GoalIteration(
                iteration.iteration_id, iteration.goal_id, iteration.sequence,
                judging.state, iteration.created_at, judging.updated_at,
                current_claim, iteration.last_error, iteration.turn_id,
                iteration.judge_result, iteration.budget_delta,
            )
            if judge_error is not None or not isinstance(judge, JudgeResult):
                return self._repository.fail_goal_iteration(
                    iteration.iteration_id, current_claim,
                    error=(
                        f"{type(judge_error).__name__}: goal judge failed"
                        if judge_error is not None else "ValueError: goal judge returned an invalid result"
                    ),
                    now=self._clock(), max_transient_failures=self._max_transient_failures,
                    expected_goal_version=int(goal["runtime_version"]),
                )
            acceptance = GoalAcceptance(
                criteria=tuple(goal["acceptance_criteria"]),
                confidence_threshold=float(goal["judge_confidence_threshold"]),
            )
            acceptance.validate_judge(judge)
            finished = self._clock()
            active_delta = self._active_delta(goal, finished)
            cost = self._cost(goal, tokens)
            delta = {"tokens": tokens, "estimated_cost": cost, "active_seconds": active_delta}
            projected = self._projected_exhaustion(goal, delta)
            continue_running = not judge.done and not projected
            status = "completed" if judge.done else ("paused" if projected else "running")
            result = judge
            if projected:
                result = JudgeResult(
                    False, judge.confidence,
                    f"Goal budget exhausted: {', '.join(projected)}", judge.next_action,
                    criterion_evidence=dict(judge.criterion_evidence),
                )
            obligation = self._result_obligation(
                goal, content, result, finished, status=status, sequence=iteration.sequence
            ) if status in {"completed", "paused"} else None
            completed, _ = self._repository.finish_goal_iteration(
                iteration.iteration_id, current_claim,
                judge_result=result.to_dict(), budget_delta=delta,
                continue_running=continue_running, goal_status=status,
                create_continuation=continue_running or status == "paused",
                expected_goal_version=int(goal["runtime_version"]),
                guidance_sequence=guidance_sequence, terminal_obligation=obligation,
                now=finished,
            )
            return completed
        except (StaleClaimError, StateConflictError):
            raise
        except _ClaimedGoalError as exc:
            return self._repository.fail_goal_iteration(
                iteration.iteration_id, exc.claim,
                error=f"{type(exc).__name__}: goal execution failed",
                now=self._clock(), max_transient_failures=self._max_transient_failures,
                expected_goal_version=int(goal["runtime_version"]),
            )
        except Exception as exc:
            return self._repository.fail_goal_iteration(
                iteration.iteration_id, iteration.claim, error=f"{type(exc).__name__}: goal iteration failed",
                now=self._clock(), max_transient_failures=self._max_transient_failures,
                expected_goal_version=int(goal["runtime_version"]),
            )

    async def _judge_with_heartbeat(self, goal, iteration, content, claim):
        task = asyncio.create_task(
            self._judge.judge(goal=goal, iteration=iteration, content=content)
        )
        heartbeat = max(0.01, min(30.0, self._lease_duration.total_seconds() / 3))
        try:
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=heartbeat)
                except asyncio.TimeoutError:
                    at = self._clock()
                    claim = self._repository.renew_claim(
                        "goal_iteration", iteration.iteration_id, claim,
                        at, at + self._lease_duration,
                    )
            try:
                return await task, claim, None
            except Exception as exc:
                return None, claim, exc
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _execute_turn(self, goal, iteration, turn, source_key):
        if turn["status"] == "completed":
            result = turn.get("result") or {}
            content, tokens = self._authoritative_result(result)
            return (content, tokens, iteration.claim,
                    int((turn.get("metadata") or {}).get("goal_guidance_sequence", goal["last_guidance_sequence"])))
        guidance = self._repository.list_goal_guidance(
            goal["goal_id"], after_sequence=int(goal["last_guidance_sequence"]),
            principal=self._request_principal,
        )
        guidance_sequence = guidance[-1]["sequence"] if guidance else int(goal["last_guidance_sequence"])
        metadata = dict(turn.get("metadata") or {})
        bound = metadata.get("goal_guidance_sequence")
        if bound is not None and int(bound) != guidance_sequence:
            raise StateConflictError("goal turn guidance watermark changed")
        metadata["goal_guidance_sequence"] = guidance_sequence
        with self._repository.control_plane._get_conn() as conn:
            updated = conn.execute(
                "UPDATE runtime_turns SET metadata = ? WHERE turn_id = ? AND status = 'running'",
                (json.dumps(metadata, ensure_ascii=False), turn["turn_id"]),
            )
        if updated.rowcount != 1:
            raise StateConflictError("goal turn is no longer runnable")
        prompt = self._prompt(goal, guidance)
        session = self._repository.control_plane.get_session(goal["session_id"])
        if session is None or not isinstance(session.get("user_id"), str):
            raise StateConflictError("goal session principal is missing")
        request = AgentRequest(
            session_id=goal["session_id"],
            user_id=session["user_id"],
            messages=[{"role": "user", "content": prompt}],
            meta={
                "goal_id": goal["goal_id"], "goal_iteration": iteration.sequence,
                "source_event_key": source_key,
                "_runtime_control_plane": self._repository.control_plane,
            },
        )
        async def consume():
            terminal = None
            async for event in self._runner.run_stream(request, runtime_turn=turn):
                if event.event in {"complete", "error", "cancelled"}:
                    terminal = event
            return terminal
        task = asyncio.create_task(consume())
        claim = iteration.claim
        heartbeat = max(0.01, min(30.0, self._lease_duration.total_seconds() / 3))
        try:
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=heartbeat)
                except asyncio.TimeoutError:
                    at = self._clock()
                    claim = self._repository.renew_claim(
                        "goal_iteration", iteration.iteration_id, claim, at, at + self._lease_duration
                    )
            terminal = await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        try:
            if terminal is None or terminal.event != "complete":
                raise RuntimeError("Agent stream ended without authoritative completion")
            persisted = self._turn(iteration)
            if persisted["status"] != "completed" or terminal.turn_id != turn["turn_id"]:
                raise RuntimeError("Agent completion was not persisted authoritatively")
            result = persisted.get("result") or {}
            content, tokens = self._authoritative_result(result)
            return content, tokens, claim, guidance_sequence
        except (StaleClaimError, StateConflictError, asyncio.CancelledError):
            raise
        except Exception as exc:
            raise _ClaimedGoalError("authoritative Agent result is invalid", claim) from exc

    def _goal(self, goal_id: str):
        return self._repository.get_goal_for_principal(
            goal_id, self._request_principal, conceal=True
        )

    def _turn(self, iteration: GoalIteration):
        row = self._repository.control_plane._get_conn().execute(
            """SELECT rt.* FROM runtime_turns rt JOIN goal_iterations gi ON gi.turn_id = rt.turn_id
               WHERE gi.iteration_id = ?""", (iteration.iteration_id,),
        ).fetchone()
        if row is None:
            raise StateConflictError("goal iteration has no authoritative runtime turn")
        return self._repository.control_plane._row_to_dict(row)

    @staticmethod
    def _authoritative_result(result: Mapping[str, Any]) -> tuple[str, int]:
        if not isinstance(result, Mapping) or not {"content", "usage"}.issubset(result):
            raise ValueError("authoritative Agent result schema is invalid")
        if set(result) - {"content", "usage", "agent_result"}:
            raise ValueError("authoritative Agent result fields are unknown")
        content = result.get("content")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 65_536:
            raise ValueError("authoritative Agent content is invalid or too large")
        agent_result = result.get("agent_result")
        if agent_result is not None and (
            not isinstance(agent_result, str) or len(agent_result.encode("utf-8")) > 65_536
        ):
            raise ValueError("authoritative agent_result is invalid or too large")
        usage = result.get("usage")
        if not isinstance(usage, Mapping) or "total_tokens" not in usage:
            raise ValueError("authoritative token usage schema is invalid")
        if set(usage) - {"total_tokens", "prompt_tokens", "completion_tokens"}:
            raise ValueError("authoritative token usage fields are unknown")
        for name, value in usage.items():
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 9_000_000_000_000_000:
                raise ValueError("authoritative token usage is invalid")
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if prompt_tokens + completion_tokens > usage["total_tokens"]:
            raise ValueError("authoritative token usage aggregate is inconsistent")
        if len(json.dumps(dict(result), ensure_ascii=False).encode("utf-8")) > 131_072:
            raise ValueError("authoritative Agent result exceeds the aggregate byte limit")
        return content, usage["total_tokens"]

    @staticmethod
    def _prompt(goal: Mapping[str, Any], guidance: Sequence[Mapping[str, Any]]) -> str:
        parts = [f"Continue the durable goal:\n{goal['goal_text']}", f"Next action: {goal.get('active_step') or 'begin'}"]
        if guidance:
            parts.append("Persisted user guidance:\n" + "\n".join(
                f"[{item['sequence']}] {item['content']}" for item in guidance
            ))
        prompt = "\n\n".join(parts)
        encoded = prompt.encode("utf-8")
        if len(encoded) > 131_072 or (len(encoded) + 3) // 4 > 32_768:
            raise ValueError("goal prompt exceeds the byte or estimated-token limit")
        return prompt

    @staticmethod
    def _active_delta(goal: Mapping[str, Any], now: datetime) -> float:
        started = goal.get("active_started_at")
        return max(0.0, (now - datetime.fromisoformat(started)).total_seconds()) if started else 0.0

    @staticmethod
    def _cost(goal: Mapping[str, Any], tokens: int) -> float:
        version = goal.get("pricing_version")
        rate = goal.get("pricing_cost_per_token")
        if not version or rate is None or not isfinite(float(rate)) or float(rate) < 0:
            raise ValueError("persisted pricing snapshot is missing or invalid")
        return tokens * float(rate)

    def _exhausted(self, goal, now):
        active = float(goal["consumed_active_seconds"] or 0) + self._active_delta(goal, now)
        checks = {
            "iteration": (goal["consumed_iterations"], goal["max_iterations"]),
            "token": (goal["consumed_tokens"], goal["max_tokens"]),
            "cost": (goal["consumed_estimated_cost"], goal["max_estimated_cost"]),
            "active time": (active, goal["max_wall_clock_seconds"]),
        }
        return [name for name, (used, limit) in checks.items() if limit is None or float(used) >= float(limit)]

    @staticmethod
    def _projected_exhaustion(goal, delta):
        checks = {
            "iteration": (int(goal["consumed_iterations"]) + 1, goal["max_iterations"]),
            "token": (int(goal["consumed_tokens"]) + delta["tokens"], goal["max_tokens"]),
            "cost": (float(goal["consumed_estimated_cost"]) + delta["estimated_cost"], goal["max_estimated_cost"]),
            "active time": (float(goal["consumed_active_seconds"]) + delta["active_seconds"], goal["max_wall_clock_seconds"]),
        }
        return [name for name, (used, limit) in checks.items() if limit is None or float(used) >= float(limit)]

    def _result_obligation(self, goal, content, judge, now, *, status: str, sequence: int):
        destination = goal.get("terminal_destination")
        if not destination:
            return None
        terminal = status == "completed"
        key = (
            f"goal:{goal['goal_id']}:terminal:v1" if terminal
            else f"goal:{goal['goal_id']}:progress:budget:{sequence}:v1"
        )
        visible = content.strip() or judge.reason.strip() or f"Goal {status}"
        return self._repository.goal_outbox_obligation(
            goal, key=key, content=visible,
            kind="goal_terminal" if terminal else "goal_progress",
            goal_status=status, delivery_status="completed", now=now,
        )
