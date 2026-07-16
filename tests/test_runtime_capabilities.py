from fastapi import FastAPI
from fastapi.testclient import TestClient

import open_agent.app._app as app_module


def _capabilities_for_platform(
    monkeypatch, platform: str, *, desktop: bool = False
) -> dict:
    monkeypatch.setattr(app_module.sys, "platform", platform)
    if desktop:
        monkeypatch.setenv("OPEN_AGENT_DESKTOP", "1")
    else:
        monkeypatch.delenv("OPEN_AGENT_DESKTOP", raising=False)
    app = FastAPI()
    app_module._setup_app_routes(app)
    response = TestClient(app).get("/api/runtime/capabilities")
    assert response.status_code == 200
    return response.json()


def test_runtime_capabilities_hide_desktop_panels_on_linux(monkeypatch):
    payload = _capabilities_for_platform(monkeypatch, "linux")

    assert payload["platform"] == "linux"
    assert payload["features"]["browserPanel"] is False
    assert payload["features"]["sandboxPanel"] is False
    assert payload["features"]["openFileLocation"] is False
    assert payload["features"]["tauriFilePicker"] is False


def test_runtime_capabilities_keep_desktop_panels_on_windows(monkeypatch):
    payload = _capabilities_for_platform(monkeypatch, "win32", desktop=True)

    assert payload["platform"] == "windows"
    assert payload["features"]["browserPanel"] is True
    assert payload["features"]["sandboxPanel"] is True
    assert payload["features"]["openFileLocation"] is True
    assert payload["features"]["tauriFilePicker"] is True


def test_runtime_capabilities_enable_native_file_actions_on_linux_desktop(monkeypatch):
    payload = _capabilities_for_platform(monkeypatch, "linux", desktop=True)

    assert payload["platform"] == "linux"
    assert payload["shell"] == "desktop"
    assert payload["features"]["browserPanel"] is False
    assert payload["features"]["sandboxPanel"] is False
    assert payload["features"]["openFileLocation"] is True
    assert payload["features"]["tauriFilePicker"] is True
