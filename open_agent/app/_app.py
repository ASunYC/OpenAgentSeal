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
import sys
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
from fastapi.responses import FileResponse, JSONResponse
from open_agent.version import get_version

logger = logging.getLogger(__name__)

# Global app instance
_app: Optional[FastAPI] = None
_mineru_mcp_app = None


def _get_mineru_mcp_app():
    global _mineru_mcp_app
    if _mineru_mcp_app is None:
        from open_agent.plugins.builtin.mineru_mcp import get_mineru_mcp_server

        _mineru_mcp_app = get_mineru_mcp_server().streamable_http_app()
    return _mineru_mcp_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("🌐 Open Agent Web UI started")

    # Initialize chat manager
    from open_agent.app.runner import init_chat_manager

    init_chat_manager()
    from open_agent.plugins.builtin.mineru_mcp import get_mineru_mcp_server

    _get_mineru_mcp_app()
    async with get_mineru_mcp_server().session_manager.run():
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
    from open_agent.app.mobile import router as mobile_router
    from open_agent.app.mobile import is_remote_api_request_allowed
    from open_agent.app.sandbox import router as sandbox_router

    @app.middleware("http")
    async def remote_api_guard(request: Request, call_next):
        if not is_remote_api_request_allowed(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "Mobile pairing is required for remote API access"},
            )
        return await call_next(request)

    app.include_router(chat_router)
    app.include_router(mobile_router)
    app.include_router(sandbox_router)
    app.mount("/api/plugins/mineru-mcp", _get_mineru_mcp_app())

    # Include application routes not owned by the chat router.
    _setup_app_routes(app)

    # Setup static file serving for Vue frontend
    _setup_static_files(app)

    _app = app
    return app


def _setup_app_routes(app: FastAPI):
    """Setup application routes."""

    @app.get("/api/health")
    async def health_check():
        """Health check endpoint"""
        return {"status": "ok", "ready": True}

    @app.get("/api/runtime/capabilities")
    async def get_runtime_capabilities():
        """Return UI/runtime capabilities for the current host platform."""
        if sys.platform.startswith("win"):
            platform = "windows"
        elif sys.platform.startswith("linux"):
            platform = "linux"
        elif sys.platform == "darwin":
            platform = "macos"
        else:
            platform = sys.platform or "unknown"

        is_windows = platform == "windows"
        is_linux = platform == "linux"
        return {
            "platform": platform,
            "shell": "web",
            "features": {
                "browserPanel": not is_linux,
                "sandboxPanel": is_windows,
                "openFileLocation": not is_linux,
                "tauriFilePicker": is_windows,
            },
        }

    @app.get("/api/main-agent")
    async def get_main_agent():
        """Get the isolated main-agent configuration."""
        try:
            from open_agent.agent_profiles import get_agent_profile_manager

            return get_agent_profile_manager().get_main_agent().to_dict()
        except Exception as e:
            logger.error(f"Failed to read main agent: {e}")
            return {"success": False, "error": str(e)}

    @app.patch("/api/main-agent")
    async def update_main_agent(data: dict):
        """Update the isolated main-agent configuration."""
        try:
            from open_agent.agent_profiles import AgentProfileConfig, MAIN_AGENT_ID, get_agent_profile_manager

            manager = get_agent_profile_manager()
            payload = manager.get_main_agent().to_dict()
            payload.update(data)
            payload["id"] = MAIN_AGENT_ID
            saved = manager.save_main_agent(AgentProfileConfig.from_dict(payload))
            return {"success": True, "data": saved.to_dict()}
        except Exception as e:
            logger.error(f"Failed to update main agent: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/agent-profiles")
    async def list_agent_profiles():
        """List isolated sub-agent profiles."""
        try:
            from open_agent.agent_profiles import get_agent_profile_manager

            return [profile.to_dict() for profile in get_agent_profile_manager().list_profiles()]
        except Exception as e:
            logger.error(f"Failed to list agent profiles: {e}")
            return []

    @app.post("/api/agent-profiles")
    async def create_agent_profile(data: dict):
        """Create an isolated sub-agent profile."""
        try:
            from open_agent.agent_profiles import get_agent_profile_manager

            payload = dict(data or {})
            clone_from = payload.pop("clone_from", "main")
            clone_all = bool(payload.pop("clone_all", False))
            profile = get_agent_profile_manager().create_profile(payload, clone_from=clone_from, clone_all=clone_all)
            return {"success": True, "data": profile.to_dict()}
        except Exception as e:
            logger.error(f"Failed to create agent profile: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/agent-profiles/{profile_id}")
    async def get_agent_profile(profile_id: str):
        """Get an isolated sub-agent profile."""
        from fastapi import HTTPException
        from open_agent.agent_profiles import get_agent_profile_manager

        profile = get_agent_profile_manager().get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Agent profile not found")
        return profile.to_dict()

    @app.patch("/api/agent-profiles/{profile_id}")
    async def update_agent_profile(profile_id: str, data: dict):
        """Update an isolated sub-agent profile."""
        from fastapi import HTTPException
        from open_agent.agent_profiles import AgentProfileConfig, get_agent_profile_manager

        manager = get_agent_profile_manager()
        current = manager.get_profile(profile_id)
        if not current:
            raise HTTPException(status_code=404, detail="Agent profile not found")
        payload = current.to_dict()
        payload.update(data)
        payload["id"] = current.id
        saved = manager.save_profile(AgentProfileConfig.from_dict(payload))
        return {"success": True, "data": saved.to_dict()}

    @app.delete("/api/agent-profiles/{profile_id}")
    async def delete_agent_profile(profile_id: str):
        """Delete an isolated sub-agent profile."""
        try:
            from open_agent.agent_profiles import get_agent_profile_manager

            return {"success": get_agent_profile_manager().delete_profile(profile_id)}
        except Exception as e:
            logger.error(f"Failed to delete agent profile: {e}")
            return {"success": False, "error": str(e)}

    @app.post("/api/agent-profiles/{profile_id}/clone")
    async def clone_agent_profile(profile_id: str, data: dict):
        """Clone an isolated sub-agent profile."""
        try:
            from open_agent.agent_profiles import get_agent_profile_manager

            payload = dict(data or {})
            clone_all = bool(payload.pop("clone_all", False))
            payload.setdefault("name", f"{profile_id} Copy")
            profile = get_agent_profile_manager().create_profile(payload, clone_from=profile_id, clone_all=clone_all)
            return {"success": True, "data": profile.to_dict()}
        except Exception as e:
            logger.error(f"Failed to clone agent profile: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/agent-profiles/{profile_id}/skills")
    async def list_agent_profile_skills(profile_id: str):
        """List skills stored in an isolated sub-agent profile."""
        from fastapi import HTTPException
        from open_agent.agent_profiles import get_agent_profile_manager
        from open_agent.tools.skill_loader import SkillLoader

        manager = get_agent_profile_manager()
        profile = manager.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Agent profile not found")
        skills_dir = manager.get_agent_home(profile_id) / "skills"
        loader = SkillLoader([{"path": str(skills_dir), "source": "profile", "source_label": profile.name}])
        skills = loader.discover_skills()
        return {
            "profile_id": profile.id,
            "skills_dir": str(skills_dir),
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "path": str(skill.skill_path) if skill.skill_path else "",
                    "content": skill.content,
                }
            for skill in skills
            ],
        }

    @app.post("/api/agent-profiles/{profile_id}/skills")
    async def save_agent_profile_skill(profile_id: str, data: dict):
        """Create or update a skill inside an isolated sub-agent profile."""
        import re
        from fastapi import HTTPException
        from open_agent.agent_profiles import get_agent_profile_manager

        manager = get_agent_profile_manager()
        profile = manager.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Agent profile not found")
        name = str(data.get("name") or "").strip()
        description = str(data.get("description") or "").strip()
        content = str(data.get("content") or "").strip()
        if not name or not description or not content:
            raise HTTPException(status_code=400, detail="name, description and content are required")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower() or "profile-skill"
        skill_dir = manager.get_agent_home(profile_id) / "skills" / safe_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n{content}\n",
            encoding="utf-8",
        )
        return {"success": True, "data": {"name": name, "path": str(skill_file)}}

    @app.delete("/api/agent-profiles/{profile_id}/skills/{skill_name}")
    async def delete_agent_profile_skill(profile_id: str, skill_name: str):
        """Delete a skill from an isolated sub-agent profile."""
        import shutil
        from fastapi import HTTPException
        from open_agent.agent_profiles import get_agent_profile_manager

        manager = get_agent_profile_manager()
        if not manager.get_profile(profile_id):
            raise HTTPException(status_code=404, detail="Agent profile not found")
        skills_dir = manager.get_agent_home(profile_id) / "skills"
        candidates = [
            item for item in skills_dir.iterdir()
            if item.is_dir() and (item.name == skill_name or (item / "SKILL.md").exists())
        ]
        target = None
        for item in candidates:
            skill_file = item / "SKILL.md"
            if item.name == skill_name:
                target = item
                break
            try:
                if f"name: {skill_name}" in skill_file.read_text(encoding="utf-8"):
                    target = item
                    break
            except Exception:
                pass
        if not target:
            raise HTTPException(status_code=404, detail="Skill not found")
        shutil.rmtree(target)
        return {"success": True}

    @app.get("/api/agent-profiles/{profile_id}/mcp")
    async def get_agent_profile_mcp(profile_id: str):
        """Read a sub-agent profile MCP config."""
        import json
        from fastapi import HTTPException
        from open_agent.agent_profiles import get_agent_profile_manager

        manager = get_agent_profile_manager()
        if not manager.get_profile(profile_id):
            raise HTTPException(status_code=404, detail="Agent profile not found")
        mcp_path = manager.get_agent_home(profile_id) / "mcp.json"
        if not mcp_path.exists():
            return {"profile_id": profile_id, "path": str(mcp_path), "config": {"mcpServers": {}}}
        try:
            config = json.loads(mcp_path.read_text(encoding="utf-8"))
        except Exception:
            config = {"mcpServers": {}}
        return {"profile_id": profile_id, "path": str(mcp_path), "config": config}

    @app.put("/api/agent-profiles/{profile_id}/mcp")
    async def save_agent_profile_mcp(profile_id: str, data: dict):
        """Save a sub-agent profile MCP config."""
        import json
        from fastapi import HTTPException
        from open_agent.agent_profiles import get_agent_profile_manager

        manager = get_agent_profile_manager()
        if not manager.get_profile(profile_id):
            raise HTTPException(status_code=404, detail="Agent profile not found")
        config = data.get("config", data)
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="config must be an object")
        config.setdefault("mcpServers", {})
        mcp_path = manager.get_agent_home(profile_id) / "mcp.json"
        mcp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"success": True, "data": {"path": str(mcp_path), "config": config}}

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
            from open_agent.user_config import (
                ModelProvider,
                get_user_config,
                resolve_model_context_window,
            )

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

                context_window, context_window_source = resolve_model_context_window(
                    m,
                    manager.get_settings().context_compaction_token_limit,
                )
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
                        "context_window": context_window,
                        "context_window_source": context_window_source,
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
            context_window_source = str(
                data.get(
                    "context_window_source",
                    existing_model.context_window_source if existing_model else "",
                )
                or ""
            )
            context_window = data.get(
                "context_window",
                existing_model.context_window if existing_model else None,
            )
            if context_window_source in {"catalog", "fallback"}:
                context_window = None
                context_window_source = ""

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
                    context_window=context_window,
                    context_window_source=context_window_source,
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
                model.context_window = context_window
                model.context_window_source = context_window_source
                manager.add_model(model)

            return {"success": True, "data": {"id": model.id}}
        except Exception as e:
            logger.error(f"Failed to save model config: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/models/context-window")
    async def get_model_context_window(model_name: str, provider: str = ""):
        """Resolve known model context metadata with a configurable fallback."""
        from open_agent.user_config import (
            ModelConfig,
            get_user_config,
            resolve_model_context_window,
        )

        manager = get_user_config()
        preview = ModelConfig(
            id="preview",
            name=model_name,
            display_name=model_name,
            provider=provider,
            api_key="",
        )
        context_window, source = resolve_model_context_window(
            preview,
            manager.get_settings().context_compaction_token_limit,
        )
        return {
            "model_name": model_name,
            "provider": provider,
            "context_window": context_window,
            "source": source,
        }

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
                "auto_context_compaction": settings.auto_context_compaction,
                "context_compaction_token_limit": settings.context_compaction_token_limit,
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

    @app.get("/api/web-search/config")
    async def get_web_search_config():
        """Get web search configuration and provider status."""
        try:
            from open_agent.user_config import get_user_config
            from open_agent.tools.web_search import get_browse_status, get_search_status

            manager = get_user_config()
            return {
                "success": True,
                "config": manager.get_web_search_config(include_secrets=False),
                "search_status": get_search_status(),
                "extract_status": get_browse_status(),
            }
        except Exception as e:
            logger.error(f"Failed to get web search config: {e}")
            return {"success": False, "error": str(e)}

    @app.post("/api/web-search/config")
    async def update_web_search_config(data: dict):
        """Update web search configuration."""
        try:
            from open_agent.user_config import get_user_config
            from open_agent.tools.web_search import get_browse_status, get_search_status

            manager = get_user_config()
            config = manager.update_web_search_config(data)
            return {
                "success": True,
                "config": config,
                "search_status": get_search_status(),
                "extract_status": get_browse_status(),
            }
        except Exception as e:
            logger.error(f"Failed to update web search config: {e}")
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
            from open_agent.plugins import get_plugin_manager

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

            plugin_manager = get_plugin_manager()

            # Load skills
            loader = SkillLoader(
                str(skills_dir),
                extra_roots=plugin_manager.effective_skill_roots(),
            )
            skills = loader.discover_skills()
            disabled_skill_paths = plugin_manager.disabled_skill_paths()

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
                        "original_name": skill.original_name or skill.name,
                        "description": skill.description,
                        "icon": icon,
                        "enabled": str(skill.skill_path) not in disabled_skill_paths if skill.skill_path else True,
                        "path": str(skill.skill_path) if skill.skill_path else "",
                        "source": skill.source,
                        "source_label": skill.source_label,
                        "plugin_id": skill.plugin_id,
                    }
                )

            logger.info(f"[SKILLS] Loaded {len(result)} skills")
            return result
        except Exception as e:
            logger.error(f"Failed to list skills: {e}")
            return []

    @app.post("/api/skills/config")
    async def set_skill_config(data: dict):
        """Persist a skill enable/disable override."""
        try:
            from open_agent.plugins import get_plugin_manager

            path = str(data.get("path", "")).strip()
            if not path:
                raise ValueError("path is required")
            enabled = bool(data.get("enabled", True))
            return get_plugin_manager().set_skill_enabled(path, enabled)
        except Exception as e:
            logger.error(f"Failed to update skill config: {e}")
            return {"success": False, "error": str(e)}

    def _get_writable_mcp_config_path() -> Path:
        """Return the MCP config path, creating a user-writable config when needed."""
        from open_agent.config import Config, get_user_app_dir
        from open_agent.utils.path_utils import get_external_config_dir, is_frozen

        def load_seed_config() -> dict:
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
                if seed_path.exists():
                    try:
                        return json.loads(seed_path.read_text(encoding="utf-8"))
                    except Exception:
                        logger.warning("Failed to read default MCP config: %s", seed_path, exc_info=True)
            return {"mcpServers": {}}

        def merge_missing_default_servers() -> None:
            try:
                user_config = json.loads(user_config_path.read_text(encoding="utf-8"))
            except Exception:
                user_config = {"mcpServers": {}}
            if not isinstance(user_config, dict):
                user_config = {"mcpServers": {}}
            user_servers = user_config.setdefault("mcpServers", {})
            if not isinstance(user_servers, dict):
                user_servers = {}
                user_config["mcpServers"] = user_servers

            seed_servers = load_seed_config().get("mcpServers", {})
            if not isinstance(seed_servers, dict):
                return
            changed = False
            for name, config in seed_servers.items():
                if name not in user_servers:
                    user_servers[name] = config
                    changed = True
            if changed:
                user_config_path.write_text(
                    json.dumps(user_config, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        user_config_dir = get_user_app_dir() / "config"
        user_config_dir.mkdir(parents=True, exist_ok=True)
        user_config_path = user_config_dir / "mcp.json"
        if user_config_path.exists():
            merge_missing_default_servers()
            return user_config_path

        seed_config = load_seed_config()
        if seed_config.get("mcpServers"):
            user_config_path.write_text(
                json.dumps(seed_config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return user_config_path

        user_config_path.write_text(json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
        return user_config_path

    @app.get("/api/mcp/config")
    async def get_mcp_config():
        """Get MCP server configuration."""
        try:
            from open_agent.plugins import get_plugin_manager

            config_path = _get_writable_mcp_config_path()
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            servers = raw.get("mcpServers", {})
            if not isinstance(servers, dict):
                servers = {}
            effective_servers, warnings = get_plugin_manager().effective_mcp_servers(
                servers,
                include_disabled_plugin_servers=True,
            )

            server_list = []
            for name, config in effective_servers.items():
                if not isinstance(config, dict):
                    continue
                server_config = dict(config)
                source = server_config.pop("_source", "user")
                plugin_id = server_config.pop("_plugin_id", None)
                server_config.update({
                    "name": name,
                    "original_name": name,
                    "type": config.get("type") or ("streamable_http" if config.get("url") else "stdio"),
                    "command": config.get("command", ""),
                    "url": config.get("url", ""),
                    "args": config.get("args", []),
                    "env": config.get("env", {}),
                    "cwd": config.get("cwd", ""),
                    "disabled": bool(config.get("disabled", False)),
                    "source": source,
                    "plugin_id": plugin_id,
                    "readonly": source == "plugin",
                })
                server_list.append(server_config)

            return {
                "success": True,
                "path": str(config_path),
                "servers": server_list,
                "warnings": warnings,
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
                if server.get("source") == "plugin" or server.get("readonly"):
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
                cwd = str(server.get("cwd", "")).strip()

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
                if cwd:
                    config["cwd"] = cwd
                else:
                    config.pop("cwd", None)

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

    @app.post("/api/mcp/plugin-server")
    async def set_plugin_mcp_server(data: dict):
        """Enable or disable a plugin-provided MCP server."""
        try:
            from open_agent.plugins import get_plugin_manager

            plugin_id = str(data.get("plugin_id", "")).strip()
            server_name = str(data.get("server_name", "")).strip()
            if not plugin_id or not server_name:
                raise ValueError("plugin_id and server_name are required")
            enabled = bool(data.get("enabled", True))
            return get_plugin_manager().set_plugin_mcp_enabled(plugin_id, server_name, enabled)
        except Exception as e:
            logger.error(f"Failed to update plugin MCP server: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/plugins")
    async def list_plugins():
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().list_plugins()
        except Exception as e:
            logger.error(f"Failed to list plugins: {e}")
            return {"success": False, "marketplaces": [], "marketplace_load_errors": [{"message": str(e)}]}

    @app.get("/api/plugins/marketplaces")
    async def list_plugin_marketplaces():
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().list_marketplaces()
        except Exception as e:
            logger.error(f"Failed to list plugin marketplaces: {e}")
            return {"success": False, "marketplaces": [], "errors": [{"message": str(e)}]}

    @app.post("/api/plugins/marketplaces")
    async def add_plugin_marketplace(data: dict):
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().add_marketplace(
                str(data.get("source", "")),
                data.get("ref"),
            )
        except Exception as e:
            logger.error(f"Failed to add plugin marketplace: {e}")
            return {"success": False, "error": str(e)}

    @app.delete("/api/plugins/marketplaces/{marketplace_name}")
    async def remove_plugin_marketplace(marketplace_name: str):
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().remove_marketplace(marketplace_name)
        except Exception as e:
            logger.error(f"Failed to remove plugin marketplace: {e}")
            return {"success": False, "error": str(e)}

    @app.post("/api/plugins/marketplaces/upgrade")
    async def upgrade_plugin_marketplaces(data: dict | None = None):
        try:
            from open_agent.plugins import get_plugin_manager

            data = data or {}
            return get_plugin_manager().upgrade_marketplaces(data.get("marketplace_name"))
        except Exception as e:
            logger.error(f"Failed to upgrade plugin marketplaces: {e}")
            return {"success": False, "error": str(e), "selected_marketplaces": [], "upgraded_roots": [], "errors": []}

    @app.post("/api/plugins/install")
    async def install_plugin(data: dict):
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().install_plugin(
                str(data.get("plugin_name", "")),
                str(data.get("marketplace_name", "")),
            )
        except Exception as e:
            logger.error(f"Failed to install plugin: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/plugins/{plugin_id}")
    async def read_plugin(plugin_id: str):
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().read_plugin(plugin_id)
        except Exception as e:
            logger.error(f"Failed to read plugin: {e}")
            return {"success": False, "error": str(e)}

    @app.delete("/api/plugins/{plugin_id}")
    async def uninstall_plugin(plugin_id: str):
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().uninstall_plugin(plugin_id)
        except Exception as e:
            logger.error(f"Failed to uninstall plugin: {e}")
            return {"success": False, "error": str(e)}

    @app.post("/api/plugins/{plugin_id}/enable")
    async def enable_plugin(plugin_id: str):
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().set_plugin_enabled(plugin_id, True)
        except Exception as e:
            logger.error(f"Failed to enable plugin: {e}")
            return {"success": False, "error": str(e)}

    @app.post("/api/plugins/{plugin_id}/disable")
    async def disable_plugin(plugin_id: str):
        try:
            from open_agent.plugins import get_plugin_manager

            return get_plugin_manager().set_plugin_enabled(plugin_id, False)
        except Exception as e:
            logger.error(f"Failed to disable plugin: {e}")
            return {"success": False, "error": str(e)}

    @app.put("/api/plugins/{plugin_id}/settings")
    async def save_plugin_settings(plugin_id: str, data: dict):
        try:
            from open_agent.plugins import get_plugin_manager

            values = data.get("values", data)
            return get_plugin_manager().save_plugin_settings(plugin_id, values)
        except Exception as e:
            logger.error(f"Failed to save plugin settings: {e}")
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
