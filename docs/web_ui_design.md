# Web UI 设计文档

## 概述

Open Agent 提供了嵌入式 Web UI，与 CLI 共享同一个 Agent 实例，实现 CLI 和 Web 界面的无缝切换。

## 架构设计

### 核心理念

1. **CLI 是主进程** - CLI 运行 Agent 的主逻辑
2. **Web UI 是前端视图** - 提供浏览器访问界面
3. **共享 Agent 实例** - CLI 和 Web UI 共享同一个 Agent 和消息历史
4. **实时同步** - 通过 WebSocket 实现消息和状态的实时同步

### 组件结构

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI 主进程                            │
│  ┌─────────────────┐    ┌─────────────────────────────┐    │
│  │   CLI Interface │    │    Integrated Web Server    │    │
│  │   (prompt_loop) │    │    (FastAPI + WebSocket)    │    │
│  └────────┬────────┘    └──────────────┬──────────────┘    │
│           │                            │                    │
│           └────────────┬───────────────┘                    │
│                        ▼                                    │
│           ┌─────────────────────────┐                       │
│           │   SharedAgentState     │                       │
│           │   - Agent 实例          │                       │
│           │   - 消息历史            │                       │
│           │   - WebSocket 连接      │                       │
│           └─────────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼ WebSocket
              ┌─────────────────────┐
              │   Browser Client   │
              │   (HTML/JS/CSS)    │
              └─────────────────────┘
```

## 使用方式

### 1. 集成模式（推荐）

```bash
# 启动 CLI 和 Web UI（默认模式）
python run.py

# 或显式指定集成模式
python run.py --integrated

# 指定端口
python run.py --port 8080

# 不自动打开浏览器
python run.py --no-browser
```

集成模式特点：
- CLI 和 Web UI 共享同一个 Agent 实例
- 消息历史完全同步
- 支持 Esc 键取消任务（CLI）
- 支持停止按钮（Web UI）

### 2. 仅 Web UI 模式

```bash
# 只启动 Web UI，不启动 CLI
python run.py --web-only

# 指定主机和端口
python run.py --web-only --host 0.0.0.0 --port 8080
```

注意：仅 Web UI 模式会创建独立的 Agent 实例，不与 CLI 共享。

### 3. 仅 CLI 模式

```bash
# 只启动 CLI，不启动 Web UI
python run.py --cli-only
```

## API 接口

### REST API

#### GET /api/status
获取当前状态

```json
{
  "ready": true,
  "is_processing": false,
  "model": "MiniMax-M2.5",
  "workspace": "/path/to/workspace",
  "message_count": 10
}
```

#### GET /api/messages
获取消息历史

```json
{
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "Hello",
      "timestamp": "2026-03-03T20:00:00"
    }
  ]
}
```

### WebSocket API

连接地址: `ws://127.0.0.1:9999/ws`

#### 发送消息

```json
{
  "type": "chat",
  "content": "你的问题"
}
```

#### 停止生成

```json
{
  "type": "stop"
}
```

#### 清空历史

```json
{
  "type": "clear"
}
```

#### 接收消息

初始化消息:
```json
{
  "type": "init",
  "data": {
    "ready": true,
    "messages": []
  }
}
```

新消息:
```json
{
  "type": "message",
  "data": {
    "id": "uuid",
    "role": "assistant",
    "content": "回复内容",
    "timestamp": "2026-03-03T20:00:00"
  }
}
```

状态更新:
```json
{
  "type": "status",
  "data": {
    "status": "processing",
    "message": "Agent is thinking..."
  }
}
```

## 核心类

### SharedAgentState

共享的 Agent 状态管理类：

```python
class SharedAgentState:
    agent: Agent              # Agent 实例
    llm_client: LLMClient     # LLM 客户端
    config: Config            # 配置
    workspace_dir: Path       # 工作目录
    messages: List[dict]      # 消息历史
    is_processing: bool       # 是否正在处理
    websocket_connections     # WebSocket 连接列表
```

### IntegratedWebServer

嵌入式 Web 服务器：

```python
class IntegratedWebServer:
    def start(self, open_browser: bool = False)  # 启动服务器
    def stop(self)                                # 停止服务器
```

## 错误处理

### cancel_event 错误修复

在 Web UI 中调用 Agent 时，需要正确设置 `cancel_event`：

```python
async def process_with_agent(user_input: str):
    # 添加用户消息
    shared_state.agent.add_user_message(user_input)
    
    # 创建取消事件
    cancel_event = asyncio.Event()
    shared_state.agent.cancel_event = cancel_event
    
    try:
        result = await shared_state.agent.run()
    finally:
        # 清理
        shared_state.agent.cancel_event = None
```

## 前端技术

- **TailwindCSS** - CSS 框架
- **Marked** - Markdown 解析
- **Highlight.js** - 代码高亮
- **WebSocket** - 实时通信

## 配置选项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | 127.0.0.1 | Web UI 绑定地址 |
| `--port` | 9999 | Web UI 端口 |
| `--no-browser` | False | 不自动打开浏览器 |
| `--web-only` | False | 仅启动 Web UI |
| `--cli-only` | False | 仅启动 CLI |
| `--integrated` | False | 集成模式（默认） |

## 安全注意事项

1. 默认绑定 `127.0.0.1`，仅本地访问
2. 如需远程访问，使用 `--host 0.0.0.0`，但需注意安全风险
3. 没有内置认证机制，请勿暴露在公网

## 未来规划

- [ ] 用户认证系统
- [ ] 多会话支持
- [ ] 文件上传功能
- [ ] 响应式移动端适配
- [ ] 暗色/亮色主题切换