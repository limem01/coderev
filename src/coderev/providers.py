"""LLM provider abstraction for CodeRev.

Supports multiple AI providers (Anthropic, OpenAI) through a unified interface.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from coderev.config import Config


@dataclass
class ProviderResponse:
    """Standardized response from any LLM provider."""
    
    content: str
    model: str
    usage: dict[str, int] | None = None


class ProviderError(Exception):
    """Base exception for provider errors."""
    pass


class RateLimitError(ProviderError):
    """Raised when the API rate limit is exceeded.
    
    Provides helpful information about retry timing and suggestions.
    """
    
    def __init__(
        self,
        message: str | None = None,
        retry_after: float | None = None,
        original_error: Exception | None = None,
        provider: str = "unknown",
    ):
        self.retry_after = retry_after
        self.original_error = original_error
        self.provider = provider
        
        if message:
            self.message = message
        else:
            self.message = self._build_message()
        
        super().__init__(self.message)
    
    def _build_message(self) -> str:
        """Build a helpful error message with retry guidance."""
        provider_display = "OpenAI" if self.provider == "openai" else self.provider.title()
        parts = [f"{provider_display} API rate limit exceeded."]
        
        if self.retry_after:
            if self.retry_after < 60:
                parts.append(f"Retry after: {self.retry_after:.0f} seconds.")
            else:
                minutes = self.retry_after / 60
                parts.append(f"Retry after: {minutes:.1f} minutes.")
        
        parts.append("\nSuggestions:")
        parts.append("  - Wait and retry the request")
        parts.append("  - Review fewer files at once")
        parts.append("  - Use --focus to limit review scope")
        
        if self.provider == "anthropic":
            parts.append("  - Check your API plan limits at console.anthropic.com")
        elif self.provider == "openai":
            parts.append("  - Check your API plan limits at platform.openai.com")
        
        return "\n".join(parts)


class BaseProvider(ABC):
    """Abstract base class for LLM providers."""
    
    provider_name: str = "base"
    
    @abstractmethod
    def __init__(self, api_key: str, model: str):
        """Initialize the provider with API key and model."""
        pass
    
    @abstractmethod
    def call(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        """Make a synchronous API call.
        
        Args:
            system_prompt: System/context prompt for the model.
            user_prompt: User message/prompt.
            
        Returns:
            ProviderResponse with the model's response.
            
        Raises:
            RateLimitError: When rate limited.
            ProviderError: For other API errors.
        """
        pass
    
    @abstractmethod
    async def call_async(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        """Make an asynchronous API call.
        
        Args:
            system_prompt: System/context prompt for the model.
            user_prompt: User message/prompt.
            
        Returns:
            ProviderResponse with the model's response.
            
        Raises:
            RateLimitError: When rate limited.
            ProviderError: For other API errors.
        """
        pass
    
    def parse_json_response(self, content: str) -> dict[str, Any]:
        """Parse JSON from response, handling markdown code blocks.
        
        Args:
            content: Raw response content from the model.
            
        Returns:
            Parsed JSON as a dictionary.
            
        Raises:
            ValueError: If JSON cannot be parsed.
        """
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if json_match:
            content = json_match.group(1)
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            # Try to salvage partial JSON
            content = content.strip()
            if not content.endswith("}"):
                content += "}"
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                raise ValueError(f"Failed to parse API response as JSON: {e}")


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider implementation."""
    
    provider_name = "anthropic"
    
    # Mapping of short model names to full model IDs
    MODEL_ALIASES: dict[str, str] = {
        "claude-3-opus": "claude-3-opus-20240229",
        "claude-3-sonnet": "claude-3-sonnet-20240229",
        "claude-3-haiku": "claude-3-haiku-20240307",
        "claude-3.5-sonnet": "claude-3-5-sonnet-20241022",
        "claude-3.5-haiku": "claude-3-5-haiku-20241022",
    }
    
    def __init__(self, api_key: str, model: str):
        """Initialize Anthropic provider.
        
        Args:
            api_key: Anthropic API key.
            model: Model name (can be alias or full name).
        """
        import anthropic
        
        self.api_key = api_key
        self.model = self.MODEL_ALIASES.get(model, model)
        self.client = anthropic.Anthropic(api_key=api_key)
        self._anthropic = anthropic  # Keep reference for exception handling
    
    def call(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        """Make a synchronous Anthropic API call."""
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except self._anthropic.RateLimitError as e:
            retry_after = None
            if hasattr(e, 'response') and e.response is not None:
                retry_header = e.response.headers.get('retry-after')
                if retry_header:
                    try:
                        retry_after = float(retry_header)
                    except (ValueError, TypeError):
                        pass
            
            raise RateLimitError(
                retry_after=retry_after,
                original_error=e,
                provider="anthropic",
            ) from e
        except self._anthropic.APIStatusError as e:
            if e.status_code == 429:
                raise RateLimitError(
                    message=f"Anthropic API rate limit exceeded (HTTP 429): {e.message}",
                    original_error=e,
                    provider="anthropic",
                ) from e
            raise ProviderError(f"Anthropic API error: {e}") from e
        
        usage = None
        if hasattr(message, 'usage'):
            usage = {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
            }
        
        return ProviderResponse(
            content=message.content[0].text,
            model=self.model,
            usage=usage,
        )
    
    async def call_async(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        """Make an asynchronous Anthropic API call."""
        import anthropic
        
        async_client = anthropic.AsyncAnthropic(api_key=self.api_key)
        
        try:
            message = await async_client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.RateLimitError as e:
            retry_after = None
            if hasattr(e, 'response') and e.response is not None:
                retry_header = e.response.headers.get('retry-after')
                if retry_header:
                    try:
                        retry_after = float(retry_header)
                    except (ValueError, TypeError):
                        pass
            
            raise RateLimitError(
                retry_after=retry_after,
                original_error=e,
                provider="anthropic",
            ) from e
        except anthropic.APIStatusError as e:
            if e.status_code == 429:
                raise RateLimitError(
                    message=f"Anthropic API rate limit exceeded (HTTP 429): {e.message}",
                    original_error=e,
                    provider="anthropic",
                ) from e
            raise ProviderError(f"Anthropic API error: {e}") from e
        
        usage = None
        if hasattr(message, 'usage'):
            usage = {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
            }
        
        return ProviderResponse(
            content=message.content[0].text,
            model=self.model,
            usage=usage,
        )


class OpenAIProvider(BaseProvider):
    """OpenAI GPT provider implementation."""
    
    provider_name = "openai"
    
    # Mapping of short model names to full model IDs
    MODEL_ALIASES: dict[str, str] = {
        "gpt-4": "gpt-4",
        "gpt-4-turbo": "gpt-4-turbo-preview",
        "gpt-4o": "gpt-4o",
        "gpt-4o-mini": "gpt-4o-mini",
        "gpt-3.5-turbo": "gpt-3.5-turbo",
        "o1": "o1-preview",
        "o1-mini": "o1-mini",
    }
    
    def __init__(self, api_key: str, model: str):
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key.
            model: Model name (can be alias or full name).
        """
        try:
            import openai
        except ImportError:
            raise ImportError(
                "OpenAI support requires the 'openai' package. "
                "Install it with: pip install coderev[openai]"
            )
        
        self.api_key = api_key
        self.model = self.MODEL_ALIASES.get(model, model)
        self.client = openai.OpenAI(api_key=api_key)
        self._openai = openai
    
    def call(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        """Make a synchronous OpenAI API call."""
        try:
            # o1 models don't support system messages
            if self.model.startswith("o1"):
                messages = [
                    {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}
                ]
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=4096,
            )
        except self._openai.RateLimitError as e:
            retry_after = None
            if hasattr(e, 'response') and e.response is not None:
                retry_header = e.response.headers.get('retry-after')
                if retry_header:
                    try:
                        retry_after = float(retry_header)
                    except (ValueError, TypeError):
                        pass
            
            raise RateLimitError(
                retry_after=retry_after,
                original_error=e,
                provider="openai",
            ) from e
        except self._openai.APIStatusError as e:
            if e.status_code == 429:
                raise RateLimitError(
                    message=f"OpenAI API rate limit exceeded (HTTP 429): {str(e)}",
                    original_error=e,
                    provider="openai",
                ) from e
            raise ProviderError(f"OpenAI API error: {e}") from e
        
        usage = None
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        
        return ProviderResponse(
            content=response.choices[0].message.content or "",
            model=self.model,
            usage=usage,
        )
    
    async def call_async(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        """Make an asynchronous OpenAI API call."""
        import openai
        
        async_client = openai.AsyncOpenAI(api_key=self.api_key)
        
        try:
            # o1 models don't support system messages
            if self.model.startswith("o1"):
                messages = [
                    {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}
                ]
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            
            response = await async_client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=4096,
            )
        except openai.RateLimitError as e:
            retry_after = None
            if hasattr(e, 'response') and e.response is not None:
                retry_header = e.response.headers.get('retry-after')
                if retry_header:
                    try:
                        retry_after = float(retry_header)
                    except (ValueError, TypeError):
                        pass
            
            raise RateLimitError(
                retry_after=retry_after,
                original_error=e,
                provider="openai",
            ) from e
        except openai.APIStatusError as e:
            if e.status_code == 429:
                raise RateLimitError(
                    message=f"OpenAI API rate limit exceeded (HTTP 429): {str(e)}",
                    original_error=e,
                    provider="openai",
                ) from e
            raise ProviderError(f"OpenAI API error: {e}") from e
        
        usage = None
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        
        return ProviderResponse(
            content=response.choices[0].message.content or "",
            model=self.model,
            usage=usage,
        )


# Provider registry
PROVIDERS: dict[str, type[BaseProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def get_provider(
    provider_name: str,
    api_key: str,
    model: str,
) -> BaseProvider:
    """Get a provider instance by name.
    
    Args:
        provider_name: Name of the provider ('anthropic' or 'openai').
        api_key: API key for the provider.
        model: Model name to use.
        
    Returns:
        Initialized provider instance.
        
    Raises:
        ValueError: If provider is not supported.
    """
    provider_class = PROVIDERS.get(provider_name.lower())
    if not provider_class:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown provider: {provider_name}. Available: {available}")
    
    return provider_class(api_key=api_key, model=model)


def detect_provider_from_model(model: str) -> str:
    """Detect the provider based on model name.
    
    Args:
        model: Model name/identifier.
        
    Returns:
        Provider name ('anthropic' or 'openai').
    """
    model_lower = model.lower()
    
    # OpenAI models
    if any(prefix in model_lower for prefix in ["gpt-", "o1", "davinci", "curie", "babbage"]):
        return "openai"
    
    # Anthropic models (default)
    if any(prefix in model_lower for prefix in ["claude", "anthropic"]):
        return "anthropic"
    
    # Default to anthropic for backwards compatibility
    return "anthropic"
