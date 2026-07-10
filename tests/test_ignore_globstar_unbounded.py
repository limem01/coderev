"""Regression tests for unbounded ``**`` in .coderevignore patterns.

Per gitignore semantics, ``**`` is only special when it is bounded by ``/`` or
the pattern boundary. Consecutive asterisks anywhere else are "regular
asterisks" and must not cross a directory separator. These tests pin that
behavior so ``a**b`` cannot leak into matching ``ax/yb``.
"""

from coderev.ignore import CodeRevIgnore, _globstar_to_regex


def _match(pattern: str, path: str) -> bool:
    ig = CodeRevIgnore()
    ig.disable_defaults()
    ig.add_pattern(pattern)
    return ig.should_ignore(path)


class TestUnboundedGlobstar:
    def test_mid_double_star_does_not_cross_slash(self):
        # 'a**b' is regular asterisks -> must stay within a segment.
        assert _match("a**b", "axxb")
        assert _match("a**b", "ab")
        assert not _match("a**b", "ax/yb")
        assert not _match("a**b", "a/b")

    def test_leading_double_star_without_slash_is_regular(self):
        # '**foo' -> '*foo', matches a single segment ending in foo.
        assert _match("**foo", "xfoo")
        assert _match("**foo", "foo")
        assert not _match("**foo", "a/xfoo")

    def test_trailing_double_star_without_slash_is_regular(self):
        # 'foo**' -> 'foo*', in-segment only (see the translation test below).
        assert _match("foo**", "foobar")
        # 'foo*' does not match a segment that lacks the 'foo' prefix.
        assert not _match("foo**", "xfoo")
        # But like gitignore, 'foo' matches the *directory* 'foo', so everything
        # under it is ignored too (verified against real ``git check-ignore``).
        assert _match("foo**", "foo/bar")

    def test_double_star_before_slash_without_prev_boundary_is_regular(self):
        # 'a**/b': the '**' is not preceded by a boundary, so it is regular.
        assert _match("a**/b", "axx/b")
        assert not _match("a**/b", "a/x/b")


class TestBoundedGlobstarStillWorks:
    def test_leading_globstar_slash(self):
        assert _match("**/build/", "src/nested/build/x.py")
        assert _match("**/foo", "a/b/foo")

    def test_middle_globstar_zero_or_more_dirs(self):
        assert _match("a/**/b", "a/b")
        assert _match("a/**/b", "a/x/b")
        assert _match("a/**/b", "a/x/y/b")
        # 'a/b' is a matched *directory*, so gitignore ignores its contents too
        # (verified against real ``git check-ignore``).
        assert _match("a/**/b", "a/b/c")

    def test_trailing_globstar_matches_everything_under(self):
        assert _match("foo/**", "foo/x")
        assert _match("foo/**", "foo/a/b/c")
        # gitignore: 'foo/**' does not match 'foo' itself (no trailing slash).
        assert not _match("foo/**", "foobar")

    def test_docs_globstar_example(self):
        assert _match("docs/**/*.md", "docs/x.md")
        assert _match("docs/**/*.md", "docs/a/b.md")
        assert not _match("docs/**/*.md", "docs/a/b.txt")


class TestRegexTranslationDirectly:
    def test_unbounded_double_star_becomes_in_segment(self):
        assert _globstar_to_regex("a**b") == "a[^/]*b"

    def test_bounded_middle_double_star(self):
        assert _globstar_to_regex("a/**/b") == "a/(?:.*/)?b"

    def test_trailing_double_star(self):
        assert _globstar_to_regex("foo/**") == "foo/.*"

    def test_bare_double_star(self):
        assert _globstar_to_regex("**") == ".*"
