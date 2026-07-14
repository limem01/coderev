"""Tests for the directory-wide cache scans (prune_expired / stats).

`get()` was hardened so that an entry it *could not read* is treated as a miss
rather than as corruption -- deleting on a failed read destroys a valid cached
review. The scans had the same bug, and prune_expired()'s version was the
destructive one: it caught OSError and unlinked the entry, so a transient
Windows lock (a concurrent writer swapping a file in with os.replace(), which
holds the destination for an instant) made pruning delete fresh, unexpired
entries. stats() had a second failure: it stat()'d files outside its try block,
so a file vanishing mid-scan crashed the caller.

These tests pin down the rule: an entry is deleted only on evidence read off
disk (parsed and expired, or parsed as garbage), never on a failed read.
"""

from __future__ import annotations

import builtins
import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from coderev.cache import TEMP_SUFFIX, ReviewCache


@pytest.fixture
def cache(tmp_path: Path) -> ReviewCache:
    return ReviewCache(cache_dir=tmp_path / "cache", ttl_hours=24)


def _entry_file(cache: ReviewCache) -> Path:
    (path,) = cache.cache_dir.rglob("*.json")
    return path


def _expire(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["created_at"] = (datetime.now() - timedelta(hours=100)).isoformat()
    data["ttl_hours"] = 1
    path.write_text(json.dumps(data), encoding="utf-8")


def _lock_reads(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Make every attempt to open `target` fail the way a locked file does on Windows.

    Patched at `io.open`, which is the one chokepoint every way of reading the
    file funnels through -- `open(path)` and `Path.read_text()` alike. Patching
    a higher-level call (say `Path.read_text`) would only lock out whichever API
    the implementation happens to use today, and would quietly stop testing
    anything the moment it changed.
    """
    real_open = io.open

    def fake_open(file: object, *args: object, **kwargs: object) -> object:
        if isinstance(file, (str, os.PathLike)) and Path(file) == target:
            raise PermissionError(32, "The process cannot access the file")
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(io, "open", fake_open)
    monkeypatch.setattr(builtins, "open", fake_open)


class TestPruneNeverDeletesUnreadableEntries:
    """A read that never completed is not evidence the entry is bad."""

    def test_locked_entry_survives_prune(
        self, cache: ReviewCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": []})
        path = _entry_file(cache)
        _lock_reads(monkeypatch, path)

        pruned = cache.prune_expired()

        assert pruned == 0
        assert path.exists()

    def test_entry_still_usable_once_the_lock_clears(
        self, cache: ReviewCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": ["real"]})
        path = _entry_file(cache)

        _lock_reads(monkeypatch, path)
        cache.prune_expired()
        monkeypatch.undo()

        assert cache.get("code", "claude-sonnet-4") == {"issues": ["real"]}

    def test_a_locked_entry_does_not_shield_a_genuinely_expired_one(
        self, cache: ReviewCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache.set("fresh", "model", {"r": 1})
        cache.set("stale", "model", {"r": 2})
        stale = cache._get_cache_path(cache._generate_cache_key("stale", "model"))
        fresh = cache._get_cache_path(cache._generate_cache_key("fresh", "model"))
        _expire(stale)
        _lock_reads(monkeypatch, fresh)

        assert cache.prune_expired() == 1
        assert not stale.exists()
        assert fresh.exists()


class TestPruneStillRemovesBadEntries:
    """Refusing to delete on a failed read must not stop real pruning."""

    def test_expired_entry_is_pruned(self, cache: ReviewCache) -> None:
        cache.set("code", "model", {"r": 1})
        _expire(_entry_file(cache))

        assert cache.prune_expired() == 1
        assert list(cache.cache_dir.rglob("*.json")) == []

    def test_corrupt_entry_is_pruned(self, cache: ReviewCache) -> None:
        cache.set("code", "model", {"r": 1})
        _entry_file(cache).write_text('{"result": {"iss', encoding="utf-8")

        assert cache.prune_expired() == 1

    def test_count_reflects_files_actually_removed(self, cache: ReviewCache) -> None:
        cache.set("a", "model", {"r": 1})
        cache.set("b", "model", {"r": 2})
        for path in cache.cache_dir.rglob("*.json"):
            _expire(path)

        assert cache.prune_expired() == 2
        assert cache.prune_expired() == 0


class TestStatsSurvivesConcurrentMutation:
    """Reporting statistics must never be what crashes a review."""

    def test_entry_vanishing_mid_scan_does_not_raise(
        self, cache: ReviewCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file the directory walk listed is gone by the time we look at it.

        Exactly what a concurrent clear()/prune() (or another coderev process)
        does. The old stats() called stat() outside its try block, so this
        raised FileNotFoundError straight out of a review.
        """
        cache.set("code", "model", {"r": 1})
        ghost = cache.cache_dir / "ab" / "abdeadbeef.json"  # listed, never on disk
        real_rglob = Path.rglob

        def rglob_with_ghost(self: Path, pattern: str) -> object:
            found = list(real_rglob(self, pattern))
            if pattern == "*.json":
                found.append(ghost)
            return iter(found)

        monkeypatch.setattr(Path, "rglob", rglob_with_ghost)

        stats = cache.stats()  # must not raise

        assert stats["total_entries"] == 1  # the ghost is not an entry
        assert stats["expired_entries"] == 0
        assert stats["unreadable_entries"] == 0

    def test_entry_vanishing_mid_scan_is_not_counted_as_pruned(
        self, cache: ReviewCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ghost = cache.cache_dir / "ab" / "abdeadbeef.json"
        cache.cache_dir.mkdir(parents=True, exist_ok=True)
        real_rglob = Path.rglob

        def rglob_with_ghost(self: Path, pattern: str) -> object:
            found = list(real_rglob(self, pattern))
            if pattern == "*.json":
                found.append(ghost)
            return iter(found)

        monkeypatch.setattr(Path, "rglob", rglob_with_ghost)

        assert cache.prune_expired() == 0  # nothing was there to remove

    def test_locked_entry_is_reported_as_unreadable_not_expired(
        self, cache: ReviewCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache.set("code", "model", {"r": 1})
        _lock_reads(monkeypatch, _entry_file(cache))

        stats = cache.stats()

        assert stats["total_entries"] == 1
        assert stats["unreadable_entries"] == 1
        assert stats["expired_entries"] == 0  # nothing here says it is prunable

    def test_corrupt_entry_counts_as_expired(self, cache: ReviewCache) -> None:
        cache.set("code", "model", {"r": 1})
        _entry_file(cache).write_text("{", encoding="utf-8")

        stats = cache.stats()

        # expired_entries is the "how many would prune_expired() remove" number.
        assert stats["expired_entries"] == 1
        assert stats["unreadable_entries"] == 0

    def test_healthy_cache_reports_nothing_unreadable(self, cache: ReviewCache) -> None:
        cache.set("code", "model", {"r": 1})

        stats = cache.stats()

        assert stats["total_entries"] == 1
        assert stats["expired_entries"] == 0
        assert stats["unreadable_entries"] == 0
        assert stats["total_size_bytes"] > 0


class TestScansIgnoreTempDebris:
    """Temp files staged by _write_atomic() are debris, never entries."""

    def test_json_named_temp_file_is_not_scanned(self, cache: ReviewCache) -> None:
        cache.set("code", "model", {"r": 1})
        _entry_file(cache).with_suffix(f".json{TEMP_SUFFIX}").write_text(
            "{", encoding="utf-8"
        )

        assert cache.stats()["total_entries"] == 1
        assert cache.prune_expired() == 0
        assert cache.get("code", "model") == {"r": 1}
