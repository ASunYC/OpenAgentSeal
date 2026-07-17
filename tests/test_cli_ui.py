from datetime import datetime, timedelta
from pathlib import Path

from open_agent.cli_ui import (
    RuntimeStatus,
    SessionOverview,
    build_prompt_fragments,
    build_status_fragments,
    build_welcome,
    render_assistant,
    render_heartbeat_line,
    render_step_header,
    render_tool_call,
)
from open_agent.utils import calculate_display_width


def test_full_welcome_contains_brand_and_session_metrics():
    output = build_welcome(
        SessionOverview(
            model="glm-5-2-260617",
            provider="Volcengine Ark",
            workspace=Path("C:/workspace/OpenAgentSeal"),
            tool_count=31,
            mcp_tool_count=7,
            skill_count=106,
            memory_count=4,
            session_id="cli-123",
        ),
        width=92,
        color=False,
    )

    assert "O P E N A G E N T S E A L" in output
    assert "AUTONOMOUS COMMAND CORE" in output
    assert "glm-5-2-260617" in output
    assert "31 tools  ·  7 MCP  ·  106 skills  ·  4 memories" in output
    assert all(len(line) == 92 for line in output.splitlines())

    colored = build_welcome(
        SessionOverview(
            model="glm-5-2-260617",
            provider="Volcengine Ark",
            workspace=Path("C:/workspace/OpenAgentSeal"),
            tool_count=31,
        ),
        width=92,
        color=True,
    )
    assert all(calculate_display_width(line) == 92 for line in colored.splitlines())


def test_compact_welcome_omits_large_mark_but_keeps_identity():
    output = build_welcome(
        SessionOverview(
            model="a-very-long-model-name-that-needs-truncation",
            provider="provider",
            workspace=Path("/tmp/project"),
            tool_count=3,
        ),
        width=48,
        color=False,
    )

    assert "OAS" in output
    assert "██████╗" not in output
    assert "CONTROL PLANE READY" in output
    assert all(len(line) == 48 for line in output.splitlines())


def test_prompt_has_mission_label_and_submit_arrow():
    fragments = build_prompt_fragments(width=80)
    text = "".join(fragment for _, fragment in fragments)
    assert "MISSION" in text
    assert text.endswith("❯ ")
    assert "\n" in text


def test_status_bar_adapts_to_available_width():
    status = RuntimeStatus(
        model="provider/glm-5-2-260617",
        workspace=Path("C:/workspace/OpenAgentSeal"),
        message_count=9,
        tool_count=31,
        running_tasks=1,
        pending_tasks=2,
        started_at=datetime.now() - timedelta(seconds=65),
    )

    wide = "".join(text for _, text in build_status_fragments(status, width=120))
    narrow = "".join(text for _, text in build_status_fragments(status, width=50))

    assert "OAS" in wide and "READY" in wide
    assert "1 running" in wide and "2 queued" in wide
    assert "OpenAgentSeal" in wide and "9 msg" in wide
    assert "OpenAgentSeal" not in narrow and "9 msg" not in narrow
    assert calculate_display_width(wide) <= 120
    assert calculate_display_width(narrow) <= 50


def test_execution_blocks_have_distinct_visual_hierarchy():
    assert "STEP 03" in render_step_header(3, 50, 12000, color=False)
    assert "◆ OPENAGENTSEAL" in render_assistant("hello\nworld", color=False)
    tool = render_tool_call("shell_command", '{\n  "command": "dir"\n}', color=False)
    assert "▸ TOOL" in tool
    assert "shell_command" in tool
    assert "INFERENCE LINK ACTIVE" in render_heartbeat_line("⠋", 2.0, color=False)
    assert "UPSTREAM DELAY" in render_heartbeat_line("⠋", 61.0, color=False)
