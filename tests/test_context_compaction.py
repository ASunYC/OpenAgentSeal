from types import SimpleNamespace
import time

import pytest

from open_agent.app.runner.context_compaction import (
    COMPACTION_SUMMARY_PREFIX,
    CCR_CONTEXT_PREFIX,
    ContextCompactor,
    build_effective_history,
    messages_after_cutoff,
)
from open_agent.app.runner.context_store import ContextBlockStore
from open_agent.app.runner.manager import ChatManager
from open_agent.app.runner.models import Message
from open_agent.app.runner.runner import AgentRunner
from open_agent.app.runner.tool_output_compaction import compact_tool_output_if_needed
from open_agent.schema import Message as AgentMessage
from open_agent.tools.context_tool import RetrieveContextTool
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
    assert defaults.context_compaction_token_limit == 1_000_000
    assert AppSettings.from_dict({"context_compaction_token_limit": 60_000}).context_compaction_token_limit == 1_000_000
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
    assert infer_model_context_window("qwen3.6-plus") == 1_000_000
    assert resolve_model_context_window(manual) == (200_000, "manual")
    assert resolve_model_context_window(inferred) == (128_000, "catalog")
    assert resolve_model_context_window(unknown, 60_000) == (1_000_000, "catalog")
    assert model_auto_compact_token_limit(128_000) == 115_200


@pytest.mark.asyncio
async def test_compaction_persists_cutoff_and_preserves_recent_messages(tmp_path):
    messages = _long_history()
    llm = SummaryLLM()
    store = ContextBlockStore(tmp_path / "context.db")
    compactor = ContextCompactor(
        token_limit=8_000,
        keep_recent_messages=4,
        store=store,
        session_id="session-test",
    )

    result = await compactor.compact_if_needed(messages, llm)

    assert result is not None
    assert result.ref_id and result.ref_id.startswith("ctx://")
    assert len(llm.calls) == 1
    assert result.compacted_messages == 16
    assert result.state["through_message_id"] == messages[15].id
    assert result.state["compaction_count"] == 1
    assert result.state["blocks"][0]["ref_id"] == result.ref_id
    block = store.get_block(result.ref_id, session_id="session-test")
    assert block is not None
    assert "message-0" in block.original_text
    effective = build_effective_history(messages, result.state)
    assert len(effective) == 5
    assert CCR_CONTEXT_PREFIX in effective[0].content
    assert result.ref_id in effective[0].content
    assert effective[-1].content.startswith("message-19")
    assert result.after_tokens < result.before_tokens


def test_context_block_store_lists_blocks_by_session(tmp_path):
    store = ContextBlockStore(tmp_path / "context.db")
    first = store.put_block(
        session_id="session-list",
        profile_id="main",
        through_message_id="m1",
        message_ids=["m1"],
        original_text="first original",
        compressed_text="first summary",
        token_before=100,
        token_after=10,
    )
    time.sleep(0.001)
    second = store.put_block(
        session_id="session-list",
        profile_id="main",
        through_message_id="m2",
        message_ids=["m2"],
        original_text="second original",
        compressed_text="second summary",
        token_before=200,
        token_after=20,
    )
    store.put_block(
        session_id="other-session",
        profile_id="main",
        through_message_id="m3",
        message_ids=["m3"],
        original_text="other original",
        compressed_text="other summary",
        token_before=300,
        token_after=30,
    )

    blocks = store.list_blocks("session-list")

    assert [block.ref_id for block in blocks] == [second.ref_id, first.ref_id]
    assert blocks[0].compressed_text == "second summary"


@pytest.mark.asyncio
async def test_existing_summary_is_merged_incrementally(tmp_path):
    messages = _long_history(28)
    llm = SummaryLLM()
    store = ContextBlockStore(tmp_path / "context.db")
    state = {
        "summary": "Previous durable summary",
        "through_message_id": messages[7].id,
        "compaction_count": 1,
        "compacted_message_count": 8,
    }
    compactor = ContextCompactor(
        token_limit=8_000,
        keep_recent_messages=4,
        store=store,
        session_id="session-test",
    )

    result = await compactor.compact_if_needed(messages, llm, state)

    assert result is not None
    prompt = llm.calls[0][1].content
    assert "Previous durable summary" in prompt
    assert result.state["compaction_count"] == 2
    assert result.state["compacted_message_count"] > 8
    assert result.state["blocks"][0]["ref_id"].startswith("ctx://")


@pytest.mark.asyncio
async def test_retrieve_context_tool_returns_original_block_text(tmp_path):
    messages = _long_history()
    llm = SummaryLLM()
    store = ContextBlockStore(tmp_path / "context.db")
    compactor = ContextCompactor(
        token_limit=8_000,
        keep_recent_messages=4,
        store=store,
        session_id="session-test",
    )

    result = await compactor.compact_if_needed(messages, llm)
    assert result and result.ref_id

    from open_agent.app.runner import context_store as context_store_module

    original_store = context_store_module._store
    context_store_module._store = store
    try:
        tool = RetrieveContextTool(session_id="session-test")
        output = await tool.execute(result.ref_id, query="message-4")
    finally:
        context_store_module._store = original_store

    assert output.success is True
    assert "message-4" in output.content
    assert "ctx://" in output.content


@pytest.mark.asyncio
async def test_large_tool_output_is_reversible_context_block(tmp_path):
    store = ContextBlockStore(tmp_path / "context.db")
    full_output = "\n".join(
        [f"{index:05d} important tool output line" for index in range(9000)]
    )

    compacted = compact_tool_output_if_needed(
        content=full_output,
        tool_name="bash",
        session_id="session-tool",
        profile_id="main",
        token_limit=1_000,
        store=store,
        metadata={"tool_call_id": "call_1"},
    )

    assert compacted is not None
    assert compacted.ref_id.startswith("ctx://")
    assert "Large Tool Output Summary" in compacted.content
    assert len(compacted.content) < len(full_output)

    from open_agent.app.runner import context_store as context_store_module

    original_store = context_store_module._store
    context_store_module._store = store
    try:
        tool = RetrieveContextTool(session_id="session-tool")
        output = await tool.execute(compacted.ref_id, query="08999")
    finally:
        context_store_module._store = original_store

    assert output.success is True
    assert "08999 important tool output line" in output.content


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


@pytest.mark.asyncio
async def test_ccr_keeps_original_messages_for_larger_model_rebuild(tmp_path):
    manager = ChatManager(storage_dir=tmp_path / "sessions")
    original_messages = _long_history(24)
    manager.replace_messages("session-resize", [m.model_copy(deep=True) for m in original_messages])

    store = ContextBlockStore(tmp_path / "context.db")
    result = await ContextCompactor(
        token_limit=8_000,
        keep_recent_messages=4,
        store=store,
        session_id="session-resize",
    ).compact_if_needed(manager.get_messages("session-resize"), SummaryLLM())

    assert result is not None
    assert manager.get_messages("session-resize")[0].content == original_messages[0].content
    assert len(manager.get_messages("session-resize")) == len(original_messages)

    rebuilt_for_small_model = build_effective_history(
        manager.get_messages("session-resize"),
        result.state,
    )
    rebuilt_for_large_model = build_effective_history(
        manager.get_messages("session-resize"),
        None,
    )

    assert CCR_CONTEXT_PREFIX in rebuilt_for_small_model[0].content
    assert rebuilt_for_large_model[0].content.startswith("message-0")
    assert len(rebuilt_for_large_model) == len(original_messages)
