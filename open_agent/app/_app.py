"""
FastAPI Application Factory following CoPaw's architecture pattern.

This module provides the main FastAPI application with:
- Chat API routes (REST + SSE streaming)
- Static file serving for Vue frontend
- CORS middleware
- Lifespan management
"""

import logging
import os
import uuid
import shutil
import json
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from open_agent.version import get_version

logger = logging.getLogger(__name__)

# Global app instance
_app: Optional[FastAPI] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("🌐 Open Agent Web UI started")

    # Initialize chat manager
    from open_agent.app.runner import init_chat_manager

    init_chat_manager()

    yield

    logger.info("🌐 Open Agent Web UI stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    from open_agent.utils.stdio import configure_utf8_stdio

    configure_utf8_stdio()

    global _app

    if _app is not None:
        return _app

    app = FastAPI(
        title="Open Agent",
        description="Intelligent Agent with Web UI",
        version=get_version(),
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include chat router
    from open_agent.app.runner import chat_router

    app.include_router(chat_router)

    # Include legacy routes for backward compatibility
    _setup_legacy_routes(app)

    # Setup static file serving for Vue frontend
    _setup_static_files(app)

    _app = app
    return app


def _setup_legacy_routes(app: FastAPI):
    """Setup legacy routes for backward compatibility"""

    @app.get("/api/health")
    async def health_check():
        """Health check endpoint"""
        return {"status": "ok", "ready": True}

    @app.get("/api/agents")
    async def list_agents():
        """List all agents - returns array directly for frontend compatibility"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            agents = manager.get_all_agents()
            return [a.to_dict() for a in agents]
        except Exception as e:
            logger.error(f"Failed to list agents: {e}")
            return []

    @app.post("/api/agents")
    async def save_agent(data: dict):
        """Create or update agent (legacy)"""
        try:
            from open_agent.user_config import get_user_config, AgentConfig

            manager = get_user_config()

            agent_id = data.get("id")

            # 检查是否已存在该 ID 的 agent
            existing_agent = manager.get_agent(agent_id) if agent_id else None

            if existing_agent:
                # 更新现有 agent
                agent = AgentConfig(
                    id=agent_id,
                    name=data.get("name", "新智能体"),
                    model_id=data.get("model_id", ""),
                    description=data.get("description", ""),
                    avatar=data.get("avatar", "🤖"),
                    system_prompt=data.get("system_prompt"),
                    temperature=data.get("temperature", 0.7),
                    max_tokens=data.get("max_tokens", 4096),
                    max_steps=data.get("max_steps", 100),
                    tools=data.get("tools", []),
                    mcp_servers=data.get("mcp_servers", []),
                    created_at=existing_agent.created_at,
                    updated_at="",
                )
                manager.update_agent(agent)
            else:
                # 创建新的 agent 配置
                # 使用前端传来的 ID（如果有的话），否则生成新的
                new_agent_id = data.get("id")
                if new_agent_id:
                    # 使用前端传来的 ID
                    agent = AgentConfig(
                        id=new_agent_id,
                        name=data.get("name", "新智能体"),
                        model_id=data.get("model_id", ""),
                        description=data.get("description", ""),
                        avatar=data.get("avatar", "🤖"),
                        system_prompt=data.get("system_prompt"),
                        temperature=data.get("temperature", 0.7),
                        max_tokens=data.get("max_tokens", 4096),
                        max_steps=data.get("max_steps", 100),
                        tools=data.get("tools", []),
                        mcp_servers=data.get("mcp_servers", []),
                        created_at="",
                        updated_at="",
                    )
                else:
                    # 后端生成新的 ID
                    agent = AgentConfig.create(
                        name=data.get("name", "新智能体"),
                        model_id=data.get("model_id", ""),
                        description=data.get("description", ""),
                        avatar=data.get("avatar", "🤖"),
                        system_prompt=data.get("system_prompt"),
                        temperature=data.get("temperature", 0.7),
                        max_tokens=data.get("max_tokens", 4096),
                        max_steps=data.get("max_steps", 100),
                        tools=data.get("tools", []),
                        mcp_servers=data.get("mcp_servers", []),
                    )
                manager.add_agent(agent)

            return {"success": True, "agent": agent.to_dict()}
        except Exception as e:
            logger.error(f"Failed to save agent: {e}")
            return {"success": False, "error": str(e)}

    @app.delete("/api/agents/{agent_id}")
    async def delete_agent(agent_id: str):
        """Delete agent (legacy)"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            success = manager.delete_agent(agent_id)
            return {"success": success}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/agents/{agent_id}/messages")
    async def get_messages(agent_id: str):
        """Get agent messages (legacy)"""
        try:
            from open_agent.agent_service import get_agent_service

            service = get_agent_service()
            messages = service.get_messages(agent_id)
            return {"messages": messages}
        except Exception as e:
            return {"messages": [], "error": str(e)}

    @app.get("/api/models")
    async def list_models():
        """List all model configurations"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            models = manager.get_all_models()
            return {
                "models": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "display_name": m.display_name,
                        "provider": m.provider,
                        "is_default": m.is_default,
                    }
                    for m in models
                ]
            }
        except Exception as e:
            return {"models": [], "error": str(e)}

    @app.get("/api/model-configs")
    async def get_model_configs():
        """Get model configuration list - returns array directly for frontend compatibility"""
        try:
            from open_agent.user_config import get_user_config, ModelProvider

            manager = get_user_config()
            manager.reload()  # 每次请求都重新加载配置
            models = manager.get_all_models()

            # 预设的提供商可用模型列表
            provider_models_map = {
                ModelProvider.OPENAI: [
                    "gpt-4o",
                    "gpt-4o-mini",
                    "gpt-4-turbo",
                    "gpt-3.5-turbo",
                    "o1",
                    "o1-mini",
                    "o1-preview",
                ],
                ModelProvider.ANTHROPIC: [
                    "claude-3-5-sonnet-20241022",
                    "claude-3-opus-20240229",
                    "claude-3-haiku-20240307",
                    "claude-3-5-haiku-20241022",
                ],
                ModelProvider.DEEPSEEK: [
                    "deepseek-chat",
                    "deepseek-coder",
                    "deepseek-reasoner",
                ],
                ModelProvider.ZHIPU: [
                    "glm-4",
                    "glm-4-flash",
                    "glm-3-turbo",
                    "glm-4-plus",
                ],
                ModelProvider.MOONSHOT: [
                    "moonshot-v1-8k",
                    "moonshot-v1-32k",
                    "moonshot-v1-128k",
                ],
                ModelProvider.MINIMAX: [
                    "abab6.5s-chat",
                    "abab6.5-chat",
                    "abab5.5-chat",
                    "abab5.5s-chat",
                ],
            }

            # 如果用户没有配置任何模型，返回默认模板
            if not models:
                default_configs = []
                default_providers = [
                    ModelProvider.OPENAI,
                    ModelProvider.ANTHROPIC,
                    ModelProvider.DEEPSEEK,
                    ModelProvider.ZHIPU,
                    ModelProvider.MOONSHOT,
                    ModelProvider.MINIMAX,
                ]

                for provider in default_providers:
                    provider_models = provider_models_map.get(provider, [])
                    provider_display_name = ModelProvider.get_display_name(provider)
                    default_configs.append(
                        {
                            "id": f"default_{provider.value}",
                            "name": provider_models[0] if provider_models else "",
                            "display_name": f"{provider_display_name} ({provider_models[0] if provider_models else ''})",
                            "provider": provider.value,
                            "provider_display_name": provider_display_name,
                            "is_default": provider == ModelProvider.OPENAI,
                            "isDefault": provider == ModelProvider.OPENAI,
                            "api_key": None,
                            "has_api_key": False,
                            "base_url": ModelProvider.get_default_base_url(provider),
                            "provider_type": "anthropic"
                            if provider == ModelProvider.ANTHROPIC
                            else "openai",
                            "available_models": provider_models,
                        }
                    )

                return default_configs

            # 用户有配置时，也要返回 available_models
            result = []
            for m in models:
                # 尝试匹配提供商的预设模型列表
                try:
                    provider_enum = (
                        ModelProvider(m.provider.lower()) if m.provider else None
                    )
                except ValueError:
                    provider_enum = None

                available_models = provider_models_map.get(
                    provider_enum, [m.name] if m.name else []
                )

                # 获取提供商友好名称
                provider_display_name = ""
                if provider_enum:
                    provider_display_name = ModelProvider.get_display_name(
                        provider_enum
                    )
                else:
                    # 对于自定义提供商，使用原始值
                    provider_display_name = m.provider

                result.append(
                    {
                        "id": m.id,
                        "name": m.name,
                        "display_name": m.display_name,
                        "provider": m.provider,
                        "provider_display_name": provider_display_name,
                        "is_default": m.is_default,
                        "isDefault": m.is_default,
                        "api_key": m.api_key,  # 返回实际 API Key 明文
                        "api_key_length": len(m.api_key) if m.api_key else 0,
                        "has_api_key": bool(m.api_key),
                        "base_url": m.base_url,
                        "provider_type": m.provider_type,
                        "available_models": available_models,
                    }
                )

            return result
        except Exception as e:
            logger.error(f"Failed to get model configs: {e}")
            return []

    @app.post("/api/model-configs")
    async def save_model_config(data: dict):
        """Save model configuration - 支持创建和更新"""
        try:
            from open_agent.user_config import get_user_config, ModelConfig

            manager = get_user_config()

            model_id = data.get("id")

            # 检查是否是更新现有配置（id 存在且配置已存在）
            existing_model = manager.get_model(model_id) if model_id else None

            if existing_model:
                # 更新现有配置 - 保留原有 ID
                model = ModelConfig(
                    id=model_id,  # 使用前端传来的 ID
                    name=data.get("name", existing_model.name),
                    display_name=data.get("display_name", existing_model.display_name),
                    provider=data.get("provider", existing_model.provider),
                    api_key=data.get("api_key", existing_model.api_key),
                    base_url=data.get("base_url", existing_model.base_url),
                    provider_type=data.get(
                        "provider_type", existing_model.provider_type
                    ),
                    is_default=data.get("is_default", existing_model.is_default),
                )
                manager.update_model(model)
            else:
                # 创建新配置 - 生成新 ID
                model = ModelConfig.create(
                    name=data.get("name", ""),
                    display_name=data.get("display_name", data.get("name", "")),
                    provider=data.get("provider", ""),
                    api_key=data.get("api_key", ""),
                    base_url=data.get("base_url"),
                    provider_type=data.get("provider_type", "openai"),
                    is_default=data.get("is_default", False),
                )
                manager.add_model(model)

            return {"success": True, "data": {"id": model.id}}
        except Exception as e:
            logger.error(f"Failed to save model config: {e}")
            return {"success": False, "error": str(e)}

    @app.delete("/api/model-configs/{model_id}")
    async def delete_model_config(model_id: str):
        """Delete model configuration"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            success = manager.delete_model(model_id)
            return {"success": success}
        except Exception as e:
            logger.error(f"Failed to delete model config: {e}")
            return {"success": False, "error": str(e)}

    @app.post("/api/model-configs/{model_id}/default")
    async def set_default_model(model_id: str):
        """Set default model"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            manager.set_default_model(model_id)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to set default model: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/providers")
    async def get_providers():
        """Get all available model providers"""
        try:
            from open_agent.user_config import ModelProvider

            providers = []
            for provider in ModelProvider:
                providers.append(
                    {
                        "id": provider.value,
                        "name": provider.value,
                        "display_name": ModelProvider.get_display_name(provider),
                        "default_base_url": ModelProvider.get_default_base_url(
                            provider
                        ),
                        "default_models": ModelProvider.get_default_models(provider),
                    }
                )
            return providers
        except Exception as e:
            logger.error(f"Failed to get providers: {e}")
            return []

    @app.get("/api/providers/{provider}/models")
    async def get_provider_models(provider: str):
        """Get available models for a specific provider"""
        try:
            from open_agent.user_config import ModelProvider

            # 尝试匹配提供商枚举
            try:
                provider_enum = ModelProvider(provider.lower())
            except ValueError:
                # 自定义提供商，返回空列表
                return {"models": [], "provider": provider, "display_name": provider}

            # 获取预设模型列表
            default_models = ModelProvider.get_default_models(provider_enum)

            # 扩展的模型列表（包含更多模型）
            extended_models_map = {
                ModelProvider.OPENAI: [
                    "gpt-4o",
                    "gpt-4o-mini",
                    "gpt-4-turbo",
                    "gpt-4",
                    "gpt-3.5-turbo",
                    "o1",
                    "o1-mini",
                    "o1-preview",
                    "gpt-4-turbo-preview",
                ],
                ModelProvider.ANTHROPIC: [
                    "claude-3-5-sonnet-20241022",
                    "claude-3-5-haiku-20241022",
                    "claude-3-opus-20240229",
                    "claude-3-sonnet-20240229",
                    "claude-3-haiku-20240307",
                    "claude-2.1",
                    "claude-2.0",
                ],
                ModelProvider.DEEPSEEK: [
                    "deepseek-chat",
                    "deepseek-coder",
                    "deepseek-reasoner",
                ],
                ModelProvider.QWEN: [
                    "qwen-turbo",
                    "qwen-plus",
                    "qwen-max",
                    "qwen-max-longcontext",
                    "qwen2.5-72b-instruct",
                    "qwen2.5-32b-instruct",
                ],
                ModelProvider.ZHIPU: [
                    "glm-4",
                    "glm-4-plus",
                    "glm-4-flash",
                    "glm-3-turbo",
                ],
                ModelProvider.VOLCANO: [
                    "doubao-pro-32k",
                    "doubao-pro-128k",
                    "doubao-lite-32k",
                ],
                ModelProvider.MINIMAX: [
                    "abab6.5s-chat",
                    "abab6.5-chat",
                    "abab5.5-chat",
                    "abab5.5s-chat",
                ],
                ModelProvider.SILICONFLOW: [
                    "Qwen/Qwen2.5-72B-Instruct",
                    "Qwen/Qwen2.5-32B-Instruct",
                    "deepseek-ai/DeepSeek-V3",
                    "deepseek-ai/DeepSeek-R1",
                ],
                ModelProvider.MOONSHOT: [
                    "moonshot-v1-8k",
                    "moonshot-v1-32k",
                    "moonshot-v1-128k",
                ],
                ModelProvider.BAICHUAN: [
                    "Baichuan4",
                    "Baichuan3-Turbo",
                    "Baichuan2-Turbo",
                ],
                ModelProvider.CUSTOM: [],
            }

            models = extended_models_map.get(provider_enum, default_models)

            return {
                "models": models,
                "provider": provider_enum.value,
                "display_name": ModelProvider.get_display_name(provider_enum),
            }
        except Exception as e:
            logger.error(f"Failed to get provider models: {e}")
            return {"models": [], "error": str(e)}

    @app.get("/api/settings")
    async def get_settings():
        """Get settings"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            settings = manager.get_settings()
            return {
                "language": settings.language,
                "theme": settings.theme,
                "font_size": settings.font_size,
                "workspace": settings.workspace,
                "auto_save": settings.auto_save,
                "stream_response": settings.stream_response,
                "use_cot": settings.use_cot,
                "enable_skills": settings.enable_skills,
            }
        except Exception as e:
            logger.error(f"Failed to get settings: {e}")
            return {"workspace": str(Path.cwd()), "language": "zh-CN", "theme": "light"}

    @app.get("/api/version")
    async def get_app_version():
        """Get application version info."""
        try:
            from open_agent.version import get_version, get_release_date

            return {
                "success": True,
                "version": get_version(),
                "release_date": get_release_date(),
            }
        except Exception as e:
            logger.error(f"Failed to get version: {e}")
            return {
                "success": False,
                "error": str(e),
                "version": get_version(),
                "release_date": "",
            }

    @app.post("/api/settings")
    async def update_settings(data: dict):
        """Update settings"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()

            # 更新单个设置项
            for key, value in data.items():
                manager.update_setting(key, value)

            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to update settings: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/smart-routing")
    async def get_smart_routing():
        """Get smart routing configuration."""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            return manager.get_smart_routing()
        except Exception as e:
            logger.error(f"Failed to get smart routing config: {e}")
            return {
                "enabled": False,
                "text_model_id": "",
                "vision_model_id": "",
                "audio_model_id": "",
                "fallback_model_id": "",
                "error": str(e),
            }

    @app.post("/api/smart-routing")
    async def update_smart_routing(data: dict):
        """Update smart routing configuration."""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            config = manager.update_smart_routing(data)
            return {"success": True, "data": config}
        except Exception as e:
            logger.error(f"Failed to update smart routing config: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/settings/work-directory")
    async def get_work_directory():
        """Get work directory"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            settings = manager.get_settings()
            return {"path": settings.workspace}
        except Exception as e:
            logger.error(f"Failed to get work directory: {e}")
            return {"path": str(Path.cwd())}

    @app.post("/api/settings/work-directory")
    async def set_work_directory(data: dict):
        """Set work directory"""
        try:
            from open_agent.user_config import get_user_config

            manager = get_user_config()
            manager.update_setting("workspace", data.get("path", ""))
            return {"success": True, "path": data.get("path", "")}
        except Exception as e:
            logger.error(f"Failed to set work directory: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/skills")
    async def list_skills():
        """List all available skills - returns array directly for frontend compatibility"""
        try:
            from open_agent.tools.skill_loader import SkillLoader
            from open_agent.config import Config
            from open_agent.utils.path_utils import get_external_skills_dir, is_frozen

            # Get skills directory - use Config.get_package_dir() to find skills directory
            # instead of find_config_file which is for files, not directories
            skills_dir = None

            # Try to find skills directory in multiple locations
            # Priority 1: Frozen mode - exe-local skills or seeded user skills
            if is_frozen():
                skills_dir = get_external_skills_dir()

            # Priority 2: Development mode - current directory's open_agent/skills
            if not skills_dir:
                dev_skills = Path.cwd() / "open_agent" / "skills"
                if dev_skills.exists():
                    skills_dir = dev_skills

            # Priority 3: Package installation directory's skills subdirectory
            if not skills_dir:
                package_skills = Config.get_package_dir() / "skills"
                if package_skills.exists():
                    skills_dir = package_skills

            # Priority 4: User app directory
            if not skills_dir:
                user_app_dir = Path.home() / ".open-agent"
                user_skills = user_app_dir / "open_agent" / "skills"
                if user_skills.exists():
                    skills_dir = user_skills

            # Fallback to default
            if not skills_dir:
                skills_dir = Path(__file__).parent.parent / "skills"

            logger.info(f"[SKILLS] Loading skills from: {skills_dir}")

            # Load skills
            loader = SkillLoader(str(skills_dir))
            skills = loader.discover_skills()

            # Return skill metadata
            result = []
            for skill in skills:
                # Map skill names to icons
                icon_map = {
                    "document-skills": "📄",
                    "web-search": "🔍",
                    "bash-tool": "💻",
                    "file-tools": "📁",
                    "mcp-builder": "🔧",
                    "skill-creator": "✨",
                    "canvas-design": "🎨",
                    "algorithmic-art": "🖼️",
                    "brand-guidelines": "📋",
                    "internal-comms": "📢",
                    "slack-gif-creator": "🎬",
                    "theme-factory": "🎭",
                    "webapp-testing": "🧪",
                    "artifacts-builder": "🏗️",
                    "template-skill": "📝",
                }

                icon = icon_map.get(skill.name, "📦")

                result.append(
                    {
                        "name": skill.name,
                        "description": skill.description,
                        "icon": icon,
                        "enabled": True,  # Default enabled
                    }
                )

            logger.info(f"[SKILLS] Loaded {len(result)} skills")
            return result
        except Exception as e:
            logger.error(f"Failed to list skills: {e}")
            return []

    def _get_writable_mcp_config_path() -> Path:
        """Return the MCP config path, creating a user-writable config when needed."""
        from open_agent.config import Config, get_user_app_dir
        from open_agent.utils.path_utils import get_external_config_dir, is_frozen

        user_config_dir = get_user_app_dir() / "config"
        user_config_dir.mkdir(parents=True, exist_ok=True)
        user_config_path = user_config_dir / "mcp.json"
        if user_config_path.exists():
            return user_config_path

        seed_paths = []
        if is_frozen():
            external_config_dir = get_external_config_dir()
            if external_config_dir:
                seed_paths.append(external_config_dir / "mcp.json")
        seed_paths.extend([
            Path.cwd() / "open_agent" / "config" / "mcp.json",
            Config.get_package_dir() / "config" / "mcp.json",
        ])

        for seed_path in seed_paths:
            if seed_path.exists() and seed_path.resolve() != user_config_path.resolve():
                user_config_path.write_text(seed_path.read_text(encoding="utf-8"), encoding="utf-8")
                return user_config_path

        user_config_path.write_text(json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
        return user_config_path

    @app.get("/api/mcp/config")
    async def get_mcp_config():
        """Get MCP server configuration."""
        try:
            config_path = _get_writable_mcp_config_path()
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            servers = raw.get("mcpServers", {})
            if not isinstance(servers, dict):
                servers = {}

            server_list = []
            for name, config in servers.items():
                if not isinstance(config, dict):
                    continue
                server_config = dict(config)
                server_config.update({
                    "name": name,
                    "original_name": name,
                    "type": config.get("type") or ("streamable_http" if config.get("url") else "stdio"),
                    "command": config.get("command", ""),
                    "url": config.get("url", ""),
                    "args": config.get("args", []),
                    "env": config.get("env", {}),
                    "disabled": bool(config.get("disabled", False)),
                })
                server_list.append(server_config)

            return {
                "success": True,
                "path": str(config_path),
                "servers": server_list,
            }
        except Exception as e:
            logger.error(f"Failed to get MCP config: {e}")
            return {"success": False, "error": str(e), "path": "", "servers": []}

    @app.post("/api/mcp/config")
    async def save_mcp_config(data: dict):
        """Save MCP server configuration."""
        try:
            config_path = _get_writable_mcp_config_path()
            servers_data = data.get("servers", [])
            try:
                raw = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                raw = {"mcpServers": {}}
            if not isinstance(raw, dict):
                raw = {"mcpServers": {}}
            previous_servers = raw.get("mcpServers", {})
            if not isinstance(previous_servers, dict):
                previous_servers = {}
            mcp_servers = {}

            if not isinstance(servers_data, list):
                raise ValueError("servers must be a list")

            for server in servers_data:
                if not isinstance(server, dict):
                    continue

                name = str(server.get("name", "")).strip()
                if not name:
                    continue

                server_type = str(server.get("type", "stdio")).strip() or "stdio"
                original_name = str(server.get("original_name") or name).strip()
                original_config = previous_servers.get(original_name, {})
                config = dict(original_config) if isinstance(original_config, dict) else {}
                config["type"] = server_type
                config["disabled"] = bool(server.get("disabled", False))

                command = str(server.get("command", "")).strip()
                url = str(server.get("url", "")).strip()
                args = server.get("args", [])
                env = server.get("env", {})

                if command:
                    config["command"] = command
                else:
                    config.pop("command", None)
                if url:
                    config["url"] = url
                else:
                    config.pop("url", None)
                if isinstance(args, list):
                    config["args"] = [str(arg) for arg in args]
                if isinstance(env, dict):
                    config["env"] = {str(key): str(value) for key, value in env.items()}

                mcp_servers[name] = config

            config_path.parent.mkdir(parents=True, exist_ok=True)
            raw["mcpServers"] = mcp_servers
            config_path.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {"success": True, "path": str(config_path)}
        except Exception as e:
            logger.error(f"Failed to save MCP config: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/commands")
    async def list_commands():
        """List available commands - returns array directly for frontend compatibility"""
        return [
            {
                "id": "clear",
                "name": "Clear Chat",
                "description": "Clear current chat history",
            },
            {
                "id": "export",
                "name": "Export Chat",
                "description": "Export chat history to file",
            },
        ]

    @app.get("/api/dashboard/stats")
    async def get_dashboard_stats():
        """Get dashboard statistics"""
        try:
            from open_agent.agent_service import get_agent_service
            from open_agent.app.runner import get_chat_manager

            service = get_agent_service()
            agents = service.list_agents()
            active_agents = [a for a in agents if getattr(a, "status", "") == "running"]
            chat_manager = get_chat_manager()
            chats = await chat_manager.list_chats()
            runner_message_count = sum(len(chat_manager.get_messages(chat.session_id)) for chat in chats)
            agent_message_count = sum(getattr(a, "message_count", 0) for a in agents)
            total_messages = max(runner_message_count, agent_message_count)

            today = datetime.now().date()
            activity_by_date = {
                (today - timedelta(days=offset)).isoformat(): 0
                for offset in range(6, -1, -1)
            }
            for chat in chats:
                updated_at = getattr(chat, "updated_at", None)
                if isinstance(updated_at, str):
                    try:
                        updated_date = datetime.fromisoformat(updated_at).date()
                    except ValueError:
                        continue
                elif updated_at:
                    updated_date = updated_at.date()
                else:
                    continue

                key = updated_date.isoformat()
                if key in activity_by_date:
                    activity_by_date[key] += max(len(chat_manager.get_messages(chat.session_id)), 1)

            return {
                "total_sessions": len(agents),
                "total_chats": len(chats),
                "active_sessions": len(active_agents),
                "active_agents": len(active_agents),
                "total_messages": total_messages,
                "recent_activity": [
                    {"date": date, "count": count}
                    for date, count in activity_by_date.items()
                ],
            }
        except Exception as e:
            return {
                "total_sessions": 0,
                "total_chats": 0,
                "active_sessions": 0,
                "active_agents": 0,
                "total_messages": 0,
                "recent_activity": [],
                "error": str(e),
            }

    @app.get("/api/logs")
    async def list_logs():
        """List recent log files and tails."""
        try:
            from open_agent.utils.path_utils import get_logs_dir

            logs_dir = get_logs_dir()
            files = []
            cutoff = datetime.now().timestamp() - 10 * 24 * 60 * 60
            log_files = [
                path
                for path in logs_dir.rglob("*.log")
                if path.is_file() and path.stat().st_mtime >= cutoff
            ]
            for log_file in sorted(log_files, key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
                try:
                    lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    lines = []
                files.append({
                    "name": log_file.name,
                    "path": str(log_file),
                    "size": log_file.stat().st_size,
                    "updated_at": datetime.fromtimestamp(log_file.stat().st_mtime).isoformat(),
                    "tail": lines[-40:],
                })

            return {"success": True, "path": str(logs_dir), "files": files}
        except Exception as e:
            logger.error(f"Failed to list logs: {e}")
            return {"success": False, "error": str(e), "path": "", "files": []}

    @app.get("/api/tasks")
    async def list_tasks():
        """List current task dispatcher state."""
        try:
            from open_agent.task_queue import get_task_dispatcher

            dispatcher = get_task_dispatcher()
            if not dispatcher:
                return {
                    "success": True,
                    "status": {"status": "idle", "status_message": "Dispatcher not initialized", "running": False, "queue_stats": {}, "worker_status": {}},
                    "tasks": [],
                    "running": [],
                    "pending": [],
                    "completed": [],
                }

            all_tasks = [task.to_dict() for task in dispatcher.get_all_tasks()]
            return {
                "success": True,
                "status": dispatcher.get_status(),
                "tasks": all_tasks,
                "running": [task.to_dict() for task in dispatcher.get_running_tasks()],
                "pending": [task.to_dict() for task in dispatcher.get_pending_tasks()],
                "completed": [task.to_dict() for task in dispatcher.get_completed_tasks()],
            }
        except Exception as e:
            logger.error(f"Failed to list tasks: {e}")
            return {"success": False, "error": str(e), "status": {}, "tasks": [], "running": [], "pending": [], "completed": []}


# MIME type mapping for static files
MIME_TYPES = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".eot": "application/vnd.ms-fontobject",
    ".map": "application/json",
}


def _get_mime_type(file_path: Path) -> str:
    """Get MIME type based on file extension."""
    ext = file_path.suffix.lower()
    return MIME_TYPES.get(ext, "application/octet-stream")


def _get_static_dir() -> Path:
    """Find the static directory for Vue frontend.

    Works in both development and packaged (frozen) modes.
    """
    import sys

    # Possible static directories to check
    static_dirs = []

    # 1. Check if running from frozen exe - use extracted source directory
    if getattr(sys, "frozen", False):
        # The source is extracted to ~/.open-agent/open_agent/
        extracted_dir = Path.home() / ".open-agent" / "open_agent" / "app" / "static"
        static_dirs.append(extracted_dir)
        logger.info(f"[STATIC] Checking extracted static dir: {extracted_dir}")

    # 2. Development mode - relative to this file
    current_dir = Path(__file__).parent
    static_dirs.append(current_dir / "static")
    static_dirs.append(current_dir / "web" / "dist")

    # 3. Check OPEN_AGENT_SOURCE_DIR environment variable
    source_dir = os.environ.get("OPEN_AGENT_SOURCE_DIR")
    if source_dir:
        static_dirs.append(Path(source_dir) / "app" / "static")

    # 4. Check common installation locations
    static_dirs.append(Path.home() / ".open-agent" / "open_agent" / "app" / "static")

    # Return first existing directory
    logger.debug(f"[STATIC] Checking {len(static_dirs)} potential static directories")
    for i, dir_path in enumerate(static_dirs):
        exists = dir_path.exists()
        logger.debug(f"[STATIC] [{i + 1}] {dir_path} - exists: {exists}")
        if exists:
            # Also check if assets subdirectory exists
            assets_dir = dir_path / "assets"
            assets_exists = assets_dir.exists()
            logger.info(
                f"[STATIC] Found static directory: {dir_path}, assets dir exists: {assets_exists}"
            )
            if assets_exists:
                # List assets for debugging
                try:
                    assets_files = list(assets_dir.iterdir())
                    logger.debug(f"[STATIC] Assets files count: {len(assets_files)}")
                except Exception as e:
                    logger.warning(f"[STATIC] Could not list assets: {e}")
            return dir_path

    # Return default (may not exist)
    logger.warning(
        f"[STATIC] No static directory found, returning default: {current_dir / 'static'}"
    )
    return current_dir / "static"


def _setup_static_files(app: FastAPI):
    """Setup static file serving for Vue frontend

    Note: We use custom routes instead of StaticFiles because StaticFiles
    may not correctly set MIME types for JS files in packaged executables.
    """
    import os

    # Find static directory
    static_dir = _get_static_dir()

    if static_dir.exists():
        logger.info(f"📂 Serving static files from: {static_dir}")

        # Custom route for assets (instead of StaticFiles mount)
        @app.get("/assets/{file_path:path}")
        async def serve_asset(file_path: str):
            from fastapi import HTTPException
            from fastapi.responses import Response
            import re

            logger.debug(f"[ASSET] Request for: {file_path}")
            asset_file = static_dir / "assets" / file_path
            logger.debug(f"[ASSET] Looking for file at: {asset_file}")
            logger.debug(
                f"[ASSET] File exists: {asset_file.exists()}, is_file: {asset_file.is_file() if asset_file.exists() else 'N/A'}"
            )

            if not asset_file.exists() or not asset_file.is_file():
                logger.warning(f"[ASSET] File not found: {asset_file}")
                raise HTTPException(status_code=404)

            # Read file content
            content = asset_file.read_bytes()
            mime_type = _get_mime_type(asset_file)
            logger.debug(f"[ASSET] Serving {file_path} with MIME: {mime_type}")

            # Check if file has hash in name (Vite format: name.[hash].js or name-[hash].css)
            # Hashed files can be cached long-term since content change means new filename
            has_hash = bool(re.search(r"[.-][a-f0-9]{8,}[.-]", file_path))
            cache_control = (
                "public, max-age=31536000, immutable" if has_hash else "no-cache"
            )

            return Response(
                content=content,
                media_type=mime_type,
                headers={
                    "Cache-Control": cache_control,
                },
            )

        # Serve index.html for all non-API routes (SPA support)
        @app.get("/{path:path}")
        async def serve_spa(path: str):
            from fastapi import HTTPException
            from fastapi.responses import Response
            import re

            logger.debug(f"[SPA] Request for path: {path}")

            # Don't intercept API routes
            if path.startswith("api/") or path.startswith("ws"):
                raise HTTPException(status_code=404)

            # Try to serve specific file first
            file_path = static_dir / path
            logger.debug(f"[SPA] Looking for file at: {file_path}")
            if file_path.exists() and file_path.is_file():
                content = file_path.read_bytes()
                mime_type = _get_mime_type(file_path)
                logger.debug(f"[SPA] Serving file {path} with MIME: {mime_type}")

                # For index.html, prevent caching to ensure users get latest version
                if path == "index.html":
                    return Response(
                        content=content,
                        media_type=mime_type,
                        headers={"Cache-Control": "no-store"},
                    )

                # For other files in static dir, check if they have hash in name
                has_hash = bool(re.search(r"[.-][a-f0-9]{8,}[.-]", path))
                cache_control = (
                    "public, max-age=31536000, immutable" if has_hash else "no-cache"
                )
                return Response(
                    content=content,
                    media_type=mime_type,
                    headers={"Cache-Control": cache_control},
                )

            # Serve index.html for SPA routes
            index_file = static_dir / "index.html"
            if index_file.exists():
                logger.debug(f"[SPA] Serving index.html for path: {path}")
                content = index_file.read_bytes()
                # Prevent caching of index.html to ensure users always get latest version
                return Response(
                    content=content,
                    media_type="text/html",
                    headers={"Cache-Control": "no-store"},
                )

            logger.warning(f"[SPA] No file found for path: {path}")
            raise HTTPException(status_code=404)
    else:
        logger.warning(f"⚠️ Static directory not found: {static_dir}")
        logger.warning(
            "Run 'npm run build' in open_agent/app/web to build the frontend"
        )


def get_app() -> FastAPI:
    """Get or create the FastAPI application"""
    if _app is None:
        return create_app()
    return _app
