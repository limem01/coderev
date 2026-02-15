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


@main.command()
@click.argument("paths", nargs=-1, required=True)
@click.option("--focus", "-f", multiple=True, help="Focus areas (bugs, security, performance, style, architecture)")
@click.option("--recursive", "-r", is_flag=True, help="Recursively review directories")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob)")
@click.option("--format", "output_format", type=click.Choice(["rich", "json", "markdown", "sarif"]), default="rich")
@click.option("--fail-on", type=click.Choice(["critical", "high", "medium", "low"]), help="Exit with error if issues of this severity or higher are found")
@click.option("--parallel/--no-parallel", default=True, help="Review files in parallel (default: enabled)")
@click.option("--max-concurrent", "-c", type=int, default=5, help="Max concurrent reviews when using parallel mode")
def review(
    paths: tuple[str, ...],
    focus: tuple[str, ...],
    recursive: bool,
    exclude: tuple[str, ...],
    output_format: str,
    fail_on: Optional[str],
    parallel: bool,
    max_concurrent: int,
) -> None:
    """Review code files for issues.
    
    Uses parallel processing by default for faster reviews of multiple files.
    """
    import asyncio
    from coderev.async_reviewer import AsyncCodeReviewer
    
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
def diff(
    ref: Optional[str],
    staged: bool,
    focus: tuple[str, ...],
    output_format: str,
    fail_on: Optional[str],
) -> None:
    """Review git diff changes."""
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
        
        reviewer = CodeReviewer(config=config)
        focus_list = list(focus) if focus else None
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


if __name__ == "__main__":
    main()
