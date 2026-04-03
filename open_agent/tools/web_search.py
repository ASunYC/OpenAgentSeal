"""
Web search and browse tools with multiple backend support.

Supported search backends:
- default: Bing (cn.bing.com, free, no API key, works in China)
- serper: Google via Serper API
- brave: Brave Search API
- tavily: Tavily Search API
- jina: Jina AI Search

Supported browse backends:
- default: Built-in HTTP + HTML parser (free, no API key required)
- jina: Jina Reader API
"""

import os
import re
import time
import random
import asyncio
import urllib.parse
from typing import Any, Optional, Callable, Awaitable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

import requests
import urllib3

# Disable SSL warnings if verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================================
# Proxy Configuration
# ============================================================================

def get_proxy() -> Optional[dict]:
    """Get proxy configuration from environment variables."""
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    
    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    
    return proxies if proxies else None


def get_request_kwargs() -> dict:
    """Get common request kwargs including proxy and SSL settings."""
    kwargs = {
        "timeout": 60,
        "verify": True,  # Default to verify SSL
    }
    
    # Add proxy if configured
    proxies = get_proxy()
    if proxies:
        kwargs["proxies"] = proxies
    
    # Allow disabling SSL verify for testing
    if os.environ.get("WEB_SEARCH_VERIFY_SSL", "true").lower() == "false":
        kwargs["verify"] = False
    
    return kwargs

from .base import Tool, ToolResult


# ============================================================================
# Backend Configuration
# ============================================================================

class SearchBackend(Enum):
    """Search backend options."""
    DEFAULT = "default"  # Bing (free, China accessible)
    BING = "bing"        # Bing Search (free, works in China via cn.bing.com)
    SERPER = "serper"    # Google via Serper
    BRAVE = "brave"      # Brave Search
    TAVILY = "tavily"    # Tavily
    JINA = "jina"        # Jina AI


class BrowseBackend(Enum):
    """Browse backend options."""
    DEFAULT = "default"  # Built-in HTTP + HTML parser
    JINA = "jina"        # Jina Reader


def get_search_backend() -> SearchBackend:
    """Get configured search backend from environment."""
    backend = os.environ.get("WEB_SEARCH_BACKEND", "").lower()
    if backend == "serper" and os.environ.get("SERPER_API_KEY"):
        return SearchBackend.SERPER
    elif backend == "brave" and os.environ.get("BRAVE_API_KEY"):
        return SearchBackend.BRAVE
    elif backend == "tavily" and os.environ.get("TAVILY_API_KEY"):
        return SearchBackend.TAVILY
    elif backend == "jina" and os.environ.get("JINA_API_KEY"):
        return SearchBackend.JINA
    return SearchBackend.DEFAULT


def get_browse_backend() -> BrowseBackend:
    """Get configured browse backend from environment."""
    backend = os.environ.get("WEB_BROWSE_BACKEND", "").lower()
    if backend == "jina" and os.environ.get("JINA_API_KEY"):
        return BrowseBackend.JINA
    return BrowseBackend.DEFAULT


# ============================================================================
# Search Backend Implementations
# ============================================================================

def search_bing(query: str, num_results: int = 10) -> list[dict]:
    """
    Search using Bing (free, no API key required).
    Works in China via cn.bing.com
    
    Args:
        query: Search query string
        num_results: Number of results to return
        
    Returns:
        List of search results with title, link, snippet
    """
    # Use cn.bing.com for China accessibility
    url = "https://cn.bing.com/search"
    params = {"q": query, "count": num_results, "setlang": "zh-CN"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    
    # Get request kwargs with proxy support
    request_kwargs = get_request_kwargs()
    
    # Debug: log the actual URL being requested
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"Bing search URL: {url}?q={query}&count={num_results}")
    
    response = requests.get(url, params=params, headers=headers, **request_kwargs)
    response.raise_for_status()
    
    results = []
    html = response.text
    
    # Parse Bing HTML results
    # Bing results are in <li class="b_algo"> elements
    # Structure: <li class="b_algo">...<h2><a href="...">title</a></h2>...<div class="b_caption"><p>snippet</p></div>...</li>
    
    # Find all result containers - use more flexible pattern
    algo_pattern = re.compile(
        r'<li\s+class="b_algo"[^>]*>(.*?)</li>',
        re.DOTALL | re.IGNORECASE
    )
    
    for match in algo_pattern.finditer(html):
        if len(results) >= num_results:
            break
            
        block = match.group(1)
        
        # Extract link and title from h2 > a
        # Use more specific pattern to match h2 with nested a
        h2_pattern = re.compile(
            r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</h2>',
            re.DOTALL | re.IGNORECASE
        )
        h2_match = h2_pattern.search(block)
        
        if not h2_match:
            continue
            
        link = h2_match.group(1)
        # Remove any inner tags from title
        title = re.sub(r'<[^>]+>', '', h2_match.group(2)).strip()
        
        # Extract snippet from b_caption > p or just p tag
        snippet = ""
        caption_pattern = re.compile(
            r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>',
            re.DOTALL | re.IGNORECASE
        )
        caption_match = caption_pattern.search(block)
        if caption_match:
            snippet = re.sub(r'<[^>]+>', '', caption_match.group(1)).strip()
        else:
            # Try direct p tag if b_caption not found
            p_pattern = re.compile(
                r'<p[^>]*>(.*?)</p>',
                re.DOTALL | re.IGNORECASE
            )
            p_match = p_pattern.search(block)
            if p_match:
                snippet = re.sub(r'<[^>]+>', '', p_match.group(1)).strip()
        
        # Filter out ads and invalid links
        if link and title and not link.startswith("javascript:"):
            results.append({
                "title": title,
                "link": link,
                "snippet": snippet,
            })
    
    return results


def search_serper(query: str, num_results: int = 10) -> list[dict]:
    """
    Search Google using Serper API.
    
    Args:
        query: Search query string
        num_results: Number of results to return
        
    Returns:
        List of search results
    """
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        raise ValueError("SERPER_API_KEY environment variable is not set")
    
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num_results}
    
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    
    result = response.json()
    return result.get("organic", [])


def search_brave(query: str, num_results: int = 10) -> list[dict]:
    """
    Search using Brave Search API.
    
    Args:
        query: Search query string
        num_results: Number of results to return
        
    Returns:
        List of search results
    """
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        raise ValueError("BRAVE_API_KEY environment variable is not set")
    
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": num_results}
    
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    results = []
    
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("url", ""),
            "snippet": item.get("description", ""),
        })
    
    return results


def search_tavily(query: str, num_results: int = 10) -> list[dict]:
    """
    Search using Tavily API.
    
    Args:
        query: Search query string
        num_results: Number of results to return
        
    Returns:
        List of search results
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY environment variable is not set")
    
    url = "https://api.tavily.com/search"
    headers = {
        "Content-Type": "application/json",
    }
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": num_results,
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    results = []
    
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("url", ""),
            "snippet": item.get("content", ""),
        })
    
    return results


def search_jina(query: str, num_results: int = 10) -> list[dict]:
    """
    Search using Jina AI API.
    
    Args:
        query: Search query string
        num_results: Number of results to return
        
    Returns:
        List of search results
    """
    api_key = os.environ.get("JINA_API_KEY")
    if not api_key:
        raise ValueError("JINA_API_KEY environment variable is not set")
    
    url = "https://s.jina.ai/"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    params = {"q": query, "count": num_results}
    
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    results = []
    
    # Jina returns data in 'data' array
    for item in data.get("data", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("url", ""),
            "snippet": item.get("description", "") or item.get("content", "")[:300],
        })
    
    return results


# ============================================================================
# Browse Backend Implementations
# ============================================================================

def parse_html_content(html: str, url: str = "") -> str:
    """
    Parse HTML content and extract text using regex-based approach.
    No external dependencies required.
    
    Args:
        html: HTML content
        url: Source URL for context
        
    Returns:
        Extracted and cleaned text content
    """
    # Remove script and style elements
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    
    # Remove nav, footer, aside, header elements
    html = re.sub(r'<(nav|footer|aside|header)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    
    # Extract title
    title = ""
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
    
    # Extract meta description
    description = ""
    desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not desc_match:
        desc_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', html, re.IGNORECASE)
    if desc_match:
        description = desc_match.group(1).strip()
    
    # Extract headings
    headings = []
    for match in re.finditer(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', html, re.IGNORECASE):
        heading = match.group(1).strip()
        if heading:
            headings.append(heading)
    
    # Extract paragraphs
    paragraphs = []
    for match in re.finditer(r'<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE):
        p_content = match.group(1)
        # Remove inner tags
        p_text = re.sub(r'<[^>]+>', '', p_content)
        p_text = re.sub(r'\s+', ' ', p_text).strip()
        if p_text and len(p_text) > 20:
            paragraphs.append(p_text)
    
    # Extract list items
    list_items = []
    for match in re.finditer(r'<li[^>]*>(.*?)</li>', html, re.DOTALL | re.IGNORECASE):
        li_content = match.group(1)
        li_text = re.sub(r'<[^>]+>', '', li_content)
        li_text = re.sub(r'\s+', ' ', li_text).strip()
        if li_text and len(li_text) > 10:
            list_items.append(f"- {li_text}")
    
    # Extract links with text
    links = []
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', html, re.IGNORECASE):
        href = match.group(1)
        text = match.group(2).strip()
        if text and href and not href.startswith(('#', 'javascript:', 'mailto:')):
            links.append(f"[{text}]({href})")
    
    # Build output
    parts = []
    
    if title:
        parts.append(f"# {title}\n")
    
    if description:
        parts.append(f"\n> {description}\n")
    
    if headings:
        parts.append("\n## Contents\n")
        for h in headings[:10]:
            parts.append(f"- {h}")
    
    if paragraphs:
        parts.append("\n## Main Content\n")
        for p in paragraphs[:20]:
            parts.append(p)
            parts.append("")
    
    if list_items:
        parts.append("\n## Key Points\n")
        parts.extend(list_items[:15])
    
    # Add source URL
    if url:
        parts.append(f"\n---\nSource: {url}")
    
    content = "\n".join(parts)
    
    # Clean up extra whitespace
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    return content.strip()


def browse_default(url: str) -> str:
    """
    Browse webpage using built-in HTTP client and HTML parser.
    Free, no API key required.
    
    Args:
        url: URL to browse
        
    Returns:
        Extracted content in markdown format
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
    }
    
    # Get request kwargs with proxy support
    request_kwargs = get_request_kwargs()
    
    response = requests.get(url, headers=headers, **request_kwargs)
    response.raise_for_status()
    
    content_type = response.headers.get("Content-Type", "")
    
    # Handle non-HTML content
    if "application/json" in content_type:
        return f"```json\n{response.text}\n```"
    
    if "text/plain" in content_type:
        return response.text
    
    # Parse HTML
    html = response.text
    return parse_html_content(html, url)


def browse_jina(url: str) -> str:
    """
    Browse webpage using Jina Reader API.
    
    Args:
        url: URL to browse
        
    Returns:
        Markdown content
    """
    api_key = os.environ.get("JINA_API_KEY")
    if not api_key:
        raise ValueError("JINA_API_KEY environment variable is not set")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Engine": "direct",
        "Content-Type": "application/json",
        "X-Retain-Images": "none",
        "X-Return-Format": "markdown",
        "X-Timeout": "60",
    }
    payload = {"url": url}
    
    response = requests.post("https://r.jina.ai/", headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.text


# ============================================================================
# Unified Search Function
# ============================================================================

def web_search(query: str, num_results: int = 10, backend: Optional[str] = None) -> tuple[list[dict], str]:
    """
    Unified web search function.
    
    Args:
        query: Search query
        num_results: Number of results
        backend: Specific backend to use (optional)
        
    Returns:
        Tuple of (results, backend_used)
    """
    # Determine backend
    if backend:
        search_backend = SearchBackend(backend.lower())
    else:
        search_backend = get_search_backend()
    
    # Execute search based on backend
    if search_backend == SearchBackend.SERPER:
        return search_serper(query, num_results), "serper"
    elif search_backend == SearchBackend.BRAVE:
        return search_brave(query, num_results), "brave"
    elif search_backend == SearchBackend.TAVILY:
        return search_tavily(query, num_results), "tavily"
    elif search_backend == SearchBackend.JINA:
        return search_jina(query, num_results), "jina"
    else:
        # Default to Bing (works in China)
        return search_bing(query, num_results), "bing"


def browse_webpage(url: str, backend: Optional[str] = None) -> tuple[str, str]:
    """
    Unified webpage browse function.
    
    Args:
        url: URL to browse
        backend: Specific backend to use (optional)
        
    Returns:
        Tuple of (content, backend_used)
    """
    # Determine backend
    if backend:
        browse_backend = BrowseBackend(backend.lower())
    else:
        browse_backend = get_browse_backend()
    
    # Execute browse based on backend
    if browse_backend == BrowseBackend.JINA:
        return browse_jina(url), "jina"
    else:
        return browse_default(url), "built-in"


def format_search_results(results: list[dict], query: str, backend: str = "") -> str:
    """Format search results into readable text with clear structure."""
    if not results:
        return f"No search results found for query: {query}"
    
    backend_info = f" (via {backend})" if backend else ""
    
    # Build a more structured output
    output_lines = [
        f"## 🔍 搜索结果: {query}{backend_info}",
        f"找到 {len(results)} 条相关结果\n",
    ]
    
    for i, item in enumerate(results, 1):
        title = item.get("title", "No title")
        link = item.get("link") or item.get("url", "")
        snippet = item.get("snippet", "") or item.get("description", "")
        
        # Clean up snippet - remove HTML entities
        if snippet:
            snippet = re.sub(r'&[a-z]+;', ' ', snippet)
            snippet = re.sub(r'\s+', ' ', snippet).strip()
        
        output_lines.append(f"### {i}. {title}")
        output_lines.append(f"**链接**: {link}")
        if snippet:
            # Truncate very long snippets but keep key info
            if len(snippet) > 300:
                snippet = snippet[:300] + "..."
            output_lines.append(f"**摘要**: {snippet}")
        output_lines.append("")  # Empty line between results
    
    output_lines.append("---")
    output_lines.append("💡 **提示**: 请仔细阅读所有搜索结果，提取关键信息回答用户问题。")
    
    return "\n".join(output_lines)


# ============================================================================
# Tool Classes
# ============================================================================

class WebSearchTool(Tool):
    """Tool for searching the web with multiple backend support."""
    
    category = "web_search"
    alternatives = ["web_browse"]

    def __init__(self, max_retries: int = 3, retry_delay: tuple[float, float] = (1, 5)):
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "搜索网络获取最新信息。"
            "默认使用 Bing (cn.bing.com，免费，国内可用，无需API密钥)。"
            "返回包含标题、链接和摘要的搜索结果。\n\n"
            "⚠️ **重要：使用条件**\n"
            "- **只有在用户明确要求联网搜索时才使用此工具**\n"
            "- 触发关键词包括：\"联网搜索\"、\"网上搜索\"、\"搜索一下\"、\"查一下\"、\"上网查\" 等\n"
            "- 如果用户没有明确要求联网搜索，**不要**主动使用此工具\n"
            "- 适合查询最新新闻、电影、事件等实时信息\n\n"
            "⚠️ **重要：搜索词规则**\n"
            "- **直接使用用户的原始问题作为搜索词**，不要修改、添加或删除任何内容\n"
            "- **不要**自己添加时间限定（如 '2024'、'2025'、'最新' 等）\n"
            "- **不要**自己添加或删除关键词\n"
            "- **不要**自己改写或优化搜索词\n"
            "- 例如：用户问'沈腾 最新电影'，搜索词就是'沈腾 最新电影'，而不是'沈腾 最新电影 2024'\n"
            "- 搜索引擎会自动处理时效性问题，你不需要添加时间词\n"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询词。**必须直接使用用户的原始问题，不要修改或添加任何内容！** 例如用户问'沈腾 最新电影'，这里就填'沈腾 最新电影'，不要改成'沈腾 最新电影 2024'。",
                },
                "num_results": {
                    "type": "integer",
                    "description": "返回结果数量（默认: 5，最大: 20）。建议使用5-10条，太多会影响阅读。",
                    "default": 5,
                },
                "backend": {
                    "type": "string",
                    "description": "Search backend: 'default' or 'bing' (Bing, works in China), 'serper' (Google), 'brave', 'tavily', 'jina'.",
                    "enum": ["default", "bing", "serper", "brave", "tavily", "jina"],
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        num_results: int = 5,
        backend: Optional[str] = None
    ) -> ToolResult:
        """Execute web search."""
        num_results = min(max(1, num_results), 20)
        
        for attempt in range(self.max_retries):
            try:
                # Add delay on retry
                if attempt > 0:
                    delay = random.uniform(*self.retry_delay)
                    await asyncio.sleep(delay)
                
                # Run search in thread pool
                loop = asyncio.get_event_loop()
                results, used_backend = await loop.run_in_executor(
                    None,
                    lambda: web_search(query, num_results, backend)
                )
                
                # Format results
                content = format_search_results(results, query, used_backend)
                return ToolResult(success=True, content=content)
                
            except ValueError as e:
                # Missing API key
                return ToolResult(
                    success=False,
                    content="",
                    error=str(e),
                )
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response else "unknown"
                if status_code == 429:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(random.uniform(5, 15))
                        continue
                    return ToolResult(
                        success=False,
                        content="",
                        error="Rate limited. Please try again later.",
                    )
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Search failed: HTTP {status_code}",
                )
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    continue
                return ToolResult(
                    success=False,
                    content="",
                    error="Search request timed out.",
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Search failed: {str(e)}",
                )
        
        return ToolResult(
            success=False,
            content="",
            error="Search failed after maximum retries.",
        )


class WebBrowseTool(Tool):
    """Tool for reading and analyzing web page content."""
    
    category = "web_search"
    alternatives = ["web_search"]

    def __init__(self, max_retries: int = 2, retry_delay: tuple[float, float] = (1, 5)):
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    @property
    def name(self) -> str:
        return "web_browse"

    @property
    def description(self) -> str:
        return (
            "Read and analyze content from a web page URL. "
            "Uses built-in HTML parser by default (free, no API key required). "
            "Can also use Jina Reader API if configured. "
            "Returns page content in structured markdown format."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the web page to read",
                },
                "backend": {
                    "type": "string",
                    "description": "Specific backend to use: 'default' (built-in), 'jina'. If not specified, uses configured default.",
                    "enum": ["default", "jina"],
                },
            },
            "required": ["url"],
        }

    async def execute(self, url: str, backend: Optional[str] = None) -> ToolResult:
        """Execute web page reading."""
        # Validate URL
        if not url.startswith(("http://", "https://")):
            return ToolResult(
                success=False,
                content="",
                error=f"Invalid URL: {url}. URL must start with http:// or https://",
            )
        
        for attempt in range(self.max_retries):
            try:
                # Add delay on retry
                if attempt > 0:
                    delay = random.uniform(*self.retry_delay)
                    await asyncio.sleep(delay)
                
                # Run browse in thread pool
                loop = asyncio.get_event_loop()
                content, used_backend = await loop.run_in_executor(
                    None,
                    lambda: browse_webpage(url, backend)
                )
                
                if not content or not content.strip():
                    return ToolResult(
                        success=False,
                        content="",
                        error="The page returned empty content.",
                    )
                
                # Truncate if too long
                max_chars = 100000
                if len(content) > max_chars:
                    content = content[:max_chars] + f"\n\n... [Content truncated, original length: {len(content)} characters]"
                
                return ToolResult(
                    success=True,
                    content=f"--- Content from: {url} (via {used_backend}) ---\n\n{content}\n\n--- End of content ---",
                )
                
            except ValueError as e:
                # Missing API key
                return ToolResult(
                    success=False,
                    content="",
                    error=str(e),
                )
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response else "unknown"
                if status_code in (403, 404):
                    return ToolResult(
                        success=False,
                        content="",
                        error=f"Access denied or page not found (HTTP {status_code}): {url}",
                    )
                if attempt < self.max_retries - 1:
                    continue
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Failed to fetch page: HTTP {status_code}",
                )
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    continue
                return ToolResult(
                    success=False,
                    content="",
                    error="Request timed out while fetching the page.",
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Failed to browse page: {str(e)}",
                )
        
        return ToolResult(
            success=False,
            content="",
            error="Failed to browse page after maximum retries.",
        )


class MultiWebSearchTool(Tool):
    """Tool for searching multiple queries in parallel."""
    
    category = "web_search"
    alternatives = ["web_search"]

    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers

    @property
    def name(self) -> str:
        return "multi_web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for multiple queries in parallel. "
            "More efficient than calling web_search multiple times. "
            "Returns combined results for all queries."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of search queries to execute in parallel",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results per query (default: 5, max: 10)",
                    "default": 5,
                },
            },
            "required": ["queries"],
        }

    async def execute(self, queries: list[str], num_results: int = 5) -> ToolResult:
        """Execute parallel web searches."""
        if not queries:
            return ToolResult(
                success=False,
                content="",
                error="No queries provided.",
            )
        
        num_results = min(max(1, num_results), 10)
        
        # Create search tasks
        search_tool = WebSearchTool()
        tasks = [
            search_tool.execute(query=query, num_results=num_results)
            for query in queries
        ]
        
        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Combine results
        combined_parts = []
        errors = []
        
        for query, result in zip(queries, results):
            if isinstance(result, Exception):
                errors.append(f"Query '{query}' failed: {str(result)}")
            elif isinstance(result, ToolResult):
                if result.success:
                    combined_parts.append(result.content)
                else:
                    errors.append(f"Query '{query}': {result.error}")
        
        # Build output
        output_lines = []
        if combined_parts:
            output_lines.append("=== Combined Search Results ===\n")
            output_lines.extend(combined_parts)
        
        if errors:
            output_lines.append("\n=== Errors ===")
            output_lines.extend(errors)
        
        if not combined_parts and errors:
            return ToolResult(
                success=False,
                content="",
                error="\n".join(errors),
            )
        
        return ToolResult(
            success=True,
            content="\n".join(output_lines),
        )


# ============================================================================
# Search Report Tool - Uses LLM to generate beautiful reports
# ============================================================================

# Report generation prompt template
REPORT_PROMPT_TEMPLATE = """你是一个专业的信息整理助手。请根据以下搜索结果，生成一份结构清晰、内容丰富的报告。

## 搜索主题
{query}

## 搜索结果
{search_results}

## 报告要求
1. 使用中文撰写报告
2. 报告结构：
   - 标题：简明扼要地概括主题
   - 摘要：用2-3句话总结核心发现
   - 主要内容：按主题分类整理信息，每个主题下提供详细说明
   - 相关链接：列出重要的参考来源
3. 使用 Markdown 格式排版
4. 突出关键信息（使用加粗）
5. 确保信息准确，不要编造内容
6. 如果搜索结果不足以回答问题，请明确说明

请开始撰写报告："""


class WebSearchReportTool(Tool):
    """Tool for searching the web and generating a formatted report using LLM.
    
    This tool combines web search with LLM-based report generation.
    It first searches for information, then uses the provided LLM callback
    to generate a well-formatted report.
    """
    
    category = "web_search"
    alternatives = ["web_search", "web_browse"]
    
    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: tuple[float, float] = (1, 5),
        llm_generate_callback: Optional[Callable[[str], Awaitable[str]]] = None,
    ):
        """Initialize the tool.
        
        Args:
            max_retries: Maximum number of retries for search
            retry_delay: Delay range between retries
            llm_generate_callback: Async function to call LLM with a prompt.
                                   Should take a prompt string and return the response string.
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._llm_callback = llm_generate_callback
    
    def set_llm_callback(self, callback: Callable[[str], Awaitable[str]]):
        """Set the LLM generate callback function.
        
        Args:
            callback: Async function that takes a prompt and returns LLM response
        """
        self._llm_callback = callback
    
    @property
    def name(self) -> str:
        return "web_search_report"
    
    @property
    def description(self) -> str:
        return (
            "搜索网络并生成格式化的研究报告。"
            "执行搜索后，会使用AI整理信息并生成一份结构清晰的报告。"
            "适合需要深入了解某个主题的场景。"
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询。支持高级搜索操作符。",
                },
                "num_results": {
                    "type": "integer",
                    "description": "搜索结果数量（默认: 10，最大: 20）",
                    "default": 10,
                },
                "browse_top_results": {
                    "type": "integer",
                    "description": "是否浏览排名前N的搜索结果页面获取更多内容（默认: 3，设为0则不浏览）",
                    "default": 3,
                },
            },
            "required": ["query"],
        }
    
    async def execute(
        self,
        query: str,
        num_results: int = 10,
        browse_top_results: int = 3,
    ) -> ToolResult:
        """Execute web search and generate report."""
        num_results = min(max(1, num_results), 20)
        browse_top_results = min(max(0, browse_top_results), 5)
        
        # Step 1: Perform search
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    delay = random.uniform(*self.retry_delay)
                    await asyncio.sleep(delay)
                
                loop = asyncio.get_event_loop()
                results, used_backend = await loop.run_in_executor(
                    None,
                    lambda: web_search(query, num_results)
                )
                break
            except Exception as e:
                if attempt == self.max_retries - 1:
                    return ToolResult(
                        success=False,
                        content="",
                        error=f"Search failed: {str(e)}",
                    )
                continue
        
        if not results:
            return ToolResult(
                success=False,
                content="",
                error=f"No search results found for: {query}",
            )
        
        # Step 2: Optionally browse top results for more content
        enriched_results = []
        if browse_top_results > 0:
            browse_tool = WebBrowseTool()
            for i, result in enumerate(results[:browse_top_results]):
                url = result.get("link") or result.get("url", "")
                if url:
                    try:
                        browse_result = await browse_tool.execute(url=url)
                        if browse_result.success:
                            # Truncate browsed content
                            content = browse_result.content[:2000]
                            enriched_results.append({
                                **result,
                                "page_content": content,
                            })
                        else:
                            enriched_results.append(result)
                    except Exception:
                        enriched_results.append(result)
                else:
                    enriched_results.append(result)
            
            # Add remaining results without browsing
            enriched_results.extend(results[browse_top_results:])
        else:
            enriched_results = results
        
        # Step 3: Format search results for LLM
        formatted_results = []
        for i, item in enumerate(enriched_results, 1):
            title = item.get("title", "No title")
            link = item.get("link") or item.get("url", "")
            snippet = item.get("snippet", "") or item.get("description", "")
            page_content = item.get("page_content", "")
            
            result_text = f"### 结果 {i}: {title}\n"
            result_text += f"链接: {link}\n"
            if snippet:
                result_text += f"摘要: {snippet}\n"
            if page_content:
                result_text += f"页面内容摘要:\n{page_content}\n"
            formatted_results.append(result_text)
        
        search_results_text = "\n---\n".join(formatted_results)
        
        # Step 4: Generate report using LLM
        if self._llm_callback is None:
            # If no LLM callback, return formatted search results
            return ToolResult(
                success=True,
                content=f"## 搜索结果: {query}\n\n"
                       f"（注：未配置LLM回调，返回原始搜索结果）\n\n"
                       f"{search_results_text}",
            )
        
        try:
            prompt = REPORT_PROMPT_TEMPLATE.format(
                query=query,
                search_results=search_results_text,
            )
            
            report = await self._llm_callback(prompt)
            
            return ToolResult(
                success=True,
                content=report,
            )
            
        except Exception as e:
            # If LLM fails, still return the search results
            return ToolResult(
                success=True,
                content=f"## 搜索结果: {query}\n\n"
                       f"（注：报告生成失败，返回原始搜索结果。错误: {str(e)}）\n\n"
                       f"{search_results_text}",
            )


# ============================================================================
# Convenience Functions
# ============================================================================

def get_serper_api_key() -> str | None:
    """Get Serper API key from environment."""
    return os.environ.get("SERPER_API_KEY")


def get_jina_api_key() -> str | None:
    """Get Jina API key from environment."""
    return os.environ.get("JINA_API_KEY")


def get_brave_api_key() -> str | None:
    """Get Brave API key from environment."""
    return os.environ.get("BRAVE_API_KEY")


def get_tavily_api_key() -> str | None:
    """Get Tavily API key from environment."""
    return os.environ.get("TAVILY_API_KEY")


def get_search_status() -> dict[str, Any]:
    """Get status of all search backends."""
    return {
        "default": {
            "available": True,
            "name": "Bing (cn.bing.com)",
            "requires_key": False,
            "note": "Works in China",
        },
        "bing": {
            "available": True,
            "name": "Bing (cn.bing.com)",
            "requires_key": False,
            "note": "Works in China",
        },
        "serper": {
            "available": bool(os.environ.get("SERPER_API_KEY")),
            "name": "Google (via Serper)",
            "requires_key": True,
            "key_set": bool(os.environ.get("SERPER_API_KEY")),
        },
        "brave": {
            "available": bool(os.environ.get("BRAVE_API_KEY")),
            "name": "Brave Search",
            "requires_key": True,
            "key_set": bool(os.environ.get("BRAVE_API_KEY")),
        },
        "tavily": {
            "available": bool(os.environ.get("TAVILY_API_KEY")),
            "name": "Tavily",
            "requires_key": True,
            "key_set": bool(os.environ.get("TAVILY_API_KEY")),
        },
        "jina": {
            "available": bool(os.environ.get("JINA_API_KEY")),
            "name": "Jina AI",
            "requires_key": True,
            "key_set": bool(os.environ.get("JINA_API_KEY")),
        },
    }


def get_browse_status() -> dict[str, Any]:
    """Get status of all browse backends."""
    return {
        "default": {
            "available": True,
            "name": "Built-in HTTP + HTML Parser",
            "requires_key": False,
        },
        "jina": {
            "available": bool(os.environ.get("JINA_API_KEY")),
            "name": "Jina Reader",
            "requires_key": True,
            "key_set": bool(os.environ.get("JINA_API_KEY")),
        },
    }