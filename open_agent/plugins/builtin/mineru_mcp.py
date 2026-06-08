"""In-process MCP server exposed by the bundled MinerU plugin."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from open_agent.plugins import get_plugin_manager
from open_agent.plugins.builtin.mineru_service import (
    MINERU_PLUGIN_ID,
    MinerUError,
    MinerUService,
)

_server: FastMCP | None = None


def _service() -> MinerUService:
    manager = get_plugin_manager()
    config = manager.load_config()
    plugin_config = config.get("plugins", {}).get(MINERU_PLUGIN_ID)
    if not isinstance(plugin_config, dict):
        raise MinerUError("Install the MinerU plugin before using its tools")
    if not plugin_config.get("enabled", True):
        raise MinerUError("The MinerU plugin is disabled")
    settings = manager.get_plugin_settings(MINERU_PLUGIN_ID, reveal_secrets=True)
    return MinerUService(
        api_url=str(settings.get("api_url") or ""),
        api_token=str(settings.get("api_token") or ""),
        translation_model_id=str(settings.get("translation_model_id") or ""),
        target_language=str(settings.get("target_language") or ""),
    )


def get_mineru_mcp_server() -> FastMCP:
    global _server
    if _server is not None:
        return _server

    server = FastMCP(
        "OpenAgentSeal MinerU",
        instructions=(
            "Parse documents with MinerU and optionally translate them using the "
            "translation model selected in OpenAgentSeal Plugin Management."
        ),
        stateless_http=True,
        streamable_http_path="/",
        json_response=True,
    )

    @server.tool()
    async def mineru_parse_document(
        file_path: str,
        add_to_library: bool = True,
    ):
        """Parse a local PDF, Office document, or image into structured Markdown."""
        result = await _service().parse_document(
            Path(file_path),
            add_to_library=add_to_library,
        )
        return json.dumps(result.to_dict(), ensure_ascii=False)

    @server.tool()
    async def mineru_translate_document(
        file_path: str,
        target_language: str = "",
        add_to_library: bool = True,
    ):
        """Parse and translate a local document, producing translated Markdown and PDF."""
        result = await _service().translate_document(
            Path(file_path),
            target_language=target_language or None,
            add_to_library=add_to_library,
        )
        return json.dumps(result.to_dict(), ensure_ascii=False)

    @server.tool()
    async def mineru_configuration_status():
        """Check whether the MinerU plugin connection and translation model are configured."""
        manager = get_plugin_manager()
        settings = manager.get_plugin_settings(
            MINERU_PLUGIN_ID,
            reveal_secrets=True,
        )
        payload = {
            "api_url_configured": bool(settings.get("api_url")),
            "api_token_configured": bool(settings.get("api_token")),
            "translation_model_configured": bool(
                settings.get("translation_model_id")
            ),
            "target_language": settings.get("target_language"),
        }
        return json.dumps(payload, ensure_ascii=False)

    _server = server
    return server
