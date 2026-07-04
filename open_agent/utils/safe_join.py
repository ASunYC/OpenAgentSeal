"""Path traversal protection for workspace file operations.

Prevents agents from reading/writing files outside the workspace directory
by resolving paths and validating containment.

Ported from AgentEarthPlatform's safeJoin() pattern:
packages/workspace/src/utils/path-validator.ts
"""

from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a path attempts to escape the workspace directory."""

    def __init__(self, message: str = "路径不能越过工作区根目录"):
        super().__init__(message)
        self.message = message


def safe_join(workspace_dir: Path, relative_path: str) -> Path:
    """Resolve a relative path against a workspace root, rejecting path traversal.

    Always resolves the path relative to workspace_dir, even if the input
    is an absolute path. Throws PathTraversalError if the resolved path
    escapes the workspace root.

    Args:
        workspace_dir: The workspace root directory (must be absolute).
        relative_path: The path to resolve (relative or absolute).

    Returns:
        The resolved absolute path within the workspace.

    Raises:
        PathTraversalError: If the resolved path escapes workspace_dir.

    Examples:
        >>> safe_join(Path("/workspace"), "src/main.py")
        PosixPath('/workspace/src/main.py')

        >>> safe_join(Path("/workspace"), "../../../etc/passwd")
        PathTraversalError: 路径不能越过工作区根目录
    """
    resolved_root = workspace_dir.resolve()

    # Always treat input as relative to workspace, even if absolute
    # This prevents absolute path injection (e.g., "/etc/passwd")
    target = (resolved_root / relative_path).resolve()

    # Compute relative path from root to target
    try:
        rel = target.relative_to(resolved_root)
    except ValueError:
        raise PathTraversalError(
            f"路径不能越过工作区根目录: {relative_path}"
        )

    # Double-check: relative path must not start with ".."
    if str(rel).startswith(".."):
        raise PathTraversalError(
            f"路径不能越过工作区根目录: {relative_path}"
        )

    return target
