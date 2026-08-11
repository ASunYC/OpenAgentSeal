"""Durable, channel-neutral inbound route resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from open_agent.durable_runtime.repository import DurableRuntimeRepository

from .contracts import NormalizedInboundEvent


class RouteResolutionError(RuntimeError):
    """A route cannot be resolved safely."""


@dataclass(frozen=True, slots=True)
class ResolvedRoute:
    account_id: str
    route_id: str
    profile_id: str
    session_id: str | None
    thread_id: str | None
    trigger_policy: str
    should_dispatch: bool


class GatewayRouter:
    """Resolve normalized events through Task 2's durable repository."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repository = repository
        self._now = now

    def resolve(self, event: NormalizedInboundEvent) -> ResolvedRoute:
        try:
            route = self._repository.resolve_channel_route(
                account_id=event.account_id,
                conversation_id=event.conversation_id,
                sender_id=event.sender_id,
                now=self._now(),
                expected_adapter_kind=event.adapter_kind,
                should_dispatch=lambda policy: self._should_dispatch(policy, event),
                require_profile=True,
            )
        except (ValueError, RuntimeError) as exc:
            raise RouteResolutionError(str(exc)) from exc
        return ResolvedRoute(
            account_id=event.account_id,
            route_id=route["route_id"],
            profile_id=route["profile_id"],
            session_id=route["session_id"],
            thread_id=route["thread_id"],
            trigger_policy=route["trigger_policy"],
            should_dispatch=route["should_dispatch"],
        )

    @staticmethod
    def _should_dispatch(policy: str, event: NormalizedInboundEvent) -> bool:
        if event.metadata.get("sender_is_bot") is True:
            return False
        if policy == "always":
            return True
        if policy == "never":
            return False
        if policy == "mention":
            return bool(event.mentioned_bot)
        if policy == "reply":
            return bool(event.replies_to_bot)
        if policy == "default":
            return event.conversation_kind == "dm" or event.mentioned_bot or event.replies_to_bot
        raise RouteResolutionError(f"unsupported trigger policy: {policy}")
