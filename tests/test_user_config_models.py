import json

import pytest

from open_agent.cli import load_shared_model_config
from open_agent.user_config import ModelConfig, UserConfigManager


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    UserConfigManager._instances.clear()
    config_file = tmp_path / "open_agent.json"
    monkeypatch.setattr(UserConfigManager, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(UserConfigManager, "CONFIG_FILE", config_file)
    yield config_file
    UserConfigManager._instances.clear()


def model_config(model_id: str, name: str) -> ModelConfig:
    return ModelConfig(
        id=model_id,
        name=name,
        display_name=name,
        provider="test",
        api_key="secret",
        base_url="https://example.test/v1",
        provider_type="openai",
        is_default=False,
    )


def test_legacy_default_model_name_is_migrated_to_canonical_id(isolated_config):
    first = model_config("model_first", "first-model")
    selected = model_config("model_selected", "selected-model")
    isolated_config.write_text(
        json.dumps(
            {
                **UserConfigManager.DEFAULT_CONFIG,
                "models": [first.to_dict(), selected.to_dict()],
                "default_model_id": selected.name,
            }
        ),
        encoding="utf-8",
    )

    manager = UserConfigManager()

    assert manager.get_default_model().id == selected.id
    persisted = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert persisted["default_model_id"] == selected.id
    assert [model["is_default"] for model in persisted["models"]] == [False, True]


def test_set_default_model_canonicalizes_names_and_rejects_unknown_models(
    isolated_config,
):
    manager = UserConfigManager()
    first = model_config("model_first", "first-model")
    second = model_config("model_second", "second-model")
    manager.add_model(first)
    manager.add_model(second)

    manager.set_default_model(second.name)

    assert manager.get_default_model().id == second.id
    persisted = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert persisted["default_model_id"] == second.id
    with pytest.raises(ValueError, match="Model configuration not found"):
        manager.set_default_model("missing-model")


def test_cli_reloads_the_desktop_shared_model_config(isolated_config):
    manager = UserConfigManager()
    first = model_config("model_first", "first-model")
    second = model_config("model_second", "second-model")
    manager.add_model(first)
    manager.add_model(second)
    manager.set_default_model(first.id)

    desktop_config = json.loads(isolated_config.read_text(encoding="utf-8"))
    desktop_config["default_model_id"] = second.id
    for model in desktop_config["models"]:
        model["is_default"] = model["id"] == second.id
    isolated_config.write_text(json.dumps(desktop_config), encoding="utf-8")

    selected = load_shared_model_config()

    assert selected.id == second.id
    assert selected.name == second.name
