"""Tests for configuration module."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from coderev.config import Config, GitHubConfig, DEFAULT_MODEL, DEFAULT_FOCUS_AREAS


class TestGitHubConfig:
    """Tests for GitHubConfig."""
    
    def test_from_dict_with_token(self):
        data = {"token": "test-token"}
        config = GitHubConfig.from_dict(data)
        assert config.token == "test-token"
    
    def test_from_dict_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            config = GitHubConfig.from_dict({})
            assert config.token is None
    
    def test_from_dict_env_fallback(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env-token"}):
            config = GitHubConfig.from_dict({})
            assert config.token == "env-token"


class TestConfig:
    """Tests for Config."""
    
    def test_defaults(self):
        with patch.dict(os.environ, {"CODEREV_API_KEY": "test-key"}, clear=True):
            config = Config.load()
            assert config.model == DEFAULT_MODEL
            assert config.focus == DEFAULT_FOCUS_AREAS
            assert config.language_hints is True
    
    def test_api_key_from_env(self):
        with patch.dict(os.environ, {"CODEREV_API_KEY": "my-api-key"}):
            config = Config.load()
            assert config.api_key == "my-api-key"
    
    def test_anthropic_key_fallback(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "anthropic-key"}, clear=True):
            config = Config.load()
            assert config.api_key == "anthropic-key"
    
    def test_validate_missing_api_key(self):
        config = Config(api_key=None)
        errors = config.validate()
        assert any("API key" in e for e in errors)
    
    def test_validate_invalid_focus(self):
        config = Config(api_key="test", focus=["invalid_focus"])
        errors = config.validate()
        assert any("Invalid focus areas" in e for e in errors)
    
    def test_validate_success(self):
        config = Config(api_key="test-key", focus=["bugs", "security"])
        errors = config.validate()
        assert len(errors) == 0
    
    def test_load_from_file(self, tmp_path):
        config_file = tmp_path / ".coderev.toml"
        config_file.write_text('''
[coderev]
api_key = "file-key"
model = "claude-3-opus"
focus = ["security"]
max_file_size = 50000
''')
        
        config = Config.load(config_file)
        assert config.api_key == "file-key"
        assert config.model == "claude-3-opus"
        assert config.focus == ["security"]
        assert config.max_file_size == 50000
