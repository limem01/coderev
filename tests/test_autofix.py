"""Tests for auto-fix functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from coderev.autofix import AutoFixer, FixResult, format_fix_diff, format_fix_summary
from coderev.reviewer import (
    InlineSuggestion,
    ReviewResult,
    Severity,
    Category,
    CodeReviewer,
)


class TestFixResult:
    """Tests for FixResult dataclass."""
    
    def test_total_fixes(self):
        """Test total_fixes property."""
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.LOW,
            category=Category.STYLE,
        )
        
        result = FixResult(
            file_path="test.py",
            original_code="x = 1\n",
            fixed_code="x: int = 1\n",
            applied_fixes=[suggestion],
            skipped_fixes=[],
        )
        
        assert result.total_fixes == 1
    
    def test_has_changes_true(self):
        """Test has_changes when code is different."""
        result = FixResult(
            file_path="test.py",
            original_code="x = 1",
            fixed_code="x: int = 1",
            applied_fixes=[],
            skipped_fixes=[],
        )
        
        assert result.has_changes is True
    
    def test_has_changes_false(self):
        """Test has_changes when code is identical."""
        result = FixResult(
            file_path="test.py",
            original_code="x = 1",
            fixed_code="x = 1",
            applied_fixes=[],
            skipped_fixes=[],
        )
        
        assert result.has_changes is False
    
    def test_diff_lines(self):
        """Test diff_lines generation."""
        result = FixResult(
            file_path="test.py",
            original_code="x = 1\n",
            fixed_code="x: int = 1\n",
            applied_fixes=[],
            skipped_fixes=[],
        )
        
        diff = result.diff_lines
        assert any("x = 1" in line for line in diff)
        assert any("x: int = 1" in line for line in diff)
    
    def test_to_dict(self):
        """Test to_dict serialization."""
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.LOW,
            category=Category.STYLE,
        )
        
        result = FixResult(
            file_path="test.py",
            original_code="x = 1\n",
            fixed_code="x: int = 1\n",
            applied_fixes=[suggestion],
            skipped_fixes=[],
        )
        
        data = result.to_dict()
        assert data["file_path"] == "test.py"
        assert data["total_fixes"] == 1
        assert data["has_changes"] is True
        assert len(data["applied_fixes"]) == 1


class TestAutoFixer:
    """Tests for AutoFixer class."""
    
    @pytest.fixture
    def mock_reviewer(self):
        """Create a mock CodeReviewer."""
        reviewer = Mock(spec=CodeReviewer)
        reviewer._detect_language = Mock(return_value="python")
        return reviewer
    
    @pytest.fixture
    def fixer(self, mock_reviewer):
        """Create an AutoFixer with mocked reviewer."""
        return AutoFixer(reviewer=mock_reviewer)
    
    def test_should_apply_fix_passes_all_checks(self, fixer):
        """Test _should_apply_fix when all checks pass."""
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        should_apply, reason = fixer._should_apply_fix(suggestion)
        assert should_apply is True
        assert reason == ""
    
    def test_should_apply_fix_below_severity_threshold(self):
        """Test _should_apply_fix when severity is below threshold."""
        fixer = AutoFixer(min_severity=Severity.HIGH)
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.LOW,
            category=Category.STYLE,
        )
        
        should_apply, reason = fixer._should_apply_fix(suggestion)
        assert should_apply is False
        assert "below threshold" in reason.lower()
    
    def test_should_apply_fix_category_filter(self):
        """Test _should_apply_fix with category filter."""
        fixer = AutoFixer(categories=["bug", "security"])
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        should_apply, reason = fixer._should_apply_fix(suggestion)
        assert should_apply is False
        assert "not in filter" in reason.lower()
    
    def test_should_apply_fix_no_suggested_code(self, fixer):
        """Test _should_apply_fix when no suggested code is provided."""
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="",
            explanation="Add type hint",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        should_apply, reason = fixer._should_apply_fix(suggestion)
        assert should_apply is False
        assert "no suggested code" in reason.lower()
    
    def test_apply_suggestions_single_line(self, fixer):
        """Test applying a single-line suggestion."""
        code = "x = 1\ny = 2\n"
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        fixed_code, applied, skipped = fixer._apply_suggestions(code, [suggestion])
        
        assert "x: int = 1" in fixed_code
        assert "y = 2" in fixed_code
        assert len(applied) == 1
        assert len(skipped) == 0
    
    def test_apply_suggestions_multi_line(self, fixer):
        """Test applying a multi-line suggestion."""
        code = "def foo():\n    pass\n    return None\n"
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=3,
            original_code="def foo():\n    pass\n    return None",
            suggested_code="def foo() -> None:\n    return None",
            explanation="Simplify function",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        fixed_code, applied, skipped = fixer._apply_suggestions(code, [suggestion])
        
        assert "def foo() -> None:" in fixed_code
        assert "pass" not in fixed_code
        assert len(applied) == 1
    
    def test_apply_suggestions_overlapping_prioritizes_severity(self, fixer):
        """Test that overlapping suggestions prioritize higher severity."""
        code = "x = 1\ny = 2\n"
        
        low_fix = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.LOW,
            category=Category.STYLE,
        )
        
        high_fix = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="X_VALUE: int = 1",
            explanation="Use constant naming",
            severity=Severity.HIGH,
            category=Category.STYLE,
        )
        
        # Even if low_fix comes first, high_fix should be applied
        fixed_code, applied, skipped = fixer._apply_suggestions(code, [low_fix, high_fix])
        
        assert "X_VALUE: int = 1" in fixed_code
        assert len(applied) == 1
        assert applied[0].severity == Severity.HIGH
        assert len(skipped) == 1
        assert "overlap" in skipped[0][1].lower()
    
    def test_apply_suggestions_preserves_newline_ending(self, fixer):
        """Test that file ending newline is preserved."""
        code_with_newline = "x = 1\n"
        code_without_newline = "x = 1"
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        fixed_with, _, _ = fixer._apply_suggestions(code_with_newline, [suggestion])
        fixed_without, _, _ = fixer._apply_suggestions(code_without_newline, [suggestion])
        
        assert fixed_with.endswith("\n")
        assert not fixed_without.endswith("\n")
    
    def test_fix_code(self, mock_reviewer, fixer):
        """Test fix_code method."""
        code = "x = 1\n"
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        mock_reviewer.review_with_inline_suggestions.return_value = ReviewResult(
            summary="Review complete",
            issues=[],
            inline_suggestions=[suggestion],
        )
        
        result = fixer.fix_code(code, language="python")
        
        assert result.has_changes
        assert "x: int = 1" in result.fixed_code
        assert result.total_fixes == 1
    
    def test_fix_file(self, mock_reviewer, fixer, tmp_path):
        """Test fix_file method."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        mock_reviewer.review_with_inline_suggestions.return_value = ReviewResult(
            summary="Review complete",
            issues=[],
            inline_suggestions=[suggestion],
        )
        
        result = fixer.fix_file(test_file, write=False)
        
        assert result.has_changes
        assert result.file_path == str(test_file)
        # File should not be modified when write=False
        assert test_file.read_text() == "x = 1\n"
    
    def test_fix_file_with_write(self, mock_reviewer, fixer, tmp_path):
        """Test fix_file with write=True."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        mock_reviewer.review_with_inline_suggestions.return_value = ReviewResult(
            summary="Review complete",
            issues=[],
            inline_suggestions=[suggestion],
        )
        
        result = fixer.fix_file(test_file, write=True, backup=True)
        
        assert result.has_changes
        # File should be modified
        assert "x: int = 1" in test_file.read_text()
        # Backup should exist
        backup_file = tmp_path / "test.py.bak"
        assert backup_file.exists()
        assert backup_file.read_text() == "x = 1\n"
    
    def test_fix_file_not_found(self, fixer):
        """Test fix_file with non-existent file."""
        with pytest.raises(FileNotFoundError):
            fixer.fix_file("nonexistent.py")
    
    def test_fix_files_multiple(self, mock_reviewer, fixer, tmp_path):
        """Test fix_files with multiple files."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("x = 1\n")
        file2.write_text("y = 2\n")
        
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="dummy",
            suggested_code="fixed",
            explanation="Fix",
            severity=Severity.MEDIUM,
            category=Category.STYLE,
        )
        
        mock_reviewer.review_with_inline_suggestions.return_value = ReviewResult(
            summary="Review complete",
            issues=[],
            inline_suggestions=[suggestion],
        )
        
        results = fixer.fix_files([file1, file2], write=False)
        
        assert len(results) == 2
        assert str(file1) in results
        assert str(file2) in results


class TestFormatFunctions:
    """Tests for formatting functions."""
    
    def test_format_fix_diff_no_changes(self):
        """Test format_fix_diff with no changes."""
        result = FixResult(
            file_path="test.py",
            original_code="x = 1",
            fixed_code="x = 1",
            applied_fixes=[],
            skipped_fixes=[],
        )
        
        output = format_fix_diff(result)
        assert "No changes" in output
    
    def test_format_fix_diff_with_changes(self):
        """Test format_fix_diff with changes."""
        result = FixResult(
            file_path="test.py",
            original_code="x = 1\n",
            fixed_code="x: int = 1\n",
            applied_fixes=[],
            skipped_fixes=[],
        )
        
        output = format_fix_diff(result, use_color=False)
        assert "-x = 1" in output
        assert "+x: int = 1" in output
    
    def test_format_fix_summary(self):
        """Test format_fix_summary."""
        suggestion = InlineSuggestion(
            start_line=1,
            end_line=1,
            original_code="x = 1",
            suggested_code="x: int = 1",
            explanation="Add type hint",
            severity=Severity.LOW,
            category=Category.STYLE,
        )
        
        result = FixResult(
            file_path="test.py",
            original_code="x = 1\n",
            fixed_code="x: int = 1\n",
            applied_fixes=[suggestion],
            skipped_fixes=[],
        )
        
        output = format_fix_summary(result)
        assert "test.py" in output
        assert "Fixes applied: 1" in output
        assert "Add type hint" in output


class TestAutoFixerIntegration:
    """Integration tests for AutoFixer (require mocking API calls)."""
    
    @pytest.fixture
    def sample_code(self):
        """Sample Python code with issues."""
        return '''def calculate(x, y):
    result = x + y
    if result == 0:
        return "zero"
    elif result > 0:
        return "positive"
    else:
        return "negative"
'''
    
    def test_fix_preserves_non_modified_code(self, sample_code):
        """Test that unmodified parts of code are preserved."""
        with patch.object(AutoFixer, '_get_reviewer') as mock_get_reviewer:
            mock_reviewer = Mock()
            mock_reviewer.review_with_inline_suggestions.return_value = ReviewResult(
                summary="Review complete",
                issues=[],
                inline_suggestions=[
                    InlineSuggestion(
                        start_line=1,
                        end_line=1,
                        original_code="def calculate(x, y):",
                        suggested_code="def calculate(x: int, y: int) -> str:",
                        explanation="Add type hints",
                        severity=Severity.LOW,
                        category=Category.STYLE,
                    )
                ],
            )
            mock_get_reviewer.return_value = mock_reviewer
            
            fixer = AutoFixer()
            result = fixer.fix_code(sample_code)
            
            # The function signature should be changed
            assert "def calculate(x: int, y: int) -> str:" in result.fixed_code
            # But the rest of the code should be preserved
            assert 'result = x + y' in result.fixed_code
            assert 'return "zero"' in result.fixed_code
            assert 'return "positive"' in result.fixed_code
            assert 'return "negative"' in result.fixed_code
