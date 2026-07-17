"""Slash-command catalog and completion for the interactive CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from prompt_toolkit.completion import Completer, Completion


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    category: str
    aliases: tuple[str, ...] = ()
    args_hint: str = ""

    @property
    def command(self) -> str:
        return f"/{self.name}"


@dataclass(frozen=True)
class ParsedCommand:
    spec: CommandSpec
    args: str = ""


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    # Session
    CommandSpec("new", "Start a fresh conversation", "Session", aliases=("clear", "reset")),
    CommandSpec("sessions", "List saved CLI conversations", "Session"),
    CommandSpec("resume", "Resume a saved CLI conversation", "Session", args_hint="<id>"),
    CommandSpec("history", "Show the current conversation history", "Session"),
    CommandSpec("retry", "Retry the most recent user message", "Session"),
    CommandSpec("undo", "Remove the last N user turns", "Session", args_hint="[N]"),
    CommandSpec("redraw", "Redraw the command console", "Session"),
    # Runtime
    CommandSpec("status", "Show session, model, workspace, and queue status", "Runtime", aliases=("stats", "usage")),
    CommandSpec("agents", "Show running, queued, and completed tasks", "Runtime", aliases=("tasks",)),
    CommandSpec("task", "Show details for one task", "Runtime", args_hint="<id>"),
    CommandSpec("cancel", "Cancel a running or queued task", "Runtime", args_hint="<id>"),
    CommandSpec("async", "Explain asynchronous task mode", "Runtime"),
    # Configuration
    CommandSpec("model", "Switch the active model", "Configuration", aliases=("switch",)),
    CommandSpec("config", "Show active runtime configuration without secrets", "Configuration"),
    CommandSpec("reload", "Reload MCP servers and skills", "Configuration", aliases=("reload-mcp", "reload-skills")),
    CommandSpec("doctor", "Diagnose the active provider and model configuration", "Configuration"),
    CommandSpec("workspace", "Show the active workspace", "Configuration", aliases=("cwd",)),
    # Tools and knowledge
    CommandSpec("tools", "List loaded tools", "Tools & Knowledge", args_hint="[filter]"),
    CommandSpec("skills", "List loaded skills", "Tools & Knowledge", args_hint="[filter]"),
    CommandSpec("mcp", "Show MCP configuration and loaded MCP tools", "Tools & Knowledge"),
    CommandSpec("memory", "Show memory database statistics", "Tools & Knowledge"),
    # Information
    CommandSpec("help", "Show all available commands", "Information", aliases=("commands",)),
    CommandSpec("logs", "Open logs or read a log file", "Information", aliases=("log",), args_hint="[file]"),
    CommandSpec("version", "Show OpenAgentSeal version", "Information", aliases=("v",)),
    CommandSpec("quit", "Exit the CLI", "Information", aliases=("exit", "q")),
)


_CATEGORY_ORDER = (
    "Session",
    "Runtime",
    "Configuration",
    "Tools & Knowledge",
    "Information",
)

_COMMAND_LOOKUP: dict[str, CommandSpec] = {}
for _spec in COMMAND_SPECS:
    _COMMAND_LOOKUP[_spec.name] = _spec
    for _alias in _spec.aliases:
        _COMMAND_LOOKUP[_alias] = _spec


def resolve_command(name: str) -> CommandSpec | None:
    return _COMMAND_LOOKUP.get(name.strip().lower().lstrip("/"))


def parse_command(text: str) -> ParsedCommand | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command_text = stripped[1:]
    name, separator, args = command_text.partition(" ")
    spec = resolve_command(name)
    if spec is None:
        return None
    return ParsedCommand(spec=spec, args=args.strip() if separator else "")


def iter_command_sections() -> Iterable[tuple[str, tuple[CommandSpec, ...]]]:
    for category in _CATEGORY_ORDER:
        specs = tuple(spec for spec in COMMAND_SPECS if spec.category == category)
        if specs:
            yield category, specs


def command_alias_label(spec: CommandSpec) -> str:
    if not spec.aliases:
        return ""
    return "aliases: " + ", ".join(f"/{alias}" for alias in spec.aliases)


class SlashCommandCompleter(Completer):
    """Complete canonical slash commands and matching legacy aliases."""

    def get_completions(self, document, complete_event):  # noqa: ARG002
        text = document.text_before_cursor
        if not text.startswith("/") or any(char.isspace() for char in text):
            return

        prefix = text[1:].lower()
        for spec in COMMAND_SPECS:
            candidate = spec.name
            alias_match = next(
                (alias for alias in spec.aliases if alias.startswith(prefix)),
                None,
            )
            if prefix and not spec.name.startswith(prefix) and alias_match is None:
                continue
            if prefix and not spec.name.startswith(prefix) and alias_match:
                candidate = alias_match

            command_display = f"/{candidate}"
            if spec.args_hint:
                command_display += f" {spec.args_hint}"
            alias_label = command_alias_label(spec)
            meta = f"{spec.category}  ·  {spec.description}"
            if alias_label:
                meta += f"  ·  {alias_label}"

            yield Completion(
                candidate,
                start_position=-len(prefix),
                display=command_display,
                display_meta=meta,
            )


__all__ = [
    "COMMAND_SPECS",
    "CommandSpec",
    "ParsedCommand",
    "SlashCommandCompleter",
    "command_alias_label",
    "iter_command_sections",
    "parse_command",
    "resolve_command",
]
