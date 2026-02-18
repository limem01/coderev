"""Output formatting for CodeRev."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.text import Text
from rich.markdown import Markdown

from coderev.reviewer import ReviewResult, Issue, Severity, InlineSuggestion


SEVERITY_COLORS = {
    Severity.CRITICAL: "red bold",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "blue",
}

SEVERITY_ICONS = {
    Severity.CRITICAL: "[X]",
    Severity.HIGH: "[!]",
    Severity.MEDIUM: "[~]",
    Severity.LOW: "[.]",
}


class OutputFormatter:
    """Base class for output formatters."""
    
    def format(self, result: ReviewResult) -> str:
        raise NotImplementedError


class RichFormatter(OutputFormatter):
    """Rich terminal output formatter."""
    
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
    
    def format(self, result: ReviewResult) -> str:
        """Format is handled via print methods for rich."""
        return ""
    
    def print_result(self, result: ReviewResult, file_path: str | None = None) -> None:
        """Print a review result to the console."""
        # Header
        title = f"Review: {file_path}" if file_path else "Code Review"
        
        # Summary panel
        summary_text = Text()
        summary_text.append(result.summary)
        summary_text.append(f"\n\nScore: {result.score}/100", style="bold")
        
        self.console.print(Panel(summary_text, title=title, border_style="blue"))
        
        # Issues table
        if result.issues:
            self.console.print()
            self._print_issues(result.issues)
        
        # Positive feedback
        if result.positive:
            self.console.print()
            self._print_positive(result.positive)
    
    def _print_issues(self, issues: list[Issue]) -> None:
        """Print issues in a table."""
        table = Table(title="Issues Found", show_lines=True)
        table.add_column("Sev", width=4)
        table.add_column("Line", width=8)
        table.add_column("Category", width=12)
        table.add_column("Issue")
        table.add_column("Suggestion")
        
        # Sort by severity
        sorted_issues = sorted(issues, key=lambda i: -i.severity.weight)
        
        for issue in sorted_issues:
            sev_style = SEVERITY_COLORS.get(issue.severity, "white")
            sev_icon = SEVERITY_ICONS.get(issue.severity, "[-]")
            
            line_str = ""
            if issue.line:
                line_str = str(issue.line)
                if issue.end_line and issue.end_line != issue.line:
                    line_str += f"-{issue.end_line}"
            
            table.add_row(
                Text(sev_icon, style=sev_style),
                line_str,
                issue.category.value,
                issue.message,
                issue.suggestion or "",
            )
        
        self.console.print(table)
    
    def _print_positive(self, positive: list[str]) -> None:
        """Print positive feedback."""
        panel_content = "\n".join(f"+ {item}" for item in positive)
        self.console.print(
            Panel(panel_content, title="What's Good", border_style="green")
        )
    
    def print_summary(self, results: dict[str, ReviewResult]) -> None:
        """Print summary for multiple files."""
        total_issues = sum(len(r.issues) for r in results.values())
        critical = sum(r.critical_count for r in results.values())
        high = sum(r.high_count for r in results.values())
        avg_score = sum(r.score for r in results.values()) / len(results) if results else 0
        
        summary = Table(title="Review Summary")
        summary.add_column("Metric")
        summary.add_column("Value", justify="right")
        
        summary.add_row("Files Reviewed", str(len(results)))
        summary.add_row("Total Issues", str(total_issues))
        summary.add_row("Critical Issues", Text(str(critical), style="red bold"))
        summary.add_row("High Issues", Text(str(high), style="red"))
        summary.add_row("Average Score", f"{avg_score:.1f}/100")
        
        self.console.print(summary)


class JsonFormatter(OutputFormatter):
    """JSON output formatter."""
    
    def format(self, result: ReviewResult) -> str:
        output = {
            "summary": result.summary,
            "score": result.score,
            "issues": [
                {
                    "line": issue.line,
                    "end_line": issue.end_line,
                    "file": issue.file,
                    "severity": issue.severity.value,
                    "category": issue.category.value,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                    "code_suggestion": issue.code_suggestion,
                }
                for issue in result.issues
            ],
            "positive": result.positive,
        }
        
        if result.verdict:
            output["verdict"] = result.verdict
        
        return json.dumps(output, indent=2)
    
    def format_multiple(self, results: dict[str, ReviewResult]) -> str:
        return json.dumps(
            {path: json.loads(self.format(result)) for path, result in results.items()},
            indent=2,
        )


class MarkdownFormatter(OutputFormatter):
    """Markdown output formatter."""
    
    def format(self, result: ReviewResult) -> str:
        lines = []
        lines.append("# Code Review Report\n")
        lines.append(f"**Score:** {result.score}/100\n")
        lines.append(f"## Summary\n\n{result.summary}\n")
        
        if result.issues:
            lines.append("## Issues\n")
            
            for issue in sorted(result.issues, key=lambda i: -i.severity.weight):
                severity_badge = {
                    Severity.CRITICAL: "🔴 CRITICAL",
                    Severity.HIGH: "🟠 HIGH",
                    Severity.MEDIUM: "🟡 MEDIUM",
                    Severity.LOW: "🔵 LOW",
                }.get(issue.severity, "")
                
                line_info = f" (Line {issue.line})" if issue.line else ""
                
                lines.append(f"### {severity_badge}{line_info}\n")
                lines.append(f"**Category:** {issue.category.value}\n")
                lines.append(f"{issue.message}\n")
                
                if issue.suggestion:
                    lines.append(f"**Suggestion:** {issue.suggestion}\n")
                
                if issue.code_suggestion:
                    lines.append(f"```\n{issue.code_suggestion}\n```\n")
        
        if result.positive:
            lines.append("## What's Good\n")
            for item in result.positive:
                lines.append(f"- {item}\n")
        
        return "\n".join(lines)


class SarifFormatter(OutputFormatter):
    """SARIF output formatter for GitHub Security integration."""
    
    SARIF_VERSION = "2.1.0"
    TOOL_NAME = "coderev"
    TOOL_VERSION = "0.3.2"
    
    def format(self, result: ReviewResult) -> str:
        sarif: dict[str, Any] = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": self.SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": self.TOOL_NAME,
                            "version": self.TOOL_VERSION,
                            "informationUri": "https://github.com/khalil/coderev",
                            "rules": self._generate_rules(result.issues),
                        }
                    },
                    "results": self._generate_results(result.issues),
                }
            ],
        }
        
        return json.dumps(sarif, indent=2)
    
    def _severity_to_level(self, severity: Severity) -> str:
        mapping = {
            Severity.CRITICAL: "error",
            Severity.HIGH: "error",
            Severity.MEDIUM: "warning",
            Severity.LOW: "note",
        }
        return mapping.get(severity, "warning")
    
    def _generate_rules(self, issues: list[Issue]) -> list[dict[str, Any]]:
        seen_categories: set[str] = set()
        rules = []
        
        for issue in issues:
            rule_id = f"coderev/{issue.category.value}"
            if rule_id not in seen_categories:
                seen_categories.add(rule_id)
                rules.append({
                    "id": rule_id,
                    "shortDescription": {"text": f"{issue.category.value.title()} Issue"},
                    "helpUri": "https://github.com/khalil/coderev/docs/rules",
                })
        
        return rules
    
    def _generate_results(self, issues: list[Issue]) -> list[dict[str, Any]]:
        results = []
        
        for issue in issues:
            result: dict[str, Any] = {
                "ruleId": f"coderev/{issue.category.value}",
                "level": self._severity_to_level(issue.severity),
                "message": {"text": issue.message},
            }
            
            if issue.file and issue.line:
                result["locations"] = [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": issue.file},
                            "region": {
                                "startLine": issue.line,
                                "endLine": issue.end_line or issue.line,
                            },
                        }
                    }
                ]
            
            if issue.suggestion:
                result["fixes"] = [
                    {
                        "description": {"text": issue.suggestion},
                    }
                ]
            
            results.append(result)
        
        return results


class InlineFormatter(OutputFormatter):
    """Formatter for line-by-line inline suggestions.
    
    Displays code suggestions in a diff-like format, showing the original
    code alongside the suggested improvements with context.
    """
    
    def __init__(self, context_lines: int = 2, colorize: bool = True):
        """Initialize the inline formatter.
        
        Args:
            context_lines: Number of context lines to show around each suggestion.
            colorize: Whether to include ANSI color codes in output.
        """
        self.context_lines = context_lines
        self.colorize = colorize
    
    def format(self, result: ReviewResult, source_code: str | None = None) -> str:
        """Format review results with inline suggestions.
        
        Args:
            result: The review result containing inline suggestions.
            source_code: Optional source code for displaying context.
            
        Returns:
            Formatted string with inline suggestions in diff-like format.
        """
        lines = []
        
        # Header
        lines.append("=" * 60)
        lines.append(f"Code Review - Score: {result.score}/100")
        lines.append("=" * 60)
        lines.append("")
        
        # Summary
        lines.append(f"Summary: {result.summary}")
        lines.append("")
        
        # Inline suggestions
        if result.inline_suggestions:
            lines.append("-" * 60)
            lines.append(f"INLINE SUGGESTIONS ({len(result.inline_suggestions)} found)")
            lines.append("-" * 60)
            lines.append("")
            
            for i, suggestion in enumerate(result.suggestions_by_line(), 1):
                lines.extend(self._format_suggestion(i, suggestion, source_code))
                lines.append("")
        else:
            lines.append("No inline suggestions - code looks good!")
        
        # Positive feedback
        if result.positive:
            lines.append("-" * 60)
            lines.append("WHAT'S GOOD")
            lines.append("-" * 60)
            for item in result.positive:
                lines.append(f"  + {item}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_suggestion(
        self, 
        index: int, 
        suggestion: InlineSuggestion,
        source_code: str | None = None
    ) -> list[str]:
        """Format a single inline suggestion.
        
        Args:
            index: Suggestion number for display.
            suggestion: The inline suggestion to format.
            source_code: Optional source code for context display.
            
        Returns:
            List of formatted lines.
        """
        lines = []
        
        # Severity indicator
        severity_markers = {
            Severity.CRITICAL: "[!!]",
            Severity.HIGH: "[! ]",
            Severity.MEDIUM: "[~ ]",
            Severity.LOW: "[. ]",
        }
        marker = severity_markers.get(suggestion.severity, "[  ]")
        
        # Header line
        lines.append(f"{marker} #{index} {suggestion.line_range} [{suggestion.category.value}]")
        lines.append(f"    {suggestion.explanation}")
        lines.append("")
        
        # Original code (with minus prefix)
        lines.append("    Original:")
        for line in suggestion.original_code.split('\n'):
            if self.colorize:
                lines.append(f"    \033[91m- {line}\033[0m")
            else:
                lines.append(f"    - {line}")
        
        # Suggested code (with plus prefix)
        lines.append("    Suggested:")
        for line in suggestion.suggested_code.split('\n'):
            if self.colorize:
                lines.append(f"    \033[92m+ {line}\033[0m")
            else:
                lines.append(f"    + {line}")
        
        return lines
    
    def format_with_source(self, result: ReviewResult, source_code: str) -> str:
        """Format suggestions showing them inline with the source code.
        
        This creates a unified view where suggestions are shown in context
        within the original source code.
        
        Args:
            result: The review result containing inline suggestions.
            source_code: The original source code.
            
        Returns:
            Formatted string with suggestions shown inline.
        """
        lines = []
        source_lines = source_code.split('\n')
        
        # Build a map of line numbers to suggestions
        suggestion_map: dict[int, list[InlineSuggestion]] = {}
        for suggestion in result.inline_suggestions:
            for line_num in range(suggestion.start_line, suggestion.end_line + 1):
                if line_num not in suggestion_map:
                    suggestion_map[line_num] = []
                suggestion_map[line_num].append(suggestion)
        
        # Header
        lines.append("=" * 70)
        lines.append(f"Code Review with Inline Suggestions - Score: {result.score}/100")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"Summary: {result.summary}")
        lines.append("")
        lines.append("-" * 70)
        lines.append("")
        
        # Track which suggestions we've shown
        shown_suggestions: set[int] = set()
        
        for line_num, line in enumerate(source_lines, 1):
            # Check if this line has a suggestion
            if line_num in suggestion_map:
                for suggestion in suggestion_map[line_num]:
                    # Only show each suggestion once (at its start line)
                    suggestion_id = id(suggestion)
                    if suggestion_id not in shown_suggestions and suggestion.start_line == line_num:
                        shown_suggestions.add(suggestion_id)
                        
                        # Add a comment-style annotation
                        sev_abbrev = {
                            Severity.CRITICAL: "CRIT",
                            Severity.HIGH: "HIGH", 
                            Severity.MEDIUM: "MED",
                            Severity.LOW: "LOW",
                        }
                        sev = sev_abbrev.get(suggestion.severity, "???")
                        
                        lines.append(f"{'':>4} | ")
                        lines.append(f"{'':>4} |  >>> [{sev}] {suggestion.explanation}")
                        lines.append(f"{'':>4} |  >>> Replace with:")
                        for suggested_line in suggestion.suggested_code.split('\n'):
                            if self.colorize:
                                lines.append(f"{'':>4} |  \033[92m+   {suggested_line}\033[0m")
                            else:
                                lines.append(f"{'':>4} |  +   {suggested_line}")
                        lines.append(f"{'':>4} | ")
            
            # Print the actual line (with marker if it's part of a suggestion)
            has_suggestion = line_num in suggestion_map
            marker = "*" if has_suggestion else " "
            
            if has_suggestion and self.colorize:
                lines.append(f"{line_num:>4}{marker}| \033[91m{line}\033[0m")
            else:
                lines.append(f"{line_num:>4}{marker}| {line}")
        
        return "\n".join(lines)


class RichInlineFormatter:
    """Rich terminal output formatter for inline suggestions."""
    
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
    
    def print_inline_suggestions(
        self, 
        result: ReviewResult, 
        file_path: str | None = None,
        source_code: str | None = None
    ) -> None:
        """Print inline suggestions with rich formatting.
        
        Args:
            result: ReviewResult containing inline suggestions.
            file_path: Optional file path for the header.
            source_code: Optional source code for syntax highlighting.
        """
        # Header
        title = f"Inline Suggestions: {file_path}" if file_path else "Inline Code Suggestions"
        
        summary_text = Text()
        summary_text.append(result.summary)
        summary_text.append(f"\n\nScore: {result.score}/100", style="bold")
        summary_text.append(f"\n{len(result.inline_suggestions)} suggestions", style="dim")
        
        self.console.print(Panel(summary_text, title=title, border_style="blue"))
        
        # Suggestions
        if result.inline_suggestions:
            for i, suggestion in enumerate(result.suggestions_by_line(), 1):
                self._print_suggestion(i, suggestion)
        else:
            self.console.print("[green]No suggestions - code looks good![/green]")
        
        # Positive feedback
        if result.positive:
            self.console.print()
            content = "\n".join(f"+ {item}" for item in result.positive)
            self.console.print(Panel(content, title="What's Good", border_style="green"))
    
    def _print_suggestion(self, index: int, suggestion: InlineSuggestion) -> None:
        """Print a single suggestion with rich formatting."""
        self.console.print()
        
        sev_style = SEVERITY_COLORS.get(suggestion.severity, "white")
        sev_icon = SEVERITY_ICONS.get(suggestion.severity, "[-]")
        
        # Header
        header = Text()
        header.append(f"{sev_icon} ", style=sev_style)
        header.append(f"#{index} ", style="bold")
        header.append(f"{suggestion.line_range} ", style="cyan")
        header.append(f"[{suggestion.category.value}]", style="dim")
        
        self.console.print(header)
        self.console.print(f"   {suggestion.explanation}")
        
        # Create a table for the diff view
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("", width=3)
        table.add_column("")
        
        # Original code
        for line in suggestion.original_code.split('\n'):
            table.add_row(Text("-", style="red"), Text(line, style="red"))
        
        # Suggested code
        for line in suggestion.suggested_code.split('\n'):
            table.add_row(Text("+", style="green"), Text(line, style="green"))
        
        self.console.print(table)


def get_formatter(format_type: str) -> OutputFormatter:
    """Get the appropriate formatter for the output type."""
    formatters = {
        "json": JsonFormatter,
        "markdown": MarkdownFormatter,
        "sarif": SarifFormatter,
        "rich": RichFormatter,
        "inline": InlineFormatter,
    }
    
    formatter_class = formatters.get(format_type.lower())
    if not formatter_class:
        raise ValueError(f"Unknown format: {format_type}. Valid: {list(formatters.keys())}")
    
    return formatter_class()
