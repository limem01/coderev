"""Tests for the code reviewer module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from coderev.reviewer import (
    CodeReviewer,
    ReviewResult,
    Issue,
    Severity,
    Category,
)
from coderev.config import Config


class TestSeverity:
    """Tests for Severity enum."""
    
    def test_weight_ordering(self):
        assert Severity.CRITICAL.weight > Severity.HIGH.weight
        assert Severity.HIGH.weight > Severity.MEDIUM.weight
        assert Severity.MEDIUM.weight > Severity.LOW.weight
    
    def test_string_conversion(self):
        assert str(Severity.CRITICAL) == "Severity.CRITICAL"
        assert Severity.CRITICAL.value == "critical"


class TestIssue:
    """Tests for Issue dataclass."""
    
    def test_from_dict_minimal(self):
        data = {"message": "Test issue"}
        issue = Issue.from_dict(data)
        
        assert issue.message == "Test issue"
        assert issue.severity == Severity.MEDIUM  # default
        assert issue.category == Category.BUG  # default
        assert issue.line is None
    
    def test_from_dict_full(self):
        data = {
            "message": "SQL injection vulnerability",
            "severity": "critical",
            "category": "security",
            "line": 42,
            "end_line": 45,
            "suggestion": "Use parameterized queries",
            "code_suggestion": "db.execute(query, params)",
        }
        issue = Issue.from_dict(data)
        
        assert issue.message == "SQL injection vulnerability"
        assert issue.severity == Severity.CRITICAL
        assert issue.category == Category.SECURITY
        assert issue.line == 42
        assert issue.end_line == 45
        assert issue.suggestion == "Use parameterized queries"
    
    def test_from_dict_with_default_file(self):
        data = {"message": "Test"}
        issue = Issue.from_dict(data, default_file="main.py")
        assert issue.file == "main.py"


class TestReviewResult:
    """Tests for ReviewResult dataclass."""
    
    def test_critical_count(self):
        result = ReviewResult(
            summary="Test",
            issues=[
                Issue(message="a", severity=Severity.CRITICAL, category=Category.BUG),
                Issue(message="b", severity=Severity.CRITICAL, category=Category.BUG),
                Issue(message="c", severity=Severity.LOW, category=Category.BUG),
            ],
        )
        assert result.critical_count == 2
    
    def test_high_count(self):
        result = ReviewResult(
            summary="Test",
            issues=[
                Issue(message="a", severity=Severity.HIGH, category=Category.BUG),
                Issue(message="b", severity=Severity.LOW, category=Category.BUG),
            ],
        )
        assert result.high_count == 1
    
    def test_has_blocking_issues(self):
        result_with_critical = ReviewResult(
            summary="Test",
            issues=[Issue(message="x", severity=Severity.CRITICAL, category=Category.BUG)],
        )
        assert result_with_critical.has_blocking_issues is True
        
        result_with_high = ReviewResult(
            summary="Test",
            issues=[Issue(message="x", severity=Severity.HIGH, category=Category.BUG)],
        )
        assert result_with_high.has_blocking_issues is True
        
        result_low_only = ReviewResult(
            summary="Test",
            issues=[Issue(message="x", severity=Severity.LOW, category=Category.BUG)],
        )
        assert result_low_only.has_blocking_issues is False
    
    def test_issues_by_severity(self):
        issues = [
            Issue(message="low", severity=Severity.LOW, category=Category.BUG),
            Issue(message="critical", severity=Severity.CRITICAL, category=Category.BUG),
            Issue(message="medium", severity=Severity.MEDIUM, category=Category.BUG),
        ]
        result = ReviewResult(summary="Test", issues=issues)
        
        sorted_issues = result.issues_by_severity()
        assert sorted_issues[0].severity == Severity.CRITICAL
        assert sorted_issues[1].severity == Severity.MEDIUM
        assert sorted_issues[2].severity == Severity.LOW
    
    def test_issues_by_file(self):
        issues = [
            Issue(message="a", severity=Severity.LOW, category=Category.BUG, file="main.py"),
            Issue(message="b", severity=Severity.LOW, category=Category.BUG, file="utils.py"),
            Issue(message="c", severity=Severity.LOW, category=Category.BUG, file="main.py"),
        ]
        result = ReviewResult(summary="Test", issues=issues)
        
        by_file = result.issues_by_file()
        assert len(by_file["main.py"]) == 2
        assert len(by_file["utils.py"]) == 1


class TestCodeReviewer:
    """Tests for CodeReviewer class."""
    
    def test_init_requires_api_key(self):
        with patch.dict('os.environ', {}, clear=True):
            config = Config(api_key=None)
            with pytest.raises(ValueError, match="API key required"):
                CodeReviewer(config=config)
    
    def test_init_with_api_key(self):
        reviewer = CodeReviewer(api_key="test-key")
        assert reviewer.api_key == "test-key"
    
    def test_detect_language_python(self):
        reviewer = CodeReviewer(api_key="test-key")
        assert reviewer._detect_language(Path("test.py")) == "python"
        assert reviewer._detect_language(Path("test.js")) == "javascript"
        assert reviewer._detect_language(Path("test.ts")) == "typescript"
        assert reviewer._detect_language(Path("test.go")) == "go"
        assert reviewer._detect_language(Path("test.rs")) == "rust"
    
    def test_detect_language_unknown(self):
        reviewer = CodeReviewer(api_key="test-key")
        assert reviewer._detect_language(Path("test.xyz")) is None
    
    @patch("coderev.reviewer.anthropic.Anthropic")
    def test_review_code(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"summary": "Good code", "issues": [], "score": 85, "positive": ["Clean"]}')]
        mock_client.messages.create.return_value = mock_response
        
        reviewer = CodeReviewer(api_key="test-key")
        result = reviewer.review_code("def hello(): pass", language="python")
        
        assert result.summary == "Good code"
        assert result.score == 85
        assert len(result.issues) == 0
        assert "Clean" in result.positive
    
    @patch("coderev.reviewer.anthropic.Anthropic")
    def test_review_code_with_issues(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        
        response_json = '''
        {
            "summary": "Needs improvement",
            "issues": [
                {
                    "line": 5,
                    "severity": "high",
                    "category": "security",
                    "message": "SQL injection",
                    "suggestion": "Use parameterized queries"
                }
            ],
            "score": 45,
            "positive": []
        }
        '''
        
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response
        
        reviewer = CodeReviewer(api_key="test-key")
        result = reviewer.review_code("SELECT * FROM users WHERE id = " + "user_input")
        
        assert result.score == 45
        assert len(result.issues) == 1
        assert result.issues[0].severity == Severity.HIGH
        assert result.issues[0].category == Category.SECURITY
    
    def test_review_file_not_found(self):
        reviewer = CodeReviewer(api_key="test-key")
        
        with pytest.raises(FileNotFoundError):
            reviewer.review_file(Path("/nonexistent/file.py"))
    
    def test_review_file_too_large(self, tmp_path):
        large_file = tmp_path / "large.py"
        large_file.write_text("x" * 200_000)  # 200KB
        
        config = Config(api_key="test", max_file_size=100_000)
        reviewer = CodeReviewer(config=config)
        
        with pytest.raises(ValueError, match="File too large"):
            reviewer.review_file(large_file)


class TestJsonParsing:
    """Tests for JSON response parsing edge cases."""
    
    @patch("coderev.reviewer.anthropic.Anthropic")
    def test_parse_json_in_code_block(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        
        # Response wrapped in markdown code block
        response_text = '''Here's my analysis:
```json
{"summary": "Test", "issues": [], "score": 100, "positive": []}
```'''
        
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_text)]
        mock_client.messages.create.return_value = mock_response
        
        reviewer = CodeReviewer(api_key="test-key")
        result = reviewer.review_code("pass")
        
        assert result.summary == "Test"
        assert result.score == 100
