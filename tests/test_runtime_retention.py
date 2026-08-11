from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.models import InboxEvent, OutboxObligation
from open_agent.durable_runtime.repository import DurableRuntimeRepository, StateConflictError
from open_agent.durable_runtime.retention import RetentionPolicy, RetentionWorker


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=31)
RETENTION_KEY = b"task5-test-retention-hmac-key-0001"


@pytest.fixture
def runtime(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(
        control_plane, retention_hmac_key=RETENTION_KEY
    )
    attachment_root = tmp_path / "attachments"
    attachment_root.mkdir()
    try:
        yield control_plane, repository, attachment_root
    finally:
        control_plane.close()


def seed_expired_records(repository, attachment_path="payload.bin"):
    repository.enqueue_inbox(
        InboxEvent(
            "event-old",
            "platform-event-key",
            "account-a",
            "private-conversation-id",
            {
                "text": "private inbox message",
                "sender_id": "private-user-id",
                "attachments": [{"storage_path": attachment_path}],
            },
            created_at=OLD,
            updated_at=OLD,
        )
    )
    repository.enqueue_outbox(
        OutboxObligation(
            "outbox-old",
            "stable-idempotency-key",
            "account-a:private-conversation-id",
            {"text": "private delivery message", "platform_response": "token-value"},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            "UPDATE inbox_events SET state = 'succeeded' WHERE event_id = 'event-old'"
        )
        conn.execute(
            """UPDATE outbox_obligations
               SET state = 'acknowledged', acknowledgement = ?, last_error = ?
               WHERE obligation_id = 'outbox-old'""",
            (json.dumps({"remote_id": "private-remote-id"}), "private diagnostic"),
        )
    repository.append_audit_event(
        audit_id="audit-old",
        entity_kind="outbox",
        entity_id="outbox-old",
        action="delivered",
        actor_id="private-operator-id",
        payload={"platform_response": "private response"},
        now=OLD,
    )


def policy(batch_limit=100):
    return RetentionPolicy(
        inbox_payload_ttl=timedelta(days=30),
        outbox_delivery_ttl=timedelta(days=30),
        audit_ttl=timedelta(days=30),
        batch_limit=batch_limit,
    )


def test_expired_sensitive_data_is_redacted_while_idempotency_tombstones_remain(runtime):
    control_plane, repository, attachment_root = runtime
    attachment = attachment_root / "payload.bin"
    attachment.write_bytes(b"private attachment")
    seed_expired_records(repository)

    summary = RetentionWorker(repository, policy(), attachment_root).run_once(NOW)

    assert repository.get_inbox("event-old") is None
    assert repository.get_outbox("outbox-old") is None
    inbox = repository.list_inbox()[0]
    outbox = repository.list_outbox()[0]
    assert inbox.payload == {}
    assert inbox.conversation_id == "retained"
    assert inbox.event_id.startswith("retained:")
    assert inbox.event_key.startswith("retained:")
    assert inbox.account_id.startswith("retained:")
    assert "event-old" not in inbox.event_id
    assert inbox.state == "succeeded"
    assert outbox.payload == {}
    assert outbox.obligation_id.startswith("retained:")
    assert outbox.idempotency_key.startswith("retained:")
    assert outbox.destination.startswith("retained:")
    assert "outbox-old" not in outbox.obligation_id
    assert outbox.state == "acknowledged"
    assert outbox.acknowledgement is None
    assert outbox.last_error is None
    assert not attachment.exists()
    assert summary.inbox_redacted == 1
    assert summary.outbox_redacted == 1
    assert summary.attachments_deleted == 1
    assert summary.audit_deleted == 1

    conn = control_plane._get_conn()
    retained_audits = conn.execute(
        "SELECT action, payload FROM runtime_audit_events ORDER BY created_at, audit_id"
    ).fetchall()
    audit_actions = [row["action"] for row in retained_audits]
    assert audit_actions == ["attachment_retention", "retention_batch"]

    database_bytes = (control_plane.db_path).read_bytes()
    for sensitive in (
        b"private inbox message",
        b"private-user-id",
        b"private delivery message",
        b"token-value",
        b"private-remote-id",
        b"private diagnostic",
        b"private-operator-id",
        b"private response",
        b"private-conversation-id",
        b"platform-event-key",
        b"stable-idempotency-key",
        b"event-old",
        b"outbox-old",
        b"account-a",
        RETENTION_KEY,
    ):
        assert sensitive not in database_bytes
        wal_path = control_plane.db_path.parent / "runtime.db-wal"
        assert not wal_path.exists() or sensitive not in wal_path.read_bytes()

    duplicate_inbox = repository.enqueue_inbox(
        InboxEvent(
            "event-duplicate",
            "platform-event-key",
            "account-a",
            "another-private-conversation",
            {"text": "must not revive"},
        )
    )
    duplicate_outbox = repository.enqueue_outbox(
        OutboxObligation(
            "outbox-duplicate",
            "stable-idempotency-key",
            "account-a:private-conversation-id",
            {"text": "must not resend"},
        )
    )
    assert duplicate_inbox.event_id == inbox.event_id
    assert duplicate_outbox.obligation_id == outbox.obligation_id


def test_email_and_phone_identifiers_are_absent_from_database_and_wal(runtime):
    control_plane, repository, attachment_root = runtime
    email = "alice.retention@example.com"
    phone = "+15551234567"
    repository.enqueue_inbox(
        InboxEvent(
            f"event:{email}",
            f"provider:{phone}",
            email,
            phone,
            {"sender": email, "text": phone},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    repository.enqueue_outbox(
        OutboxObligation(
            f"delivery:{phone}",
            f"reply:{email}",
            f"{email}:{phone}",
            {"recipient": phone},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    conn = control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")
        conn.execute("UPDATE outbox_obligations SET state = 'acknowledged'")

    RetentionWorker(repository, policy(), attachment_root).run_once(NOW)

    for path in (control_plane.db_path, control_plane.db_path.with_name("runtime.db-wal")):
        if path.exists():
            contents = path.read_bytes()
            assert email.encode() not in contents
            assert phone.encode() not in contents


def test_tombstones_and_attachment_queue_survive_external_hmac_key_rotation(
    runtime, monkeypatch
):
    control_plane, repository, attachment_root = runtime
    attachment = attachment_root / "payload.bin"
    attachment.write_bytes(b"private attachment")
    seed_expired_records(repository)
    first_worker = RetentionWorker(repository, policy(), attachment_root)
    monkeypatch.setattr(
        first_worker, "_delete_managed_attachment", lambda storage_path: "failed"
    )
    assert first_worker.run_once(NOW).attachments_failed == 1

    rotated = DurableRuntimeRepository(
        control_plane,
        retention_hmac_key=b"task5-test-retention-hmac-key-0002",
        previous_retention_hmac_keys=(RETENTION_KEY,),
    )
    duplicate = rotated.enqueue_outbox(
        OutboxObligation(
            "outbox-after-key-rotation",
            "stable-idempotency-key",
            "account-a:private-conversation-id",
            {},
        )
    )
    retried = RetentionWorker(rotated, policy(), attachment_root).run_once(
        NOW + timedelta(seconds=3)
    )

    assert duplicate.obligation_id == rotated.list_outbox()[0].obligation_id
    assert retried.attachments_deleted == 1
    assert not attachment.exists()

    with pytest.raises(StateConflictError, match="historical HMAC"):
        DurableRuntimeRepository(
            control_plane,
            retention_hmac_key=b"task5-test-retention-hmac-key-0003",
        )


def test_stale_repository_revalidates_hmac_registry_inside_dedupe_transaction(
    tmp_path,
):
    control_plane = ControlPlane(tmp_path)
    stale = DurableRuntimeRepository(control_plane, retention_hmac_key=RETENTION_KEY)
    current_key = b"task5-test-retention-hmac-key-0002"
    current = DurableRuntimeRepository(
        control_plane,
        retention_hmac_key=current_key,
        previous_retention_hmac_keys=(RETENTION_KEY,),
    )
    attachment_root = tmp_path / "attachments"
    attachment_root.mkdir()
    try:
        current.enqueue_inbox(
            InboxEvent(
                "event-rolling",
                "rolling-event-key",
                "account@example.com",
                "+15551234567",
                {"text": "rolling private payload"},
                created_at=OLD,
                updated_at=OLD,
            )
        )
        with control_plane._get_conn() as conn:
            conn.execute(
                "UPDATE inbox_events SET state = 'succeeded' WHERE event_id = ?",
                ("event-rolling",),
            )
        RetentionWorker(current, policy(), attachment_root).run_once(NOW)

        with pytest.raises(StateConflictError, match="historical HMAC"):
            stale.enqueue_inbox(
                InboxEvent(
                    "event-rolling-duplicate",
                    "rolling-event-key",
                    "account@example.com",
                    "other",
                    {},
                )
            )
        assert len(current.list_inbox()) == 1
    finally:
        control_plane.close()


def test_poison_attachment_payload_is_redacted_without_blocking_the_batch(runtime):
    _, repository, attachment_root = runtime
    repository.enqueue_inbox(
        InboxEvent(
            "event-poison",
            "poison-key",
            "account-a",
            "private",
            {
                "attachments": [
                    {"storage_path": f"forged-{index}.bin"} for index in range(65)
                ]
            },
            created_at=OLD,
            updated_at=OLD,
        )
    )
    repository.enqueue_inbox(
        InboxEvent(
            "event-after-poison",
            "after-poison-key",
            "account-a",
            "private",
            {"text": "ordinary private payload"},
            created_at=OLD + timedelta(seconds=1),
            updated_at=OLD + timedelta(seconds=1),
        )
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")

    summary = RetentionWorker(repository, policy(batch_limit=1), attachment_root).run_once(
        NOW
    )

    assert summary.inbox_redacted == 1
    assert repository.get_inbox("event-poison") is None
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_backlog").fetchone()[0] == 1
    followup = RetentionWorker(repository, policy(batch_limit=1), attachment_root).run_once(
        NOW + timedelta(seconds=1)
    )
    assert followup.inbox_redacted == 1
    assert repository.get_inbox("event-after-poison") is None


def test_attachment_enqueue_and_due_work_are_hard_capped_at_64(runtime, monkeypatch):
    _, repository, attachment_root = runtime
    for index in range(80):
        repository.enqueue_inbox(
            InboxEvent(
                f"event-cap-{index}",
                f"key-cap-{index}",
                "account-a",
                "private",
                {"attachments": [{"storage_path": f"missing-{index}.bin"}]},
                created_at=OLD,
                updated_at=OLD,
            )
        )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")
    worker = RetentionWorker(repository, policy(batch_limit=80), attachment_root)
    attempted = []
    monkeypatch.setattr(
        worker,
        "_delete_managed_attachment",
        lambda path: attempted.append(path) or "failed",
    )

    worker.run_once(NOW)

    assert len(attempted) == 64
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 64
    deferred_paths = json.loads(
        conn.execute(
            "SELECT storage_paths FROM retention_attachment_backlog"
        ).fetchone()[0]
    )
    assert len(deferred_paths) == 16
    audit_payloads = [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT payload FROM runtime_audit_events WHERE action = 'retention_batch'"
        )
    ]
    assert any(payload.get("attachments_deferred") == 16 for payload in audit_payloads)


def test_full_retry_queue_defers_backlog_until_ack_releases_slots(runtime, monkeypatch):
    _, repository, attachment_root = runtime
    for index in range(80):
        repository.enqueue_inbox(
            InboxEvent(
                f"event-occupancy-{index}",
                f"key-occupancy-{index}",
                "account-a",
                "private",
                {"attachments": [{"storage_path": f"occupancy-{index}.bin"}]},
                created_at=OLD,
                updated_at=OLD,
            )
        )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")
    attempted = []
    worker = RetentionWorker(repository, policy(batch_limit=80), attachment_root)
    monkeypatch.setattr(
        worker,
        "_delete_managed_attachment",
        lambda path: attempted.append(path) or "failed",
    )

    worker.run_once(NOW)
    worker.run_once(NOW + timedelta(seconds=1))

    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 64
    assert sum(
        len(json.loads(row[0]))
        for row in conn.execute(
            "SELECT storage_paths FROM retention_attachment_backlog"
        )
    ) == 16
    assert len(attempted) == 64

    queued_paths = [
        row[0]
        for row in conn.execute(
            "SELECT storage_path FROM retention_attachment_queue"
        )
    ]
    repository.complete_retention_attachments(
        {path: "deleted" for path in queued_paths},
        now=NOW + timedelta(seconds=2),
    )
    worker.run_once(NOW + timedelta(seconds=3))

    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 16
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_backlog").fetchone()[0] == 0
    assert len(attempted) == 80
    assert len(set(attempted)) == 80


def test_failed_attachment_backoff_does_not_starve_newer_due_work(runtime, monkeypatch):
    _, repository, attachment_root = runtime
    for index, path in enumerate(("blocked.bin", "new.bin")):
        (attachment_root / path).write_bytes(path.encode())
        repository.enqueue_inbox(
            InboxEvent(
                f"event-fair-{index}",
                f"fair-key-{index}",
                "account-a",
                "private",
                {"attachments": [{"storage_path": path}]},
                created_at=OLD + timedelta(seconds=index),
                updated_at=OLD + timedelta(seconds=index),
            )
        )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")
    worker = RetentionWorker(repository, policy(batch_limit=1), attachment_root)
    original_delete = worker._delete_managed_attachment
    monkeypatch.setattr(
        worker,
        "_delete_managed_attachment",
        lambda path: "failed" if path == "blocked.bin" else original_delete(path),
    )

    first = worker.run_once(NOW)
    second = worker.run_once(NOW + timedelta(seconds=1))

    assert first.attachments_failed == 1
    assert second.attachments_deleted == 1
    assert (attachment_root / "blocked.bin").exists()
    assert not (attachment_root / "new.bin").exists()


def test_failed_attachment_delete_is_persisted_and_retried(runtime, monkeypatch):
    _, repository, attachment_root = runtime
    attachment = attachment_root / "payload.bin"
    attachment.write_bytes(b"private attachment")
    seed_expired_records(repository)
    worker = RetentionWorker(repository, policy(), attachment_root)
    original_delete = worker._delete_managed_attachment
    calls = 0

    def fail_once(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "failed"
        return original_delete(path)

    monkeypatch.setattr(worker, "_delete_managed_attachment", fail_once)

    first = worker.run_once(NOW)
    second = worker.run_once(NOW + timedelta(seconds=3))

    assert first.attachments_failed == 1
    assert attachment.exists() is False
    assert second.attachments_deleted == 1


def test_retention_is_bounded_and_already_redacted_rows_are_idempotent(runtime):
    _, repository, attachment_root = runtime
    for index in range(3):
        repository.enqueue_inbox(
            InboxEvent(
                f"event-{index}",
                f"key-{index}",
                "account-a",
                f"private-{index}",
                {"text": f"secret-{index}"},
                created_at=OLD,
                updated_at=OLD,
            )
        )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")

    worker = RetentionWorker(repository, policy(batch_limit=2), attachment_root)
    first = worker.run_once(NOW)
    second = worker.run_once(NOW)
    third = worker.run_once(NOW)

    assert first.records_processed == 2
    assert second.records_processed == 1
    assert third.records_processed == 0
    assert len(repository.list_audit_events("retention", "runtime")) == 2


def test_active_records_are_not_redacted(runtime):
    _, repository, attachment_root = runtime
    repository.enqueue_inbox(
        InboxEvent(
            "event-active",
            "active-key",
            "account-a",
            "private-conversation",
            {"text": "still required"},
            created_at=OLD,
            updated_at=OLD,
        )
    )

    summary = RetentionWorker(repository, policy(), attachment_root).run_once(NOW)

    assert repository.get_inbox("event-active").payload["text"] == "still required"
    assert summary.records_processed == 0


def test_terminal_record_expires_at_the_configured_cutoff(runtime):
    _, repository, attachment_root = runtime
    cutoff = NOW - timedelta(days=30)
    repository.enqueue_inbox(
        InboxEvent(
            "event-cutoff",
            "cutoff-key",
            "account-a",
            "private-conversation",
            {"text": "expires now"},
            created_at=cutoff,
            updated_at=cutoff,
        )
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            "UPDATE inbox_events SET state = 'succeeded' WHERE event_id = 'event-cutoff'"
        )

    summary = RetentionWorker(repository, policy(), attachment_root).run_once(NOW)

    assert summary.inbox_redacted == 1
    assert repository.get_inbox("event-cutoff") is None
    assert repository.list_inbox()[0].payload == {}


def test_attachment_cleanup_rejects_traversal_and_symlink_escape(
    runtime, tmp_path, monkeypatch
):
    _, repository, attachment_root = runtime
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"must survive")
    link = attachment_root / "escape"
    created_symlink = True
    try:
        os.symlink(tmp_path, link, target_is_directory=True)
    except OSError:
        created_symlink = False

    seed_expired_records(repository, "escape/outside.txt")
    worker = RetentionWorker(repository, policy(), attachment_root)
    if not created_symlink:
        monkeypatch.setattr(worker, "_delete_windows_handle", lambda candidate: "rejected")
    summary = worker.run_once(NOW)

    assert outside.read_bytes() == b"must survive"
    assert summary.attachments_deleted == 0
    assert summary.attachments_rejected == 1


@pytest.mark.parametrize("unsafe_path", ["../outside.txt", "C:\\outside.txt", "/outside.txt"])
def test_attachment_cleanup_rejects_non_relative_managed_paths(runtime, unsafe_path):
    _, repository, attachment_root = runtime
    seed_expired_records(repository, unsafe_path)

    summary = RetentionWorker(repository, policy(), attachment_root).run_once(NOW)

    assert summary.attachments_deleted == 0
    assert summary.attachments_rejected == 1


@pytest.mark.parametrize(
    "change",
    [
        {"inbox_payload_ttl": timedelta(0)},
        {"outbox_delivery_ttl": timedelta(seconds=-1)},
        {"audit_ttl": "30 days"},
        {"batch_limit": 0},
        {"batch_limit": 1001},
        {"batch_limit": True},
    ],
)
def test_retention_policy_rejects_invalid_or_unbounded_configuration(change):
    values = {
        "inbox_payload_ttl": timedelta(days=30),
        "outbox_delivery_ttl": timedelta(days=30),
        "audit_ttl": timedelta(days=30),
        "batch_limit": 100,
    }
    values.update(change)
    with pytest.raises((TypeError, ValueError)):
        RetentionPolicy(**values)


def test_run_once_requires_timezone_aware_now(runtime):
    _, repository, attachment_root = runtime
    worker = RetentionWorker(repository, policy(), attachment_root)
    with pytest.raises(ValueError, match="timezone"):
        worker.run_once(NOW.replace(tzinfo=None))


def test_attachment_root_and_windows_path_normalization_are_defensive(runtime, tmp_path):
    _, repository, attachment_root = runtime
    with pytest.raises(ValueError, match="attachment_root"):
        RetentionWorker(repository, policy(), tmp_path / "missing")

    worker = RetentionWorker(repository, policy(), attachment_root)
    assert worker._delete_managed_attachment("") == "rejected"
    assert worker._normalize_windows_handle_path(r"\\?\UNC\server\share\file") == (
        r"\\server\share\file"
    )
    assert worker._normalize_windows_handle_path(r"C:\managed\file") == r"C:\managed\file"


def test_missing_managed_attachment_is_acknowledged_without_retry(runtime):
    _, repository, attachment_root = runtime
    seed_expired_records(repository, "already-missing.bin")

    first = RetentionWorker(repository, policy(), attachment_root).run_once(NOW)
    second = RetentionWorker(repository, policy(), attachment_root).run_once(
        NOW + timedelta(seconds=3)
    )

    assert first.attachments_deleted == 0
    assert first.attachments_failed == 0
    assert second.records_processed == 0
