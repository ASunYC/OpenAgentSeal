"""Secret storage separated from the durable SQLite runtime database."""

from __future__ import annotations

import asyncio
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from open_agent.durable_runtime.repository import DurableRuntimeRepository


_REFERENCE_PATTERN = re.compile(r"\Aoas-cred:[0-9a-f]{32}\Z")


class CredentialError(RuntimeError):
    """Base error that deliberately omits credential values and references."""


class CredentialNotFoundError(CredentialError):
    """The opaque reference does not identify an available credential."""


class RevokedCredentialError(CredentialError):
    """The credential exists but has been revoked."""


class CredentialScopeError(CredentialError):
    """The credential belongs to a different channel account."""


@dataclass(frozen=True, slots=True)
class StoredCredential:
    account_id: str
    secret: str
    revoked: bool = False

    def __repr__(self) -> str:
        return (
            "StoredCredential(account_id='<redacted>', secret='<redacted>', "
            f"revoked={self.revoked!r})"
        )


class CredentialBackend(Protocol):
    """Blocking backend contract; async callers use ``CredentialStore`` helpers."""

    def put(self, target_name: str, credential: StoredCredential) -> None: ...

    def resolve(self, target_name: str) -> StoredCredential: ...

    def delete(self, target_name: str) -> None: ...


class MemoryCredentialBackend:
    """Process-local backend intended only for tests."""

    def __init__(self) -> None:
        self._credentials: dict[str, StoredCredential] = {}
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"MemoryCredentialBackend(records={len(self._credentials)})"

    def put(self, target_name: str, credential: StoredCredential) -> None:
        with self._lock:
            self._credentials = {**self._credentials, target_name: credential}

    def resolve(self, target_name: str) -> StoredCredential:
        with self._lock:
            credential = self._credentials.get(target_name)
        if credential is None:
            raise CredentialNotFoundError("credential not found")
        return credential

    def delete(self, target_name: str) -> None:
        with self._lock:
            if target_name not in self._credentials:
                raise CredentialNotFoundError("credential not found")
            self._credentials = {
                key: value for key, value in self._credentials.items() if key != target_name
            }


class WindowsCredentialBackend:
    """Current-user Windows Credential Manager generic-credential backend."""

    def __init__(
        self,
        *,
        target_prefix: str = "OpenAgentSeal/",
        win32cred_module: Any | None = None,
    ) -> None:
        if not isinstance(target_prefix, str) or not target_prefix:
            raise ValueError("target_prefix must be a non-empty string")
        if win32cred_module is None:
            try:
                import win32cred as win32cred_module  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError("Windows Credential Manager support is unavailable") from exc
        self._api = win32cred_module
        self._target_prefix = target_prefix
        backend_errors: list[type[BaseException]] = [OSError]
        try:
            import pywintypes

            backend_errors.append(pywintypes.error)
        except ImportError:
            pass
        self._backend_errors = tuple(backend_errors)

    def __repr__(self) -> str:
        return f"WindowsCredentialBackend(target_prefix={self._target_prefix!r})"

    def put(self, target_name: str, credential: StoredCredential) -> None:
        payload = {
            "Type": self._api.CRED_TYPE_GENERIC,
            "TargetName": self._target(target_name),
            "CredentialBlob": "" if credential.revoked else credential.secret,
            "Persist": self._api.CRED_PERSIST_ENTERPRISE,
            "UserName": credential.account_id,
            "Comment": "revoked" if credential.revoked else "active",
        }
        try:
            self._api.CredWrite(payload, 0)
        except self._backend_errors:
            raise CredentialError("credential backend write failed") from None

    def resolve(self, target_name: str) -> StoredCredential:
        try:
            payload = self._api.CredRead(
                self._target(target_name), self._api.CRED_TYPE_GENERIC, 0
            )
        except self._backend_errors:
            raise CredentialNotFoundError("credential not found") from None
        blob = payload.get("CredentialBlob", "")
        if isinstance(blob, bytes):
            blob = blob.decode("utf-16-le").rstrip("\x00")
        if not isinstance(blob, str):
            raise CredentialError("credential backend returned an invalid record")
        account_id = payload.get("UserName")
        if not isinstance(account_id, str) or not account_id:
            raise CredentialError("credential backend returned an invalid record")
        return StoredCredential(
            account_id=account_id,
            secret=blob,
            revoked=payload.get("Comment") == "revoked",
        )

    def delete(self, target_name: str) -> None:
        try:
            self._api.CredDelete(
                self._target(target_name), self._api.CRED_TYPE_GENERIC, 0
            )
        except self._backend_errors:
            raise CredentialNotFoundError("credential not found") from None

    def _target(self, target_name: str) -> str:
        return f"{self._target_prefix}{target_name}"


class CredentialStore:
    """Creates opaque capabilities while keeping secret bytes in a separate backend."""

    def __init__(self, backend: CredentialBackend) -> None:
        self._backend = backend

    def __repr__(self) -> str:
        return f"CredentialStore(backend={self._backend!r})"

    def for_account(self, account_id: str) -> AccountCredentialStore:
        self._validate_account(account_id)
        return AccountCredentialStore(self, account_id)

    def create_retention_hmac_key(self) -> str:
        """Create a protected external key; only its opaque ref belongs in SQLite."""
        return self.put("runtime-retention", secrets.token_hex(32))

    def resolve_retention_hmac_key(self, secret_ref: str) -> bytes:
        encoded = self.resolve_for_account("runtime-retention", secret_ref)
        try:
            key = bytes.fromhex(encoded)
        except ValueError:
            raise CredentialError("retention HMAC credential is invalid") from None
        if len(key) != 32:
            raise CredentialError("retention HMAC credential is invalid")
        return key

    @staticmethod
    def is_reference(value: object) -> bool:
        return isinstance(value, str) and _REFERENCE_PATTERN.fullmatch(value) is not None

    def put(self, account_id: str, secret: str) -> str:
        self._validate_account(account_id)
        self._validate_secret(secret)
        secret_ref = f"oas-cred:{uuid.uuid4().hex}"
        self._backend.put(secret_ref, StoredCredential(account_id, secret))
        return secret_ref

    def resolve(self, secret_ref: str) -> str:
        self._validate_reference(secret_ref)
        credential = self._backend.resolve(secret_ref)
        if credential.revoked:
            raise RevokedCredentialError("credential has been revoked")
        return credential.secret

    def resolve_for_account(self, account_id: str, secret_ref: str) -> str:
        credential = self._resolve_record_for_account(account_id, secret_ref)
        if credential.revoked:
            raise RevokedCredentialError("credential has been revoked")
        return credential.secret

    def rotate_for_account(
        self, account_id: str, secret_ref: str, replacement: str
    ) -> None:
        self._validate_secret(replacement)
        current = self._resolve_record_for_account(account_id, secret_ref)
        self._backend.put(
            secret_ref,
            StoredCredential(account_id=current.account_id, secret=replacement),
        )

    def revoke_for_account(self, account_id: str, secret_ref: str) -> None:
        current = self._resolve_record_for_account(account_id, secret_ref)
        self._backend.put(secret_ref, replace(current, secret="", revoked=True))

    def delete_for_account(self, account_id: str, secret_ref: str) -> None:
        self._resolve_record_for_account(account_id, secret_ref)
        self._backend.delete(secret_ref)

    def rotate(self, secret_ref: str, replacement: str) -> None:
        self._validate_reference(secret_ref)
        self._validate_secret(replacement)
        current = self._backend.resolve(secret_ref)
        self._backend.put(
            secret_ref,
            StoredCredential(account_id=current.account_id, secret=replacement),
        )

    def revoke(self, secret_ref: str) -> None:
        self._validate_reference(secret_ref)
        current = self._backend.resolve(secret_ref)
        self._backend.put(secret_ref, replace(current, secret="", revoked=True))

    def delete(self, secret_ref: str) -> None:
        self._validate_reference(secret_ref)
        self._backend.delete(secret_ref)

    async def put_async(self, account_id: str, secret: str) -> str:
        return await asyncio.to_thread(self.put, account_id, secret)

    async def resolve_async(self, secret_ref: str) -> str:
        return await asyncio.to_thread(self.resolve, secret_ref)

    async def resolve_for_account_async(self, account_id: str, secret_ref: str) -> str:
        return await asyncio.to_thread(self.resolve_for_account, account_id, secret_ref)

    async def rotate_async(self, secret_ref: str, replacement: str) -> None:
        await asyncio.to_thread(self.rotate, secret_ref, replacement)

    async def revoke_async(self, secret_ref: str) -> None:
        await asyncio.to_thread(self.revoke, secret_ref)

    async def delete_async(self, secret_ref: str) -> None:
        await asyncio.to_thread(self.delete, secret_ref)

    async def rotate_for_account_async(
        self, account_id: str, secret_ref: str, replacement: str
    ) -> None:
        await asyncio.to_thread(
            self.rotate_for_account, account_id, secret_ref, replacement
        )

    async def revoke_for_account_async(self, account_id: str, secret_ref: str) -> None:
        await asyncio.to_thread(self.revoke_for_account, account_id, secret_ref)

    async def delete_for_account_async(self, account_id: str, secret_ref: str) -> None:
        await asyncio.to_thread(self.delete_for_account, account_id, secret_ref)

    def migrate_legacy_account(
        self,
        repository: DurableRuntimeRepository,
        account_id: str,
        now: datetime,
    ) -> str:
        """Move one legacy inline value into the backend, then CAS the SQLite reference."""
        account = repository.get_channel_account(account_id)
        if account is None:
            raise CredentialNotFoundError("channel account not found")
        existing = account.get("credential_ref")
        if self.is_reference(existing):
            repository.secure_checkpoint()
            return existing
        if not isinstance(existing, str) or not existing:
            raise CredentialNotFoundError("channel account has no credential")
        migration_identity = f"{repository.control_plane.db_path.resolve()}\0{account_id}"
        secret_ref = f"oas-cred:{uuid.uuid5(uuid.NAMESPACE_URL, migration_identity).hex}"
        migrated = repository.migrate_channel_account_credential(
            account_id=account_id,
            expected_credential=existing,
            credential_ref=secret_ref,
            store_secret=lambda secret: self._backend.put(
                secret_ref, StoredCredential(account_id, secret)
            ),
            now=now,
        )
        if migrated == secret_ref:
            repository.secure_checkpoint()
            return secret_ref
        if self.is_reference(migrated):
            return migrated
        raise CredentialError("credential migration lost its compare-and-set race")

    def _resolve_record_for_account(
        self, account_id: str, secret_ref: str
    ) -> StoredCredential:
        self._validate_account(account_id)
        self._validate_reference(secret_ref)
        credential = self._backend.resolve(secret_ref)
        if credential.account_id != account_id:
            raise CredentialScopeError("credential belongs to another account")
        return credential

    @staticmethod
    def _validate_account(account_id: str) -> None:
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("account_id must be a non-empty string")

    @staticmethod
    def _validate_secret(secret: str) -> None:
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret must be a non-empty string")

    @staticmethod
    def _validate_reference(secret_ref: str) -> None:
        if not CredentialStore.is_reference(secret_ref):
            raise CredentialNotFoundError("credential not found")


class AccountCredentialStore:
    """Production-facing credential capability bound to one channel account."""

    def __init__(self, store: CredentialStore, account_id: str) -> None:
        self._store = store
        self._account_id = account_id

    def __repr__(self) -> str:
        return "AccountCredentialStore(account_id='<redacted>')"

    def put(self, secret: str) -> str:
        return self._store.put(self._account_id, secret)

    def resolve(self, secret_ref: str) -> str:
        return self._store.resolve_for_account(self._account_id, secret_ref)

    def rotate(self, secret_ref: str, replacement: str) -> None:
        self._store.rotate_for_account(self._account_id, secret_ref, replacement)

    def revoke(self, secret_ref: str) -> None:
        self._store.revoke_for_account(self._account_id, secret_ref)

    def delete(self, secret_ref: str) -> None:
        self._store.delete_for_account(self._account_id, secret_ref)

    async def resolve_async(self, secret_ref: str) -> str:
        return await self._store.resolve_for_account_async(self._account_id, secret_ref)

    async def rotate_async(self, secret_ref: str, replacement: str) -> None:
        await self._store.rotate_for_account_async(
            self._account_id, secret_ref, replacement
        )

    async def revoke_async(self, secret_ref: str) -> None:
        await self._store.revoke_for_account_async(self._account_id, secret_ref)

    async def delete_async(self, secret_ref: str) -> None:
        await self._store.delete_for_account_async(self._account_id, secret_ref)
