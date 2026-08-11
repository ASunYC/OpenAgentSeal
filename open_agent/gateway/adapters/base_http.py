"""Bounded HTTP transport and common official-adapter behavior."""

from __future__ import annotations

import json
import re
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import httpx

from open_agent.durable_runtime.delivery import (
    DeliveryOutcomeUnknown,
    PermanentDeliveryError,
    RetryableDeliveryError,
)
from open_agent.gateway.contracts import OutboundMessage


_SECRET = re.compile(
    r"(?i)(?:\b(?:authorization|token|secret|key)\b\s*[:=]\s*(?:bearer\s+)?|\bbearer\s+)[^\s,;\"'}]+"
)
_TOKEN_PATH = re.compile(r"(?i)(/bot)[^/?#\s]+")
_TOKEN_QUERY = re.compile(r"(?i)([?&](?:access_token|token|secret|key)=)[^&#\s]+")


def sanitize_error(value: object) -> str:
    """Return a bounded diagnostic that never includes credential-like values."""
    redacted = _TOKEN_PATH.sub(r"\1[redacted]", str(value))
    redacted = _TOKEN_QUERY.sub(r"\1[redacted]", redacted)
    return _SECRET.sub("[redacted]", redacted)[:500]


class _RedactingTransport(httpx.AsyncBaseTransport):
    """Send the real URL, then scrub the request before httpx logs it."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        request.url = httpx.URL(sanitize_error(str(request.url)))
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class AdapterAuthenticationError(PermanentDeliveryError):
    """The provider callback failed authentication."""


class AdapterRateLimited(RetryableDeliveryError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(0.0, min(float(retry_after), 86400.0))
        super().__init__(f"provider rate limited delivery; retry after {self.retry_after:g}s")


class AdapterRejected(PermanentDeliveryError):
    """The provider rejected a validly transmitted request."""


class AdapterUnavailable(RetryableDeliveryError):
    """The provider definitively did not accept the request."""


class AdapterOutcomeUnknown(DeliveryOutcomeUnknown):
    """The request may have reached a provider without safe retry semantics."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes

    def json(self) -> Mapping[str, Any]:
        try:
            value = json.loads(self.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdapterRejected("provider returned invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise AdapterRejected("provider returned a non-object response")
        return value


class HttpTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        allowed_hosts: frozenset[str],
    ) -> HttpResponse: ...


class BoundedHttpTransport:
    """One-shot HTTPS transport: no redirects, bounded bodies and official hosts."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        max_request_bytes: int = 256 * 1024,
        max_response_bytes: int = 1024 * 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between zero and 30")
        if not 1 <= max_request_bytes <= 1024 * 1024:
            raise ValueError("max_request_bytes is outside the supported range")
        if not 1 <= max_response_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_response_bytes is outside the supported range")
        self._timeout = timeout_seconds
        self._max_request = max_request_bytes
        self._max_response = max_response_bytes
        self._client = client

    async def request(self, method, url, *, headers=None, json_body=None, allowed_hosts):
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        normalized_hosts = frozenset(item.lower() for item in allowed_hosts)
        if parsed.scheme != "https" or host not in normalized_hosts:
            raise AdapterRejected("outbound provider URL is not on the official HTTPS allowlist")
        if parsed.username or parsed.password or parsed.fragment:
            raise AdapterRejected("outbound provider URL contains forbidden components")
        encoded = json.dumps(json_body or {}, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > self._max_request:
            raise AdapterRejected("outbound provider request exceeds the size limit")
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            transport=_RedactingTransport(
                httpx.AsyncHTTPTransport(
                    limits=httpx.Limits(
                        max_connections=20, max_keepalive_connections=10
                    )
                )
            ),
        )
        owns_client = self._client is None
        try:
            async with client.stream(method, url, headers=headers, content=encoded) as response:
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(chunks) + len(chunk) > self._max_response:
                        raise AdapterRejected("provider response exceeds the size limit")
                    chunks.extend(chunk)
                content = bytes(chunks)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            del exc
            raise AdapterOutcomeUnknown("provider response was not observed") from None
        finally:
            if owns_client:
                await client.aclose()
        if 300 <= response.status_code < 400:
            raise AdapterRejected("provider redirects are forbidden")
        return HttpResponse(response.status_code, dict(response.headers), content)


def required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f"{name} must be a non-empty bounded string")
    return value


def required_identifier(value: Any, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{name} must be a string or integer identifier")
    normalized = str(value).strip()
    if not normalized or len(normalized) > 512:
        raise ValueError(f"{name} must be a non-empty bounded identifier")
    return normalized


def parse_object(raw_payload: bytes) -> Mapping[str, Any]:
    if not isinstance(raw_payload, bytes) or not raw_payload or len(raw_payload) > 1024 * 1024:
        raise ValueError("payload must be non-empty bytes within the size limit")
    try:
        value = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("payload is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError("payload must be a JSON object")
    return value


def delivery_id(message: OutboundMessage) -> str:
    value = message.metadata.get("delivery_id")
    return required_string(value, "metadata.delivery_id") if value is not None else "untracked"


def compact_idempotency_key(value: str) -> str:
    return hashlib.sha256(required_string(value, "delivery_id").encode()).hexdigest()[:24]


def uuid_idempotency_key(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, required_string(value, "delivery_id")))


def classify_response(response: HttpResponse) -> Mapping[str, Any]:
    if response.status_code == 429:
        retry = response.headers.get("retry-after", "1")
        try:
            seconds = float(retry)
        except ValueError:
            seconds = 1.0
        raise AdapterRateLimited(seconds)
    if response.status_code in {408, 425} or 500 <= response.status_code <= 599:
        raise AdapterOutcomeUnknown(f"provider outcome is ambiguous ({response.status_code})")
    if not 200 <= response.status_code < 300:
        raise AdapterRejected(f"provider rejected delivery ({response.status_code})")
    return response.json()


def platform_message_id(payload: Mapping[str, Any]) -> str:
    for key in ("message_id", "id", "ts", "msgid", "messageId"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    data = payload.get("data")
    if isinstance(data, Mapping):
        return platform_message_id(data)
    return "accepted"


__all__ = [
    "AdapterAuthenticationError", "AdapterOutcomeUnknown", "AdapterRateLimited",
    "AdapterRejected", "AdapterUnavailable", "BoundedHttpTransport", "HttpResponse",
    "HttpTransport", "classify_response", "compact_idempotency_key", "delivery_id", "parse_object",
    "platform_message_id", "required_identifier", "required_string", "sanitize_error",
    "uuid_idempotency_key",
]
