"""Server-minted authentication and authorization for operational APIs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Iterable
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request


_MAX_SESSION_AGE = timedelta(hours=12)
_RECENT_REAUTH = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class OperationalPrincipal:
    actor_id: str
    tenant_id: str
    roles: frozenset[str]
    scopes: frozenset[str]
    authenticated_at: datetime
    auth_method: str
    session_id: str


@dataclass(frozen=True, slots=True)
class _Session:
    principal: OperationalPrincipal
    expires_at: datetime
    csrf_digest: bytes | None


class OperationalRateLimitError(RuntimeError):
    pass


class OperationalAuthStore:
    """In-process session registry with signed, opaque bearer/cookie handles."""

    def __init__(self, *, signing_key: bytes, trusted_origins: Iterable[str]) -> None:
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("signing_key must contain at least 32 bytes")
        origins = frozenset(_canonical_origin(value) for value in trusted_origins)
        if not origins:
            raise ValueError("trusted_origins must not be empty")
        self._key = signing_key
        self._trusted_origins = origins
        self._sessions: dict[str, _Session] = {}
        self._rate_windows: dict[str, tuple[int, int]] = {}
        self._lock = threading.RLock()

    def issue_bearer(
        self,
        *,
        actor_id: str,
        tenant_id: str,
        roles: Iterable[str],
        scopes: Iterable[str],
        authenticated_at: datetime | None = None,
    ) -> str:
        return self._issue(
            actor_id=actor_id,
            tenant_id=tenant_id,
            roles=roles,
            scopes=scopes,
            authenticated_at=authenticated_at,
            method="bearer",
            csrf=None,
        )[0]

    def issue_cookie_session(
        self,
        *,
        actor_id: str,
        tenant_id: str,
        roles: Iterable[str],
        scopes: Iterable[str],
        authenticated_at: datetime | None = None,
    ) -> tuple[str, str]:
        csrf = secrets.token_urlsafe(32)
        token, _ = self._issue(
            actor_id=actor_id,
            tenant_id=tenant_id,
            roles=roles,
            scopes=scopes,
            authenticated_at=authenticated_at,
            method="cookie",
            csrf=csrf,
        )
        return token, csrf

    def authenticate(self, token: str, *, method: str) -> OperationalPrincipal | None:
        session_id = self._verify_handle(token)
        if session_id is None:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None or session.expires_at <= _now():
            return None
        if session.principal.auth_method != method:
            return None
        minute = int(_now().timestamp() // 60)
        with self._lock:
            window, count = self._rate_windows.get(session_id, (minute, 0))
            if window != minute:
                window, count = minute, 0
            if count >= 300:
                raise OperationalRateLimitError("operational request rate exceeded")
            self._rate_windows = {**self._rate_windows, session_id: (window, count + 1)}
        return session.principal

    def verify_csrf(self, principal: OperationalPrincipal, supplied: str) -> bool:
        with self._lock:
            session = self._sessions.get(principal.session_id)
        return bool(
            session
            and session.csrf_digest is not None
            and isinstance(supplied, str)
            and hmac.compare_digest(
                session.csrf_digest,
                hmac.new(self._key, supplied.encode("utf-8"), hashlib.sha256).digest(),
            )
        )

    def origin_is_trusted(self, supplied: str | None) -> bool:
        if not isinstance(supplied, str):
            return False
        try:
            canonical = _canonical_origin(supplied)
        except ValueError:
            return False
        return canonical in self._trusted_origins

    def sign_cursor(self, principal: OperationalPrincipal, resource: str, position: str) -> str:
        payload = json.dumps(
            {"t": principal.tenant_id, "a": principal.actor_id, "r": resource, "p": position},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(self._key, b"cursor\0" + payload, hashlib.sha256).digest()
        return _b64(payload + signature)

    def mint_resource_id(
        self, principal: OperationalPrincipal, resource: str, client_reference: str
    ) -> str:
        for value, name in (
            (resource, "resource"),
            (client_reference, "client_reference"),
        ):
            if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 128:
                raise ValueError(f"{name} must be a bounded identifier")
        payload = json.dumps(
            [principal.tenant_id, principal.actor_id, resource, client_reference],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        digest = hmac.new(self._key, b"resource-id\0" + payload, hashlib.sha256).hexdigest()
        prefix = {
            "channel_account": "acct",
            "scheduler_job": "job",
            "goal": "goal",
            "goal_session": "session",
            "goal_approval": "approval",
        }.get(resource, "resource")
        return f"{prefix}_{digest}"

    def verify_cursor(self, principal: OperationalPrincipal, resource: str, cursor: str) -> str:
        try:
            packed = _unb64(cursor)
            payload, supplied = packed[:-32], packed[-32:]
            expected = hmac.new(self._key, b"cursor\0" + payload, hashlib.sha256).digest()
            value = json.loads(payload)
        except Exception:
            raise ValueError("invalid pagination cursor") from None
        if not hmac.compare_digest(supplied, expected) or value != {
            "a": principal.actor_id,
            "p": value.get("p"),
            "r": resource,
            "t": principal.tenant_id,
        }:
            raise ValueError("invalid pagination cursor")
        position = value.get("p")
        if not isinstance(position, str):
            raise ValueError("invalid pagination cursor")
        return position

    def _issue(self, *, actor_id, tenant_id, roles, scopes, authenticated_at, method, csrf):
        for value, name in ((actor_id, "actor_id"), (tenant_id, "tenant_id")):
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f"{name} must be a bounded identifier")
        role_set = _bounded_set(roles, "roles")
        scope_set = _bounded_set(scopes, "scopes")
        auth_time = authenticated_at or _now()
        if auth_time.tzinfo is None or auth_time.utcoffset() is None:
            raise ValueError("authenticated_at must be timezone-aware")
        if auth_time.astimezone(timezone.utc) > _now() + timedelta(minutes=1):
            raise ValueError("authenticated_at cannot be in the future")
        session_id = secrets.token_urlsafe(24)
        principal = OperationalPrincipal(
            actor_id,
            tenant_id,
            role_set,
            scope_set,
            auth_time.astimezone(timezone.utc),
            method,
            session_id,
        )
        csrf_digest = (
            hmac.new(self._key, csrf.encode("utf-8"), hashlib.sha256).digest()
            if csrf is not None
            else None
        )
        with self._lock:
            self._sessions = {
                **self._sessions,
                session_id: _Session(principal, _now() + _MAX_SESSION_AGE, csrf_digest),
            }
        signature = hmac.new(self._key, b"session\0" + session_id.encode(), hashlib.sha256).digest()
        return _b64(session_id.encode() + b"." + signature), csrf

    def _verify_handle(self, token: str) -> str | None:
        try:
            packed = _unb64(token)
            session, supplied = packed.split(b".", 1)
            expected = hmac.new(self._key, b"session\0" + session, hashlib.sha256).digest()
            if not hmac.compare_digest(supplied, expected):
                return None
            return session.decode("ascii")
        except Exception:
            return None


def _bounded_set(values: Iterable[str], name: str) -> frozenset[str]:
    result = frozenset(values)
    if len(result) > 32 or any(not isinstance(v, str) or not v or len(v) > 64 for v in result):
        raise ValueError(f"{name} must contain bounded identifiers")
    return result


def _canonical_origin(value: str) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("trusted origin is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("trusted origin is invalid")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid token")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def require_authenticated(request: Request) -> OperationalPrincipal:
    store = getattr(request.app.state, "operational_auth", None)
    if not isinstance(store, OperationalAuthStore):
        raise _error(503, "authentication_unavailable", "Operational authentication is unavailable")
    authorization = request.headers.get("authorization", "")
    method = "bearer"
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        method = "cookie"
        token = request.cookies.get("oas_operational_session", "")
    try:
        principal = store.authenticate(token, method=method)
    except OperationalRateLimitError:
        raise _error(429, "rate_limit_exceeded", "Too many operational requests") from None
    if principal is None:
        raise _error(401, "authentication_required", "Authentication is required")
    if "operations" not in principal.scopes:
        raise _error(403, "insufficient_scope", "Operational scope is required")
    if method == "cookie" and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if not store.origin_is_trusted(origin):
            raise _error(403, "same_origin_required", "A same-origin request is required")
        if not store.verify_csrf(principal, request.headers.get("x-csrf-token", "")):
            raise _error(403, "csrf_required", "A valid CSRF token is required")
    return principal


Authenticated = Annotated[OperationalPrincipal, Depends(require_authenticated)]


def require_role(*roles: str):
    async def dependency(principal: Authenticated) -> OperationalPrincipal:
        if principal.roles.isdisjoint(roles):
            raise _error(403, "role_required", "The requested operation is not permitted")
        return principal
    return dependency


async def require_recent_reauth(principal: Authenticated) -> OperationalPrincipal:
    if _now() - principal.authenticated_at > _RECENT_REAUTH:
        raise _error(403, "recent_reauthentication_required", "Recent reauthentication is required")
    return principal


RecentPrincipal = Annotated[OperationalPrincipal, Depends(require_recent_reauth)]


__all__ = [
    "Authenticated", "OperationalAuthStore", "OperationalPrincipal", "RecentPrincipal",
    "require_authenticated", "require_recent_reauth", "require_role",
]
