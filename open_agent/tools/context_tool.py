"""Tools for retrieving reversible compressed context."""

from __future__ import annotations

from typing import Any

from open_agent.app.runner.context_store import get_context_block_store
from open_agent.tools.base import Tool, ToolResult


class RetrieveContextTool(Tool):
    """Retrieve original text for a CCR context reference."""

    def __init__(self, session_id: str, profile_id: str | None = None):
        self.session_id = session_id
        self.profile_id = profile_id or "main"

    @property
    def name(self) -> str:
        return "retrieve_context"

    @property
    def description(self) -> str:
        return (
            "Retrieve the original, uncompressed text for a ctx:// context reference. "
            "Use this when a compressed context block mentions details you need to answer accurately."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ref_id": {
                    "type": "string",
                    "description": "The ctx:// reference shown in compressed conversation context.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional keyword to focus the returned original text.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return. Defaults to 12000.",
                    "default": 12000,
                },
            },
            "required": ["ref_id"],
        }

    async def execute(
        self,
        ref_id: str,
        query: str | None = None,
        max_chars: int = 12000,
    ) -> ToolResult:
        ref_id = str(ref_id or "").strip()
        if not ref_id.startswith("ctx://"):
            return ToolResult(success=False, error="ref_id must start with ctx://")

        block = get_context_block_store().get_block(ref_id, session_id=self.session_id)
        if not block:
            return ToolResult(
                success=False,
                error=f"Context reference not found for this session: {ref_id}",
            )

        text = block.original_text
        query = str(query or "").strip()
        if query:
            text = self._focused_excerpt(text, query)

        max_chars = max(1000, min(int(max_chars or 12000), 50000))
        clipped = text[:max_chars]
        if len(text) > max_chars:
            clipped += "\n\n[truncated; call retrieve_context again with a query or larger max_chars if needed]"

        header = (
            f"[Original context]\n"
            f"ref: {block.ref_id}\n"
            f"session: {block.session_id}\n"
            f"messages: {', '.join(block.message_ids)}\n\n"
        )
        return ToolResult(success=True, content=header + clipped)

    def _focused_excerpt(self, text: str, query: str) -> str:
        lower_text = text.lower()
        lower_query = query.lower()
        index = lower_text.find(lower_query)
        if index < 0:
            return text
        radius = 6000
        start = max(0, index - radius)
        end = min(len(text), index + len(query) + radius)
        prefix = "[excerpt]\n" if start > 0 or end < len(text) else ""
        return prefix + text[start:end]
