from unittest.mock import AsyncMock, patch

import httpx
import pytest

import open_agent.app._app as app_module


def _test_app():
    app_module._app = None
    with patch("open_agent.app.mobile.is_remote_api_request_allowed", return_value=True):
        return app_module.create_app()


@pytest.mark.asyncio
async def test_mcp_check_endpoint_uses_posted_server_config():
    check_result = {
        "success": False,
        "status": "error",
        "name": "drawio",
        "type": "stdio",
        "message": "Working directory is not valid: C:/missing",
    }

    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch(
            "open_agent.tools.mcp_loader.check_mcp_server_async",
            new=AsyncMock(return_value=check_result),
        ) as check_server:
            response = await client.post(
                "/api/mcp/check",
                json={
                    "server": {
                        "name": "drawio",
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@next-ai-drawio/mcp-server@latest"],
                        "cwd": "C:/missing",
                    }
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload == check_result
    check_server.assert_awaited_once()
    name, server = check_server.await_args.args
    assert name == "drawio"
    assert server["cwd"] == "C:/missing"
