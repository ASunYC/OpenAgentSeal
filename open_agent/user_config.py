#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Open Agent - 用户配置管理模块

统一管理用户配置，包括：
- 大模型配置 (models)
- 智能体配置 (agents)
- 应用设置 (settings)

配置文件: ~/.open-agent/open_agent.json
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path


# ==================== 枚举定义 ====================

class ModelProvider(Enum):
    """大模型厂商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    ZHIPU = "zhipu"
    VOLCANO = "volcano"
    MINIMAX = "minimax"
    SILICONFLOW = "siliconflow"
    MOONSHOT = "moonshot"
    BAICHUAN = "baichuan"
    CUSTOM = "custom"
    
    @classmethod
    def get_display_name(cls, provider: "ModelProvider") -> str:
        """获取显示名称"""
        display_names = {
            cls.OPENAI: "🌐 OpenAI (GPT)",
            cls.ANTHROPIC: "💜 Anthropic (Claude)",
            cls.DEEPSEEK: "🐋 DeepSeek",
            cls.QWEN: "🌟 通义千问 (Qwen)",
            cls.ZHIPU: "🧠 智谱 (ChatGLM)",
            cls.VOLCANO: "🔥 火山大模型 (Volcano)",
            cls.MINIMAX: "🎯 MiniMax",
            cls.SILICONFLOW: "💎 硅基流动 (SiliconFlow)",
            cls.MOONSHOT: "🌙 月之暗面 (Moonshot)",
            cls.BAICHUAN: "🏔️ 百川 (Baichuan)",
            cls.CUSTOM: "⚙️ 自定义 (Custom)",
        }
        return display_names.get(provider, provider.value)
    
    @classmethod
    def get_default_base_url(cls, provider: "ModelProvider") -> str:
        """获取默认 API 地址"""
        default_urls = {
            cls.OPENAI: "https://api.openai.com/v1",
            cls.ANTHROPIC: "https://api.anthropic.com",
            cls.DEEPSEEK: "https://api.deepseek.com",
            cls.QWEN: "https://dashscope.aliyuncs.com/api/v1",
            cls.ZHIPU: "https://open.bigmodel.cn/api/paas/v4",
            cls.VOLCANO: "https://ark.cn-beijing.volces.com/api/coding/v3",
            cls.MINIMAX: "https://api.minimaxi.com/anthropic",
            cls.SILICONFLOW: "https://api.siliconflow.cn/v1",
            cls.MOONSHOT: "https://api.moonshot.cn/v1",
            cls.BAICHUAN: "https://api.baichuan-ai.com/v1",
            cls.CUSTOM: "",
        }
        return default_urls.get(provider, "")
    
    @classmethod
    def get_default_models(cls, provider: "ModelProvider") -> List[str]:
        """获取默认模型列表"""
        default_models = {
            cls.OPENAI: ["gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"],
            cls.ANTHROPIC: ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-sonnet-20240229"],
            cls.DEEPSEEK: ["deepseek-chat", "deepseek-coder"],
            cls.QWEN: ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-max-longcontext"],
            cls.ZHIPU: ["glm-4", "glm-4-plus", "glm-3-turbo"],
            cls.VOLCANO: [],
            cls.MINIMAX: ["MiniMax-M2.5", "MiniMax-Text-01", "MiniMax-VL-01"],
            cls.SILICONFLOW: ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3"],
            cls.MOONSHOT: ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
            cls.BAICHUAN: ["Baichuan4", "Baichuan3-Turbo", "Baichuan2-Turbo"],
            cls.CUSTOM: [],
        }
        return default_models.get(provider, [])


# ==================== 数据类定义 ====================

@dataclass
class ModelConfig:
    """大模型配置"""
    id: str                              # 唯一标识
    name: str                            # 模型名称（如 gpt-4, MiniMax-M2.5）
    display_name: str                    # 显示名称
    provider: str                        # 厂商
    api_key: str                         # API 密钥
    base_url: Optional[str] = None       # 自定义 API 地址
    provider_type: str = "openai"        # SDK 类型: "openai" 或 "anthropic"
    is_default: bool = False             # 是否为默认模型
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig":
        # 兼容旧数据（没有 id 字段）
        if "id" not in data:
            data["id"] = f"model_{uuid.uuid4().hex[:8]}"
        return cls(**data)
    
    @classmethod
    def create(cls, name: str, display_name: str, provider: str, 
               api_key: str, base_url: str = None, provider_type: str = "openai",
               is_default: bool = False) -> "ModelConfig":
        """创建新的模型配置（自动生成 ID）"""
        return cls(
            id=f"model_{uuid.uuid4().hex[:8]}",
            name=name,
            display_name=display_name,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            provider_type=provider_type,
            is_default=is_default
        )


@dataclass
class AgentConfig:
    """智能体配置"""
    id: str                                      # 唯一标识
    name: str                                    # 智能体名称
    model_id: str                                # 使用的模型 ID（引用 ModelConfig.id）
    description: Optional[str] = None            # 描述
    avatar: Optional[str] = None                 # 头像（emoji 或 URL）
    system_prompt: Optional[str] = None          # 系统提示词
    temperature: float = 0.7                     # 温度参数
    max_tokens: int = 4096                       # 最大 token 数
    max_steps: int = 100                         # 最大步骤数
    tools: List[str] = field(default_factory=list)           # 启用的工具列表
    mcp_servers: List[str] = field(default_factory=list)      # 启用的 MCP 服务器
    created_at: str = ""                         # 创建时间
    updated_at: str = ""                         # 更新时间
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        # 兼容旧数据
        if "id" not in data:
            data["id"] = f"agent_{uuid.uuid4().hex[:8]}"
        if "created_at" not in data or not data["created_at"]:
            data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in data or not data["updated_at"]:
            data["updated_at"] = datetime.now().isoformat()
        # 兼容旧数据：如果没有 max_steps 字段，使用默认值 100
        if "max_steps" not in data:
            data["max_steps"] = 100
        return cls(**data)
    
    @classmethod
    def create(cls, name: str, model_id: str, **kwargs) -> "AgentConfig":
        """创建新的智能体配置"""
        now = datetime.now().isoformat()
        return cls(
            id=f"agent_{uuid.uuid4().hex[:8]}",
            name=name,
            model_id=model_id,
            description=kwargs.get("description"),
            avatar=kwargs.get("avatar", "🤖"),
            system_prompt=kwargs.get("system_prompt"),
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4096),
            max_steps=kwargs.get("max_steps", 100),
            tools=kwargs.get("tools", []),
            mcp_servers=kwargs.get("mcp_servers", []),
            created_at=now,
            updated_at=now
        )


def _get_default_workspace() -> str:
    """获取默认工作目录
    
    打包后：使用 exe 所在目录
    开发模式：使用 ./workspace
    """
    try:
        from open_agent.utils.path_utils import is_frozen, get_executable_dir
        if is_frozen():
            return str(get_executable_dir())
    except Exception:
        pass
    return "./workspace"


@dataclass
class AppSettings:
    """应用设置"""
    language: str = "zh-CN"              # 语言
    theme: str = "dark"                  # 主题: light, dark, system
    font_size: str = "medium"            # 字体大小: small, medium, large
    workspace: str = field(default_factory=_get_default_workspace)  # 工作目录
    auto_save: bool = True               # 自动保存
    stream_response: bool = True         # 流式响应
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppSettings":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ==================== 配置管理器 ====================

class UserConfigManager:
    """用户配置管理器
    
    配置文件位置: ~/.open-agent/open_agent.json
    """
    
    CONFIG_DIR = Path.home() / ".open-agent"
    CONFIG_FILE = CONFIG_DIR / "open_agent.json"
    
    # 默认配置
    DEFAULT_CONFIG = {
        "version": "2.0",
        "models": [],
        "agents": [],
        "settings": {
            "language": "zh-CN",
            "theme": "dark",
            "font_size": "medium",
            "workspace": "./workspace",
            "auto_save": True,
            "stream_response": True
        },
        "default_model_id": None,
        "default_agent_id": None
    }
    
    # 使用类名作为键的单例存储，支持子类各自独立的单例
    _instances: Dict[str, "UserConfigManager"] = {}
    
    def __new__(cls):
        """单例模式 - 每个子类有独立的单例"""
        cls_name = cls.__name__
        if cls_name not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[cls_name] = instance
        return cls._instances[cls_name]
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._config: Dict[str, Any] = {}
        self._ensure_config_exists()
    
    def _ensure_config_exists(self):
        """确保配置文件存在"""
        if not self.CONFIG_DIR.exists():
            self.CONFIG_DIR.mkdir(parents=True)
        
        if self.CONFIG_FILE.exists():
            # 加载现有配置
            self._config = self._load_config()
        else:
            # 创建默认配置
            self._config = self.DEFAULT_CONFIG.copy()
            
            # 首次创建时，自动创建一个默认 agent
            self._create_default_agent_on_init()
            
            self._save_config()
    
    def _create_default_agent_on_init(self):
        """首次创建配置时，自动创建一个默认 agent"""
        # 获取默认模型（如果有的话）
        default_model_id = self._get_first_model_id_or_none()
        
        # 创建默认 agent
        default_agent = AgentConfig.create(
            name="默认助手",
            model_id=default_model_id or "",  # 如果没有模型，设为空字符串
            description="默认的智能体助手",
            avatar="🤖"
        )
        
        # 添加到配置中
        self._config["agents"] = [default_agent.to_dict()]
        self._config["default_agent_id"] = default_agent.id
        
        print(f"✅ 已创建默认智能体：{default_agent.name}")
        if default_model_id:
            print(f"   已关联默认模型 ID: {default_model_id}")
        else:
            print(f"   暂无可用模型，请在设置中添加模型后再选择")
    
    def _get_first_model_id_or_none(self) -> Optional[str]:
        """获取第一个模型的 ID（用于默认 agent）"""
        models = self._config.get("models", [])
        if models:
            # 优先返回标记为 is_default 的模型
            for m in models:
                if m.get("is_default"):
                    return m.get("id")
            # 否则返回第一个模型
            return models[0].get("id")
        return None
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            # 使用 utf-8-sig 自动处理 BOM
            with open(self.CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  加载配置文件失败: {e}")
            return self.DEFAULT_CONFIG.copy()
    
    def _save_config(self):
        """保存配置文件"""
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ 保存配置文件失败: {e}")
    
    def reload(self) -> None:
        """强制重新加载配置文件"""
        self._config = self._load_config()
    
    # ==================== 模型管理 ====================
    
    def get_all_models(self) -> List[ModelConfig]:
        """获取所有模型配置"""
        models = []
        for m in self._config.get("models", []):
            try:
                models.append(ModelConfig.from_dict(m))
            except Exception:
                pass
        return models
    
    def get_model(self, model_id: str) -> Optional[ModelConfig]:
        """根据 ID 获取模型配置"""
        for model in self.get_all_models():
            if model.id == model_id:
                return model
        return None
    
    def get_default_model(self) -> Optional[ModelConfig]:
        """获取默认模型配置"""
        default_id = self._config.get("default_model_id")
        if default_id:
            return self.get_model(default_id)
        
        # 回退：查找 is_default=True 的模型
        for model in self.get_all_models():
            if model.is_default:
                return model
        
        # 如果只有一个模型，返回它
        models = self.get_all_models()
        if len(models) == 1:
            return models[0]
        
        return None
    
    def add_model(self, model: ModelConfig):
        """添加模型配置"""
        models = self._config.get("models", [])
        
        # 检查是否已存在相同 ID
        for i, m in enumerate(models):
            if m.get("id") == model.id:
                models[i] = model.to_dict()
                break
        else:
            models.append(model.to_dict())
        
        self._config["models"] = models
        
        # 如果是第一个模型，设为默认
        if len(models) == 1:
            self._config["default_model_id"] = model.id
        
        self._save_config()
    
    def update_model(self, model: ModelConfig):
        """更新模型配置"""
        models = self._config.get("models", [])
        for i, m in enumerate(models):
            if m.get("id") == model.id:
                models[i] = model.to_dict()
                self._save_config()
                return
        # 如果不存在，添加
        self.add_model(model)
    
    def delete_model(self, model_id: str) -> bool:
        """删除模型配置"""
        models = self._config.get("models", [])
        original_count = len(models)
        
        self._config["models"] = [m for m in models if m.get("id") != model_id]
        
        if len(self._config["models"]) < original_count:
            # 更新默认模型
            if self._config.get("default_model_id") == model_id:
                remaining = self._config["models"]
                self._config["default_model_id"] = remaining[0].get("id") if remaining else None
            
            # 检查是否有智能体使用此模型
            agents = self.get_agents_by_model(model_id)
            if agents:
                print(f"⚠️  有 {len(agents)} 个智能体正在使用此模型")
            
            self._save_config()
            return True
        
        return False
    
    def set_default_model(self, model_id: str):
        """设置默认模型"""
        self._config["default_model_id"] = model_id
        
        # 更新 is_default 标志
        models = self._config.get("models", [])
        for m in models:
            m["is_default"] = (m.get("id") == model_id)
        
        self._save_config()
    
    # ==================== 智能体管理 ====================
    
    def get_all_agents(self) -> List[AgentConfig]:
        """获取所有智能体配置"""
        agents = []
        for a in self._config.get("agents", []):
            try:
                agents.append(AgentConfig.from_dict(a))
            except Exception:
                pass
        return agents
    
    def get_agent(self, agent_id: str) -> Optional[AgentConfig]:
        """根据 ID 获取智能体配置"""
        for agent in self.get_all_agents():
            if agent.id == agent_id:
                return agent
        return None
    
    def get_default_agent(self) -> Optional[AgentConfig]:
        """获取默认智能体
        
        如果 default_agent_id 为空但存在 agents，返回第一个 agent
        如果 agents 为空但 models 有值，自动创建一个默认 agent
        """
        default_id = self._config.get("default_agent_id")
        
        # 如果有默认 ID，返回对应的 agent
        if default_id:
            agent = self.get_agent(default_id)
            if agent:
                return agent
        
        # 如果没有默认 ID，但有 agents，返回第一个
        agents = self.get_all_agents()
        if agents:
            return agents[0]
        
        # 如果 agents 为空，但 models 有值，自动创建一个默认 agent
        models = self._config.get("models", [])
        if models:
            # 获取默认模型 ID
            model_id = self._get_first_model_id_or_none()
            if model_id:
                return self._create_default_agent(model_id)
        
        return None
    
    def _create_default_agent(self, model_id: str) -> AgentConfig:
        """创建默认 agent 并保存
        
        Args:
            model_id: 关联的模型 ID
            
        Returns:
            创建的 AgentConfig 对象
        """
        default_agent = AgentConfig.create(
            name="默认助手",
            model_id=model_id,
            description="默认的智能体助手",
            avatar="🤖"
        )
        
        # 添加到配置中
        agents = self._config.get("agents", [])
        agents.append(default_agent.to_dict())
        self._config["agents"] = agents
        self._config["default_agent_id"] = default_agent.id
        self._save_config()
        
        print(f"✅ 已创建默认智能体：{default_agent.name}，关联模型 ID: {model_id}")
        return default_agent
    
    def get_agents_by_model(self, model_id: str) -> List[AgentConfig]:
        """获取使用指定模型的智能体列表"""
        return [a for a in self.get_all_agents() if a.model_id == model_id]
    
    def add_agent(self, agent: AgentConfig):
        """添加智能体配置"""
        agents = self._config.get("agents", [])
        
        # 检查是否已存在相同 ID
        for i, a in enumerate(agents):
            if a.get("id") == agent.id:
                agents[i] = agent.to_dict()
                break
        else:
            agents.append(agent.to_dict())
        
        self._config["agents"] = agents
        self._save_config()
    
    def update_agent(self, agent: AgentConfig):
        """更新智能体配置"""
        agent.updated_at = datetime.now().isoformat()
        agents = self._config.get("agents", [])
        for i, a in enumerate(agents):
            if a.get("id") == agent.id:
                agents[i] = agent.to_dict()
                self._save_config()
                return
        self.add_agent(agent)
    
    def delete_agent(self, agent_id: str) -> bool:
        """删除智能体配置"""
        agents = self._config.get("agents", [])
        original_count = len(agents)
        
        self._config["agents"] = [a for a in agents if a.get("id") != agent_id]
        
        if len(self._config["agents"]) < original_count:
            # 更新默认智能体
            if self._config.get("default_agent_id") == agent_id:
                remaining = self._config["agents"]
                self._config["default_agent_id"] = remaining[0].get("id") if remaining else None
            
            self._save_config()
            return True
        
        return False
    
    def set_default_agent(self, agent_id: str):
        """设置默认智能体"""
        self._config["default_agent_id"] = agent_id
        self._save_config()
    
    # ==================== 应用设置 ====================
    
    def get_settings(self) -> AppSettings:
        """获取应用设置"""
        settings_data = self._config.get("settings", {})
        return AppSettings.from_dict(settings_data)
    
    def update_settings(self, settings: AppSettings):
        """更新应用设置"""
        self._config["settings"] = settings.to_dict()
        self._save_config()
    
    def update_setting(self, key: str, value: Any):
        """更新单个设置项"""
        settings = self._config.get("settings", {})
        settings[key] = value
        self._config["settings"] = settings
        self._save_config()
    
    # ==================== 导出/导入 ====================
    
    def export_config(self, path: str):
        """导出配置到指定路径"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)
    
    def import_config(self, path: str):
        """从指定路径导入配置"""
        with open(path, 'r', encoding='utf-8') as f:
            self._config = json.load(f)
        self._save_config()
    
    def get_full_config(self) -> Dict[str, Any]:
        """获取完整配置（用于 API 返回）"""
        return self._config.copy()


# ==================== 兼容旧接口 ====================

# 保留对旧 ModelConfigManager 的兼容
class ModelConfigManager(UserConfigManager):
    """兼容旧版本的模型配置管理器"""
    
    def __init__(self):
        super().__init__()
    
    def get_provider_config(self, provider: str) -> Dict[str, Any]:
        """
        获取厂商的配置信息
        
        Args:
            provider: 厂商标识符
            
        Returns:
            包含 base_url, models, api_key 的配置字典
        """
        try:
            provider_enum = ModelProvider(provider)
            default_base_url = ModelProvider.get_default_base_url(provider_enum)
            default_models = ModelProvider.get_default_models(provider_enum)
        except ValueError:
            default_base_url = ""
            default_models = []
        
        # 查找该厂商的已保存配置
        saved_api_key = ""
        saved_base_url = ""
        for model in self.get_all_models():
            if model.provider == provider:
                saved_api_key = model.api_key
                saved_base_url = model.base_url or ""
                break
        
        return {
            "base_url": saved_base_url or default_base_url,
            "models": default_models,
            "api_key": saved_api_key,
        }


# ==================== 便捷函数 ====================

def get_user_config() -> UserConfigManager:
    """获取用户配置管理器单例"""
    return UserConfigManager()


def get_default_model() -> Optional[ModelConfig]:
    """获取默认模型配置"""
    return get_user_config().get_default_model()


def get_default_agent() -> Optional[AgentConfig]:
    """获取默认智能体配置"""
    return get_user_config().get_default_agent()


def list_all_models() -> List[ModelConfig]:
    """获取所有模型配置"""
    return get_user_config().get_all_models()


def list_all_agents() -> List[AgentConfig]:
    """获取所有智能体配置"""
    return get_user_config().get_all_agents()


# 导出
__all__ = [
    "ModelProvider",
    "ModelConfig",
    "AgentConfig", 
    "AppSettings",
    "UserConfigManager",
    "ModelConfigManager",
    "get_user_config",
    "get_default_model",
    "get_default_agent",
    "list_all_models",
    "list_all_agents",
]