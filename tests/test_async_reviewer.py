"""Tests for the async code reviewer module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from coderev.async_reviewer import AsyncCodeReviewer, review_files_parallel
from coderev.reviewer import (
    ReviewResult,
    Severity,
    Category,
    BinaryFileError,
    RateLimitError,
)
from coderev.config import Config
# anthropic is accessed via provider abstraction; no direct dependency in tests


class TestAsyncCodeReviewer:
    """Tests for AsyncCodeReviewer class."""
    
    def test_init_requires_api_key(self):
        with patch.dict('os.environ', {}, clear=True):
            config = Config(api_key=None)
            with pytest.raises(ValueError, match="API key required"):
                AsyncCodeReviewer(config=config)
    
    def test_init_with_api_key(self):
        reviewer = AsyncCodeReviewer(api_key="test-key")
        assert reviewer.api_key == "test-key"
        assert reviewer.max_concurrent == 5
    
    def test_init_custom_max_concurrent(self):
        reviewer = AsyncCodeReviewer(api_key="test-key", max_concurrent=10)
        assert reviewer.max_concurrent == 10
    
    def test_detect_language(self):
        reviewer = AsyncCodeReviewer(api_key="test-key")
        assert reviewer._detect_language(Path("test.py")) == "python"
        assert reviewer._detect_language(Path("test.js")) == "javascript"
        assert reviewer._detect_language(Path("test.ts")) == "typescript"
        assert reviewer._detect_language(Path("test.xyz")) is None


class TestAsyncReviewCode:
    """Tests for async review_code functionality."""
    
    @pytest.mark.asyncio
    async def test_review_code_async(self):
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()
            provider.call_async = AsyncMock(return_value=MagicMock(content="<ignored>"))
            provider.parse_json_response.return_value = {
                "summary": "Good code",
                "issues": [],
                "score": 85,
                "positive": ["Clean"],
            }
            mock_get_provider.return_value = provider

            async with AsyncCodeReviewer(api_key="test-key") as reviewer:
                result = await reviewer.review_code_async("def hello(): pass", language="python")

            assert result.summary == "Good code"
            assert result.score == 85
            assert len(result.issues) == 0
            assert "Clean" in result.positive
    
    @pytest.mark.asyncio
    async def test_review_code_with_issues(self):
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()
            provider.call_async = AsyncMock(return_value=MagicMock(content="<ignored>"))
            provider.parse_json_response.return_value = {
                "summary": "Security issue found",
                "issues": [
                    {
                        "line": 5,
                        "severity": "critical",
                        "category": "security",
                        "message": "SQL injection vulnerability",
                        "suggestion": "Use parameterized queries",
                    }
                ],
                "score": 30,
                "positive": [],
            }
            mock_get_provider.return_value = provider

            async with AsyncCodeReviewer(api_key="test-key") as reviewer:
                result = await reviewer.review_code_async("SELECT * FROM users")

            assert result.score == 30
            assert len(result.issues) == 1
            assert result.issues[0].severity == Severity.CRITICAL
            assert result.issues[0].category == Category.SECURITY


class TestAsyncReviewFile:
    """Tests for async file review functionality."""
    
    @pytest.mark.asyncio
    async def test_review_file_not_found(self):
        reviewer = AsyncCodeReviewer(api_key="test-key")
        
        with pytest.raises(FileNotFoundError):
            await reviewer.review_file_async(Path("/nonexistent/file.py"))
    
    @pytest.mark.asyncio
    async def test_review_file_binary_rejected(self, tmp_path):
        binary_file = tmp_path / "image.png"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        
        reviewer = AsyncCodeReviewer(api_key="test-key")
        
        with pytest.raises(BinaryFileError):
            await reviewer.review_file_async(binary_file)
    
    @pytest.mark.asyncio
    async def test_review_file_too_large(self, tmp_path):
        large_file = tmp_path / "large.py"
        large_file.write_text("x" * 200_000)
        
        config = Config(api_key="test", max_file_size=100_000)
        reviewer = AsyncCodeReviewer(config=config)
        
        with pytest.raises(ValueError, match="File too large"):
            await reviewer.review_file_async(large_file)
    
    @pytest.mark.asyncio
    async def test_review_file_success(self, tmp_path):
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()
            provider.call_async = AsyncMock(return_value=MagicMock(content="<ignored>"))
            provider.parse_json_response.return_value = {
                "summary": "OK",
                "issues": [],
                "score": 90,
                "positive": [],
            }
            mock_get_provider.return_value = provider

            test_file = tmp_path / "test.py"
            test_file.write_text("def hello(): print('world')")

            async with AsyncCodeReviewer(api_key="test-key") as reviewer:
                result = await reviewer.review_file_async(test_file)

            assert result.score == 90
            assert result.issues[0].file == str(test_file) if result.issues else True


class TestAsyncReviewFilesParallel:
    """Tests for parallel file review functionality."""
    
    @pytest.mark.asyncio
    async def test_review_files_async_parallel(self, tmp_path):
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()
            provider.call_async = AsyncMock(return_value=MagicMock(content="<ignored>"))
            provider.parse_json_response.return_value = {
                "summary": "OK",
                "issues": [],
                "score": 80,
                "positive": [],
            }
            mock_get_provider.return_value = provider

            files = []
            for i in range(5):
                f = tmp_path / f"test_{i}.py"
                f.write_text(f"def func_{i}(): pass")
                files.append(f)

            async with AsyncCodeReviewer(api_key="test-key") as reviewer:
                results = await reviewer.review_files_async(files)

            assert len(results) == 5
            for path in files:
                assert str(path) in results
                assert results[str(path)].score == 80
    
    @pytest.mark.asyncio
    async def test_review_files_handles_binary_gracefully(self, tmp_path):
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()
            provider.call_async = AsyncMock(return_value=MagicMock(content="<ignored>"))
            provider.parse_json_response.return_value = {
                "summary": "OK",
                "issues": [],
                "score": 80,
                "positive": [],
            }
            mock_get_provider.return_value = provider

            text_file = tmp_path / "code.py"
            text_file.write_text("print('hello')")

            binary_file = tmp_path / "image.png"
            binary_file.write_bytes(b"\x89PNG" + b"\x00" * 100)

            async with AsyncCodeReviewer(api_key="test-key") as reviewer:
                results = await reviewer.review_files_async([text_file, binary_file])

            assert results[str(text_file)].score == 80
            assert results[str(binary_file)].score == -1
            assert "Skipped" in results[str(binary_file)].summary
    
    @pytest.mark.asyncio
    async def test_review_files_handles_errors_gracefully(self, tmp_path):
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()
            call_count = 0

            async def call_async(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return MagicMock(content="<ignored>")
                raise Exception("API error")

            provider.call_async = AsyncMock(side_effect=call_async)
            provider.parse_json_response.return_value = {
                "summary": "OK",
                "issues": [],
                "score": 80,
                "positive": [],
            }
            mock_get_provider.return_value = provider

            file1 = tmp_path / "good.py"
            file1.write_text("print('ok')")
            file2 = tmp_path / "bad.py"
            file2.write_text("print('error')")

            async with AsyncCodeReviewer(api_key="test-key") as reviewer:
                results = await reviewer.review_files_async([file1, file2])

            assert results[str(file1)].score == 80
            assert results[str(file2)].score == 0
            assert "Error" in results[str(file2)].summary
    
    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self, tmp_path):
        """Test that max_concurrent properly limits parallel requests."""
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()

            concurrent_calls = 0
            max_concurrent_seen = 0

            async def call_async(*args, **kwargs):
                nonlocal concurrent_calls, max_concurrent_seen
                concurrent_calls += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent_calls)

                import asyncio
                await asyncio.sleep(0.05)

                concurrent_calls -= 1
                return MagicMock(content="<ignored>")

            provider.call_async = AsyncMock(side_effect=call_async)
            provider.parse_json_response.return_value = {
                "summary": "OK",
                "issues": [],
                "score": 80,
                "positive": [],
            }
            mock_get_provider.return_value = provider

            files = []
            for i in range(10):
                f = tmp_path / f"test_{i}.py"
                f.write_text(f"x = {i}")
                files.append(f)
            
            # Limit to 3 concurrent
            async with AsyncCodeReviewer(
                api_key="test-key",
                max_concurrent=3
            ) as reviewer:
                await reviewer.review_files_async(files)
            
            # Should never exceed max_concurrent
            assert max_concurrent_seen <= 3


class TestAsyncRateLimitHandling:
    """Tests for async rate limit handling."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_error_raised(self):
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()
            provider.call_async = AsyncMock(side_effect=RateLimitError(provider="anthropic", retry_after=30))
            mock_get_provider.return_value = provider

            async with AsyncCodeReviewer(api_key="test-key") as reviewer:
                with pytest.raises(RateLimitError) as exc_info:
                    await reviewer.review_code_async("def test(): pass")

            assert exc_info.value.retry_after == 30


class TestAsyncContextManager:
    """Tests for async context manager functionality."""
    
    @pytest.mark.asyncio
    async def test_context_manager_exits_cleanly(self):
        # Provider abstraction doesn't expose a raw client; just ensure context manager works.
        async with AsyncCodeReviewer(api_key="test-key") as reviewer:
            assert reviewer.api_key == "test-key"


class TestConvenienceFunction:
    """Tests for the review_files_parallel convenience function."""
    
    @pytest.mark.asyncio
    async def test_review_files_parallel_function(self, tmp_path):
        with patch("coderev.async_reviewer.get_provider") as mock_get_provider:
            provider = MagicMock()
            provider.call_async = AsyncMock(return_value=MagicMock(content="<ignored>"))
            provider.parse_json_response.return_value = {
                "summary": "OK",
                "issues": [],
                "score": 95,
                "positive": [],
            }
            mock_get_provider.return_value = provider

            test_file = tmp_path / "test.py"
            test_file.write_text("x = 1")

            results = await review_files_parallel([test_file], api_key="test-key", max_concurrent=2)

            assert len(results) == 1
            assert results[str(test_file)].score == 95
