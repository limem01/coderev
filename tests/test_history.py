"""Tests for review history and tracking."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from coderev.history import (
    ReviewHistory,
    ReviewEntry,
    HistoryStats,
    _default_history_dir,
)
from coderev.reviewer import ReviewResult, Issue, Severity, Category


@pytest.fixture
def temp_history_dir():
    """Create a temporary directory for history storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def history(temp_history_dir):
    """Create a ReviewHistory instance with temp storage."""
    return ReviewHistory(history_dir=temp_history_dir)


@pytest.fixture
def sample_result():
    """Create a sample ReviewResult for testing."""
    return ReviewResult(
        summary="Test review completed",
        issues=[
            Issue(
                message="SQL injection vulnerability",
                severity=Severity.CRITICAL,
                category=Category.SECURITY,
                line=10,
            ),
            Issue(
                message="Missing error handling",
                severity=Severity.HIGH,
                category=Category.BUG,
                line=25,
            ),
            Issue(
                message="Variable naming convention",
                severity=Severity.LOW,
                category=Category.STYLE,
                line=5,
            ),
        ],
        score=65,
        positive=["Good code structure"],
    )


@pytest.fixture
def sample_result_clean():
    """Create a clean ReviewResult with no issues."""
    return ReviewResult(
        summary="Code looks good!",
        issues=[],
        score=95,
        positive=["Clean code", "Good documentation"],
    )


class TestReviewEntry:
    """Tests for ReviewEntry class."""
    
    def test_from_review_result(self, sample_result):
        """Test creating entry from ReviewResult."""
        entry = ReviewEntry.from_review_result(
            result=sample_result,
            file_path="src/main.py",
            review_type="file",
            model="claude-3-sonnet",
            focus=["security", "bugs"],
        )
        
        assert entry.file_path == "src/main.py"
        assert entry.review_type == "file"
        assert entry.model == "claude-3-sonnet"
        assert entry.score == 65
        assert entry.issue_count == 3
        assert entry.critical_count == 1
        assert entry.high_count == 1
        assert entry.low_count == 1
        assert entry.focus == ["security", "bugs"]
        assert len(entry.id) == 16
        assert entry.timestamp is not None
    
    def test_from_review_result_with_content_hash(self, sample_result):
        """Test that content hash is computed when content is provided."""
        content = "def hello(): pass"
        entry = ReviewEntry.from_review_result(
            result=sample_result,
            content=content,
        )
        
        assert entry.content_hash is not None
        assert len(entry.content_hash) == 32
    
    def test_to_dict_and_from_dict(self, sample_result):
        """Test serialization round-trip."""
        entry = ReviewEntry.from_review_result(
            result=sample_result,
            file_path="test.py",
            model="gpt-4",
        )
        
        data = entry.to_dict()
        restored = ReviewEntry.from_dict(data)
        
        assert restored.id == entry.id
        assert restored.file_path == entry.file_path
        assert restored.score == entry.score
        assert restored.issue_count == entry.issue_count
    
    def test_datetime_property(self, sample_result):
        """Test datetime parsing."""
        entry = ReviewEntry.from_review_result(result=sample_result)
        
        dt = entry.datetime
        assert isinstance(dt, datetime)
        assert dt.year >= 2024
    
    def test_has_blocking_issues(self, sample_result, sample_result_clean):
        """Test blocking issues detection."""
        entry_with_issues = ReviewEntry.from_review_result(result=sample_result)
        entry_clean = ReviewEntry.from_review_result(result=sample_result_clean)
        
        assert entry_with_issues.has_blocking_issues is True
        assert entry_clean.has_blocking_issues is False


class TestReviewHistory:
    """Tests for ReviewHistory class."""
    
    def test_init_creates_directory(self, temp_history_dir):
        """Test that init creates the history directory."""
        history = ReviewHistory(history_dir=temp_history_dir / "subdir")
        assert (temp_history_dir / "subdir").exists()
    
    def test_disabled_history(self, temp_history_dir):
        """Test that disabled history doesn't store anything."""
        history = ReviewHistory(history_dir=temp_history_dir, enabled=False)
        
        result = ReviewResult(summary="Test", issues=[], score=80)
        entry = history.add(result, file_path="test.py")
        
        assert entry is None
        assert list(history.get_all()) == []
    
    def test_add_and_retrieve(self, history, sample_result):
        """Test adding and retrieving entries."""
        entry = history.add(
            result=sample_result,
            file_path="src/main.py",
            model="claude-3-sonnet",
        )
        
        assert entry is not None
        assert entry.file_path == "src/main.py"
        
        # Retrieve
        entries = list(history.get_all())
        assert len(entries) == 1
        assert entries[0].file_path == "src/main.py"
    
    def test_get_recent(self, history, sample_result, sample_result_clean):
        """Test getting recent entries."""
        # Add multiple entries
        history.add(sample_result, file_path="file1.py")
        history.add(sample_result_clean, file_path="file2.py")
        history.add(sample_result, file_path="file3.py")
        
        recent = history.get_recent(limit=2)
        
        assert len(recent) == 2
        # Most recent should be first
        assert recent[0].file_path == "file3.py"
        assert recent[1].file_path == "file2.py"
    
    def test_get_by_file(self, history, sample_result):
        """Test getting entries by file path."""
        history.add(sample_result, file_path="src/main.py")
        history.add(sample_result, file_path="src/utils.py")
        history.add(sample_result, file_path="src/main.py")
        
        main_reviews = history.get_by_file("main.py")
        
        assert len(main_reviews) == 2
        for entry in main_reviews:
            assert "main.py" in entry.file_path
    
    def test_get_by_severity(self, history, sample_result, sample_result_clean):
        """Test getting entries by severity."""
        history.add(sample_result, file_path="risky.py")  # Has critical/high
        history.add(sample_result_clean, file_path="clean.py")  # No issues
        
        critical = history.get_by_severity("critical")
        assert len(critical) == 1
        assert critical[0].file_path == "risky.py"
        
        high = history.get_by_severity("high")
        assert len(high) == 1
    
    def test_get_stats(self, history, sample_result, sample_result_clean):
        """Test statistics generation."""
        history.add(sample_result, file_path="file1.py", model="claude-3-sonnet")
        history.add(sample_result_clean, file_path="file2.py", model="gpt-4")
        history.add(sample_result, file_path="file1.py", model="claude-3-sonnet")
        
        stats = history.get_stats()
        
        assert stats.total_reviews == 3
        assert stats.total_files == 2  # file1.py reviewed twice but counted once
        assert stats.total_issues == 6  # 3 issues per sample_result, 2 reviews
        assert stats.average_score == (65 + 95 + 65) / 3
        assert stats.critical_issues == 2
        assert stats.high_issues == 2
        assert stats.reviews_by_model["claude-3-sonnet"] == 2
        assert stats.reviews_by_model["gpt-4"] == 1
    
    def test_get_stats_with_days_filter(self, history, sample_result):
        """Test statistics with date filter."""
        # Add an entry
        history.add(sample_result, file_path="test.py")
        
        # Stats for last 7 days should include it
        stats = history.get_stats(days=7)
        assert stats.total_reviews == 1
        
        # Stats for 0 days should not include it (entry is from today)
        # Actually, the entry IS within "last 0 days" since it's today
        # Let's test with proper logic
        stats_all = history.get_stats()
        assert stats_all.total_reviews == 1
    
    def test_clear(self, history, sample_result):
        """Test clearing history."""
        history.add(sample_result, file_path="file1.py")
        history.add(sample_result, file_path="file2.py")
        
        cleared = history.clear()
        
        assert cleared == 2
        assert list(history.get_all()) == []
    
    def test_export_and_import(self, history, temp_history_dir, sample_result):
        """Test export and import functionality."""
        # Add entries
        history.add(sample_result, file_path="file1.py")
        history.add(sample_result, file_path="file2.py")
        
        # Export
        export_path = temp_history_dir / "export.json"
        exported = history.export(export_path)
        
        assert exported == 2
        assert export_path.exists()
        
        # Verify export format
        with open(export_path) as f:
            data = json.load(f)
        assert data["entry_count"] == 2
        assert len(data["entries"]) == 2
        
        # Clear and import
        history.clear()
        assert list(history.get_all()) == []
        
        imported = history.import_from(export_path)
        assert imported == 2
        assert len(list(history.get_all())) == 2
    
    def test_duplicate_import_prevention(self, history, temp_history_dir, sample_result):
        """Test that duplicate entries are not imported."""
        history.add(sample_result, file_path="file1.py")
        
        # Export
        export_path = temp_history_dir / "export.json"
        history.export(export_path)
        
        # Try to import again (should skip duplicates)
        imported = history.import_from(export_path)
        assert imported == 0  # Nothing new imported
        
        # Total should still be 1
        assert len(list(history.get_all())) == 1


class TestHistoryStats:
    """Tests for HistoryStats class."""
    
    def test_to_dict(self):
        """Test serialization of stats."""
        stats = HistoryStats(
            total_reviews=10,
            total_files=5,
            total_issues=25,
            average_score=75.5,
            critical_issues=2,
            high_issues=5,
            medium_issues=10,
            low_issues=8,
            reviews_by_type={"file": 8, "diff": 2},
            reviews_by_model={"claude": 6, "gpt": 4},
            issues_by_category={"security": 5, "bug": 10},
            score_trend=[("2024-01-01", 70.0), ("2024-01-02", 80.0)],
            first_review="2024-01-01T10:00:00",
            last_review="2024-01-02T15:00:00",
        )
        
        data = stats.to_dict()
        
        assert data["total_reviews"] == 10
        assert data["average_score"] == 75.5
        assert data["reviews_by_type"]["file"] == 8


class TestDefaultHistoryDir:
    """Tests for default history directory detection."""
    
    def test_default_dir_exists(self):
        """Test that default directory path is valid."""
        default_dir = _default_history_dir()
        
        assert isinstance(default_dir, Path)
        assert "coderev" in str(default_dir)
        assert "history" in str(default_dir)
