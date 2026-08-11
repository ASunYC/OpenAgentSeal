"""Channel-neutral messaging gateway contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Awaitable, Mapping, Protocol, runtime_checkable


def _require_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("mapping keys must be strings")
            if key in frozen:
                raise TypeError("mapping keys must be unique strings")
            frozen[key] = _freeze(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    if type(value) in {type(None), bool, int, str, bytes}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise TypeError("floating-point values must be finite")
        return value
    raise TypeError(f"unsupported contract value: {type(value).__name__}")


def _freeze_attachments(value: Any) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("attachments must be a list or tuple")
    return tuple(_freeze(value))


def _freeze_metadata(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    return _freeze(value)


@dataclass(frozen=True, slots=True)
class ChannelCapabilities:
    """Features exposed by an adapter without leaking platform payloads."""

    supports_threads: bool = False
    supports_replies: bool = False
    supports_edits: bool = False
    supports_deletes: bool = False
    supports_reactions: bool = False
    supports_attachments: bool = False
    supports_text: bool = True
    supports_idempotency: bool = False
    supports_reconciliation: bool = False
    supports_polling: bool = False
    supports_webhook: bool = False
    supports_gateway_resume: bool = False
    acknowledgement_deadline_seconds: int = 10
    max_message_chars: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "supports_threads",
            "supports_replies",
            "supports_edits",
            "supports_deletes",
            "supports_reactions",
            "supports_attachments",
            "supports_text",
            "supports_idempotency",
            "supports_reconciliation",
            "supports_polling",
            "supports_webhook",
            "supports_gateway_resume",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean")
        if type(self.acknowledgement_deadline_seconds) is not int:
            raise TypeError("acknowledgement_deadline_seconds must be an integer")
        if not 1 <= self.acknowledgement_deadline_seconds <= 30:
            raise ValueError("acknowledgement_deadline_seconds must be between 1 and 30")
        if self.max_message_chars is not None:
            if type(self.max_message_chars) is not int:
                raise TypeError("max_message_chars must be an integer")
            if self.max_message_chars < 1:
                raise ValueError("max_message_chars must be positive")


@dataclass(frozen=True, slots=True)
class NormalizedInboundEvent:
    """Validated platform-independent input produced by a channel adapter."""

    event_key: str
    adapter_kind: str
    account_id: str
    conversation_id: str
    sender_id: str
    conversation_kind: str
    text: str = ""
    mentioned_bot: bool = False
    replies_to_bot: bool = False
    attachments: tuple[Any, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "event_key",
            "adapter_kind",
            "account_id",
            "conversation_id",
            "sender_id",
        ):
            _require_id(getattr(self, name), name)
        if self.conversation_kind not in {"dm", "group"}:
            raise ValueError("conversation_kind must be 'dm' or 'group'")
        for name in ("mentioned_bot", "replies_to_bot"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean")
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        object.__setattr__(self, "attachments", _freeze_attachments(self.attachments))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """Channel-neutral outbound message."""

    account_id: str
    conversation_id: str
    content: str
    reply_to_event_key: str | None = None
    attachments: tuple[Any, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.account_id, "account_id")
        _require_id(self.conversation_id, "conversation_id")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if self.reply_to_event_key is not None:
            _require_id(self.reply_to_event_key, "reply_to_event_key")
        object.__setattr__(self, "attachments", _freeze_attachments(self.attachments))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AuthenticatedGatewayFrame:
    """A provider frame minted only by its configured authenticated connector."""

    event: NormalizedInboundEvent
    gateway_session_id: str
    gateway_sequence: int
    connector_id: str
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.event, NormalizedInboundEvent):
            raise TypeError("event must be a NormalizedInboundEvent")
        _require_id(self.gateway_session_id, "gateway_session_id")
        _require_id(self.connector_id, "connector_id")
        if type(self.gateway_sequence) is not int or self.gateway_sequence < 0:
            raise ValueError("gateway_sequence must be a non-negative integer")


class GatewayConnectorCapability:
    """Unforgeable-in-process proof owned by one authenticated provider connector."""

    __slots__ = ("connector_id", "adapter_kind", "account_id", "__proof")

    def __init__(self, connector_id: str, adapter_kind: str, account_id: str) -> None:
        for value, name in (
            (connector_id, "connector_id"),
            (adapter_kind, "adapter_kind"),
            (account_id, "account_id"),
        ):
            _require_id(value, name)
        self.connector_id = connector_id
        self.adapter_kind = adapter_kind
        self.account_id = account_id
        self.__proof = object()

    def authenticate(
        self,
        event: NormalizedInboundEvent,
        *,
        gateway_session_id: str,
        gateway_sequence: int,
    ) -> AuthenticatedGatewayFrame:
        if event.adapter_kind != self.adapter_kind or event.account_id != self.account_id:
            raise ValueError("gateway event identity does not match connector capability")
        return AuthenticatedGatewayFrame(
            event,
            gateway_session_id,
            gateway_sequence,
            self.connector_id,
            self.__proof,
        )

    def verifies(self, frame: AuthenticatedGatewayFrame) -> bool:
        return (
            isinstance(frame, AuthenticatedGatewayFrame)
            and frame._proof is self.__proof
            and frame.connector_id == self.connector_id
            and frame.event.adapter_kind == self.adapter_kind
            and frame.event.account_id == self.account_id
        )


@runtime_checkable
class ChannelAdapter(Protocol):
    """Platform boundary. Payload parsing stays behind this protocol."""

    @property
    def kind(self) -> str: ...

    @property
    def capabilities(self) -> ChannelCapabilities: ...

    def normalize(self, raw_payload: bytes) -> NormalizedInboundEvent: ...

    def send(self, message: OutboundMessage) -> Awaitable[Mapping[str, Any]]: ...
