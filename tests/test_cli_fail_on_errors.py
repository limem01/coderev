"""`--fail-on` must fail closed when a file's review errored.

A review that errors out (bad API key, provider outage, rate limit) leaves a
placeholder result with no issues. The `--fail-on` gates in `coderev review`
and `coderev batch` only looked for issues at or above the threshold, so a CI
run where *every* review failed exited 0 -- a green check for code nobody
reviewed. The single-file rich path was worse: it printed the error and
dropped the file from the results entirely.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.cli import main
from coderev.reviewer import BinaryFileError, Category, Issue, ReviewResult, Severity


def _clean(summary: str = "ok") -> ReviewResult:
    return ReviewResult(summary=summary, issues=[], score=90)


def _errored(message: str = "401 invalid x-api-key") -> ReviewResult:
    return ReviewResult(
        summary=f"Error reviewing file: {message}", issues=[], score=0, error=message
    )


def _with_issue(severity: Severity) -> ReviewResult:
    return ReviewResult(
        summary="issues",
        issues=[Issue(message="m", severity=severity, category=Category.BUG, line=1)],
        score=60,
    )


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def mock_config():
    with patch("coderev.cli.Config") as config_cls:
        config = MagicMock()
        config.validate.return_value = []
        config_cls.load.return_value = config
        yield config


def _patch_async_reviewer(results_for):
    """Patch AsyncCodeReviewer so review_files_async maps files via ``results_for``."""
    instance = MagicMock()
    instance.__aenter__.return_value = instance

    async def review_files_async(files, focus=None):
        return {str(f): results_for(str(f)) for f in files}

    instance.review_files_async = AsyncMock(side_effect=review_files_async)
    return patch("coderev.async_reviewer.AsyncCodeReviewer", MagicMock(return_value=instance))


def _write(*names: str) -> None:
    for name in names:
        Path(name).write_text("x = 1\n", encoding="utf-8")


# --- coderev review: parallel path -------------------------------------------


def test_parallel_review_fails_gate_when_every_file_errored(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(lambda _: _errored()):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--fail-on", "high"])

    assert result.exit_code == 1
    assert "could not be reviewed" in result.stderr
    assert "a.py" in result.stderr and "b.py" in result.stderr


def test_parallel_review_fails_gate_when_one_file_errored(runner, tmp_path):
    results = {"a.py": _clean(), "b.py": _errored()}
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(results.__getitem__):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--fail-on", "critical"])

    assert result.exit_code == 1
    assert "1 file(s) could not be reviewed" in result.stderr


def test_parallel_review_passes_gate_when_all_clean(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(lambda _: _clean()):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--fail-on", "low"])

    assert result.exit_code == 0, result.output


def test_parallel_review_skipped_files_do_not_fail_gate(runner, tmp_path):
    # Binary files are skipped on purpose (score -1, no error); not a failure.
    skipped = ReviewResult(summary="Skipped: binary", issues=[], score=-1)
    results = {"a.py": _clean(), "b.py": skipped}
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(results.__getitem__):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--fail-on", "low"])

    assert result.exit_code == 0, result.output


def test_parallel_review_still_fails_on_blocking_issues(runner, tmp_path):
    results = {"a.py": _clean(), "b.py": _with_issue(Severity.HIGH)}
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(results.__getitem__):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--fail-on", "high"])

    assert result.exit_code == 1
    assert "at or above 'high'" in result.stderr


def test_parallel_review_issue_below_threshold_passes(runner, tmp_path):
    results = {"a.py": _clean(), "b.py": _with_issue(Severity.MEDIUM)}
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(results.__getitem__):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--fail-on", "high"])

    assert result.exit_code == 0, result.output


# --- coderev review: sequential paths ----------------------------------------


@patch("coderev.cli.CodeReviewer")
def test_sequential_rich_review_fails_gate_when_review_raises(reviewer_cls, runner, tmp_path):
    # The rich path printed the error and dropped the file from `results`,
    # so the gate saw nothing at all and passed.
    reviewer_cls.return_value.review_file.side_effect = RuntimeError("connection reset")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(main, ["review", "a.py", "--fail-on", "high"])

    assert result.exit_code == 1
    assert "connection reset" in result.output
    assert "could not be reviewed" in result.stderr


@patch("coderev.cli.CodeReviewer")
def test_sequential_rich_review_binary_skip_does_not_fail_gate(reviewer_cls, runner, tmp_path):
    reviewer_cls.return_value.review_file.side_effect = BinaryFileError("a.py")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(main, ["review", "a.py", "--fail-on", "low"])

    assert result.exit_code == 0, result.output
    assert "Skipped" in result.output


@patch("coderev.cli.CodeReviewer")
def test_sequential_json_review_fails_gate_and_keeps_stdout_json(reviewer_cls, runner, tmp_path):
    reviewer_cls.return_value.review_files.return_value = {"a.py": _errored()}
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(
            main, ["review", "a.py", "--no-parallel", "--format", "json", "--fail-on", "high"]
        )

    assert result.exit_code == 1
    json.loads(result.stdout)  # gate message must not corrupt machine output
    assert "could not be reviewed" in result.stderr


# --- coderev batch -----------------------------------------------------------


def test_batch_fails_gate_when_file_errored(runner, tmp_path):
    results = {"a.py": _clean(), "b.py": _errored()}
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(results.__getitem__):
        _write("a.py", "b.py")
        result = runner.invoke(
            main, ["batch", "a.py", "b.py", "--format", "json", "--fail-on", "high"]
        )

    assert result.exit_code == 1
    assert "could not be reviewed" in result.stderr


def test_batch_json_stdout_stays_parseable_when_gate_trips_on_issues(runner, tmp_path):
    results = {"a.py": _clean(), "b.py": _with_issue(Severity.CRITICAL)}
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(results.__getitem__):
        _write("a.py", "b.py")
        result = runner.invoke(
            main, ["batch", "a.py", "b.py", "--format", "json", "--fail-on", "high"]
        )

    assert result.exit_code == 1
    # The FAIL line used to be printed to stdout right after the JSON report.
    # (Batch progress lines still precede it on stdout; that is separate.)
    assert "FAIL" not in result.stdout
    report = json.loads(result.stdout[result.stdout.index("{"):])
    assert report["summary"]["critical_issues"] == 1
    assert "at or above 'high'" in result.stderr


def test_batch_passes_gate_when_all_clean(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path), _patch_async_reviewer(lambda _: _clean()):
        _write("a.py", "b.py")
        result = runner.invoke(
            main, ["batch", "a.py", "b.py", "--format", "json", "--fail-on", "low"]
        )

    assert result.exit_code == 0, result.output
