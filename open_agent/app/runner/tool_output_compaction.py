"""CCR-style compression for large tool outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from open_agent.app.runner.context_compaction import estimate_text_tokens
from open_agent.app.runner.context_store import ContextBlockStore, get_context_block_store


DEFAULT_TOOL_OUTPUT_TOKEN_LIMIT = 8_000
DEFAULT_TOOL_OUTPUT_KEEP_CHARS = 6_000


@dataclass
class ToolOutputCompaction:
    content: str
    ref_id: str
    before_tokens: int
    after_tokens: int


def _compress_tool_output_text(
    text: str,
    *,
    tool_name: str,
    before_tokens: int,
    max_chars: int = DEFAULT_TOOL_OUTPUT_KEEP_CHARS,
) -> str:
    lines = text.splitlines()
    head_lines = lines[:80]
    tail_lines = lines[-80:] if len(lines) > 80 else []
    head = "\n".join(head_lines)
    tail = "\n".join(tail_lines)
    if len(head) > max_chars // 2:
        head = head[: max_chars // 2]
    if len(tail) > max_chars // 2:
        tail = tail[-max_chars // 2 :]

    parts = [
        "[Large Tool Output Summary]",
        f"tool: {tool_name}",
        "status: original tool call succeeded; this is a compressed view for context only",
        f"original_tokens_estimate: {before_tokens}",
        f"original_lines: {len(lines)}",
        "",
        "head:",
        head.strip(),
    ]
    if tail and tail.strip() != head.strip():
        parts.extend(["", "tail:", tail.strip()])
    parts.append(
        "\nThe full original output is stored locally. "
        "Call retrieve_context(ref_id) if exact omitted lines are needed."
    )
    return "\n".join(parts).strip()


def compact_tool_output_if_needed(
    *,
    content: str,
    tool_name: str,
    session_id: str,
    profile_id: str | None = None,
    token_limit: int = DEFAULT_TOOL_OUTPUT_TOKEN_LIMIT,
    store: ContextBlockStore | None = None,
    metadata: dict[str, Any] | None = None,
) -> ToolOutputCompaction | None:
    if not content:
        return None
    before_tokens = estimate_text_tokens(content)
    if before_tokens <= token_limit:
        return None

    store = store or get_context_block_store()
    compressed = _compress_tool_output_text(
        content,
        tool_name=tool_name,
        before_tokens=before_tokens,
    )
    block = store.put_block(
        session_id=session_id,
        profile_id=profile_id or "main",
        through_message_id=str((metadata or {}).get("tool_call_id") or ""),
        message_ids=[],
        kind="tool_output",
        original_text=content,
        compressed_text=compressed,
        token_before=before_tokens,
        token_after=estimate_text_tokens(compressed),
    )
    compacted_content = (
        f"{compressed}\n\n"
        f"ref: {block.ref_id}\n"
        "Use retrieve_context with this ref to inspect the original full tool output."
    )
    return ToolOutputCompaction(
        content=compacted_content,
        ref_id=block.ref_id,
        before_tokens=before_tokens,
        after_tokens=estimate_text_tokens(compacted_content),
    )
