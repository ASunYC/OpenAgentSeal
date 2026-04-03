"""Test the 4-step decision flow for tool selection.

This test verifies that the agent correctly uses MCP tools for drawing
instead of trying to install packages like pillow/numpy.

Expected behavior:
1. Agent recognizes drawing task
2. Agent finds MCP drawing tools (draw.io)
3. Agent uses MCP tool directly (NOT install packages)
"""

import asyncio
from pathlib import Path

from open_agent import LLMClient
from open_agent.agent import Agent
from open_agent.schema import LLMProvider
from open_agent.tools.file_tools import ReadTool, WriteTool, EditTool
from open_agent.tools.bash_tool import BashTool
from open_agent.tools.mcp_loader import load_mcp_tools_async, cleanup_mcp_connections
from open_agent.tools.skill_tool import create_skill_tools
from open_agent.tools.choice_tool import AskUserChoiceTool


async def test_draw_lion():
    """Test that agent uses MCP tools for drawing."""
    print("\n" + "=" * 80)
    print("Testing: Draw a Lion (MCP Tool Usage)")
    print("=" * 80)
    
    # Model configuration
    api_key = "sk-cp-U1Eog8D_ra3OVvLAgv4QqFYmC7LAJHK2FXc02nY0cNYGz_g4U_4aRA7FEPEdhqwuOY6ZmuYrPe-A90_ntcrfmfwEpwLb2HkDGDrv5BBUALd8gInF_AMSGOg"
    base_url = "https://api.minimaxi.com"
    model = "MiniMax-M2.5"
    
    # Workspace
    workspace_dir = Path("./workspace/test_draw")
    workspace_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📁 Workspace: {workspace_dir}")
    
    # Initialize LLM client
    llm_client = LLMClient(
        api_key=api_key,
        provider=LLMProvider.ANTHROPIC,
        api_base=base_url,
        model=model,
    )
    print(f"✅ LLM Client: {model}")
    
    # Initialize tools
    tools = []
    
    # Basic tools
    tools.append(ReadTool(workspace_dir=str(workspace_dir)))
    tools.append(WriteTool(workspace_dir=str(workspace_dir)))
    tools.append(EditTool(workspace_dir=str(workspace_dir)))
    tools.append(BashTool(workspace_dir=str(workspace_dir)))
    print("✅ Basic tools loaded")
    
    # Load MCP tools
    print("\n📦 Loading MCP tools...")
    mcp_config_path = Path("open_agent/config/mcp.json")
    if mcp_config_path.exists():
        mcp_tools = await load_mcp_tools_async(str(mcp_config_path))
        tools.extend(mcp_tools)
        print(f"✅ Loaded {len(mcp_tools)} MCP tools")
    else:
        print("⚠️ MCP config not found")
    
    # Load Skills tools
    print("\n📚 Loading Skills...")
    skills_dir = Path("open_agent/skills")
    if skills_dir.exists():
        skill_tools, _ = create_skill_tools(str(skills_dir))
        tools.extend(skill_tools)
        print(f"✅ Skills tools loaded")
    
    # Add choice tool for interactive selection
    tools.append(AskUserChoiceTool(timeout=30))
    print("✅ Choice tool loaded")
    
    # Load system prompt
    system_prompt_path = Path("open_agent/config/system_prompt.md")
    system_prompt = system_prompt_path.read_text(encoding="utf-8") if system_prompt_path.exists() else "You are a helpful assistant."
    print(f"✅ System prompt loaded")
    
    # Create agent
    agent = Agent(
        llm_client=llm_client,
        system_prompt=system_prompt,
        tools=tools,
        max_steps=20,
        workspace_dir=str(workspace_dir),
    )
    
    # Task
    task = "帮我画一个小狮子的png图片，保存到 workspace 目录"
    print(f"\n🎯 Task: {task}")
    print("-" * 80)
    
    # Run agent
    agent.add_user_message(task)
    
    try:
        result = await agent.run()
        
        print("\n" + "=" * 80)
        print("📊 Test Result")
        print("=" * 80)
        
        # Check tools used
        used_tools = []
        for msg in agent.messages:
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    used_tools.append(tc.function.name)
        
        print(f"🔧 Tools used: {used_tools}")
        
        # Check result
        if any("create_new_diagram" in t or "start_session" in t for t in used_tools):
            print("\n✅ SUCCESS: Agent used MCP tools for drawing!")
        else:
            print("\n⚠️ Agent did not use MCP drawing tools")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(lambda _loop, _ctx: None)
        try:
            await cleanup_mcp_connections()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(test_draw_lion())