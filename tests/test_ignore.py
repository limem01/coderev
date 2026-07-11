"""Tests for .coderevignore handling."""

import os
from pathlib import Path

import pytest

from coderev.ignore import CodeRevIgnore, DEFAULT_IGNORE_PATTERNS


class TestCodeRevIgnore:
    """Tests for CodeRevIgnore class."""
    
    def test_default_patterns_exist(self):
        assert len(DEFAULT_IGNORE_PATTERNS) > 0
        assert "node_modules/" in DEFAULT_IGNORE_PATTERNS
        assert "__pycache__/" in DEFAULT_IGNORE_PATTERNS
    
    def test_ignore_node_modules(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("node_modules/package/index.js") is True
        assert ignore.should_ignore("src/node_modules/test.js") is True
        # Windows-style separators should still match
        assert ignore.should_ignore(r"node_modules\\package\\index.js") is True
        assert ignore.should_ignore(r"src\\node_modules\\test.js") is True
    
    def test_ignore_pycache(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("__pycache__/module.pyc") is True
        assert ignore.should_ignore("src/__pycache__/test.pyc") is True
    
    def test_ignore_pyc_files(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("module.pyc") is True
        assert ignore.should_ignore("src/utils/helper.pyc") is True
    
    def test_ignore_min_files(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("bundle.min.js") is True
        assert ignore.should_ignore("styles.min.css") is True
    
    def test_allow_normal_files(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("src/main.py") is False
        assert ignore.should_ignore("app/index.js") is False
        assert ignore.should_ignore("README.md") is False
    
    def test_custom_patterns(self):
        ignore = CodeRevIgnore(patterns=["*.test.py", "fixtures/"])
        assert ignore.should_ignore("test_main.test.py") is True
        assert ignore.should_ignore("fixtures/data.json") is True
        assert ignore.should_ignore(r"fixtures\\data.json") is True
        assert ignore.should_ignore("src/main.py") is False
    
    def test_add_pattern(self):
        ignore = CodeRevIgnore()
        assert ignore.should_ignore("custom.xyz") is False
        
        ignore.add_pattern("*.xyz")
        assert ignore.should_ignore("custom.xyz") is True
    
    def test_disable_defaults(self):
        ignore = CodeRevIgnore(patterns=["*.custom"])
        ignore.disable_defaults()
        
        # Default patterns should not apply
        assert ignore.should_ignore("node_modules/test.js") is False
        # Custom pattern still works
        assert ignore.should_ignore("file.custom") is True
    
    def test_filter_paths(self):
        ignore = CodeRevIgnore()
        paths = [
            Path("src/main.py"),
            Path("node_modules/pkg/index.js"),
            Path("src/utils.py"),
            Path("__pycache__/main.pyc"),
        ]
        
        filtered = list(ignore.filter_paths(paths))
        assert len(filtered) == 2
        assert Path("src/main.py") in filtered
        assert Path("src/utils.py") in filtered
    
    def test_load_from_file(self, tmp_path):
        ignore_file = tmp_path / ".coderevignore"
        ignore_file.write_text("""
# This is a comment
*.log
temp/
secret.txt
""")
        
        ignore = CodeRevIgnore.load(tmp_path)
        assert ignore.should_ignore("app.log") is True
        assert ignore.should_ignore("temp/file.txt") is True
        assert ignore.should_ignore("secret.txt") is True
        assert ignore.should_ignore("main.py") is False
    
    def test_empty_ignore_file(self, tmp_path):
        ignore_file = tmp_path / ".coderevignore"
        ignore_file.write_text("")
        
        ignore = CodeRevIgnore.load(tmp_path)
        # Should still have default patterns
        assert ignore.should_ignore("node_modules/x.js") is True

    def test_windows_style_patterns_in_ignore_file(self, tmp_path):
        """Users on Windows often write patterns with backslashes.

        We normalize both input paths and patterns so matching remains consistent.
        """
        ignore_file = tmp_path / ".coderevignore"
        ignore_file.write_text(
            """
# Windows-style separators in patterns
src\\generated\\
*.secret
""".lstrip()
        )

        ignore = CodeRevIgnore.load(tmp_path)
        assert ignore.should_ignore("src/generated/file.py") is True
        assert ignore.should_ignore(r"src\generated\file.py") is True
        assert ignore.should_ignore("notes.secret") is True
        assert ignore.should_ignore("src/main.py") is False

    def test_directory_segment_matching_does_not_false_positive(self):
        """Directory patterns like build/ should not match 'rebuild/' segments."""
        ignore = CodeRevIgnore(patterns=["build/"])
        assert ignore.should_ignore("build/output.js") is True
        assert ignore.should_ignore("src/build/output.js") is True
        assert ignore.should_ignore("rebuild/output.js") is False
        assert ignore.should_ignore("src/rebuild/output.js") is False

    def test_leading_dot_slash_is_normalized(self):
        ignore = CodeRevIgnore(patterns=["./build/", "./*.log"])
        assert ignore.should_ignore("./build/output.js") is True
        assert ignore.should_ignore("./app.log") is True
        assert ignore.should_ignore("app.log") is True

    def test_leading_slash_in_pattern_is_treated_as_repo_relative(self):
        ignore = CodeRevIgnore(patterns=["/build/", "/*.log"])
        assert ignore.should_ignore("build/output.js") is True
        assert ignore.should_ignore("/build/output.js") is True
        assert ignore.should_ignore("app.log") is True
        assert ignore.should_ignore("/app.log") is True

    def test_leading_slash_anchors_to_repo_root(self):
        """A leading '/' anchors a pattern to the root (gitignore semantics)."""
        # 'reports/' is not in DEFAULT_IGNORE_PATTERNS, so the anchoring is what
        # determines the result here.
        ignore = CodeRevIgnore(patterns=["/reports/"])
        # Top-level reports/ is ignored...
        assert ignore.should_ignore("reports/output.js") is True
        # ...but a nested reports/ is NOT, because the pattern is anchored.
        assert ignore.should_ignore("src/reports/output.js") is False
        assert ignore.should_ignore("a/b/reports/output.js") is False

    def test_unanchored_directory_still_matches_at_any_depth(self):
        """Without a leading slash, a directory pattern matches at any depth."""
        ignore = CodeRevIgnore(patterns=["reports/"])
        assert ignore.should_ignore("reports/output.js") is True
        assert ignore.should_ignore("src/reports/output.js") is True

    def test_wildcard_in_directory_pattern_does_not_cross_separator(self):
        """A '*' in an unanchored directory pattern stays within one segment.

        ``foo*bar/`` must match a single directory segment named like
        ``fooXbar`` at any depth, but must not let ``*`` span ``/`` (so it does
        not match ``foo/x/bar/z``), mirroring gitignore's FNM_PATHNAME rule.
        """
        ignore = CodeRevIgnore(patterns=["foo*bar/"])
        assert ignore.should_ignore("a/fooXbar/y") is True
        assert ignore.should_ignore("fooXbar/y") is True
        assert ignore.should_ignore("foo/x/bar/z") is False

    def test_question_mark_in_directory_pattern_does_not_cross_separator(self):
        """A '?' in a directory pattern matches one non-separator char only."""
        ignore = CodeRevIgnore(patterns=["a?c/"])
        assert ignore.should_ignore("abc/z") is True
        assert ignore.should_ignore("x/abc/z") is True
        assert ignore.should_ignore("a/c/z") is False

    def test_leading_slash_anchors_file_glob_to_root(self):
        """An anchored file glob keeps '*' within the top-level segment."""
        ignore = CodeRevIgnore(patterns=["/*.tmp"])
        assert ignore.should_ignore("app.tmp") is True
        # A nested file is not matched by the anchored, single-segment glob.
        assert ignore.should_ignore("src/app.tmp") is False

    def test_leading_dot_slash_anchors_to_root(self):
        ignore = CodeRevIgnore(patterns=["./reports/"])
        assert ignore.should_ignore("reports/output.js") is True
        assert ignore.should_ignore("src/reports/output.js") is False

    def test_negation_patterns_unignore_files(self):
        ignore = CodeRevIgnore(patterns=["*.log", "!important.log"])
        assert ignore.should_ignore("debug.log") is True
        assert ignore.should_ignore("important.log") is False

    def test_negation_patterns_last_match_wins(self):
        ignore = CodeRevIgnore(patterns=["!important.log", "*.log"])
        # The later ignore should take precedence
        assert ignore.should_ignore("important.log") is True

    def test_negation_cannot_reinclude_under_excluded_directory(self):
        # gitignore: "It is not possible to re-include a file if a parent
        # directory of that file is excluded." ``build/`` excludes the
        # directory itself, so the ``!build/keep.txt`` negation is void.
        ignore = CodeRevIgnore(patterns=["build/", "!build/keep.txt"])
        assert ignore.should_ignore("build/output.js") is True
        assert ignore.should_ignore("build/keep.txt") is True

    def test_negation_reincludes_when_only_contents_excluded(self):
        # ``generated/*`` excludes the *contents* of the directory, not the
        # directory itself, so a file-level negation can still re-include a
        # path. (Uses a non-default dir name so DEFAULT_IGNORE_PATTERNS'
        # ``build/`` doesn't independently exclude the directory.)
        ignore = CodeRevIgnore(patterns=["generated/*", "!generated/keep.txt"])
        assert ignore.should_ignore("generated/output.js") is True
        assert ignore.should_ignore("generated/keep.txt") is False


class TestGlobstarPatterns:
    """Tests for ** (globstar) pattern support."""

    def test_globstar_matches_zero_or_more_directories(self):
        ignore = CodeRevIgnore(patterns=["docs/**/*.md"])
        # Zero intermediate directories
        assert ignore.should_ignore("docs/x.md") is True
        # One or more intermediate directories
        assert ignore.should_ignore("docs/a/b.md") is True
        assert ignore.should_ignore("docs/a/b/c.md") is True

    def test_globstar_is_anchored(self):
        ignore = CodeRevIgnore(patterns=["docs/**/*.md"])
        # The leading segment is anchored; a nested docs/ should not match.
        assert ignore.should_ignore("other/docs/x.md") is False

    def test_globstar_respects_trailing_extension(self):
        ignore = CodeRevIgnore(patterns=["docs/**/*.md"])
        assert ignore.should_ignore("docs/a/b.txt") is False

    def test_leading_globstar_matches_directory_anywhere(self):
        ignore = CodeRevIgnore(patterns=["**/build/"])
        assert ignore.should_ignore("build/output.js") is True
        assert ignore.should_ignore("a/b/build/output.js") is True
        # Should not false-positive on similarly named directories.
        assert ignore.should_ignore("rebuild/output.js") is False

    def test_trailing_globstar_matches_everything_under_directory(self):
        ignore = CodeRevIgnore(patterns=["generated/**"])
        assert ignore.should_ignore("generated/a.py") is True
        assert ignore.should_ignore("generated/a/b.py") is True
        assert ignore.should_ignore("other/a.py") is False

    def test_single_star_does_not_cross_separator_in_globstar_pattern(self):
        # In a globstar pattern, a lone * must stay within one path segment.
        ignore = CodeRevIgnore(patterns=["src/*/mod.py"])
        # (no ** here, so this exercises regular matching) — sanity baseline
        assert ignore.should_ignore("src/pkg/mod.py") is True

        ignore2 = CodeRevIgnore(patterns=["src/**/*.py"])
        assert ignore2.should_ignore("src/a/b/file.py") is True
        assert ignore2.should_ignore("src/file.py") is True

    def test_globstar_with_negation(self):
        ignore = CodeRevIgnore(patterns=["src/**/*.py", "!src/**/keep.py"])
        assert ignore.should_ignore("src/a/b/util.py") is True
        assert ignore.should_ignore("src/a/b/keep.py") is False

    def test_single_star_does_not_cross_separator_in_plain_pattern(self):
        # gitignore: a lone '*' never crosses '/', even without '**'.
        ignore = CodeRevIgnore(patterns=["src/*.py"])
        ignore.disable_defaults()
        assert ignore.should_ignore("src/a.py") is True
        assert ignore.should_ignore("src/sub/a.py") is False

    def test_internal_separator_anchors_to_root(self):
        # A separator in the middle anchors the pattern to the repo root, so it
        # must not match the same tail nested under another directory.
        ignore = CodeRevIgnore(patterns=["doc/frotz"])
        ignore.disable_defaults()
        assert ignore.should_ignore("doc/frotz") is True
        assert ignore.should_ignore("a/doc/frotz") is False

    def test_slashless_dir_pattern_still_matches_any_depth(self):
        # A pattern with no internal separator keeps matching at any depth.
        ignore = CodeRevIgnore(patterns=["build/"])
        ignore.disable_defaults()
        assert ignore.should_ignore("build/x") is True
        assert ignore.should_ignore("a/b/build/x") is True

    def test_mid_pattern_star_in_directory_segment(self):
        # 'logs/*/debug.txt' matches exactly one intermediate segment.
        ignore = CodeRevIgnore(patterns=["logs/*/debug.txt"])
        ignore.disable_defaults()
        assert ignore.should_ignore("logs/x/debug.txt") is True
        assert ignore.should_ignore("logs/x/y/debug.txt") is False
