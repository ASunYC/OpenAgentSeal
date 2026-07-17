"""Workspace Resource Manager API.

Provides full workspace CRUD and file management endpoints for the
independent resource manager page.

Borrowed patterns from AgentEarthPlatform's workspace-routes.ts
and workspace-service.ts.
"""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from send2trash import send2trash

from open_agent.utils.path_utils import get_data_dir
from open_agent.utils.safe_join import PathTraversalError, safe_join
from open_agent.utils.doc_extract import BINARY_DOC_EXTS, read_file_content


router = APIRouter(prefix="/api/workspace", tags=["workspace"])


# ── Models ──


class WorkspaceCreate(BaseModel):
    name: str
    path: str = ""


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None


class WriteFileRequest(BaseModel):
    path: str
    content: str


class DeleteFileRequest(BaseModel):
    path: str


class MkdirRequest(BaseModel):
    path: str


class RenameRequest(BaseModel):
    path: str
    name: str


class LocalImportRequest(BaseModel):
    paths: list[str]
    dest_path: str = ""


class SearchRequest(BaseModel):
    pattern: str
    path: Optional[str] = None
    include: Optional[str] = None
    output_mode: Optional[str] = "content"


class GlobRequest(BaseModel):
    pattern: str


def _validate_entry_name(name: str | None, field: str = "name") -> str:
    """Validate a single path segment used for rename/upload targets."""
    candidate = (name or "").strip()
    if (
        not candidate
        or candidate in {".", ".."}
        or "/" in candidate
        or "\\" in candidate
        or Path(candidate).name != candidate
    ):
        raise HTTPException(status_code=400, detail=f"{field} 必须是有效的文件名")
    return candidate


# ── Workspace Store ──


def _workspace_store_path() -> Path:
    return get_data_dir() / "workspaces.json"


def _load_workspaces() -> dict:
    store_path = _workspace_store_path()
    if store_path.exists():
        try:
            return json.loads(store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"workspaces": []}


def _save_workspaces(data: dict) -> None:
    store_path = _workspace_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _find_workspace(ws_id: str) -> dict:
    data = _load_workspaces()
    for ws in data["workspaces"]:
        if ws["id"] == ws_id:
            return ws
    raise HTTPException(status_code=404, detail=f"工作区不存在: {ws_id}")


def _resolve_workspace_path(ws: dict, relative_path: str) -> Path:
    """Resolve a relative path within a workspace, with traversal protection."""
    ws_root = Path(ws["path"])
    if not ws_root.is_dir():
        raise HTTPException(status_code=404, detail=f"工作区目录不存在: {ws_root}")
    try:
        return safe_join(ws_root, relative_path or ".")
    except PathTraversalError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ── Workspace CRUD ──


@router.get("/")
async def list_workspaces():
    """List all workspaces."""
    return _load_workspaces()


@router.post("/")
async def create_workspace(req: WorkspaceCreate):
    """Create a new workspace."""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="工作区名称不能为空")

    ws_path = req.path.strip() or req.name.strip()
    resolved = Path(ws_path).expanduser().resolve()

    # Create directory if it doesn't exist
    resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="路径不是目录")

    now = datetime.now().isoformat()
    data = _load_workspaces()

    # If this is the first workspace, set it as current
    is_current = len(data["workspaces"]) == 0

    workspace = {
        "id": f"ws_{uuid.uuid4().hex[:12]}",
        "name": req.name.strip(),
        "path": str(resolved),
        "created": now,
        "updated": now,
        "is_current": is_current,
    }

    data["workspaces"].append(workspace)
    _save_workspaces(data)

    return {"workspace": workspace}


@router.put("/{ws_id}")
async def update_workspace(ws_id: str, req: WorkspaceUpdate):
    """Update workspace name or path."""
    data = _load_workspaces()
    ws = None
    for item in data["workspaces"]:
        if item["id"] == ws_id:
            ws = item
            break

    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区不存在: {ws_id}")

    if req.name is not None:
        ws["name"] = req.name.strip()
    if req.path is not None:
        resolved = Path(req.path).expanduser().resolve()
        if not resolved.is_dir():
            raise HTTPException(status_code=400, detail="路径不是目录")
        ws["path"] = str(resolved)
    ws["updated"] = datetime.now().isoformat()

    _save_workspaces(data)
    return {"workspace": ws}


@router.delete("/{ws_id}")
async def delete_workspace(ws_id: str):
    """Delete a workspace (does not delete files on disk)."""
    data = _load_workspaces()
    original = len(data["workspaces"])
    data["workspaces"] = [ws for ws in data["workspaces"] if ws["id"] != ws_id]

    if len(data["workspaces"]) == original:
        raise HTTPException(status_code=404, detail=f"工作区不存在: {ws_id}")

    _save_workspaces(data)
    return {"status": "ok"}


@router.put("/{ws_id}/set-current")
async def set_current_workspace(ws_id: str):
    """Set a workspace as the current workspace."""
    data = _load_workspaces()
    found = False
    for ws in data["workspaces"]:
        if ws["id"] == ws_id:
            ws["is_current"] = True
            ws["updated"] = datetime.now().isoformat()
            found = True
        else:
            ws["is_current"] = False

    if not found:
        raise HTTPException(status_code=404, detail=f"工作区不存在: {ws_id}")

    _save_workspaces(data)
    return {"status": "ok"}


# ── File Operations ──


@router.get("/{ws_id}/files")
async def list_files(ws_id: str, path: str = ""):
    """List directory contents within a workspace."""
    ws = _find_workspace(ws_id)
    target = _resolve_workspace_path(ws, path)

    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"目录不存在: {path}")

    ws_root = Path(ws["path"])
    files = []
    try:
        entries = sorted(
            target.iterdir(),
            key=lambda e: (not e.is_dir(), e.name.lower()),
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="无权限访问该目录")

    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            stat = entry.stat()
            is_dir = entry.is_dir()
            rel = str(entry.relative_to(ws_root)).replace("\\", "/")
            files.append({
                "name": entry.name,
                "path": rel,
                "is_dir": is_dir,
                "size": None if is_dir else stat.st_size,
                "modified_at": stat.st_mtime,
                "mime_type": (
                    None if is_dir
                    else (
                        __import__("mimetypes").guess_type(entry.name)[0]
                        or "application/octet-stream"
                    )
                ),
            })
        except OSError:
            continue

    return {
        "path": path or ".",
        "ws_path": ws["path"],
        "files": files,
    }


@router.get("/{ws_id}/read")
async def read_file(
    ws_id: str,
    path: str,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
):
    """Read file content (supports binary docs via doc_extract)."""
    ws = _find_workspace(ws_id)
    target = _resolve_workspace_path(ws, path)

    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")

    # Use doc_extract for binary docs, plain read for text
    if target.suffix.lower() in BINARY_DOC_EXTS:
        content = read_file_content(target)
    else:
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"读取失败: {e}")

    # Apply offset/limit
    lines = content.split("\n")
    start = max(0, (offset or 1) - 1)
    end = (start + limit) if limit else len(lines)
    selected = lines[start:end]
    numbered = [f"{start + i + 1}: {line}" for i, line in enumerate(selected)]

    return {
        "ok": True,
        "path": path,
        "content": "\n".join(numbered),
        "size": target.stat().st_size,
    }


@router.post("/{ws_id}/write")
async def write_file(ws_id: str, req: WriteFileRequest):
    """Write content to a file."""
    ws = _find_workspace(ws_id)
    target = _resolve_workspace_path(ws, req.path)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")

    return {
        "ok": True,
        "path": req.path,
        "size": target.stat().st_size,
    }


@router.post("/{ws_id}/delete")
async def delete_file(ws_id: str, req: DeleteFileRequest):
    """Move a file or directory to the operating system recycle bin."""
    ws = _find_workspace(ws_id)
    target = _resolve_workspace_path(ws, req.path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"不存在: {req.path}")

    # Prevent deleting workspace root
    ws_root = Path(ws["path"]).resolve()
    if target.resolve() == ws_root:
        raise HTTPException(status_code=403, detail="不能删除工作区根目录")

    try:
        send2trash(str(target))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"无法移入系统回收站，文件未删除: {exc}",
        ) from exc

    return {"ok": True, "path": req.path, "trashed": True}


@router.post("/{ws_id}/mkdir")
async def make_directory(ws_id: str, req: MkdirRequest):
    """Create a new directory."""
    ws = _find_workspace(ws_id)
    target = _resolve_workspace_path(ws, req.path)

    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": req.path}


@router.post("/{ws_id}/rename")
async def rename_file(ws_id: str, req: RenameRequest):
    """Rename a file or directory."""
    ws = _find_workspace(ws_id)
    target = _resolve_workspace_path(ws, req.path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"不存在: {req.path}")

    new_name = _validate_entry_name(req.name)
    ws_root = Path(ws["path"])
    parent_rel = str(target.parent.relative_to(ws_root)).replace("\\", "/")
    new_relative = f"{parent_rel}/{new_name}" if parent_rel != "." else new_name
    new_path = _resolve_workspace_path(ws, new_relative)
    if new_path.exists():
        raise HTTPException(status_code=409, detail=f"目标已存在: {new_name}")

    target.rename(new_path)
    new_rel = str(new_path.relative_to(ws_root)).replace("\\", "/")

    return {
        "ok": True,
        "old_path": req.path,
        "new_path": new_rel,
    }


@router.post("/{ws_id}/upload")
async def upload_file(
    ws_id: str,
    file: UploadFile = File(...),
    dest_path: str = Form(""),
):
    """Upload a file to the workspace."""
    ws = _find_workspace(ws_id)

    # dest_path is the directory to upload into
    dest_dir = _resolve_workspace_path(ws, dest_path or ".")
    if not dest_dir.is_dir():
        dest_dir.mkdir(parents=True, exist_ok=True)

    filename = _validate_entry_name(file.filename, "filename")
    ws_root = Path(ws["path"])
    dest_rel = str(dest_dir.relative_to(ws_root)).replace("\\", "/")
    target_rel = f"{dest_rel}/{filename}" if dest_rel != "." else filename
    target = _resolve_workspace_path(ws, target_rel)
    # Prevent overwriting directories
    if target.is_dir():
        raise HTTPException(status_code=400, detail="不能覆盖目录")

    content = await file.read()
    target.write_bytes(content)

    rel = str(target.relative_to(ws_root)).replace("\\", "/")

    return {
        "ok": True,
        "path": rel,
        "size": len(content),
    }


@router.post("/{ws_id}/import-local")
async def import_local_files(ws_id: str, request: LocalImportRequest):
    """Copy files selected by the desktop shell into a workspace."""
    ws = _find_workspace(ws_id)
    dest_dir = _resolve_workspace_path(ws, request.dest_path or ".")
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination is not a directory")

    ws_root = Path(ws["path"]).resolve()
    imported = []
    rejected = []
    for raw_path in request.paths[:100]:
        source = Path(raw_path).expanduser()
        try:
            source = source.resolve(strict=True)
            if not source.is_file():
                rejected.append({"path": raw_path, "reason": "not a file"})
                continue

            filename = _validate_entry_name(source.name, "filename")
            dest_rel = str(dest_dir.relative_to(ws_root)).replace("\\", "/")
            target_rel = f"{dest_rel}/{filename}" if dest_rel != "." else filename
            target = _resolve_workspace_path(ws, target_rel)
            if target.is_dir():
                rejected.append({"path": raw_path, "reason": "cannot overwrite a directory"})
                continue

            if source != target.resolve():
                shutil.copy2(source, target)

            imported.append(
                {
                    "source": str(source),
                    "path": str(target.relative_to(ws_root)).replace("\\", "/"),
                    "size": target.stat().st_size,
                }
            )
        except (OSError, ValueError) as exc:
            rejected.append({"path": raw_path, "reason": str(exc)})

    return {"imported": imported, "rejected": rejected}


# ── Search ──


@router.post("/{ws_id}/search")
async def search_content(ws_id: str, req: SearchRequest):
    """Search file contents within a workspace."""
    ws = _find_workspace(ws_id)
    ws_root = Path(ws["path"])

    if not ws_root.is_dir():
        raise HTTPException(status_code=404, detail="工作区目录不存在")

    search_dir = ws_root
    if req.path:
        search_dir = _resolve_workspace_path(ws, req.path)
        if not search_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"目录不存在: {req.path}")

    # Use grep-like logic from search_tools
    import re

    try:
        regex = re.compile(req.pattern, re.IGNORECASE)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"正则表达式错误: {e}")

    results = []
    SKIP_DIRS = {
        ".git", "node_modules", "target", "dist", "build",
        ".next", ".nuxt", ".cache", ".idea", ".vscode",
        "__pycache__", ".venv", ".workspace",
    }

    def _search_dir(dir_path: Path, depth: int = 0) -> None:
        if depth > 15 or len(results) >= 100:
            return
        try:
            entries = list(dir_path.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith(".") or entry.name in SKIP_DIRS:
                continue
            if entry.is_dir():
                _search_dir(entry, depth + 1)
            elif entry.is_file():
                try:
                    if entry.stat().st_size > 2 * 1024 * 1024:
                        continue
                    content = entry.read_text(encoding="utf-8", errors="replace")
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        if regex.search(line):
                            results.append({
                                "file": str(entry.relative_to(ws_root)).replace("\\", "/"),
                                "line": i,
                                "content": line.strip()[:300],
                            })
                            if len(results) >= 100:
                                return
                except OSError:
                    continue

    _search_dir(search_dir)
    return {"query": req.pattern, "results": results}


@router.post("/{ws_id}/glob")
async def glob_files(ws_id: str, req: GlobRequest):
    """Find files matching a glob pattern."""
    ws = _find_workspace(ws_id)
    ws_root = Path(ws["path"])

    if not ws_root.is_dir():
        raise HTTPException(status_code=404, detail="工作区目录不存在")

    # Use the glob_to_regex from search_tools
    from open_agent.tools.search_tools import glob_to_regex

    regex = glob_to_regex(req.pattern)
    SKIP_DIRS = {
        ".git", "node_modules", "target", "dist", "build",
        ".next", ".nuxt", ".cache", ".idea", ".vscode",
        "__pycache__", ".venv", ".workspace",
    }
    matched = []

    def _collect(dir_path: Path, depth: int = 0) -> None:
        if depth > 15 or len(matched) >= 100:
            return
        try:
            entries = list(dir_path.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith(".") or entry.name in SKIP_DIRS:
                continue
            if entry.is_dir():
                _collect(entry, depth + 1)
            elif entry.is_file():
                rel = str(entry.relative_to(ws_root)).replace("\\", "/")
                if regex.match(rel):
                    matched.append(rel)
                    if len(matched) >= 100:
                        return

    _collect(ws_root)
    return {"pattern": req.pattern, "files": matched}


@router.post("/search-all")
async def search_all_workspaces(req: SearchRequest):
    """Search across all workspaces."""
    data = _load_workspaces()
    all_results = []

    import re
    try:
        regex = re.compile(req.pattern, re.IGNORECASE)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"正则表达式错误: {e}")

    SKIP_DIRS = {
        ".git", "node_modules", "target", "dist", "build",
        ".next", ".nuxt", ".cache", ".idea", ".vscode",
        "__pycache__", ".venv", ".workspace",
    }

    for ws in data["workspaces"]:
        ws_root = Path(ws["path"])
        if not ws_root.is_dir():
            continue

        ws_results = []

        def _search_dir(dir_path: Path, depth: int = 0) -> None:
            if depth > 15 or len(ws_results) >= 50:
                return
            try:
                entries = list(dir_path.iterdir())
            except PermissionError:
                return
            for entry in entries:
                if entry.name.startswith(".") or entry.name in SKIP_DIRS:
                    continue
                if entry.is_dir():
                    _search_dir(entry, depth + 1)
                elif entry.is_file():
                    try:
                        if entry.stat().st_size > 2 * 1024 * 1024:
                            continue
                        content = entry.read_text(encoding="utf-8", errors="replace")
                        lines = content.split("\n")
                        for i, line in enumerate(lines, 1):
                            if regex.search(line):
                                ws_results.append({
                                    "workspace": ws["name"],
                                    "workspace_id": ws["id"],
                                    "file": str(entry.relative_to(ws_root)).replace("\\", "/"),
                                    "line": i,
                                    "content": line.strip()[:300],
                                })
                                if len(ws_results) >= 50:
                                    return
                    except OSError:
                        continue

        _search_dir(ws_root)
        all_results.extend(ws_results)
        if len(all_results) >= 200:
            break

    return {"query": req.pattern, "results": all_results[:200]}
