"""Review history and tracking for CodeRev.

This module provides persistent storage and querying of review results,
allowing users to track code quality over time, view past reviews,
and analyze trends in their codebase.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from coderev.reviewer import ReviewResult, Issue, Severity, Category

# Suffix for the temporary files used to stage atomic history writes.
TEMP_SUFFIX = ".tmp"

# Suffix for a month file quarantined because it could not be parsed. Kept
# rather than deleted so a user can recover entries by hand.
CORRUPT_SUFFIX = ".corrupt"

# On Windows, os.replace() and read_text() fail while another process holds the
# file open, which a concurrent reader/writer does for a moment. Retry briefly.
_RETRY_ATTEMPTS = 5
_RETRY_BACKOFF_SECONDS = 0.01

# How an attempt to load a month file off disk turned out. The distinction that
# matters is CORRUPT (the bytes were read and are garbage) vs UNREADABLE (the
# bytes were never seen, so the file must be left strictly alone).
_OK = "ok"
_MISSING = "missing"
_UNREADABLE = "unreadable"
_CORRUPT = "corrupt"


class HistoryWriteError(RuntimeError):
    """Raised when history cannot be updated without risking data loss.

    Adding to history is a read-modify-write against a whole month file. If the
    read fails, the in-memory entry list is not "the month so far" -- it is
    nothing at all, and writing it back would erase every review recorded that
    month. So a failed read aborts the write instead.
    """


def _default_history_dir() -> Path:
    """Get the default history directory.
    
    Uses XDG_DATA_HOME on Linux, or platform-appropriate locations elsewhere.
    Falls back to ~/.coderev/history
    """
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    
    return base / 'coderev' / 'history'


@dataclass
class ReviewEntry:
    """A single review entry in the history."""
    
    id: str  # Unique ID for this entry
    timestamp: str  # ISO format timestamp
    file_path: str | None  # Path to the reviewed file (or None for diff/code snippet)
    review_type: str  # 'file', 'diff', 'code', 'pr'
    model: str  # Model used for the review
    score: int  # Review score (0-100)
    summary: str
    issue_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    issues: list[dict[str, Any]] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    content_hash: str | None = None  # Hash of reviewed content for deduplication
    duration_ms: int | None = None  # Time taken for the review
    
    @classmethod
    def from_review_result(
        cls,
        result: ReviewResult,
        file_path: str | None = None,
        review_type: str = "file",
        model: str = "unknown",
        focus: list[str] | None = None,
        content: str | None = None,
        duration_ms: int | None = None,
    ) -> "ReviewEntry":
        """Create a ReviewEntry from a ReviewResult."""
        # Generate unique ID
        entry_id = hashlib.sha256(
            f"{datetime.now(timezone.utc).isoformat()}-{file_path or 'snippet'}-{model}".encode()
        ).hexdigest()[:16]
        
        # Compute content hash if content provided
        content_hash = None
        if content:
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        
        # Serialize issues
        issues_data = []
        for issue in result.issues:
            issues_data.append({
                "message": issue.message,
                "severity": issue.severity.value,
                "category": issue.category.value,
                "line": issue.line,
                "end_line": issue.end_line,
                "file": issue.file,
                "suggestion": issue.suggestion,
            })
        
        return cls(
            id=entry_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            file_path=file_path,
            review_type=review_type,
            model=model,
            score=result.score,
            summary=result.summary,
            issue_count=len(result.issues),
            critical_count=result.critical_count,
            high_count=result.high_count,
            medium_count=sum(1 for i in result.issues if i.severity == Severity.MEDIUM),
            low_count=sum(1 for i in result.issues if i.severity == Severity.LOW),
            issues=issues_data,
            focus=focus or [],
            content_hash=content_hash,
            duration_ms=duration_ms,
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewEntry":
        """Create from dictionary."""
        return cls(**data)
    
    @property
    def datetime(self) -> datetime:
        """Parse timestamp to datetime object."""
        return datetime.fromisoformat(self.timestamp)
    
    @property
    def has_blocking_issues(self) -> bool:
        """Check if review has critical or high severity issues."""
        return self.critical_count > 0 or self.high_count > 0


@dataclass
class HistoryStats:
    """Aggregated statistics from review history."""
    
    total_reviews: int
    total_files: int
    total_issues: int
    average_score: float
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    reviews_by_type: dict[str, int]
    reviews_by_model: dict[str, int]
    issues_by_category: dict[str, int]
    score_trend: list[tuple[str, float]]  # (date, avg_score) pairs
    first_review: str | None
    last_review: str | None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_reviews": self.total_reviews,
            "total_files": self.total_files,
            "total_issues": self.total_issues,
            "average_score": round(self.average_score, 1),
            "critical_issues": self.critical_issues,
            "high_issues": self.high_issues,
            "medium_issues": self.medium_issues,
            "low_issues": self.low_issues,
            "reviews_by_type": self.reviews_by_type,
            "reviews_by_model": self.reviews_by_model,
            "issues_by_category": self.issues_by_category,
            "score_trend": self.score_trend,
            "first_review": self.first_review,
            "last_review": self.last_review,
        }


class ReviewHistory:
    """Manages persistent storage of review history.
    
    History is stored in JSON files organized by month for efficient access
    and to prevent any single file from growing too large.
    
    File structure:
        history_dir/
            reviews_2024-01.json
            reviews_2024-02.json
            ...
            index.json  # Quick lookup index
    
    Example usage:
        history = ReviewHistory()
        
        # Add a review
        history.add(result, file_path="src/main.py", model="claude-3-sonnet")
        
        # Query recent reviews
        recent = history.get_recent(limit=10)
        
        # Get statistics
        stats = history.get_stats()
        
        # Search by file
        file_reviews = history.get_by_file("src/main.py")
    """
    
    def __init__(
        self,
        history_dir: Path | str | None = None,
        enabled: bool = True,
        max_entries_per_file: int = 1000,
    ):
        """Initialize the review history.
        
        Args:
            history_dir: Directory for history storage.
            enabled: Whether history tracking is enabled.
            max_entries_per_file: Max entries per monthly file before rotation.
        """
        self.enabled = enabled
        self.max_entries_per_file = max_entries_per_file
        
        if history_dir:
            self.history_dir = Path(history_dir)
        else:
            self.history_dir = _default_history_dir()
        
        if self.enabled:
            self.history_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_month_file(self, dt: datetime | None = None) -> Path:
        """Get the history file for a specific month."""
        dt = dt or datetime.now(timezone.utc)
        return self.history_dir / f"reviews_{dt.strftime('%Y-%m')}.json"
    
    def _month_files(self) -> list[Path]:
        """Every file in the history dir that is meant to be a month file.

        Materialized into a list so a concurrent clear() mutating the directory
        cannot disturb an in-progress walk. Temp files staged by _write_atomic()
        and quarantined `.corrupt` sidecars are debris, not month files, and are
        never picked up -- `reviews_*.json` alone would match neither, but the
        explicit filter keeps that guarantee from resting on suffix ordering.
        """
        if not self.history_dir.exists():
            return []

        return [
            path
            for path in sorted(self.history_dir.glob("reviews_*.json"))
            if not path.name.endswith((TEMP_SUFFIX, CORRUPT_SUFFIX))
        ]

    @staticmethod
    def _read_with_retry(path: Path) -> str | None:
        """Read a month file, retrying while a concurrent writer holds it locked.

        Returns None if the file is missing or stayed unreadable. The caller must
        never read that as "empty" -- the bytes were never seen, so there is
        nothing to judge.
        """
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                return path.read_text(encoding='utf-8')
            except FileNotFoundError:
                # Removed or replaced out from under us; nothing to retry for.
                return None
            except PermissionError:  # Windows: a writer is swapping the file in
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
            except OSError:
                return None
        return None

    @classmethod
    def _load_entries(cls, path: Path) -> tuple[list[dict[str, Any]], str]:
        """Load one month file, reporting *why* it could not be loaded.

        Every caller that reads a month file goes through here, because the safe
        reaction to a failed read depends entirely on whether the bytes were
        actually seen. Writes are atomic, so JSON that parses badly is genuinely
        corrupt. But a read that never completed -- a concurrent writer's
        os.replace() holding a Windows lock, an I/O blip -- says nothing about
        the file, and treating it as empty would let add() write back a
        single-entry month and erase every review recorded that month.

        Returns:
            (entries, _OK) when the file parsed, else ([], _MISSING/_UNREADABLE/_CORRUPT).
        """
        raw = cls._read_with_retry(path)
        if raw is None:
            return [], _MISSING if not path.exists() else _UNREADABLE

        try:
            data = json.loads(raw)
            entries = data.get("entries", [])
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            # Written by an incompatible version, or truncated by a pre-atomic
            # writer from an older coderev. Either way it is unusable.
            return [], _CORRUPT

        if not isinstance(entries, list):
            return [], _CORRUPT

        return entries, _OK

    def _load_month_file(self, path: Path) -> list[dict[str, Any]]:
        """Load entries from a monthly history file, tolerating failure.

        For the read-only queries this backs (get_all(), get_stats(), ...), a
        month file that cannot be read degrades the answer but cannot destroy
        anything, so an unreadable file is reported as empty. The read-modify-
        write path in add() must NOT use this -- see _load_for_update().
        """
        entries, _state = self._load_entries(path)
        return entries

    def _load_for_update(self, path: Path) -> list[dict[str, Any]]:
        """Load a month file that is about to be rewritten with a new entry.

        Unlike _load_month_file(), this refuses to silently return [] for a file
        it could not read: the caller appends to the result and writes it back,
        so "[]" would mean erasing the month rather than merely under-reporting.

        A file whose bytes *were* read and are garbage is quarantined alongside
        itself (see CORRUPT_SUFFIX) instead of being overwritten in place, so
        the unparseable content survives for manual recovery and the new entry
        still gets recorded.

        Raises:
            HistoryWriteError: If the file exists but could not be read.
        """
        entries, state = self._load_entries(path)

        if state == _UNREADABLE:
            raise HistoryWriteError(
                f"Could not read existing history file {path}; refusing to "
                f"overwrite it, as that would discard the reviews it holds."
            )

        if state == _CORRUPT:
            quarantine = path.with_name(path.name + CORRUPT_SUFFIX)
            try:
                os.replace(path, quarantine)
            except OSError:
                raise HistoryWriteError(
                    f"History file {path} is corrupt and could not be moved "
                    f"aside; refusing to overwrite it."
                ) from None
            return []

        return entries

    def _save_month_file(self, path: Path, entries: list[dict[str, Any]]) -> None:
        """Save entries to a monthly history file, atomically.

        The history dir is shared between concurrent reviews (async batches, a
        pre-commit hook running alongside a CI review, two coderev processes).
        Writing JSON straight into the destination truncates it first, leaving a
        window where a reader sees a partial file -- and since a torn read used
        to come back as "no entries", the next add() would write back a
        single-entry month, destroying every review recorded that month.

        Instead, stage the content in a temp file in the same directory (same
        filesystem, so the rename cannot cross devices) and swap it in with
        os.replace(), which is atomic on both POSIX and Windows. A reader
        therefore only ever observes the old file or the new one.

        Raises:
            OSError: If the file could not be written or swapped into place. The
                destination is left untouched and no temp file survives.
        """
        data = {
            "version": 1,
            "updated": datetime.now(timezone.utc).isoformat(),
            "entries": entries,
        }

        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=TEMP_SUFFIX,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())

            last_error: PermissionError | None = None
            for attempt in range(_RETRY_ATTEMPTS):
                try:
                    os.replace(tmp_path, path)
                    return
                except PermissionError as exc:  # Windows: reader holds it open
                    last_error = exc
                    time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
            raise last_error  # type: ignore[misc]
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    def add(
        self,
        result: ReviewResult,
        file_path: str | None = None,
        review_type: str = "file",
        model: str = "unknown",
        focus: list[str] | None = None,
        content: str | None = None,
        duration_ms: int | None = None,
    ) -> ReviewEntry | None:
        """Add a review result to history.
        
        Args:
            result: The ReviewResult to store.
            file_path: Path to the reviewed file.
            review_type: Type of review ('file', 'diff', 'code', 'pr').
            model: Model used for the review.
            focus: Focus areas used for the review.
            content: The reviewed content (for deduplication).
            duration_ms: Time taken for the review.

        Returns:
            The created ReviewEntry, or None if history is disabled.

        Raises:
            HistoryWriteError: If the existing month file could not be read, in
                which case nothing is written and the stored history is intact.
        """
        if not self.enabled:
            return None

        # Create entry
        entry = ReviewEntry.from_review_result(
            result=result,
            file_path=file_path,
            review_type=review_type,
            model=model,
            focus=focus,
            content=content,
            duration_ms=duration_ms,
        )

        # Load current month's file. Strictly: appending to a month we failed to
        # read would write back a month containing only this entry.
        month_file = self._get_month_file()
        entries = self._load_for_update(month_file)

        # Add new entry
        entries.append(entry.to_dict())
        
        # Save
        self._save_month_file(month_file, entries)
        
        return entry
    
    def get_all(self) -> Iterator[ReviewEntry]:
        """Iterate over all review entries in chronological order."""
        for path in self._month_files():
            entries = self._load_month_file(path)
            for entry_data in entries:
                yield ReviewEntry.from_dict(entry_data)
    
    def get_recent(self, limit: int = 10) -> list[ReviewEntry]:
        """Get the most recent review entries.
        
        Args:
            limit: Maximum number of entries to return.
            
        Returns:
            List of ReviewEntry objects, most recent first.
        """
        if not self.enabled:
            return []

        entries: list[ReviewEntry] = []

        for path in reversed(self._month_files()):
            if len(entries) >= limit:
                break
            
            month_entries = self._load_month_file(path)
            # Entries within a file are chronological, so reverse
            for entry_data in reversed(month_entries):
                if len(entries) >= limit:
                    break
                entries.append(ReviewEntry.from_dict(entry_data))
        
        return entries
    
    def get_by_file(self, file_path: str, limit: int | None = None) -> list[ReviewEntry]:
        """Get all reviews for a specific file.
        
        Args:
            file_path: Path to the file to search for.
            limit: Maximum number of entries to return.
            
        Returns:
            List of ReviewEntry objects for the file.
        """
        entries = []
        
        for entry in self.get_all():
            if entry.file_path and file_path in entry.file_path:
                entries.append(entry)
                if limit and len(entries) >= limit:
                    break
        
        return sorted(entries, key=lambda e: e.timestamp, reverse=True)
    
    def get_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime | None = None,
    ) -> list[ReviewEntry]:
        """Get reviews within a date range.
        
        Args:
            start_date: Start of the date range.
            end_date: End of the date range (defaults to now).
            
        Returns:
            List of ReviewEntry objects in the date range.
        """
        end_date = end_date or datetime.now(timezone.utc)
        entries = []
        
        for entry in self.get_all():
            entry_dt = entry.datetime
            if start_date <= entry_dt <= end_date:
                entries.append(entry)
        
        return sorted(entries, key=lambda e: e.timestamp, reverse=True)
    
    def get_by_severity(
        self,
        min_severity: str = "low",
        limit: int | None = None,
    ) -> list[ReviewEntry]:
        """Get reviews that have issues at or above a severity level.
        
        Args:
            min_severity: Minimum severity to include ('low', 'medium', 'high', 'critical').
            limit: Maximum number of entries to return.
            
        Returns:
            List of ReviewEntry objects with matching issues.
        """
        severity_order = ["low", "medium", "high", "critical"]
        min_idx = severity_order.index(min_severity)
        
        entries = []
        for entry in self.get_all():
            has_match = False
            if min_idx <= 3 and entry.critical_count > 0:
                has_match = True
            elif min_idx <= 2 and entry.high_count > 0:
                has_match = True
            elif min_idx <= 1 and entry.medium_count > 0:
                has_match = True
            elif min_idx <= 0 and entry.low_count > 0:
                has_match = True
            
            if has_match:
                entries.append(entry)
                if limit and len(entries) >= limit:
                    break
        
        return sorted(entries, key=lambda e: e.timestamp, reverse=True)
    
    def get_stats(self, days: int | None = None) -> HistoryStats:
        """Get aggregated statistics from review history.
        
        Args:
            days: Only include reviews from the last N days.
                  If None, include all reviews.
                  
        Returns:
            HistoryStats object with aggregated data.
        """
        # Determine date filter
        start_date = None
        if days:
            start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Collect stats
        total_reviews = 0
        total_issues = 0
        total_score = 0
        files = set()
        critical = 0
        high = 0
        medium = 0
        low = 0
        by_type: dict[str, int] = {}
        by_model: dict[str, int] = {}
        by_category: dict[str, int] = {}
        daily_scores: dict[str, list[int]] = {}
        first_review = None
        last_review = None
        
        for entry in self.get_all():
            # Apply date filter
            if start_date and entry.datetime < start_date:
                continue
            
            total_reviews += 1
            total_issues += entry.issue_count
            total_score += entry.score
            
            if entry.file_path:
                files.add(entry.file_path)
            
            critical += entry.critical_count
            high += entry.high_count
            medium += entry.medium_count
            low += entry.low_count
            
            by_type[entry.review_type] = by_type.get(entry.review_type, 0) + 1
            by_model[entry.model] = by_model.get(entry.model, 0) + 1
            
            # Track issues by category
            for issue in entry.issues:
                cat = issue.get("category", "unknown")
                by_category[cat] = by_category.get(cat, 0) + 1
            
            # Track daily scores for trend
            date_str = entry.timestamp[:10]  # YYYY-MM-DD
            if date_str not in daily_scores:
                daily_scores[date_str] = []
            daily_scores[date_str].append(entry.score)
            
            # Track first/last review
            if first_review is None or entry.timestamp < first_review:
                first_review = entry.timestamp
            if last_review is None or entry.timestamp > last_review:
                last_review = entry.timestamp
        
        # Compute score trend (average per day)
        score_trend = []
        for date_str in sorted(daily_scores.keys()):
            scores = daily_scores[date_str]
            avg = sum(scores) / len(scores) if scores else 0
            score_trend.append((date_str, round(avg, 1)))
        
        return HistoryStats(
            total_reviews=total_reviews,
            total_files=len(files),
            total_issues=total_issues,
            average_score=total_score / total_reviews if total_reviews > 0 else 0,
            critical_issues=critical,
            high_issues=high,
            medium_issues=medium,
            low_issues=low,
            reviews_by_type=by_type,
            reviews_by_model=by_model,
            issues_by_category=by_category,
            score_trend=score_trend,
            first_review=first_review,
            last_review=last_review,
        )
    
    def clear(self) -> int:
        """Clear all history entries.
        
        Returns:
            Number of entries cleared.
        """
        if not self.enabled:
            return 0

        count = 0
        for path in self._month_files():
            entries = self._load_month_file(path)
            try:
                path.unlink()
            except OSError:
                # Another process holds it open, or already removed it. Do not
                # count entries we did not actually clear.
                continue
            count += len(entries)

        if not self.history_dir.exists():
            return count

        # Sweep temp files left behind by a writer that was killed mid-write.
        # They are not month files, so they are removed but not counted.
        for tmp_file in self.history_dir.glob(f"*{TEMP_SUFFIX}"):
            try:
                tmp_file.unlink()
            except OSError:
                pass

        return count
    
    def export(self, output_path: Path | str) -> int:
        """Export all history to a single JSON file.
        
        Args:
            output_path: Path for the export file.
            
        Returns:
            Number of entries exported.
        """
        output_path = Path(output_path)
        entries = list(self.get_all())
        
        data = {
            "version": 1,
            "exported": datetime.now(timezone.utc).isoformat(),
            "entry_count": len(entries),
            "entries": [e.to_dict() for e in entries],
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        
        return len(entries)
    
    def import_from(self, input_path: Path | str) -> int:
        """Import history from an export file.
        
        Args:
            input_path: Path to the import file.
            
        Returns:
            Number of entries imported.
        """
        if not self.enabled:
            return 0
        
        input_path = Path(input_path)
        
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        imported = 0
        for entry_data in data.get("entries", []):
            entry = ReviewEntry.from_dict(entry_data)
            
            # Determine which month file to add to
            entry_dt = entry.datetime
            month_file = self._get_month_file(entry_dt)
            entries = self._load_for_update(month_file)

            # Check for duplicates by ID
            existing_ids = {e.get("id") for e in entries}
            if entry.id not in existing_ids:
                entries.append(entry.to_dict())
                self._save_month_file(month_file, entries)
                imported += 1
        
        return imported
