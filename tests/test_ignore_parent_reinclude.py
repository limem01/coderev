"""Regression tests for gitignore's parent-directory re-inclusion rule.

gitignore documents: "It is not possible to re-include a file if a parent
directory of that file is excluded." These tests pin coderev's behavior to
what real ``git check-ignore`` produces for the same patterns.
"""

from coderev.ignore import CodeRevIgnore


def _ignore(patterns):
    ig = CodeRevIgnore(patterns=patterns)
    ig.disable_defaults()
    return ig


class TestParentDirectoryReinclude:
    def test_excluded_dir_voids_file_negation(self):
        ig = _ignore(["build/", "!build/keep.txt"])
        # Directory itself is excluded -> negation on a child is ignored.
        assert ig.should_ignore("build/keep.txt") is True
        assert ig.should_ignore("build/output.js") is True

    def test_contents_only_exclusion_allows_negation(self):
        ig = _ignore(["build/*", "!build/keep.txt"])
        # ``build/*`` excludes contents, not the directory -> negation works.
        assert ig.should_ignore("build/keep.txt") is False
        assert ig.should_ignore("build/output.js") is True

    def test_reinclude_void_for_deeply_nested_paths(self):
        ig = _ignore(["logs/", "!logs/a/b/keep.log"])
        assert ig.should_ignore("logs/a/b/keep.log") is True
        assert ig.should_ignore("logs/x.log") is True

    def test_excluded_dir_at_any_depth_voids_negation(self):
        # Unanchored ``node_modules/`` matches at any depth; once matched, a
        # deeper negation cannot bring the file back.
        ig = _ignore(["node_modules/", "!node_modules/pkg/keep.js"])
        assert ig.should_ignore("src/node_modules/pkg/keep.js") is True

    def test_negation_still_works_without_excluded_parent(self):
        # Plain file-level negation (no parent directory excluded) is unaffected.
        ig = _ignore(["*.log", "!important.log"])
        assert ig.should_ignore("important.log") is False
        assert ig.should_ignore("other.log") is True

    def test_reinclude_directory_then_exclude_specific(self):
        # Contents excluded, one file re-included, then that file re-excluded:
        # last matching rule wins because the directory itself is never excluded.
        ig = _ignore(["cache/*", "!cache/keep", "cache/keep"])
        assert ig.should_ignore("cache/keep") is True

    def test_grandparent_exclusion_blocks_reinclude(self):
        # An excluded grandparent directory blocks re-inclusion two levels down.
        ig = _ignore(["dist/", "!dist/js/app.js"])
        assert ig.should_ignore("dist/js/app.js") is True

    def test_anchored_dir_exclusion_scope(self):
        # ``/build/`` only excludes the top-level build dir; a nested build is
        # untouched, so a negation elsewhere is irrelevant here.
        ig = _ignore(["/build/"])
        assert ig.should_ignore("build/x.py") is True
        assert ig.should_ignore("src/build/x.py") is False
