"""Caching for code review results."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Default cache settings
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "coderev"
DEFAULT_CACHE_TTL_HOURS = 168  # 1 week

# Suffix for the temporary files used to stage atomic cache writes.
TEMP_SUFFIX = ".tmp"

# On Windows, os.replace() fails if another process has the destination open,
# which a concurrent reader does for a moment. Retry a few times before giving up.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_SECONDS = 0.01

# How an attempt to load an entry off disk turned out. The distinction that
# matters is CORRUPT (the bytes were read and are garbage -- safe to drop) vs
# UNREADABLE (the bytes were never seen, so the entry must be left alone).
_OK = "ok"
_MISSING = "missing"
_UNREADABLE = "unreadable"
_CORRUPT = "corrupt"


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

    @staticmethod
    def _write_atomic(cache_path: Path, payload: dict[str, Any]) -> None:
        """Serialize `payload` to `cache_path` atomically.

        The cache directory is shared between concurrent reviews (async batches,
        a pre-commit hook running alongside a CI review, ...). Writing JSON
        straight into the destination leaves a window where a reader sees a
        truncated file -- and `get()` treats unparseable entries as corrupt and
        deletes them, so a partial write would destroy a perfectly good entry.

        Instead, stage the content in a temp file in the same directory (same
        filesystem, so the rename cannot cross devices) and swap it in with
        os.replace(), which is atomic on both POSIX and Windows. A reader
        therefore only ever observes the old file or the new one, never a
        half-written one.

        Raises:
            OSError: If the entry could not be written or swapped into place.
                The destination is left untouched and no temp file survives.
        """
        fd, tmp_name = tempfile.mkstemp(
            dir=cache_path.parent,
            prefix=f".{cache_path.stem}.",
            suffix=TEMP_SUFFIX,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            last_error: PermissionError | None = None
            for attempt in range(_REPLACE_ATTEMPTS):
                try:
                    os.replace(tmp_path, cache_path)
                    return
                except PermissionError as exc:  # Windows: reader holds the file open
                    last_error = exc
                    time.sleep(_REPLACE_BACKOFF_SECONDS * (attempt + 1))
            raise last_error  # type: ignore[misc]
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

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
        
        entry, state = self._load_entry(cache_path)

        if state == _CORRUPT:
            self._discard(cache_path)
            return None
        if entry is None:
            # Missing, or it stayed unreadable -- on Windows a concurrent writer's
            # os.replace() locks the file for an instant. That is a transient miss,
            # not corruption, so leave the entry alone and recompute.
            return None

        if entry.is_expired():
            self._discard(cache_path)
            return None

        return entry.result

    @classmethod
    def _load_entry(cls, cache_path: Path) -> tuple[CacheEntry | None, str]:
        """Load one entry off disk, reporting *why* it could not be loaded.

        Every caller that reads an entry goes through here, because the safe
        reaction to a failed read depends entirely on whether the bytes were
        actually seen. Writes are atomic, so JSON that parses badly is genuinely
        corrupt and may be dropped. But a read that never completed -- a
        concurrent writer's os.replace() holding a Windows lock, an I/O blip --
        says nothing about the entry, and deleting on that basis destroys a
        perfectly valid cached review.

        Returns:
            (entry, _OK) when the entry parsed, else (None, _MISSING/_UNREADABLE/_CORRUPT).
        """
        raw = cls._read_with_retry(cache_path)
        if raw is None:
            return None, _MISSING if not cache_path.exists() else _UNREADABLE

        try:
            return CacheEntry.from_dict(json.loads(raw)), _OK
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, KeyError):
            # Written by an incompatible version, or truncated by a pre-atomic
            # writer. Either way the content is unusable: drop it.
            return None, _CORRUPT

    def _entry_files(self) -> list[Path]:
        """Every file in the cache dir that is meant to be an entry.

        Materialized into a list so a concurrent clear()/prune() mutating the
        directory cannot disturb an in-progress walk. Temp files staged by
        _write_atomic() are debris, not entries, and never count.
        """
        return [
            path
            for path in self.cache_dir.rglob("*.json")
            if not path.name.endswith(TEMP_SUFFIX)
        ]

    @staticmethod
    def _read_with_retry(cache_path: Path) -> str | None:
        """Read a cache entry, retrying while a concurrent writer holds it locked.

        Returns None if the entry is missing or stayed unreadable, in which case
        the caller must treat it as a miss (never as corruption -- the bytes were
        never seen, so there is nothing to judge).
        """
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                return cache_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                # Pruned or replaced out from under us; nothing to retry for.
                return None
            except PermissionError:  # Windows: writer is swapping the file in
                time.sleep(_REPLACE_BACKOFF_SECONDS * (attempt + 1))
            except OSError:
                return None
        return None

    @staticmethod
    def _discard(cache_path: Path) -> bool:
        """Delete a cache entry, tolerating a concurrent deletion or a lock.

        Returns True only if this call actually removed the file, so callers can
        report a count that reflects what happened rather than what was intended.
        """
        try:
            cache_path.unlink()
        except OSError:
            # Another process holds it open, or already removed it.
            return False
        return True

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
            self._write_atomic(cache_path, entry.to_dict())
        except (OSError, TypeError, ValueError):
            # Cache write failures are non-fatal: any previously cached entry
            # for this key is still intact, and the next review just recomputes.
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

        # Sweep temp files left behind by a writer that was killed mid-write.
        # They are not entries, so they are removed but not counted.
        for tmp_file in self.cache_dir.rglob(f"*{TEMP_SUFFIX}"):
            try:
                tmp_file.unlink()
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
        """Remove expired (and corrupt) cache entries.

        An entry is only ever deleted on evidence read off disk: it parsed and
        is past its TTL, or it parsed as garbage. An entry that could not be
        read -- a concurrent writer's os.replace() holding a Windows lock, a
        transient I/O error -- is left strictly alone, because a failed read is
        not evidence of anything and pruning on it would silently destroy valid
        cached reviews.

        Returns:
            Number of entries actually removed.
        """
        if not self.cache_dir.exists():
            return 0

        count = 0
        for cache_file in self._entry_files():
            entry, state = self._load_entry(cache_file)

            if state in (_MISSING, _UNREADABLE):
                continue

            if state == _CORRUPT or entry.is_expired():  # type: ignore[union-attr]
                if self._discard(cache_file):
                    count += 1

        return count

    def stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics including:
            - total_entries: Number of cached entries
            - total_size_bytes: Total size of cache in bytes
            - expired_entries: Number of entries prune_expired() would remove
              (past their TTL, or corrupt)
            - unreadable_entries: Number of entries that could not be read this
              scan (transient -- they are not pruned and may well be valid)
            - cache_dir: Path to cache directory
        """
        total = 0
        expired = 0
        unreadable = 0
        size = 0

        for cache_file in self._entry_files() if self.cache_dir.exists() else []:
            entry, state = self._load_entry(cache_file)
            if state == _MISSING:
                # Removed by a concurrent clear()/prune() mid-scan: not an entry.
                continue

            try:
                size += cache_file.stat().st_size
            except OSError:
                # Vanished (or locked) between the read and the stat. Reporting
                # statistics must never be the thing that crashes a review.
                continue

            total += 1
            if state == _UNREADABLE:
                unreadable += 1
            elif state == _CORRUPT or entry.is_expired():  # type: ignore[union-attr]
                # Corrupt entries are counted as expired: prune_expired() drops
                # both, so this stays the "how many would pruning remove" number.
                expired += 1

        return {
            "total_entries": total,
            "total_size_bytes": size,
            "expired_entries": expired,
            "unreadable_entries": unreadable,
            "cache_dir": str(self.cache_dir),
        }
