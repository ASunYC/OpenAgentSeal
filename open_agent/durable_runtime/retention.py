"""Bounded, audited retention for durable runtime sensitive data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import errno
import os
from pathlib import Path, PureWindowsPath
import stat

from .repository import DurableRuntimeRepository


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    inbox_payload_ttl: timedelta
    outbox_delivery_ttl: timedelta
    audit_ttl: timedelta
    batch_limit: int = 100

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


@dataclass(frozen=True, slots=True)
class RetentionSummary:
    inbox_redacted: int = 0
    outbox_redacted: int = 0
    audit_deleted: int = 0
    attachments_deleted: int = 0
    attachments_rejected: int = 0
    attachments_failed: int = 0

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
    ) -> None:
        self._repository = repository
        self._policy = policy
        root = Path(attachment_root)
        if not root.exists() or not root.is_dir():
            raise ValueError("attachment_root must be an existing directory")
        self._attachment_root = root.resolve(strict=True)

    def run_once(self, now: datetime) -> RetentionSummary:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        batch = self._repository.apply_retention_batch(
            now=now,
            inbox_before=now - self._policy.inbox_payload_ttl,
            outbox_before=now - self._policy.outbox_delivery_ttl,
            audit_before=now - self._policy.audit_ttl,
            limit=self._policy.batch_limit,
        )
        deleted = 0
        rejected = 0
        failed = 0
        outcomes: dict[str, str] = {}
        for storage_path in batch["attachment_paths"]:
            outcome = self._delete_managed_attachment(storage_path)
            outcomes[storage_path] = outcome
            if outcome == "deleted":
                deleted += 1
            elif outcome == "rejected":
                rejected += 1
            elif outcome == "failed":
                failed += 1
        self._repository.complete_retention_attachments(outcomes, now=now)
        self._repository.secure_checkpoint()
        return RetentionSummary(
            inbox_redacted=batch["inbox_redacted"],
            outbox_redacted=batch["outbox_redacted"],
            audit_deleted=batch["audit_deleted"],
            attachments_deleted=deleted,
            attachments_rejected=rejected,
            attachments_failed=failed,
        )

    def _delete_managed_attachment(self, storage_path: str) -> str:
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
            return self._delete_windows_handle(candidate)
        return self._delete_posix_handle(relative)

    def _delete_posix_handle(self, relative: Path) -> str:  # pragma: no cover - POSIX
        """Traverse beneath the managed root with non-following directory handles."""
        descriptors: list[int] = []
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
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                return "rejected"
            os.unlink(parts[-1], dir_fd=descriptors[-2])
            return "deleted"
        except FileNotFoundError:
            return "missing"
        except (NotADirectoryError, IsADirectoryError):
            return "rejected"
        except OSError as exc:
            return "rejected" if exc.errno == errno.ELOOP else "failed"
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _delete_windows_handle(self, candidate: Path) -> str:
        """Delete the verified opened object, not a path that can be swapped after check."""
        import pywintypes
        import win32con
        import win32file

        try:
            handle = win32file.CreateFile(
                str(candidate),
                win32con.DELETE | 0x0080,  # FILE_READ_ATTRIBUTES
                win32file.FILE_SHARE_READ
                | win32file.FILE_SHARE_WRITE
                | win32file.FILE_SHARE_DELETE,
                None,
                win32file.OPEN_EXISTING,
                win32file.FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            )
        except pywintypes.error as exc:
            return "missing" if exc.winerror in {2, 3} else "failed"
        try:
            information = win32file.GetFileInformationByHandle(handle)
            attributes = information[0]
            if attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
                return "rejected"
            if attributes & win32con.FILE_ATTRIBUTE_DIRECTORY:
                return "rejected"
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
            win32file.SetFileInformationByHandle(
                handle, win32file.FileDispositionInfo, True
            )
            return "deleted"
        except (OSError, pywintypes.error, ValueError):
            return "failed"
        finally:
            handle.Close()

    @staticmethod
    def _normalize_windows_handle_path(path: str) -> str:
        if path.startswith("\\\\?\\UNC\\"):
            return "\\\\" + path[8:]
        if path.startswith("\\\\?\\"):
            return path[4:]
        return path
