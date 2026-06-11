"""Sandbox CLI API for interactive agent-switch terminals on Windows."""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import shutil
import site
import subprocess
import sys
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

PtyProcess = None  # type: ignore
PtyBackend = None  # type: ignore
_pty_import_error = ""


def _get_pty_process_class():
    """Load pywinpty lazily so installing it during dev does not require module reload."""
    global PtyProcess, _pty_import_error
    if PtyProcess is not None:
        return PtyProcess
    try:
        from winpty import PtyProcess as ImportedPtyProcess  # type: ignore

        PtyProcess = ImportedPtyProcess  # type: ignore
        _pty_import_error = ""
        return PtyProcess
    except Exception as exc:  # pragma: no cover - depends on Windows optional dependency
        first_error = f"{type(exc).__name__}: {exc}"

    try:
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            sys.path.append(user_site)
        from winpty import PtyProcess as ImportedPtyProcess  # type: ignore

        PtyProcess = ImportedPtyProcess  # type: ignore
        _pty_import_error = ""
        return PtyProcess
    except Exception as exc:  # pragma: no cover - depends on Windows optional dependency
        _pty_import_error = f"{first_error}; retry with user site failed: {type(exc).__name__}: {exc}"
        return None


def _get_pty_backend():
    """Prefer WinPTY for npm/Claude TUI compatibility in the packaged desktop app."""
    global PtyBackend
    if PtyBackend is not None:
        return PtyBackend
    try:
        from winpty import Backend  # type: ignore

        PtyBackend = Backend.WinPTY
        return PtyBackend
    except Exception:
        return None


router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])

ALLOWED_PROVIDERS = ("claude", "codex", "codewhale", "deepseek", "kimi", "opencode")
PROVIDER_COMMANDS = {
    "claude": ("claude",),
    "codex": ("codex",),
    "codewhale": ("codewhale",),
    "deepseek": ("deepseek", "deepseek-tui"),
    "kimi": ("kimi",),
    "opencode": ("opencode",),
}
DEFAULT_COLS = 100
DEFAULT_ROWS = 30
MAX_OUTPUT_BUFFER_CHARS = 200_000
EXITED_SESSION_TTL_SECONDS = 300


class SandboxSessionRequest(BaseModel):
    provider: str
    cols: int = Field(default=DEFAULT_COLS, ge=20, le=240)
    rows: int = Field(default=DEFAULT_ROWS, ge=8, le=80)


@dataclass
class SandboxSession:
    session_id: str
    provider: str
    command: str
    cwd: str
    process: Any
    closed: bool = False
    reader_task: Optional[asyncio.Task[None]] = None

    def is_alive(self) -> bool:
        try:
            return bool(self.process.isalive())
        except Exception:
            return not self.closed

    def read(self) -> str:
        return self.process.read()

    def write(self, data: str) -> None:
        self.process.write(data)

    def resize(self, rows: int, cols: int) -> None:
        if hasattr(self.process, "setwinsize"):
            self.process.setwinsize(rows, cols)

    def terminate(self) -> None:
        self.closed = True
        try:
            self.process.terminate(force=True)
        except TypeError:
            try:
                self.process.terminate()
            except Exception:
                pass
        except Exception:
            pass

    def __post_init__(self) -> None:
        self._output_buffer: deque[str] = deque()
        self._output_buffer_chars = 0
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._exit_sent = False

    def buffered_output(self) -> str:
        return "".join(self._output_buffer)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, message: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(message)

    def append_output(self, output: str) -> None:
        if not output:
            return
        self._output_buffer.append(output)
        self._output_buffer_chars += len(output)
        while self._output_buffer_chars > MAX_OUTPUT_BUFFER_CHARS and self._output_buffer:
            removed = self._output_buffer.popleft()
            self._output_buffer_chars -= len(removed)

    async def mark_exited(self) -> None:
        if self._exit_sent:
            return
        self.closed = True
        self._exit_sent = True
        await self.publish({"type": "exit"})

    def start_reader(self) -> None:
        if self.reader_task and not self.reader_task.done():
            return
        self.reader_task = asyncio.create_task(_read_session_output(self))


_sessions: dict[str, SandboxSession] = {}


async def _read_session_output(session: SandboxSession) -> None:
    empty_reads_after_exit = 0
    while not session.closed:
        alive = session.is_alive()
        if not alive and empty_reads_after_exit >= 3:
            break
        try:
            output = await asyncio.to_thread(session.read)
        except EOFError:
            break
        except Exception as exc:
            error_text = f"\r\n[Sandbox read error] {type(exc).__name__}: {exc}\r\n"
            session.append_output(error_text)
            await session.publish({"type": "output", "data": error_text})
            await session.publish({"type": "error", "message": str(exc)})
            break
        if output:
            session.append_output(output)
            await session.publish({"type": "output", "data": output})
            empty_reads_after_exit = 0
        else:
            if not alive:
                empty_reads_after_exit += 1
            await asyncio.sleep(0.02)

    await session.mark_exited()
    asyncio.create_task(_cleanup_exited_session_later(session.session_id))


async def _cleanup_exited_session_later(session_id: str) -> None:
    await asyncio.sleep(EXITED_SESSION_TTL_SECONDS)
    session = _sessions.get(session_id)
    if session and session.closed:
        _sessions.pop(session_id, None)


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _subprocess_no_window_kwargs() -> dict[str, int]:
    if not _is_windows():
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _command_available(command: str) -> bool:
    if shutil.which(command):
        return True
    if not _is_windows():
        return False
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f"if (Get-Command {command} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
        return result.returncode == 0
    except Exception:
        return False


def _cmd_runnable_command(command: str) -> str:
    resolved = shutil.which(command)
    if resolved and Path(resolved).suffix.lower() in {".cmd", ".exe", ".bat", ".com"}:
        return resolved
    if not _is_windows():
        return resolved or command

    candidates: list[str] = []
    for suffix in (".cmd", ".exe", ".bat", ".com"):
        candidate = shutil.which(f"{command}{suffix}")
        if candidate:
            candidates.append(candidate)

    if not candidates:
        try:
            result = subprocess.run(
                ["where.exe", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=4,
                check=False,
                **_subprocess_no_window_kwargs(),
            )
            candidates.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
        except Exception:
            pass

    for candidate in candidates:
        if Path(candidate).suffix.lower() in {".cmd", ".exe", ".bat", ".com"}:
            return candidate
    return resolved or command


def _windows_cmd_shell_command(args: list[str]) -> str:
    command_line = subprocess.list2cmdline(args)
    return f"cmd.exe /d /c call {command_line}"


def _ensure_hidden_console_for_pty() -> None:
    if not _is_windows():
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            kernel32.AllocConsole()
            hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _workspace_cwd() -> str:
    try:
        from open_agent.user_config import get_user_config

        workspace = str(get_user_config().get_settings().workspace or "").strip()
        if workspace:
            path = Path(workspace).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            return str(path)
    except Exception:
        pass
    return str(Path.cwd().resolve())


def _agent_switch_capture_dir() -> Path:
    candidates: list[Path] = []
    explicit_dir = os.environ.get("OPEN_AGENT_SANDBOX_AGENT_SWITCH_DIR")
    if explicit_dir:
        candidates.append(Path(explicit_dir))

    try:
        from open_agent.utils.path_utils import get_data_dir

        candidates.append(get_data_dir() / "sandbox" / "agent-switch")
    except Exception:
        pass

    local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "OpenAgentSeal" / "sandbox" / "agent-switch")
    candidates.append(Path(_workspace_cwd()) / ".agent-switch" / "sessions")

    for capture_dir in candidates:
        try:
            capture_dir.mkdir(parents=True, exist_ok=True)
            probe = capture_dir / ".write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return capture_dir
        except Exception:
            continue

    raise HTTPException(status_code=500, detail="No writable agent-switch capture directory is available")


def _provider_status(provider: str, agent_switch_available: bool) -> dict[str, Any]:
    commands = PROVIDER_COMMANDS.get(provider, (provider,))
    available_command = next((command for command in commands if _command_available(command)), None)
    available = bool(agent_switch_available and available_command)
    if not agent_switch_available:
        status = "agent-switch missing"
    elif available_command:
        status = "ready"
    else:
        status = f"{'/'.join(commands)} missing"
    return {
        "provider": provider,
        "label": provider,
        "available": available,
        "status": status,
        "command": f"agent-switch {provider}",
        "target_command": available_command or commands[0],
    }


def _start_session(provider: str, rows: int, cols: int) -> SandboxSession:
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported sandbox provider")
    if not _is_windows():
        raise HTTPException(status_code=400, detail="Sandbox terminal is only supported on Windows")
    pty_process = _get_pty_process_class()
    if pty_process is None:
        raise HTTPException(status_code=500, detail="pywinpty is not installed; install pywinpty to enable sandbox terminals")

    cwd = _workspace_cwd()
    capture_dir = _agent_switch_capture_dir()
    agent_switch_command = _cmd_runnable_command("agent-switch")
    command_args = [agent_switch_command, provider, "--dir", str(capture_dir)]
    command = f"agent-switch {provider}"
    shell_command = _windows_cmd_shell_command(command_args)
    try:
        _ensure_hidden_console_for_pty()
        spawn_kwargs = {
            "cwd": cwd,
            "dimensions": (rows, cols),
            "env": {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        }
        backend = _get_pty_backend()
        if backend is not None:
            spawn_kwargs["backend"] = backend
        process = pty_process.spawn(
            shell_command,
            **spawn_kwargs,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start sandbox terminal: {exc}") from exc

    session = SandboxSession(
        session_id=f"sandbox_{uuid.uuid4().hex}",
        provider=provider,
        command=command,
        cwd=cwd,
        process=process,
    )
    _sessions[session.session_id] = session
    session.start_reader()
    return session


@router.get("/cli-status")
async def cli_status() -> dict[str, Any]:
    """Return agent-switch and target CLI availability."""
    agent_switch_available = _command_available("agent-switch")
    pty_process = _get_pty_process_class()
    return {
        "windows": _is_windows(),
        "pty_available": pty_process is not None,
        "pty_error": _pty_import_error,
        "agent_switch_available": agent_switch_available,
        "workspace": _workspace_cwd(),
        "providers": [_provider_status(provider, agent_switch_available) for provider in ALLOWED_PROVIDERS],
    }


@router.post("/sessions")
async def create_session(request: SandboxSessionRequest) -> dict[str, Any]:
    """Create an interactive agent-switch sandbox session."""
    session = _start_session(request.provider, request.rows, request.cols)
    return {
        "session_id": session.session_id,
        "provider": session.provider,
        "cwd": session.cwd,
        "command": session.command,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    """Terminate and remove a sandbox session."""
    session = _sessions.pop(session_id, None)
    if session:
        session.terminate()
        await session.mark_exited()
    return {"success": True}


@router.websocket("/sessions/{session_id}/ws")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    """Bridge browser terminal input/output to a Windows PTY session."""
    await websocket.accept()
    session = _sessions.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "Sandbox session not found"})
        await websocket.close()
        return

    queue = session.subscribe()

    buffered_output = session.buffered_output()
    if buffered_output:
        await websocket.send_json({"type": "output", "data": buffered_output})
    if session.closed:
        await websocket.send_json({"type": "exit"})
        await websocket.close()
        session.unsubscribe(queue)
        return

    async def send_loop() -> None:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("type") == "exit":
                break

    async def receive_loop() -> None:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "input":
                session.write(str(message.get("data") or ""))
            elif message_type == "resize":
                rows = int(message.get("rows") or DEFAULT_ROWS)
                cols = int(message.get("cols") or DEFAULT_COLS)
                session.resize(max(8, min(rows, 80)), max(20, min(cols, 240)))
            elif message_type == "terminate":
                _sessions.pop(session_id, None)
                session.terminate()
                await session.mark_exited()
                break

    sender = asyncio.create_task(send_loop())
    receiver = asyncio.create_task(receive_loop())
    try:
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        session.unsubscribe(queue)
        sender.cancel()
        receiver.cancel()
        with contextlib.suppress(BaseException):
            await sender
        with contextlib.suppress(BaseException):
            await receiver
