"""Tests for the pre-commit hook module."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.precommit import main, filter_reviewable_files


@pytest.fixture
def runner():
    """Create a CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_config():
    """Create a mock Config object."""
    config = MagicMock()
    config.model = "claude-3-sonnet"
    config.api_key = "test-key"
    config.ignore_patterns = ["*.test.py", "*.spec.ts"]
    config.max_file_size = 100000
    config.validate.return_value = []
    return config


@pytest.fixture
def temp_files(tmp_path):
    """Create temporary test files."""
    # Create test Python file (using 'main_' prefix to avoid being filtered)
    py_file = tmp_path / "main_code.py"
    py_file.write_text("def hello():\n    print('world')\n")
    
    # Create a test file that should be ignored (ends with .test.py)
    test_file = tmp_path / "ignored.test.py"
    test_file.write_text("# test file\n")
    
    # Create a large file
    large_file = tmp_path / "large_file.py"
    large_file.write_text("x" * 200000)  # 200KB
    
    return {
        "py_file": py_file,
        "test_file": test_file,
        "large_file": large_file,
    }


class TestFilterReviewableFiles:
    """Tests for filter_reviewable_files function."""
    
    def test_filters_nonexistent_files(self, mock_config, tmp_path):
        """Should skip files that don't exist."""
        files = [str(tmp_path / "nonexistent.py")]
        result = filter_reviewable_files(files, mock_config)
        assert result == []
    
    def test_filters_directories(self, mock_config, tmp_path):
        """Should skip directories."""
        files = [str(tmp_path)]
        result = filter_reviewable_files(files, mock_config)
        assert result == []
    
    def test_filters_by_ignore_patterns(self, mock_config, temp_files):
        """Should skip files matching ignore patterns."""
        files = [str(temp_files["py_file"]), str(temp_files["test_file"])]
        result = filter_reviewable_files(files, mock_config)
        
        assert len(result) == 1
        assert result[0].name == "main_code.py"
    
    def test_filters_large_files(self, mock_config, temp_files):
        """Should skip files exceeding max_file_size."""
        files = [str(temp_files["py_file"]), str(temp_files["large_file"])]
        result = filter_reviewable_files(files, mock_config)
        
        assert len(result) == 1
        assert result[0].name == "main_code.py"
    
    def test_returns_valid_files(self, mock_config, temp_files):
        """Should return valid files as Path objects."""
        files = [str(temp_files["py_file"])]
        result = filter_reviewable_files(files, mock_config)
        
        assert len(result) == 1
        assert isinstance(result[0], Path)
        assert result[0].name == "main_code.py"


class TestPrecommitCLI:
    """Tests for the pre-commit CLI command."""
    
    def test_no_files_exits_cleanly(self, runner, mock_config):
        """Should exit with code 0 when no files to review."""
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            result = runner.invoke(main, [])
            assert result.exit_code == 0
            assert "No files to review" in result.output or result.output == ""
    
    def test_config_error_exits_with_error(self, runner):
        """Should exit with code 1 on config errors."""
        mock_config = MagicMock()
        mock_config.validate.return_value = ["API key is required"]
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            result = runner.invoke(main, ["some_file.py"])
            assert result.exit_code == 1
            assert "Config error" in result.output
    
    def test_estimate_flag_shows_cost(self, runner, mock_config, temp_files):
        """Should show cost estimate when --estimate is passed."""
        mock_estimate = MagicMock()
        mock_estimate.file_count = 1
        mock_estimate.total_tokens = 1000
        mock_estimate.format_cost.return_value = "$0.0010"
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("coderev.cost.CostEstimator") as mock_estimator:
                mock_estimator.return_value.estimate_files.return_value = mock_estimate
                
                result = runner.invoke(main, [
                    str(temp_files["py_file"]),
                    "--estimate",
                ])
                
                assert result.exit_code == 0
                assert "Cost Estimate" in result.output
    
    def test_max_files_limit(self, runner, mock_config, tmp_path):
        """Should respect max_files limit."""
        # Create multiple files
        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"# file {i}")
            files.append(str(f))
        
        mock_result = MagicMock()
        mock_result.issues = []
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("coderev.precommit.CodeReviewer") as mock_reviewer:
                mock_reviewer.return_value.review_file.return_value = mock_result
                
                result = runner.invoke(main, files + ["--max-files", "2"])
                
                # Should only review 2 files
                assert mock_reviewer.return_value.review_file.call_count == 2
    
    def test_fail_on_severity(self, runner, mock_config, temp_files):
        """Should exit with error when issues exceed fail-on threshold."""
        from coderev.reviewer import Severity
        
        mock_issue = MagicMock()
        mock_issue.severity = MagicMock()
        mock_issue.severity.value = "high"  # Must be a string, not Severity enum
        
        mock_result = MagicMock()
        mock_result.issues = [mock_issue]
        mock_result.summary = "Found issues"
        mock_result.score = 50
        mock_result.positive = []
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("coderev.precommit.CodeReviewer") as mock_reviewer:
                with patch("coderev.precommit.RichFormatter"):  # Mock the formatter to avoid rendering issues
                    mock_reviewer.return_value.review_file.return_value = mock_result
                    
                    result = runner.invoke(main, [
                        str(temp_files["py_file"]),
                        "--fail-on", "high",
                    ])
                    
                    assert result.exit_code == 1
                    assert "Failing commit" in result.output
    
    def test_no_issues_passes(self, runner, mock_config, temp_files):
        """Should pass when no issues found."""
        mock_result = MagicMock()
        mock_result.issues = []
        mock_result.summary = "Code looks good"
        mock_result.score = 100
        mock_result.positive = []
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("coderev.precommit.CodeReviewer") as mock_reviewer:
                mock_reviewer.return_value.review_file.return_value = mock_result
                
                result = runner.invoke(main, [str(temp_files["py_file"])])
                
                assert result.exit_code == 0
    
    def test_quiet_mode_minimal_output(self, runner, mock_config, temp_files):
        """Should suppress progress messages in quiet mode."""
        mock_result = MagicMock()
        mock_result.issues = []
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("coderev.precommit.CodeReviewer") as mock_reviewer:
                mock_reviewer.return_value.review_file.return_value = mock_result
                
                result = runner.invoke(main, [
                    str(temp_files["py_file"]),
                    "--quiet",
                ])
                
                assert "Reviewing" not in result.output
    
    def test_focus_areas_passed_to_reviewer(self, runner, mock_config, temp_files):
        """Should pass focus areas to the reviewer."""
        mock_result = MagicMock()
        mock_result.issues = []
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("coderev.precommit.CodeReviewer") as mock_reviewer:
                mock_reviewer.return_value.review_file.return_value = mock_result
                
                result = runner.invoke(main, [
                    str(temp_files["py_file"]),
                    "--focus", "security",
                    "--focus", "bugs",
                ])
                
                # Check focus was passed correctly
                mock_reviewer.return_value.review_file.assert_called_once()
                call_kwargs = mock_reviewer.return_value.review_file.call_args
                assert call_kwargs[1]["focus"] == ["security", "bugs"]


class TestStagedMode:
    """Tests for staged/diff mode."""
    
    def test_staged_no_changes(self, runner, mock_config):
        """Should exit cleanly when no staged changes."""
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = ""
                
                result = runner.invoke(main, ["--staged"])
                
                assert result.exit_code == 0
                assert "No staged changes" in result.output
    
    def test_staged_with_changes(self, runner, mock_config):
        """Should review staged changes."""
        mock_diff = """diff --git a/test.py b/test.py
--- a/test.py
+++ b/test.py
@@ -1 +1 @@
-old code
+new code"""
        
        mock_result = MagicMock()
        mock_result.issues = []
        mock_result.summary = "Looks good"
        mock_result.score = 100
        mock_result.positive = []
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = mock_diff
                
                with patch("coderev.precommit.CodeReviewer") as mock_reviewer:
                    mock_reviewer.return_value.review_diff.return_value = mock_result
                    
                    result = runner.invoke(main, ["--staged"])
                    
                    assert result.exit_code == 0
                    mock_reviewer.return_value.review_diff.assert_called_once()
    
    def test_staged_estimate(self, runner, mock_config):
        """Should show cost estimate for staged changes."""
        mock_diff = "diff content here"
        
        mock_estimate = MagicMock()
        mock_estimate.total_tokens = 500
        mock_estimate.format_cost.return_value = "$0.0005"
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = mock_diff
                
                with patch("coderev.cost.CostEstimator") as mock_estimator:
                    mock_estimator.return_value.estimate_diff.return_value = mock_estimate
                    
                    result = runner.invoke(main, ["--staged", "--estimate"])
                    
                    assert result.exit_code == 0
                    assert "Cost Estimate" in result.output


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_rate_limit_error(self, runner, mock_config, temp_files):
        """Should handle rate limit errors gracefully."""
        from coderev.reviewer import RateLimitError
        
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("coderev.precommit.CodeReviewer") as mock_reviewer:
                mock_reviewer.return_value.review_file.side_effect = RateLimitError(
                    "Rate limit exceeded"
                )
                
                result = runner.invoke(main, [str(temp_files["py_file"])])
                
                assert result.exit_code == 2
                assert "Rate Limit" in result.output
    
    def test_generic_error(self, runner, mock_config, temp_files):
        """Should handle generic errors gracefully."""
        with patch("coderev.precommit.Config.load", return_value=mock_config):
            with patch("coderev.precommit.CodeReviewer") as mock_reviewer:
                mock_reviewer.return_value.review_file.side_effect = Exception(
                    "Something went wrong"
                )
                
                result = runner.invoke(main, [str(temp_files["py_file"])])
                
                # Should continue to next file, not crash
                assert "Error reviewing" in result.output
