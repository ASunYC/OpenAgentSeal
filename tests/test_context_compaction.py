from types import SimpleNamespace

import pytest

from open_agent.app.runner.context_compaction import (
    COMPACTION_SUMMARY_PREFIX,
    ContextCompactor,
    build_effective_history,
    messages_after_cutoff,
)
from open_agent.app.runner.manager import ChatManager
from open_agent.app.runner.models import Message
from open_agent.app.runner.runner import AgentRunner
from open_agent.schema import Message as AgentMessage
from open_agent.user_config import (
    AppSettings,
    ModelConfig,
    infer_model_context_window,
    model_auto_compact_token_limit,
    resolve_model_context_window,
)


class SummaryLLM:
    def __init__(self):
        self.calls = []

    async def generate(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content="用户要求持续完成工程；已修改配置；下一步运行测试。")


def _long_history(count: int = 20) -> list[Message]:
    messages = []
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append(
            Message(
                role=role,
                content=f"message-{index} " + ("context " * 1200),
            )
        )
    return messages


def test_build_effective_history_keeps_summary_and_tail():
    messages = [
        Message(id="m1", role="user", content="old question"),
        Message(id="m2", role="assistant", content="old answer"),
        Message(id="m3", role="user", content="recent question"),
    ]
    state = {"summary": "Earlier work summary", "through_message_id": "m2"}

    history = build_effective_history(messages, state)

    assert len(history) == 2
    assert history[0].role == "user"
    assert COMPACTION_SUMMARY_PREFIX in history[0].content
    assert "Earlier work summary" in history[0].content
    assert history[1].content == "recent question"


def test_missing_cutoff_does_not_drop_messages():
    messages = [
        Message(id="m1", role="user", content="one"),
        Message(id="m2", role="assistant", content="two"),
    ]

    assert messages_after_cutoff(messages, "missing") == messages
    history = build_effective_history(
        messages,
        {"summary": "stale summary", "through_message_id": "missing"},
    )
    assert [message.content for message in history] == ["one", "two"]


def test_context_compaction_settings_default_and_clamp():
    defaults = AppSettings.from_dict({})
    clamped = AppSettings.from_dict(
        {
            "auto_context_compaction": False,
            "context_compaction_token_limit": 100,
        }
    )

    assert defaults.auto_context_compaction is True
    assert defaults.context_compaction_token_limit == 60000
    assert clamped.auto_context_compaction is False
    assert clamped.context_compaction_token_limit == 8000


def test_model_context_window_resolution_and_compaction_threshold():
    manual = ModelConfig(
        id="manual",
        name="custom-model",
        display_name="Custom",
        provider="custom",
        api_key="",
        context_window=200_000,
        context_window_source="manual",
    )
    inferred = ModelConfig(
        id="moonshot",
        name="moonshot-v1-128k",
        display_name="Moonshot",
        provider="moonshot",
        api_key="",
    )
    unknown = ModelConfig(
        id="unknown",
        name="qwen3.6-plus",
        display_name="Qwen",
        provider="qwen",
        api_key="",
    )

    assert infer_model_context_window("moonshot-v1-32k") == 32_000
    assert resolve_model_context_window(manual) == (200_000, "manual")
    assert resolve_model_context_window(inferred) == (128_000, "catalog")
    assert resolve_model_context_window(unknown, 60_000) == (60_000, "fallback")
    assert model_auto_compact_token_limit(128_000) == 115_200


@pytest.mark.asyncio
async def test_compaction_persists_cutoff_and_preserves_recent_messages():
    messages = _long_history()
    llm = SummaryLLM()
    compactor = ContextCompactor(token_limit=8_000, keep_recent_messages=4)

    result = await compactor.compact_if_needed(messages, llm)

    assert result is not None
    assert len(llm.calls) == 1
    assert result.compacted_messages == 16
    assert result.state["through_message_id"] == messages[15].id
    assert result.state["compaction_count"] == 1
    effective = build_effective_history(messages, result.state)
    assert len(effective) == 5
    assert effective[-1].content.startswith("message-19")
    assert result.after_tokens < result.before_tokens


@pytest.mark.asyncio
async def test_existing_summary_is_merged_incrementally():
    messages = _long_history(28)
    llm = SummaryLLM()
    state = {
        "summary": "Previous durable summary",
        "through_message_id": messages[7].id,
        "compaction_count": 1,
        "compacted_message_count": 8,
    }
    compactor = ContextCompactor(token_limit=8_000, keep_recent_messages=4)

    result = await compactor.compact_if_needed(messages, llm, state)

    assert result is not None
    prompt = llm.calls[0][1].content
    assert "Previous durable summary" in prompt
    assert result.state["compaction_count"] == 2
    assert result.state["compacted_message_count"] > 8


def test_runner_restores_summary_without_replacing_persisted_messages(tmp_path):
    manager = ChatManager(storage_dir=tmp_path)
    messages = [
        Message(id="m1", role="user", content="old question"),
        Message(id="m2", role="assistant", content="old answer"),
        Message(id="m3", role="user", content="recent question"),
    ]
    manager.replace_messages("session-test", messages)
    agent = SimpleNamespace(
        system_prompt="system",
        messages=[AgentMessage(role="system", content="system")],
    )

    AgentRunner()._restore_agent_history(
        agent,
        "session-test",
        manager,
        compaction_state={
            "summary": "Durable earlier summary",
            "through_message_id": "m2",
        },
        auto_compaction_enabled=True,
    )

    assert [message.role for message in agent.messages] == ["system", "user", "user"]
    assert "Durable earlier summary" in agent.messages[1].content
    assert agent.messages[2].content == "recent question"
    assert [message.id for message in manager.get_messages("session-test")] == [
        "m1",
        "m2",
        "m3",
    ]
