from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import threading

import pytest

from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import DurableRuntimeRepository
from open_agent.gateway.credentials import (
    CredentialNotFoundError,
    CredentialScopeError,
    CredentialStore,
    MemoryCredentialBackend,
    RevokedCredentialError,
    StoredCredential,
    WindowsCredentialBackend,
)


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)


def seed_legacy_inline_credential(repository, secret="legacy-inline-secret"):
    """Model an existing pre-credential-store row without using the normal API."""
    repository.upsert_channel_account(
        account_id="legacy-account",
        adapter_kind="line",
        default_profile_id=None,
        credential_ref=None,
        now=NOW,
    )
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute(
            "UPDATE channel_accounts SET credential_ref = ? WHERE account_id = ?",
            (secret, "legacy-account"),
        )


def test_sqlite_receives_only_an_opaque_reference_and_backend_owns_secret(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    backend = MemoryCredentialBackend()
    store = CredentialStore(backend)
    secret = "gateway-token-that-must-never-enter-sqlite"
    try:
        secret_ref = store.put("account-a", secret)
        repository.upsert_channel_account(
            account_id="account-a",
            adapter_kind="telegram",
            default_profile_id=None,
            credential_ref=secret_ref,
            now=NOW,
        )

        row = repository.get_channel_account("account-a")
        assert row["credential_ref"] == secret_ref
        assert secret_ref.startswith("oas-cred:")
        assert secret not in secret_ref
        assert store.resolve(secret_ref) == secret
        control_plane.close()
        sqlite_bytes = b"".join(
            path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
        )
        assert secret.encode() not in sqlite_bytes
    finally:
        control_plane.close()


def test_account_scopes_are_separate_and_diagnostics_are_redacted():
    store = CredentialStore(MemoryCredentialBackend())
    first = store.put("account-a", "alpha-secret")
    second = store.put("account-b", "beta-secret")

    assert first != second
    assert store.resolve(first) == "alpha-secret"
    assert store.resolve(second) == "beta-secret"
    assert store.resolve_for_account("account-a", first) == "alpha-secret"
    with pytest.raises(CredentialScopeError):
        store.resolve_for_account("account-a", second)
    assert "alpha-secret" not in repr(store)
    assert "beta-secret" not in repr(store)

    with pytest.raises(CredentialNotFoundError) as missing:
        store.resolve("oas-cred:missing")
    assert "alpha-secret" not in str(missing.value)
    assert "oas-cred:missing" not in str(missing.value)

    diagnostic = repr(StoredCredential("private-account-id", "private-secret"))
    assert "private-account-id" not in diagnostic
    assert "private-secret" not in diagnostic

    bound_a = store.for_account("account-a")
    bound_b = store.for_account("account-b")
    bound_ref = bound_b.put("bound-secret")
    with pytest.raises(CredentialScopeError):
        bound_a.resolve(bound_ref)
    assert bound_b.resolve(bound_ref) == "bound-secret"


def test_retention_hmac_key_provider_keeps_key_behind_an_opaque_reference():
    store = CredentialStore(MemoryCredentialBackend())

    key_ref = store.create_retention_hmac_key()
    key = store.resolve_retention_hmac_key(key_ref)

    assert key_ref.startswith("oas-cred:")
    assert len(key) == 32
    assert key.hex() not in key_ref


def test_rotate_revoke_and_delete_take_effect_immediately():
    store = CredentialStore(MemoryCredentialBackend())
    secret_ref = store.put("account-a", "original")

    store.rotate(secret_ref, "replacement")
    assert store.resolve(secret_ref) == "replacement"

    store.revoke(secret_ref)
    with pytest.raises(RevokedCredentialError):
        store.resolve(secret_ref)

    store.delete(secret_ref)
    with pytest.raises(CredentialNotFoundError):
        store.resolve(secret_ref)


@pytest.mark.parametrize(
    "unsafe_ref",
    ("INLINE-SECRET", "oas-cred:not-a-uuid", "oas-cred:" + "A" * 32),
)
def test_normal_channel_account_upsert_rejects_non_opaque_credentials(
    tmp_path, unsafe_ref
):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    try:
        with pytest.raises(ValueError, match="opaque credential reference"):
            repository.upsert_channel_account(
                account_id="account-a",
                adapter_kind="telegram",
                default_profile_id=None,
                credential_ref=unsafe_ref,
                now=NOW,
            )
        assert repository.get_channel_account("account-a") is None
    finally:
        control_plane.close()


def test_legacy_inline_secret_is_migrated_once_and_replaced_atomically(tmp_path):
    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    store = CredentialStore(MemoryCredentialBackend())
    try:
        seed_legacy_inline_credential(repository)

        first = store.migrate_legacy_account(repository, "legacy-account", NOW)
        second = store.migrate_legacy_account(repository, "legacy-account", NOW)

        assert first == second
        assert first.startswith("oas-cred:")
        assert store.resolve(first) == "legacy-inline-secret"
        assert repository.get_channel_account("legacy-account")["credential_ref"] == first
        assert control_plane._get_conn().execute("PRAGMA secure_delete").fetchone()[0] == 1
        for path in tmp_path.iterdir():
            if path.is_file():
                assert b"legacy-inline-secret" not in path.read_bytes()
    finally:
        control_plane.close()


def test_async_resolution_moves_blocking_backend_work_to_a_thread():
    class ThreadRecordingBackend(MemoryCredentialBackend):
        def __init__(self):
            super().__init__()
            self.resolve_threads: list[int] = []

        def resolve(self, target_name: str):
            import threading

            self.resolve_threads.append(threading.get_ident())
            return super().resolve(target_name)

    backend = ThreadRecordingBackend()
    store = CredentialStore(backend)
    secret_ref = store.put("account-a", "secret")
    caller_thread = threading.get_ident()

    assert asyncio.run(store.resolve_async(secret_ref)) == "secret"
    assert backend.resolve_threads[-1] != caller_thread


def test_concurrent_legacy_migration_cannot_overwrite_a_later_rotation(tmp_path):
    class BlockingBackend(MemoryCredentialBackend):
        def __init__(self):
            super().__init__()
            self.first_put_started = threading.Event()
            self.release_first_put = threading.Event()
            self.put_count = 0

        def put(self, target_name, credential):
            self.put_count += 1
            if self.put_count == 1:
                self.first_put_started.set()
                self.release_first_put.wait(timeout=2)
            return super().put(target_name, credential)

    control_plane = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control_plane)
    backend = BlockingBackend()
    store = CredentialStore(backend)
    seed_legacy_inline_credential(repository)
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                store.migrate_legacy_account(repository, "legacy-account", NOW)
            )
        )
        for _ in range(2)
    ]
    try:
        threads[0].start()
        assert backend.first_put_started.wait(timeout=2)
        threads[1].start()
        backend.release_first_put.set()
        for thread in threads:
            thread.join(timeout=2)
        assert len(results) == 2

        store.rotate_for_account("legacy-account", results[0], "replacement")

        assert store.resolve_for_account("legacy-account", results[0]) == "replacement"
        assert backend.put_count == 2
    finally:
        backend.release_first_put.set()
        for thread in threads:
            thread.join(timeout=2)
        control_plane.close()


def test_scoped_async_mutations_reject_cross_account_references():
    store = CredentialStore(MemoryCredentialBackend())
    secret_ref = store.put("account-b", "secret")

    async def exercise():
        with pytest.raises(CredentialScopeError):
            await store.resolve_for_account_async("account-a", secret_ref)
        with pytest.raises(CredentialScopeError):
            await store.rotate_for_account_async("account-a", secret_ref, "replacement")
        with pytest.raises(CredentialScopeError):
            await store.revoke_for_account_async("account-a", secret_ref)
        with pytest.raises(CredentialScopeError):
            await store.delete_for_account_async("account-a", secret_ref)

    asyncio.run(exercise())
    assert store.resolve_for_account("account-b", secret_ref) == "secret"


def test_windows_backend_uses_generic_enterprise_credential_contract():
    class FakeWin32Cred:
        CRED_TYPE_GENERIC = 1
        CRED_PERSIST_ENTERPRISE = 3

        def __init__(self):
            self.records = {}
            self.writes = []
            self.deletes = []

        def CredWrite(self, credential, flags=0):
            self.writes.append((dict(credential), flags))
            self.records[credential["TargetName"]] = dict(credential)

        def CredRead(self, target_name, credential_type, flags=0):
            if target_name not in self.records:
                raise OSError("not found")
            return dict(self.records[target_name])

        def CredDelete(self, target_name, credential_type, flags=0):
            self.deletes.append((target_name, credential_type, flags))
            if target_name not in self.records:
                raise OSError("not found")
            del self.records[target_name]

    api = FakeWin32Cred()
    store = CredentialStore(WindowsCredentialBackend(win32cred_module=api))
    secret_ref = store.put("account-a", "windows-secret")

    written, flags = api.writes[-1]
    assert written == {
        "Type": api.CRED_TYPE_GENERIC,
        "TargetName": f"OpenAgentSeal/{secret_ref}",
        "CredentialBlob": "windows-secret",
        "Persist": api.CRED_PERSIST_ENTERPRISE,
        "UserName": "account-a",
        "Comment": "active",
    }
    assert flags == 0
    assert store.resolve(secret_ref) == "windows-secret"

    store.revoke(secret_ref)
    assert api.writes[-1][0]["CredentialBlob"] == ""
    assert api.writes[-1][0]["Comment"] == "revoked"
    with pytest.raises(RevokedCredentialError):
        store.resolve(secret_ref)

    store.delete(secret_ref)
    assert api.deletes[-1] == (f"OpenAgentSeal/{secret_ref}", 1, 0)


def test_backend_failures_do_not_chain_diagnostics_containing_opaque_targets():
    pywintypes = pytest.importorskip("pywintypes")

    class BrokenWin32Cred:
        CRED_TYPE_GENERIC = 1
        CRED_PERSIST_ENTERPRISE = 3

        def CredRead(self, target_name, credential_type, flags=0):
            raise pywintypes.error(
                1168, "CredRead", f"backend diagnostic exposed {target_name}"
            )

    store = CredentialStore(WindowsCredentialBackend(win32cred_module=BrokenWin32Cred()))
    secret_ref = "oas-cred:0123456789abcdef0123456789abcdef"

    with pytest.raises(CredentialNotFoundError) as error:
        store.resolve(secret_ref)

    assert error.value.__cause__ is None
    assert secret_ref not in str(error.value)
