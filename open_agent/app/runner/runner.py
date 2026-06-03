"""
Agent Runner for handling streaming agent execution.

Following CoPaw's Runner pattern for SSE-based streaming responses.
"""

import asyncio
import logging
import mimetypes
from dataclasses import replace
from pathlib import Path
from typing import AsyncGenerator, Optional, Callable, Any, Dict, List

from open_agent.app.runner.models import (
    ChatSpec, Message, AgentRequest, AgentEvent
)
from open_agent.app.runner.manager import ChatManager, get_chat_manager
from open_agent.app.runner.file_parser import MAX_FILE_BYTES, attachment_to_context, parse_file_bytes
from open_agent.schema import Message as AgentMessage

logger = logging.getLogger(__name__)

WORKSPACE_MAX_SELECTED_FILES = 20
WORKSPACE_MAX_CONTEXT_CHARS = 60000
AGENT_HISTORY_MAX_MESSAGES = 80


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
        if not isinstance(sources, list) or not sources or selected_paths:
            return False

        normalized = (text or "").lower()
        library_terms = ("资料库", "资料", "来源", "文件", "目录", "library", "workspace")
        list_terms = ("有什么", "有哪些", "列出", "查看", "内容", "清单", "list", "ls", "show")
        return any(term in normalized for term in library_terms) and any(
            term in normalized for term in list_terms
        )

    def _workspace_listing_answer(self, request: AgentRequest, limit: int = 100) -> str:
        sources = request.meta.get("workspace_sources") or []
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

    def _restore_agent_history(self, agent: Any, session_id: str) -> None:
        system_content = getattr(agent, "system_prompt", "")
        if getattr(agent, "messages", None):
            first_message = agent.messages[0]
            if getattr(first_message, "role", "") == "system":
                system_content = first_message.content

        restored: List[AgentMessage] = []
        if system_content:
            restored.append(AgentMessage(role="system", content=system_content))

        persisted_messages = self.chat_manager.get_messages(session_id)
        for stored in persisted_messages[-AGENT_HISTORY_MAX_MESSAGES:]:
            if stored.role not in {"user", "assistant"}:
                continue
            content = self._content_to_agent_text(stored.content)
            if isinstance(content, str) and not content.strip():
                continue
            restored.append(AgentMessage(role=stored.role, content=content))

        agent.messages = restored or [AgentMessage(role="system", content=system_content or "")]
    
    async def process_message(
        self,
        request: AgentRequest,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        Process a message through the agent with streaming events.
        
        Yields AgentEvent objects for SSE streaming.
        """
        session_id = request.session_id
        user_id = request.user_id
        tool_access_mode = "full" if request.meta.get("tool_access_mode") == "full" else "default"
        
        # Get or create chat
        chat = await self.chat_manager.get_or_create_chat(
            session_id=session_id,
            user_id=user_id,
            channel="web",
        )
        
        # Get agent from user_config based on session_id
        try:
            from open_agent.user_config import get_user_config
            config_manager = get_user_config()
        except ImportError:
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error="User config not available",
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

        if self._is_workspace_listing_request(user_content, request):
            answer = self._workspace_listing_answer(request)
            self.chat_manager.add_message(session_id, Message(role="user", content=user_content))
            self.chat_manager.add_message(session_id, Message(role="assistant", content=answer))
            yield AgentEvent(event="run_start", session_id=session_id, status="running")
            yield AgentEvent(event="complete", session_id=session_id, status="idle", content=answer)
            await self.chat_manager.update_chat(chat)
            return
        
        # Get or create agent for this session
        agent_id = self.chat_manager.get_session_agent(session_id)
        agent = None
        
        # DEBUG: Log session info
        logger.info(f"[DEBUG] session_id: {session_id}")
        logger.info(f"[DEBUG] agent_id from chat_manager: {agent_id}")
        
        # Try to extract agent_id from session_id if not set
        # Session ID format: session_agent_{agentId}_{timestamp}
        # Example: session_agent_agent-1710820800000_1710820800000
        # The agentId can contain various characters including hyphens
        if not agent_id and session_id.startswith("session_agent_"):
            # Remove the prefix "session_agent_" to get the rest
            rest = session_id[len("session_agent_"):]
            # The rest should be: {agentId}_{timestamp}
            # Find the last underscore to separate agentId from timestamp
            last_underscore = rest.rfind("_")
            if last_underscore > 0:
                extracted_agent_id = rest[:last_underscore]
                logger.info(f"[DEBUG] extracted_agent_id: {extracted_agent_id}")
                # Verify this is a valid agent ID
                existing_agent = config_manager.get_agent(extracted_agent_id)
                if existing_agent:
                    agent_id = extracted_agent_id
                    self.chat_manager.set_session_agent(session_id, agent_id)
                    logger.info(f"Extracted agent_id {agent_id} from session_id {session_id}")
                    logger.info(f"Agent config: name={existing_agent.name}, system_prompt={existing_agent.system_prompt[:50] if existing_agent.system_prompt else 'None'}...")
                else:
                    logger.warning(f"Agent {extracted_agent_id} not found in config")
                    # List all available agents
                    all_agents = config_manager.get_all_agents()
                    logger.info(f"Available agents: {[a.id for a in all_agents]}")
            else:
                logger.warning(f"Invalid session_id format: {session_id}, cannot extract agent_id")
        
        session_agent_config = config_manager.get_agent(agent_id) if agent_id else None
        can_reuse_agent = True
        if session_agent_config:
            routed_model_id = config_manager.resolve_smart_model_id(
                input_modality,
                session_agent_config.model_id,
            )
            can_reuse_agent = routed_model_id == session_agent_config.model_id

        if agent_id and can_reuse_agent:
            # Try to get existing agent from AgentService
            try:
                from open_agent.agent_service import get_agent_service
                service = get_agent_service()
                agent = service.get_agent(agent_id)
            except Exception:
                agent = None
        
        if not agent:
            # Get agent config from user_config based on session_id
            # Priority: use the agent_id extracted from session_id
            agent_config = None
            
            # First, try to get config using the agent_id from session
            if agent_id:
                agent_config = config_manager.get_agent(agent_id)
                if agent_config:
                    logger.info(f"Found agent config for agent_id: {agent_id}")
            
            # If not found, fall back to first agent
            if not agent_config:
                agents = config_manager.get_all_agents()
                if agents:
                    agent_config = agents[0]
                    agent_id = agent_config.id
                    logger.info(f"Using first agent: {agent_id}")
                else:
                    # Create default agent config with system prompt
                    from open_agent.user_config import AgentConfig
                    from open_agent.config import Config
                    
                    system_prompt = "You are an intelligent assistant that helps users complete various tasks."
                    try:
                        system_prompt_path = Config.find_config_file("system_prompt.md")
                        if system_prompt_path and system_prompt_path.exists():
                            system_prompt = system_prompt_path.read_text(encoding="utf-8")
                            print(f"[Runner] Loaded system prompt from: {system_prompt_path}")
                        else:
                            print(f"[Runner] system_prompt.md not found, using default")
                    except Exception as e:
                        print(f"[Runner] Failed to load system prompt: {e}")
                    
                    agent_config = AgentConfig.create(
                        name="默认助手",
                        model_id="",
                        system_prompt=system_prompt
                    )
                    config_manager.add_agent(agent_config)
                    agent_id = agent_config.id
                    self.chat_manager.set_session_agent(session_id, agent_id)

            routed_model_id = config_manager.resolve_smart_model_id(
                input_modality,
                agent_config.model_id if agent_config else None,
            )
            if agent_config and routed_model_id and routed_model_id != agent_config.model_id:
                logger.info(
                    "Smart routing selected model_id=%s for modality=%s (agent default=%s)",
                    routed_model_id,
                    input_modality,
                    agent_config.model_id,
                )
                agent_config = replace(agent_config, model_id=routed_model_id)
            
            # Create agent instance from config
            agent = self._create_agent_from_config(agent_config)
        
        if not agent:
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error="Failed to create agent",
                status="error",
            )
            return

        agent.tool_access_mode = tool_access_mode
        self._restore_agent_history(agent, session_id)
        
        # Add user message to history
        user_attachments = []
        if request.messages:
            last_request_message = request.messages[-1]
            if isinstance(last_request_message, dict):
                raw_attachments = last_request_message.get("attachments") or []
                if isinstance(raw_attachments, list):
                    user_attachments = raw_attachments
        user_message = Message(role="user", content=user_content, attachments=user_attachments)
        self.chat_manager.add_message(session_id, user_message)
        
        # Add message to agent
        agent.add_user_message(agent_user_content)

        from open_agent.control_plane import get_control_plane

        control_plane = get_control_plane()
        runtime_thread = control_plane.get_runtime_thread_by_session(session_id)
        if runtime_thread is None:
            runtime_thread = control_plane.create_runtime_thread(
                session_id=session_id,
                user_id=user_id,
                title=user_content[:80],
                metadata={"chat_id": chat.id, "source": "runner"},
            )
        runtime_turn = control_plane.start_runtime_turn(
            runtime_thread["thread_id"],
            user_input=user_content,
            metadata={"agent_id": agent_id, "tool_access_mode": tool_access_mode},
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
                tool_name=event_data.get("tool_name"),
                arguments=event_data.get("arguments"),
                result=event_data.get("result"),
                success=event_data.get("success"),
                error=event_data.get("error"),
                status=event_data.get("status"),
                max_steps=event_data.get("max_steps"),
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
                self.chat_manager.add_message(session_id, assistant_message)
            
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
            await self.chat_manager.update_chat(chat)
        
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
    
    def _create_agent_from_config(self, agent_config):
        """Create agent instance from agent config"""
        try:
            from open_agent.agent import Agent
            from open_agent.llm import LLMClient
            from open_agent.schema import LLMProvider
            from open_agent.tools.bash_tool import BashTool, BashOutputTool, BashKillTool
            from open_agent.tools.file_tools import ReadTool, WriteTool, EditTool
            from open_agent.tools.note_tool import RecordNoteTool, RecallNotesTool
            from open_agent.tools.choice_tool import AskUserChoiceTool
            from open_agent.user_config import get_user_config
            
            # Get model config
            config_manager = get_user_config()
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
                # Determine provider type based on provider_type field first, then fallback to base_url detection
                provider_type_str = model_config.provider_type.lower() if model_config.provider_type else ""
                base_url_lower = (model_config.base_url or "").lower()
                
                # Use ANTHROPIC provider for:
                # - provider_type is "anthropic"
                # - base_url contains "anthropic"
                if provider_type_str == "anthropic" or "anthropic" in base_url_lower:
                    provider_type = LLMProvider.ANTHROPIC
                    logger.info(f"Using ANTHROPIC provider (detected from provider_type={provider_type_str} or base_url={base_url_lower})")
                else:
                    provider_type = LLMProvider.OPENAI
                    logger.info(f"Using OPENAI provider (provider_type={provider_type_str})")
                
                llm_client = LLMClient(
                    api_key=model_config.api_key,
                    provider=provider_type,
                    api_base=model_config.base_url or "",
                    model=model_config.name,
                )
                logger.info(f"LLM client created: provider={provider_type}, model={model_config.name}, api_base={model_config.base_url}")
            else:
                # No model configured, return None
                logger.warning("No model configured for agent")
                return None
            
            # Create tools
            tools = [
                BashTool(workspace_dir=str(config_manager.get_settings().workspace)),
                BashOutputTool(),
                BashKillTool(),
                ReadTool(workspace_dir=str(config_manager.get_settings().workspace)),
                WriteTool(workspace_dir=str(config_manager.get_settings().workspace)),
                EditTool(workspace_dir=str(config_manager.get_settings().workspace)),
                RecordNoteTool(),
                RecallNotesTool(),
                AskUserChoiceTool(),
            ]
            skill_loader = None

            # Web search tools
            config_obj = None
            try:
                from open_agent.config import Config
                config_path = Config.get_default_config_path()
                if config_path and config_path.exists():
                    config_obj = Config.from_yaml(config_path)
                    if config_obj.tools.enable_web_search:
                        from open_agent.tools.web_search import (
                            WebSearchTool,
                            WebBrowseTool,
                        )
                        tools.append(WebSearchTool())
                        tools.append(WebBrowseTool())
            except Exception:
                pass

            # Skills tools
            try:
                # Check user settings first (UI toggle), then config.yaml
                user_settings = config_manager.get_settings()
                enable_skills = getattr(user_settings, 'enable_skills', True) if user_settings else True
                if enable_skills and config_obj and config_obj.tools.enable_skills:
                    from open_agent.utils.path_utils import resolve_skills_dir
                    skills_path = resolve_skills_dir(config_obj.tools.skills_dir)
                    if skills_path and Path(skills_path).exists():
                        from open_agent.tools.skill_tool import create_skill_tools
                        skill_tools, skill_loader = create_skill_tools(str(skills_path))
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
                    mcp_config_path = Cfg.find_config_file(config_obj.tools.mcp_config_path)
                    if mcp_config_path:
                        from open_agent.tools.mcp_loader import load_mcp_tools_async
                        mcp_tools = asyncio.run(load_mcp_tools_async(str(mcp_config_path)))
                        if mcp_tools:
                            tools.extend(mcp_tools)
                            logger.info(f"Loaded {len(mcp_tools)} MCP tools from {mcp_config_path}")
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
            
            # Create agent
            agent = Agent(
                llm_client=llm_client,
                system_prompt=system_prompt,
                tools=tools,
                max_steps=agent_config.max_steps if hasattr(agent_config, 'max_steps') and agent_config.max_steps else 100,
                workspace_dir=str(config_manager.get_settings().workspace),
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
