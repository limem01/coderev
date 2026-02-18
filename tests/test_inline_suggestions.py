"""Tests for line-by-line inline suggestions feature."""

import pytest

from coderev.reviewer import (
    InlineSuggestion,
    ReviewResult,
    Severity,
    Category,
)
from coderev.output import InlineFormatter, RichInlineFormatter, get_formatter


@pytest.fixture
def sample_inline_suggestions():
    """Create sample inline suggestions for testing."""
    return [
        InlineSuggestion(
            start_line=5,
            end_line=5,
            original_code='password = "hardcoded123"',
            suggested_code='password = os.environ.get("DB_PASSWORD")',
            explanation="Hardcoded passwords are a security risk. Use environment variables.",
            severity=Severity.CRITICAL,
            category=Category.SECURITY,
        ),
        InlineSuggestion(
            start_line=10,
            end_line=12,
            original_code='for i in range(len(items)):\n    item = items[i]\n    process(item)',
            suggested_code='for item in items:\n    process(item)',
            explanation="Use direct iteration instead of indexing for cleaner code.",
            severity=Severity.LOW,
            category=Category.STYLE,
        ),
        InlineSuggestion(
            start_line=20,
            end_line=20,
            original_code='result = data.get("key") if data.get("key") else "default"',
            suggested_code='result = data.get("key", "default")',
            explanation="Use dict.get() with default value parameter.",
            severity=Severity.MEDIUM,
            category=Category.PERFORMANCE,
        ),
    ]


@pytest.fixture
def sample_result_with_inline(sample_inline_suggestions):
    """Create a sample review result with inline suggestions."""
    return ReviewResult(
        summary="Code has security and style issues",
        issues=[],
        inline_suggestions=sample_inline_suggestions,
        score=65,
        positive=["Good function naming", "Clear structure"],
    )


@pytest.fixture
def sample_source_code():
    """Sample source code for testing context display."""
    return '''import os

def get_connection():
    # Bad: hardcoded password
    password = "hardcoded123"
    return connect(password)

def process_items(items):
    results = []
    for i in range(len(items)):
        item = items[i]
        process(item)
        results.append(item)
    return results

def get_config(data):
    # Redundant pattern
    result = data.get("key") if data.get("key") else "default"
    return result
'''


class TestInlineSuggestion:
    """Tests for InlineSuggestion dataclass."""
    
    def test_from_dict_basic(self):
        data = {
            "start_line": 10,
            "end_line": 12,
            "original_code": "old code",
            "suggested_code": "new code",
            "explanation": "Better this way",
            "severity": "high",
            "category": "bug",
        }
        suggestion = InlineSuggestion.from_dict(data)
        
        assert suggestion.start_line == 10
        assert suggestion.end_line == 12
        assert suggestion.original_code == "old code"
        assert suggestion.suggested_code == "new code"
        assert suggestion.explanation == "Better this way"
        assert suggestion.severity == Severity.HIGH
        assert suggestion.category == Category.BUG
    
    def test_from_dict_defaults(self):
        data = {"start_line": 5}
        suggestion = InlineSuggestion.from_dict(data)
        
        assert suggestion.start_line == 5
        assert suggestion.end_line == 5  # Defaults to start_line
        assert suggestion.original_code == ""
        assert suggestion.suggested_code == ""
        assert suggestion.severity == Severity.MEDIUM
        assert suggestion.category == Category.STYLE
    
    def test_line_range_single_line(self):
        suggestion = InlineSuggestion(
            start_line=42,
            end_line=42,
            original_code="x",
            suggested_code="y",
            explanation="test",
            severity=Severity.LOW,
            category=Category.STYLE,
        )
        assert suggestion.line_range == "L42"
    
    def test_line_range_multiple_lines(self):
        suggestion = InlineSuggestion(
            start_line=10,
            end_line=15,
            original_code="x",
            suggested_code="y",
            explanation="test",
            severity=Severity.LOW,
            category=Category.STYLE,
        )
        assert suggestion.line_range == "L10-15"


class TestReviewResultInlineSuggestions:
    """Tests for ReviewResult with inline suggestions."""
    
    def test_suggestions_by_line_sorted(self, sample_result_with_inline):
        sorted_suggestions = sample_result_with_inline.suggestions_by_line()
        
        # Should be sorted by start_line
        lines = [s.start_line for s in sorted_suggestions]
        assert lines == [5, 10, 20]
    
    def test_empty_suggestions(self):
        result = ReviewResult(
            summary="All good",
            issues=[],
            inline_suggestions=[],
            score=100,
        )
        assert result.suggestions_by_line() == []


class TestInlineFormatter:
    """Tests for the InlineFormatter class."""
    
    def test_format_basic(self, sample_result_with_inline):
        formatter = InlineFormatter(colorize=False)
        output = formatter.format(sample_result_with_inline)
        
        assert "Code Review - Score: 65/100" in output
        assert "Code has security and style issues" in output
        assert "INLINE SUGGESTIONS (3 found)" in output
    
    def test_format_includes_suggestions(self, sample_result_with_inline):
        formatter = InlineFormatter(colorize=False)
        output = formatter.format(sample_result_with_inline)
        
        # Check that all suggestions are included
        assert "Hardcoded passwords" in output
        assert "Use direct iteration" in output
        assert "dict.get()" in output
    
    def test_format_shows_severity_markers(self, sample_result_with_inline):
        formatter = InlineFormatter(colorize=False)
        output = formatter.format(sample_result_with_inline)
        
        assert "[!!]" in output  # Critical
        assert "[. ]" in output  # Low
        assert "[~ ]" in output  # Medium
    
    def test_format_shows_diff_style(self, sample_result_with_inline):
        formatter = InlineFormatter(colorize=False)
        output = formatter.format(sample_result_with_inline)
        
        assert "- password = " in output or "Original:" in output
        assert "+ password = os.environ" in output or "Suggested:" in output
    
    def test_format_shows_positive_feedback(self, sample_result_with_inline):
        formatter = InlineFormatter(colorize=False)
        output = formatter.format(sample_result_with_inline)
        
        assert "WHAT'S GOOD" in output
        assert "Good function naming" in output
    
    def test_format_empty_suggestions(self):
        result = ReviewResult(
            summary="Perfect code",
            issues=[],
            inline_suggestions=[],
            score=100,
        )
        formatter = InlineFormatter(colorize=False)
        output = formatter.format(result)
        
        assert "No inline suggestions - code looks good!" in output
    
    def test_format_with_source_context(
        self, sample_result_with_inline, sample_source_code
    ):
        formatter = InlineFormatter(colorize=False)
        output = formatter.format_with_source(sample_result_with_inline, sample_source_code)
        
        # Should include line numbers
        assert "   5*|" in output or "   5 |" in output
        # Should include suggestions inline
        assert ">>>" in output
        assert "Replace with:" in output


class TestGetFormatterInline:
    """Tests for get_formatter with inline format."""
    
    def test_get_inline_formatter(self):
        formatter = get_formatter("inline")
        assert isinstance(formatter, InlineFormatter)
    
    def test_get_inline_formatter_case_insensitive(self):
        formatter = get_formatter("INLINE")
        assert isinstance(formatter, InlineFormatter)


class TestRichInlineFormatter:
    """Tests for RichInlineFormatter class."""
    
    def test_initialization(self):
        formatter = RichInlineFormatter()
        assert formatter.console is not None
    
    def test_print_inline_suggestions_no_error(self, sample_result_with_inline, capsys):
        """Test that printing doesn't raise errors (basic smoke test)."""
        from rich.console import Console
        from io import StringIO
        
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        formatter = RichInlineFormatter(console=console)
        
        # Should not raise any exceptions
        formatter.print_inline_suggestions(
            sample_result_with_inline,
            file_path="test.py"
        )
        
        result = output.getvalue()
        assert "Inline Suggestions" in result or "test.py" in result
