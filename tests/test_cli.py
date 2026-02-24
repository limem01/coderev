"""Tests for CLI module."""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from pathlib import Path

from coderev.cli import main, collect_files


class TestCollectFiles:
    """Tests for file collection utility."""
    
    def test_collect_single_file(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")
        
        files = collect_files((str(test_file),))
        assert len(files) == 1
        assert files[0] == test_file
    
    def test_collect_directory_non_recursive(self, tmp_path):
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.py").write_text("pass")
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "c.py").write_text("pass")
        
        files = collect_files((str(tmp_path),), recursive=False)
        assert len(files) == 2  # Only top-level files
    
    def test_collect_directory_recursive(self, tmp_path):
        (tmp_path / "a.py").write_text("pass")
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "b.py").write_text("pass")
        
        files = collect_files((str(tmp_path),), recursive=True)
        assert len(files) == 2
    
    def test_collect_with_exclusions(self, tmp_path):
        (tmp_path / "main.py").write_text("pass")
        (tmp_path / "test_main.py").write_text("pass")
        (tmp_path / "main.test.py").write_text("pass")
        
        files = collect_files(
            (str(tmp_path),),
            exclude=("test_*.py", "*.test.py"),
        )
        assert len(files) == 1
        assert files[0].name == "main.py"


class TestCLI:
    """Tests for CLI commands."""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_version(self, runner):
        from coderev import __version__
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output
    
    def test_init_creates_config(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init"])
            assert result.exit_code == 0
            assert Path(".coderev.toml").exists()
    
    def test_init_confirms_overwrite(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".coderev.toml").write_text("existing")
            
            # Decline overwrite
            result = runner.invoke(main, ["init"], input="n\n")
            assert "already exists" in result.output
            assert Path(".coderev.toml").read_text() == "existing"
    
    @patch("coderev.cli.CodeReviewer")
    def test_review_missing_api_key(self, mock_reviewer, runner, tmp_path):
        mock_reviewer.side_effect = ValueError("API key required")
        
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("test.py").write_text("print('hello')")
            
            with patch.dict("os.environ", {}, clear=True):
                result = runner.invoke(main, ["review", "test.py"])
                assert result.exit_code == 1
    
    @patch("coderev.cli.CodeReviewer")
    @patch("coderev.cli.Config")
    def test_review_success(self, mock_config_cls, mock_reviewer_cls, runner, tmp_path):
        from coderev.reviewer import ReviewResult
        
        mock_config = MagicMock()
        mock_config.validate.return_value = []
        mock_config_cls.load.return_value = mock_config
        
        mock_reviewer = MagicMock()
        mock_reviewer.review_file.return_value = ReviewResult(
            summary="Clean code",
            issues=[],
            score=95,
            positive=["Well structured"],
        )
        mock_reviewer_cls.return_value = mock_reviewer
        
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("test.py").write_text("print('hello')")
            
            result = runner.invoke(main, ["review", "test.py"])
            assert result.exit_code == 0
    
    @patch("coderev.cli.get_git_diff")
    @patch("coderev.cli.CodeReviewer")
    @patch("coderev.cli.Config")
    def test_diff_no_changes(self, mock_config_cls, mock_reviewer_cls, mock_git_diff, runner):
        mock_config = MagicMock()
        mock_config.validate.return_value = []
        mock_config_cls.load.return_value = mock_config
        
        mock_git_diff.return_value = ""
        
        result = runner.invoke(main, ["diff"])
        assert "No changes to review" in result.output
    
    @patch("coderev.cli.get_git_diff")
    @patch("coderev.cli.CodeReviewer")
    @patch("coderev.cli.Config")
    def test_diff_with_changes(self, mock_config_cls, mock_reviewer_cls, mock_git_diff, runner):
        from coderev.reviewer import ReviewResult
        
        mock_config = MagicMock()
        mock_config.validate.return_value = []
        mock_config_cls.load.return_value = mock_config
        
        mock_git_diff.return_value = """
diff --git a/test.py b/test.py
index 123..456 789
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 def hello():
+    print("world")
     pass
"""
        
        mock_reviewer = MagicMock()
        mock_reviewer.review_diff.return_value = ReviewResult(
            summary="Minor changes",
            issues=[],
            score=90,
        )
        mock_reviewer_cls.return_value = mock_reviewer
        
        result = runner.invoke(main, ["diff"])
        assert result.exit_code == 0


class TestOutputFormats:
    """Tests for different output formats."""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    @patch("coderev.cli.CodeReviewer")
    @patch("coderev.cli.Config")
    def test_json_output(self, mock_config_cls, mock_reviewer_cls, runner, tmp_path):
        from coderev.reviewer import ReviewResult, Issue, Severity, Category
        
        mock_config = MagicMock()
        mock_config.validate.return_value = []
        mock_config_cls.load.return_value = mock_config
        
        mock_reviewer = MagicMock()
        mock_reviewer.review_files.return_value = {
            "test.py": ReviewResult(
                summary="Test",
                issues=[
                    Issue(
                        message="Test issue",
                        severity=Severity.HIGH,
                        category=Category.BUG,
                        line=10,
                    )
                ],
                score=70,
            )
        }
        mock_reviewer_cls.return_value = mock_reviewer
        
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("test.py").write_text("pass")
            
            result = runner.invoke(main, ["review", "test.py", "--format", "json"])
            assert result.exit_code == 0
            assert '"summary": "Test"' in result.output
            assert '"severity": "high"' in result.output
