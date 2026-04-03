"""Session Note Tool - Let agent record and recall important information.

This tool allows the agent to:
- Record key points and important information during sessions
- Recall previously recorded notes with fast keyword-based search
- Maintain context across agent execution chains
- Tree-structured memory storage with year/month/day hierarchy

Uses SQLite backend with FTS5 full-text search for efficient retrieval.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult
from ..memory_manager import (
    MemoryManager,
    get_memory_manager,
    MemoryImportance,
    MemoryCategory,
)


class RecordNoteTool(Tool):
    """Tool for recording session notes with importance levels.

    The agent can use this tool to:
    - Record important facts, decisions, or context during sessions
    - Set importance levels (critical/high/medium/normal)
    - Categorize notes for better organization
    - Keywords are auto-extracted for fast retrieval

    Example usage by agent:
    - record_note("User prefers Python with type hints", importance="critical")
    - record_note("Project uses Python 3.12 and async/await", category="project_info")
    - record_note("Decided to use SQLite for memory storage", importance="high", category="decision")
    """

    def __init__(self, memory_dir: str = None):
        """Initialize record note tool.

        Args:
            memory_dir: Custom memory directory path (default: ~/.open-agent/memory)
        """
        self.memory_manager = get_memory_manager(memory_dir)

    @property
    def name(self) -> str:
        return "record_note"

    @property
    def description(self) -> str:
        return (
            "Record important information as persistent memory. "
            "Use this to record key facts, user preferences, decisions, or context "
            "that should be remembered in future sessions. "
            "Set appropriate importance level: 'critical' for permanent memories (user info, preferences), "
            "'high' for important yearly events, 'medium' for monthly summaries, 'normal' for daily notes."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to record. Be concise but specific.",
                },
                "category": {
                    "type": "string",
                    "description": "Category for this note: user_info, user_preference, project_info, decision, event, conversation, knowledge, general",
                    "enum": ["user_info", "user_preference", "project_info", "decision", "event", "conversation", "knowledge", "general"],
                },
                "importance": {
                    "type": "string",
                    "description": "Importance level: 'critical' (permanent), 'high' (yearly), 'medium' (monthly), 'normal' (daily)",
                    "enum": ["critical", "high", "medium", "normal"],
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: Custom keywords for faster retrieval. Auto-extracted if not provided.",
                },
            },
            "required": ["content"],
        }

    async def execute(
        self,
        content: str,
        category: str = "general",
        importance: str = "normal",
        keywords: List[str] = None,
    ) -> ToolResult:
        """Record a session note.

        Args:
            content: The information to record
            category: Category for this note
            importance: Importance level
            keywords: Optional custom keywords

        Returns:
            ToolResult with success status and memory path
        """
        try:
            memory = self.memory_manager.record(
                content=content,
                category=category,
                importance=importance,
                keywords=keywords,
            )

            path = self.memory_manager.get_memory_path(memory)
            
            importance_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "normal": "🟢",
            }
            
            return ToolResult(
                success=True,
                content=f"{importance_emoji.get(importance, '📝')} Recorded: {content}\n"
                        f"   Category: {category}, Importance: {importance}\n"
                        f"   Path: {path}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to record note: {str(e)}",
            )


class RecallNotesTool(Tool):
    """Tool for recalling recorded session notes with fast retrieval.

    Supports multiple search modes:
    - Keyword search: Find memories by keywords (tree-structured index)
    - Full-text search: Search in memory content
    - Time-based search: Filter by time range or specific date
    - Category/importance filter: Filter by type and importance
    """

    def __init__(self, memory_dir: str = None):
        """Initialize recall notes tool.

        Args:
            memory_dir: Custom memory directory path
        """
        self.memory_manager = get_memory_manager(memory_dir)

    @property
    def name(self) -> str:
        return "recall_notes"

    @property
    def description(self) -> str:
        return (
            "Recall previously recorded memories. Supports multiple search modes:\n"
            "- Use 'query' for full-text search (e.g., 'movie we discussed')\n"
            "- Use 'keywords' for fast indexed search (e.g., ['电影', 'movie'])\n"
            "- Use 'time_range' for recent memories (today/week/month/year)\n"
            "- Use 'category' or 'importance' to filter results\n"
            "Combine multiple filters for precise retrieval."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Full-text search query. Searches in memory content.",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords for indexed search. Faster than full-text search.",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category: user_info, user_preference, project_info, decision, event, conversation, knowledge, general",
                },
                "importance": {
                    "type": "string",
                    "description": "Filter by importance: critical, high, medium, normal",
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range filter: today, week, month, year, all",
                    "enum": ["today", "week", "month", "year", "all"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of memories to return (default: 20)",
                },
            },
        }

    async def execute(
        self,
        query: str = None,
        keywords: List[str] = None,
        category: str = None,
        importance: str = None,
        time_range: str = None,
        limit: int = 20,
    ) -> ToolResult:
        """Recall session notes.

        Args:
            query: Full-text search query
            keywords: Keywords for indexed search
            category: Filter by category
            importance: Filter by importance
            time_range: Time range filter
            limit: Maximum results

        Returns:
            ToolResult with matching memories
        """
        try:
            # 处理 time_range='all' 的情况
            if time_range == "all":
                time_range = None
            
            memories = self.memory_manager.recall(
                query=query,
                keywords=keywords,
                category=category,
                importance=importance,
                time_range=time_range,
                limit=limit,
            )

            if not memories:
                filters = []
                if query:
                    filters.append(f"query='{query}'")
                if keywords:
                    filters.append(f"keywords={keywords}")
                if category:
                    filters.append(f"category={category}")
                if importance:
                    filters.append(f"importance={importance}")
                if time_range:
                    filters.append(f"time_range={time_range}")
                
                filter_str = f" with {', '.join(filters)}" if filters else ""
                return ToolResult(
                    success=True,
                    content=f"No memories found{filter_str}. Try different search terms.",
                )

            # Format results
            lines = [f"📚 Found {len(memories)} memories:\n"]
            
            importance_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "normal": "🟢",
            }
            
            for memory in memories:
                emoji = importance_emoji.get(memory.importance, "📝")
                date_str = f"{memory.year}-{memory.month:02d}-{memory.day:02d}"
                
                lines.append(f"{emoji} [{date_str}] [{memory.category}]")
                lines.append(f"   {memory.content}")
                
                if memory.keywords:
                    lines.append(f"   Keywords: {', '.join(memory.keywords[:5])}")
                
                lines.append("")

            return ToolResult(
                success=True,
                content="\n".join(lines),
            )

        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to recall notes: {str(e)}",
            )


class SearchMemoryTreeTool(Tool):
    """Tool for exploring memory tree structure by keyword.

    Shows how a keyword is distributed across years/months/days,
    helping to quickly locate specific memories.
    """

    def __init__(self, memory_dir: str = None):
        """Initialize search memory tree tool."""
        self.memory_manager = get_memory_manager(memory_dir)

    @property
    def name(self) -> str:
        return "search_memory_tree"

    @property
    def description(self) -> str:
        return (
            "Search the memory tree structure by keyword. "
            "Shows how memories with this keyword are distributed across years, months, and days. "
            "Use this to quickly locate when a specific topic was discussed. "
            "Example: search_memory_tree(keyword='电影') shows all years/months/days where movies were discussed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "The keyword to search in the memory tree",
                },
            },
            "required": ["keyword"],
        }

    async def execute(self, keyword: str) -> ToolResult:
        """Search memory tree by keyword.

        Args:
            keyword: The keyword to search

        Returns:
            ToolResult with tree structure
        """
        try:
            tree = self.memory_manager.find_by_keyword_tree(keyword)

            if tree['total_count'] == 0:
                return ToolResult(
                    success=True,
                    content=f"No memories found with keyword: '{keyword}'",
                )

            # Format tree output
            lines = [
                f"🌳 Memory Tree for '{keyword}' ({tree['total_count']} memories)\n",
                "─" * 50,
            ]

            for year, year_data in sorted(tree['years'].items(), reverse=True):
                lines.append(f"\n📅 {year} ({year_data['count']} memories)")
                
                for month, month_data in sorted(year_data['months'].items(), reverse=True):
                    lines.append(f"   📁 {month:02d}月 ({month_data['count']} memories)")
                    
                    for day, count in sorted(month_data['days'].items(), reverse=True):
                        lines.append(f"      📄 {day:02d}日: {count} memories")

            lines.append("\n" + "─" * 50)
            lines.append(f"\n💡 Use recall_notes(keywords=['{keyword}']) to retrieve specific memories")

            return ToolResult(
                success=True,
                content="\n".join(lines),
            )

        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to search memory tree: {str(e)}",
            )


class GetMemoryStatsTool(Tool):
    """Tool for getting memory statistics."""

    def __init__(self, memory_dir: str = None):
        """Initialize get memory stats tool."""
        self.memory_manager = get_memory_manager(memory_dir)

    @property
    def name(self) -> str:
        return "get_memory_stats"

    @property
    def description(self) -> str:
        return (
            "Get statistics about stored memories: total count, "
            "distribution by importance/category/year, and unique keywords."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self) -> ToolResult:
        """Get memory statistics."""
        try:
            stats = self.memory_manager.get_stats()

            lines = [
                "📊 Memory Statistics\n",
                "─" * 40,
                f"\nTotal Memories: {stats['total_memories']}",
                f"Unique Keywords: {stats['unique_keywords']}",
                f"\nDatabase: {stats['db_path']}\n",
            ]

            if stats['by_importance']:
                lines.append("\n📌 By Importance:")
                importance_order = ['critical', 'high', 'medium', 'normal']
                for imp in importance_order:
                    if imp in stats['by_importance']:
                        lines.append(f"   {imp}: {stats['by_importance'][imp]}")

            if stats['by_category']:
                lines.append("\n📂 By Category:")
                for cat, count in sorted(stats['by_category'].items(), key=lambda x: -x[1]):
                    lines.append(f"   {cat}: {count}")

            if stats['by_year']:
                lines.append("\n📅 By Year:")
                for year, count in sorted(stats['by_year'].items(), reverse=True):
                    lines.append(f"   {year}: {count}")

            return ToolResult(
                success=True,
                content="\n".join(lines),
            )

        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to get memory stats: {str(e)}",
            )


# Legacy aliases for backward compatibility
SessionNoteTool = RecordNoteTool
RecallNoteTool = RecallNotesTool