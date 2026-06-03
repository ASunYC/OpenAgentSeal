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
