from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_agent.app.runner.auth import OperationalAuthStore
from open_agent.app.runner.autonomics_api import router as autonomics_router
from open_agent.app.runner.gateway_api import install_operational_error_handlers, router as gateway_router
from open_agent.gateway.credentials import CredentialStore, MemoryCredentialBackend
from open_agent.gateway.security import SecurityViolation
from open_agent.control_plane import ControlPlane
from open_agent.durable_runtime.repository import DurableRuntimeRepository
from open_agent.durable_runtime.models import InboxEvent, OutboxObligation


@pytest.fixture
def operational_app(tmp_path):
    control = ControlPlane(tmp_path)
    goal_capability = object()
    operator_capability = object()
    repository = DurableRuntimeRepository(
        control,
        retention_hmac_key=b"r" * 32,
        goal_authority_capability=goal_capability,
        operator_authority_capability=operator_capability,
    )
    app = FastAPI()
    auth = OperationalAuthStore(
        signing_key=b"a" * 32,
        trusted_origins=("https://ops.example.test",),
        bootstrap_token="bootstrap-capability-" + "b" * 48,
    )
    app.state.operational_auth = auth
    app.state.operational_credentials = CredentialStore(MemoryCredentialBackend())
    app.state.runtime_composition = SimpleNamespace(
        repository=repository,
        supervisor=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                running=True, ready=True, workers=(), started_at=None
            ),
            wake=lambda worker: None,
        ),
        adapters={},
        public_webhook_limiter=SimpleNamespace(
            acquire=lambda *args, **kwargs: nullcontext()
        ),
        retention_policy=None,
        retention_worker=SimpleNamespace(set_policy=lambda policy: None),
        goal_capability=goal_capability,
        operator_capability=operator_capability,
    )
    app.include_router(gateway_router)
    app.include_router(autonomics_router)
    install_operational_error_handlers(app)
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


def test_local_operational_session_bootstrap_and_rotation(operational_app):
    app, _, _ = operational_app
    remote = TestClient(
        app, base_url="https://ops.example.test", client=("203.0.113.20", 51000)
    )
    headers = {"Origin": "https://ops.example.test", "Sec-Fetch-Site": "same-origin"}
    capability = "bootstrap-capability-" + "b" * 48
    assert remote.post(
        "/api/operations/session/bootstrap", headers=headers,
        json={"mode": "cookie", "capability": capability},
    ).status_code == 403

    client = TestClient(
        app, base_url="https://ops.example.test", client=("127.0.0.1", 51001)
    )
    assert client.post(
        "/api/operations/session/bootstrap",
        headers={"Origin": "https://evil.test", "Sec-Fetch-Site": "cross-site"},
        json={"mode": "cookie", "capability": capability},
    ).status_code == 403
    assert client.post(
        "/api/operations/session/bootstrap", headers=headers,
        json={"mode": "cookie", "capability": "wrong-capability-" + "x" * 48},
    ).status_code == 403
    bootstrapped = client.post(
        "/api/operations/session/bootstrap", headers=headers,
        json={"mode": "cookie", "capability": capability},
    )
    assert bootstrapped.status_code == 200, bootstrapped.text
    data = bootstrapped.json()["data"]
    assert data["auth_mode"] == "cookie"
    assert data["csrf_token"]
    assert "access_token" not in data
    assert "HttpOnly" in bootstrapped.headers["set-cookie"]
    assert "Cache-Control" not in bootstrapped.text
    assert client.get("/api/operations/channel-accounts").status_code == 200
    assert client.post(
        "/api/operations/session/bootstrap", headers=headers,
        json={"mode": "cookie", "capability": capability},
    ).status_code == 403

    rotated = client.post(
        "/api/operations/session/reauthenticate",
        headers={**headers, "X-CSRF-Token": data["csrf_token"]},
        json={"user_presence_confirmed": True},
    )
    assert rotated.status_code == 200, rotated.text
    next_csrf = rotated.json()["data"]["csrf_token"]
    assert next_csrf and next_csrf != data["csrf_token"]
    rejected = client.post(
        "/api/operations/scheduler/jobs",
        headers={**headers, "X-CSRF-Token": data["csrf_token"]},
        json={
            "job_id": "stale-csrf", "schedule": "0 9 * * *", "timezone": "UTC",
            "prompt": "must not run",
        },
    )
    assert rejected.status_code == 403


def test_local_desktop_bootstrap_returns_memory_only_bearer(operational_app):
    app, _, _ = operational_app
    app.state.operational_auth = OperationalAuthStore(
        signing_key=b"d" * 32,
        trusted_origins=("http://tauri.localhost",),
        bootstrap_token="desktop-capability-" + "d" * 48,
    )
    client = TestClient(
        app, base_url="http://tauri.localhost", client=("::1", 51002)
    )
    response = client.post(
        "/api/operations/session/bootstrap",
        headers={"Origin": "http://tauri.localhost", "Sec-Fetch-Site": "same-origin"},
        json={"mode": "bearer", "capability": "desktop-capability-" + "d" * 48},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["auth_mode"] == "bearer"
    assert data["access_token"]
    assert data["csrf_token"] is None
    assert "set-cookie" not in response.headers
    assert client.get(
        "/api/operations/channel-accounts",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    ).status_code == 200


def test_channel_account_views_include_exact_cas_version(operational_app):
    app, auth, _ = operational_app
    client = TestClient(app)
    headers = _headers(auth)
    created = client.post(
        "/api/operations/channel-accounts", headers=headers,
        json={"account_id": "versioned", "adapter_kind": "slack", "credential": "write-only"},
    )
    account_id = created.json()["data"]["account_id"]
    assert created.json()["data"]["version"] == 0
    changed = client.patch(
        f"/api/operations/channel-accounts/{account_id}", headers=headers,
        json={"enabled": False, "expected_version": 0},
    )
    assert changed.json()["data"]["version"] == 1
    assert client.get(
        f"/api/operations/channel-accounts/{account_id}", headers=headers
    ).json()["data"]["version"] == 1


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
    account_id = body["account_id"]
    assert account_id.startswith("acct_")
    assert body["credential_ref"].startswith("oas-cred:")
    assert "super-secret-token" not in created.text

    other = client.get(
        f"/api/operations/channel-accounts/{account_id}",
        headers=_headers(auth, actor="mallory", tenant="tenant-b"),
    )
    assert other.status_code == 404
    own = client.get(
        f"/api/operations/channel-accounts/{account_id}", headers=_headers(auth)
    )
    assert own.status_code == 200


def test_client_resource_references_are_opaque_and_tenant_namespaced(operational_app):
    app, auth, _ = operational_app
    client = TestClient(app)
    payload = {
        "account_id": "shared-client-reference",
        "adapter_kind": "telegram",
        "credential": "opaque-secret",
    }
    first = client.post(
        "/api/operations/channel-accounts", headers=_headers(auth), json=payload
    )
    second = client.post(
        "/api/operations/channel-accounts",
        headers=_headers(auth, actor="mallory", tenant="tenant-b"),
        json=payload,
    )

    assert first.status_code == second.status_code == 201
    first_id = first.json()["data"]["account_id"]
    second_id = second.json()["data"]["account_id"]
    assert first_id.startswith("acct_") and second_id.startswith("acct_")
    assert first_id != second_id
    assert client.get(
        f"/api/operations/channel-accounts/{first_id}",
        headers=_headers(auth, actor="mallory", tenant="tenant-b"),
    ).status_code == 404

    goal_payload = {
        "goal_id": "shared-goal-reference",
        "session_id": "shared-session-reference",
        "goal_text": "verify tenant namespace",
        "acceptance_criteria": ["isolated"],
    }
    first_goal = client.post(
        "/api/operations/goals", headers=_headers(auth), json=goal_payload
    )
    second_goal = client.post(
        "/api/operations/goals",
        headers=_headers(auth, actor="mallory", tenant="tenant-b"),
        json=goal_payload,
    )
    assert first_goal.status_code == second_goal.status_code == 201
    first_goal_id = first_goal.json()["data"]["goal_id"]
    second_goal_id = second_goal.json()["data"]["goal_id"]
    assert first_goal_id != second_goal_id

    approval_payload = {
        "approval_id": "shared-approval-reference",
        "decision": "reset_failures",
        "expected_goal_version": 0,
    }
    first_approval = client.post(
        f"/api/operations/goals/{first_goal_id}/approvals",
        headers=_headers(auth),
        json=approval_payload,
    )
    second_approval = client.post(
        f"/api/operations/goals/{second_goal_id}/approvals",
        headers=_headers(auth, actor="mallory", tenant="tenant-b"),
        json=approval_payload,
    )
    assert first_approval.status_code == second_approval.status_code == 201
    assert (
        first_approval.json()["data"]["approval_id"]
        != second_approval.json()["data"]["approval_id"]
    )


@pytest.mark.parametrize(
    ("path", "payload"),
    (
        (
            "/api/operations/goals",
            {
                "goal_id": "",
                "session_id": "session",
                "goal_text": "invalid reference",
                "acceptance_criteria": ["rejected"],
            },
        ),
        (
            "/api/operations/goals",
            {
                "goal_id": "goal",
                "session_id": "s" * 129,
                "goal_text": "invalid reference",
                "acceptance_criteria": ["rejected"],
            },
        ),
        (
            "/api/operations/goals/missing/approvals",
            {
                "approval_id": "界" * 128,
                "decision": "reset_failures",
                "expected_goal_version": 0,
            },
        ),
    ),
)
def test_opaque_client_references_reject_invalid_utf8_boundaries(
    operational_app, path, payload
):
    app, auth, _ = operational_app
    response = TestClient(app).post(path, headers=_headers(auth), json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


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
    assert client.post(
        "/api/operations/scheduler/jobs",
        json=payload,
        headers={
            "Host": "evil.test",
            "Origin": "https://evil.test",
            "X-CSRF-Token": csrf,
        },
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
                "headers": {"x-api-key": "sk-never-list-this"},
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
    assert "sk-never-list-this" not in text
    assert '"safe_count":2' in text


def test_channel_route_lifecycle_and_credential_rotation(operational_app):
    app, auth, _ = operational_app
    client = TestClient(app)
    headers = _headers(auth)
    created = client.post(
        "/api/operations/channel-accounts", headers=headers,
        json={"account_id": "slack-main", "adapter_kind": "slack", "credential": "old"},
    )
    assert created.status_code == 201
    account_id = created.json()["data"]["account_id"]
    patched = client.patch(
        f"/api/operations/channel-accounts/{account_id}", headers=headers,
        json={"enabled": False, "expected_version": 0},
    )
    assert patched.status_code == 200
    rotated = client.put(
        f"/api/operations/channel-accounts/{account_id}/credential", headers=headers,
        json={"credential": "new", "expected_version": 1},
    )
    assert rotated.status_code == 200
    route = client.put(
        f"/api/operations/channel-accounts/{account_id}/routes", headers=headers,
        json={"conversation_id": "C123", "profile_id": "main", "trigger_policy": "mention"},
    )
    assert route.status_code == 201, route.text
    route_id = route.json()["data"]["route_id"]
    assert client.get(
        f"/api/operations/channel-accounts/{account_id}/routes", headers=headers
    ).json()["data"][0]["route_id"] == route_id
    assert client.get(f"/api/operations/routes/{route_id}", headers=headers).status_code == 200
    diagnostic = client.get(
        f"/api/operations/channel-accounts/{account_id}/diagnostics", headers=headers
    ).json()["data"]
    assert diagnostic == {
        "account_id": account_id, "configured": True,
        "adapter_registered": False, "enabled": False,
    }
    assert client.delete(f"/api/operations/routes/{route_id}", headers=headers).status_code == 200
    assert client.delete(
        f"/api/operations/channel-accounts/{account_id}", headers=headers
    ).status_code == 200
    assert client.get(
        f"/api/operations/channel-accounts/{account_id}", headers=headers
    ).status_code == 404


def test_channel_delete_persists_cleanup_before_external_secret_delete(
    operational_app, monkeypatch
):
    app, auth, repository = operational_app
    client = TestClient(app)
    headers = _headers(auth)
    created = client.post(
        "/api/operations/channel-accounts", headers=headers,
        json={"account_id": "crash-delete", "adapter_kind": "slack", "credential": "old"},
    )
    assert created.status_code == 201
    account_id = created.json()["data"]["account_id"]

    def crash(*args, **kwargs):
        raise SystemExit("simulated process termination")

    monkeypatch.setattr(CredentialStore, "delete_for_account", crash)
    with pytest.raises(SystemExit, match="simulated process termination"):
        client.delete(f"/api/operations/channel-accounts/{account_id}", headers=headers)

    row = repository.control_plane._get_conn().execute(
        "SELECT state FROM runtime_credential_cleanup WHERE account_id=?",
        (account_id,),
    ).fetchone()
    assert row is not None and row["state"] == "pending"


def test_scheduler_lifecycle_retention_and_health(operational_app):
    app, auth, _ = operational_app
    client = TestClient(app)
    headers = _headers(auth)
    created = client.post(
        "/api/operations/scheduler/jobs", headers=headers,
        json={
            "job_id": "ops-job", "schedule": "*/5 * * * *", "timezone": "UTC",
            "prompt": "run checks", "max_retries": 2,
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["data"]["job_id"]
    assert job_id.startswith("job_")
    assert client.get("/api/operations/scheduler/jobs", headers=headers).json()["data"][0]["job_id"] == job_id
    assert client.get(f"/api/operations/scheduler/jobs/{job_id}", headers=headers).status_code == 200
    assert client.patch(
        f"/api/operations/scheduler/jobs/{job_id}", headers=headers,
        json={"status": "paused", "expected_version": 0},
    ).status_code == 200
    triggered = client.post(
        f"/api/operations/scheduler/jobs/{job_id}/trigger", headers=headers
    )
    assert triggered.status_code == 202, triggered.text
    run_id = client.get("/api/operations/scheduler/runs", headers=headers).json()["data"][0]["run_id"]
    assert client.get(f"/api/operations/scheduler/runs/{run_id}", headers=headers).status_code == 200
    system_headers = _headers(auth, roles=("operator", "system_operator"))
    assert client.get("/api/operations/retention/policy", headers=system_headers).status_code == 200
    policy = client.put(
        "/api/operations/retention/policy", headers=system_headers,
        json={"inbox_days": 10, "outbox_days": 20, "audit_days": 30, "expected_version": 0},
    )
    assert policy.json()["data"]["version"] == 1
    assert client.get("/api/operations/retention/policy", headers=system_headers).json()["data"]["inbox_days"] == 10
    assert client.post("/api/operations/retention/run", headers=system_headers).status_code == 202
    assert client.get("/api/operations/retention/dead-letters", headers=headers).status_code == 200
    assert client.get("/api/operations/supervisor/health", headers=headers).status_code == 200


def test_goal_runtime_uses_exact_authenticated_principal(operational_app):
    app, auth, _ = operational_app
    client = TestClient(app)
    headers = _headers(auth)
    created = client.post(
        "/api/operations/goals", headers=headers,
        json={
            "goal_id": "goal-ops", "session_id": "session-ops", "goal_text": "ship safely",
            "acceptance_criteria": ["tests pass"], "max_iterations": 3, "max_tokens": 1000,
            "max_estimated_cost": 10.0, "max_active_seconds": 600.0,
        },
    )
    assert created.status_code == 201, created.text
    goal_id = created.json()["data"]["goal_id"]
    assert goal_id.startswith("goal_")
    assert client.get("/api/operations/goals", headers=headers).json()["data"][0]["goal_id"] == goal_id
    detail = client.get(f"/api/operations/goals/{goal_id}", headers=headers)
    assert detail.status_code == 200
    assert client.get(f"/api/operations/goals/{goal_id}/iterations", headers=headers).status_code == 200
    guidance = client.post(
        f"/api/operations/goals/{goal_id}/guidance", headers=headers,
        json={"content": "Prefer the verified route"},
    )
    assert guidance.status_code == 202, guidance.text
    assert client.get(f"/api/operations/goals/{goal_id}/guidance", headers=headers).status_code == 200
    paused = client.post(
        f"/api/operations/goals/{goal_id}/control", headers=headers,
        json={"action": "pause", "expected_version": 0, "reason": "operator review"},
    )
    assert paused.status_code == 200, paused.text
    concealed = client.get(
        f"/api/operations/goals/{goal_id}",
        headers=_headers(auth, actor="mallory", tenant="tenant-b"),
    )
    assert concealed.status_code == 404


def test_audit_reveal_is_prior_audited_and_forbids_credentials(operational_app):
    app, auth, repository = operational_app
    now = datetime.now(timezone.utc)
    repository.append_audit_event(
        audit_id="audit-reveal-source", entity_kind="scheduler", entity_id="job",
        action="diagnostic", actor_id="alice",
        payload={"safe_count": 7, "token": "never"}, now=now,
    )
    repository.bind_operational_owner(
        entity_kind="audit", entity_id="audit-reveal-source",
        tenant_id="tenant-a", owner_actor_id="alice",
    )
    client = TestClient(app)
    headers = _headers(auth, roles=("auditor",))
    denied = client.post(
        "/api/operations/audit/audit-reveal-source/reveal", headers=headers,
        json={"fields": ["token"], "reason": "investigate"},
    )
    assert denied.status_code == 403
    revealed = client.post(
        "/api/operations/audit/audit-reveal-source/reveal", headers=headers,
        json={"fields": ["safe_count"], "reason": "investigate"},
    )
    assert revealed.status_code == 200
    assert revealed.json()["data"]["revealed"] == {"safe_count": 7}
    audit_id = revealed.json()["data"]["authorization_audit_id"]
    assert repository.control_plane._get_conn().execute(
        "SELECT 1 FROM runtime_audit_events WHERE audit_id=?", (audit_id,)
    ).fetchone()


def test_audit_reveal_denies_sensitive_values_nested_in_safe_container(operational_app):
    app, auth, repository = operational_app
    now = datetime.now(timezone.utc)
    repository.append_audit_event(
        audit_id="audit-nested-classified", entity_kind="scheduler", entity_id="job",
        action="diagnostic", actor_id="alice",
        payload={"metadata": {"authorization": "Bearer never-return-this"}}, now=now,
    )
    repository.bind_operational_owner(
        entity_kind="audit", entity_id="audit-nested-classified",
        tenant_id="tenant-a", owner_actor_id="alice",
    )

    response = TestClient(app).post(
        "/api/operations/audit/audit-nested-classified/reveal",
        headers=_headers(auth, roles=("auditor",)),
        json={"fields": ["metadata"], "reason": "investigate"},
    )

    assert response.status_code == 403
    assert "never-return-this" not in response.text


def test_inbox_outbox_details_and_explicit_manual_resend(operational_app):
    app, auth, repository = operational_app
    now = datetime.now(timezone.utc)
    repository.upsert_channel_account(
        account_id="owned-account", adapter_kind="telegram", default_profile_id="main", now=now
    )
    repository.bind_operational_owner(
        entity_kind="channel_account", entity_id="owned-account",
        tenant_id="tenant-a", owner_actor_id="alice",
    )
    inbox = repository.enqueue_inbox(InboxEvent(
        event_id="inbox-owned", event_key="event-owned", account_id="owned-account",
        conversation_id="private-conversation", payload={"body": "secret"},
        created_at=now, updated_at=now,
    ))
    outbox = repository.enqueue_outbox(OutboxObligation(
        obligation_id="outbox-owned", idempotency_key="send-owned",
        destination="channel:owned-account", payload={"content": "secret"},
        created_at=now, updated_at=now,
    ))
    with repository.control_plane._get_conn() as conn:
        conn.execute(
            "UPDATE outbox_obligations SET state='dead_letter' WHERE obligation_id=?",
            (outbox.obligation_id,),
        )
    client = TestClient(app)
    headers = _headers(auth)
    assert client.get(f"/api/operations/inbox/{inbox.event_id}", headers=headers).status_code == 200
    assert client.get(f"/api/operations/outbox/{outbox.obligation_id}", headers=headers).status_code == 200
    resent = client.post(
        f"/api/operations/outbox/{outbox.obligation_id}/resend", headers=headers,
        json={
            "reason": "operator accepted duplicate risk",
            "duplicate_risk_acknowledged": True,
            "acknowledgement_version": "1",
        },
    )
    assert resent.status_code == 202, resent.text


def test_known_webhook_is_bounded_before_authenticated_ingress(operational_app):
    app, auth, repository = operational_app
    now = datetime.now(timezone.utc)
    repository.upsert_channel_account(
        account_id="webhook-account", adapter_kind="telegram", default_profile_id="main", now=now
    )
    repository.bind_operational_owner(
        entity_kind="channel_account", entity_id="webhook-account",
        tenant_id="tenant-a", owner_actor_id="alice",
    )
    app.state.runtime_composition.adapters["webhook-account"] = SimpleNamespace()

    class Ingress:
        def accept_webhook(self, adapter, raw, headers, *, account_id, remote_ip):
            assert raw == b"{}"
            assert account_id == "webhook-account"
            return SimpleNamespace(event_id="accepted-event")

    app.state.runtime_composition.ingress_service = Ingress()
    client = TestClient(app)
    too_large = client.post(
        "/api/gateway/webhook/webhook-account", content=b"x" * (1024 * 1024 + 1)
    )
    assert too_large.status_code == 413
    accepted = client.post(
        "/api/gateway/webhook/webhook-account", content=b"{}"
    )
    assert accepted.status_code == 202
    assert accepted.json()["data"]["event_id"] == "accepted-event"


def test_public_webhook_limiter_runs_before_account_lookup(operational_app):
    app, _, _ = operational_app

    class RejectAll:
        def acquire(self, context, dimensions):
            raise SecurityViolation("ip request limit exceeded")

    app.state.runtime_composition.public_webhook_limiter = RejectAll()
    response = TestClient(app).post(
        "/api/gateway/webhook/missing", content=b"{}"
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "webhook_rate_limit_exceeded"
