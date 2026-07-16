from pathlib import Path
from types import SimpleNamespace
import tomllib

from open_agent.cli import _apply_cli_launch_context


def test_cli_entrypoints_are_exposed():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    scripts = data["project"]["scripts"]

    assert scripts["open-agent"] == "open_agent.cli:main"
    assert scripts["open-agent-cli"] == "open_agent.cli:main"
    assert scripts["open-agent-acp"] == "open_agent.acp.server:main"


def test_cli_launch_context_applies_desktop_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("OPEN_AGENT_SESSION_ID", "cli-session-1")
    monkeypatch.setenv("OPEN_AGENT_PROFILE_ID", "main")
    monkeypatch.setenv("OPEN_AGENT_LAUNCH_SOURCE", "desktop-tray")
    agent = SimpleNamespace(session_id="", profile_id="")

    metadata = _apply_cli_launch_context(agent, tmp_path)

    assert agent.session_id == "cli-session-1"
    assert agent.profile_id == "main"
    assert metadata == {
        "session_id": "cli-session-1",
        "profile_id": "main",
        "workspace_dir": str(tmp_path),
        "launch_source": "desktop-tray",
    }
