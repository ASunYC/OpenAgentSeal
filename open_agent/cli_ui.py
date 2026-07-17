"""Terminal presentation helpers for the OpenAgentSeal CLI.

The module intentionally keeps rendering separate from the agent runtime so
the desktop, ACP, and API paths do not inherit terminal-specific behavior.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from open_agent.utils import calculate_display_width


RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[38;2;44;225;210m"
BLUE = "\033[38;2;83;138;255m"
AMBER = "\033[38;2;246;190;74m"
GREEN = "\033[38;2;90;224;149m"
RED = "\033[38;2;255;107;107m"
WHITE = "\033[38;2;232;240;247m"
MUTED = "\033[38;2;122;139;153m"


@dataclass(frozen=True)
class SessionOverview:
    model: str
    provider: str
    workspace: Path
    tool_count: int
    mcp_tool_count: int = 0
    skill_count: int = 0
    memory_count: int = 0
    session_id: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeStatus:
    model: str
    workspace: Path
    message_count: int
    tool_count: int
    started_at: datetime
    running_tasks: int = 0
    pending_tasks: int = 0


def color_enabled(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def terminal_width(*, minimum: int = 42, maximum: int = 104) -> int:
    columns = shutil.get_terminal_size((100, 24)).columns
    return max(minimum, min(maximum, columns - 2))


def _paint(text: str, color: str, enabled: bool, *, bold: bool = False) -> str:
    if not enabled:
        return text
    prefix = f"{BOLD if bold else ''}{color}"
    return f"{prefix}{text}{RESET}"


def _clip(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if calculate_display_width(text) <= width:
        return text
    if width <= 3:
        return "." * width

    result: list[str] = []
    used = 0
    for char in text:
        char_width = calculate_display_width(char)
        if used + char_width > width - 3:
            break
        result.append(char)
        used += char_width
    return "".join(result) + "..."


def _align(text: str, width: int, align: str = "left") -> str:
    text = _clip(text, width)
    padding = max(0, width - calculate_display_width(text))
    if align == "center":
        left = padding // 2
        return " " * left + text + " " * (padding - left)
    if align == "right":
        return " " * padding + text
    return text + " " * padding


def _box_line(content: str, width: int, enabled: bool, *, align: str = "left") -> str:
    inner_width = width - 4
    body = _align(content, inner_width, align)
    border = _paint("│", CYAN, enabled)
    return f"{border} {body} {border}"


def _divider(width: int, enabled: bool) -> str:
    return _paint("├" + "─" * (width - 2) + "┤", CYAN, enabled)


def _metric_line(label: str, value: str, width: int, enabled: bool) -> str:
    label_text = _paint(f"{label:<10}", AMBER, enabled, bold=True)
    available = max(8, width - 17)
    value_text = _paint(_clip(value, available), WHITE, enabled)
    return _box_line(f"{label_text}{value_text}", width, enabled)


_OAS_MARK = (
    " ██████╗  █████╗ ███████╗",
    "██╔═══██╗██╔══██╗██╔════╝",
    "██║   ██║███████║███████╗",
    "██║   ██║██╔══██║╚════██║",
    "╚██████╔╝██║  ██║███████║",
    " ╚═════╝ ╚═╝  ╚═╝╚══════╝",
)


def build_welcome(overview: SessionOverview, *, width: int | None = None, color: bool = True) -> str:
    """Build the responsive command-console welcome screen."""
    width = max(42, width or terminal_width())
    lines = [_paint("╭" + "─" * (width - 2) + "╮", CYAN, color)]

    if width >= 72:
        lines.append(_box_line("", width, color))
        for art_line in _OAS_MARK:
            lines.append(
                _box_line(_paint(art_line, BLUE, color, bold=True), width, color, align="center")
            )
        lines.append(_box_line("", width, color))
    else:
        lines.append(
            _box_line(_paint("OAS", BLUE, color, bold=True), width, color, align="center")
        )

    lines.append(
        _box_line(
            _paint("O P E N A G E N T S E A L", WHITE, color, bold=True),
            width,
            color,
            align="center",
        )
    )
    lines.append(
        _box_line(
            _paint("AUTONOMOUS COMMAND CORE", MUTED, color),
            width,
            color,
            align="center",
        )
    )
    lines.append(_divider(width, color))

    online = _paint("● ONLINE", GREEN, color, bold=True)
    lines.append(_box_line(f"{online}   CONTROL PLANE READY", width, color))
    lines.append(_metric_line("MODEL", overview.model, width, color))
    lines.append(_metric_line("PROVIDER", overview.provider, width, color))
    lines.append(_metric_line("WORKSPACE", str(overview.workspace), width, color))

    capacity = (
        f"{overview.tool_count} tools  ·  {overview.mcp_tool_count} MCP  ·  "
        f"{overview.skill_count} skills  ·  {overview.memory_count} memories"
    )
    lines.append(_metric_line("CAPACITY", capacity, width, color))
    if overview.session_id:
        lines.append(_metric_line("SESSION", overview.session_id, width, color))

    if overview.warnings:
        lines.append(_divider(width, color))
        for warning in overview.warnings[:3]:
            warning_text = _paint("! ", AMBER, color, bold=True) + _paint(
                _clip(warning, width - 8), MUTED, color
            )
            lines.append(_box_line(warning_text, width, color))

    lines.append(_divider(width, color))
    footer = "ENTER A MISSION   Type / for commands   Esc abort"
    lines.append(_box_line(_paint(footer, MUTED, color), width, color, align="center"))
    lines.append(_paint("╰" + "─" * (width - 2) + "╯", CYAN, color))
    return "\n".join(lines)


def clear_terminal(stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    if os.environ.get("OPEN_AGENT_CLI_VERBOSE") == "1":
        return
    try:
        if not stream.isatty():
            return
    except Exception:
        return
    stream.write("\033[2J\033[H")
    stream.flush()


def print_welcome(overview: SessionOverview, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    clear_terminal(stream)
    enabled = color_enabled(stream)
    stream.write(build_welcome(overview, color=enabled) + "\n\n")
    stream.flush()


def build_prompt_fragments(*, width: int | None = None):
    width = max(32, width or shutil.get_terminal_size((100, 24)).columns)
    rule_width = max(8, min(width - 12, 84))
    return [
        ("class:input-border", "╭─"),
        ("class:input-title", " MISSION "),
        ("class:input-border", "─" * rule_width),
        ("", "\n"),
        ("class:input-border", "╰─"),
        ("class:input-arrow", "❯ "),
    ]


def _format_duration(started_at: datetime) -> str:
    elapsed = max(0, int((datetime.now() - started_at).total_seconds()))
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def build_status_fragments(status: RuntimeStatus, *, width: int | None = None):
    width = max(32, width or shutil.get_terminal_size((100, 24)).columns)
    model = _clip(status.model.split("/")[-1], 24 if width >= 90 else 14)
    workspace = _clip(status.workspace.name or str(status.workspace), 18)

    fragments = [
        ("class:status-brand", " OAS "),
        ("class:status-online", "● READY "),
        ("class:status-dim", "│ "),
        ("class:status-value", model),
    ]
    if width >= 96:
        fragments.extend(
            [
                ("class:status-dim", " │ "),
                ("class:status-dim", workspace),
            ]
        )
    if width >= 72:
        fragments.extend(
            [
                ("class:status-dim", " │ "),
                ("class:status-value", f"{status.message_count} msg"),
                ("class:status-dim", " · "),
                ("class:status-value", f"{status.tool_count} tools"),
            ]
        )
    if width >= 120 and (status.running_tasks or status.pending_tasks):
        fragments.extend(
            [
                ("class:status-dim", " │ "),
                ("class:status-warn", f"{status.running_tasks} running"),
                ("class:status-dim", " · "),
                ("class:status-dim", f"{status.pending_tasks} queued"),
            ]
        )
    fragments.extend(
        [
            ("class:status-dim", " │ "),
            ("class:status-dim", _format_duration(status.started_at)),
            ("class:status-bar", " "),
        ]
    )
    return fragments


PROMPT_STYLE = {
    "input-border": "#2ce1d2",
    "input-title": "#f6be4a bold",
    "input-arrow": "#53a0ff bold",
    "status-bar": "bg:#101923 #7a8b99",
    "status-brand": "bg:#2ce1d2 #071014 bold",
    "status-online": "bg:#101923 #5ae095 bold",
    "status-value": "bg:#101923 #e8f0f7 bold",
    "status-dim": "bg:#101923 #7a8b99",
    "status-warn": "bg:#101923 #f6be4a bold",
    "completion-menu": "bg:#101923 #e8f0f7",
    "completion-menu.completion.current": "bg:#18314a #2ce1d2 bold",
    "completion-menu.meta.completion": "bg:#101923 #7a8b99",
    "completion-menu.meta.completion.current": "bg:#18314a #f6be4a",
}


def render_execution_header(model: str, provider: str, *, color: bool | None = None) -> str:
    enabled = color_enabled() if color is None else color
    title = _paint("◆ EXECUTION LINK ESTABLISHED", CYAN, enabled, bold=True)
    details = _paint(f"{provider} / {model}   ·   Esc to abort", MUTED, enabled)
    return f"\n{title}\n{details}\n"


def render_heartbeat_line(spinner: str, elapsed: float, *, color: bool | None = None) -> str:
    enabled = color_enabled() if color is None else color
    if elapsed < 10:
        state = "INFERENCE LINK ACTIVE"
        tone = CYAN
    elif elapsed < 30:
        state = "MODEL IS REASONING"
        tone = AMBER
    elif elapsed < 60:
        state = "EXTENDED INFERENCE"
        tone = AMBER
    else:
        state = "UPSTREAM DELAY · ESC TO ABORT"
        tone = RED
    return (
        f"{_paint(spinner, tone, enabled, bold=True)} "
        f"{_paint(state, tone, enabled, bold=True)} "
        f"{_paint(f'{elapsed:05.1f}s', MUTED, enabled)}"
    )


def render_step_header(step: int, max_steps: int, tokens: int, *, color: bool | None = None) -> str:
    enabled = color_enabled() if color is None else color
    marker = _paint(f"STEP {step:02d}", AMBER, enabled, bold=True)
    total = _paint(f"/{max_steps:02d}", MUTED, enabled)
    context = _paint(f"CONTEXT {tokens:,} TOKENS", MUTED, enabled)
    return f"\n{_paint('┌─', CYAN, enabled)} {marker}{total}  {context}"


def render_assistant(content: str, *, color: bool | None = None) -> str:
    enabled = color_enabled() if color is None else color
    header = _paint("◆ OPENAGENTSEAL", BLUE, enabled, bold=True)
    rail = _paint("│", CYAN, enabled)
    body = "\n".join(f"{rail} {line}" if line else rail for line in content.splitlines() or [""])
    return f"\n{header}\n{body}"


def render_thinking(content: str, *, color: bool | None = None) -> str:
    enabled = color_enabled() if color is None else color
    header = _paint("◇ REASONING", MUTED, enabled, bold=True)
    body = "\n".join(f"  {_paint(line, MUTED, enabled)}" for line in content.splitlines())
    return f"\n{header}\n{body}"


def render_tool_call(name: str, arguments: str, *, color: bool | None = None) -> str:
    enabled = color_enabled() if color is None else color
    header = _paint("▸ TOOL", AMBER, enabled, bold=True)
    tool_name = _paint(name, WHITE, enabled, bold=True)
    rail = _paint("│", AMBER, enabled)
    args = "\n".join(f"  {rail} {_paint(line, MUTED, enabled)}" for line in arguments.splitlines())
    return f"\n{header}  {tool_name}\n{args}"


def render_tool_result(content: str, *, success: bool, color: bool | None = None) -> str:
    enabled = color_enabled() if color is None else color
    tone = GREEN if success else RED
    label = "SUCCESS" if success else "FAILED"
    header = _paint(f"  └─ {label}", tone, enabled, bold=True)
    body = _clip(content.replace("\n", " "), 240)
    return f"{header}  {_paint(body, MUTED, enabled)}"


def render_step_complete(step: int, elapsed: float, total: float, *, color: bool | None = None) -> str:
    enabled = color_enabled() if color is None else color
    rule = _paint("└─", CYAN, enabled)
    timing = _paint(f"STEP {step:02d} COMPLETE  {elapsed:.2f}s  ·  TOTAL {total:.2f}s", MUTED, enabled)
    return f"\n{rule} {timing}"
