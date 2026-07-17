"""Tests for atomic, non-destructive history writes.

`ReviewHistory.add()` is a read-modify-write over a whole month file: it loads
every review recorded that month, appends one, and writes the list back. That
makes two failure modes catastrophic rather than merely annoying:

  * A non-atomic write truncates the destination, so a concurrent reader sees a
    partial file, parses nothing, and its own add() writes back a month
    containing only its entry -- erasing the month.
  * A read that fails for a transient reason (a Windows lock held by a
    concurrent writer's os.replace()) is not evidence the month is empty, but
    treating it as [] erases the month just the same.

These tests pin the invariant behind both: history is only ever overwritten with
content that was actually read off disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coderev.history import (
    CORRUPT_SUFFIX,
    TEMP_SUFFIX,
    HistoryWriteError,
    ReviewHistory,
)
from coderev.reviewer import Category, Issue, ReviewResult, Severity


def make_result(summary: str = "ok", score: int = 90) -> ReviewResult:
    """A minimal ReviewResult with one issue, enough to round-trip."""
    return ReviewResult(
        summary=summary,
        score=score,
        issues=[
            Issue(
                message="something",
                severity=Severity.LOW,
                category=Category.STYLE,
                line=1,
            )
        ],
    )


@pytest.fixture
def history(tmp_path: Path) -> ReviewHistory:
    return ReviewHistory(history_dir=tmp_path / "history")


class TestAtomicWrite:
    """A write is only ever observed as fully-old or fully-new."""

    def test_add_leaves_no_temp_debris(self, history: ReviewHistory) -> None:
        history.add(make_result(), file_path="a.py")

        leftovers = list(history.history_dir.glob(f"*{TEMP_SUFFIX}"))
        assert leftovers == [], f"temp files survived a successful write: {leftovers}"

    def test_month_file_is_never_observed_truncated(
        self, history: ReviewHistory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The destination must go from valid-old to valid-new in one step.

        Staging into a temp file and swapping with os.replace() is what buys
        this; a plain open(path, 'w') would expose a zero-length file here.
        """
        history.add(make_result(summary="first"), file_path="a.py")
        month_file = history._get_month_file()
        observed: list[int] = []

        real_replace = __import__("os").replace

        def spy_replace(src, dst):
            # Stand where a concurrent reader stands: right before the swap.
            observed.append(len(month_file.read_bytes()))
            return real_replace(src, dst)

        monkeypatch.setattr("coderev.history.os.replace", spy_replace)
        history.add(make_result(summary="second"), file_path="b.py")

        assert observed, "os.replace() was not used to install the new file"
        assert all(size > 0 for size in observed), (
            "destination was truncated before the swap -- a concurrent reader "
            f"would see a partial file (observed sizes: {observed})"
        )
        # And the pre-swap content was the *complete* previous version.
        assert len(list(history.get_all())) == 2

    def test_failed_write_leaves_previous_history_intact(
        self, history: ReviewHistory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        history.add(make_result(summary="keep me"), file_path="a.py")

        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr("coderev.history.os.replace", boom)
        with pytest.raises(OSError):
            history.add(make_result(summary="doomed"), file_path="b.py")

        # The earlier review survived, and the failed write left no debris.
        summaries = [e.summary for e in history.get_all()]
        assert summaries == ["keep me"]
        assert list(history.history_dir.glob(f"*{TEMP_SUFFIX}")) == []


class TestUnreadableMonthFileIsNotEmpty:
    """A read that never completed says nothing about the month's contents."""

    def test_add_refuses_to_overwrite_unreadable_month(
        self, history: ReviewHistory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        history.add(make_result(summary="first"), file_path="a.py")
        history.add(make_result(summary="second"), file_path="b.py")
        before = history._get_month_file().read_text(encoding="utf-8")

        def locked(self, encoding="utf-8"):  # noqa: ARG001
            raise PermissionError("another process holds the file open")

        monkeypatch.setattr(Path, "read_text", locked)

        with pytest.raises(HistoryWriteError):
            history.add(make_result(summary="third"), file_path="c.py")

        monkeypatch.undo()
        # The month file is byte-for-byte what it was: not replaced by a
        # single-entry month, which is what treating the failure as [] would do.
        assert history._get_month_file().read_text(encoding="utf-8") == before
        assert [e.summary for e in history.get_all()] == ["first", "second"]

    def test_transient_lock_is_retried_then_succeeds(
        self, history: ReviewHistory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A writer's lock lasts an instant -- retry rather than give up."""
        history.add(make_result(summary="first"), file_path="a.py")

        real_read_text = Path.read_text
        calls = {"n": 0}

        def flaky(self, encoding="utf-8"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("swap in progress")
            return real_read_text(self, encoding=encoding)

        monkeypatch.setattr(Path, "read_text", flaky)
        history.add(make_result(summary="second"), file_path="b.py")
        monkeypatch.undo()

        assert calls["n"] >= 2, "a transient lock was not retried"
        assert [e.summary for e in history.get_all()] == ["first", "second"]

    def test_read_only_queries_tolerate_an_unreadable_month(
        self, history: ReviewHistory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reporting must degrade, not raise: stats must never crash a review."""
        history.add(make_result(), file_path="a.py")

        def locked(self, encoding="utf-8"):  # noqa: ARG001
            raise PermissionError("locked")

        monkeypatch.setattr(Path, "read_text", locked)

        assert list(history.get_all()) == []
        assert history.get_recent() == []
        assert history.get_stats().total_reviews == 0


class TestCorruptMonthFileIsQuarantined:
    """Garbage that *was* read is unusable -- but preserve it, don't erase it."""

    def test_corrupt_month_is_moved_aside_and_add_proceeds(
        self, history: ReviewHistory
    ) -> None:
        history.add(make_result(summary="first"), file_path="a.py")
        month_file = history._get_month_file()
        month_file.write_text("{not json at all", encoding="utf-8")

        entry = history.add(make_result(summary="after corruption"), file_path="b.py")

        assert entry is not None
        # The new entry was recorded...
        assert [e.summary for e in history.get_all()] == ["after corruption"]
        # ...and the unparseable bytes survive for manual recovery rather than
        # being silently overwritten.
        quarantined = month_file.with_name(month_file.name + CORRUPT_SUFFIX)
        assert quarantined.exists()
        assert quarantined.read_text(encoding="utf-8") == "{not json at all"

    def test_entries_of_wrong_type_are_treated_as_corrupt(
        self, history: ReviewHistory
    ) -> None:
        month_file = history._get_month_file()
        history.history_dir.mkdir(parents=True, exist_ok=True)
        month_file.write_text(
            json.dumps({"version": 1, "entries": {"not": "a list"}}), encoding="utf-8"
        )

        history.add(make_result(summary="fresh"), file_path="a.py")

        assert [e.summary for e in history.get_all()] == ["fresh"]
        assert month_file.with_name(month_file.name + CORRUPT_SUFFIX).exists()


class TestDirectoryScansIgnoreDebris:
    """Temp files and quarantined sidecars are not month files."""

    def test_scans_skip_temp_and_corrupt_files(self, history: ReviewHistory) -> None:
        history.add(make_result(summary="real"), file_path="a.py")
        month_file = history._get_month_file()

        # Debris a killed writer / an earlier quarantine would leave behind.
        (history.history_dir / f".reviews_2024-01.abcd{TEMP_SUFFIX}").write_text(
            "half written", encoding="utf-8"
        )
        month_file.with_name(f"reviews_2024-01.json{CORRUPT_SUFFIX}").write_text(
            "garbage", encoding="utf-8"
        )

        assert [p.name for p in history._month_files()] == [month_file.name]
        assert [e.summary for e in history.get_all()] == ["real"]
        assert history.get_stats().total_reviews == 1

    def test_clear_sweeps_temp_debris_without_counting_it(
        self, history: ReviewHistory
    ) -> None:
        history.add(make_result(), file_path="a.py")
        debris = history.history_dir / f".reviews_2024-01.abcd{TEMP_SUFFIX}"
        debris.write_text("half written", encoding="utf-8")

        cleared = history.clear()

        assert cleared == 1, "temp debris must not be counted as a cleared entry"
        assert not debris.exists(), "clear() left temp debris behind"


class TestConcurrentReadDuringWrite:
    """The end-to-end property the atomic swap exists to provide."""

    def test_reader_mid_write_never_sees_an_empty_month(
        self, history: ReviewHistory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for i in range(5):
            history.add(make_result(summary=f"r{i}"), file_path=f"f{i}.py")

        seen: list[int] = []
        real_replace = __import__("os").replace

        def read_then_replace(src, dst):
            # A second coderev process reading at the worst possible moment.
            other = ReviewHistory(history_dir=history.history_dir)
            seen.append(len(list(other.get_all())))
            return real_replace(src, dst)

        monkeypatch.setattr("coderev.history.os.replace", read_then_replace)
        history.add(make_result(summary="r5"), file_path="f5.py")

        assert seen == [5], f"concurrent reader saw a torn month file: {seen}"
        assert len(list(history.get_all())) == 6
