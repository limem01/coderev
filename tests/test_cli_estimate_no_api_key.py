"""`review --estimate` and `diff --estimate` must work without an API key.

Estimating counts tokens locally and never calls the API, but both commands ran
`config.validate()` first, so with no `CODEREV_API_KEY`/`ANTHROPIC_API_KEY`/
`OPENAI_API_KEY` they exited 1 with "Config error: ... API key not configured".
`coderev estimate` already worked offline. Now the API-key check only applies
when a review will actually run; focus/provider validation still applies.

These tests use the real `Config.load()` (no mock) with every key unset.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from coderev.cli import main
from coderev.config import Config

API_KEY_VARS = ("CODEREV_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")

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
def no_api_keys(monkeypatch, tmp_path):
    """Unset every API key and keep a real ~/.coderev.toml out of the run."""
    for var in API_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


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


# --- Config.validate(require_api_key=...) -----------------------------------


def test_validate_reports_missing_key_by_default():
    errors = Config(api_key=None).validate()
    assert any("API key not configured" in e for e in errors)


def test_validate_skips_key_check_when_not_required():
    assert Config(api_key=None).validate(require_api_key=False) == []


def test_validate_skips_openai_key_check_when_not_required():
    config = Config(model="gpt-4o", openai_api_key=None)
    assert any("OpenAI API key" in e for e in config.validate())
    assert config.validate(require_api_key=False) == []


def test_validate_still_checks_focus_and_provider_without_key():
    config = Config(api_key=None, focus=["bugs", "vibes"], provider="mystery")
    errors = config.validate(require_api_key=False)
    assert not any("API key" in e for e in errors)
    assert any("Invalid focus areas" in e for e in errors)
    assert any("Invalid provider" in e for e in errors)


# --- coderev review --estimate ----------------------------------------------


@pytest.mark.parametrize("fmt", ["rich", "json"])
def test_review_estimate_runs_without_api_key(runner, tmp_path, reviewers, fmt):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py", "b.py")
        result = runner.invoke(main, ["review", "a.py", "b.py", "--estimate", "--format", fmt])

    assert result.exit_code == 0, result.output
    assert "API key not configured" not in result.output
    if fmt == "json":
        data = json.loads(result.stdout)
        assert data["file_count"] == 2
        assert data["total_cost_usd"] > 0
    else:
        assert "Total estimated cost" in result.stdout
    sync_cls, async_cls = reviewers
    sync_cls.assert_not_called()
    async_cls.assert_not_called()


def test_review_estimate_openai_model_runs_without_api_key(runner, tmp_path, reviewers):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".coderev.toml").write_text('[coderev]\nmodel = "gpt-4o"\n', encoding="utf-8")
        _write("a.py")
        result = runner.invoke(main, ["review", "a.py", "--estimate", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["model"] == "gpt-4o"


def test_review_without_estimate_still_requires_api_key(runner, tmp_path, reviewers):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write("a.py")
        result = runner.invoke(main, ["review", "a.py"])

    assert result.exit_code == 1
    assert "API key not configured" in result.output
    sync_cls, async_cls = reviewers
    sync_cls.assert_not_called()
    async_cls.assert_not_called()


def test_review_estimate_still_rejects_invalid_config(runner, tmp_path, reviewers):
    """Skipping the key check must not skip the rest of validation."""
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".coderev.toml").write_text('[coderev]\nprovider = "mystery"\n', encoding="utf-8")
        _write("a.py")
        result = runner.invoke(main, ["review", "a.py", "--estimate"])

    assert result.exit_code == 1
    assert "Invalid provider" in result.output
    assert "API key not configured" not in result.output


# --- coderev diff --estimate ------------------------------------------------


@pytest.mark.parametrize("fmt", ["rich", "json"])
def test_diff_estimate_runs_without_api_key(runner, tmp_path, reviewers, fmt):
    with (
        runner.isolated_filesystem(temp_dir=tmp_path),
        patch("coderev.cli.get_git_diff", return_value=SAMPLE_DIFF),
    ):
        result = runner.invoke(main, ["diff", "--estimate", "--format", fmt])

    assert result.exit_code == 0, result.output
    assert "API key not configured" not in result.output
    if fmt == "json":
        assert json.loads(result.stdout)["input_tokens"] > 0
    else:
        assert "Total estimated cost" in result.stdout
    sync_cls, _ = reviewers
    sync_cls.assert_not_called()


def test_diff_without_estimate_still_requires_api_key(runner, tmp_path, reviewers):
    with (
        runner.isolated_filesystem(temp_dir=tmp_path),
        patch("coderev.cli.get_git_diff", return_value=SAMPLE_DIFF) as get_diff,
    ):
        result = runner.invoke(main, ["diff"])

    assert result.exit_code == 1
    assert "API key not configured" in result.output
    get_diff.assert_not_called()
    sync_cls, _ = reviewers
    sync_cls.assert_not_called()
