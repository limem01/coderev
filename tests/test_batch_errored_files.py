"""Files whose review failed must be reported as errored, not as score-0 reviews.

`review_files` (sequential) and `review_files_async` (parallel) turn a failed
review into a placeholder ReviewResult. Without an explicit error marker the
batch report classified it as "reviewed" with score 0: `files_errored` was
always 0 and a single API failure dragged the average score down and put the
file at the top of the "worst files" list.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coderev.async_reviewer import AsyncCodeReviewer
from coderev.batch import BatchReviewReport, FileReviewSummary
from coderev.reviewer import CodeReviewer, ReviewResult

RESPONSE = {"summary": "ok", "issues": [], "score": 90, "positive": []}


def _failing_provider():
    provider = MagicMock()
    provider.call_async = AsyncMock(side_effect=RuntimeError("API exploded"))
    provider.call = MagicMock(side_effect=RuntimeError("API exploded"))
    return provider


@pytest.fixture
def files(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("x = 1\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text("y = 2\n", encoding="utf-8")
    return good, bad


def test_review_result_error_defaults_to_none():
    result = ReviewResult(summary="ok", score=80)
    assert result.error is None
    assert result.failed is False


def test_summary_from_errored_result_has_error_status():
    result = ReviewResult(summary="Error reviewing file: boom", score=0, error="boom")
    summary = FileReviewSummary.from_result("a.py", result)
    assert summary.status == "error"
    assert summary.error_message == "Error reviewing file: boom"


def test_report_excludes_errored_files_from_score_stats():
    results = {
        "good.py": ReviewResult(summary="ok", score=90),
        "bad.py": ReviewResult(summary="Error reviewing file: boom", score=0, error="boom"),
    }
    report = BatchReviewReport.from_results(results)

    assert report.files_reviewed == 1
    assert report.files_errored == 1
    assert report.total_files == 2
    assert report.average_score == 90
    assert report.min_score == 90
    assert "bad.py" not in report.worst_files


def test_legacy_score_zero_result_without_error_is_still_reviewed():
    # A genuine review can score 0; only the error marker means "errored".
    report = BatchReviewReport.from_results({"a.py": ReviewResult(summary="awful", score=0)})
    assert report.files_reviewed == 1
    assert report.files_errored == 0


def test_sequential_review_files_marks_failures(files):
    good, bad = files
    with patch("coderev.reviewer.get_provider", return_value=_failing_provider()):
        reviewer = CodeReviewer(api_key="k", auto_load_rules=False, cache_enabled=False)
        results = reviewer.review_files([bad])

    result = results[str(bad)]
    assert result.failed
    assert "API exploded" in result.error
    assert BatchReviewReport.from_results(results).files_errored == 1


def test_parallel_review_files_marks_failures(files):
    good, bad = files
    provider = MagicMock()

    async def call_async(system, prompt):
        if "bad.py" in prompt:
            raise RuntimeError("API exploded")
        return MagicMock(content="<ignored>")

    provider.call_async = AsyncMock(side_effect=call_async)
    provider.parse_json_response.side_effect = lambda _: dict(RESPONSE)

    with patch("coderev.async_reviewer.get_provider", return_value=provider):
        reviewer = AsyncCodeReviewer(api_key="k", auto_load_rules=False, cache_enabled=False)
        results = asyncio.run(reviewer.review_files_async([good, bad]))

    assert not results[str(good)].failed
    assert results[str(bad)].failed
    report = BatchReviewReport.from_results(results)
    assert report.files_reviewed == 1
    assert report.files_errored == 1
    assert report.average_score == 90


def test_skipped_binary_file_is_not_errored(tmp_path):
    binary = tmp_path / "img.bin"
    binary.write_bytes(b"\x00\x01\x02\xff" * 64)
    with patch("coderev.reviewer.get_provider", return_value=_failing_provider()):
        reviewer = CodeReviewer(api_key="k", auto_load_rules=False, cache_enabled=False)
        results = reviewer.review_files([binary])

    assert not results[str(binary)].failed
    assert BatchReviewReport.from_results(results).files_skipped == 1
