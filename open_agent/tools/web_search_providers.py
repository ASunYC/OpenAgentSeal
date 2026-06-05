"""Hermes-style web search provider registry for OpenAgentSeal.

This module keeps the current free Bing/HTTP implementation as the last
fallback, while making API-backed providers the primary path when configured.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable, Optional

import requests

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT = 30
SEARCH_BACKEND_ORDER = (
    "firecrawl",
    "tavily",
    "exa",
    "brave",
    "serper",
    "jina",
    "searxng",
    "ddgs",
    "duckduckgo_html",
    "legacy_bing",
)
EXTRACT_BACKEND_ORDER = (
    "jina",
    "firecrawl",
    "built_in",
)


@dataclass
class ProviderInfo:
    name: str
    display_name: str
    supports_search: bool
    supports_extract: bool
    available: bool
    requires_key: bool
    note: str = ""


def _request_kwargs(timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"timeout": timeout}
    proxies = {}
    if os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"):
        proxies["http"] = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        proxies["https"] = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxies:
        kwargs["proxies"] = proxies
    if os.environ.get("WEB_SEARCH_VERIFY_SSL", "true").lower() == "false":
        kwargs["verify"] = False
    return kwargs


def _load_config(include_secrets: bool = True) -> dict[str, Any]:
    try:
        from open_agent.user_config import get_user_config

        return get_user_config().get_web_search_config(include_secrets=include_secrets)
    except Exception:
        logger.debug("Failed to load web search config", exc_info=True)
        return {
            "enabled": True,
            "search_backend": "auto",
            "extract_backend": "auto",
            "searxng_url": "",
            "api_keys": {},
        }


def _configured_key(provider: str, env_names: Iterable[str]) -> str:
    config = _load_config(include_secrets=True)
    api_keys = config.get("api_keys") if isinstance(config, dict) else {}
    if isinstance(api_keys, dict):
        value = str(api_keys.get(provider) or "").strip()
        if value and value != "***":
            return value
    for name in env_names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


def _configured_searxng_url() -> str:
    config = _load_config(include_secrets=True)
    value = str(config.get("searxng_url") or "").strip()
    if value:
        return value.rstrip("/")
    return (os.environ.get("SEARXNG_URL") or "").strip().rstrip("/")


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_result(title: Any, link: Any, snippet: Any = "") -> dict[str, str] | None:
    clean_title = _clean_text(title)
    clean_link = html.unescape(str(link or "")).strip()
    clean_snippet = _clean_text(snippet)
    if not clean_title or not clean_link:
        return None
    if clean_link.startswith(("javascript:", "#", "mailto:")):
        return None
    return {"title": clean_title, "link": clean_link, "snippet": clean_snippet}


def _decode_base64_urlsafe(value: str) -> str:
    import base64

    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii", errors="ignore")).decode("utf-8", errors="ignore")


def _unwrap_bing_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("bing.com"):
        query = urllib.parse.parse_qs(parsed.query)
        encoded = (query.get("u") or [""])[0]
        if encoded.startswith("a1"):
            decoded = _decode_base64_urlsafe(encoded[2:])
            if decoded.startswith(("http://", "https://")):
                return decoded
    return url


def _unwrap_duckduckgo_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") or not parsed.netloc:
        query = urllib.parse.parse_qs(parsed.query)
        target = (query.get("uddg") or [""])[0]
        if target:
            return urllib.parse.unquote(target)
    return urllib.parse.urljoin("https://duckduckgo.com", url)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = _clean_text(data)
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        self.parts.append(text)

    def text(self) -> str:
        content = " ".join(self.parts)
        content = re.sub(r"[ \t\r\f\v]+", " ", content)
        content = re.sub(r"\n\s*", "\n", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()


class WebProvider:
    name = "provider"
    display_name = "Provider"
    requires_key = True

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return False

    def is_available(self) -> bool:
        return False

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        raise NotImplementedError

    def extract(self, url: str) -> str:
        raise NotImplementedError

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            display_name=self.display_name,
            supports_search=self.supports_search(),
            supports_extract=self.supports_extract(),
            available=self.is_available(),
            requires_key=self.requires_key,
        )


class TavilyProvider(WebProvider):
    name = "tavily"
    display_name = "Tavily"

    def _key(self) -> str:
        return _configured_key("tavily", ("TAVILY_API_KEY",))

    def supports_search(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(self._key())

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        payload = {"api_key": self._key(), "query": query, "max_results": limit}
        response = requests.post("https://api.tavily.com/search", json=payload, **_request_kwargs())
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("results", []):
            normalized = _normalize_result(item.get("title"), item.get("url"), item.get("content"))
            if normalized:
                results.append(normalized)
        return results


class ExaProvider(WebProvider):
    name = "exa"
    display_name = "Exa"

    def _key(self) -> str:
        return _configured_key("exa", ("EXA_API_KEY",))

    def supports_search(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(self._key())

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        headers = {"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json"}
        payload = {"query": query, "numResults": limit}
        response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, **_request_kwargs())
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("results", []):
            normalized = _normalize_result(item.get("title"), item.get("url"), item.get("text") or item.get("snippet"))
            if normalized:
                results.append(normalized)
        return results


class BraveProvider(WebProvider):
    name = "brave"
    display_name = "Brave Search"

    def _key(self) -> str:
        return _configured_key("brave", ("BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"))

    def supports_search(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(self._key())

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        headers = {"Accept": "application/json", "X-Subscription-Token": self._key()}
        params = {"q": query, "count": min(max(limit, 1), 20)}
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params=params,
            **_request_kwargs(),
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("web", {}).get("results", []):
            normalized = _normalize_result(item.get("title"), item.get("url"), item.get("description"))
            if normalized:
                results.append(normalized)
        return results


class SerperProvider(WebProvider):
    name = "serper"
    display_name = "Google via Serper"

    def _key(self) -> str:
        return _configured_key("serper", ("SERPER_API_KEY",))

    def supports_search(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(self._key())

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        headers = {"X-API-KEY": self._key(), "Content-Type": "application/json"}
        response = requests.post(
            "https://google.serper.dev/search",
            headers=headers,
            json={"q": query, "num": limit},
            **_request_kwargs(),
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("organic", []):
            normalized = _normalize_result(item.get("title"), item.get("link"), item.get("snippet"))
            if normalized:
                results.append(normalized)
        return results


class JinaProvider(WebProvider):
    name = "jina"
    display_name = "Jina Search/Reader"

    def _key(self) -> str:
        return _configured_key("jina", ("JINA_API_KEY",))

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(self._key())

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        headers = {"Authorization": f"Bearer {self._key()}", "Accept": "application/json"}
        response = requests.get("https://s.jina.ai/", headers=headers, params={"q": query, "count": limit}, **_request_kwargs())
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("data", []):
            normalized = _normalize_result(
                item.get("title"),
                item.get("url"),
                item.get("description") or str(item.get("content") or "")[:400],
            )
            if normalized:
                results.append(normalized)
        return results

    def extract(self, url: str) -> str:
        headers = {
            "Authorization": f"Bearer {self._key()}",
            "X-Return-Format": "markdown",
            "X-Retain-Images": "none",
            "X-Timeout": "60",
        }
        response = requests.get(f"https://r.jina.ai/{url}", headers=headers, **_request_kwargs(timeout=60))
        response.raise_for_status()
        return response.text


class SearXNGProvider(WebProvider):
    name = "searxng"
    display_name = "SearXNG"
    requires_key = False

    def _url(self) -> str:
        return _configured_searxng_url()

    def supports_search(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(self._url())

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        response = requests.get(
            f"{self._url()}/search",
            params={"q": query, "format": "json", "language": "auto"},
            **_request_kwargs(),
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("results", [])[:limit]:
            normalized = _normalize_result(item.get("title"), item.get("url"), item.get("content"))
            if normalized:
                results.append(normalized)
        return results


class DDGSProvider(WebProvider):
    name = "ddgs"
    display_name = "DuckDuckGo (ddgs)"
    requires_key = False

    def supports_search(self) -> bool:
        return True

    def is_available(self) -> bool:
        try:
            import ddgs  # noqa: F401
            return True
        except Exception:
            try:
                import duckduckgo_search  # noqa: F401
                return True
            except Exception:
                return False

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        try:
            from ddgs import DDGS
        except Exception:
            from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=limit):
                normalized = _normalize_result(
                    item.get("title"),
                    item.get("href") or item.get("url"),
                    item.get("body") or item.get("snippet"),
                )
                if normalized:
                    results.append(normalized)
        return results


class DuckDuckGoHtmlProvider(WebProvider):
    name = "duckduckgo_html"
    display_name = "DuckDuckGo HTML"
    requires_key = False

    def supports_search(self) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        headers = {
            "User-Agent": "Mozilla/5.0",
        }
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
            **_request_kwargs(),
        )
        response.raise_for_status()
        return self._parse_html(response.text, limit)

    def _parse_html(self, text: str, limit: int) -> list[dict[str, str]]:
        blocks = re.split(r'<div[^>]+class=["\'][^"\']*\bresult\b[^"\']*["\'][^>]*>', text, flags=re.I)
        results: list[dict[str, str]] = []
        for block in blocks[1:]:
            if len(results) >= limit:
                break
            block = block.split('<div class="clear"', 1)[0]
            anchor_match = re.search(
                r'<a\b(?=[^>]*class=["\'][^"\']*\bresult__a\b[^"\']*["\'])([^>]*)>(.*?)</a>',
                block,
                re.I | re.S,
            )
            if not anchor_match:
                continue
            href_match = re.search(r'href=["\']([^"\']+)["\']', anchor_match.group(1), re.I)
            if not href_match:
                continue
            snippet_match = re.search(
                r'<a[^>]+class=["\'][^"\']*\bresult__snippet\b[^"\']*["\'][^>]*>(.*?)</a>',
                block,
                re.I | re.S,
            )
            if not snippet_match:
                snippet_match = re.search(
                    r'<div[^>]+class=["\'][^"\']*\bresult__snippet\b[^"\']*["\'][^>]*>(.*?)</div>',
                    block,
                    re.I | re.S,
                )
            normalized = _normalize_result(
                anchor_match.group(2),
                _unwrap_duckduckgo_url(html.unescape(href_match.group(1))),
                snippet_match.group(1) if snippet_match else "",
            )
            if normalized:
                results.append(normalized)
        return results


class FirecrawlProvider(WebProvider):
    name = "firecrawl"
    display_name = "Firecrawl"

    def _key(self) -> str:
        return _configured_key("firecrawl", ("FIRECRAWL_API_KEY",))

    def _base_url(self) -> str:
        return (os.environ.get("FIRECRAWL_API_URL") or "https://api.firecrawl.dev").rstrip("/")

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(self._key())

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json"}

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        response = requests.post(
            f"{self._base_url()}/v1/search",
            headers=self._headers(),
            json={"query": query, "limit": limit},
            **_request_kwargs(),
        )
        response.raise_for_status()
        data = response.json()
        raw_results = data.get("data") or data.get("results") or []
        results = []
        for item in raw_results:
            normalized = _normalize_result(
                item.get("title"),
                item.get("url"),
                item.get("description") or item.get("markdown") or item.get("content"),
            )
            if normalized:
                results.append(normalized)
        return results

    def extract(self, url: str) -> str:
        response = requests.post(
            f"{self._base_url()}/v1/scrape",
            headers=self._headers(),
            json={"url": url, "formats": ["markdown"]},
            **_request_kwargs(timeout=60),
        )
        response.raise_for_status()
        data = response.json()
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        return str(payload.get("markdown") or payload.get("content") or json.dumps(payload, ensure_ascii=False))


class BuiltInExtractorProvider(WebProvider):
    name = "built_in"
    display_name = "Built-in HTTP Reader"
    requires_key = False

    def supports_extract(self) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    def extract(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
        }
        response = requests.get(url, headers=headers, **_request_kwargs(timeout=60))
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return f"```json\n{response.text}\n```"
        if "text/plain" in content_type:
            return response.text
        parser = TextExtractor()
        parser.feed(response.text)
        title = parser.title
        text = parser.text()
        if title:
            return f"# {title}\n\n{text}\n\nSource: {url}"
        return f"{text}\n\nSource: {url}"


class LegacyBingProvider(WebProvider):
    name = "legacy_bing"
    display_name = "Legacy Bing fallback"
    requires_key = False

    def supports_search(self) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        candidates = [
            ("https://www.bing.com/search", {"q": query, "count": limit, "mkt": "zh-CN"}),
            ("https://cn.bing.com/search", {"q": query, "count": limit, "setlang": "zh-CN", "cc": "cn"}),
        ]
        for url, params in candidates:
            response = requests.get(url, params=params, headers=headers, **_request_kwargs())
            response.raise_for_status()
            results = self._parse_bing_html(response.text, limit)
            if results:
                return results
        return []

    def _parse_bing_html(self, text: str, limit: int) -> list[dict[str, str]]:
        blocks = re.split(r'<li[^>]+class=["\'][^"\']*\bb_algo\b[^"\']*["\'][^>]*>', text, flags=re.I)
        results: list[dict[str, str]] = []
        for block in blocks[1:]:
            if len(results) >= limit:
                break
            block = block.split("</li>", 1)[0]
            link_match = re.search(r"<h2[^>]*>.*?<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", block, re.I | re.S)
            if not link_match:
                continue
            snippet_match = re.search(r'<(?:p|div)[^>]*class=["\'][^"\']*(?:b_caption|b_snippetText)[^"\']*["\'][^>]*>(.*?)</(?:p|div)>', block, re.I | re.S)
            if not snippet_match:
                snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.I | re.S)
            normalized = _normalize_result(
                link_match.group(2),
                link_match.group(1),
                snippet_match.group(1) if snippet_match else "",
            )
            if normalized:
                results.append(normalized)
        return results


def _providers() -> dict[str, WebProvider]:
    providers: list[WebProvider] = [
        TavilyProvider(),
        ExaProvider(),
        BraveProvider(),
        SerperProvider(),
        JinaProvider(),
        SearXNGProvider(),
        DDGSProvider(),
        DuckDuckGoHtmlProvider(),
        FirecrawlProvider(),
        BuiltInExtractorProvider(),
        LegacyBingProvider(),
    ]
    return {provider.name: provider for provider in providers}


def _active_provider(config_key: str, capability: str, explicit: Optional[str] = None) -> WebProvider | None:
    config = _load_config(include_secrets=True)
    providers = _providers()
    configured = (explicit or config.get(config_key) or "auto").strip()
    if configured in {"default", "bing"}:
        configured = "legacy_bing"
    if configured and configured != "auto":
        provider = providers.get(configured)
        if provider and (provider.supports_search() if capability == "search" else provider.supports_extract()):
            return provider

    order = SEARCH_BACKEND_ORDER if capability == "search" else EXTRACT_BACKEND_ORDER
    for name in order:
        provider = providers.get(name)
        if not provider:
            continue
        if capability == "search" and not provider.supports_search():
            continue
        if capability == "extract" and not provider.supports_extract():
            continue
        if provider.is_available():
            return provider
    return None


def _provider_candidates(config_key: str, capability: str, explicit: Optional[str] = None) -> list[WebProvider]:
    config = _load_config(include_secrets=True)
    providers = _providers()
    configured = (explicit or config.get(config_key) or "auto").strip()
    if configured in {"default", "bing"}:
        configured = "legacy_bing"
    if configured and configured != "auto":
        provider = providers.get(configured)
        if provider and (provider.supports_search() if capability == "search" else provider.supports_extract()):
            return [provider]
        return []

    order = SEARCH_BACKEND_ORDER if capability == "search" else EXTRACT_BACKEND_ORDER
    candidates: list[WebProvider] = []
    for name in order:
        provider = providers.get(name)
        if not provider:
            continue
        if capability == "search" and not provider.supports_search():
            continue
        if capability == "extract" and not provider.supports_extract():
            continue
        if provider.is_available():
            candidates.append(provider)
    return candidates


def web_search(query: str, num_results: int = 10, backend: Optional[str] = None) -> tuple[list[dict[str, str]], str]:
    config = _load_config(include_secrets=True)
    if not config.get("enabled", True):
        raise RuntimeError("Web search is disabled in settings.")
    candidates = _provider_candidates("search_backend", "search", backend)
    if not candidates:
        raise RuntimeError("No web search provider is available.")
    limit = min(max(int(num_results or 10), 1), 20)
    errors: list[str] = []
    empty_provider = candidates[-1].name
    for provider in candidates:
        try:
            results = provider.search(query, limit)
        except Exception as exc:
            errors.append(f"{provider.name}: {exc}")
            logger.debug("Web search provider failed: %s", provider.name, exc_info=True)
            continue
        if results:
            return results, provider.name
        empty_provider = provider.name
    if errors and len(candidates) == len(errors):
        raise RuntimeError("; ".join(errors))
    return [], empty_provider


def browse_webpage(url: str, backend: Optional[str] = None) -> tuple[str, str]:
    config = _load_config(include_secrets=True)
    if not config.get("enabled", True):
        raise RuntimeError("Web search is disabled in settings.")
    provider = _active_provider("extract_backend", "extract", backend)
    if provider is None:
        raise RuntimeError("No web extraction provider is available.")
    return provider.extract(url), provider.name


def get_search_status() -> dict[str, Any]:
    providers = _providers()
    return {
        name: provider.info().__dict__
        for name, provider in providers.items()
        if provider.supports_search()
    }


def get_browse_status() -> dict[str, Any]:
    providers = _providers()
    return {
        name: provider.info().__dict__
        for name, provider in providers.items()
        if provider.supports_extract()
    }
