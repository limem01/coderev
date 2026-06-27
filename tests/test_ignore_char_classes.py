"""Tests for character-class support in .coderevignore patterns.

Character classes (``[abc]``, ranges like ``[a-z]``, and negations like
``[!0-9]``) must work in the anchored and ``**`` matching paths the same way
they already do via ``fnmatch`` for unanchored patterns. These exercise the
``_globstar_to_regex`` translation that previously escaped brackets literally.
"""

from coderev.ignore import CodeRevIgnore, _globstar_to_regex


class TestCharClassRegexBuilder:
    """Direct checks on the glob->regex translation."""

    def test_simple_class(self):
        assert _globstar_to_regex("[abc].py") == "[abc]\\.py"

    def test_range_class(self):
        assert _globstar_to_regex("[a-z].py") == "[a-z]\\.py"

    def test_negated_class(self):
        # '!' becomes regex '^'
        assert _globstar_to_regex("[!0-9].py") == "[^0-9]\\.py"

    def test_unterminated_bracket_is_literal(self):
        # No closing ']' -> '[' treated literally, must not raise.
        assert _globstar_to_regex("a[b") == "a\\[b"

    def test_leading_bracket_literal_in_class(self):
        # A ']' right after '[' is a literal member of the class.
        assert _globstar_to_regex("[]x]") == "[]x]"


class TestCharClassMatching:
    """End-to-end matching through should_ignore."""

    def test_anchored_class_matches(self):
        ignore = CodeRevIgnore(["/src/test_[0-9].py"])
        assert ignore.should_ignore("src/test_3.py") is True
        assert ignore.should_ignore("src/test_x.py") is False

    def test_anchored_class_does_not_cross_directories(self):
        ignore = CodeRevIgnore(["/src/[abc].py"])
        assert ignore.should_ignore("src/a.py") is True
        # The class matches a single char, not a directory separator.
        assert ignore.should_ignore("src/sub/a.py") is False

    def test_range_class_in_internal_anchored_pattern(self):
        ignore = CodeRevIgnore(["gen/file[0-9].o"])
        assert ignore.should_ignore("gen/file7.o") is True
        assert ignore.should_ignore("gen/fileX.o") is False

    def test_negated_class(self):
        ignore = CodeRevIgnore(["/log[!0-9].txt"])
        assert ignore.should_ignore("loga.txt") is True
        assert ignore.should_ignore("log5.txt") is False

    def test_class_with_globstar(self):
        ignore = CodeRevIgnore(["docs/**/draft_[a-z].md"])
        assert ignore.should_ignore("docs/draft_a.md") is True
        assert ignore.should_ignore("docs/2026/q1/draft_z.md") is True
        assert ignore.should_ignore("docs/draft_1.md") is False

    def test_negation_with_char_class(self):
        # Last matching rule wins; a '!' rule re-includes.
        ignore = CodeRevIgnore(["/data/[a-z].csv", "!/data/[k].csv"])
        assert ignore.should_ignore("data/a.csv") is True
        assert ignore.should_ignore("data/k.csv") is False
