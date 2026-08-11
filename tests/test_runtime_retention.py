from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import os
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.models import InboxEvent, OutboxObligation
from open_agent.durable_runtime.repository import (
    DurableRuntimeRepository,
    StaleClaimError,
    StateConflictError,
)
from open_agent.durable_runtime.retention import RetentionPolicy, RetentionWorker


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=31)
RETENTION_KEY = b"task5-test-retention-hmac-key-0001"


def retention_key_id(key):
    return hashlib.sha256(key).hexdigest()[:16]


def attachment_digest(key, kind, storage_path, key_id, work_id, generation):
    authenticated = json.dumps(
        [
            "retention-attachment-v1",
            kind,
            key_id,
            work_id,
            generation,
            storage_path,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hmac.new(key, authenticated.encode("utf-8"), hashlib.sha256).hexdigest()


def file_identity_digest(
    key, kind, storage_path, key_id, work_id, generation, file_identity
):
    authenticated = json.dumps(
        [
            "retention-attachment-file-v1",
            kind,
            key_id,
            work_id,
            generation,
            storage_path,
            file_identity,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hmac.new(key, authenticated.encode("utf-8"), hashlib.sha256).hexdigest()


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


def policy(batch_limit=100, attachment_max_attempts=5):
    return RetentionPolicy(
        inbox_payload_ttl=timedelta(days=30),
        outbox_delivery_ttl=timedelta(days=30),
        audit_ttl=timedelta(days=30),
        batch_limit=batch_limit,
        attachment_max_attempts=attachment_max_attempts,
    )


def apply_batch(repository, **kwargs):
    return repository.apply_retention_batch(**kwargs)


def attachment_claims(batch):
    claims = batch["attachment_claims"]
    assert batch["attachment_paths"] == tuple(claim.storage_path for claim in claims)
    return {claim.storage_path: claim for claim in claims}


def claim_due_attachment(repository, storage_path, *, now=NOW):
    claims = repository.claim_retention_attachments(now=now, limit=64)
    return next(claim for claim in claims if claim.storage_path == storage_path)


def insert_authenticated_queue_row(repository, storage_path, *, generation):
    key_id = retention_key_id(RETENTION_KEY)
    work_id = f"work-{generation}"
    queue_id = attachment_digest(
        RETENTION_KEY, "queue", storage_path, key_id, work_id, generation
    )
    file_identity = "missing"
    identity_tag = file_identity_digest(
        RETENTION_KEY,
        "queue",
        storage_path,
        key_id,
        work_id,
        generation,
        file_identity,
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            """INSERT INTO retention_attachment_queue (
                   queue_id, storage_path, key_id, work_id, generation,
                   queued_at, next_attempt_at, file_identity, file_identity_tag
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                queue_id,
                storage_path,
                key_id,
                work_id,
                generation,
                NOW.isoformat(),
                NOW.isoformat(),
                file_identity,
                identity_tag,
            ),
        )
    return queue_id


def quarantine_attachment(repository, storage_path, *, suffix):
    event_id = f"event-quarantine-{suffix}"
    repository.enqueue_inbox(
        InboxEvent(
            event_id,
            f"key-quarantine-{suffix}",
            "account-a",
            "private",
            {"attachments": [{"storage_path": storage_path}]},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            "UPDATE inbox_events SET state = 'succeeded' WHERE event_id = ?",
            (event_id,),
        )
    batch = apply_batch(repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    claims = attachment_claims(batch)
    assert batch["attachment_paths"] == (storage_path,)
    repository.complete_retention_attachments(
        {claims[storage_path]: "failed"}, now=NOW, max_attempts=1
    )
    return next(
        item
        for item in repository.list_retention_attachment_dead_letters()
        if item["storage_path"] == storage_path
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
    assert set(audit_actions) == {"attachment_retention", "retention_batch"}

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
        first_worker, "_delete_managed_attachment", lambda claim, now: "failed"
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


def test_k1_backlog_manifest_promotes_under_k2_only_with_k1_history(runtime):
    control_plane, k1_repository, _ = runtime
    storage_path = "quarantine/k1-backlog-object-0001"
    page = k1_repository._new_retention_attachment_backlog_page(
        ((storage_path, "missing"),)
    )
    conn = control_plane._get_conn()
    with conn:
        conn.execute(
            """INSERT INTO retention_key_registry (key_id, first_used_at)
               VALUES (?, ?)""",
            (retention_key_id(RETENTION_KEY), NOW.isoformat()),
        )
        conn.execute(
            """INSERT INTO retention_attachment_backlog (
                   backlog_id, storage_paths, key_id, generation, backlog_tag, queued_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (*page, NOW.isoformat()),
        )
    k2 = b"task5-test-retention-hmac-key-0002"
    rotated = DurableRuntimeRepository(
        control_plane,
        retention_hmac_key=k2,
        previous_retention_hmac_keys=(RETENTION_KEY,),
    )

    batch = apply_batch(
        rotated,
        now=NOW,
        inbox_before=OLD,
        outbox_before=OLD,
        audit_before=OLD,
        limit=1,
    )

    claim = attachment_claims(batch)[storage_path]
    assert claim.file_identity == "missing"
    assert claim.key_id == retention_key_id(k2)
    assert conn.execute(
        "SELECT COUNT(*) FROM retention_attachment_backlog"
    ).fetchone()[0] == 0
    with pytest.raises(StateConflictError, match="historical HMAC"):
        DurableRuntimeRepository(control_plane, retention_hmac_key=k2)


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


def test_rotated_requeue_registers_key_and_old_worker_completion_fails_closed(runtime):
    control_plane, old_worker_repository, _ = runtime
    for index, storage_path in enumerate(("claimed-with-k1.bin", "requeued-with-k2.bin")):
        old_worker_repository.enqueue_inbox(
            InboxEvent(
                f"event-rotation-{index}",
                f"key-rotation-{index}",
                "account-a",
                "private",
                {"attachments": [{"storage_path": storage_path}]},
                created_at=OLD,
                updated_at=OLD,
            )
        )
    conn = control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")

    batch = apply_batch(old_worker_repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=2,
    )
    claims = attachment_claims(batch)
    assert set(batch["attachment_paths"]) == {
        "claimed-with-k1.bin",
        "requeued-with-k2.bin",
    }
    old_worker_repository.complete_retention_attachments(
        {claims["requeued-with-k2.bin"]: "failed"},
        now=NOW,
        max_attempts=1,
    )
    dead_letter = old_worker_repository.list_retention_attachment_dead_letters()[0]

    current_key = b"task5-test-retention-hmac-key-0002"
    current_repository = DurableRuntimeRepository(
        control_plane,
        retention_hmac_key=current_key,
        previous_retention_hmac_keys=(RETENTION_KEY,),
    )
    assert current_repository.requeue_retention_attachment(
        dead_letter["dead_letter_id"], actor_id="operator-a", now=NOW
    )

    registered_ids = {
        row[0] for row in conn.execute("SELECT key_id FROM retention_key_registry")
    }
    assert registered_ids == {
        hashlib.sha256(RETENTION_KEY).hexdigest()[:16],
        hashlib.sha256(current_key).hexdigest()[:16],
    }
    with pytest.raises(StateConflictError, match="historical HMAC"):
        old_worker_repository.complete_retention_attachments(
            {claims["claimed-with-k1.bin"]: "deleted"}, now=NOW
        )

    requeued_claim = claim_due_attachment(
        current_repository, "requeued-with-k2.bin", now=NOW
    )
    current_repository.complete_retention_attachments(
        {
            claims["claimed-with-k1.bin"]: "missing",
            requeued_claim: "missing",
        },
        now=NOW,
    )
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM retention_attachment_dead_letters").fetchone()[0]
        == 0
    )


def test_attachment_completion_fails_closed_for_an_unavailable_id_key(runtime):
    control_plane, repository, _ = runtime
    storage_path = "legacy-k2-active.bin"
    unavailable_key = b"task5-test-retention-hmac-key-0002"
    unavailable_key_id = retention_key_id(unavailable_key)
    work_id = "work-unavailable-k2"
    generation = "generation-unavailable-k2"
    queue_id = attachment_digest(
        unavailable_key,
        "queue",
        storage_path,
        unavailable_key_id,
        work_id,
        generation,
    )
    file_identity = "missing"
    identity_tag = file_identity_digest(
        unavailable_key,
        "queue",
        storage_path,
        unavailable_key_id,
        work_id,
        generation,
        file_identity,
    )
    conn = control_plane._get_conn()
    with conn:
        conn.execute(
            "INSERT INTO retention_key_registry (key_id, first_used_at) VALUES (?, ?)",
            (hashlib.sha256(RETENTION_KEY).hexdigest()[:16], NOW.isoformat()),
        )
        conn.execute(
            """INSERT INTO retention_attachment_queue (
                   queue_id, storage_path, key_id, work_id, generation,
                   queued_at, next_attempt_at, file_identity, file_identity_tag
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                queue_id,
                storage_path,
                unavailable_key_id,
                work_id,
                generation,
                NOW.isoformat(),
                NOW.isoformat(),
                file_identity,
                identity_tag,
            ),
        )

    with pytest.raises(StateConflictError, match="historical HMAC"):
        repository.claim_retention_attachments(now=NOW, limit=1)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM retention_attachment_queue WHERE storage_path = ?",
            (storage_path,),
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("queue_id", "0" * 64),
        ("storage_path", "forged-exposed.bin"),
        ("key_id", "0" * 16),
        ("work_id", "forged-work-id"),
        ("generation", "forged-generation"),
        ("file_identity", "forged-file-identity"),
        ("file_identity_tag", "0" * 64),
    ],
)
def test_due_queue_row_is_authenticated_before_path_is_exposed(
    runtime, column, replacement
):
    _, repository, _ = runtime
    seed_expired_records(repository, "authenticated-due.bin")
    batch = apply_batch(repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    claim = attachment_claims(batch)["authenticated-due.bin"]
    repository.complete_retention_attachments(
        {claim: "failed"}, now=NOW, max_attempts=5
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            f"UPDATE retention_attachment_queue SET {column} = ?",
            (replacement,),
        )

    with pytest.raises(StateConflictError, match="authenticate|historical HMAC"):
        repository.claim_retention_attachments(
            now=NOW + timedelta(seconds=3), limit=1
        )


def test_claim_cas_rechecks_authenticated_file_identity(runtime, monkeypatch):
    _, repository, _ = runtime
    storage_path = "claim-cas-file-identity.bin"
    seed_expired_records(repository, storage_path)
    batch = apply_batch(
        repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    claim = attachment_claims(batch)[storage_path]
    repository.complete_retention_attachments(
        {claim: "failed"}, now=NOW, max_attempts=5
    )
    conn = repository.control_plane._get_conn()
    original_authenticate = repository._authenticate_retention_attachment_row
    tampered = False

    def authenticate_then_tamper(row, kind):
        nonlocal tampered
        original_authenticate(row, kind)
        if kind == "queue" and not tampered:
            tampered = True
            conn.execute(
                """UPDATE retention_attachment_queue SET file_identity = ?
                   WHERE queue_id = ?""",
                ("tampered-between-auth-and-claim-cas", row["queue_id"]),
            )

    monkeypatch.setattr(
        repository,
        "_authenticate_retention_attachment_row",
        authenticate_then_tamper,
    )

    with pytest.raises(StateConflictError, match="compare-and-swap"):
        repository.claim_retention_attachments(
            now=NOW + timedelta(seconds=3), limit=1
        )

    row = conn.execute(
        "SELECT state, file_identity FROM retention_attachment_queue"
    ).fetchone()
    assert row["state"] == "pending"
    assert row["file_identity"] == "missing"


def test_stale_claim_cannot_delete_or_ack_a_requeued_same_path_occurrence(runtime):
    _, repository, attachment_root = runtime
    storage_path = "same-path-new-occurrence.bin"
    attachment = attachment_root / storage_path
    attachment.write_bytes(b"new occurrence must survive")
    seed_expired_records(repository, storage_path)
    batch = apply_batch(repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    old_claim = attachment_claims(batch)[storage_path]
    assert old_claim.work_id
    assert old_claim.generation
    assert old_claim.claim_owner
    assert old_claim.claim_token
    assert old_claim.claim_expires_at > NOW
    repository.complete_retention_attachments(
        {old_claim: "failed"}, now=NOW, max_attempts=1
    )
    dead_letter = repository.list_retention_attachment_dead_letters()[0]
    assert repository.requeue_retention_attachment(
        dead_letter["dead_letter_id"], actor_id="operator-a", now=NOW
    )
    new_claim = claim_due_attachment(repository, storage_path, now=NOW)
    assert new_claim.work_id != old_claim.work_id
    assert new_claim.generation != old_claim.generation

    worker = RetentionWorker(repository, policy(), attachment_root)
    assert worker._delete_managed_attachment(old_claim, NOW) == "stale"
    stale_counts = repository.complete_retention_attachments(
        {old_claim: "deleted"}, now=NOW
    )

    assert stale_counts["deleted"] == 0
    assert stale_counts["stale"] == 1
    assert attachment.read_bytes() == b"new occurrence must survive"
    row = repository.control_plane._get_conn().execute(
        "SELECT work_id, generation FROM retention_attachment_queue WHERE storage_path = ?",
        (storage_path,),
    ).fetchone()
    assert (row["work_id"], row["generation"]) == (
        new_claim.work_id,
        new_claim.generation,
    )
    audit_payload = json.loads(
        repository.control_plane._get_conn().execute(
            """SELECT payload FROM runtime_audit_events
               WHERE action = 'attachment_retention'
               ORDER BY rowid DESC LIMIT 1"""
        ).fetchone()[0]
    )
    assert audit_payload["attachments_deleted"] == 0
    assert audit_payload["attachments_stale"] == 1


def test_expired_claim_is_reclaimed_with_a_new_fencing_token(runtime):
    _, repository, attachment_root = runtime
    storage_path = "expired-claim.bin"
    attachment = attachment_root / storage_path
    attachment.write_bytes(b"must survive stale lease holder")
    seed_expired_records(repository, storage_path)
    batch = apply_batch(repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    stale_claim = attachment_claims(batch)[storage_path]

    assert repository.claim_retention_attachments(
        now=NOW + timedelta(minutes=4), limit=1
    ) == ()
    with pytest.raises(StaleClaimError, match="expired|stale"):
        repository.authorize_retention_attachment_deletion(
            stale_claim,
            "expired-claim-must-not-bind-an-identity",
            now=NOW + timedelta(minutes=6),
        )
    expired_counts = repository.complete_retention_attachments(
        {stale_claim: "missing"}, now=NOW + timedelta(minutes=6)
    )
    assert expired_counts["missing"] == 0
    assert expired_counts["stale"] == 1
    assert attachment.exists()

    replacement_claim = claim_due_attachment(
        repository, storage_path, now=NOW + timedelta(minutes=6)
    )

    assert replacement_claim.work_id == stale_claim.work_id
    assert replacement_claim.generation == stale_claim.generation
    assert replacement_claim.claim_generation == stale_claim.claim_generation + 1
    assert replacement_claim.claim_token != stale_claim.claim_token
    assert replacement_claim.claim_owner != stale_claim.claim_owner
    worker = RetentionWorker(repository, policy(), attachment_root)
    assert (
        worker._delete_managed_attachment(
            stale_claim, NOW + timedelta(minutes=6)
        )
        == "stale"
    )
    assert attachment.exists()


def test_file_identity_mismatch_fails_closed_before_handle_deletion(runtime):
    _, repository, attachment_root = runtime
    storage_path = "identity-version.bin"
    attachment = attachment_root / storage_path
    attachment.write_bytes(b"must survive identity mismatch")
    seed_expired_records(repository, storage_path)
    batch = apply_batch(repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    claim = attachment_claims(batch)[storage_path]
    with pytest.raises(StateConflictError, match="identity"):
        repository.authorize_retention_attachment_deletion(
            claim, "forged-immutable-file-identity", now=NOW
        )
    authorized_claim = repository.authorize_retention_attachment_deletion(
        claim, claim.file_identity, now=NOW
    )
    forged_identity_claim = replace(
        authorized_claim, file_identity="forged-immutable-file-identity"
    )

    worker = RetentionWorker(repository, policy(), attachment_root)
    assert worker._delete_managed_attachment(forged_identity_claim, NOW) == "failed"
    fenced = repository.complete_retention_attachments(
        {authorized_claim: "failed"}, now=NOW
    )
    assert fenced["failed"] == 0
    assert fenced["fenced"] == 1
    assert attachment.read_bytes() == b"must survive identity mismatch"
    assert repository.claim_retention_attachments(
        now=NOW + timedelta(minutes=6), limit=1
    ) == ()

    repository.enqueue_inbox(
        InboxEvent(
            "event-after-delete-fence",
            "key-after-delete-fence",
            "account-a",
            "private",
            {"attachments": [{"storage_path": storage_path}]},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            """UPDATE inbox_events SET state = 'succeeded'
               WHERE event_id = 'event-after-delete-fence'"""
        )
    later = apply_batch(repository,
        now=NOW + timedelta(minutes=7),
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    assert later["attachment_claims"] == ()
    assert conn.execute(
        "SELECT work_id FROM retention_attachment_queue WHERE storage_path = ?",
        (storage_path,),
    ).fetchone()[0] == claim.work_id


def test_backlog_tampering_cannot_launder_a_path_into_an_authenticated_claim(
    runtime, monkeypatch
):
    _, repository, attachment_root = runtime
    original_paths = (
        "quarantine/backlog-source-object-0001",
        "quarantine/backlog-source-object-0002",
    )
    repository.enqueue_inbox(
        InboxEvent(
            "event-backlog-source",
            "key-backlog-source",
            "account-a",
            "private",
            {
                "attachments": [
                    {"storage_path": storage_path}
                    for storage_path in original_paths
                ]
            },
            created_at=OLD,
            updated_at=OLD,
        )
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")
    first_worker = RetentionWorker(
        repository,
        policy(batch_limit=1, attachment_max_attempts=1),
        attachment_root,
    )
    monkeypatch.setattr(
        first_worker, "_delete_managed_attachment", lambda claim, now: "failed"
    )
    first_worker.run_once(NOW)
    assert conn.execute(
        "SELECT COUNT(*) FROM retention_attachment_backlog"
    ).fetchone()[0] == 1

    victim_path = "quarantine/backlog-victim-object-0003"
    victim = attachment_root / victim_path
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_bytes(b"must not be MAC-laundered")
    with conn:
        conn.execute(
            "UPDATE retention_attachment_backlog SET storage_paths = ?",
            (json.dumps([victim_path]),),
        )
    attempted: list[str] = []
    second_worker = RetentionWorker(
        repository, policy(batch_limit=1), attachment_root
    )
    monkeypatch.setattr(
        second_worker,
        "_delete_managed_attachment",
        lambda claim, now: attempted.append(claim.storage_path) or "failed",
    )

    with pytest.raises(StateConflictError, match="backlog|authenticate"):
        second_worker.run_once(NOW + timedelta(seconds=1))

    assert attempted == []
    assert victim.read_bytes() == b"must not be MAC-laundered"


def test_nested_raw_storage_path_is_not_a_trusted_attachment_container(
    runtime, monkeypatch
):
    _, repository, attachment_root = runtime
    victim_path = "quarantine/nested-victim-object-0001"
    victim = attachment_root / victim_path
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_bytes(b"nested metadata is not an attachment capability")
    repository.enqueue_inbox(
        InboxEvent(
            "event-nested-untrusted-path",
            "key-nested-untrusted-path",
            "account-a",
            "private",
            {"metadata": {"storage_path": victim_path}},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            "UPDATE inbox_events SET state = 'succeeded' WHERE event_id = ?",
            ("event-nested-untrusted-path",),
        )
    attempted: list[str] = []
    worker = RetentionWorker(repository, policy(), attachment_root)
    monkeypatch.setattr(
        worker,
        "_delete_managed_attachment",
        lambda claim, now: attempted.append(claim.storage_path) or "failed",
    )

    worker.run_once(NOW)

    assert attempted == []
    assert victim.read_bytes() == b"nested metadata is not an attachment capability"


def test_worker_refreshes_operation_time_before_authorization(runtime):
    _, repository, attachment_root = runtime
    storage_path = "quarantine/expired-during-batch-object-0001"
    attachment = attachment_root / storage_path
    attachment.parent.mkdir(parents=True, exist_ok=True)
    attachment.write_bytes(b"lease expires while batch is running")
    seed_expired_records(repository, storage_path)
    ticks = iter((0.0, 301.0, 301.0))
    worker = RetentionWorker(
        repository,
        policy(),
        attachment_root,
        monotonic=lambda: next(ticks, 301.0),
    )

    summary = worker.run_once(NOW)

    assert summary.attachments_deleted == 0
    assert summary.attachments_stale == 1
    assert attachment.read_bytes() == b"lease expires while batch is running"


def test_pre_open_replacement_cannot_become_the_bound_file_identity(
    runtime, monkeypatch
):
    _, repository, attachment_root = runtime
    storage_path = "quarantine/pre-open-replacement-object-0001"
    attachment = attachment_root / storage_path
    saved_original = attachment_root / "saved-original-object-0001"
    attachment.parent.mkdir(parents=True, exist_ok=True)
    attachment.write_bytes(b"original occurrence")
    seed_expired_records(repository, storage_path)
    worker = RetentionWorker(repository, policy(), attachment_root)
    original_delete = worker._delete_managed_attachment
    swapped = False

    def replace_before_open(claim, now):
        nonlocal swapped
        if not swapped:
            attachment.replace(saved_original)
            attachment.write_bytes(b"newer same-path occurrence")
            swapped = True
        return original_delete(claim, now)

    monkeypatch.setattr(worker, "_delete_managed_attachment", replace_before_open)

    summary = worker.run_once(NOW)

    assert summary.attachments_deleted == 0
    assert attachment.read_bytes() == b"newer same-path occurrence"
    assert saved_original.read_bytes() == b"original occurrence"
    row = repository.control_plane._get_conn().execute(
        "SELECT file_identity FROM retention_attachment_queue WHERE storage_path = ?",
        (storage_path,),
    ).fetchone()
    assert row is not None and row["file_identity"] is not None


def test_replacement_before_queue_creation_cannot_rebind_the_source_occurrence(runtime):
    _, repository, attachment_root = runtime
    storage_path = "quarantine/pre-queue-replacement-object-0001"
    attachment = attachment_root / storage_path
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"original occurrence")
    seed_expired_records(repository, storage_path)
    saved_original = attachment_root / "saved-original-occurrence"
    os.replace(attachment, saved_original)
    attachment.write_bytes(b"replacement must survive")

    summary = RetentionWorker(repository, policy(), attachment_root).run_once(NOW)

    assert summary.attachments_deleted == 0
    assert summary.attachments_failed == 1
    assert attachment.read_bytes() == b"replacement must survive"
    assert saved_original.read_bytes() == b"original occurrence"


def test_tampered_source_manifest_fails_before_any_filesystem_operation(
    runtime, monkeypatch
):
    _, repository, attachment_root = runtime
    storage_path = "quarantine/authenticated-source-object-0001"
    victim_path = "quarantine/tampered-source-victim-0001"
    seed_expired_records(repository, storage_path)
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            """UPDATE inbox_events SET retention_attachment_paths = ?
               WHERE event_id = 'event-old'""",
            (json.dumps([victim_path], separators=(",", ":")),),
        )
    attempted = []
    worker = RetentionWorker(repository, policy(), attachment_root)
    monkeypatch.setattr(
        worker,
        "_delete_managed_attachment",
        lambda claim, now: attempted.append(claim.storage_path) or "failed",
    )

    with pytest.raises(StateConflictError, match="source manifest"):
        worker.run_once(NOW)

    assert attempted == []
    assert repository.get_inbox("event-old").payload["attachments"][0][
        "storage_path"
    ] == storage_path


def test_legacy_unsigned_source_requires_migration_without_losing_its_path(runtime):
    control_plane, repository, attachment_root = runtime
    storage_path = "quarantine/legacy-unsigned-source-object-0001"
    attachment = attachment_root / storage_path
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"legacy attachment must remain referenced")
    repository.enqueue_inbox(
        InboxEvent(
            "event-legacy-unsigned-source",
            "key-legacy-unsigned-source",
            "account-a",
            "private",
            {},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    unsigned_payload = json.dumps(
        {"attachments": [{"storage_path": storage_path}]}, separators=(",", ":")
    )
    conn = control_plane._get_conn()
    with conn:
        conn.execute(
            """UPDATE inbox_events SET payload = ?, state = 'succeeded'
               WHERE event_id = 'event-legacy-unsigned-source'""",
            (unsigned_payload,),
        )

    with pytest.raises(StateConflictError, match="unsigned.*explicit migration"):
        DurableRuntimeRepository(control_plane, retention_hmac_key=RETENTION_KEY)

    row = conn.execute(
        """SELECT payload, retained_at, retention_attachment_paths
           FROM inbox_events WHERE event_id = 'event-legacy-unsigned-source'"""
    ).fetchone()
    assert row["payload"] == unsigned_payload
    assert row["retained_at"] is None
    assert row["retention_attachment_paths"] is None
    assert attachment.read_bytes() == b"legacy attachment must remain referenced"
    assert conn.execute(
        "SELECT COUNT(*) FROM retention_attachment_queue"
    ).fetchone()[0] == 0


def test_late_unsigned_source_tamper_aborts_batch_before_redaction(runtime):
    _, repository, attachment_root = runtime
    storage_path = "quarantine/late-unsigned-source-object-0001"
    attachment = attachment_root / storage_path
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"late unsigned attachment")
    repository.enqueue_inbox(
        InboxEvent(
            "event-late-unsigned-source",
            "key-late-unsigned-source",
            "account-a",
            "private",
            {},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    unsigned_payload = json.dumps(
        {"attachments": [{"storage_path": storage_path}]}, separators=(",", ":")
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            """UPDATE inbox_events SET payload = ?, state = 'succeeded'
               WHERE event_id = 'event-late-unsigned-source'""",
            (unsigned_payload,),
        )

    with pytest.raises(StateConflictError, match="unsigned.*explicit migration"):
        RetentionWorker(repository, policy(), attachment_root).run_once(NOW)

    row = conn.execute(
        """SELECT payload, retained_at FROM inbox_events
           WHERE event_id = 'event-late-unsigned-source'"""
    ).fetchone()
    assert row["payload"] == unsigned_payload
    assert row["retained_at"] is None
    assert attachment.read_bytes() == b"late unsigned attachment"
    assert conn.execute(
        "SELECT COUNT(*) FROM retention_attachment_queue"
    ).fetchone()[0] == 0


def test_raw_payload_tampering_cannot_replace_the_signed_source_occurrence(runtime):
    _, repository, attachment_root = runtime
    storage_path = "quarantine/signed-source-object-0001"
    victim_path = "quarantine/raw-payload-victim-0001"
    attachment = attachment_root / storage_path
    victim = attachment_root / victim_path
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"signed source occurrence")
    victim.write_bytes(b"tampered payload victim")
    seed_expired_records(repository, storage_path)
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            """UPDATE inbox_events SET payload = ?
               WHERE event_id = 'event-old'""",
            (
                json.dumps(
                    {"attachments": [{"storage_path": victim_path}]},
                    separators=(",", ":"),
                ),
            ),
        )

    summary = RetentionWorker(repository, policy(), attachment_root).run_once(NOW)

    assert summary.attachments_deleted == 1
    assert not attachment.exists()
    assert victim.read_bytes() == b"tampered payload victim"


def test_posix_deletion_uses_a_private_quarantine_before_unlink():
    source = inspect.getsource(RetentionWorker._delete_posix_handle)

    assert "os.rename" in source
    assert "private" in source or "quarantine" in source
    assert source.index("os.rename") < source.index("os.unlink")


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX dir_fd semantics")
def test_posix_quarantine_rename_deletes_the_held_occurrence(runtime):
    _, repository, attachment_root = runtime
    storage_path = "quarantine/posix-normal-delete-object-0001"
    attachment = attachment_root / storage_path
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"ordinary POSIX occurrence")
    seed_expired_records(repository, storage_path)
    batch = apply_batch(
        repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    claim = attachment_claims(batch)[storage_path]
    worker = RetentionWorker(repository, policy(), attachment_root)

    assert worker._delete_managed_attachment(claim, NOW) == "deleted"
    assert not attachment.exists()
    assert list((attachment_root / ".retention-delete").iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX dir_fd semantics")
def test_posix_swap_before_quarantine_rename_never_unlinks_replacement(
    runtime, monkeypatch
):
    import open_agent.durable_runtime.retention as retention_module

    _, repository, attachment_root = runtime
    storage_path = "quarantine/posix-rename-race-object-0001"
    attachment = attachment_root / storage_path
    saved_original = attachment_root / "saved-posix-original-object-0001"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"original POSIX occurrence")
    seed_expired_records(repository, storage_path)
    batch = apply_batch(
        repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    claim = attachment_claims(batch)[storage_path]
    worker = RetentionWorker(repository, policy(), attachment_root)
    original_rename = retention_module.os.rename
    swapped = False

    def swap_then_rename(src, dst, *, src_dir_fd, dst_dir_fd):
        nonlocal swapped
        if not swapped:
            os.replace(attachment, saved_original)
            attachment.write_bytes(b"replacement must remain quarantined")
            swapped = True
        return original_rename(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(retention_module.os, "rename", swap_then_rename)

    assert worker._delete_managed_attachment(claim, NOW) == "fenced"
    assert saved_original.read_bytes() == b"original POSIX occurrence"
    private_files = list((attachment_root / ".retention-delete").iterdir())
    assert len(private_files) == 1
    assert private_files[0].read_bytes() == b"replacement must remain quarantined"


@pytest.mark.parametrize(
    "storage_path",
    [
        "quarantine//canonical-object-0001",
        "quarantine/./canonical-object-0001",
        "Quarantine/canonical-object-0001",
        r"quarantine\canonical-object-0001",
        "quarantine/canonical-object-0001.",
    ],
)
def test_attachment_source_rejects_filesystem_alias_paths(runtime, storage_path):
    _, repository, _ = runtime

    with pytest.raises(ValueError, match="canonical|storage_path"):
        repository.enqueue_inbox(
            InboxEvent(
                f"event-alias-{hashlib.sha256(storage_path.encode()).hexdigest()[:8]}",
                f"key-alias-{hashlib.sha256(storage_path.encode()).hexdigest()[:8]}",
                "account-a",
                "private",
                {"attachments": [{"storage_path": storage_path}]},
                created_at=OLD,
                updated_at=OLD,
            )
        )


def test_noncanonical_persisted_alias_aborts_before_any_claim_path_is_exposed(runtime):
    _, repository, _ = runtime
    insert_authenticated_queue_row(
        repository,
        "quarantine/canonical-persisted-object-0001",
        generation="canonical-persisted-generation",
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            """UPDATE retention_attachment_queue SET storage_path = ?""",
            ("quarantine//canonical-persisted-object-0001",),
        )

    with pytest.raises(StateConflictError, match="non-canonical"):
        repository.claim_retention_attachments(now=NOW, limit=1)


@pytest.mark.parametrize(
    ("column", "replacement", "use_replacement_id"),
    [
        ("dead_letter_id", "f" * 64, True),
        ("storage_path", "forged-dead-path.bin", False),
        ("key_id", "0" * 16, False),
        ("work_id", "forged-dead-work", False),
        ("generation", "forged-dead-generation", False),
    ],
)
def test_requeue_authenticates_dead_letter_path_key_and_generation(
    runtime, column, replacement, use_replacement_id
):
    _, repository, _ = runtime
    dead_letter = quarantine_attachment(
        repository, "authenticated-dead-letter.bin", suffix=column
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            f"UPDATE retention_attachment_dead_letters SET {column} = ?",
            (replacement,),
        )
    supplied_id = replacement if use_replacement_id else dead_letter["dead_letter_id"]

    with pytest.raises(StateConflictError, match="authenticate|historical HMAC"):
        repository.requeue_retention_attachment(
            supplied_id, actor_id="operator-a", now=NOW
        )
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM retention_attachment_dead_letters").fetchone()[0]
        == 1
    )


def test_requeue_fails_closed_when_dead_letter_historical_key_is_unavailable(runtime):
    control_plane, repository, _ = runtime
    current_without_history = DurableRuntimeRepository(
        control_plane,
        retention_hmac_key=b"task5-test-retention-hmac-key-0002",
    )
    dead_letter = quarantine_attachment(
        repository, "historical-dead-letter.bin", suffix="historical"
    )

    with pytest.raises(StateConflictError, match="historical HMAC"):
        current_without_history.requeue_retention_attachment(
            dead_letter["dead_letter_id"], actor_id="operator-a", now=NOW
        )


def test_completion_audit_counts_authenticated_cas_and_separates_no_op(runtime):
    _, repository, _ = runtime
    storage_path = "audit-cas.bin"
    seed_expired_records(repository, storage_path)
    batch = apply_batch(repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    claim = attachment_claims(batch)[storage_path]

    success = repository.complete_retention_attachments(
        {claim: "missing"}, now=NOW
    )
    duplicate = repository.complete_retention_attachments(
        {claim: "missing"}, now=NOW
    )

    assert success["missing"] == 1
    assert success["no_op"] == 0
    assert duplicate["missing"] == 0
    assert duplicate["no_op"] == 1
    payload = json.loads(
        repository.control_plane._get_conn().execute(
            """SELECT payload FROM runtime_audit_events
               WHERE action = 'attachment_retention'
               ORDER BY rowid DESC LIMIT 1"""
        ).fetchone()[0]
    )
    assert payload["attachments_missing"] == 0
    assert payload["attachments_no_op"] == 1


def test_completion_cas_fences_a_forged_claim_file_identity(runtime):
    _, repository, _ = runtime
    storage_path = "completion-file-identity.bin"
    seed_expired_records(repository, storage_path)
    batch = apply_batch(
        repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )
    claim = attachment_claims(batch)[storage_path]
    forged_claim = replace(claim, file_identity="forged-completion-identity")

    counts = repository.complete_retention_attachments(
        {forged_claim: "missing"}, now=NOW
    )

    assert counts["missing"] == 0
    assert counts["stale"] == 1
    assert repository.control_plane._get_conn().execute(
        "SELECT COUNT(*) FROM retention_attachment_queue WHERE storage_path = ?",
        (storage_path,),
    ).fetchone()[0] == 1


def test_poison_attachment_payload_is_redacted_without_blocking_the_batch(runtime):
    _, repository, attachment_root = runtime
    with pytest.raises(ValueError, match="safety bound"):
        repository.enqueue_inbox(
            InboxEvent(
                "event-poison",
                "poison-key",
                "account-a",
                "private",
                {
                    "attachments": [
                        {"storage_path": f"forged-{index}.bin"}
                        for index in range(65)
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
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_backlog").fetchone()[0] == 0
    assert summary.inbox_redacted == 1
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
    worker = RetentionWorker(
        repository,
        policy(batch_limit=80),
        attachment_root,
        monotonic=lambda: 0.0,
    )
    attempted = []
    monkeypatch.setattr(
        worker,
        "_delete_managed_attachment",
        lambda claim, now: attempted.append(claim.storage_path) or "failed",
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
    worker = RetentionWorker(
        repository,
        policy(batch_limit=80),
        attachment_root,
        monotonic=lambda: 0.0,
    )
    monkeypatch.setattr(
        worker,
        "_delete_managed_attachment",
        lambda claim, now: attempted.append(claim.storage_path) or "failed",
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

    queued_claims = repository.claim_retention_attachments(
        now=NOW + timedelta(seconds=2), limit=64
    )
    repository.complete_retention_attachments(
        {claim: "missing" for claim in queued_claims},
        now=NOW + timedelta(seconds=2),
    )
    worker.run_once(NOW + timedelta(seconds=3))

    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 16
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_backlog").fetchone()[0] == 0
    assert len(attempted) == 80
    assert len(set(attempted)) == 80


def test_overflow_backlog_preserves_owner_through_dead_letter_and_requeue(
    runtime, monkeypatch
):
    _, repository, attachment_root = runtime
    for index in range(65):
        event_id = f"event-owned-overflow-{index}"
        repository.enqueue_inbox(
            InboxEvent(
                event_id,
                f"key-owned-overflow-{index}",
                "account-a",
                "private",
                {"attachments": [{"storage_path": f"owned-overflow-{index}.bin"}]},
                created_at=OLD,
                updated_at=OLD,
            )
        )
        repository.bind_operational_owner(
            entity_kind="inbox",
            entity_id=event_id,
            tenant_id="tenant-a",
            owner_actor_id="alice",
        )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")
    worker = RetentionWorker(
        repository,
        policy(batch_limit=65, attachment_max_attempts=1),
        attachment_root,
        monotonic=lambda: 0.0,
    )
    monkeypatch.setattr(
        worker, "_delete_managed_attachment", lambda claim, now: "failed"
    )

    worker.run_once(NOW)
    assert conn.execute(
        "SELECT COUNT(*) FROM retention_attachment_backlog"
    ).fetchone()[0] == 1
    worker.run_once(NOW + timedelta(seconds=1))

    owned_ids = repository.list_operational_ids(
        entity_kind="retention_dead_letter",
        tenant_id="tenant-a",
        owner_actor_id=None,
        limit=100,
    )
    assert len(owned_ids) == 65
    assert len(repository.get_retention_attachment_dead_letters(owned_ids)) == 65
    assert repository.requeue_retention_attachment(
        owned_ids[-1], actor_id="alice", now=NOW + timedelta(seconds=2)
    )
    queued_owner = conn.execute(
        "SELECT tenant_id, owner_actor_id FROM retention_attachment_queue"
    ).fetchone()
    assert tuple(queued_owner) == ("tenant-a", "alice")


def test_terminal_attachment_failures_release_capacity_and_can_be_requeued(
    runtime, monkeypatch
):
    _, repository, attachment_root = runtime
    for index in range(80):
        repository.enqueue_inbox(
            InboxEvent(
                f"event-dead-letter-{index}",
                f"key-dead-letter-{index}",
                "account-a",
                "private",
                {"attachments": [{"storage_path": f"dead-letter-{index}.bin"}]},
                created_at=OLD,
                updated_at=OLD,
            )
        )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("UPDATE inbox_events SET state = 'succeeded'")
    worker = RetentionWorker(
        repository,
        policy(batch_limit=80, attachment_max_attempts=2),
        attachment_root,
        monotonic=lambda: 0.0,
    )
    monkeypatch.setattr(
        worker, "_delete_managed_attachment", lambda claim, now: "failed"
    )

    worker.run_once(NOW)
    persisted_retry = conn.execute(
        "SELECT attempt, next_attempt_at FROM retention_attachment_queue LIMIT 1"
    ).fetchone()
    assert persisted_retry["attempt"] == 1
    assert datetime.fromisoformat(persisted_retry["next_attempt_at"]) == (
        NOW + timedelta(seconds=2)
    )

    worker.run_once(NOW + timedelta(seconds=2))

    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 0
    dead_letters = repository.list_retention_attachment_dead_letters(limit=100)
    assert len(dead_letters) == 64
    assert {item["attempt"] for item in dead_letters} == {2}
    assert all(item["storage_path"] not in item["dead_letter_id"] for item in dead_letters)
    audit_payloads = [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT payload FROM runtime_audit_events WHERE action = 'attachment_retention'"
        )
    ]
    assert any(payload.get("attachments_quarantined") == 64 for payload in audit_payloads)

    worker.run_once(NOW + timedelta(seconds=3))

    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 16
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_backlog").fetchone()[0] == 0
    live_paths = {
        row[0]
        for row in conn.execute(
            "SELECT storage_path FROM retention_attachment_queue"
        )
    }
    dead_paths = {
        item["storage_path"]
        for item in repository.list_retention_attachment_dead_letters(limit=100)
    }
    assert len(live_paths | dead_paths) == 80

    for item in dead_letters[:48]:
        assert repository.requeue_retention_attachment(
            item["dead_letter_id"], actor_id="operator-a", now=NOW + timedelta(seconds=4)
        )
    blocked = dead_letters[48]
    assert not repository.requeue_retention_attachment(
        blocked["dead_letter_id"], actor_id="operator-a", now=NOW + timedelta(seconds=4)
    )
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 64

    released_path = conn.execute(
        "SELECT storage_path FROM retention_attachment_queue LIMIT 1"
    ).fetchone()[0]
    released_claim = claim_due_attachment(
        repository, released_path, now=NOW + timedelta(seconds=5)
    )
    repository.complete_retention_attachments(
        {released_claim: "missing"}, now=NOW + timedelta(seconds=5)
    )
    assert repository.requeue_retention_attachment(
        blocked["dead_letter_id"], actor_id="operator-a", now=NOW + timedelta(seconds=5)
    )
    assert not repository.requeue_retention_attachment(
        blocked["dead_letter_id"], actor_id="operator-a", now=NOW + timedelta(seconds=5)
    )
    active_paths = [
        row[0]
        for row in conn.execute(
            "SELECT storage_path FROM retention_attachment_queue"
        )
    ]
    assert len(active_paths) == 64
    assert len(set(active_paths)) == 64


def test_retention_batch_keeps_a_quarantined_path_out_of_the_active_queue(runtime):
    _, repository, _ = runtime
    storage_path = "reused-after-quarantine.bin"
    quarantine_attachment(repository, storage_path, suffix="original")
    repository.enqueue_inbox(
        InboxEvent(
            "event-reused-path",
            "key-reused-path",
            "account-a",
            "private",
            {"attachments": [{"storage_path": storage_path}]},
            created_at=OLD,
            updated_at=OLD,
        )
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            "UPDATE inbox_events SET state = 'succeeded' WHERE event_id = ?",
            ("event-reused-path",),
        )

    batch = apply_batch(repository,
        now=NOW,
        inbox_before=NOW,
        outbox_before=NOW,
        audit_before=OLD - timedelta(days=1),
        limit=1,
    )

    assert batch["attachment_paths"] == ()
    assert conn.execute("SELECT COUNT(*) FROM retention_attachment_queue").fetchone()[0] == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM retention_attachment_dead_letters").fetchone()[0]
        == 1
    )


def test_due_claim_fails_closed_for_ambiguous_active_and_dead_state(runtime):
    _, repository, _ = runtime
    storage_path = "ambiguous-dual-claim.bin"
    quarantine_attachment(repository, storage_path, suffix="claim")
    conn = repository.control_plane._get_conn()
    insert_authenticated_queue_row(
        repository, storage_path, generation="ambiguous-active-generation"
    )

    with pytest.raises(StateConflictError, match="ambiguous"):
        apply_batch(repository,
            now=NOW,
            inbox_before=NOW,
            outbox_before=NOW,
            audit_before=OLD - timedelta(days=1),
            limit=1,
        )

    assert (
        conn.execute(
            """SELECT
                   (SELECT COUNT(*) FROM retention_attachment_queue
                    WHERE storage_path = ?) +
                   (SELECT COUNT(*) FROM retention_attachment_dead_letters
                    WHERE storage_path = ?)""",
            (storage_path, storage_path),
        ).fetchone()[0]
        == 2
    )


def test_requeue_refuses_ambiguous_active_and_dead_state(runtime):
    _, repository, _ = runtime
    storage_path = "ambiguous-dual-requeue.bin"
    dead_letter = quarantine_attachment(repository, storage_path, suffix="requeue")
    conn = repository.control_plane._get_conn()
    insert_authenticated_queue_row(
        repository, storage_path, generation="ambiguous-requeue-generation"
    )

    with pytest.raises(StateConflictError, match="ambiguous"):
        repository.requeue_retention_attachment(
            dead_letter["dead_letter_id"], actor_id="operator-a", now=NOW
        )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM retention_attachment_queue WHERE storage_path = ?",
            (storage_path,),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM retention_attachment_dead_letters WHERE storage_path = ?",
            (storage_path,),
        ).fetchone()[0]
        == 1
    )


def test_legacy_queue_without_file_identity_requires_explicit_migration(tmp_path):
    storage_path = "legacy-unambiguous.bin"
    legacy_queue_id = hmac.new(
        RETENTION_KEY, storage_path.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    conn = sqlite3.connect(tmp_path / "runtime.db")
    conn.execute(
        """CREATE TABLE retention_attachment_queue (
               queue_id TEXT PRIMARY KEY, storage_path TEXT NOT NULL,
               queued_at TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
               next_attempt_at TEXT NOT NULL, last_error TEXT
           )"""
    )
    conn.execute(
        """INSERT INTO retention_attachment_queue (
               queue_id, storage_path, queued_at, next_attempt_at
           ) VALUES (?, ?, ?, ?)""",
        (legacy_queue_id, storage_path, NOW.isoformat(), NOW.isoformat()),
    )
    conn.commit()
    conn.close()

    control_plane = ControlPlane(tmp_path)
    try:
        with pytest.raises(StateConflictError, match="identity.*explicit migration"):
            DurableRuntimeRepository(
                control_plane, retention_hmac_key=RETENTION_KEY
            )
        row = control_plane._get_conn().execute(
            "SELECT * FROM retention_attachment_queue"
        ).fetchone()
        assert row["queue_id"] == legacy_queue_id
        assert row["key_id"] is None
        assert row["work_id"] is None
        assert row["generation"] is None
    finally:
        control_plane.close()


def test_legacy_active_and_dead_overlap_fails_without_destructive_guess(tmp_path):
    storage_path = "legacy-ambiguous.bin"
    legacy_queue_id = hmac.new(
        RETENTION_KEY, storage_path.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    legacy_dead_id = hmac.new(
        RETENTION_KEY,
        f"dead-letter:{storage_path}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    conn = sqlite3.connect(tmp_path / "runtime.db")
    conn.executescript(
        """
        CREATE TABLE retention_attachment_queue (
            queue_id TEXT PRIMARY KEY, storage_path TEXT NOT NULL,
            queued_at TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL, last_error TEXT
        );
        CREATE TABLE retention_attachment_dead_letters (
            dead_letter_id TEXT PRIMARY KEY, storage_path TEXT NOT NULL UNIQUE,
            attempt INTEGER NOT NULL, last_error TEXT NOT NULL,
            quarantined_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """INSERT INTO retention_attachment_queue (
               queue_id, storage_path, queued_at, next_attempt_at
           ) VALUES (?, ?, ?, ?)""",
        (legacy_queue_id, storage_path, NOW.isoformat(), NOW.isoformat()),
    )
    conn.execute(
        """INSERT INTO retention_attachment_dead_letters (
               dead_letter_id, storage_path, attempt, last_error, quarantined_at
           ) VALUES (?, ?, 5, 'delete_failed', ?)""",
        (legacy_dead_id, storage_path, NOW.isoformat()),
    )
    conn.commit()
    conn.close()

    control_plane = ControlPlane(tmp_path)
    try:
        with pytest.raises(StateConflictError, match="ambiguous"):
            DurableRuntimeRepository(
                control_plane, retention_hmac_key=RETENTION_KEY
            )
        persisted = control_plane._get_conn().execute(
            """SELECT
                   (SELECT queue_id FROM retention_attachment_queue),
                   (SELECT dead_letter_id FROM retention_attachment_dead_letters)"""
        ).fetchone()
        assert tuple(persisted) == (legacy_queue_id, legacy_dead_id)
    finally:
        control_plane.close()


def test_dead_letter_controls_reject_invalid_attempts_and_untrusted_ids(runtime):
    _, repository, _ = runtime

    with pytest.raises(ValueError, match="max_attempts"):
        repository.complete_retention_attachments({}, now=NOW, max_attempts=0)
    with pytest.raises(ValueError, match="dead_letter_id"):
        repository.requeue_retention_attachment(
            "alice@example.com", actor_id="operator-a", now=NOW
        )
    assert repository.list_audit_events(
        "retention_attachment_dead_letter", "alice@example.com"
    ) == []


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
        lambda claim, now: (
            "failed"
            if claim.storage_path == "blocked.bin"
            else original_delete(claim, now)
        ),
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

    def fail_once(claim, now):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "failed"
        return original_delete(claim, now)

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
        monkeypatch.setattr(
            worker,
            "_delete_windows_handle",
            lambda candidate, claim, now: "rejected",
        )
    summary = worker.run_once(NOW)

    assert outside.read_bytes() == b"must survive"
    assert summary.attachments_deleted == 0
    assert summary.attachments_rejected == 1


@pytest.mark.parametrize("unsafe_path", ["../outside.txt", "C:\\outside.txt", "/outside.txt"])
def test_attachment_cleanup_rejects_non_relative_managed_paths(runtime, unsafe_path):
    _, repository, _ = runtime

    with pytest.raises(ValueError, match="canonical|storage_path"):
        seed_expired_records(repository, unsafe_path)


@pytest.mark.parametrize(
    "change",
    [
        {"inbox_payload_ttl": timedelta(0)},
        {"outbox_delivery_ttl": timedelta(seconds=-1)},
        {"audit_ttl": "30 days"},
        {"batch_limit": 0},
        {"batch_limit": 1001},
        {"batch_limit": True},
        {"attachment_max_attempts": 0},
        {"attachment_max_attempts": 101},
        {"attachment_max_attempts": True},
    ],
)
def test_retention_policy_rejects_invalid_or_unbounded_configuration(change):
    values = {
        "inbox_payload_ttl": timedelta(days=30),
        "outbox_delivery_ttl": timedelta(days=30),
        "audit_ttl": timedelta(days=30),
        "batch_limit": 100,
        "attachment_max_attempts": 5,
    }
    values.update(change)
    with pytest.raises((TypeError, ValueError)):
        RetentionPolicy(**values)


def test_run_once_requires_timezone_aware_now(runtime):
    _, repository, attachment_root = runtime
    worker = RetentionWorker(repository, policy(), attachment_root)
    with pytest.raises(ValueError, match="timezone"):
        worker.run_once(NOW.replace(tzinfo=None))


def test_run_once_rejects_a_non_finite_monotonic_clock(runtime):
    _, repository, attachment_root = runtime
    worker = RetentionWorker(
        repository, policy(), attachment_root, monotonic=lambda: float("nan")
    )

    with pytest.raises(ValueError, match="monotonic"):
        worker.run_once(NOW)


def test_run_once_fails_closed_if_the_monotonic_clock_moves_backwards(runtime):
    _, repository, attachment_root = runtime
    ticks = iter((2.0, 1.0))
    worker = RetentionWorker(
        repository, policy(), attachment_root, monotonic=lambda: next(ticks)
    )

    with pytest.raises(StateConflictError, match="monotonic"):
        worker.run_once(NOW)


def test_attachment_root_and_windows_path_normalization_are_defensive(runtime, tmp_path):
    _, repository, attachment_root = runtime
    with pytest.raises(ValueError, match="attachment_root"):
        RetentionWorker(repository, policy(), tmp_path / "missing")

    worker = RetentionWorker(repository, policy(), attachment_root)
    assert worker._delete_managed_attachment("", NOW) == "rejected"
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
