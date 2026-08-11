"""
Agent Runner for handling streaming agent execution.

Following CoPaw's Runner pattern for SSE-based streaming responses.
"""

import asyncio
import json
import logging
import mimetypes
import re
from dataclasses import replace
from pathlib import Path
from typing import AsyncGenerator, Optional, Callable, Any, Dict, List, Mapping

from open_agent.app.runner.models import (
    ChatSpec, Message, AgentRequest, AgentEvent
)
from open_agent.app.runner.manager import ChatManager, get_chat_manager
from open_agent.app.runner.file_parser import MAX_FILE_BYTES, attachment_to_context, parse_file_bytes
from open_agent.app.runner.context_compaction import (
    COMPACTION_META_KEY,
    COMPACTION_SUMMARY_PREFIX,
    ContextCompactor,
    build_effective_history,
)
from open_agent.schema import Message as AgentMessage

logger = logging.getLogger(__name__)

WORKSPACE_MAX_SELECTED_FILES = 20
WORKSPACE_MAX_CONTEXT_CHARS = 60000
AGENT_HISTORY_MAX_MESSAGES = 80
WEB_SEARCH_CONTEXT_MAX_CHARS = 12000
WEB_SEARCH_QUERY_MAX_CHARS = 500


class AgentRunner:
    """
    Handles agent execution with streaming response support.
    
    This class bridges the FastAPI routes with the Agent system,
    providing SSE-based streaming responses following CoPaw's pattern.
    """
    
    def __init__(self):
        self._chat_manager: Optional[ChatManager] = None
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._active_agents: Dict[str, Any] = {}
        self._active_cancel_events: Dict[str, asyncio.Event] = {}
    
    def set_chat_manager(self, chat_manager: ChatManager):
        """Set the chat manager instance"""
        self._chat_manager = chat_manager
    
    @property
    def chat_manager(self) -> ChatManager:
        """Get the chat manager"""
        if self._chat_manager is None:
            self._chat_manager = get_chat_manager()
        return self._chat_manager

    def _extract_user_input(
        self,
        request: AgentRequest,
    ) -> tuple[str, str | List[Dict[str, Any]], str]:
        """Extract display text, model content, and modality from the last message."""
        if not request.messages:
            return "", "", "text"

        last_msg = request.messages[-1]
        if isinstance(last_msg, dict):
            content = last_msg.get("content", "")
            attachments = last_msg.get("attachments", [])
        else:
            content = getattr(last_msg, "content", "")
            attachments = getattr(last_msg, "attachments", [])

        if isinstance(content, list):
            display_text = self._display_text_from_blocks(content)
            modality = "vision" if self._contains_image_block(content) else "text"
            return display_text or "[image]", content, modality

        text = str(content or "")
        file_contexts: List[str] = []
        file_names: List[str] = []
        image_blocks: List[Dict[str, Any]] = []
        has_image = False
        if isinstance(attachments, list):
            for attachment in attachments:
                image_block = self._attachment_to_image_block(attachment)
                if image_block:
                    has_image = True
                    image_blocks.append(image_block)
                    continue

                file_context = attachment_to_context(attachment)
                if file_context:
                    file_contexts.append(file_context)
                    if isinstance(attachment, dict):
                        file_names.append(str(attachment.get("name") or "file"))

        workspace_context = self._workspace_context(request)
        if workspace_context:
            file_contexts.append(workspace_context)

        model_text = "\n".join(part for part in [text, *file_contexts] if part).strip()
        blocks: List[Dict[str, Any]] = []
        if model_text:
            blocks.append({"type": "text", "text": model_text})
        blocks.extend(image_blocks)

        display_text = text
        if not display_text and file_names:
            display_text = "已上传文件：" + "、".join(file_names[:3])

        if has_image:
            return display_text or "[image]", blocks, "vision"

        return display_text, model_text or text, "text"

    def _workspace_context(self, request: AgentRequest) -> str:
        sources = request.meta.get("workspace_sources") or []
        if not isinstance(sources, list) or not sources:
            return ""

        selected_paths = request.meta.get("selected_workspace_paths") or []
        selected = {str(path) for path in selected_paths if path}
        source_index = self._workspace_index(sources)

        if not selected:
            return (
                "\n\n[资料库]\n"
                "用户当前挂载了以下资料库来源，但没有勾选具体文件或目录。\n"
                "当用户的问题明确需要资料库资料时，请优先根据这些路径使用可用工具读取或检索相关内容；"
                "如果问题与资料库无关，不要主动展开读取。\n"
                "注意：这里的“资料库”是主页左侧的参考资料来源，不是设置里的运行工作目录。\n"
                f"{source_index}"
            )

        parts = [
            "\n\n[资料库已选来源]",
            "用户勾选了以下资料库来源。请把这些资料作为本轮对话的重要上下文。",
            "注意：这里的“资料库”是主页左侧的参考资料来源，不是设置里的运行工作目录。",
            "已选路径：",
            *[f"- {path}" for path in sorted(selected)],
            "",
        ]
        file_budget = {"count": WORKSPACE_MAX_SELECTED_FILES}
        for path in sorted(selected):
            node = self._workspace_node_by_path(sources, path)
            if (isinstance(node, dict) and node.get("type") == "web") or self._is_web_url(path):
                parts.append(self._workspace_web_context(node if isinstance(node, dict) else {"path": path}))
            else:
                parts.append(self._workspace_path_context(Path(path), file_budget))

        context = "\n".join(part for part in parts if part)
        if len(context) > WORKSPACE_MAX_CONTEXT_CHARS:
            context = context[:WORKSPACE_MAX_CONTEXT_CHARS] + "\n\n[资料库内容过长，已截断]"
        return context

    def _workspace_index(self, sources: List[Any], level: int = 0, limit: int = 80) -> str:
        lines: List[str] = []

        def visit(nodes: List[Any], depth: int) -> None:
            for node in nodes:
                if len(lines) >= limit or not isinstance(node, dict):
                    return
                node_type = node.get("type") or "file"
                marker = self._workspace_source_marker(node_type)
                path = node.get("path") or node.get("name") or ""
                lines.append(f"{'  ' * depth}- [{marker}] {path}")
                children = node.get("children") or []
                if node_type == "directory" and isinstance(children, list):
                    visit(children, depth + 1)

        visit(sources, level)
        if len(lines) >= limit:
            lines.append(f"...（仅展示前 {limit} 项）")
        return "\n".join(lines)

    def _workspace_source_marker(self, source_type: str) -> str:
        if source_type == "directory":
            return "目录"
        if source_type == "web":
            return "网页"
        return "文件"

    def _workspace_node_by_path(self, sources: List[Any], path: str) -> Optional[Dict[str, Any]]:
        def visit(nodes: List[Any]) -> Optional[Dict[str, Any]]:
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if str(node.get("path") or "") == path:
                    return node
                children = node.get("children") or []
                if isinstance(children, list):
                    found = visit(children)
                    if found:
                        return found
            return None

        return visit(sources)

    def _is_web_url(self, value: str) -> bool:
        normalized = str(value or "").lower()
        return normalized.startswith("http://") or normalized.startswith("https://")

    def _workspace_web_context(self, node: Dict[str, Any]) -> str:
        url = str(node.get("path") or node.get("url") or "").strip()
        name = str(node.get("name") or url or "Web 来源")
        return (
            "\n[已选网页来源]\n"
            f"名称：{name}\n"
            f"地址：{url}\n"
            "说明：这是用户添加到资料库的 Web 地址。需要网页正文时，优先使用可用的浏览、检索或网页读取工具打开该地址。"
        )

    def _workspace_path_context(self, path: Path, file_budget: Dict[str, int]) -> str:
        try:
            if not path.exists():
                return f"\n[来源不可用]\n路径：{path}\n原因：路径不存在"
            if path.is_file():
                return self._workspace_file_context(path, file_budget)
            if path.is_dir():
                lines = [f"\n[已选目录]\n路径：{path}", "目录内容："]
                files = []
                for child in path.rglob("*"):
                    if child.is_file():
                        files.append(child)
                    if len(files) >= WORKSPACE_MAX_SELECTED_FILES:
                        break
                for child in files[:WORKSPACE_MAX_SELECTED_FILES]:
                    try:
                        lines.append(f"- {child.relative_to(path)}")
                    except ValueError:
                        lines.append(f"- {child}")
                lines.append("")
                for child in files:
                    if file_budget["count"] <= 0:
                        lines.append("[已达到本轮资料库文件解析上限]")
                        break
                    lines.append(self._workspace_file_context(child, file_budget))
                return "\n".join(lines)
            return f"\n[来源不可用]\n路径：{path}\n原因：不是文件或目录"
        except Exception as exc:
            return f"\n[来源读取失败]\n路径：{path}\n错误：{exc}"

    def _workspace_file_context(self, path: Path, file_budget: Dict[str, int]) -> str:
        if file_budget["count"] <= 0:
            return ""
        file_budget["count"] -= 1

        try:
            stat = path.stat()
            mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if stat.st_size > MAX_FILE_BYTES:
                return (
                    f"\n[已选文件]\n路径：{path}\n文件类型：{mime_type}\n"
                    f"内容：文件超过 {MAX_FILE_BYTES // 1024 // 1024}MB，本轮未解析。"
                )
            raw = path.read_bytes()
            text = parse_file_bytes(path.name, mime_type, raw)
            return (
                f"\n[已选文件]\n"
                f"路径：{path}\n"
                f"文件类型：{mime_type}\n"
                f"内容：\n{text.strip() or '未提取到可用文本。'}"
            )
        except Exception as exc:
            return f"\n[文件读取失败]\n路径：{path}\n错误：{exc}"

    def _is_workspace_listing_request(self, text: str, request: AgentRequest) -> bool:
        sources = request.meta.get("workspace_sources") or []
        selected_paths = request.meta.get("selected_workspace_paths") or []
        if not isinstance(sources, list):
            sources = []
        if not isinstance(selected_paths, list):
            selected_paths = []
        if not sources and not selected_paths:
            return False

        normalized = (text or "").lower()
        library_terms = ("资料库", "资料", "来源", "文件", "目录", "文件夹", "选中", "勾选", "library", "workspace", "selected")
        list_terms = ("有什么", "有哪些", "列出", "查看", "内容", "清单", "包含", "list", "ls", "show")
        if selected_paths:
            selected_terms = ("选", "勾", "文件", "目录", "文件夹", "selected")
            selected_list_terms = ("哪些", "有什么", "列", "清单", "list", "show")
            if any(term in normalized for term in selected_terms) and any(
                term in normalized for term in selected_list_terms
            ):
                return True
        return any(term in normalized for term in library_terms) and any(
            term in normalized for term in list_terms
        )

    def _workspace_listing_answer(self, request: AgentRequest, limit: int = 100) -> str:
        sources = request.meta.get("workspace_sources") or []
        selected_paths = request.meta.get("selected_workspace_paths") or []
        selected = [str(path) for path in selected_paths if path] if isinstance(selected_paths, list) else []
        if selected:
            return self._selected_workspace_listing_answer(selected, limit=limit)

        entries: List[Dict[str, Any]] = []

        def visit(node: Any, root_name: str, depth: int = 0) -> None:
            if len(entries) >= 500 or not isinstance(node, dict):
                return
            node_type = str(node.get("type") or "file")
            path = str(node.get("path") or node.get("name") or "")
            name = str(node.get("relative_path") or node.get("name") or path)
            modified_at = float(node.get("modified_at") or 0)
            if not modified_at and path:
                try:
                    modified_at = Path(path).stat().st_mtime
                except OSError:
                    modified_at = 0
            entries.append(
                {
                    "name": name,
                    "path": path,
                    "type": node_type,
                    "root": root_name,
                    "depth": depth,
                    "modified_at": modified_at,
                    "children_count": int(node.get("children_count") or 0),
                }
            )
            children = node.get("children") or []
            if isinstance(children, list):
                for child in children:
                    visit(child, root_name, depth + 1)

        for source in sources:
            if not isinstance(source, dict):
                continue
            visit(source, str(source.get("name") or source.get("path") or "资料来源"))

        total = len(entries)
        entries.sort(key=lambda item: (item["modified_at"], item["type"] == "file"), reverse=True)
        visible = entries[:limit]

        lines = [
            f"资料库当前有 {len(sources)} 个挂载来源，已索引 {total} 项。",
            f"下面先列出最近更新的前 {min(limit, total)} 项：",
            "",
        ]
        for item in visible:
            marker = self._workspace_source_marker(item["type"])
            suffix = ""
            if item["type"] == "directory" and item["children_count"]:
                suffix = f"（包含 {item['children_count']} 项）"
            lines.append(f"- [{marker}] {item['name']}{suffix}")

        if total > limit:
            lines.append("")
            lines.append(f"还有 {total - limit} 项未展开显示。你可以让我按目录、文件类型或关键词继续筛选。")
        return "\n".join(lines)

    def _selected_workspace_listing_answer(self, selected_paths: List[str], limit: int = 100) -> str:
        lines = [
            f"你当前勾选了 {len(selected_paths)} 个路径：",
            "",
        ]
        shown = 0

        for raw_path in sorted(selected_paths):
            path = Path(raw_path)
            if not path.exists():
                lines.append(f"- [不可用] {raw_path}（路径不存在）")
                continue

            if path.is_file():
                lines.append(f"- [文件] {path.name}")
                lines.append(f"  路径：{path}")
                shown += 1
                continue

            if not path.is_dir():
                lines.append(f"- [不可用] {path}（不是文件或目录）")
                continue

            files = []
            for child in path.rglob("*"):
                if child.is_file():
                    files.append(child)
                if len(files) >= limit:
                    break

            lines.append(f"- [目录] {path.name}（包含 {len(files)} 个文件，最多显示 {limit} 个）")
            lines.append(f"  路径：{path}")
            for child in files[:limit]:
                try:
                    rel = child.relative_to(path)
                except ValueError:
                    rel = child
                lines.append(f"  - {rel}")
                shown += 1
            if len(files) >= limit:
                lines.append("  - ...（文件较多，已截断）")

        if shown == 0:
            lines.append("没有找到可列出的文件。")
        return "\n".join(lines)

    def _attachment_to_image_block(self, attachment: Any) -> Optional[Dict[str, Any]]:
        """Convert a frontend attachment into an Anthropic-style image block."""
        if not isinstance(attachment, dict):
            return None

        media_type = (
            attachment.get("mime_type")
            or attachment.get("mimeType")
            or attachment.get("type")
            or "image/png"
        )
        data = attachment.get("data") or attachment.get("base64") or ""
        source = attachment.get("source")
        if isinstance(source, dict):
            media_type = source.get("media_type") or source.get("mediaType") or media_type
            data = source.get("data") or data

        if not str(media_type).startswith("image/") or not data:
            return None

        data = str(data)
        if data.startswith("data:"):
            header, _, payload = data.partition(",")
            if ";base64" in header:
                media_type = header[5:].split(";", 1)[0] or media_type
                data = payload

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            },
        }

    def _display_text_from_blocks(self, blocks: List[Any]) -> str:
        texts = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                texts.append(str(block.get("text")))
        return "\n".join(texts).strip()

    def _contains_image_block(self, blocks: List[Any]) -> bool:
        return any(isinstance(block, dict) and block.get("type") == "image" for block in blocks)

    def _has_content(self, content: str | List[Dict[str, Any]]) -> bool:
        if isinstance(content, str):
            return bool(content.strip())
        return bool(content)

    def _looks_like_web_search_request(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False

        search_terms = (
            "联网",
            "搜索",
            "网上",
            "查一下",
            "查下",
            "帮我找",
            "找到",
            "原地址",
            "原文",
            "原链接",
            "链接",
            "网址",
            "来源",
            "出处",
            "报道",
            "新闻",
            "最新",
            "site:",
            "http://",
            "https://",
        )
        return any(term in normalized for term in search_terms)

    def _build_web_search_query(self, text: str) -> str:
        query = re.sub(r"\s+", " ", (text or "").strip())
        if len(query) <= WEB_SEARCH_QUERY_MAX_CHARS:
            return query

        title_match = re.match(r"^([^，。！？!?]{8,120})", query)
        if title_match:
            return title_match.group(1).strip()
        return query[:WEB_SEARCH_QUERY_MAX_CHARS].strip()

    async def _prefetch_web_search_context(self, text: str) -> str:
        if not self._looks_like_web_search_request(text):
            return ""

        query = self._build_web_search_query(text)
        if not query:
            return ""

        try:
            from open_agent.tools.web_search import web_search

            loop = asyncio.get_event_loop()
            results, backend = await loop.run_in_executor(
                None,
                lambda: web_search(query, 8),
            )
        except Exception as exc:
            logger.warning("Web search prefetch failed: %s", exc)
            return (
                "\n\n[联网搜索预取失败]\n"
                f"搜索词：{query}\n"
                f"错误：{exc}\n"
                "请优先尝试继续调用 web_search 或 web_browse 工具完成用户的联网查询。"
            )

        if not results:
            return (
                "\n\n[联网搜索预取结果]\n"
                f"搜索词：{query}\n"
                f"后端：{backend}\n"
                "未找到候选结果。请尝试继续调用 web_search 更换关键词，或明确说明未检索到可靠来源。"
            )

        lines = [
            "\n\n[联网搜索预取结果]",
            "用户问题明显需要联网核验。下面是 OpenAgentSeal 预先搜索到的候选结果；回答时请优先基于这些结果，并保留可点击链接。若结果不充分，请继续调用 web_search 或 web_browse。",
            f"搜索词：{query}",
            f"后端：{backend}",
            "",
        ]
        for index, item in enumerate(results[:8], 1):
            title = str(item.get("title") or "无标题").strip()
            link = str(item.get("link") or item.get("url") or "").strip()
            snippet = str(item.get("snippet") or item.get("description") or "").strip()
            lines.append(f"{index}. {title}")
            if link:
                lines.append(f"   URL: {link}")
            if snippet:
                lines.append(f"   摘要: {snippet}")

        context = "\n".join(lines)
        if len(context) > WEB_SEARCH_CONTEXT_MAX_CHARS:
            context = context[:WEB_SEARCH_CONTEXT_MAX_CHARS] + "\n\n[联网搜索预取结果已截断]"
        return context

    def _runtime_turn_metadata(
        self,
        request: AgentRequest,
        *,
        agent_id: str,
        profile_id: str,
        tool_access_mode: str,
        memory_references: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        selected_paths = request.meta.get("selected_workspace_paths") or []
        references: List[Dict[str, Any]] = []
        remaining = WORKSPACE_MAX_SELECTED_FILES
        seen: set[str] = set()

        for raw_path in selected_paths if isinstance(selected_paths, list) else []:
            value = str(raw_path or "").strip()
            if not value:
                continue
            if self._is_web_url(value):
                if value not in seen:
                    seen.add(value)
                    references.append({"kind": "web", "name": value, "path": value, "root": value})
                continue

            path = Path(value)
            candidates: List[Path] = []
            try:
                if path.is_file():
                    candidates = [path]
                elif path.is_dir():
                    candidates = [child for child in path.rglob("*") if child.is_file()]
            except OSError:
                candidates = []

            for candidate in candidates:
                if remaining <= 0:
                    break
                candidate_path = str(candidate)
                if candidate_path in seen:
                    continue
                try:
                    modified_at = candidate.stat().st_mtime
                except OSError:
                    continue
                seen.add(candidate_path)
                remaining -= 1
                references.append({
                    "kind": "file",
                    "name": candidate.name,
                    "path": candidate_path,
                    "root": value,
                    "modified_at": modified_at,
                })

        attachments: List[Dict[str, Any]] = []
        if request.messages:
            last_message = request.messages[-1]
            raw_attachments = (
                last_message.get("attachments")
                if isinstance(last_message, dict)
                else getattr(last_message, "attachments", None)
            )
            for attachment in raw_attachments if isinstance(raw_attachments, list) else []:
                if not isinstance(attachment, dict):
                    continue
                name = str(attachment.get("name") or "attachment")
                attachments.append({
                    "kind": "attachment",
                    "name": name,
                    "path": name,
                    "mime_type": str(attachment.get("mime_type") or ""),
                    "size": int(attachment.get("size") or 0),
                })

        metadata = {
            "agent_id": agent_id,
            "profile_id": profile_id,
            "tool_access_mode": tool_access_mode,
            "selected_workspace_paths": [str(path) for path in selected_paths if path]
            if isinstance(selected_paths, list)
            else [],
            "workspace_references": references,
            "attachments": attachments,
            "memory_references": memory_references or [],
        }
        source_event_key = request.meta.get("source_event_key")
        if source_event_key is not None:
            if not isinstance(source_event_key, str) or not source_event_key.strip():
                raise ValueError("source_event_key must be a non-empty string")
            metadata["source_event_key"] = source_event_key
        return metadata

    def _recall_memory_context(
        self,
        query: str,
        injected_memory_ids: set[int | str],
    ) -> tuple[str, List[Dict[str, Any]]]:
        from open_agent.memory_manager import get_memory_manager

        try:
            memories = get_memory_manager().recall(query=query, limit=8)
        except Exception:
            logger.warning("Memory recall failed for the current turn", exc_info=True)
            return "", []

        seen = {str(memory_id) for memory_id in injected_memory_ids}
        references: List[Dict[str, Any]] = []
        context_lines: List[str] = []
        for memory in memories:
            memory_id = str(getattr(memory, "id", ""))
            content = str(getattr(memory, "content", "")).strip()
            if not memory_id or not content or memory_id in seen:
                continue
            seen.add(memory_id)
            preview = content[:1000]
            references.append({
                "id": getattr(memory, "id", memory_id),
                "category": str(getattr(memory, "category", "general")),
                "importance": str(getattr(memory, "importance", "normal")),
                "content": preview,
            })
            context_lines.append(f"- [memory:{memory_id}] {preview}")
            if len(references) >= 5:
                break

        if not references:
            return "", []
        context = "\n\n## Recalled Memories\nUse these only when relevant to the current request:\n" + "\n".join(context_lines)
        return context, references

    def _append_context_to_agent_content(
        self,
        content: str | List[Dict[str, Any]],
        context: str,
    ) -> str | List[Dict[str, Any]]:
        if not context:
            return content

        if isinstance(content, list):
            blocks = list(content)
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = f"{block.get('text') or ''}{context}"
                    return blocks
            return [{"type": "text", "text": context.strip()}, *blocks]

        return f"{content}{context}"

    def _content_to_agent_text(self, content: Any) -> str | List[Dict[str, Any]]:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        text_parts.append(str(text))
                    continue
                text = getattr(item, "text", None) or getattr(item, "content", None)
                if text:
                    text_parts.append(str(text))
            return "\n".join(text_parts).strip()
        return str(content or "")

    def _restore_agent_history(
        self,
        agent: Any,
        session_id: str,
        chat_manager: ChatManager | None = None,
        compaction_state: dict[str, Any] | None = None,
        auto_compaction_enabled: bool = False,
        fallback_recent_only: bool = False,
        runtime_events: list[dict[str, Any]] | None = None,
    ) -> None:
        chat_manager = chat_manager or self.chat_manager
        system_content = getattr(agent, "system_prompt", "")
        if getattr(agent, "messages", None):
            first_message = agent.messages[0]
            if getattr(first_message, "role", "") == "system":
                system_content = first_message.content

        restored: List[AgentMessage] = []
        if system_content:
            restored.append(AgentMessage(role="system", content=system_content))

        persisted_messages = chat_manager.get_messages(session_id)
        if auto_compaction_enabled:
            effective_history = build_effective_history(
                persisted_messages,
                compaction_state,
            )
            if fallback_recent_only and len(effective_history) > AGENT_HISTORY_MAX_MESSAGES:
                if (
                    effective_history
                    and isinstance(effective_history[0].content, str)
                    and effective_history[0].content.startswith(
                        COMPACTION_SUMMARY_PREFIX
                    )
                ):
                    effective_history = [
                        effective_history[0],
                        *effective_history[-AGENT_HISTORY_MAX_MESSAGES:],
                    ]
                else:
                    effective_history = effective_history[-AGENT_HISTORY_MAX_MESSAGES:]
            restored.extend(effective_history)
        else:
            for stored in persisted_messages[-AGENT_HISTORY_MAX_MESSAGES:]:
                if stored.role not in {"user", "assistant"}:
                    continue
                content = self._content_to_agent_text(stored.content)
                if isinstance(content, str) and not content.strip():
                    continue
                restored.append(AgentMessage(role=stored.role, content=content))

        restored.extend(
            self._recover_agent_messages_from_runtime_events(
                runtime_events or [],
                restored,
            )
        )
        agent.messages = restored or [AgentMessage(role="system", content=system_content or "")]

    def _recover_agent_messages_from_runtime_events(
        self,
        runtime_events: list[dict[str, Any]],
        restored_messages: list[AgentMessage],
    ) -> list[AgentMessage]:
        if not runtime_events:
            return []

        existing_assistant_texts = {
            str(message.content)
            for message in restored_messages
            if getattr(message, "role", "") == "assistant" and message.content
        }
        chunks: list[str] = []
        final_content = ""
        for event in runtime_events:
            event_type = str(event.get("event_type") or "").strip()
            payload = event.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            content = payload.get("content")
            if event_type == "complete" and content:
                final_content = str(content)
            elif event_type in {"message", "assistant", "content_delta"} and content:
                chunks.append(str(content))
            elif event_type == "error" and payload.get("error"):
                final_content = f"Error: {payload.get('error')}"

        recovered_content = final_content or "".join(chunks)
        if not recovered_content.strip() or recovered_content in existing_assistant_texts:
            return []
        return [AgentMessage(role="assistant", content=recovered_content)]

    def _latest_runtime_events_for_session(
        self,
        control_plane: Any,
        session_id: str,
    ) -> list[dict[str, Any]]:
        runtime_thread = control_plane.get_runtime_thread_by_session(session_id)
        if runtime_thread is None:
            return []
        runtime_turns = control_plane.list_runtime_turns(
            runtime_thread["thread_id"],
            limit=1,
        )
        if not runtime_turns:
            return []
        latest_turn_id = runtime_turns[0]["turn_id"]
        return [
            event
            for event in control_plane.list_runtime_events(runtime_thread["thread_id"])
            if event.get("turn_id") == latest_turn_id
        ]
    
    async def run_stream(
        self,
        request: AgentRequest,
        *,
        runtime_turn: Mapping[str, Any] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Stream through the one existing Agent loop, optionally resuming a durable turn."""
        async for event in self.process_message(request, runtime_turn=runtime_turn):
            yield event

    async def process_message(
        self,
        request: AgentRequest,
        *,
        runtime_turn: Mapping[str, Any] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        Process a message through the agent with streaming events.
        
        Yields AgentEvent objects for SSE streaming.
        """
        session_id = request.session_id
        user_id = request.user_id
        requested_tool_access_mode = "full" if request.meta.get("tool_access_mode") == "full" else "default"
        tool_access_mode = requested_tool_access_mode
        profile_id = str(request.meta.get("profile_id") or "main")
        manager_profile_id = None if profile_id == "main" else profile_id
        chat_manager = get_chat_manager(manager_profile_id)
        
        # Get or create chat
        chat = await chat_manager.get_or_create_chat(
            session_id=session_id,
            user_id=user_id,
            channel="web",
        )
        
        # Get agent from user_config based on session_id
        try:
            from open_agent.user_config import get_user_config
            from open_agent.agent_profiles import get_agent_profile_manager
            config_manager = get_user_config()
            profile_manager = get_agent_profile_manager()
        except ImportError:
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error="Agent config not available",
                status="error",
            )
            return

        user_content, agent_user_content, input_modality = self._extract_user_input(request)
        if not self._has_content(agent_user_content):
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error="No message content provided",
                status="error",
            )
            return

        if runtime_turn is None and self._is_workspace_listing_request(user_content, request):
            answer = self._workspace_listing_answer(request)
            chat_manager.add_message(session_id, Message(role="user", content=user_content))
            chat_manager.add_message(session_id, Message(role="assistant", content=answer))
            yield AgentEvent(event="run_start", session_id=session_id, status="running")
            yield AgentEvent(event="complete", session_id=session_id, status="idle", content=answer)
            await chat_manager.update_chat(chat)
            return
        
        agent_config = profile_manager.get_agent_config(manager_profile_id)
        if not agent_config:
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error=f"Agent profile not found: {profile_id}",
                status="error",
            )
            return
        if manager_profile_id and not getattr(agent_config, "enabled", True):
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error=f"Agent profile is disabled: {profile_id}",
                status="error",
            )
            return
        if requested_tool_access_mode != "full":
            tool_access_mode = "full" if getattr(agent_config, "permission_mode", "default") == "full" else "default"

        routed_model_id = config_manager.resolve_smart_model_id(input_modality, agent_config.model_id)
        if routed_model_id and routed_model_id != agent_config.model_id:
            logger.info(
                "Smart routing selected model_id=%s for modality=%s (agent default=%s)",
                routed_model_id,
                input_modality,
                agent_config.model_id,
            )
            agent_config = replace(agent_config, model_id=routed_model_id)

        agent_id = agent_config.id
        agent = self._create_agent_from_config(
            agent_config,
            profile_id=manager_profile_id,
            session_id=session_id,
        )

        if not agent:
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error="Failed to create agent",
                status="error",
            )
            return

        agent.session_id = session_id
        agent.profile_id = profile_id
        agent.tool_access_mode = tool_access_mode
        from open_agent.control_plane import get_control_plane

        agent_home = profile_manager.get_agent_home(manager_profile_id)
        control_plane = get_control_plane(agent_home)
        runtime_thread = control_plane.get_runtime_thread_by_session(session_id)
        if runtime_turn is not None:
            supplied_turn_id = str(runtime_turn.get("turn_id") or "")
            supplied_thread_id = str(runtime_turn.get("thread_id") or "")
            if not supplied_turn_id or not supplied_thread_id:
                raise ValueError("runtime_turn must include turn_id and thread_id")
            stored_turn = control_plane._get_conn().execute(
                "SELECT * FROM runtime_turns WHERE turn_id = ?",
                (supplied_turn_id,),
            ).fetchone()
            supplied_thread = control_plane.get_runtime_thread(supplied_thread_id)
            if (
                stored_turn is None
                or supplied_thread is None
                or stored_turn["thread_id"] != supplied_thread_id
                or stored_turn["session_id"] != session_id
                or supplied_thread["session_id"] != session_id
            ):
                raise ValueError("runtime_turn does not belong to the requested session")
            runtime_turn = control_plane._row_to_dict(stored_turn)
            runtime_thread = supplied_thread
        recovery_runtime_events = self._latest_runtime_events_for_session(
            control_plane,
            session_id,
        )
        from open_agent.user_config import (
            DEFAULT_CONTEXT_WINDOW,
            model_auto_compact_token_limit,
            resolve_model_context_window,
        )

        app_settings = config_manager.get_settings()
        active_model_config = (
            config_manager.get_model(agent_config.model_id)
            or config_manager.get_default_model()
        )
        model_context_window, model_context_source = resolve_model_context_window(
            active_model_config,
            getattr(app_settings, "context_compaction_token_limit", DEFAULT_CONTEXT_WINDOW),
        )
        auto_compact_token_limit = model_auto_compact_token_limit(
            model_context_window
        )
        chat.meta["context_model_id"] = (
            active_model_config.id if active_model_config else agent_config.model_id
        )
        chat.meta["context_window"] = model_context_window
        chat.meta["context_window_source"] = model_context_source
        chat.meta["auto_compact_token_limit"] = auto_compact_token_limit
        adaptive_context_enabled = bool(
            getattr(app_settings, "auto_context_compaction", True)
        )
        trigger_token_limit = (
            auto_compact_token_limit
            if adaptive_context_enabled
            else model_context_window
        )
        compaction_state = chat.meta.get(COMPACTION_META_KEY)
        compaction_result = None
        compaction_failed = False
        try:
            compactor = ContextCompactor(
                token_limit=auto_compact_token_limit,
                trigger_token_limit=trigger_token_limit,
                session_id=session_id,
                profile_id=profile_id,
            )
            preview_messages = [
                *chat_manager.get_messages(session_id),
                Message(role="user", content=user_content),
            ]
            for _ in range(3):
                compaction_result = await compactor.compact_if_needed(
                    preview_messages,
                    agent.llm,
                    compaction_state,
                )
                if not compaction_result:
                    break
                compaction_state = compaction_result.state
                chat.meta[COMPACTION_META_KEY] = compaction_state
                await chat_manager.update_chat(chat)
                logger.info(
                    "Created reversible context block for session %s: %s (%d -> %d tokens, %d messages)",
                    session_id,
                    compaction_result.ref_id,
                    compaction_result.before_tokens,
                    compaction_result.after_tokens,
                    compaction_result.compacted_messages,
                )
                if compaction_result.after_tokens < auto_compact_token_limit:
                    break
        except Exception:
            compaction_failed = True
            logger.warning(
                "Context compaction failed for session %s; continuing with current history",
                session_id,
                exc_info=True,
            )
        self._restore_agent_history(
            agent,
            session_id,
            chat_manager,
            compaction_state=compaction_state,
            auto_compaction_enabled=True,
            fallback_recent_only=compaction_failed,
            runtime_events=recovery_runtime_events,
        )
        search_context = await self._prefetch_web_search_context(user_content)
        agent_user_content = self._append_context_to_agent_content(agent_user_content, search_context)
        existing_memory_ids = list(chat.meta.get("injected_memory_ids") or [])
        injected_memory_ids = set(existing_memory_ids)
        memory_context, memory_references = self._recall_memory_context(
            user_content,
            injected_memory_ids,
        )
        agent_user_content = self._append_context_to_agent_content(agent_user_content, memory_context)
        if memory_references:
            chat.meta["injected_memory_ids"] = [
                *existing_memory_ids,
                *[reference["id"] for reference in memory_references],
            ][-200:]
            await chat_manager.update_chat(chat)
        
        # Add user message to history
        user_attachments = []
        if request.messages:
            last_request_message = request.messages[-1]
            if isinstance(last_request_message, dict):
                raw_attachments = last_request_message.get("attachments") or []
                if isinstance(raw_attachments, list):
                    user_attachments = raw_attachments
        user_message = Message(role="user", content=user_content, attachments=user_attachments)
        chat_manager.add_message(session_id, user_message)
        
        # Add message to agent
        agent.add_user_message(agent_user_content)

        if runtime_thread is None:
            runtime_thread = control_plane.create_runtime_thread(
                session_id=session_id,
                user_id=user_id,
                title=user_content[:80],
                metadata={"chat_id": chat.id, "source": "runner", "profile_id": profile_id},
            )
        if runtime_turn is None:
            runtime_turn = control_plane.start_runtime_turn(
                runtime_thread["thread_id"],
                user_input=user_content,
                metadata=self._runtime_turn_metadata(
                    request,
                    agent_id=agent_id,
                    profile_id=profile_id,
                    tool_access_mode=tool_access_mode,
                    memory_references=memory_references,
                ),
            )

        def persist_event(event: AgentEvent) -> AgentEvent:
            payload = event.model_dump(exclude_none=True)
            stored = control_plane.append_runtime_event(
                runtime_thread["thread_id"],
                event.event,
                payload=payload,
                turn_id=runtime_turn["turn_id"],
                session_id=session_id,
            )
            return event.model_copy(
                update={
                    "thread_id": runtime_thread["thread_id"],
                    "turn_id": runtime_turn["turn_id"],
                    "seq": stored["seq"],
                    "created_at": stored["created_at"],
                }
            )
        
        # Yield start event
        yield persist_event(AgentEvent(
            event="run_start",
            session_id=session_id,
            status="running",
        ))
        if compaction_result:
            yield persist_event(
                AgentEvent(
                    event="context_compaction",
                    session_id=session_id,
                    status="completed",
                    content=(
                        f"已自动压缩早期上下文："
                        f"{compaction_result.before_tokens} → "
                        f"{compaction_result.after_tokens} tokens"
                    ),
                    result={
                        "ref_id": compaction_result.ref_id,
                        "before_tokens": compaction_result.before_tokens,
                        "after_tokens": compaction_result.after_tokens,
                        "compacted_messages": compaction_result.compacted_messages,
                        "compaction_count": compaction_result.state.get("compaction_count"),
                    },
                )
            )
        
        # Create event collector for status callback
        event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

        stream_response = config_manager.get_settings().stream_response

        async def stream_callback(stream_data: Dict[str, Any]):
            """Convert incremental LLM stream updates into AgentEvents."""
            content = stream_data.get("content")
            if content is None:
                return

            await event_queue.put(
                AgentEvent(
                    event=stream_data.get("event", "message"),
                    session_id=session_id,
                    step=agent.current_step,
                    content=content,
                    status=stream_data.get("status", "streaming"),
                )
            )

        async def status_callback(event_data: Dict[str, Any]):
            """Convert agent status callbacks to AgentEvents"""
            event_type = event_data.get("event", "")
            
            # Debug: Log all events
            logger.info(f"[Runner] Received callback event: {event_type}, data: {event_data}")
            
            event = AgentEvent(
                event=event_type,
                session_id=session_id,
                step=event_data.get("step"),
                content=event_data.get("content"),
                tool_call_id=event_data.get("tool_call_id"),
                tool_name=event_data.get("tool_name"),
                arguments=event_data.get("arguments"),
                result=event_data.get("result"),
                success=event_data.get("success"),
                error=event_data.get("error"),
                status=event_data.get("status"),
                max_steps=event_data.get("max_steps"),
                elapsed=event_data.get("elapsed"),
            )
            await event_queue.put(event)

        # Set callback on agent
        agent.status_callback = status_callback
        agent.llm.stream_callback = stream_callback if stream_response else None

        # Create a task to run the agent
        cancel_event = asyncio.Event()
        agent_task = asyncio.create_task(agent.run(cancel_event))
        self._active_tasks[session_id] = agent_task
        self._active_agents[session_id] = agent
        self._active_cancel_events[session_id] = cancel_event
        
        try:
            # Yield events as they come in, while agent is running
            while not agent_task.done():
                # Check for events with a small timeout
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    yield persist_event(event)
                except asyncio.TimeoutError:
                    # No event available, continue waiting
                    pass
            
            # Agent is done, drain any remaining events
            while not event_queue.empty():
                yield persist_event(await event_queue.get())
            
            # Get the result (this will raise if agent raised an exception)
            result = agent_task.result()
            
            # Get final assistant message
            last_assistant_msg = None
            for msg in reversed(agent.messages):
                if msg.role == "assistant" and msg.content:
                    last_assistant_msg = msg.content
                    break
            
            if last_assistant_msg:
                # Add to history
                assistant_message = Message(role="assistant", content=last_assistant_msg)
                chat_manager.add_message(session_id, assistant_message)
            
            # Yield completion event
            complete_event = persist_event(AgentEvent(
                event="complete",
                session_id=session_id,
                status="idle",
                content=last_assistant_msg,
            ))
            control_plane.complete_runtime_turn(
                runtime_turn["turn_id"],
                status="completed",
                result={"content": last_assistant_msg, "agent_result": str(result)},
            )
            yield complete_event
            
            # Update chat
            await chat_manager.update_chat(chat)
        
        except asyncio.CancelledError:
            agent_task.cancel()
            cancelled_event = persist_event(AgentEvent(
                event="cancelled",
                session_id=session_id,
                status="idle",
            ))
            control_plane.complete_runtime_turn(runtime_turn["turn_id"], status="cancelled")
            yield cancelled_event
        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            error_event = persist_event(AgentEvent(
                event="error",
                session_id=session_id,
                error=str(e),
                status="error",
            ))
            control_plane.complete_runtime_turn(
                runtime_turn["turn_id"],
                status="error",
                error=str(e),
            )
            yield error_event
        finally:
            self._active_tasks.pop(session_id, None)
            self._active_agents.pop(session_id, None)
            self._active_cancel_events.pop(session_id, None)
            agent.status_callback = None
            agent.llm.stream_callback = None
    
    def _create_agent_from_config(self, agent_config, profile_id: str | None = None, session_id: str | None = None):
        """Create agent instance from agent config"""
        try:
            from open_agent.agent import Agent
            from open_agent.llm import LLMClient
            from open_agent.provider_registry import get_provider_registry
            from open_agent.tools.bash_tool import BashTool, BashOutputTool, BashKillTool
            from open_agent.tools.file_tools import ReadTool, WriteTool, EditTool
            from open_agent.tools.note_tool import RecordNoteTool, RecallNotesTool
            from open_agent.tools.choice_tool import AskUserChoiceTool
            from open_agent.tools.context_tool import RetrieveContextTool
            from open_agent.user_config import get_user_config
            from open_agent.agent_profiles import get_agent_profile_manager
            
            # Get model config
            config_manager = get_user_config()
            profile_manager = get_agent_profile_manager()
            agent_home = profile_manager.get_agent_home(profile_id)
            memory_dir = agent_home / "memory"
            workspace_dir = agent_home / "workspace"
            profile_skills_dir = agent_home / "skills"
            profile_mcp_path = agent_home / "mcp.json"
            model_config = None
            
            if agent_config.model_id:
                model_config = config_manager.get_model(agent_config.model_id)
            
            if not model_config:
                model_config = config_manager.get_default_model()
            
            logger.info(f"Creating agent with model: {model_config.name if model_config else 'None'}")
            logger.info(f"Model provider: {model_config.provider if model_config else 'None'}")
            logger.info(f"Model base_url: {model_config.base_url if model_config else 'None'}")
            
            # Create LLM client
            if model_config:
                route = get_provider_registry().resolve_model_config(model_config)
                llm_client = LLMClient(
                    api_key=model_config.api_key,
                    provider=route.llm_provider,
                    api_base=route.api_base,
                    model=route.model,
                )
                logger.info(
                    "LLM client created: provider=%s, model=%s, api_base=%s",
                    route.llm_provider,
                    route.model,
                    route.api_base,
                )
            else:
                # No model configured, return None
                logger.warning("No model configured for agent")
                return None
            
            # Create tools
            tools = [
                BashTool(workspace_dir=str(workspace_dir)),
                BashOutputTool(),
                BashKillTool(),
                ReadTool(workspace_dir=str(workspace_dir)),
                WriteTool(workspace_dir=str(workspace_dir)),
                EditTool(workspace_dir=str(workspace_dir)),
                RecordNoteTool(memory_dir=str(memory_dir)),
                RecallNotesTool(memory_dir=str(memory_dir)),
                AskUserChoiceTool(),
                RetrieveContextTool(),
            ]
            try:
                from open_agent.tools.agent_control_tool import create_agent_control_tools

                can_delegate = profile_id is None or bool(getattr(agent_config, "allow_delegation", False))
                tools.extend(
                    create_agent_control_tools(
                        can_delegate=can_delegate,
                        parent_session_id=session_id,
                        parent_profile_id=profile_id or "main",
                    )
                )
            except Exception as exc:
                logger.warning("Failed to load agent control tools: %s", exc)
            skill_loader = None

            # Web search tools. Keep them available by default; only an explicit
            # config switch should remove the agent's network search capability.
            config_obj = None
            try:
                from open_agent.config import Config
                config_path = Config.get_default_config_path()
                if config_path and config_path.exists():
                    config_obj = Config.from_yaml(config_path)
            except Exception:
                logger.warning("Failed to read config.yaml while loading web search tools", exc_info=True)
            if config_obj is None or config_obj.tools.enable_web_search:
                try:
                    from open_agent.tools.web_search import (
                        WebSearchTool,
                        WebBrowseTool,
                    )
                    tools.append(WebSearchTool())
                    tools.append(WebBrowseTool())
                except Exception:
                    logger.warning("Failed to load web search tools", exc_info=True)

            # Skills tools
            try:
                # Check user settings first (UI toggle), then config.yaml
                user_settings = config_manager.get_settings()
                enable_skills = getattr(user_settings, 'enable_skills', True) if user_settings else True
                if enable_skills and config_obj and config_obj.tools.enable_skills:
                    from open_agent.utils.path_utils import resolve_skills_dir
                    from open_agent.plugins import get_plugin_manager
                    skills_path = profile_skills_dir if profile_id else resolve_skills_dir(config_obj.tools.skills_dir)
                    if skills_path and Path(skills_path).exists():
                        from open_agent.tools.skill_tool import create_skill_tools
                        plugin_manager = get_plugin_manager()
                        extra_roots = plugin_manager.effective_skill_roots()
                        if not profile_id and profile_skills_dir.exists():
                            extra_roots = [
                                {
                                    "path": str(profile_skills_dir),
                                    "source": "profile",
                                    "plugin_name": agent_config.name,
                                },
                                *extra_roots,
                            ]
                        skill_tools, skill_loader = create_skill_tools(
                            str(skills_path),
                            extra_roots=extra_roots,
                            disabled_paths=plugin_manager.disabled_skill_paths(),
                        )
                        if skill_tools:
                            tools.extend(skill_tools)
                            logger.info(f"Loaded {len(skill_tools)} skill tools from {skills_path}")
                    else:
                        logger.warning("Skills enabled but no skills directory was found")
                else:
                    logger.info("Skills disabled by user settings or config")
            except Exception as e:
                logger.error(f"Failed to load skill tools: {e}", exc_info=True)

            # MCP tools
            try:
                if config_obj and config_obj.tools.enable_mcp:
                    from open_agent.config import Config as Cfg
                    if profile_id:
                        mcp_config_path = profile_mcp_path if profile_mcp_path.exists() else None
                    else:
                        mcp_config_path = Cfg.find_config_file(config_obj.tools.mcp_config_path)

                    from open_agent.plugins import get_plugin_manager
                    from open_agent.tools.mcp_loader import load_mcp_tools_from_servers_async

                    raw_mcp_config = {"mcpServers": {}}
                    if mcp_config_path:
                        try:
                            raw_mcp_config = json.loads(Path(mcp_config_path).read_text(encoding="utf-8"))
                        except Exception:
                            raw_mcp_config = {"mcpServers": {}}
                    user_mcp_servers = raw_mcp_config.get("mcpServers", {}) if isinstance(raw_mcp_config, dict) else {}
                    effective_mcp_servers, mcp_warnings = get_plugin_manager().effective_mcp_servers(user_mcp_servers)
                    for warning in mcp_warnings:
                        logger.warning("Plugin MCP skipped: %s", warning)
                    mcp_tools = asyncio.run(load_mcp_tools_from_servers_async(effective_mcp_servers))
                    if mcp_tools:
                        tools.extend(mcp_tools)
                        logger.info(f"Loaded {len(mcp_tools)} MCP tools from effective MCP config")
            except Exception:
                pass
            
            # Get system prompt
            system_prompt = agent_config.system_prompt
            
            # If agent_config doesn't have system_prompt, load from system_prompt.md
            if not system_prompt:
                try:
                    from open_agent.config import Config
                    system_prompt_path = Config.find_config_file("system_prompt.md")
                    if system_prompt_path and system_prompt_path.exists():
                        system_prompt = system_prompt_path.read_text(encoding="utf-8")
                        logger.info(f"Loaded system prompt from: {system_prompt_path}")
                    else:
                        system_prompt = "You are an intelligent assistant that helps users complete various tasks."
                        logger.warning("system_prompt.md not found, using default")
                except Exception as e:
                    logger.error(f"Failed to load system prompt: {e}")
                    system_prompt = "You are an intelligent assistant that helps users complete various tasks."

            if skill_loader:
                skills_metadata = skill_loader.get_skills_metadata_prompt()
                if skills_metadata:
                    if "{SKILLS_METADATA}" in system_prompt:
                        system_prompt = system_prompt.replace("{SKILLS_METADATA}", skills_metadata)
                    else:
                        system_prompt = system_prompt + "\n\n" + skills_metadata
                    logger.info(
                        "Injected %d skills into agent system prompt",
                        len(skill_loader.loaded_skills),
                    )
            else:
                system_prompt = system_prompt.replace("{SKILLS_METADATA}", "")

            try:
                from open_agent.plugins import get_plugin_manager

                plugin_roots = get_plugin_manager().effective_skill_roots()
                if plugin_roots:
                    plugin_names = sorted({root.get("plugin_name", "plugin") for root in plugin_roots})
                    plugins_instructions = (
                        "\n\n<plugins_instructions>\n"
                        "## Plugins\n"
                        "A plugin is a local bundle of skills and MCP servers. Plugins are not invoked directly; "
                        "use the skills and MCP tools they contribute. If a user names a plugin, prefer the "
                        "capabilities associated with that plugin when they are relevant.\n"
                        f"Enabled plugins: {', '.join(plugin_names)}\n"
                        "</plugins_instructions>"
                    )
                    system_prompt += plugins_instructions
            except Exception:
                logger.debug("Failed to inject plugin instructions", exc_info=True)

            system_prompt += (
                "\n\n<context_management>\n"
                "Earlier conversation may appear as reversible compressed context blocks with ctx:// refs. "
                "The original text is stored locally. If a compressed block lacks details needed for an "
                "accurate answer, call retrieve_context(ref_id, query?) to inspect the original text before "
                "answering. Treat compressed context as prior history, never as a new user request.\n"
                "</context_management>"
            )

            agent_kind = "main-agent" if not profile_id else "sub-agent"
            delegation_note = (
                "This agent may delegate work to enabled sub-agent profiles with start_agent_task. "
                if (not profile_id or getattr(agent_config, "allow_delegation", False))
                else "This sub-agent should complete its assigned work directly and must not delegate to other agents. "
            )
            system_prompt += (
                "\n\n<agent_profile>\n"
                f"Agent kind: {agent_kind}\n"
                f"Agent id: {agent_config.id}\n"
                f"Agent name: {agent_config.name}\n"
                f"Isolated home: {agent_home}\n"
                "Memory and session history are isolated to this agent home. "
                "The library/资料库 and global model registry are shared across agents.\n"
                f"{delegation_note}\n"
                "</agent_profile>"
            )
            
            from open_agent.user_config import (
                DEFAULT_CONTEXT_WINDOW,
                model_auto_compact_token_limit,
                resolve_model_context_window,
            )

            model_context_window, _ = resolve_model_context_window(
                model_config,
                getattr(
                    config_manager.get_settings(),
                    "context_compaction_token_limit",
                    DEFAULT_CONTEXT_WINDOW,
                ),
            )

            # Create agent
            agent = Agent(
                llm_client=llm_client,
                system_prompt=system_prompt,
                tools=tools,
                max_steps=agent_config.max_steps if hasattr(agent_config, 'max_steps') and agent_config.max_steps else 100,
                workspace_dir=str(workspace_dir),
                token_limit=model_auto_compact_token_limit(model_context_window),
                auto_compaction_enabled=True,
            )
            
            logger.info(f"Agent created successfully")
            return agent
        except Exception as e:
            logger.error(f"Failed to create agent from config: {e}", exc_info=True)
            return None
    
    async def cancel_session(self, session_id: str) -> bool:
        """Cancel a running session"""
        cancelled = False

        cancel_event = self._active_cancel_events.get(session_id)
        if cancel_event:
            cancel_event.set()
            cancelled = True

        task = self._active_tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            cancelled = True

        agent = self._active_agents.get(session_id)
        if agent and getattr(agent, "cancel_event", None):
            agent.cancel_event.set()
            cancelled = True

        if cancelled:
            return True

        agent_id = self.chat_manager.get_session_agent(session_id)
        if not agent_id:
            return False
        
        try:
            from open_agent.agent_service import get_agent_service
            service = get_agent_service()
            agent = service.get_agent(agent_id)
            
            if agent and hasattr(agent, 'cancel'):
                agent.cancel()
                return True
        except Exception as e:
            logger.error(f"Failed to cancel session: {e}")
        
        return False


# Singleton instance
_runner: Optional[AgentRunner] = None


def get_runner() -> AgentRunner:
    """Get the global AgentRunner instance"""
    global _runner
    if _runner is None:
        _runner = AgentRunner()
    return _runner
