"""Tests for output formatters."""

import json
import pytest

from coderev.output import (
    JsonFormatter,
    MarkdownFormatter,
    SarifFormatter,
    get_formatter,
)
from coderev.reviewer import ReviewResult, Issue, Severity, Category


@pytest.fixture
def sample_result():
    """Create a sample review result for testing."""
    return ReviewResult(
        summary="Code needs improvement",
        issues=[
            Issue(
                message="SQL injection vulnerability",
                severity=Severity.CRITICAL,
                category=Category.SECURITY,
                line=42,
                file="db.py",
                suggestion="Use parameterized queries",
            ),
            Issue(
                message="Missing error handling",
                severity=Severity.MEDIUM,
                category=Category.BUG,
                line=55,
                file="api.py",
            ),
        ],
        score=65,
        positive=["Good test coverage", "Clear naming conventions"],
    )


class TestJsonFormatter:
    """Tests for JSON formatter."""
    
    def test_format_basic(self, sample_result):
        formatter = JsonFormatter()
        output = formatter.format(sample_result)
        data = json.loads(output)
        
        assert data["summary"] == "Code needs improvement"
        assert data["score"] == 65
        assert len(data["issues"]) == 2
        assert len(data["positive"]) == 2
    
    def test_format_issue_fields(self, sample_result):
        formatter = JsonFormatter()
        output = formatter.format(sample_result)
        data = json.loads(output)
        
        critical_issue = next(i for i in data["issues"] if i["severity"] == "critical")
        assert critical_issue["line"] == 42
        assert critical_issue["file"] == "db.py"
        assert critical_issue["category"] == "security"
        assert critical_issue["message"] == "SQL injection vulnerability"
        assert critical_issue["suggestion"] == "Use parameterized queries"
    
    def test_format_empty_result(self):
        result = ReviewResult(summary="All good", issues=[], score=100)
        formatter = JsonFormatter()
        output = formatter.format(result)
        data = json.loads(output)
        
        assert data["issues"] == []
        assert data["score"] == 100
    
    def test_format_multiple(self, sample_result):
        formatter = JsonFormatter()
        results = {"file1.py": sample_result, "file2.py": sample_result}
        output = formatter.format_multiple(results)
        data = json.loads(output)
        
        assert "file1.py" in data
        assert "file2.py" in data


class TestMarkdownFormatter:
    """Tests for Markdown formatter."""
    
    def test_format_includes_header(self, sample_result):
        formatter = MarkdownFormatter()
        output = formatter.format(sample_result)
        
        assert "# Code Review Report" in output
        assert "**Score:** 65/100" in output
    
    def test_format_includes_summary(self, sample_result):
        formatter = MarkdownFormatter()
        output = formatter.format(sample_result)
        
        assert "## Summary" in output
        assert "Code needs improvement" in output
    
    def test_format_includes_issues(self, sample_result):
        formatter = MarkdownFormatter()
        output = formatter.format(sample_result)
        
        assert "## Issues" in output
        assert "CRITICAL" in output
        assert "SQL injection vulnerability" in output
    
    def test_format_includes_positive(self, sample_result):
        formatter = MarkdownFormatter()
        output = formatter.format(sample_result)
        
        assert "## What's Good" in output
        assert "Good test coverage" in output


class TestSarifFormatter:
    """Tests for SARIF formatter."""
    
    def test_format_valid_sarif(self, sample_result):
        formatter = SarifFormatter()
        output = formatter.format(sample_result)
        data = json.loads(output)
        
        assert data["version"] == "2.1.0"
        assert "$schema" in data
        assert len(data["runs"]) == 1
    
    def test_format_tool_info(self, sample_result):
        formatter = SarifFormatter()
        output = formatter.format(sample_result)
        data = json.loads(output)
        
        tool = data["runs"][0]["tool"]["driver"]
        assert tool["name"] == "coderev"
        assert "version" in tool
    
    def test_format_results(self, sample_result):
        formatter = SarifFormatter()
        output = formatter.format(sample_result)
        data = json.loads(output)
        
        results = data["runs"][0]["results"]
        assert len(results) == 2
        
        # Check severity mapping
        levels = [r["level"] for r in results]
        assert "error" in levels  # critical maps to error
    
    def test_format_location(self, sample_result):
        formatter = SarifFormatter()
        output = formatter.format(sample_result)
        data = json.loads(output)
        
        results = data["runs"][0]["results"]
        result_with_location = next(
            r for r in results if "locations" in r
        )
        
        location = result_with_location["locations"][0]["physicalLocation"]
        assert "artifactLocation" in location
        assert location["region"]["startLine"] == 42


class TestGetFormatter:
    """Tests for formatter factory function."""
    
    def test_get_json_formatter(self):
        formatter = get_formatter("json")
        assert isinstance(formatter, JsonFormatter)
    
    def test_get_markdown_formatter(self):
        formatter = get_formatter("markdown")
        assert isinstance(formatter, MarkdownFormatter)
    
    def test_get_sarif_formatter(self):
        formatter = get_formatter("sarif")
        assert isinstance(formatter, SarifFormatter)
    
    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Unknown format"):
            get_formatter("invalid")
