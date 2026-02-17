"""Configuration management for CodeRev."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml


DEFAULT_CONFIG_FILENAME = ".coderev.toml"
DEFAULT_FOCUS_AREAS = ["bugs", "security", "performance"]
DEFAULT_MODEL = "claude-3-sonnet-20240229"
DEFAULT_MAX_FILE_SIZE = 100_000  # 100KB

# Provider detection based on model prefix
OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "davinci", "curie", "babbage")
ANTHROPIC_MODEL_PREFIXES = ("claude",)


def detect_provider(model: str) -> str:
    """Detect provider from model name.
    
    Args:
        model: Model name/identifier.
        
    Returns:
        Provider name ('anthropic' or 'openai').
    """
    model_lower = model.lower()
    
    if any(model_lower.startswith(p) for p in OPENAI_MODEL_PREFIXES):
        return "openai"
    
    # Default to anthropic
    return "anthropic"


@dataclass
class GitHubConfig:
    """GitHub-specific configuration."""
    
    token: str | None = None
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubConfig:
        return cls(
            token=data.get("token") or os.environ.get("GITHUB_TOKEN")
        )


@dataclass
class Config:
    """Main configuration for CodeRev."""
    
    api_key: str | None = None
    openai_api_key: str | None = None
    provider: str | None = None  # 'anthropic', 'openai', or None (auto-detect)
    model: str = DEFAULT_MODEL
    focus: list[str] = field(default_factory=lambda: DEFAULT_FOCUS_AREAS.copy())
    ignore_patterns: list[str] = field(default_factory=list)
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    language_hints: bool = True
    github: GitHubConfig = field(default_factory=GitHubConfig)
    
    def get_provider(self) -> str:
        """Get the provider to use, auto-detecting from model if not specified."""
        if self.provider:
            return self.provider
        return detect_provider(self.model)
    
    def get_api_key_for_provider(self, provider: str | None = None) -> str | None:
        """Get the appropriate API key for the given provider.
        
        Args:
            provider: Provider name. If None, auto-detects from model.
            
        Returns:
            API key for the provider, or None if not configured.
        """
        provider = provider or self.get_provider()
        
        if provider == "openai":
            return self.openai_api_key
        else:  # anthropic
            return self.api_key
    
    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load configuration from file and environment variables."""
        config_data: dict[str, Any] = {}
        
        # Search for config file
        search_paths = []
        if config_path:
            search_paths.append(config_path)
        search_paths.extend([
            Path.cwd() / DEFAULT_CONFIG_FILENAME,
            Path.home() / DEFAULT_CONFIG_FILENAME,
        ])
        
        for path in search_paths:
            if path.exists():
                with open(path) as f:
                    loaded = toml.load(f)
                    config_data = loaded.get("coderev", loaded)
                break
        
        # Extract github config
        github_data = config_data.pop("github", {})
        
        # Build config with env var fallbacks
        # Anthropic API key (backwards compatible)
        api_key = config_data.get("api_key") or os.environ.get("CODEREV_API_KEY")
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        
        # OpenAI API key
        openai_api_key = config_data.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
        
        # Provider (optional, auto-detected from model if not specified)
        provider = config_data.get("provider")
        
        return cls(
            api_key=api_key,
            openai_api_key=openai_api_key,
            provider=provider,
            model=config_data.get("model", DEFAULT_MODEL),
            focus=config_data.get("focus", DEFAULT_FOCUS_AREAS.copy()),
            ignore_patterns=config_data.get("ignore_patterns", []),
            max_file_size=config_data.get("max_file_size", DEFAULT_MAX_FILE_SIZE),
            language_hints=config_data.get("language_hints", True),
            github=GitHubConfig.from_dict(github_data),
        )
    
    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []
        
        provider = self.get_provider()
        api_key = self.get_api_key_for_provider(provider)
        
        if not api_key:
            if provider == "openai":
                errors.append(
                    "OpenAI API key not configured. "
                    "Set OPENAI_API_KEY environment variable or add openai_api_key to .coderev.toml"
                )
            else:
                errors.append(
                    "Anthropic API key not configured. "
                    "Set CODEREV_API_KEY or ANTHROPIC_API_KEY environment variable "
                    "or add api_key to .coderev.toml"
                )
        
        valid_focus = {"bugs", "security", "performance", "style", "architecture", "testing"}
        invalid_focus = set(self.focus) - valid_focus
        if invalid_focus:
            errors.append(f"Invalid focus areas: {invalid_focus}. Valid: {valid_focus}")
        
        valid_providers = {"anthropic", "openai"}
        if self.provider and self.provider not in valid_providers:
            errors.append(f"Invalid provider: {self.provider}. Valid: {valid_providers}")
        
        return errors
