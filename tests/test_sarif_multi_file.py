"""Multi-file `coderev review --format sarif` must emit one valid SARIF log.

Both the parallel and the sequential review paths joined one complete SARIF
document per file with blank lines. That is not valid JSON, and GitHub code
scanning rejects the upload. All files' results now go into a single run,
each result carrying its own file location.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.cli import main
from coderev.output import MarkdownFormatter, SarifFormatter
from coderev.reviewer import Category, Issue, ReviewResult, Severity


def _issue(
    message: str, file: str | None, line: int | None = 3, category: Category = Category.BUG
) -> Issue:
    return Issue(message=message, severity=Severity.HIGH, category=category, line=line, file=file)


def _uris(run: dict) -> list[str]:
    return [
        r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in run["results"]
    ]


# --- SarifFormatter.format_multiple ------------------------------------------


def test_format_multiple_is_one_valid_log_with_one_run():
    results = {
        "a.py": ReviewResult(summary="a", issues=[_issue("bug in a", "a.py")], score=70),
        "b.py": ReviewResult(summary="b", issues=[_issue("bug in b", "b.py")], score=70),
    }

    data = json.loads(SarifFormatter().format_multiple(results))

    assert data["version"] == "2.1.0"
    assert len(data["runs"]) == 1
    run = data["runs"][0]
    assert [r["message"]["text"] for r in run["results"]] == ["bug in a", "bug in b"]
    assert _uris(run) == ["a.py", "b.py"]


def test_format_multiple_dedupes_rules_across_files():
    results = {
        "a.py": ReviewResult(summary="a", issues=[_issue("x", "a.py", category=Category.SECURITY)]),
        "b.py": ReviewResult(
            summary="b",
            issues=[
                _issue("y", "b.py", category=Category.SECURITY),
                _issue("z", "b.py", category=Category.STYLE),
            ],
        ),
    }

    run = json.loads(SarifFormatter().format_multiple(results))["runs"][0]

    rule_ids = [rule["id"] for rule in run["tool"]["driver"]["rules"]]
    assert rule_ids == ["coderev/security", "coderev/style"]


def test_issue_without_file_uses_the_reviewed_path():
    results = {"pkg/mod.py": ReviewResult(summary="m", issues=[_issue("no file set", None)])}

    run = json.loads(SarifFormatter().format_multiple(results))["runs"][0]

    assert _uris(run) == ["pkg/mod.py"]


def test_issue_without_line_still_has_a_file_location():
    results = {"a.py": ReviewResult(summary="a", issues=[_issue("file-level", "a.py", line=None)])}

    run = json.loads(SarifFormatter().format_multiple(results))["runs"][0]

    location = run["results"][0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "a.py"
    assert "region" not in location


def test_windows_paths_become_valid_uris():
    results = {
        "src\\pkg\\a.py": ReviewResult(summary="a", issues=[_issue("rel", "src\\pkg\\a.py")]),
        "C:\\work\\b.py": ReviewResult(summary="b", issues=[_issue("abs", "C:\\work\\b.py")]),
    }

    run = json.loads(SarifFormatter().format_multiple(results))["runs"][0]

    assert _uris(run) == ["src/pkg/a.py", "file:///C:/work/b.py"]


def test_errored_file_is_reported_as_a_failed_invocation():
    results = {
        "ok.py": ReviewResult(summary="fine", issues=[], score=90),
        "bad.py": ReviewResult(summary="Error reviewing file: boom", score=0, error="boom"),
    }

    run = json.loads(SarifFormatter().format_multiple(results))["runs"][0]

    assert run["results"] == []
    invocation = run["invocations"][0]
    assert invocation["executionSuccessful"] is False
    [note] = invocation["toolExecutionNotifications"]
    assert note["level"] == "error"
    assert "boom" in note["message"]["text"]
    assert note["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "bad.py"


def test_clean_run_is_a_successful_invocation():
    results = {"ok.py": ReviewResult(summary="fine", issues=[], score=90)}

    run = json.loads(SarifFormatter().format_multiple(results))["runs"][0]

    assert run["invocations"] == [{"executionSuccessful": True}]


def test_empty_results_is_still_a_valid_log():
    data = json.loads(SarifFormatter().format_multiple({}))

    assert data["runs"][0]["results"] == []


def test_single_format_accepts_a_file_path():
    result = ReviewResult(summary="a", issues=[_issue("no file set", None)])

    run = json.loads(SarifFormatter().format(result, file_path="a.py"))["runs"][0]

    assert _uris(run) == ["a.py"]


def test_markdown_format_multiple_keeps_joining_reports():
    results = {
        "a.py": ReviewResult(summary="first", score=80),
        "b.py": ReviewResult(summary="second", score=80),
    }
    formatter = MarkdownFormatter()

    output = formatter.format_multiple(results)

    assert output == formatter.format(results["a.py"]) + "\n\n" + formatter.format(results["b.py"])


# --- coderev review --format sarif -------------------------------------------


def _reviewed(files) -> dict[str, ReviewResult]:
    return {
        str(f): ReviewResult(summary=str(f), issues=[_issue(f"issue in {f}", str(f))], score=70)
        for f in files
    }


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


def _write(*names: str) -> None:
    for name in names:
        Path(name).write_text("x = 1\n", encoding="utf-8")


def test_review_parallel_sarif_is_one_log(runner, tmp_path):
    instance = MagicMock()
    instance.__aenter__.return_value = instance

    async def review_files_async(files, focus=None):
        return _reviewed(files)

    instance.review_files_async = AsyncMock(side_effect=review_files_async)
    with (
        patch("coderev.async_reviewer.AsyncCodeReviewer", MagicMock(return_value=instance)),
        runner.isolated_filesystem(temp_dir=tmp_path),
    ):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--format", "sarif"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert len(data["runs"]) == 1
    assert sorted(_uris(data["runs"][0])) == ["a.py", "b.py"]


def test_review_sequential_sarif_is_one_log(runner, tmp_path):
    with patch("coderev.cli.CodeReviewer") as reviewer_cls:
        reviewer_cls.return_value.review_files.side_effect = lambda files, focus=None: _reviewed(
            files
        )
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _write("a.py", "b.py")
            result = runner.invoke(
                main, ["review", "a.py", "b.py", "--no-parallel", "--format", "sarif"]
            )

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert len(data["runs"]) == 1
    assert sorted(_uris(data["runs"][0])) == ["a.py", "b.py"]


# --- suggestions -------------------------------------------------------------


def test_suggestion_is_not_emitted_as_a_fix_without_artifact_changes():
    """A SARIF fix requires `artifactChanges`; schema validation rejects a description-only fix."""
    issue = _issue("SQL injection", "db.py")
    issue.suggestion = "Use parameterized queries"
    results = {"db.py": ReviewResult(summary="s", issues=[issue])}

    [result] = json.loads(SarifFormatter().format_multiple(results))["runs"][0]["results"]

    assert "fixes" not in result
    assert result["message"]["text"] == "SQL injection\n\nSuggestion: Use parameterized queries"
    assert result["properties"] == {"suggestion": "Use parameterized queries"}


def test_issue_without_suggestion_has_plain_message():
    results = {"a.py": ReviewResult(summary="a", issues=[_issue("plain", "a.py")])}

    [result] = json.loads(SarifFormatter().format_multiple(results))["runs"][0]["results"]

    assert result["message"]["text"] == "plain"
    assert "properties" not in result
