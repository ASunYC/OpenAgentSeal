"""
Open Agent - Interactive Runtime Example

Usage:
    open-agent [--workspace DIR] [--task TASK]

Examples:
    open-agent                              # Use current directory as workspace (interactive mode)
    open-agent --workspace /path/to/dir     # Use specific workspace directory (interactive mode)
    open-agent --task "create a file"       # Execute a task non-interactively
"""

import argparse
import asyncio
import os
import platform
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import List

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style

from open_agent import LLMClient, __version__
from open_agent.agent import Agent
from open_agent.cli_commands import (
    SlashCommandCompleter,
    command_alias_label,
    iter_command_sections,
    parse_command,
)
from open_agent.cli_ui import (
    PROMPT_STYLE,
    RuntimeStatus,
    SessionOverview,
    build_prompt_fragments,
    build_status_fragments,
    print_welcome,
    render_execution_header,
)
from open_agent.config import Config
from open_agent.schema import LLMProvider
from open_agent.memory_manager import get_memory_manager
from open_agent.user_config import (
    get_user_config,
    ModelConfig,
    ModelProvider,
)


def _apply_cli_launch_context(agent: Agent, workspace_dir: Path) -> dict[str, str]:
    session_id = os.environ.get("OPEN_AGENT_SESSION_ID", "").strip() or f"cli-{id(agent)}"
    profile_id = os.environ.get("OPEN_AGENT_PROFILE_ID", "").strip() or "main"
    launch_source = os.environ.get("OPEN_AGENT_LAUNCH_SOURCE", "").strip() or "terminal"
    agent.session_id = session_id
    agent.profile_id = profile_id
    return {
        "session_id": session_id,
        "profile_id": profile_id,
        "workspace_dir": str(workspace_dir),
        "launch_source": launch_source,
    }


def load_shared_model_config() -> ModelConfig | None:
    """Load the desktop and CLI model selection from the shared user config."""
    manager = get_user_config()
    manager.reload()
    return manager.get_default_model()


# select_model function - defined below after all imports
def select_model():
    """Interactive model selection wizard.

    Returns:
        ModelConfig if selected, None if cancelled
    """
    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}🚀 Model Selection Wizard{Colors.RESET}")
    print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")

    manager = get_user_config()

    # Check for saved models
    saved_models = manager.get_all_models()

    if saved_models:
        print(f"\n{Colors.BOLD}{Colors.BRIGHT_YELLOW}Saved Models:{Colors.RESET}")
        for i, m in enumerate(saved_models, 1):
            default_marker = (
                f" {Colors.BRIGHT_YELLOW}(default){Colors.RESET}"
                if m.is_default
                else ""
            )
            print(
                f"  {Colors.BRIGHT_GREEN}{i}{Colors.RESET}. {m.display_name}{default_marker}"
            )
            print(
                f"      {Colors.DIM}Provider: {m.provider}, Model: {m.name}{Colors.RESET}"
            )

        print(f"\n  {Colors.BRIGHT_GREEN}0{Colors.RESET}. Configure new model")
        print(f"  {Colors.BRIGHT_GREEN}q{Colors.RESET}. Quit (no model selected)")

        choice = (
            input(
                f"\n{Colors.BRIGHT_CYAN}➤ Select (0-{len(saved_models)}, or 'q'): {Colors.RESET}"
            )
            .strip()
            .lower()
        )

        if choice == "q":
            return None

        if choice.isdigit() and 1 <= int(choice) <= len(saved_models):
            return saved_models[int(choice) - 1]

        if choice != "0":
            print(f"{Colors.RED}Invalid selection.{Colors.RESET}")
            return None

    # Configure new model
    print(f"\n{Colors.BOLD}{Colors.BRIGHT_YELLOW}Select Provider:{Colors.RESET}")
    print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")

    providers = list(ModelProvider)
    for i, p in enumerate(providers, 1):
        print(
            f"  {Colors.BRIGHT_GREEN}{i}{Colors.RESET}. {ModelProvider.get_display_name(p)}"
        )

    print(f"\n  {Colors.BRIGHT_GREEN}0{Colors.RESET}. Cancel")

    p_choice = input(
        f"\n{Colors.BRIGHT_CYAN}➤ Select provider (0-{len(providers)}): {Colors.RESET}"
    ).strip()

    if p_choice == "0":
        return None

    try:
        p_idx = int(p_choice)
        if not (1 <= p_idx <= len(providers)):
            print(f"{Colors.RED}Invalid selection.{Colors.RESET}")
            return None

        selected_provider = providers[p_idx - 1]

        # Get provider config
        provider_config = manager.get_provider_config(selected_provider.value)

        # Ask for base URL
        default_url = provider_config.get("base_url", "")
        print(f"\n{Colors.BRIGHT_YELLOW}API Base URL:{Colors.RESET}")
        if default_url:
            print(f"  {Colors.BRIGHT_GREEN}1{Colors.RESET}. Use default: {default_url}")
            print(f"  {Colors.BRIGHT_GREEN}2{Colors.RESET}. Enter custom URL")

            url_choice = input(
                f"\n{Colors.BRIGHT_CYAN}➤ Select (1-2): {Colors.RESET}"
            ).strip()

            if url_choice == "2":
                base_url = input(
                    f"{Colors.BRIGHT_CYAN}➤ Enter base URL: {Colors.RESET}"
                ).strip()
            else:
                base_url = default_url
        else:
            base_url = input(
                f"{Colors.BRIGHT_CYAN}➤ Enter base URL: {Colors.RESET}"
            ).strip()

        # Get API key
        api_key = input(
            f"\n{Colors.BRIGHT_CYAN}➤ Enter API key: {Colors.RESET}"
        ).strip()

        if not api_key:
            print(f"{Colors.RED}❌ API key is required.{Colors.RESET}")
            return None

        # Select model
        default_models = provider_config.get("models", [])
        model_name = ""

        if default_models:
            print(f"\n{Colors.BRIGHT_YELLOW}Select Model:{Colors.RESET}")
            for i, m in enumerate(default_models, 1):
                print(f"  {Colors.BRIGHT_GREEN}{i}{Colors.RESET}. {m}")
            print(f"  {Colors.BRIGHT_GREEN}0{Colors.RESET}. Enter custom model name")

            m_choice = input(
                f"\n{Colors.BRIGHT_CYAN}➤ Select model: {Colors.RESET}"
            ).strip()

            if m_choice == "0":
                model_name = input(
                    f"{Colors.BRIGHT_CYAN}➤ Enter model name: {Colors.RESET}"
                ).strip()
            elif m_choice.isdigit() and 1 <= int(m_choice) <= len(default_models):
                model_name = default_models[int(m_choice) - 1]
        else:
            model_name = input(
                f"\n{Colors.BRIGHT_CYAN}➤ Enter model name: {Colors.RESET}"
            ).strip()

        if not model_name:
            print(f"{Colors.RED}❌ Model name is required.{Colors.RESET}")
            return None

        # Determine provider_type
        # OpenAI and Anthropic have fixed provider_type
        if selected_provider.value.lower() == "openai":
            provider_type = "openai"
        elif selected_provider.value.lower() == "anthropic":
            provider_type = "anthropic"
        else:
            # Other providers: let user choose
            print(f"\n{Colors.BRIGHT_YELLOW}Select API Protocol:{Colors.RESET}")
            print(
                f"  {Colors.DIM}Which SDK/protocol to use for this model?{Colors.RESET}"
            )
            print(
                f"  {Colors.BRIGHT_GREEN}1{Colors.RESET}. anthropic - Use Anthropic SDK (default)"
            )
            print(
                f"  {Colors.BRIGHT_GREEN}2{Colors.RESET}. openai - Use OpenAI-compatible API"
            )
            print(f"  {Colors.BRIGHT_GREEN}3{Colors.RESET}. none - No specific SDK")

            pt_choice = input(
                f"\n{Colors.BRIGHT_CYAN}➤ Select (1-3, default=1): {Colors.RESET}"
            ).strip()

            if pt_choice == "2":
                provider_type = "openai"
            elif pt_choice == "3":
                provider_type = "none"
            else:
                provider_type = "anthropic"

        # Create model config
        provider_display = ModelProvider.get_display_name(selected_provider)
        new_config = ModelConfig.create(
            name=model_name,
            display_name=f"{provider_display} - {model_name}",
            provider=selected_provider.value,
            api_key=api_key,
            base_url=base_url,
            provider_type=provider_type,
        )

        # Save
        manager.add_model(new_config)
        manager.set_default_model(new_config.id)

        print(f"\n{Colors.GREEN}✅ Model configured and saved!{Colors.RESET}")
        print(f"   {Colors.DIM}Provider: {provider_display}{Colors.RESET}")
        print(f"   {Colors.DIM}Model: {model_name}{Colors.RESET}")

        return new_config

    except ValueError:
        print(f"{Colors.RED}Invalid input.{Colors.RESET}")
        return None


from open_agent.tools.base import Tool
from open_agent.tools.bash_tool import BashKillTool, BashOutputTool, BashTool
from open_agent.tools.file_tools import EditTool, ReadTool, WriteTool
from open_agent.tools.search_tools import GlobTool, GrepTool, ListDirTool
from open_agent.tools.mcp_loader import (
    cleanup_mcp_connections,
    load_mcp_tools_async,
    set_mcp_timeout_config,
    ListMCPPromptsTool,
    GetMCPPromptTool,
)
from open_agent.tools.note_tool import (
    RecordNoteTool,
    RecallNotesTool,
    SearchMemoryTreeTool,
    GetMemoryStatsTool,
)
from open_agent.tools.skill_tool import create_skill_tools
from open_agent.tools.choice_tool import AskUserChoiceTool
from open_agent.tools.config_watcher import (
    get_config_watcher,
    reload_mcp_tools,
    reload_skills,
)
from open_agent.tools.web_search import (
    WebSearchTool,
    WebBrowseTool,
    WebSearchReportTool,
)
from open_agent.utils.path_utils import (
    get_external_skills_dir,
    get_user_app_dir,
    is_frozen,
)
from open_agent.task_queue import (
    TaskStatus,
    create_task_dispatcher,
)
def enable_windows_ansi():
    """Enable ANSI escape sequences on Windows console.

    Windows 10+ supports ANSI escape sequences but requires
    enabling virtual terminal processing mode.
    """
    if platform.system() != "Windows":
        return True

    try:
        import ctypes

        # Get STD_OUTPUT_HANDLE (-11)
        kernel32 = ctypes.windll.kernel32
        hOut = kernel32.GetStdHandle(-11)
        if hOut == -1:
            return False

        # Get current console mode
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(hOut, ctypes.byref(mode)) == 0:
            return False

        # Enable virtual terminal processing (ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004)
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

        # Check if already enabled
        if mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True

        # Set the new mode
        mode.value |= ENABLE_VIRTUAL_TERMINAL_PROCESSING
        result = kernel32.SetConsoleMode(hOut, mode)
        return result != 0
    except Exception:
        return False


# ANSI color codes
class Colors:
    """Terminal color definitions"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"


def get_log_directory() -> Path:
    """Get the log directory path."""
    from open_agent.utils.path_utils import get_logs_dir
    return get_logs_dir()


def show_log_directory(open_file_manager: bool = True) -> None:
    """Show log directory contents and optionally open file manager.

    Args:
        open_file_manager: Whether to open the system file manager
    """
    log_dir = get_log_directory()

    print(f"\n{Colors.BRIGHT_CYAN}📁 Log Directory: {log_dir}{Colors.RESET}")

    if not log_dir.exists() or not log_dir.is_dir():
        print(f"{Colors.RED}Log directory does not exist: {log_dir}{Colors.RESET}\n")
        return

    log_files = list(log_dir.glob("*.log"))

    if not log_files:
        print(f"{Colors.YELLOW}No log files found in directory.{Colors.RESET}\n")
        return

    # Sort by modification time (newest first)
    log_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")
    print(
        f"{Colors.BOLD}{Colors.BRIGHT_YELLOW}Available Log Files (newest first):{Colors.RESET}"
    )

    for i, log_file in enumerate(log_files[:10], 1):
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
        size = log_file.stat().st_size
        size_str = f"{size:,}" if size < 1024 else f"{size / 1024:.1f}K"
        print(
            f"  {Colors.GREEN}{i:2d}.{Colors.RESET} {Colors.BRIGHT_WHITE}{log_file.name}{Colors.RESET}"
        )
        print(
            f"      {Colors.DIM}Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}, Size: {size_str}{Colors.RESET}"
        )

    if len(log_files) > 10:
        print(f"  {Colors.DIM}... and {len(log_files) - 10} more files{Colors.RESET}")

    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")

    # Open file manager
    if open_file_manager:
        _open_directory_in_file_manager(log_dir)

    print()


def _open_directory_in_file_manager(directory: Path) -> None:
    """Open directory in system file manager (cross-platform)."""
    system = platform.system()

    try:
        if system == "Darwin":
            subprocess.run(["open", str(directory)], check=False)
        elif system == "Windows":
            subprocess.run(["explorer", str(directory)], check=False)
        elif system == "Linux":
            subprocess.run(["xdg-open", str(directory)], check=False)
    except FileNotFoundError:
        print(
            f"{Colors.YELLOW}Could not open file manager. Please navigate manually.{Colors.RESET}"
        )
    except Exception as e:
        print(f"{Colors.YELLOW}Error opening file manager: {e}{Colors.RESET}")


def read_log_file(filename: str) -> None:
    """Read and display a specific log file.

    Args:
        filename: The log filename to read
    """
    log_dir = get_log_directory()
    log_file = log_dir / filename

    if not log_file.exists() or not log_file.is_file():
        print(f"\n{Colors.RED}❌ Log file not found: {log_file}{Colors.RESET}\n")
        return

    print(f"\n{Colors.BRIGHT_CYAN}📄 Reading: {log_file}{Colors.RESET}")
    print(f"{Colors.DIM}{'─' * 80}{Colors.RESET}")

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        print(content)
        print(f"{Colors.DIM}{'─' * 80}{Colors.RESET}")
        print(f"\n{Colors.GREEN}✅ End of file{Colors.RESET}\n")
    except Exception as e:
        print(f"\n{Colors.RED}❌ Error reading file: {e}{Colors.RESET}\n")


def print_help():
    """Print help from the same catalog used by slash completion."""
    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}OPENAGENTSEAL COMMAND INDEX{Colors.RESET}")
    print(f"{Colors.DIM}{'─' * 72}{Colors.RESET}")
    for category, specs in iter_command_sections():
        print(f"\n{Colors.BOLD}{Colors.BRIGHT_YELLOW}{category.upper()}{Colors.RESET}")
        for spec in specs:
            usage = spec.command
            if spec.args_hint:
                usage += f" {spec.args_hint}"
            alias_label = command_alias_label(spec)
            alias_text = f"  {Colors.DIM}{alias_label}{Colors.RESET}" if alias_label else ""
            print(
                f"  {Colors.BRIGHT_CYAN}{usage:<24}{Colors.RESET}"
                f"{spec.description}{alias_text}"
            )
    print(f"\n{Colors.DIM}Type / to browse commands · Esc aborts a running turn · Ctrl+J inserts a newline{Colors.RESET}\n")


def create_cli_prompt_session(
    *,
    history_file: Path,
    completer,
    style: Style,
    key_bindings: KeyBindings,
    input_stream=None,
    output_stream=None,
) -> PromptSession:
    """Create a CLI prompt where live slash completion remains enabled."""
    session_options = {
        "history": FileHistory(str(history_file)),
        "auto_suggest": AutoSuggestFromHistory(),
        "completer": completer,
        "style": style,
        "key_bindings": key_bindings,
        "complete_while_typing": True,
        # prompt_toolkit disables live completion when history search is enabled.
        "enable_history_search": False,
        "complete_style": CompleteStyle.COLUMN,
        "reserve_space_for_menu": 12,
    }
    if input_stream is not None:
        session_options["input"] = input_stream
    if output_stream is not None:
        session_options["output"] = output_stream
    return PromptSession(**session_options)


async def handle_switch_model(agent: Agent, llm_client: LLMClient, config: Config):
    """Handle model switching during runtime.

    Args:
        agent: The current Agent instance
        llm_client: The current LLM client
        config: The current configuration
    """
    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}🔄 Switch Model{Colors.RESET}")
    print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")

    manager = get_user_config()

    # Show current model info
    current_model = manager.get_default_model()
    if current_model:
        print(f"\n{Colors.BRIGHT_YELLOW}Current Model:{Colors.RESET}")
        print(f"  {Colors.GREEN}• Provider: {current_model.provider}{Colors.RESET}")
        print(f"  {Colors.GREEN}• Model: {current_model.name}{Colors.RESET}")
        if current_model.base_url:
            print(f"  {Colors.GREEN}• Base URL: {current_model.base_url}{Colors.RESET}")

    print(f"\n{Colors.BOLD}{Colors.BRIGHT_YELLOW}Options:{Colors.RESET}")
    print(f"  {Colors.BRIGHT_GREEN}1{Colors.RESET}. Switch Provider")

    # List saved models
    models = manager.get_all_models()
    if models:
        print(f"\n  {Colors.DIM}Saved Models:{Colors.RESET}")
        for i, m in enumerate(models, 2):
            default_marker = (
                f" {Colors.BRIGHT_YELLOW}(default){Colors.RESET}"
                if m.is_default
                else ""
            )
            print(
                f"  {Colors.BRIGHT_GREEN}{i}{Colors.RESET}. {m.display_name}{default_marker}"
            )
            print(
                f"      {Colors.DIM}Provider: {m.provider}, Model: {m.name}{Colors.RESET}"
            )
    else:
        print(
            f"\n  {Colors.DIM}No saved models - use option 1 to configure{Colors.RESET}"
        )

    print(f"\n  {Colors.BRIGHT_GREEN}0{Colors.RESET}. Cancel")

    choice = input(f"\n{Colors.BRIGHT_CYAN}➤ Select option: {Colors.RESET}").strip()

    if choice == "0":
        print(f"{Colors.DIM}Cancelled.{Colors.RESET}\n")
        return

    if choice == "1":
        # Switch provider - show provider list
        print(f"\n{Colors.BOLD}{Colors.BRIGHT_YELLOW}Select Provider:{Colors.RESET}")
        print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")

        providers = list(ModelProvider)
        for i, p in enumerate(providers, 1):
            print(
                f"  {Colors.BRIGHT_GREEN}{i}{Colors.RESET}. {ModelProvider.get_display_name(p)}"
            )

        print(f"\n  {Colors.BRIGHT_GREEN}0{Colors.RESET}. Cancel")

        p_choice = input(
            f"\n{Colors.BRIGHT_CYAN}➤ Select provider (0-{len(providers)}): {Colors.RESET}"
        ).strip()

        if p_choice == "0":
            print(f"{Colors.DIM}Cancelled.{Colors.RESET}\n")
            return

        try:
            p_idx = int(p_choice)
            if 1 <= p_idx <= len(providers):
                selected_provider = providers[p_idx - 1]

                # Get provider config
                provider_config = manager.get_provider_config(selected_provider.value)

                # Ask for base URL
                print(f"\n{Colors.BRIGHT_YELLOW}API Base URL:{Colors.RESET}")
                print(
                    f"  {Colors.BRIGHT_GREEN}1{Colors.RESET}. Use default: {provider_config.get('base_url', 'N/A')}"
                )
                print(f"  {Colors.BRIGHT_GREEN}2{Colors.RESET}. Enter custom URL")
                print(f"\n  {Colors.BRIGHT_GREEN}0{Colors.RESET}. Cancel")

                url_choice = input(
                    f"\n{Colors.BRIGHT_CYAN}➤ Select: {Colors.RESET}"
                ).strip()

                if url_choice == "0":
                    print(f"{Colors.DIM}Cancelled.{Colors.RESET}\n")
                    return

                base_url = provider_config.get("base_url", "")
                if url_choice == "2":
                    custom_url = input(
                        f"{Colors.BRIGHT_CYAN}➤ Enter base URL: {Colors.RESET}"
                    ).strip()
                    if custom_url:
                        base_url = custom_url

                # Get API key
                saved_key = provider_config.get("api_key", "")
                if saved_key:
                    print(f"\n{Colors.BRIGHT_YELLOW}API Key:{Colors.RESET}")
                    print(
                        f"  {Colors.BRIGHT_GREEN}1{Colors.RESET}. Use saved key: ****{saved_key[-4:] if len(saved_key) > 4 else '****'}"
                    )
                    print(f"  {Colors.BRIGHT_GREEN}2{Colors.RESET}. Enter new key")
                    print(f"\n  {Colors.BRIGHT_GREEN}0{Colors.RESET}. Cancel")

                    key_choice = input(
                        f"\n{Colors.BRIGHT_CYAN}➤ Select: {Colors.RESET}"
                    ).strip()

                    if key_choice == "0":
                        print(f"{Colors.DIM}Cancelled.{Colors.RESET}\n")
                        return

                    if key_choice == "2":
                        api_key = input(
                            f"{Colors.BRIGHT_CYAN}➤ Enter API key: {Colors.RESET}"
                        ).strip()
                    else:
                        api_key = saved_key
                else:
                    api_key = input(
                        f"\n{Colors.BRIGHT_CYAN}➤ Enter API key: {Colors.RESET}"
                    ).strip()

                if not api_key:
                    print(f"{Colors.RED}❌ API key is required.{Colors.RESET}\n")
                    return

                # Select model
                print(f"\n{Colors.BRIGHT_YELLOW}Select Model:{Colors.RESET}")
                default_models = provider_config.get("models", [])
                if default_models:
                    print(f"  {Colors.BRIGHT_GREEN}Available models:{Colors.RESET}")
                    for i, m in enumerate(default_models, 1):
                        print(f"    {Colors.BRIGHT_GREEN}{i}{Colors.RESET}. {m}")
                    print(
                        f"  {Colors.BRIGHT_GREEN}0{Colors.RESET}. Enter custom model name"
                    )

                    m_choice = input(
                        f"\n{Colors.BRIGHT_CYAN}➤ Select model: {Colors.RESET}"
                    ).strip()

                    if m_choice == "0":
                        model_name = input(
                            f"{Colors.BRIGHT_CYAN}➤ Enter model name: {Colors.RESET}"
                        ).strip()
                    else:
                        try:
                            m_idx = int(m_choice)
                            if 1 <= m_idx <= len(default_models):
                                model_name = default_models[m_idx - 1]
                            else:
                                print(f"{Colors.RED}Invalid selection.{Colors.RESET}\n")
                                return
                        except ValueError:
                            print(f"{Colors.RED}Invalid input.{Colors.RESET}\n")
                            return
                else:
                    model_name = input(
                        f"{Colors.BRIGHT_CYAN}➤ Enter model name: {Colors.RESET}"
                    ).strip()

                if not model_name:
                    print(f"{Colors.RED}❌ Model name is required.{Colors.RESET}\n")
                    return

                # Determine provider_type
                # OpenAI and Anthropic have fixed provider_type
                if selected_provider.value.lower() == "openai":
                    provider_type = "openai"
                elif selected_provider.value.lower() == "anthropic":
                    provider_type = "anthropic"
                else:
                    # Other providers: let user choose
                    print(f"\n{Colors.BRIGHT_YELLOW}Select API Protocol:{Colors.RESET}")
                    print(
                        f"  {Colors.DIM}Which SDK/protocol to use for this model?{Colors.RESET}"
                    )
                    print(
                        f"  {Colors.BRIGHT_GREEN}1{Colors.RESET}. anthropic - Use Anthropic SDK (default)"
                    )
                    print(
                        f"  {Colors.BRIGHT_GREEN}2{Colors.RESET}. openai - Use OpenAI-compatible API"
                    )
                    print(
                        f"  {Colors.BRIGHT_GREEN}3{Colors.RESET}. none - No specific SDK"
                    )

                    pt_choice = input(
                        f"\n{Colors.BRIGHT_CYAN}➤ Select (1-3, default=1): {Colors.RESET}"
                    ).strip()

                    if pt_choice == "2":
                        provider_type = "openai"
                    elif pt_choice == "3":
                        provider_type = "none"
                    else:
                        provider_type = "anthropic"

                # Create new model config
                provider_display = ModelProvider.get_display_name(selected_provider)
                new_config = ModelConfig.create(
                    name=model_name,
                    display_name=f"{provider_display} - {model_name}",
                    provider=selected_provider.value,
                    api_key=api_key,
                    base_url=base_url,
                    provider_type=provider_type,
                )

                # Save the configuration
                manager.add_model(new_config)
                manager.set_default_model(new_config.id)

                # Update LLM client
                llm_client.api_key = api_key
                llm_client.api_base = base_url
                llm_client.model = model_name
                provider_type = (
                    LLMProvider.ANTHROPIC
                    if selected_provider.value.lower() == "anthropic"
                    else LLMProvider.OPENAI
                )
                llm_client.provider = provider_type

                # Update Agent's system prompt to reflect new provider
                _update_agent_system_prompt(agent, selected_provider.value, model_name)

                print(f"\n{Colors.GREEN}✅ Model switched successfully!{Colors.RESET}")
                print(f"   {Colors.DIM}Provider: {provider_display}{Colors.RESET}")
                print(f"   {Colors.DIM}Model: {model_name}{Colors.RESET}")
                print(f"   {Colors.DIM}Base URL: {base_url}{Colors.RESET}\n")

            else:
                print(f"{Colors.RED}Invalid selection.{Colors.RESET}\n")
        except ValueError:
            print(f"{Colors.RED}Please enter a number.{Colors.RESET}\n")

    elif choice.isdigit() and int(choice) >= 2:
        # Select from saved models (options 2, 3, 4, ... correspond to models[0], models[1], models[2], ...)
        try:
            idx = int(choice) - 2  # choice 2 -> idx 0, choice 3 -> idx 1, etc.
            if 0 <= idx < len(models):
                selected = models[idx]

                # Update LLM client
                llm_client.api_key = selected.api_key
                llm_client.api_base = selected.base_url or ""
                llm_client.model = selected.name
                provider_type = (
                    LLMProvider.ANTHROPIC
                    if selected.provider.lower() == "anthropic"
                    else LLMProvider.OPENAI
                )
                llm_client.provider = provider_type

                # Set as default
                manager.set_default_model(selected.id)

                # Update Agent's system prompt to reflect new provider
                _update_agent_system_prompt(agent, selected.provider, selected.name)

                print(f"\n{Colors.GREEN}✅ Model switched successfully!{Colors.RESET}")
                print(f"   {Colors.DIM}Provider: {selected.provider}{Colors.RESET}")
                print(f"   {Colors.DIM}Model: {selected.name}{Colors.RESET}")
                if selected.base_url:
                    print(
                        f"   {Colors.DIM}Base URL: {selected.base_url}{Colors.RESET}\n"
                    )
                else:
                    print()
            else:
                print(f"{Colors.RED}Invalid selection.{Colors.RESET}\n")
        except ValueError:
            print(f"{Colors.RED}Please enter a number.{Colors.RESET}\n")


def _update_agent_system_prompt(agent: Agent, provider: str, model_name: str):
    """Update agent's system prompt to reflect the new model provider.

    Args:
        agent: The Agent instance
        provider: The provider name (e.g., "volcano", "openai", "minimax")
        model_name: The model name
    """
    # Provider display names for system prompt
    provider_names = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "deepseek": "DeepSeek",
        "minimax": "MiniMax",
        "qwen": "阿里云通义千问",
        "zhipu": "智谱AI",
        "volcano": "火山引擎",
        "moonshot": "月之暗面",
        "baichuan": "百川",
        "siliconflow": "硅基流动",
        "custom": "Custom",
    }

    provider_display = provider_names.get(provider.lower(), provider)

    # Update the first message (system prompt) if it exists
    if agent.messages and len(agent.messages) > 0:
        old_prompt = agent.messages[0].content
        if isinstance(old_prompt, str):
            # Replace provider references in the system prompt
            new_prompt = old_prompt

            # Replace common provider references
            replacements = [
                ("MiniMax", provider_display),
                ("minimax", provider.lower()),
                ("MiniMax M2.5", f"{provider_display} {model_name}"),
                ("MiniMax M2", f"{provider_display} {model_name}"),
            ]

            for old, new in replacements:
                new_prompt = new_prompt.replace(old, new)

            # Update the message
            agent.messages[0].content = new_prompt


def print_stats(agent: Agent, session_start: datetime):
    """Print session statistics"""
    duration = datetime.now() - session_start
    hours, remainder = divmod(int(duration.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    # Count different types of messages
    user_msgs = sum(1 for m in agent.messages if m.role == "user")
    assistant_msgs = sum(1 for m in agent.messages if m.role == "assistant")
    tool_msgs = sum(1 for m in agent.messages if m.role == "tool")

    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}Session Statistics:{Colors.RESET}")
    print(f"{Colors.DIM}{'─' * 40}{Colors.RESET}")
    print(f"  Session Duration: {hours:02d}:{minutes:02d}:{seconds:02d}")
    print(f"  Total Messages: {len(agent.messages)}")
    print(f"    - User Messages: {Colors.BRIGHT_GREEN}{user_msgs}{Colors.RESET}")
    print(
        f"    - Assistant Replies: {Colors.BRIGHT_BLUE}{assistant_msgs}{Colors.RESET}"
    )
    print(f"    - Tool Calls: {Colors.BRIGHT_YELLOW}{tool_msgs}{Colors.RESET}")
    print(f"  Available Tools: {len(agent.tools)}")
    if agent.api_total_tokens > 0:
        print(
            f"  API Tokens Used: {Colors.BRIGHT_MAGENTA}{agent.api_total_tokens:,}{Colors.RESET}"
        )
    print(f"{Colors.DIM}{'─' * 40}{Colors.RESET}\n")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Open Agent - AI assistant with file tools and MCP support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  open-agent                              # Use current directory as workspace
  open-agent-cli                          # Explicit CLI-only command
  open-agent --workspace /path/to/dir     # Use specific workspace directory
  open-agent log                          # Show log directory and recent files
  open-agent log agent_run_xxx.log        # Read a specific log file
  open-agent --cli-only                   # Run CLI only (same runtime as open-agent-cli)
        """,
    )
    parser.add_argument(
        "--workspace",
        "-w",
        type=str,
        default=None,
        help="Workspace directory (default: current directory)",
    )
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        default=None,
        help="Execute a task non-interactively and exit",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version="open-agent 0.1.0",
    )
    parser.add_argument(
        "--config",
        "-c",
        action="store_true",
        help="Compatibility flag; shared desktop configuration is always used",
    )
    parser.add_argument(
        "--cli-only",
        action="store_true",
        help="Run CLI only (no Web UI)",
    )
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Run Web UI only (no CLI)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically when Web UI starts",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=9998,
        help="Port for Web UI server (default: 9998)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for Web UI server (default: 127.0.0.1)",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # log subcommand
    log_parser = subparsers.add_parser(
        "log", help="Show log directory or read log files"
    )
    log_parser.add_argument(
        "filename",
        nargs="?",
        default=None,
        help="Log filename to read (optional, shows directory if omitted)",
    )

    return parser.parse_args()


async def initialize_base_tools(config: Config):
    """Initialize base tools (independent of workspace)

    These tools are loaded from package configuration and don't depend on workspace.
    Note: File tools are now workspace-dependent and initialized in add_workspace_tools()

    Args:
        config: Configuration object

    Returns:
        Tuple of (list of tools, skill loader if skills enabled)
    """

    tools = []
    skill_loader = None

    # 1. Bash auxiliary tools (output monitoring and kill)
    # Note: BashTool itself is created in add_workspace_tools() with workspace_dir as cwd
    if config.tools.enable_bash:
        bash_output_tool = BashOutputTool()
        tools.append(bash_output_tool)
        print(f"{Colors.GREEN}✅ Loaded Bash Output tool{Colors.RESET}")

        bash_kill_tool = BashKillTool()
        tools.append(bash_kill_tool)
        print(f"{Colors.GREEN}✅ Loaded Bash Kill tool{Colors.RESET}")

    # 3. Claude Skills (loaded from package directory)
    if config.tools.enable_skills:
        print(f"{Colors.BRIGHT_CYAN}Loading Claude Skills...{Colors.RESET}")
        try:
            # Resolve skills directory with priority search
            # Expand ~ to user home directory for portability
            skills_path = Path(config.tools.skills_dir).expanduser()

            if is_frozen():
                # When running as frozen executable, prioritize external skills directory
                external_skills = get_external_skills_dir()
                if external_skills:
                    skills_dir = str(external_skills)
                    print(
                        f"{Colors.DIM}  Using external skills directory: {external_skills}{Colors.RESET}"
                    )
                else:
                    # No external skills directory found
                    print(
                        f"{Colors.YELLOW}⚠️  Skills directory not found. Please create 'skills/' directory next to the executable.{Colors.RESET}"
                    )
                    skills_dir = None
            elif skills_path.is_absolute():
                skills_dir = str(skills_path)
            else:
                # Search in priority order:
                # 1. Current directory (dev mode: ./skills or ./open_agent/skills)
                # 2. Package directory (installed: site-packages/open_agent/skills)
                search_paths = [
                    skills_path,  # ./skills for backward compatibility
                    Path("open_agent") / skills_path,  # ./open_agent/skills
                    Config.get_package_dir()
                    / skills_path,  # site-packages/open_agent/skills
                ]

                # Find first existing path
                skills_dir = str(skills_path)  # default
                for path in search_paths:
                    if path.exists():
                        skills_dir = str(path.resolve())
                        break

            # Load skills if directory was found
            if skills_dir:
                skill_tools, skill_loader = create_skill_tools(skills_dir)
                if skill_tools:
                    tools.extend(skill_tools)
                    print(
                        f"{Colors.GREEN}✅ Loaded Skill tool (get_skill){Colors.RESET}"
                    )
                else:
                    print(f"{Colors.YELLOW}⚠️  No available Skills found{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.YELLOW}⚠️  Failed to load Skills: {e}{Colors.RESET}")

    # 4. MCP tools (loaded with priority search)
    if config.tools.enable_mcp:
        print(f"{Colors.BRIGHT_CYAN}Loading MCP tools...{Colors.RESET}")
        try:
            # Apply MCP timeout configuration from config.yaml
            mcp_config = config.tools.mcp
            set_mcp_timeout_config(
                connect_timeout=mcp_config.connect_timeout,
                execute_timeout=mcp_config.execute_timeout,
                sse_read_timeout=mcp_config.sse_read_timeout,
            )
            print(
                f"{Colors.DIM}  MCP timeouts: connect={mcp_config.connect_timeout}s, "
                f"execute={mcp_config.execute_timeout}s, sse_read={mcp_config.sse_read_timeout}s{Colors.RESET}"
            )

            # Use priority search for mcp.json
            mcp_config_path = Config.find_config_file(config.tools.mcp_config_path)
            if mcp_config_path:
                mcp_tools = await load_mcp_tools_async(str(mcp_config_path))
                if mcp_tools:
                    tools.extend(mcp_tools)
                    print(
                        f"{Colors.GREEN}✅ Loaded {len(mcp_tools)} MCP tools (from: {mcp_config_path}){Colors.RESET}"
                    )

                    # Add MCP Prompt tools (for querying MCP usage guides)
                    tools.append(ListMCPPromptsTool())
                    tools.append(GetMCPPromptTool())
                    print(
                        f"{Colors.GREEN}✅ Loaded MCP Prompt tools (list_mcp_prompts, get_mcp_prompt){Colors.RESET}"
                    )
                else:
                    print(
                        f"{Colors.YELLOW}⚠️  No available MCP tools found{Colors.RESET}"
                    )
            else:
                print(
                    f"{Colors.YELLOW}⚠️  MCP config file not found: {config.tools.mcp_config_path}{Colors.RESET}"
                )
        except Exception as e:
            print(f"{Colors.YELLOW}⚠️  Failed to load MCP tools: {e}{Colors.RESET}")

    print()  # Empty line separator
    return tools, skill_loader


def add_workspace_tools(tools: List[Tool], config: Config, workspace_dir: Path):
    """Add workspace-dependent tools

    These tools need to know the workspace directory.

    Args:
        tools: Existing tools list to add to
        config: Configuration object
        workspace_dir: Workspace directory path
    """
    # Ensure workspace directory exists
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Bash tool - needs workspace as cwd for command execution
    if config.tools.enable_bash:
        bash_tool = BashTool(workspace_dir=str(workspace_dir))
        tools.append(bash_tool)
        print(f"{Colors.GREEN}✅ Loaded Bash tool (cwd: {workspace_dir}){Colors.RESET}")

    # File tools - need workspace to resolve relative paths
    if config.tools.enable_file_tools:
        tools.extend(
            [
                ReadTool(workspace_dir=str(workspace_dir)),
                WriteTool(workspace_dir=str(workspace_dir)),
                EditTool(workspace_dir=str(workspace_dir)),
            ]
        )
        print(
            f"{Colors.GREEN}✅ Loaded file operation tools (workspace: {workspace_dir}){Colors.RESET}"
        )

    # Search tools - glob, grep, list_dir for workspace file operations
    if config.tools.enable_file_tools:
        tools.extend(
            [
                GlobTool(workspace_dir=str(workspace_dir)),
                GrepTool(workspace_dir=str(workspace_dir)),
                ListDirTool(workspace_dir=str(workspace_dir)),
            ]
        )
        print(
            f"{Colors.GREEN}✅ Loaded search tools (glob, grep, list_dir){Colors.RESET}"
        )

    # Memory tools - tree-structured memory storage with SQLite backend
    if config.tools.enable_note:
        tools.append(RecordNoteTool())
        tools.append(RecallNotesTool())
        tools.append(SearchMemoryTreeTool())
        tools.append(GetMemoryStatsTool())
        print(
            f"{Colors.GREEN}✅ Loaded memory tools (record_note, recall_notes, search_memory_tree, get_memory_stats){Colors.RESET}"
        )

    # Choice tool - for interactive tool selection when multiple options exist
    tools.append(AskUserChoiceTool(timeout=30))
    print(f"{Colors.GREEN}✅ Loaded choice tool (ask_user_choice){Colors.RESET}")

    # Web search tools - for searching and browsing the web (disabled by default)
    # Only load when enable_web_search is True in config
    if config.tools.enable_web_search:
        tools.append(WebSearchTool())
        tools.append(WebBrowseTool())
        print(
            f"{Colors.GREEN}✅ Loaded web search tools (web_search, web_browse){Colors.RESET}"
        )


async def _quiet_cleanup():
    """Clean up MCP connections, suppressing noisy asyncgen teardown tracebacks."""
    # Silence the asyncgen finalization noise that anyio/mcp emits when
    # stdio_client's task group is torn down across tasks.  The handler is
    # intentionally NOT restored: asyncgen finalization happens during
    # asyncio.run() shutdown (after run_agent returns), so restoring the
    # handler here would still let the noise through.  Since this runs
    # right before process exit, swallowing late exceptions is safe.
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(lambda _loop, _ctx: None)
    try:
        await cleanup_mcp_connections()
    except Exception:
        pass


async def run_agent(
    workspace_dir: Path,
    task: str = None,
):
    """Run Agent in interactive or non-interactive mode.

    Args:
        workspace_dir: Workspace directory path
        task: If provided, execute this task and exit (non-interactive mode)
    """
    session_start = datetime.now()
    startup_warnings: list[str] = []
    memory_count = 0

    # 1. Desktop and CLI share the same model configuration file.
    model_config = load_shared_model_config()
    if model_config is None:
        print(f"\n{Colors.BRIGHT_YELLOW}⚠️  未检测到默认模型配置{Colors.RESET}")
        print(
            f"{Colors.DIM}   桌面端和 CLI 共用 {get_user_config().CONFIG_FILE}{Colors.RESET}"
        )
        print()
        model_config = select_model()
        if model_config is None:
            print(f"{Colors.RED}❌ 未选择模型，无法启动 Agent{Colors.RESET}")
            return

    # 2. Initialize memory system (check database exists, create if not)
    print(f"\n{Colors.BRIGHT_CYAN}🔧 Initializing memory system...{Colors.RESET}")
    try:
        # Initialize memory manager first to get the memory_dir
        memory_manager = get_memory_manager()

        # Get the database path from the instance
        db_path = memory_manager.memory_dir / memory_manager.DB_FILE
        db_existed = db_path.exists()

        if not db_existed:
            print(
                f"{Colors.GREEN}✅ Created new memory database: {db_path}{Colors.RESET}"
            )
        else:
            stats = memory_manager.get_stats()
            memory_count = stats.get("total_memories", 0)
            print(f"{Colors.GREEN}✅ Memory database found: {db_path}{Colors.RESET}")
            print(f"   {Colors.DIM}Total memories: {memory_count}{Colors.RESET}")
    except Exception as e:
        startup_warnings.append(f"Memory initialization degraded: {e}")
        print(
            f"{Colors.YELLOW}⚠️  Failed to initialize memory system: {e}{Colors.RESET}"
        )

    # 3. Load configuration from package directory (for non-LLM settings)
    config_path = Config.get_default_config_path()

    # Create a default config if no config file exists
    if not config_path.exists():
        # Create minimal default config
        from open_agent.config import LLMConfig, AgentConfig, ToolsConfig, MCPConfig

        config = Config(
            llm=LLMConfig(
                api_key="placeholder",
                api_base="https://api.minimaxi.com",
                model="MiniMax-M2.5",
                provider="anthropic",
            ),
            agent=AgentConfig(
                max_steps=100,
                workspace_dir="./workspace",
                system_prompt_path="system_prompt.md",
            ),
            tools=ToolsConfig(
                enable_file_tools=True,
                enable_bash=True,
                enable_note=True,
                enable_skills=True,
                skills_dir="./skills",
                enable_mcp=True,
                mcp_config_path="mcp.json",
                mcp=MCPConfig(),
            ),
        )
        print(
            f"{Colors.YELLOW}⚠️  No config file found, using model selection settings{Colors.RESET}"
        )
    else:
        try:
            config = Config.from_yaml(config_path)
        except FileNotFoundError:
            print(
                f"{Colors.RED}❌ Error: Configuration file not found: {config_path}{Colors.RESET}"
            )
            return
        except ValueError as e:
            print(f"{Colors.RED}❌ Error: {e}{Colors.RESET}")
            print(
                f"{Colors.YELLOW}Please check the configuration file format{Colors.RESET}"
            )
            return
        except Exception as e:
            print(
                f"{Colors.RED}❌ Error: Failed to load configuration file: {e}{Colors.RESET}"
            )
            return

    # 3. Initialize LLM client
    from open_agent.retry import RetryConfig as RetryConfigBase

    # Convert configuration format
    retry_config = RetryConfigBase(
        enabled=config.llm.retry.enabled,
        max_retries=config.llm.retry.max_retries,
        initial_delay=config.llm.retry.initial_delay,
        max_delay=config.llm.retry.max_delay,
        exponential_base=config.llm.retry.exponential_base,
        retryable_exceptions=(Exception,),
    )

    # Create retry callback function to display retry information in terminal
    def on_retry(exception: Exception, attempt: int):
        """Retry callback function to display retry information"""
        print(
            f"\n{Colors.BRIGHT_YELLOW}⚠️  LLM call failed (attempt {attempt}): {str(exception)}{Colors.RESET}"
        )
        next_delay = retry_config.calculate_delay(attempt - 1)
        print(
            f"{Colors.DIM}   Retrying in {next_delay:.1f}s (attempt {attempt + 1})...{Colors.RESET}"
        )

    api_key = model_config.api_key
    api_base = model_config.base_url or ""
    model = model_config.name
    provider = (
        LLMProvider.ANTHROPIC
        if model_config.provider_type.lower() == "anthropic"
        else LLMProvider.OPENAI
    )
    provider_display = model_config.provider

    print(f"\n{Colors.GREEN}✅ Using shared desktop model configuration:{Colors.RESET}")
    print(f"   {Colors.DIM}Config: {get_user_config().CONFIG_FILE}{Colors.RESET}")
    print(f"   {Colors.DIM}Provider: {model_config.provider}{Colors.RESET}")
    print(f"   {Colors.DIM}Model: {model}{Colors.RESET}")
    if api_base:
        print(f"   {Colors.DIM}Base URL: {api_base}{Colors.RESET}")

    llm_client = LLMClient(
        api_key=api_key,
        provider=provider,
        api_base=api_base,
        model=model,
        retry_config=retry_config if config.llm.retry.enabled else None,
    )

    # Set retry callback
    if config.llm.retry.enabled:
        llm_client.retry_callback = on_retry
        print(
            f"{Colors.GREEN}✅ LLM retry mechanism enabled (max {config.llm.retry.max_retries} retries){Colors.RESET}"
        )

    # 3. Initialize base tools (independent of workspace)
    tools, skill_loader = await initialize_base_tools(config)

    # 4. Add workspace-dependent tools
    add_workspace_tools(tools, config, workspace_dir)

    # 5. Load System Prompt (with priority search)
    system_prompt_path = Config.find_config_file(config.agent.system_prompt_path)
    if system_prompt_path and system_prompt_path.exists():
        system_prompt = system_prompt_path.read_text(encoding="utf-8")
        print(
            f"{Colors.GREEN}✅ Loaded system prompt (from: {system_prompt_path}){Colors.RESET}"
        )
    else:
        system_prompt = "You are open-agent, an intelligent assistant powered by MiniMax M2.5 that can help users complete various tasks."
        startup_warnings.append("System prompt missing; built-in fallback is active")
        print(f"{Colors.YELLOW}⚠️  System prompt not found, using default{Colors.RESET}")

    # 6. Inject Skills Metadata into System Prompt (Progressive Disclosure - Level 1)
    if skill_loader:
        skills_metadata = skill_loader.get_skills_metadata_prompt()
        if skills_metadata:
            # Replace placeholder with actual metadata
            system_prompt = system_prompt.replace("{SKILLS_METADATA}", skills_metadata)
            print(
                f"{Colors.GREEN}✅ Injected {len(skill_loader.loaded_skills)} skills metadata into system prompt{Colors.RESET}"
            )
        else:
            # Remove placeholder if no skills
            system_prompt = system_prompt.replace("{SKILLS_METADATA}", "")
    else:
        # Remove placeholder if skills not enabled
        system_prompt = system_prompt.replace("{SKILLS_METADATA}", "")

    # 7. Create Agent
    agent = Agent(
        llm_client=llm_client,
        system_prompt=system_prompt,
        tools=tools,
        max_steps=config.agent.max_steps,
        workspace_dir=str(workspace_dir),
        terminal_ui=not bool(task),
    )
    launch_metadata = _apply_cli_launch_context(agent, workspace_dir)

    # 7.3 Register CLI Agent to AgentService (so Web UI can see it)
    cli_agent_id = f"cli_agent_{id(agent)}"
    try:
        from open_agent.agent_service import get_agent_service

        service = get_agent_service()
        # 直接注册 Agent 实例到服务
        service._agents[cli_agent_id] = agent
        import datetime as dt_module

        service._agent_info[cli_agent_id] = type(
            "AgentInfo",
            (),
            {
                "agent_id": cli_agent_id,
                "agent_type": "cli",
                "status": "idle",
                "created_at": dt_module.datetime.now().isoformat(),
                "name": "CLI Agent",
                "description": "Terminal interactive agent",
                "model": model,
                "provider": "CLI",
                "message_count": 0,
                "metadata": launch_metadata,
                "to_dict": lambda self: {
                    "agent_id": self.agent_id,
                    "agent_type": self.agent_type,
                    "status": self.status,
                    "created_at": self.created_at,
                    "name": self.name,
                    "description": self.description,
                    "model": self.model,
                    "provider": self.provider,
                    "message_count": self.message_count,
                    "metadata": self.metadata,
                },
            },
        )()
        service._sessions[cli_agent_id] = type(
            "AgentSession",
            (),
            {
                "agent_id": cli_agent_id,
                "messages": agent.messages,
                "system_prompt": system_prompt,
                "updated_at": dt_module.datetime.now().isoformat(),
            },
        )()
        print(
            f"{Colors.GREEN}✅ Registered CLI Agent to AgentService (ID: {cli_agent_id}){Colors.RESET}"
        )
    except Exception as e:
        startup_warnings.append(f"Desktop agent registry unavailable: {e}")
        print(
            f"{Colors.YELLOW}⚠️  Failed to register CLI Agent to AgentService: {e}{Colors.RESET}"
        )

    # 7.5 Enable automatic log memory compression
    agent.enable_log_memory(True)

    # 7.6 Initialize Task Dispatcher for async task execution
    task_dispatcher = create_task_dispatcher(
        max_workers=3,
        workspace_dir=workspace_dir,
    )
    task_dispatcher.initialize(main_agent=agent)
    print(f"{Colors.GREEN}✅ Task Queue system initialized{Colors.RESET}")
    print(f"   {Colors.DIM}Tasks run asynchronously without blocking UI{Colors.RESET}")

    # 7.7 Load relevant memories and inject into context
    try:
        memory_manager = get_memory_manager()

        # Get recent memories (last 7 days)
        recent_memories = memory_manager.recall(time_range="week", limit=20)
        memory_count = max(memory_count, len(recent_memories))

        if recent_memories:
            # Build memory context
            memory_context = "\n\n## Recent Memories (Last 7 Days)\n"
            memory_context += "Here are some relevant memories from previous sessions that might help with current tasks:\n\n"

            for mem in recent_memories[:10]:  # Limit to 10 most recent
                # Truncate long content
                content_preview = (
                    mem.content[:300] + "..." if len(mem.content) > 300 else mem.content
                )
                memory_context += (
                    f"### {mem.timestamp[:10]} ({mem.category})\n{content_preview}\n\n"
                )

            # Inject into agent's system prompt (update first message)
            if agent.messages and len(agent.messages) > 0:
                original_prompt = agent.messages[0].content
                if isinstance(original_prompt, str):
                    # Append memories to system prompt
                    agent.messages[0].content = original_prompt + memory_context

            print(
                f"{Colors.GREEN}✅ Loaded {len(recent_memories[:10])} recent memories into context{Colors.RESET}"
            )
        else:
            print(
                f"{Colors.DIM}ℹ️  No recent memories found (first run or memories expired){Colors.RESET}"
            )

    except Exception as e:
        startup_warnings.append(f"Recent memory recall unavailable: {e}")
        print(f"{Colors.YELLOW}⚠️  Failed to load memories: {e}{Colors.RESET}")

    # 8. Initialize config watcher for auto-reload detection
    config_watcher = get_config_watcher()
    mcp_config_path = Config.find_config_file(config.tools.mcp_config_path)
    skills_dir = None
    if config.tools.enable_skills:
        skills_path = Path(config.tools.skills_dir).expanduser()
        if is_frozen():
            external_skills = get_external_skills_dir()
            if external_skills:
                skills_dir = external_skills
        elif skills_path.is_absolute():
            skills_dir = skills_path
        else:
            search_paths = [
                skills_path,
                Path("open_agent") / skills_path,
                Config.get_package_dir() / skills_path,
            ]
            for path in search_paths:
                if path.exists():
                    skills_dir = path.resolve()
                    break
    config_watcher.initialize(mcp_config_path, skills_dir)

    # 9. Display welcome information
    def session_overview() -> SessionOverview:
        mcp_tool_count = sum(
            1
            for tool in agent.tools.values()
            if "mcp" in tool.__class__.__module__.lower()
        )
        skill_count = len(skill_loader.loaded_skills) if skill_loader else 0
        active_model = get_user_config().get_default_model()
        return SessionOverview(
            model=llm_client.model,
            provider=active_model.provider if active_model else provider_display,
            workspace=workspace_dir,
            tool_count=len(agent.tools),
            mcp_tool_count=mcp_tool_count,
            skill_count=skill_count,
            memory_count=memory_count,
            session_id=launch_metadata["session_id"],
            warnings=tuple(startup_warnings),
        )

    if not task:
        print_welcome(session_overview())

    # 8.5 Non-interactive mode: execute task and exit
    if task:
        print(
            f"\n{Colors.BRIGHT_BLUE}Agent{Colors.RESET} {Colors.DIM}›{Colors.RESET} {Colors.DIM}Executing task...{Colors.RESET}\n"
        )
        agent.add_user_message(task)
        try:
            await agent.run()
        except Exception as e:
            print(f"\n{Colors.RED}❌ Error: {e}{Colors.RESET}")
        finally:
            print_stats(agent, session_start)

        # Cleanup MCP connections
        await _quiet_cleanup()
        return

    # 9. Setup prompt_toolkit session
    command_completer = SlashCommandCompleter()

    prompt_style = Style.from_dict(PROMPT_STYLE)

    # Custom key bindings
    kb = KeyBindings()

    @kb.add("c-u")  # Ctrl+U: Clear current line
    def _(event):
        """Clear the current input line"""
        event.current_buffer.reset()

    @kb.add("c-l")  # Ctrl+L: Clear screen (optional bonus)
    def _(event):
        """Clear the screen"""
        event.app.renderer.clear()

    @kb.add("c-j")  # Ctrl+J (对应 Ctrl+Enter)
    def _(event):
        """Insert a newline"""
        event.current_buffer.insert_text("\n")

    @kb.add("/")
    def _(event):
        """Insert slash and immediately expose the command palette."""
        buffer = event.current_buffer
        buffer.insert_text("/")
        if buffer.text.startswith("/"):
            buffer.start_completion(select_first=False)

    # Create prompt session with history and auto-suggest
    # Use FileHistory for persistent history across sessions (stored in user's home directory)
    history_file = Path.home() / ".open-agent" / ".history"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    session = create_cli_prompt_session(
        history_file=history_file,
        completer=command_completer,
        style=prompt_style,
        key_bindings=kb,
    )

    def runtime_status() -> RuntimeStatus:
        try:
            running_tasks = len(task_dispatcher.get_running_tasks())
            pending_tasks = len(task_dispatcher.get_pending_tasks())
        except Exception:
            running_tasks = 0
            pending_tasks = 0
        return RuntimeStatus(
            model=llm_client.model,
            workspace=workspace_dir,
            message_count=len(agent.messages),
            tool_count=len(agent.tools),
            started_at=session_start,
            running_tasks=running_tasks,
            pending_tasks=pending_tasks,
        )

    # 10. Interactive loop
    while True:
        try:
            # Check for configuration changes before each prompt
            mcp_changed, skills_changed = config_watcher.check_for_changes()
            if mcp_changed or skills_changed:
                print(
                    f"\n{Colors.BOLD}{Colors.BRIGHT_YELLOW}🔄 Configuration Change Detected!{Colors.RESET}"
                )
                if mcp_changed:
                    print(
                        f"   {Colors.DIM}• MCP config updated: {mcp_config_path}{Colors.RESET}"
                    )
                if skills_changed:
                    print(
                        f"   {Colors.DIM}• Skills directory updated: {skills_dir}{Colors.RESET}"
                    )
                print(
                    f"\n   {Colors.BRIGHT_GREEN}Auto-reloading configuration...{Colors.RESET}"
                )

                # Auto-reload MCP tools
                reload_count = 0
                if mcp_changed and config.tools.enable_mcp and mcp_config_path:
                    new_mcp_tools = await reload_mcp_tools(mcp_config_path)
                    for tool in new_mcp_tools:
                        agent.tools[tool.name] = tool
                    reload_count += len(new_mcp_tools)

                # Auto-reload Skills
                if skills_changed and config.tools.enable_skills and skills_dir:
                    new_skill_tools, new_skill_loader = reload_skills(skills_dir)
                    for tool in new_skill_tools:
                        agent.tools[tool.name] = tool

                    # Update system prompt with new skills metadata
                    if new_skill_loader:
                        skills_metadata = new_skill_loader.get_skills_metadata_prompt()
                        if agent.messages and len(agent.messages) > 0:
                            old_prompt = agent.messages[0].content
                            if isinstance(old_prompt, str):
                                new_prompt = old_prompt
                                if "{SKILLS_METADATA}" in new_prompt:
                                    new_prompt = new_prompt.replace(
                                        "{SKILLS_METADATA}", skills_metadata or ""
                                    )
                                elif skills_metadata:
                                    new_prompt += "\n\n" + skills_metadata
                                agent.messages[0].content = new_prompt
                    reload_count += len(new_skill_tools)

                print(
                    f"   {Colors.GREEN}✅ Reloaded {reload_count} tools{Colors.RESET}"
                )
                print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}\n")

            # Get user input using prompt_toolkit
            user_input = await session.prompt_async(
                build_prompt_fragments(),
                multiline=False,
                bottom_toolbar=lambda: build_status_fragments(runtime_status()),
            )
            user_input = user_input.strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                parsed_command = parse_command(user_input)
                if parsed_command is None:
                    print(f"{Colors.RED}❌ Unknown command: {user_input}{Colors.RESET}")
                    print(
                        f"{Colors.DIM}Type / to browse commands or /help for the full index{Colors.RESET}\n"
                    )
                    continue

                command = parsed_command.spec.name
                command_args = parsed_command.args

                if command == "quit":
                    print(
                        f"\n{Colors.BRIGHT_YELLOW}👋 Goodbye! Thanks for using Open Agent{Colors.RESET}\n"
                    )
                    print_stats(agent, session_start)
                    break

                elif command == "help":
                    print_help()
                    continue

                elif command == "new":
                    # Clear message history but keep system prompt
                    old_count = len(agent.messages)
                    agent.messages = [agent.messages[0]]  # Keep only system message
                    print(
                        f"{Colors.GREEN}✅ Cleared {old_count - 1} messages, starting new session{Colors.RESET}\n"
                    )
                    continue

                elif command == "history":
                    messages = [m for m in agent.messages if m.role != "system"]
                    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}Conversation History{Colors.RESET}")
                    print(f"{Colors.DIM}{'─' * 72}{Colors.RESET}")
                    if not messages:
                        print(f"  {Colors.DIM}No conversation messages yet.{Colors.RESET}")
                    for message in messages[-20:]:
                        content = message.content
                        if not isinstance(content, str):
                            content = str(content)
                        preview = " ".join(content.split())
                        if len(preview) > 100:
                            preview = preview[:97] + "..."
                        role = message.role.upper()
                        role_color = (
                            Colors.BRIGHT_BLUE if message.role == "user" else Colors.BRIGHT_GREEN
                        )
                        print(f"  {role_color}{role:<10}{Colors.RESET}{preview}")
                    if len(messages) > 20:
                        print(f"  {Colors.DIM}Showing the latest 20 of {len(messages)} messages.{Colors.RESET}")
                    print()
                    continue

                elif command == "retry":
                    user_indexes = [
                        index
                        for index, message in enumerate(agent.messages)
                        if message.role == "user"
                    ]
                    if not user_indexes:
                        print(f"\n{Colors.YELLOW}No user message is available to retry.{Colors.RESET}\n")
                        continue
                    retry_index = user_indexes[-1]
                    retry_content = agent.messages[retry_index].content
                    user_input = retry_content if isinstance(retry_content, str) else str(retry_content)
                    agent.messages = agent.messages[:retry_index]
                    print(f"\n{Colors.BRIGHT_CYAN}Retrying the last user message...{Colors.RESET}")

                elif command == "undo":
                    try:
                        turn_count = int(command_args or "1")
                        if turn_count < 1:
                            raise ValueError
                    except ValueError:
                        print(f"\n{Colors.RED}Usage: /undo [positive number]{Colors.RESET}\n")
                        continue
                    user_indexes = [
                        index
                        for index, message in enumerate(agent.messages)
                        if message.role == "user"
                    ]
                    if not user_indexes:
                        print(f"\n{Colors.YELLOW}No user turns are available to undo.{Colors.RESET}\n")
                        continue
                    actual_count = min(turn_count, len(user_indexes))
                    agent.messages = agent.messages[: user_indexes[-actual_count]]
                    print(
                        f"\n{Colors.GREEN}Removed {actual_count} conversation turn"
                        f"{'s' if actual_count != 1 else ''}.{Colors.RESET}\n"
                    )
                    continue

                elif command == "redraw":
                    print_welcome(session_overview())
                    continue

                elif command == "status":
                    print_stats(agent, session_start)
                    running_count = len(task_dispatcher.get_running_tasks())
                    pending_count = len(task_dispatcher.get_pending_tasks())
                    print(f"  {Colors.DIM}Workspace:{Colors.RESET} {workspace_dir}")
                    print(
                        f"  {Colors.DIM}Task queue:{Colors.RESET} "
                        f"{running_count} running, {pending_count} pending\n"
                    )
                    continue

                elif command == "reload":
                    # Reload MCP and Skills configuration
                    print(
                        f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}🔄 Reloading Configuration...{Colors.RESET}"
                    )
                    print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")

                    shared_model = load_shared_model_config()
                    model_changed = False
                    if shared_model is not None:
                        next_provider = (
                            LLMProvider.ANTHROPIC
                            if shared_model.provider_type.lower() == "anthropic"
                            else LLMProvider.OPENAI
                        )
                        model_changed = any(
                            (
                                llm_client.model != shared_model.name,
                                llm_client.api_base != (shared_model.base_url or ""),
                                llm_client.provider != next_provider,
                            )
                        )
                        llm_client.api_key = shared_model.api_key
                        llm_client.api_base = shared_model.base_url or ""
                        llm_client.model = shared_model.name
                        llm_client.provider = next_provider
                        model = shared_model.name
                        provider_display = shared_model.provider
                        _update_agent_system_prompt(
                            agent,
                            shared_model.provider,
                            shared_model.name,
                        )

                    # Get config paths
                    mcp_config_path = Config.find_config_file(
                        config.tools.mcp_config_path
                    )
                    skills_dir = None
                    if config.tools.enable_skills:
                        skills_path = Path(config.tools.skills_dir).expanduser()
                        if is_frozen():
                            external_skills = get_external_skills_dir()
                            if external_skills:
                                skills_dir = external_skills
                        elif skills_path.is_absolute():
                            skills_dir = skills_path
                        else:
                            search_paths = [
                                skills_path,
                                Path("open_agent") / skills_path,
                                Config.get_package_dir() / skills_path,
                            ]
                            for path in search_paths:
                                if path.exists():
                                    skills_dir = path.resolve()
                                    break

                    reload_count = 0

                    # Reload MCP tools
                    if config.tools.enable_mcp and mcp_config_path:
                        new_mcp_tools = await reload_mcp_tools(mcp_config_path)
                        # Update agent's tools
                        for tool in new_mcp_tools:
                            agent.tools[tool.name] = tool
                        reload_count += len(new_mcp_tools)

                    # Reload Skills
                    if config.tools.enable_skills and skills_dir:
                        new_skill_tools, new_skill_loader = reload_skills(skills_dir)
                        # Update agent's tools
                        for tool in new_skill_tools:
                            agent.tools[tool.name] = tool

                        # Update system prompt with new skills metadata
                        if new_skill_loader:
                            skills_metadata = (
                                new_skill_loader.get_skills_metadata_prompt()
                            )
                            if agent.messages and len(agent.messages) > 0:
                                old_prompt = agent.messages[0].content
                                if isinstance(old_prompt, str):
                                    # Update skills metadata in system prompt
                                    new_prompt = old_prompt
                                    if "{SKILLS_METADATA}" in new_prompt:
                                        new_prompt = new_prompt.replace(
                                            "{SKILLS_METADATA}", skills_metadata or ""
                                        )
                                    else:
                                        # Append skills metadata if placeholder not found
                                        if skills_metadata:
                                            new_prompt += "\n\n" + skills_metadata
                                    agent.messages[0].content = new_prompt

                        reload_count += len(new_skill_tools)

                    print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")
                    print(
                        f"{Colors.GREEN}✅ Reload complete! {reload_count} tools available.{Colors.RESET}\n"
                    )
                    if model_changed:
                        print(
                            f"{Colors.GREEN}✅ Shared desktop model reloaded: "
                            f"{shared_model.provider}/{shared_model.name}{Colors.RESET}\n"
                        )
                    continue

                elif command == "model":
                    # Switch model provider or model
                    await handle_switch_model(agent, llm_client, config)
                    continue

                elif command == "config":
                    active_model = get_user_config().get_default_model()
                    resolved_mcp_path = Config.find_config_file(
                        config.tools.mcp_config_path
                    )
                    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}Active Configuration{Colors.RESET}")
                    print(f"{Colors.DIM}{'─' * 72}{Colors.RESET}")
                    print(f"  Model       {llm_client.model}")
                    print(
                        f"  Provider    "
                        f"{active_model.provider if active_model else provider_display}"
                    )
                    print(
                        f"  API base    "
                        f"{(active_model.base_url if active_model else llm_client.api_base) or '(SDK default)'}"
                    )
                    print(f"  Workspace   {workspace_dir}")
                    print(f"  User config {get_user_config().CONFIG_FILE}")
                    print(f"  MCP config  {resolved_mcp_path or '(not found)'}")
                    print(
                        f"  Features    MCP={'on' if config.tools.enable_mcp else 'off'}, "
                        f"skills={'on' if config.tools.enable_skills else 'off'}\n"
                    )
                    continue

                elif command == "doctor":
                    active_model = get_user_config().get_default_model()
                    if active_model is None:
                        print(f"\n{Colors.RED}No default model is configured.{Colors.RESET}\n")
                        continue
                    from open_agent.provider_registry import get_provider_registry

                    print(
                        f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}Provider Doctor{Colors.RESET} "
                        f"{Colors.DIM}testing {active_model.provider}/{active_model.name}...{Colors.RESET}"
                    )
                    report = await get_provider_registry().test_model_config(active_model)
                    for check_name, check in report.get("checks", {}).items():
                        check_status = check.get("status", "warning")
                        icon = "OK" if check_status == "ok" else "WARN" if check_status == "warning" else "FAIL"
                        color = (
                            Colors.GREEN
                            if check_status == "ok"
                            else Colors.YELLOW
                            if check_status == "warning"
                            else Colors.RED
                        )
                        print(
                            f"  {color}{icon:<4}{Colors.RESET} "
                            f"{check_name:<14}{check.get('message', '')}"
                        )
                    latency = report.get("latency_ms")
                    if latency is not None:
                        print(f"  {Colors.DIM}Latency: {latency} ms{Colors.RESET}")
                    print()
                    continue

                elif command == "workspace":
                    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}Workspace{Colors.RESET}")
                    print(f"  Path     {workspace_dir}")
                    print(f"  Session  {launch_metadata['session_id']}")
                    print(f"  Profile  {launch_metadata['profile_id']}")
                    print(f"  Source   {launch_metadata['launch_source']}\n")
                    continue

                elif command == "logs":
                    if not command_args:
                        show_log_directory(open_file_manager=True)
                    else:
                        filename = command_args.strip("\"'")
                        read_log_file(filename)
                    continue

                elif command == "tools":
                    filter_text = command_args.lower()
                    tool_names = sorted(
                        name
                        for name in agent.tools
                        if not filter_text or filter_text in name.lower()
                    )
                    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}Loaded Tools{Colors.RESET}")
                    print(f"{Colors.DIM}{'─' * 72}{Colors.RESET}")
                    for name in tool_names:
                        tool = agent.tools[name]
                        source = tool.__class__.__module__
                        print(f"  {Colors.BRIGHT_GREEN}{name:<28}{Colors.RESET}{Colors.DIM}{source}{Colors.RESET}")
                    if not tool_names:
                        print(f"  {Colors.DIM}No tools match '{command_args}'.{Colors.RESET}")
                    print(f"\n  {Colors.DIM}{len(tool_names)} tool(s) shown.{Colors.RESET}\n")
                    continue

                elif command == "skills":
                    loaded_skills = skill_loader.loaded_skills if skill_loader else {}
                    filter_text = command_args.lower()
                    skill_names = sorted(
                        name
                        for name in loaded_skills
                        if not filter_text or filter_text in name.lower()
                    )
                    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}Loaded Skills{Colors.RESET}")
                    print(f"{Colors.DIM}{'─' * 72}{Colors.RESET}")
                    for name in skill_names:
                        skill = loaded_skills[name]
                        description = " ".join((skill.description or "").split())
                        if len(description) > 70:
                            description = description[:67] + "..."
                        print(f"  {Colors.BRIGHT_GREEN}{name}{Colors.RESET}")
                        if description:
                            print(f"    {Colors.DIM}{description}{Colors.RESET}")
                    if not skill_names:
                        suffix = f" matching '{command_args}'" if command_args else ""
                        print(f"  {Colors.DIM}No loaded skills{suffix}.{Colors.RESET}")
                    print(f"\n  {Colors.DIM}{len(skill_names)} skill(s) shown.{Colors.RESET}\n")
                    continue

                elif command == "mcp":
                    resolved_mcp_path = Config.find_config_file(
                        config.tools.mcp_config_path
                    )
                    mcp_tools = sorted(
                        name
                        for name, tool in agent.tools.items()
                        if "mcp" in tool.__class__.__module__.lower()
                    )
                    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}MCP Runtime{Colors.RESET}")
                    print(f"  Config   {resolved_mcp_path or '(not found)'}")
                    print(f"  Enabled  {'yes' if config.tools.enable_mcp else 'no'}")
                    print(f"  Tools    {len(mcp_tools)}")
                    for name in mcp_tools:
                        print(f"    {Colors.BRIGHT_GREEN}{name}{Colors.RESET}")
                    print()
                    continue

                elif command == "memory":
                    try:
                        memory_stats = get_memory_manager().get_stats()
                    except Exception as exc:
                        print(f"\n{Colors.RED}Unable to read memory statistics: {exc}{Colors.RESET}\n")
                        continue
                    print(f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}Memory Store{Colors.RESET}")
                    print(f"  Database   {memory_stats.get('db_path', '(unknown)')}")
                    print(f"  Memories   {memory_stats.get('total_memories', 0)}")
                    print(f"  Keywords   {memory_stats.get('unique_keywords', 0)}")
                    categories = memory_stats.get("by_category", {})
                    if categories:
                        summary = ", ".join(
                            f"{name}: {count}" for name, count in sorted(categories.items())
                        )
                        print(f"  Categories {summary}")
                    print()
                    continue

                elif command == "version":
                    print(f"\n{Colors.BRIGHT_CYAN}OpenAgentSeal {__version__}{Colors.RESET}\n")
                    continue

                elif command == "agents":
                    # Show task queue status
                    tasks = task_dispatcher.get_all_tasks()
                    running = task_dispatcher.get_running_tasks()
                    pending = task_dispatcher.get_pending_tasks()
                    completed = task_dispatcher.get_completed_tasks()

                    print(
                        f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}📋 任务队列状态{Colors.RESET}"
                    )
                    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")
                    print(
                        f"  {Colors.GREEN}运行中: {len(running)}{Colors.RESET}  {Colors.YELLOW}等待中: {len(pending)}{Colors.RESET}  {Colors.DIM}已完成: {len(completed)}{Colors.RESET}"
                    )
                    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")

                    # Show running tasks
                    if running:
                        print(f"\n  {Colors.BOLD}{Colors.GREEN}▶️ 运行中{Colors.RESET}")
                        for task in running:
                            elapsed = task.get_elapsed_time()
                            status_msg = task.get_status_message()
                            print(
                                f"    {Colors.BRIGHT_WHITE}{task.task_id}{Colors.RESET}"
                            )
                            print(
                                f"      {Colors.DIM}输入: {task.user_input[:50]}{'...' if len(task.user_input) > 50 else ''}{Colors.RESET}"
                            )
                            print(f"      {Colors.DIM}状态: {status_msg}{Colors.RESET}")
                            print(
                                f"      {Colors.DIM}耗时: {elapsed:.1f}s{Colors.RESET}"
                            )

                    # Show pending tasks
                    if pending:
                        print(
                            f"\n  {Colors.BOLD}{Colors.YELLOW}⏳ 等待中{Colors.RESET}"
                        )
                        for task in pending[:5]:  # Show max 5
                            print(
                                f"    {Colors.DIM}{task.task_id}: {task.user_input[:40]}{'...' if len(task.user_input) > 40 else ''}{Colors.RESET}"
                            )
                        if len(pending) > 5:
                            print(
                                f"    {Colors.DIM}... 还有 {len(pending) - 5} 个任务{Colors.RESET}"
                            )

                    # Show recent completed
                    if completed:
                        print(f"\n  {Colors.BOLD}{Colors.DIM}✅ 最近完成{Colors.RESET}")
                        for task in completed[-3:]:  # Show last 3
                            status_icon = (
                                "✅" if task.status == TaskStatus.COMPLETED else "❌"
                            )
                            print(
                                f"    {status_icon} {Colors.DIM}{task.task_id}: {task.user_input[:40]}{'...' if len(task.user_input) > 40 else ''}{Colors.RESET}"
                            )

                    if not tasks:
                        print(f"\n  {Colors.DIM}暂无任务{Colors.RESET}")
                        print(
                            f"  {Colors.DIM}输入任务内容，系统将自动异步执行{Colors.RESET}"
                        )

                    print(f"\n  {Colors.DIM}使用 /task <id> 查看详情{Colors.RESET}")
                    print(f"  {Colors.DIM}使用 /cancel <id> 取消任务{Colors.RESET}\n")
                    continue

                elif command == "task":
                    # Show specific task details
                    if not command_args:
                        print(
                            f"\n{Colors.RED}❌ Usage: /task <task_id>{Colors.RESET}\n"
                        )
                        continue

                    task_id = command_args
                    task = task_dispatcher.get_task(task_id)

                    if not task:
                        # Try partial match
                        all_tasks = task_dispatcher.get_all_tasks()
                        matches = [
                            t for t in all_tasks if t.task_id.startswith(task_id)
                        ]
                        if len(matches) == 1:
                            task = matches[0]
                        elif len(matches) > 1:
                            print(
                                f"\n{Colors.YELLOW}⚠️  多个任务匹配 '{task_id}':{Colors.RESET}"
                            )
                            for m in matches:
                                print(f"   {Colors.DIM}- {m.task_id}{Colors.RESET}")
                            print()
                            continue
                        else:
                            print(
                                f"\n{Colors.RED}❌ 任务 '{task_id}' 不存在{Colors.RESET}\n"
                            )
                            continue

                    # Display task details
                    print(
                        f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}📋 任务详情{Colors.RESET}"
                    )
                    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")
                    print(f"  {Colors.BRIGHT_WHITE}ID:{Colors.RESET} {task.task_id}")
                    print(f"  {Colors.BRIGHT_WHITE}状态:{Colors.RESET} ", end="")

                    status_colors = {
                        TaskStatus.PENDING: Colors.DIM,
                        TaskStatus.QUEUED: Colors.YELLOW,
                        TaskStatus.RUNNING: Colors.GREEN,
                        TaskStatus.PAUSED: Colors.YELLOW,
                        TaskStatus.COMPLETED: Colors.BRIGHT_GREEN,
                        TaskStatus.FAILED: Colors.RED,
                        TaskStatus.CANCELLED: Colors.DIM,
                    }
                    status_color = status_colors.get(task.status, Colors.DIM)
                    print(f"{status_color}{task.status.value}{Colors.RESET}")

                    print(f"  {Colors.BRIGHT_WHITE}原始输入:{Colors.RESET}")
                    print(f"    {Colors.DIM}{task.user_input}{Colors.RESET}")

                    if task.status == TaskStatus.RUNNING:
                        print(
                            f"  {Colors.BRIGHT_WHITE}当前状态:{Colors.RESET} {task.get_status_message()}"
                        )
                        print(
                            f"  {Colors.BRIGHT_WHITE}已耗时:{Colors.RESET} {task.get_elapsed_time():.1f}s"
                        )
                        if task.progress.total_steps > 0:
                            pct = task.progress.percentage
                            print(
                                f"  {Colors.BRIGHT_WHITE}进度:{Colors.RESET} {pct:.0f}%"
                            )

                    if task.result:
                        print(f"\n  {Colors.BRIGHT_WHITE}结果:{Colors.RESET}")
                        if task.result.success:
                            result_text = task.result.content[:300]
                            print(
                                f"    {Colors.GREEN}{result_text}{'...' if len(task.result.content) > 300 else ''}{Colors.RESET}"
                            )
                        else:
                            print(
                                f"    {Colors.RED}❌ {task.result.error}{Colors.RESET}"
                            )

                    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}\n")
                    continue

                elif command == "cancel":
                    # Cancel a task
                    if not command_args:
                        print(
                            f"\n{Colors.RED}❌ Usage: /cancel <task_id>{Colors.RESET}\n"
                        )
                        continue

                    task_id = command_args
                    success = task_dispatcher.cancel_task(task_id, "Cancelled by user")

                    if success:
                        print(
                            f"\n{Colors.GREEN}✅ 任务 '{task_id}' 已取消{Colors.RESET}\n"
                        )
                    else:
                        print(
                            f"\n{Colors.RED}❌ 无法取消任务 '{task_id}' (可能已完成或不存在){Colors.RESET}\n"
                        )
                    continue

                elif command == "async":
                    # Toggle async mode info
                    print(
                        f"\n{Colors.BOLD}{Colors.BRIGHT_CYAN}🔄 异步任务模式{Colors.RESET}"
                    )
                    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")
                    print(f"  任务队列已启用，所有任务将异步执行。")
                    print(f"  {Colors.DIM}• 输入任务内容 → 自动提交到队列")
                    print(f"  {Colors.DIM}• /tasks - 查看所有任务状态")
                    print(f"  {Colors.DIM}• /task <id> - 查看任务详情")
                    print(f"  {Colors.DIM}• /cancel <id> - 取消任务")
                    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}\n")
                    continue

                else:
                    print(f"{Colors.RED}❌ Unknown command: {user_input}{Colors.RESET}")
                    print(
                        f"{Colors.DIM}Type /help to see available commands{Colors.RESET}\n"
                    )
                    continue

            # Normal conversation - exit check
            if user_input.lower() in ["exit", "quit", "q"]:
                print(
                    f"\n{Colors.BRIGHT_YELLOW}👋 Goodbye! Thanks for using Open Agent{Colors.RESET}\n"
                )
                print_stats(agent, session_start)
                break

            # Run Agent with Esc cancellation support
            # Show current model info
            current_provider = "MiniMax"  # default
            if llm_client.provider == LLMProvider.ANTHROPIC:
                current_provider = "Anthropic"

            # Try to get provider name from model config
            manager = get_user_config()
            default_model = manager.get_default_model()
            if default_model:
                current_provider = default_model.provider

            print(render_execution_header(llm_client.model, current_provider))
            agent.add_user_message(user_input)

            # Create cancellation event
            cancel_event = asyncio.Event()
            agent.cancel_event = cancel_event

            # Esc key listener thread
            esc_listener_stop = threading.Event()
            esc_cancelled = [False]  # Mutable container for thread access

            def esc_key_listener():
                """Listen for Esc key in a separate thread."""
                if platform.system() == "Windows":
                    try:
                        import msvcrt

                        while not esc_listener_stop.is_set():
                            if msvcrt.kbhit():
                                char = msvcrt.getch()
                                if char == b"\x1b":  # Esc
                                    print(
                                        f"\n{Colors.BRIGHT_YELLOW}⏹️  Esc pressed, cancelling...{Colors.RESET}"
                                    )
                                    esc_cancelled[0] = True
                                    cancel_event.set()
                                    break
                            esc_listener_stop.wait(0.05)
                    except Exception:
                        pass
                    return

                # Unix/macOS
                try:
                    import select
                    import termios
                    import tty

                    fd = sys.stdin.fileno()
                    old_settings = termios.tcgetattr(fd)

                    try:
                        tty.setcbreak(fd)
                        while not esc_listener_stop.is_set():
                            rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                            if rlist:
                                char = sys.stdin.read(1)
                                if char == "\x1b":  # Esc
                                    print(
                                        f"\n{Colors.BRIGHT_YELLOW}⏹️  Esc pressed, cancelling...{Colors.RESET}"
                                    )
                                    esc_cancelled[0] = True
                                    cancel_event.set()
                                    break
                    finally:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except Exception:
                    pass

            # Start Esc listener thread
            esc_thread = threading.Thread(target=esc_key_listener, daemon=True)
            esc_thread.start()

            # Run agent with periodic cancellation check
            try:
                agent_task = asyncio.create_task(agent.run())

                # Poll for cancellation while agent runs
                while not agent_task.done():
                    if esc_cancelled[0]:
                        cancel_event.set()
                    await asyncio.sleep(0.1)

                # Get result
                _ = agent_task.result()

            except asyncio.CancelledError:
                print(
                    f"\n{Colors.BRIGHT_YELLOW}⚠️  Agent execution cancelled{Colors.RESET}"
                )
            finally:
                agent.cancel_event = None
                esc_listener_stop.set()
                esc_thread.join(timeout=0.2)

            print()

        except KeyboardInterrupt:
            print(
                f"\n\n{Colors.BRIGHT_YELLOW}👋 Interrupt signal detected, exiting...{Colors.RESET}\n"
            )
            print_stats(agent, session_start)
            break

        except Exception as e:
            print(f"\n{Colors.RED}❌ Error: {e}{Colors.RESET}")
            print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}\n")

    # 11. Cleanup MCP connections
    await _quiet_cleanup()


async def run_unified(
    workspace_dir: Path,
    task: str = None,
    open_browser: bool = True,
):
    """Run CLI and Web UI in the same process, sharing the same AgentService.

    This allows CLI-created agents to be visible in Web UI.

    Args:
        workspace_dir: Workspace directory path
        task: If provided, execute this task and exit (non-interactive mode)
        open_browser: Whether to open browser automatically
    """
    import asyncio
    import threading
    from open_agent.agent_service import init_agent_service, get_agent_service

    # Enable ANSI escape sequences on Windows
    enable_windows_ansi()

    # Initialize AgentService first (shared singleton)
    service = init_agent_service(
        host="127.0.0.1",
        port=9998,
        workspace_dir=str(workspace_dir),
    )

    # Start Web UI in background thread
    print(f"\n{Colors.BRIGHT_CYAN}🌐 Starting Web UI...{Colors.RESET}")
    service.start(open_browser=open_browser)

    # Wait for web server to be ready
    import time

    max_wait = 10
    for i in range(max_wait):
        try:
            import http.client

            conn = http.client.HTTPConnection("127.0.0.1", service.port, timeout=1)
            conn.request("GET", "/api/health")
            response = conn.getresponse()
            conn.close()
            if response.status == 200:
                print(
                    f"{Colors.GREEN}✅ Web UI ready at http://127.0.0.1:{service.port}{Colors.RESET}"
                )
                break
        except Exception:
            time.sleep(0.5)

    # Now run CLI with the same AgentService
    print(f"\n{Colors.BRIGHT_CYAN}💻 Starting CLI...{Colors.RESET}")

    # Run the agent (will use the same AgentService)
    await run_agent(
        workspace_dir=workspace_dir,
        task=task,
    )

    # Stop AgentService when CLI exits
    print(f"\n{Colors.DIM}Stopping Web UI...{Colors.RESET}")
    service.stop()


def main():
    """Main entry point for CLI"""
    from open_agent.utils.stdio import configure_utf8_stdio

    configure_utf8_stdio()

    # Enable ANSI escape sequences on Windows
    enable_windows_ansi()

    # Parse command line arguments
    args = parse_args()

    # Handle log subcommand
    if args.command == "log":
        if args.filename:
            read_log_file(args.filename)
        else:
            show_log_directory(open_file_manager=True)
        return

    # Determine workspace directory
    # Priority: CLI argument > config file > current directory
    if args.workspace:
        # 1. CLI argument specified - use it
        workspace_dir = Path(args.workspace).expanduser().absolute()
    else:
        # 2. Try to load from config file
        try:
            config_path = Config.get_default_config_path()
            if config_path.exists():
                config = Config.from_yaml(config_path)
                config_workspace = config.agent.workspace_dir
                if config_workspace:
                    # Expand ~ and resolve relative path
                    workspace_dir = Path(config_workspace).expanduser()
                    if not workspace_dir.is_absolute():
                        # Relative path - resolve from current directory
                        workspace_dir = Path.cwd() / workspace_dir
                    workspace_dir = workspace_dir.absolute()
                    print(
                        f"{Colors.DIM}Using workspace from config: {workspace_dir}{Colors.RESET}"
                    )
                else:
                    workspace_dir = Path.cwd()
            else:
                # No config file - use current directory
                workspace_dir = Path.cwd()
        except Exception as e:
            # Config load failed - use current directory
            print(
                f"{Colors.YELLOW}⚠️  Failed to load config, using current directory: {e}{Colors.RESET}"
            )
            workspace_dir = Path.cwd()

    # Ensure workspace directory exists
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Handle --web-only mode (使用新架构 app/runner)
    if args.web_only:
        from open_agent.agent_service import init_agent_service

        print(f"{Colors.BRIGHT_CYAN}🌐 Starting Web UI only mode...{Colors.RESET}")
        print(f"   {Colors.DIM}Host: {args.host}{Colors.RESET}")
        print(f"   {Colors.DIM}Port: {args.port}{Colors.RESET}")
        print(f"   {Colors.DIM}Workspace: {workspace_dir}{Colors.RESET}")

        # 使用 AgentService 启动 Web UI (新架构)
        service = init_agent_service(
            host=args.host,
            port=args.port,
            workspace_dir=str(workspace_dir),
        )
        service.start(open_browser=not args.no_browser)

        # 保持运行直到用户中断
        try:
            import time

            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{Colors.BRIGHT_YELLOW}👋 Stopping Web UI...{Colors.RESET}")
            service.stop()
        return

    # Run the agent (config always loaded from package directory)
    asyncio.run(
        run_agent(workspace_dir, task=args.task)
    )


if __name__ == "__main__":
    main()
