"""Base tool classes."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Tool execution result."""

    success: bool
    content: str = ""
    error: str | None = None


@dataclass(frozen=True)
class ToolContext:
    """Runtime context shared with tools for the current agent session."""

    session_id: str = ""
    profile_id: str = "main"
    workspace_dir: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool:
    """Base class for all tools."""

    context: ToolContext | None = None

    @property
    def name(self) -> str:
        """Tool name."""
        raise NotImplementedError

    @property
    def description(self) -> str:
        """Tool description."""
        raise NotImplementedError

    @property
    def parameters(self) -> dict[str, Any]:
        """Tool parameters schema (JSON Schema format)."""
        raise NotImplementedError

    async def execute(self, *args, **kwargs) -> ToolResult:  # type: ignore
        """Execute the tool with arbitrary arguments."""
        raise NotImplementedError

    def bind_context(self, context: ToolContext) -> "Tool":
        """Bind runtime context before execution and return this tool."""
        self.context = context
        return self

    def require_context(self) -> ToolContext:
        """Return the bound context or raise a clear error."""
        if self.context is None:
            raise RuntimeError(f"Tool context is not bound for {self.name}")
        return self.context

    def to_schema(self) -> dict[str, Any]:
        """Convert tool to Anthropic tool schema."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert tool to OpenAI tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
