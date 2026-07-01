"""Regression tests: ``*`` and ``?`` in unanchored patterns must not cross ``/``.

Gitignore matches with FNM_PATHNAME semantics, so wildcards never span a
directory separator. Anchored and globstar patterns already enforced this, but
the unanchored ``fnmatch`` path let ``*``/``?`` cross ``/`` -- e.g. ``a?.py``
wrongly matched ``a/.py``. These tests lock in the corrected behaviour and its
consistency with the cached matcher used by ``should_ignore``.
"""

from coderev.ignore import CodeRevIgnore


def _ig(*patterns):
    ig = CodeRevIgnore(list(patterns))
    ig._include_defaults = False
    return ig


class TestQuestionMarkDoesNotCross:
    def test_question_mark_stays_in_segment(self):
        ig = _ig("a?.py")
        # '?' matches a single non-separator char within one segment.
        assert ig.should_ignore("ab.py")
        # It must NOT treat the '/' as the char matched by '?'.
        assert not ig.should_ignore("a/.py")

    def test_question_mark_matches_at_any_depth(self):
        ig = _ig("a?.py")
        assert ig.should_ignore("src/ab.py")
        assert not ig.should_ignore("src/a/.py")


class TestStarDoesNotCross:
    def test_star_still_matches_basename_at_depth(self):
        # Preserved behaviour: a no-slash '*.py' matches at any level.
        ig = _ig("*.py")
        assert ig.should_ignore("a.py")
        assert ig.should_ignore("src/a.py")
        assert ig.should_ignore("src/sub/a.py")

    def test_star_does_not_span_separator(self):
        # 'foo*bar' must match within a single segment, not across a '/'.
        ig = _ig("foo*bar")
        assert ig.should_ignore("fooXbar")
        assert ig.should_ignore("src/fooXbar")
        assert not ig.should_ignore("foo/bar")
        assert not ig.should_ignore("src/foo/bar")


class TestDirectoryComponentMatch:
    def test_no_slash_pattern_matches_directory_component(self):
        # A no-separator pattern matches a directory component at any depth
        # (gitignore: 'foo' matches a dir 'foo' and everything under it).
        ig = _ig("foo")
        assert ig.should_ignore("foo")
        assert ig.should_ignore("a/foo/b.txt")
        assert not ig.should_ignore("a/food/b.txt")


class TestCachedMatcherAgrees:
    """The cached matcher path (should_ignore) must agree with _matches."""

    CASES = [
        ("a?.py", "ab.py"),
        ("a?.py", "a/.py"),
        ("a?.py", "src/ab.py"),
        ("*.py", "src/sub/a.py"),
        ("foo*bar", "foo/bar"),
        ("foo*bar", "src/fooXbar"),
        ("foo", "a/foo/b.txt"),
        ("foo", "a/food/b.txt"),
    ]

    def test_matches_matches_cached(self):
        for pat, path in self.CASES:
            ig = _ig(pat)
            path_str = ig._normalize_path(path)
            padded = f"/{path_str.strip('/')}/"
            norm_pat, anchored = ig._normalize_pattern(pat)
            oracle = ig._matches(norm_pat, path_str, padded, anchored)
            assert ig.should_ignore(path) == oracle, (pat, path)
