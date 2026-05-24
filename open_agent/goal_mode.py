"""Durable goal-mode controller built on the local control plane."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .control_plane import ControlPlane, get_control_plane


GOAL_STATUSES = {"draft", "running", "paused", "blocked", "completed", "failed", "cancelled"}


@dataclass
class JudgeResult:
    done: bool
    confidence: float
    reason: str
    next_action: str

    @classmethod
    def from_json(cls, value: str | dict[str, Any]) -> "JudgeResult":
        data = json.loads(value) if isinstance(value, str) else value
        done = data.get("done")
        if not isinstance(done, bool):
            raise ValueError("Judge result field 'done' must be a boolean")
        confidence = float(data.get("confidence", 0.0))
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("Judge result field 'confidence' must be between 0 and 1")
        return cls(
            done=done,
            confidence=confidence,
            reason=str(data.get("reason", "")),
            next_action=str(data.get("next_action", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "done": self.done,
            "confidence": self.confidence,
            "reason": self.reason,
            "next_action": self.next_action,
        }


@dataclass
class GoalState:
    goal_id: str
    session_id: str
    goal_text: str
    status: str
    plan: str = ""
    active_step: str = ""
    todo_items: list[dict[str, Any]] = field(default_factory=list)
    attempt_count: int = 0
    last_judge_result: dict[str, Any] = field(default_factory=dict)
    resume_token: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "GoalState":
        return cls(
            goal_id=record["goal_id"],
            session_id=record["session_id"],
            goal_text=record["goal_text"],
            status=record["status"],
            plan=record.get("plan", ""),
            active_step=record.get("active_step", ""),
            todo_items=record.get("todo_items", []),
            attempt_count=record.get("attempt_count", 0),
            last_judge_result=record.get("last_judge_result", {}),
            resume_token=record.get("resume_token", ""),
            created_at=record.get("created_at", ""),
            updated_at=record.get("updated_at", ""),
            metadata=record.get("metadata", {}),
        )


class GoalController:
    """Session-level controller for durable autonomous goal execution."""

    def __init__(self, control_plane: ControlPlane | None = None):
        self.control_plane = control_plane or get_control_plane()

    def start_goal(
        self,
        session_id: str,
        goal_text: str,
        plan: str = "",
        todo_items: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GoalState:
        goal = self.control_plane.create_goal(
            session_id=session_id,
            goal_text=goal_text,
            status="running",
            metadata=metadata,
        )
        if plan or todo_items:
            goal = self.control_plane.update_goal(
                goal["goal_id"],
                plan=plan,
                todo_items=todo_items or [],
            )
        self.control_plane.append_message(
            session_id,
            "user",
            self.build_start_prompt(goal_text, plan=plan),
            metadata={"goal_id": goal["goal_id"], "goal_event": "start"},
        )
        return GoalState.from_record(goal)

    def get_goal(self, goal_id: str) -> GoalState | None:
        record = self.control_plane.get_goal(goal_id)
        return GoalState.from_record(record) if record else None

    def pause_goal(self, goal_id: str, reason: str = "Paused by user") -> GoalState:
        return self._transition(goal_id, "paused", reason)

    def resume_goal(self, goal_id: str, reason: str = "Resumed by user") -> GoalState:
        return self._transition(goal_id, "running", reason)

    def cancel_goal(self, goal_id: str, reason: str = "Cancelled by user") -> GoalState:
        return self._transition(goal_id, "cancelled", reason)

    def apply_judge_result(self, goal_id: str, judge_result: JudgeResult | dict[str, Any] | str) -> GoalState:
        result = judge_result if isinstance(judge_result, JudgeResult) else JudgeResult.from_json(judge_result)
        goal = self.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal not found: {goal_id}")
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

    def _transition(self, goal_id: str, status: str, reason: str) -> GoalState:
        if status not in GOAL_STATUSES:
            raise ValueError(f"Unsupported goal status: {status}")
        goal = self.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal not found: {goal_id}")
        updated = self.control_plane.update_goal(
            goal_id,
            status=status,
            metadata={**goal.metadata, "last_transition_reason": reason, "last_transition_at": datetime.now().isoformat()},
        )
        self.control_plane.append_message(
            goal.session_id,
            "system",
            f"Goal status changed to {status}: {reason}",
            metadata={"goal_id": goal_id, "goal_event": status},
        )
        return GoalState.from_record(updated)
