from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import uuid

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import DurableRuntimeRepository
from open_agent.gateway.contracts import (
    ChannelCapabilities,
    NormalizedInboundEvent,
    OutboundMessage,
)
from open_agent.gateway.router import GatewayRouter, RouteResolutionError


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def repository(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    try:
        yield repository
    finally:
        control_plane.close()


def event(**changes):
    values = {
        "event_key": "platform-event-1",
        "adapter_kind": "test",
        "account_id": "account-1",
        "conversation_id": "conversation-1",
        "sender_id": "sender-1",
        "conversation_kind": "dm",
        "text": "hello",
        "metadata": {"nested": {"source": "fixture"}},
    }
    values.update(changes)
    return NormalizedInboundEvent(**values)


def configure_account(repository, **changes):
    values = {
        "account_id": "account-1",
        "adapter_kind": "test",
        "default_profile_id": "default-profile",
        "now": NOW,
    }
    values.update(changes)
    return repository.upsert_channel_account(**values)


def test_normalized_event_ids_and_nested_metadata_are_immutable():
    inbound = event()

    with pytest.raises(FrozenInstanceError):
        inbound.account_id = "other"
    with pytest.raises(TypeError):
        inbound.metadata["nested"]["source"] = "changed"
    with pytest.raises(ValueError, match="account_id"):
        event(account_id=" ")
    with pytest.raises(TypeError, match="mentioned_bot"):
        event(mentioned_bot="false")
    with pytest.raises(TypeError, match="replies_to_bot"):
        event(replies_to_bot=1)


def test_contract_values_are_recursively_copied_into_a_strict_immutable_domain():
    mutable_bytes = bytearray(b"safe")
    inbound = event(
        metadata={"blob": mutable_bytes, "nested": [{"enabled": True}]},
        attachments=[{"attachment_id": "file-1"}],
    )
    mutable_bytes[:] = b"evil"

    assert inbound.metadata["blob"] == b"safe"
    assert inbound.metadata["nested"][0]["enabled"] is True
    assert inbound.attachments[0]["attachment_id"] == "file-1"
    with pytest.raises(TypeError):
        inbound.attachments[0]["attachment_id"] = "changed"


@pytest.mark.parametrize(
    "changes",
    [
        {"metadata": None},
        {"metadata": {1: "numeric key"}},
        {"metadata": {type("StringKey", (str,), {})("derived"): "bad key"}},
        {"metadata": {"custom": object()}},
        {"metadata": {"set": {"mutable"}}},
        {"metadata": {"nan": float("nan")}},
        {"attachments": None},
        {"attachments": "file-1"},
    ],
)
def test_contracts_reject_values_outside_the_immutable_json_like_domain(changes):
    with pytest.raises(TypeError):
        event(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"supports_threads": 1},
        {"supports_replies": "false"},
        {"max_message_chars": True},
        {"max_message_chars": 1.5},
    ],
)
def test_channel_capabilities_require_exact_booleans_and_non_bool_integer_limits(changes):
    with pytest.raises((TypeError, ValueError)):
        ChannelCapabilities(**changes)


def test_outbound_contract_applies_the_same_metadata_and_attachment_validation():
    with pytest.raises(TypeError):
        OutboundMessage("account", "conversation", "hello", metadata={1: "bad"})
    with pytest.raises(TypeError):
        OutboundMessage("account", "conversation", "hello", attachments="file")


@pytest.mark.parametrize(
    ("conversation_kind", "mentioned", "reply", "expected"),
    [
        ("dm", False, False, True),
        ("group", True, False, True),
        ("group", False, True, True),
        ("group", False, False, False),
    ],
)
def test_default_trigger_policy_handles_dm_mentions_and_replies(
    repository, conversation_kind, mentioned, reply, expected
):
    configure_account(repository)
    resolved = GatewayRouter(repository, now=lambda: NOW).resolve(
        event(
            conversation_kind=conversation_kind,
            mentioned_bot=mentioned,
            replies_to_bot=reply,
        )
    )

    assert resolved.should_dispatch is expected
    assert resolved.profile_id == "default-profile"


def test_sender_route_overrides_conversation_route_and_account_default(repository):
    configure_account(repository)
    repository.upsert_channel_route(
        account_id="account-1",
        conversation_id="conversation-1",
        profile_id="conversation-profile",
        now=NOW,
    )
    repository.upsert_channel_route(
        account_id="account-1",
        conversation_id="conversation-1",
        sender_id="sender-1",
        profile_id="sender-profile",
        trigger_policy="always",
        now=NOW,
    )

    resolved = GatewayRouter(repository, now=lambda: NOW).resolve(
        event(conversation_kind="group")
    )

    assert resolved.profile_id == "sender-profile"
    assert resolved.should_dispatch is True


def test_route_mapping_is_stable_and_persisted_in_runtime_tables(repository):
    configure_account(repository)
    router = GatewayRouter(repository, now=lambda: NOW)

    first = router.resolve(event())
    second = GatewayRouter(repository, now=lambda: NOW).resolve(event(event_key="event-2"))

    assert second.session_id == first.session_id
    assert second.thread_id == first.thread_id
    assert repository.control_plane.get_session(first.session_id) is not None
    assert repository.control_plane.get_runtime_thread(first.thread_id)["session_id"] == first.session_id


def test_composite_gateway_ids_and_shared_principals_are_unambiguous(repository):
    first_id = repository._gateway_id("route", "a\x1fb", "c", "")
    second_id = repository._gateway_id("route", "a", "b\x1fc", "")
    assert first_id != second_id

    configure_account(repository, account_id="a:b")
    configure_account(repository, account_id="a")
    router = GatewayRouter(repository, now=lambda: NOW)
    first = router.resolve(
        event(account_id="a:b", conversation_id="c", sender_id="sender")
    )
    second = router.resolve(
        event(account_id="a", conversation_id="b:c", sender_id="sender")
    )
    first_session = repository.control_plane.get_session(first.session_id)
    second_session = repository.control_plane.get_session(second.session_id)

    assert first.session_id != second.session_id
    assert first_session["user_id"] != second_session["user_id"]


def test_legacy_shared_route_principal_is_migrated_atomically(repository):
    configure_account(repository)

    def legacy_id(prefix, *parts):
        value = "\x1f".join(parts)
        return f"{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex}"

    route_id = legacy_id("route", "account-1", "conversation-1", "")
    session_id = legacy_id("session", route_id)
    thread_id = legacy_id("thread", route_id)
    legacy_principal = "gateway:account-1:conversation-1"
    repository.control_plane.create_session(
        session_id=session_id,
        channel="gateway",
        user_id=legacy_principal,
        metadata={"route_id": route_id},
    )
    repository.control_plane.create_runtime_thread(
        session_id=session_id,
        thread_id=thread_id,
        user_id=legacy_principal,
        metadata={"route_id": route_id},
    )
    with repository.control_plane._get_conn() as conn:
        conn.execute(
            """
            INSERT INTO channel_routes (
                route_id, account_id, conversation_id, sender_id, profile_id,
                trigger_policy, session_id, thread_id, created_at, updated_at, metadata
            ) VALUES (?, 'account-1', 'conversation-1', '', NULL,
                      'default', ?, ?, ?, ?, '{}')
            """,
            (route_id, session_id, thread_id, NOW.isoformat(), NOW.isoformat()),
        )

    resolved = GatewayRouter(repository, now=lambda: NOW).resolve(event())
    expected_principal = repository._gateway_id(
        "principal", "account-1", "conversation-1"
    )

    assert resolved.session_id == session_id
    assert repository.control_plane.get_session(session_id)["user_id"] == expected_principal
    assert repository.control_plane.get_runtime_thread(thread_id)["user_id"] == expected_principal


def test_account_validation_and_route_provisioning_share_an_explicit_transaction(repository):
    configure_account(repository)
    observed = []

    repository.resolve_channel_route(
        account_id="account-1",
        conversation_id="conversation-1",
        sender_id="sender-1",
        now=NOW,
        expected_adapter_kind="test",
        should_dispatch=lambda policy: observed.append(
            repository.control_plane._get_conn().in_transaction
        )
        or True,
        require_profile=True,
    )

    assert observed == [True]


def test_ignored_group_event_does_not_create_route_or_runtime_state(repository):
    configure_account(repository)
    conn = repository.control_plane._get_conn()
    session_count = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]

    resolved = GatewayRouter(repository, now=lambda: NOW).resolve(
        event(conversation_kind="group")
    )

    assert resolved.should_dispatch is False
    assert resolved.session_id is None
    assert resolved.thread_id is None
    assert conn.execute("SELECT count(*) FROM channel_routes").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == session_count


def test_shared_conversation_route_uses_conversation_principal_not_first_sender(repository):
    configure_account(repository)
    repository.upsert_channel_route(
        account_id="account-1",
        conversation_id="conversation-1",
        trigger_policy="always",
        now=NOW,
    )
    router = GatewayRouter(repository, now=lambda: NOW)

    first = router.resolve(event(sender_id="sender-a", conversation_kind="group"))
    second = router.resolve(event(sender_id="sender-b", conversation_kind="group"))

    assert first.session_id == second.session_id
    session = repository.control_plane.get_session(first.session_id)
    thread = repository.control_plane.get_runtime_thread(first.thread_id)
    principal = repository._gateway_id("principal", "account-1", "conversation-1")
    assert session["user_id"] == principal
    assert thread["user_id"] == principal


@pytest.mark.parametrize("collision", ["session", "thread", "matching"])
def test_route_provisioning_rejects_precreated_id_collisions(repository, collision):
    configure_account(repository)
    route_id = repository._gateway_id("route", "account-1", "conversation-1", "")
    session_id = repository._gateway_id("session", route_id)
    thread_id = repository._gateway_id("thread", route_id)
    principal = repository._gateway_id("principal", "account-1", "conversation-1")
    if collision == "session":
        repository.control_plane.create_session(
            session_id=session_id, channel="attacker", user_id="attacker"
        )
    elif collision == "matching":
        repository.control_plane.create_session(
            session_id=session_id,
            channel="gateway",
            user_id=principal,
            metadata={"route_id": route_id},
        )
        repository.control_plane.create_runtime_thread(
            session_id=session_id,
            thread_id=thread_id,
            user_id=principal,
            metadata={"route_id": route_id},
        )
    else:
        repository.control_plane.create_session(
            session_id="attacker-session", channel="attacker", user_id="attacker"
        )
        repository.control_plane.create_runtime_thread(
            session_id="attacker-session",
            thread_id=thread_id,
            user_id="attacker",
            metadata={"route_id": route_id},
        )

    with pytest.raises(RouteResolutionError, match="collision"):
        GatewayRouter(repository, now=lambda: NOW).resolve(event())

    assert repository.control_plane._get_conn().execute(
        "SELECT count(*) FROM channel_routes"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("account_changes", "message"),
    [({"enabled": False}, "disabled"), ({"default_profile_id": None}, "profile")],
)
def test_router_fails_closed_for_unusable_accounts(repository, account_changes, message):
    configure_account(repository, **account_changes)

    with pytest.raises(RouteResolutionError, match=message):
        GatewayRouter(repository, now=lambda: NOW).resolve(event())


def test_router_rejects_adapter_account_confusion(repository):
    configure_account(repository, adapter_kind="other")

    with pytest.raises(RouteResolutionError, match="adapter"):
        GatewayRouter(repository, now=lambda: NOW).resolve(event())
