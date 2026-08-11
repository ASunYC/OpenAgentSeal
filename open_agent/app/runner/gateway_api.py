"""Authenticated operational API for the durable messaging gateway."""

from __future__ import annotations

import json
import ipaddress
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from open_agent.app.runner.auth import (
    Authenticated,
    OperationalPrincipal,
    RecentPrincipal,
    require_role,
)
from open_agent.app.runner.models import StrictOperationalModel
from open_agent.durable_runtime.models import OutboxObligation, to_json_value
from open_agent.durable_runtime.repository import StateConflictError
from open_agent.gateway.credentials import CredentialStore
from open_agent.gateway.security import IngressContext, SecurityViolation


router = APIRouter(tags=["autonomous-runtime-operations"])
operations = APIRouter(prefix="/api/operations")

_SENSITIVE_KEYS = frozenset({
    "body", "content", "text", "attachment_url", "attachments", "user_id",
    "conversation_id", "temp_token", "token", "secret", "credential",
    "platform_response", "error", "last_error", "acknowledgement",
    "actor_id", "user_id", "principal_id", "issuer_id",
    "api_key", "authorization", "cookie", "set_cookie", "signature",
    "webhook_signature",
})


class ChannelAccountCreate(StrictOperationalModel):
    account_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    adapter_kind: Literal[
        "telegram", "discord", "slack", "whatsapp", "feishu", "dingtalk", "line", "qq", "wecom"
    ]
    credential: str = Field(min_length=1, max_length=65536)
    enabled: bool = True
    default_profile_id: str | None = Field(default=None, max_length=128)


class ChannelAccountUpdate(StrictOperationalModel):
    enabled: bool
    expected_version: int = Field(ge=0)


class CredentialRotate(StrictOperationalModel):
    credential: str = Field(min_length=1, max_length=65536)
    expected_version: int = Field(ge=0)


class RouteWrite(StrictOperationalModel):
    conversation_id: str = Field(min_length=1, max_length=256)
    sender_id: str = Field(default="", max_length=256)
    profile_id: str | None = Field(default=None, max_length=128)
    trigger_policy: Literal["default", "always", "never", "mention", "reply"] = "default"


class ManualResend(StrictOperationalModel):
    reason: str = Field(min_length=1, max_length=500)
    duplicate_risk_acknowledged: Literal[True]
    acknowledgement_version: Literal["1"] = "1"


class AuditReveal(StrictOperationalModel):
    fields: list[str] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=500)


class SessionBootstrap(StrictOperationalModel):
    mode: Literal["cookie", "bearer"]
    capability: str = Field(min_length=32, max_length=4096)


class SessionReauthenticate(StrictOperationalModel):
    user_presence_confirmed: Literal[True]
    capability: str = Field(min_length=32, max_length=4096)


def _composition(request: Request):
    value = getattr(request.app.state, "runtime_composition", None)
    if value is None:
        raise _http(503, "runtime_unavailable", "The durable runtime is unavailable")
    return value


def _credentials(request: Request) -> CredentialStore:
    value = getattr(request.app.state, "operational_credentials", None)
    if not isinstance(value, CredentialStore):
        value = getattr(_composition(request), "credential_store", None)
    if not isinstance(value, CredentialStore):
        raise _http(503, "credential_store_unavailable", "Credential storage is unavailable")
    return value


def _wake_connectors(request: Request) -> None:
    manager = getattr(_composition(request), "connector_manager", None)
    if manager is not None:
        manager.wake()


def _restart_connector(request: Request, account_id: str) -> None:
    manager = getattr(_composition(request), "connector_manager", None)
    if manager is not None:
        manager.invalidate(account_id)


def _owner_visible(repository, kind: str, entity_id: str, principal: OperationalPrincipal, *, shared=False):
    return repository.operational_owner_matches(
        kind, entity_id, principal.tenant_id, None if shared else principal.actor_id
    )


def _page(request, principal, kind, *, limit, cursor, shared=False, tenant_id=None):
    auth = request.app.state.operational_auth
    after = ""
    if cursor:
        try:
            after = auth.verify_cursor(principal, kind, cursor)
        except ValueError:
            raise _http(422, "invalid_cursor", "The pagination cursor is invalid") from None
    repository = _composition(request).repository
    ids = repository.list_operational_ids(
        entity_kind=kind,
        tenant_id=tenant_id or principal.tenant_id,
        owner_actor_id=None if shared else principal.actor_id,
        after=after,
        limit=limit + 1,
    )
    visible, more = ids[:limit], len(ids) > limit
    return visible, auth.sign_cursor(principal, kind, visible[-1]) if more and visible else None


def _require_local_trusted_client(request: Request, *, allow_cross_site: bool = False) -> None:
    try:
        local = ipaddress.ip_address(request.client.host if request.client else "").is_loopback
    except ValueError:
        local = False
    auth = getattr(request.app.state, "operational_auth", None)
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site", "none").lower()
    if (
        not local
        or not hasattr(auth, "origin_is_trusted")
        or not auth.origin_is_trusted(origin)
        or (fetch_site == "cross-site" and not allow_cross_site)
    ):
        raise _http(403, "local_session_required", "A trusted local application session is required")


def _session_view(
    *, mode: str, token: str, csrf: str | None,
    next_bootstrap_capability: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "auth_mode": mode,
        "csrf_token": csrf,
        "roles": ["operator", "system_operator", "auditor"],
        "expires_in_seconds": 1800,
    }
    if mode == "bearer":
        result["access_token"] = token
    if next_bootstrap_capability is not None:
        result["next_bootstrap_capability"] = next_bootstrap_capability
    return result


def _set_operational_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        "oas_operational_session", token, max_age=1800, httponly=True,
        secure=request.url.scheme == "https", samesite="strict",
        path="/api/operations",
    )
    response.headers["Cache-Control"] = "no-store"


@operations.post("/session/bootstrap")
async def bootstrap_session(body: SessionBootstrap, request: Request, response: Response):
    _require_local_trusted_client(request, allow_cross_site=body.mode == "bearer")
    auth = request.app.state.operational_auth
    common = {
        "actor_id": "local-operator", "tenant_id": "local",
        "roles": ("operator", "system_operator", "auditor"),
        "scopes": ("operations",), "session_ttl": timedelta(minutes=30),
    }
    if body.mode == "cookie":
        token, csrf = auth.issue_cookie_session(**common)
    else:
        token, csrf = auth.issue_bearer(**common), None
    successor = auth.consume_bootstrap_capability(body.capability)
    if successor is None:
        auth.revoke_token(token)
        raise _http(403, "bootstrap_capability_required", "A valid one-time bootstrap capability is required")
    if body.mode == "cookie":
        _set_operational_cookie(response, request, token)
    else:
        response.headers["Cache-Control"] = "no-store"
    return _ok(_session_view(
        mode=body.mode, token=token, csrf=csrf,
        next_bootstrap_capability=successor,
    ))


@operations.get("/session/resume")
async def resume_cookie_session(request: Request, response: Response, principal: Authenticated):
    if principal.auth_method != "cookie":
        raise _http(409, "cookie_session_required", "Cookie session resume is not available")
    _require_local_trusted_client(request)
    try:
        csrf = request.app.state.operational_auth.refresh_cookie_csrf(principal)
    except ValueError:
        raise _http(401, "authentication_required", "Authentication is required") from None
    response.headers["Cache-Control"] = "no-store"
    return _ok(_session_view(mode="cookie", token="", csrf=csrf))


@operations.post("/session/reauthenticate")
async def reauthenticate_session(
    body: SessionReauthenticate, request: Request, response: Response,
    principal: Authenticated,
):
    _require_local_trusted_client(request, allow_cross_site=principal.auth_method == "bearer")
    auth = request.app.state.operational_auth
    common = {
        "actor_id": principal.actor_id, "tenant_id": principal.tenant_id,
        "roles": principal.roles, "scopes": principal.scopes,
        "session_ttl": timedelta(minutes=30),
    }
    if principal.auth_method == "cookie":
        token, csrf = auth.issue_cookie_session(**common)
    else:
        token, csrf = auth.issue_bearer(**common), None
    successor = auth.consume_bootstrap_capability(body.capability)
    if successor is None:
        auth.revoke_token(token)
        raise _http(403, "bootstrap_capability_required", "A valid one-time bootstrap capability is required")
    auth.revoke_session_id(principal.session_id)
    if principal.auth_method == "cookie":
        _set_operational_cookie(response, request, token)
    else:
        response.headers["Cache-Control"] = "no-store"
    return _ok(_session_view(
        mode=principal.auth_method, token=token, csrf=csrf,
        next_bootstrap_capability=successor,
    ))


@operations.get("/channel-accounts")
async def list_channel_accounts(
    request: Request,
    principal: Authenticated,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
):
    ids, next_cursor = _page(request, principal, "channel_account", limit=limit, cursor=cursor)
    repository = _composition(request).repository
    rows = [repository.get_channel_account(entity_id) for entity_id in ids]
    versions = _account_versions(repository, [row["account_id"] for row in rows if row])
    return _ok(
        [_account_view(row, versions.get(row["account_id"], 0)) for row in rows if row],
        next_cursor,
    )


@operations.post("/channel-accounts", status_code=201)
async def create_channel_account(
    body: ChannelAccountCreate, request: Request, principal: RecentPrincipal,
):
    if "operator" not in principal.roles:
        raise _http(403, "role_required", "Operator role is required")
    repository = _composition(request).repository
    store = _credentials(request)
    account_id = request.app.state.operational_auth.mint_resource_id(
        principal, "channel_account", body.account_id
    )
    credential_ref = store.put(account_id, body.credential)
    now = datetime.now(timezone.utc)
    try:
        conn = repository.control_plane._get_conn()
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM channel_accounts WHERE account_id=?", (account_id,)
            ).fetchone():
                raise StateConflictError("channel account already exists")
            conn.execute(
                """INSERT INTO channel_accounts (
                       account_id, adapter_kind, enabled, credential_ref, default_profile_id,
                       capabilities, created_at, updated_at, metadata
                   ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, '{}')""",
                (account_id, body.adapter_kind, int(body.enabled), credential_ref,
                 body.default_profile_id, now.isoformat(), now.isoformat()),
            )
            _insert_owner(conn, "channel_account", account_id, principal, now)
    except Exception as exc:
        try:
            store.delete_for_account(account_id, credential_ref)
        except Exception as cleanup_exc:
            _record_credential_cleanup(
                repository.control_plane._get_conn(), account_id,
                credential_ref, cleanup_exc,
            )
        if isinstance(exc, StateConflictError):
            raise _http(409, "already_exists", "Channel account already exists") from None
        raise
    _wake_connectors(request)
    return _ok(_account_view(repository.get_channel_account(account_id), 0))


@operations.get("/channel-accounts/{account_id}")
async def get_channel_account(account_id: str, request: Request, principal: Authenticated):
    repository = _composition(request).repository
    if not _owner_visible(repository, "channel_account", account_id, principal):
        raise _http(404, "not_found", "Resource not found")
    row = repository.get_channel_account(account_id)
    if row is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok(_account_view(row, _account_versions(repository, [account_id]).get(account_id, 0)))


@operations.delete("/channel-accounts/{account_id}")
async def delete_channel_account(account_id: str, request: Request, principal: RecentPrincipal):
    _require_operator(principal)
    repository = _composition(request).repository
    conn = repository.control_plane._get_conn()
    cleanup_id: str | None = None
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        account = conn.execute(
            """SELECT a.credential_ref FROM channel_accounts a
               WHERE a.account_id=? AND EXISTS (
                 SELECT 1 FROM runtime_operational_ownership o
                 WHERE o.entity_kind='channel_account' AND o.entity_id=a.account_id
                   AND o.tenant_id=? AND o.owner_actor_id=?
               )""",
            (account_id, principal.tenant_id, principal.actor_id),
        ).fetchone()
        if account is None:
            raise _http(404, "not_found", "Resource not found")
        route_ids = [row["route_id"] for row in conn.execute(
            "SELECT route_id FROM channel_routes WHERE account_id=?", (account_id,)
        ).fetchall()]
        deleted = conn.execute(
            """DELETE FROM channel_accounts WHERE account_id=? AND EXISTS (
                 SELECT 1 FROM runtime_operational_ownership o
                 WHERE o.entity_kind='channel_account'
                   AND o.entity_id=channel_accounts.account_id
                   AND o.tenant_id=? AND o.owner_actor_id=?
               ) RETURNING credential_ref""",
            (account_id, principal.tenant_id, principal.actor_id),
        ).fetchone()
        if deleted is None:
            raise _http(404, "not_found", "Resource not found")
        conn.execute(
            """DELETE FROM runtime_operational_ownership
               WHERE entity_kind='channel_account' AND entity_id=?
                 AND tenant_id=? AND owner_actor_id=?""",
            (account_id, principal.tenant_id, principal.actor_id),
        )
        if route_ids:
            placeholders = ",".join("?" for _ in route_ids)
            conn.execute(
                f"DELETE FROM runtime_operational_ownership WHERE entity_kind='channel_route' AND entity_id IN ({placeholders})",
                route_ids,
            )
        credential_ref = deleted["credential_ref"]
        if credential_ref:
            cleanup_id = f"cleanup:{uuid.uuid4().hex}"
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO runtime_credential_cleanup (
                     cleanup_id, account_id, credential_ref, state, created_at,
                     attempt, next_attempt_at
                   ) VALUES (?, ?, ?, 'pending', ?, 0, ?)""",
                (cleanup_id, account_id, credential_ref, now, now),
            )
    cleanup_pending = False
    if credential_ref and cleanup_id:
        try:
            _credentials(request).delete_for_account(account_id, credential_ref)
        except Exception as exc:
            cleanup_pending = True
            with conn:
                conn.execute(
                    """UPDATE runtime_credential_cleanup
                       SET last_error=? WHERE cleanup_id=? AND state='pending'""",
                    (exc.__class__.__name__, cleanup_id),
                )
            _composition(request).supervisor.wake("credential_cleanup")
        else:
            with conn:
                conn.execute(
                    """UPDATE runtime_credential_cleanup
                       SET state='completed', completed_at=?, last_error=NULL
                       WHERE cleanup_id=? AND state='pending'""",
                    (datetime.now(timezone.utc).isoformat(), cleanup_id),
                )
    _wake_connectors(request)
    return _ok({"account_id": account_id, "deleted": True, "credential_cleanup_pending": cleanup_pending})


@operations.patch("/channel-accounts/{account_id}")
async def update_channel_account(
    account_id: str, body: ChannelAccountUpdate, request: Request, principal: RecentPrincipal,
):
    _require_operator(principal)
    repository = _composition(request).repository
    conn = repository.control_plane._get_conn()
    with conn:
        row = conn.execute(
            """UPDATE channel_accounts SET enabled=?, updated_at=?
               WHERE account_id=? AND EXISTS (
                 SELECT 1 FROM runtime_operational_ownership o
                 WHERE o.entity_kind='channel_account' AND o.entity_id=channel_accounts.account_id
                   AND o.tenant_id=? AND o.owner_actor_id=? AND o.version=?
               ) RETURNING *""",
            (int(body.enabled), datetime.now(timezone.utc).isoformat(), account_id,
             principal.tenant_id, principal.actor_id, body.expected_version),
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE runtime_operational_ownership SET version=version+1, updated_at=?
                   WHERE entity_kind='channel_account' AND entity_id=?""",
                (datetime.now(timezone.utc).isoformat(), account_id),
            )
    if row is None:
        if not _owner_visible(repository, "channel_account", account_id, principal):
            raise _http(404, "not_found", "Resource not found")
        raise _http(409, "version_conflict", "The resource changed concurrently")
    _composition(request).supervisor.wake("inbox")
    _wake_connectors(request)
    return _ok(_account_view(repository._channel_account(row), body.expected_version + 1))


@operations.put("/channel-accounts/{account_id}/credential")
async def rotate_credential(
    account_id: str, body: CredentialRotate, request: Request, principal: RecentPrincipal,
):
    _require_operator(principal)
    repository = _composition(request).repository
    if not _owner_visible(repository, "channel_account", account_id, principal):
        raise _http(404, "not_found", "Resource not found")
    row = repository.get_channel_account(account_id)
    if row is None or not row.get("credential_ref"):
        raise _http(404, "not_found", "Resource not found")
    store = _credentials(request)
    prior_secret = store.resolve_for_account(account_id, row["credential_ref"])
    conn = repository.control_plane._get_conn()
    published = False
    publication_attempted = False
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute(
                """SELECT version FROM runtime_operational_ownership
                   WHERE entity_kind='channel_account' AND entity_id=?
                     AND tenant_id=? AND owner_actor_id=?""",
                (account_id, principal.tenant_id, principal.actor_id),
            ).fetchone()
            if owner is None or int(owner["version"]) != body.expected_version:
                raise _http(409, "version_conflict", "The resource changed concurrently")
            publication_attempted = True
            store.rotate_for_account(account_id, row["credential_ref"], body.credential)
            published = True
            changed = conn.execute(
                """UPDATE runtime_operational_ownership
                     SET version=version+1, updated_at=?
                   WHERE entity_kind='channel_account' AND entity_id=? AND version=?""",
                (datetime.now(timezone.utc).isoformat(), account_id, body.expected_version),
            )
            if changed.rowcount != 1:
                raise StateConflictError("credential publication lost its compare-and-set race")
    except Exception:
        if published:
            try:
                store.rotate_for_account(account_id, row["credential_ref"], prior_secret)
            except Exception:
                with conn:
                    reconciled = conn.execute(
                        """UPDATE runtime_operational_ownership
                             SET version=version+1, updated_at=?
                           WHERE entity_kind='channel_account' AND entity_id=? AND version=?""",
                        (datetime.now(timezone.utc).isoformat(), account_id, body.expected_version),
                    )
                if reconciled.rowcount != 1:
                    raise _http(
                        503, "credential_reconciliation_required",
                        "Credential publication requires operator reconciliation",
                    ) from None
                raise _http(
                    503, "credential_publication_reconciled",
                    "Credential publication completed but the response was interrupted",
                ) from None
        raise
    finally:
        if publication_attempted:
            # A provider session authenticated before publication must never
            # survive any complete, failed, or partially committed write.
            _restart_connector(request, account_id)
    return _ok({"credential_ref": row["credential_ref"], "rotated": True, "version": body.expected_version + 1})


@operations.put("/channel-accounts/{account_id}/routes", status_code=201)
async def put_route(
    account_id: str, body: RouteWrite, request: Request, principal: RecentPrincipal,
):
    _require_operator(principal)
    repository = _composition(request).repository
    if not _owner_visible(repository, "channel_account", account_id, principal):
        raise _http(404, "not_found", "Resource not found")
    route_id = repository._gateway_id(
        "route", account_id, body.conversation_id, body.sender_id
    )
    now = datetime.now(timezone.utc)
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """INSERT INTO channel_routes (
                 route_id, account_id, conversation_id, sender_id, profile_id,
                 trigger_policy, created_at, updated_at, metadata
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')
               ON CONFLICT(account_id, conversation_id, sender_id) DO UPDATE SET
                 profile_id=excluded.profile_id, trigger_policy=excluded.trigger_policy,
                 updated_at=excluded.updated_at
               RETURNING *""",
            (route_id, account_id, body.conversation_id, body.sender_id,
             body.profile_id, body.trigger_policy, now.isoformat(), now.isoformat()),
        ).fetchone()
        _insert_owner(conn, "channel_route", row["route_id"], principal, now)
    route = repository._channel_route(row, should_dispatch=False)
    return _ok(_redact(route))


@operations.get("/channel-accounts/{account_id}/routes")
async def list_routes(account_id: str, request: Request, principal: Authenticated):
    repository = _composition(request).repository
    if not _owner_visible(repository, "channel_account", account_id, principal):
        raise _http(404, "not_found", "Resource not found")
    rows = repository.control_plane._get_conn().execute(
        "SELECT * FROM channel_routes WHERE account_id=? ORDER BY route_id LIMIT 100",
        (account_id,),
    ).fetchall()
    return _ok([_redact(_row(row)) for row in rows])


@operations.get("/routes/{route_id}")
async def get_route(route_id: str, request: Request, principal: Authenticated):
    repository = _composition(request).repository
    if not _owner_visible(repository, "channel_route", route_id, principal):
        raise _http(404, "not_found", "Resource not found")
    row = repository.control_plane._get_conn().execute(
        "SELECT * FROM channel_routes WHERE route_id=?", (route_id,)
    ).fetchone()
    if row is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok(_redact(_row(row)))


@operations.delete("/routes/{route_id}")
async def delete_route(route_id: str, request: Request, principal: RecentPrincipal):
    _require_operator(principal)
    repository = _composition(request).repository
    conn = repository.control_plane._get_conn()
    with conn:
        row = conn.execute(
            """DELETE FROM channel_routes WHERE route_id=? AND EXISTS (
                 SELECT 1 FROM runtime_operational_ownership o
                  WHERE o.entity_kind='channel_route' AND o.entity_id=channel_routes.route_id
                    AND o.tenant_id=? AND o.owner_actor_id=?) RETURNING route_id""",
            (route_id, principal.tenant_id, principal.actor_id),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM runtime_operational_ownership WHERE entity_kind='channel_route' AND entity_id=?",
                (route_id,),
            )
    if row is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok({"route_id": route_id, "deleted": True})


@operations.get("/channel-accounts/{account_id}/diagnostics")
async def account_diagnostics(account_id: str, request: Request, principal: Authenticated):
    composition = _composition(request)
    if not _owner_visible(composition.repository, "channel_account", account_id, principal):
        raise _http(404, "not_found", "Resource not found")
    account = composition.repository.get_channel_account(account_id)
    manager = getattr(composition, "connector_manager", None)
    connector = manager.snapshot(account_id) if manager is not None else {
        "state": "unavailable", "authenticated": False,
        "session_resumable": False, "last_error": None,
    }
    return _ok({
        "account_id": account_id,
        "configured": bool(account and account.get("credential_ref")),
        "adapter_registered": account_id in composition.adapters,
        "enabled": bool(account and account.get("enabled")),
        "connector": connector,
    })


@operations.get("/inbox")
async def list_inbox(request: Request, principal: Authenticated, limit: Annotated[int, Query(ge=1, le=100)] = 100, cursor: str | None = None):
    ids, next_cursor = _page(request, principal, "inbox", limit=limit, cursor=cursor, shared=True)
    repository = _composition(request).repository
    items = []
    for item_id in ids:
        item = repository.get_inbox(item_id)
        if item:
            items.append(_redact({name: to_json_value(getattr(item, name)) for name in item.__dataclass_fields__}))
    return _ok(items, next_cursor)


@operations.get("/inbox/{event_id}")
async def get_inbox(event_id: str, request: Request, principal: Authenticated):
    repository = _composition(request).repository
    if not _owner_visible(repository, "inbox", event_id, principal, shared=True):
        raise _http(404, "not_found", "Resource not found")
    item = repository.get_inbox(event_id)
    if item is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok(_redact({name: to_json_value(getattr(item, name)) for name in item.__dataclass_fields__}))


@operations.get("/outbox")
async def list_outbox(request: Request, principal: Authenticated, limit: Annotated[int, Query(ge=1, le=100)] = 100, cursor: str | None = None):
    ids, next_cursor = _page(request, principal, "outbox", limit=limit, cursor=cursor, shared=True)
    repository = _composition(request).repository
    items = []
    for item_id in ids:
        item = repository.get_outbox(item_id)
        if item:
            items.append(_redact({name: to_json_value(getattr(item, name)) for name in item.__dataclass_fields__}))
    return _ok(items, next_cursor)


@operations.get("/outbox/{obligation_id}")
async def get_outbox(obligation_id: str, request: Request, principal: Authenticated):
    repository = _composition(request).repository
    if not _owner_visible(repository, "outbox", obligation_id, principal, shared=True):
        raise _http(404, "not_found", "Resource not found")
    item = repository.get_outbox(obligation_id)
    if item is None:
        raise _http(404, "not_found", "Resource not found")
    return _ok(_redact({name: to_json_value(getattr(item, name)) for name in item.__dataclass_fields__}))


@operations.post("/outbox/{obligation_id}/resend", status_code=202)
async def resend_outbox(obligation_id: str, body: ManualResend, request: Request, principal: RecentPrincipal):
    _require_operator(principal)
    repository = _composition(request).repository
    if not _owner_visible(repository, "outbox", obligation_id, principal, shared=True):
        raise _http(404, "not_found", "Resource not found")
    source = repository.get_outbox(obligation_id)
    if source is None:
        raise _http(404, "not_found", "Resource not found")
    now = datetime.now(timezone.utc)
    resend_id = f"resend_{uuid.uuid4().hex}"
    resent = repository.manual_resend_outbox(
        obligation_id,
        OutboxObligation(
            obligation_id=resend_id,
            idempotency_key=f"manual-resend:{obligation_id}:{resend_id}",
            destination=source.destination,
            payload=source.payload,
            created_at=now,
            updated_at=now,
        ),
        actor_id=principal.actor_id,
        duplicate_risk_acknowledged=body.duplicate_risk_acknowledged,
        acknowledgement_version=body.acknowledgement_version,
        now=now,
    )
    repository.bind_operational_owner(
        entity_kind="outbox", entity_id=resent.obligation_id,
        tenant_id=principal.tenant_id, owner_actor_id=principal.actor_id,
    )
    _composition(request).supervisor.wake("outbox")
    return _ok({"obligation_id": resent.obligation_id, "state": resent.state})


@operations.get("/audit")
async def list_audit(
    request: Request,
    principal: Annotated[OperationalPrincipal, Depends(require_role("auditor", "operator", "system_operator"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
):
    audit_tenant = "__global__" if "system_operator" in principal.roles else principal.tenant_id
    ids, next_cursor = _page(
        request, principal, "audit", limit=limit, cursor=cursor,
        shared=True, tenant_id=audit_tenant,
    )
    if not ids:
        return _ok([], next_cursor)
    placeholders = ",".join("?" for _ in ids)
    rows = _composition(request).repository.control_plane._get_conn().execute(
        f"SELECT * FROM runtime_audit_events WHERE audit_id IN ({placeholders}) ORDER BY audit_id", ids
    ).fetchall()
    return _ok([_redact(_row(row)) for row in rows], next_cursor)


@operations.post("/audit/{audit_id}/reveal")
async def reveal_audit(
    audit_id: str, body: AuditReveal, request: Request,
    principal: Annotated[OperationalPrincipal, Depends(require_role("auditor"))],
    recent: RecentPrincipal,
):
    del recent
    repository = _composition(request).repository
    if not _owner_visible(repository, "audit", audit_id, principal, shared=True):
        raise _http(404, "not_found", "Resource not found")
    forbidden = {
        field for field in body.fields
        if field.lower() in _SENSITIVE_KEYS
        or any(part in field.lower() for part in ("secret", "token", "credential", "password", "url"))
    }
    if forbidden:
        raise _http(403, "classified_content", "Credential or classified content cannot be revealed")
    conn = repository.control_plane._get_conn()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM runtime_audit_events WHERE audit_id=?", (audit_id,)).fetchone()
        if row is None:
            raise _http(404, "not_found", "Resource not found")
        payload = json.loads(row["payload"] or "{}")
        revealed = {field: payload.get(field) for field in body.fields if field in payload}
        if any(_contains_classified(value, key=field) for field, value in revealed.items()):
            raise _http(
                403,
                "classified_content",
                "Credential or classified content cannot be revealed",
            )
        reveal_id = f"audit-reveal:{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO runtime_audit_events (
                 audit_id, entity_kind, entity_id, action, actor_id, payload, created_at
               ) VALUES (?, 'audit', ?, 'reveal_authorized', ?, ?, ?)""",
            (reveal_id, audit_id, principal.actor_id,
             json.dumps({"fields": list(revealed), "reason": body.reason}, separators=(",", ":")), now),
        )
        _insert_owner(conn, "audit", reveal_id, principal, datetime.fromisoformat(now))
    return _ok({"audit_id": audit_id, "revealed": revealed, "authorization_audit_id": reveal_id})


@router.post("/api/gateway/webhook/{account_id}", status_code=202)
async def webhook(account_id: str, request: Request):
    composition = _composition(request)
    remote_ip = request.client.host if request.client else "unknown"
    limiter = getattr(composition, "public_webhook_limiter", None)
    if limiter is None:
        raise _http(503, "ingress_unavailable", "Webhook ingress is unavailable")
    try:
        lease = limiter.acquire(
            IngressContext(ip=remote_ip, adapter="public-webhook", account=account_id),
            ("global", "ip"),
        )
    except SecurityViolation:
        raise _http(429, "webhook_rate_limit_exceeded", "Too many webhook requests") from None
    with lease:
        adapter = composition.adapters.get(account_id)
        if adapter is None or composition.repository.get_channel_account(account_id) is None:
            raise _http(404, "not_found", "Resource not found")
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 1024 * 1024):
            raise _http(413, "body_too_large", "Webhook body is too large")
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > 1024 * 1024:
                raise _http(413, "body_too_large", "Webhook body is too large")
            chunks.append(chunk)
        raw = b"".join(chunks)
        service = getattr(composition, "ingress_service", None)
        if service is None:
            raise _http(503, "ingress_unavailable", "Webhook ingress is unavailable")
        try:
            receipt = service.accept_webhook(
                adapter, raw, dict(request.headers), account_id=account_id,
                remote_ip=remote_ip,
            )
        except Exception as exc:
            if exc.__class__.__name__ in {"SecurityViolation", "AdapterAuthenticationError"}:
                raise _http(401, "webhook_authentication_failed", "Webhook authentication failed") from None
            raise _http(422, "invalid_webhook", "Webhook payload is invalid") from None
        composition.supervisor.wake("inbox")
    return _ok({"event_id": receipt.event_id})


def _insert_owner(conn, kind: str, entity_id: str, principal: OperationalPrincipal, now: datetime):
    row = conn.execute(
        """INSERT INTO runtime_operational_ownership (
               entity_kind, entity_id, tenant_id, owner_actor_id, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(entity_kind, entity_id) DO UPDATE SET updated_at=excluded.updated_at
           WHERE tenant_id=excluded.tenant_id AND owner_actor_id=excluded.owner_actor_id
           RETURNING entity_id""",
        (kind, entity_id, principal.tenant_id, principal.actor_id, now.isoformat(), now.isoformat()),
    ).fetchone()
    if row is None:
        raise StateConflictError("resource ownership is immutable")


def _record_credential_cleanup(conn, account_id: str, credential_ref: str, exc: Exception) -> None:
    with conn:
        conn.execute(
            """INSERT INTO runtime_credential_cleanup (
                 cleanup_id, account_id, credential_ref, state, created_at,
                 attempt, next_attempt_at, last_error
               ) VALUES (?, ?, ?, 'pending', ?, 0, ?, ?)""",
            (f"cleanup:{uuid.uuid4().hex}", account_id, credential_ref,
             datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(),
             exc.__class__.__name__),
        )


def _account_versions(repository, account_ids: list[str]) -> dict[str, int]:
    if not account_ids:
        return {}
    placeholders = ",".join("?" for _ in account_ids)
    rows = repository.control_plane._get_conn().execute(
        f"""SELECT entity_id, version FROM runtime_operational_ownership
             WHERE entity_kind='channel_account' AND entity_id IN ({placeholders})""",
        account_ids,
    ).fetchall()
    return {row["entity_id"]: int(row["version"]) for row in rows}


def _account_view(row, version: int):
    if row is None:
        return None
    return {
        "account_id": row["account_id"], "adapter_kind": row["adapter_kind"],
        "enabled": bool(row["enabled"]), "credential_ref": row.get("credential_ref"),
        "default_profile_id": row.get("default_profile_id"), "updated_at": row["updated_at"],
        "version": version,
    }


def _require_operator(principal: OperationalPrincipal) -> None:
    if "operator" not in principal.roles:
        raise _http(403, "role_required", "Operator role is required")


def _row(row) -> dict[str, Any]:
    result = dict(row)
    for key, value in tuple(result.items()):
        if isinstance(value, str) and value[:1] in {"{", "["}:
            try:
                result[key] = json.loads(value)
            except ValueError:
                pass
    return result


def _redact(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, key=key) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        part in normalized
        for part in (
            "password", "secret", "token", "credential", "url", "api_key",
            "authorization", "cookie", "signature",
        )
    )


def _contains_classified(value: Any, *, key: str = "") -> bool:
    if _is_sensitive_key(key):
        return True
    if isinstance(value, dict):
        return any(_contains_classified(item, key=str(item_key)) for item_key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_classified(item, key=key) for item in value)
    return False


def _ok(data, cursor: str | None = None):
    result = {"success": True, "data": data}
    if cursor is not None:
        result["meta"] = {"next_cursor": cursor}
    elif isinstance(data, list):
        result["meta"] = {"next_cursor": None}
    return result


def _http(status: int, code: str, message: str):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


router.include_router(operations)


def install_operational_error_handlers(app: FastAPI) -> None:
    """Install non-reflective envelopes without changing legacy API responses."""
    existing_http = app.exception_handlers.get(HTTPException)
    existing_validation = app.exception_handlers.get(RequestValidationError)

    @app.exception_handler(HTTPException)
    async def operational_http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith(("/api/operations", "/api/gateway/webhook/")):
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            return JSONResponse(
                status_code=exc.status_code,
                content={"success": False, "error": {
                    "code": str(detail.get("code") or "request_failed"),
                    "message": str(detail.get("message") or "The request could not be completed"),
                }},
                headers=exc.headers,
            )
        if existing_http:
            result = existing_http(request, exc)
            return await result if hasattr(result, "__await__") else result
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def operational_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/operations"):
            return JSONResponse(
                status_code=422,
                content={"success": False, "error": {
                    "code": "validation_error", "message": "The request is invalid",
                }},
            )
        if existing_validation:
            result = existing_validation(request, exc)
            return await result if hasattr(result, "__await__") else result
        return JSONResponse(status_code=422, content={"detail": exc.errors()})


__all__ = ["install_operational_error_handlers", "router", "_redact"]
