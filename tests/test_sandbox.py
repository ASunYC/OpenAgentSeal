import pytest

from open_agent.app import sandbox


def test_command_available_hides_powershell_window(monkeypatch):
    calls = []

    class Result:
        returncode = 0

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(sandbox.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sandbox.shutil, "which", lambda command: None)
    monkeypatch.setattr(sandbox.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)

    assert sandbox._command_available("agent-switch") is True

    command_args = calls[0][0][0]
    command_kwargs = calls[0][1]
    assert "powershell.exe" in command_args
    assert "-NonInteractive" in command_args
    assert command_kwargs["creationflags"] == 0x08000000


def test_start_session_uses_app_owned_agent_switch_dir(tmp_path, monkeypatch):
    spawned = {}

    class FakePtyProcess:
        @staticmethod
        def spawn(command, **kwargs):
            spawned["command"] = command
            spawned["kwargs"] = kwargs
            return FakeProcess()

    class FakeProcess:
        def isalive(self):
            return True

        def read(self):
            return ""

        def write(self, data):
            pass

    monkeypatch.setattr(sandbox, "ALLOWED_PROVIDERS", ("claude",))
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sandbox, "_get_pty_process_class", lambda: FakePtyProcess)
    monkeypatch.setattr(sandbox, "_workspace_cwd", lambda: str(tmp_path / "workspace"))
    monkeypatch.setattr(sandbox, "_agent_switch_capture_dir", lambda: tmp_path / "captures")
    monkeypatch.setattr(sandbox, "_cmd_runnable_command", lambda command: f"C:\\tools\\{command}.cmd")
    monkeypatch.setattr(sandbox, "_get_pty_backend", lambda: "conpty")
    monkeypatch.setattr(sandbox.asyncio, "create_task", lambda coro: coro.close())

    session = sandbox._start_session("claude", 30, 100)

    assert session.command == "agent-switch claude"
    assert spawned["command"].startswith("cmd.exe /d /c call ")
    assert "C:\\tools\\agent-switch.cmd claude --dir" in spawned["command"]
    assert str(tmp_path / "captures") in spawned["command"]
    assert spawned["kwargs"]["cwd"] == str(tmp_path / "workspace")
    assert spawned["kwargs"]["backend"] == "conpty"


def test_agent_switch_capture_dir_falls_back_to_local_app_data(tmp_path, monkeypatch):
    blocked_parent = tmp_path / "blocked"
    local_app_data = tmp_path / "local-app-data"

    def fake_get_data_dir():
        return blocked_parent

    original_mkdir = sandbox.Path.mkdir

    def guarded_mkdir(self, *args, **kwargs):
        if str(self).startswith(str(blocked_parent)):
            raise PermissionError("blocked")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.delenv("OPEN_AGENT_SANDBOX_AGENT_SWITCH_DIR", raising=False)
    monkeypatch.setattr("open_agent.utils.path_utils.get_data_dir", fake_get_data_dir)
    monkeypatch.setattr(sandbox.Path, "mkdir", guarded_mkdir)
    monkeypatch.setattr(sandbox, "_workspace_cwd", lambda: str(tmp_path / "workspace"))

    assert sandbox._agent_switch_capture_dir() == local_app_data / "OpenAgentSeal" / "sandbox" / "agent-switch"


def test_cmd_runnable_command_prefers_cmd_from_where(monkeypatch):
    class Result:
        stdout = "C:\\nvm\\nodejs\\agent-switch.ps1\nC:\\nvm\\nodejs\\agent-switch.cmd\n"

    monkeypatch.setattr(sandbox.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sandbox.shutil, "which", lambda command: None)
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *args, **kwargs: Result())

    assert sandbox._cmd_runnable_command("agent-switch") == "C:\\nvm\\nodejs\\agent-switch.cmd"


def test_windows_cmd_shell_command_wraps_batch_command():
    command = sandbox._windows_cmd_shell_command(["C:\\Program Files\\agent-switch.cmd", "claude", "--dir", "C:\\Open Agent\\captures"])

    assert command == 'cmd.exe /d /c call "C:\\Program Files\\agent-switch.cmd" claude --dir "C:\\Open Agent\\captures"'


@pytest.mark.asyncio
async def test_read_session_output_buffers_read_errors():
    class BrokenProcess:
        def __init__(self):
            self.calls = 0

        def isalive(self):
            self.calls += 1
            return self.calls == 1

        def read(self):
            raise UnicodeDecodeError("utf-8", b"\xd2", 0, 1, "invalid")

    session = sandbox.SandboxSession(
        session_id="test-session",
        provider="claude",
        command="agent-switch claude",
        cwd=".",
        process=BrokenProcess(),
    )

    await sandbox._read_session_output(session)

    assert "Sandbox read error" in session.buffered_output()
    assert session.closed is True
