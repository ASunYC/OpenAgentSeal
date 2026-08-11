from datetime import datetime, timedelta, timezone

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import StaleClaimError


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def control_plane(tmp_path):
    value = ControlPlane(tmp_path)
    value.create_session("session-1")
    value.create_runtime_thread(
        session_id="session-1", thread_id="thread-1", user_id="gateway-user"
    )
    value.start_runtime_turn(
        "thread-1", session_id="session-1", turn_id="turn-1", user_input="run"
    )
    try:
        yield value
    finally:
        value.close()


def claim(
    control_plane, owner, now, *, mode="non_idempotent",
    platform_tool_call_id="call-1", invocation_id="step:1:tool:1",
    turn_id="turn-1",
):
    return control_plane.claim_tool_effect(
        session_id="session-1",
        turn_id=turn_id,
        source_event_key='["account-1","event-1"]',
        platform_tool_call_id=platform_tool_call_id,
        invocation_id=invocation_id,
        tool_name="external_write",
        arguments={"value": 1},
        idempotency_mode=mode,
        owner_id=owner,
        now=now,
        expires_at=now + timedelta(seconds=10),
    )


def test_non_idempotent_crash_after_effect_requires_manual_reconciliation(control_plane):
    first = claim(control_plane, "worker-1", NOW)
    assert first["disposition"] == "execute"

    recovered = claim(
        control_plane,
        "worker-2",
        NOW + timedelta(seconds=10),
    )

    assert recovered["disposition"] == "manual_reconciliation"
    assert recovered["state"] == "delivery_unknown"


def test_idempotent_effect_can_be_reclaimed_but_stale_owner_cannot_complete(control_plane):
    first = claim(control_plane, "worker-1", NOW, mode="idempotent")
    second = claim(
        control_plane,
        "worker-2",
        NOW + timedelta(seconds=10),
        mode="idempotent",
    )
    assert second["disposition"] == "execute"
    assert second["claim_generation"] == first["claim_generation"] + 1

    with pytest.raises(StaleClaimError):
        control_plane.complete_tool_effect(
            first["tool_call_id"], first["claim"], success=True,
            result={"content": "done"}, now=NOW + timedelta(seconds=10),
        )
    completed = control_plane.complete_tool_effect(
        second["tool_call_id"], second["claim"], success=True,
        result={"content": "done"}, now=NOW + timedelta(seconds=11),
    )
    assert completed["state"] == "completed"


def test_completed_tool_effect_replays_persisted_result_without_execution(control_plane):
    first = claim(control_plane, "worker-1", NOW, mode="idempotent")
    control_plane.complete_tool_effect(
        first["tool_call_id"], first["claim"], success=True,
        result={"content": "stable-result"}, now=NOW + timedelta(seconds=1),
    )

    replay = claim(
        control_plane,
        "worker-after-restart",
        NOW + timedelta(seconds=2),
        mode="idempotent",
    )

    assert replay["disposition"] == "replay"
    assert replay["result"] == {"content": "stable-result"}


def test_stable_invocation_replays_when_provider_changes_tool_call_id(control_plane):
    first = claim(control_plane, "worker-1", NOW, mode="idempotent")
    control_plane.complete_tool_effect(
        first["tool_call_id"], first["claim"], success=True,
        result={"content": "once"}, now=NOW + timedelta(seconds=1),
    )

    replay = claim(
        control_plane, "worker-2", NOW + timedelta(seconds=2), mode="idempotent",
        platform_tool_call_id="provider-generated-a-different-id",
    )

    assert replay["tool_call_id"] == first["tool_call_id"]
    assert replay["disposition"] == "replay"

    retry_turn_replay = claim(
        control_plane, "worker-3", NOW + timedelta(seconds=3), mode="idempotent",
        platform_tool_call_id="yet-another-provider-id", turn_id="turn-retry-2",
    )
    assert retry_turn_replay["tool_call_id"] == first["tool_call_id"]
    assert retry_turn_replay["disposition"] == "replay"


def test_uncertain_claimed_effect_is_fenced_for_manual_reconciliation(control_plane):
    effect = claim(control_plane, "worker-1", NOW)

    unknown = control_plane.mark_tool_effect_delivery_unknown(
        effect["tool_call_id"], effect["claim"], now=NOW + timedelta(seconds=1),
        reason="connection closed after request write",
    )

    assert unknown["state"] == "delivery_unknown"
    assert unknown["reconciliation"] == "manual_required"
    assert claim(control_plane, "worker-2", NOW + timedelta(seconds=2))["disposition"] == "manual_reconciliation"
