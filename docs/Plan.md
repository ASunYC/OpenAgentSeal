# OpenAgent 开发计划

> 当前版本: V1.1.0 | 最后更新: 2026-03-14
> 
> 本文档记录 OpenAgent 的架构规划和开发路线图

## 当前状态摘要

### 已完成功能 ✅
- 核心 Agent 执行循环
- 多提供商 LLM 支持 (OpenAI, Anthropic, DeepSeek)
- MCP 工具集成
- Skills 系统
- 树状记忆管理 (SQLite)
- 任务队列系统
- 子 Agent 系统
- Web UI (WebSocket 版本)
- ACP 协议支持
- 系统托盘应用

### 进行中 🔄
- Web UI 设置面板功能完善
- 测试覆盖提升
- 文档完善

### 待开始 📋
- 长期记忆增强 (向量索引 + 时序 Graph RAG)
- 技能系统增强
- MCP 工具扩展

### 已完成 ✅ (2026.03.18)
- Web UI 重构完成 (REST API + SSE)
- 设置面板支持拖拽调整宽度 (500px-1600px)
- 前端 Vue3 完整集成

---

# Web UI 重构计划

> 基于 CoPaw 项目学习，重构 freeman.agent 的 Web UI 架构

## 0. 完整架构总览

### 0.1 模块架构图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              freeman.agent 完整架构                               │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           用户交互层 (User Interface)                     │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │    │
│  │  │     CLI      │  │   Web UI     │  │  Tray App    │                  │    │
│  │  │  (cli.py)    │  │ (Vue3+Vite)  │  │  (tray.py)   │                  │    │
│  │  │              │  │              │  │              │                  │    │
│  │  │ 命令行交互   │  │ 浏览器访问   │  │ 系统托盘     │                  │    │
│  │  │ (开发/调试)  │  │ (主要界面)   │  │ (启动入口)   │                  │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘                  │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                        │                                         │
│                                        ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           服务层 (Service Layer)                         │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │                     AgentService (单例)                          │    │    │
│  │  │  - 创建/销毁/管理 Agent 实例                                      │    │    │
│  │  │  - 会话生命周期管理                                               │    │    │
│  │  │  - 状态回调通知                                                   │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  │                                  │                                       │    │
│  │  ┌───────────────────────────────┼───────────────────────────────────┐  │    │
│  │  │                               ▼                                   │  │    │
│  │  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐  │  │    │
│  │  │  │  MasterAgent   │  │ TaskDispatcher │  │ SubAgentManager    │  │  │    │
│  │  │  │                │  │                │  │                    │  │  │    │
│  │  │  │ - 任务提交     │  │ - 任务调度     │  │ - 子Agent生命周期  │  │  │    │
│  │  │  │ - 任务队列管理 │  │ - WorkerPool   │  │ - Role注册表       │  │  │    │
│  │  │  │ - 子Agent协调  │  │ - 优先级队列   │  │ - Session管理      │  │  │    │
│  │  │  └────────────────┘  └────────────────┘  └────────────────────┘  │  │    │
│  │  └───────────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                        │                                         │
│                                        ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           核心执行层 (Core Execution)                    │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │                        Agent (核心)                              │    │    │
│  │  │  - LLM 调用与流式响应                                            │    │    │
│  │  │  - 工具执行与结果处理                                             │    │    │
│  │  │  - 消息历史管理与摘要                                             │    │    │
│  │  │  - 状态回调 (status_callback)                                    │    │    │
│  │  │  - 取消机制 (cancel_event)                                       │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  │                                  │                                       │    │
│  │  ┌───────────────────────────────┼───────────────────────────────────┐  │    │
│  │  │                               ▼                                   │  │    │
│  │  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐  │  │    │
│  │  │  │  SubAgentWrap  │  │ SubAgentWrap   │  │  SubAgentWrap      │  │  │    │
│  │  │  │  (Thread 1)    │  │ (Thread 2)     │  │  (Thread N)        │  │  │    │
│  │  │  └────────────────┘  └────────────────┘  └────────────────────┘  │  │    │
│  │  └───────────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                        │                                         │
│                                        ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           工具层 (Tools Layer)                           │    │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐           │    │
│  │  │ BashTool   │ │ FileTools  │ │ NoteTools  │ │ ChoiceTool │           │    │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘           │    │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐           │    │
│  │  │SubAgentTool│ │ SkillTool  │ │ MCPTools   │ │ WebSearch  │           │    │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘           │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                        │                                         │
│                                        ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           LLM 客户端层 (LLM Clients)                     │    │
│  │  ┌────────────────────────────────────────────────────────────────┐     │    │
│  │  │                      LLMClient (统一接口)                       │     │    │
│  │  │  ┌──────────────────┐  ┌──────────────────┐                    │     │    │
│  │  │  │ OpenAIClient     │  │ AnthropicClient  │                    │     │    │
│  │  │  └──────────────────┘  └──────────────────┘                    │     │    │
│  │  └────────────────────────────────────────────────────────────────┘     │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                        │                                         │
│                                        ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           存储层 (Storage Layer)                         │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │                 MemoryManager (SQLite)                           │    │    │
│  │  │  - 树状记忆存储 (年/月/日)      │    │    │
│  │  │  - 关键词索引 + FTS5 全文搜索                                     │    │    │
│  │  │  - 记忆压缩与重要性分级                                           │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │                 WorkspaceManager (Git)                           │    │    │
│  │  │  - Git 工作区协调                                                │    │    │
│  │  │  - 分支管理                                                      │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │              TaskQueue (任务队列 - 内存 + 持久化)                 │    │    │
│  │  │  - 优先级队列                                                    │    │    │
│  │  │  - 任务状态追踪                                                  │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 0.2 数据流与通讯架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              数据流与通讯架构                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  用户 ──────▶ Web UI (Vue 3)                                                    │
│                    │                                                             │
│                    │  REST API                                                   │
│                    │  ┌──────────────────────────────────────────────┐          │
│                    │  │ GET    /api/chats         # 列出会话         │          │
│                    │  │ POST   /api/chats         # 创建会话         │          │
│                    │  │ GET    /api/chats/{id}    # 获取会话详情     │          │
│                    │  │ DELETE /api/chats/{id}    # 删除会话         │          │
│                    │  │ POST   /api/agent/process # 发送消息(流式)   │          │
│                    │  │ GET    /api/tasks         # 列出任务         │          │
│                    │  │ POST   /api/tasks         # 提交任务         │          │
│                    │  │ GET    /api/subagents     # 列出子Agent      │          │
│                    │  └──────────────────────────────────────────────┘          │
│                    ▼                                                             │
│              FastAPI 路由层                                                      │
│                    │                                                             │
│                    ▼                                                             │
│              ChatManager / TaskDispatcher                                       │
│                    │                                                             │
│         ┌─────────┼─────────┐                                                   │
│         ▼         ▼         ▼                                                   │
│    AgentService  MasterAgent  SubAgentManager                                   │
│         │         │         │                                                   │
│         └─────────┼─────────┘                                                   │
│                   ▼                                                             │
│              Agent.run()                                                        │
│                   │                                                             │
│                   │  WebSocket / SSE (流式响应)                                  │
│                   │  ┌──────────────────────────────────────────────┐          │
│                   │  │ event: step_start     # 步骤开始             │          │
│                   │  │ event: thinking       # 思考内容             │          │
│                   │  │ event: tool_call      # 工具调用             │          │
│                   │  │ event: tool_result    # 工具结果             │          │
│                   │  │ event: step_end       # 步骤结束             │          │
│                   │  │ event: complete       # 任务完成             │          │
│                   │  └──────────────────────────────────────────────┘          │
│                   ▼                                                             │
│              Web UI 实时更新                                                    │
│                                                                                  │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                              存储层数据流                                        │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  ChatSpec (JSON)                消息内容 (MemoryManager)                        │
│  ┌─────────────────┐           ┌─────────────────────────────────┐             │
│  │ ~/.open-agent/  │           │ ~/.open-agent/memory/memory.db  │             │
│  │ chats.json      │           │                                 │             │
│  │                 │           │ memories 表:                    │             │
│  │ [{              │           │ - id, content, category         │             │
│  │   id,           │◀─────────▶│ - keywords, timestamp           │             │
│  │   name,         │  关联     │ - year, month, day              │             │
│  │   session_id,   │  通过     │ - parent_id, metadata           │             │
│  │   created_at    │session_id │                                 │             │
│  │ }]              │           │ memory_keywords 表:             │             │
│  │                 │           │ - keyword, memory_id            │             │
│  └─────────────────┘           └─────────────────────────────────┘             │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 0.3 Sub-Agent 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Sub-Agent 系统架构                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                         Main Agent                                       │    │
│  │  ┌─────────────────────────────────────────────────────────────────────┐│    │
│  │  │                     SubAgentManager                                  ││    │
│  │  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────────────┐││    │
│  │  │  │ RoleRegistry│ │SessionManager│ │    WorkspaceManager            │││    │
│  │  │  │             │ │             │ │    (Git 工作区协调)              │││    │
│  │  │  │ - 代码专家   │ │ - 会话创建   │ │    - 分支管理                  │││    │
│  │  │  │ - 文档大师   │ │ - 消息传递   │ │    - 冲突解决                  │││    │
│  │  │  │ - 测试专家   │ │ - 状态追踪   │ │    - 版本控制                  │││    │
│  │  │  │ - DevOps    │ │             │ │                                │││    │
│  │  │  └─────────────┘ └─────────────┘ └─────────────────────────────────┘││    │
│  │  │  ┌─────────────────────────────────────────────────────────────────┐││    │
│  │  │  │              SubAgentWrapper Pool (线程池)                       │││    │
│  │  │  │  ┌───────────┐ ┌───────────┐ ┌───────────┐                      │││    │
│  │  │  │  │ SubAgent1 │ │ SubAgent2 │ │ SubAgent3 │ ...                  │││    │
│  │  │  │  │ (Thread)  │ │ (Thread)  │ │ (Thread)  │                      │││    │
│  │  │  │  └───────────┘ └───────────┘ └───────────┘                      │││    │
│  │  │  └─────────────────────────────────────────────────────────────────┘││    │
│  │  └─────────────────────────────────────────────────────────────────────┘│    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  通信协议:                                                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐     │
│  │  MessageType: TASK | QUERY | RESPONSE | STATUS | ERROR | CONTROL      │     │
│  │  Message: { id, type, sender, receiver, content, timestamp, metadata }│     │
│  └────────────────────────────────────────────────────────────────────────┘     │
│                                                                                  │
│  文件存储:                                                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐     │
│  │  workspace/sub_agents/                                                  │     │
│  │  ├── sub_1708123456/           # 子Agent目录                            │     │
│  │  │   ├── session.json          # 会话信息                              │     │
│  │  │   ├── messages.json         # 消息历史                              │     │
│  │  │   ├── result.json           # 执行结果                              │     │
│  │  │   └── state.json            # 当前状态                              │     │
│  │  └── registry.json             # Agent 注册表                          │     │
│  └────────────────────────────────────────────────────────────────────────┘     │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 0.4 Task Queue 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Task Queue 系统架构                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                         MasterAgent                                      │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │                    TaskDispatcher                                │    │    │
│  │  │  ┌─────────────┐    ┌──────────────────────────────┐           │    │    │
│  │  │  │ TaskQueue   │───▶│      WorkerPool              │           │    │    │
│  │  │  │             │    │  ┌────────┐ ┌────────┐       │           │    │    │
│  │  │  │ Priority    │    │  │Worker 1│ │Worker 2│ ...   │           │    │    │
│  │  │  │ Queue       │    │  └────────┘ └────────┘       │           │    │    │
│  │  │  │             │    │                              │           │    │    │
│  │  │  │ LOW/NORMAL  │    │  每个Worker执行一个Task      │           │    │    │
│  │  │  │ HIGH/URGENT │    │                              │           │    │    │
│  │  │  └─────────────┘    └──────────────────────────────┘           │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  │                              │                                           │    │
│  │                              ▼                                           │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │                      Agent (执行任务)                            │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  │                              │                                           │    │
│  │                              ▼                                           │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │                  SubAgentManager (任务委派)                       │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  Task 生命周期:                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐     │
│  │                                                                         │     │
│  │   PENDING ──▶ QUEUED ──▶ RUNNING ──▶ COMPLETED                         │     │
│  │                              │                                          │     │
│  │                              ├──▶ FAILED                                │     │
│  │                              │                                          │     │
│  │                              └──▶ CANCELLED                             │     │
│  │                                                                         │     │
│  └────────────────────────────────────────────────────────────────────────┘     │
│                                                                                  │
│  核心组件:                                                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐     │
│  │  Task:          任务单元 (task_id, user_input, status, priority)       │     │
│  │  TaskQueue:     线程安全优先级队列                                      │     │
│  │  TaskDispatcher: 任务调度中心                                           │     │
│  │  WorkerPool:    工作线程池                                              │     │
│  │  MasterAgent:   主Agent，整合任务队列和子Agent管理                       │     │
│  └────────────────────────────────────────────────────────────────────────┘     │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 1. 架构对比

### 1.1 当前架构问题

| 问题 | 描述 |
|------|------|
| 前端内嵌 | HTML/CSS/JS 内嵌在 Python 文件中，难以维护 |
| 无独立 API 层 | 缺少模块化的 API 定义和类型 |
| WebSocket 通讯 | 使用 WebSocket 进行所有通讯，不够灵活 |
| 会话管理简陋 | 依赖内存管理，缺少持久化机制 |
| 无前端构建 | 没有使用现代前端构建工具 |

### 1.2 CoPaw 架构优点

| 特性 | 描述 |
|------|------|
| 前后端分离 | 独立的前端项目，使用 Vite 构建 |
| 模块化 API | TypeScript 类型定义 + 模块化 API 层 |
| SessionApi 模式 | 统一的会话管理接口 |
| Runner 模式 | 后端使用 Runner 处理流式响应 |
| JSON 持久化 | 会话数据持久化到 JSON 文件 |

## 2. 目标架构

### 2.1 前端架构 (Vue 3 + TypeScript + Vite)

```
web-ui/                           # 独立前端项目
├── public/                       # 静态资源
│   └── logo.png
├── src/
│   ├── api/                      # API 层
│   │   ├── config.ts             # API 配置（baseURL, token）
│   │   ├── request.ts            # 统一请求封装
│   │   ├── index.ts              # API 聚合导出
│   │   ├── modules/              # 模块化 API
│   │   │   ├── chat.ts           # 会话 API
│   │   │   ├── agent.ts          # Agent API
│   │   │   ├── model.ts          # 模型配置 API
│   │   │   └── settings.ts       # 设置 API
│   │   └── types/                # TypeScript 类型定义
│   │       ├── chat.ts           # 会话相关类型
│   │       ├── agent.ts          # Agent 相关类型
│   │       ├── message.ts        # 消息相关类型
│   │       └── index.ts          # 类型聚合导出
│   ├── components/               # Vue 组件
│   │   ├── chat/
│   │   │   ├── ChatPanel.vue     # 对话面板
│   │   │   ├── MessageList.vue   # 消息列表
│   │   │   ├── MessageItem.vue   # 单条消息
│   │   │   ├── InputArea.vue     # 输入区域
│   │   │   └── ThinkingBlock.vue # 思考过程展示
│   │   ├── session/
│   │   │   ├── SessionList.vue   # 会话列表
│   │   │   └── SessionItem.vue   # 会话项
│   │   └── common/
│   │       ├── Sidebar.vue       # 侧边栏
│   │       └── Header.vue        # 头部
│   ├── composables/              # Vue 组合式函数
│   │   ├── useSession.ts         # 会话管理
│   │   ├── useChat.ts            # 对话管理
│   │   └── useStream.ts          # 流式响应处理
│   ├── stores/                   # Pinia 状态管理
│   │   ├── session.ts            # 会话状态
│   │   ├── chat.ts               # 对话状态
│   │   └── settings.ts           # 设置状态
│   ├── views/                    # 页面视图
│   │   ├── ChatView.vue          # 对话页面
│   │   ├── SettingsView.vue      # 设置页面
│   │   └── HistoryView.vue       # 历史页面
│   ├── router/                   # 路由配置
│   │   └── index.ts
│   ├── styles/                   # 样式文件
│   │   └── main.css
│   ├── App.vue                   # 根组件
│   └── main.ts                   # 入口文件
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
└── README.md
```

### 2.2 后端架构改进

```
open_agent/
├── app/                          # 应用模块
│   ├── __init__.py
│   ├── _app.py                   # FastAPI 应用入口
│   ├── runner/                   # Runner 模式
│   │   ├── __init__.py
│   │   ├── runner.py             # AgentRunner
│   │   ├── session.py            # Session 管理
│   │   ├── api.py                # Chat API 路由
│   │   ├── manager.py            # ChatManager
│   │   ├── models.py             # 数据模型
│   │   └── repo/                 # 数据仓库
│   │       ├── __init__.py
│   │       ├── base.py           # 基类
│   │       └── json_repo.py      # JSON 实现
│   ├── routers/                  # API 路由
│   │   ├── __init__.py
│   │   ├── agent.py              # Agent 相关 API
│   │   ├── models.py             # 模型配置 API
│   │   └── settings.py           # 设置 API
│   └── schemas/                  # Pydantic 模型
│       ├── chat.py
│       ├── agent.py
│       └── message.py
├── web_ui/                       # Web UI 模块（保留兼容）
│   ├── __init__.py
│   └── web_server.py             # 服务器启动
└── ...
```

## 3. 核心实现

### 3.1 SessionApi 类（前端）

```typescript
// src/composables/useSession.ts
import type { Session, Message } from '@/api/types'

export interface ISessionApi {
  getSessionList(): Promise<Session[]>
  getSession(sessionId: string): Promise<Session>
  createSession(session: Partial<Session>): Promise<Session[]>
  updateSession(session: Partial<Session>): Promise<Session[]>
  removeSession(session: Partial<Session>): Promise<Session[]>
}

export class SessionApi implements ISessionApi {
  private sessionList: Session[] = []
  private cache: Map<string, { session: Session; timestamp: number }> = new Map()
  
  async getSessionList(): Promise<Session[]> {
    // 从后端获取会话列表
    const chats = await api.listChats()
    this.sessionList = chats.map(chatToSession).reverse()
    return [...this.sessionList]
  }
  
  async getSession(sessionId: string): Promise<Session> {
    // 获取会话详情，包含消息历史
    const chatHistory = await api.getChat(sessionId)
    return {
      id: sessionId,
      messages: convertMessages(chatHistory.messages),
      // ...
    }
  }
  
  // ... 其他方法
}
```

### 3.2 消息格式转换

```typescript
// 将后端消息转换为 UI Card 格式
function convertMessages(messages: Message[]): UIMessage[] {
  const result: UIMessage[] = []
  
  for (const msg of messages) {
    if (msg.role === 'user') {
      result.push(buildUserCard(msg))
    } else {
      // 非用户消息分组为响应卡片
      result.push(buildResponseCard(msg))
    }
  }
  
  return result
}

function buildUserCard(msg: Message): UIMessage {
  return {
    id: msg.id || generateId(),
    role: 'user',
    cards: [{
      code: 'UserMessageCard',
      data: { input: [msg] }
    }]
  }
}
```

### 3.3 流式响应处理

```typescript
// src/composables/useStream.ts
export function useStream() {
  const abortController = ref<AbortController | null>(null)
  
  async function sendMessage(
    input: Message[],
    sessionId: string,
    onMessage: (chunk: string) => void,
    onComplete: () => void,
    onError: (error: Error) => void
  ) {
    abortController.value = new AbortController()
    
    const response = await fetch('/api/agent/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input: input.slice(-1),
        session_id: sessionId,
        stream: true
      }),
      signal: abortController.value.signal
    })
    
    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    
    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      
      const chunk = decoder.decode(value)
      onMessage(chunk)
    }
    
    onComplete()
  }
  
  function cancel() {
    abortController.value?.abort()
  }
  
  return { sendMessage, cancel }
}
```

### 3.4 后端 Runner 模式

```python
# open_agent/app/runner/runner.py
from agentscope_runtime.engine.runner import Runner
from agentscope_runtime.engine.schemas import AgentRequest

class AgentRunner(Runner):
    def __init__(self):
        super().__init__()
        self._chat_manager = None
        self._session = None
    
    def set_chat_manager(self, chat_manager):
        self._chat_manager = chat_manager
    
    async def query_handler(self, msgs, request: AgentRequest = None, **kwargs):
        """处理 Agent 查询，流式返回"""
        session_id = request.session_id
        user_id = request.user_id
        
        # 获取或创建会话
        if self._chat_manager:
            chat = await self._chat_manager.get_or_create_chat(
                session_id, user_id, "web"
            )
        
        # 加载会话状态
        await self.session.load_session_state(session_id, user_id, agent)
        
        # 流式处理
        async for msg, last in stream_process(agent, msgs):
            yield msg, last
        
        # 保存会话状态
        await self.session.save_session_state(session_id, user_id, agent)
        
        # 更新会话
        if self._chat_manager:
            await self._chat_manager.update_chat(chat)
```

### 3.5 Chat API 路由

```python
# open_agent/app/runner/api.py
from fastapi import APIRouter, Depends, Request
from .manager import ChatManager
from .models import ChatSpec, ChatHistory

router = APIRouter(prefix="/chats", tags=["chats"])

@router.get("", response_model=list[ChatSpec])
async def list_chats(
    user_id: str | None = None,
    mgr: ChatManager = Depends(get_chat_manager)
):
    """列出所有会话"""
    return await mgr.list_chats(user_id=user_id)

@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager)
):
    """获取会话详情"""
    chat_spec = await mgr.get_chat(chat_id)
    if not chat_spec:
        raise HTTPException(404, "Chat not found")
    
    # 加载消息历史
    messages = await load_session_messages(chat_spec.session_id)
    return ChatHistory(messages=messages)

@router.post("", response_model=ChatSpec)
async def create_chat(
    request: ChatSpec,
    mgr: ChatManager = Depends(get_chat_manager)
):
    """创建新会话"""
    return await mgr.create_chat(request)

@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager)
):
    """删除会话"""
    await mgr.delete_chats([chat_id])
    return {"deleted": True}
```

### 3.6 ChatManager

```python
# open_agent/app/runner/manager.py
from .repo import JsonChatRepository
from .models import ChatSpec

class ChatManager:
    def __init__(self, repo: JsonChatRepository):
        self.repo = repo
    
    async def list_chats(self, user_id: str = None) -> list[ChatSpec]:
        """列出所有会话"""
        return await self.repo.list_chats(user_id)
    
    async def get_chat(self, chat_id: str) -> ChatSpec | None:
        """获取会话"""
        return await self.repo.get_chat(chat_id)
    
    async def get_or_create_chat(
        self, session_id: str, user_id: str, channel: str, name: str = "New Chat"
    ) -> ChatSpec:
        """获取或创建会话"""
        chat = await self.repo.find_by_session_id(session_id)
        if not chat:
            chat = ChatSpec(
                id=str(uuid4()),
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                name=name
            )
            await self.repo.create_chat(chat)
        return chat
    
    async def update_chat(self, chat: ChatSpec) -> ChatSpec:
        """更新会话"""
        return await self.repo.update_chat(chat)
    
    async def delete_chats(self, chat_ids: list[str]) -> bool:
        """删除会话"""
        return await self.repo.delete_chats(chat_ids)
```

## 4. 数据模型

### 4.1 会话模型

```python
# open_agent/app/runner/models.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ChatSpec(BaseModel):
    """会话元数据"""
    id: str = Field(..., description="会话 UUID")
    name: str = Field(default="New Chat", description="会话名称")
    session_id: str = Field(..., description="会话 ID")
    user_id: str = Field(default="default", description="用户 ID")
    channel: str = Field(default="web", description="渠道")
    meta: dict = Field(default_factory=dict, description="元数据")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class Message(BaseModel):
    """消息"""
    id: str | None = None
    role: str  # user, assistant, system, tool
    type: str = "message"
    content: list | str
    timestamp: datetime | None = None

class ChatHistory(BaseModel):
    """会话历史"""
    messages: list[Message] = Field(default_factory=list)
```

### 4.2 TypeScript 类型

```typescript
// src/api/types/chat.ts
export interface ChatSpec {
  id: string
  name: string
  session_id: string
  user_id: string
  channel: string
  meta: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface Message {
  id?: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  type: string
  content: ContentItem[] | string
  timestamp?: string
}

export interface ContentItem {
  type: 'text' | 'image' | 'tool_call' | 'tool_result'
  text?: string
  tool_name?: string
  arguments?: Record<string, unknown>
  result?: unknown
}

export interface ChatHistory {
  messages: Message[]
}
```

## 5. 实施步骤

### 阶段一：后端重构 ✅ (已完成)

- [x] 创建 `open_agent/app/` 目录结构
- [x] 实现 `AgentRunner` 类
- [x] 实现 `ChatManager` 和 `JsonChatRepository`
- [x] 实现 Chat API 路由
- [x] 实现会话持久化
- [x] 修改 `_app.py` 整合新架构

### 阶段二：前端项目搭建 ✅ (已完成)

- [x] 创建 Vue 3 + TypeScript + Vite 项目
- [x] 配置项目结构和依赖
- [x] 实现 API 层（config, request, modules）
- [x] 定义 TypeScript 类型
- [x] 实现基础组件

### 阶段三：核心功能实现 ✅ (已完成)

- [x] 实现 `useSession` 组合式函数
- [x] 实现 `useStream` 流式响应处理
- [x] 实现 ChatPanel 组件
- [x] 实现 MessageList 组件
- [x] 实现会话列表组件
- [x] 实现思考过程展示

### 阶段四：设置面板增强 ✅ (2026.03.18 完成)

- [x] 重构 App.vue 为聊天面板主界面
- [x] 创建 SettingsPanel.vue 设置面板组件
- [x] 实现拖拽调整宽度功能 (500px-1600px)
- [x] 创建 9 个设置子组件
  - [x] UserSettings.vue - 用户设置
  - [x] ModelsSettings.vue - 模型配置
  - [x] AgentsSettings.vue - 智能体管理
  - [x] SessionsSettings.vue - 会话管理
  - [x] SkillsSettings.vue - 技能管理
  - [x] MCPSettings.vue - MCP 配置
  - [x] SystemSettings.vue - 系统设置
  - [x] DashboardSettings.vue - 数据面板
  - [x] WorkspaceSettings.vue - 工作目录

### 阶段五：集成测试 ✅ (已完成)

- [x] 前后端联调
- [x] 测试会话创建、切换、删除
- [x] 测试流式响应
- [x] 测试持久化
- [x] 性能优化

### 阶段六：构建部署 ✅ (已完成)

- [x] 配置 Vite 生产构建
- [x] 配置后端静态文件服务
- [x] 更新打包脚本
- [x] 文档更新

## 6. 技术选型

### 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.4+ | 前端框架 |
| TypeScript | 5.0+ | 类型支持 |
| Vite | 5.0+ | 构建工具 |
| Pinia | 2.1+ | 状态管理 |
| Vue Router | 4.2+ | 路由管理 |
| TailwindCSS | 3.4+ | 样式框架 |
| marked | 12.0+ | Markdown 解析 |
| highlight.js | 11.9+ | 代码高亮 |

### 后端

| 技术 | 版本 | 用途 |
|------|------|------|
| FastAPI | 0.109+ | Web 框架 |
| Pydantic | 2.5+ | 数据验证 |
| uvicorn | 0.27+ | ASGI 服务器 |

## 7. 参考资源

- [CoPaw 项目](https://github.com/agentscope-ai/agentscope-runtime)
- [Vue 3 文档](https://vuejs.org/)
- [Vite 文档](https://vitejs.dev/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [Pinia 文档](https://pinia.vuejs.org/)

---

# 多智能体系统扩展计划

> 基于 `docs/agent_team.md` 设计文档实现
> 最后更新: 2026-03-23

## 1. 功能概述

多智能体系统扩展允许用户创建智能小组，由组长智能体协调多个成员智能体协作完成任务。

### 核心功能
- **智能小组管理**: 创建、查看、删除小组
- **双面板聊天**: 左侧小组协作区 + 右侧私人对话区
- **任务队列**: 组长向成员派发任务，成员按序执行
- **实时消息广播**: 小组内部消息实时推送给所有成员

## 2. 架构设计

### 2.1 后端架构

```
open_agent/
├── team_service.py           # 智能小组服务 (新增)
│   ├── TeamService           # 小组 CRUD
│   ├── TeamMessageRouter     # 消息路由
│   └── TaskQueueManager      # 任务队列管理
│
├── app/
│   └── _app.py               # FastAPI 路由注册
```

### 2.2 前端架构

```
app/web/src/
├── components/
│   ├── DualChatPanel.vue     # 双面板聊天布局 (新增)
│   ├── ThinkingProcess.vue   # 迭代过程组件 (修改)
│   └── settings/
│       └── TeamsSettings.vue # 智能小组管理面板 (新增)
│
├── stores/
│   └── team.ts               # 小组状态管理 (新增)
│
└── types/
    └── index.ts              # 类型定义 (扩展)
```

## 3. API 接口

### 3.1 小组管理

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/teams` | 创建小组 |
| GET | `/api/teams` | 获取小组列表 |
| GET | `/api/teams/:teamId` | 获取小组详情 |
| DELETE | `/api/teams/:teamId` | 删除小组 |

### 3.2 消息路由

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/teams/:teamId/messages` | 发送小组消息 |
| GET | `/api/teams/:teamId/chat-history` | 获取小组聊天记录 |

## 4. 数据结构

### 4.1 智能小组

```typescript
interface Team {
  id: string
  name: string
  leader_id: string
  mission: string
  status: 'running' | 'completed' | 'paused'
  progress: number
  created_at: string
  members: TeamMember[]
}

interface TeamMember {
  agent_id: string
  role: string  // "组长" | "架构师" | "开发工程师" 等
}
```

### 4.2 任务队列

```typescript
interface AgentTask {
  id: string
  from: string      // 来源 agent_id
  type: 'team_task' | 'private_task'
  content: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  created_at: string
}
```

## 5. 实施进度

### 阶段一：后端基础 ✅ (已完成)

- [x] 创建 `team_service.py`
- [x] 实现小组 CRUD API
- [x] 实现消息路由系统
- [x] 实现任务队列管理

### 阶段二：前端基础 ✅ (已完成)

- [x] 添加"智能小组"菜单项
- [x] 创建 `TeamsSettings.vue` 管理面板
- [x] 创建 `team.ts` 状态管理
- [x] 扩展类型定义

### 阶段三：聊天面板重构 ✅ (已完成)

- [x] 创建 `DualChatPanel.vue` 双面板布局
- [x] 实现小组协作区（左侧）
- [x] 实现私人对话区（右侧）
- [x] 可拖动分割条

### 阶段四：迭代过程组件 ✅ (已完成)

- [x] 重命名"思考组件"为"迭代过程组件"
- [x] 每条 assistant 消息独立显示迭代步骤
- [x] 支持展开/收起功能

### 阶段五：联调测试 ✅ (已完成)

- [x] SSE 事件流调试
- [x] 消息显示问题修复
- [x] 实时通信测试

## 6. 已解决问题

### 6.1 Web 前端消息显示问题 ✅ (已解决)

**现象**: 消息发送后不立即显示，需要点击展开/收起按钮才刷新

**根因分析**:
在 `app/runner/runner.py` 中，`await agent.run()` 是阻塞调用，所有 SSE 事件在 agent 执行完成后才被 yield，导致前端无法实时接收消息。

**解决方案**:
将阻塞调用改为使用 `asyncio.create_task()` 创建后台任务，然后在循环中实时从 `event_queue` 获取事件并 yield：

```python
# 创建后台任务运行 agent
agent_task = asyncio.create_task(agent.run())

# 实时 yield 事件
while not agent_task.done():
    try:
        event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
        yield event
    except asyncio.TimeoutError:
        pass

# Agent 完成后，排空剩余事件
while not event_queue.empty():
    yield await event_queue.get()
```

**修改文件**: `open_agent/app/runner/runner.py` (第 225-289 行)

## 7. 后续规划

### 7.1 组长智能体规划能力

- 组长接收任务后调用 LLM 进行任务规划
- 根据规划结果动态创建成员智能体
- 为每个成员分配子任务

### 7.2 成员智能体执行

- 成员按任务队列顺序执行任务
- 执行结果通过小组频道广播
- 组长汇总结果并汇报给用户

### 7.3 会话存储分离

- `session_type: 'group_chat'` - 小组内部对话
- `session_type: 'private_chat'` - 用户-智能体私聊