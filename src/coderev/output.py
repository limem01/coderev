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

from coderev.reviewer import ReviewResult, Issue, Severity


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


def get_formatter(format_type: str) -> OutputFormatter:
    """Get the appropriate formatter for the output type."""
    formatters = {
        "json": JsonFormatter,
        "markdown": MarkdownFormatter,
        "sarif": SarifFormatter,
        "rich": RichFormatter,
    }
    
    formatter_class = formatters.get(format_type.lower())
    if not formatter_class:
        raise ValueError(f"Unknown format: {format_type}. Valid: {list(formatters.keys())}")
    
    return formatter_class()
