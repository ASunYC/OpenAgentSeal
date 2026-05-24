"""Lightweight autonomous runtime primitives for roadmap phases 4-8."""

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .control_plane import ControlPlane, get_control_plane


@dataclass
class MemoryProvenance:
    source: str
    session_id: str | None = None
    goal_id: str | None = None
    tool_call_id: str | None = None
    file_path: str | None = None
    confidence: float = 1.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "tool_call_id": self.tool_call_id,
            "file_path": self.file_path,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


def export_memory_vault(memories: list[dict[str, Any]], output_dir: str | Path) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, memory in enumerate(memories, start=1):
        path = output / f"memory-{index:04d}.md"
        provenance = memory.get("provenance") or memory.get("metadata", {}).get("provenance", {})
        content = memory.get("content", "")
        path.write_text(
            "---\n"
            f"source: {provenance.get('source', 'unknown')}\n"
            f"session_id: {provenance.get('session_id', '')}\n"
            f"goal_id: {provenance.get('goal_id', '')}\n"
            f"tool_call_id: {provenance.get('tool_call_id', '')}\n"
            f"confidence: {provenance.get('confidence', '')}\n"
            "---\n\n"
            f"{content}\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


@dataclass
class SchedulerJobSpec:
    schedule: str
    prompt: str
    goal_id: str | None = None
    next_run_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SchedulerController:
    """Durable scheduler facade backed by the control plane."""

    def __init__(self, control_plane: ControlPlane | None = None):
        self.control_plane = control_plane or get_control_plane()

    def create_job(self, spec: SchedulerJobSpec) -> dict[str, Any]:
        return self.control_plane.create_scheduler_job(
            schedule=spec.schedule,
            prompt=spec.prompt,
            goal_id=spec.goal_id,
            next_run_at=spec.next_run_at,
            metadata=spec.metadata,
        )

    def pause_job(self, job_id: str) -> dict[str, Any]:
        return self._set_job_status(job_id, "paused")

    def resume_job(self, job_id: str) -> dict[str, Any]:
        return self._set_job_status(job_id, "active")

    def delete_job(self, job_id: str) -> dict[str, Any]:
        return self._set_job_status(job_id, "deleted")

    def _set_job_status(self, job_id: str, status: str) -> dict[str, Any]:
        return self.control_plane.update_scheduler_job_status(job_id, status)


@dataclass
class DelegationSpec:
    parent_goal_id: str
    user_input: str
    role: str
    allowed_tools: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    max_depth: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DelegationResult:
    delegation_id: str
    status: str
    summary: str = ""
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class DelegationController:
    """Bounded delegation contract without spawning agents directly."""

    def __init__(self, max_delegates: int = 3, max_depth: int = 1):
        self.max_delegates = max_delegates
        self.max_depth = max_depth
        self.active: dict[str, DelegationSpec] = {}
        self._lock = threading.Lock()

    def submit(self, spec: DelegationSpec) -> DelegationResult:
        with self._lock:
            if len(self.active) >= self.max_delegates:
                return DelegationResult(delegation_id="", status="rejected", error="Maximum active delegations reached")
            if spec.max_depth > self.max_depth:
                return DelegationResult(delegation_id="", status="rejected", error="Delegation depth exceeds policy")
            delegation_id = f"delegate_{uuid.uuid4().hex[:8]}"
            self.active[delegation_id] = spec
        return DelegationResult(delegation_id=delegation_id, status="queued", data={"allowed_tools": spec.allowed_tools})

    def complete(self, delegation_id: str, summary: str) -> DelegationResult:
        with self._lock:
            if delegation_id not in self.active:
                raise KeyError(f"Delegation not found: {delegation_id}")
            del self.active[delegation_id]
        return DelegationResult(delegation_id=delegation_id, status="completed", summary=summary)


class ObservabilitySnapshot:
    """Aggregates goal, scheduler, and metadata state for UI/API surfaces."""

    def __init__(self, control_plane: ControlPlane | None = None):
        self.control_plane = control_plane or get_control_plane()

    def build(self, session_id: str | None = None) -> dict[str, Any]:
        goals = self.control_plane.list_goals(session_id=session_id)
        jobs = self.control_plane.list_scheduler_jobs(session_id=session_id)
        return {
            "session_id": session_id,
            "goals": goals,
            "scheduler_jobs": jobs,
            "generated_at": datetime.now().isoformat(),
        }


class GoalReplay:
    """Minimal replay helper for verifying expected goal final state."""

    def __init__(self, control_plane: ControlPlane | None = None):
        self.control_plane = control_plane or get_control_plane()

    def assert_goal_status(self, goal_id: str, expected_status: str) -> bool:
        goal = self.control_plane.get_goal(goal_id)
        return bool(goal and goal["status"] == expected_status)

    def export_trajectory(self, session_id: str) -> list[dict[str, Any]]:
        return self.control_plane.list_messages(session_id)
