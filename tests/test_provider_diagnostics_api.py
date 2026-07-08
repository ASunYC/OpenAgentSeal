from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import open_agent.app._app as app_module
from open_agent.user_config import ModelConfig


def _test_app():
    app_module._app = None
    with patch("open_agent.app.mobile.is_remote_api_request_allowed", return_value=True):
        return app_module.create_app()


@pytest.mark.asyncio
async def test_saved_model_diagnostics_endpoint_returns_registry_report():
    model = ModelConfig(
        id="model_volcano",
        name="glm-5-2-260617",
        display_name="Volcano GLM",
        provider="volcano",
        api_key="test-key",
        base_url="",
        provider_type="",
    )
    manager = MagicMock()
    manager.get_model.return_value = model

    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch("open_agent.user_config.get_user_config", return_value=manager):
            response = await client.get("/api/model-configs/model_volcano/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["diagnostic"]["status"] == "ok"
    assert payload["diagnostic"]["route"]["provider"] == "volcano"


@pytest.mark.asyncio
async def test_provider_preview_diagnostics_endpoint_uses_post_body():
    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/providers/ark/diagnostics",
            json={
                "model": "glm-5-2-260617",
                "api_key": "test-key",
                "base_url": "",
                "provider_type": "",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["diagnostic"]["status"] == "ok"
    assert payload["diagnostic"]["route"]["api_base"] == (
        "https://ark.cn-beijing.volces.com/api/coding/v3"
    )


@pytest.mark.asyncio
async def test_saved_model_live_test_endpoint_returns_registry_report():
    model = ModelConfig(
        id="model_volcano",
        name="glm-5-2-260617",
        display_name="Volcano GLM",
        provider="volcano",
        api_key="test-key",
        base_url="",
        provider_type="",
    )
    manager = MagicMock()
    manager.get_model.return_value = model
    live_report = {
        "status": "ok",
        "id": "model_volcano",
        "display_name": "Volcano GLM",
        "route": {"provider": "volcano", "model": "glm-5-2-260617"},
        "checks": {"live_request": {"status": "ok", "message": "Provider responded successfully."}},
    }

    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch("open_agent.user_config.get_user_config", return_value=manager), patch(
            "open_agent.provider_registry.ProviderRegistry.test_model_config",
            new=AsyncMock(return_value=live_report),
        ) as live_test:
            response = await client.post("/api/model-configs/model_volcano/live-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["live_test"]["status"] == "ok"
    live_test.assert_awaited_once_with(model)


@pytest.mark.asyncio
async def test_provider_preview_live_test_endpoint_uses_post_body():
    live_report = {
        "status": "error",
        "id": "preview_ark",
        "display_name": "glm-5-2-260617",
        "route": {"provider": "volcano", "model": "glm-5-2-260617"},
        "checks": {"live_request": {"status": "error", "category": "api_key"}},
    }

    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch(
            "open_agent.provider_registry.ProviderRegistry.test_model_config",
            new=AsyncMock(return_value=live_report),
        ) as live_test:
            response = await client.post(
                "/api/providers/ark/live-test",
                json={
                    "model": "glm-5-2-260617",
                    "api_key": "test-key",
                    "base_url": "",
                    "provider_type": "",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["live_test"]["id"] == "preview_ark"
    live_test.assert_awaited_once()
    model = live_test.await_args.args[0]
    assert model.provider == "ark"
    assert model.name == "glm-5-2-260617"
    assert model.api_key == "test-key"
