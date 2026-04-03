"""Tool for asking user to choose between multiple options."""

import asyncio
import sys
import threading
from typing import Any

from .base import Tool, ToolResult


class AskUserChoiceTool(Tool):
    """Tool to ask user to choose between multiple options.
    
    This tool is used when the agent finds multiple tools/skills that can 
    accomplish the same task. It presents the options to the user and waits
    for their selection.
    """

    def __init__(self, timeout: int = 30):
        """Initialize the tool.
        
        Args:
            timeout: Seconds to wait for user input before auto-selecting (default: 30)
        """
        self._timeout = timeout

    @property
    def name(self) -> str:
        """Tool name."""
        return "ask_user_choice"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Ask user to choose between multiple tool/skill options. Use this when you find 2+ tools that can accomplish the same task."

    @property
    def parameters(self) -> dict[str, Any]:
        """Tool parameters schema."""
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task description (e.g., 'Draw a lion')"
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Option ID (e.g., '1', '2', '3')"},
                            "type": {"type": "string", "description": "Tool type: 'MCP', 'Skill', 'Basic', or 'Existing'"},
                            "name": {"type": "string", "description": "Tool/skill name"},
                            "description": {"type": "string", "description": "Brief description of this option"},
                            "recommendation": {"type": "string", "description": "Why this option might be good (optional)"}
                        },
                        "required": ["id", "type", "name", "description"]
                    },
                    "description": "List of available options"
                },
                "default_choice": {
                    "type": "string",
                    "description": "The ID of the recommended/default choice (optional)"
                }
            },
            "required": ["task", "options"]
        }

    @property
    def timeout(self) -> int:
        """Timeout for user input."""
        return self._timeout

    @property
    def schema(self) -> dict:
        """Return the tool schema for LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task description (e.g., 'Draw a lion')"
                    },
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Option ID (e.g., '1', '2', '3')"},
                                "type": {"type": "string", "description": "Tool type: 'MCP', 'Skill', 'Basic', or 'Existing'"},
                                "name": {"type": "string", "description": "Tool/skill name"},
                                "description": {"type": "string", "description": "Brief description of this option"},
                                "recommendation": {"type": "string", "description": "Why this option might be good (optional)"}
                            },
                            "required": ["id", "type", "name", "description"]
                        },
                        "description": "List of available options"
                    },
                    "default_choice": {
                        "type": "string",
                        "description": "The ID of the recommended/default choice (optional)"
                    }
                },
                "required": ["task", "options"]
            }
        }

    async def execute(self, task: str, options: list[dict], default_choice: str = None) -> ToolResult:
        """Execute the tool to ask user for choice.
        
        Args:
            task: The task description
            options: List of option dictionaries
            default_choice: The ID of the default choice (used on timeout)
            
        Returns:
            ToolResult with the user's choice
        """
        # ANSI color codes
        BOLD = "\033[1m"
        RESET = "\033[0m"
        BRIGHT_CYAN = "\033[96m"
        BRIGHT_YELLOW = "\033[93m"
        BRIGHT_GREEN = "\033[92m"
        DIM = "\033[2m"
        
        # Print the options table
        print(f"\n{BOLD}{BRIGHT_CYAN}📋 Found multiple options for: {task}{RESET}")
        print(f"\n{BOLD}{'#':<4} {'Type':<8} {'Name':<20} {'Description'}{RESET}")
        print("─" * 70)
        
        for opt in options:
            opt_id = opt.get("id", "?")
            opt_type = opt.get("type", "Unknown")
            opt_name = opt.get("name", "Unknown")
            opt_desc = opt.get("description", "")[:40]
            recommendation = opt.get("recommendation", "")
            
            # Highlight recommended option
            if recommendation:
                print(f"{BRIGHT_GREEN}{opt_id:<4}{RESET} {opt_type:<8} {opt_name:<20} {opt_desc}")
                print(f"{DIM}   └─ {recommendation}{RESET}")
            else:
                print(f"{opt_id:<4} {opt_type:<8} {opt_name:<20} {opt_desc}")
        
        print("─" * 70)
        
        # Determine default choice
        if not default_choice and options:
            default_choice = options[0].get("id", "1")
        
        # Prompt for user input
        prompt = f"\n{BRIGHT_YELLOW}❓ Which option would you like to use?{RESET} "
        if default_choice:
            prompt += f"{DIM}(Enter 1-{len(options)}, 'n' to skip, or wait {self.timeout}s for auto-select: #{default_choice}){RESET} "
        else:
            prompt += f"{DIM}(Enter 1-{len(options)}, or 'n' to skip){RESET} "
        
        print(prompt, end="", flush=True)
        
        # Wait for user input with timeout
        user_choice = await self._wait_for_input(timeout=self.timeout)
        
        if user_choice is None:
            # Timeout - use default
            print(f"\n{DIM}⏱️ No input received, using default: #{default_choice}{RESET}")
            selected_id = default_choice
        else:
            selected_id = user_choice.strip()
            if not selected_id:
                selected_id = default_choice
        
        # Check if user wants to skip (n/no)
        if selected_id.lower() in ('n', 'no'):
            print(f"\n{BRIGHT_YELLOW}✗ User declined all options{RESET}")
            return ToolResult(
                success=False,
                content="User declined all options. The user does not want to use any of the suggested tools/skills. Please ask the user what they would like to do instead, or try a different approach.",
                error="USER_DECLINED"
            )
        
        # Validate and find the selected option
        selected_option = None
        for opt in options:
            if opt.get("id") == selected_id:
                selected_option = opt
                break
        
        if not selected_option:
            # User entered something that's not a valid option ID
            # This could be a custom instruction from the user
            print(f"\n{BRIGHT_YELLOW}💬 User input: {selected_id}{RESET}")
            return ToolResult(
                success=False,
                content=f"User did not select any of the provided options. Instead, the user said: '{selected_id}'. Please respond to the user's input and adjust your approach accordingly.",
                error="USER_CUSTOM_INPUT"
            )
        
        print(f"\n{BRIGHT_GREEN}✓ Selected: {selected_option.get('type')} - {selected_option.get('name')}{RESET}")
        
        return ToolResult(
            success=True,
            content=f"User selected: {selected_option.get('id')} - {selected_option.get('type')} - {selected_option.get('name')}. Proceed with this option."
        )

    async def _wait_for_input(self, timeout: int) -> str:
        """Wait for user input with timeout.
        
        Args:
            timeout: Seconds to wait
            
        Returns:
            User input string, or None if timeout
        """
        result = None
        input_received = threading.Event()
        
        def get_input():
            nonlocal result
            try:
                result = sys.stdin.readline().strip()
            except Exception:
                pass
            finally:
                input_received.set()
        
        # Start input thread
        input_thread = threading.Thread(target=get_input, daemon=True)
        input_thread.start()
        
        # Wait for input or timeout
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: input_received.wait(timeout)
            )
        except Exception:
            pass
        
        return result