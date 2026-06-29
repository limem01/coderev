"""Tests for the compiled-pattern cache in CodeRevIgnore.

Patterns are parsed/normalized/compiled once and reused across path checks.
These tests verify the cache is built lazily, reused, and correctly
invalidated when the pattern set changes — without altering match results.
"""

from coderev.ignore import CodeRevIgnore


class TestCompiledPatternCache:
    def test_cache_is_lazy(self):
        ignore = CodeRevIgnore(["*.tmp"])
        # Nothing compiled until the first check.
        assert ignore._compiled is None
        ignore.should_ignore("foo.tmp")
        assert ignore._compiled is not None

    def test_cache_is_reused_across_checks(self):
        ignore = CodeRevIgnore(["*.tmp"])
        ignore.should_ignore("a.tmp")
        first = ignore._compiled
        ignore.should_ignore("b.tmp")
        # Same compiled list object: it was not rebuilt for the second path.
        assert ignore._compiled is first

    def test_add_pattern_invalidates_cache(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("secret.key") is False
        ignore.add_pattern("*.key")
        # The newly added pattern takes effect (cache was invalidated).
        assert ignore.should_ignore("secret.key") is True

    def test_disable_defaults_invalidates_cache(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("module.pyc") is True
        ignore.disable_defaults()
        # Defaults no longer apply once disabled.
        assert ignore.should_ignore("module.pyc") is False

    def test_cache_preserves_negation_ordering(self):
        ignore = CodeRevIgnore(["*.log", "!keep.log"])
        assert ignore.should_ignore("debug.log") is True
        assert ignore.should_ignore("keep.log") is False
        # Re-checking (served from cache) yields identical results.
        assert ignore.should_ignore("debug.log") is True
        assert ignore.should_ignore("keep.log") is False

    def test_compiled_results_match_uncached_dispatch(self):
        """The cached matchers must agree with the original _matches dispatch."""
        patterns = [
            "*.tmp",
            "build/",
            "/dist/",
            "src/*.py",
            "docs/**/*.md",
            "[Tt]est.txt",
        ]
        paths = [
            "a.tmp",
            "build/x.o",
            "src/build/x.o",
            "dist/x.o",
            "src/dist/x.o",
            "src/a.py",
            "src/sub/a.py",
            "docs/guide.md",
            "docs/a/b/guide.md",
            "Test.txt",
            "best.txt",
        ]
        ignore = CodeRevIgnore(patterns)
        ignore.disable_defaults()
        for p in paths:
            path_str = ignore._normalize_path(p)
            padded = f"/{path_str.strip('/')}/"
            # Replicate the pre-cache dispatch directly via _matches.
            expected = False
            for raw in patterns:
                parsed = ignore._preprocess_line(raw)
                if parsed is None:
                    continue
                pat, negated = parsed
                pat, anchored = ignore._normalize_pattern(pat)
                if not pat:
                    continue
                if ignore._matches(pat, path_str, padded, anchored):
                    expected = not negated
            assert ignore.should_ignore(p) is expected, p
