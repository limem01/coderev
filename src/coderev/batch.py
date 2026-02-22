"""Batch review functionality with summary report generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from coderev.reviewer import ReviewResult, Issue, Severity, Category


@dataclass
class FileReviewSummary:
    """Summary of a single file's review."""
    
    file_path: str
    score: int
    total_issues: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    status: str  # "reviewed", "skipped", "error"
    error_message: str | None = None
    top_categories: list[str] = field(default_factory=list)
    
    @classmethod
    def from_result(cls, file_path: str, result: ReviewResult) -> "FileReviewSummary":
        """Create a FileReviewSummary from a ReviewResult."""
        if result.score < 0:
            # Skipped file
            return cls(
                file_path=file_path,
                score=0,
                total_issues=0,
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
                status="skipped",
                error_message=result.summary,
            )
        
        # Count issues by category
        category_counts: dict[str, int] = {}
        for issue in result.issues:
            cat = issue.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        # Sort categories by count
        top_categories = sorted(category_counts.keys(), key=lambda c: -category_counts[c])[:3]
        
        return cls(
            file_path=file_path,
            score=result.score,
            total_issues=len(result.issues),
            critical_count=result.critical_count,
            high_count=result.high_count,
            medium_count=sum(1 for i in result.issues if i.severity == Severity.MEDIUM),
            low_count=sum(1 for i in result.issues if i.severity == Severity.LOW),
            status="reviewed",
            top_categories=top_categories,
        )


@dataclass
class BatchReviewReport:
    """Comprehensive batch review report with aggregated statistics."""
    
    timestamp: datetime
    files_reviewed: int
    files_skipped: int
    files_errored: int
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    average_score: float
    min_score: int
    max_score: int
    file_summaries: list[FileReviewSummary] = field(default_factory=list)
    issues_by_category: dict[str, int] = field(default_factory=dict)
    issues_by_severity: dict[str, int] = field(default_factory=dict)
    worst_files: list[str] = field(default_factory=list)
    best_files: list[str] = field(default_factory=list)
    all_issues: list[tuple[str, Issue]] = field(default_factory=list)  # (file_path, issue) pairs
    
    @classmethod
    def from_results(cls, results: dict[str, ReviewResult]) -> "BatchReviewReport":
        """Create a BatchReviewReport from a dictionary of results."""
        file_summaries = []
        all_issues: list[tuple[str, Issue]] = []
        issues_by_category: dict[str, int] = {}
        issues_by_severity: dict[str, int] = {}
        
        reviewed_scores = []
        files_reviewed = 0
        files_skipped = 0
        files_errored = 0
        total_issues = 0
        critical_issues = 0
        high_issues = 0
        medium_issues = 0
        low_issues = 0
        
        for file_path, result in results.items():
            summary = FileReviewSummary.from_result(file_path, result)
            file_summaries.append(summary)
            
            if summary.status == "skipped":
                files_skipped += 1
            elif summary.status == "error":
                files_errored += 1
            else:
                files_reviewed += 1
                reviewed_scores.append(summary.score)
                total_issues += summary.total_issues
                critical_issues += summary.critical_count
                high_issues += summary.high_count
                medium_issues += summary.medium_count
                low_issues += summary.low_count
                
                # Aggregate issues
                for issue in result.issues:
                    all_issues.append((file_path, issue))
                    cat = issue.category.value
                    sev = issue.severity.value
                    issues_by_category[cat] = issues_by_category.get(cat, 0) + 1
                    issues_by_severity[sev] = issues_by_severity.get(sev, 0) + 1
        
        # Calculate statistics
        avg_score = sum(reviewed_scores) / len(reviewed_scores) if reviewed_scores else 0.0
        min_score = min(reviewed_scores) if reviewed_scores else 0
        max_score = max(reviewed_scores) if reviewed_scores else 0
        
        # Sort files by score to find worst/best
        reviewed_summaries = [s for s in file_summaries if s.status == "reviewed"]
        sorted_by_score = sorted(reviewed_summaries, key=lambda s: s.score)
        
        worst_files = [s.file_path for s in sorted_by_score[:5]]
        best_files = [s.file_path for s in sorted_by_score[-5:][::-1]]
        
        return cls(
            timestamp=datetime.now(),
            files_reviewed=files_reviewed,
            files_skipped=files_skipped,
            files_errored=files_errored,
            total_issues=total_issues,
            critical_issues=critical_issues,
            high_issues=high_issues,
            medium_issues=medium_issues,
            low_issues=low_issues,
            average_score=avg_score,
            min_score=min_score,
            max_score=max_score,
            file_summaries=file_summaries,
            issues_by_category=issues_by_category,
            issues_by_severity=issues_by_severity,
            worst_files=worst_files,
            best_files=best_files,
            all_issues=all_issues,
        )
    
    @property
    def total_files(self) -> int:
        """Total number of files processed."""
        return self.files_reviewed + self.files_skipped + self.files_errored
    
    @property
    def health_grade(self) -> str:
        """Calculate an overall health grade for the codebase."""
        if self.average_score >= 90:
            return "A"
        elif self.average_score >= 80:
            return "B"
        elif self.average_score >= 70:
            return "C"
        elif self.average_score >= 60:
            return "D"
        else:
            return "F"
    
    @property
    def has_blocking_issues(self) -> bool:
        """Check if there are any critical or high severity issues."""
        return self.critical_issues > 0 or self.high_issues > 0
    
    def get_issues_for_file(self, file_path: str) -> list[Issue]:
        """Get all issues for a specific file."""
        return [issue for fp, issue in self.all_issues if fp == file_path]
    
    def top_issues(self, limit: int = 10) -> list[tuple[str, Issue]]:
        """Get the top issues sorted by severity."""
        sorted_issues = sorted(
            self.all_issues,
            key=lambda x: -x[1].severity.weight
        )
        return sorted_issues[:limit]
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "summary": {
                "total_files": self.total_files,
                "files_reviewed": self.files_reviewed,
                "files_skipped": self.files_skipped,
                "files_errored": self.files_errored,
                "total_issues": self.total_issues,
                "critical_issues": self.critical_issues,
                "high_issues": self.high_issues,
                "medium_issues": self.medium_issues,
                "low_issues": self.low_issues,
                "average_score": round(self.average_score, 1),
                "min_score": self.min_score,
                "max_score": self.max_score,
                "health_grade": self.health_grade,
                "has_blocking_issues": self.has_blocking_issues,
            },
            "issues_by_category": self.issues_by_category,
            "issues_by_severity": self.issues_by_severity,
            "worst_files": self.worst_files,
            "best_files": self.best_files,
            "files": [
                {
                    "path": s.file_path,
                    "score": s.score,
                    "status": s.status,
                    "total_issues": s.total_issues,
                    "critical": s.critical_count,
                    "high": s.high_count,
                    "medium": s.medium_count,
                    "low": s.low_count,
                    "top_categories": s.top_categories,
                    "error": s.error_message,
                }
                for s in self.file_summaries
            ],
            "all_issues": [
                {
                    "file": fp,
                    "line": issue.line,
                    "severity": issue.severity.value,
                    "category": issue.category.value,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                }
                for fp, issue in self.all_issues
            ],
        }


def format_batch_report_rich(report: BatchReviewReport, console: "Console") -> None:
    """Print a rich terminal batch report."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.columns import Columns
    
    # Title banner
    grade_colors = {"A": "green", "B": "blue", "C": "yellow", "D": "orange1", "F": "red"}
    grade_style = grade_colors.get(report.health_grade, "white")
    
    title_text = Text()
    title_text.append("Batch Code Review Report\n", style="bold")
    title_text.append(f"Generated: {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n", style="dim")
    title_text.append(f"\nHealth Grade: ", style="")
    title_text.append(f"{report.health_grade}", style=f"bold {grade_style}")
    title_text.append(f"  (Average Score: {report.average_score:.1f}/100)", style="dim")
    
    console.print(Panel(title_text, border_style="blue"))
    
    # Overview stats
    stats_table = Table(title="Overview", show_header=False, box=None)
    stats_table.add_column("Metric", style="dim")
    stats_table.add_column("Value", style="bold")
    
    stats_table.add_row("Files Reviewed", str(report.files_reviewed))
    stats_table.add_row("Files Skipped", str(report.files_skipped))
    if report.files_errored:
        stats_table.add_row("Files Errored", Text(str(report.files_errored), style="red"))
    stats_table.add_row("", "")
    stats_table.add_row("Total Issues", str(report.total_issues))
    stats_table.add_row("Critical", Text(str(report.critical_issues), style="red bold"))
    stats_table.add_row("High", Text(str(report.high_issues), style="red"))
    stats_table.add_row("Medium", Text(str(report.medium_issues), style="yellow"))
    stats_table.add_row("Low", Text(str(report.low_issues), style="blue"))
    stats_table.add_row("", "")
    stats_table.add_row("Score Range", f"{report.min_score} - {report.max_score}")
    
    # Issues by category
    cat_table = Table(title="Issues by Category", show_header=True)
    cat_table.add_column("Category")
    cat_table.add_column("Count", justify="right")
    
    for cat, count in sorted(report.issues_by_category.items(), key=lambda x: -x[1]):
        cat_table.add_row(cat.title(), str(count))
    
    console.print()
    console.print(Columns([stats_table, cat_table], equal=True, expand=True))
    
    # File breakdown
    if report.file_summaries:
        console.print()
        file_table = Table(title="File Results", show_lines=False)
        file_table.add_column("File", max_width=50)
        file_table.add_column("Score", justify="right")
        file_table.add_column("Issues", justify="right")
        file_table.add_column("Crit", justify="right")
        file_table.add_column("High", justify="right")
        file_table.add_column("Status")
        
        # Sort by score (lowest first for attention)
        sorted_summaries = sorted(
            report.file_summaries,
            key=lambda s: (s.status != "reviewed", s.score if s.status == "reviewed" else 999)
        )
        
        for summary in sorted_summaries:
            if summary.status == "skipped":
                file_table.add_row(
                    summary.file_path,
                    "-",
                    "-",
                    "-",
                    "-",
                    Text("skipped", style="dim"),
                )
            elif summary.status == "error":
                file_table.add_row(
                    summary.file_path,
                    "-",
                    "-",
                    "-",
                    "-",
                    Text("error", style="red"),
                )
            else:
                score_style = "green" if summary.score >= 80 else "yellow" if summary.score >= 60 else "red"
                crit_style = "red bold" if summary.critical_count > 0 else "dim"
                high_style = "red" if summary.high_count > 0 else "dim"
                
                file_table.add_row(
                    summary.file_path,
                    Text(str(summary.score), style=score_style),
                    str(summary.total_issues),
                    Text(str(summary.critical_count), style=crit_style),
                    Text(str(summary.high_count), style=high_style),
                    Text("✓", style="green"),
                )
        
        console.print(file_table)
    
    # Top issues (critical/high)
    blocking_issues = [(fp, i) for fp, i in report.all_issues 
                       if i.severity in (Severity.CRITICAL, Severity.HIGH)]
    if blocking_issues:
        console.print()
        issue_table = Table(title="Blocking Issues (Critical/High)", show_lines=True)
        issue_table.add_column("Sev", width=4)
        issue_table.add_column("File")
        issue_table.add_column("Line", width=6)
        issue_table.add_column("Issue")
        
        for fp, issue in blocking_issues[:10]:  # Limit to 10
            sev_style = "red bold" if issue.severity == Severity.CRITICAL else "red"
            sev_icon = "[X]" if issue.severity == Severity.CRITICAL else "[!]"
            line_str = str(issue.line) if issue.line else "-"
            
            issue_table.add_row(
                Text(sev_icon, style=sev_style),
                fp,
                line_str,
                issue.message,
            )
        
        if len(blocking_issues) > 10:
            console.print(f"[dim]... and {len(blocking_issues) - 10} more blocking issues[/]")
        
        console.print(issue_table)
    
    # Worst files callout
    if report.worst_files and report.files_reviewed > 1:
        console.print()
        worst_text = "Files needing attention (lowest scores):\n"
        for fp in report.worst_files[:3]:
            summary = next((s for s in report.file_summaries if s.file_path == fp), None)
            if summary:
                worst_text += f"  • {fp} (score: {summary.score})\n"
        console.print(Panel(worst_text.strip(), title="⚠️ Focus Areas", border_style="yellow"))


def format_batch_report_markdown(report: BatchReviewReport) -> str:
    """Generate a markdown batch report."""
    lines = []
    
    # Header
    lines.append("# Code Review Batch Report")
    lines.append("")
    lines.append(f"**Generated:** {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Health Grade:** {report.health_grade}")
    lines.append(f"**Average Score:** {report.average_score:.1f}/100")
    lines.append("")
    
    # Summary stats
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Files Reviewed | {report.files_reviewed} |")
    lines.append(f"| Files Skipped | {report.files_skipped} |")
    lines.append(f"| Total Issues | {report.total_issues} |")
    lines.append(f"| 🔴 Critical | {report.critical_issues} |")
    lines.append(f"| 🟠 High | {report.high_issues} |")
    lines.append(f"| 🟡 Medium | {report.medium_issues} |")
    lines.append(f"| 🔵 Low | {report.low_issues} |")
    lines.append(f"| Score Range | {report.min_score} - {report.max_score} |")
    lines.append("")
    
    # Issues by category
    if report.issues_by_category:
        lines.append("## Issues by Category")
        lines.append("")
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        for cat, count in sorted(report.issues_by_category.items(), key=lambda x: -x[1]):
            lines.append(f"| {cat.title()} | {count} |")
        lines.append("")
    
    # File breakdown
    lines.append("## File Results")
    lines.append("")
    lines.append("| File | Score | Issues | Critical | High | Status |")
    lines.append("|------|-------|--------|----------|------|--------|")
    
    sorted_summaries = sorted(
        report.file_summaries,
        key=lambda s: (s.status != "reviewed", s.score if s.status == "reviewed" else 999)
    )
    
    for summary in sorted_summaries:
        if summary.status == "skipped":
            lines.append(f"| {summary.file_path} | - | - | - | - | ⏭️ Skipped |")
        elif summary.status == "error":
            lines.append(f"| {summary.file_path} | - | - | - | - | ❌ Error |")
        else:
            score_emoji = "✅" if summary.score >= 80 else "⚠️" if summary.score >= 60 else "❌"
            lines.append(
                f"| {summary.file_path} | {score_emoji} {summary.score} | "
                f"{summary.total_issues} | {summary.critical_count} | "
                f"{summary.high_count} | ✓ |"
            )
    lines.append("")
    
    # Blocking issues
    blocking_issues = [(fp, i) for fp, i in report.all_issues 
                       if i.severity in (Severity.CRITICAL, Severity.HIGH)]
    if blocking_issues:
        lines.append("## Blocking Issues")
        lines.append("")
        for fp, issue in blocking_issues:
            sev_emoji = "🔴" if issue.severity == Severity.CRITICAL else "🟠"
            line_str = f" (Line {issue.line})" if issue.line else ""
            lines.append(f"### {sev_emoji} {fp}{line_str}")
            lines.append("")
            lines.append(f"**Category:** {issue.category.value}")
            lines.append(f"**Issue:** {issue.message}")
            if issue.suggestion:
                lines.append(f"**Suggestion:** {issue.suggestion}")
            lines.append("")
    
    # Recommendations
    lines.append("## Recommendations")
    lines.append("")
    if report.critical_issues > 0:
        lines.append(f"⚠️ **{report.critical_issues} critical issues** require immediate attention!")
        lines.append("")
    if report.worst_files:
        lines.append("Focus on these files first:")
        for fp in report.worst_files[:5]:
            summary = next((s for s in report.file_summaries if s.file_path == fp), None)
            if summary:
                lines.append(f"- `{fp}` (score: {summary.score})")
        lines.append("")
    
    return "\n".join(lines)


def format_batch_report_html(report: BatchReviewReport) -> str:
    """Generate an HTML batch report."""
    grade_colors = {"A": "#22c55e", "B": "#3b82f6", "C": "#eab308", "D": "#f97316", "F": "#ef4444"}
    grade_color = grade_colors.get(report.health_grade, "#888")
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Code Review Report - {report.timestamp.strftime('%Y-%m-%d')}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; padding: 2rem; background: #f8fafc; color: #1e293b; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: #0f172a; margin-bottom: 0.5rem; }}
        h2 {{ color: #334155; margin: 2rem 0 1rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }}
        .grade {{ font-size: 4rem; font-weight: bold; color: {grade_color}; }}
        .meta {{ color: #64748b; font-size: 0.9rem; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
        .stat {{ background: white; padding: 1rem; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
        .stat-value {{ font-size: 2rem; font-weight: bold; }}
        .stat-label {{ color: #64748b; font-size: 0.85rem; }}
        .critical {{ color: #ef4444; }}
        .high {{ color: #f97316; }}
        .medium {{ color: #eab308; }}
        .low {{ color: #3b82f6; }}
        table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin: 1rem 0; }}
        th, td {{ padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ background: #f1f5f9; font-weight: 600; }}
        tr:hover {{ background: #f8fafc; }}
        .badge {{ display: inline-block; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }}
        .badge-critical {{ background: #fef2f2; color: #dc2626; }}
        .badge-high {{ background: #fff7ed; color: #ea580c; }}
        .badge-skipped {{ background: #f1f5f9; color: #64748b; }}
        .issue-card {{ background: white; padding: 1rem; border-radius: 8px; margin: 0.5rem 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid; }}
        .issue-card.critical {{ border-color: #ef4444; }}
        .issue-card.high {{ border-color: #f97316; }}
        .issue-message {{ font-weight: 500; }}
        .issue-meta {{ color: #64748b; font-size: 0.85rem; margin-top: 0.5rem; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>Code Review Report</h1>
                <p class="meta">Generated: {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            <div class="grade">{report.health_grade}</div>
        </div>
        
        <div class="stats">
            <div class="stat">
                <div class="stat-value">{report.files_reviewed}</div>
                <div class="stat-label">Files Reviewed</div>
            </div>
            <div class="stat">
                <div class="stat-value">{report.average_score:.0f}</div>
                <div class="stat-label">Average Score</div>
            </div>
            <div class="stat">
                <div class="stat-value">{report.total_issues}</div>
                <div class="stat-label">Total Issues</div>
            </div>
            <div class="stat">
                <div class="stat-value critical">{report.critical_issues}</div>
                <div class="stat-label">Critical</div>
            </div>
            <div class="stat">
                <div class="stat-value high">{report.high_issues}</div>
                <div class="stat-label">High</div>
            </div>
        </div>
        
        <h2>File Results</h2>
        <table>
            <thead>
                <tr>
                    <th>File</th>
                    <th>Score</th>
                    <th>Issues</th>
                    <th>Critical</th>
                    <th>High</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
"""
    
    sorted_summaries = sorted(
        report.file_summaries,
        key=lambda s: (s.status != "reviewed", s.score if s.status == "reviewed" else 999)
    )
    
    for summary in sorted_summaries:
        if summary.status == "skipped":
            html += f"""                <tr>
                    <td>{summary.file_path}</td>
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
                    <td><span class="badge badge-skipped">Skipped</span></td>
                </tr>
"""
        elif summary.status == "error":
            html += f"""                <tr>
                    <td>{summary.file_path}</td>
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
                    <td><span class="badge badge-critical">Error</span></td>
                </tr>
"""
        else:
            score_class = "low" if summary.score >= 80 else "medium" if summary.score >= 60 else "critical"
            html += f"""                <tr>
                    <td>{summary.file_path}</td>
                    <td class="{score_class}">{summary.score}</td>
                    <td>{summary.total_issues}</td>
                    <td class="critical">{summary.critical_count}</td>
                    <td class="high">{summary.high_count}</td>
                    <td>✓</td>
                </tr>
"""
    
    html += """            </tbody>
        </table>
"""
    
    # Blocking issues section
    blocking_issues = [(fp, i) for fp, i in report.all_issues 
                       if i.severity in (Severity.CRITICAL, Severity.HIGH)]
    if blocking_issues:
        html += """        <h2>Blocking Issues</h2>
"""
        for fp, issue in blocking_issues[:15]:
            sev_class = "critical" if issue.severity == Severity.CRITICAL else "high"
            line_info = f" Line {issue.line}" if issue.line else ""
            html += f"""        <div class="issue-card {sev_class}">
            <div class="issue-message">{issue.message}</div>
            <div class="issue-meta">{fp}{line_info} • {issue.category.value}</div>
        </div>
"""
    
    html += """    </div>
</body>
</html>"""
    
    return html
