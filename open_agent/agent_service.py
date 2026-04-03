#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Open Agent - Agent管理服务

核心服务，管理所有Agent实例：
- 创建/销毁/列出所有Agent
- 管理Agent生命周期
- 会话存储（使用memory_manager压缩存储）
- 提供全局访问点
"""

import asyncio
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class AgentType(Enum):
    """Agent类型"""
    WEB = "web"          # Web UI Agent
    CLI = "cli"          # CLI Agent
    BACKGROUND = "background"  # 后台Agent


class AgentStatus(Enum):
    """Agent状态"""
    IDLE = "idle"        # 空闲
    RUNNING = "running"  # 运行中
    STOPPED = "stopped"  # 已停止
    ERROR = "error"      # 错误


@dataclass
class AgentInfo:
    """Agent信息"""
    agent_id: str
    agent_type: str  # "web", "cli", "background"
    status: str  # "idle", "running", "stopped", "error"
    created_at: str
    name: str = ""
    description: str = ""
    model: str = ""
    provider: str = ""
    message_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentSession:
    """Agent会话数据"""
    agent_id: str
    messages: List[Dict[str, Any]]
    system_prompt: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AgentService:
    """Agent管理服务 - 单例模式
    
    核心功能：
    1. 管理所有Agent实例
    2. 创建/销毁/列出Agent
    3. 会话存储和恢复
    4. 与记忆模块集成
    """
    
    _instance: Optional['AgentService'] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9998,
        workspace_dir: str = None,
    ):
        """初始化Agent服务
        
        Args:
            host: Web服务器主机
            port: Web服务器端口
            workspace_dir: 工作目录
        """
        if self._initialized:
            return
        
        self.host = host
        self.port = port
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        
        # Agent注册表
        self._agents: Dict[str, Any] = {}  # agent_id -> Agent实例
        self._agent_info: Dict[str, AgentInfo] = {}  # agent_id -> AgentInfo
        self._sessions: Dict[str, AgentSession] = {}  # agent_id -> AgentSession
        
        # 会话存储目录
        self.session_dir = Path.home() / ".open-agent" / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # 记忆管理器（延迟导入避免循环依赖）
        self._memory_manager = None
        
        # 状态回调
        self._status_callbacks: List[Callable] = []
        
        # Web服务器引用
        self._web_server = None
        
        # 运行状态
        self._running = False
        
        self._initialized = True
        logger.info(f"AgentService initialized: host={host}, port={port}, workspace={self.workspace_dir}")
    
    @classmethod
    def get_instance(cls) -> 'AgentService':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def initialize(
        cls,
        host: str = "127.0.0.1",
        port: int = 9998,
        workspace_dir: str = None,
    ) -> 'AgentService':
        """初始化单例"""
        instance = cls(host=host, port=port, workspace_dir=workspace_dir)
        return instance
    
    @property
    def memory_manager(self):
        """延迟加载记忆管理器"""
        if self._memory_manager is None:
            from open_agent.memory_manager import get_memory_manager
            self._memory_manager = get_memory_manager()
        return self._memory_manager
    
    def start(self, open_browser: bool = False):
        """启动服务
        
        Args:
            open_browser: 是否打开浏览器
        """
        if self._running:
            logger.warning("AgentService already running")
            return
        
        self._running = True
        logger.info("AgentService started")
        
        # 启动Web服务器
        self._start_web_server(open_browser)
    
    def stop(self):
        """停止服务"""
        self._running = False
        
        # 保存所有活跃会话
        for agent_id in list(self._agents.keys()):
            try:
                self.save_session(agent_id)
            except Exception as e:
                logger.error(f"Failed to save session {agent_id}: {e}")
        
        # 停止所有Agent
        for agent_id in list(self._agents.keys()):
            try:
                self.destroy_agent(agent_id)
            except Exception as e:
                logger.error(f"Failed to destroy agent {agent_id}: {e}")
        
        # 停止Web服务器 (新架构 - app/runner)
        if hasattr(self, '_uvicorn_server') and self._uvicorn_server:
            try:
                self._uvicorn_server.should_exit = True
                logger.info("Web server stopped")
            except Exception as e:
                logger.error(f"Failed to stop web server: {e}")
        
        logger.info("AgentService stopped")
    
    def _find_available_port(self, start_port: int, max_attempts: int = 10) -> int:
        """查找可用端口
        
        Args:
            start_port: 起始端口
            max_attempts: 最大尝试次数
            
        Returns:
            可用的端口号
        """
        import socket
        
        for port in range(start_port, start_port + max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind((self.host, port))
                    # 端口可用
                    if port != start_port:
                        logger.info(f"Port {start_port} is in use, using port {port}")
                    return port
            except OSError:
                # 端口被占用，尝试下一个
                continue
        
        # 如果都不可用，返回起始端口（让uvicorn报错）
        return start_port
    
    def _start_web_server(self, open_browser: bool = False):
        """启动Web服务器 - 使用新的Vue前端架构"""
        try:
            # 使用新的 FastAPI 应用 (Vue + SSE)
            from open_agent.app import create_app
            from open_agent.app.runner import init_chat_manager
            import uvicorn
            import threading
            
            # 查找可用端口
            actual_port = self._find_available_port(self.port)
            if actual_port != self.port:
                logger.warning(f"Port {self.port} is in use, switching to port {actual_port}")
                self.port = actual_port
                # 更新 web_url
                import sys
                if hasattr(sys.modules.get('launcher'), '_web_url'):
                    sys.modules['launcher']._web_url = f"http://{self.host}:{self.port}"
            
            # 初始化 ChatManager
            init_chat_manager()
            
            # 创建 FastAPI 应用
            app = create_app()
            
            # 在后台线程启动服务器
            def run_server():
                config = uvicorn.Config(
                    app,
                    host=self.host,
                    port=self.port,
                    log_level="warning",
                )
                server = uvicorn.Server(config)
                self._uvicorn_server = server
                import asyncio
                asyncio.run(server.serve())
            
            self._server_thread = threading.Thread(target=run_server, daemon=True)
            self._server_thread.start()
            
            # 延迟打开浏览器
            if open_browser:
                import webbrowser
                import time
                import http.client
                
                def open_browser_delayed():
                    url = f"http://{self.host}:{self.port}"
                    max_retries = 10
                    for attempt in range(max_retries):
                        try:
                            conn = http.client.HTTPConnection(self.host, self.port, timeout=1)
                            conn.request("GET", "/api/health")
                            response = conn.getresponse()
                            conn.close()
                            if response.status == 200:
                                logger.info(f"Opening browser: {url}")
                                webbrowser.open(url)
                                return
                        except Exception:
                            time.sleep(0.5)
                    webbrowser.open(url)
                
                threading.Thread(target=open_browser_delayed, daemon=True).start()
            
            logger.info(f"Web server started at http://{self.host}:{self.port}, open_browser={open_browser}")
        except Exception as e:
            logger.error(f"Failed to start web server: {e}")
            import traceback
            traceback.print_exc()
    
    # ==================== Agent管理 ====================
    
    def create_agent(
        self,
        agent_type: str = "background",
        name: str = "",
        description: str = "",
        model: str = "",
        provider: str = "",
        config: Dict[str, Any] = None,
    ) -> AgentInfo:
        """创建新Agent
        
        Args:
            agent_type: Agent类型 (web/cli/background)
            name: Agent名称
            description: Agent描述
            model: 模型名称
            provider: 提供商
            config: 配置参数
            
        Returns:
            AgentInfo
        """
        from open_agent.agent import Agent
        from open_agent.config import Config
        from open_agent import LLMClient
        from open_agent.schema import LLMProvider
        from open_agent.user_config import ModelConfigManager
        
        agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        
        # 获取模型配置
        manager = ModelConfigManager()
        model_config = manager.get_default_model()
        
        if not model and model_config:
            model = model_config.name
        if not provider and model_config:
            provider = model_config.provider
        
        # 创建Agent实例
        llm_client = self._create_llm_client(model, provider, config)
        tools = self._create_tools(config)
        system_prompt = self._get_system_prompt(config)
        
        agent = Agent(
            llm_client=llm_client,
            system_prompt=system_prompt,
            tools=tools,
            max_steps=config.get("max_steps", 100) if config else 100,
            workspace_dir=str(self.workspace_dir),
        )
        
        # 注册Agent
        now = datetime.now().isoformat()
        info = AgentInfo(
            agent_id=agent_id,
            agent_type=agent_type,
            status="idle",
            created_at=now,
            name=name or f"Agent {agent_id[:8]}",
            description=description,
            model=model,
            provider=provider,
        )
        
        self._agents[agent_id] = agent
        self._agent_info[agent_id] = info
        
        # 创建会话
        self._sessions[agent_id] = AgentSession(
            agent_id=agent_id,
            messages=[{"role": "system", "content": system_prompt}] if system_prompt else [],
            system_prompt=system_prompt,
            updated_at=now,
        )
        
        # 通知状态变化
        self._notify_status_change("agent_created", info.to_dict())
        
        # 通过 WebSocket 通知 Web UI
        self._notify_web_ui("agent_created", info.to_dict())
        
        logger.info(f"Created agent: {agent_id} (type={agent_type})")
        return info
    
    def destroy_agent(self, agent_id: str) -> bool:
        """销毁Agent
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否成功
        """
        if agent_id not in self._agents:
            return False
        
        # 保存会话
        self.save_session(agent_id)
        
        # 移除Agent
        del self._agents[agent_id]
        if agent_id in self._agent_info:
            info = self._agent_info[agent_id]
            del self._agent_info[agent_id]
        if agent_id in self._sessions:
            del self._sessions[agent_id]
        
        # 通知状态变化
        self._notify_status_change("agent_destroyed", {"agent_id": agent_id})
        
        logger.info(f"Destroyed agent: {agent_id}")
        return True
    
    def list_agents(self) -> List[AgentInfo]:
        """列出所有Agent
        
        Returns:
            AgentInfo列表
        """
        return list(self._agent_info.values())
    
    def get_agent(self, agent_id: str) -> Optional[Any]:
        """获取Agent实例
        
        Args:
            agent_id: Agent ID
            
        Returns:
            Agent实例或None
        """
        return self._agents.get(agent_id)
    
    def get_agent_info(self, agent_id: str) -> Optional[AgentInfo]:
        """获取Agent信息
        
        Args:
            agent_id: Agent ID
            
        Returns:
            AgentInfo或None
        """
        return self._agent_info.get(agent_id)
    
    def update_agent_status(self, agent_id: str, status: str):
        """更新Agent状态
        
        Args:
            agent_id: Agent ID
            status: 新状态
        """
        if agent_id in self._agent_info:
            self._agent_info[agent_id].status = status
            self._notify_status_change("agent_status", {
                "agent_id": agent_id,
                "status": status
            })
    
    # ==================== 会话管理 ====================
    
    def save_session(self, agent_id: str) -> bool:
        """保存会话到记忆模块
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否成功
        """
        if agent_id not in self._sessions:
            return False
        
        session = self._sessions[agent_id]
        
        try:
            # 压缩存储会话内容
            content = self._compress_session(session)
            
            # 使用记忆模块存储
            self.memory_manager.record(
                content=content,
                category="conversation",
                importance="medium",
                keywords=[agent_id, "session", session.agent_type],
                metadata={
                    "agent_id": agent_id,
                    "message_count": len(session.messages),
                    "system_prompt": session.system_prompt[:500] if session.system_prompt else "",
                }
            )
            
            logger.info(f"Saved session for agent: {agent_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            return False
    
    def load_session(self, agent_id: str) -> Optional[List[Dict]]:
        """从记忆模块加载会话
        
        Args:
            agent_id: Agent ID
            
        Returns:
            消息列表或None
        """
        try:
            memories = self.memory_manager.recall(
                keywords=[agent_id, "session"],
                category="conversation",
                limit=1,
            )
            
            if memories:
                session_data = memories[0].metadata
                if "messages" in session_data:
                    return session_data["messages"]
            
            return None
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None
    
    def add_message(self, agent_id: str, role: str, content: str):
        """添加消息到会话
        
        Args:
            agent_id: Agent ID
            role: 角色 (user/assistant/system/tool)
            content: 消息内容
        """
        if agent_id not in self._sessions:
            return
        
        from datetime import datetime
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        
        self._sessions[agent_id].messages.append(message)
        self._sessions[agent_id].updated_at = datetime.now().isoformat()
        
        # 更新消息计数
        if agent_id in self._agent_info:
            self._agent_info[agent_id].message_count = len(self._sessions[agent_id].messages)
    
    def get_messages(self, agent_id: str) -> List[Dict]:
        """获取会话消息
        
        Args:
            agent_id: Agent ID
            
        Returns:
            消息列表
        """
        if agent_id not in self._sessions:
            return []
        return self._sessions[agent_id].messages
    
    def clear_messages(self, agent_id: str):
        """清空会话消息
        
        Args:
            agent_id: Agent ID
        """
        if agent_id in self._sessions:
            # 保留系统提示
            system_prompt = self._sessions[agent_id].system_prompt
            self._sessions[agent_id].messages = []
            if system_prompt:
                self._sessions[agent_id].messages.append({
                    "role": "system",
                    "content": system_prompt,
                })
            
            if agent_id in self._agent_info:
                self._agent_info[agent_id].message_count = 1
    
    def _compress_session(self, session: AgentSession) -> str:
        """压缩会话内容
        
        Args:
            session: 会话数据
            
        Returns:
            压缩后的内容
        """
        # 简单压缩：只保留最后20条消息的摘要
        messages = session.messages
        
        if len(messages) <= 20:
            return json.dumps(messages, ensure_ascii=False)
        
        # 保留系统提示和最后20条消息
        compressed = {
            "system_prompt": session.system_prompt,
            "message_count": len(messages),
            "recent_messages": messages[-20:],
            "summary": f"Session with {len(messages)} messages"
        }
        
        return json.dumps(compressed, ensure_ascii=False)
    
    # ==================== 辅助方法 ====================
    
    def _create_llm_client(
        self,
        model: str,
        provider: str,
        config: Dict[str, Any] = None,
    ):
        """创建LLM客户端"""
        from open_agent import LLMClient
        from open_agent.schema import LLMProvider
        from open_agent.user_config import ModelConfigManager
        from open_agent.retry import RetryConfig
        
        manager = ModelConfigManager()
        model_config = manager.get_default_model()
        
        if not model and model_config:
            model = model_config.name
        if not provider and model_config:
            provider = model_config.provider
        
        api_key = ""
        api_base = ""
        
        if model_config:
            api_key = model_config.api_key
            api_base = model_config.base_url or ""
        
        if config:
            api_key = config.get("api_key", api_key)
            api_base = config.get("api_base", api_base)
        
        # Determine provider type based on provider_type field first, then fallback to base_url detection
        provider_type_str = model_config.provider_type.lower() if model_config and model_config.provider_type else ""
        base_url_lower = (api_base or "").lower()
        
        # Use ANTHROPIC provider for:
        # - provider_type is "anthropic"
        # - base_url contains "anthropic"
        if provider_type_str == "anthropic" or "anthropic" in base_url_lower:
            provider_type = LLMProvider.ANTHROPIC
        else:
            provider_type = LLMProvider.OPENAI
        
        # [DEBUG] 打印 LLM 配置信息
        provider_name = provider if provider else (model_config.provider if model_config else "unknown")
        api_key_masked = f"{api_key[:8]}...{api_key[-4:]}" if api_key and len(api_key) > 12 else "(too short or empty)"
        print(f"[DEBUG] _create_llm_client: provider={provider_name}, provider_type={provider_type}, base_url={api_base}, model={model}")
        print(f"[DEBUG] _create_llm_client: api_key={api_key_masked}")
        
        return LLMClient(
            api_key=api_key,
            provider=provider_type,
            api_base=api_base,
            model=model,
        )
    
    def _create_tools(self, config: Dict[str, Any] = None) -> list:
        """创建工具集
        
        Returns:
            Tool对象列表 (Agent期望的是list[Tool]而不是Dict)
        """
        from open_agent.tools.bash_tool import BashTool, BashOutputTool, BashKillTool
        from open_agent.tools.file_tools import ReadTool, WriteTool, EditTool
        from open_agent.tools.note_tool import RecordNoteTool, RecallNotesTool
        from open_agent.tools.choice_tool import AskUserChoiceTool
        
        tools = []
        
        # Bash工具
        bash_tool = BashTool(workspace_dir=str(self.workspace_dir))
        tools.append(bash_tool)
        tools.append(BashOutputTool())
        tools.append(BashKillTool())
        
        # 文件工具
        tools.append(ReadTool(workspace_dir=str(self.workspace_dir)))
        tools.append(WriteTool(workspace_dir=str(self.workspace_dir)))
        tools.append(EditTool(workspace_dir=str(self.workspace_dir)))
        
        # 记忆工具
        tools.append(RecordNoteTool())
        tools.append(RecallNotesTool())
        
        # 选择工具
        tools.append(AskUserChoiceTool())
        
        return tools
    
    def _get_system_prompt(self, config: Dict[str, Any] = None) -> str:
        """获取系统提示"""
        from open_agent.config import Config
        
        try:
            config_path = Config.get_default_config_path()
            config_obj = Config.from_yaml(config_path)
            system_prompt_path = Config.find_config_file(config_obj.agent.system_prompt_path)
            
            if system_prompt_path and system_prompt_path.exists():
                return system_prompt_path.read_text(encoding="utf-8")
        except Exception:
            pass
        
        return "You are an intelligent assistant that helps users complete various tasks."
    
    def _notify_status_change(self, event: str, data: Any):
        """通知状态变化"""
        for callback in self._status_callbacks:
            try:
                callback(event, data)
            except Exception as e:
                logger.error(f"Status callback error: {e}")
    
    def _notify_web_ui(self, event: str, data: Any):
        """通知 Web UI (新架构 - 通过 SSE)
        
        Args:
            event: 事件类型 (agent_created, agent_destroyed, agent_status)
            data: 事件数据
        """
        try:
            # 新架构：通过 app/runner 的 SSE 广播
            from open_agent.app.runner import get_chat_manager
            import asyncio
            
            chat_manager = get_chat_manager()
            if chat_manager:
                agent_id = data.get("agent_id", "") if isinstance(data, dict) else ""
                
                # 构建事件数据
                event_data = {
                    "type": event,
                    "agent_id": agent_id,
                    "data": data,
                    "timestamp": datetime.now().isoformat(),
                }
                
                # 尝试广播
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(chat_manager.broadcast_event(event_data))
                    else:
                        loop.run_until_complete(chat_manager.broadcast_event(event_data))
                except RuntimeError:
                    # 没有事件循环，创建一个新的
                    asyncio.run(chat_manager.broadcast_event(event_data))
                
        except Exception as e:
            logger.debug(f"Failed to notify web ui: {e}")
    
    def add_status_callback(self, callback: Callable):
        """添加状态回调"""
        self._status_callbacks.append(callback)
    
    def remove_status_callback(self, callback: Callable):
        """移除状态回调"""
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)


# 便捷函数
_service_instance: Optional[AgentService] = None


def get_agent_service() -> AgentService:
    """获取Agent服务实例"""
    global _service_instance
    if _service_instance is None:
        _service_instance = AgentService.get_instance()
    return _service_instance


def init_agent_service(
    host: str = "127.0.0.1",
    port: int = 9998,
    workspace_dir: str = None,
) -> AgentService:
    """初始化Agent服务"""
    global _service_instance
    _service_instance = AgentService.initialize(
        host=host,
        port=port,
        workspace_dir=workspace_dir,
    )
    return _service_instance