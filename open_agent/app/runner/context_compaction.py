"""Persistent conversation context compaction for web chat sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import tiktoken

from open_agent.app.runner.models import Message
from open_agent.app.runner.context_store import ContextBlock, ContextBlockStore, get_context_block_store
from open_agent.schema import Message as AgentMessage


COMPACTION_META_KEY = "context_compaction"
COMPACTION_SUMMARY_PREFIX = "[Conversation Context Summary]"
CCR_CONTEXT_PREFIX = "[Reversible Compressed Context]"
DEFAULT_TOKEN_LIMIT = 1_000_000
DEFAULT_TRIGGER_LIMIT = 1_000_000
DEFAULT_KEEP_RECENT_MESSAGES = 12
MAX_COMPACTION_INPUT_CHARS = 180_000
MAX_MESSAGE_CHARS = 12_000


@dataclass
class CompactionResult:
    state: dict[str, Any]
    before_tokens: int
    after_tokens: int
    compacted_messages: int
    ref_id: str | None = None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")


def estimate_text_tokens(text: str) -> int:
    try:
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, int(len(text) / 2.5))


def estimate_messages_tokens(messages: Iterable[Message | AgentMessage]) -> int:
    total = 0
    for message in messages:
        total += estimate_text_tokens(_content_text(message.content)) + 4
        thinking = getattr(message, "thinking", None)
        if thinking:
            total += estimate_text_tokens(str(thinking))
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            total += estimate_text_tokens(str(tool_calls))
    return total


def messages_after_cutoff(
    messages: list[Message],
    through_message_id: str | None,
) -> list[Message]:
    if not through_message_id:
        return list(messages)
    for index, message in enumerate(messages):
        if message.id == through_message_id:
            return messages[index + 1 :]
    return list(messages)


def _has_cutoff(messages: list[Message], through_message_id: str | None) -> bool:
    return bool(through_message_id) and any(
        message.id == through_message_id for message in messages
    )


def build_effective_history(
    messages: list[Message],
    state: dict[str, Any] | None,
) -> list[AgentMessage]:
    state = state if isinstance(state, dict) else {}
    blocks = _state_blocks(state)
    through_message_id = _state_through_message_id(state, blocks)
    cutoff_valid = _has_cutoff(messages, through_message_id)
    tail = messages_after_cutoff(messages, through_message_id if cutoff_valid else None)
    history: list[AgentMessage] = []

    if blocks and cutoff_valid:
        rendered_blocks = []
        for block in blocks:
            ref_id = str(block.get("ref_id") or "").strip()
            summary = str(block.get("summary") or block.get("compressed_text") or "").strip()
            if not ref_id or not summary:
                continue
            rendered_blocks.append(
                f"ref: {ref_id}\n"
                f"covered_messages: {', '.join(block.get('message_ids') or [])}\n"
                f"summary:\n{summary}\n"
                "If exact details are needed, call retrieve_context with this ref."
            )
        if rendered_blocks:
            history.append(
                AgentMessage(
                    role="user",
                    content=(
                        f"{CCR_CONTEXT_PREFIX}\n"
                        "These blocks represent earlier conversation history in compressed form. "
                        "Treat them as context, not as a new user request. The original text is "
                        "stored locally and can be retrieved with the retrieve_context tool.\n\n"
                        + "\n\n---\n\n".join(rendered_blocks)
                    ),
                )
            )
    elif cutoff_valid:
        summary = str(state.get("summary") or "").strip()
        if summary:
            history.append(
                AgentMessage(
                    role="user",
                    content=(
                        f"{COMPACTION_SUMMARY_PREFIX}\n"
                        "This summary represents earlier conversation history. Treat it as context, "
                        "not as a new user request.\n\n"
                        f"{summary}"
                    ),
                )
            )

    for message in tail:
        if message.role not in {"user", "assistant"}:
            continue
        text = _content_text(message.content).strip()
        if text:
            history.append(AgentMessage(role=message.role, content=text))
    return history


def _state_blocks(state: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = state.get("blocks")
    if isinstance(blocks, list):
        return [block for block in blocks if isinstance(block, dict)]
    return []


def _state_through_message_id(
    state: dict[str, Any],
    blocks: list[dict[str, Any]] | None = None,
) -> str | None:
    blocks = blocks if blocks is not None else _state_blocks(state)
    for block in reversed(blocks):
        through = str(block.get("through_message_id") or "").strip()
        if through:
            return through
    return state.get("through_message_id")


def _legacy_summary_history(
    messages: list[Message],
    state: dict[str, Any],
) -> list[AgentMessage]:
    through_message_id = state.get("through_message_id")
    cutoff_valid = _has_cutoff(messages, through_message_id)
    summary = str(state.get("summary") or "").strip() if cutoff_valid else ""
    tail = messages_after_cutoff(messages, through_message_id if cutoff_valid else None)
    history: list[AgentMessage] = []
    if summary:
        history.append(
            AgentMessage(
                role="user",
                content=(
                    f"{COMPACTION_SUMMARY_PREFIX}\n"
                    "This summary represents earlier conversation history. Treat it as context, "
                    "not as a new user request.\n\n"
                    f"{summary}"
                ),
            )
        )
    for message in tail:
        if message.role not in {"user", "assistant"}:
            continue
        text = _content_text(message.content).strip()
        if text:
            history.append(AgentMessage(role=message.role, content=text))
    return history


def _render_messages(messages: list[Message]) -> tuple[str, list[Message]]:
    chunks: list[str] = []
    included: list[Message] = []
    remaining = MAX_COMPACTION_INPUT_CHARS
    for message in messages:
        text = _content_text(message.content).strip()
        if not text:
            continue
        if len(text) > MAX_MESSAGE_CHARS:
            half = MAX_MESSAGE_CHARS // 2
            text = f"{text[:half]}\n...[message truncated for compaction]...\n{text[-half:]}"
        chunk = f"{message.role.upper()}:\n{text}\n"
        if len(chunk) > remaining:
            break
        chunks.append(chunk)
        included.append(message)
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return "\n".join(chunks), included


class ContextCompactor:
    def __init__(
        self,
        token_limit: int = DEFAULT_TOKEN_LIMIT,
        trigger_token_limit: int | None = None,
        keep_recent_messages: int = DEFAULT_KEEP_RECENT_MESSAGES,
        store: ContextBlockStore | None = None,
        session_id: str = "",
        profile_id: str | None = None,
    ):
        self.token_limit = max(8_000, int(token_limit))
        self.trigger_token_limit = max(
            self.token_limit,
            int(trigger_token_limit or token_limit or DEFAULT_TRIGGER_LIMIT),
        )
        self.keep_recent_messages = max(4, int(keep_recent_messages))
        self.store = store or get_context_block_store()
        self.session_id = session_id
        self.profile_id = profile_id or "main"

    async def compact_if_needed(
        self,
        messages: list[Message],
        llm: Any,
        existing_state: dict[str, Any] | None = None,
    ) -> CompactionResult | None:
        state = existing_state if isinstance(existing_state, dict) else {}
        effective_history = build_effective_history(messages, state)
        before_tokens = estimate_messages_tokens(effective_history)
        if before_tokens < self.trigger_token_limit:
            return None

        blocks = _state_blocks(state)
        unsummarized = messages_after_cutoff(messages, _state_through_message_id(state, blocks))
        compactable = unsummarized[: -self.keep_recent_messages]
        if len(compactable) < 2:
            return None

        transcript, compacted_batch = _render_messages(compactable)
        if len(compacted_batch) < 2:
            return None
        prompt = (
            "Create an accurate, compact CCR context block for an AI agent conversation. "
            "The original chat remains stored locally and can be retrieved later by ref_id; "
            "only your compressed text plus the ref_id will be sent to the model.\n\n"
            "Preserve:\n"
            "- user goals, constraints, preferences, and corrections\n"
            "- decisions already made and why\n"
            "- completed work, important tool results, file paths, commands, and errors\n"
            "- unresolved tasks and the exact next actions\n"
            "- identities of relevant agents, models, plugins, sessions, and workspaces\n\n"
            "Do not invent facts. Do not address the user. Use concise Chinese unless technical "
            "identifiers require their original form.\n\n"
        )
        previous_summary = str(state.get("summary") or "").strip()
        if previous_summary and not blocks:
            prompt += f"PREVIOUS LEGACY SUMMARY:\n{previous_summary}\n\n"
        prompt += f"NEW HISTORY TO MERGE:\n{transcript}"

        response = await llm.generate(
            messages=[
                AgentMessage(
                    role="system",
                    content=(
                        "You compress conversation history for another AI agent. Produce a durable "
                        "handoff summary that lets the next model continue without asking the user "
                        "to repeat established context."
                    ),
                ),
                AgentMessage(role="user", content=prompt),
            ]
        )
        summary = str(response.content or "").strip()
        if not summary:
            return None

        original_text, _ = _render_messages(compacted_batch)
        message_ids = [message.id for message in compacted_batch]
        block: ContextBlock = self.store.put_block(
            session_id=self.session_id,
            profile_id=self.profile_id,
            through_message_id=compacted_batch[-1].id,
            message_ids=message_ids,
            original_text=original_text,
            compressed_text=summary,
            token_before=estimate_messages_tokens(compacted_batch),
            token_after=estimate_text_tokens(summary),
        )

        next_blocks = [
            *blocks,
            {
                "ref_id": block.ref_id,
                "summary": summary,
                "compressed_text": summary,
                "through_message_id": block.through_message_id,
                "message_ids": message_ids,
                "token_before": block.token_before,
                "token_after": block.token_after,
                "created_at": block.created_at,
            },
        ]

        next_state = {
            "version": 2,
            "blocks": next_blocks,
            "through_message_id": compacted_batch[-1].id,
            "compaction_count": int(state.get("compaction_count") or 0) + 1,
            "compacted_message_count": int(state.get("compacted_message_count") or 0)
            + len(compacted_batch),
            "last_compacted_messages": len(compacted_batch),
            "before_tokens": before_tokens,
            "last_ref_id": block.ref_id,
            "updated_at": datetime.now().isoformat(),
        }
        after_tokens = estimate_messages_tokens(build_effective_history(messages, next_state))
        next_state["after_tokens"] = after_tokens
        return CompactionResult(
            state=next_state,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            compacted_messages=len(compacted_batch),
            ref_id=block.ref_id,
        )
