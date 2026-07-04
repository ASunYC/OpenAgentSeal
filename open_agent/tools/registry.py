"""Tool registry with capability, toolset, and safety metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .base import Tool


class ToolRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"


class ToolCapability(str, Enum):
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    EXECUTE = "execute"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    capabilities: frozenset[ToolCapability] = field(default_factory=frozenset)
    risk: ToolRisk = ToolRisk.LOW
    approval_required: bool = False
    toolsets: frozenset[str] = field(default_factory=lambda: frozenset({"cli", "web"}))
    max_result_chars: int | None = None


@dataclass
class RegisteredTool:
    tool: Tool
    metadata: ToolMetadata

    def to_schema(self) -> dict[str, Any]:
        schema = self.tool.to_schema()
        schema["x_open_agent"] = {
            "capabilities": sorted(cap.value for cap in self.metadata.capabilities),
            "risk": self.metadata.risk.value,
            "approval_required": self.metadata.approval_required,
            "toolsets": sorted(self.metadata.toolsets),
            "max_result_chars": self.metadata.max_result_chars,
        }
        return schema


class SafetyPolicy:
    """Non-bypassable checks for high-risk tool usage."""

    HARD_BLOCK_PATTERNS = (
        "rm -rf /",
        "rm -rf /*",
        "del /f /s /q c:\\",
        "format c:",
        "shutdown /s",
        "shutdown -h",
        "mkfs.",
    )

    def check(self, tool_name: str, arguments: dict[str, Any], metadata: ToolMetadata, approved: bool = False) -> tuple[bool, str | None]:
        command = str(arguments.get("command", "")).lower()
        if ToolCapability.DESTRUCTIVE in metadata.capabilities:
            return False, f"Tool '{tool_name}' is classified as destructive and requires an explicit approval flow."
        if metadata.approval_required and not approved:
            return False, f"Tool '{tool_name}' requires approval before execution."
        if tool_name in {"bash", "shell", "run_command"}:
            for pattern in self.HARD_BLOCK_PATTERNS:
                if pattern in command:
                    return False, f"Command is hard-blocked by safety policy: {pattern}"
        return True, None


class ToolRegistry:
    """Registry that projects model-facing tools by execution surface."""

    def __init__(self, safety_policy: SafetyPolicy | None = None):
        self._tools: dict[str, RegisteredTool] = {}
        self.safety_policy = safety_policy or SafetyPolicy()

    def register(self, tool: Tool, metadata: ToolMetadata | None = None) -> RegisteredTool:
        metadata = metadata or infer_tool_metadata(tool)
        entry = RegisteredTool(tool=tool, metadata=metadata)
        self._tools[tool.name] = entry
        return entry

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list(self, toolset: str | None = None) -> list[RegisteredTool]:
        entries = list(self._tools.values())
        if toolset is not None:
            entries = [entry for entry in entries if toolset in entry.metadata.toolsets]
        return entries

    def schemas(self, toolset: str | None = None) -> list[dict[str, Any]]:
        return [entry.to_schema() for entry in self.list(toolset=toolset)]

    def check_call(self, tool_name: str, arguments: dict[str, Any], approved: bool = False) -> tuple[bool, str | None]:
        entry = self.get(tool_name)
        if entry is None:
            return False, f"Tool not registered: {tool_name}"
        return self.safety_policy.check(tool_name, arguments, entry.metadata, approved=approved)


def infer_tool_metadata(tool: Tool) -> ToolMetadata:
    name = tool.name
    if name in {"read_file", "list_files", "search_files", "grep", "list_dir"}:
        return ToolMetadata(name=name, capabilities=frozenset({ToolCapability.READ}), risk=ToolRisk.LOW)
    if name == "glob":
        return ToolMetadata(name=name, capabilities=frozenset({ToolCapability.READ}), risk=ToolRisk.LOW)
    if name in {"write_file", "edit_file"}:
        return ToolMetadata(
            name=name,
            capabilities=frozenset({ToolCapability.WRITE}),
            risk=ToolRisk.MEDIUM,
            approval_required=True,
        )
    if name == "bash":
        return ToolMetadata(
            name=name,
            capabilities=frozenset({ToolCapability.EXECUTE}),
            risk=ToolRisk.HIGH,
            approval_required=True,
            toolsets=frozenset({"cli", "web"}),
        )
    if name.startswith("mcp_") or "web" in name:
        return ToolMetadata(name=name, capabilities=frozenset({ToolCapability.NETWORK}), risk=ToolRisk.MEDIUM)
    return ToolMetadata(name=name)


def build_tool_registry(tools: list[Tool], metadata_provider: Callable[[Tool], ToolMetadata] = infer_tool_metadata) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool, metadata_provider(tool))
    return registry
