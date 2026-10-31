"""Progress and status lines must not corrupt machine-readable stdout.

`coderev batch . --format json | jq` failed to parse: batch printed
"Batch Review - N files" and "Reviewing in parallel..." to stdout ahead of the
JSON report, and parallel `coderev review --format json` printed "Reviewing N
files in parallel...". For json/sarif/markdown/html, stdout belongs to the
report, so status lines go to stderr. Rich output keeps them on stdout.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev import cli
from coderev.cli import main, status_console
from coderev.reviewer import ReviewResult


def _clean(summary: str = "ok") -> ReviewResult:
    return ReviewResult(summary=summary, issues=[], score=90)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def mock_config():
    with patch("coderev.cli.Config") as config_cls:
        config = MagicMock()
        config.validate.return_value = []
        config_cls.load.return_value = config
        yield config_cls


@pytest.fixture
def async_reviewer():
    instance = MagicMock()
    instance.__aenter__.return_value = instance

    async def review_files_async(files, focus=None):
        return {str(f): _clean() for f in files}

    instance.review_files_async = AsyncMock(side_effect=review_files_async)
    with patch("coderev.async_reviewer.AsyncCodeReviewer", MagicMock(return_value=instance)):
        yield instance


@pytest.fixture
def sync_reviewer():
    with patch("coderev.cli.CodeReviewer") as reviewer_cls:
        reviewer_cls.return_value.review_files.side_effect = (
            lambda files, focus=None: {f: _clean() for f in files}
        )
        yield reviewer_cls


def _write(*names: str) -> None:
    for name in names:
        Path(name).write_text("x = 1\n", encoding="utf-8")


def test_status_console_routes_by_format():
    assert status_console("rich") is cli.console
    for fmt in ("json", "sarif", "markdown", "html"):
        assert status_console(fmt) is cli.err_console


# --- coderev batch -----------------------------------------------------------


def test_batch_parallel_json_stdout_is_pure_json(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["batch", "a.py", "b.py", "--format", "json"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)  # whole stdout, no slicing past progress lines
    assert report["summary"]["total_files"] == 2
    assert "Batch Review" in result.stderr
    assert "Reviewing in parallel" in result.stderr
    assert "Batch Review" not in result.stdout


def test_batch_sequential_json_stdout_is_pure_json(runner, tmp_path, sync_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(
            main, ["batch", "a.py", "b.py", "--no-parallel", "--format", "json"]
        )

    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert "Reviewing files sequentially" in result.stderr
    assert "sequentially" not in result.stdout


def test_batch_markdown_stdout_starts_with_report(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["batch", "a.py", "b.py", "--format", "markdown"])

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# Code Review Batch Report")
    assert "Reviewing in parallel" in result.stderr


def test_batch_output_file_keeps_stdout_empty(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(
            main, ["batch", "a.py", "b.py", "--format", "json", "-o", "report.json"]
        )
        saved = json.loads(Path("report.json").read_text())

    assert result.exit_code == 0, result.output
    assert saved["summary"]["total_files"] == 2
    assert result.stdout == ""
    assert "Report saved to report.json" in result.stderr


def test_batch_missing_path_warning_goes_to_stderr(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(
            main, ["batch", "a.py", "b.py", "missing.py", "--format", "json"]
        )

    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert "missing.py does not exist" in result.stderr


def test_batch_no_files_message_goes_to_stderr(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("empty").mkdir()
        result = runner.invoke(main, ["batch", "empty", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "No files to review" in result.stderr


def test_batch_error_goes_to_stderr_in_json_mode(runner, tmp_path, mock_config):
    mock_config.load.side_effect = RuntimeError("config exploded")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(main, ["batch", "a.py", "--format", "json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "config exploded" in result.stderr


def test_batch_rich_keeps_progress_on_stdout(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["batch", "a.py", "b.py"])

    assert result.exit_code == 0, result.output
    assert "Batch Review" in result.stdout
    assert "Reviewing in parallel" in result.stdout
    assert result.stderr == ""


# --- coderev review ----------------------------------------------------------


def test_review_parallel_json_stdout_is_pure_json(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert set(json.loads(result.stdout)) == {"a.py", "b.py"}
    assert "Reviewing 2 files in parallel" in result.stderr
    assert "in parallel" not in result.stdout


def test_review_missing_path_warning_goes_to_stderr(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(
            main, ["review", "a.py", "b.py", "missing.py", "--format", "json"]
        )

    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert "missing.py does not exist" in result.stderr


def test_review_error_goes_to_stderr_in_json_mode(runner, tmp_path, mock_config):
    mock_config.load.side_effect = RuntimeError("config exploded")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(main, ["review", "a.py", "--format", "json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "config exploded" in result.stderr


def test_review_rich_keeps_progress_on_stdout(runner, tmp_path, async_reviewer):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py"])

    assert result.exit_code == 0, result.output
    assert "Reviewing 2 files in parallel" in result.stdout
    assert result.stderr == ""
