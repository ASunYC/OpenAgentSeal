import json
from pathlib import Path

from open_agent.plugins.manager import PluginManager


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _create_marketplace(root: Path) -> Path:
    marketplace_root = root / "market"
    plugin_root = marketplace_root / "plugins" / "demo"
    skill_root = plugin_root / "skills" / "demo-skill"
    skill_root.mkdir(parents=True)
    (plugin_root / ".codex-plugin").mkdir(parents=True)

    _write_json(
        marketplace_root / ".agents" / "plugins" / "marketplace.json",
        {
            "name": "local-market",
            "interface": {"displayName": "Local Market"},
            "plugins": [{"name": "demo", "source": "./plugins/demo"}],
        },
    )
    _write_json(
        plugin_root / ".codex-plugin" / "plugin.json",
        {
            "name": "demo",
            "version": "1.0.0",
            "description": "Demo plugin",
            "skills": "./skills",
            "mcpServers": "./.mcp.json",
        },
    )
    _write_json(
        plugin_root / ".mcp.json",
        {"mcpServers": {"demo-mcp": {"command": "node", "args": ["server.js"]}}},
    )
    (skill_root / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill\n---\nUse this demo skill.",
        encoding="utf-8",
    )
    return marketplace_root


def _create_configurable_marketplace(root: Path) -> Path:
    marketplace_root = _create_marketplace(root)
    plugin_root = marketplace_root / "plugins" / "demo"
    settings_root = plugin_root / ".open-agent"
    settings_root.mkdir(parents=True)
    _write_json(
        settings_root / "settings.json",
        {
            "title": "Demo Settings",
            "fields": [
                {
                    "key": "api_url",
                    "type": "url",
                    "label": "API URL",
                    "default": "https://example.test",
                    "required": True,
                },
                {
                    "key": "api_token",
                    "type": "secret",
                    "label": "API Token",
                },
                {
                    "key": "translation_model_id",
                    "type": "model",
                    "label": "Translation model",
                    "required": True,
                },
            ],
        },
    )
    _write_json(
        plugin_root / ".mcp.json",
        {
            "mcpServers": {
                "demo-mcp": {
                    "type": "streamable_http",
                    "url": "{{open_agent_api_url}}/api/plugins/demo-mcp/",
                    "headers": {"Authorization": "Bearer {{setting.api_token}}"},
                }
            }
        },
    )
    return marketplace_root


def test_plugin_install_projects_skills_and_mcp(tmp_path):
    marketplace_root = _create_marketplace(tmp_path)
    manager = PluginManager(tmp_path / "data")

    added = manager.add_marketplace(str(marketplace_root))
    installed = manager.install_plugin("demo", "local-market")
    listed = manager.list_plugins()
    detail = manager.read_plugin("demo@local-market")
    mcp_servers, warnings = manager.effective_mcp_servers({})

    assert added["marketplace_name"] == "local-market"
    assert installed["plugin_id"] == "demo@local-market"
    assert listed["marketplaces"][0]["plugins"][0]["installed"] is True
    assert len(manager.effective_skill_roots()) == 1
    assert detail["plugin"]["skills"][0]["name"] == "demo-skill"
    assert "demo-mcp" in mcp_servers
    assert warnings == []


def test_disabled_plugin_mcp_is_hidden_from_runtime_but_visible_for_settings(tmp_path):
    marketplace_root = _create_marketplace(tmp_path)
    manager = PluginManager(tmp_path / "data")
    manager.add_marketplace(str(marketplace_root))
    manager.install_plugin("demo", "local-market")

    manager.set_plugin_mcp_enabled("demo@local-market", "demo-mcp", False)

    runtime_servers, _ = manager.effective_mcp_servers({})
    settings_servers, _ = manager.effective_mcp_servers({}, include_disabled_plugin_servers=True)

    assert "demo-mcp" not in runtime_servers
    assert settings_servers["demo-mcp"]["disabled"] is True


def test_plugin_disable_hides_all_runtime_capabilities(tmp_path):
    marketplace_root = _create_marketplace(tmp_path)
    manager = PluginManager(tmp_path / "data")
    manager.add_marketplace(str(marketplace_root))
    manager.install_plugin("demo", "local-market")

    manager.set_plugin_enabled("demo@local-market", False)

    mcp_servers, _ = manager.effective_mcp_servers({})
    assert manager.effective_skill_roots() == []
    assert mcp_servers == {}


def test_plugin_settings_are_persisted_masked_and_projected_to_mcp(tmp_path, monkeypatch):
    marketplace_root = _create_configurable_marketplace(tmp_path)
    manager = PluginManager(tmp_path / "data")
    manager.add_marketplace(str(marketplace_root))
    manager.install_plugin("demo", "local-market")
    monkeypatch.setenv("OPEN_AGENT_API_URL", "http://127.0.0.1:9998")

    saved = manager.save_plugin_settings(
        "demo@local-market",
        {
            "api_url": "https://mineru.example",
            "api_token": "secret-token",
            "translation_model_id": "model_123",
        },
    )
    detail = manager.read_plugin("demo@local-market")["plugin"]
    servers, warnings = manager.effective_mcp_servers({})

    assert saved["success"] is True
    assert detail["settings"]["values"]["api_token"] == "********"
    assert detail["settings"]["values"]["api_url"] == "https://mineru.example"
    assert servers["demo-mcp"]["url"] == "http://127.0.0.1:9998/api/plugins/demo-mcp/"
    assert servers["demo-mcp"]["headers"]["Authorization"] == "Bearer secret-token"
    assert warnings == []


def test_updating_masked_secret_preserves_existing_value(tmp_path):
    marketplace_root = _create_configurable_marketplace(tmp_path)
    manager = PluginManager(tmp_path / "data")
    manager.add_marketplace(str(marketplace_root))
    manager.install_plugin("demo", "local-market")
    manager.save_plugin_settings(
        "demo@local-market",
        {
            "api_url": "https://example.test",
            "api_token": "secret-token",
            "translation_model_id": "model_123",
        },
    )

    manager.save_plugin_settings(
        "demo@local-market",
        {
            "api_url": "https://changed.example",
            "api_token": "********",
            "translation_model_id": "model_456",
        },
    )

    config = manager.load_config()
    values = config["plugins"]["demo@local-market"]["settings"]
    assert values["api_token"] == "secret-token"
    assert values["api_url"] == "https://changed.example"
    assert values["translation_model_id"] == "model_456"


def test_bundled_marketplace_can_be_discovered_and_installed(tmp_path):
    bundled_marketplace = (
        Path(__file__).parents[1]
        / "open_agent"
        / "plugins"
        / "bundled"
        / ".agents"
        / "plugins"
        / "marketplace.json"
    )
    manager = PluginManager(tmp_path / "data", bundled_marketplace_path=bundled_marketplace)

    listed = manager.list_plugins()
    plugin = listed["marketplaces"][0]["plugins"][0]
    installed = manager.install_plugin(plugin["name"], plugin["marketplace_name"])
    detail = manager.read_plugin(installed["plugin_id"])["plugin"]

    assert plugin["id"] == "mineru@openagentseal"
    assert detail["settings"]["schema"]["title"] == "MinerU 文档解析与翻译"
    assert detail["mcp_servers"][0]["name"] == "mineru"
