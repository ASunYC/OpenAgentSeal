from pathlib import Path

import pytest

from open_agent.agent import Agent
from open_agent.schema import FunctionCall, LLMResponse, TokenUsage, ToolCall
from open_agent.tools.base import Tool, ToolResult


class LoopTool(Tool):
    @property
    def name(self) -> str:
        return "loop"

    @property
    def description(self) -> str:
        return "Keep the test agent running"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, content="continue")


class LoopingLLM:
    def __init__(self):
        self.calls: list[list[Tool] | None] = []

    async def generate(self, messages, tools):
        self.calls.append(tools)
        if tools is None:
            return LLMResponse(
                content="Partial work is summarized here.",
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
            )
        return LLMResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=[
                ToolCall(
                    id="call-1",
                    type="function",
                    function=FunctionCall(name="loop", arguments={}),
                )
            ],
        )


@pytest.mark.asyncio
async def test_iteration_limit_requests_one_tool_free_final_response(tmp_path: Path):
    llm = LoopingLLM()
    agent = Agent(
        llm_client=llm,
        system_prompt="system",
        tools=[LoopTool()],
        max_steps=1,
        workspace_dir=str(tmp_path),
    )
    agent.add_user_message("keep working")

    result = await agent.run()

    assert result == "Partial work is summarized here."
    assert len(llm.calls) == 2
    assert llm.calls[0]
    assert llm.calls[1] is None
    assert agent.messages[-1].role == "assistant"
    assert agent.messages[-1].content == result
    assert agent.session_total_tokens == 25
    assert not any(
        message.role == "user" and "configured safety limit" in str(message.content)
        for message in agent.messages
    )
