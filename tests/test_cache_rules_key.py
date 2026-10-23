"""Regression tests: custom rules must be part of the review cache key.

Custom rules are injected into the review prompt, so a review produced under
one rule set is not a valid answer under another. Before this fix the cache
key was only ``content|model|focus|language``, so editing ``.coderev`` rules
kept serving reviews made under the old rules until the TTL expired.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from coderev.cache import ReviewCache
from coderev.reviewer import CodeReviewer
from coderev.rules import Rule, RuleSet

CODE = "def f(x):\n    return eval(x)\n"
DIFF = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x = 1\n+x = eval(y)\n"


def _ruleset(*rule_ids: str, languages: list[str] | None = None) -> RuleSet:
    return RuleSet(
        rules=[
            Rule(
                id=rid,
                name=f"Rule {rid}",
                description=f"Description for {rid}",
                languages=list(languages or []),
            )
            for rid in rule_ids
        ]
    )


class TestCacheKeyIncludesRules:
    @pytest.fixture
    def cache(self, tmp_path: Path) -> ReviewCache:
        return ReviewCache(cache_dir=tmp_path, ttl_hours=24, enabled=True)

    def test_different_rules_text_is_a_miss(self, cache: ReviewCache) -> None:
        cache.set(CODE, "m", {"score": 1}, rules_text="rule A")
        assert cache.get(CODE, "m", rules_text="rule B") is None
        assert cache.get(CODE, "m", rules_text="rule A") == {"score": 1}

    def test_rules_vs_no_rules_is_a_miss(self, cache: ReviewCache) -> None:
        cache.set(CODE, "m", {"score": 1})
        assert cache.get(CODE, "m", rules_text="rule A") is None
        cache.set(CODE, "m", {"score": 2}, rules_text="rule A")
        assert cache.get(CODE, "m") == {"score": 1}

    def test_empty_rules_text_keeps_legacy_key(self, cache: ReviewCache) -> None:
        """No rules must hash exactly as before, so existing entries stay valid."""
        legacy = cache._generate_cache_key(CODE, "m", ["security"], "python")
        assert cache._generate_cache_key(CODE, "m", ["security"], "python", "") == legacy
        assert cache._generate_cache_key(CODE, "m", ["security"], "python", None) == legacy

    def test_rules_key_is_deterministic(self, cache: ReviewCache) -> None:
        k1 = cache._generate_cache_key(CODE, "m", None, None, "rule A")
        k2 = cache._generate_cache_key(CODE, "m", None, None, "rule A")
        assert k1 == k2


class TestReviewerKeysCacheOnRules:
    @pytest.fixture
    def reviewer(self, tmp_path: Path) -> CodeReviewer:
        return CodeReviewer(
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            cache_dir=tmp_path,
            auto_load_rules=False,
        )

    def _review(self, reviewer: CodeReviewer, method: str, rules: RuleSet | None) -> int:
        """Run a review with a mocked API; return the number of API calls made."""
        response = {"summary": "s", "issues": [], "score": 90, "positive": [],
                    "inline_suggestions": []}
        with patch.object(reviewer, "_call_api", return_value=response) as api:
            if method == "code":
                reviewer.review_code(CODE, language="python", rules=rules)
            elif method == "diff":
                reviewer.review_diff(DIFF, rules=rules)
            else:
                reviewer.review_with_inline_suggestions(CODE, language="python", rules=rules)
            return api.call_count

    @pytest.mark.parametrize("method", ["code", "diff", "inline"])
    def test_changed_rules_bypass_stale_cache(self, reviewer: CodeReviewer, method: str) -> None:
        assert self._review(reviewer, method, _ruleset("no-eval")) == 1
        # Same rules: served from cache.
        assert self._review(reviewer, method, _ruleset("no-eval")) == 0
        # Edited rules: must re-review, not return the old rules' result.
        assert self._review(reviewer, method, _ruleset("no-eval", "no-exec")) == 1
        # Rules removed entirely: also a different prompt.
        assert self._review(reviewer, method, None) == 1

    def test_rule_for_other_language_does_not_split_cache(self, reviewer: CodeReviewer) -> None:
        """A rule that doesn't apply to the file's language isn't in its prompt,
        so it shouldn't invalidate that file's cached review."""
        assert self._review(reviewer, "code", None) == 1
        assert self._review(reviewer, "code", _ruleset("go-only", languages=["go"])) == 0

    def test_instance_rules_are_keyed(self, tmp_path: Path) -> None:
        """Rules set on the reviewer (the .coderev path) are keyed, not just per-call ones."""
        r1 = CodeReviewer(api_key="k", model="claude-3-5-sonnet-20241022",
                          cache_dir=tmp_path, rules=_ruleset("a"), auto_load_rules=False)
        r2 = CodeReviewer(api_key="k", model="claude-3-5-sonnet-20241022",
                          cache_dir=tmp_path, rules=_ruleset("b"), auto_load_rules=False)
        assert self._review(r1, "code", None) == 1
        assert self._review(r2, "code", None) == 1
        assert self._review(r1, "code", None) == 0
