<picture>
  <source
    width="100%"
    srcset="./docs/images/banner.avif"
    media="(prefers-color-scheme: dark)"
  />
  <source
    width="100%"
    srcset="./docs/images/banner.avif"
    media="(prefers-color-scheme: light), (prefers-color-scheme: no-preference)"
  />
  <img width="250" src="./docs/images/banner.avif" />
</picture>

<h1 align="center">🦭 OpenAgentSeal</h1>

<p align="center">A flexible Python-based AI Agent framework providing complete Agent execution loop, tool system, memory system, and multi-LLM integration.</p>

> 💡 **TypeScript Version**: If you need the TypeScript/Node.js version, check out [OpenAgentSeal-JS](https://github.com/ASunYC/OpenAgentSeal-JS)

<p align="center">
  <a href="https://github.com/ASunYC/OpenAgentSeal/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/ASunYC/OpenAgentSeal.svg?style=flat&colorA=080f12&colorB=1fa669" alt="License">
  </a>
  <a href="https://github.com/ASunYC/OpenAgentSeal">
    <img src="https://img.shields.io/github/stars/ASunYC/OpenAgentSeal?style=flat&colorA=080f12&colorB=1fa669" alt="Stars">
  </a>
  <a href="https://github.com/ASunYC/OpenAgentSeal/issues">
    <img src="https://img.shields.io/github/issues/ASunYC/OpenAgentSeal?style=flat&colorA=080f12&colorB=1fa669" alt="Issues">
  </a>
  <a href="https://pypi.org/project/open-agent/">
    <img src="https://img.shields.io/pypi/v/open-agent.svg?style=flat&colorA=080f12&colorB=1fa669" alt="PyPI">
  </a>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#development-guide">Development Guide</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#api-reference">API Reference</a>
</p>

---

## Features

### Core Features

- ✅ **Agent Execution Loop** - Support for multi-turn conversations and tool calling
- ✅ **Multi-LLM Support** - Support for Anthropic, OpenAI, DeepSeek, MiniMax, Volcano Engine, Qwen, Zhipu AI, and more
- ✅ **Streaming Response** - SSE streaming output with real-time AI responses
- ✅ **Tool System** - File operations, command execution, note taking, MCP tools, Claude Skills
- ✅ **Chain of Thought (CoT)** - ReAct mode with step-by-step reasoning
- ✅ **Memory System** - Tree-structured memory with SQLite backend and temporal graph RAG
- ✅ **Task Queue** - Priority scheduling and concurrency control
- ✅ **Logging System** - Tiered logging with automatic rotation

### Advanced Features

- ✅ **MCP Protocol** - Support for Model Context Protocol tools
- ✅ **ACP Protocol** - Agent Communication Protocol for external integration
- ✅ **System Tray** - Background running with tray minimization

### Web UI (Vue3)

- ✅ **Streaming Chat** - Real-time AI response display
- ✅ **Model Switching** - Support for multiple model configurations
- ✅ **Thinking Process** - Display CoT reasoning steps
- ✅ **Settings Panel** - User/Model/Agent/MCP/Skill/Workspace configuration
- ✅ **Overview Canvas** - Agent status visualization

---

## Quick Start

### 1. Installation

```bash
# Clone the project
git clone https://github.com/ASunYC/OpenAgentSeal.git
cd OpenAgentSeal

# Install with uv (recommended)
pip install uv
uv sync

# Or install with pip
pip install -e .
```

### 2. Configure Model

The model configuration wizard will start automatically on first run:

```bash
open-agent
```

Or manually configure `~/.open-agent/models.yaml`:

```yaml
models:
  - id: anthropic-claude
    name: claude-3-5-sonnet-20241022
    display_name: Anthropic Claude
    provider: anthropic
    api_key: your-api-key
    base_url: https://api.anthropic.com
    provider_type: anthropic
    is_default: true
```

### 3. Run

```bash
# Interactive mode (default)
open-agent

# Specify workspace directory
open-agent --workspace /path/to/workspace

# Single task execution
open-agent --task "Create a Python script"

# CLI only mode
open-agent --cli-only

# Web UI only mode
open-agent --web-only --port 9998

# ACP service mode
open-agent-acp --port 8080
```

Visit Web UI at: http://127.0.0.1:9998

---

## Development Guide

### Project Structure

```
OpenAgentSeal/
├── open_agent/               # Main package
│   ├── agent.py              # Agent core class
│   ├── master_agent.py       # Master Agent
│   ├── agent_service.py      # Agent service layer
│   ├── cli.py                # CLI entry point
│   ├── config.py             # Configuration management
│   ├── memory_manager.py     # Memory manager
│   ├── logger.py             # Logging system
│   ├── retry.py              # Retry mechanism
│   ├── tray.py               # System tray
│   ├── user_config.py        # User configuration
│   ├── llm/                  # LLM clients
│   │   ├── anthropic_client.py
│   │   ├── openai_client.py
│   │   └── llm_wrapper.py
│   ├── tools/                # Tool system
│   │   ├── bash_tool.py      # Bash execution
│   │   ├── file_tools.py     # File operations
│   │   ├── note_tool.py      # Note taking
│   │   ├── mcp_loader.py     # MCP tool loading
│   │   ├── skill_tool.py     # Skills tool
│   │   └── web_search.py     # Web search
│   ├── task_queue/           # Task queue
│   │   ├── dispatcher.py
│   │   ├── queue.py
│   │   └── worker.py
│   ├── app/                  # Web UI
│   │   ├── runner/           # Runner module
│   │   └── web/              # Vue3 frontend
│   ├── acp/                  # ACP protocol
│   │   └── server.py
│   ├── skills/               # Claude Skills
│   └── config/               # Configuration files
│       ├── config.yaml
│       └── mcp.json
├── tests/                    # Test suite
├── docs/                     # Documentation
├── workspace/                # Default workspace
├── pyproject.toml            # Project configuration
└── VERSION.md                # Version history
```

### Development Mode

```bash
# Install dev dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Format code
uv run ruff format .

# Type check
uv run mypy open_agent
```

### Adding New Tools

```python
from open_agent.tools.base import Tool, ToolResult
from pydantic import BaseModel

class MyToolArgs(BaseModel):
    input: str

class MyTool(Tool):
    name = "my_tool"
    description = "My custom tool"
    parameters = MyToolArgs

    async def execute(self, args: MyToolArgs) -> ToolResult:
        return ToolResult(
            success=True,
            content=f"Result: {args.input}"
        )
```

### Configuration Files

#### config.yaml

```yaml
llm:
  api_key: ${ANTHROPIC_API_KEY}
  api_base: https://api.anthropic.com
  model: claude-3-5-sonnet-20241022
  provider: anthropic

agent:
  max_steps: 100
  workspace_dir: ./workspace

tools:
  enable_file_tools: true
  enable_bash: true
  enable_note: true
  enable_skills: true
  enable_mcp: true
  enable_web_search: false
```

#### mcp.json

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    }
  }
}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Vue3 Web UI                             │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ ChatView │  │ SettingsPanel│  │   OverviewCanvas     │  │
│  └──────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │ WebSocket
┌─────────────────────────▼───────────────────────────────────┐
│                    FastAPI Server                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Agent   │  │  Runner  │  │  Memory  │  │   Task   │   │
│  │ Service  │  │ Manager  │  │ Manager  │  │  Queue   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Tools   │  │   LLM    │  │  Logger  │  │   ACP    │   │
│  │ System   │  │  Client  │  │          │  │ Server   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## API Reference

### Python SDK

```python
from open_agent import Agent, LLMClient
from open_agent.schema import LLMProvider

# Create LLM client
llm_client = LLMClient(
    api_key="your-api-key",
    api_base="https://api.anthropic.com",
    model="claude-3-5-sonnet-20241022",
    provider=LLMProvider.ANTHROPIC
)

# Create Agent
agent = Agent(
    llm_client=llm_client,
    tools=["read", "write", "edit", "bash", "note"],
    workspace_dir="./workspace"
)

# Synchronous chat
response = await agent.chat("Hello, please help me create a file")

# Streaming chat
async for chunk in agent.stream_chat("Hello"):
    print(chunk, end="", flush=True)
```

### ACP Protocol

```bash
# Start ACP service
open-agent-acp --port 8080

# Connect via ACP-compatible client
# Connect through Agent Client Protocol compatible clients
```

---

## Supported LLM Providers

| Provider | Protocol | Description |
|----------|----------|-------------|
| Anthropic | anthropic | Claude series |
| OpenAI | openai | GPT series |
| DeepSeek | anthropic/openai | DeepSeek series |
| MiniMax | anthropic | MiniMax series |
| Qwen | openai | Alibaba Cloud |
| Zhipu AI | anthropic | GLM series |
| Volcano Engine | anthropic | Doubao series |
| Moonshot | anthropic | Moonshot |
| Baichuan | openai | Baichuan |
| SiliconFlow | openai | Multi-model proxy |

---

## Skills System

Built-in Claude Skills:

- **document-skills** - Document processing (PDF, DOCX, XLSX, PPTX)
- **mcp-builder** - MCP server building
- **webapp-testing** - Web application automation testing

---

## Version History

See [VERSION.md](./VERSION.md) for details.

Current version: **2026.3.30**

---

## Contact & Collaboration

Welcome to join our community!

- 📧 **Email**: [452212601@qq.com](mailto:452212601@qq.com)
- 💬 **QQ**: 452212601
- 🐛 **Issues**: [GitHub Issues](https://github.com/ASunYC/OpenAgentSeal/issues)

---

## License

MIT License

---

<p align="center">
  Made with ❤️ by OpenAgentSeal Team
</p>