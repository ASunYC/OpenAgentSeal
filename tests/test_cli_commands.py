from prompt_toolkit.document import Document

from open_agent.cli_commands import (
    COMMAND_SPECS,
    SlashCommandCompleter,
    iter_command_sections,
    parse_command,
    resolve_command,
)


def completion_names(text: str) -> list[str]:
    completer = SlashCommandCompleter()
    return [
        completion.text
        for completion in completer.get_completions(Document(text), None)
    ]


def test_bare_slash_lists_every_canonical_command():
    names = completion_names("/")
    assert names == [spec.name for spec in COMMAND_SPECS]
    assert {
        "new",
        "sessions",
        "resume",
        "status",
        "model",
        "tools",
        "mcp",
        "help",
        "quit",
    } <= set(names)


def test_prefix_completion_supports_commands_and_legacy_aliases():
    assert completion_names("/mo") == ["model"]
    assert "switch" in completion_names("/sw")
    assert completion_names("/sta") == ["status"]
    assert "stats" in completion_names("/stats")
    assert completion_names("hello") == []


def test_command_parser_resolves_aliases_and_preserves_arguments():
    parsed = parse_command("/switch")
    assert parsed is not None
    assert parsed.spec.name == "model"

    parsed = parse_command("/task Task-AbC")
    assert parsed is not None
    assert parsed.spec.name == "task"
    assert parsed.args == "Task-AbC"

    assert parse_command("/does-not-exist") is None
    assert parse_command("plain text") is None


def test_registry_has_unique_names_aliases_and_ordered_sections():
    all_names = [spec.name for spec in COMMAND_SPECS]
    all_aliases = [alias for spec in COMMAND_SPECS for alias in spec.aliases]
    assert len(all_names) == len(set(all_names))
    assert not set(all_names).intersection(all_aliases)
    assert len(all_aliases) == len(set(all_aliases))
    assert resolve_command("/clear").name == "new"
    assert [name for name, _ in iter_command_sections()] == [
        "Session",
        "Runtime",
        "Configuration",
        "Tools & Knowledge",
        "Information",
    ]


def test_all_legacy_cli_commands_remain_available():
    expected_aliases = {
        "clear": "new",
        "stats": "status",
        "switch": "model",
        "tasks": "agents",
        "log": "logs",
        "exit": "quit",
        "q": "quit",
    }

    assert {
        alias: resolve_command(alias).name
        for alias in expected_aliases
    } == expected_aliases
