"""Content cache for binary document extraction results.

Caches extracted text from PDF/DOCX/XLSX files to avoid repeated
expensive extraction. Invalidation is based on file mtime + size.

Cache layout:
    {workspace}/.workspace/cache/{sanitized_key}       — extracted text
    {workspace}/.workspace/cache/{sanitized_key}.meta   — JSON {mtime, size}

Ported from AgentEarthPlatform's getCachedBinDocText() pattern.
"""

import json
from pathlib import Path

from .doc_extract import read_file_content


class DocContentCache:
    """File-based content cache with mtime+size invalidation.

    Used to cache extracted text from binary documents (PDF, DOCX, XLSX)
    so that repeated reads of the same file don't re-extract.
    """

    def __init__(self, workspace_dir: Path):
        """Initialize the cache.

        Args:
            workspace_dir: The workspace root directory.
                Cache is stored at {workspace_dir}/.workspace/cache/.
        """
        self._cache_dir = workspace_dir / ".workspace" / "cache"

    def _ensure_dir(self) -> None:
        """Create the cache directory if it doesn't exist."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _cache_key(file_path: Path) -> str:
        """Generate a sanitized cache key from a file path."""
        # Replace path separators and special chars
        key = str(file_path).replace("\\", "__").replace("/", "__")
        # Remove any remaining unsafe chars
        key = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)
        return key

    def _text_path(self, file_path: Path) -> Path:
        """Get the path to the cached text file."""
        return self._cache_dir / self._cache_key(file_path)

    def _meta_path(self, file_path: Path) -> Path:
        """Get the path to the cache metadata file."""
        return self._cache_dir / (self._cache_key(file_path) + ".meta")

    def _is_valid(self, file_path: Path) -> bool:
        """Check if the cache entry is still valid (mtime + size match)."""
        text_path = self._text_path(file_path)
        meta_path = self._meta_path(file_path)

        if not text_path.exists() or not meta_path.exists():
            return False

        if not file_path.exists():
            return False

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            stat = file_path.stat()
            return (
                meta.get("mtime") == stat.st_mtime
                and meta.get("size") == stat.st_size
            )
        except (json.JSONDecodeError, OSError, KeyError):
            return False

    def _store(self, file_path: Path, text: str) -> None:
        """Store extracted text in the cache."""
        self._ensure_dir()
        text_path = self._text_path(file_path)
        meta_path = self._meta_path(file_path)

        try:
            text_path.write_text(text, encoding="utf-8")
            stat = file_path.stat()
            meta = json.dumps({"mtime": stat.st_mtime, "size": stat.st_size})
            meta_path.write_text(meta, encoding="utf-8")
        except OSError:
            pass  # Cache write failures are non-fatal

    def get(self, file_path: Path) -> str | None:
        """Get cached text for a file, or None if not cached or stale.

        Args:
            file_path: Absolute path to the file.

        Returns:
            Cached text content, or None if cache miss.
        """
        if not self._is_valid(file_path):
            return None

        try:
            return self._text_path(file_path).read_text(encoding="utf-8")
        except OSError:
            return None

    def put(self, file_path: Path, text: str) -> None:
        """Store text in the cache for a file.

        Args:
            file_path: Absolute path to the file.
            text: The extracted text content.
        """
        self._store(file_path, text)

    def get_or_extract(self, file_path: Path) -> str:
        """Get cached text, or extract and cache if not available.

        This is the main entry point for cache usage. If the file
        is cached and valid, returns the cached text. Otherwise,
        extracts the text (via read_file_content), caches it,
        and returns it.

        Args:
            file_path: Absolute path to the file.

        Returns:
            The file's text content (from cache or fresh extraction).
        """
        cached = self.get(file_path)
        if cached is not None:
            return cached

        # Cache miss — extract and store
        text = read_file_content(file_path)
        self.put(file_path, text)
        return text

    def invalidate(self, file_path: Path) -> None:
        """Remove a specific cache entry.

        Args:
            file_path: Absolute path to the file.
        """
        text_path = self._text_path(file_path)
        meta_path = self._meta_path(file_path)

        for p in (text_path, meta_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def clear(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries removed.
        """
        if not self._cache_dir.exists():
            return 0

        count = 0
        for f in self._cache_dir.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    count += 1
                except OSError:
                    pass
        return count
