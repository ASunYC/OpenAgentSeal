"""Codex-compatible local plugin manager.

Plugins are local bundles that can contribute skills and MCP servers. The
manager intentionally keeps plugin-derived MCP config separate from the user's
own mcp.json and exposes an effective view for the agent runtime.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from open_agent.utils.path_utils import get_data_dir

logger = logging.getLogger(__name__)

MARKETPLACE_RELATIVE_PATHS = (
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
)
PLUGIN_MANIFEST_RELATIVE_PATHS = (
    ".codex-plugin/plugin.json",
    "plugin.json",
)


def _safe_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    segment = segment.strip(".-")
    return segment or "item"


def _plugin_id(plugin_name: str, marketplace_name: str) -> str:
    return f"{plugin_name}@{marketplace_name}"


def _split_plugin_id(plugin_id: str) -> tuple[str, str]:
    if "@" not in plugin_id:
        raise ValueError("plugin_id must be in the form plugin@marketplace")
    plugin_name, marketplace_name = plugin_id.rsplit("@", 1)
    if not plugin_name or not marketplace_name:
        raise ValueError("plugin_id must be in the form plugin@marketplace")
    return plugin_name, marketplace_name


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_plugin_manifest_path(plugin_root: Path) -> Path | None:
    for relative in PLUGIN_MANIFEST_RELATIVE_PATHS:
        path = plugin_root / relative
        if path.exists():
            return path
    return None


def find_marketplace_manifest_path(path: Path) -> Path | None:
    if path.is_file() and path.name == "marketplace.json":
        return path
    for relative in MARKETPLACE_RELATIVE_PATHS:
        candidate = path / relative
        if candidate.exists():
            return candidate
    return None


def marketplace_root_from_manifest(marketplace_path: Path) -> Path:
    parent = marketplace_path.parent
    parts = marketplace_path.as_posix()
    for relative in MARKETPLACE_RELATIVE_PATHS:
        suffix = "/" + relative
        if parts.endswith(suffix):
            return marketplace_path.parent.parent.parent
    return parent


def _resolve_relative_path(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value.startswith("./"):
        return (root / value[2:]).resolve()
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (root / value).resolve()


@dataclass
class MarketplaceSource:
    kind: str
    source: str
    installed_root: str | None = None


@dataclass
class PluginManifest:
    name: str
    version: str | None
    description: str | None = None
    keywords: list[str] = field(default_factory=list)
    skills_path: str | None = None
    mcp_servers_path: str | None = None
    apps_path: str | None = None
    hooks_path: str | None = None
    hooks_paths: list[str] = field(default_factory=list)
    hooks_inline: Any = None
    interface: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketplacePlugin:
    name: str
    source: dict[str, Any]
    policy: dict[str, Any] = field(default_factory=dict)
    interface: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)


@dataclass
class Marketplace:
    name: str
    path: str
    interface: dict[str, Any] = field(default_factory=dict)
    plugins: list[MarketplacePlugin] = field(default_factory=list)


class PluginManager:
    """Manage local plugins, marketplaces, and runtime capability projection."""

    def __init__(self, data_root: Path | None = None):
        self.root = data_root or (get_data_dir() / "plugins")
        self.cache_root = self.root / "cache"
        self.marketplaces_root = self.root / "marketplaces"
        self.git_sources_root = self.root / "git-sources"
        self.config_path = self.root / "config.json"

    def _default_config(self) -> dict[str, Any]:
        return {"marketplaces": {}, "plugins": {}}

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return self._default_config()
        try:
            config = _read_json(self.config_path)
            if not isinstance(config, dict):
                return self._default_config()
            config.setdefault("marketplaces", {})
            config.setdefault("plugins", {})
            return config
        except Exception as exc:
            logger.warning("Failed to read plugin config %s: %s", self.config_path, exc)
            return self._default_config()

    def save_config(self, config: dict[str, Any]) -> None:
        config.setdefault("marketplaces", {})
        config.setdefault("plugins", {})
        _write_json(self.config_path, config)

    def _marketplace_entry(self, name: str) -> dict[str, Any] | None:
        return self.load_config().get("marketplaces", {}).get(name)

    def _marketplace_path_from_entry(self, entry: dict[str, Any]) -> Path | None:
        path_value = entry.get("path") or entry.get("installed_root") or entry.get("source")
        if not path_value:
            return None
        return find_marketplace_manifest_path(Path(str(path_value)).expanduser())

    def _clone_or_update(self, url: str, destination: Path, ref_name: str | None = None) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            subprocess.run(["git", "-C", str(destination), "fetch", "--all", "--tags"], check=True)
        else:
            subprocess.run(["git", "clone", url, str(destination)], check=True)
        if ref_name:
            subprocess.run(["git", "-C", str(destination), "checkout", ref_name], check=True)
        return destination

    def add_marketplace(self, source: str, ref_name: str | None = None) -> dict[str, Any]:
        source = source.strip()
        if not source:
            raise ValueError("marketplace source is required")

        source_path = Path(source).expanduser()
        kind = "local"
        installed_root: Path | None = None
        if source_path.exists():
            marketplace_path = find_marketplace_manifest_path(source_path)
            if marketplace_path is None:
                raise ValueError("marketplace.json was not found in the selected path")
        else:
            kind = "git"
            if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", source):
                url = f"https://github.com/{source}.git"
                market_dir_name = _safe_segment(source.replace("/", "-"))
            else:
                url = source
                market_dir_name = _safe_segment(Path(source).stem or source)
            installed_root = self.marketplaces_root / market_dir_name
            self._clone_or_update(url, installed_root, ref_name)
            marketplace_path = find_marketplace_manifest_path(installed_root)
            if marketplace_path is None:
                raise ValueError("marketplace.json was not found after cloning")
            source = url

        marketplace = self.load_marketplace(marketplace_path)
        config = self.load_config()
        already_added = marketplace.name in config["marketplaces"]
        config["marketplaces"][marketplace.name] = {
            "name": marketplace.name,
            "kind": kind,
            "source": source,
            "path": str(marketplace_path),
            "installed_root": str(installed_root) if installed_root else None,
            "ref": ref_name,
        }
        self.save_config(config)
        return {
            "success": True,
            "marketplace_name": marketplace.name,
            "path": str(marketplace_path),
            "installed_root": str(installed_root) if installed_root else None,
            "already_added": already_added,
        }

    def remove_marketplace(self, marketplace_name: str) -> dict[str, Any]:
        config = self.load_config()
        entry = config.get("marketplaces", {}).pop(marketplace_name, None)
        self.save_config(config)
        return {
            "success": True,
            "marketplace_name": marketplace_name,
            "installed_root": entry.get("installed_root") if isinstance(entry, dict) else None,
        }

    def upgrade_marketplaces(self, marketplace_name: str | None = None) -> dict[str, Any]:
        config = self.load_config()
        selected = []
        upgraded = []
        errors = []
        for name, entry in list(config.get("marketplaces", {}).items()):
            if marketplace_name and name != marketplace_name:
                continue
            selected.append(name)
            if entry.get("kind") != "git" or not entry.get("installed_root"):
                continue
            try:
                self._clone_or_update(entry["source"], Path(entry["installed_root"]), entry.get("ref"))
                path = find_marketplace_manifest_path(Path(entry["installed_root"]))
                if path:
                    entry["path"] = str(path)
                    upgraded.append(str(path))
            except Exception as exc:
                errors.append({"marketplace_name": name, "message": str(exc)})
        self.save_config(config)
        return {"success": not errors, "selected_marketplaces": selected, "upgraded_roots": upgraded, "errors": errors}

    def load_plugin_manifest(self, plugin_root: Path) -> PluginManifest | None:
        manifest_path = find_plugin_manifest_path(plugin_root)
        if manifest_path is None:
            return None
        raw = _read_json(manifest_path)
        if not isinstance(raw, dict):
            return None

        name = str(raw.get("name") or plugin_root.name)
        interface = raw.get("interface") if isinstance(raw.get("interface"), dict) else {}

        def resolve_manifest_field(field: str, default: str | None = None) -> str | None:
            raw_value = raw.get(field, default)
            if raw_value is None:
                return None
            resolved = _resolve_relative_path(plugin_root, raw_value)
            if resolved and resolved.exists():
                return str(resolved)
            return None

        hooks_value = raw.get("hooks", "./hooks/hooks.json")
        hooks_path = None
        hooks_paths: list[str] = []
        hooks_inline = None
        if isinstance(hooks_value, str):
            resolved_hooks = _resolve_relative_path(plugin_root, hooks_value)
            hooks_path = str(resolved_hooks) if resolved_hooks and resolved_hooks.exists() else None
        elif isinstance(hooks_value, list):
            if all(isinstance(item, str) for item in hooks_value):
                for item in hooks_value:
                    resolved_hooks = _resolve_relative_path(plugin_root, item)
                    if resolved_hooks and resolved_hooks.exists():
                        hooks_paths.append(str(resolved_hooks))
            else:
                hooks_inline = hooks_value
        elif isinstance(hooks_value, dict):
            hooks_inline = hooks_value

        return PluginManifest(
            name=name,
            version=str(raw.get("version")) if raw.get("version") else None,
            description=raw.get("description") if isinstance(raw.get("description"), str) else None,
            keywords=raw.get("keywords") if isinstance(raw.get("keywords"), list) else [],
            skills_path=resolve_manifest_field("skills", "./skills"),
            mcp_servers_path=resolve_manifest_field("mcpServers", "./.mcp.json"),
            apps_path=resolve_manifest_field("apps", "./.app.json"),
            hooks_path=hooks_path,
            hooks_paths=hooks_paths,
            hooks_inline=hooks_inline,
            interface=interface,
        )

    def load_marketplace(self, marketplace_path: Path) -> Marketplace:
        marketplace_path = marketplace_path.resolve()
        raw = _read_json(marketplace_path)
        root = marketplace_root_from_manifest(marketplace_path)
        plugins = []
        for item in raw.get("plugins", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            source = self._resolve_marketplace_plugin_source(root, item.get("source"))
            if source is None:
                continue
            interface = {}
            keywords: list[str] = []
            if source.get("type") == "local":
                manifest = self.load_plugin_manifest(Path(source["path"]))
                if manifest:
                    interface = manifest.interface
                    keywords = manifest.keywords
            plugins.append(
                MarketplacePlugin(
                    name=str(item["name"]),
                    source=source,
                    policy=item.get("policy") if isinstance(item.get("policy"), dict) else {},
                    interface=interface,
                    keywords=keywords,
                )
            )
        return Marketplace(
            name=str(raw["name"]),
            path=str(marketplace_path),
            interface=raw.get("interface") if isinstance(raw.get("interface"), dict) else {},
            plugins=plugins,
        )

    def _resolve_marketplace_plugin_source(self, marketplace_root: Path, raw_source: Any) -> dict[str, Any] | None:
        if isinstance(raw_source, str):
            path = _resolve_relative_path(marketplace_root, raw_source)
            return {"type": "local", "path": str(path)} if path else None
        if not isinstance(raw_source, dict):
            return None

        source_type = str(raw_source.get("source") or raw_source.get("type") or "").lower()
        if source_type == "local":
            path = _resolve_relative_path(marketplace_root, raw_source.get("path"))
            return {"type": "local", "path": str(path)} if path else None
        if source_type in {"url", "git", "git-subdir"} or raw_source.get("url"):
            return {
                "type": "git",
                "url": str(raw_source.get("url")),
                "path": raw_source.get("path"),
                "ref": raw_source.get("ref") or raw_source.get("ref_name"),
                "sha": raw_source.get("sha"),
            }
        return None

    def _plugin_cache_base(self, plugin_name: str, marketplace_name: str) -> Path:
        return self.cache_root / _safe_segment(marketplace_name) / _safe_segment(plugin_name)

    def installed_plugin_root(self, plugin_name: str, marketplace_name: str) -> Path | None:
        base = self._plugin_cache_base(plugin_name, marketplace_name)
        if not base.exists():
            return None
        config = self.load_config()
        plugin_config = config.get("plugins", {}).get(_plugin_id(plugin_name, marketplace_name), {})
        version = plugin_config.get("installed_version")
        if version and (base / _safe_segment(str(version))).exists():
            return base / _safe_segment(str(version))
        versions = [path for path in base.iterdir() if path.is_dir()]
        if not versions:
            return None
        return sorted(versions, key=lambda item: item.name.lower())[-1]

    def _materialize_source(self, plugin_name: str, marketplace_name: str, source: dict[str, Any]) -> Path:
        if source.get("type") == "local":
            path = Path(str(source["path"]))
            if not path.exists():
                raise FileNotFoundError(f"plugin source does not exist: {path}")
            return path

        if source.get("type") == "git":
            url = str(source.get("url") or "")
            if not url:
                raise ValueError("git plugin source requires url")
            source_key = _safe_segment(f"{marketplace_name}-{plugin_name}-{Path(url).stem}")
            root = self.git_sources_root / source_key
            self._clone_or_update(url, root, source.get("ref") or source.get("sha"))
            subdir = source.get("path")
            return (root / str(subdir)).resolve() if subdir else root

        raise ValueError("unsupported plugin source")

    def install_plugin(self, plugin_name: str, marketplace_name: str) -> dict[str, Any]:
        marketplace_entry = self._marketplace_entry(marketplace_name)
        if not marketplace_entry:
            raise ValueError(f"marketplace not found: {marketplace_name}")
        marketplace_path = self._marketplace_path_from_entry(marketplace_entry)
        if not marketplace_path:
            raise ValueError(f"marketplace manifest not found: {marketplace_name}")

        marketplace = self.load_marketplace(marketplace_path)
        plugin = next((item for item in marketplace.plugins if item.name == plugin_name), None)
        if not plugin:
            raise ValueError(f"plugin not found: {plugin_name}")

        source_root = self._materialize_source(plugin_name, marketplace_name, plugin.source)
        manifest = self.load_plugin_manifest(source_root)
        version = manifest.version if manifest and manifest.version else "local"
        safe_version = _safe_segment(version)
        destination = self._plugin_cache_base(plugin_name, marketplace_name) / safe_version
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_root, destination)

        config = self.load_config()
        pid = _plugin_id(plugin_name, marketplace_name)
        existing = config["plugins"].get(pid, {})
        config["plugins"][pid] = {
            **existing,
            "enabled": bool(existing.get("enabled", True)),
            "installed_version": version,
            "installed_path": str(destination),
            "disabled_skills": existing.get("disabled_skills", []),
            "disabled_mcp_servers": existing.get("disabled_mcp_servers", []),
        }
        self.save_config(config)
        return {"success": True, "plugin_id": pid, "installed_version": version, "installed_path": str(destination)}

    def uninstall_plugin(self, plugin_id: str) -> dict[str, Any]:
        plugin_name, marketplace_name = _split_plugin_id(plugin_id)
        base = self._plugin_cache_base(plugin_name, marketplace_name)
        if base.exists() and self.root in base.resolve().parents:
            shutil.rmtree(base)
        config = self.load_config()
        config.get("plugins", {}).pop(plugin_id, None)
        self.save_config(config)
        return {"success": True}

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        _split_plugin_id(plugin_id)
        config = self.load_config()
        plugin_config = config.setdefault("plugins", {}).setdefault(plugin_id, {})
        plugin_config["enabled"] = enabled
        self.save_config(config)
        return {"success": True, "plugin_id": plugin_id, "enabled": enabled}

    def set_skill_enabled(self, skill_path: str, enabled: bool) -> dict[str, Any]:
        config = self.load_config()
        disabled = set(config.setdefault("skills", {}).setdefault("disabled_paths", []))
        if enabled:
            disabled.discard(skill_path)
        else:
            disabled.add(skill_path)
        config["skills"]["disabled_paths"] = sorted(disabled)
        self.save_config(config)
        return {"success": True, "path": skill_path, "enabled": enabled}

    def set_plugin_mcp_enabled(self, plugin_id: str, server_name: str, enabled: bool) -> dict[str, Any]:
        _split_plugin_id(plugin_id)
        config = self.load_config()
        plugin_config = config.setdefault("plugins", {}).setdefault(plugin_id, {})
        disabled = set(plugin_config.setdefault("disabled_mcp_servers", []))
        if enabled:
            disabled.discard(server_name)
        else:
            disabled.add(server_name)
        plugin_config["disabled_mcp_servers"] = sorted(disabled)
        self.save_config(config)
        return {"success": True, "plugin_id": plugin_id, "server_name": server_name, "enabled": enabled}

    def list_marketplaces(self) -> dict[str, Any]:
        config = self.load_config()
        marketplaces = []
        errors = []
        for name, entry in config.get("marketplaces", {}).items():
            path = self._marketplace_path_from_entry(entry)
            if not path:
                errors.append({"marketplace_name": name, "message": "marketplace manifest not found"})
                continue
            try:
                marketplace = self.load_marketplace(path)
                marketplaces.append({
                    "name": marketplace.name,
                    "path": marketplace.path,
                    "interface": marketplace.interface,
                    "plugin_count": len(marketplace.plugins),
                    "kind": entry.get("kind", "local"),
                })
            except Exception as exc:
                errors.append({"marketplace_name": name, "message": str(exc)})
        return {"success": not errors, "marketplaces": marketplaces, "errors": errors}

    def list_plugins(self) -> dict[str, Any]:
        config = self.load_config()
        marketplaces_payload = []
        errors = []
        for name, entry in config.get("marketplaces", {}).items():
            path = self._marketplace_path_from_entry(entry)
            if not path:
                errors.append({"marketplace_name": name, "message": "marketplace manifest not found"})
                continue
            try:
                marketplace = self.load_marketplace(path)
                plugins = []
                for plugin in marketplace.plugins:
                    pid = _plugin_id(plugin.name, marketplace.name)
                    plugin_config = config.get("plugins", {}).get(pid, {})
                    installed_root = self.installed_plugin_root(plugin.name, marketplace.name)
                    manifest = self.load_plugin_manifest(installed_root) if installed_root else None
                    interface = (manifest.interface if manifest else plugin.interface) or {}
                    plugins.append({
                        "id": pid,
                        "name": plugin.name,
                        "marketplace_name": marketplace.name,
                        "installed": installed_root is not None,
                        "enabled": bool(plugin_config.get("enabled", True)),
                        "local_version": plugin_config.get("installed_version") or (manifest.version if manifest else None),
                        "source": plugin.source,
                        "install_policy": plugin.policy.get("installation", "AVAILABLE"),
                        "auth_policy": plugin.policy.get("authentication", "ON_INSTALL"),
                        "interface": interface,
                        "keywords": plugin.keywords,
                    })
                marketplaces_payload.append({
                    "name": marketplace.name,
                    "path": marketplace.path,
                    "interface": marketplace.interface,
                    "plugins": plugins,
                })
            except Exception as exc:
                errors.append({"marketplace_name": name, "message": str(exc)})
        return {"success": not errors, "marketplaces": marketplaces_payload, "marketplace_load_errors": errors}

    def read_plugin(self, plugin_id: str) -> dict[str, Any]:
        plugin_name, marketplace_name = _split_plugin_id(plugin_id)
        config = self.load_config()
        root = self.installed_plugin_root(plugin_name, marketplace_name)
        manifest = self.load_plugin_manifest(root) if root else None
        plugin_config = config.get("plugins", {}).get(plugin_id, {})
        disabled_skills = set(config.get("skills", {}).get("disabled_paths", []))
        skills = []
        if manifest and manifest.skills_path:
            from open_agent.tools.skill_loader import SkillLoader

            loader = SkillLoader(manifest.skills_path)
            for skill in loader.discover_skills():
                skill_path = str(skill.skill_path) if skill.skill_path else ""
                skills.append({
                    "name": skill.name,
                    "description": skill.description,
                    "path": skill_path,
                    "enabled": skill_path not in disabled_skills,
                    "source": "plugin",
                    "plugin_id": plugin_id,
                })

        mcp_servers = self._read_plugin_mcp_servers(root, manifest) if root and manifest else {}
        disabled_mcp = set(plugin_config.get("disabled_mcp_servers", []))
        return {
            "success": True,
            "plugin": {
                "marketplace_name": marketplace_name,
                "marketplace_path": (self._marketplace_entry(marketplace_name) or {}).get("path"),
                "summary": {
                    "id": plugin_id,
                    "name": plugin_name,
                    "installed": root is not None,
                    "enabled": bool(plugin_config.get("enabled", True)),
                    "local_version": plugin_config.get("installed_version") or (manifest.version if manifest else None),
                    "interface": manifest.interface if manifest else {},
                },
                "description": manifest.description if manifest else None,
                "skills": skills,
                "mcp_servers": [
                    {"name": name, "enabled": name not in disabled_mcp, "config": value}
                    for name, value in mcp_servers.items()
                ],
                "apps": self._read_json_file(manifest.apps_path) if manifest and manifest.apps_path else [],
                "hooks": self._read_manifest_hooks(manifest) if manifest else [],
            },
        }

    def _read_json_file(self, path: str | None) -> Any:
        if not path:
            return None

    def _read_manifest_hooks(self, manifest: PluginManifest) -> Any:
        if manifest.hooks_inline is not None:
            return manifest.hooks_inline
        if manifest.hooks_paths:
            return [self._read_json_file(path) for path in manifest.hooks_paths]
        if manifest.hooks_path:
            return self._read_json_file(manifest.hooks_path)
        return []
        try:
            return _read_json(Path(path))
        except Exception:
            return None

    def _read_plugin_mcp_servers(self, root: Path, manifest: PluginManifest) -> dict[str, Any]:
        if not manifest.mcp_servers_path:
            return {}
        try:
            raw = _read_json(Path(manifest.mcp_servers_path))
        except Exception as exc:
            logger.warning("Failed to read plugin MCP config %s: %s", manifest.mcp_servers_path, exc)
            return {}
        servers = raw.get("mcpServers", raw) if isinstance(raw, dict) else {}
        return servers if isinstance(servers, dict) else {}

    def effective_skill_roots(self) -> list[dict[str, str]]:
        config = self.load_config()
        roots: list[dict[str, str]] = []
        for pid, plugin_config in config.get("plugins", {}).items():
            if not plugin_config.get("enabled", True):
                continue
            try:
                plugin_name, marketplace_name = _split_plugin_id(pid)
            except ValueError:
                continue
            root = self.installed_plugin_root(plugin_name, marketplace_name)
            manifest = self.load_plugin_manifest(root) if root else None
            if manifest and manifest.skills_path:
                roots.append({
                    "path": manifest.skills_path,
                    "plugin_id": pid,
                    "plugin_name": plugin_name,
                    "source": "plugin",
                })
        return roots

    def disabled_skill_paths(self) -> set[str]:
        config = self.load_config()
        return set(config.get("skills", {}).get("disabled_paths", []))

    def effective_mcp_servers(
        self,
        user_servers: dict[str, Any] | None = None,
        include_disabled_plugin_servers: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        effective = dict(user_servers or {})
        warnings = []
        config = self.load_config()
        for pid, plugin_config in config.get("plugins", {}).items():
            if not plugin_config.get("enabled", True):
                continue
            try:
                plugin_name, marketplace_name = _split_plugin_id(pid)
            except ValueError:
                continue
            root = self.installed_plugin_root(plugin_name, marketplace_name)
            manifest = self.load_plugin_manifest(root) if root else None
            if not root or not manifest:
                continue
            disabled = set(plugin_config.get("disabled_mcp_servers", []))
            for server_name, server_config in self._read_plugin_mcp_servers(root, manifest).items():
                server_disabled = server_name in disabled
                if server_disabled and not include_disabled_plugin_servers:
                    continue
                if server_name in effective:
                    warnings.append({
                        "plugin_id": pid,
                        "server_name": server_name,
                        "message": "MCP server name conflicts with an existing server and was skipped.",
                    })
                    continue
                if isinstance(server_config, dict):
                    config_copy = dict(server_config)
                    config_copy["_source"] = "plugin"
                    config_copy["_plugin_id"] = pid
                    if server_disabled:
                        config_copy["disabled"] = True
                    effective[server_name] = config_copy
        return effective, warnings


_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager
