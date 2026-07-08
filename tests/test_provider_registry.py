import pytest

from open_agent.schema import LLMProvider
from open_agent.user_config import ModelConfig


def test_volcano_route_uses_openai_protocol_and_preserves_coding_base_url():
    from open_agent.provider_registry import get_provider_registry

    config = ModelConfig(
        id="volcano",
        name="glm-5-2-260617",
        display_name="Volcano GLM",
        provider="volcano",
        api_key="test-key",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        provider_type="",
    )

    route = get_provider_registry().resolve_model_config(config)

    assert route.llm_provider == LLMProvider.OPENAI
    assert route.api_base == "https://ark.cn-beijing.volces.com/api/coding/v3"
    assert route.api_protocol == "openai"


def test_anthropic_route_uses_anthropic_protocol_and_default_base_url():
    from open_agent.provider_registry import get_provider_registry

    config = ModelConfig(
        id="anthropic",
        name="claude-3-5-sonnet-20241022",
        display_name="Claude",
        provider="anthropic",
        api_key="test-key",
        base_url="",
        provider_type="",
    )

    route = get_provider_registry().resolve_model_config(config)

    assert route.llm_provider == LLMProvider.ANTHROPIC
    assert route.api_base == "https://api.anthropic.com"
    assert route.api_protocol == "anthropic"


def test_provider_type_override_is_honored_for_custom_providers():
    from open_agent.provider_registry import get_provider_registry

    config = ModelConfig(
        id="custom",
        name="custom-claude",
        display_name="Custom Claude",
        provider="custom",
        api_key="test-key",
        base_url="https://gateway.example.com/anthropic/",
        provider_type="anthropic",
    )

    route = get_provider_registry().resolve_model_config(config)

    assert route.llm_provider == LLMProvider.ANTHROPIC
    assert route.api_base == "https://gateway.example.com/anthropic"


def test_registry_profiles_include_protocol_and_default_models():
    from open_agent.provider_registry import get_provider_registry

    providers = {profile.id: profile for profile in get_provider_registry().list_profiles()}

    assert providers["openai"].api_protocol == "openai"
    assert providers["anthropic"].api_protocol == "anthropic"
    assert providers["volcano"].api_protocol == "openai"
    assert "glm-5-2-260617" in providers["volcano"].default_models


def test_diagnose_model_config_reports_resolved_volcano_route():
    from open_agent.provider_registry import get_provider_registry

    config = ModelConfig(
        id="volcano",
        name="glm-5-2-260617",
        display_name="Volcano GLM",
        provider="ark",
        api_key="test-key",
        base_url="",
        provider_type="",
    )

    diagnostic = get_provider_registry().diagnose_model_config(config)

    assert diagnostic["status"] == "ok"
    assert diagnostic["route"]["provider"] == "volcano"
    assert diagnostic["route"]["api_protocol"] == "openai"
    assert diagnostic["route"]["api_base"] == "https://ark.cn-beijing.volces.com/api/coding/v3"
    assert diagnostic["checks"]["api_key"]["status"] == "ok"


def test_diagnose_model_config_warns_about_missing_key_and_unknown_model():
    from open_agent.provider_registry import get_provider_registry

    config = ModelConfig(
        id="volcano",
        name="glm-5.2",
        display_name="Volcano GLM Legacy",
        provider="volcano",
        api_key="",
        base_url="",
        provider_type="",
    )

    diagnostic = get_provider_registry().diagnose_model_config(config)

    assert diagnostic["status"] == "error"
    assert diagnostic["checks"]["api_key"]["status"] == "error"
    assert diagnostic["checks"]["model"]["status"] == "warning"
    assert "glm-5-2-260617" in diagnostic["checks"]["model"]["suggestions"]


def test_diagnose_model_config_uses_anthropic_protocol_check():
    from open_agent.provider_registry import get_provider_registry

    config = ModelConfig(
        id="anthropic",
        name="claude-3-5-sonnet-20241022",
        display_name="Claude",
        provider="anthropic",
        api_key="test-key",
        base_url="",
        provider_type="",
    )

    diagnostic = get_provider_registry().diagnose_model_config(config)

    assert diagnostic["status"] == "ok"
    assert diagnostic["checks"]["protocol"]["status"] == "ok"
    assert diagnostic["route"]["api_protocol"] == "anthropic"


@pytest.mark.asyncio
async def test_live_test_model_config_rejects_missing_api_key_without_network():
    from open_agent.provider_registry import get_provider_registry

    config = ModelConfig(
        id="volcano",
        name="glm-5-2-260617",
        display_name="Volcano GLM",
        provider="volcano",
        api_key="",
        base_url="",
        provider_type="",
    )

    result = await get_provider_registry().test_model_config(config)

    assert result["status"] == "error"
    assert result["checks"]["live_request"]["category"] == "api_key"
    assert "API key is not available" in result["checks"]["live_request"]["message"]
