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

    @patch("coderev.cli.CodeReviewer")
    @patch("coderev.cli.Config")
    def test_review_fail_on_does_not_rereview_in_sequential_mode(
        self, mock_config_cls, mock_reviewer_cls, runner, tmp_path
    ):
        """Regression test: --fail-on should not trigger duplicate API calls.

        Previously, sequential mode would call review_file once for printing
        and then again for fail-on checks.
        """
        from coderev.reviewer import ReviewResult, Issue, Severity, Category

        mock_config = MagicMock()
        mock_config.validate.return_value = []
        mock_config_cls.load.return_value = mock_config

        mock_reviewer = MagicMock()
        mock_reviewer.review_file.side_effect = [
            ReviewResult(
                summary="File 1",
                issues=[],
                score=90,
            ),
            ReviewResult(
                summary="File 2",
                issues=[
                    Issue(
                        message="Minor issue",
                        severity=Severity.LOW,
                        category=Category.STYLE,
                        line=1,
                    )
                ],
                score=80,
            ),
        ]
        mock_reviewer_cls.return_value = mock_reviewer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("a.py").write_text("pass")
            Path("b.py").write_text("pass")

            result = runner.invoke(
                main,
                ["review", "a.py", "b.py", "--no-parallel", "--fail-on", "low"],
            )
            assert result.exit_code == 1
            assert mock_reviewer.review_file.call_count == 2

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


class TestEstimateBudget:
    """Tests for the `estimate --max-cost` budget gate."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_within_budget_exits_zero(self, runner, tmp_path):
        import json as json_module
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("a.py").write_text("def f():\n    return 1\n")
            result = runner.invoke(
                main,
                ["estimate", "a.py", "--max-cost", "100", "--format", "json"],
            )
            assert result.exit_code == 0
            data = json_module.loads(result.output)
            assert data["over_budget"] is False
            assert data["max_cost_usd"] == 100.0

    def test_over_budget_exits_two(self, runner, tmp_path):
        import json as json_module
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("a.py").write_text("def f():\n    return 1\n")
            result = runner.invoke(
                main,
                ["estimate", "a.py", "--max-cost", "0", "--format", "json"],
            )
            assert result.exit_code == 2
            data = json_module.loads(result.output)
            assert data["over_budget"] is True

    def test_negative_budget_errors(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("a.py").write_text("pass\n")
            result = runner.invoke(main, ["estimate", "a.py", "--max-cost", "-1"])
            assert result.exit_code == 1
            assert "non-negative" in result.output

    def test_no_max_cost_omits_budget_fields(self, runner, tmp_path):
        import json as json_module
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("a.py").write_text("pass\n")
            result = runner.invoke(
                main, ["estimate", "a.py", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json_module.loads(result.output)
            assert "over_budget" not in data
            assert "max_cost_usd" not in data


class TestEstimatePerFile:
    """Tests for the `estimate --per-file` breakdown."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_per_file_json_lists_each_file(self, runner, tmp_path):
        import json as json_module
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("small.py").write_text("x = 1\n")
            Path("big.py").write_text("y = 2\n" * 300)
            result = runner.invoke(
                main,
                ["estimate", "small.py", "big.py", "--per-file", "--format", "json"],
            )
            assert result.exit_code == 0
            data = json_module.loads(result.output)
            assert "per_file" in data
            assert len(data["per_file"]) == 2
            paths = [item["path"] for item in data["per_file"]]
            assert "small.py" in paths and "big.py" in paths
            # Most expensive first.
            costs = [item["total_cost_usd"] for item in data["per_file"]]
            assert costs == sorted(costs, reverse=True)

    def test_no_per_file_omits_breakdown(self, runner, tmp_path):
        import json as json_module
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("a.py").write_text("pass\n")
            result = runner.invoke(
                main, ["estimate", "a.py", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json_module.loads(result.output)
            assert "per_file" not in data

    def test_per_file_rich_output_shows_files(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("alpha.py").write_text("def a(): pass\n")
            result = runner.invoke(main, ["estimate", "alpha.py", "--per-file"])
            assert result.exit_code == 0
            assert "Per-file breakdown" in result.output
            assert "alpha.py" in result.output
