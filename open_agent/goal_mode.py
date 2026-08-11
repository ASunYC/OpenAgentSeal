"""Durable goal-mode controller built on the local control plane."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

from .control_plane import ControlPlane, get_control_plane


GOAL_STATUSES = {"draft", "running", "paused", "blocked", "completed", "failed", "cancelled"}
MAX_JUDGE_TEXT_BYTES = 16_384
MAX_EVIDENCE_BYTES = 65_536
MAX_EVIDENCE_ITEM_BYTES = 8_192


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class CriterionEvidence:
    satisfied: bool
    evidence: str
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.satisfied, bool):
            raise ValueError("criterion evidence satisfied must be a boolean")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("criterion evidence must be a non-empty string")
        if len(self.evidence.encode("utf-8")) > MAX_EVIDENCE_ITEM_BYTES:
            raise ValueError("criterion evidence exceeds the byte limit")
        if self.schema_version != "1":
            raise ValueError("unsupported criterion evidence schema version")

    @classmethod
    def from_value(cls, value: Any) -> "CriterionEvidence":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("criterion evidence must be an object")
        if set(value) not in ({"satisfied", "evidence"}, {"satisfied", "evidence", "schema_version"}):
            raise ValueError("criterion evidence fields are invalid")
        return cls(
            satisfied=value.get("satisfied"), evidence=value.get("evidence"),
            schema_version=value.get("schema_version", "1"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "satisfied": self.satisfied, "evidence": self.evidence}


@dataclass(frozen=True, slots=True)
class JudgeResult:
    done: bool
    confidence: float
    reason: str
    next_action: str
    criterion_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.done, bool):
            raise ValueError("Judge result field 'done' must be a boolean")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not isfinite(self.confidence):
            raise ValueError("Judge result field 'confidence' must be finite")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("Judge result field 'confidence' must be between 0 and 1")
        if not isinstance(self.reason, str) or not isinstance(self.next_action, str):
            raise ValueError("Judge reason and next_action must be strings")
        if len(self.reason.encode("utf-8")) > MAX_JUDGE_TEXT_BYTES or len(self.next_action.encode("utf-8")) > MAX_JUDGE_TEXT_BYTES:
            raise ValueError("Judge reason or next_action exceeds the byte limit")
        if not isinstance(self.criterion_evidence, Mapping) or len(self.criterion_evidence) > 100:
            raise ValueError("criterion_evidence must be a bounded object")
        normalized: dict[str, CriterionEvidence] = {}
        total = 0
        for key, value in self.criterion_evidence.items():
            if not isinstance(key, str) or not key.strip() or len(key.encode("utf-8")) > 4096:
                raise ValueError("criterion evidence keys must be bounded strings")
            item = CriterionEvidence.from_value(value)
            total += len(key.encode("utf-8")) + len(item.evidence.encode("utf-8"))
            normalized[key] = item
        if total > MAX_EVIDENCE_BYTES:
            raise ValueError("criterion evidence exceeds the aggregate byte limit")
        object.__setattr__(self, "criterion_evidence", MappingProxyType(normalized))

    @classmethod
    def from_json(cls, value: str | Mapping[str, Any]) -> "JudgeResult":
        try:
            data = json.loads(value) if isinstance(value, str) else value
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Judge result must be valid JSON") from exc
        if not isinstance(data, Mapping):
            raise ValueError("Judge result must be an object")
        required = {"done", "confidence", "reason", "next_action", "criterion_evidence"}
        if set(data) != required:
            raise ValueError("Judge result fields are incomplete or unknown")
        done = data["done"]
        confidence = data["confidence"]
        reason = data["reason"]
        next_action = data["next_action"]
        evidence = data["criterion_evidence"]
        if not isinstance(done, bool):
            raise ValueError("Judge result field 'done' must be a boolean")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("Judge result field 'confidence' must be numeric")
        if not isinstance(reason, str) or not isinstance(next_action, str):
            raise ValueError("Judge reason and next_action must be strings")
        if not isinstance(evidence, Mapping):
            raise ValueError("criterion_evidence must be an object")
        return cls(
            done=done,
            confidence=confidence,
            reason=reason,
            next_action=next_action,
            criterion_evidence=evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "done": self.done,
            "confidence": self.confidence,
            "reason": self.reason,
            "next_action": self.next_action,
            "criterion_evidence": {key: value.to_dict() for key, value in self.criterion_evidence.items()},
        }


@dataclass(frozen=True, slots=True)
class GoalState:
    goal_id: str
    session_id: str
    goal_text: str
    status: str
    plan: str = ""
    active_step: str = ""
    todo_items: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    attempt_count: int = 0
    last_judge_result: Mapping[str, Any] = field(default_factory=dict)
    resume_token: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    acceptance_criteria: tuple[str, ...] = field(default_factory=tuple)
    judge_confidence_threshold: float = 1.0
    consumed_iterations: int = 0
    consumed_tokens: int = 0
    consumed_estimated_cost: float = 0.0
    consumed_active_seconds: float = 0.0
    runtime_version: int = 0

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "GoalState":
        return cls(
            goal_id=record["goal_id"],
            session_id=record["session_id"],
            goal_text=record["goal_text"],
            status=record["status"],
            plan=record.get("plan", ""),
            active_step=record.get("active_step", ""),
            todo_items=tuple(_freeze(item) for item in record.get("todo_items", [])),
            attempt_count=record.get("attempt_count", 0),
            last_judge_result=_freeze(record.get("last_judge_result", {})),
            resume_token=record.get("resume_token", ""),
            created_at=record.get("created_at", ""),
            updated_at=record.get("updated_at", ""),
            metadata=_freeze(record.get("metadata", {})),
            acceptance_criteria=tuple(record.get("acceptance_criteria", [])),
            judge_confidence_threshold=record.get("judge_confidence_threshold", 1.0),
            consumed_iterations=record.get("consumed_iterations", 0),
            consumed_tokens=record.get("consumed_tokens", 0),
            consumed_estimated_cost=record.get("consumed_estimated_cost", 0.0),
            consumed_active_seconds=record.get("consumed_active_seconds", 0.0),
            runtime_version=record.get("runtime_version", 0),
        )


class GoalController:
    """Session-level controller for durable autonomous goal execution."""

    def __init__(
        self, control_plane: ControlPlane | None = None, *,
        goal_repository: Any | None = None, request_principal: Any | None = None,
    ):
        self.control_plane = control_plane or get_control_plane()
        self._goal_repository = goal_repository
        self._request_principal = request_principal

    def start_goal(
        self,
        session_id: str,
        goal_text: str,
        plan: str = "",
        todo_items: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        configuration: Any | None = None,
        destination: str | None = None,
    ) -> GoalState:
        if configuration is not None:
            if self._goal_repository is None or self._request_principal is None:
                raise PermissionError("configured goals require an authenticated Goal runtime context")
            iteration = self._goal_repository.create_goal_with_first_iteration(
                session_id=session_id, goal_text=goal_text,
                configuration=configuration.to_record(), now=datetime.now(timezone.utc),
                destination=destination, metadata=metadata, plan=plan,
                todo_items=todo_items or [], start_prompt=self.build_start_prompt(goal_text, plan=plan),
                principal=self._request_principal,
            )
            goal = self.control_plane.get_goal(iteration.goal_id) or {}
        else:
            goal = self.control_plane.create_goal(
                session_id=session_id,
                goal_text=goal_text,
                status="running",
                metadata=metadata,
            )
        if configuration is None and (plan or todo_items):
            goal = self.control_plane.update_goal(
                goal["goal_id"],
                plan=plan,
                todo_items=todo_items or [],
            )
        if configuration is None:
            self.control_plane.append_message(
                session_id,
                "user",
                self.build_start_prompt(goal_text, plan=plan),
                metadata={"goal_id": goal["goal_id"], "goal_event": "start"},
            )
        return GoalState.from_record(goal)

    def get_goal(self, goal_id: str) -> GoalState | None:
        record = (
            self._goal_repository.get_goal_for_principal(goal_id, self._request_principal)
            if self._goal_repository is not None and self._request_principal is not None
            else self.control_plane.get_goal(goal_id)
        )
        return GoalState.from_record(record) if record else None

    def list_goals(self) -> list[GoalState]:
        if self._goal_repository is None or self._request_principal is None:
            return [GoalState.from_record(item) for item in self.control_plane.list_goals()]
        return [
            GoalState.from_record(item)
            for item in self._goal_repository.list_goals_for_principal(
                self._request_principal
            )
        ]

    def pause_goal(self, goal_id: str, reason: str = "Paused by user") -> GoalState:
        return self._transition(goal_id, "paused", reason)

    def resume_goal(
        self, goal_id: str, reason: str = "Resumed by user", *,
        operator_decision: str | None = None,
        approval_id: str | None = None,
        budget_updates: Mapping[str, int | float] | None = None,
    ) -> GoalState:
        return self._transition(
            goal_id, "running", reason,
            operator_decision=operator_decision, approval_id=approval_id,
            budget_updates=budget_updates,
        )

    def cancel_goal(self, goal_id: str, reason: str = "Cancelled by user") -> GoalState:
        return self._transition(goal_id, "cancelled", reason)

    def apply_judge_result(self, goal_id: str, judge_result: JudgeResult | dict[str, Any] | str) -> GoalState:
        result = judge_result if isinstance(judge_result, JudgeResult) else JudgeResult.from_json(judge_result)
        goal = self.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal not found: {goal_id}")
        if goal.acceptance_criteria:
            raise RuntimeError("configured durable goals must be judged by GoalRunner")
        status = "completed" if result.done else "running"
        updated = self.control_plane.update_goal(
            goal_id,
            status=status,
            active_step="" if result.done else result.next_action,
            attempt_count=goal.attempt_count + 1,
            last_judge_result=result.to_dict(),
        )
        self.control_plane.append_message(
            goal.session_id,
            "system",
            f"Goal judge result: {json.dumps(result.to_dict(), ensure_ascii=False)}",
            metadata={"goal_id": goal_id, "goal_event": "judge"},
        )
        if not result.done and result.next_action:
            self.control_plane.append_message(
                goal.session_id,
                "user",
                self.build_continuation_prompt(goal.goal_text, result),
                metadata={"goal_id": goal_id, "goal_event": "continue"},
            )
        return GoalState.from_record(updated)

    def build_start_prompt(self, goal_text: str, plan: str = "") -> str:
        prompt = f"Start durable goal execution for:\n{goal_text}\n"
        if plan:
            prompt += f"\nInitial plan:\n{plan}\n"
        return prompt

    def build_continuation_prompt(self, goal_text: str, judge_result: JudgeResult) -> str:
        return (
            "Continue the durable goal in the same visible conversation.\n"
            f"Goal: {goal_text}\n"
            f"Judge reason: {judge_result.reason}\n"
            f"Next action: {judge_result.next_action}\n"
        )

    def _transition(
        self, goal_id: str, status: str, reason: str, *,
        operator_decision: str | None = None,
        approval_id: str | None = None,
        budget_updates: Mapping[str, int | float] | None = None,
    ) -> GoalState:
        if status not in GOAL_STATUSES:
            raise ValueError(f"Unsupported goal status: {status}")
        goal = self.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal not found: {goal_id}")
        if goal.acceptance_criteria and status in {"paused", "running", "cancelled"}:
            if self._goal_repository is None or self._request_principal is None:
                raise PermissionError("configured goals require an authenticated Goal runtime context")
            action = {"paused": "pause", "running": "resume", "cancelled": "cancel"}[status]
            updated = self._goal_repository.transition_goal(
                goal_id, expected_version=goal.runtime_version, action=action,
                now=datetime.now(timezone.utc), reason=reason,
                principal=self._request_principal, operator_decision=operator_decision,
                approval_id=approval_id, budget_updates=budget_updates,
            )
        else:
            updated = self.control_plane.update_goal(
                goal_id,
                status=status,
                metadata={**goal.metadata, "last_transition_reason": reason, "last_transition_at": datetime.now().isoformat()},
            )
        if not goal.acceptance_criteria:
            self.control_plane.append_message(
                goal.session_id,
                "system",
                f"Goal status changed to {status}: {reason}",
                metadata={"goal_id": goal_id, "goal_event": status},
            )
        return GoalState.from_record(updated)
