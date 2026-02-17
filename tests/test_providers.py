"""Tests for LLM provider abstraction."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import sys

from coderev.providers import (
    BaseProvider,
    AnthropicProvider,
    OpenAIProvider,
    RateLimitError,
    ProviderError,
    ProviderResponse,
    get_provider,
    detect_provider_from_model,
    PROVIDERS,
)
from coderev.config import Config, detect_provider


class TestProviderResponse:
    """Tests for ProviderResponse dataclass."""
    
    def test_basic_response(self):
        response = ProviderResponse(
            content="Hello, world!",
            model="gpt-4",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
        assert response.content == "Hello, world!"
        assert response.model == "gpt-4"
        assert response.usage["input_tokens"] == 10
    
    def test_response_without_usage(self):
        response = ProviderResponse(content="Test", model="claude-3")
        assert response.usage is None


class TestRateLimitError:
    """Tests for RateLimitError."""
    
    def test_basic_error(self):
        error = RateLimitError(provider="anthropic")
        assert "Anthropic" in error.message
        assert "rate limit" in error.message.lower()
    
    def test_with_retry_after(self):
        error = RateLimitError(retry_after=30, provider="openai")
        assert "30 seconds" in error.message
        assert "OpenAI" in error.message
    
    def test_with_retry_after_minutes(self):
        error = RateLimitError(retry_after=120, provider="anthropic")
        assert "2.0 minutes" in error.message
    
    def test_custom_message(self):
        error = RateLimitError(message="Custom error message", provider="openai")
        assert error.message == "Custom error message"
    
    def test_original_error_preserved(self):
        original = ValueError("Original")
        error = RateLimitError(original_error=original, provider="anthropic")
        assert error.original_error is original


class TestDetectProvider:
    """Tests for provider detection from model name."""
    
    def test_detect_openai_gpt4(self):
        assert detect_provider_from_model("gpt-4") == "openai"
        assert detect_provider_from_model("gpt-4-turbo") == "openai"
        assert detect_provider_from_model("gpt-4o") == "openai"
        assert detect_provider_from_model("gpt-4o-mini") == "openai"
    
    def test_detect_openai_gpt35(self):
        assert detect_provider_from_model("gpt-3.5-turbo") == "openai"
    
    def test_detect_openai_o1(self):
        assert detect_provider_from_model("o1") == "openai"
        assert detect_provider_from_model("o1-mini") == "openai"
        assert detect_provider_from_model("o1-preview") == "openai"
    
    def test_detect_anthropic_claude(self):
        assert detect_provider_from_model("claude-3-opus") == "anthropic"
        assert detect_provider_from_model("claude-3-sonnet") == "anthropic"
        assert detect_provider_from_model("claude-3-haiku") == "anthropic"
        assert detect_provider_from_model("claude-3-5-sonnet") == "anthropic"
    
    def test_detect_default_anthropic(self):
        # Unknown models default to anthropic
        assert detect_provider_from_model("unknown-model") == "anthropic"
    
    def test_config_detect_provider(self):
        # Test the config module's detect_provider function
        assert detect_provider("gpt-4o") == "openai"
        assert detect_provider("claude-3-sonnet") == "anthropic"


class TestGetProvider:
    """Tests for get_provider factory function."""
    
    def test_get_anthropic_provider(self):
        # Use the actual anthropic module but don't call the API
        provider = get_provider("anthropic", "test-key", "claude-3-sonnet")
        assert isinstance(provider, AnthropicProvider)
        assert provider.api_key == "test-key"
    
    def test_get_openai_provider(self):
        provider = get_provider("openai", "sk-test", "gpt-4")
        assert isinstance(provider, OpenAIProvider)
        assert provider.api_key == "sk-test"
    
    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("unknown", "key", "model")
    
    def test_case_insensitive(self):
        provider = get_provider("ANTHROPIC", "test-key", "claude-3")
        assert isinstance(provider, AnthropicProvider)


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""
    
    def test_initialization(self):
        provider = AnthropicProvider(api_key="test-key", model="claude-3-sonnet")
        assert provider.api_key == "test-key"
        assert provider.client is not None
    
    def test_model_alias_expansion(self):
        provider = AnthropicProvider(api_key="key", model="claude-3-sonnet")
        assert provider.model == "claude-3-sonnet-20240229"
    
    def test_model_full_name_passthrough(self):
        provider = AnthropicProvider(api_key="key", model="claude-3-opus-20240229")
        assert provider.model == "claude-3-opus-20240229"


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""
    
    def test_initialization(self):
        provider = OpenAIProvider(api_key="sk-test", model="gpt-4")
        assert provider.api_key == "sk-test"
        assert provider.client is not None
    
    def test_model_alias_expansion(self):
        provider = OpenAIProvider(api_key="key", model="gpt-4-turbo")
        assert provider.model == "gpt-4-turbo-preview"
    
    def test_model_full_name_passthrough(self):
        provider = OpenAIProvider(api_key="key", model="gpt-4o-2024-08-06")
        assert provider.model == "gpt-4o-2024-08-06"


class TestBaseProviderJSONParsing:
    """Tests for JSON parsing in BaseProvider."""
    
    def test_parse_json_plain(self):
        provider = AnthropicProvider(api_key="key", model="claude-3")
        result = provider.parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}
    
    def test_parse_json_with_code_block(self):
        provider = AnthropicProvider(api_key="key", model="claude-3")
        content = '```json\n{"key": "value"}\n```'
        result = provider.parse_json_response(content)
        assert result == {"key": "value"}
    
    def test_parse_json_with_code_block_no_lang(self):
        provider = AnthropicProvider(api_key="key", model="claude-3")
        content = '```\n{"key": "value"}\n```'
        result = provider.parse_json_response(content)
        assert result == {"key": "value"}
    
    def test_parse_json_partial_recovery(self):
        provider = AnthropicProvider(api_key="key", model="claude-3")
        # Missing closing brace
        content = '{"key": "value"'
        result = provider.parse_json_response(content)
        assert result == {"key": "value"}
    
    def test_parse_json_invalid_raises(self):
        provider = AnthropicProvider(api_key="key", model="claude-3")
        with pytest.raises(ValueError, match="Failed to parse"):
            provider.parse_json_response("not json at all")
    
    def test_parse_json_nested(self):
        provider = OpenAIProvider(api_key="key", model="gpt-4")
        content = '{"issues": [{"line": 1, "message": "test"}], "score": 85}'
        result = provider.parse_json_response(content)
        assert result["score"] == 85
        assert len(result["issues"]) == 1


class TestConfigProviderIntegration:
    """Tests for Config integration with providers."""
    
    def test_config_get_provider_auto(self):
        config = Config(
            api_key="anthropic-key",
            model="claude-3-sonnet",
        )
        assert config.get_provider() == "anthropic"
    
    def test_config_get_provider_openai_auto(self):
        config = Config(
            openai_api_key="openai-key",
            model="gpt-4o",
        )
        assert config.get_provider() == "openai"
    
    def test_config_get_provider_explicit(self):
        config = Config(
            api_key="key",
            provider="openai",
            model="claude-3-sonnet",  # Model suggests anthropic
        )
        # Explicit provider overrides auto-detection
        assert config.get_provider() == "openai"
    
    def test_config_get_api_key_for_anthropic(self):
        config = Config(
            api_key="anthropic-key",
            openai_api_key="openai-key",
        )
        assert config.get_api_key_for_provider("anthropic") == "anthropic-key"
    
    def test_config_get_api_key_for_openai(self):
        config = Config(
            api_key="anthropic-key",
            openai_api_key="openai-key",
        )
        assert config.get_api_key_for_provider("openai") == "openai-key"
    
    def test_config_validate_openai_missing_key(self):
        config = Config(
            model="gpt-4o",
            openai_api_key=None,
        )
        errors = config.validate()
        assert any("OpenAI API key" in e for e in errors)
    
    def test_config_validate_invalid_provider(self):
        config = Config(
            api_key="key",
            provider="invalid",
        )
        errors = config.validate()
        assert any("Invalid provider" in e for e in errors)


class TestProviderRegistry:
    """Tests for provider registry."""
    
    def test_providers_registered(self):
        assert "anthropic" in PROVIDERS
        assert "openai" in PROVIDERS
    
    def test_provider_classes(self):
        assert PROVIDERS["anthropic"] == AnthropicProvider
        assert PROVIDERS["openai"] == OpenAIProvider
