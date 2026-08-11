"""Bounded, audited retention for durable runtime sensitive data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import errno
import hashlib
from math import isfinite
import os
from pathlib import Path, PureWindowsPath
import stat
import time
from typing import Callable

from .repository import (
    DurableRuntimeRepository,
    RetentionAttachmentClaim,
    StaleClaimError,
    StateConflictError,
)


def snapshot_managed_attachment(
    attachment_root: str | Path, storage_path: str
) -> str:
    """Bind a source manifest to the exact object present at durable ingest."""
    root = Path(attachment_root)
    if not root.exists() or not root.is_dir():
        raise StateConflictError("retention attachment root is unavailable")
    managed_root = root.resolve(strict=True)
    relative = RetentionWorker._managed_relative_path(storage_path)
    if relative is None:
        return "rejected"
    if os.name == "nt":
        return _snapshot_windows_attachment(managed_root, managed_root.joinpath(relative))
    return _snapshot_posix_attachment(managed_root, relative)  # pragma: no cover - POSIX


def _snapshot_posix_attachment(  # pragma: no cover - POSIX
    attachment_root: Path, relative: Path
) -> str:
    descriptors: list[int] = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors.append(os.open(attachment_root, flags))
        for part in relative.parts[:-1]:
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        file_fd = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=descriptors[-1],
        )
        descriptors.append(file_fd)
        opened_stat = os.fstat(file_fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            return "rejected"
        return RetentionWorker._posix_file_identity(opened_stat)
    except FileNotFoundError:
        return "missing"
    except (NotADirectoryError, IsADirectoryError):
        return "rejected"
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return "rejected"
        raise StateConflictError(
            "retention attachment identity snapshot failed"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _snapshot_windows_attachment(attachment_root: Path, candidate: Path) -> str:
    import pywintypes
    import win32con
    import win32file

    try:
        handle = win32file.CreateFile(
            str(candidate),
            0x0080,  # FILE_READ_ATTRIBUTES
            win32file.FILE_SHARE_READ
            | win32file.FILE_SHARE_WRITE
            | win32file.FILE_SHARE_DELETE,
            None,
            win32file.OPEN_EXISTING,
            win32file.FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
    except pywintypes.error as exc:
        if exc.winerror in {2, 3}:
            return "missing"
        raise StateConflictError(
            "retention attachment identity snapshot failed"
        ) from exc
    try:
        information = win32file.GetFileInformationByHandle(handle)
        attributes = information[0]
        if attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
            return "rejected"
        if attributes & win32con.FILE_ATTRIBUTE_DIRECTORY:
            return "rejected"
        final_path = RetentionWorker._normalize_windows_handle_path(
            win32file.GetFinalPathNameByHandle(handle, 0)
        )
        root_value = os.path.normcase(str(attachment_root))
        try:
            common_path = os.path.commonpath(
                (root_value, os.path.normcase(final_path))
            )
        except ValueError:
            return "rejected"
        if common_path != root_value:
            return "rejected"
        return RetentionWorker._windows_file_identity(information)
    finally:
        handle.Close()


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    inbox_payload_ttl: timedelta
    outbox_delivery_ttl: timedelta
    audit_ttl: timedelta
    batch_limit: int = 100
    attachment_max_attempts: int = 5

    def __post_init__(self) -> None:
        for name in (
            "inbox_payload_ttl",
            "outbox_delivery_ttl",
            "audit_ttl",
        ):
            value = getattr(self, name)
            if not isinstance(value, timedelta):
                raise TypeError(f"{name} must be a timedelta")
            if value <= timedelta(0):
                raise ValueError(f"{name} must be positive")
        if (
            isinstance(self.batch_limit, bool)
            or not isinstance(self.batch_limit, int)
            or not 1 <= self.batch_limit <= 1000
        ):
            raise ValueError("batch_limit must be an integer between 1 and 1000")
        if (
            isinstance(self.attachment_max_attempts, bool)
            or not isinstance(self.attachment_max_attempts, int)
            or not 1 <= self.attachment_max_attempts <= 100
        ):
            raise ValueError(
                "attachment_max_attempts must be an integer between 1 and 100"
            )


@dataclass(frozen=True, slots=True)
class RetentionSummary:
    inbox_redacted: int = 0
    outbox_redacted: int = 0
    audit_deleted: int = 0
    attachments_deleted: int = 0
    attachments_rejected: int = 0
    attachments_failed: int = 0
    attachments_stale: int = 0
    attachments_fenced: int = 0
    attachments_no_op: int = 0

    @property
    def records_processed(self) -> int:
        return self.inbox_redacted + self.outbox_redacted + self.audit_deleted


class RetentionWorker:
    """Runs one bounded database batch and deletes only managed attachment files."""

    def __init__(
        self,
        repository: DurableRuntimeRepository,
        policy: RetentionPolicy,
        attachment_root: str | Path,
        *,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy
        root = Path(attachment_root)
        if not root.exists() or not root.is_dir():
            raise ValueError("attachment_root must be an existing directory")
        self._attachment_root = root.resolve(strict=True)
        self._monotonic = monotonic or time.monotonic
        self._private_deletion_root: Path | None = None
        if os.name != "nt":  # pragma: no cover - POSIX
            self._private_deletion_root = self._prepare_posix_deletion_root()

    def run_once(self, now: datetime) -> RetentionSummary:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        started = self._monotonic()
        if not isfinite(started):
            raise ValueError("retention monotonic clock must be finite")

        def operation_now() -> datetime:
            current = self._monotonic()
            elapsed = current - started
            if not isfinite(current) or not isfinite(elapsed) or elapsed < 0:
                raise StateConflictError("retention monotonic clock is invalid")
            return now + timedelta(seconds=elapsed)

        batch = self._repository.apply_retention_batch(
            now=now,
            inbox_before=now - self._policy.inbox_payload_ttl,
            outbox_before=now - self._policy.outbox_delivery_ttl,
            audit_before=now - self._policy.audit_ttl,
            limit=self._policy.batch_limit,
        )
        outcomes: dict[RetentionAttachmentClaim, str] = {}
        for claim in batch["attachment_claims"]:
            outcomes[claim] = self._delete_managed_attachment(claim, operation_now)
        completion = self._repository.complete_retention_attachments(
            outcomes,
            now=operation_now(),
            max_attempts=self._policy.attachment_max_attempts,
        )
        self._repository.secure_checkpoint()
        return RetentionSummary(
            inbox_redacted=batch["inbox_redacted"],
            outbox_redacted=batch["outbox_redacted"],
            audit_deleted=batch["audit_deleted"],
            attachments_deleted=completion["deleted"],
            attachments_rejected=completion["rejected"],
            attachments_failed=completion["failed"],
            attachments_stale=completion["stale"],
            attachments_fenced=completion["fenced"],
            attachments_no_op=completion["no_op"],
        )

    def _delete_managed_attachment(
        self,
        claim: RetentionAttachmentClaim,
        operation_now: datetime | Callable[[], datetime],
    ) -> str:
        if not isinstance(claim, RetentionAttachmentClaim):
            return "rejected"
        if not callable(operation_now) and (
            operation_now.tzinfo is None or operation_now.utcoffset() is None
        ):
            return "rejected"
        storage_path = claim.storage_path
        if not isinstance(storage_path, str) or not storage_path:
            return "rejected"
        relative = Path(storage_path)
        windows_path = PureWindowsPath(storage_path)
        if (
            relative.is_absolute()
            or relative.anchor
            or windows_path.is_absolute()
            or windows_path.drive
            or windows_path.root
            or ".." in windows_path.parts
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            return "rejected"
        candidate = self._attachment_root.joinpath(relative)
        if os.name == "nt":
            return self._delete_windows_handle(candidate, claim, operation_now)
        return self._delete_posix_handle(relative, claim, operation_now)

    def _snapshot_managed_attachment(self, storage_path: str) -> str:
        """Capture the object version before a filesystem claim is exposed."""
        return snapshot_managed_attachment(self._attachment_root, storage_path)

    @staticmethod
    def _managed_relative_path(storage_path: str) -> Path | None:
        if not isinstance(storage_path, str) or not storage_path:
            return None
        relative = Path(storage_path)
        windows_path = PureWindowsPath(storage_path)
        if (
            relative.is_absolute()
            or relative.anchor
            or windows_path.is_absolute()
            or windows_path.drive
            or windows_path.root
            or ".." in windows_path.parts
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            return None
        return relative

    @staticmethod
    def _resolve_operation_now(
        operation_now: datetime | Callable[[], datetime],
    ) -> datetime:
        value = operation_now() if callable(operation_now) else operation_now
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operation time must be timezone-aware")
        return value

    def _prepare_posix_deletion_root(self) -> Path:  # pragma: no cover - POSIX
        root_stat = os.stat(self._attachment_root, follow_symlinks=False)
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_IMODE(root_stat.st_mode) & 0o022:
            raise ValueError("attachment_root must not be group/world writable")
        private_root = self._attachment_root / ".retention-delete"
        try:
            os.mkdir(private_root, 0o700)
        except FileExistsError:
            pass
        private_stat = os.stat(private_root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(private_stat.st_mode)
            or stat.S_IMODE(private_stat.st_mode) != 0o700
        ):
            raise ValueError("retention private deletion root is not secure")
        return private_root

    @staticmethod
    def _posix_deletion_slot(claim: RetentionAttachmentClaim) -> str:
        material = "\0".join(
            (
                claim.work_id,
                claim.generation,
                str(claim.claim_generation),
                claim.claim_token,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _delete_posix_handle(  # pragma: no cover - POSIX
        self,
        relative: Path,
        claim: RetentionAttachmentClaim,
        operation_now: datetime | Callable[[], datetime],
    ) -> str:
        """Move into a worker-private quarantine before identity-checked unlink."""
        descriptors: list[int] = []
        authorized = False
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptors.append(os.open(self._attachment_root, flags))
            parts = relative.parts
            for part in parts[:-1]:
                descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
            file_fd = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptors[-1]
            )
            descriptors.append(file_fd)
            opened_stat = os.fstat(file_fd)
            if not stat.S_ISREG(opened_stat.st_mode):
                return "rejected" if claim.file_identity == "rejected" else "failed"
            identity = self._posix_file_identity(opened_stat)
            if identity != claim.file_identity:
                return "failed"
            self._repository.authorize_retention_attachment_deletion(
                claim,
                identity,
                now=self._resolve_operation_now(operation_now),
            )
            authorized = True
            if self._posix_file_identity(os.fstat(file_fd)) != identity:
                return "fenced"
            if self._private_deletion_root is None:
                return "fenced"
            private_fd = os.open(self._private_deletion_root, flags)
            descriptors.append(private_fd)
            slot = self._posix_deletion_slot(claim)
            placeholder_fd = os.open(
                slot,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=private_fd,
            )
            os.close(placeholder_fd)
            os.rename(
                parts[-1],
                slot,
                src_dir_fd=descriptors[-3],
                dst_dir_fd=private_fd,
            )
            quarantined_fd = os.open(
                slot, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=private_fd
            )
            descriptors.append(quarantined_fd)
            held_identity = self._posix_file_identity(os.fstat(file_fd))
            quarantined_identity = self._posix_file_identity(
                os.fstat(quarantined_fd)
            )
            if quarantined_identity != held_identity:
                return "fenced"
            os.unlink(slot, dir_fd=private_fd)
            return "deleted"
        except StaleClaimError:
            return "stale"
        except StateConflictError:
            return "fenced" if authorized else "failed"
        except FileNotFoundError:
            if authorized:
                return "fenced"
            return "missing" if claim.file_identity == "missing" else "failed"
        except (NotADirectoryError, IsADirectoryError):
            if authorized:
                return "fenced"
            return "rejected" if claim.file_identity == "rejected" else "failed"
        except OSError as exc:
            if authorized:
                return "fenced"
            if exc.errno == errno.ELOOP and claim.file_identity == "rejected":
                return "rejected"
            return "failed"
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _delete_windows_handle(
        self,
        candidate: Path,
        claim: RetentionAttachmentClaim,
        operation_now: datetime | Callable[[], datetime],
    ) -> str:
        """Delete the verified opened object, not a path that can be swapped after check."""
        import pywintypes
        import win32con
        import win32file

        authorized = False
        try:
            handle = win32file.CreateFile(
                str(candidate),
                win32con.DELETE | 0x0080,  # FILE_READ_ATTRIBUTES
                win32file.FILE_SHARE_READ
                | win32file.FILE_SHARE_DELETE,
                None,
                win32file.OPEN_EXISTING,
                win32file.FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            )
        except pywintypes.error as exc:
            if exc.winerror in {2, 3}:
                return "missing" if claim.file_identity == "missing" else "failed"
            return "failed"
        try:
            information = win32file.GetFileInformationByHandle(handle)
            attributes = information[0]
            if attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
                return "rejected" if claim.file_identity == "rejected" else "failed"
            if attributes & win32con.FILE_ATTRIBUTE_DIRECTORY:
                return "rejected" if claim.file_identity == "rejected" else "failed"
            final_path = self._normalize_windows_handle_path(
                win32file.GetFinalPathNameByHandle(handle, 0)
            )
            managed_root = os.path.normcase(str(self._attachment_root))
            try:
                common_path = os.path.commonpath(
                    (managed_root, os.path.normcase(final_path))
                )
            except ValueError:
                return "rejected"
            if common_path != managed_root:
                return "rejected"
            identity = self._windows_file_identity(information)
            if identity != claim.file_identity:
                return "failed"
            self._repository.authorize_retention_attachment_deletion(
                claim,
                identity,
                now=self._resolve_operation_now(operation_now),
            )
            authorized = True
            if (
                self._windows_file_identity(
                    win32file.GetFileInformationByHandle(handle)
                )
                != identity
            ):
                return "fenced"
            win32file.SetFileInformationByHandle(
                handle, win32file.FileDispositionInfo, True
            )
            return "deleted"
        except StaleClaimError:
            return "stale"
        except StateConflictError:
            return "fenced" if authorized else "failed"
        except (OSError, pywintypes.error, ValueError):
            return "fenced" if authorized else "failed"
        finally:
            handle.Close()

    @staticmethod
    def _normalize_windows_handle_path(path: str) -> str:
        if path.startswith("\\\\?\\UNC\\"):
            return "\\\\" + path[8:]
        if path.startswith("\\\\?\\"):
            return path[4:]
        return path

    @staticmethod
    def _posix_file_identity(value: os.stat_result) -> str:
        return "posix:{}:{}:{}:{}:{}".format(
            value.st_dev,
            value.st_ino,
            value.st_ctime_ns,
            value.st_mtime_ns,
            value.st_size,
        )

    @staticmethod
    def _windows_file_identity(information: tuple) -> str:
        creation_time = information[1]
        last_write = information[3]
        creation_timestamp = getattr(creation_time, "timestamp", None)
        timestamp = getattr(last_write, "timestamp", None)
        creation_version = (
            str(int(creation_timestamp() * 1_000_000_000))
            if callable(creation_timestamp)
            else str(creation_time)
        )
        write_version = (
            str(int(timestamp() * 1_000_000_000))
            if callable(timestamp)
            else str(last_write)
        )
        return "windows:{}:{}:{}:{}:{}:{}:{}".format(
            information[4],
            information[8],
            information[9],
            information[5],
            information[6],
            creation_version,
            write_version,
        )
