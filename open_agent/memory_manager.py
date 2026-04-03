#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Open Agent - 树状记忆存储系统

基于 SQLite 的树状记忆管理系统，支持：
- 分层记忆存储（年/月/日）
- 关键词索引快速检索
- 全文搜索（FTS5）
- 记忆压缩和摘要
- 重要性分级
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class MemoryImportance(Enum):
    """记忆重要性级别"""
    CRITICAL = "critical"  # 永久记忆（用户基础信息、偏好）
    HIGH = "high"          # 年度重要记忆
    MEDIUM = "medium"      # 月度重要记忆
    NORMAL = "normal"      # 日常记忆


class MemoryCategory(Enum):
    """记忆分类"""
    USER_INFO = "user_info"              # 用户基础信息
    USER_PREFERENCE = "user_preference"  # 用户偏好
    PROJECT_INFO = "project_info"        # 项目信息
    DECISION = "decision"                # 重要决策
    EVENT = "event"                      # 重要事件
    CONVERSATION = "conversation"        # 对话摘要
    KNOWLEDGE = "knowledge"              # 知识记录
    GENERAL = "general"                  # 一般记忆


@dataclass
class Memory:
    """记忆数据模型"""
    id: Optional[int] = None
    content: str = ""
    category: str = "general"
    importance: str = "normal"
    keywords: List[str] = None
    timestamp: str = None
    year: int = None
    month: int = None
    day: int = None
    parent_id: Optional[int] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()
        if self.keywords is None:
            self.keywords = []
        if self.metadata is None:
            self.metadata = {}
        
        # 从时间戳提取年月日
        if self.year is None or self.month is None or self.day is None:
            dt = datetime.fromisoformat(self.timestamp)
            self.year = self.year or dt.year
            self.month = self.month or dt.month
            self.day = self.day or dt.day
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "importance": self.importance,
            "keywords": self.keywords,
            "timestamp": self.timestamp,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "parent_id": self.parent_id,
            "metadata": self.metadata,
        }


class MemoryManager:
    """树状记忆管理器
    
    基于 SQLite 的记忆管理系统，支持：
    - 分层存储：年/月/日结构
    - 关键词索引：快速定位记忆
    - 全文搜索：FTS5 支持
    - 记忆压缩：智能摘要
    """
    
    # 记忆数据库文件名
    DB_FILE = "memory.db"
    
    # 线程本地存储，用于数据库连接
    _local = threading.local()
    
    def __init__(self, memory_dir: str = None):
        """初始化记忆管理器
        
        Args:
            memory_dir: 自定义记忆目录路径
        """
        if memory_dir:
            self.memory_dir = Path(memory_dir)
        else:
            # 使用统一的路径工具
            from .utils.path_utils import get_memory_dir
            self.memory_dir = get_memory_dir()
        
        # 确保目录存在
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        # 数据库文件路径
        self.db_path = self.memory_dir / self.DB_FILE
        
        # 初始化数据库
        self._init_database()
    
    @contextmanager
    def _get_connection(self):
        """获取线程安全的数据库连接"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row
        
        try:
            yield self._local.conn
        except Exception:
            self._local.conn.rollback()
            raise
    
    def _init_database(self):
        """初始化数据库表结构"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. 记忆主表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    importance TEXT DEFAULT 'normal',
                    keywords TEXT DEFAULT '[]',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    year INTEGER,
                    month INTEGER,
                    day INTEGER,
                    parent_id INTEGER,
                    metadata TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_id) REFERENCES memories(id)
                )
            """)
            
            # 2. 关键词索引表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    memory_id INTEGER NOT NULL,
                    level TEXT DEFAULT 'day',
                    year INTEGER,
                    month INTEGER,
                    day INTEGER,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
            """)
            
            # 3. 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_keywords_keyword 
                ON memory_keywords(keyword)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_keywords_ymd 
                ON memory_keywords(year, month, day)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_timestamp 
                ON memories(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_importance 
                ON memories(importance)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_category 
                ON memories(category)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_ymd 
                ON memories(year, month, day)
            """)
            
            # 4. 全文搜索虚拟表（FTS5）
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    content,
                    keywords,
                    category,
                    importance,
                    content='memories',
                    content_rowid='id'
                )
            """)
            
            # 5. 触发器：自动同步 FTS 索引
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_memories_ai 
                AFTER INSERT ON memories BEGIN
                    INSERT INTO memory_fts(rowid, content, keywords, category, importance)
                    VALUES (
                        new.id, 
                        new.content, 
                        new.keywords, 
                        new.category, 
                        new.importance
                    );
                END
            """)
            
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_memories_ad 
                AFTER DELETE ON memories BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, content, keywords, category, importance)
                    VALUES ('delete', old.id, old.content, old.keywords, old.category, old.importance);
                END
            """)
            
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_memories_au 
                AFTER UPDATE ON memories BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, content, keywords, category, importance)
                    VALUES ('delete', old.id, old.content, old.keywords, old.category, old.importance);
                    INSERT INTO memory_fts(rowid, content, keywords, category, importance)
                    VALUES (new.id, new.content, new.keywords, new.category, new.importance);
                END
            """)
            
            conn.commit()
    
    def record(
        self,
        content: str,
        category: str = "general",
        importance: str = "normal",
        keywords: List[str] = None,
        timestamp: str = None,
        parent_id: int = None,
        metadata: Dict[str, Any] = None,
    ) -> Memory:
        """记录一条记忆
        
        Args:
            content: 记忆内容
            category: 分类（user_info, user_preference, project_info, decision, event, conversation, knowledge, general）
            importance: 重要性（critical, high, medium, normal）
            keywords: 关键词列表
            timestamp: 时间戳（默认当前时间）
            parent_id: 父记忆ID（用于关联）
            metadata: 额外元数据
            
        Returns:
            创建的 Memory 对象
        """
        # 处理时间戳
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        
        dt = datetime.fromisoformat(timestamp)
        year, month, day = dt.year, dt.month, dt.day
        
        # 处理关键词
        if keywords is None:
            keywords = self._extract_keywords(content)
        
        keywords_json = json.dumps(keywords, ensure_ascii=False)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 插入记忆
            cursor.execute("""
                INSERT INTO memories (content, category, importance, keywords, timestamp, year, month, day, parent_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (content, category, importance, keywords_json, timestamp, year, month, day, parent_id, metadata_json))
            
            memory_id = cursor.lastrowid
            
            # 插入关键词索引
            self._insert_keyword_indexes(cursor, memory_id, keywords, year, month, day)
            
            conn.commit()
        
        return Memory(
            id=memory_id,
            content=content,
            category=category,
            importance=importance,
            keywords=keywords,
            timestamp=timestamp,
            year=year,
            month=month,
            day=day,
            parent_id=parent_id,
            metadata=metadata,
        )
    
    def _extract_keywords(self, content: str) -> List[str]:
        """从内容中提取关键词
        
        简单实现：提取中文词组和英文单词
        可以后续接入 NLP 库进行更智能的提取
        """
        import re
        
        keywords = []
        
        # 提取中文词组（2-4个字）
        chinese_pattern = r'[\u4e00-\u9fa5]{2,4}'
        chinese_matches = re.findall(chinese_pattern, content)
        keywords.extend(chinese_matches[:5])  # 最多5个
        
        # 提取英文单词（3个字母以上）
        english_pattern = r'\b[a-zA-Z]{3,}\b'
        english_matches = re.findall(english_pattern, content)
        keywords.extend([w.lower() for w in english_matches[:5]])
        
        return list(set(keywords))[:10]  # 去重，最多10个
    
    def _insert_keyword_indexes(
        self,
        cursor: sqlite3.Cursor,
        memory_id: int,
        keywords: List[str],
        year: int,
        month: int,
        day: int,
    ):
        """插入关键词索引"""
        for keyword in keywords:
            cursor.execute("""
                INSERT INTO memory_keywords (keyword, memory_id, level, year, month, day)
                VALUES (?, ?, 'day', ?, ?, ?)
            """, (keyword, memory_id, year, month, day))
    
    def recall(
        self,
        query: str = None,
        keywords: List[str] = None,
        category: str = None,
        importance: str = None,
        time_range: str = None,
        year: int = None,
        month: int = None,
        day: int = None,
        limit: int = 50,
    ) -> List[Memory]:
        """检索记忆
        
        Args:
            query: 全文搜索查询
            keywords: 关键词列表
            category: 分类过滤
            importance: 重要性过滤
            time_range: 时间范围（today, week, month, year, all）
            year: 年份过滤
            month: 月份过滤
            day: 日期过滤
            limit: 返回数量限制
            
        Returns:
            匹配的 Memory 列表
        """
        memories = []
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 构建查询
            if query:
                # 全文搜索
                memories = self._fts_search(cursor, query, limit)
            elif keywords:
                # 关键词索引搜索
                memories = self._keyword_search(cursor, keywords, category, importance, time_range, year, month, day, limit)
            else:
                # 普通条件搜索
                memories = self._condition_search(cursor, category, importance, time_range, year, month, day, limit)
        
        return memories
    
    def _fts_search(self, cursor: sqlite3.Cursor, query: str, limit: int) -> List[Memory]:
        """全文搜索"""
        cursor.execute("""
            SELECT m.* FROM memories m
            JOIN memory_fts fts ON m.id = fts.rowid
            WHERE memory_fts MATCH ?
            ORDER BY m.timestamp DESC
            LIMIT ?
        """, (query, limit))
        
        return [self._row_to_memory(row) for row in cursor.fetchall()]
    
    def _keyword_search(
        self,
        cursor: sqlite3.Cursor,
        keywords: List[str],
        category: str,
        importance: str,
        time_range: str,
        year: int,
        month: int,
        day: int,
        limit: int,
    ) -> List[Memory]:
        """关键词索引搜索 - 树状定位"""
        
        # 构建基础查询
        sql = """
            SELECT DISTINCT m.* FROM memories m
            JOIN memory_keywords mk ON m.id = mk.memory_id
            WHERE mk.keyword IN ({})
        """.format(','.join('?' * len(keywords)))
        
        params = list(keywords)
        
        # 添加条件
        if category:
            sql += " AND m.category = ?"
            params.append(category)
        
        if importance:
            sql += " AND m.importance = ?"
            params.append(importance)
        
        if year:
            sql += " AND m.year = ?"
            params.append(year)
            
            if month:
                sql += " AND m.month = ?"
                params.append(month)
                
                if day:
                    sql += " AND m.day = ?"
                    params.append(day)
        
        sql += " ORDER BY m.timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        return [self._row_to_memory(row) for row in cursor.fetchall()]
    
    def _condition_search(
        self,
        cursor: sqlite3.Cursor,
        category: str,
        importance: str,
        time_range: str,
        year: int,
        month: int,
        day: int,
        limit: int,
    ) -> List[Memory]:
        """条件搜索"""
        sql = "SELECT * FROM memories WHERE 1=1"
        params = []
        
        if category:
            sql += " AND category = ?"
            params.append(category)
        
        if importance:
            sql += " AND importance = ?"
            params.append(importance)
        
        if year:
            sql += " AND year = ?"
            params.append(year)
            
            if month:
                sql += " AND month = ?"
                params.append(month)
                
                if day:
                    sql += " AND day = ?"
                    params.append(day)
        
        if time_range:
            now = datetime.now()
            if time_range == "today":
                sql += " AND date(timestamp) = date(?)"
                params.append(now.isoformat())
            elif time_range == "week":
                week_ago = (now - timedelta(days=7)).isoformat()
                sql += " AND timestamp >= ?"
                params.append(week_ago)
            elif time_range == "month":
                month_ago = (now - timedelta(days=30)).isoformat()
                sql += " AND timestamp >= ?"
                params.append(month_ago)
            elif time_range == "year":
                year_ago = (now - timedelta(days=365)).isoformat()
                sql += " AND timestamp >= ?"
                params.append(year_ago)
        
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        return [self._row_to_memory(row) for row in cursor.fetchall()]
    
    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        """将数据库行转换为 Memory 对象"""
        return Memory(
            id=row['id'],
            content=row['content'],
            category=row['category'],
            importance=row['importance'],
            keywords=json.loads(row['keywords']),
            timestamp=row['timestamp'],
            year=row['year'],
            month=row['month'],
            day=row['day'],
            parent_id=row['parent_id'],
            metadata=json.loads(row['metadata']),
        )
    
    def get_by_id(self, memory_id: int) -> Optional[Memory]:
        """根据ID获取记忆"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_memory(row)
        return None
    
    def get_memory_path(self, memory: Memory) -> str:
        """获取记忆的树状路径
        
        Returns:
            如 "2025/02/27#123" 的路径字符串
        """
        return f"{memory.year}/{memory.month:02d}/{memory.day:02d}#{memory.id}"
    
    def find_by_keyword_tree(self, keyword: str) -> Dict[str, Any]:
        """通过关键词树状检索记忆
        
        返回关键词在各个时间层的分布情况
        """
        result = {
            "keyword": keyword,
            "years": {},
            "total_count": 0,
        }
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 查询关键词在各年份的分布
            cursor.execute("""
                SELECT year, COUNT(DISTINCT memory_id) as count
                FROM memory_keywords
                WHERE keyword = ?
                GROUP BY year
                ORDER BY year DESC
            """, (keyword,))
            
            for row in cursor.fetchall():
                year = row['year']
                count = row['count']
                result['years'][year] = {
                    'count': count,
                    'months': {},
                }
                result['total_count'] += count
            
            # 查询每个月份的分布
            for year in result['years']:
                cursor.execute("""
                    SELECT month, COUNT(DISTINCT memory_id) as count
                    FROM memory_keywords
                    WHERE keyword = ? AND year = ?
                    GROUP BY month
                    ORDER BY month DESC
                """, (keyword, year))
                
                for row in cursor.fetchall():
                    month = row['month']
                    count = row['count']
                    result['years'][year]['months'][month] = {
                        'count': count,
                        'days': {},
                    }
            
            # 查询每天的分布
            for year in result['years']:
                for month in result['years'][year]['months']:
                    cursor.execute("""
                        SELECT day, COUNT(DISTINCT memory_id) as count
                        FROM memory_keywords
                        WHERE keyword = ? AND year = ? AND month = ?
                        GROUP BY day
                        ORDER BY day DESC
                    """, (keyword, year, month))
                    
                    for row in cursor.fetchall():
                        day = row['day']
                        count = row['count']
                        result['years'][year]['months'][month]['days'][day] = count
        
        return result
    
    def get_memories_by_date(self, year: int, month: int = None, day: int = None) -> List[Memory]:
        """获取指定日期的记忆"""
        return self.recall(year=year, month=month, day=day)
    
    def update(self, memory_id: int, **kwargs) -> bool:
        """更新记忆"""
        allowed_fields = ['content', 'category', 'importance', 'keywords', 'metadata']
        
        updates = []
        params = []
        
        for field in allowed_fields:
            if field in kwargs:
                if field in ['keywords', 'metadata']:
                    updates.append(f"{field} = ?")
                    params.append(json.dumps(kwargs[field], ensure_ascii=False))
                else:
                    updates.append(f"{field} = ?")
                    params.append(kwargs[field])
        
        if not updates:
            return False
        
        params.append(memory_id)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE memories SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                params
            )
            conn.commit()
        
        return True
    
    def delete(self, memory_id: int) -> bool:
        """删除记忆"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
        return True
    
    def compress_day(self, year: int, month: int, day: int, summary: str = None) -> Optional[Memory]:
        """压缩当天的记忆为摘要
        
        Args:
            year: 年份
            month: 月份
            day: 日期
            summary: 自定义摘要内容（如果为None则返回当天记忆列表供外部压缩）
            
        Returns:
            压缩后的摘要记忆
        """
        # 获取当天所有记忆
        memories = self.get_memories_by_date(year, month, day)
        
        if not memories:
            return None
        
        if summary is None:
            # 返回记忆列表，让调用方（可能是 LLM）生成摘要
            return memories
        
        # 创建摘要记忆
        compressed = self.record(
            content=summary,
            category="conversation",
            importance="medium",
            keywords=[f"{year}-{month:02d}-{day:02d}", "daily-summary"],
            timestamp=f"{year}-{month:02d}-{day:02d}T23:59:59",
            metadata={
                "type": "daily_summary",
                "memory_count": len(memories),
                "memory_ids": [m.id for m in memories],
            }
        )
        
        return compressed
    
    def export_to_json(self, output_dir: Path = None) -> Dict[str, Any]:
        """导出记忆为 JSON 格式
        
        Args:
            output_dir: 导出目录（默认为 memory_dir/exports）
            
        Returns:
            导出统计信息
        """
        if output_dir is None:
            output_dir = self.memory_dir / "exports"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        stats = {
            "export_time": datetime.now().isoformat(),
            "files": [],
            "total_memories": 0,
        }
        
        # 按年/月/日结构导出
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取所有年份
            cursor.execute("SELECT DISTINCT year FROM memories ORDER BY year")
            years = [row['year'] for row in cursor.fetchall()]
            
            for year in years:
                year_dir = output_dir / str(year)
                year_dir.mkdir(exist_ok=True)
                
                # 获取该年所有月份
                cursor.execute(
                    "SELECT DISTINCT month FROM memories WHERE year = ? ORDER BY month",
                    (year,)
                )
                months = [row['month'] for row in cursor.fetchall()]
                
                for month in months:
                    month_dir = year_dir / f"{month:02d}"
                    month_dir.mkdir(exist_ok=True)
                    
                    # 获取该月所有日期
                    cursor.execute(
                        "SELECT DISTINCT day FROM memories WHERE year = ? AND month = ? ORDER BY day",
                        (year, month)
                    )
                    days = [row['day'] for row in cursor.fetchall()]
                    
                    for day in days:
                        # 导出当天的记忆
                        memories = self.get_memories_by_date(year, month, day)
                        
                        file_path = month_dir / f"{year}-{month:02d}-{day:02d}.json"
                        data = {
                            "date": f"{year}-{month:02d}-{day:02d}",
                            "memory_count": len(memories),
                            "memories": [m.to_dict() for m in memories],
                        }
                        
                        file_path.write_text(
                            json.dumps(data, indent=2, ensure_ascii=False),
                            encoding='utf-8'
                        )
                        
                        stats['files'].append(str(file_path))
                        stats['total_memories'] += len(memories)
        
        # 写入导出统计
        stats_file = output_dir / "export_stats.json"
        stats_file.write_text(
            json.dumps(stats, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        
        return stats
    
    def get_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 总记忆数
            cursor.execute("SELECT COUNT(*) as count FROM memories")
            total = cursor.fetchone()['count']
            
            # 按重要性统计
            cursor.execute("""
                SELECT importance, COUNT(*) as count 
                FROM memories 
                GROUP BY importance
            """)
            by_importance = {row['importance']: row['count'] for row in cursor.fetchall()}
            
            # 按分类统计
            cursor.execute("""
                SELECT category, COUNT(*) as count 
                FROM memories 
                GROUP BY category
            """)
            by_category = {row['category']: row['count'] for row in cursor.fetchall()}
            
            # 按年份统计
            cursor.execute("""
                SELECT year, COUNT(*) as count 
                FROM memories 
                GROUP BY year 
                ORDER BY year DESC
            """)
            by_year = {row['year']: row['count'] for row in cursor.fetchall()}
            
            # 关键词数量
            cursor.execute("SELECT COUNT(DISTINCT keyword) as count FROM memory_keywords")
            keyword_count = cursor.fetchone()['count']
            
            return {
                "total_memories": total,
                "by_importance": by_importance,
                "by_category": by_category,
                "by_year": by_year,
                "unique_keywords": keyword_count,
                "db_path": str(self.db_path),
            }
    
    def close(self):
        """关闭数据库连接"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# 单例模式
_memory_manager_instance: Optional[MemoryManager] = None


def get_memory_manager(memory_dir: str = None) -> MemoryManager:
    """获取记忆管理器单例"""
    global _memory_manager_instance
    if _memory_manager_instance is None:
        _memory_manager_instance = MemoryManager(memory_dir)
    return _memory_manager_instance