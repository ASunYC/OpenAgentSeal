# OpenAgent Version Info

## Current Version: 2026.3.30
## Last Updated: 2026-03-30

---

## 版本号规则

采用 **日期版本号** 格式：`YYYY.M.D` 或 `YYYY.MM.DD`

### 版本号说明
- **主版本号 (YYYY)**: 年份，重大架构变更时更新
- **次版本号 (M 或 MM)**: 月份，功能迭代更新
- **修订号 (D 或 DD)**: 日期，Bug 修复和小优化

### 版本类型标签
- **-alpha**: 内部测试版本
- **-beta**: 公开测试版本
- **-rc**: 候选发布版本
- **无标签**: 正式稳定版本

---

## Changelog

### 2026.3.30 - Current
**Team 功能与前端优化**
- 新增 Team（团队）功能模块，支持多 Agent 协作
- 新增 Agent Team 功能，优化思考方式
- 前端设置组件完善：MCP、模型、会话、技能、系统、用户、工作区管理
- 支持通过前端传递的 ID 创建智能体
- 优化会话恢复逻辑
- 增加用户查询摘要和会话管理功能
- 多项 Bug 修复与稳定性改进

**核心模块状态**
- ✅ Agent 核心层: `agent.py`, `master_agent.py`, `agent_service.py`
- ✅ LLM 客户端: `llm/` (OpenAI, Anthropic, DeepSeek 支持)
- ✅ 工具层: `tools/` (Bash, File, MCP, Skills, SubAgent)
- ✅ 任务队列: `task_queue/` (Dispatcher, Queue, Worker)
- ✅ 子 Agent: `sub_agent/` (Manager, Roles, Session, Workspace)
- ✅ Web UI: `web_ui/web_server.py` (WebSocket 版本)
- ✅ ACP 协议: `acp/` (外部集成支持)
- ✅ Team 服务: `team_service.py` (多 Agent 协作)

---

### 2026.3.14
**架构优化与代码整理**
- 新增模块文档 `docs/Info.md`，详细记录所有模块功能
- 分析并标记未使用/待清理代码文件
- 优化 `docs/Plan.md`，添加当前状态摘要
- 代码结构梳理，明确模块依赖关系
- 删除空 `service/` 目录
- 标记 `sub_agent/ui.py` 为实验性功能

**核心模块状态**
- ✅ Agent 核心层: `agent.py`, `master_agent.py`, `agent_service.py`
- ✅ LLM 客户端: `llm/` (OpenAI, Anthropic, DeepSeek 支持)
- ✅ 工具层: `tools/` (Bash, File, MCP, Skills, SubAgent)
- ✅ 任务队列: `task_queue/` (Dispatcher, Queue, Worker)
- ✅ 子 Agent: `sub_agent/` (Manager, Roles, Session, Workspace)
- ✅ Web UI: `web_ui/web_server.py` (WebSocket 版本)
- ✅ ACP 协议: `acp/` (外部集成支持)

**待清理模块**
- ⚠️ `sub_agent/ui.py` - 终端 UI，实验性功能
- ⚠️ `app/web/` - Vue3 前端，待完整集成

---

### 2026.3.3
**Web UI 增强**
- 新增嵌入式 Web UI，支持 WebSocket 通信
- 集成模式：CLI 和 Web UI 共享同一个 Agent 实例
- CLI 与 Web UI 实时消息同步
- Web UI 支持停止生成
- 新增命令行选项：`--integrated`, `--web-only`, `--cli-only`, `--no-browser`
- 修复 Web UI 中的 `cancel_event` 错误

---

### 2026.2.28
**Skills 系统改进**
- 新增 `list_skills` 工具，列出所有可用 Skills 及其描述
- 修复 Skill 工具使用方式：`list_skills` 现在是独立工具，不再是 Skill 名称
- 改进渐进式披露：用户可以在加载完整内容前发现 Skills

---

### 2026.2.27
**初始版本发布**
- 树状记忆系统，SQLite 后端
- 多提供商 LLM 支持 (OpenAI, DeepSeek, Anthropic 等)
- 启动时交互式模型选择
- MCP 工具支持
- Claude Skills 集成
- Bash 工具，支持后台进程
- 文件工具 (读取、写入、编辑)
- 基于会话的对话与历史记录
- 长对话日志内存压缩

---

## 版本规划

### 近期 (2026.4.x)
- Runner 模式完整实现
- REST API + SSE 流式响应
- Vue3 前端完整集成
- 会话持久化改进

### 中期 (2026.6.x)
- 插件系统架构
- 多用户支持基础
- 性能优化

### 远期 (2026.12.x / 2027.x)
- 分布式 Agent 架构
- 企业级部署方案
- 高级安全特性

---

## 模块版本对应

| 模块 | 版本 | 状态 | 说明 |
|------|------|------|------|
| Core Agent | 2026.3.30 | ✅ 稳定 | 核心 Agent 执行循环 |
| Task Queue | 2026.3.30 | ✅ 稳定 | 任务队列系统 |
| Sub Agent | 2026.3.30 | ✅ 稳定 | 子 Agent 系统 |
| Team Service | 2026.3.30 | ✅ 稳定 | 多 Agent 协作服务 |
| Web UI | 2026.3.30 | 🔄 重构中 | Vue3 前端，设置组件完善 |
| ACP | 2026.3.30 | ✅ 稳定 | Agent 通信协议 |
| Skills | 2026.2.28 | ✅ 稳定 | Skills 系统 |
| Memory | 2026.2.27 | ✅ 稳定 | 树状记忆管理 |
| Tools | 2026.3.30 | ✅ 稳定 | 工具层 |

---

## 版本历史

| 版本 | 日期 | 类型 | 主要变更 |
|------|------|------|----------|
| 2026.3.30 | 2026-03-30 | 功能 | Team 功能，前端设置组件完善 |
| 2026.3.14 | 2026-03-14 | 优化 | 架构整理，文档完善 |
| 2026.3.3 | 2026-03-03 | 功能 | Web UI 增强 |
| 2026.2.28 | 2026-02-28 | 修复 | Skills 系统改进 |
| 2026.2.27 | 2026-02-27 | 发布 | 初始版本 |
