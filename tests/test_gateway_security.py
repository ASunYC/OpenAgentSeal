from __future__ import annotations

import hashlib
import hmac
import io
import threading
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from open_agent.gateway.security import (
    AttachmentGuard,
    AttachmentPolicy,
    AttachmentUpload,
    HierarchicalIngressLimiter,
    IngressContext,
    IngressGuard,
    LimitRule,
    OutboundUrlPolicy,
    QuotaSnapshot,
    ResourceQuotaPolicy,
    SecurityViolation,
    ToolApprovalGuard,
    WebhookAuthenticator,
)


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
SECRET = b"test-secret"


class Nonces:
    def __init__(self):
        self.values = set()

    def claim(self, account_id, nonce, expires_at):
        key = (account_id, nonce)
        if key in self.values:
            return False
        self.values.add(key)
        return True


def signed_headers(body=b"{}", *, timestamp=NOW, nonce="nonce-1", account="account-1"):
    stamp = str(int(timestamp.timestamp()))
    signature = hmac.new(
        SECRET, stamp.encode() + b"." + nonce.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return {
        "x-account-id": account,
        "x-webhook-timestamp": stamp,
        "x-webhook-nonce": nonce,
        "x-webhook-signature": f"sha256={signature}",
    }


def authenticator(nonces=None):
    return WebhookAuthenticator(
        secret_lookup=lambda account: SECRET if account == "account-1" else None,
        nonce_store=nonces or Nonces(),
        max_age=timedelta(minutes=5),
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {**signed_headers(), "x-webhook-signature": "sha256=bad"},
        signed_headers(timestamp=NOW - timedelta(minutes=6)),
        signed_headers(account="unknown"),
    ],
)
def test_webhook_authentication_fails_closed_for_missing_invalid_stale_or_unknown(headers):
    with pytest.raises(SecurityViolation):
        authenticator().verify(b"{}", headers, NOW)


def test_webhook_authentication_rejects_nonce_replay():
    verifier = authenticator()
    headers = signed_headers()
    assert verifier.verify(b"{}", headers, NOW) == "account-1"

    with pytest.raises(SecurityViolation, match="replay"):
        verifier.verify(b"{}", headers, NOW)


def test_webhook_authentication_rejects_future_and_naive_time():
    with pytest.raises(SecurityViolation, match="timestamp"):
        authenticator().verify(b"{}", signed_headers(timestamp=NOW + timedelta(seconds=1)), NOW)
    with pytest.raises(ValueError, match="timezone"):
        authenticator().verify(b"{}", signed_headers(), NOW.replace(tzinfo=None))


def test_invalid_authentication_is_counted_by_preauth_global_limits():
    rules = {
        "global": LimitRule(1, timedelta(minutes=1), 10),
        "ip": LimitRule(10, timedelta(minutes=1), 10),
        "adapter": LimitRule(10, timedelta(minutes=1), 10),
        "account": LimitRule(10, timedelta(minutes=1), 10),
    }
    guard = IngressGuard(authenticator(), HierarchicalIngressLimiter(rules, now=lambda: NOW))
    context = IngressContext("93.184.216.34", "test", "account-1")
    invalid = {**signed_headers(nonce="bad"), "x-webhook-signature": "sha256=bad"}
    with pytest.raises(SecurityViolation, match="signature"):
        guard.process(b"{}", invalid, context, lambda raw: raw, NOW)
    with pytest.raises(SecurityViolation, match="global"):
        guard.process(
            b"{}", signed_headers(nonce="valid"), context, lambda raw: raw, NOW
        )


def ingress_limiter(**overrides):
    rules = {
        "global": LimitRule(requests=10, window=timedelta(minutes=1), concurrency=10),
        "ip": LimitRule(requests=10, window=timedelta(minutes=1), concurrency=10),
        "adapter": LimitRule(requests=10, window=timedelta(minutes=1), concurrency=10),
        "account": LimitRule(requests=10, window=timedelta(minutes=1), concurrency=10),
    }
    rules.update(overrides)
    return HierarchicalIngressLimiter(rules, now=lambda: NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requests", True),
        ("requests", 1.5),
        ("requests", float("nan")),
        ("requests", float("inf")),
        ("requests", 1_000_001),
        ("concurrency", False),
        ("concurrency", 2.5),
        ("concurrency", float("nan")),
        ("concurrency", float("inf")),
        ("concurrency", 100_001),
        ("window", True),
        ("window", 1.5),
        ("window", float("nan")),
        ("window", float("inf")),
        ("window", timedelta(days=2)),
    ],
)
def test_limit_rules_reject_non_integer_non_finite_and_unbounded_values(field, value):
    values = {"requests": 10, "window": timedelta(minutes=1), "concurrency": 10}
    values[field] = value
    with pytest.raises(ValueError):
        LimitRule(**values)


@pytest.mark.parametrize("dimension", ["global", "ip", "adapter", "account"])
def test_each_request_limit_rejects_before_payload_parsing(dimension):
    limiter = ingress_limiter(**{dimension: LimitRule(1, timedelta(minutes=1), 10)})
    context = IngressContext("203.0.113.5", "test", "account-1")
    parsed = []
    guard = IngressGuard(authenticator(Nonces()), limiter)
    guard.process(b"{}", signed_headers(nonce="first"), context, lambda raw: parsed.append(raw), NOW)

    with pytest.raises(SecurityViolation, match=dimension):
        guard.process(b"{}", signed_headers(nonce="second"), context, lambda raw: parsed.append(raw), NOW)
    assert parsed == [b"{}"]


@pytest.mark.parametrize("dimension", ["global", "ip", "adapter", "account"])
def test_each_concurrency_limit_rejects_and_release_restores_capacity(dimension):
    limiter = ingress_limiter(**{dimension: LimitRule(10, timedelta(minutes=1), 1)})
    context = IngressContext("203.0.113.5", "test", "account-1")
    lease = limiter.acquire(context)
    with pytest.raises(SecurityViolation, match=dimension):
        limiter.acquire(context)
    lease.release()
    limiter.acquire(context).release()


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        (QuotaSnapshot(queue_depth=11), "queue"),
        (QuotaSnapshot(database_bytes=101), "database"),
        (QuotaSnapshot(disk_free_bytes=9), "disk"),
        (QuotaSnapshot(attachment_bytes=51), "attachment"),
        (QuotaSnapshot(conversation_agents=3), "conversation"),
    ],
)
def test_resource_and_per_conversation_quotas_fail_closed(snapshot, message):
    policy = ResourceQuotaPolicy(10, 100, 10, 50, 2)
    with pytest.raises(SecurityViolation, match=message):
        policy.validate(snapshot)


def test_quota_reservations_are_delegated_atomically_and_fail_closed():
    class Ledger:
        def __init__(self, accepted):
            self.accepted = accepted
            self.released = []

        def try_reserve(self, policy, request, conversation_id):
            return "reservation-1" if self.accepted else None

        def release(self, token):
            self.released.append(token)

    policy = ResourceQuotaPolicy(10, 100, 10, 50, 2)
    request = QuotaSnapshot(queue_depth=1, disk_free_bytes=10)
    with pytest.raises(SecurityViolation, match="quota"):
        policy.reserve(Ledger(False), request, conversation_id="conversation-1")

    ledger = Ledger(True)
    lease = policy.reserve(ledger, request, conversation_id="conversation-1")
    lease.release()
    lease.release()
    assert ledger.released == ["reservation-1"]


PUBLIC = {"files.example.com": ("93.184.216.34",), "cdn.example.com": ("1.1.1.1",)}


def url_policy(records=None):
    table = records or PUBLIC
    return OutboundUrlPolicy(
        allowed_hosts=("files.example.com", "cdn.example.com"),
        resolver=lambda host: table.get(host, ()),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://files.example.com/a",
        "https://evil.example/a",
        "https://user:pass@files.example.com/a",
    ],
)
def test_outbound_urls_require_https_allowlisted_hosts_and_no_credentials(url):
    with pytest.raises(SecurityViolation):
        url_policy().validate(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "100.64.0.1",
        "169.254.1.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
    ],
)
def test_outbound_urls_reject_private_loopback_link_local_and_metadata_addresses(address):
    with pytest.raises(SecurityViolation, match="address"):
        url_policy({"files.example.com": (address,)}).validate("https://files.example.com/a")


def test_redirects_are_revalidated_and_dns_answers_are_pinned():
    policy = url_policy()
    validated = policy.validate("https://files.example.com/a")
    assert validated.addresses == ("93.184.216.34",)
    policy.validate_peer(validated, "93.184.216.34")

    with pytest.raises(SecurityViolation, match="rebinding"):
        policy.validate_peer(validated, "8.8.8.8")
    with pytest.raises(SecurityViolation):
        policy.validate_redirect(validated, "https://evil.example/redirect")


class MemoryStorage:
    def __init__(self):
        self.saved = []
        self.cleaned_at = None
        self.batch_calls = 0

    def put(self, path, content, *, expires_at, executable):
        self.saved.append((path, content, expires_at, executable))
        return True

    def put_batch(self, entries):
        self.batch_calls += 1
        self.saved.extend(entries)
        return True

    def cleanup_expired(self, now):
        self.cleaned_at = now
        return 2

    def delete_batch_if_owned(self, owned_paths):
        selected = dict(owned_paths)
        self.saved = [
            entry for entry in self.saved
            if selected.get(entry[0]) != entry[4]
        ]
        return True


class CleanScanner:
    def scan(self, content):
        return True


class ChunkStream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self.deadlines = []

    def read(self, max_bytes, deadline):
        self.deadlines.append((max_bytes, deadline))
        return next(self._chunks, None)


def attachment_guard(
    storage=None,
    scanner=None,
    monotonic=lambda: 0.0,
    random_name=lambda: "random-token-123456",
    **policy_changes,
):
    values = {
        "max_count": 2,
        "max_aggregate_bytes": 12,
        "max_decompressed_bytes": 24,
        "max_compression_ratio": 4,
        "max_stream_seconds": 2,
        "retention": timedelta(hours=1),
    }
    values.update(policy_changes)
    return AttachmentGuard(
        AttachmentPolicy(**values),
        storage or MemoryStorage(),
        scanner or CleanScanner(),
        now=lambda: NOW,
        monotonic=monotonic,
        random_name=random_name,
    )


def upload(**changes):
    values = {
        "filename": "photo.png",
        "claimed_content_type": "image/png",
        "chunks": (b"\x89PNG\r\n\x1a\n",),
    }
    values.update(changes)
    if not hasattr(values["chunks"], "read"):
        values["chunks"] = ChunkStream(values["chunks"])
    return AttachmentUpload(**values)


def test_attachment_count_aggregate_decompressed_and_stream_time_limits():
    with pytest.raises(SecurityViolation, match="count"):
        attachment_guard().ingest((upload(), upload(), upload()))
    with pytest.raises(SecurityViolation, match="aggregate"):
        attachment_guard().ingest((upload(chunks=(b"\x89PNG\r\n\x1a\n12345",)),))
    large = make_zip({"large.txt": b"x" * 25})
    with pytest.raises(SecurityViolation, match="decompressed"):
        attachment_guard(max_aggregate_bytes=1000).ingest(
            (upload(claimed_content_type="application/zip", chunks=(large,)),)
        )
    first_archive = make_zip({"first.txt": b"x" * 13})
    second_archive = make_zip({"second.txt": b"x" * 13})
    with pytest.raises(SecurityViolation, match="decompressed"):
        attachment_guard(max_aggregate_bytes=1000).ingest(
            (
                upload(claimed_content_type="application/zip", chunks=(first_archive,)),
                upload(claimed_content_type="application/zip", chunks=(second_archive,)),
            )
        )
    archive = make_zip({"large.txt": b"x" * 25})
    with pytest.raises(SecurityViolation, match="decompressed"):
        attachment_guard(max_aggregate_bytes=1000).ingest(
            (upload(claimed_content_type="application/zip", chunks=(archive,)),)
        )
    ticks = iter((0.0, 0.0, 2.1))
    with pytest.raises(SecurityViolation, match="stream"):
        attachment_guard(monotonic=lambda: next(ticks)).ingest(
            (upload(chunks=(b"\x89PNG", b"data")),)
        )


def test_aggregate_decompression_stops_at_the_request_wide_remaining_budget(monkeypatch):
    first = make_zip({"first.txt": b"x" * 13})
    second = make_zip({"second.txt": b"x" * 100})
    observed = []
    original_read = zipfile.ZipExtFile.read

    def tracked_read(source, size=-1):
        chunk = original_read(source, size)
        observed.append(len(chunk))
        return chunk

    monkeypatch.setattr(zipfile.ZipExtFile, "read", tracked_read)
    with pytest.raises(SecurityViolation, match="decompressed"):
        attachment_guard(max_aggregate_bytes=1000).ingest(
            (
                upload(claimed_content_type="application/zip", chunks=(first,)),
                upload(claimed_content_type="application/zip", chunks=(second,)),
            )
        )

    assert sum(observed) <= 25


def test_attachment_count_limit_stops_consuming_an_untrusted_upload_stream():
    def uploads():
        yield upload()
        yield upload()
        yield upload()
        raise AssertionError("guard consumed beyond max_count + 1")

    with pytest.raises(SecurityViolation, match="count"):
        attachment_guard().ingest(uploads())


def test_attachment_stream_receives_a_transport_enforced_deadline():
    stream = ChunkStream((b"\x89PNG\r\n\x1a\n",))
    attachment_guard().ingest((upload(chunks=stream),))

    assert stream.deadlines == [(13, 2.0), (5, 2.0)]


def make_zip(entries):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return target.getvalue()


def forge_zip_uncompressed_size(content, forged_size):
    payload = bytearray(make_zip({"payload.txt": content}))
    central = payload.find(b"PK\x01\x02")
    assert central >= 0
    payload[central + 24 : central + 28] = forged_size.to_bytes(4, "little")
    return bytes(payload)


def make_symlink_zip():
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        entry = zipfile.ZipInfo("safe/link")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        archive.writestr(entry, "target")
    return target.getvalue()


def test_attachment_magic_bytes_archive_bombs_paths_and_symlinks_are_rejected():
    with pytest.raises(SecurityViolation, match="magic"):
        attachment_guard().ingest((upload(chunks=(b"not-a-png",)),))
    bomb = make_zip({"huge.txt": b"0" * 5000})
    with pytest.raises(SecurityViolation, match="archive bomb"):
        attachment_guard(
            max_aggregate_bytes=1000,
            max_decompressed_bytes=10000,
            max_compression_ratio=2,
        ).ingest(
            (upload(claimed_content_type="application/zip", chunks=(bomb,)),)
        )
    forged = forge_zip_uncompressed_size(b"x" * 5000, 1)
    with pytest.raises(SecurityViolation, match="decompressed|archive"):
        attachment_guard(
            max_aggregate_bytes=1000,
            max_decompressed_bytes=10,
            max_compression_ratio=1000,
        ).ingest(
            (upload(claimed_content_type="application/zip", chunks=(forged,)),)
        )
    for name in ("../escape.txt", "C:\\escape.txt"):
        unsafe = make_zip({name: b"x"})
        with pytest.raises(SecurityViolation):
            attachment_guard(max_aggregate_bytes=1000).ingest(
                (upload(claimed_content_type="application/zip", chunks=(unsafe,)),)
            )
    with pytest.raises(SecurityViolation, match="archive"):
        attachment_guard(max_aggregate_bytes=1000).ingest(
            (
                upload(
                    claimed_content_type="application/zip",
                    chunks=(make_symlink_zip(),),
                ),
            )
        )


def test_attachment_storage_names_are_safe_and_created_exclusively():
    unsafe = attachment_guard()
    unsafe._random_name = lambda: "../escape"
    with pytest.raises(SecurityViolation, match="name"):
        unsafe.ingest((upload(),))

    class CollisionStorage(MemoryStorage):
        def put(self, path, content, *, expires_at, executable):
            return False

        def put_batch(self, entries):
            return False

    collision_storage = CollisionStorage()
    collision_storage.saved.append(
        (
            "quarantine/random-token-123456", b"pre-existing", NOW,
            False, "0" * 32,
        )
    )
    staged = []
    collision_guard = attachment_guard(storage=collision_storage)
    with pytest.raises(SecurityViolation, match="collision"):
        collision_guard.ingest((upload(),), on_staging=staged.extend)
    collision_guard.rollback(staged)
    assert collision_storage.saved[0][1] == b"pre-existing"


def test_multi_attachment_storage_uses_one_atomic_batch_boundary():
    storage = MemoryStorage()
    names = iter(("random-token-123456", "random-token-654321"))

    stored = attachment_guard(
        storage=storage,
        max_aggregate_bytes=20,
        random_name=lambda: next(names),
    ).ingest((upload(), upload()))

    assert len(stored) == 2
    assert storage.batch_calls == 1
    assert len(storage.saved) == 2


def test_attachment_guard_rolls_back_exact_managed_batch():
    storage = MemoryStorage()
    guard = attachment_guard(storage=storage)
    stored = guard.ingest((upload(),))

    guard.rollback(stored)

    assert storage.saved == []


def test_attachments_use_random_non_executable_isolated_paths_and_expire():
    storage = MemoryStorage()
    guard = attachment_guard(storage=storage)
    stored = guard.ingest((upload(),))[0]

    assert stored.storage_path == "quarantine/random-token-123456"
    assert "photo.png" not in stored.storage_path
    assert storage.saved[0][3] is False
    assert stored.expires_at == NOW + timedelta(hours=1)
    assert guard.cleanup_expired() == 2
    assert storage.cleaned_at == NOW


def test_attachment_scanner_failure_or_detection_fails_closed():
    class BrokenScanner:
        def scan(self, content):
            raise RuntimeError("offline")

    with pytest.raises(SecurityViolation, match="scanner"):
        attachment_guard(scanner=BrokenScanner()).ingest((upload(),))

    class MalwareScanner:
        def scan(self, content):
            return False

    with pytest.raises(SecurityViolation, match="malware"):
        attachment_guard(scanner=MalwareScanner()).ingest((upload(),))


def test_ingress_metadata_cannot_bypass_tool_approval():
    guard = ToolApprovalGuard()
    with pytest.raises(SecurityViolation, match="approval"):
        guard.authorize(
            requires_approval=True,
            approved_by_control_plane=False,
            ingress_metadata={"approved": True, "bypass_tool_approval": True},
        )
    guard.authorize(
        requires_approval=True,
        approved_by_control_plane=True,
        ingress_metadata={"approved": False},
    )


@pytest.mark.parametrize(
    ("requires_approval", "approved"),
    [(None, False), (0, False), (False, None), (True, 1)],
)
def test_tool_approval_rejects_non_boolean_policy_inputs(requires_approval, approved):
    with pytest.raises(TypeError, match="boolean"):
        ToolApprovalGuard().authorize(
            requires_approval=requires_approval,
            approved_by_control_plane=approved,
        )


def test_rate_rejection_does_not_consume_a_valid_webhook_nonce():
    current = [NOW]
    rules = {
        "global": LimitRule(10, timedelta(minutes=1), 10),
        "ip": LimitRule(10, timedelta(minutes=1), 10),
        "adapter": LimitRule(10, timedelta(minutes=1), 10),
        "account": LimitRule(1, timedelta(minutes=1), 10),
    }
    guard = IngressGuard(
        authenticator(Nonces()), HierarchicalIngressLimiter(rules, now=lambda: current[0])
    )
    context = IngressContext("93.184.216.34", "test", "account-1")
    guard.process(b"{}", signed_headers(nonce="first"), context, lambda raw: raw, NOW)
    second = signed_headers(nonce="retryable")
    with pytest.raises(SecurityViolation, match="account"):
        guard.process(b"{}", second, context, lambda raw: raw, NOW)

    current[0] = NOW + timedelta(minutes=1)
    assert guard.process(b"{}", second, context, lambda raw: raw, current[0]) == b"{}"


def test_concurrency_lease_release_is_idempotent_across_threads():
    limiter = ingress_limiter(
        **{
            name: LimitRule(10, timedelta(minutes=1), 2)
            for name in ("global", "ip", "adapter", "account")
        }
    )
    context = IngressContext("93.184.216.34", "test", "account-1")
    first = limiter.acquire(context)
    second = limiter.acquire(context)
    both_called = threading.Event()
    call_count = [0]
    count_lock = threading.Lock()
    original_release = limiter._release

    def synchronized(keys):
        with count_lock:
            call_count[0] += 1
            if call_count[0] == 2:
                both_called.set()
        both_called.wait(timeout=0.2)
        original_release(keys)

    limiter._release = synchronized
    threads = [threading.Thread(target=first.release) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    limiter._release = original_release

    third = limiter.acquire(context)
    with pytest.raises(SecurityViolation, match="concurrency"):
        limiter.acquire(context)
    second.release()
    third.release()


def test_expired_rate_limit_keys_are_pruned():
    current = [NOW]
    rules = {name: LimitRule(100, timedelta(seconds=1), 100) for name in ("global", "ip", "adapter", "account")}
    limiter = HierarchicalIngressLimiter(rules, now=lambda: current[0])
    for index in range(20):
        limiter.acquire(IngressContext(f"93.184.216.{index}", "test", "account-1")).release()
    current[0] += timedelta(seconds=1)
    limiter.acquire(IngressContext("8.8.8.8", "test", "account-1")).release()

    assert len(limiter._requests) == 4


@pytest.mark.parametrize(
    "change",
    [
        {"max_count": 0},
        {"max_count": 65},
        {"max_aggregate_bytes": -1},
        {"max_decompressed_bytes": 0},
        {"max_compression_ratio": float("nan")},
        {"max_stream_seconds": float("inf")},
        {"retention": timedelta(0)},
    ],
)
def test_attachment_policy_rejects_non_positive_or_non_finite_limits(change):
    values = {
        "max_count": 2,
        "max_aggregate_bytes": 12,
        "max_decompressed_bytes": 24,
        "max_compression_ratio": 4,
        "max_stream_seconds": 2,
        "retention": timedelta(hours=1),
    }
    values.update(change)
    with pytest.raises(ValueError):
        AttachmentPolicy(**values)
