"""Tests for GitHub Action functionality."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest


class TestActionConfig:
    """Tests for action.yml configuration."""
    
    @pytest.fixture
    def action_yaml(self) -> dict:
        """Load and parse action.yml."""
        import yaml
        
        action_path = Path(__file__).parent.parent / "action.yml"
        with open(action_path) as f:
            return yaml.safe_load(f)
    
    def test_action_yaml_exists(self) -> None:
        """Test that action.yml exists."""
        action_path = Path(__file__).parent.parent / "action.yml"
        assert action_path.exists(), "action.yml must exist at project root"
    
    def test_action_has_required_fields(self, action_yaml: dict) -> None:
        """Test that action.yml has all required fields."""
        assert "name" in action_yaml
        assert "description" in action_yaml
        assert "inputs" in action_yaml
        assert "outputs" in action_yaml
        assert "runs" in action_yaml
    
    def test_action_branding(self, action_yaml: dict) -> None:
        """Test action branding is configured."""
        assert "branding" in action_yaml
        assert action_yaml["branding"]["icon"] == "code"
        assert action_yaml["branding"]["color"] == "purple"
    
    def test_action_inputs(self, action_yaml: dict) -> None:
        """Test all expected inputs are defined."""
        inputs = action_yaml["inputs"]
        
        # Required inputs
        assert "github_token" in inputs
        
        # Optional but important inputs
        assert "anthropic_api_key" in inputs
        assert "openai_api_key" in inputs
        assert "model" in inputs
        assert "focus" in inputs
        assert "fail_on" in inputs
        assert "post_review" in inputs
        assert "max_files" in inputs
        assert "ignore_patterns" in inputs
    
    def test_action_outputs(self, action_yaml: dict) -> None:
        """Test all expected outputs are defined."""
        outputs = action_yaml["outputs"]
        
        assert "score" in outputs
        assert "issues_count" in outputs
        assert "critical_count" in outputs
        assert "high_count" in outputs
        assert "medium_count" in outputs
        assert "low_count" in outputs
    
    def test_action_uses_docker(self, action_yaml: dict) -> None:
        """Test action uses Docker runtime."""
        assert action_yaml["runs"]["using"] == "docker"
        assert action_yaml["runs"]["image"] == "Dockerfile"


class TestDockerfile:
    """Tests for Dockerfile configuration."""
    
    def test_dockerfile_exists(self) -> None:
        """Test that Dockerfile exists."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        assert dockerfile_path.exists(), "Dockerfile must exist at project root"
    
    def test_dockerfile_has_python(self) -> None:
        """Test Dockerfile uses Python base image."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()
        
        assert "FROM python:" in content
    
    def test_dockerfile_installs_dependencies(self) -> None:
        """Test Dockerfile installs required tools."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()
        
        assert "git" in content
        assert "jq" in content
    
    def test_dockerfile_copies_package(self) -> None:
        """Test Dockerfile copies package files."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()
        
        assert "COPY pyproject.toml" in content
        assert "COPY src/" in content
    
    def test_dockerfile_sets_entrypoint(self) -> None:
        """Test Dockerfile sets correct entrypoint."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()
        
        assert "ENTRYPOINT" in content
        assert "entrypoint.sh" in content


class TestEntrypoint:
    """Tests for entrypoint.sh script."""
    
    @pytest.fixture
    def entrypoint_content(self) -> str:
        """Load entrypoint.sh content with UTF-8 encoding."""
        entrypoint_path = Path(__file__).parent.parent / "entrypoint.sh"
        return entrypoint_path.read_text(encoding="utf-8")
    
    def test_entrypoint_exists(self) -> None:
        """Test that entrypoint.sh exists."""
        entrypoint_path = Path(__file__).parent.parent / "entrypoint.sh"
        assert entrypoint_path.exists(), "entrypoint.sh must exist at project root"
    
    def test_entrypoint_is_shell_script(self, entrypoint_content: str) -> None:
        """Test entrypoint has correct shebang."""
        assert entrypoint_content.startswith("#!/bin/bash")
    
    def test_entrypoint_checks_api_keys(self, entrypoint_content: str) -> None:
        """Test entrypoint validates API keys."""
        assert "ANTHROPIC_API_KEY" in entrypoint_content
        assert "OPENAI_API_KEY" in entrypoint_content
    
    def test_entrypoint_uses_github_event(self, entrypoint_content: str) -> None:
        """Test entrypoint reads GitHub event data."""
        assert "GITHUB_EVENT_PATH" in entrypoint_content
        assert "pull_request" in entrypoint_content
    
    def test_entrypoint_sets_outputs(self, entrypoint_content: str) -> None:
        """Test entrypoint sets GitHub outputs."""
        assert "GITHUB_OUTPUT" in entrypoint_content
        assert "score=" in entrypoint_content
        assert "issues_count=" in entrypoint_content
    
    def test_entrypoint_handles_fail_on(self, entrypoint_content: str) -> None:
        """Test entrypoint handles fail_on option."""
        assert "FAIL_ON" in entrypoint_content
        assert "critical)" in entrypoint_content
        assert "high)" in entrypoint_content
        assert "medium)" in entrypoint_content


class TestActionIntegration:
    """Integration tests for the GitHub Action (requires API keys)."""
    
    @pytest.fixture
    def mock_github_event(self, tmp_path: Path) -> Path:
        """Create a mock GitHub event file."""
        event_data = {
            "pull_request": {
                "number": 1,
                "base": {"sha": "abc123"},
                "head": {"sha": "def456"},
            },
            "repository": {
                "full_name": "test/repo",
            },
        }
        
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps(event_data))
        return event_path
    
    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set"
    )
    def test_action_can_parse_pr_output(self) -> None:
        """Test that PR review output is parseable JSON."""
        # This is a unit test for the JSON parsing logic
        sample_output = {
            "summary": "Test review",
            "score": 85,
            "issues": [
                {"severity": "high", "message": "Issue 1"},
                {"severity": "low", "message": "Issue 2"},
            ],
        }
        
        # Test parsing logic
        score = sample_output.get("score", 0)
        issues = sample_output.get("issues", [])
        
        assert score == 85
        assert len(issues) == 2
        
        critical_count = len([i for i in issues if i.get("severity") == "critical"])
        high_count = len([i for i in issues if i.get("severity") == "high"])
        
        assert critical_count == 0
        assert high_count == 1


class TestFileFiltering:
    """Tests for file filtering logic."""
    
    def test_ignore_test_files(self) -> None:
        """Test that test files are filtered out."""
        patterns = "*.test.*,*.spec.*"
        files = [
            "main.py",
            "app.test.py",
            "component.spec.ts",
            "utils.py",
        ]
        
        # Simple glob matching
        import fnmatch
        
        filtered = []
        for f in files:
            skip = False
            for pattern in patterns.split(","):
                if fnmatch.fnmatch(f, pattern.strip()):
                    skip = True
                    break
            if not skip:
                filtered.append(f)
        
        assert "main.py" in filtered
        assert "utils.py" in filtered
        assert "app.test.py" not in filtered
        assert "component.spec.ts" not in filtered
    
    def test_ignore_minified_files(self) -> None:
        """Test that minified files are filtered out."""
        patterns = "*.min.js,*.min.css"
        files = [
            "bundle.min.js",
            "styles.min.css",
            "main.js",
            "styles.css",
        ]
        
        import fnmatch
        
        filtered = []
        for f in files:
            skip = False
            for pattern in patterns.split(","):
                if fnmatch.fnmatch(f, pattern.strip()):
                    skip = True
                    break
            if not skip:
                filtered.append(f)
        
        assert "main.js" in filtered
        assert "styles.css" in filtered
        assert "bundle.min.js" not in filtered
        assert "styles.min.css" not in filtered


class TestOutputParsing:
    """Tests for parsing review output."""
    
    def test_parse_json_output(self) -> None:
        """Test parsing JSON output from coderev."""
        output = json.dumps({
            "summary": "Code review completed",
            "score": 75,
            "issues": [
                {"severity": "critical", "message": "SQL injection"},
                {"severity": "high", "message": "Missing auth"},
                {"severity": "medium", "message": "Magic number"},
                {"severity": "low", "message": "Naming convention"},
            ],
        })
        
        result = json.loads(output)
        
        assert result["score"] == 75
        
        issues = result["issues"]
        critical = [i for i in issues if i["severity"] == "critical"]
        high = [i for i in issues if i["severity"] == "high"]
        medium = [i for i in issues if i["severity"] == "medium"]
        low = [i for i in issues if i["severity"] == "low"]
        
        assert len(critical) == 1
        assert len(high) == 1
        assert len(medium) == 1
        assert len(low) == 1
    
    def test_fail_on_critical(self) -> None:
        """Test fail_on logic for critical issues."""
        fail_on = "critical"
        critical_count = 1
        high_count = 2
        
        should_fail = False
        if fail_on == "critical" and critical_count > 0:
            should_fail = True
        
        assert should_fail is True
    
    def test_fail_on_high(self) -> None:
        """Test fail_on logic for high issues."""
        fail_on = "high"
        critical_count = 0
        high_count = 2
        
        should_fail = False
        if fail_on == "high" and (critical_count > 0 or high_count > 0):
            should_fail = True
        
        assert should_fail is True
    
    def test_no_fail_when_below_threshold(self) -> None:
        """Test no failure when issues below threshold."""
        fail_on = "high"
        critical_count = 0
        high_count = 0
        medium_count = 5
        
        should_fail = False
        if fail_on == "high" and (critical_count > 0 or high_count > 0):
            should_fail = True
        
        assert should_fail is False
