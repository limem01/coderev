"""Command-line interface for CodeRev."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from coderev import __version__
from coderev.config import Config
from coderev.reviewer import CodeReviewer, RateLimitError
from coderev.output import RichFormatter, get_formatter, JsonFormatter


console = Console()


def get_git_diff(ref: str | None = None, staged: bool = False) -> str:
    """Get git diff output."""
    import subprocess
    
    cmd = ["git", "diff"]
    
    if staged:
        cmd.append("--staged")
    elif ref:
        cmd.append(ref)
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise click.ClickException(f"Git error: {result.stderr}")
    
    return result.stdout


def collect_files(
    paths: tuple[str, ...],
    recursive: bool = False,
    exclude: tuple[str, ...] = (),
) -> list[Path]:
    """Collect files from paths, handling directories."""
    import fnmatch
    
    files: list[Path] = []
    
    for path_str in paths:
        path = Path(path_str)
        
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for file_path in path.glob(pattern):
                if file_path.is_file():
                    # Check exclusions
                    excluded = any(
                        fnmatch.fnmatch(str(file_path), exc) or
                        fnmatch.fnmatch(file_path.name, exc)
                        for exc in exclude
                    )
                    if not excluded:
                        files.append(file_path)
        else:
            console.print(f"[yellow]Warning: {path} does not exist[/]")
    
    return files


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """CodeRev - AI-powered code review CLI tool."""
    pass


def print_cost_estimate(estimate: "CostEstimate", console: Console) -> None:
    """Print a formatted cost estimate to the console."""
    from rich.table import Table
    from rich.panel import Panel
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim")
    table.add_column("Value", style="bold")
    
    table.add_row("Model", estimate.model)
    table.add_row("Files", f"{estimate.file_count}" + (f" ({estimate.skipped_files} skipped)" if estimate.skipped_files else ""))
    table.add_row("Input tokens", f"{estimate.input_tokens:,}")
    table.add_row("Est. output tokens", f"{estimate.estimated_output_tokens:,}")
    table.add_row("Input cost", f"${estimate.input_cost_usd:.4f}")
    table.add_row("Output cost", f"${estimate.output_cost_usd:.4f}")
    table.add_row("", "")
    table.add_row("Total estimated cost", f"[green bold]{estimate.format_cost()}[/]")
    
    panel = Panel(table, title="[bold blue]Cost Estimate[/]", border_style="blue")
    console.print(panel)


@main.command()
@click.argument("paths", nargs=-1, required=True)
@click.option("--focus", "-f", multiple=True, help="Focus areas (bugs, security, performance, style, architecture)")
@click.option("--recursive", "-r", is_flag=True, help="Recursively review directories")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob)")
@click.option("--format", "output_format", type=click.Choice(["rich", "json", "markdown", "sarif"]), default="rich")
@click.option("--fail-on", type=click.Choice(["critical", "high", "medium", "low"]), help="Exit with error if issues of this severity or higher are found")
@click.option("--parallel/--no-parallel", default=True, help="Review files in parallel (default: enabled)")
@click.option("--max-concurrent", "-c", type=int, default=5, help="Max concurrent reviews when using parallel mode")
@click.option("--estimate", is_flag=True, help="Show cost estimate without running the review")
def review(
    paths: tuple[str, ...],
    focus: tuple[str, ...],
    recursive: bool,
    exclude: tuple[str, ...],
    output_format: str,
    fail_on: Optional[str],
    parallel: bool,
    max_concurrent: int,
    estimate: bool,
) -> None:
    """Review code files for issues.
    
    Uses parallel processing by default for faster reviews of multiple files.
    Use --estimate to see the expected cost before running.
    """
    import asyncio
    from coderev.async_reviewer import AsyncCodeReviewer
    from coderev.cost import CostEstimator, CostEstimate
    
    try:
        config = Config.load()
        errors = config.validate()
        if errors:
            for error in errors:
                console.print(f"[red]Config error: {error}[/]")
            sys.exit(1)
        
        files = collect_files(paths, recursive, exclude)
        
        if not files:
            console.print("[yellow]No files to review[/]")
            return
        
        focus_list = list(focus) if focus else None
        
        # Handle cost estimation
        if estimate:
            estimator = CostEstimator(model=config.model)
            cost_estimate = estimator.estimate_files(files, focus=focus_list)
            print_cost_estimate(cost_estimate, console)
            return
        
        # Use parallel processing for multiple files (unless disabled)
        use_parallel = parallel and len(files) > 1
        
        if use_parallel:
            console.print(f"[dim]Reviewing {len(files)} files in parallel (max {max_concurrent} concurrent)...[/]")
            
            async def run_parallel_review():
                async with AsyncCodeReviewer(
                    config=config,
                    max_concurrent=max_concurrent,
                ) as reviewer:
                    return await reviewer.review_files_async(files, focus=focus_list)
            
            results = asyncio.run(run_parallel_review())
            
            if output_format == "rich":
                formatter = RichFormatter(console)
                for file_path, result in results.items():
                    console.print(f"\n[bold blue]{file_path}[/]")
                    formatter.print_result(result, file_path)
            else:
                formatter = get_formatter(output_format)
                if isinstance(formatter, JsonFormatter):
                    output = formatter.format_multiple(results)
                else:
                    output = "\n\n".join(
                        formatter.format(result) for result in results.values()
                    )
                click.echo(output)
            
            # Check fail condition
            if fail_on:
                from coderev.reviewer import Severity
                severity_order = ["low", "medium", "high", "critical"]
                min_severity_idx = severity_order.index(fail_on)
                
                for result in results.values():
                    for issue in result.issues:
                        issue_idx = severity_order.index(issue.severity.value)
                        if issue_idx >= min_severity_idx:
                            sys.exit(1)
        else:
            # Sequential processing for single file or when parallel is disabled
            reviewer = CodeReviewer(config=config)
            
            if output_format == "rich":
                formatter = RichFormatter(console)
                
                for file_path in files:
                    console.print(f"\n[bold blue]Reviewing {file_path}...[/]")
                    try:
                        result = reviewer.review_file(file_path, focus=focus_list)
                        formatter.print_result(result, str(file_path))
                    except Exception as e:
                        console.print(f"[red]Error reviewing {file_path}: {e}[/]")
            else:
                formatter = get_formatter(output_format)
                results = reviewer.review_files([str(f) for f in files], focus=focus_list)
                
                if isinstance(formatter, JsonFormatter):
                    output = formatter.format_multiple(results)
                else:
                    output = "\n\n".join(
                        formatter.format(result) for result in results.values()
                    )
                
                click.echo(output)
            
            # Check fail condition
            if fail_on:
                from coderev.reviewer import Severity
                severity_order = ["low", "medium", "high", "critical"]
                min_severity_idx = severity_order.index(fail_on)
                
                for file_path in files:
                    result = reviewer.review_file(file_path, focus=focus_list)
                    for issue in result.issues:
                        issue_idx = severity_order.index(issue.severity.value)
                        if issue_idx >= min_severity_idx:
                            sys.exit(1)
    
    except RateLimitError as e:
        console.print(f"[red bold]Rate Limit Exceeded[/]")
        console.print(f"[yellow]{e.message}[/]")
        sys.exit(2)
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@main.command()
@click.argument("ref", required=False)
@click.option("--staged", "-s", is_flag=True, help="Review staged changes only")
@click.option("--focus", "-f", multiple=True, help="Focus areas")
@click.option("--format", "output_format", type=click.Choice(["rich", "json", "markdown", "sarif"]), default="rich")
@click.option("--fail-on", type=click.Choice(["critical", "high", "medium", "low"]))
@click.option("--estimate", is_flag=True, help="Show cost estimate without running the review")
def diff(
    ref: Optional[str],
    staged: bool,
    focus: tuple[str, ...],
    output_format: str,
    fail_on: Optional[str],
    estimate: bool,
) -> None:
    """Review git diff changes.
    
    Use --estimate to see the expected cost before running.
    """
    from coderev.cost import CostEstimator
    
    try:
        config = Config.load()
        errors = config.validate()
        if errors:
            for error in errors:
                console.print(f"[red]Config error: {error}[/]")
            sys.exit(1)
        
        diff_content = get_git_diff(ref, staged)
        
        if not diff_content.strip():
            console.print("[yellow]No changes to review[/]")
            return
        
        focus_list = list(focus) if focus else None
        
        # Handle cost estimation
        if estimate:
            estimator = CostEstimator(model=config.model)
            cost_estimate = estimator.estimate_diff(diff_content, focus=focus_list)
            print_cost_estimate(cost_estimate, console)
            return
        
        reviewer = CodeReviewer(config=config)
        result = reviewer.review_diff(diff_content, focus=focus_list)
        
        if output_format == "rich":
            formatter = RichFormatter(console)
            formatter.print_result(result, "Git Diff")
        else:
            formatter = get_formatter(output_format)
            click.echo(formatter.format(result))
        
        # Check fail condition
        if fail_on:
            severity_order = ["low", "medium", "high", "critical"]
            min_severity_idx = severity_order.index(fail_on)
            
            for issue in result.issues:
                issue_idx = severity_order.index(issue.severity.value)
                if issue_idx >= min_severity_idx:
                    sys.exit(1)
    
    except RateLimitError as e:
        console.print(f"[red bold]Rate Limit Exceeded[/]")
        console.print(f"[yellow]{e.message}[/]")
        sys.exit(2)
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@main.command()
@click.argument("pr_ref")
@click.option("--focus", "-f", multiple=True, help="Focus areas")
@click.option("--format", "output_format", type=click.Choice(["rich", "json", "markdown"]), default="rich")
@click.option("--post-comments", is_flag=True, help="Post review comments to PR")
def pr(
    pr_ref: str,
    focus: tuple[str, ...],
    output_format: str,
    post_comments: bool,
) -> None:
    """Review a GitHub pull request."""
    from coderev.github import GitHubClient, detect_language_from_filename
    from coderev.prompts import build_pr_prompt
    
    try:
        config = Config.load()
        errors = config.validate()
        if errors:
            for error in errors:
                console.print(f"[red]Config error: {error}[/]")
            sys.exit(1)
        
        # Parse PR reference
        if pr_ref.startswith(("http://", "https://")):
            owner, repo, pr_number = GitHubClient.parse_pr_url(pr_ref)
        else:
            # Assume local repo and PR number
            import subprocess
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise click.ClickException("Could not determine repository from git remote")
            
            remote_url = result.stdout.strip()
            # Parse github.com/owner/repo from various URL formats
            import re
            match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote_url)
            if not match:
                raise click.ClickException(f"Could not parse GitHub repo from: {remote_url}")
            
            owner, repo = match.groups()
            pr_number = int(pr_ref)
        
        console.print(f"[bold blue]Fetching PR #{pr_number} from {owner}/{repo}...[/]")
        
        with GitHubClient(config=config) as gh:
            pr_data = gh.get_pull_request(owner, repo, pr_number)
        
        console.print(f"[bold]PR: {pr_data.title}[/]")
        console.print(f"[dim]{pr_data.additions} additions, {pr_data.deletions} deletions across {len(pr_data.files)} files[/]")
        
        # Prepare files for review
        files_for_review = []
        for file_info in pr_data.files:
            if file_info.get("patch"):  # Only include files with diffs
                files_for_review.append({
                    "filename": file_info["filename"],
                    "patch": file_info["patch"],
                    "language": detect_language_from_filename(file_info["filename"]),
                })
        
        if not files_for_review:
            console.print("[yellow]No reviewable file changes found[/]")
            return
        
        # Build prompt and review
        reviewer = CodeReviewer(config=config)
        focus_list = list(focus) if focus else None
        
        prompt = build_pr_prompt(
            pr_data.title,
            pr_data.description,
            files_for_review,
            focus_list,
        )
        
        console.print("[dim]Analyzing changes...[/]")
        response = reviewer._call_api(prompt)
        
        from coderev.reviewer import ReviewResult, Issue
        
        issues = [Issue.from_dict(i) for i in response.get("issues", [])]
        result = ReviewResult(
            summary=response.get("summary", "PR review completed"),
            issues=issues,
            score=response.get("score", 0),
            positive=response.get("positive", []),
            verdict=response.get("verdict"),
            raw_response=response,
        )
        
        if output_format == "rich":
            formatter = RichFormatter(console)
            formatter.print_result(result, f"PR #{pr_number}")
            
            if result.verdict:
                verdict_style = {
                    "approve": "green bold",
                    "request_changes": "red bold",
                    "comment": "yellow",
                }.get(result.verdict, "white")
                console.print(f"\n[{verdict_style}]Verdict: {result.verdict.upper()}[/]")
        else:
            formatter = get_formatter(output_format)
            click.echo(formatter.format(result))
        
        # Post comments if requested
        if post_comments and result.issues:
            console.print("\n[bold]Posting review to GitHub...[/]")
            with GitHubClient(config=config) as gh:
                event = {
                    "approve": "APPROVE",
                    "request_changes": "REQUEST_CHANGES",
                }.get(result.verdict or "", "COMMENT")
                
                gh.post_review(
                    owner,
                    repo,
                    pr_number,
                    body=f"## AI Code Review\n\n{result.summary}\n\n**Score:** {result.score}/100",
                    event=event,
                )
                console.print("[green]Review posted successfully![/]")
    
    except RateLimitError as e:
        console.print(f"[red bold]Rate Limit Exceeded[/]")
        console.print(f"[yellow]{e.message}[/]")
        sys.exit(2)
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@main.command()
@click.argument("paths", nargs=-1, required=True)
@click.option("--focus", "-f", multiple=True, help="Focus areas (bugs, security, performance, style, architecture)")
@click.option("--recursive", "-r", is_flag=True, help="Recursively review directories")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob)")
@click.option("--model", "-m", help="Model to estimate costs for (overrides config)")
@click.option("--format", "output_format", type=click.Choice(["rich", "json"]), default="rich")
def estimate(
    paths: tuple[str, ...],
    focus: tuple[str, ...],
    recursive: bool,
    exclude: tuple[str, ...],
    model: Optional[str],
    output_format: str,
) -> None:
    """Estimate review cost without running the review.
    
    Shows token counts and estimated API costs for the specified files.
    Useful for budgeting and understanding costs before committing to a review.
    
    Examples:
        coderev estimate src/
        coderev estimate *.py --model gpt-4o
        coderev estimate . -r --exclude "*.test.py"
    """
    import json as json_module
    from coderev.cost import CostEstimator
    
    try:
        config = Config.load()
        
        files = collect_files(paths, recursive, exclude)
        
        if not files:
            console.print("[yellow]No files to estimate[/]")
            return
        
        focus_list = list(focus) if focus else None
        model_name = model or config.model
        
        estimator = CostEstimator(model=model_name)
        cost_estimate = estimator.estimate_files(files, focus=focus_list)
        
        if output_format == "json":
            result = {
                "model": cost_estimate.model,
                "file_count": cost_estimate.file_count,
                "skipped_files": cost_estimate.skipped_files,
                "input_tokens": cost_estimate.input_tokens,
                "estimated_output_tokens": cost_estimate.estimated_output_tokens,
                "total_tokens": cost_estimate.total_tokens,
                "input_cost_usd": round(cost_estimate.input_cost_usd, 6),
                "output_cost_usd": round(cost_estimate.output_cost_usd, 6),
                "total_cost_usd": round(cost_estimate.total_cost_usd, 6),
            }
            click.echo(json_module.dumps(result, indent=2))
        else:
            print_cost_estimate(cost_estimate, console)
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@main.command()
def init() -> None:
    """Initialize a .coderev.toml configuration file."""
    config_path = Path.cwd() / ".coderev.toml"
    
    if config_path.exists():
        if not click.confirm(f"{config_path} already exists. Overwrite?"):
            return
    
    default_config = '''[coderev]
# API key for Claude (or set CODEREV_API_KEY / ANTHROPIC_API_KEY env var)
# api_key = "your-api-key"

# Model to use for reviews
model = "claude-3-sonnet-20240229"

# Default focus areas
focus = ["bugs", "security", "performance"]

# File patterns to ignore
ignore_patterns = ["*.test.py", "*.spec.ts", "migrations/*", "*.min.js"]

# Maximum file size in bytes
max_file_size = 100000

# Enable language detection from file extensions
language_hints = true

[github]
# GitHub token for PR reviews (or set GITHUB_TOKEN env var)
# token = "ghp_xxx"
'''
    
    config_path.write_text(default_config)
    console.print(f"[green]Created {config_path}[/]")
    console.print("[dim]Edit the file to add your API keys and customize settings.[/]")


@main.command()
@click.argument("paths", nargs=-1, required=True)
@click.option("--focus", "-f", multiple=True, help="Focus areas (bugs, security, performance, style, architecture)")
@click.option("--recursive", "-r", is_flag=True, help="Recursively review directories")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob)")
@click.option("--format", "output_format", type=click.Choice(["rich", "json", "markdown", "html"]), default="rich")
@click.option("--output", "-o", "output_file", type=click.Path(), help="Output file path (default: stdout)")
@click.option("--parallel/--no-parallel", default=True, help="Review files in parallel (default: enabled)")
@click.option("--max-concurrent", "-c", type=int, default=5, help="Max concurrent reviews when using parallel mode")
@click.option("--fail-on", type=click.Choice(["critical", "high", "medium", "low"]), help="Exit with error if issues of this severity or higher are found")
def batch(
    paths: tuple[str, ...],
    focus: tuple[str, ...],
    recursive: bool,
    exclude: tuple[str, ...],
    output_format: str,
    output_file: Optional[str],
    parallel: bool,
    max_concurrent: int,
    fail_on: Optional[str],
) -> None:
    """Batch review multiple files and generate a summary report.
    
    Reviews all specified files/directories and produces a comprehensive
    summary report with aggregated statistics, health grades, and actionable
    insights.
    
    The report includes:
    - Overall health grade (A-F) based on average score
    - Issue counts by severity and category
    - Per-file breakdown with scores
    - Blocking issues (critical/high) highlighted
    - Recommendations for files needing attention
    
    Examples:
        coderev batch src/
        coderev batch . -r --exclude "*.test.py" --format markdown -o report.md
        coderev batch src/ tests/ --format html -o report.html
        coderev batch . -r --fail-on high  # CI mode: exit 1 if high/critical issues
    """
    import asyncio
    import json as json_module
    from coderev.async_reviewer import AsyncCodeReviewer
    from coderev.batch import (
        BatchReviewReport,
        format_batch_report_rich,
        format_batch_report_markdown,
        format_batch_report_html,
    )
    
    try:
        config = Config.load()
        errors = config.validate()
        if errors:
            for error in errors:
                console.print(f"[red]Config error: {error}[/]")
            sys.exit(1)
        
        files = collect_files(paths, recursive, exclude)
        
        if not files:
            console.print("[yellow]No files to review[/]")
            return
        
        focus_list = list(focus) if focus else None
        
        console.print(f"[bold blue]Batch Review[/] - {len(files)} files")
        
        # Use parallel processing for multiple files
        use_parallel = parallel and len(files) > 1
        
        if use_parallel:
            console.print(f"[dim]Reviewing in parallel (max {max_concurrent} concurrent)...[/]")
            
            async def run_parallel_review():
                async with AsyncCodeReviewer(
                    config=config,
                    max_concurrent=max_concurrent,
                ) as reviewer:
                    return await reviewer.review_files_async(files, focus=focus_list)
            
            results = asyncio.run(run_parallel_review())
        else:
            console.print("[dim]Reviewing files sequentially...[/]")
            reviewer = CodeReviewer(config=config)
            results = reviewer.review_files([str(f) for f in files], focus=focus_list)
        
        # Generate batch report
        report = BatchReviewReport.from_results(results)
        
        # Output the report
        if output_format == "rich":
            format_batch_report_rich(report, console)
        elif output_format == "json":
            output = json_module.dumps(report.to_dict(), indent=2)
            if output_file:
                Path(output_file).write_text(output)
                console.print(f"[green]Report saved to {output_file}[/]")
            else:
                click.echo(output)
        elif output_format == "markdown":
            output = format_batch_report_markdown(report)
            if output_file:
                Path(output_file).write_text(output)
                console.print(f"[green]Report saved to {output_file}[/]")
            else:
                click.echo(output)
        elif output_format == "html":
            output = format_batch_report_html(report)
            if output_file:
                Path(output_file).write_text(output)
                console.print(f"[green]Report saved to {output_file}[/]")
            else:
                click.echo(output)
        
        # Check fail condition
        if fail_on:
            severity_order = ["low", "medium", "high", "critical"]
            min_severity_idx = severity_order.index(fail_on)
            
            should_fail = False
            if min_severity_idx <= 3 and report.critical_issues > 0:
                should_fail = True
            if min_severity_idx <= 2 and report.high_issues > 0:
                should_fail = True
            if min_severity_idx <= 1 and report.medium_issues > 0:
                should_fail = True
            if min_severity_idx <= 0 and report.low_issues > 0:
                should_fail = True
            
            if should_fail:
                console.print(f"\n[red bold]FAIL: Issues found at or above '{fail_on}' severity[/]")
                sys.exit(1)
    
    except RateLimitError as e:
        console.print(f"[red bold]Rate Limit Exceeded[/]")
        console.print(f"[yellow]{e.message}[/]")
        sys.exit(2)
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@main.group()
def history() -> None:
    """Manage review history and tracking."""
    pass


@history.command("list")
@click.option("--limit", "-n", type=int, default=10, help="Number of entries to show")
@click.option("--file", "-f", "file_path", help="Filter by file path")
@click.option("--severity", "-s", type=click.Choice(["critical", "high", "medium", "low"]), help="Filter by minimum severity")
@click.option("--format", "output_format", type=click.Choice(["rich", "json"]), default="rich")
def history_list(
    limit: int,
    file_path: Optional[str],
    severity: Optional[str],
    output_format: str,
) -> None:
    """List recent review entries.
    
    Shows the most recent code reviews with their scores and issue counts.
    Use filters to narrow down results by file or severity.
    
    Examples:
        coderev history list
        coderev history list --limit 20
        coderev history list --file main.py
        coderev history list --severity high
    """
    import json as json_module
    from coderev.history import ReviewHistory
    
    try:
        history_store = ReviewHistory()
        
        if file_path:
            entries = history_store.get_by_file(file_path, limit=limit)
        elif severity:
            entries = history_store.get_by_severity(severity, limit=limit)
        else:
            entries = history_store.get_recent(limit=limit)
        
        if not entries:
            console.print("[yellow]No review history found[/]")
            return
        
        if output_format == "json":
            data = [e.to_dict() for e in entries]
            click.echo(json_module.dumps(data, indent=2, default=str))
        else:
            from rich.table import Table
            
            table = Table(title=f"Recent Reviews ({len(entries)} entries)")
            table.add_column("Date", style="dim")
            table.add_column("File", style="cyan")
            table.add_column("Score", justify="center")
            table.add_column("Issues", justify="center")
            table.add_column("Model", style="dim")
            
            for entry in entries:
                # Format date
                dt_str = entry.timestamp[:16].replace("T", " ")
                
                # Format score with color
                if entry.score >= 80:
                    score_str = f"[green]{entry.score}[/]"
                elif entry.score >= 60:
                    score_str = f"[yellow]{entry.score}[/]"
                else:
                    score_str = f"[red]{entry.score}[/]"
                
                # Format issues with severity breakdown
                issue_parts = []
                if entry.critical_count > 0:
                    issue_parts.append(f"[red]{entry.critical_count}C[/]")
                if entry.high_count > 0:
                    issue_parts.append(f"[orange1]{entry.high_count}H[/]")
                if entry.medium_count > 0:
                    issue_parts.append(f"[yellow]{entry.medium_count}M[/]")
                if entry.low_count > 0:
                    issue_parts.append(f"[dim]{entry.low_count}L[/]")
                issues_str = " ".join(issue_parts) if issue_parts else "[green]0[/]"
                
                table.add_row(
                    dt_str,
                    entry.file_path or entry.review_type,
                    score_str,
                    issues_str,
                    entry.model,
                )
            
            console.print(table)
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@history.command("stats")
@click.option("--days", "-d", type=int, help="Only include reviews from last N days")
@click.option("--format", "output_format", type=click.Choice(["rich", "json"]), default="rich")
def history_stats(days: Optional[int], output_format: str) -> None:
    """Show review history statistics.
    
    Displays aggregated statistics including total reviews, average scores,
    issue breakdowns, and trends over time.
    
    Examples:
        coderev history stats
        coderev history stats --days 30
        coderev history stats --format json
    """
    import json as json_module
    from coderev.history import ReviewHistory
    
    try:
        history_store = ReviewHistory()
        stats = history_store.get_stats(days=days)
        
        if stats.total_reviews == 0:
            console.print("[yellow]No review history found[/]")
            return
        
        if output_format == "json":
            click.echo(json_module.dumps(stats.to_dict(), indent=2, default=str))
        else:
            from rich.table import Table
            from rich.panel import Panel
            
            # Overview panel
            overview = Table(show_header=False, box=None, padding=(0, 2))
            overview.add_column("Label", style="dim")
            overview.add_column("Value", style="bold")
            
            overview.add_row("Total Reviews", str(stats.total_reviews))
            overview.add_row("Unique Files", str(stats.total_files))
            overview.add_row("Total Issues", str(stats.total_issues))
            overview.add_row("Average Score", f"{stats.average_score:.1f}/100")
            
            if stats.first_review:
                overview.add_row("First Review", stats.first_review[:10])
            if stats.last_review:
                overview.add_row("Last Review", stats.last_review[:10])
            
            console.print(Panel(overview, title="[bold blue]Overview[/]", border_style="blue"))
            
            # Issues by severity
            severity_table = Table(title="Issues by Severity")
            severity_table.add_column("Severity")
            severity_table.add_column("Count", justify="right")
            
            severity_table.add_row("[red]Critical[/]", str(stats.critical_issues))
            severity_table.add_row("[orange1]High[/]", str(stats.high_issues))
            severity_table.add_row("[yellow]Medium[/]", str(stats.medium_issues))
            severity_table.add_row("[dim]Low[/]", str(stats.low_issues))
            
            console.print(severity_table)
            
            # Reviews by type
            if stats.reviews_by_type:
                type_table = Table(title="Reviews by Type")
                type_table.add_column("Type")
                type_table.add_column("Count", justify="right")
                
                for rtype, count in sorted(stats.reviews_by_type.items(), key=lambda x: -x[1]):
                    type_table.add_row(rtype, str(count))
                
                console.print(type_table)
            
            # Reviews by model
            if stats.reviews_by_model:
                model_table = Table(title="Reviews by Model")
                model_table.add_column("Model")
                model_table.add_column("Count", justify="right")
                
                for model, count in sorted(stats.reviews_by_model.items(), key=lambda x: -x[1]):
                    model_table.add_row(model, str(count))
                
                console.print(model_table)
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@history.command("export")
@click.argument("output_path", type=click.Path())
def history_export(output_path: str) -> None:
    """Export review history to a JSON file.
    
    Creates a portable backup of all review history that can be imported
    on another machine or restored later.
    
    Example:
        coderev history export backup.json
    """
    from coderev.history import ReviewHistory
    
    try:
        history_store = ReviewHistory()
        count = history_store.export(output_path)
        
        console.print(f"[green]Exported {count} entries to {output_path}[/]")
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@history.command("import")
@click.argument("input_path", type=click.Path(exists=True))
def history_import(input_path: str) -> None:
    """Import review history from a JSON file.
    
    Imports previously exported history. Duplicate entries are automatically
    skipped to prevent data duplication.
    
    Example:
        coderev history import backup.json
    """
    from coderev.history import ReviewHistory
    
    try:
        history_store = ReviewHistory()
        count = history_store.import_from(input_path)
        
        console.print(f"[green]Imported {count} entries from {input_path}[/]")
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


@history.command("clear")
@click.confirmation_option(prompt="Are you sure you want to clear all review history?")
def history_clear() -> None:
    """Clear all review history.
    
    Permanently deletes all stored review history. This action cannot be undone.
    Consider exporting your history first with 'coderev history export'.
    """
    from coderev.history import ReviewHistory
    
    try:
        history_store = ReviewHistory()
        count = history_store.clear()
        
        console.print(f"[yellow]Cleared {count} history entries[/]")
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
