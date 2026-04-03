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

<p align="center">一个基于 Python 的灵活 AI Agent 框架，提供完整的 Agent 执行循环、工具系统、记忆系统和多 LLM 集成。</p>

> 💡 **TypeScript 版本**: 如果你需要 TypeScript/Node.js 版本，请查看 [OpenAgentSeal-JS](https://github.com/ASunYC/OpenAgentSeal-JS)

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
  <a href="#功能特性">功能特性</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#开发指南">开发指南</a> •
  <a href="#架构设计">架构设计</a> •
  <a href="#api-参考">API 参考</a>
</p>

---

## 功能特性

### 核心功能

- ✅ **Agent 执行循环** - 支持多轮对话和工具调用
- ✅ **多 LLM 支持** - 支持 Anthropic、OpenAI、DeepSeek、MiniMax、火山引擎、通义千问、智谱 AI 等
- ✅ **流式响应** - SSE 流式输出，实时显示 AI 回复
- ✅ **工具系统** - 文件操作、命令执行、笔记记录、MCP 工具、Claude Skills
- ✅ **思维链 (CoT)** - ReAct 模式，逐步推理，展示思考过程
- ✅ **记忆系统** - 树状记忆结构，SQLite 后端，支持时序图 RAG
- ✅ **任务队列** - 优先级调度，并发控制
- ✅ **日志系统** - 分级日志，自动轮转

### 高级功能

- ✅ **MCP 协议** - 支持 Model Context Protocol 工具
- ✅ **ACP 协议** - Agent Communication Protocol，外部集成支持
- ✅ **系统托盘** - 后台运行，最小化到托盘

### Web UI (Vue3)

- ✅ **流式对话** - 实时显示 AI 回复
- ✅ **模型切换** - 支持多模型配置和切换
- ✅ **思考过程** - 展示 CoT 推理步骤
- ✅ **设置面板** - 用户/模型/Agent/MCP/技能/工作区配置
- ✅ **概览画布** - Agent 状态可视化

---

## 快速开始

### 1. 安装

```bash
# 克隆项目
git clone https://github.com/ASunYC/OpenAgentSeal.git
cd OpenAgentSeal

# 使用 uv 安装 (推荐)
pip install uv
uv sync

# 或使用 pip 安装
pip install -e .
```

### 2. 配置模型

首次运行会自动启动模型配置向导：

```bash
open-agent
```

或手动配置 `~/.open-agent/models.yaml`：

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

### 3. 运行

```bash
# 交互模式 (默认)
open-agent

# 指定工作目录
open-agent --workspace /path/to/workspace

# 单任务执行
open-agent --task "创建一个 Python 脚本"

# 仅 CLI 模式
open-agent --cli-only

# 仅 Web UI 模式
open-agent --web-only --port 9998

# ACP 服务模式
open-agent-acp --port 8080
```

访问 Web UI: http://127.0.0.1:9998

---

## 开发指南

### 项目结构

```
OpenAgentSeal/
├── open_agent/               # 主包
│   ├── agent.py              # Agent 核心类
│   ├── master_agent.py       # Master Agent
│   ├── agent_service.py      # Agent 服务层
│   ├── cli.py                # 命令行入口
│   ├── config.py             # 配置管理
│   ├── memory_manager.py     # 记忆管理器
│   ├── logger.py             # 日志系统
│   ├── retry.py              # 重试机制
│   ├── tray.py               # 系统托盘
│   ├── user_config.py        # 用户配置
│   ├── llm/                  # LLM 客户端
│   │   ├── anthropic_client.py
│   │   ├── openai_client.py
│   │   └── llm_wrapper.py
│   ├── tools/                # 工具系统
│   │   ├── bash_tool.py      # Bash 执行
│   │   ├── file_tools.py     # 文件操作
│   │   ├── note_tool.py      # 笔记工具
│   │   ├── mcp_loader.py     # MCP 工具加载
│   │   ├── skill_tool.py     # Skills 工具
│   │   └── web_search.py     # Web 搜索
│   ├── task_queue/           # 任务队列
│   │   ├── dispatcher.py
│   │   ├── queue.py
│   │   └── worker.py
│   ├── app/                  # Web UI
│   │   ├── runner/           # Runner 模块
│   │   └── web/              # Vue3 前端
│   ├── acp/                  # ACP 协议
│   │   └── server.py
│   ├── skills/               # Claude Skills
│   └── config/               # 配置文件
│       ├── config.yaml
│       └── mcp.json
├── tests/                    # 测试套件
├── docs/                     # 文档
├── workspace/                # 默认工作目录
├── pyproject.toml            # 项目配置
└── VERSION.md                # 版本历史
```

### 开发模式

```bash
# 安装开发依赖
uv sync --all-extras

# 运行测试
uv run pytest

# 代码格式化
uv run ruff format .

# 类型检查
uv run mypy open_agent
```

### 添加新工具

```python
from open_agent.tools.base import Tool, ToolResult
from pydantic import BaseModel

class MyToolArgs(BaseModel):
    input: str

class MyTool(Tool):
    name = "my_tool"
    description = "我的自定义工具"
    parameters = MyToolArgs

    async def execute(self, args: MyToolArgs) -> ToolResult:
        return ToolResult(
            success=True,
            content=f"结果：{args.input}"
        )
```

### 配置文件

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

## 架构设计

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

## API 参考

### Python SDK

```python
from open_agent import Agent, LLMClient
from open_agent.schema import LLMProvider

# 创建 LLM 客户端
llm_client = LLMClient(
    api_key="your-api-key",
    api_base="https://api.anthropic.com",
    model="claude-3-5-sonnet-20241022",
    provider=LLMProvider.ANTHROPIC
)

# 创建 Agent
agent = Agent(
    llm_client=llm_client,
    tools=["read", "write", "edit", "bash", "note"],
    workspace_dir="./workspace"
)

# 同步对话
response = await agent.chat("你好，请帮我创建一个文件")

# 流式对话
async for chunk in agent.stream_chat("你好"):
    print(chunk, end="", flush=True)
```

### ACP 协议

```bash
# 启动 ACP 服务
open-agent-acp --port 8080

# ACP 客户端连接
# 通过 Agent Client Protocol 兼容的客户端连接
```

---

## 支持的 LLM 提供商

| 提供商 | 协议 | 说明 |
|--------|------|------|
| Anthropic | anthropic | Claude 系列 |
| OpenAI | openai | GPT 系列 |
| DeepSeek | anthropic/openai | DeepSeek 系列 |
| MiniMax | anthropic | MiniMax 系列 |
| 通义千问 | openai | 阿里云 |
| 智谱 AI | anthropic | GLM 系列 |
| 火山引擎 | anthropic | 豆包系列 |
| 月之暗面 | anthropic | Moonshot |
| 百川 | openai | Baichuan |
| 硅基流动 | openai | 多模型代理 |

---

## Skills 系统

项目内置丰富的 Claude Skills：

- **document-skills** - 文档处理 (PDF, DOCX, XLSX, PPTX)
- **mcp-builder** - MCP 服务器构建
- **webapp-testing** - Web 应用自动化测试

---

## 版本历史

详见 [VERSION.md](./VERSION.md)

当前版本：**2026.3.30**

---

## 合作交流

欢迎加入我们的社区，一起交流讨论！

- 📧 **邮箱**: [452212601@qq.com](mailto:452212601@qq.com)
- 💬 **QQ**: 452212601
- 🐛 **问题反馈**: [GitHub Issues](https://github.com/ASunYC/OpenAgentSeal/issues)

---

## 许可证

MIT License

---

<p align="center">
  Made with ❤️ by OpenAgentSeal Team
</p>