import tempfile
import unittest

from open_agent.agent import Agent
from open_agent.schema import FunctionCall, LLMResponse, ToolCall
from open_agent.tools.base import Tool, ToolResult
from open_agent.tools.file_tools import WriteTool
from open_agent.tools.registry import ToolCapability, ToolRegistry, ToolRisk, build_tool_registry


class DummyTool(Tool):
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "dummy"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, *args, **kwargs) -> ToolResult:
        return ToolResult(success=True, content="ok")


class FakeLLM:
    def __init__(self, arguments=None):
        self.calls = 0
        self.stream_callback = None
        self.retry_callback = None
        self.arguments = arguments or {"path": "blocked.txt", "content": "no"}

    async def generate(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tool_1",
                        type="function",
                        function=FunctionCall(name="write_file", arguments=dict(self.arguments)),
                    )
                ],
                finish_reason="tool_use",
            )
        return LLMResponse(content="done", finish_reason="stop")


class TestToolRegistry(unittest.TestCase):
    def test_infers_metadata_and_projects_schema(self):
        registry = build_tool_registry([DummyTool("read_file"), DummyTool("write_file"), DummyTool("bash")])
        schemas = {schema["name"]: schema for schema in registry.schemas(toolset="cli")}

        self.assertEqual(schemas["read_file"]["x_open_agent"]["risk"], ToolRisk.LOW.value)
        self.assertEqual(schemas["write_file"]["x_open_agent"]["risk"], ToolRisk.MEDIUM.value)
        self.assertTrue(schemas["write_file"]["x_open_agent"]["approval_required"])
        self.assertIn(ToolCapability.EXECUTE.value, schemas["bash"]["x_open_agent"]["capabilities"])

    def test_toolset_filtering(self):
        registry = build_tool_registry([DummyTool("bash"), DummyTool("read_file")])
        self.assertEqual({entry.tool.name for entry in registry.list("cli")}, {"bash", "read_file"})
        self.assertEqual({entry.tool.name for entry in registry.list("cron")}, set())

    def test_hard_blocks_dangerous_shell_commands(self):
        registry = build_tool_registry([DummyTool("bash")])
        allowed, reason = registry.check_call("bash", {"command": "rm -rf /"}, approved=True)

        self.assertFalse(allowed)
        self.assertIn("hard-blocked", reason)

    def test_approval_required_tools_are_rejected_without_approval(self):
        registry = build_tool_registry([DummyTool("bash"), DummyTool("write_file")])

        bash_allowed, bash_reason = registry.check_call("bash", {"command": "pwd"})
        write_allowed, write_reason = registry.check_call("write_file", {"path": "x", "content": "y"})
        approved_allowed, approved_reason = registry.check_call("bash", {"command": "pwd"}, approved=True)

        self.assertFalse(bash_allowed)
        self.assertIn("requires approval", bash_reason)
        self.assertFalse(write_allowed)
        self.assertIn("requires approval", write_reason)
        self.assertTrue(approved_allowed)
        self.assertIsNone(approved_reason)

    def test_unknown_tool_is_rejected(self):
        registry = ToolRegistry()
        allowed, reason = registry.check_call("missing", {})

        self.assertFalse(allowed)
        self.assertIn("not registered", reason)


async def test_agent_enforces_registry_policy_before_tool_execution():
    with tempfile.TemporaryDirectory() as workspace:
        agent = Agent(
            llm_client=FakeLLM(),
            system_prompt="test",
            tools=[WriteTool(workspace_dir=workspace)],
            max_steps=2,
            workspace_dir=workspace,
        )
        agent.add_user_message("write a file")

        result = await agent.run()

        assert result == "done"
        assert "requires approval" in agent.messages[-2].content


async def test_agent_rejects_model_supplied_approval_flag():
    with tempfile.TemporaryDirectory() as workspace:
        agent = Agent(
            llm_client=FakeLLM({"path": "blocked.txt", "content": "no", "_approved": True}),
            system_prompt="test",
            tools=[WriteTool(workspace_dir=workspace)],
            max_steps=2,
            workspace_dir=workspace,
        )
        agent.add_user_message("write a file")

        result = await agent.run()

        assert result == "done"
        assert "cannot be supplied" in agent.messages[-2].content


if __name__ == "__main__":
    unittest.main()
