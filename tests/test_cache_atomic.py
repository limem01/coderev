"""Tests for atomic cache writes.

The cache directory is shared across concurrent reviews (async batches, a
pre-commit hook running next to a CI review, several coderev processes on the
same machine). A non-atomic write leaves a window where a reader observes a
truncated JSON file -- and because `get()` treats unparseable entries as
corrupt and deletes them, that window turns a partial write into the loss of a
valid entry. These tests pin down that writes are staged in a temp file and
swapped into place with os.replace().
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from coderev.cache import TEMP_SUFFIX, ReviewCache


@pytest.fixture
def cache(tmp_path: Path) -> ReviewCache:
    return ReviewCache(cache_dir=tmp_path / "cache", ttl_hours=24)


def _temp_files(cache: ReviewCache) -> list[Path]:
    return list(cache.cache_dir.rglob(f"*{TEMP_SUFFIX}"))


class TestAtomicWrite:
    """A successful set() leaves exactly one valid entry and no debris."""

    def test_set_leaves_no_temp_files_behind(self, cache: ReviewCache) -> None:
        cache.set("def f(): pass", "claude-sonnet-4", {"issues": []})

        assert _temp_files(cache) == []
        assert len(list(cache.cache_dir.rglob("*.json"))) == 1

    def test_entry_on_disk_is_always_complete_json(self, cache: ReviewCache) -> None:
        result = {"issues": [{"line": i, "message": "x" * 500} for i in range(50)]}
        cache.set("code", "claude-sonnet-4", result)

        (cache_file,) = cache.cache_dir.rglob("*.json")
        data = json.loads(cache_file.read_text(encoding="utf-8"))

        assert data["result"] == result

    def test_overwriting_a_key_replaces_rather_than_appends(
        self, cache: ReviewCache
    ) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": ["old"]})
        cache.set("code", "claude-sonnet-4", {"issues": ["new"]})

        assert cache.get("code", "claude-sonnet-4") == {"issues": ["new"]}
        assert len(list(cache.cache_dir.rglob("*.json"))) == 1


class TestFailedWriteDoesNotDestroyEntry:
    """A write that blows up must leave the previous entry usable."""

    def test_replace_failure_preserves_existing_entry(
        self, cache: ReviewCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": ["good"]})

        def boom(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        cache.set("code", "claude-sonnet-4", {"issues": ["doomed"]})

        assert cache.get("code", "claude-sonnet-4") == {"issues": ["good"]}

    def test_replace_failure_leaves_no_temp_file(
        self, cache: ReviewCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": ["good"]})

        def boom(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        cache.set("code", "claude-sonnet-4", {"issues": ["doomed"]})

        assert _temp_files(cache) == []

    def test_unserializable_result_preserves_existing_entry(
        self, cache: ReviewCache
    ) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": ["good"]})

        # json.dump raises partway through, after the temp file already has bytes.
        cache.set("code", "claude-sonnet-4", {"issues": [object()]})

        assert cache.get("code", "claude-sonnet-4") == {"issues": ["good"]}
        assert _temp_files(cache) == []


class TestConcurrentAccess:
    """Readers never observe a partially written entry."""

    def test_reader_never_sees_partial_entry_while_writers_hammer_key(
        self, cache: ReviewCache
    ) -> None:
        code, model = "def f(): pass", "claude-sonnet-4"
        payload = {"issues": [{"line": i, "message": "y" * 400} for i in range(40)]}
        cache.set(code, model, payload)

        stop = threading.Event()
        misses: list[str] = []

        def writer() -> None:
            for _ in range(40):
                cache.set(code, model, payload)

        def reader() -> None:
            while not stop.is_set():
                got = cache.get(code, model)
                if got != payload:
                    misses.append(repr(got))

        writers = [threading.Thread(target=writer) for _ in range(4)]
        readers = [threading.Thread(target=reader) for _ in range(4)]
        for t in readers + writers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        for t in readers:
            t.join()

        assert misses == []

    def test_concurrent_writers_leave_one_valid_entry(self, cache: ReviewCache) -> None:
        code, model = "def f(): pass", "claude-sonnet-4"
        payload = {"issues": ["only"]}

        threads = [
            threading.Thread(target=lambda: cache.set(code, model, payload))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache.get(code, model) == payload
        assert len(list(cache.cache_dir.rglob("*.json"))) == 1
        assert _temp_files(cache) == []


class TestTempFileSweeping:
    """Temp files from a killed writer are debris, not entries."""

    def test_clear_removes_stray_temp_files(self, cache: ReviewCache) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": []})
        (cache_file,) = cache.cache_dir.rglob("*.json")
        stray = cache_file.with_suffix(f".json{TEMP_SUFFIX}")
        stray.write_text('{"result": {"iss', encoding="utf-8")

        cleared = cache.clear()

        assert cleared == 1  # the entry; the temp file is debris, not an entry
        assert _temp_files(cache) == []

    def test_stray_temp_file_is_not_counted_as_an_entry(
        self, cache: ReviewCache
    ) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": []})
        (cache_file,) = cache.cache_dir.rglob("*.json")
        cache_file.with_suffix(f".json{TEMP_SUFFIX}").write_text("{", encoding="utf-8")

        stats = cache.stats()

        assert stats["total_entries"] == 1
        assert stats["expired_entries"] == 0

    def test_stray_temp_file_does_not_break_prune(self, cache: ReviewCache) -> None:
        cache.set("code", "claude-sonnet-4", {"issues": []})
        (cache_file,) = cache.cache_dir.rglob("*.json")
        cache_file.with_suffix(f".json{TEMP_SUFFIX}").write_text("{", encoding="utf-8")

        assert cache.prune_expired() == 0
        assert cache.get("code", "claude-sonnet-4") == {"issues": []}
