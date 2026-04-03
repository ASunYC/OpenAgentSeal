# Sub-Agent System Design Document

## Overview

The Sub-Agent system provides a comprehensive solution for creating, managing, and communicating with sub-agents that run in independent threads. This document describes the architecture, components, and design decisions of the system.

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Main Agent                               │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                     SubAgentManager                          │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐│ │
│  │  │ RoleRegistry│ │SessionManager│ │    WorkspaceManager    ││ │
│  │  └─────────────┘ └─────────────┘ └─────────────────────────┘│ │
│  │  ┌─────────────────────────────────────────────────────────┐│ │
│  │  │              SubAgentWrapper Pool                        ││ │
│  │  │  ┌───────────┐ ┌───────────┐ ┌───────────┐              ││ │
│  │  │  │ SubAgent1 │ │ SubAgent2 │ │ SubAgent3 │ ...          ││ │
│  │  │  │ (Thread)  │ │ (Thread)  │ │ (Thread)  │              ││ │
│  │  │  └───────────┘ └───────────┘ └───────────┘              ││ │
│  │  └─────────────────────────────────────────────────────────┘│ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    MultiWindowUI                             │ │
│  │  ┌──────────────────────┬────────────────────────────────┐  │ │
│  │  │   Main Chat Window   │      Sub-Agent Panel           │  │ │
│  │  │     (2/3 width)      │  ┌──────────────────────────┐  │  │ │
│  │  │                      │  │   Chat Lobby (2/3 ht)    │  │  │ │
│  │  │                      │  ├──────────────────────────┤  │  │ │
│  │  │                      │  │   Agent List (1/3 ht)    │  │  │ │
│  │  │                      │  └──────────────────────────┘  │  │ │
│  │  └──────────────────────┴────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Module Structure

```
open_agent/sub_agent/
├── __init__.py          # Module exports
├── roles.py             # Role definitions and registry
├── session.py           # Session management
├── workspace.py         # Git-based workspace coordination
├── manager.py           # Sub-agent lifecycle management
└── ui.py                # Multi-window terminal UI
```

## Core Components

### 1. Role System (`roles.py`)

The role system defines specialized agent personas with tailored system prompts.

#### Predefined Roles

| Role ID | Name | Description |
|---------|------|-------------|
| `code_expert` | 代码高手 | Programming, debugging, code review specialist |
| `doc_master` | 文档大师 | Technical documentation, API docs specialist |
| `design_master` | 设计大师 | System architecture, UI/UX design specialist |
| `test_expert` | 测试专家 | Testing, QA, test automation specialist |
| `data_analyst` | 数据分析师 | Data analysis, SQL, visualization specialist |
| `devops_expert` | DevOps专家 | CI/CD, Docker, Kubernetes specialist |
| `security_expert` | 安全专家 | Security audit, vulnerability analysis specialist |
| `general_assistant` | 通用助手 | General purpose assistant |

#### Role Structure

```python
@dataclass
class SubAgentRole:
    role_id: str           # Unique identifier
    name: str              # Display name
    description: str       # Brief description
    system_prompt: str     # Detailed system prompt
    skills: List[str]      # Associated skills
    tools_preference: List[str]  # Preferred tools
```

### 2. Session System (`session.py`)

Manages communication sessions between main agent and sub-agents.

#### Session Flow

```
Main Agent                    Session Manager                 Sub-Agent
    │                              │                             │
    │  create_session()            │                             │
    │─────────────────────────────>│                             │
    │                              │  new Session                │
    │                              │────────────────────────────>│
    │                              │                             │
    │  send_message(msg, to=agent) │                             │
    │─────────────────────────────>│  deliver_message()          │
    │                              │────────────────────────────>│
    │                              │                             │
    │                              │  response                   │
    │                              │<────────────────────────────│
    │  receive_message()           │                             │
    │<─────────────────────────────│                             │
```

#### Session Data Structure

```python
@dataclass
class Session:
    session_id: str           # Unique session ID
    main_agent_id: str        # Main agent identifier
    sub_agent_id: str         # Sub-agent identifier
    created_at: datetime      # Creation timestamp
    messages: List[Message]   # Message history
    status: SessionStatus     # active/closed
```

### 3. Workspace Management (`workspace.py`)

Git-based workspace coordination to prevent conflicts.

#### Workflow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Main Agent    │     │  Git Repository │     │   Sub-Agent     │
│                 │     │                 │     │                 │
│  1. Pull latest │────>│   main branch   │<────│  1. Pull latest │
│  2. Make changes│     │                 │     │  2. Make changes│
│  3. Commit      │────>│                 │<────│  3. Commit      │
│  4. Push        │     │                 │     │  4. Push        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Conflict Handler│
                    │ - Auto merge    │
                    │ - Report issues │
                    └─────────────────┘
```

#### Operations

- `init_workspace()`: Initialize Git repository
- `checkout_branch(branch_name)`: Create/switch to branch
- `commit_changes(message)`: Commit local changes
- `pull_updates()`: Pull remote changes
- `resolve_conflicts()`: Handle merge conflicts

### 4. Sub-Agent Manager (`manager.py`)

Central manager for sub-agent lifecycle.

#### Lifecycle States

```
         ┌─────────┐
         │  IDLE   │
         └────┬────┘
              │ start()
              ▼
         ┌─────────┐
         │ RUNNING │◄────────────┐
         └────┬────┘             │
    complete │  │ error          │ resume()
              ▼  ▼                │
    ┌───────────────┐            │
    │ COMPLETED     │            │
    │ ERROR         │            │
    │ CANCELLED     │────────────┘
    └───────────────┘
```

#### SubAgentWrapper

```python
class SubAgentWrapper:
    """Wrapper for a sub-agent instance."""
    
    agent_id: str
    role: SubAgentRole
    status: SubAgentStatus
    thread: threading.Thread
    message_queue: queue.Queue
    
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def send_message(self, content: str) -> None: ...
    def get_result(self) -> Optional[str]: ...
```

### 5. Multi-Window UI (`ui.py`)

Terminal-based multi-window interface.

#### Layout

```
┌────────────────────────────────────┬──────────────────────────┐
│                                    │   🏠 聊天大厅 (2/3 高度)  │
│       主会话窗口                    │   显示所有Agent对话       │
│       (2/3 宽度)                   │   输入框支持 @提及        │
│                                    ├──────────────────────────┤
│                                    │   📋 Agent列表 (1/3 高度) │
│                                    │   显示状态和基本信息      │
└────────────────────────────────────┴──────────────────────────┘
```

#### Components

- **MultiWindowUI**: Main UI controller
- **ChatLobby**: Multi-agent chat interface
- **TerminalCodes**: ANSI terminal control codes

## Data Storage

### Directory Structure

```
workspace/
├── sub_agents/                    # Sub-agent data directory
│   ├── sub_1708123456/           # Individual agent directory
│   │   ├── session.json          # Session information
│   │   ├── messages.json         # Message history
│   │   ├── result.json           # Execution result
│   │   └── state.json            # Current state
│   ├── sub_1708234567/
│   │   └── ...
│   └── registry.json             # Agent registry
└── .git/                         # Git repository
```

### Registry Format

```json
{
  "agents": [
    {
      "agent_id": "sub_1708123456",
      "role": "code_expert",
      "task": "Fix login bug",
      "status": "running",
      "created_at": "2024-01-15T10:30:00",
      "branch": "sub-agent/sub_1708123456"
    }
  ]
}
```

## Communication Protocol

### Message Types

```python
class MessageType(Enum):
    TASK = "task"           # Task assignment
    QUERY = "query"         # Information query
    RESPONSE = "response"   # Response to query
    STATUS = "status"       # Status update
    ERROR = "error"         # Error report
    CONTROL = "control"     # Control commands
```

### Message Format

```python
@dataclass
class Message:
    id: str
    type: MessageType
    sender: str
    receiver: str
    content: str
    timestamp: datetime
    metadata: dict
```

## CLI Integration

### Commands

| Command | Description |
|---------|-------------|
| `/open <role> <task>` | Create a new sub-agent |
| `/close <id>` | Close/delete a sub-agent |
| `/sub-agents` | List all sub-agents |
| `/panel` | Toggle sub-agent panel |
| `/lobby` | Show chat lobby |
| `/agents` | Show agent list |
| `/switch-agent <id>` | Switch to specific agent |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Tab` | Toggle sub-agent panel |
| `Esc` | Cancel current operation |

## Error Handling

### Error Types

- `SubAgentError`: Base error class
- `SubAgentCreationError`: Failed to create sub-agent
- `SubAgentCommunicationError`: Message delivery failed
- `SubAgentTimeoutError`: Operation timeout
- `WorkspaceConflictError`: Git conflict

### Error Recovery

1. Automatic retry for transient errors
2. Graceful degradation for non-critical failures
3. State preservation for recovery

## Performance Considerations

### Thread Management

- Each sub-agent runs in a dedicated thread
- Thread pool for resource management
- Graceful shutdown on exit

### Memory Management

- Message history limit (last 100 messages)
- Automatic cleanup of completed agents
- State serialization for persistence

## Future Enhancements

1. **Agent-to-Agent Communication**: Direct messaging between sub-agents
2. **Task Dependencies**: Define dependencies between sub-agent tasks
3. **Resource Limits**: CPU/memory limits for sub-agents
4. **Distributed Execution**: Run sub-agents on remote machines
5. **Web UI**: Browser-based multi-window interface

## Version History

- **v1.0.0** (2024-01): Initial implementation
  - Basic sub-agent creation and management
  - Role system with 8 predefined roles
  - Session-based communication
  - Git workspace coordination
  - Multi-window terminal UI