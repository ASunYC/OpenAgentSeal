"""Isolated main-agent and sub-agent profile configuration."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from open_agent.utils.path_utils import (
    get_agent_profile_dir,
    get_agent_profiles_root,
    get_data_dir,
    get_main_agent_dir,
)


MAIN_AGENT_ID = "main"
PROFILE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_AGENT_HOME_OVERRIDE: ContextVar[Path | None] = ContextVar("agent_home_override", default=None)


@dataclass
class AgentProfileConfig:
    id: str
    name: str
    model_id: str = ""
    description: str = ""
    avatar: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    max_steps: int = 100
    tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    permission_mode: str = "default"
    allow_delegation: bool = False
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def create(cls, name: str, model_id: str = "", **kwargs: Any) -> "AgentProfileConfig":
        now = datetime.now().isoformat()
        profile_id = kwargs.get("id") or f"profile_{uuid.uuid4().hex[:8]}"
        return cls(
            id=normalize_profile_id(profile_id),
            name=name,
            model_id=model_id,
            description=kwargs.get("description", ""),
            avatar=kwargs.get("avatar", ""),
            system_prompt=kwargs.get("system_prompt", ""),
            temperature=float(kwargs.get("temperature", 0.7)),
            max_tokens=int(kwargs.get("max_tokens", 4096)),
            max_steps=int(kwargs.get("max_steps", 100)),
            tools=list(kwargs.get("tools") or []),
            mcp_servers=list(kwargs.get("mcp_servers") or []),
            permission_mode=kwargs.get("permission_mode", "default") or "default",
            allow_delegation=bool(kwargs.get("allow_delegation", False)),
            enabled=bool(kwargs.get("enabled", True)),
            created_at=kwargs.get("created_at") or now,
            updated_at=kwargs.get("updated_at") or now,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentProfileConfig":
        payload = dict(data or {})
        now = datetime.now().isoformat()
        raw_id = str(payload.get("id") or f"profile_{uuid.uuid4().hex[:8]}")
        payload["id"] = MAIN_AGENT_ID if raw_id == MAIN_AGENT_ID else normalize_profile_id(raw_id)
        payload.setdefault("name", payload["id"])
        payload.setdefault("model_id", "")
        payload.setdefault("description", "")
        payload.setdefault("avatar", "")
        payload.setdefault("system_prompt", "")
        payload.setdefault("temperature", 0.7)
        payload.setdefault("max_tokens", 4096)
        payload.setdefault("max_steps", 100)
        payload.setdefault("tools", [])
        payload.setdefault("mcp_servers", [])
        payload.setdefault("permission_mode", "default")
        payload.setdefault("allow_delegation", False)
        payload.setdefault("enabled", True)
        payload.setdefault("created_at", now)
        payload.setdefault("updated_at", now)
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in payload.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_profile_id(value: str) -> str:
    text = str(value or "").strip().replace(" ", "_")
    text = re.sub(r"[^a-zA-Z0-9_-]", "_", text)
    if not text:
        text = f"profile_{uuid.uuid4().hex[:8]}"
    if text == MAIN_AGENT_ID:
        text = f"profile_{uuid.uuid4().hex[:8]}"
    if not PROFILE_ID_RE.match(text):
        text = f"profile_{uuid.uuid4().hex[:8]}"
    return text[:64]


def get_agent_home() -> Path:
    override = _AGENT_HOME_OVERRIDE.get()
    if override is not None:
        return override
    return get_main_agent_dir()


def set_agent_home_override(path: str | Path | None) -> Token:
    return _AGENT_HOME_OVERRIDE.set(Path(path) if path else None)


def reset_agent_home_override(token: Token) -> None:
    _AGENT_HOME_OVERRIDE.reset(token)


class AgentProfileManager:
    """Manages the main agent and isolated sub-agent profiles."""

    MIGRATION_MARKER = ".profiles_migrated"

    def __init__(self) -> None:
        self.data_dir = get_data_dir()
        self.main_dir = get_main_agent_dir()
        self.profiles_root = get_agent_profiles_root()
        self.ensure_layout()
        self.migrate_legacy_agents()

    def ensure_layout(self) -> None:
        self._ensure_agent_dirs(self.main_dir)
        self.profiles_root.mkdir(parents=True, exist_ok=True)
        if not self._config_path(self.main_dir).exists():
            self.save_main_agent(
                AgentProfileConfig(
                    id=MAIN_AGENT_ID,
                    name="默认助手",
                    avatar="",
                    allow_delegation=True,
                    enabled=True,
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat(),
                )
            )

    def _ensure_agent_dirs(self, home: Path) -> None:
        for name in ("memory", "sessions", "logs", "workspace", "artifacts", "skills"):
            (home / name).mkdir(parents=True, exist_ok=True)

    def _config_path(self, home: Path) -> Path:
        return home / "config.json"

    def _read_config(self, home: Path) -> AgentProfileConfig | None:
        path = self._config_path(home)
        if not path.exists():
            return None
        try:
            return AgentProfileConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def _write_config(self, home: Path, config: AgentProfileConfig) -> AgentProfileConfig:
        self._ensure_agent_dirs(home)
        config.updated_at = datetime.now().isoformat()
        self._config_path(home).write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return config

    def get_main_agent(self) -> AgentProfileConfig:
        config = self._read_config(self.main_dir)
        if config is None:
            config = AgentProfileConfig(id=MAIN_AGENT_ID, name="默认助手", allow_delegation=True, enabled=True)
            self.save_main_agent(config)
        config.id = MAIN_AGENT_ID
        config.allow_delegation = True
        config.enabled = True
        return config

    def save_main_agent(self, config: AgentProfileConfig) -> AgentProfileConfig:
        config.id = MAIN_AGENT_ID
        config.allow_delegation = True
        config.enabled = True
        if not config.created_at:
            config.created_at = datetime.now().isoformat()
        return self._write_config(self.main_dir, config)

    def list_profiles(self, include_disabled: bool = True) -> list[AgentProfileConfig]:
        profiles: list[AgentProfileConfig] = []
        for config_path in sorted(self.profiles_root.glob("*/config.json")):
            config = self._read_config(config_path.parent)
            if config and (include_disabled or config.enabled):
                profiles.append(config)
        return profiles

    def get_profile(self, profile_id: str) -> AgentProfileConfig | None:
        path = get_agent_profile_dir(normalize_profile_id(profile_id))
        return self._read_config(path)

    def save_profile(self, config: AgentProfileConfig) -> AgentProfileConfig:
        config.id = normalize_profile_id(config.id)
        if not config.created_at:
            config.created_at = datetime.now().isoformat()
        return self._write_config(get_agent_profile_dir(config.id), config)

    def create_profile(self, data: dict[str, Any], clone_from: str | None = None, clone_all: bool = False) -> AgentProfileConfig:
        base: AgentProfileConfig | None = None
        if clone_from == MAIN_AGENT_ID:
            base = self.get_main_agent()
        elif clone_from:
            base = self.get_profile(clone_from)

        if base:
            payload = base.to_dict()
            payload.update(data)
        else:
            payload = dict(data)
        payload["id"] = normalize_profile_id(payload.get("id") or f"profile_{uuid.uuid4().hex[:8]}")
        payload.setdefault("name", payload["id"])
        payload["created_at"] = datetime.now().isoformat()
        payload["updated_at"] = payload["created_at"]
        config = AgentProfileConfig.from_dict(payload)
        home = get_agent_profile_dir(config.id)
        if clone_all and base:
            source_home = self.main_dir if base.id == MAIN_AGENT_ID else get_agent_profile_dir(base.id)
            if home.exists():
                shutil.rmtree(home)
            shutil.copytree(
                source_home,
                home,
                ignore=shutil.ignore_patterns(
                    "runtime.db-wal",
                    "runtime.db-shm",
                    "control_plane.db-wal",
                    "control_plane.db-shm",
                ),
            )
        return self._write_config(home, config)

    def delete_profile(self, profile_id: str) -> bool:
        profile_id = normalize_profile_id(profile_id)
        home = get_agent_profile_dir(profile_id)
        if not home.exists():
            return False
        shutil.rmtree(home)
        return True

    def get_agent_config(self, profile_id: str | None = None) -> AgentProfileConfig | None:
        if not profile_id or profile_id == MAIN_AGENT_ID:
            return self.get_main_agent()
        return self.get_profile(profile_id)

    def get_agent_home(self, profile_id: str | None = None) -> Path:
        if not profile_id or profile_id == MAIN_AGENT_ID:
            return self.main_dir
        return get_agent_profile_dir(profile_id)

    def migrate_legacy_agents(self) -> None:
        marker = self.data_dir / self.MIGRATION_MARKER
        if marker.exists():
            return
        try:
            from open_agent.user_config import get_user_config

            config_manager = get_user_config()
            agents = config_manager.get_all_agents()
        except Exception:
            agents = []

        if not agents:
            marker.write_text(datetime.now().isoformat(), encoding="utf-8")
            return

        default_agent = None
        try:
            from open_agent.user_config import get_user_config

            default_agent = get_user_config().get_default_agent()
        except Exception:
            default_agent = agents[0]

        for agent in agents:
            data = agent.to_dict()
            if default_agent and agent.id == default_agent.id:
                self.save_main_agent(AgentProfileConfig.from_dict({**data, "id": MAIN_AGENT_ID}))
            else:
                profile_id = normalize_profile_id(agent.id)
                if not self.get_profile(profile_id):
                    self.save_profile(AgentProfileConfig.from_dict({**data, "id": profile_id}))

        marker.write_text(datetime.now().isoformat(), encoding="utf-8")


_profile_manager: AgentProfileManager | None = None


def get_agent_profile_manager() -> AgentProfileManager:
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = AgentProfileManager()
    return _profile_manager
