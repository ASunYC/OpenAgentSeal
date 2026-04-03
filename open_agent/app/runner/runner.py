"""
Agent Runner for handling streaming agent execution.

Following CoPaw's Runner pattern for SSE-based streaming responses.
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional, Callable, Any, Dict, List

from open_agent.app.runner.models import (
    ChatSpec, Message, AgentRequest, AgentEvent
)
from open_agent.app.runner.manager import ChatManager, get_chat_manager

logger = logging.getLogger(__name__)


class AgentRunner:
    """
    Handles agent execution with streaming response support.
    
    This class bridges the FastAPI routes with the Agent system,
    providing SSE-based streaming responses following CoPaw's pattern.
    """
    
    def __init__(self):
        self._chat_manager: Optional[ChatManager] = None
    
    def set_chat_manager(self, chat_manager: ChatManager):
        """Set the chat manager instance"""
        self._chat_manager = chat_manager
    
    @property
    def chat_manager(self) -> ChatManager:
        """Get the chat manager"""
        if self._chat_manager is None:
            self._chat_manager = get_chat_manager()
        return self._chat_manager
    
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
                    logger.info(f"✅ Extracted agent_id {agent_id} from session_id {session_id}")
                    logger.info(f"✅ Agent config: name={existing_agent.name}, system_prompt={existing_agent.system_prompt[:50] if existing_agent.system_prompt else 'None'}...")
                else:
                    logger.warning(f"❌ Agent {extracted_agent_id} not found in config")
                    # List all available agents
                    all_agents = config_manager.get_all_agents()
                    logger.info(f"Available agents: {[a.id for a in all_agents]}")
            else:
                logger.warning(f"Invalid session_id format: {session_id}, cannot extract agent_id")
        
        if agent_id:
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
                        system_prompt=system_prompt
                    )
                    config_manager.add_agent(agent_config)
                    agent_id = agent_config.id
                    self.chat_manager.set_session_agent(session_id, agent_id)
            
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
        
        # Get the last user message
        user_content = ""
        if request.messages:
            last_msg = request.messages[-1]
            if isinstance(last_msg, dict):
                user_content = last_msg.get("content", "")
            elif hasattr(last_msg, "content"):
                user_content = last_msg.content
        
        if not user_content:
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error="No message content provided",
                status="error",
            )
            return
        
        # Add user message to history
        user_message = Message(role="user", content=user_content)
        self.chat_manager.add_message(session_id, user_message)
        
        # Add message to agent
        agent.add_user_message(user_content)
        
        # Yield start event
        yield AgentEvent(
            event="run_start",
            session_id=session_id,
            status="running",
        )
        
        # Create event collector for status callback
        event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        
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
        
        # Create a task to run the agent
        agent_task = asyncio.create_task(agent.run())
        
        try:
            # Yield events as they come in, while agent is running
            while not agent_task.done():
                # Check for events with a small timeout
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    yield event
                except asyncio.TimeoutError:
                    # No event available, continue waiting
                    pass
            
            # Agent is done, drain any remaining events
            while not event_queue.empty():
                yield await event_queue.get()
            
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
            yield AgentEvent(
                event="complete",
                session_id=session_id,
                status="idle",
                content=last_assistant_msg,
            )
            
            # Update chat
            await self.chat_manager.update_chat(chat)
        
        except asyncio.CancelledError:
            agent_task.cancel()
            yield AgentEvent(
                event="cancelled",
                session_id=session_id,
                status="idle",
            )
        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            yield AgentEvent(
                event="error",
                session_id=session_id,
                error=str(e),
                status="error",
            )
        finally:
            agent.status_callback = None
    
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