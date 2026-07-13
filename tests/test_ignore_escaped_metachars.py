"""Backslash escapes for glob metacharacters in .coderevignore.

gitignore lets a backslash escape a metacharacter so it matches literally:
``\\*`` is a literal asterisk, not a wildcard. Previously every backslash in a
pattern was folded to ``/`` (for Windows path compatibility), which made escapes
impossible -- ``report\\*.csv`` silently became the anchored pattern
``report/*.csv``.

Backslash before a *non*-metacharacter is still treated as a Windows path
separator, so ``src\\generated\\`` keeps working (see test_ignore.py).
"""

from pathlib import Path

from coderev.ignore import CodeRevIgnore, _globstar_to_regex, _has_globstar


class TestGlobstarRegexEscapes:
    def test_escaped_star_is_literal(self):
        assert _globstar_to_regex(r"a\*b") == "a\\*b"

    def test_escaped_question_mark_is_literal(self):
        assert _globstar_to_regex(r"a\?b") == "a\\?b"

    def test_escaped_bracket_is_literal(self):
        assert _globstar_to_regex(r"a\[b") == "a\\[b"

    def test_unescaped_star_stays_a_wildcard(self):
        assert _globstar_to_regex("a*b") == "a[^/]*b"

    def test_trailing_lone_backslash_is_literal(self):
        assert _globstar_to_regex("a\\") == "a\\\\"


class TestHasGlobstar:
    def test_plain_globstar_detected(self):
        assert _has_globstar("docs/**/x.md") is True

    def test_escaped_star_then_star_is_not_a_globstar(self):
        # ``a\**`` is a literal '*' followed by a wildcard, not a globstar.
        assert _has_globstar(r"a\**") is False

    def test_no_asterisks(self):
        assert _has_globstar("build/") is False


class TestEscapedMetacharMatching:
    def test_escaped_star_matches_literal_star_only(self):
        ignore = CodeRevIgnore(patterns=[r"report\*.csv"])
        ignore.disable_defaults()

        assert ignore.should_ignore("report*.csv") is True
        # The star is literal, so it must not behave as a wildcard.
        assert ignore.should_ignore("report-q1.csv") is False
        assert ignore.should_ignore("report.csv") is False

    def test_unescaped_star_still_wildcards(self):
        ignore = CodeRevIgnore(patterns=["report*.csv"])
        ignore.disable_defaults()

        assert ignore.should_ignore("report-q1.csv") is True
        assert ignore.should_ignore("report*.csv") is True

    def test_escaped_star_is_not_turned_into_a_separator(self):
        """Regression: ``report\\*.csv`` used to become ``report/*.csv``."""
        ignore = CodeRevIgnore(patterns=[r"report\*.csv"])
        ignore.disable_defaults()

        assert ignore.should_ignore("report/q1.csv") is False

    def test_escaped_star_matches_at_any_depth(self):
        ignore = CodeRevIgnore(patterns=[r"report\*.csv"])
        ignore.disable_defaults()

        assert ignore.should_ignore("data/2026/report*.csv") is True

    def test_escaped_question_mark_matches_literal(self):
        ignore = CodeRevIgnore(patterns=[r"what\?.txt"])
        ignore.disable_defaults()

        assert ignore.should_ignore("what?.txt") is True
        assert ignore.should_ignore("whatX.txt") is False

    def test_escaped_bracket_matches_literal(self):
        ignore = CodeRevIgnore(patterns=[r"\[draft\].md"])
        ignore.disable_defaults()

        assert ignore.should_ignore("[draft].md") is True
        assert ignore.should_ignore("d.md") is False

    def test_escaped_star_in_anchored_pattern(self):
        ignore = CodeRevIgnore(patterns=[r"/logs/star\*.txt"])
        ignore.disable_defaults()

        assert ignore.should_ignore("logs/star*.txt") is True
        assert ignore.should_ignore("logs/starX.txt") is False

    def test_escaped_star_in_directory_pattern(self):
        ignore = CodeRevIgnore(patterns=[r"tmp\*dir/"])
        ignore.disable_defaults()

        assert ignore.should_ignore("a/tmp*dir/x.py") is True
        assert ignore.should_ignore("a/tmpXdir/x.py") is False


class TestWindowsSeparatorsStillWork:
    """A backslash before a non-metacharacter remains a path separator."""

    def test_backslash_separator_pattern(self):
        ignore = CodeRevIgnore(patterns=["src\\generated\\"])
        ignore.disable_defaults()

        assert ignore.should_ignore("src/generated/file.py") is True
        assert ignore.should_ignore("src/other/file.py") is False

    def test_backslash_separator_anchors_pattern(self):
        # An internal separator anchors to the repo root, backslash or not.
        ignore = CodeRevIgnore(patterns=["src\\generated\\"])
        ignore.disable_defaults()

        assert ignore.should_ignore("app/src/generated/file.py") is False


class TestEscapesFromIgnoreFile:
    def test_escaped_star_read_from_file(self, tmp_path: Path):
        (tmp_path / ".coderevignore").write_text("report\\*.csv\n")

        ignore = CodeRevIgnore.load(root=tmp_path)
        ignore.disable_defaults()

        assert ignore.should_ignore("report*.csv") is True
        assert ignore.should_ignore("report-q1.csv") is False

    def test_negated_escaped_star(self, tmp_path: Path):
        (tmp_path / ".coderevignore").write_text("*.csv\n!report\\*.csv\n")

        ignore = CodeRevIgnore.load(root=tmp_path)
        ignore.disable_defaults()

        assert ignore.should_ignore("data.csv") is True
        assert ignore.should_ignore("report*.csv") is False
        # The negation is literal, so a wildcard-ish name stays ignored.
        assert ignore.should_ignore("report-q1.csv") is True
