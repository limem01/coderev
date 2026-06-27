"""Tests for gitignore-style escape handling in .coderevignore patterns.

Covers the three escape mechanisms gitignore defines:

* ``\\#`` -> a literal leading ``#`` (the line is a pattern, not a comment).
* ``\\!`` -> a literal leading ``!`` (the line is *not* a negation).
* backslash-escaped trailing whitespace is preserved; unescaped trailing
  whitespace is stripped.
"""

from coderev.ignore import CodeRevIgnore


class TestPreprocessLine:
    """Direct checks on the line preprocessor."""

    def test_blank_and_comment(self):
        assert CodeRevIgnore._preprocess_line("") is None
        assert CodeRevIgnore._preprocess_line("   ") is None
        assert CodeRevIgnore._preprocess_line("# comment") is None

    def test_plain_pattern(self):
        assert CodeRevIgnore._preprocess_line("*.log") == ("*.log", False)

    def test_negation(self):
        assert CodeRevIgnore._preprocess_line("!keep.log") == ("keep.log", True)

    def test_escaped_hash_is_literal_pattern(self):
        # "\#foo" -> literal "#foo", not a comment.
        assert CodeRevIgnore._preprocess_line(r"\#foo") == ("#foo", False)

    def test_escaped_bang_is_literal_not_negation(self):
        # "\!foo" -> literal "!foo", NOT a negation.
        assert CodeRevIgnore._preprocess_line(r"\!foo") == ("!foo", False)

    def test_unescaped_trailing_space_stripped(self):
        assert CodeRevIgnore._preprocess_line("foo   ") == ("foo", False)

    def test_escaped_trailing_space_kept(self):
        assert CodeRevIgnore._preprocess_line("foo\\ ") == ("foo ", False)


class TestEscapeMatching:
    """End-to-end matching through should_ignore."""

    def test_literal_hash_file_is_ignored(self):
        ignore = CodeRevIgnore(patterns=[r"\#notes.md"])
        ignore.disable_defaults()
        assert ignore.should_ignore("#notes.md") is True
        assert ignore.should_ignore("notes.md") is False

    def test_comment_line_is_not_a_pattern(self):
        # An unescaped leading '#' is a comment and matches nothing.
        ignore = CodeRevIgnore(patterns=["#notes.md"])
        ignore.disable_defaults()
        assert ignore.should_ignore("#notes.md") is False

    def test_literal_bang_file_is_ignored(self):
        ignore = CodeRevIgnore(patterns=[r"\!important.txt"])
        ignore.disable_defaults()
        assert ignore.should_ignore("!important.txt") is True

    def test_negation_still_works_alongside_escapes(self):
        ignore = CodeRevIgnore(patterns=["*.log", "!keep.log"])
        ignore.disable_defaults()
        assert ignore.should_ignore("app.log") is True
        assert ignore.should_ignore("keep.log") is False

    def test_unescaped_trailing_space_from_file_is_trimmed(self, tmp_path):
        ignore_file = tmp_path / ".coderevignore"
        ignore_file.write_text("trim.txt   \n")
        ignore = CodeRevIgnore.load(tmp_path)
        ignore.disable_defaults()
        assert ignore.should_ignore("trim.txt") is True

    def test_escaped_hash_pattern_from_file(self, tmp_path):
        ignore_file = tmp_path / ".coderevignore"
        ignore_file.write_text("# a real comment\n\\#literal.txt\n")
        ignore = CodeRevIgnore.load(tmp_path)
        ignore.disable_defaults()
        assert ignore.should_ignore("#literal.txt") is True
        assert ignore.should_ignore("literal.txt") is False
