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
    BinaryFileError,
    RateLimitError,
    is_binary_file,
)
from coderev.config import Config
import anthropic


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


class TestBinaryFileHandling:
    """Tests for binary file detection and handling."""
    
    def test_is_binary_by_extension_image(self, tmp_path):
        """Test that common image extensions are detected as binary."""
        for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico']:
            file = tmp_path / f"test{ext}"
            file.write_bytes(b"fake image data")
            assert is_binary_file(file) is True
    
    def test_is_binary_by_extension_archive(self, tmp_path):
        """Test that archive extensions are detected as binary."""
        for ext in ['.zip', '.tar', '.gz', '.7z', '.rar']:
            file = tmp_path / f"test{ext}"
            file.write_bytes(b"fake archive data")
            assert is_binary_file(file) is True
    
    def test_is_binary_by_extension_executable(self, tmp_path):
        """Test that executable extensions are detected as binary."""
        for ext in ['.exe', '.dll', '.so', '.pyc', '.class']:
            file = tmp_path / f"test{ext}"
            file.write_bytes(b"fake binary data")
            assert is_binary_file(file) is True
    
    def test_is_binary_by_null_bytes(self, tmp_path):
        """Test that files with null bytes are detected as binary."""
        file = tmp_path / "test.dat"
        file.write_bytes(b"hello\x00world")
        assert is_binary_file(file) is True
    
    def test_is_binary_by_high_non_text_ratio(self, tmp_path):
        """Test that files with high non-printable char ratio are binary."""
        file = tmp_path / "test.unknown"
        # Create content with >10% non-text bytes
        content = bytes([0x01, 0x02, 0x03, 0x04, 0x05] + list(b"hello"))
        file.write_bytes(content)
        assert is_binary_file(file) is True
    
    def test_text_file_not_binary(self, tmp_path):
        """Test that normal text files are not detected as binary."""
        file = tmp_path / "test.py"
        file.write_text("def hello():\n    print('world')\n")
        assert is_binary_file(file) is False
    
    def test_text_file_with_unicode(self, tmp_path):
        """Test that UTF-8 text files are not detected as binary."""
        file = tmp_path / "test.md"
        file.write_text("# Hello World\n\nEmojis: 🎉 🚀 ✨\n", encoding="utf-8")
        assert is_binary_file(file) is False
    
    def test_empty_file_not_binary(self, tmp_path):
        """Test that empty files are not detected as binary."""
        file = tmp_path / "empty.txt"
        file.write_text("")
        assert is_binary_file(file) is False
    
    def test_review_file_rejects_binary(self, tmp_path):
        """Test that review_file raises BinaryFileError for binary files."""
        binary_file = tmp_path / "image.png"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        
        reviewer = CodeReviewer(api_key="test-key")
        
        with pytest.raises(BinaryFileError) as exc_info:
            reviewer.review_file(binary_file)
        
        assert "image.png" in str(exc_info.value)
    
    def test_review_file_rejects_binary_by_content(self, tmp_path):
        """Test that files with binary content but text extension are rejected."""
        sneaky_binary = tmp_path / "sneaky.txt"
        sneaky_binary.write_bytes(b"looks like text\x00but has null bytes")
        
        reviewer = CodeReviewer(api_key="test-key")
        
        with pytest.raises(BinaryFileError):
            reviewer.review_file(sneaky_binary)
    
    @patch("coderev.reviewer.anthropic.Anthropic")
    def test_review_files_skips_binary_gracefully(self, mock_anthropic, tmp_path):
        """Test that review_files handles binary files without crashing."""
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"summary": "OK", "issues": [], "score": 80, "positive": []}')]
        mock_client.messages.create.return_value = mock_response
        
        # Create a text file and a binary file
        text_file = tmp_path / "code.py"
        text_file.write_text("print('hello')")
        
        binary_file = tmp_path / "image.png"
        binary_file.write_bytes(b"\x89PNG" + b"\x00" * 100)
        
        reviewer = CodeReviewer(api_key="test-key")
        results = reviewer.review_files([text_file, binary_file])
        
        # Text file should be reviewed
        assert results[str(text_file)].score == 80
        
        # Binary file should be skipped with score -1
        assert results[str(binary_file)].score == -1
        assert "Skipped" in results[str(binary_file)].summary
        assert "binary" in results[str(binary_file)].summary.lower()
    
    def test_binary_file_error_attributes(self):
        """Test BinaryFileError exception attributes."""
        error = BinaryFileError(Path("/path/to/file.bin"))
        assert error.file_path == Path("/path/to/file.bin")
        assert "file.bin" in str(error)
        
        error_custom = BinaryFileError(Path("test.exe"), "Custom message")
        assert error_custom.message == "Custom message"


class TestRateLimitError:
    """Tests for RateLimitError exception."""
    
    def test_basic_rate_limit_error(self):
        """Test basic RateLimitError creation."""
        error = RateLimitError()
        assert "rate limit exceeded" in error.message.lower()
        assert "Suggestions" in error.message
    
    def test_rate_limit_error_with_retry_seconds(self):
        """Test RateLimitError with retry_after in seconds."""
        error = RateLimitError(retry_after=30)
        assert "30 seconds" in error.message
        assert error.retry_after == 30
    
    def test_rate_limit_error_with_retry_minutes(self):
        """Test RateLimitError with retry_after in minutes."""
        error = RateLimitError(retry_after=120)
        assert "2.0 minutes" in error.message
    
    def test_rate_limit_error_suggestions(self):
        """Test that RateLimitError includes helpful suggestions."""
        error = RateLimitError(provider="anthropic")
        assert "Wait and retry" in error.message
        assert "Review fewer files" in error.message
        assert "--focus" in error.message
        assert "console.anthropic.com" in error.message
    
    def test_rate_limit_error_custom_message(self):
        """Test RateLimitError with custom message."""
        error = RateLimitError(message="Custom rate limit message")
        assert error.message == "Custom rate limit message"
    
    def test_rate_limit_error_preserves_original(self):
        """Test that original error is preserved."""
        original = ValueError("original error")
        error = RateLimitError(original_error=original)
        assert error.original_error is original
    
    @patch("coderev.reviewer.anthropic.Anthropic")
    def test_call_api_catches_rate_limit(self, mock_anthropic):
        """Test that _call_api properly catches Anthropic rate limit errors."""
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        
        # Simulate rate limit error
        mock_response = MagicMock()
        mock_response.headers = {"retry-after": "60"}
        rate_limit_error = anthropic.RateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body=None,
        )
        mock_client.messages.create.side_effect = rate_limit_error
        
        reviewer = CodeReviewer(api_key="test-key")
        
        with pytest.raises(RateLimitError) as exc_info:
            reviewer.review_code("def test(): pass")
        
        error = exc_info.value
        assert error.retry_after == 60
        assert error.original_error is rate_limit_error
    
    @patch("coderev.reviewer.anthropic.Anthropic")
    def test_call_api_catches_429_status(self, mock_anthropic):
        """Test that _call_api catches 429 API status errors as rate limits."""
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        
        # Simulate 429 status error
        mock_response = MagicMock()
        mock_response.status_code = 429
        status_error = anthropic.APIStatusError(
            message="Too many requests",
            response=mock_response,
            body=None,
        )
        status_error.status_code = 429
        mock_client.messages.create.side_effect = status_error
        
        reviewer = CodeReviewer(api_key="test-key")
        
        with pytest.raises(RateLimitError) as exc_info:
            reviewer.review_code("def test(): pass")
        
        error = exc_info.value
        assert "429" in error.message
        assert error.original_error is status_error
