"""Regression tests: a pattern that matches a directory ignores its contents.

Per gitignore, a pattern *without* a trailing ``/`` matches both files and
directories, and when the match is a directory everything under it is ignored
too. Before the fix, anchored and globstar patterns compiled to ``^pat$`` and so
matched only the directory entry itself, not its contents -- diverging from
``git``. Each expectation below was verified against real ``git check-ignore``.
"""

from coderev.ignore import CodeRevIgnore


def _match(pattern: str, path: str) -> bool:
    ig = CodeRevIgnore()
    ig.disable_defaults()
    ig.add_pattern(pattern)
    return ig.should_ignore(path)


class TestAnchoredDirectoryContents:
    def test_anchored_dir_ignores_contents(self):
        # '/build' matches top-level 'build' and everything under it.
        assert _match("/build", "build")
        assert _match("/build", "build/foo.py")
        assert _match("/build", "build/a/b.py")

    def test_anchored_dir_stays_anchored(self):
        # ... but not a nested 'src/build'.
        assert not _match("/build", "src/build")
        assert not _match("/build", "src/build/x.py")

    def test_anchored_file_does_not_overmatch_siblings(self):
        # '/README.md' matches the file, not lookalike siblings.
        assert _match("/README.md", "README.md")
        assert not _match("/README.md", "README.md.bak")
        assert not _match("/README.md", "src/README.md")

    def test_internal_slash_pattern_ignores_contents(self):
        # 'src/build' is anchored by its internal '/'; contents ignored too.
        assert _match("src/build", "src/build")
        assert _match("src/build", "src/build/x.py")
        assert not _match("src/build", "src/build.py")


class TestGlobstarDirectoryContents:
    def test_globstar_match_ignores_contents(self):
        # 'docs/**/build' matches the 'build' dir at any depth and its contents.
        assert _match("docs/**/build", "docs/build")
        assert _match("docs/**/build", "docs/build/a/b.py")
        assert _match("docs/**/build", "docs/x/build")
        assert _match("docs/**/build", "docs/x/build/foo.py")

    def test_globstar_no_partial_segment_overmatch(self):
        # 'build' must be a whole segment, not a prefix like 'buildish'.
        assert not _match("docs/**/build", "docs/x/buildish")
