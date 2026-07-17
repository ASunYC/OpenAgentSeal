import asyncio

import pytest
from prompt_toolkit.input import DummyInput
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.styles import Style

from open_agent.cli import create_cli_prompt_session
from open_agent.cli_commands import SlashCommandCompleter


def test_live_slash_completion_is_not_disabled_by_history_search(tmp_path):
    session = create_cli_prompt_session(
        history_file=tmp_path / "history",
        completer=SlashCommandCompleter(),
        style=Style([]),
        key_bindings=KeyBindings(),
        input_stream=DummyInput(),
        output_stream=DummyOutput(),
    )

    assert session.default_buffer.complete_while_typing()
    assert not session.default_buffer.enable_history_search()


@pytest.mark.asyncio
async def test_typing_slash_prefix_keeps_history_completion_visible(tmp_path):
    with create_pipe_input() as input_stream:
        session = create_cli_prompt_session(
            history_file=tmp_path / "history",
            completer=SlashCommandCompleter(),
            style=Style([]),
            key_bindings=KeyBindings(),
            input_stream=input_stream,
            output_stream=DummyOutput(),
        )
        prompt_task = asyncio.create_task(session.prompt_async("> "))
        await asyncio.sleep(0.05)

        input_stream.send_text("/hi")
        await asyncio.sleep(0.2)

        completion_state = session.default_buffer.complete_state
        assert completion_state is not None
        assert "history" in {
            completion.text for completion in completion_state.completions
        }

        input_stream.send_text("\r")
        assert await prompt_task == "/hi"
