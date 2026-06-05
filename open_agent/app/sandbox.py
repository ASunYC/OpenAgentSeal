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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

PtyProcess = None  # type: ignore
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


_sessions: dict[str, SandboxSession] = {}


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


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
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f"if (Get-Command {command} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


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
    command = f"agent-switch {provider}"
    shell_command = f"cmd.exe /d /s /c {command}"
    try:
        process = pty_process.spawn(
            shell_command,
            cwd=cwd,
            dimensions=(rows, cols),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
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

    async def read_loop() -> None:
        while session.is_alive() and not session.closed:
            try:
                output = await asyncio.to_thread(session.read)
            except EOFError:
                break
            except Exception as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                break
            if output:
                await websocket.send_json({"type": "output", "data": output})
            else:
                await asyncio.sleep(0.02)
        await websocket.send_json({"type": "exit"})

    reader = asyncio.create_task(read_loop())
    try:
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
                session.terminate()
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        session.terminate()
        _sessions.pop(session_id, None)
        reader.cancel()
        with contextlib.suppress(BaseException):
            await reader
