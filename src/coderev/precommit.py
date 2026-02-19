"""Pre-commit hook entry point for CodeRev.

This module provides a streamlined entry point optimized for use as a pre-commit hook.
It reviews only the staged files passed by pre-commit and outputs results in a
CI-friendly format.

Usage:
    As a pre-commit hook in .pre-commit-config.yaml:

        repos:
          - repo: https://github.com/khalil/coderev
            rev: v0.4.0
            hooks:
              - id: coderev
                args: ['--fail-on', 'high']

    Or run directly:
        coderev-precommit file1.py file2.py --fail-on high
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

import click
from rich.console import Console

from coderev.config import Config
from coderev.ignore import should_ignore
from coderev.output import RichFormatter
from coderev.reviewer import CodeReviewer, RateLimitError, Severity


console = Console(force_terminal=True, stderr=True)


def filter_reviewable_files(
    files: Sequence[str],
    config: Config,
) -> list[Path]:
    """Filter files to only those that should be reviewed.
    
    Applies ignore patterns and file size limits from config.
    """
    reviewable: list[Path] = []
    
    for file_str in files:
        file_path = Path(file_str)
        
        # Skip if doesn't exist
        if not file_path.exists():
            continue
        
        # Skip if not a file
        if not file_path.is_file():
            continue
        
        # Check ignore patterns
        if should_ignore(file_path, config.ignore_patterns):
            continue
        
        # Check file size
        if config.max_file_size and file_path.stat().st_size > config.max_file_size:
            console.print(f"[dim]Skipping {file_path} (exceeds max file size)[/]", highlight=False)
            continue
        
        reviewable.append(file_path)
    
    return reviewable


def severity_to_exit_code(severity: str) -> int:
    """Map severity to exit code for CI."""
    mapping = {
        "critical": 4,
        "high": 3,
        "medium": 2,
        "low": 1,
    }
    return mapping.get(severity, 0)


@click.command()
@click.argument("files", nargs=-1, required=False)
@click.option(
    "--focus",
    "-f",
    multiple=True,
    help="Focus areas (bugs, security, performance, style, architecture). Can be specified multiple times.",
)
@click.option(
    "--fail-on",
    type=click.Choice(["critical", "high", "medium", "low"]),
    default=None,
    help="Exit with error if issues of this severity or higher are found.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Only output issues, no progress messages.",
)
@click.option(
    "--max-files",
    type=int,
    default=10,
    help="Maximum number of files to review in one commit (default: 10).",
)
@click.option(
    "--estimate",
    is_flag=True,
    help="Show cost estimate instead of running the review.",
)
@click.option(
    "--staged",
    "-s",
    is_flag=True,
    help="Review staged changes only (diff mode). Ignores file arguments.",
)
def main(
    files: tuple[str, ...],
    focus: tuple[str, ...],
    fail_on: Optional[str],
    quiet: bool,
    max_files: int,
    estimate: bool,
    staged: bool,
) -> None:
    """AI-powered code review for pre-commit hooks.
    
    When used with pre-commit, files are passed automatically.
    Outputs to stderr so pre-commit can capture it properly.
    
    Examples:
        # Review specific files
        coderev-precommit src/main.py src/utils.py
        
        # Review with security focus, fail on high severity
        coderev-precommit --focus security --fail-on high src/
        
        # Estimate cost before reviewing
        coderev-precommit --estimate src/main.py
        
        # Review staged changes as a diff
        coderev-precommit --staged
    """
    try:
        # Load configuration
        config = Config.load()
        errors = config.validate()
        if errors:
            for error in errors:
                console.print(f"[red]Config error: {error}[/]")
            sys.exit(1)
        
        # Handle staged mode (diff-based review)
        if staged:
            _review_staged(config, focus, fail_on, quiet, estimate)
            return
        
        # Filter files
        reviewable = filter_reviewable_files(files, config)
        
        if not reviewable:
            if not quiet:
                console.print("[dim]No files to review[/]")
            sys.exit(0)
        
        # Check max files limit
        if len(reviewable) > max_files:
            console.print(
                f"[yellow]Warning: {len(reviewable)} files to review, "
                f"but max is {max_files}. Review the first {max_files} only.[/]"
            )
            reviewable = reviewable[:max_files]
        
        focus_list = list(focus) if focus else None
        
        # Handle cost estimation
        if estimate:
            from coderev.cost import CostEstimator
            
            estimator = CostEstimator(model=config.model)
            cost_estimate = estimator.estimate_files(reviewable, focus=focus_list)
            
            console.print(f"[bold]Cost Estimate[/]")
            console.print(f"  Files: {cost_estimate.file_count}")
            console.print(f"  Tokens: ~{cost_estimate.total_tokens:,}")
            console.print(f"  Estimated cost: {cost_estimate.format_cost()}")
            sys.exit(0)
        
        # Run review
        reviewer = CodeReviewer(config=config)
        formatter = RichFormatter(console)
        
        highest_severity: Optional[str] = None
        total_issues = 0
        
        for file_path in reviewable:
            if not quiet:
                console.print(f"[dim]Reviewing {file_path}...[/]", highlight=False)
            
            try:
                result = reviewer.review_file(file_path, focus=focus_list)
                
                if result.issues:
                    console.print(f"\n[bold]{file_path}[/]")
                    formatter.print_result(result, str(file_path))
                    total_issues += len(result.issues)
                    
                    # Track highest severity
                    for issue in result.issues:
                        if highest_severity is None:
                            highest_severity = issue.severity.value
                        else:
                            severity_order = ["low", "medium", "high", "critical"]
                            if severity_order.index(issue.severity.value) > severity_order.index(highest_severity):
                                highest_severity = issue.severity.value
            
            except RateLimitError:
                # Re-raise rate limit errors to be handled by outer handler
                raise
            except Exception as e:
                console.print(f"[red]Error reviewing {file_path}: {e}[/]")
        
        # Summary
        if not quiet:
            if total_issues == 0:
                console.print("\n[green]No issues found![/]")
            else:
                console.print(f"\n[yellow]Found {total_issues} issue(s)[/]")
        
        # Check fail condition
        if fail_on and highest_severity:
            severity_order = ["low", "medium", "high", "critical"]
            min_severity_idx = severity_order.index(fail_on)
            highest_idx = severity_order.index(highest_severity)
            
            if highest_idx >= min_severity_idx:
                console.print(
                    f"\n[red]Failing commit: found {highest_severity} severity issue(s)[/]"
                )
                sys.exit(1)
        
        sys.exit(0)
    
    except RateLimitError as e:
        console.print(f"[red bold]Rate Limit Exceeded[/]")
        console.print(f"[yellow]{e.message}[/]")
        console.print("[dim]Tip: Use --estimate to check costs before reviewing[/]")
        sys.exit(2)
    
    except KeyboardInterrupt:
        console.print("\n[yellow]Review cancelled[/]")
        sys.exit(130)
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


def _review_staged(
    config: Config,
    focus: tuple[str, ...],
    fail_on: Optional[str],
    quiet: bool,
    estimate: bool,
) -> None:
    """Review staged changes using diff mode."""
    import subprocess
    
    # Get staged diff
    result = subprocess.run(
        ["git", "diff", "--staged"],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        console.print(f"[red]Git error: {result.stderr}[/]")
        sys.exit(1)
    
    diff_content = result.stdout
    
    if not diff_content.strip():
        if not quiet:
            console.print("[dim]No staged changes to review[/]")
        sys.exit(0)
    
    focus_list = list(focus) if focus else None
    
    # Handle cost estimation
    if estimate:
        from coderev.cost import CostEstimator
        
        estimator = CostEstimator(model=config.model)
        cost_estimate = estimator.estimate_diff(diff_content, focus=focus_list)
        
        console.print(f"[bold]Cost Estimate[/]")
        console.print(f"  Tokens: ~{cost_estimate.total_tokens:,}")
        console.print(f"  Estimated cost: {cost_estimate.format_cost()}")
        sys.exit(0)
    
    # Run review
    if not quiet:
        console.print("[dim]Reviewing staged changes...[/]")
    
    reviewer = CodeReviewer(config=config)
    review_result = reviewer.review_diff(diff_content, focus=focus_list)
    
    formatter = RichFormatter(console)
    formatter.print_result(review_result, "Staged Changes")
    
    # Check fail condition
    if fail_on and review_result.issues:
        severity_order = ["low", "medium", "high", "critical"]
        min_severity_idx = severity_order.index(fail_on)
        
        for issue in review_result.issues:
            issue_idx = severity_order.index(issue.severity.value)
            if issue_idx >= min_severity_idx:
                console.print(
                    f"\n[red]Failing commit: found {issue.severity.value} severity issue(s)[/]"
                )
                sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
