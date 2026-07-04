from pathlib import Path
import tomllib


def test_cli_entrypoints_are_exposed():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    scripts = data["project"]["scripts"]

    assert scripts["open-agent"] == "open_agent.cli:main"
    assert scripts["open-agent-cli"] == "open_agent.cli:main"
    assert scripts["open-agent-acp"] == "open_agent.acp.server:main"
