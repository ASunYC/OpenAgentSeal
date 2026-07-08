from unittest.mock import MagicMock, patch

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
