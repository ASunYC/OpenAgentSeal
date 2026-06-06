import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from open_agent.app import mobile
from open_agent.app.runner.models import ChatHistory, ChatSpec, Message


@pytest.fixture
def mobile_client(tmp_path, monkeypatch):
    monkeypatch.setattr(mobile, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(mobile, "_pairing_code", None)
    monkeypatch.setattr(mobile, "_pairing_attempts", {})

    async def fake_agents():
        return [{"id": "main", "name": "默认助手"}, {"id": "coder", "name": "代码高手"}]

    async def fake_chats(profile_id="main", limit=20):
        return [{"id": profile_id, "name": profile_id, "session_id": f"session-{profile_id}"}]

    monkeypatch.setattr(mobile, "_list_agents", fake_agents)
    monkeypatch.setattr(mobile, "_list_recent_chats", fake_chats)
    monkeypatch.setattr(mobile, "_list_running_tasks", lambda: [])

    app = FastAPI()
    app.include_router(mobile.router)
    return TestClient(app), tmp_path


def _pair(client: TestClient) -> tuple[str, str]:
    code_response = client.post("/api/mobile/pairing-code")
    assert code_response.status_code == 200
    code = code_response.json()["code"]
    pair_response = client.post(
        "/api/mobile/pair",
        json={"code": code, "device_name": "Test Phone"},
    )
    assert pair_response.status_code == 200
    payload = pair_response.json()
    return payload["token"], payload["device"]["id"]


def test_pairing_hashes_token_and_revoke_invalidates_device(mobile_client):
    client, data_dir = mobile_client
    token, device_id = _pair(client)

    config = json.loads((data_dir / "mobile" / "config.json").read_text(encoding="utf-8"))
    stored_device = config["devices"][0]
    assert "token" not in stored_device
    assert len(stored_device["token_hash"]) == 64

    summary = client.get(
        "/api/mobile/summary?profile_id=coder",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert summary.status_code == 200
    assert summary.json()["chats"][0]["id"] == "coder"
    assert "token_hash" not in summary.json()["device"]

    revoke = client.delete(f"/api/mobile/devices/{device_id}")
    assert revoke.status_code == 200
    denied = client.get(
        "/api/mobile/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 401


def test_mobile_chat_routes_to_selected_profile(mobile_client, monkeypatch):
    client, _ = mobile_client
    token, _ = _pair(client)
    requested_profiles = []

    class FakeManager:
        async def create_chat(self, name, user_id, channel):
            return ChatSpec(
                id="chat-coder",
                name=name,
                session_id="session-coder",
                user_id=user_id,
                channel=channel,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

        async def get_history(self, chat_id):
            return ChatHistory(
                chat_id=chat_id,
                total=1,
                messages=[Message(role="assistant", content="coder history")],
            )

    def fake_get_chat_manager(profile_id=None):
        requested_profiles.append(profile_id)
        return FakeManager()

    import open_agent.app.runner

    monkeypatch.setattr(open_agent.app.runner, "get_chat_manager", fake_get_chat_manager)

    created = client.post(
        "/api/mobile/chats",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Coder Chat", "profile_id": "coder"},
    )
    assert created.status_code == 200
    assert created.json()["profile_id"] == "coder"

    history = client.get(
        "/api/mobile/chats/chat-coder/history?profile_id=coder",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert history.status_code == 200
    assert history.json()["messages"][0]["content"] == "coder history"
    assert requested_profiles == ["coder", "coder"]


def _remote_request(path: str, method: str = "GET", token: str = "") -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "scheme": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "client": ("192.168.1.40", 50000),
            "server": ("192.168.1.10", 9998),
        }
    )


def test_remote_guard_limits_mobile_token_scope(mobile_client):
    client, _ = mobile_client
    token, _ = _pair(client)

    assert mobile.is_remote_api_request_allowed(_remote_request("/api/health"))
    assert mobile.is_remote_api_request_allowed(_remote_request("/api/mobile/pair", "POST"))
    assert mobile.is_remote_api_request_allowed(_remote_request("/api/run", "OPTIONS"))
    assert mobile.is_remote_api_request_allowed(_remote_request("/api/run", "POST", token))
    assert not mobile.is_remote_api_request_allowed(_remote_request("/api/run", "POST"))
    assert not mobile.is_remote_api_request_allowed(_remote_request("/api/settings", "GET", token))


def test_pairing_rate_limit_blocks_brute_force(mobile_client):
    client, _ = mobile_client
    client.post("/api/mobile/pairing-code")

    for _ in range(mobile.PAIRING_MAX_FAILED_ATTEMPTS):
        response = client.post("/api/mobile/pair", json={"code": "000000"})
        assert response.status_code == 401

    blocked = client.post("/api/mobile/pair", json={"code": "000000"})
    assert blocked.status_code == 429


def test_bind_host_falls_back_to_cli_argument(monkeypatch):
    monkeypatch.delenv("OPEN_AGENT_DESKTOP_HOST", raising=False)
    monkeypatch.setattr(mobile.sys, "argv", ["open-agent", "--host", "0.0.0.0", "--port", "9998"])
    assert mobile._configured_bind_host() == "0.0.0.0"
