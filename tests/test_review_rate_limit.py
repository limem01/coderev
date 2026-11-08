"""`coderev review` stops at the first rate limit and exits 2.

The command's ``except RateLimitError`` (exit 2 plus retry guidance) was dead
code for file reviews: the sequential rich loop, ``review_files`` and
``review_files_async`` all caught the error as a generic ``Exception``. A
rate-limited review printed "Error reviewing ..." and exited 0 (or 1 under
``--fail-on``), and the remaining files kept calling a provider that was
already refusing requests. The pre-commit hook already stopped and exited 2.

``review_files`` / ``review_files_async`` keep their default (record the
error, carry on) for library callers; the review command opts in with
``stop_on_rate_limit=True``. ``coderev batch`` uses ``skip_after_rate_limit``
instead (see test_batch_rate_limit.py).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.async_reviewer import AsyncCodeReviewer
from coderev.cli import main
from coderev.reviewer import CodeReviewer, RateLimitError, ReviewResult


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


# --- library: CodeReviewer.review_files --------------------------------------


def _sync_reviewer(review_file) -> CodeReviewer:
    reviewer = CodeReviewer.__new__(CodeReviewer)
    reviewer.review_file = MagicMock(side_effect=review_file)
    return reviewer


def test_review_files_records_rate_limit_by_default(tmp_path):
    # Library callers keep the old contract.
    a, b = _write(tmp_path, "a.py", "b.py")

    def review_file(path, *args, **kwargs):
        if path.name == "a.py":
            raise _rate_limit()
        return _clean()

    reviewer = _sync_reviewer(review_file)
    results = reviewer.review_files([a, b])

    assert results[str(a)].failed
    assert "rate limit" in results[str(a)].error.lower()
    assert not results[str(b)].failed
    assert reviewer.review_file.call_count == 2


def test_review_files_stops_at_first_rate_limit(tmp_path):
    a, b, c = _write(tmp_path, "a.py", "b.py", "c.py")

    def review_file(path, *args, **kwargs):
        if path.name == "b.py":
            raise _rate_limit()
        return _clean()

    reviewer = _sync_reviewer(review_file)
    with pytest.raises(RateLimitError) as exc_info:
        reviewer.review_files([a, b, c], stop_on_rate_limit=True)

    assert exc_info.value.retry_after == 30
    reviewed = [call.args[0].name for call in reviewer.review_file.call_args_list]
    assert reviewed == ["a.py", "b.py"]  # c.py never sent


def test_review_files_stop_flag_still_records_other_errors(tmp_path):
    a, b = _write(tmp_path, "a.py", "b.py")

    def review_file(path, *args, **kwargs):
        if path.name == "a.py":
            raise RuntimeError("401 invalid x-api-key")
        return _clean()

    reviewer = _sync_reviewer(review_file)
    results = reviewer.review_files([a, b], stop_on_rate_limit=True)

    assert results[str(a)].error == "401 invalid x-api-key"
    assert not results[str(b)].failed


# --- library: AsyncCodeReviewer.review_files_async ---------------------------


def _async_provider(rate_limited: set[str], sent: list[str]) -> MagicMock:
    """Provider whose call_async rate-limits prompts mentioning a listed file."""
    provider = MagicMock()

    async def call_async(system_prompt, user_prompt):
        name = next(n for n in ("a.py", "b.py", "c.py", "d.py", "e.py") if n in user_prompt)
        sent.append(name)
        if name in rate_limited:
            raise _rate_limit()
        await asyncio.sleep(0.01)
        return MagicMock(content="{}")

    provider.call_async = AsyncMock(side_effect=call_async)
    provider.parse_json_response.return_value = {"summary": "ok", "issues": [], "score": 90}
    return provider


@pytest.mark.asyncio
async def test_review_files_async_records_rate_limit_by_default(tmp_path):
    files = _write(tmp_path, "a.py", "b.py", "c.py")
    sent: list[str] = []

    with patch("coderev.async_reviewer.get_provider") as get_provider:
        get_provider.return_value = _async_provider({"a.py"}, sent)
        async with AsyncCodeReviewer(
            api_key="test-key", max_concurrent=1, cache_enabled=False
        ) as reviewer:
            results = await reviewer.review_files_async(files)

    assert results[str(files[0])].failed
    assert not results[str(files[1])].failed
    assert sorted(sent) == ["a.py", "b.py", "c.py"]


@pytest.mark.asyncio
async def test_review_files_async_stops_and_cancels_queued_reviews(tmp_path):
    files = _write(tmp_path, "a.py", "b.py", "c.py", "d.py", "e.py")
    sent: list[str] = []

    with patch("coderev.async_reviewer.get_provider") as get_provider:
        get_provider.return_value = _async_provider({"a.py"}, sent)
        async with AsyncCodeReviewer(
            api_key="test-key", max_concurrent=1, cache_enabled=False
        ) as reviewer:
            with pytest.raises(RateLimitError):
                await reviewer.review_files_async(files, stop_on_rate_limit=True)

        # Give any review that escaped cancellation a chance to reach the provider.
        await asyncio.sleep(0.05)

    assert sent[0] == "a.py"
    # One slot: at most the review already handed the slot can get through;
    # everything still queued behind the semaphore is cancelled, not sent.
    assert len(sent) <= 2, sent


@pytest.mark.asyncio
async def test_review_files_async_stop_flag_keeps_results_without_rate_limit(tmp_path):
    files = _write(tmp_path, "a.py", "b.py")
    sent: list[str] = []

    with patch("coderev.async_reviewer.get_provider") as get_provider:
        get_provider.return_value = _async_provider(set(), sent)
        async with AsyncCodeReviewer(
            api_key="test-key", max_concurrent=2, cache_enabled=False
        ) as reviewer:
            results = await reviewer.review_files_async(files, stop_on_rate_limit=True)

    assert set(results) == {str(f) for f in files}
    assert not any(r.failed for r in results.values())


# --- CLI: coderev review -----------------------------------------------------


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


def _assert_rate_limit_exit(result) -> None:
    assert result.exit_code == 2, result.output
    assert "Rate Limit Exceeded" in result.output
    assert "Retry after: 30 seconds" in result.output
    assert "Error reviewing" not in result.output


def test_single_file_rich_review_exits_2(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py")
        with patch("coderev.cli.CodeReviewer") as reviewer_cls:
            reviewer_cls.return_value.review_file.side_effect = _rate_limit()
            result = runner.invoke(main, ["review", "a.py"])

    _assert_rate_limit_exit(result)


def test_single_file_rich_review_exits_2_not_1_under_fail_on(runner, tmp_path):
    # Previously the errored placeholder tripped the gate: exit 1, no retry hint.
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py")
        with patch("coderev.cli.CodeReviewer") as reviewer_cls:
            reviewer_cls.return_value.review_file.side_effect = _rate_limit()
            result = runner.invoke(main, ["review", "a.py", "--fail-on", "high"])

    _assert_rate_limit_exit(result)
    assert "could not be reviewed" not in result.output


def test_sequential_rich_review_stops_at_first_rate_limit(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py", "b.py", "c.py")
        with patch("coderev.cli.CodeReviewer") as reviewer_cls:
            review_file = reviewer_cls.return_value.review_file
            review_file.side_effect = [_clean(), _rate_limit(), _clean()]
            result = runner.invoke(main, ["review", "a.py", "b.py", "c.py", "--no-parallel"])

    _assert_rate_limit_exit(result)
    assert review_file.call_count == 2
    assert "Reviewing c.py" not in result.output


def test_sequential_json_review_exits_2_with_nothing_on_stdout(runner, tmp_path):
    def review_file(path, *args, **kwargs):
        if path.name == "a.py":
            raise _rate_limit()
        return _clean()

    reviewer = _sync_reviewer(review_file)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py", "b.py")
        with patch("coderev.cli.CodeReviewer", return_value=reviewer):
            result = runner.invoke(
                main, ["review", "a.py", "b.py", "--no-parallel", "--format", "json"]
            )

    _assert_rate_limit_exit(result)
    assert result.stdout == ""  # no half-finished report
    assert "Rate Limit Exceeded" in result.stderr
    assert reviewer.review_file.call_count == 1


def test_parallel_review_exits_2_and_asks_reviewer_to_stop(runner, tmp_path):
    instance = MagicMock()
    instance.__aenter__.return_value = instance
    instance.review_files_async = AsyncMock(side_effect=_rate_limit())

    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py", "b.py")
        with patch("coderev.async_reviewer.AsyncCodeReviewer", MagicMock(return_value=instance)):
            result = runner.invoke(main, ["review", "a.py", "b.py", "--format", "json"])

    _assert_rate_limit_exit(result)
    assert result.stdout == ""
    assert instance.review_files_async.call_args.kwargs["stop_on_rate_limit"] is True


def test_parallel_review_end_to_end_exits_2(runner, tmp_path, mock_config):
    # Real AsyncCodeReviewer and semaphore; only the provider is faked.
    sent: list[str] = []
    real_init = AsyncCodeReviewer.__init__

    def init(self, *args, config=None, max_concurrent=5, **kwargs):
        real_init(self, api_key="test-key", max_concurrent=1, cache_enabled=False)

    with runner.isolated_filesystem(temp_dir=tmp_path):
        _write(Path("."), "a.py", "b.py", "c.py", "d.py")
        with (
            patch("coderev.async_reviewer.get_provider") as get_provider,
            patch.object(AsyncCodeReviewer, "__init__", init),
        ):
            get_provider.return_value = _async_provider({"a.py"}, sent)
            result = runner.invoke(
                main, ["review", "a.py", "b.py", "c.py", "d.py", "--format", "json"]
            )

    _assert_rate_limit_exit(result)
    assert result.stdout == ""
    assert len(sent) <= 2, sent
