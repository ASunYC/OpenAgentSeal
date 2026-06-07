"""Persistent conversation context compaction for web chat sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import tiktoken

from open_agent.app.runner.models import Message
from open_agent.schema import Message as AgentMessage


COMPACTION_META_KEY = "context_compaction"
COMPACTION_SUMMARY_PREFIX = "[Conversation Context Summary]"
DEFAULT_TOKEN_LIMIT = 60_000
DEFAULT_KEEP_RECENT_MESSAGES = 12
MAX_COMPACTION_INPUT_CHARS = 180_000
MAX_MESSAGE_CHARS = 12_000


@dataclass
class CompactionResult:
    state: dict[str, Any]
    before_tokens: int
    after_tokens: int
    compacted_messages: int


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
        keep_recent_messages: int = DEFAULT_KEEP_RECENT_MESSAGES,
    ):
        self.token_limit = max(8_000, int(token_limit))
        self.keep_recent_messages = max(4, int(keep_recent_messages))

    async def compact_if_needed(
        self,
        messages: list[Message],
        llm: Any,
        existing_state: dict[str, Any] | None = None,
    ) -> CompactionResult | None:
        state = existing_state if isinstance(existing_state, dict) else {}
        effective_history = build_effective_history(messages, state)
        before_tokens = estimate_messages_tokens(effective_history)
        if before_tokens < self.token_limit:
            return None

        unsummarized = messages_after_cutoff(messages, state.get("through_message_id"))
        compactable = unsummarized[: -self.keep_recent_messages]
        if len(compactable) < 2:
            return None

        previous_summary = str(state.get("summary") or "").strip()
        transcript, compacted_batch = _render_messages(compactable)
        if len(compacted_batch) < 2:
            return None
        prompt = (
            "Create an accurate, compact continuation summary for an AI agent conversation. "
            "The original chat remains stored, but only this summary and recent messages will be "
            "sent to the model.\n\n"
            "Preserve:\n"
            "- user goals, constraints, preferences, and corrections\n"
            "- decisions already made and why\n"
            "- completed work, important tool results, file paths, commands, and errors\n"
            "- unresolved tasks and the exact next actions\n"
            "- identities of relevant agents, models, plugins, sessions, and workspaces\n\n"
            "Do not invent facts. Do not address the user. Use concise Chinese unless technical "
            "identifiers require their original form.\n\n"
        )
        if previous_summary:
            prompt += f"PREVIOUS SUMMARY:\n{previous_summary}\n\n"
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

        next_state = {
            "version": 1,
            "summary": summary,
            "through_message_id": compacted_batch[-1].id,
            "compaction_count": int(state.get("compaction_count") or 0) + 1,
            "compacted_message_count": int(state.get("compacted_message_count") or 0)
            + len(compacted_batch),
            "last_compacted_messages": len(compacted_batch),
            "before_tokens": before_tokens,
            "updated_at": datetime.now().isoformat(),
        }
        after_tokens = estimate_messages_tokens(build_effective_history(messages, next_state))
        next_state["after_tokens"] = after_tokens
        return CompactionResult(
            state=next_state,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            compacted_messages=len(compacted_batch),
        )
