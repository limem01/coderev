"""`--estimate` on `review` and `diff` must honour `--format`.

`coderev review . --estimate --format json` printed the rich cost panel to
stdout regardless of the format, while `coderev estimate --format json` already
emitted JSON. Now `--estimate --format json` emits the same schema as
`coderev estimate --format json`, and formats that cannot represent an estimate
(markdown, sarif) are rejected instead of getting the rich panel on stdout.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.cli import cost_estimate_to_dict, main
from coderev.cost import CostEstimate

MODEL = "claude-3-5-sonnet-20241022"

BASE_KEYS = {
    "model",
    "file_count",
    "skipped_files",
    "input_tokens",
    "estimated_output_tokens",
    "total_tokens",
    "input_cost_usd",
    "output_cost_usd",
    "total_cost_usd",
    "pricing_is_estimated",
    "batch_mode",
}

SAMPLE_DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
 x = 1
+y = 2
"""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def mock_config():
    with patch("coderev.cli.Config") as config_cls:
        config = MagicMock()
        config.validate.return_value = []
        config.model = MODEL
        config_cls.load.return_value = config
        yield config_cls


@pytest.fixture
def reviewers():
    """Fail loudly if an estimate run ever reaches a reviewer."""
    with (
        patch("coderev.cli.CodeReviewer") as sync_cls,
        patch("coderev.async_reviewer.AsyncCodeReviewer") as async_cls,
    ):
        yield sync_cls, async_cls


def _write(*names: str) -> None:
    for name in names:
        Path(name).write_text("def f():\n    return 1\n", encoding="utf-8")


# --- coderev review --estimate ----------------------------------------------


def test_review_estimate_json_stdout_is_pure_json(runner, tmp_path, reviewers):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--estimate", "--format", "json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert set(data) == BASE_KEYS
    assert data["model"] == MODEL
    assert data["file_count"] == 2
    assert data["total_tokens"] == data["input_tokens"] + data["estimated_output_tokens"]
    assert data["total_cost_usd"] > 0
    assert "Cost Estimate" not in result.stdout
    sync_cls, async_cls = reviewers
    sync_cls.assert_not_called()
    async_cls.assert_not_called()


def test_review_estimate_json_matches_estimate_command(runner, tmp_path, reviewers):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        via_review = runner.invoke(
            main, ["review", "a.py", "b.py", "--estimate", "--format", "json"]
        )
        via_estimate = runner.invoke(main, ["estimate", "a.py", "b.py", "--format", "json"])

    assert via_review.exit_code == 0, via_review.output
    assert via_estimate.exit_code == 0, via_estimate.output
    assert json.loads(via_review.stdout) == json.loads(via_estimate.stdout)


def test_review_estimate_json_status_lines_go_to_stderr(runner, tmp_path, reviewers):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(
            main, ["review", "a.py", "missing.py", "--estimate", "--format", "json"]
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["file_count"] == 1
    assert "missing.py does not exist" in result.stderr


def test_review_estimate_rich_still_prints_panel(runner, tmp_path, reviewers):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(main, ["review", "a.py", "--estimate"])

    assert result.exit_code == 0, result.output
    assert "Cost Estimate" in result.stdout
    assert "Total estimated cost" in result.stdout


@pytest.mark.parametrize("fmt", ["markdown", "sarif"])
def test_review_estimate_rejects_formats_without_an_estimate_view(runner, tmp_path, reviewers, fmt):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(main, ["review", "a.py", "--estimate", "--format", fmt])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--estimate supports --format rich or json" in result.stderr
    assert fmt in result.stderr


def test_review_without_estimate_still_accepts_sarif(runner, tmp_path):
    """The format check only applies to --estimate runs."""
    with patch("coderev.cli.CodeReviewer") as reviewer_cls:
        reviewer_cls.return_value.review_files.return_value = {}
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _write("a.py")
            result = runner.invoke(main, ["review", "a.py", "--format", "sarif"])

    assert result.exit_code == 0, result.output
    assert "--estimate supports" not in result.stderr


# --- coderev diff --estimate ------------------------------------------------


def test_diff_estimate_json_stdout_is_pure_json(runner, reviewers):
    with patch("coderev.cli.get_git_diff", return_value=SAMPLE_DIFF):
        result = runner.invoke(main, ["diff", "--estimate", "--format", "json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert set(data) == BASE_KEYS
    assert data["model"] == MODEL
    assert data["input_tokens"] > 0
    sync_cls, _ = reviewers
    sync_cls.assert_not_called()


def test_diff_estimate_rich_still_prints_panel(runner, reviewers):
    with patch("coderev.cli.get_git_diff", return_value=SAMPLE_DIFF):
        result = runner.invoke(main, ["diff", "--estimate"])

    assert result.exit_code == 0, result.output
    assert "Cost Estimate" in result.stdout


@pytest.mark.parametrize("fmt", ["markdown", "sarif"])
def test_diff_estimate_rejects_formats_without_an_estimate_view(runner, reviewers, fmt):
    with patch("coderev.cli.get_git_diff", return_value=SAMPLE_DIFF) as get_diff:
        result = runner.invoke(main, ["diff", "--estimate", "--format", fmt])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--estimate supports --format rich or json" in result.stderr
    get_diff.assert_not_called()


# --- cost_estimate_to_dict --------------------------------------------------


def _estimate(**overrides) -> CostEstimate:
    fields: dict[str, object] = {
        "input_tokens": 1000,
        "estimated_output_tokens": 300,
        "model": MODEL,
        "input_cost_usd": 0.003,
        "output_cost_usd": 0.0045,
        "total_cost_usd": 0.0075,
        "file_count": 2,
    }
    fields.update(overrides)
    return CostEstimate(**fields)


def test_to_dict_omits_optional_sections_by_default():
    data = cost_estimate_to_dict(_estimate())
    assert set(data) == BASE_KEYS
    assert data["total_tokens"] == 1300
    assert data["total_cost_usd"] == 0.0075


def test_to_dict_adds_budget_fields_when_max_cost_given():
    within = cost_estimate_to_dict(_estimate(), max_cost=0.0075)
    assert within["max_cost_usd"] == 0.0075
    assert within["over_budget"] is False  # budget is inclusive

    over = cost_estimate_to_dict(_estimate(), max_cost=0.001)
    assert over["over_budget"] is True


def test_to_dict_includes_per_file_breakdown():
    item = _estimate(
        input_tokens=600,
        estimated_output_tokens=180,
        total_cost_usd=0.1234567,
        file_count=1,
        path="a.py",
    )
    data = cost_estimate_to_dict(_estimate(file_breakdown=[item]))
    assert data["per_file"] == [
        {
            "path": "a.py",
            "input_tokens": 600,
            "estimated_output_tokens": 180,
            "total_cost_usd": 0.123457,
        }
    ]


def test_to_dict_rounds_costs_to_six_places():
    data = cost_estimate_to_dict(
        _estimate(input_cost_usd=0.1234564, output_cost_usd=0.0000004, total_cost_usd=1.9999996)
    )
    assert data["input_cost_usd"] == 0.123456
    assert data["output_cost_usd"] == 0.0
    assert data["total_cost_usd"] == 2.0
