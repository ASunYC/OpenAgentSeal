"""MinerU API adapter and document translation pipeline.

The bundled plugin talks to MinerU through HTTP only. It does not install or
import the heavyweight MinerU runtime.
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import mimetypes
import re
import shutil
import subprocess
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from open_agent.llm import LLMClient
from open_agent.schema import LLMProvider, Message
from open_agent.user_config import get_user_config
from open_agent.utils.path_utils import get_data_dir

MINERU_PLUGIN_ID = "mineru@openagentseal"
DEFAULT_API_URL = "https://mineru.net"
DEFAULT_TARGET_LANGUAGE = "Simplified Chinese"
POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 30 * 60
TRANSLATION_CHUNK_SIZE = 6000


class MinerUError(RuntimeError):
    """Raised when MinerU parsing or translation fails."""


@dataclass
class MinerUResult:
    task_id: str
    protocol: str
    result_dir: Path
    markdown_path: Path
    translated_markdown_path: Path | None = None
    translated_pdf_path: Path | None = None
    pdf_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "protocol": self.protocol,
            "result_dir": str(self.result_dir),
            "markdown_path": str(self.markdown_path),
            "translated_markdown_path": (
                str(self.translated_markdown_path)
                if self.translated_markdown_path
                else None
            ),
            "translated_pdf_path": (
                str(self.translated_pdf_path) if self.translated_pdf_path else None
            ),
            "pdf_error": self.pdf_error,
        }


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip(".-")
    return cleaned or "document"


def _result_directory(source: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_dir = (
        get_data_dir()
        / "plugins"
        / "mineru"
        / "results"
        / f"{stamp}_{_safe_name(source.stem)}_{uuid.uuid4().hex[:6]}"
    )
    result_dir.mkdir(parents=True, exist_ok=False)
    return result_dir


def _safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            target = (destination / info.filename).resolve()
            if target != destination_root and destination_root not in target.parents:
                raise MinerUError(f"Unsafe path in MinerU result archive: {info.filename}")
        archive.extractall(destination)


def _find_markdown(root: Path) -> Path:
    preferred = list(root.rglob("full.md"))
    candidates = preferred or list(root.rglob("*.md"))
    if not candidates:
        raise MinerUError("MinerU result did not contain a Markdown file")
    return candidates[0]


def _materialize_markdown(source_markdown: Path, result_dir: Path) -> Path:
    destination = result_dir / "original.md"
    shutil.copy2(source_markdown, destination)
    source_images = source_markdown.parent / "images"
    destination_images = result_dir / "images"
    if source_images.exists() and source_images.is_dir():
        shutil.copytree(source_images, destination_images, dirs_exist_ok=True)
    return destination


def _normalize_api_root(api_url: str) -> str:
    value = (api_url or DEFAULT_API_URL).strip().rstrip("/")
    for suffix in ("/api/v4", "/api/v1/agent"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    if not value.startswith(("http://", "https://")):
        raise MinerUError("MinerU API address must start with http:// or https://")
    return value


class MinerUService:
    def __init__(
        self,
        api_url: str,
        api_token: str = "",
        translation_model_id: str = "",
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_root = _normalize_api_root(api_url)
        self.api_token = api_token.strip()
        self.translation_model_id = translation_model_id.strip()
        self.target_language = target_language or DEFAULT_TARGET_LANGUAGE
        self._client = client

    async def parse_document(
        self,
        file_path: str | Path,
        *,
        add_to_library: bool = True,
    ) -> MinerUResult:
        source = Path(file_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise MinerUError(f"Document does not exist: {source}")

        result_dir = _result_directory(source)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(180, connect=30),
        )
        try:
            if "mineru.net" in self.api_root:
                if self.api_token:
                    result = await self._parse_cloud_v4(client, source, result_dir)
                else:
                    result = await self._parse_cloud_agent(client, source, result_dir)
            else:
                try:
                    result = await self._parse_self_hosted(client, source, result_dir)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {404, 405}:
                        raise
                    if not self.api_token:
                        raise MinerUError(
                            "The configured service is not a compatible self-hosted MinerU API"
                        ) from exc
                    result = await self._parse_cloud_v4(client, source, result_dir)
        except Exception:
            shutil.rmtree(result_dir, ignore_errors=True)
            raise
        finally:
            if owns_client:
                await client.aclose()

        if add_to_library:
            add_result_to_library(result.result_dir)
        return result

    async def translate_document(
        self,
        file_path: str | Path,
        *,
        target_language: str | None = None,
        add_to_library: bool = True,
    ) -> MinerUResult:
        result = await self.parse_document(file_path, add_to_library=False)
        language = target_language or self.target_language
        translated = await self._translate_markdown(
            result.markdown_path.read_text(encoding="utf-8"),
            language,
        )
        suffix = {
            "Simplified Chinese": "zh",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
        }.get(language, _safe_name(language).lower()[:12])
        translated_md = result.result_dir / f"translated_{suffix}.md"
        translated_md.write_text(translated, encoding="utf-8")
        result.translated_markdown_path = translated_md

        translated_pdf = result.result_dir / f"translated_{suffix}.pdf"
        try:
            await asyncio.to_thread(
                render_markdown_to_pdf,
                translated,
                translated_pdf,
                result.markdown_path.parent,
                Path(file_path).stem,
            )
            result.translated_pdf_path = translated_pdf
        except Exception as exc:
            result.pdf_error = str(exc)

        metadata_path = result.result_dir / "result.json"
        metadata_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if add_to_library:
            add_result_to_library(result.result_dir)
        return result

    async def _parse_cloud_v4(
        self,
        client: httpx.AsyncClient,
        source: Path,
        result_dir: Path,
    ) -> MinerUResult:
        headers = {"Authorization": f"Bearer {self.api_token}"}
        create_response = await client.post(
            f"{self.api_root}/api/v4/file-urls/batch",
            headers=headers,
            json={
                "files": [{"name": source.name, "data_id": uuid.uuid4().hex}],
                "model_version": "vlm",
                "enable_formula": True,
                "enable_table": True,
                "language": "ch",
            },
        )
        create_response.raise_for_status()
        payload = create_response.json()
        self._ensure_cloud_success(payload, "create upload task")
        data = payload.get("data") or {}
        batch_id = str(data.get("batch_id") or "")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            raise MinerUError("MinerU did not return a batch ID and upload URL")
        first_url = file_urls[0]
        upload_url = first_url.get("url") if isinstance(first_url, dict) else first_url
        if not upload_url:
            raise MinerUError("MinerU upload URL is empty")
        upload_response = await client.put(str(upload_url), content=source.read_bytes())
        upload_response.raise_for_status()

        deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            response = await client.get(
                f"{self.api_root}/api/v4/extract-results/batch/{batch_id}",
                headers=headers,
            )
            response.raise_for_status()
            poll_payload = response.json()
            self._ensure_cloud_success(poll_payload, "poll extraction task")
            items = (poll_payload.get("data") or {}).get("extract_result") or []
            if items:
                item = items[0]
                state = str(item.get("state") or "").lower()
                if state == "done":
                    zip_url = item.get("full_zip_url")
                    if not zip_url:
                        raise MinerUError("MinerU completed without a full_zip_url")
                    markdown_path = await self._download_result_zip(
                        client,
                        str(zip_url),
                        result_dir,
                    )
                    return MinerUResult(
                        task_id=batch_id,
                        protocol="cloud-v4",
                        result_dir=result_dir,
                        markdown_path=markdown_path,
                    )
                if state == "failed":
                    raise MinerUError(item.get("err_msg") or "MinerU extraction failed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise MinerUError(f"MinerU task timed out: {batch_id}")

    async def _parse_cloud_agent(
        self,
        client: httpx.AsyncClient,
        source: Path,
        result_dir: Path,
    ) -> MinerUResult:
        response = await client.post(
            f"{self.api_root}/api/v1/agent/parse/file",
            json={
                "file_name": source.name,
                "language": "ch",
                "enable_table": True,
                "is_ocr": False,
                "enable_formula": True,
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._ensure_cloud_success(payload, "create lightweight upload task")
        data = payload.get("data") or {}
        task_id = str(data.get("task_id") or "")
        upload_url = str(data.get("file_url") or "")
        if not task_id or not upload_url:
            raise MinerUError("MinerU did not return a task ID and upload URL")
        upload_response = await client.put(upload_url, content=source.read_bytes())
        upload_response.raise_for_status()

        deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            poll_response = await client.get(
                f"{self.api_root}/api/v1/agent/parse/{task_id}"
            )
            poll_response.raise_for_status()
            poll_payload = poll_response.json()
            self._ensure_cloud_success(poll_payload, "poll lightweight task")
            poll_data = poll_payload.get("data") or {}
            state = str(poll_data.get("state") or "").lower()
            if state == "done":
                markdown_url = poll_data.get("markdown_url")
                if not markdown_url:
                    raise MinerUError("MinerU completed without a markdown_url")
                markdown_response = await client.get(str(markdown_url))
                markdown_response.raise_for_status()
                markdown_path = result_dir / "original.md"
                markdown_path.write_text(markdown_response.text, encoding="utf-8")
                return MinerUResult(
                    task_id=task_id,
                    protocol="cloud-agent",
                    result_dir=result_dir,
                    markdown_path=markdown_path,
                )
            if state == "failed":
                raise MinerUError(poll_data.get("err_msg") or "MinerU extraction failed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise MinerUError(f"MinerU task timed out: {task_id}")

    async def _parse_self_hosted(
        self,
        client: httpx.AsyncClient,
        source: Path,
        result_dir: Path,
    ) -> MinerUResult:
        headers = (
            {"Authorization": f"Bearer {self.api_token}"}
            if self.api_token
            else None
        )
        with source.open("rb") as stream:
            response = await client.post(
                f"{self.api_root}/tasks",
                headers=headers,
                files={
                    "files": (
                        source.name,
                        stream,
                        mimetypes.guess_type(source.name)[0]
                        or "application/octet-stream",
                    )
                },
                data={
                    "return_md": "true",
                    "return_images": "true",
                    "return_content_list": "true",
                },
            )
        response.raise_for_status()
        payload = response.json()
        task_id = str(
            payload.get("task_id")
            or (payload.get("data") or {}).get("task_id")
            or ""
        )
        if not task_id:
            raise MinerUError("Self-hosted MinerU did not return a task_id")

        deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            status_response = await client.get(
                f"{self.api_root}/tasks/{task_id}",
                headers=headers,
            )
            status_response.raise_for_status()
            status_payload = status_response.json()
            state = str(
                status_payload.get("state")
                or status_payload.get("status")
                or (status_payload.get("data") or {}).get("state")
                or ""
            ).lower()
            if state in {"done", "completed", "success", "succeeded"}:
                result_response = await client.get(
                    f"{self.api_root}/tasks/{task_id}/result",
                    headers=headers,
                )
                result_response.raise_for_status()
                markdown_path = self._save_self_hosted_result(
                    result_response,
                    source,
                    result_dir,
                )
                return MinerUResult(
                    task_id=task_id,
                    protocol="self-hosted",
                    result_dir=result_dir,
                    markdown_path=markdown_path,
                )
            if state in {"failed", "error"}:
                raise MinerUError(
                    status_payload.get("error")
                    or status_payload.get("message")
                    or "MinerU extraction failed"
                )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise MinerUError(f"MinerU task timed out: {task_id}")

    async def _download_result_zip(
        self,
        client: httpx.AsyncClient,
        zip_url: str,
        result_dir: Path,
    ) -> Path:
        response = await client.get(zip_url)
        response.raise_for_status()
        zip_path = result_dir / "mineru_result.zip"
        zip_path.write_bytes(response.content)
        extract_dir = result_dir / "parsed"
        _safe_extract_zip(zip_path, extract_dir)
        zip_path.unlink(missing_ok=True)
        source_markdown = _find_markdown(extract_dir)
        return _materialize_markdown(source_markdown, result_dir)

    def _save_self_hosted_result(
        self,
        response: httpx.Response,
        source: Path,
        result_dir: Path,
    ) -> Path:
        content_type = response.headers.get("content-type", "")
        if "zip" in content_type or response.content.startswith(b"PK"):
            zip_path = result_dir / "mineru_result.zip"
            zip_path.write_bytes(response.content)
            extract_dir = result_dir / "parsed"
            _safe_extract_zip(zip_path, extract_dir)
            zip_path.unlink(missing_ok=True)
            markdown = _find_markdown(extract_dir)
            return _materialize_markdown(markdown, result_dir)

        payload = response.json()
        raw_result = payload.get("result") or payload.get("data") or payload
        document_result = raw_result
        if isinstance(raw_result, dict) and source.name in raw_result:
            document_result = raw_result[source.name]
        if not isinstance(document_result, dict):
            raise MinerUError("Self-hosted MinerU returned an unsupported result")
        markdown_text = (
            document_result.get("md_content")
            or document_result.get("markdown")
            or document_result.get("content")
        )
        if not isinstance(markdown_text, str):
            raise MinerUError("Self-hosted MinerU result did not contain Markdown")
        markdown_path = result_dir / "original.md"
        markdown_path.write_text(markdown_text, encoding="utf-8")

        images = document_result.get("images") or {}
        if isinstance(images, dict):
            images_dir = result_dir / "images"
            for name, encoded in images.items():
                if not isinstance(encoded, str):
                    continue
                images_dir.mkdir(exist_ok=True)
                try:
                    (images_dir / Path(name).name).write_bytes(base64.b64decode(encoded))
                except ValueError:
                    continue
        return markdown_path

    @staticmethod
    def _ensure_cloud_success(payload: dict[str, Any], action: str) -> None:
        if payload.get("code", 0) != 0:
            message = payload.get("msg") or payload.get("message") or payload
            raise MinerUError(f"MinerU failed to {action}: {message}")

    async def _translate_markdown(self, source: str, target_language: str) -> str:
        if not self.translation_model_id:
            raise MinerUError("Select a translation model in the MinerU plugin settings")
        model_config = get_user_config().get_model(self.translation_model_id)
        if model_config is None:
            raise MinerUError("The configured translation model no longer exists")
        provider = (
            LLMProvider.ANTHROPIC
            if (model_config.provider_type or "").lower() == "anthropic"
            else LLMProvider.OPENAI
        )
        client = LLMClient(
            api_key=model_config.api_key,
            provider=provider,
            api_base=model_config.base_url or "",
            model=model_config.name,
        )
        chunks, placeholders = split_markdown_for_translation(source)
        translated_chunks = []
        system_prompt = (
            f"Translate the supplied Markdown into {target_language}. "
            "Preserve headings, lists, tables, citations, numbering, URLs and all "
            "@@MINERU_KEEP_XXXXXX@@ placeholders exactly. Do not add commentary or "
            "Markdown fences around the response."
        )
        for index, chunk in enumerate(chunks, start=1):
            response = await client.generate(
                [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=chunk),
                ]
            )
            translated = response.content
            expected = set(re.findall(r"@@MINERU_KEEP_\d{6}@@", chunk))
            actual = set(re.findall(r"@@MINERU_KEEP_\d{6}@@", translated))
            if expected != actual:
                raise MinerUError(
                    f"Translation model changed protected content in chunk {index}"
                )
            translated_chunks.append(translated)
        result = "\n".join(translated_chunks)
        for placeholder, original in placeholders.items():
            result = result.replace(placeholder, original)
        return result


def split_markdown_for_translation(
    source: str,
    limit: int = TRANSLATION_CHUNK_SIZE,
) -> tuple[list[str], dict[str, str]]:
    placeholders: dict[str, str] = {}
    protected = source
    patterns = [
        r"```[\s\S]*?```",
        r"!\[[^\]]*]\([^)]+\)",
        r"\$\$[\s\S]*?\$\$",
        r"\\\[[\s\S]*?\\\]",
        r"\\\([\s\S]*?\\\)",
        r"(?<!\$)\$(?!\$)[^\n$]+\$",
        r"`[^`\n]+`",
    ]

    for pattern in patterns:
        def replace(match: re.Match[str]) -> str:
            key = f"@@MINERU_KEEP_{len(placeholders):06d}@@"
            placeholders[key] = match.group(0)
            return key

        protected = re.sub(pattern, replace, protected)

    chunks: list[str] = []
    current = ""
    for block in re.split(r"(\n\s*\n)", protected):
        if not block:
            continue
        if len(block) > limit:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(block), limit):
                chunks.append(block[start : start + limit])
            continue
        if current and len(current) + len(block) > limit:
            chunks.append(current)
            current = ""
        current += block
    if current:
        chunks.append(current)
    return chunks or [""], placeholders


def _browser_path() -> Path:
    candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        shutil.which("chromium"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise MinerUError("Microsoft Edge, Chrome, or Chromium is required to render PDF")


def render_markdown_to_pdf(
    markdown_text: str,
    output_path: Path,
    asset_root: Path,
    title: str,
) -> None:
    try:
        import markdown
    except ImportError as exc:
        raise MinerUError("The markdown package is required to render PDF") from exc

    body = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
        output_format="html5",
    )
    document = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <base href="{html.escape(asset_root.resolve().as_uri())}/">
  <title>{html.escape(title)}</title>
  <style>
    @page {{ size: A4; margin: 18mm 16mm; }}
    body {{ color: #171717; font: 15px/1.65 "Segoe UI", Arial, sans-serif; }}
    img {{ max-width: 100%; height: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 6px 8px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #f5f7fa; padding: 12px; }}
    code {{ overflow-wrap: anywhere; }}
  </style>
  <script>
    window.MathJax = {{ tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']] }} }};
  </script>
  <script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>{body}</body>
</html>"""
    html_path = output_path.with_suffix(".html")
    html_path.write_text(document, encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(_browser_path()),
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-background-networking",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=15000",
        "--no-pdf-header-footer",
        f"--print-to-pdf={output_path.resolve()}",
        html_path.resolve().as_uri(),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    html_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output_path.exists():
        raise MinerUError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Browser did not produce the translated PDF"
        )


def _source_descriptor(path: Path) -> dict[str, Any]:
    stat = path.stat()
    children = []
    if path.is_dir():
        for child in sorted(
            path.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )[:200]:
            try:
                child_stat = child.stat()
            except OSError:
                continue
            children.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "type": "directory" if child.is_dir() else "file",
                    "mime_type": (
                        None
                        if child.is_dir()
                        else mimetypes.guess_type(child.name)[0]
                        or "application/octet-stream"
                    ),
                    "size": None if child.is_dir() else child_stat.st_size,
                    "modified_at": child_stat.st_mtime,
                    "relative_path": child.name,
                    "children": [],
                    "children_count": 0,
                }
            )
    return {
        "id": f"src_{uuid.uuid4().hex[:12]}",
        "name": path.name,
        "path": str(path),
        "type": "directory" if path.is_dir() else "file",
        "mime_type": (
            None
            if path.is_dir()
            else mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        ),
        "size": None if path.is_dir() else stat.st_size,
        "modified_at": stat.st_mtime,
        "children": children,
        "children_count": len(children),
    }


def add_result_to_library(result_dir: Path) -> None:
    state_path = get_data_dir() / "workspace_sources.json"
    state = {"sources": [], "selected_paths": [], "expanded_paths": []}
    if state_path.exists():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state.update(raw)
        except Exception:
            pass

    result_path = str(result_dir.resolve())
    existing_sources = [
        source
        for source in state.get("sources", [])
        if isinstance(source, dict) and str(source.get("path")) != result_path
    ]
    state["sources"] = [_source_descriptor(result_dir), *existing_sources][:50]
    selected = [
        path
        for path in state.get("selected_paths", [])
        if isinstance(path, str) and path != result_path
    ]
    state["selected_paths"] = [result_path, *selected]
    state["expanded_paths"] = [
        path
        for path in state.get("expanded_paths", [])
        if isinstance(path, str)
    ][:500]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
