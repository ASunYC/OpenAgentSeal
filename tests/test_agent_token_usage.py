from pathlib import Path

import pytest

from open_agent.agent import Agent
from open_agent.schema import LLMResponse, TokenUsage


class UsageLLM:
    def __init__(self, usages: list[TokenUsage]):
        self.usages = iter(usages)

    async def generate(self, messages, tools):
        return LLMResponse(
            content="done",
            finish_reason="stop",
            usage=next(self.usages),
        )


@pytest.mark.asyncio
async def test_agent_accumulates_and_resets_session_token_usage(tmp_path: Path):
    agent = Agent(
        llm_client=UsageLLM(
            [
                TokenUsage(prompt_tokens=100, completion_tokens=25, total_tokens=125),
                TokenUsage(prompt_tokens=180, completion_tokens=40, total_tokens=220),
            ]
        ),
        system_prompt="system",
        tools=[],
        workspace_dir=str(tmp_path),
    )

    agent.add_user_message("first")
    await agent.run()
    agent.add_user_message("second")
    await agent.run()

    assert agent.api_total_tokens == 220
    assert agent.session_prompt_tokens == 280
    assert agent.session_completion_tokens == 65
    assert agent.session_total_tokens == 345
    assert agent.estimate_context_tokens() > 0

    agent.reset_session_usage()
    assert agent.api_total_tokens == 0
    assert agent.session_prompt_tokens == 0
    assert agent.session_completion_tokens == 0
    assert agent.session_total_tokens == 0
