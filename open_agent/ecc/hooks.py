"""
OpenAgentSeal Custom ECC Hooks

This module provides custom hooks for OpenAgentSeal that integrate with
ECC (Everything Claude Code) infrastructure.

Hooks provided:
- pre_task: Validate task input before agent execution
- post_task: Log task completion and quality metrics
- session_start: Load project context and configuration
- quality_gate: Run Python linting, type checking, and tests
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def get_project_root() -> Path:
    """Get the OpenAgentSeal project root directory."""
    return Path(__file__).parent.parent.parent


def run_command(
    cmd: list[str], cwd: Path | None = None, timeout: int = 60
) -> tuple[int, str, str]:
    """
    Run a shell command and return exit code, stdout, stderr.

    Args:
        cmd: Command and arguments to run
        cwd: Working directory (defaults to project root)
        timeout: Timeout in seconds

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    if cwd is None:
        cwd = get_project_root()

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def pre_task(task_input: dict[str, Any]) -> dict[str, Any]:
    """
    Pre-task hook: Validate task input before agent execution.

    Args:
        task_input: Task input dictionary

    Returns:
        Dictionary with 'valid' bool and optional 'errors' list
    """
    errors = []

    task = task_input.get("task", "")
    if not task or len(task.strip()) < 3:
        errors.append("Task description too short (minimum 3 characters)")

    workspace = task_input.get("workspace", "")
    if workspace:
        workspace_path = Path(workspace)
        if not workspace_path.exists():
            errors.append(f"Workspace does not exist: {workspace}")

    model = task_input.get("model", "sonnet")
    valid_models = ["haiku", "sonnet", "opus"]
    if model not in valid_models:
        errors.append(f"Invalid model '{model}'. Valid: {valid_models}")

    return {
        "valid": len(errors) == 0,
        "errors": errors if errors else None,
    }


def post_task(task_result: dict[str, Any]) -> dict[str, Any]:
    """
    Post-task hook: Log task completion and quality metrics.

    Args:
        task_result: Task result dictionary

    Returns:
        Dictionary with metrics and recommendations
    """
    metrics = {
        "files_changed": 0,
        "lines_added": 0,
        "lines_removed": 0,
        "tests_run": 0,
        "tests_passed": 0,
    }

    changes = task_result.get("changes", [])
    if changes:
        metrics["files_changed"] = len(changes)
        for change in changes:
            metrics["lines_added"] += change.get("lines_added", 0)
            metrics["lines_removed"] += change.get("lines_removed", 0)

    test_results = task_result.get("test_results", {})
    if test_results:
        metrics["tests_run"] = test_results.get("total", 0)
        metrics["tests_passed"] = test_results.get("passed", 0)

    recommendations = []
    if metrics["files_changed"] > 10:
        recommendations.append("Consider breaking into smaller PRs")
    if metrics["tests_run"] > 0 and metrics["tests_passed"] < metrics["tests_run"]:
        recommendations.append("Fix failing tests before committing")

    return {
        "metrics": metrics,
        "recommendations": recommendations if recommendations else None,
    }


def session_start() -> dict[str, Any]:
    """
    Session start hook: Load project context and configuration.

    Returns:
        Dictionary with project context
    """
    project_root = get_project_root()

    context = {
        "project_name": "OpenAgentSeal",
        "project_root": str(project_root),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "ecc_installed": False,
        "ecc_version": None,
    }

    ecc_dir = project_root / ".ecc"
    if ecc_dir.exists():
        context["ecc_installed"] = True
        version_file = ecc_dir / "VERSION"
        if version_file.exists():
            context["ecc_version"] = version_file.read_text().strip()

    config_file = project_root / "config" / "config.yaml"
    if config_file.exists():
        context["config_exists"] = True

    return context


def quality_gate(
    files: list[str] | None = None,
    run_lint: bool = True,
    run_typecheck: bool = True,
    run_tests: bool = False,
) -> dict[str, Any]:
    """
    Quality gate hook: Run Python linting, type checking, and tests.

    Args:
        files: Specific files to check (None = all files)
        run_lint: Whether to run ruff linting
        run_typecheck: Whether to run pyright type checking
        run_tests: Whether to run pytest

    Returns:
        Dictionary with results for each check
    """
    project_root = get_project_root()
    results = {
        "lint": None,
        "typecheck": None,
        "tests": None,
        "overall_pass": True,
    }

    if run_lint:
        cmd = ["ruff", "check", "."]
        if files:
            cmd = ["ruff", "check"] + files
        exit_code, stdout, stderr = run_command(cmd, cwd=project_root)
        results["lint"] = {
            "passed": exit_code == 0,
            "output": stdout + stderr,
        }
        if exit_code != 0:
            results["overall_pass"] = False

    if run_typecheck:
        cmd = ["pyright", "--warnings"]
        if files:
            cmd = ["pyright", "--warnings"] + files
        exit_code, stdout, stderr = run_command(cmd, cwd=project_root, timeout=120)
        results["typecheck"] = {
            "passed": exit_code == 0,
            "output": stdout + stderr,
        }
        if exit_code != 0:
            results["overall_pass"] = False

    if run_tests:
        cmd = ["pytest", "-x", "-q"]
        exit_code, stdout, stderr = run_command(cmd, cwd=project_root, timeout=300)
        results["tests"] = {
            "passed": exit_code == 0,
            "output": stdout + stderr,
        }
        if exit_code != 0:
            results["overall_pass"] = False

    return results


def main():
    """CLI entry point for running hooks."""
    import argparse

    parser = argparse.ArgumentParser(description="OpenAgentSeal ECC Hooks")
    parser.add_argument(
        "hook",
        choices=["pre-task", "post-task", "session-start", "quality-gate"],
        help="Hook to run",
    )
    parser.add_argument("--input", help="JSON input for the hook")
    parser.add_argument("--files", nargs="*", help="Files for quality-gate")
    parser.add_argument("--no-lint", action="store_true", help="Skip linting")
    parser.add_argument(
        "--no-typecheck", action="store_true", help="Skip type checking"
    )
    parser.add_argument("--tests", action="store_true", help="Run tests")

    args = parser.parse_args()

    if args.hook == "pre-task":
        input_data = json.loads(args.input) if args.input else {}
        result = pre_task(input_data)
    elif args.hook == "post-task":
        input_data = json.loads(args.input) if args.input else {}
        result = post_task(input_data)
    elif args.hook == "session-start":
        result = session_start()
    elif args.hook == "quality-gate":
        result = quality_gate(
            files=args.files,
            run_lint=not args.no_lint,
            run_typecheck=not args.no_typecheck,
            run_tests=args.tests,
        )
    else:
        result = {"error": f"Unknown hook: {args.hook}"}

    print(json.dumps(result, indent=2))
    return 0 if result.get("overall_pass", True) else 1


if __name__ == "__main__":
    sys.exit(main())
