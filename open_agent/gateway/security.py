"""Fail-closed, dependency-injected gateway ingress and egress security."""

from __future__ import annotations

import hashlib
import hmac
import io
import ipaddress
import math
import re
import stat
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib.parse import urlsplit


class SecurityViolation(RuntimeError):
    """An untrusted gateway operation failed a mandatory security boundary."""


class NonceStore(Protocol):
    def claim(self, account_id: str, nonce: str, expires_at: datetime) -> bool: ...


class WebhookAuthenticator:
    REQUIRED = (
        "x-account-id",
        "x-webhook-timestamp",
        "x-webhook-nonce",
        "x-webhook-signature",
    )

    def __init__(
        self,
        *,
        secret_lookup: Callable[[str], bytes | None],
        nonce_store: NonceStore,
        max_age: timedelta,
    ) -> None:
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        self._secret_lookup = secret_lookup
        self._nonce_store = nonce_store
        self._max_age = max_age

    def authenticate(
        self, raw_body: bytes, headers: Mapping[str, str], now: datetime
    ) -> "VerifiedWebhook":
        _require_aware(now)
        normalized = {str(key).lower(): str(value) for key, value in headers.items()}
        if any(not normalized.get(name) for name in self.REQUIRED):
            raise SecurityViolation("missing webhook authentication headers")
        account = normalized["x-account-id"]
        nonce = normalized["x-webhook-nonce"]
        try:
            timestamp = datetime.fromtimestamp(
                int(normalized["x-webhook-timestamp"]), tz=timezone.utc
            )
        except (ValueError, OverflowError) as exc:
            raise SecurityViolation("invalid webhook timestamp") from exc
        utc_now = now.astimezone(timezone.utc)
        if timestamp > utc_now or utc_now - timestamp > self._max_age:
            raise SecurityViolation("stale or future webhook timestamp")
        try:
            secret = self._secret_lookup(account)
        except Exception as exc:
            raise SecurityViolation("webhook secret lookup unavailable") from exc
        if not isinstance(secret, bytes) or not secret:
            raise SecurityViolation("webhook secret unavailable")
        stamp = normalized["x-webhook-timestamp"].encode()
        expected = hmac.new(
            secret, stamp + b"." + nonce.encode() + b"." + raw_body, hashlib.sha256
        ).hexdigest()
        supplied = normalized["x-webhook-signature"]
        if not supplied.startswith("sha256=") or not hmac.compare_digest(
            supplied[7:], expected
        ):
            raise SecurityViolation("invalid webhook signature")
        return VerifiedWebhook(
            account_id=account,
            nonce=nonce,
            expires_at=utc_now + self._max_age,
            nonce_store=self._nonce_store,
        )

    def verify(self, raw_body: bytes, headers: Mapping[str, str], now: datetime) -> str:
        verified = self.authenticate(raw_body, headers, now)
        verified.claim_nonce()
        return verified.account_id


@dataclass(frozen=True, slots=True)
class VerifiedWebhook:
    account_id: str
    nonce: str
    expires_at: datetime
    nonce_store: NonceStore

    def claim_nonce(self) -> None:
        try:
            claimed = self.nonce_store.claim(self.account_id, self.nonce, self.expires_at)
        except Exception as exc:
            raise SecurityViolation("webhook replay store unavailable") from exc
        if not claimed:
            raise SecurityViolation("webhook nonce replay detected")


@dataclass(frozen=True, slots=True)
class IngressContext:
    ip: str
    adapter: str
    account: str


@dataclass(frozen=True, slots=True)
class LimitRule:
    requests: int
    window: timedelta
    concurrency: int

    def __post_init__(self) -> None:
        if type(self.requests) is not int or not 1 <= self.requests <= 1_000_000:
            raise ValueError("requests must be an integer between 1 and 1000000")
        if type(self.concurrency) is not int or not 1 <= self.concurrency <= 100_000:
            raise ValueError("concurrency must be an integer between 1 and 100000")
        if type(self.window) is not timedelta or not timedelta(0) < self.window <= timedelta(days=1):
            raise ValueError("window must be a timedelta between 0 and 1 day")


class _IngressLease:
    def __init__(self, limiter: "HierarchicalIngressLimiter", keys: tuple[tuple[str, str], ...]):
        self._limiter = limiter
        self._keys = keys
        self._released = False
        self._release_lock = threading.Lock()

    def release(self) -> None:
        with self._release_lock:
            if not self._released:
                self._limiter._release(self._keys)
                self._released = True

    def __enter__(self) -> "_IngressLease":
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()


class HierarchicalIngressLimiter:
    DIMENSIONS = ("global", "ip", "adapter", "account")

    def __init__(self, rules: Mapping[str, LimitRule], *, now: Callable[[], datetime]):
        if set(rules) != set(self.DIMENSIONS):
            raise ValueError("rules must define global, ip, adapter, and account")
        self._rules = dict(rules)
        self._now = now
        self._requests: dict[tuple[str, str], tuple[datetime, int]] = {}
        self._concurrency: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def acquire(
        self,
        context: IngressContext,
        dimensions: Iterable[str] | None = None,
    ) -> _IngressLease:
        now = self._now()
        _require_aware(now)
        all_keys = (
            ("global", "global"),
            ("ip", context.ip),
            ("adapter", context.adapter),
            ("account", context.account),
        )
        selected = tuple(dimensions) if dimensions is not None else self.DIMENSIONS
        if not selected or len(set(selected)) != len(selected) or any(
            dimension not in self.DIMENSIONS for dimension in selected
        ):
            raise ValueError("dimensions must be a unique non-empty limiter subset")
        keys = tuple(key for key in all_keys if key[0] in selected)
        with self._lock:
            next_requests = {
                key: value
                for key, value in self._requests.items()
                if now - value[0] < self._rules[key[0]].window
                or self._concurrency.get(key, 0) > 0
            }
            next_concurrency = dict(self._concurrency)
            for dimension, value in keys:
                rule = self._rules[dimension]
                key = (dimension, value)
                started, count = next_requests.get(key, (now, 0))
                if now - started >= rule.window:
                    started, count = now, 0
                if count >= rule.requests:
                    raise SecurityViolation(f"{dimension} request limit exceeded")
                if next_concurrency.get(key, 0) >= rule.concurrency:
                    raise SecurityViolation(f"{dimension} concurrency limit exceeded")
                next_requests[key] = (started, count + 1)
                next_concurrency[key] = next_concurrency.get(key, 0) + 1
            self._requests = next_requests
            self._concurrency = next_concurrency
        return _IngressLease(self, keys)

    def _release(self, keys: tuple[tuple[str, str], ...]) -> None:
        with self._lock:
            updated = dict(self._concurrency)
            for key in keys:
                remaining = updated.get(key, 0) - 1
                if remaining > 0:
                    updated[key] = remaining
                else:
                    updated.pop(key, None)
            self._concurrency = updated


class IngressGuard:
    def __init__(self, authenticator: WebhookAuthenticator, limiter: HierarchicalIngressLimiter):
        self._authenticator = authenticator
        self._limiter = limiter

    def process(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        context: IngressContext,
        parser: Callable[[bytes], Any],
        now: datetime,
    ) -> Any:
        with self._limiter.acquire(context, ("global", "ip", "adapter")):
            verified = self._authenticator.authenticate(raw_body, headers, now)
            if verified.account_id != context.account:
                raise SecurityViolation("authenticated account mismatch")
            with self._limiter.acquire(context, ("account",)):
                verified.claim_nonce()
                return parser(raw_body)


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    queue_depth: int = 0
    database_bytes: int = 0
    disk_free_bytes: int = 2**63 - 1
    attachment_bytes: int = 0
    conversation_agents: int = 0

    def __post_init__(self) -> None:
        for name in (
            "queue_depth",
            "database_bytes",
            "disk_free_bytes",
            "attachment_bytes",
            "conversation_agents",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


class QuotaLedger(Protocol):
    def try_reserve(
        self,
        policy: "ResourceQuotaPolicy",
        request: QuotaSnapshot,
        conversation_id: str,
    ) -> str | None: ...

    def release(self, token: str) -> None: ...


class QuotaLease:
    def __init__(self, ledger: QuotaLedger, token: str) -> None:
        self._ledger = ledger
        self._token = token
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if not self._released:
                self._ledger.release(self._token)
                self._released = True

    def __enter__(self) -> "QuotaLease":
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class ResourceQuotaPolicy:
    max_queue_depth: int
    max_database_bytes: int
    min_disk_free_bytes: int
    max_attachment_bytes: int
    max_agents_per_conversation: int

    def __post_init__(self) -> None:
        for name in (
            "max_queue_depth",
            "max_database_bytes",
            "min_disk_free_bytes",
            "max_attachment_bytes",
            "max_agents_per_conversation",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def validate(self, snapshot: QuotaSnapshot) -> None:
        checks = (
            (snapshot.queue_depth <= self.max_queue_depth, "queue quota exceeded"),
            (snapshot.database_bytes <= self.max_database_bytes, "database quota exceeded"),
            (snapshot.disk_free_bytes >= self.min_disk_free_bytes, "disk quota exceeded"),
            (snapshot.attachment_bytes <= self.max_attachment_bytes, "attachment quota exceeded"),
            (
                snapshot.conversation_agents <= self.max_agents_per_conversation,
                "per-conversation Agent quota exceeded",
            ),
        )
        for allowed, message in checks:
            if not allowed:
                raise SecurityViolation(message)

    def reserve(
        self,
        ledger: QuotaLedger,
        request: QuotaSnapshot,
        *,
        conversation_id: str,
    ) -> QuotaLease:
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("conversation_id must be a non-empty string")
        self.validate(request)
        try:
            token = ledger.try_reserve(self, request, conversation_id)
        except Exception as exc:
            raise SecurityViolation("quota ledger unavailable") from exc
        if not isinstance(token, str) or not token:
            raise SecurityViolation("quota reservation denied")
        return QuotaLease(ledger, token)

@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    url: str
    host: str
    addresses: tuple[str, ...]


class OutboundUrlPolicy:
    def __init__(
        self,
        *,
        allowed_hosts: Iterable[str],
        resolver: Callable[[str], Iterable[str]],
    ) -> None:
        self._allowed_hosts = frozenset(host.lower().rstrip(".") for host in allowed_hosts)
        if not self._allowed_hosts:
            raise ValueError("allowed_hosts cannot be empty")
        self._resolver = resolver

    def validate(self, url: str) -> ValidatedUrl:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise SecurityViolation("invalid outbound URL") from exc
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not host:
            raise SecurityViolation("outbound URL must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise SecurityViolation("outbound URL credentials are forbidden")
        if port not in (None, 443):
            raise SecurityViolation("outbound URL port is forbidden")
        if host not in self._allowed_hosts:
            raise SecurityViolation("outbound URL host is not allowlisted")
        try:
            addresses = tuple(dict.fromkeys(str(value) for value in self._resolver(host)))
        except Exception as exc:
            raise SecurityViolation("outbound DNS resolution failed") from exc
        if not addresses:
            raise SecurityViolation("outbound DNS returned no addresses")
        for address in addresses:
            self._validate_address(address)
        return ValidatedUrl(url=url, host=host, addresses=addresses)

    def validate_redirect(self, previous: ValidatedUrl, redirect_url: str) -> ValidatedUrl:
        del previous
        return self.validate(redirect_url)

    def validate_peer(self, validated: ValidatedUrl, peer_address: str) -> None:
        self._validate_address(peer_address)
        if peer_address not in validated.addresses:
            raise SecurityViolation("DNS rebinding detected")

    @staticmethod
    def _validate_address(address: str) -> None:
        try:
            value = ipaddress.ip_address(address)
        except ValueError as exc:
            raise SecurityViolation("DNS returned an invalid address") from exc
        if not value.is_global:
            raise SecurityViolation("outbound address is not globally routable")


class AttachmentChunkStream(Protocol):
    """Transport stream that must honor the supplied absolute deadline."""

    def read(self, max_bytes: int, deadline: float) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class AttachmentUpload:
    filename: str
    claimed_content_type: str
    chunks: AttachmentChunkStream


@dataclass(frozen=True, slots=True)
class AttachmentPolicy:
    max_count: int
    max_aggregate_bytes: int
    max_decompressed_bytes: int
    max_compression_ratio: float
    max_stream_seconds: float
    retention: timedelta
    max_archive_entries: int = 1000

    def __post_init__(self) -> None:
        for value, name in (
            (self.max_count, "max_count"),
            (self.max_aggregate_bytes, "max_aggregate_bytes"),
            (self.max_decompressed_bytes, "max_decompressed_bytes"),
            (self.max_archive_entries, "max_archive_entries"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for value, name in (
            (self.max_compression_ratio, "max_compression_ratio"),
            (self.max_stream_seconds, "max_stream_seconds"),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if self.retention <= timedelta(0):
            raise ValueError("retention must be positive")


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    storage_path: str
    size: int
    expires_at: datetime


class AttachmentStorage(Protocol):
    def put_batch(
        self, entries: tuple[tuple[str, bytes, datetime, bool], ...]
    ) -> bool:
        """Exclusively create every entry atomically; false must leave none."""
        ...

    def cleanup_expired(self, now: datetime) -> int: ...


class AttachmentScanner(Protocol):
    def scan(self, content: bytes) -> bool: ...


class AttachmentGuard:
    MAGIC = {
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/jpeg": (b"\xff\xd8\xff",),
        "application/pdf": (b"%PDF-",),
        "application/zip": (b"PK\x03\x04",),
    }

    def __init__(
        self,
        policy: AttachmentPolicy,
        storage: AttachmentStorage,
        scanner: AttachmentScanner,
        *,
        now: Callable[[], datetime],
        monotonic: Callable[[], float],
        random_name: Callable[[], str],
    ) -> None:
        self._policy = policy
        self._storage = storage
        self._scanner = scanner
        self._now = now
        self._monotonic = monotonic
        self._random_name = random_name

    def ingest(self, uploads: Iterable[AttachmentUpload]) -> tuple[StoredAttachment, ...]:
        items: list[AttachmentUpload] = []
        for item in uploads:
            items.append(item)
            if len(items) > self._policy.max_count:
                raise SecurityViolation("attachment count limit exceeded")
        prepared: list[tuple[AttachmentUpload, bytes]] = []
        aggregate = 0
        aggregate_decompressed = 0
        for item in items:
            content = self._read_stream(item, self._policy.max_aggregate_bytes - aggregate)
            aggregate += len(content)
            decompressed = self._inspect_content(
                item.claimed_content_type,
                content,
                self._policy.max_decompressed_bytes - aggregate_decompressed,
            )
            aggregate_decompressed += decompressed
            if aggregate_decompressed > self._policy.max_decompressed_bytes:
                raise SecurityViolation("attachment decompressed size limit exceeded")
            if decompressed > max(1, len(content)) * self._policy.max_compression_ratio:
                raise SecurityViolation("attachment archive bomb detected")
            signatures = self.MAGIC.get(item.claimed_content_type)
            if signatures is None or not any(content.startswith(signature) for signature in signatures):
                raise SecurityViolation("attachment magic-byte mismatch")
            prepared.append((item, content))

        for _, content in prepared:
            try:
                clean = self._scanner.scan(content)
            except Exception as exc:
                raise SecurityViolation("attachment scanner unavailable") from exc
            if clean is not True:
                raise SecurityViolation("attachment malware detected")

        now = self._now()
        _require_aware(now)
        expires_at = now + self._policy.retention
        results = []
        writes: list[tuple[str, bytes, datetime, bool]] = []
        used_paths: set[str] = set()
        for _, content in prepared:
            path = f"quarantine/{self._random_name()}"
            token = path.removeprefix("quarantine/")
            if (
                path in used_paths
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token)
            ):
                raise SecurityViolation("unsafe attachment storage name")
            used_paths.add(path)
            writes.append((path, content, expires_at, False))
            results.append(StoredAttachment(path, len(content), expires_at))
        try:
            created = self._storage.put_batch(tuple(writes))
        except Exception as exc:
            raise SecurityViolation("attachment storage unavailable") from exc
        if created is not True:
            raise SecurityViolation("attachment storage collision")
        return tuple(results)

    def cleanup_expired(self) -> int:
        now = self._now()
        _require_aware(now)
        try:
            return self._storage.cleanup_expired(now)
        except Exception as exc:
            raise SecurityViolation("attachment cleanup unavailable") from exc

    def _read_stream(self, item: AttachmentUpload, remaining_bytes: int) -> bytes:
        started = self._monotonic()
        if not math.isfinite(started):
            raise SecurityViolation("attachment stream clock is invalid")
        deadline = started + self._policy.max_stream_seconds
        content = bytearray()
        while True:
            try:
                chunk = item.chunks.read(remaining_bytes - len(content) + 1, deadline)
            except TimeoutError as exc:
                raise SecurityViolation("attachment stream-time limit exceeded") from exc
            except Exception as exc:
                raise SecurityViolation("attachment stream unavailable") from exc
            observed_at = self._monotonic()
            if (
                not math.isfinite(observed_at)
                or observed_at < started
                or observed_at > deadline
            ):
                raise SecurityViolation("attachment stream-time limit exceeded")
            if chunk is None:
                break
            if not isinstance(chunk, bytes):
                raise SecurityViolation("attachment stream returned non-bytes")
            if len(content) + len(chunk) > remaining_bytes:
                raise SecurityViolation("attachment aggregate size limit exceeded")
            content.extend(chunk)
        if not content:
            raise SecurityViolation("empty attachment")
        return bytes(content)

    def _inspect_content(
        self, content_type: str, content: bytes, remaining_decompressed: int
    ) -> int:
        if content_type != "application/zip":
            return len(content)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > self._policy.max_archive_entries:
                    raise SecurityViolation("attachment archive entry limit exceeded")
                return self._inspect_zip_entries(
                    archive, entries, len(content), remaining_decompressed
                )
        except (OSError, zipfile.BadZipFile) as exc:
            raise SecurityViolation("invalid attachment archive") from exc

    def _inspect_zip_entries(
        self,
        archive: zipfile.ZipFile,
        entries: list[zipfile.ZipInfo],
        compressed_bytes: int,
        decompressed_budget: int,
    ) -> int:
        decompressed = 0
        started = self._monotonic()
        deadline = started + self._policy.max_stream_seconds
        for entry in entries:
            normalized = entry.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            mode = entry.external_attr >> 16
            if (
                stat.S_ISLNK(mode)
                or path.is_absolute()
                or ".." in path.parts
                or re.match(r"^[A-Za-z]:", normalized)
                or any(ord(character) < 32 for character in normalized)
            ):
                raise SecurityViolation("unsafe attachment archive entry")
            if entry.is_dir():
                continue
            if entry.flag_bits & 0x1:
                raise SecurityViolation("encrypted attachment archives are forbidden")
            entry_size = 0
            try:
                with archive.open(entry) as source:
                    while True:
                        remaining = decompressed_budget - decompressed
                        chunk = source.read(min(65536, remaining + 1))
                        observed_at = self._monotonic()
                        if (
                            not math.isfinite(observed_at)
                            or observed_at < started
                            or observed_at > deadline
                        ):
                            raise SecurityViolation("attachment stream-time limit exceeded")
                        if not chunk:
                            break
                        entry_size += len(chunk)
                        decompressed += len(chunk)
                        if decompressed > decompressed_budget:
                            raise SecurityViolation("attachment decompressed size limit exceeded")
                        if decompressed > max(1, compressed_bytes) * self._policy.max_compression_ratio:
                            raise SecurityViolation("attachment archive bomb detected")
            except SecurityViolation:
                raise
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise SecurityViolation("invalid attachment archive") from exc
            if entry_size != entry.file_size:
                raise SecurityViolation("invalid attachment archive size metadata")
        return decompressed


class ToolApprovalGuard:
    def authorize(
        self,
        *,
        requires_approval: bool,
        approved_by_control_plane: bool,
        ingress_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        del ingress_metadata
        if not isinstance(requires_approval, bool) or not isinstance(
            approved_by_control_plane, bool
        ):
            raise TypeError("tool approval policy inputs must be boolean")
        if requires_approval and approved_by_control_plane is not True:
            raise SecurityViolation("tool approval required")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("time must be timezone-aware")
