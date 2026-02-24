"""Auto-fix functionality for code review suggestions.

This module provides the ability to automatically apply code review
suggestions to source files, transforming identified issues into fixes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coderev.reviewer import (
    CodeReviewer,
    InlineSuggestion,
    ReviewResult,
    Severity,
    is_binary_file,
    BinaryFileError,
)


@dataclass
class FixResult:
    """Result of applying auto-fixes to a file."""
    
    file_path: str
    original_code: str
    fixed_code: str
    applied_fixes: list[InlineSuggestion] = field(default_factory=list)
    skipped_fixes: list[tuple[InlineSuggestion, str]] = field(default_factory=list)
    
    @property
    def total_fixes(self) -> int:
        """Total number of fixes applied."""
        return len(self.applied_fixes)
    
    @property
    def has_changes(self) -> bool:
        """Check if any changes were made."""
        return self.original_code != self.fixed_code
    
    @property
    def diff_lines(self) -> list[str]:
        """Generate a simple diff showing changes."""
        import difflib
        
        original_lines = self.original_code.splitlines(keepends=True)
        fixed_lines = self.fixed_code.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            fixed_lines,
            fromfile=f"a/{Path(self.file_path).name}",
            tofile=f"b/{Path(self.file_path).name}",
        )
        return list(diff)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "file_path": self.file_path,
            "total_fixes": self.total_fixes,
            "has_changes": self.has_changes,
            "applied_fixes": [
                {
                    "line_range": f.line_range,
                    "explanation": f.explanation,
                    "severity": f.severity.value,
                    "category": f.category.value,
                }
                for f in self.applied_fixes
            ],
            "skipped_fixes": [
                {
                    "line_range": f.line_range,
                    "explanation": f.explanation,
                    "reason": reason,
                }
                for f, reason in self.skipped_fixes
            ],
        }


class AutoFixer:
    """Applies code review suggestions to automatically fix issues.
    
    The AutoFixer reviews code to get inline suggestions, then applies
    those suggestions to generate fixed code. It handles overlapping
    suggestions by prioritizing higher-severity issues.
    
    Example:
        fixer = AutoFixer()
        result = fixer.fix_file("main.py")
        
        if result.has_changes:
            print(f"Applied {result.total_fixes} fixes")
            # Preview the diff
            for line in result.diff_lines:
                print(line, end="")
            # Write changes
            result.write()
    """
    
    def __init__(
        self,
        reviewer: CodeReviewer | None = None,
        min_severity: Severity = Severity.LOW,
        categories: list[str] | None = None,
        interactive: bool = False,
    ):
        """Initialize the AutoFixer.
        
        Args:
            reviewer: CodeReviewer instance to use. If not provided, creates one.
            min_severity: Minimum severity level to apply fixes for.
            categories: List of categories to fix (e.g., ['bug', 'security']).
                       If None, fixes all categories.
            interactive: If True, prompt before applying each fix.
        """
        self.reviewer = reviewer
        self.min_severity = min_severity
        self.categories = [c.lower() for c in categories] if categories else None
        self.interactive = interactive
    
    def _get_reviewer(self) -> CodeReviewer:
        """Get or create a CodeReviewer instance."""
        if self.reviewer is None:
            from coderev.config import Config
            config = Config.load()
            self.reviewer = CodeReviewer(config=config)
        return self.reviewer
    
    def _should_apply_fix(self, suggestion: InlineSuggestion) -> tuple[bool, str]:
        """Determine if a suggestion should be applied.
        
        Returns:
            Tuple of (should_apply, reason_if_not).
        """
        # Check severity threshold
        if suggestion.severity.weight < self.min_severity.weight:
            return False, f"Severity {suggestion.severity.value} below threshold {self.min_severity.value}"
        
        # Check category filter
        if self.categories and suggestion.category.value.lower() not in self.categories:
            return False, f"Category {suggestion.category.value} not in filter list"
        
        # Check if suggestion has actual code changes
        if not suggestion.suggested_code or not suggestion.suggested_code.strip():
            return False, "No suggested code provided"
        
        return True, ""
    
    def _apply_suggestions(
        self,
        code: str,
        suggestions: list[InlineSuggestion],
    ) -> tuple[str, list[InlineSuggestion], list[tuple[InlineSuggestion, str]]]:
        """Apply suggestions to code, handling overlaps.
        
        Args:
            code: Original source code.
            suggestions: List of inline suggestions to apply.
            
        Returns:
            Tuple of (fixed_code, applied_suggestions, skipped_suggestions).
        """
        if not suggestions:
            return code, [], []
        
        lines = code.splitlines(keepends=True)
        
        # If code doesn't end with newline, track it
        ends_with_newline = code.endswith('\n') if code else False
        if lines and not lines[-1].endswith('\n'):
            # Add newline to last line for consistent processing
            pass
        
        # Sort by severity (highest first) then by line number
        sorted_suggestions = sorted(
            suggestions,
            key=lambda s: (-s.severity.weight, s.start_line),
        )
        
        applied: list[InlineSuggestion] = []
        skipped: list[tuple[InlineSuggestion, str]] = []
        
        # Track which lines have been modified
        modified_lines: set[int] = set()
        
        # Track line offset due to insertions/deletions
        line_offset = 0
        
        for suggestion in sorted_suggestions:
            # Check if we should apply this fix
            should_apply, reason = self._should_apply_fix(suggestion)
            if not should_apply:
                skipped.append((suggestion, reason))
                continue
            
            # Check for overlap with already-modified lines
            affected_range = range(suggestion.start_line, suggestion.end_line + 1)
            if any(line in modified_lines for line in affected_range):
                skipped.append((suggestion, "Overlaps with already-applied fix"))
                continue
            
            # Apply the fix
            try:
                # Adjust line numbers for offset
                start_idx = suggestion.start_line - 1 + line_offset
                end_idx = suggestion.end_line + line_offset
                
                if start_idx < 0 or end_idx > len(lines):
                    skipped.append((suggestion, f"Line numbers out of range"))
                    continue
                
                # Get the original lines being replaced
                original_lines = lines[start_idx:end_idx]
                
                # Prepare the replacement
                suggested_lines = suggestion.suggested_code.splitlines(keepends=True)
                
                # Ensure suggested lines end with newlines (except possibly last)
                if suggested_lines and not suggested_lines[-1].endswith('\n'):
                    # Check if original last line had a newline
                    if original_lines and original_lines[-1].endswith('\n'):
                        suggested_lines[-1] += '\n'
                
                # Replace lines
                lines[start_idx:end_idx] = suggested_lines
                
                # Update offset for future fixes
                original_count = end_idx - start_idx
                new_count = len(suggested_lines)
                line_offset += new_count - original_count
                
                # Mark lines as modified
                for line_num in affected_range:
                    modified_lines.add(line_num)
                
                applied.append(suggestion)
                
            except Exception as e:
                skipped.append((suggestion, f"Error applying fix: {e}"))
        
        # Reconstruct code
        fixed_code = ''.join(lines)
        
        # Ensure consistent newline ending
        if ends_with_newline and not fixed_code.endswith('\n'):
            fixed_code += '\n'
        elif not ends_with_newline and fixed_code.endswith('\n'):
            fixed_code = fixed_code.rstrip('\n')
        
        return fixed_code, applied, skipped
    
    def fix_code(
        self,
        code: str,
        language: str | None = None,
        focus: list[str] | None = None,
        context: str | None = None,
    ) -> FixResult:
        """Review and fix code.
        
        Args:
            code: Source code to fix.
            language: Programming language (optional).
            focus: Focus areas for the review.
            context: Additional context (e.g., file path).
            
        Returns:
            FixResult containing the original and fixed code.
        """
        reviewer = self._get_reviewer()
        
        # Get inline suggestions
        result = reviewer.review_with_inline_suggestions(
            code,
            language=language,
            focus=focus,
            context=context,
        )
        
        # Apply the suggestions
        fixed_code, applied, skipped = self._apply_suggestions(
            code,
            result.inline_suggestions,
        )
        
        return FixResult(
            file_path=context or "<code>",
            original_code=code,
            fixed_code=fixed_code,
            applied_fixes=applied,
            skipped_fixes=skipped,
        )
    
    def fix_file(
        self,
        file_path: Path | str,
        focus: list[str] | None = None,
        write: bool = False,
        backup: bool = True,
    ) -> FixResult:
        """Review and fix a file.
        
        Args:
            file_path: Path to the file to fix.
            focus: Focus areas for the review.
            write: If True, write changes back to file.
            backup: If True and write is True, create a .bak backup first.
            
        Returns:
            FixResult containing the original and fixed code.
            
        Raises:
            FileNotFoundError: If the file doesn't exist.
            BinaryFileError: If the file is binary.
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if is_binary_file(file_path):
            raise BinaryFileError(file_path)
        
        # Read the file
        try:
            code = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise BinaryFileError(
                file_path,
                f"Cannot decode file as UTF-8: {file_path}"
            ) from e
        
        # Detect language
        reviewer = self._get_reviewer()
        language = reviewer._detect_language(file_path)
        
        # Fix the code
        result = self.fix_code(
            code,
            language=language,
            focus=focus,
            context=str(file_path),
        )
        
        # Write changes if requested
        if write and result.has_changes:
            if backup:
                backup_path = file_path.with_suffix(file_path.suffix + ".bak")
                backup_path.write_text(code, encoding="utf-8")
            
            file_path.write_text(result.fixed_code, encoding="utf-8")
        
        return result
    
    def fix_files(
        self,
        file_paths: list[Path | str],
        focus: list[str] | None = None,
        write: bool = False,
        backup: bool = True,
    ) -> dict[str, FixResult]:
        """Review and fix multiple files.
        
        Args:
            file_paths: List of file paths to fix.
            focus: Focus areas for the review.
            write: If True, write changes back to files.
            backup: If True and write is True, create .bak backups.
            
        Returns:
            Dictionary mapping file paths to their fix results.
        """
        results: dict[str, FixResult] = {}
        
        for path in file_paths:
            path = Path(path)
            try:
                results[str(path)] = self.fix_file(
                    path,
                    focus=focus,
                    write=write,
                    backup=backup,
                )
            except (BinaryFileError, FileNotFoundError) as e:
                # Create a result indicating the file was skipped
                results[str(path)] = FixResult(
                    file_path=str(path),
                    original_code="",
                    fixed_code="",
                    applied_fixes=[],
                    skipped_fixes=[],
                )
            except Exception as e:
                # Create a result with error info
                results[str(path)] = FixResult(
                    file_path=str(path),
                    original_code="",
                    fixed_code="",
                    applied_fixes=[],
                    skipped_fixes=[],
                )
        
        return results


def format_fix_diff(result: FixResult, use_color: bool = True) -> str:
    """Format a fix result as a colored diff string.
    
    Args:
        result: The fix result to format.
        use_color: Whether to include ANSI color codes.
        
    Returns:
        Formatted diff string.
    """
    if not result.has_changes:
        return "No changes made."
    
    lines = []
    for line in result.diff_lines:
        if use_color:
            if line.startswith('+') and not line.startswith('+++'):
                lines.append(f"\033[32m{line}\033[0m")  # Green
            elif line.startswith('-') and not line.startswith('---'):
                lines.append(f"\033[31m{line}\033[0m")  # Red
            elif line.startswith('@@'):
                lines.append(f"\033[36m{line}\033[0m")  # Cyan
            else:
                lines.append(line)
        else:
            lines.append(line)
    
    return ''.join(lines)


def format_fix_summary(result: FixResult) -> str:
    """Format a summary of fixes applied.
    
    Args:
        result: The fix result to summarize.
        
    Returns:
        Human-readable summary string.
    """
    lines = [f"File: {result.file_path}"]
    lines.append(f"Fixes applied: {result.total_fixes}")
    lines.append(f"Fixes skipped: {len(result.skipped_fixes)}")
    
    if result.applied_fixes:
        lines.append("\nApplied fixes:")
        for fix in result.applied_fixes:
            lines.append(f"  - {fix.line_range}: [{fix.severity.value}] {fix.explanation}")
    
    if result.skipped_fixes:
        lines.append("\nSkipped fixes:")
        for fix, reason in result.skipped_fixes:
            lines.append(f"  - {fix.line_range}: {reason}")
    
    return '\n'.join(lines)
