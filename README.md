# OpenAgentSeal

<div align="center">

<img alt="Python" src="https://img.shields.io/badge/python-3.10+-blue.svg"> <img alt="Vue" src="https://img.shields.io/badge/vue-3-green.svg"> <img alt="Tauri" src="https://img.shields.io/badge/tauri-2-24C8DB.svg"> <img alt="License" src="https://img.shields.io/github/license/ASunYC/OpenAgentSeal.svg">

**Language / 语言**

[English](./README.en.md) | [中文](./README.zh-CN.md)

</div>

---

## English

OpenAgentSeal is a Python-first AI Agent framework with a complete agent execution loop, tool system, memory system, multi-LLM configuration, Web UI, and a lightweight Tauri desktop shell.

It is designed for building local-first agent applications that can run as:

- an interactive CLI assistant
- a FastAPI + Vue Web UI
- a Windows desktop shell with tray integration
- an ACP-compatible agent service
- a tool-using agent runtime with MCP and skills support

Read the full English documentation: [README.en.md](./README.en.md)

## 中文

OpenAgentSeal 是一个以 Python 为核心的 AI Agent 框架，包含完整的 Agent 执行循环、工具系统、记忆系统、多模型配置、Web UI，以及轻量 Tauri 桌面壳。

它适合用来构建本地优先的 Agent 应用，可运行在多种形态下：

- 交互式 CLI 助手
- FastAPI + Vue Web UI
- 带系统托盘的 Windows 桌面壳
- ACP 兼容 Agent 服务
- 支持 MCP 和 Skills 的工具调用运行时

查看完整中文文档：[README.zh-CN.md](./README.zh-CN.md)

---

## Quick Start

```bash
git clone https://github.com/ASunYC/OpenAgentSeal.git
cd OpenAgentSeal
uv sync
open-agent
```

Start the Web UI:

```bash
open-agent --web-only --port 9998
```

Start the desktop shell:

```bash
cd desktop
npm install
npm run dev
```

## Links

- English docs: [README.en.md](./README.en.md)
- 中文文档: [README.zh-CN.md](./README.zh-CN.md)
- Desktop shell notes: [desktop/README.md](./desktop/README.md)
- License: [LICENSE](./LICENSE)
