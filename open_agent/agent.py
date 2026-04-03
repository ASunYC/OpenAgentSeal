"""Core Agent implementation."""

import asyncio
import json
import os
import platform
import sys
import threading
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Optional

import tiktoken

from .llm import LLMClient
from .logger import AgentLogger
from .log_memory_worker import get_log_memory_worker, LogMemoryWorker
from .schema import Message
from .tools.base import Tool, ToolResult
from .utils import calculate_display_width


# ANSI color codes
class Colors:
    """Terminal color definitions"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    # Bright colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


from typing import Callable

class Agent:
    """Single agent with basic tools and MCP support."""

    def __init__(
        self,
        llm_client: LLMClient,
        system_prompt: str,
        tools: list[Tool],
        max_steps: int = 50,
        workspace_dir: str = "./workspace",
        token_limit: int = 80000,  # Summary triggered when tokens exceed this value
        interactive: bool = True,  # Whether to ask user for tool selection when multiple options exist
        status_callback: Optional[Callable] = None,  # 状态回调函数，用于实时报告状态
    ):
        self.llm = llm_client
        self.tools = {tool.name: tool for tool in tools}
        self.max_steps = max_steps
        self.token_limit = token_limit
        self.workspace_dir = Path(workspace_dir)
        self.interactive = interactive
        # Cancellation event for interrupting agent execution (set externally, e.g., by Esc key)
        self.cancel_event: Optional[asyncio.Event] = None
        # User input callback for interactive mode
        self.user_input_callback: Optional[callable] = None
        # Status callback for real-time updates (e.g., for Web UI)
        self.status_callback = status_callback
        
        # 当前运行状态（用于外部查询）
        self.current_status = "idle"
        self.current_step = 0
        self.current_thinking = ""
        self.current_tool_call = None

        # Ensure workspace exists
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # Detect operating system environment
        os_name = platform.system()  # Windows, Linux, Darwin (macOS)
        shell_name = self._detect_shell()
        
        # Inject workspace and OS environment information into system prompt
        if "Current Workspace" not in system_prompt:
            workspace_info = f"\n\n## Current Workspace\nYou are currently working in: `{self.workspace_dir.absolute()}`\nAll relative paths will be resolved relative to this directory."
            system_prompt = system_prompt + workspace_info

        # Inject OS environment information
        if "System Environment" not in system_prompt:
            os_env_info = self._build_os_env_info(os_name, shell_name)
            system_prompt = system_prompt + os_env_info

        self.system_prompt = system_prompt

        # Initialize message history
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

        # Initialize logger
        self.logger = AgentLogger()

        # Initialize log memory worker for automatic step log compression
        self._log_memory_worker: Optional[LogMemoryWorker] = None

        # Token usage from last API response (updated after each LLM call)
        self.api_total_tokens: int = 0
        # Flag to skip token check right after summary (avoid consecutive triggers)
        self._skip_next_token_check: bool = False

    def enable_log_memory(self, enabled: bool = True):
        """Enable or disable automatic log memory compression.

        Args:
            enabled: Whether to enable log memory compression.
        """
        if enabled and self._log_memory_worker is None:
            self._log_memory_worker = get_log_memory_worker()
        elif not enabled and self._log_memory_worker is not None:
            self._log_memory_worker = None

    def add_user_message(self, content: str):
        """Add a user message to history."""
        self.messages.append(Message(role="user", content=content))

    def _emit_status(self, event_type: str, data: dict = None):
        """发送状态更新回调
        
        Args:
            event_type: 事件类型 (step_start, thinking, tool_call, tool_result, step_end, complete, error)
            data: 事件数据
        """
        if self.status_callback:
            try:
                event_data = {
                    "event": event_type,
                    "step": self.current_step,
                    "status": self.current_status,
                    **(data or {})
                }
                # 如果是协程回调，需要调度执行
                import asyncio
                if asyncio.iscoroutinefunction(self.status_callback):
                    asyncio.create_task(self.status_callback(event_data))
                else:
                    self.status_callback(event_data)
            except Exception as e:
                logger.error(f"Status callback error: {e}")

    def _check_cancelled(self) -> bool:
        """Check if agent execution has been cancelled.

        Returns:
            True if cancelled, False otherwise.
        """
        if self.cancel_event is not None and self.cancel_event.is_set():
            return True
        return False

    def _cleanup_incomplete_messages(self):
        """Remove the incomplete assistant message and its partial tool results.

        This ensures message consistency after cancellation by removing
        only the current step's incomplete messages, preserving completed steps.
        """
        # Find the index of the last assistant message
        last_assistant_idx = -1
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].role == "assistant":
                last_assistant_idx = i
                break

        if last_assistant_idx == -1:
            # No assistant message found, nothing to clean
            return

        # Remove the last assistant message and all tool results after it
        removed_count = len(self.messages) - last_assistant_idx
        if removed_count > 0:
            self.messages = self.messages[:last_assistant_idx]
            print(f"{Colors.DIM}   Cleaned up {removed_count} incomplete message(s){Colors.RESET}")

    def _estimate_tokens(self) -> int:
        """Accurately calculate token count for message history using tiktoken

        Uses cl100k_base encoder (GPT-4/Claude/M2 compatible)
        """
        try:
            # Use cl100k_base encoder (used by GPT-4 and most modern models)
            encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # Fallback: if tiktoken initialization fails, use simple estimation
            return self._estimate_tokens_fallback()

        total_tokens = 0

        for msg in self.messages:
            # Count text content
            if isinstance(msg.content, str):
                total_tokens += len(encoding.encode(msg.content))
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        # Convert dict to string for calculation
                        total_tokens += len(encoding.encode(str(block)))

            # Count thinking
            if msg.thinking:
                total_tokens += len(encoding.encode(msg.thinking))

            # Count tool_calls
            if msg.tool_calls:
                total_tokens += len(encoding.encode(str(msg.tool_calls)))

            # Metadata overhead per message (approximately 4 tokens)
            total_tokens += 4

        return total_tokens

    def _estimate_tokens_fallback(self) -> int:
        """Fallback token estimation method (when tiktoken is unavailable)"""
        total_chars = 0
        for msg in self.messages:
            if isinstance(msg.content, str):
                total_chars += len(msg.content)
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        total_chars += len(str(block))

            if msg.thinking:
                total_chars += len(msg.thinking)

            if msg.tool_calls:
                total_chars += len(str(msg.tool_calls))

        # Rough estimation: average 2.5 characters = 1 token
        return int(total_chars / 2.5)

    async def _summarize_messages(self):
        """Message history summarization: summarize conversations between user messages when tokens exceed limit

        Strategy (Agent mode):
        - Keep all user messages (these are user intents)
        - Summarize content between each user-user pair (agent execution process)
        - If last round is still executing (has agent/tool messages but no next user), also summarize
        - Structure: system -> user1 -> summary1 -> user2 -> summary2 -> user3 -> summary3 (if executing)

        Summary is triggered when EITHER:
        - Local token estimation exceeds limit
        - API reported total_tokens exceeds limit
        """
        # Skip check if we just completed a summary (wait for next LLM call to update api_total_tokens)
        if self._skip_next_token_check:
            self._skip_next_token_check = False
            return

        estimated_tokens = self._estimate_tokens()

        # Check both local estimation and API reported tokens
        should_summarize = estimated_tokens > self.token_limit or self.api_total_tokens > self.token_limit

        # If neither exceeded, no summary needed
        if not should_summarize:
            return

        print(
            f"\n{Colors.BRIGHT_YELLOW}📊 Token usage - Local estimate: {estimated_tokens}, API reported: {self.api_total_tokens}, Limit: {self.token_limit}{Colors.RESET}"
        )
        print(f"{Colors.BRIGHT_YELLOW}🔄 Triggering message history summarization...{Colors.RESET}")

        # Find all user message indices (skip system prompt)
        user_indices = [i for i, msg in enumerate(self.messages) if msg.role == "user" and i > 0]

        # Need at least 1 user message to perform summary
        if len(user_indices) < 1:
            print(f"{Colors.BRIGHT_YELLOW}⚠️  Insufficient messages, cannot summarize{Colors.RESET}")
            return

        # Build new message list
        new_messages = [self.messages[0]]  # Keep system prompt
        summary_count = 0

        # Iterate through each user message and summarize the execution process after it
        for i, user_idx in enumerate(user_indices):
            # Add current user message
            new_messages.append(self.messages[user_idx])

            # Determine message range to summarize
            # If last user, go to end of message list; otherwise to before next user
            if i < len(user_indices) - 1:
                next_user_idx = user_indices[i + 1]
            else:
                next_user_idx = len(self.messages)

            # Extract execution messages for this round
            execution_messages = self.messages[user_idx + 1 : next_user_idx]

            # If there are execution messages in this round, summarize them
            if execution_messages:
                summary_text = await self._create_summary(execution_messages, i + 1)
                if summary_text:
                    summary_message = Message(
                        role="user",
                        content=f"[Assistant Execution Summary]\n\n{summary_text}",
                    )
                    new_messages.append(summary_message)
                    summary_count += 1

        # Replace message list
        self.messages = new_messages

        # Skip next token check to avoid consecutive summary triggers
        # (api_total_tokens will be updated after next LLM call)
        self._skip_next_token_check = True

        new_tokens = self._estimate_tokens()
        print(f"{Colors.BRIGHT_GREEN}✓ Summary completed, local tokens: {estimated_tokens} → {new_tokens}{Colors.RESET}")
        print(f"{Colors.DIM}  Structure: system + {len(user_indices)} user messages + {summary_count} summaries{Colors.RESET}")
        print(f"{Colors.DIM}  Note: API token count will update on next LLM call{Colors.RESET}")

    async def _create_summary(self, messages: list[Message], round_num: int) -> str:
        """Create summary for one execution round

        Args:
            messages: List of messages to summarize
            round_num: Round number

        Returns:
            Summary text
        """
        if not messages:
            return ""

        # Build summary content
        summary_content = f"Round {round_num} execution process:\n\n"
        for msg in messages:
            if msg.role == "assistant":
                content_text = msg.content if isinstance(msg.content, str) else str(msg.content)
                summary_content += f"Assistant: {content_text}\n"
                if msg.tool_calls:
                    tool_names = [tc.function.name for tc in msg.tool_calls]
                    summary_content += f"  → Called tools: {', '.join(tool_names)}\n"
            elif msg.role == "tool":
                result_preview = msg.content if isinstance(msg.content, str) else str(msg.content)
                summary_content += f"  ← Tool returned: {result_preview}...\n"

        # Call LLM to generate concise summary
        try:
            summary_prompt = f"""Please provide a concise summary of the following Agent execution process:

{summary_content}

Requirements:
1. Focus on what tasks were completed and which tools were called
2. Keep key execution results and important findings
3. Be concise and clear, within 1000 words
4. Use English
5. Do not include "user" related content, only summarize the Agent's execution process"""

            summary_msg = Message(role="user", content=summary_prompt)
            response = await self.llm.generate(
                messages=[
                    Message(
                        role="system",
                        content="You are an assistant skilled at summarizing Agent execution processes.",
                    ),
                    summary_msg,
                ]
            )

            summary_text = response.content
            print(f"{Colors.BRIGHT_GREEN}✓ Summary for round {round_num} generated successfully{Colors.RESET}")
            return summary_text

        except Exception as e:
            print(f"{Colors.BRIGHT_RED}✗ Summary generation failed for round {round_num}: {e}{Colors.RESET}")
            # Use simple text summary on failure
            return summary_content

    async def run(self, cancel_event: Optional[asyncio.Event] = None) -> str:
        """Execute agent loop until task is complete or max steps reached.

        Args:
            cancel_event: Optional asyncio.Event that can be set to cancel execution.
                          When set, the agent will stop at the next safe checkpoint
                          (after completing the current step to keep messages consistent).

        Returns:
            The final response content, or error message (including cancellation message).
        """
        # Set cancellation event (can also be set via self.cancel_event before calling run())
        if cancel_event is not None:
            self.cancel_event = cancel_event

        # Start new run, initialize log file
        self.logger.start_new_run()
        print(f"{Colors.DIM}📝 Log file: {self.logger.get_log_file_path()}{Colors.RESET}")

        step = 0
        run_start_time = perf_counter()
        
        # 更新状态为运行中
        self.current_status = "running"
        self._emit_status("run_start", {"max_steps": self.max_steps})

        while step < self.max_steps:
            # Check for cancellation at start of each step
            if self._check_cancelled():
                self._cleanup_incomplete_messages()
                cancel_msg = "Task cancelled by user."
                print(f"\n{Colors.BRIGHT_YELLOW}⚠️  {cancel_msg}{Colors.RESET}")
                self.current_status = "cancelled"
                self._emit_status("cancelled", {"message": cancel_msg})
                return cancel_msg

            step_start_time = perf_counter()
            
            # 更新步骤状态
            self.current_step = step + 1
            self.current_status = "thinking"
            self._emit_status("step_start", {
                "step": step + 1,
                "max_steps": self.max_steps,
                "tokens": self._estimate_tokens()
            })
            # Check and summarize message history to prevent context overflow
            await self._summarize_messages()

            # Calculate current token count for display
            current_tokens = self._estimate_tokens()
            
            # Step header with proper width calculation
            BOX_WIDTH = 58
            step_text = f"{Colors.BOLD}{Colors.BRIGHT_CYAN}💭 Step {step + 1}/{self.max_steps}{Colors.RESET}"
            token_text = f"{Colors.DIM}token: {current_tokens}{Colors.RESET}"
            step_display_width = calculate_display_width(step_text)
            token_display_width = calculate_display_width(token_text)
            
            # Calculate padding to fit both step text and token info
            total_content_width = step_display_width + 1 + token_display_width  # +1 for space separator
            if total_content_width < BOX_WIDTH - 1:
                padding = BOX_WIDTH - 1 - total_content_width
                line_content = f"{step_text}{' ' * padding} {token_text}"
            else:
                # If too long, just show step text
                padding = max(0, BOX_WIDTH - 1 - step_display_width)
                line_content = f"{step_text}{' ' * padding}"

            print(f"\n{Colors.DIM}╭{'─' * BOX_WIDTH}╮{Colors.RESET}")
            print(f"{Colors.DIM}│{Colors.RESET} {line_content}{Colors.DIM}│{Colors.RESET}")
            print(f"{Colors.DIM}╰{'─' * BOX_WIDTH}╯{Colors.RESET}")

            # Notify log memory worker of step start
            if self._log_memory_worker:
                self._log_memory_worker.submit_step_start(step + 1, self.max_steps)

            # Get tool list for LLM call
            tool_list = list(self.tools.values())

            # Log LLM request and call LLM with Tool objects directly
            self.logger.log_request(messages=self.messages, tools=tool_list)

            # Start heartbeat display for LLM call
            heartbeat_stop = threading.Event()
            heartbeat_thread = threading.Thread(
                target=self._llm_heartbeat,
                args=(heartbeat_stop, step + 1),
                daemon=True,
            )
            heartbeat_thread.start()

            try:
                response = await self.llm.generate(messages=self.messages, tools=tool_list)
            except Exception as e:
                # Stop heartbeat
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=0.5)
                
                # Check if it's a retry exhausted error
                from .retry import RetryExhaustedError

                if isinstance(e, RetryExhaustedError):
                    error_msg = f"LLM call failed after {e.attempts} retries\nLast error: {str(e.last_exception)}"
                    print(f"\n{Colors.BRIGHT_RED}❌ Retry failed:{Colors.RESET} {error_msg}")
                else:
                    error_msg = f"LLM call failed: {str(e)}"
                    print(f"\n{Colors.BRIGHT_RED}❌ Error:{Colors.RESET} {error_msg}")
                return error_msg
            finally:
                # Always stop heartbeat
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=0.5)

            # Accumulate API reported token usage
            if response.usage:
                self.api_total_tokens = response.usage.total_tokens

            # Log LLM response
            self.logger.log_response(
                content=response.content,
                thinking=response.thinking,
                tool_calls=response.tool_calls,
                finish_reason=response.finish_reason,
            )

            # Add assistant message
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                thinking=response.thinking,
                tool_calls=response.tool_calls,
            )
            self.messages.append(assistant_msg)

            # 发送思考状态
            if response.thinking:
                self.current_thinking = response.thinking
                self.current_status = "thinking"
                self._emit_status("thinking", {"content": response.thinking})
                print(f"\n{Colors.BOLD}{Colors.MAGENTA}🧠 Thinking:{Colors.RESET}")
                print(f"{Colors.DIM}{response.thinking}{Colors.RESET}")
                # Submit thinking to log memory
                if self._log_memory_worker:
                    self._log_memory_worker.submit_log_entry(
                        content=f"Thinking: {response.thinking}",
                        entry_type="thinking",
                    )

            # Print assistant response
            if response.content:
                print(f"\n{Colors.BOLD}{Colors.BRIGHT_BLUE}🤖 Assistant:{Colors.RESET}")
                print(f"{response.content}")
                # Submit assistant response to log memory
                if self._log_memory_worker:
                    self._log_memory_worker.submit_log_entry(
                        content=f"Assistant: {response.content}",
                        entry_type="assistant_response",
                    )

            # Check if task is complete (no tool calls)
            if not response.tool_calls:
                step_elapsed = perf_counter() - step_start_time
                total_elapsed = perf_counter() - run_start_time
                print(f"\n{Colors.DIM}⏱️  Step {step + 1} completed in {step_elapsed:.2f}s (total: {total_elapsed:.2f}s){Colors.RESET}")
                return response.content

            # Check for cancellation before executing tools
            if self._check_cancelled():
                self._cleanup_incomplete_messages()
                cancel_msg = "Task cancelled by user."
                print(f"\n{Colors.BRIGHT_YELLOW}⚠️  {cancel_msg}{Colors.RESET}")
                return cancel_msg

            # Execute tool calls
            for tool_call in response.tool_calls:
                tool_call_id = tool_call.id
                function_name = tool_call.function.name
                arguments = tool_call.function.arguments

                # 发送工具调用状态
                self.current_status = "tool_call"
                self.current_tool_call = {"name": function_name, "arguments": arguments}
                self._emit_status("tool_call", {
                    "tool_name": function_name,
                    "arguments": arguments
                })

                # Tool call header
                print(f"\n{Colors.BRIGHT_YELLOW}🔧 Tool Call:{Colors.RESET} {Colors.BOLD}{Colors.CYAN}{function_name}{Colors.RESET}")

                # Arguments (formatted display)
                print(f"{Colors.DIM}   Arguments:{Colors.RESET}")
                # Truncate each argument value to avoid overly long output
                truncated_args = {}
                for key, value in arguments.items():
                    value_str = str(value)
                    if len(value_str) > 200:
                        truncated_args[key] = value_str[:200] + "..."
                    else:
                        truncated_args[key] = value
                args_json = json.dumps(truncated_args, indent=2, ensure_ascii=False)
                for line in args_json.split("\n"):
                    print(f"   {Colors.DIM}{line}{Colors.RESET}")

                # Execute tool
                if function_name not in self.tools:
                    result = ToolResult(
                        success=False,
                        content="",
                        error=f"Unknown tool: {function_name}",
                    )
                else:
                    try:
                        tool = self.tools[function_name]
                        result = await tool.execute(**arguments)
                    except Exception as e:
                        # Catch all exceptions during tool execution, convert to failed ToolResult
                        import traceback

                        error_detail = f"{type(e).__name__}: {str(e)}"
                        error_trace = traceback.format_exc()
                        result = ToolResult(
                            success=False,
                            content="",
                            error=f"Tool execution failed: {error_detail}\n\nTraceback:\n{error_trace}",
                        )

                # Log tool execution result
                self.logger.log_tool_result(
                    tool_name=function_name,
                    arguments=arguments,
                    result_success=result.success,
                    result_content=result.content if result.success else None,
                    result_error=result.error if not result.success else None,
                )

                # Print result
                if result.success:
                    result_text = result.content
                    if len(result_text) > 300:
                        result_text = result_text[:300] + f"{Colors.DIM}...{Colors.RESET}"
                    print(f"{Colors.BRIGHT_GREEN}✓ Result:{Colors.RESET} {result_text}")
                else:
                    print(f"{Colors.BRIGHT_RED}✗ Error:{Colors.RESET} {Colors.RED}{result.error}{Colors.RESET}")
                
                # 发送工具结果状态
                self._emit_status("tool_result", {
                    "tool_name": function_name,
                    "success": result.success,
                    "content": result.content[:500] if result.success and result.content else None,
                    "error": result.error if not result.success else None
                })

                # Submit tool call to log memory
                if self._log_memory_worker:
                    tool_log = f"Tool Call: {function_name}\nArguments: {json.dumps(arguments, ensure_ascii=False)}"
                    if result.success:
                        tool_log += f"\nResult: {result.content[:500]}{'...' if len(result.content) > 500 else ''}"
                    else:
                        tool_log += f"\nError: {result.error}"
                    self._log_memory_worker.submit_log_entry(
                        content=tool_log,
                        entry_type="tool_call",
                        metadata={"tool": function_name, "success": result.success},
                    )

                # Add tool result message
                tool_msg = Message(
                    role="tool",
                    content=result.content if result.success else f"Error: {result.error}",
                    tool_call_id=tool_call_id,
                    name=function_name,
                )
                self.messages.append(tool_msg)

                # Check for cancellation after each tool execution
                if self._check_cancelled():
                    self._cleanup_incomplete_messages()
                    cancel_msg = "Task cancelled by user."
                    print(f"\n{Colors.BRIGHT_YELLOW}⚠️  {cancel_msg}{Colors.RESET}")
                    return cancel_msg

            step_elapsed = perf_counter() - step_start_time
            total_elapsed = perf_counter() - run_start_time
            print(f"\n{Colors.DIM}⏱️  Step {step + 1} completed in {step_elapsed:.2f}s (total: {total_elapsed:.2f}s){Colors.RESET}")

            # 发送步骤结束状态
            self._emit_status("step_end", {
                "step": step + 1,
                "elapsed": step_elapsed,
                "total_elapsed": total_elapsed
            })

            # Notify log memory worker of step end
            if self._log_memory_worker:
                self._log_memory_worker.submit_step_end(
                    step=step + 1,
                    elapsed_time=step_elapsed,
                    total_time=total_elapsed,
                )

            step += 1

        # Max steps reached
        error_msg = f"Task couldn't be completed after {self.max_steps} steps."
        print(f"\n{Colors.BRIGHT_YELLOW}⚠️  {error_msg}{Colors.RESET}")
        self.current_status = "error"
        self._emit_status("error", {"message": error_msg})
        return error_msg

    def get_history(self) -> list[Message]:
        """Get message history."""
        return self.messages.copy()

    def _detect_shell(self) -> str:
        """Detect the current shell environment.
        
        Returns:
            Shell name: 'powershell', 'cmd', 'bash', 'zsh', 'fish', or 'unknown'
        """
        # Check environment variables for shell detection
        if os.name == 'nt':  # Windows
            # Check for PowerShell
            ps_module = os.environ.get('PSModulePath', '')
            if ps_module:
                return 'powershell'
            # Check for cmd
            comspec = os.environ.get('COMSPEC', '')
            if 'cmd.exe' in comspec.lower():
                return 'cmd'
            # Default to powershell on modern Windows
            return 'powershell'
        else:  # Unix-like (Linux, macOS)
            shell = os.environ.get('SHELL', '')
            if 'bash' in shell:
                return 'bash'
            elif 'zsh' in shell:
                return 'zsh'
            elif 'fish' in shell:
                return 'fish'
            elif shell:
                return shell.split('/')[-1]
            return 'bash'  # Default fallback

    def _build_os_env_info(self, os_name: str, shell_name: str) -> str:
        """Build OS environment information for system prompt.
        
        Args:
            os_name: Operating system name (Windows, Linux, Darwin)
            shell_name: Shell name (powershell, cmd, bash, zsh, fish)
            
        Returns:
            Formatted OS environment information string
        """
        info = "\n\n## System Environment\n"
        info += f"**Operating System**: {os_name}\n"
        info += f"**Shell**: {shell_name}\n\n"
        
        # Add shell-specific command guidelines
        if shell_name == 'powershell':
            info += """### PowerShell Command Guidelines
- **DO NOT** use Unix-style commands like `ls -la`, `rm -rf`, `cat`, `grep`
- **USE** PowerShell equivalents:
  - `ls` → `Get-ChildItem` or `dir`
  - `rm` → `Remove-Item`
  - `cat` → `Get-Content`
  - `grep` → `Select-String`
  - `mkdir` → `New-Item -ItemType Directory`
- **DO NOT** use `&&` to chain commands - use `;` instead
- **DO NOT** use `||` for fallback - use `if` statements
- **DO NOT** use `2>/dev/null` - use `2>$null` or `-ErrorAction SilentlyContinue`
- Use `|` for piping (this works in PowerShell too)
- Example: `Get-ChildItem -Path . -Filter "*.txt" | Select-Object Name, Length`
"""
        elif shell_name == 'cmd':
            info += """### CMD Command Guidelines
- Use Windows-style commands: `dir`, `del`, `copy`, `move`, `mkdir`
- Use `&` to chain commands, not `&&`
- Use `|` for piping
- Avoid Unix-style commands
"""
        elif shell_name in ('bash', 'zsh', 'fish'):
            info += """### Unix Shell Command Guidelines
- Standard Unix commands are available: `ls`, `rm`, `cat`, `grep`, `find`
- Use `&&` to chain commands
- Use `||` for fallback
- Use `|` for piping
- Use `2>/dev/null` to suppress errors
"""
        else:
            info += f"""### Shell Guidelines
- Current shell: {shell_name}
- Use commands appropriate for this shell
"""
        
        info += "\n**IMPORTANT**: Always use commands that are compatible with the current shell environment to avoid errors."
        
        return info

    def _llm_heartbeat(self, stop_event: threading.Event, step: int):
        """Display heartbeat animation while waiting for LLM response.
        
        Shows a rotating animation with elapsed time to indicate the agent is waiting
        for the LLM API response. This prevents the UI from appearing frozen.
        
        Args:
            stop_event: Event to signal the heartbeat to stop
            step: Current step number for display
        """
        start_time = perf_counter()
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        
        while not stop_event.is_set():
            elapsed = perf_counter() - start_time
            spinner = spinner_chars[idx % len(spinner_chars)]
            
            # Build status message based on elapsed time
            if elapsed < 10:
                status = f"{Colors.BRIGHT_CYAN}🌐 Waiting for LLM response...{Colors.RESET}"
            elif elapsed < 30:
                status = f"{Colors.BRIGHT_YELLOW}⏳ LLM is thinking ({elapsed:.0f}s)...{Colors.RESET}"
            elif elapsed < 60:
                status = f"{Colors.BRIGHT_YELLOW}⚠️  Still waiting ({elapsed:.0f}s), check network...{Colors.RESET}"
            else:
                status = f"{Colors.BRIGHT_RED}🔴 Long wait ({elapsed:.0f}s), possible timeout or network issue, or press Esc to stop current session{Colors.RESET}"
            
            # Print heartbeat line (overwrite previous)
            sys.stdout.write(f"\r{spinner} {status}")
            sys.stdout.flush()
            
            # Sleep for animation frame rate
            stop_event.wait(0.15)
            idx += 1
        
        # Clear the heartbeat line when done
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
