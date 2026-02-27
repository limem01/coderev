"""Tests for team configuration sharing."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import toml

from coderev.team import (
    TeamConfigError,
    parse_extends_url,
    resolve_github_url,
    deep_merge,
    resolve_extends,
    load_local_config,
    sync_team_config,
    create_team_config_template,
    clear_config_cache,
    list_cached_configs,
    get_cache_path,
    cache_remote_config,
)


class TestParseExtendsUrl:
    """Tests for parse_extends_url."""
    
    def test_github_shorthand(self):
        ref_type, location = parse_extends_url("gh:myorg/repo/config.toml")
        assert ref_type == "github"
        assert location == "myorg/repo/config.toml"
    
    def test_github_with_branch(self):
        ref_type, location = parse_extends_url("gh:myorg/repo/config.toml@develop")
        assert ref_type == "github"
        assert location == "myorg/repo/config.toml@develop"
    
    def test_https_url(self):
        ref_type, location = parse_extends_url("https://example.com/config.toml")
        assert ref_type == "url"
        assert location == "https://example.com/config.toml"
    
    def test_http_url(self):
        ref_type, location = parse_extends_url("http://example.com/config.toml")
        assert ref_type == "url"
        assert location == "http://example.com/config.toml"
    
    def test_local_relative(self):
        ref_type, location = parse_extends_url("./team/config.toml")
        assert ref_type == "local"
        assert location == "./team/config.toml"
    
    def test_local_absolute(self):
        ref_type, location = parse_extends_url("/etc/coderev/config.toml")
        assert ref_type == "local"
        assert location == "/etc/coderev/config.toml"


class TestResolveGitHubUrl:
    """Tests for resolve_github_url."""
    
    def test_basic_ref(self):
        url = resolve_github_url("myorg/repo/configs/coderev.toml")
        assert url == "https://raw.githubusercontent.com/myorg/repo/main/configs/coderev.toml"
    
    def test_with_branch(self):
        url = resolve_github_url("myorg/repo/configs/coderev.toml@develop")
        assert url == "https://raw.githubusercontent.com/myorg/repo/develop/configs/coderev.toml"
    
    def test_nested_path(self):
        url = resolve_github_url("myorg/repo/configs/team/strict.toml")
        assert url == "https://raw.githubusercontent.com/myorg/repo/main/configs/team/strict.toml"
    
    def test_invalid_ref_missing_parts(self):
        with pytest.raises(TeamConfigError) as exc_info:
            resolve_github_url("myorg/repo")
        assert "Invalid GitHub reference" in str(exc_info.value)


class TestDeepMerge:
    """Tests for deep_merge."""
    
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}
    
    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 20, "z": 30}}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3}
    
    def test_list_replacement(self):
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        result = deep_merge(base, override)
        assert result == {"items": [4, 5]}
    
    def test_base_unchanged(self):
        base = {"a": 1}
        override = {"b": 2}
        deep_merge(base, override)
        assert base == {"a": 1}  # Original unchanged
    
    def test_deeply_nested(self):
        base = {"a": {"b": {"c": {"d": 1}}}}
        override = {"a": {"b": {"c": {"e": 2}}}}
        result = deep_merge(base, override)
        assert result == {"a": {"b": {"c": {"d": 1, "e": 2}}}}


class TestLoadLocalConfig:
    """Tests for load_local_config."""
    
    def test_load_valid_config(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('[coderev]\nmodel = "gpt-4"\n')
        
        result = load_local_config(str(config_file))
        assert result == {"coderev": {"model": "gpt-4"}}
    
    def test_relative_path_with_base(self, tmp_path):
        config_file = tmp_path / "configs" / "team.toml"
        config_file.parent.mkdir()
        config_file.write_text('[coderev]\nfocus = ["bugs"]\n')
        
        result = load_local_config("configs/team.toml", base_path=tmp_path)
        assert result == {"coderev": {"focus": ["bugs"]}}
    
    def test_file_not_found(self):
        with pytest.raises(TeamConfigError) as exc_info:
            load_local_config("/nonexistent/path/config.toml")
        assert "not found" in str(exc_info.value)


class TestResolveExtends:
    """Tests for resolve_extends."""
    
    def test_no_extends(self):
        config = {"coderev": {"model": "gpt-4"}}
        result = resolve_extends(config)
        assert result == {"coderev": {"model": "gpt-4"}}
    
    def test_local_extends(self, tmp_path):
        # Create parent config
        parent = tmp_path / "parent.toml"
        parent.write_text("""
[coderev]
model = "claude-3-sonnet"
focus = ["bugs", "security"]
max_file_size = 50000
""")
        
        # Child config that extends parent
        child_config = {
            "coderev": {
                "extends": str(parent),
                "focus": ["bugs"],  # Override
            }
        }
        
        result = resolve_extends(child_config, base_path=tmp_path)
        coderev = result.get("coderev", result)
        
        assert coderev["model"] == "claude-3-sonnet"  # From parent
        assert coderev["focus"] == ["bugs"]  # Overridden
        assert coderev["max_file_size"] == 50000  # From parent
    
    def test_extends_list(self, tmp_path):
        # Create two parent configs
        parent1 = tmp_path / "parent1.toml"
        parent1.write_text('[coderev]\nmodel = "model1"\nfocus = ["bugs"]\n')
        
        parent2 = tmp_path / "parent2.toml"
        parent2.write_text('[coderev]\nmax_file_size = 100000\nfocus = ["security"]\n')
        
        # Child extends both
        child_config = {
            "coderev": {
                "extends": [str(parent1), str(parent2)],
                "language_hints": True,
            }
        }
        
        result = resolve_extends(child_config, base_path=tmp_path)
        coderev = result.get("coderev", result)
        
        assert coderev["model"] == "model1"  # From parent1
        assert coderev["max_file_size"] == 100000  # From parent2
        assert coderev["focus"] == ["security"]  # parent2 overrides parent1
        assert coderev["language_hints"] is True  # From child
    
    def test_circular_extends_detection(self, tmp_path):
        # Create circular reference
        config_a = tmp_path / "a.toml"
        config_b = tmp_path / "b.toml"
        
        # Use forward slashes for TOML compatibility on Windows
        config_a.write_text(f'[coderev]\nextends = "{config_b.as_posix()}"\n')
        config_b.write_text(f'[coderev]\nextends = "{config_a.as_posix()}"\n')
        
        config = {"coderev": {"extends": str(config_a)}}
        
        with pytest.raises(TeamConfigError) as exc_info:
            resolve_extends(config, base_path=tmp_path)
        assert "Circular" in str(exc_info.value)
    
    def test_recursive_extends(self, tmp_path):
        # Grandparent -> Parent -> Child
        grandparent = tmp_path / "grandparent.toml"
        grandparent.write_text('[coderev]\nmodel = "base-model"\n')
        
        parent = tmp_path / "parent.toml"
        # Use forward slashes for TOML compatibility on Windows
        parent.write_text(f'[coderev]\nextends = "{grandparent.as_posix()}"\nfocus = ["bugs"]\n')
        
        child_config = {
            "coderev": {
                "extends": str(parent),
                "max_file_size": 200000,
            }
        }
        
        result = resolve_extends(child_config, base_path=tmp_path)
        coderev = result.get("coderev", result)
        
        assert coderev["model"] == "base-model"  # From grandparent
        assert coderev["focus"] == ["bugs"]  # From parent
        assert coderev["max_file_size"] == 200000  # From child


class TestCaching:
    """Tests for config caching."""
    
    def test_cache_path_generation(self):
        url1 = "https://example.com/config.toml"
        url2 = "https://example.com/config.toml"
        url3 = "https://other.com/config.toml"
        
        path1 = get_cache_path(url1)
        path2 = get_cache_path(url2)
        path3 = get_cache_path(url3)
        
        assert path1 == path2  # Same URL, same path
        assert path1 != path3  # Different URL, different path
    
    def test_cache_and_retrieve(self, tmp_path):
        # Temporarily override cache dir
        import coderev.team as team_module
        original_cache_dir = team_module.CACHE_DIR
        team_module.CACHE_DIR = tmp_path / "cache"
        
        try:
            url = "https://example.com/test-config.toml"
            config_data = {"coderev": {"model": "cached-model"}}
            
            cache_remote_config(url, config_data)
            
            # Check file was created
            cached = list_cached_configs()
            assert len(cached) == 1
            
            # Clean up
            count = clear_config_cache()
            assert count == 1
            assert list_cached_configs() == []
        finally:
            team_module.CACHE_DIR = original_cache_dir


class TestCreateTeamConfig:
    """Tests for create_team_config_template."""
    
    def test_creates_valid_toml(self, tmp_path):
        output = tmp_path / "team.toml"
        create_team_config_template(output)
        
        assert output.exists()
        
        # Should be valid TOML
        content = toml.load(output)
        assert "coderev" in content
        assert "model" in content["coderev"]
        assert "focus" in content["coderev"]
        assert "ignore_patterns" in content["coderev"]


class TestConfigIntegration:
    """Integration tests for Config with team extends."""
    
    def test_config_load_with_extends(self, tmp_path, monkeypatch):
        from coderev.config import Config
        
        # Create team config
        team_config = tmp_path / "team.toml"
        team_config.write_text("""
[coderev]
model = "team-model"
focus = ["bugs", "security", "performance"]
ignore_patterns = ["*.test.py", "vendor/*"]
""")
        
        # Create local config that extends team
        # Use forward slashes for TOML compatibility on Windows
        local_config = tmp_path / ".coderev.toml"
        local_config.write_text(f"""
[coderev]
extends = "{team_config.as_posix()}"
focus = ["bugs"]
""")
        
        # Change to temp dir
        monkeypatch.chdir(tmp_path)
        
        # Load config
        config = Config.load()
        
        assert config.model == "team-model"  # From team
        assert config.focus == ["bugs"]  # Overridden locally
        assert "*.test.py" in config.ignore_patterns  # From team
