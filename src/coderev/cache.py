"""Caching for code review results."""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Default cache settings
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "coderev"
DEFAULT_CACHE_TTL_HOURS = 168  # 1 week


@dataclass
class CacheEntry:
    """A cached review result."""
    
    result: dict[str, Any]
    created_at: str
    ttl_hours: int
    cache_key: str
    model: str
    focus: list[str]
    
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        created = datetime.fromisoformat(self.created_at)
        return datetime.now() - created > timedelta(hours=self.ttl_hours)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheEntry:
        """Create from dictionary."""
        return cls(
            result=data["result"],
            created_at=data["created_at"],
            ttl_hours=data["ttl_hours"],
            cache_key=data["cache_key"],
            model=data["model"],
            focus=data["focus"],
        )


class ReviewCache:
    """File-based cache for code review results.
    
    Cache keys are generated from:
    - Content hash (SHA-256)
    - Model name
    - Focus areas (sorted)
    - Language (if provided)
    
    This ensures that changing any review parameter invalidates the cache.
    """
    
    def __init__(
        self,
        cache_dir: Path | str | None = None,
        ttl_hours: int = DEFAULT_CACHE_TTL_HOURS,
        enabled: bool = True,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.ttl_hours = ttl_hours
        self.enabled = enabled
        
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _generate_cache_key(
        self,
        content: str,
        model: str,
        focus: list[str] | None = None,
        language: str | None = None,
    ) -> str:
        """Generate a unique cache key for the review parameters.
        
        The key is a SHA-256 hash of the combined parameters, ensuring that
        any change to content, model, focus, or language produces a different key.
        
        Unicode content is normalized to NFC form before hashing to ensure
        consistent cache keys regardless of unicode representation.
        """
        # Normalize unicode content to NFC form for consistent hashing
        # This handles cases where the same character can be represented
        # differently (e.g., é as single codepoint vs e + combining accent)
        normalized_content = unicodedata.normalize('NFC', content)
        
        # Sort focus areas for consistent hashing
        focus_str = ",".join(sorted(focus or []))
        
        # Combine all parameters
        key_content = f"{normalized_content}|{model}|{focus_str}|{language or ''}"
        
        # Generate SHA-256 hash
        return hashlib.sha256(key_content.encode("utf-8")).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """Get the file path for a cache key.
        
        Uses first 2 characters as subdirectory to avoid too many files
        in a single directory.
        """
        subdir = cache_key[:2]
        return self.cache_dir / subdir / f"{cache_key}.json"
    
    def get(
        self,
        content: str,
        model: str,
        focus: list[str] | None = None,
        language: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a cached review result if available and not expired.
        
        Args:
            content: The code content being reviewed.
            model: The AI model being used.
            focus: List of focus areas for the review.
            language: The programming language (optional).
            
        Returns:
            The cached result dictionary if found and valid, None otherwise.
        """
        if not self.enabled:
            return None
        
        cache_key = self._generate_cache_key(content, model, focus, language)
        cache_path = self._get_cache_path(cache_key)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            entry = CacheEntry.from_dict(data)
            
            if entry.is_expired():
                # Clean up expired entry
                cache_path.unlink(missing_ok=True)
                return None
            
            return entry.result
            
        except (json.JSONDecodeError, KeyError, OSError):
            # Invalid cache entry, remove it
            cache_path.unlink(missing_ok=True)
            return None
    
    def set(
        self,
        content: str,
        model: str,
        result: dict[str, Any],
        focus: list[str] | None = None,
        language: str | None = None,
    ) -> None:
        """Store a review result in the cache.
        
        Args:
            content: The code content that was reviewed.
            model: The AI model that was used.
            result: The review result dictionary to cache.
            focus: List of focus areas used for the review.
            language: The programming language (optional).
        """
        if not self.enabled:
            return
        
        cache_key = self._generate_cache_key(content, model, focus, language)
        cache_path = self._get_cache_path(cache_key)
        
        # Ensure subdirectory exists
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        entry = CacheEntry(
            result=result,
            created_at=datetime.now().isoformat(),
            ttl_hours=self.ttl_hours,
            cache_key=cache_key,
            model=model,
            focus=focus or [],
        )
        
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)
        except OSError:
            # Cache write failures are non-fatal
            pass
    
    def clear(self) -> int:
        """Clear all cached entries.
        
        Returns:
            Number of entries cleared.
        """
        if not self.cache_dir.exists():
            return 0
        
        count = 0
        for cache_file in self.cache_dir.rglob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass
        
        # Clean up empty subdirectories
        for subdir in self.cache_dir.iterdir():
            if subdir.is_dir() and not any(subdir.iterdir()):
                try:
                    subdir.rmdir()
                except OSError:
                    pass
        
        return count
    
    def prune_expired(self) -> int:
        """Remove all expired cache entries.
        
        Returns:
            Number of entries pruned.
        """
        if not self.cache_dir.exists():
            return 0
        
        count = 0
        for cache_file in self.cache_dir.rglob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = CacheEntry.from_dict(data)
                if entry.is_expired():
                    cache_file.unlink()
                    count += 1
            except (json.JSONDecodeError, KeyError, OSError):
                # Invalid entry, remove it
                try:
                    cache_file.unlink()
                    count += 1
                except OSError:
                    pass
        
        return count
    
    def stats(self) -> dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics including:
            - total_entries: Number of cached entries
            - total_size_bytes: Total size of cache in bytes
            - expired_entries: Number of expired entries
            - cache_dir: Path to cache directory
        """
        if not self.cache_dir.exists():
            return {
                "total_entries": 0,
                "total_size_bytes": 0,
                "expired_entries": 0,
                "cache_dir": str(self.cache_dir),
            }
        
        total = 0
        expired = 0
        size = 0
        
        for cache_file in self.cache_dir.rglob("*.json"):
            total += 1
            size += cache_file.stat().st_size
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = CacheEntry.from_dict(data)
                if entry.is_expired():
                    expired += 1
            except (json.JSONDecodeError, KeyError, OSError):
                expired += 1  # Count invalid entries as expired
        
        return {
            "total_entries": total,
            "total_size_bytes": size,
            "expired_entries": expired,
            "cache_dir": str(self.cache_dir),
        }
