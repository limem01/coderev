"""Parallel (async) reviews must use the review cache like sequential ones.

`coderev review`/`coderev batch` switch to AsyncCodeReviewer whenever more
than one file is reviewed, so if the async path skips the cache, every
multi-file re-review pays for every API call again while single-file
re-reviews are free.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coderev.async_reviewer import AsyncCodeReviewer
from coderev.reviewer import CodeReviewer
from coderev.rules import Rule, RuleSet

RESPONSE = {
    "summary": "ok",
    "issues": [{"severity": "low", "category": "style", "message": "nit", "line": 1}],
    "score": 88,
    "positive": ["clean"],
}


def _mock_provider():
    provider = MagicMock()
    provider.call_async = AsyncMock(return_value=MagicMock(content="<ignored>"))
    provider.call = MagicMock(return_value=MagicMock(content="<ignored>"))
    provider.parse_json_response.side_effect = lambda _: dict(RESPONSE)
    return provider


@pytest.fixture
def provider():
    p = _mock_provider()
    with patch("coderev.async_reviewer.get_provider", return_value=p), \
         patch("coderev.reviewer.get_provider", return_value=p):
        yield p


def _async_reviewer(tmp_path, **kwargs):
    kwargs.setdefault("cache_dir", tmp_path / "cache")
    return AsyncCodeReviewer(api_key="test-key", auto_load_rules=False, **kwargs)


def test_repeat_code_review_hits_cache(provider, tmp_path):
    reviewer = _async_reviewer(tmp_path)
    first = asyncio.run(reviewer.review_code_async("x = 1\n", "python"))
    second = asyncio.run(reviewer.review_code_async("x = 1\n", "python"))

    assert provider.call_async.await_count == 1
    assert second.score == first.score == 88
    assert [i.message for i in second.issues] == ["nit"]
    assert second.positive == ["clean"]


def test_changed_code_misses_cache(provider, tmp_path):
    reviewer = _async_reviewer(tmp_path)
    asyncio.run(reviewer.review_code_async("x = 1\n", "python"))
    asyncio.run(reviewer.review_code_async("x = 2\n", "python"))
    assert provider.call_async.await_count == 2


def test_use_cache_false_bypasses_cache(provider, tmp_path):
    reviewer = _async_reviewer(tmp_path)
    asyncio.run(reviewer.review_code_async("x = 1\n", "python"))
    asyncio.run(reviewer.review_code_async("x = 1\n", "python", use_cache=False))
    assert provider.call_async.await_count == 2


def test_cache_disabled_never_caches(provider, tmp_path):
    reviewer = _async_reviewer(tmp_path, cache_enabled=False)
    asyncio.run(reviewer.review_code_async("x = 1\n", "python"))
    asyncio.run(reviewer.review_code_async("x = 1\n", "python"))
    assert provider.call_async.await_count == 2
    assert not list((tmp_path / "cache").rglob("*.json"))


def test_rules_change_invalidates_cache(provider, tmp_path):
    reviewer = _async_reviewer(tmp_path)
    rules = RuleSet(rules=[Rule(id="r", name="R", description="NEW-RULE")])
    asyncio.run(reviewer.review_code_async("x = 1\n", "python"))
    asyncio.run(reviewer.review_code_async("x = 1\n", "python", rules=rules))
    assert provider.call_async.await_count == 2


def test_repeat_multi_file_review_hits_cache(provider, tmp_path):
    files = []
    for name, body in [("a.py", "a = 1\n"), ("b.py", "b = 2\n"), ("c.py", "c = 3\n")]:
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        files.append(f)

    reviewer = _async_reviewer(tmp_path)
    asyncio.run(reviewer.review_files_async(files))
    assert provider.call_async.await_count == 3

    results = asyncio.run(reviewer.review_files_async(files))
    assert provider.call_async.await_count == 3
    # Cached results still get file attribution on issues
    for f in files:
        assert all(i.file == str(f) for i in results[str(f)].issues)


def test_repeat_diff_review_hits_cache(provider, tmp_path):
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    reviewer = _async_reviewer(tmp_path)
    asyncio.run(reviewer.review_diff_async(diff))
    second = asyncio.run(reviewer.review_diff_async(diff))
    assert provider.call_async.await_count == 1
    assert second.score == 88


def test_diff_and_code_entries_do_not_collide(provider, tmp_path):
    text = "x = 1\n"
    reviewer = _async_reviewer(tmp_path)
    asyncio.run(reviewer.review_code_async(text))
    asyncio.run(reviewer.review_diff_async(text))
    assert provider.call_async.await_count == 2


def test_parallel_and_sequential_share_cache_entries(provider, tmp_path):
    """A sequential single-file review warms the cache for a later parallel one."""
    f = tmp_path / "m.py"
    f.write_text("m = 1\n", encoding="utf-8")
    cache_dir = tmp_path / "shared"

    seq = CodeReviewer(api_key="test-key", cache_dir=cache_dir, auto_load_rules=False)
    seq.review_file(f)
    assert provider.call.call_count == 1

    par = _async_reviewer(tmp_path, cache_dir=cache_dir)
    asyncio.run(par.review_files_async([f]))
    assert provider.call_async.await_count == 0


def test_default_cache_dir_is_isolated_in_tests(provider, tmp_path):
    """Guard for the conftest fixture: default reviewers must not touch ~/.cache."""
    from pathlib import Path

    reviewer = AsyncCodeReviewer(api_key="test-key", auto_load_rules=False)
    assert reviewer.cache.cache_dir != Path.home() / ".cache" / "coderev"
