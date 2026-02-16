"""Tests for review caching functionality."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from coderev.cache import CacheEntry, ReviewCache, DEFAULT_CACHE_TTL_HOURS


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""
    
    def test_is_expired_returns_false_for_fresh_entry(self) -> None:
        """Fresh entry should not be expired."""
        entry = CacheEntry(
            result={"summary": "test"},
            created_at=datetime.now().isoformat(),
            ttl_hours=24,
            cache_key="abc123",
            model="test-model",
            focus=["bugs"],
        )
        assert entry.is_expired() is False
    
    def test_is_expired_returns_true_for_old_entry(self) -> None:
        """Old entry should be expired."""
        old_time = datetime.now() - timedelta(hours=25)
        entry = CacheEntry(
            result={"summary": "test"},
            created_at=old_time.isoformat(),
            ttl_hours=24,
            cache_key="abc123",
            model="test-model",
            focus=["bugs"],
        )
        assert entry.is_expired() is True
    
    def test_to_dict_and_from_dict_roundtrip(self) -> None:
        """Entry should survive serialization roundtrip."""
        original = CacheEntry(
            result={"summary": "test", "issues": []},
            created_at=datetime.now().isoformat(),
            ttl_hours=168,
            cache_key="abc123def456",
            model="claude-3-sonnet",
            focus=["bugs", "security"],
        )
        
        data = original.to_dict()
        restored = CacheEntry.from_dict(data)
        
        assert restored.result == original.result
        assert restored.created_at == original.created_at
        assert restored.ttl_hours == original.ttl_hours
        assert restored.cache_key == original.cache_key
        assert restored.model == original.model
        assert restored.focus == original.focus


class TestReviewCache:
    """Tests for ReviewCache class."""
    
    @pytest.fixture
    def cache_dir(self) -> Path:
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def cache(self, cache_dir: Path) -> ReviewCache:
        """Create a ReviewCache with temporary directory."""
        return ReviewCache(cache_dir=cache_dir, ttl_hours=24, enabled=True)
    
    def test_disabled_cache_does_not_store(self, cache_dir: Path) -> None:
        """Disabled cache should not store or retrieve anything."""
        cache = ReviewCache(cache_dir=cache_dir, enabled=False)
        
        cache.set("code", "model", {"result": "test"}, ["bugs"])
        result = cache.get("code", "model", ["bugs"])
        
        assert result is None
    
    def test_get_returns_none_for_missing_key(self, cache: ReviewCache) -> None:
        """Cache miss should return None."""
        result = cache.get("nonexistent code", "model", ["bugs"])
        assert result is None
    
    def test_set_and_get_retrieves_cached_result(self, cache: ReviewCache) -> None:
        """Cached result should be retrievable."""
        code = "def hello(): pass"
        model = "claude-3-sonnet"
        focus = ["bugs", "security"]
        expected_result = {"summary": "Looks good!", "issues": [], "score": 90}
        
        cache.set(code, model, expected_result, focus)
        result = cache.get(code, model, focus)
        
        assert result == expected_result
    
    def test_different_code_produces_cache_miss(self, cache: ReviewCache) -> None:
        """Different code should not match cached result."""
        cache.set("code1", "model", {"result": "one"}, ["bugs"])
        result = cache.get("code2", "model", ["bugs"])
        
        assert result is None
    
    def test_different_model_produces_cache_miss(self, cache: ReviewCache) -> None:
        """Different model should not match cached result."""
        cache.set("code", "model1", {"result": "one"}, ["bugs"])
        result = cache.get("code", "model2", ["bugs"])
        
        assert result is None
    
    def test_different_focus_produces_cache_miss(self, cache: ReviewCache) -> None:
        """Different focus areas should not match cached result."""
        cache.set("code", "model", {"result": "one"}, ["bugs"])
        result = cache.get("code", "model", ["security"])
        
        assert result is None
    
    def test_focus_order_does_not_affect_cache_hit(self, cache: ReviewCache) -> None:
        """Focus areas should be order-independent for cache matching."""
        code = "def test(): pass"
        model = "model"
        result = {"summary": "test"}
        
        # Store with one order
        cache.set(code, model, result, ["bugs", "security"])
        # Retrieve with different order
        cached = cache.get(code, model, ["security", "bugs"])
        
        assert cached == result
    
    def test_language_affects_cache_key(self, cache: ReviewCache) -> None:
        """Different language should produce different cache key."""
        code = "def test(): pass"
        
        cache.set(code, "model", {"lang": "python"}, ["bugs"], language="python")
        
        # Same code but different language should miss
        result = cache.get(code, "model", ["bugs"], language="javascript")
        assert result is None
        
        # Same code and language should hit
        result = cache.get(code, "model", ["bugs"], language="python")
        assert result == {"lang": "python"}
    
    def test_expired_entry_returns_none_and_is_cleaned(self, cache: ReviewCache) -> None:
        """Expired entries should return None and be deleted."""
        code = "def test(): pass"
        model = "model"
        
        # Store entry
        cache.set(code, model, {"result": "test"}, ["bugs"])
        
        # Verify it exists
        cache_key = cache._generate_cache_key(code, model, ["bugs"])
        cache_path = cache._get_cache_path(cache_key)
        assert cache_path.exists()
        
        # Manually expire the entry
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        old_time = datetime.now() - timedelta(hours=25)
        data["created_at"] = old_time.isoformat()
        data["ttl_hours"] = 1
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        
        # Should return None and delete the file
        result = cache.get(code, model, ["bugs"])
        assert result is None
        assert not cache_path.exists()
    
    def test_clear_removes_all_entries(self, cache: ReviewCache) -> None:
        """Clear should remove all cached entries."""
        # Add several entries
        cache.set("code1", "model", {"r": 1}, ["bugs"])
        cache.set("code2", "model", {"r": 2}, ["bugs"])
        cache.set("code3", "model", {"r": 3}, ["bugs"])
        
        # Verify they exist
        assert cache.stats()["total_entries"] == 3
        
        # Clear
        count = cache.clear()
        
        assert count == 3
        assert cache.stats()["total_entries"] == 0
    
    def test_prune_expired_removes_only_expired(self, cache: ReviewCache) -> None:
        """Prune should only remove expired entries."""
        # Add fresh entry
        cache.set("fresh", "model", {"status": "fresh"}, ["bugs"])
        
        # Add and expire an entry
        cache.set("old", "model", {"status": "old"}, ["bugs"])
        cache_key = cache._generate_cache_key("old", "model", ["bugs"])
        cache_path = cache._get_cache_path(cache_key)
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["created_at"] = (datetime.now() - timedelta(hours=100)).isoformat()
        data["ttl_hours"] = 1
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        
        # Prune
        pruned = cache.prune_expired()
        
        assert pruned == 1
        assert cache.stats()["total_entries"] == 1
        assert cache.get("fresh", "model", ["bugs"]) == {"status": "fresh"}
    
    def test_stats_returns_correct_information(self, cache: ReviewCache) -> None:
        """Stats should return accurate cache information."""
        cache.set("code1", "model", {"r": 1}, ["bugs"])
        cache.set("code2", "model", {"r": 2}, ["bugs"])
        
        stats = cache.stats()
        
        assert stats["total_entries"] == 2
        assert stats["total_size_bytes"] > 0
        assert stats["expired_entries"] == 0
        assert "cache_dir" in stats
    
    def test_stats_on_empty_cache(self, cache: ReviewCache) -> None:
        """Stats should work on empty cache."""
        stats = cache.stats()
        
        assert stats["total_entries"] == 0
        assert stats["total_size_bytes"] == 0
        assert stats["expired_entries"] == 0
    
    def test_invalid_json_in_cache_returns_none(self, cache: ReviewCache) -> None:
        """Invalid JSON in cache file should be handled gracefully."""
        code = "test"
        model = "model"
        
        # Create invalid cache file
        cache_key = cache._generate_cache_key(code, model, ["bugs"])
        cache_path = cache._get_cache_path(cache_key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            f.write("not valid json {{{")
        
        # Should return None and clean up
        result = cache.get(code, model, ["bugs"])
        
        assert result is None
        assert not cache_path.exists()
    
    def test_cache_creates_subdirectories(self, cache: ReviewCache) -> None:
        """Cache should create subdirectories based on cache key prefix."""
        cache.set("code", "model", {"test": True}, ["bugs"])
        
        # Should have created subdirectory
        subdirs = [d for d in cache.cache_dir.iterdir() if d.is_dir()]
        assert len(subdirs) == 1
        assert len(subdirs[0].name) == 2  # 2-char prefix


class TestReviewCacheIntegration:
    """Integration tests for caching with CodeReviewer."""
    
    @pytest.fixture
    def cache_dir(self) -> Path:
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_cache_key_deterministic(self, cache_dir: Path) -> None:
        """Same inputs should always produce same cache key."""
        cache1 = ReviewCache(cache_dir=cache_dir)
        cache2 = ReviewCache(cache_dir=cache_dir)
        
        key1 = cache1._generate_cache_key("code", "model", ["a", "b"], "python")
        key2 = cache2._generate_cache_key("code", "model", ["a", "b"], "python")
        
        assert key1 == key2
    
    def test_cache_key_changes_with_content(self, cache_dir: Path) -> None:
        """Different content should produce different cache keys."""
        cache = ReviewCache(cache_dir=cache_dir)
        
        key1 = cache._generate_cache_key("code1", "model", ["bugs"])
        key2 = cache._generate_cache_key("code2", "model", ["bugs"])
        
        assert key1 != key2
    
    def test_large_content_caches_correctly(self, cache_dir: Path) -> None:
        """Large content should be cached correctly."""
        cache = ReviewCache(cache_dir=cache_dir)
        
        large_code = "x = 1\n" * 10000  # ~60KB
        result = {"summary": "Large file reviewed", "issues": []}
        
        cache.set(large_code, "model", result, ["bugs"])
        cached = cache.get(large_code, "model", ["bugs"])
        
        assert cached == result
