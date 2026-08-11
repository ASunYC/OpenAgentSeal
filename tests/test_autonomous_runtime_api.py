from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_agent.app.runner.auth import OperationalAuthStore
from open_agent.app.runner.autonomics_api import router as autonomics_router
from open_agent.app.runner.gateway_api import router as gateway_router
from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import DurableRuntimeRepository


@pytest.fixture
def operational_app(tmp_path):
    control = ControlPlane(tmp_path)
    repository = DurableRuntimeRepository(control, retention_hmac_key=b"r" * 32)
    app = FastAPI()
    auth = OperationalAuthStore(signing_key=b"a" * 32)
    app.state.operational_auth = auth
    app.state.runtime_composition = SimpleNamespace(
        repository=repository,
        supervisor=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                running=True, ready=True, workers=(), started_at=None
            ),
            wake=lambda worker: None,
        ),
        adapters={},
        retention_policy=None,
    )
    app.include_router(gateway_router)
    app.include_router(autonomics_router)
    yield app, auth, repository
    control.close()


def _headers(auth, *, actor="alice", tenant="tenant-a", roles=("operator",), recent=True):
    now = datetime.now(timezone.utc)
    token = auth.issue_bearer(
        actor_id=actor,
        tenant_id=tenant,
        roles=roles,
        scopes=("operations",),
        authenticated_at=now if recent else now - timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


def test_operational_routes_reject_anonymous_and_mobile_tokens(operational_app):
    app, auth, _ = operational_app
    client = TestClient(app)
    assert client.get("/api/operations/channel-accounts").status_code == 401
    mobile = auth.issue_bearer(
        actor_id="alice",
        tenant_id="tenant-a",
        roles=("operator",),
        scopes=("mobile",),
    )
    response = client.get(
        "/api/operations/channel-accounts",
        headers={"Authorization": f"Bearer {mobile}"},
    )
    assert response.status_code == 403
    assert "token" not in response.text.lower()


def test_channel_accounts_are_tenant_scoped_and_secrets_are_opaque(operational_app):
    app, auth, _ = operational_app
    client = TestClient(app)
    created = client.post(
        "/api/operations/channel-accounts",
        headers=_headers(auth),
        json={
            "account_id": "telegram-main",
            "adapter_kind": "telegram",
            "credential": "super-secret-token",
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    assert body["credential_ref"].startswith("oas-cred:")
    assert "super-secret-token" not in created.text

    other = client.get(
        "/api/operations/channel-accounts/telegram-main",
        headers=_headers(auth, actor="mallory", tenant="tenant-b"),
    )
    assert other.status_code == 404
    own = client.get(
        "/api/operations/channel-accounts/telegram-main", headers=_headers(auth)
    )
    assert own.status_code == 200


def test_sensitive_mutations_require_recent_reauthentication(operational_app):
    app, auth, _ = operational_app
    response = TestClient(app).post(
        "/api/operations/scheduler/jobs",
        headers=_headers(auth, recent=False),
        json={
            "job_id": "daily-report",
            "schedule": "0 9 * * *",
            "timezone": "Asia/Shanghai",
            "prompt": "prepare report",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "recent_reauthentication_required"


def test_cookie_mutation_requires_same_origin_and_csrf(operational_app):
    app, auth, _ = operational_app
    token, csrf = auth.issue_cookie_session(
        actor_id="alice",
        tenant_id="tenant-a",
        roles=("operator",),
        scopes=("operations",),
    )
    client = TestClient(app, base_url="https://ops.example.test")
    client.cookies.set("oas_operational_session", token)
    payload = {
        "job_id": "job-cookie",
        "schedule": "0 9 * * *",
        "timezone": "Asia/Shanghai",
        "prompt": "prepare report",
    }
    assert client.post("/api/operations/scheduler/jobs", json=payload).status_code == 403
    assert client.post(
        "/api/operations/scheduler/jobs",
        json=payload,
        headers={"Origin": "https://evil.test", "X-CSRF-Token": csrf},
    ).status_code == 403
    accepted = client.post(
        "/api/operations/scheduler/jobs",
        json=payload,
        headers={"Origin": "https://ops.example.test", "X-CSRF-Token": csrf},
    )
    assert accepted.status_code == 201, accepted.text


def test_pagination_cursor_is_tenant_bound_and_tamper_evident(operational_app):
    app, auth, _ = operational_app
    client = TestClient(app)
    headers = _headers(auth)
    for suffix in ("a", "b"):
        response = client.post(
            "/api/operations/scheduler/jobs",
            headers=headers,
            json={
                "job_id": f"job-{suffix}",
                "schedule": "0 9 * * *",
                "timezone": "UTC",
                "prompt": suffix,
            },
        )
        assert response.status_code == 201, response.text
    first = client.get(
        "/api/operations/scheduler/jobs?limit=1", headers=headers
    ).json()
    cursor = first["meta"]["next_cursor"]
    assert cursor
    assert client.get(
        f"/api/operations/scheduler/jobs?limit=1&cursor={cursor[:-1]}x",
        headers=headers,
    ).status_code == 422
    assert client.get(
        f"/api/operations/scheduler/jobs?limit=1&cursor={cursor}",
        headers=_headers(auth, tenant="tenant-b", actor="bob"),
    ).status_code == 422


def test_webhook_is_public_but_unknown_account_is_concealed(operational_app):
    app, _, _ = operational_app
    response = TestClient(app).post(
        "/api/gateway/webhook/missing",
        content=b'{}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 404
    paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/operations")
    }
    assert paths
    assert all("webhook" not in path for path in paths)


def test_recursive_redaction_never_returns_sensitive_runtime_fields(operational_app):
    app, auth, repository = operational_app
    repository.append_audit_event(
        audit_id="audit-one",
        entity_kind="inbox",
        entity_id="event-one",
        action="failed",
        actor_id="alice",
        payload={
            "body": "private body",
            "nested": {
                "attachment_url": "https://secret.example/file",
                "platform_response": {"token": "abc"},
            },
            "safe_count": 2,
        },
        now=datetime.now(timezone.utc),
    )
    repository.bind_operational_owner(
        entity_kind="audit", entity_id="audit-one", tenant_id="tenant-a", owner_actor_id="alice"
    )
    response = TestClient(app).get(
        "/api/operations/audit", headers=_headers(auth, roles=("auditor",))
    )
    assert response.status_code == 200
    text = response.text
    assert "private body" not in text
    assert "secret.example" not in text
    assert '"safe_count":2' in text

