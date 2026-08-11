"""Bounded official HTTPS/WebSocket transport for connector drivers."""

from __future__ import annotations

import json
import re
import zlib
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import websockets

from .contracts import ConnectorLimits, ConnectorProtocolError


def _official_url(url: str, allowed_hosts: frozenset[str], scheme: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ConnectorProtocolError("provider endpoint is invalid") from None
    host = parsed.hostname or ""
    def matches(allowed: str) -> bool:
        if host == allowed:
            return True
        if allowed.count("*") != 1:
            return False
        prefix, suffix = allowed.split("*", 1)
        if not host.startswith(prefix) or not host.endswith(suffix):
            return False
        end = len(host) - len(suffix) if suffix else len(host)
        wildcard = host[len(prefix):end]
        return bool(re.fullmatch(r"[a-z0-9-]+", wildcard))

    host_allowed = any(matches(allowed) for allowed in allowed_hosts)
    if (
        parsed.scheme != scheme or parsed.username or parsed.password
        or not host_allowed or port not in (None, 443)
    ):
        raise ConnectorProtocolError("provider endpoint is outside the official allowlist")


class DefaultConnectorNetwork:
    async def connect(
        self, url: str, *, allowed_hosts: frozenset[str], max_frame_bytes: int
    ):
        _official_url(url, allowed_hosts, "wss")
        return await websockets.connect(
            url, max_size=max_frame_bytes, compression=None, ping_interval=None,
            close_timeout=5, open_timeout=10,
        )


def decode_gateway_frame(raw: object, limits: ConnectorLimits) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        value = dict(raw)
    else:
        if isinstance(raw, str):
            encoded = raw.encode("utf-8")
            if len(encoded) > limits.max_frame_bytes:
                raise ConnectorProtocolError("gateway frame exceeds the byte limit")
            decoded = encoded
        elif isinstance(raw, bytes):
            if len(raw) > limits.max_frame_bytes:
                raise ConnectorProtocolError("gateway frame exceeds the byte limit")
            try:
                decompressor = zlib.decompressobj()
                decoded = decompressor.decompress(raw, limits.max_decompressed_bytes + 1)
                if len(decoded) > limits.max_decompressed_bytes or decompressor.unconsumed_tail:
                    raise ConnectorProtocolError("gateway decompressed frame exceeds the limit")
                decoded += decompressor.flush(limits.max_decompressed_bytes + 1 - len(decoded))
            except zlib.error:
                decoded = raw
            if len(decoded) > limits.max_decompressed_bytes:
                raise ConnectorProtocolError("gateway decompressed frame exceeds the limit")
        else:
            raise ConnectorProtocolError("gateway frame must be text or binary")
        try:
            value = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ConnectorProtocolError("gateway frame is not valid JSON") from None
    if not isinstance(value, dict):
        raise ConnectorProtocolError("gateway frame must be a JSON object")
    if len(value) > 64:
        raise ConnectorProtocolError("gateway frame has too many fields")
    return value


__all__ = ["DefaultConnectorNetwork", "decode_gateway_frame"]
