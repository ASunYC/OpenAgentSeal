"""Explicit, crash-safe execution of durable five-field cron jobs."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from open_agent.app.runner.models import AgentRequest
from open_agent.durable_runtime.models import OutboxObligation, SchedulerRun
from open_agent.durable_runtime.repository import (
    DurableRuntimeRepository,
    StateConflictError,
)


DEFAULT_SCHEDULER_TIMEZONE = "Asia/Shanghai"
def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CronSchedule:
    expression: str
    timezone: ZoneInfo

    @classmethod
    def parse(
        cls,
        expression: str,
        timezone_name: str = DEFAULT_SCHEDULER_TIMEZONE,
    ) -> "CronSchedule":
        if not isinstance(expression, str) or len(expression) > 255:
            raise ValueError("cron expression must be a string")
        fields = expression.split()
        if len(fields) != 5 or expression != " ".join(fields):
            raise ValueError("cron expression must contain exactly five normalized fields")
        if not croniter.is_valid(expression, second_at_beginning=False):
            raise ValueError("invalid five-field cron expression")
        if (
            not isinstance(timezone_name, str)
            or not timezone_name.strip()
            or len(timezone_name) > 255
        ):
            raise ValueError("timezone must be a valid IANA name")
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError("timezone must be a valid IANA name") from exc
        return cls(expression=expression, timezone=zone)

    def next_occurrence(self, after: datetime) -> datetime:
        _aware(after, "after")
        local_after = after.astimezone(self.timezone)
        iterator = croniter(self.expression, local_after)
        after_utc = after.astimezone(timezone.utc)
        for _ in range(8):
            candidate = iterator.get_next(datetime)
            # croniter normalizes nonexistent wall times to the DST transition.
            # Such a value no longer matches the requested fields and is skipped.
            if not croniter.match(self.expression, candidate.replace(tzinfo=None)):
                continue
            if candidate.astimezone(timezone.utc) > after_utc:
                return candidate
        raise RuntimeError("cron schedule did not produce a valid future occurrence")

    def _latest_occurrence(self, at_or_before: datetime) -> datetime:
        """Calculate latest-only catch-up without replaying every missed tick."""
        _aware(at_or_before, "at_or_before")
        local = at_or_before.astimezone(self.timezone)
        iterator = croniter(self.expression, local + timedelta(microseconds=1))
        boundary_utc = at_or_before.astimezone(timezone.utc)
        for _ in range(8):
            candidate = iterator.get_prev(datetime)
            if not croniter.match(self.expression, candidate.replace(tzinfo=None)):
                continue
            if candidate.astimezone(timezone.utc) <= boundary_utc:
                return candidate
        raise RuntimeError("cron schedule did not produce a valid prior occurrence")


class SchedulerWorker:
    """Callable scanner/executor; Task 10 owns recurring process supervision."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        runner,
        *,
        clock: Callable[[], datetime] | None = None,
        owner_id: str = "scheduler-worker",
        lease_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._repository = repository
        self._runner = runner
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._owner_id = owner_id
        self._lease_duration = lease_duration

    def scan_once(self, now: datetime | None = None, *, limit: int = 100) -> list[SchedulerRun]:
        scan_time = now or self._clock()
        _aware(scan_time, "now")
        jobs = self._repository.control_plane.list_due_scheduler_jobs(scan_time, limit)
        created: list[SchedulerRun] = []
        for job in jobs:
            try:
                schedule = CronSchedule.parse(job["schedule"], job["timezone"])
                expected_cursor = self._parse_cursor(job["next_run_at"])
                latest = schedule._latest_occurrence(scan_time)
                if latest.astimezone(timezone.utc) < expected_cursor.astimezone(timezone.utc):
                    latest = expected_cursor
                future = schedule.next_occurrence(latest)
            except (TypeError, ValueError, RuntimeError):
                self._repository.control_plane.update_scheduler_job_status(
                    job["job_id"], "paused"
                )
                continue
            run = self._repository.create_due_scheduler_run(
                job["job_id"],
                latest,
                future,
                expected_cursor=expected_cursor,
                now=scan_time,
                skip_if_overlapping=job["overlap_policy"] == "skip",
            )
            if run is not None:
                created.append(run)
        return created

    def request_manual_run(
        self, job_id: str, request_id: str, now: datetime | None = None
    ) -> SchedulerRun:
        return self._repository.create_manual_scheduler_run(
            job_id, request_id, now=now or self._clock()
        )

    async def execute_run(self, run_id: str) -> SchedulerRun:
        now = self._clock()
        claimed = self._repository.claim_due_scheduler_runs(
            self._owner_id,
            now,
            now + self._lease_duration,
            run_id=run_id,
        )
        if not claimed:
            current = self._repository.get_scheduler_run(run_id)
            if current is None:
                raise KeyError(f"Scheduler run not found: {run_id}")
            return current
        run = claimed[0]
        assert run.claim is not None
        job = self._repository.control_plane.get_scheduler_job(run.job_id)
        if job is None:
            return self._retry(run, "scheduler job was deleted", now)
        row = self._repository.control_plane._get_conn().execute(
            "SELECT turn_id FROM scheduler_runs WHERE run_id = ?", (run.run_id,)
        ).fetchone()
        turn = self._repository.control_plane._row_to_dict(
            self._repository.control_plane._get_conn().execute(
                "SELECT * FROM runtime_turns WHERE turn_id = ?", (row["turn_id"],)
            ).fetchone()
        )
        turn_metadata = turn.get("metadata") if isinstance(turn.get("metadata"), dict) else {}
        source_event_key = f"scheduler:{run.run_id}"
        request = AgentRequest(
            session_id=f"scheduler:{run.job_id}",
            user_id=str(turn_metadata.get("user_id") or "default"),
            messages=[{"role": "user", "content": job["prompt"]}],
            meta={
                "profile_id": str(turn_metadata.get("profile_id") or "main"),
                "scheduler_job_id": run.job_id,
                "scheduler_run_id": run.run_id,
                "source_event_key": source_event_key,
                "_runtime_control_plane": self._repository.control_plane,
            },
        )
        try:
            self._repository.control_plane.prepare_tool_effect_retry(
                source_event_key, now=now
            )
        except RuntimeError:
            return self._fail_manual_reconciliation(
                run, "scheduler tool effect requires manual reconciliation", now
            )
        if turn["status"] == "completed":
            result = turn.get("result")
            recovered_content = (
                str(result.get("content") or "") if isinstance(result, dict) else ""
            )
            return self._finish_completed(run, job, recovered_content, now)
        async def consume_stream() -> tuple[bool, str, str | None]:
            complete = False
            content = ""
            error: str | None = None
            async for event in self._runner.run_stream(request, runtime_turn=turn):
                if event.event == "complete":
                    complete = True
                    content = event.content if isinstance(event.content, str) else ""
                elif event.event in {"error", "cancelled"}:
                    error = f"Agent stream terminated with {event.event}"
                    break
            return complete, content, error

        current_claim = run.claim
        runner_task = asyncio.create_task(consume_stream())
        heartbeat_seconds = max(0.01, min(30.0, self._lease_duration.total_seconds() / 3))
        try:
            while not runner_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(runner_task), timeout=heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    heartbeat_now = self._clock()
                    current_claim = self._repository.renew_claim(
                        "scheduler_run",
                        run.run_id,
                        current_claim,
                        heartbeat_now,
                        heartbeat_now + self._lease_duration,
                    )
            complete, content, error = await runner_task
        except Exception as exc:
            runner_task.cancel()
            error = f"Agent stream failed: {type(exc).__name__}"
            complete = False
            content = ""
        run = replace(run, claim=current_claim)
        finished_at = self._clock()
        if not complete or error is not None:
            return self._retry(run, error or "Agent stream ended without completion", finished_at)
        return self._finish_completed(run, job, content, finished_at)

    def _finish_completed(
        self, run: SchedulerRun, job: dict, content: str, now: datetime
    ) -> SchedulerRun:
        destination = job.get("destination")
        if destination and not content.strip():
            return self._retry(run, "scheduled destination requires non-empty content", now)
        try:
            obligation = self._obligation(run, job, destination, content, now) if destination else None
            return self._repository.complete_scheduler_run(
                run.run_id, run.claim, content=content, obligation=obligation, now=now
            )
        except StateConflictError as exc:
            return self._retry(run, str(exc), now)

    def _fail_manual_reconciliation(
        self, run: SchedulerRun, error: str, now: datetime
    ) -> SchedulerRun:
        assert run.claim is not None
        return self._repository.retry_scheduler_run(
            run.run_id,
            run.claim,
            error,
            now=now,
            next_attempt_at=None,
            failed=True,
        )

    def _retry(self, run: SchedulerRun, error: str, now: datetime) -> SchedulerRun:
        assert run.claim is not None
        job = self._repository.control_plane.get_scheduler_job(run.job_id)
        max_retries = int(job["max_retries"]) if job else 0
        failed = run.attempt > max_retries
        bounded_exponent = min(7, max(0, run.attempt - 1))
        delay = min(3600, 30 * (2 ** bounded_exponent))
        return self._repository.retry_scheduler_run(
            run.run_id,
            run.claim,
            error,
            now=now,
            next_attempt_at=None if failed else now + timedelta(seconds=delay),
            failed=failed,
        )

    @staticmethod
    def _parse_cursor(raw: str) -> datetime:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        value = datetime.fromisoformat(normalized)
        _aware(value, "persisted scheduler cursor")
        return value

    @staticmethod
    def _obligation(
        run: SchedulerRun,
        job: dict,
        destination: str,
        content: str,
        now: datetime,
    ) -> OutboxObligation:
        if destination.startswith("channel:"):
            from open_agent.gateway.destinations import channel_obligation

            metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
            conversation_id = metadata.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id.strip():
                raise StateConflictError(
                    "channel scheduler destination requires metadata.conversation_id"
                )
            return channel_obligation(
                account_id=destination.removeprefix("channel:"),
                conversation_id=conversation_id,
                content=content,
                source_event_key=f"scheduler:{run.run_id}",
                now=now,
                metadata={"scheduler_job_id": run.job_id, "scheduler_run_id": run.run_id},
            )
        identity = json.dumps([run.run_id, destination], separators=(",", ":"))
        obligation_id = f"delivery:scheduler:{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"
        return OutboxObligation(
            obligation_id=obligation_id,
            idempotency_key=f"scheduler-result:{run.run_id}",
            destination=destination,
            payload={
                "content": content,
                "scheduler_run_id": run.run_id,
                "scheduler_job_id": run.job_id,
            },
            created_at=now,
            updated_at=now,
        )


__all__ = ["CronSchedule", "SchedulerWorker"]
