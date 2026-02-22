"""Tests for batch review functionality."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from coderev.batch import (
    FileReviewSummary,
    BatchReviewReport,
    format_batch_report_markdown,
    format_batch_report_html,
)
from coderev.reviewer import ReviewResult, Issue, Severity, Category


class TestFileReviewSummary:
    """Tests for FileReviewSummary class."""
    
    def test_from_result_reviewed(self):
        """Test creating summary from a reviewed result."""
        result = ReviewResult(
            summary="Good code",
            score=85,
            issues=[
                Issue(message="Bug found", severity=Severity.HIGH, category=Category.BUG),
                Issue(message="Style issue", severity=Severity.LOW, category=Category.STYLE),
                Issue(message="Security issue", severity=Severity.CRITICAL, category=Category.SECURITY),
            ],
            positive=["Clean imports"],
        )
        
        summary = FileReviewSummary.from_result("test.py", result)
        
        assert summary.file_path == "test.py"
        assert summary.score == 85
        assert summary.total_issues == 3
        assert summary.critical_count == 1
        assert summary.high_count == 1
        assert summary.low_count == 1
        assert summary.status == "reviewed"
        assert summary.error_message is None
    
    def test_from_result_skipped(self):
        """Test creating summary from a skipped file."""
        result = ReviewResult(
            summary="Skipped: binary file",
            score=-1,
            issues=[],
        )
        
        summary = FileReviewSummary.from_result("image.png", result)
        
        assert summary.file_path == "image.png"
        assert summary.status == "skipped"
        assert summary.error_message == "Skipped: binary file"
    
    def test_top_categories(self):
        """Test that top categories are extracted correctly."""
        result = ReviewResult(
            summary="Review",
            score=70,
            issues=[
                Issue(message="Bug 1", severity=Severity.HIGH, category=Category.BUG),
                Issue(message="Bug 2", severity=Severity.MEDIUM, category=Category.BUG),
                Issue(message="Security", severity=Severity.HIGH, category=Category.SECURITY),
                Issue(message="Style", severity=Severity.LOW, category=Category.STYLE),
            ],
        )
        
        summary = FileReviewSummary.from_result("test.py", result)
        
        assert "bug" in summary.top_categories
        assert len(summary.top_categories) <= 3


class TestBatchReviewReport:
    """Tests for BatchReviewReport class."""
    
    def test_from_results_basic(self):
        """Test creating a report from multiple results."""
        results = {
            "file1.py": ReviewResult(
                summary="Good",
                score=90,
                issues=[
                    Issue(message="Minor", severity=Severity.LOW, category=Category.STYLE),
                ],
            ),
            "file2.py": ReviewResult(
                summary="Needs work",
                score=60,
                issues=[
                    Issue(message="Bug", severity=Severity.HIGH, category=Category.BUG),
                    Issue(message="Security", severity=Severity.CRITICAL, category=Category.SECURITY),
                ],
            ),
        }
        
        report = BatchReviewReport.from_results(results)
        
        assert report.files_reviewed == 2
        assert report.files_skipped == 0
        assert report.total_issues == 3
        assert report.critical_issues == 1
        assert report.high_issues == 1
        assert report.low_issues == 1
        assert report.average_score == 75.0
        assert report.min_score == 60
        assert report.max_score == 90
    
    def test_from_results_with_skipped(self):
        """Test creating a report with skipped files."""
        results = {
            "file1.py": ReviewResult(
                summary="Good",
                score=80,
                issues=[],
            ),
            "image.png": ReviewResult(
                summary="Skipped: binary",
                score=-1,
                issues=[],
            ),
        }
        
        report = BatchReviewReport.from_results(results)
        
        assert report.files_reviewed == 1
        assert report.files_skipped == 1
        assert report.total_files == 2
    
    def test_health_grade_a(self):
        """Test A grade for high scores."""
        results = {
            "file.py": ReviewResult(summary="Great", score=95, issues=[]),
        }
        report = BatchReviewReport.from_results(results)
        assert report.health_grade == "A"
    
    def test_health_grade_f(self):
        """Test F grade for low scores."""
        results = {
            "file.py": ReviewResult(summary="Bad", score=40, issues=[]),
        }
        report = BatchReviewReport.from_results(results)
        assert report.health_grade == "F"
    
    def test_has_blocking_issues(self):
        """Test blocking issues detection."""
        results = {
            "file.py": ReviewResult(
                summary="Critical issue",
                score=50,
                issues=[
                    Issue(message="Critical!", severity=Severity.CRITICAL, category=Category.SECURITY),
                ],
            ),
        }
        report = BatchReviewReport.from_results(results)
        assert report.has_blocking_issues is True
    
    def test_no_blocking_issues(self):
        """Test when no blocking issues."""
        results = {
            "file.py": ReviewResult(
                summary="Minor issues",
                score=75,
                issues=[
                    Issue(message="Style", severity=Severity.LOW, category=Category.STYLE),
                ],
            ),
        }
        report = BatchReviewReport.from_results(results)
        assert report.has_blocking_issues is False
    
    def test_top_issues(self):
        """Test getting top issues sorted by severity."""
        results = {
            "file.py": ReviewResult(
                summary="Issues",
                score=60,
                issues=[
                    Issue(message="Low", severity=Severity.LOW, category=Category.STYLE),
                    Issue(message="Critical", severity=Severity.CRITICAL, category=Category.BUG),
                    Issue(message="Medium", severity=Severity.MEDIUM, category=Category.PERFORMANCE),
                ],
            ),
        }
        report = BatchReviewReport.from_results(results)
        
        top = report.top_issues(2)
        assert len(top) == 2
        assert top[0][1].message == "Critical"
        assert top[1][1].message == "Medium"
    
    def test_to_dict(self):
        """Test JSON serialization."""
        results = {
            "file.py": ReviewResult(
                summary="Good",
                score=85,
                issues=[
                    Issue(message="Bug", severity=Severity.HIGH, category=Category.BUG, line=10),
                ],
            ),
        }
        report = BatchReviewReport.from_results(results)
        
        data = report.to_dict()
        
        assert "timestamp" in data
        assert data["summary"]["files_reviewed"] == 1
        assert data["summary"]["total_issues"] == 1
        assert data["summary"]["health_grade"] == "B"
        assert len(data["files"]) == 1
        assert len(data["all_issues"]) == 1
        
        # Verify it's JSON serializable
        json_str = json.dumps(data)
        assert "file.py" in json_str
    
    def test_worst_and_best_files(self):
        """Test identification of worst and best files."""
        results = {
            "good.py": ReviewResult(summary="Great", score=95, issues=[]),
            "bad.py": ReviewResult(summary="Bad", score=40, issues=[]),
            "medium.py": ReviewResult(summary="OK", score=70, issues=[]),
        }
        
        report = BatchReviewReport.from_results(results)
        
        assert "bad.py" in report.worst_files
        assert "good.py" in report.best_files
    
    def test_issues_by_category(self):
        """Test aggregation of issues by category."""
        results = {
            "file1.py": ReviewResult(
                summary="Issues",
                score=70,
                issues=[
                    Issue(message="Bug1", severity=Severity.HIGH, category=Category.BUG),
                    Issue(message="Bug2", severity=Severity.MEDIUM, category=Category.BUG),
                ],
            ),
            "file2.py": ReviewResult(
                summary="More issues",
                score=60,
                issues=[
                    Issue(message="Security", severity=Severity.HIGH, category=Category.SECURITY),
                ],
            ),
        }
        
        report = BatchReviewReport.from_results(results)
        
        assert report.issues_by_category["bug"] == 2
        assert report.issues_by_category["security"] == 1


class TestMarkdownFormatter:
    """Tests for markdown report formatting."""
    
    def test_format_basic_report(self):
        """Test basic markdown report generation."""
        results = {
            "test.py": ReviewResult(
                summary="Review complete",
                score=80,
                issues=[
                    Issue(message="Bug found", severity=Severity.HIGH, category=Category.BUG, line=10),
                ],
            ),
        }
        report = BatchReviewReport.from_results(results)
        
        md = format_batch_report_markdown(report)
        
        assert "# Code Review Batch Report" in md
        assert "Health Grade" in md
        assert "test.py" in md
        assert "Bug found" in md
    
    def test_format_with_blocking_issues(self):
        """Test markdown includes blocking issues section."""
        results = {
            "critical.py": ReviewResult(
                summary="Critical issues",
                score=30,
                issues=[
                    Issue(message="Critical bug", severity=Severity.CRITICAL, category=Category.BUG),
                ],
            ),
        }
        report = BatchReviewReport.from_results(results)
        
        md = format_batch_report_markdown(report)
        
        assert "## Blocking Issues" in md
        assert "🔴" in md  # Critical emoji


class TestHtmlFormatter:
    """Tests for HTML report formatting."""
    
    def test_format_basic_report(self):
        """Test basic HTML report generation."""
        results = {
            "test.py": ReviewResult(
                summary="Review complete",
                score=80,
                issues=[],
            ),
        }
        report = BatchReviewReport.from_results(results)
        
        html = format_batch_report_html(report)
        
        assert "<!DOCTYPE html>" in html
        assert "Code Review Report" in html
        assert "test.py" in html
        assert "</html>" in html
    
    def test_format_contains_stats(self):
        """Test HTML contains statistics."""
        results = {
            "test.py": ReviewResult(
                summary="Issues found",
                score=60,
                issues=[
                    Issue(message="Critical", severity=Severity.CRITICAL, category=Category.BUG),
                    Issue(message="High", severity=Severity.HIGH, category=Category.SECURITY),
                ],
            ),
        }
        report = BatchReviewReport.from_results(results)
        
        html = format_batch_report_html(report)
        
        assert "Files Reviewed" in html
        assert "Critical" in html
        assert "Average Score" in html


class TestBatchCLI:
    """Tests for the batch CLI command."""
    
    def test_batch_command_exists(self):
        """Test that the batch command is registered."""
        from coderev.cli import main
        
        assert "batch" in main.commands
    
    def test_batch_command_help(self):
        """Test batch command has proper help text."""
        from click.testing import CliRunner
        from coderev.cli import main
        
        runner = CliRunner()
        result = runner.invoke(main, ["batch", "--help"])
        
        assert result.exit_code == 0
        assert "Batch review multiple files" in result.output
        assert "--format" in result.output
        assert "--output" in result.output
