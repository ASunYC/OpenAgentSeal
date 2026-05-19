# OpenAgentSeal

> 一个以 Python 为核心的 AI Agent 框架，提供 Agent 执行循环、工具系统、记忆系统、多模型配置、Web UI 和轻量桌面壳。

<div align="center">

<img alt="Python" src="https://img.shields.io/badge/python-3.10+-blue.svg"> <img alt="Vue" src="https://img.shields.io/badge/vue-3-green.svg"> <img alt="Tauri" src="https://img.shields.io/badge/tauri-2-24C8DB.svg"> <img alt="License" src="https://img.shields.io/github/license/ASunYC/OpenAgentSeal.svg">

**创作者**: [ASunYC](https://github.com/ASunYC)

[English](./README.en.md) | [语言入口](./README.md)

[项目简介](#项目简介) • [功能特性](#功能特性) • [快速开始](#快速开始) • [桌面应用](#桌面应用) • [开发指南](#开发指南) • [架构说明](#架构说明)

</div>

---

## 项目简介

OpenAgentSeal 是一个本地优先的 Agent 应用框架。它把 Python Agent 核心、FastAPI 服务、Vue Web UI、MCP/Skills 工具生态和桌面壳组合在一起，既可以作为命令行 Agent 使用，也可以作为 Web/桌面应用运行。

当前项目的核心形态：

- **Python 核心**：负责 Agent 执行循环、LLM 调用、工具调用、记忆和任务调度。
- **FastAPI 服务**：为 Web UI 和桌面壳提供本地 API。
- **Vue3 Web UI**：提供聊天、模型配置、Agent 配置、Skills/MCP 设置等界面。
- **Tauri 桌面壳**：提供窗口、系统托盘、后端进程管理和桌面打包。

TypeScript/Node.js 版本请查看：[OpenAgentSeal-JS](https://github.com/ASunYC/OpenAgentSeal-JS)

---

## 功能特性

### Agent 核心

- **Agent 执行循环**：支持多轮对话、工具调用和任务执行。
- **多 LLM 支持**：支持 OpenAI、Anthropic、DeepSeek、MiniMax、火山引擎、通义千问、智谱 AI 等供应商。
- **流式响应**：通过 SSE 实时返回 Agent 输出。
- **工具系统**：包含文件操作、命令执行、笔记、MCP 工具和 Skills 工具。
- **记忆系统**：基于 SQLite 的树状记忆和检索能力。
- **任务队列**：支持任务调度、后台执行和并发控制。

### 应用形态

- **CLI 模式**：适合开发者在终端中直接使用 Agent。
- **Web UI 模式**：通过浏览器访问本地 FastAPI + Vue 应用。
- **桌面模式**：通过 Tauri 轻量壳运行，支持窗口和系统托盘。
- **ACP 服务模式**：作为 Agent Communication Protocol 服务集成到外部系统。

### Web UI

- 实时聊天和流式输出
- 模型配置和切换
- Agent 配置管理
- MCP、Skills、Workspace 设置
- 历史会话和运行状态查看

---

## 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/ASunYC/OpenAgentSeal.git
cd OpenAgentSeal

# 推荐使用 uv
pip install uv
uv sync

# 或使用 pip
pip install -e .
```

### 2. 配置模型

首次运行会进入模型配置流程：

```bash
open-agent
```

也可以手动配置 `~/.open-agent/open_agent.json` 或 `~/.open-agent/models.yaml`，具体字段以项目当前配置管理器为准。

### 3. 启动 CLI

```bash
open-agent
```

指定工作目录：

```bash
open-agent --workspace /path/to/workspace
```

执行单次任务：

```bash
open-agent --task "创建一个 Python 脚本"
```

### 4. 启动 Web UI

```bash
open-agent --web-only --host 127.0.0.1 --port 9998
```

访问：

```text
http://127.0.0.1:9998
```

---

## 桌面应用

OpenAgentSeal 已加入轻量 Tauri 桌面壳。桌面壳只负责窗口、托盘、后端进程生命周期和打包；Agent 核心仍然保留在 Python 中。

### 开发启动

```bash
cd desktop
npm install
npm run dev
```

### 打包

```bash
cd desktop
npm run build
```

Windows 构建产物位于：

```text
desktop/src-tauri/target/release/open-agent-seal-desktop.exe
desktop/src-tauri/target/release/bundle/nsis/OpenAgentSeal_0.1.0_x64-setup.exe
desktop/src-tauri/target/release/bundle/msi/OpenAgentSeal_0.1.0_x64_en-US.msi
```

### 托盘能力

桌面壳默认提供机器人托盘图标，并支持：

- Open Window：恢复主窗口
- Open in Browser：在浏览器打开本地 Web UI
- Restart Backend：重启 Python 后端
- Open Backend Log：打开 `desktop-backend.log`
- Quit：退出桌面应用并清理后端进程

更多说明见：[desktop/README.md](./desktop/README.md)

---

## 开发指南

### 常用命令

```bash
# 安装开发依赖
uv sync --all-extras

# 运行测试
uv run pytest

# 格式化
uv run ruff format .

# 启动 Web UI
open-agent --web-only --port 9998
```

### Web UI 开发

```bash
cd open_agent/app/web
npm install
npm run dev
```

Vite 开发服务会代理 `/api` 到本地 Python 后端。

### 桌面壳开发

```bash
cd desktop
npm install
npm run dev
```

Tauri 会启动 Vue 开发服务，并拉起 Python 后端：

```bash
python -m open_agent --web-only --no-browser --host 127.0.0.1 --port 9998
```

---

## 架构说明

```text
OpenAgentSeal
├─ desktop/                 # Tauri 桌面壳
├─ open_agent/
│  ├─ agent.py              # Agent 核心
│  ├─ agent_service.py      # Agent 服务层
│  ├─ cli.py                # CLI 入口
│  ├─ memory_manager.py     # 记忆系统
│  ├─ llm/                  # LLM 适配层
│  ├─ tools/                # 工具系统
│  ├─ task_queue/           # 任务队列
│  ├─ app/                  # FastAPI + Web UI
│  ├─ acp/                  # ACP 服务
│  └─ skills/               # Skills 生态
├─ tests/                   # 测试
├─ docs/                    # 文档
└─ pyproject.toml           # Python 包配置
```

运行时关系：

```text
Tauri Desktop Shell
        │
        │ starts/manages
        ▼
Python FastAPI Backend
        │
        │ serves API/SSE
        ▼
Vue Web UI
        │
        │ calls
        ▼
Agent Core / Tools / Memory / LLM
```

---

## 许可证

本项目使用 [LICENSE](./LICENSE) 中声明的许可证。
