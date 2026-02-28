"""Integration tests with real API calls.

These tests make actual API calls to Anthropic and OpenAI.
They are skipped by default and only run when:
1. The --integration flag is passed to pytest
2. The required API keys are set in environment variables

Run with: pytest tests/test_integration.py --integration -v

Environment variables required:
- ANTHROPIC_API_KEY: For Anthropic/Claude tests
- OPENAI_API_KEY: For OpenAI/GPT tests
"""

import pytest
import asyncio
import tempfile
import os
from pathlib import Path

from coderev.providers import (
    AnthropicProvider,
    OpenAIProvider,
    ProviderResponse,
    get_provider,
)
from coderev.reviewer import CodeReviewer, ReviewResult
from coderev.config import Config
from coderev.async_reviewer import AsyncCodeReviewer


@pytest.mark.integration
class TestAnthropicProviderIntegration:
    """Integration tests for Anthropic/Claude API."""
    
    def test_basic_call(self, anthropic_api_key):
        """Test basic synchronous API call to Claude."""
        provider = AnthropicProvider(
            api_key=anthropic_api_key,
            model="claude-3-haiku-20240307",  # Cheapest model
        )
        
        response = provider.call(
            system_prompt="You are a helpful assistant. Respond concisely.",
            user_prompt="What is 2 + 2? Answer with just the number.",
        )
        
        assert isinstance(response, ProviderResponse)
        assert response.content is not None
        assert len(response.content) > 0
        assert "4" in response.content
        assert response.model == "claude-3-haiku-20240307"
        assert response.usage is not None
        assert response.usage["input_tokens"] > 0
        assert response.usage["output_tokens"] > 0
    
    @pytest.mark.asyncio
    async def test_async_call(self, anthropic_api_key):
        """Test asynchronous API call to Claude."""
        provider = AnthropicProvider(
            api_key=anthropic_api_key,
            model="claude-3-haiku-20240307",
        )
        
        response = await provider.call_async(
            system_prompt="You are a helpful assistant. Respond concisely.",
            user_prompt="What is the capital of France? Answer with just the city name.",
        )
        
        assert isinstance(response, ProviderResponse)
        assert "Paris" in response.content
        assert response.usage is not None
    
    def test_json_response(self, anthropic_api_key):
        """Test getting and parsing JSON response."""
        provider = AnthropicProvider(
            api_key=anthropic_api_key,
            model="claude-3-haiku-20240307",
        )
        
        response = provider.call(
            system_prompt="You are a JSON API. Always respond with valid JSON only, no markdown.",
            user_prompt='Return a JSON object with keys "name" and "value".',
        )
        
        # Should be able to parse the response as JSON
        parsed = provider.parse_json_response(response.content)
        assert isinstance(parsed, dict)
        assert "name" in parsed or "value" in parsed


@pytest.mark.integration
class TestOpenAIProviderIntegration:
    """Integration tests for OpenAI/GPT API."""
    
    def test_basic_call(self, openai_api_key):
        """Test basic synchronous API call to GPT."""
        provider = OpenAIProvider(
            api_key=openai_api_key,
            model="gpt-4o-mini",  # Cheapest GPT-4 class model
        )
        
        response = provider.call(
            system_prompt="You are a helpful assistant. Respond concisely.",
            user_prompt="What is 3 + 3? Answer with just the number.",
        )
        
        assert isinstance(response, ProviderResponse)
        assert response.content is not None
        assert len(response.content) > 0
        assert "6" in response.content
        assert response.usage is not None
        assert response.usage["input_tokens"] > 0
        assert response.usage["output_tokens"] > 0
    
    @pytest.mark.asyncio
    async def test_async_call(self, openai_api_key):
        """Test asynchronous API call to GPT."""
        provider = OpenAIProvider(
            api_key=openai_api_key,
            model="gpt-4o-mini",
        )
        
        response = await provider.call_async(
            system_prompt="You are a helpful assistant. Respond concisely.",
            user_prompt="What is the capital of Germany? Answer with just the city name.",
        )
        
        assert isinstance(response, ProviderResponse)
        assert "Berlin" in response.content
        assert response.usage is not None
    
    def test_json_response(self, openai_api_key):
        """Test getting and parsing JSON response."""
        provider = OpenAIProvider(
            api_key=openai_api_key,
            model="gpt-4o-mini",
        )
        
        response = provider.call(
            system_prompt="You are a JSON API. Always respond with valid JSON only.",
            user_prompt='Return a JSON object with keys "status" and "code".',
        )
        
        parsed = provider.parse_json_response(response.content)
        assert isinstance(parsed, dict)


@pytest.mark.integration
class TestCodeReviewerIntegration:
    """Integration tests for full code review workflow."""
    
    def test_review_python_code_anthropic(self, anthropic_api_key, sample_python_code):
        """Test reviewing Python code with Anthropic."""
        config = Config(
            api_key=anthropic_api_key,
            model="claude-3-haiku-20240307",
            provider="anthropic",
            focus=["bugs", "security"],
        )
        
        reviewer = CodeReviewer(config)
        
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
        ) as f:
            f.write(sample_python_code)
            temp_path = f.name
        
        try:
            result = reviewer.review_file(Path(temp_path))
            
            assert isinstance(result, ReviewResult)
            assert result.file_path == Path(temp_path)
            assert result.issues is not None
            assert isinstance(result.issues, list)
            # The code has intentional issues, should find some
            assert len(result.issues) > 0
            # Should have a score
            assert result.score is not None
            assert 0 <= result.score <= 100
        finally:
            os.unlink(temp_path)
    
    def test_review_python_code_openai(self, openai_api_key, sample_python_code):
        """Test reviewing Python code with OpenAI."""
        config = Config(
            openai_api_key=openai_api_key,
            model="gpt-4o-mini",
            provider="openai",
            focus=["bugs", "security"],
        )
        
        reviewer = CodeReviewer(config)
        
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
        ) as f:
            f.write(sample_python_code)
            temp_path = f.name
        
        try:
            result = reviewer.review_file(Path(temp_path))
            
            assert isinstance(result, ReviewResult)
            assert result.issues is not None
            assert len(result.issues) > 0
            assert result.score is not None
        finally:
            os.unlink(temp_path)
    
    def test_review_javascript_code(self, anthropic_api_key, sample_javascript_code):
        """Test reviewing JavaScript code."""
        config = Config(
            api_key=anthropic_api_key,
            model="claude-3-haiku-20240307",
            focus=["bugs", "security", "async"],
        )
        
        reviewer = CodeReviewer(config)
        
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            delete=False,
        ) as f:
            f.write(sample_javascript_code)
            temp_path = f.name
        
        try:
            result = reviewer.review_file(Path(temp_path))
            
            assert isinstance(result, ReviewResult)
            assert result.issues is not None
            # Should catch async issues and hardcoded secret
            assert len(result.issues) >= 2
            
            # Check that issues have required fields
            for issue in result.issues:
                assert hasattr(issue, "message") or "message" in issue
                assert hasattr(issue, "severity") or "severity" in issue
        finally:
            os.unlink(temp_path)


@pytest.mark.integration
class TestAsyncReviewerIntegration:
    """Integration tests for async parallel review."""
    
    @pytest.mark.asyncio
    async def test_parallel_review(self, anthropic_api_key, sample_python_code, sample_javascript_code):
        """Test reviewing multiple files in parallel."""
        config = Config(
            api_key=anthropic_api_key,
            model="claude-3-haiku-20240307",
            focus=["bugs"],
        )
        
        reviewer = AsyncCodeReviewer(config)
        
        # Create temp files
        temp_files = []
        try:
            for i, (code, ext) in enumerate([
                (sample_python_code, ".py"),
                (sample_javascript_code, ".js"),
            ]):
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=ext,
                    delete=False,
                ) as f:
                    f.write(code)
                    temp_files.append(Path(f.name))
            
            results = await reviewer.review_files(temp_files)
            
            assert len(results) == 2
            for result in results:
                assert isinstance(result, ReviewResult)
                assert result.issues is not None
                assert result.score is not None
        finally:
            for f in temp_files:
                if f.exists():
                    os.unlink(f)
    
    @pytest.mark.asyncio
    async def test_concurrent_api_calls(self, anthropic_api_key):
        """Test that multiple API calls execute concurrently."""
        import time
        
        provider = AnthropicProvider(
            api_key=anthropic_api_key,
            model="claude-3-haiku-20240307",
        )
        
        async def make_call(n):
            return await provider.call_async(
                system_prompt="Respond with just a single word.",
                user_prompt=f"What is number {n}? Just say the number.",
            )
        
        start = time.time()
        
        # Run 3 calls concurrently
        results = await asyncio.gather(
            make_call(1),
            make_call(2),
            make_call(3),
        )
        
        elapsed = time.time() - start
        
        assert len(results) == 3
        for r in results:
            assert isinstance(r, ProviderResponse)
        
        # Concurrent calls should complete faster than 3x sequential
        # (assuming each call takes ~1-2 seconds)
        # We don't assert timing strictly but log it
        print(f"\nConcurrent calls completed in {elapsed:.2f}s")


@pytest.mark.integration
class TestProviderFactoryIntegration:
    """Integration tests for provider factory."""
    
    def test_get_anthropic_provider_works(self, anthropic_api_key):
        """Test that get_provider returns working Anthropic provider."""
        provider = get_provider("anthropic", anthropic_api_key, "claude-3-haiku-20240307")
        
        response = provider.call(
            system_prompt="Be concise.",
            user_prompt="Say 'hello'",
        )
        
        assert "hello" in response.content.lower()
    
    def test_get_openai_provider_works(self, openai_api_key):
        """Test that get_provider returns working OpenAI provider."""
        provider = get_provider("openai", openai_api_key, "gpt-4o-mini")
        
        response = provider.call(
            system_prompt="Be concise.",
            user_prompt="Say 'hello'",
        )
        
        assert "hello" in response.content.lower()


@pytest.mark.integration
class TestModelAliasesIntegration:
    """Integration tests for model alias resolution."""
    
    def test_claude_sonnet_alias(self, anthropic_api_key):
        """Test that model aliases resolve correctly for Claude."""
        provider = AnthropicProvider(
            api_key=anthropic_api_key,
            model="claude-3-haiku",  # Short alias
        )
        
        # Should expand to full model name
        assert provider.model == "claude-3-haiku-20240307"
        
        # And the call should work
        response = provider.call(
            system_prompt="Be concise.",
            user_prompt="Say 'test'",
        )
        assert response.content is not None
    
    def test_gpt4o_alias(self, openai_api_key):
        """Test that model aliases resolve correctly for OpenAI."""
        provider = OpenAIProvider(
            api_key=openai_api_key,
            model="gpt-4o-mini",  # Should pass through
        )
        
        response = provider.call(
            system_prompt="Be concise.",
            user_prompt="Say 'test'",
        )
        assert response.content is not None


@pytest.mark.integration
class TestUsageTrackingIntegration:
    """Integration tests for token usage tracking."""
    
    def test_anthropic_usage_tracking(self, anthropic_api_key):
        """Test that Anthropic returns accurate usage stats."""
        provider = AnthropicProvider(
            api_key=anthropic_api_key,
            model="claude-3-haiku-20240307",
        )
        
        response = provider.call(
            system_prompt="You are a word counter.",
            user_prompt="Count to 10, one number per line.",
        )
        
        assert response.usage is not None
        assert response.usage["input_tokens"] > 0
        assert response.usage["output_tokens"] > 0
        # Output should be reasonably sized for counting to 10
        assert response.usage["output_tokens"] < 100
    
    def test_openai_usage_tracking(self, openai_api_key):
        """Test that OpenAI returns accurate usage stats."""
        provider = OpenAIProvider(
            api_key=openai_api_key,
            model="gpt-4o-mini",
        )
        
        response = provider.call(
            system_prompt="You are a word counter.",
            user_prompt="Count to 5, one number per line.",
        )
        
        assert response.usage is not None
        assert response.usage["input_tokens"] > 0
        assert response.usage["output_tokens"] > 0
