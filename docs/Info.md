# OpenAgent 模块信息文档

> 本文档记录 open_agent 目录中所有模块的功能和职责
> 生成时间: 2026-03-14

## 目录结构总览

```
open_agent/
├── __init__.py              # 包入口
├── __main__.py              # 命令行入口 (python -m open_agent)
├── agent.py                 # 核心 Agent 实现
├── agent_service.py         # Agent 服务管理 (单例模式)
├── cli.py                   # 命令行界面
├── config.py                # 配置管理
├── logger.py                # 日志记录器
├── log_memory_worker.py     # 日志内存压缩工作器
├── master_agent.py          # 主 Agent (整合任务队列和子 Agent)
├── memory_manager.py        # 记忆管理器 (SQLite)
├── retry.py                 # 重试机制
├── tray.py                  # 系统托盘应用
├── user_config.py           # 用户配置管理
│
├── acp/                     # ACP (Agent Communication Protocol)
│   ├── __init__.py
│   └── server.py            # ACP 服务器
│
├── app/                     # Web 应用 (FastAPI)
│   ├── __init__.py
│   ├── _app.py              # FastAPI 应用入口
│   ├── static/              # 静态文件
│   ├── web/                 # Web UI (Vue3)
│   └── runner/              # Runner 模式
│       ├── __init__.py
│       ├── api.py           # Chat API 路由
│       ├── manager.py       # ChatManager
│       ├── models.py        # 数据模型
│       └── runner.py        # AgentRunner
│
├── config/                  # 配置文件
│   ├── config-example.yaml  # 配置示例
│   ├── mcp-example.json     # MCP 配置示例
│   └── system_prompt.md     # 系统提示词
│
├── llm/                     # LLM 客户端
│   ├── __init__.py
│   ├── base.py              # 基础接口
│   ├── llm_wrapper.py       # LLM 包装器
│   ├── openai_client.py     # OpenAI 客户端
│   └── anthropic_client.py  # Anthropic 客户端
│
├── schema/                  # 数据模型
│   ├── __init__.py
│   └── schema.py            # Pydantic 模型
│
├── skills/                  # Skills 目录
│   ├── README.md
│   ├── agent_skills_spec.md
│   └── [各种 skill 目录...]
│
├── sub_agent/               # 子 Agent 系统
│   ├── __init__.py
│   ├── manager.py           # SubAgentManager
│   ├── roles.py             # 角色注册表
│   ├── session.py           # 会话管理
│   ├── ui.py                # UI 相关
│   └── workspace.py         # 工作区管理
│
├── task_queue/              # 任务队列系统
│   ├── __init__.py
│   ├── dispatcher.py        # 任务调度器
│   ├── queue.py             # 任务队列
│   ├── task.py              # 任务定义
│   └── worker.py            # 工作线程池
│
├── tools/                   # 工具层
│   ├── __init__.py
│   ├── base.py              # 工具基类
│   ├── bash_tool.py         # Bash 命令工具
│   ├── choice_tool.py       # 选择工具
│   ├── config_watcher.py    # 配置监视器
│   ├── file_tools.py        # 文件操作工具
│   ├── mcp_loader.py        # MCP 工具加载器
│   ├── note_tool.py         # 笔记工具
│   ├── skill_loader.py      # Skill 加载器
│   ├── skill_tool.py        # Skill 工具
│   ├── sub_agent_tool.py    # 子 Agent 工具
│   └── web_search.py        # 网页搜索工具
│
└── utils/                   # 工具函数
    ├── __init__.py
    ├── path_utils.py        # 路径工具
    └── terminal_utils.py    # 终端工具
```

## 核心模块详解

### 1. Agent 核心层

#### `agent.py` - 核心 Agent 实现
- **职责**: 单 Agent 执行循环，处理 LLM 调用和工具执行
- **主要功能**:
  - LLM 调用与流式响应处理
  - 工具执行与结果处理
  - 消息历史管理与自动摘要
  - 取消机制 (cancel_event)
  - 状态回调 (status_callback)
  - Token 限制管理
- **关键类**: `Agent`, `Colors`

#### `master_agent.py` - 主 Agent
- **职责**: 整合任务队列和子 Agent 管理
- **主要功能**:
  - 任务提交到队列
  - 子 Agent 协调
  - 状态管理
- **关键类**: `MasterAgent`

#### `agent_service.py` - Agent 服务
- **职责**: Agent 实例的生命周期管理 (单例模式)
- **主要功能**:
  - 创建/销毁 Agent 实例
  - 会话生命周期管理
  - 状态回调通知
- **关键类**: `AgentService`

### 2. LLM 客户端层

#### `llm/` - LLM 客户端
- **`base.py`**: 基础接口定义
- **`llm_wrapper.py`**: LLM 包装器，统一接口
- **`openai_client.py`**: OpenAI API 客户端
- **`anthropic_client.py`**: Anthropic API 客户端
- **关键类**: `LLMClient`, `OpenAIClient`, `AnthropicClient`

### 3. 工具层

#### `tools/base.py` - 工具基类
- **职责**: 定义所有工具的接口
- **关键类**: `Tool`, `ToolResult`

#### `tools/bash_tool.py` - Bash 工具
- **职责**: 执行 shell 命令
- **功能**: 支持后台进程、超时控制

#### `tools/file_tools.py` - 文件工具
- **职责**: 文件读写操作
- **功能**: 读取、写入、编辑文件

#### `tools/note_tool.py` - 笔记工具
- **职责**: 管理会话笔记

#### `tools/skill_tool.py` - Skill 工具
- **职责**: 加载和执行 Skills

#### `tools/mcp_loader.py` - MCP 加载器
- **职责**: 加载 MCP (Model Context Protocol) 工具

#### `tools/sub_agent_tool.py` - 子 Agent 工具
- **职责**: 创建和管理子 Agent

### 4. 子 Agent 系统

#### `sub_agent/manager.py` - 子 Agent 管理器
- **职责**: 创建、管理、协调子 Agent
- **主要功能**:
  - 创建带角色的子 Agent
  - 独立线程执行
  - 生命周期管理
- **关键类**: `SubAgentManager`, `SubAgentWrapper`, `SubAgentInfo`

#### `sub_agent/roles.py` - 角色注册表
- **职责**: 定义子 Agent 角色
- **关键类**: `RoleRegistry`, `SubAgentRole`

#### `sub_agent/session.py` - 会话管理
- **职责**: 子 Agent 会话管理
- **关键类**: `SessionManager`, `Session`

#### `sub_agent/workspace.py` - 工作区管理
- **职责**: Git 工作区协调
- **功能**: 分支管理、冲突解决

### 5. 任务队列系统

#### `task_queue/dispatcher.py` - 任务调度器
- **职责**: 任务执行协调中心
- **主要功能**:
  - 管理任务队列和工作线程池
  - 协调主 Agent 任务委派
  - 子 Agent 创建和管理
  - 实时状态更新
- **关键类**: `TaskDispatcher`

#### `task_queue/queue.py` - 任务队列
- **职责**: 线程安全优先级队列
- **关键类**: `TaskQueue`

#### `task_queue/task.py` - 任务定义
- **职责**: 任务数据模型
- **关键类**: `Task`, `SubTask`, `TaskResult`, `TaskStatus`, `TaskPriority`

#### `task_queue/worker.py` - 工作线程池
- **职责**: 并行任务执行
- **关键类**: `WorkerPool`

### 6. 存储层

#### `memory_manager.py` - 记忆管理器
- **职责**: 树状记忆存储 (SQLite)
- **主要功能**:
  - 年/月/日树状结构
  - 关键词索引 + FTS5 全文搜索
  - 记忆压缩与重要性分级

**【规划】长期记忆增强 - 向量索引 + 时序 Graph RAG**

当前记忆管理器基于 SQLite 的 FTS5 全文搜索，计划增强为支持语义检索的向量索引和时序知识图谱：

**向量索引 (Vector Index)**
- 将记忆内容编码为向量嵌入 (Embeddings)
- 支持语义相似度搜索，超越关键词匹配
- 使用向量数据库 (如 ChromaDB、Pinecone 或 pgvector)
- 实现模糊记忆检索："我记得之前讨论过类似的问题..."

**时序 Graph RAG (Temporal Graph Retrieval-Augmented Generation)**

将知识存储为带时间戳的知识图谱，实现时序感知检索：

- **Graph (图结构)**:
  - 节点：实体 (如"苹果公司"、"iPhone 15")
  - 边：关系 (如"发布"、"营收")
  - 优势：理解实体间复杂关系，支持多跳推理

- **Temporal (时序)**:
  - 在知识图谱的边上打上时间戳
  - 明确知道"iPhone 15"是在"2023年"发布的
  - 检索时精准过滤过时信息

**工作流程**:
1. **构建**: 将文档解析为带时间戳的实体和关系，存入图数据库 (如 Neo4j)
2. **检索**: 用户提问时，系统先进行时间感知解析 (如"2024年")，然后在图谱中沿着时间线查找相关实体路径
3. **生成**: 将检索到的带时间上下文的结构化事实喂给 LLM，生成准确且有时序逻辑的答案

**技术栈规划**:
- 向量存储: ChromaDB / pgvector
- 图数据库: Neo4j / Kùzu (嵌入式)
- 实体抽取: LLM-based NER
- 关系抽取: 开源模型 (如 REBEL) 或 LLM

#### `logger.py` - 日志记录器
- **职责**: Agent 执行日志记录
- **关键类**: `AgentLogger`

#### `log_memory_worker.py` - 日志内存压缩
- **职责**: 自动压缩步骤日志
- **关键类**: `LogMemoryWorker`

### 7. Web 应用层

#### `app/` - 应用模块
- **`_app.py`**: FastAPI 应用入口，路由注册和中间件配置
- **`runner/`**: **Runner 模式实现 (新架构)**
  - `runner.py` - AgentRunner 类，处理流式响应
  - `api.py` - REST API 路由 (替代 WebSocket)
  - `manager.py` - ChatManager 会话管理
  - `models.py` - Pydantic 数据模型
  - `repo.py` - 数据仓库 (JSON 持久化)
- **`static/`**: 静态文件
- **`web/`**: Web 前端资源 (Vue3 + Vite)

**架构**:
- `app/runner/` - Runner 模式 (当前使用)
  - 通信协议: REST API + SSE
  - 前端技术: Vue3 + TypeScript
  - 会话管理: JSON 持久化
- `app/static/` - 静态文件服务

**状态**: ✅ 稳定运行

### 8. 用户界面层

#### `cli.py` - 命令行界面
- **职责**: 命令行交互
- **功能**: 交互式对话、配置管理

#### `tray.py` - 系统托盘
- **职责**: 系统托盘应用
- **功能**: 快速启动、状态显示

### 9. 配置与工具

#### `config.py` - 配置管理
- **职责**: 加载和管理配置

#### `user_config.py` - 用户配置
- **职责**: 用户级配置管理

#### `retry.py` - 重试机制
- **职责**: API 调用重试
- **关键类**: `RetryConfig`, `RetryExhaustedError`

#### `utils/` - 工具函数
- **`path_utils.py`**: 路径处理
- **`terminal_utils.py`**: 终端显示工具

### 10. ACP 协议层

#### `acp/server.py` - ACP 服务器
- **职责**: Agent Communication Protocol 服务器
- **功能**: 子 Agent 间通信

## 模块依赖关系

```
用户交互层 (CLI/Web/Tray)
    │
    ▼
服务层 (AgentService)
    │
    ▼
核心层 (MasterAgent)
    │
    ├──▶ 任务队列 (TaskDispatcher)
    │
    ├──▶ 子 Agent (SubAgentManager)
    │
    ▼
执行层 (Agent)
    │
    ├──▶ LLM 客户端
    │
    ├──▶ 工具层
    │
    ▼
存储层 (MemoryManager/Logger)
```

## 模块使用状态分析

### ✅ 活跃使用模块
1. `agent.py` - 核心 Agent 实现
2. `agent_service.py` - Agent 服务管理
3. `cli.py` - 命令行界面
4. `master_agent.py` - 主 Agent
5. `memory_manager.py` - 记忆管理
6. `logger.py` - 日志记录
7. `task_queue/` - 任务队列系统
8. `sub_agent/` - 子 Agent 系统 (manager.py, roles.py, session.py, workspace.py)
9. `tools/` - 工具层 (全部在用)
10. `llm/` - LLM 客户端 (全部在用)
11. `app/runner/` - Runner 模式 (Web UI)
12. `acp/` - ACP 协议 (在用，用于外部集成)

### ⚠️ 需要清理/整合的模块
1. **`sub_agent/ui.py`** - 终端 UI 相关，功能完整但未在主线使用
   - 建议: 保留但标记为实验性功能，或整合到 CLI 中

2. **`app/web/` 目录** - Vue3 前端项目
   - 当前状态: 存在但可能未完整集成
   - 建议: 完成与 Runner 模式的整合

### 🔄 架构演进

#### Web UI 架构 (当前使用)

**架构** (`app/`)
- `app/_app.py`: FastAPI 应用入口
- `app/runner/`: Runner 模式实现
  - `runner.py`: AgentRunner 类，处理流式响应
  - `api.py`: REST API 路由
  - `manager.py`: ChatManager 会话管理
  - `models.py`: Pydantic 数据模型
  - `repo.py`: 数据仓库 (JSON 持久化)
- `app/static/`: 静态文件
- `app/web/`: Web 前端资源 (Vue3 + Vite + TypeScript)

**技术栈**:
| 特性 | app/runner/ |
|------|-------------|
| 通信协议 | REST API + SSE |
| 前端技术 | Vue3 + TypeScript |
| 构建工具 | Vite |
| 会话管理 | JSON 持久化 |
| 会话历史 | 完整支持 |
| 状态 | ✅ 稳定运行 |

**历史变更**:
- 2026.03.18: Web UI 设置面板支持拖拽调整宽度 (500px-1600px)，默认 900px
- 2026.03.15: 删除 `web_ui/` 旧架构，完全迁移到 `app/runner/` 架构

## 代码优化建议

### 1. 导入优化
- 统一使用绝对导入 `from open_agent.xxx`
- 避免循环导入

### 2. 配置管理
- 统一配置入口，避免分散在多个文件
- `config.py` 和 `user_config.py` 职责需要明确区分

### 3. 错误处理
- 统一异常类型定义
- 添加更多上下文信息

### 4. 日志记录
- 统一使用 `logger = logging.getLogger(__name__)`
- 避免使用 `print` 直接输出

### 5. 类型注解
- 补充缺失的类型注解
- 使用 `from __future__ import annotations` 避免前向引用问题

## 最近变更

- 2026.03.23: SSE 事件流式传输修复
  - 修复 `app/runner/runner.py` 中事件流式传输问题
  - 原问题：`await agent.run()` 阻塞导致所有事件在 agent 执行完成后才发送
  - 解决方案：使用 `asyncio.create_task()` 创建后台任务，循环从 `event_queue` 实时获取并 yield 事件
  - 现在前端能够实时接收 SSE 事件，消息和迭代过程立即显示
- 2026.03.23: 多智能体系统扩展
  - 新增 `team_service.py` - 智能小组服务，支持小组 CRUD、成员管理、消息路由
  - 新增 `app/web/src/components/settings/TeamsSettings.vue` - 智能小组管理面板
  - 新增 `app/web/src/components/DualChatPanel.vue` - 双面板聊天布局（小组协作区 + 私人对话区）
  - 新增 `app/web/src/stores/team.ts` - 小组状态管理
  - 新增 API 接口：`/api/teams`, `/api/teams/:teamId/messages`, `/api/teams/:teamId/chat-history`
  - 支持小组创建、成员管理、任务分配、实时消息广播
- 2026.03.23: 迭代过程组件（原思考组件）
  - 重命名"思考组件"为"迭代过程组件"，避免与 LLM thinking 模式混淆
  - 每条 assistant 消息独立显示迭代步骤（步骤开始、工具调用、工具结果、步骤结束）
  - 支持展开/收起迭代详情
- 2026.03.18: Web UI 设置面板支持拖拽调整宽度，默认宽度增至 900px
- 2026.03.15: 删除 `web_ui/` 旧架构，完全迁移到 `app/runner/` 架构
- 2026.03.15: 删除空 `service/` 目录
- 新增 Runner 模式 (`app/runner/`)
- 新增任务队列系统 (`task_queue/`)
- 新增子 Agent 系统 (`sub_agent/`)
- 新增 ACP 协议支持 (`acp/`)
