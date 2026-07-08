from pathlib import Path

import pytest

from open_agent.agent import Agent
from open_agent.app.runner.context_store import ContextBlockStore
from open_agent.app.runner.tool_output_compaction import compact_tool_output_if_needed
from open_agent.tools.base import Tool, ToolContext, ToolResult
from open_agent.tools.context_tool import RetrieveContextTool


class CaptureContextTool(Tool):
    @property
    def name(self) -> str:
        return "capture_context"

    @property
    def description(self) -> str:
        return "Capture the currently bound tool context."

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        context = self.require_context()
        return ToolResult(
            success=True,
            content=f"{context.session_id}|{context.profile_id}|{context.workspace_dir}",
        )


def test_agent_binds_tool_context_with_current_runtime_identity(tmp_path):
    tool = CaptureContextTool()
    agent = Agent(
        llm_client=object(),
        system_prompt="system",
        tools=[tool],
        workspace_dir=str(tmp_path),
    )
    agent.session_id = "session-tool-context"
    agent.profile_id = "coder"

    context = agent._bind_tool_context(tool)

    assert isinstance(context, ToolContext)
    assert context.session_id == "session-tool-context"
    assert context.profile_id == "coder"
    assert context.workspace_dir == tmp_path.resolve()
    assert tool.context == context


@pytest.mark.asyncio
async def test_retrieve_context_tool_uses_bound_context_session(tmp_path):
    store = ContextBlockStore(tmp_path / "context.db")
    compacted = compact_tool_output_if_needed(
        content="\n".join(f"{index:04d} retained output" for index in range(2000)),
        tool_name="bash",
        session_id="session-bound",
        profile_id="main",
        token_limit=500,
        store=store,
        metadata={"tool_call_id": "call_1"},
    )
    assert compacted is not None

    from open_agent.app.runner import context_store as context_store_module

    original_store = context_store_module._store
    context_store_module._store = store
    try:
        tool = RetrieveContextTool()
        tool.bind_context(
            ToolContext(
                session_id="session-bound",
                profile_id="main",
                workspace_dir=Path(tmp_path),
            )
        )
        output = await tool.execute(compacted.ref_id, query="1999")
    finally:
        context_store_module._store = original_store

    assert output.success is True
    assert "1999 retained output" in output.content
