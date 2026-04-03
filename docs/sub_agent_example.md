# Sub-Agent System Usage Examples

This document provides practical examples of how to use the Sub-Agent system.

## Quick Start

### 1. Start Open Agent

```bash
# Enter project directory
cd d:\git-workspace\freeman.agent

# Start Open Agent
python run.py
# Or use the installed command
open-agent
```

### 2. Basic Commands

```bash
# Show help
/help

# Show available sub-agent commands
/help
```

## Creating Sub-Agents

### Method 1: Command Line

```bash
# Syntax: /open <role> <task>

# Create a code expert to fix a bug
/open code_expert "修复app.py中的登录bug"

# Create a documentation specialist
/open doc_master "为API接口编写使用文档"

# Create a test expert
/open test_expert "为用户模块编写单元测试"

# Create a design master
/open design_master "设计电商系统的数据库架构"

# Create a data analyst
/open data_analyst "分析销售数据并生成报告"

# Create a DevOps expert
/open devops_expert "配置Docker部署环境"

# Create a security expert
/open security_expert "审计登录模块的安全性"
```

### Method 2: Tool Invocation

In conversation, ask the main agent to create a sub-agent:

```
请帮我创建一个代码专家来优化main.py的性能
```

The main agent will automatically invoke the `sub_agent` tool.

## Available Roles

| Role ID | Chinese Name | Best For |
|---------|--------------|----------|
| `code_expert` | 代码高手 | Programming, debugging, code review, refactoring |
| `doc_master` | 文档大师 | Technical docs, API docs, README, user guides |
| `design_master` | 设计大师 | System architecture, database design, UI/UX design |
| `test_expert` | 测试专家 | Unit tests, integration tests, test automation |
| `data_analyst` | 数据分析师 | Data analysis, SQL queries, visualization, reports |
| `devops_expert` | DevOps专家 | CI/CD, Docker, Kubernetes, deployment |
| `security_expert` | 安全专家 | Security audit, vulnerability analysis, penetration testing |
| `general_assistant` | 通用助手 | General tasks, research, organization |

## Multi-Window UI Operations

### Opening the Panel

```bash
# Toggle the sub-agent panel (opens on the right side)
/panel
# Or press Tab key
```

The panel shows:
- **Top (2/3)**: Chat Lobby - all agent conversations
- **Bottom (1/3)**: Agent List - status of all sub-agents

### Viewing Agents

```bash
# List all sub-agents with detailed status
/sub-agents
```

Output example:
```
📋 Agent列表
──────────────────────────────────────────────────
  状态  ID                角色           任务预览
──────────────────────────────────────────────────
  ▶️   sub_1709123456    code_expert   Fix login bug...
  ⏸️   sub_1709234567    doc_master    Write API docs...
  ✅   sub_1709345678    test_expert   Write unit tests...
──────────────────────────────────────────────────
```

### Chat Lobby

The chat lobby shows all conversations in real-time:

```bash
# Show chat lobby messages
/lobby
```

#### Using @Mentions

In the chat lobby, use `@agent_id` to send messages to specific agents:

```bash
# Mention a specific agent
@sub_1709123456 请重点检查数据库连接部分

# Mention multiple agents
@sub_1709123456 @sub_1709234567 请两位协作完成这个任务

# Broadcast to all agents (no @mention)
大家请汇报一下各自的进度
```

### Switching Between Agents

```bash
# Switch to a specific agent for one-on-one chat
/switch-agent sub_1709123456

# Show available agents to switch
/switch-agent

# Use index number
/switch-agent 1

# Return to main agent
/switch-agent main
```

## Complete Workflow Example

### Scenario: Building a Feature

```bash
# 1. Start Open Agent
python run.py

# 2. Open the multi-window panel
/panel

# 3. Create sub-agents for different tasks
/open code_expert "实现用户注册功能，包括表单验证和数据库存储"
/open test_expert "为用户注册功能编写测试用例"
/open doc_master "编写用户注册API文档"

# 4. Check status
/sub-agents

# 5. Communicate with agents
@sub_1709123456 注册表单需要支持邮箱和手机号两种方式

# 6. Check progress
@sub_1709123456 进度如何？

# 7. Switch to specific agent for detailed discussion
/switch-agent sub_1709123456

# 8. In the switched mode, chat directly
请详细说明数据库表结构的设计

# 9. Return to main agent
/switch-agent main

# 10. Close completed agents
/close sub_1709123456
```

### Scenario: Code Review and Fix

```bash
# 1. Create a code expert for review
/open code_expert "审查src/auth.py的代码质量并提出改进建议"

# 2. Wait for initial analysis, then ask follow-up
@sub_1709123456 请重点关注安全方面的问题

# 3. Create another agent for fixing issues
/open security_expert "修复sub_1709123456发现的安全问题"

# 4. Coordinate between agents
@sub_1709234567 请参考sub_1709123456的审查报告进行修复

# 5. Create test agent
/open test_expert "编写安全测试用例验证修复效果"
```

### Scenario: Documentation Project

```bash
# 1. Create documentation specialist
/open doc_master "为整个项目编写README文档"

# 2. Provide context
@sub_1709123456 项目是一个Python的AI Agent框架，主要功能包括...

# 3. Create API documentation
/open doc_master "编写API参考文档"

# 4. Review progress
/lobby
```

## Status Icons

| Icon | Status | Description |
|------|--------|-------------|
| ⏸️ | idle | Agent is idle, waiting for tasks |
| ▶️ | running | Agent is actively working |
| ✅ | completed | Agent finished successfully |
| 🚫 | cancelled | Agent was cancelled |
| ❌ | error | Agent encountered an error |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Tab` | Toggle sub-agent panel |
| `Esc` | Cancel current operation |
| `↑/↓` | Browse command history |
| `Ctrl+C` | Exit program |
| `Ctrl+L` | Clear screen |

## Tips and Best Practices

### 1. Task Clarity

Be specific when creating sub-agents:

```bash
# ❌ Vague
/open code_expert "fix bug"

# ✅ Clear
/open code_expert "修复login.py中第45行的空指针异常，当用户名为空时触发"
```

### 2. Role Selection

Choose the right role for your task:

| Task Type | Recommended Role |
|-----------|------------------|
| Bug fix, feature implementation | `code_expert` |
| Writing documentation | `doc_master` |
| System design | `design_master` |
| Writing tests | `test_expert` |
| Data analysis | `data_analyst` |
| Deployment, CI/CD | `devops_expert` |
| Security review | `security_expert` |
| General tasks | `general_assistant` |

### 3. Coordination

Use the chat lobby for coordination:

```bash
# Broadcast to all
所有agent请注意：项目目录结构已更新，请重新熟悉

# Direct specific agent
@sub_1709123456 请暂停当前任务，先处理紧急bug

# Multiple agents
@sub_1709123456 @sub_1709234567 请两位同步一下进度
```

### 4. Resource Management

Clean up completed agents:

```bash
# Check all agents
/sub-agents

# Close completed ones
/close sub_1709123456
/close sub_1709234567
```

## Troubleshooting

### Agent Not Responding

```bash
# Check status
/sub-agents

# If stuck, cancel and recreate
/close sub_1709123456
/open code_expert "retry the task"
```

### Panel Not Showing

```bash
# Toggle panel
/panel

# Or press Tab key
```

### Cannot Switch Agent

```bash
# Check available agents
/sub-agents

# Use full ID
/switch-agent sub_1709123456789
```

## API Usage (Programmatic)

```python
from open_agent.sub_agent import SubAgentManager, SubAgentStatus

# Create manager
manager = SubAgentManager(
    workspace_dir="./workspace",
    main_agent_id="main_001",
    llm_client=llm_client,
    base_tools=tools,
)

# Create sub-agent
wrapper = manager.create_sub_agent(
    role="code_expert",
    task="Fix the bug in app.py",
    auto_start=True,
)

# Get status
info = wrapper.get_info()
print(f"Status: {info.status}")
print(f"Agent ID: {info.agent_id}")

# Send message
wrapper.send_message("Please also check the related tests")

# Get result
result = wrapper.get_result()

# Clean up
manager.delete_sub_agent(wrapper.agent_id)
```

## Summary

The Sub-Agent system enables parallel task execution with specialized agents. Key features:

- **8 specialized roles** for different task types
- **Independent thread execution** for parallel work
- **Multi-window UI** for monitoring and coordination
- **Chat lobby** with @mention support
- **Git-based workspace** for conflict prevention

For more details, see [sub_agent_design.md](./sub_agent_design.md).