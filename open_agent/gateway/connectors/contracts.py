"""Immutable contracts shared by official long-lived channel connectors."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


class ConnectorError(RuntimeError):
    """Sanitized operational connector failure."""


class ConnectorProtocolError(ConnectorError):
    """The provider sent a malformed or unsupported frame."""


class ConnectorAuthenticationError(ConnectorError):
    """Official session authentication failed."""


@dataclass(frozen=True, slots=True)
class ConnectorLimits:
    max_frame_bytes: int = 1024 * 1024
    max_decompressed_bytes: int = 2 * 1024 * 1024
    max_queue_depth: int = 100
    lease_seconds: int = 120
    heartbeat_timeout_seconds: int = 90

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value < 1 or value > 64 * 1024 * 1024:
                raise ValueError(f"{name} must be a positive bounded integer")


@dataclass(frozen=True, slots=True)
class ConnectorSnapshot:
    account_id: str
    adapter_kind: str
    state: str = "idle"
    authenticated: bool = False
    session_resumable: bool = False
    last_sequence: int | None = None
    reconnect_count: int = 0
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "adapter_kind": self.adapter_kind,
            "state": self.state,
            "authenticated": self.authenticated,
            "session_resumable": self.session_resumable,
            "last_sequence": self.last_sequence,
            "reconnect_count": self.reconnect_count,
            "last_error": self.last_error,
        }


class ConnectorCredential(Mapping[str, Any]):
    """Read-only secret values whose repr is safe for diagnostics."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"ConnectorCredential(fields={tuple(sorted(self._values))!r}, values=<redacted>)"


_SCHEMAS: Mapping[str, Mapping[str, type]] = {
    "discord": {"bot_token": str, "application_id": str, "intents": int},
    "qq": {"access_token": str, "app_id": str, "intents": int},
    "dingtalk": {
        "client_id": str, "client_secret": str, "access_token": str, "robot_code": str,
    },
    "wecom": {"bot_id": str, "secret": str},
}


def parse_connector_credential(kind: str, raw: str) -> ConnectorCredential:
    schema = _SCHEMAS.get(kind)
    if schema is None:
        raise ValueError("unsupported connector kind")
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > 65536:
        raise ValueError("connector credential must be bounded JSON")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("connector credential must be valid JSON") from None
    if not isinstance(value, dict) or set(value) != set(schema):
        raise ValueError("connector credential fields do not match the official schema")
    normalized: dict[str, Any] = {}
    for name, expected in schema.items():
        item = value[name]
        if expected is str:
            if not isinstance(item, str) or not item.strip() or len(item) > 4096:
                raise ValueError(f"{name} must be a bounded non-empty string")
        elif type(item) is not int or item < 0 or item > (1 << 53) - 1:
            raise ValueError(f"{name} must be a bounded non-negative integer")
        normalized[name] = item
    return ConnectorCredential(normalized)


__all__ = [
    "ConnectorAuthenticationError", "ConnectorCredential", "ConnectorError",
    "ConnectorLimits", "ConnectorProtocolError", "ConnectorSnapshot",
    "parse_connector_credential",
]
