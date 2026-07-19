"""Regression tests for out-of-order fix application in AutoFixer.

Suggestions are considered in severity order (so the highest-severity fix wins
an overlap), but they must be *spliced* bottom-up. The original implementation
applied them in severity order while carrying a single cumulative `line_offset`,
which is only correct when each successive fix sits below the previous one. When
a later fix sat above an earlier one that changed the line count, the offset
shifted it onto the wrong lines and silently mangled unrelated source.
"""

from __future__ import annotations

import pytest

from coderev.autofix import AutoFixer
from coderev.reviewer import Category, InlineSuggestion, Severity


def make_code(n: int = 8) -> str:
    return "".join(f"line{i}\n" for i in range(1, n + 1))


def suggestion(
    start: int,
    end: int,
    replacement: str,
    severity: Severity = Severity.MEDIUM,
    category: Category = Category.BUG,
) -> InlineSuggestion:
    return InlineSuggestion(
        start_line=start,
        end_line=end,
        original_code="",
        suggested_code=replacement,
        explanation=f"fix L{start}-{end}",
        severity=severity,
        category=category,
    )


class TestOutOfOrderApplication:
    """A lower-severity fix above a line-count-changing higher-severity fix."""

    def test_shrinking_fix_below_does_not_shift_fix_above(self):
        code = make_code(8)
        # HIGH collapses lines 5-6 into one line (delta -1); LOW targets line 2.
        suggestions = [
            suggestion(5, 6, "MERGED\n", Severity.HIGH),
            suggestion(2, 2, "FIXED2\n", Severity.LOW, Category.STYLE),
        ]

        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, suggestions)

        assert skipped == []
        assert len(applied) == 2
        assert fixed == (
            "line1\nFIXED2\nline3\nline4\nMERGED\nline7\nline8\n"
        )

    def test_growing_fix_below_does_not_shift_fix_above(self):
        code = make_code(6)
        # HIGH expands line 5 into three lines (delta +2); LOW targets line 1.
        suggestions = [
            suggestion(5, 5, "A\nB\nC\n", Severity.HIGH),
            suggestion(1, 1, "FIRST\n", Severity.LOW, Category.STYLE),
        ]

        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, suggestions)

        assert skipped == []
        assert fixed == "FIRST\nline2\nline3\nline4\nA\nB\nC\nline6\n"

    def test_many_interleaved_fixes_land_on_their_own_lines(self):
        code = make_code(10)
        # Deliberately mixed severities so severity order != line order.
        suggestions = [
            suggestion(9, 10, "NINE_TEN\n", Severity.CRITICAL),
            suggestion(6, 6, "SIX\nSIX_B\n", Severity.HIGH),
            suggestion(3, 3, "THREE\n", Severity.MEDIUM),
            suggestion(1, 1, "ONE\n", Severity.LOW, Category.STYLE),
        ]

        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, suggestions)

        assert skipped == []
        assert len(applied) == 4
        assert fixed == (
            "ONE\nline2\nTHREE\nline4\nline5\nSIX\nSIX_B\nline7\nline8\nNINE_TEN\n"
        )

    def test_no_original_line_is_lost_when_fix_above_is_last(self):
        """The exact corruption the old code produced: line1 was destroyed."""
        code = make_code(8)
        suggestions = [
            suggestion(5, 6, "MERGED\n", Severity.HIGH),
            suggestion(2, 2, "FIXED2\n", Severity.LOW, Category.STYLE),
        ]

        fixed, _, _ = AutoFixer()._apply_suggestions(code, suggestions)

        assert fixed.startswith("line1\n")
        assert "line2\n" not in fixed  # line2 is the one that was replaced


class TestOrderingPreservesExistingBehavior:
    """Bottom-up splicing must not regress the previously-correct cases."""

    def test_in_order_fixes_still_apply(self):
        code = make_code(6)
        suggestions = [
            suggestion(2, 2, "TWO\n", Severity.HIGH),
            suggestion(5, 5, "FIVE\n", Severity.LOW, Category.STYLE),
        ]

        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, suggestions)

        assert skipped == []
        assert fixed == "line1\nTWO\nline3\nline4\nFIVE\nline6\n"

    def test_higher_severity_still_wins_overlap(self):
        code = make_code(6)
        suggestions = [
            suggestion(3, 4, "WINNER\n", Severity.CRITICAL),
            suggestion(4, 5, "LOSER\n", Severity.LOW, Category.STYLE),
        ]

        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, suggestions)

        assert len(applied) == 1
        assert applied[0].explanation == "fix L3-4"
        assert len(skipped) == 1
        assert "Overlaps" in skipped[0][1]
        assert fixed == "line1\nline2\nWINNER\nline5\nline6\n"

    def test_applied_list_is_reported_in_severity_order(self):
        code = make_code(8)
        suggestions = [
            suggestion(6, 6, "SIX\n", Severity.LOW, Category.STYLE),
            suggestion(2, 2, "TWO\n", Severity.CRITICAL),
        ]

        _, applied, _ = AutoFixer()._apply_suggestions(code, suggestions)

        assert [s.severity for s in applied] == [Severity.CRITICAL, Severity.LOW]

    def test_out_of_range_line_numbers_are_skipped_not_applied(self):
        code = make_code(3)
        suggestions = [
            suggestion(2, 2, "TWO\n", Severity.HIGH),
            suggestion(5, 6, "NOPE\n", Severity.CRITICAL),
        ]

        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, suggestions)

        assert len(applied) == 1
        assert len(skipped) == 1
        assert "out of range" in skipped[0][1]
        assert fixed == "line1\nTWO\nline3\n"

    def test_out_of_range_check_uses_original_line_count(self):
        """A shrinking fix must not make a valid later fix look out of range."""
        code = make_code(6)
        suggestions = [
            # Collapses 3 lines into 1, shortening the buffer to 4 lines.
            suggestion(1, 3, "ONLY\n", Severity.CRITICAL),
            # Line 6 is valid in the original code and must still apply.
            suggestion(6, 6, "SIX\n", Severity.LOW, Category.STYLE),
        ]

        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, suggestions)

        assert skipped == []
        assert len(applied) == 2
        assert fixed == "ONLY\nline4\nline5\nSIX\n"

    def test_file_without_trailing_newline_is_preserved(self):
        code = "line1\nline2\nline3"
        suggestions = [
            suggestion(3, 3, "LAST", Severity.HIGH),
            suggestion(1, 1, "FIRST\n", Severity.LOW, Category.STYLE),
        ]

        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, suggestions)

        assert skipped == []
        assert fixed == "FIRST\nline2\nLAST"

    def test_no_suggestions_returns_code_unchanged(self):
        code = make_code(3)
        fixed, applied, skipped = AutoFixer()._apply_suggestions(code, [])
        assert fixed == code
        assert applied == []
        assert skipped == []
