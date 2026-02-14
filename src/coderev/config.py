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
    model: str = DEFAULT_MODEL
    focus: list[str] = field(default_factory=lambda: DEFAULT_FOCUS_AREAS.copy())
    ignore_patterns: list[str] = field(default_factory=list)
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    language_hints: bool = True
    github: GitHubConfig = field(default_factory=GitHubConfig)
    
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
        api_key = config_data.get("api_key") or os.environ.get("CODEREV_API_KEY")
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        
        return cls(
            api_key=api_key,
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
        
        if not self.api_key:
            errors.append("API key not configured. Set CODEREV_API_KEY or add to .coderev.toml")
        
        valid_focus = {"bugs", "security", "performance", "style", "architecture", "testing"}
        invalid_focus = set(self.focus) - valid_focus
        if invalid_focus:
            errors.append(f"Invalid focus areas: {invalid_focus}. Valid: {valid_focus}")
        
        return errors
