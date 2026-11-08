"""`coderev batch` stops sending at the first rate limit, still reports, exits 2.

Batch had the same dead ``except RateLimitError`` (exit 2) as ``review`` had:
``review_files`` / ``review_files_async`` folded the error into an errored
result, so a rate-limited batch kept calling the provider for every remaining
file, reported them as errored and exited 0 (1 under ``--fail-on``, with no
retry hint).

Batch exists to produce a report, so it does not stop the way ``review`` does.
With ``skip_after_rate_limit=True`` the reviewers stop sending at the first
rate limit but still return a result for every file: completed reviews keep
their results, the rest are errored results with ``rate_limited`` set. The
command writes that report (the files show as errored) and exits 2 with the
provider's retry hint instead of running the ``--fail-on`` gate on a partial
set of files.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.async_reviewer import AsyncCodeReviewer
from coderev.cli import main
from coderev.reviewer import (
    UNSENT_AFTER_RATE_LIMIT,
    CodeReviewer,
    RateLimitError,
    ReviewResult,
    errored_result,
)

NAMES = ("a.py", "b.py", "c.py", "d.py", "e.py")


def _clean() -> ReviewResult:
    return ReviewResult(summary="ok", issues=[], score=90)


def _rate_limit() -> RateLimitError:
    return RateLimitError(provider="anthropic", retry_after=30)


def _write(directory: Path, *names: str) -> list[Path]:
    paths = []
    for name in names:
        path = directory / name
        path.write_text(f"{name.split('.')[0]} = 1\n", encoding="utf-8")
        paths.append(path)
    return paths


def _sync_reviewer(rate_limited: set[str]) -> CodeReviewer:
    def review_file(path, *args, **kwargs):
        if Path(path).name in rate_limited:
            raise _rate_limit()
        return _clean()

    reviewer = CodeReviewer.__new__(CodeReviewer)
    reviewer.review_file = MagicMock(side_effect=review_file)
    return reviewer


def _async_provider(rate_limited: set[str], sent: list[str]) -> MagicMock:
    """Provider whose call_async rate-limits prompts mentioning a listed file."""
    provider = MagicMock()

    async def call_async(system_prompt, user_prompt):
        name = next(n for n in NAMES if n in user_prompt)
        sent.append(name)
        if name in rate_limited:
            raise _rate_limit()
        await asyncio.sleep(0.01)
        return MagicMock(content="{}")

    provider.call_async = AsyncMock(side_effect=call_async)
    provider.parse_json_response.return_value = {"summary": "ok", "issues": [], "score": 90}
    return provider


# --- ReviewResult marker -----------------------------------------------------


def test_errored_result_marks_rate_limits_only():
    limited = errored_result(_rate_limit())
    assert limited.failed and limited.rate_limited
    assert "Retry after: 30 seconds" in limited.error

    other = errored_result(RuntimeError("401 invalid x-api-key"))
    assert other.failed and not other.rate_limited
    assert other.error == "401 invalid x-api-key"


def test_review_result_rate_limited_defaults_to_false():
    assert ReviewResult(summary="ok", score=80).rate_limited is False


# --- library: CodeReviewer.review_files --------------------------------------


def test_review_files_skip_after_rate_limit_stops_sending(tmp_path):
    a, b, c = _write(tmp_path, "a.py", "b.py", "c.py")
    reviewer = _sync_reviewer({"b.py"})

    results = reviewer.review_files([a, b, c], skip_after_rate_limit=True)

    reviewed = [call.args[0].name for call in reviewer.review_file.call_args_list]
    assert reviewed == ["a.py", "b.py"]  # c.py never sent
    assert list(results) == [str(a), str(b), str(c)]
    assert not results[str(a)].failed
    assert results[str(b)].rate_limited
    assert "Retry after: 30 seconds" in results[str(b)].error
    assert results[str(c)].rate_limited
    assert results[str(c)].error == UNSENT_AFTER_RATE_LIMIT


def test_review_files_default_marks_rate_limit_but_keeps_going(tmp_path):
    a, b = _write(tmp_path, "a.py", "b.py")
    reviewer = _sync_reviewer({"a.py"})

    results = reviewer.review_files([a, b])

    assert results[str(a)].rate_limited
    assert not results[str(b)].failed
    assert reviewer.review_file.call_count == 2


def test_review_files_rejects_both_rate_limit_modes(tmp_path):
    reviewer = _sync_reviewer(set())
    with pytest.raises(ValueError):
        reviewer.review_files(
            _write(tmp_path, "a.py"), stop_on_rate_limit=True, skip_after_rate_limit=True
        )
    reviewer.review_file.assert_not_called()


# --- library: AsyncCodeReviewer.review_files_async ---------------------------


async def _review_async(files, rate_limited, sent, max_concurrent=1, **kwargs):
    with patch("coderev.async_reviewer.get_provider") as get_provider:
        get_provider.return_value = _async_provider(rate_limited, sent)
        async with AsyncCodeReviewer(
            api_key="test-key", max_concurrent=max_concurrent, cache_enabled=False
        ) as reviewer:
            results = await reviewer.review_files_async(files, **kwargs)
        # Give any review that escaped cancellation a chance to reach the provider.
        await asyncio.sleep(0.05)
    return results


@pytest.mark.asyncio
async def test_review_files_async_skip_after_rate_limit_returns_every_file(tmp_path):
    files = _write(tmp_path, *NAMES)
    sent: list[str] = []

    results = await _review_async(files, {"a.py"}, sent, skip_after_rate_limit=True)

    assert list(results) == [str(f) for f in files]
    assert all(r.failed and r.rate_limited for r in results.values())
    assert "Retry after: 30 seconds" in results[str(files[0])].error
    assert all(results[str(f)].error == UNSENT_AFTER_RATE_LIMIT for f in files[1:])
    # One slot: at most the review already handed the slot gets through.
    assert sent[0] == "a.py"
    assert len(sent) <= 2, sent


@pytest.mark.asyncio
async def test_review_files_async_skip_keeps_reviews_that_finished(tmp_path):
    files = _write(tmp_path, *NAMES)
    sent: list[str] = []

    results = await _review_async(files, {"c.py"}, sent, skip_after_rate_limit=True)

    a, b, c, d, e = (results[str(f)] for f in files)
    assert not a.failed and a.score == 90
    assert not b.failed and b.score == 90
    assert c.rate_limited and "Retry after: 30 seconds" in c.error
    assert d.error == UNSENT_AFTER_RATE_LIMIT and e.error == UNSENT_AFTER_RATE_LIMIT
    assert len(sent) <= 4, sent


@pytest.mark.asyncio
async def test_review_files_async_skip_without_rate_limit_is_a_normal_review(tmp_path):
    files = _write(tmp_path, "a.py", "b.py")
    sent: list[str] = []

    results = await _review_async(files, set(), sent, max_concurrent=2, skip_after_rate_limit=True)

    assert not any(r.failed for r in results.values())
    assert sorted(sent) == ["a.py", "b.py"]


@pytest.mark.asyncio
async def test_review_files_async_rejects_both_rate_limit_modes(tmp_path):
    sent: list[str] = []
    with pytest.raises(ValueError):
        await _review_async(
            _write(tmp_path, "a.py"),
            set(),
            sent,
            stop_on_rate_limit=True,
            skip_after_rate_limit=True,
        )
    assert sent == []


# --- CLI: coderev batch ------------------------------------------------------


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


@pytest.fixture
def real_async_reviewer():
    """Real AsyncCodeReviewer (one slot, no cache); the test fakes the provider."""
    real_init = AsyncCodeReviewer.__init__

    def init(self, *args, config=None, max_concurrent=5, **kwargs):
        real_init(self, api_key="test-key", max_concurrent=1, cache_enabled=False)

    with patch.object(AsyncCodeReviewer, "__init__", init):
        yield


def _assert_rate_limit_exit(result, stream: str) -> None:
    assert result.exit_code == 2, result.output
    assert "Rate Limit Exceeded" in stream
    assert "Retry after: 30 seconds" in stream
    assert "could not be reviewed" not in result.output  # the --fail-on gate did not run


def test_parallel_json_batch_reports_and_exits_2(runner, tmp_path, real_async_reviewer):
    sent: list[str] = []
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py", "b.py", "c.py", "d.py")
        with patch("coderev.async_reviewer.get_provider") as get_provider:
            get_provider.return_value = _async_provider({"b.py"}, sent)
            result = runner.invoke(
                main, ["batch", "a.py", "b.py", "c.py", "d.py", "--format", "json"]
            )

    _assert_rate_limit_exit(result, result.stderr)
    report = json.loads(result.stdout)  # the partial report is still valid JSON
    statuses = {f["path"]: f["status"] for f in report["files"]}
    assert statuses == {"a.py": "reviewed", "b.py": "error", "c.py": "error", "d.py": "error"}
    assert report["summary"]["files_reviewed"] == 1
    assert report["summary"]["files_errored"] == 3
    assert "3 of 4 file(s) were not reviewed" in result.stderr
    assert len(sent) <= 3, sent  # c.py may slip through the slot; d.py never does


def test_parallel_batch_asks_reviewer_to_skip_after_rate_limit(runner, tmp_path):
    instance = MagicMock()
    instance.__aenter__.return_value = instance
    instance.review_files_async = AsyncMock(return_value={"a.py": _clean(), "b.py": _clean()})

    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py", "b.py")
        with patch("coderev.async_reviewer.AsyncCodeReviewer", MagicMock(return_value=instance)):
            result = runner.invoke(main, ["batch", "a.py", "b.py", "--format", "json"])

    assert result.exit_code == 0, result.output
    kwargs = instance.review_files_async.call_args.kwargs
    assert kwargs["skip_after_rate_limit"] is True
    assert not kwargs.get("stop_on_rate_limit")


def test_sequential_rich_batch_exits_2_not_1_under_fail_on(runner, tmp_path):
    reviewer = _sync_reviewer({"a.py"})
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py", "b.py", "c.py")
        with patch("coderev.cli.CodeReviewer", return_value=reviewer):
            result = runner.invoke(
                main, ["batch", "a.py", "b.py", "c.py", "--no-parallel", "--fail-on", "high"]
            )

    _assert_rate_limit_exit(result, result.output)
    assert reviewer.review_file.call_count == 1  # b.py and c.py never sent
    assert "Files Errored" in result.output  # the report was still printed
    assert "3 of 3 file(s) were not reviewed" in result.output
    assert result.output.index("Files Errored") < result.output.index("Rate Limit Exceeded")


def test_batch_report_file_is_written_before_exit_2(runner, tmp_path):
    reviewer = _sync_reviewer({"b.py"})
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py", "b.py")
        with patch("coderev.cli.CodeReviewer", return_value=reviewer):
            result = runner.invoke(
                main,
                ["batch", "a.py", "b.py", "--no-parallel", "--format", "json", "-o", "report.json"],
            )
        saved = json.loads(Path("report.json").read_text(encoding="utf-8"))

    _assert_rate_limit_exit(result, result.stderr)
    assert result.stdout == ""
    assert {f["path"]: f["status"] for f in saved["files"]} == {"a.py": "reviewed", "b.py": "error"}
    assert "Report saved to report.json" in result.stderr
    assert "1 of 2 file(s) were not reviewed" in result.stderr


def test_batch_without_rate_limit_still_runs_fail_on_gate(runner, tmp_path):
    def review_file(path, *args, **kwargs):
        raise RuntimeError("401 invalid x-api-key")

    reviewer = CodeReviewer.__new__(CodeReviewer)
    reviewer.review_file = MagicMock(side_effect=review_file)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py")
        with patch("coderev.cli.CodeReviewer", return_value=reviewer):
            result = runner.invoke(main, ["batch", "a.py", "--no-parallel", "--fail-on", "high"])

    assert result.exit_code == 1, result.output
    assert "could not be reviewed" in result.output
    assert "Rate Limit Exceeded" not in result.output
