"""Provider registry and model route resolution.

This module keeps provider metadata in one place so the UI, API layer, and
runtime create the same LLM client for a saved model configuration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from open_agent.retry import RetryConfig
from open_agent.schema import LLMProvider
from open_agent.user_config import ModelConfig, ModelProvider


OPENAI_PROTOCOL = "openai"
ANTHROPIC_PROTOCOL = "anthropic"


@dataclass(frozen=True)
class ProviderProfile:
    """Static metadata for a provider family."""

    id: str
    display_name: str
    api_protocol: str
    default_base_url: str = ""
    default_models: list[str] = field(default_factory=list)
    aliases: tuple[str, ...] = ()
    supports_custom_base_url: bool = True

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.id,
            "display_name": self.display_name,
            "default_base_url": self.default_base_url,
            "default_models": list(self.default_models),
            "api_protocol": self.api_protocol,
            "provider_type": self.api_protocol,
            "aliases": list(self.aliases),
            "supports_custom_base_url": self.supports_custom_base_url,
        }


@dataclass(frozen=True)
class ModelRoute:
    """Resolved runtime route for one saved model config."""

    id: str
    provider: str
    model: str
    display_name: str
    api_base: str
    api_protocol: str
    llm_provider: LLMProvider
    context_window: int | None = None


def _normalize_id(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_url(value: str | None) -> str:
    return str(value or "").strip().rstrip("/")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


EXTENDED_DEFAULT_MODELS: dict[str, list[str]] = {
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        "o1",
        "o1-mini",
        "o1-preview",
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    ],
    "deepseek": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
    "qwen": [
        "qwen3.6-plus",
        "qwen-plus",
        "qwen-max",
        "qwen-max-longcontext",
        "qwen-turbo",
        "qwen2.5-72b-instruct",
        "qwen2.5-32b-instruct",
    ],
    "zhipu": ["glm-4", "glm-4-plus", "glm-4-flash", "glm-3-turbo"],
    "volcano": [
        "glm-5-2-260617",
        "doubao-pro-32k",
        "doubao-pro-128k",
        "doubao-lite-32k",
    ],
    "minimax": ["MiniMax-M2.5", "MiniMax-Text-01", "MiniMax-VL-01"],
    "siliconflow": [
        "Qwen/Qwen2.5-72B-Instruct",
        "Qwen/Qwen2.5-32B-Instruct",
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-R1",
    ],
    "moonshot": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    "baichuan": ["Baichuan4", "Baichuan3-Turbo", "Baichuan2-Turbo"],
}


PROVIDER_PROTOCOLS: dict[str, str] = {
    "anthropic": ANTHROPIC_PROTOCOL,
}


PROVIDER_BASE_URLS: dict[str, str] = {
    "volcano": "https://ark.cn-beijing.volces.com/api/coding/v3",
}


PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "volcano": ("volcengine", "ark", "doubao"),
    "zhipu": ("glm", "bigmodel", "chatglm"),
    "qwen": ("dashscope", "aliyun"),
}


class ProviderRegistry:
    """Central provider metadata and model-route resolver."""

    def __init__(self, profiles: list[ProviderProfile] | None = None):
        self._profiles: dict[str, ProviderProfile] = {}
        if profiles is None:
            profiles = self._build_default_profiles()
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ProviderProfile) -> None:
        profile_id = _normalize_id(profile.id)
        self._profiles[profile_id] = profile
        for alias in profile.aliases:
            self._profiles[_normalize_id(alias)] = profile

    def list_profiles(self) -> list[ProviderProfile]:
        canonical: dict[str, ProviderProfile] = {}
        for profile in self._profiles.values():
            canonical[profile.id] = profile
        return list(canonical.values())

    def get_profile(self, provider: str) -> ProviderProfile | None:
        return self._profiles.get(_normalize_id(provider))

    def get_default_models(self, provider: str) -> list[str]:
        profile = self.get_profile(provider)
        return list(profile.default_models) if profile else []

    def resolve_model_config(self, config: ModelConfig) -> ModelRoute:
        provider_id = _normalize_id(config.provider)
        profile = self.get_profile(provider_id)
        api_protocol = self._resolve_protocol(config, profile)
        api_base = _normalize_url(config.base_url) or (
            profile.default_base_url if profile else ""
        )
        return ModelRoute(
            id=config.id,
            provider=profile.id if profile else provider_id,
            model=config.name,
            display_name=config.display_name,
            api_base=api_base,
            api_protocol=api_protocol,
            llm_provider=self.to_llm_provider(api_protocol),
            context_window=config.context_window,
        )

    def diagnose_model_config(self, config: ModelConfig) -> dict[str, Any]:
        """Return an offline diagnostic report for one model configuration."""
        route = self.resolve_model_config(config)
        profile = self.get_profile(config.provider)
        known_models = profile.default_models if profile else []

        checks = {
            "provider": self._diagnose_provider(config, profile),
            "protocol": self._diagnose_protocol(config, route, profile),
            "api_base": self._diagnose_api_base(config, route, profile),
            "api_key": self._diagnose_api_key(config),
            "model": self._diagnose_model(config, known_models),
        }
        status = self._aggregate_check_status(checks)

        return {
            "status": status,
            "id": config.id,
            "display_name": config.display_name,
            "route": {
                "provider": route.provider,
                "model": route.model,
                "api_base": route.api_base,
                "api_protocol": route.api_protocol,
                "llm_provider": route.llm_provider.value,
                "context_window": route.context_window,
            },
            "checks": checks,
        }

    async def test_model_config(
        self,
        config: ModelConfig,
        *,
        prompt: str = "Reply exactly: OK",
        timeout_secs: float = 30.0,
    ) -> dict[str, Any]:
        """Run a minimal live request against a model configuration."""
        diagnostic = self.diagnose_model_config(config)
        route = self.resolve_model_config(config)
        api_key = str(config.api_key or "").strip()

        if not api_key or api_key == "__configured__":
            return self._live_test_result(
                config,
                route,
                diagnostic,
                status="error",
                category="api_key",
                message=(
                    "API key is not available for a live test. "
                    "Save the model config or enter the key again before testing."
                ),
            )

        if not str(route.model or "").strip():
            return self._live_test_result(
                config,
                route,
                diagnostic,
                status="error",
                category="model",
                message="Model name is empty.",
            )

        started = perf_counter()
        try:
            from open_agent.llm.llm_wrapper import LLMClient
            from open_agent.schema import Message

            client = LLMClient(
                api_key=api_key,
                provider=route.llm_provider,
                api_base=route.api_base,
                model=route.model,
                retry_config=RetryConfig(enabled=False, max_retries=0),
            )
            response = await asyncio.wait_for(
                client.generate([Message(role="user", content=prompt)], tools=[]),
                timeout=timeout_secs,
            )
            latency_ms = int((perf_counter() - started) * 1000)
            return self._live_test_result(
                config,
                route,
                diagnostic,
                status="ok",
                category="live_request",
                message="Provider responded successfully.",
                latency_ms=latency_ms,
                response_preview=self._truncate(str(response.content or ""), 240),
                finish_reason=response.finish_reason,
            )
        except asyncio.TimeoutError:
            latency_ms = int((perf_counter() - started) * 1000)
            return self._live_test_result(
                config,
                route,
                diagnostic,
                status="error",
                category="timeout",
                message=f"Live test timed out after {timeout_secs:.0f}s.",
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            category = self._classify_live_test_error(exc)
            return self._live_test_result(
                config,
                route,
                diagnostic,
                status="error",
                category=category,
                message=self._sanitize_error_message(exc, api_key),
                latency_ms=latency_ms,
            )

    def to_llm_provider(self, api_protocol: str) -> LLMProvider:
        if _normalize_id(api_protocol) == ANTHROPIC_PROTOCOL:
            return LLMProvider.ANTHROPIC
        return LLMProvider.OPENAI

    def _resolve_protocol(
        self,
        config: ModelConfig,
        profile: ProviderProfile | None,
    ) -> str:
        provider_type = _normalize_id(config.provider_type)
        if provider_type in {OPENAI_PROTOCOL, ANTHROPIC_PROTOCOL}:
            return provider_type
        if profile:
            return profile.api_protocol
        if "anthropic" in _normalize_url(config.base_url).lower():
            return ANTHROPIC_PROTOCOL
        return OPENAI_PROTOCOL

    def _diagnose_provider(
        self,
        config: ModelConfig,
        profile: ProviderProfile | None,
    ) -> dict[str, Any]:
        if profile:
            return {
                "status": "ok",
                "message": f"Provider '{config.provider}' resolves to '{profile.id}'.",
                "canonical_provider": profile.id,
                "aliases": list(profile.aliases),
            }
        return {
            "status": "warning",
            "message": "Provider is custom or unknown; using explicit settings and OpenAI-compatible defaults.",
            "canonical_provider": _normalize_id(config.provider),
            "suggestions": [profile.id for profile in self.list_profiles()[:5]],
        }

    def _diagnose_protocol(
        self,
        config: ModelConfig,
        route: ModelRoute,
        profile: ProviderProfile | None,
    ) -> dict[str, Any]:
        configured = _normalize_id(config.provider_type)
        if configured and configured not in {OPENAI_PROTOCOL, ANTHROPIC_PROTOCOL}:
            return {
                "status": "warning",
                "message": f"Unsupported provider_type '{config.provider_type}' was ignored.",
                "resolved_protocol": route.api_protocol,
                "supported": [OPENAI_PROTOCOL, ANTHROPIC_PROTOCOL],
            }
        expected = profile.api_protocol if profile else route.api_protocol
        if configured and configured != expected:
            return {
                "status": "warning",
                "message": f"provider_type overrides the default protocol '{expected}'.",
                "resolved_protocol": route.api_protocol,
            }
        return {
            "status": "ok",
            "message": f"Using {route.api_protocol} protocol.",
            "resolved_protocol": route.api_protocol,
        }

    def _diagnose_api_base(
        self,
        config: ModelConfig,
        route: ModelRoute,
        profile: ProviderProfile | None,
    ) -> dict[str, Any]:
        explicit_base = _normalize_url(config.base_url)
        if route.api_base:
            status = "ok"
            source = "configured" if explicit_base else "provider_default"
            message = f"Using {source} API base."
            if profile and not explicit_base and not profile.default_base_url:
                status = "warning"
                message = "Provider has no default API base; runtime SDK default will be used."
            return {
                "status": status,
                "message": message,
                "api_base": route.api_base,
                "source": source,
            }
        return {
            "status": "warning",
            "message": "No API base configured; runtime client may rely on SDK defaults.",
            "api_base": "",
            "source": "sdk_default",
        }

    def _diagnose_api_key(self, config: ModelConfig) -> dict[str, Any]:
        api_key = str(config.api_key or "")
        if api_key.strip():
            return {
                "status": "ok",
                "message": "API key is configured.",
                "api_key_length": len(api_key),
            }
        return {
            "status": "error",
            "message": "API key is missing for this saved model configuration.",
            "api_key_length": 0,
        }

    def _diagnose_model(
        self,
        config: ModelConfig,
        known_models: list[str],
    ) -> dict[str, Any]:
        model = str(config.name or "").strip()
        if not model:
            return {
                "status": "error",
                "message": "Model name is empty.",
                "suggestions": known_models[:5],
            }
        if not known_models or model in known_models:
            return {
                "status": "ok",
                "message": "Model name is configured.",
                "known": bool(known_models),
                "suggestions": [],
            }
        return {
            "status": "warning",
            "message": "Model is not in the built-in provider catalog; verify the exact model id.",
            "known": True,
            "suggestions": known_models[:5],
        }

    @staticmethod
    def _aggregate_check_status(checks: dict[str, dict[str, Any]]) -> str:
        statuses = {check.get("status") for check in checks.values()}
        if "error" in statuses:
            return "error"
        if "warning" in statuses:
            return "warning"
        return "ok"

    def _live_test_result(
        self,
        config: ModelConfig,
        route: ModelRoute,
        diagnostic: dict[str, Any],
        *,
        status: str,
        category: str,
        message: str,
        latency_ms: int | None = None,
        response_preview: str = "",
        finish_reason: str = "",
    ) -> dict[str, Any]:
        return {
            "status": status,
            "id": config.id,
            "display_name": config.display_name,
            "route": diagnostic["route"],
            "diagnostic_status": diagnostic["status"],
            "latency_ms": latency_ms,
            "response_preview": response_preview,
            "finish_reason": finish_reason,
            "checks": {
                **diagnostic["checks"],
                "live_request": {
                    "status": status,
                    "category": category,
                    "message": message,
                    "provider": route.provider,
                    "model": route.model,
                    "api_base": route.api_base,
                },
            },
        }

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        text = value.strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _sanitize_error_message(self, exc: Exception, api_key: str) -> str:
        message = self._truncate(str(exc) or exc.__class__.__name__, 1200)
        if api_key:
            message = message.replace(api_key, "[redacted]")
        return message

    @staticmethod
    def _classify_live_test_error(exc: Exception) -> str:
        text = f"{exc.__class__.__name__}: {exc}".lower()
        if any(token in text for token in ("401", "403", "unauthorized", "forbidden", "api key", "apikey", "authentication")):
            return "api_key"
        if any(token in text for token in ("404", "not found", "unsupportedmodel", "model")):
            return "model"
        if any(token in text for token in ("timeout", "timed out")):
            return "timeout"
        if any(token in text for token in ("dns", "connect", "connection", "tls", "ssl", "network")):
            return "network"
        if any(token in text for token in ("base_url", "base url", "invalid url", "api base")):
            return "api_base"
        return "provider"

    def _build_default_profiles(self) -> list[ProviderProfile]:
        profiles: list[ProviderProfile] = []
        for provider in ModelProvider:
            provider_id = provider.value
            defaults = _dedupe(
                EXTENDED_DEFAULT_MODELS.get(provider_id, [])
                + ModelProvider.get_default_models(provider)
            )
            profiles.append(
                ProviderProfile(
                    id=provider_id,
                    display_name=ModelProvider.get_display_name(provider),
                    api_protocol=PROVIDER_PROTOCOLS.get(provider_id, OPENAI_PROTOCOL),
                    default_base_url=PROVIDER_BASE_URLS.get(
                        provider_id,
                        ModelProvider.get_default_base_url(provider),
                    ),
                    default_models=defaults,
                    aliases=PROVIDER_ALIASES.get(provider_id, ()),
                )
            )
        return profiles


_REGISTRY = ProviderRegistry()


def get_provider_registry() -> ProviderRegistry:
    return _REGISTRY
