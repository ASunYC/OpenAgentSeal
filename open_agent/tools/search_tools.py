"""Workspace search tools: glob, grep, and list_dir.

Borrows patterns from AgentEarthPlatform's @agent-earth/workspace package:
- globToRegex() for glob pattern matching
- collectAllFiles() with SKIP_DIRS and MAX_SEARCH_FILE_BYTES
- executeRgGrep() with ripgrep + Python fallback
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult
from ..utils.safe_join import safe_join, PathTraversalError


# ── Constants (ported from AgentEarth) ──

SKIP_DIRS = frozenset({
    ".git", ".svn", ".hg",
    "node_modules", "target", "dist", "build",
    ".next", ".nuxt", ".cache",
    ".idea", ".vscode", "__pycache__", ".venv",
    ".ruff_cache", ".pytest_cache",
})

TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".mdx", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".csv",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".html", ".css", ".scss", ".less", ".sass",
    ".py", ".go", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".php", ".rb", ".sh", ".ps1", ".bat",
    ".sql", ".xml", ".vue", ".svelte", ".astro",
    ".rs", ".kt", ".scala", ".swift", ".dart",
    ".lua", ".zig", ".nim", ".cmake", ".proto",
    ".graphql", ".prisma", ".tf",
    ".env", ".properties", ".conf",
    ".rst", ".adoc", ".org", ".tex",
})

MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024  # 2MB
MAX_MATCH_SNIPPET = 300


# ── Utility functions ──


def glob_to_regex(pattern: str) -> re.Pattern:
    """Convert a glob pattern to a compiled regex.

    Supports:
    - ** / matches any directory depth
    - * matches anything except /
    - ? matches a single char except /

    Ported from AgentEarth globToRegex().
    """
    normalized = pattern.replace("\\", "/")
    escaped = re.escape(normalized)
    # Now un-escape the glob tokens we want to interpret
    glob_part = (
        escaped
        .replace(r"\*\*/", "__GLOBDIR__")
        .replace(r"/\*\*", "__GLOBSLASHDIR__")
        .replace(r"\*\*", "__GLOBALL__")
        .replace(r"\*", "__GLOBSTAR__")
        .replace(r"\?", "__GLOBQ__")
        .replace("__GLOBDIR__", "(.*/)?")
        .replace("__GLOBSLASHDIR__", "(/.*)?")
        .replace("__GLOBALL__", ".*")
        .replace("__GLOBSTAR__", "[^/]*")
        .replace("__GLOBQ__", "[^/]")
    )
    return re.compile(f"^{glob_part}$")


def _is_text_file(filename: str) -> bool:
    """Check if a filename has a text extension."""
    ext = Path(filename).suffix.lower()
    return ext in TEXT_EXTENSIONS


def collect_files_relative(
    dir_path: Path,
    root: Path,
    out: list[str],
    max_depth: int = 20,
    current_depth: int = 0,
) -> None:
    """Recursively collect text file relative paths from root."""
    if current_depth > max_depth:
        return
    try:
        entries = list(dir_path.iterdir())
    except PermissionError:
        return

    for entry in entries:
        name = entry.name
        if name.startswith("."):
            continue
        if entry.is_dir():
            if name not in SKIP_DIRS:
                collect_files_relative(entry, root, out, max_depth, current_depth + 1)
            continue
        if not entry.is_file():
            continue
        try:
            rel = str(entry.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        out.append(rel)


def _truncate_snippet(line: str, max_len: int = MAX_MATCH_SNIPPET) -> str:
    """Truncate a long line, keeping context around the match."""
    if len(line) <= max_len:
        return line
    return line[:max_len] + "..."


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


# ── GlobTool ──


class GlobTool(Tool):
    """Search for files matching a glob pattern."""

    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = Path(workspace_dir).absolute()

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files matching a glob pattern in the workspace. "
            "Returns file paths sorted by modification time (newest first), up to 100 results. "
            "Examples: '**/*.py' for all Python files, 'src/**/*.ts' for TypeScript in src/."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, e.g. **/*.py, src/**/*.ts, *.md",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str) -> ToolResult:
        """Execute glob search."""
        try:
            regex = glob_to_regex(pattern)
            all_files: list[str] = []
            collect_files_relative(self.workspace_dir, self.workspace_dir, all_files)

            # Filter by regex and check text extension
            matched: list[tuple[str, float]] = []
            for rel in all_files:
                if not regex.match(rel):
                    continue
                if not _is_text_file(rel):
                    continue
                full = self.workspace_dir / rel
                try:
                    stat = full.stat()
                    if stat.st_size > MAX_SEARCH_FILE_BYTES:
                        continue
                    matched.append((rel, stat.st_mtime))
                except OSError:
                    continue

            # Sort by mtime descending, take top 100
            matched.sort(key=lambda x: x[1], reverse=True)
            results = [rel for rel, _ in matched[:100]]

            if not results:
                return ToolResult(success=True, content="没有匹配的文件")

            return ToolResult(success=True, content="\n".join(results))
        except Exception as e:
            return ToolResult(success=False, content="", error=str(e))


# ── GrepTool ──


class GrepTool(Tool):
    """Search file contents using regex pattern."""

    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = Path(workspace_dir).absolute()
        self._rg_path = shutil.which("rg")

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search file contents using a regular expression pattern. "
            "Supports filtering by file extension and subdirectory. "
            "Output modes: 'content' (default, show matching lines), "
            "'files_with_matches' (only file paths), 'count' (match count per file)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Limit search to this subdirectory (relative to workspace)",
                },
                "include": {
                    "type": "string",
                    "description": "Filter by file extension, e.g. '.py', '.ts'",
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": "Output mode (default: content)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        pattern: str,
        path: str | None = None,
        include: str | None = None,
        output_mode: str | None = None,
    ) -> ToolResult:
        """Execute grep search."""
        if not pattern:
            return ToolResult(success=False, content="", error="pattern 不能为空")

        output_mode = output_mode or "content"
        search_dir = self.workspace_dir
        if path:
            try:
                search_dir = safe_join(self.workspace_dir, path)
            except PathTraversalError as e:
                return ToolResult(success=False, content="", error=str(e))
            if not search_dir.is_dir():
                return ToolResult(success=False, content="", error=f"目录不存在: {path}")

        # Try ripgrep first
        if self._rg_path:
            try:
                result = await self._run_rg(pattern, search_dir, include, output_mode)
                return result
            except Exception:
                pass  # Fallback to Python

        # Python fallback
        return self._python_grep(pattern, search_dir, include, output_mode)

    async def _run_rg(
        self,
        pattern: str,
        search_dir: Path,
        include: str | None,
        output_mode: str,
    ) -> ToolResult:
        """Run ripgrep search."""
        args = [
            self._rg_path,
            "--regexp", pattern,
            "--ignore-case",
            "--no-config",
            "--no-messages",
            "--max-count", "500",
        ]
        if include:
            ext = include if include.startswith(".") else f".{include}"
            args.extend(["--glob", f"*{ext}"])
        if output_mode == "files_with_matches":
            args.append("--files-with-matches")
        elif output_mode == "count":
            args.append("--count")
        else:
            args.append("--line-number")
        args.extend(["--", str(search_dir)])

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
            stdout = proc.stdout.strip()
            if proc.returncode == 1 and not stdout:
                return ToolResult(success=True, content="没有匹配的内容")
            if not stdout:
                return ToolResult(success=True, content="没有匹配的内容")
            return ToolResult(success=True, content=stdout)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="搜索超时")

    def _python_grep(
        self,
        pattern: str,
        search_dir: Path,
        include: str | None,
        output_mode: str,
    ) -> ToolResult:
        """Pure Python grep fallback."""
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return ToolResult(success=False, content="", error=f"正则表达式错误: {e}")

        # Collect files
        all_files: list[str] = []
        collect_files_relative(search_dir, search_dir, all_files)

        # Filter
        if include:
            ext = include if include.startswith(".") else f".{include}"
            ext = ext.lower()
            all_files = [f for f in all_files if Path(f).suffix.lower() == ext]

        if output_mode == "files_with_matches":
            matched_files = []
            for rel in all_files:
                full = search_dir / rel
                try:
                    content = full.read_text(encoding="utf-8", errors="replace")
                    if regex.search(content):
                        matched_files.append(rel)
                        if len(matched_files) >= 100:
                            break
                except OSError:
                    continue
            if not matched_files:
                return ToolResult(success=True, content="没有匹配的文件")
            return ToolResult(success=True, content="\n".join(matched_files))

        if output_mode == "count":
            counts = []
            for rel in all_files:
                full = search_dir / rel
                try:
                    content = full.read_text(encoding="utf-8", errors="replace")
                    match_count = len(regex.findall(content))
                    if match_count > 0:
                        counts.append(f"{rel}: {match_count}")
                        if len(counts) >= 100:
                            break
                except OSError:
                    continue
            if not counts:
                return ToolResult(success=True, content="没有匹配的内容")
            return ToolResult(success=True, content="\n".join(counts))

        # content mode
        results = []
        for rel in all_files:
            full = search_dir / rel
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    snippet = _truncate_snippet(line.strip())
                    results.append(f"{rel}:{i}: {snippet}")
                    if len(results) >= 50:
                        break
            if len(results) >= 50:
                break

        if not results:
            return ToolResult(success=True, content="没有匹配的内容")
        return ToolResult(success=True, content="\n".join(results))


# ── ListDirTool ──


class ListDirTool(Tool):
    """List directory contents."""

    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = Path(workspace_dir).absolute()

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return (
            "List the immediate children of a directory in the workspace. "
            "Shows file type icons, names, and sizes. "
            "Directories are listed first, then files, both sorted alphabetically."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to workspace (default: '.')",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Execute list directory."""
        try:
            target = safe_join(self.workspace_dir, path)
        except PathTraversalError as e:
            return ToolResult(success=False, content="", error=str(e))

        if not target.is_dir():
            return ToolResult(
                success=False, content="", error=f"目录不存在: {path}"
            )

        try:
            entries = list(target.iterdir())
        except PermissionError:
            return ToolResult(success=False, content="", error="无权限访问该目录")

        # Filter hidden entries and sort (dirs first, then alphabetical)
        items = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            is_dir = entry.is_dir()
            try:
                size = entry.stat().st_size if not is_dir else 0
            except OSError:
                size = 0
            size_str = "" if is_dir else f" ({_format_size(size)})"
            icon = "📁" if is_dir else "📄"
            items.append((is_dir, entry.name, size_str, icon))

        items.sort(key=lambda x: (not x[0], x[1].lower()))

        lines = [f"{icon} {name}{size_str}" for _, name, size_str, icon in items]
        if not lines:
            return ToolResult(success=True, content="(空目录)")

        return ToolResult(success=True, content="\n".join(lines))
