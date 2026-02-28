"""Interactive TUI (Text User Interface) for CodeRev.

Provides a rich terminal interface for browsing files, running reviews,
and navigating through results interactively.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from rich.live import Live
from rich.layout import Layout
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown

from coderev.config import Config
from coderev.reviewer import CodeReviewer, ReviewResult, Issue, Severity


# ANSI escape sequences for terminal control
CLEAR_SCREEN = "\033[2J\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


@dataclass
class TUIState:
    """State container for the TUI application."""
    
    # Current working directory and selected paths
    cwd: Path = field(default_factory=Path.cwd)
    selected_files: list[Path] = field(default_factory=list)
    
    # Current view state
    current_view: str = "files"  # files, review, results, issue
    cursor_position: int = 0
    scroll_offset: int = 0
    
    # Review state
    review_results: dict[str, ReviewResult] = field(default_factory=dict)
    current_file: str | None = None
    current_issue_idx: int = 0
    
    # Config
    focus: list[str] = field(default_factory=lambda: ["bugs", "security", "performance"])
    show_hidden: bool = False
    recursive: bool = False


class TUIApp:
    """Interactive TUI application for CodeRev.
    
    Provides keyboard-driven navigation for:
    - File/directory browsing
    - File selection for review
    - Review execution with progress
    - Results browsing with issue navigation
    - Code preview with syntax highlighting
    
    Example:
        app = TUIApp()
        app.run()
    """
    
    def __init__(
        self,
        config: Config | None = None,
        start_path: Path | str | None = None,
    ):
        """Initialize the TUI application.
        
        Args:
            config: Optional CodeRev config. Loads default if not provided.
            start_path: Starting directory path.
        """
        self.config = config or Config.load()
        self.console = Console()
        self.state = TUIState()
        
        if start_path:
            self.state.cwd = Path(start_path).resolve()
        
        self._running = False
        self._reviewer: CodeReviewer | None = None
        
        # Key bindings
        self.keybindings: dict[str, Callable[[], None]] = {
            "q": self._quit,
            "Q": self._quit,
            "\x1b": self._back,  # Escape
            "j": self._move_down,
            "k": self._move_up,
            "J": self._page_down,
            "K": self._page_up,
            "\r": self._select,  # Enter
            " ": self._toggle_select,  # Space
            "a": self._select_all,
            "A": self._deselect_all,
            "r": self._start_review,
            "R": self._start_review,
            ".": self._toggle_hidden,
            "/": self._toggle_recursive,
            "?": self._show_help,
            "h": self._show_help,
            "n": self._next_issue,
            "p": self._prev_issue,
            "g": self._go_to_top,
            "G": self._go_to_bottom,
            "f": self._cycle_focus,
            "e": self._export_results,
        }
    
    def run(self) -> None:
        """Run the TUI application.
        
        Blocks until the user quits. Handles terminal setup/teardown
        and keyboard input processing.
        """
        import sys
        import termios
        import tty
        
        self._running = True
        
        # Save terminal settings
        old_settings = termios.tcgetattr(sys.stdin)
        
        try:
            # Set terminal to raw mode for direct key reading
            tty.setraw(sys.stdin.fileno())
            self.console.print(HIDE_CURSOR, end="")
            
            while self._running:
                self._render()
                
                # Read a single keypress
                char = sys.stdin.read(1)
                
                # Handle escape sequences (arrow keys, etc.)
                if char == "\x1b":
                    # Check for escape sequence
                    import select
                    if select.select([sys.stdin], [], [], 0.01)[0]:
                        char += sys.stdin.read(2)
                        self._handle_escape_sequence(char)
                        continue
                
                # Handle regular keys
                if char in self.keybindings:
                    self.keybindings[char]()
                elif char == "\x03":  # Ctrl+C
                    self._quit()
        
        finally:
            # Restore terminal settings
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            self.console.print(SHOW_CURSOR, end="")
            self.console.print(CLEAR_SCREEN, end="")
    
    def run_simple(self) -> None:
        """Run a simplified TUI without raw terminal mode.
        
        Uses standard input with line buffering. Less interactive but
        more compatible across terminals and platforms (including Windows).
        """
        self._running = True
        
        while self._running:
            self._render()
            
            try:
                cmd = input("\n> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                self._quit()
                continue
            
            self._process_command(cmd)
    
    def _process_command(self, cmd: str) -> None:
        """Process a command in simple mode."""
        if cmd in ("q", "quit", "exit"):
            self._quit()
        elif cmd in ("?", "h", "help"):
            self._show_help()
        elif cmd in ("j", "down"):
            self._move_down()
        elif cmd in ("k", "up"):
            self._move_up()
        elif cmd in ("", "enter"):
            self._select()
        elif cmd.startswith("s ") or cmd.startswith("select "):
            # Select by number
            try:
                idx = int(cmd.split()[1]) - 1
                if 0 <= idx < len(self._get_current_items()):
                    self.state.cursor_position = idx
                    self._toggle_select()
            except (ValueError, IndexError):
                pass
        elif cmd in ("r", "review"):
            self._start_review()
        elif cmd in ("b", "back"):
            self._back()
        elif cmd in ("a", "all"):
            self._select_all()
        elif cmd in ("n", "next"):
            self._next_issue()
        elif cmd in ("p", "prev"):
            self._prev_issue()
    
    def _render(self) -> None:
        """Render the current view."""
        self.console.print(CLEAR_SCREEN, end="")
        
        # Header
        self._render_header()
        
        # Main content based on view
        if self.state.current_view == "files":
            self._render_file_browser()
        elif self.state.current_view == "review":
            self._render_review_progress()
        elif self.state.current_view == "results":
            self._render_results()
        elif self.state.current_view == "issue":
            self._render_issue_detail()
        elif self.state.current_view == "help":
            self._render_help()
        
        # Footer with keybindings hint
        self._render_footer()
    
    def _render_header(self) -> None:
        """Render the header bar."""
        title = Text()
        title.append("CodeRev", style="bold cyan")
        title.append(" │ ", style="dim")
        title.append(str(self.state.cwd), style="dim white")
        
        # Selection count
        if self.state.selected_files:
            title.append(" │ ", style="dim")
            title.append(f"{len(self.state.selected_files)} selected", style="yellow")
        
        self.console.print(Panel(title, border_style="blue", padding=(0, 1)))
    
    def _render_footer(self) -> None:
        """Render the footer with keybindings."""
        hints = {
            "files": "j/k:nav  ↵:open  space:select  r:review  ?:help  q:quit",
            "results": "j/k:nav  ↵:details  n/p:issues  b:back  e:export  q:quit",
            "issue": "n:next  p:prev  b:back  q:quit",
            "help": "any key to return",
        }
        
        hint = hints.get(self.state.current_view, "?:help  q:quit")
        self.console.print(f"\n[dim]{hint}[/]")
    
    def _render_file_browser(self) -> None:
        """Render the file browser view."""
        items = self._get_current_items()
        
        if not items:
            self.console.print("[dim]Empty directory[/]")
            return
        
        # Calculate visible range
        height = self.console.size.height - 10  # Leave room for header/footer
        start = self.state.scroll_offset
        end = min(start + height, len(items))
        
        # Adjust scroll offset if cursor is outside visible range
        if self.state.cursor_position < start:
            self.state.scroll_offset = self.state.cursor_position
        elif self.state.cursor_position >= end:
            self.state.scroll_offset = self.state.cursor_position - height + 1
        
        start = self.state.scroll_offset
        end = min(start + height, len(items))
        
        # Render items
        for i in range(start, end):
            item = items[i]
            is_cursor = i == self.state.cursor_position
            is_selected = item in self.state.selected_files
            
            # Build line
            prefix = ">" if is_cursor else " "
            checkbox = "[x]" if is_selected else "[ ]"
            
            if item.is_dir():
                icon = "📁"
                name = f"{item.name}/"
                style = "bold cyan" if is_cursor else "cyan"
            else:
                icon = self._get_file_icon(item)
                name = item.name
                style = "bold white" if is_cursor else "white"
            
            # Highlight selected
            if is_selected:
                style = "bold yellow" if is_cursor else "yellow"
            
            line = Text()
            line.append(f" {prefix} ", style="bold cyan" if is_cursor else "dim")
            line.append(f"{checkbox} ", style="yellow" if is_selected else "dim")
            line.append(f"{icon} ", style="dim")
            line.append(name, style=style)
            
            self.console.print(line)
        
        # Scroll indicator
        if len(items) > height:
            pct = (self.state.cursor_position + 1) / len(items) * 100
            self.console.print(f"\n[dim]─── {self.state.cursor_position + 1}/{len(items)} ({pct:.0f}%) ───[/]")
    
    def _render_results(self) -> None:
        """Render the review results overview."""
        if not self.state.review_results:
            self.console.print("[yellow]No review results yet. Press 'r' to start a review.[/]")
            return
        
        # Summary table
        table = Table(title="Review Results", expand=True)
        table.add_column("File", style="cyan")
        table.add_column("Score", justify="center")
        table.add_column("Critical", justify="center", style="red")
        table.add_column("High", justify="center", style="orange1")
        table.add_column("Medium", justify="center", style="yellow")
        table.add_column("Low", justify="center", style="dim")
        
        items = list(self.state.review_results.items())
        
        for i, (path, result) in enumerate(items):
            is_cursor = i == self.state.cursor_position
            
            # Score formatting
            if result.score >= 80:
                score_style = "green"
            elif result.score >= 60:
                score_style = "yellow"
            else:
                score_style = "red"
            
            score_str = f"[{score_style}]{result.score}[/]" if result.score >= 0 else "[dim]N/A[/]"
            
            # Count issues by severity
            critical = sum(1 for i in result.issues if i.severity == Severity.CRITICAL)
            high = sum(1 for i in result.issues if i.severity == Severity.HIGH)
            medium = sum(1 for i in result.issues if i.severity == Severity.MEDIUM)
            low = sum(1 for i in result.issues if i.severity == Severity.LOW)
            
            # Highlight cursor row
            file_name = Path(path).name
            if is_cursor:
                file_name = f"[bold reverse] {file_name} [/]"
            
            table.add_row(
                file_name,
                score_str,
                str(critical) if critical else "-",
                str(high) if high else "-",
                str(medium) if medium else "-",
                str(low) if low else "-",
            )
        
        self.console.print(table)
        
        # Overall summary
        total_issues = sum(len(r.issues) for r in self.state.review_results.values())
        avg_score = sum(r.score for r in self.state.review_results.values() if r.score >= 0) / max(1, len([r for r in self.state.review_results.values() if r.score >= 0]))
        
        self.console.print(f"\n[dim]Total issues: {total_issues} │ Average score: {avg_score:.0f}/100[/]")
    
    def _render_issue_detail(self) -> None:
        """Render detailed view for a single issue."""
        if not self.state.current_file or self.state.current_file not in self.state.review_results:
            self._back()
            return
        
        result = self.state.review_results[self.state.current_file]
        
        if not result.issues:
            self.console.print(Panel("[green]No issues found in this file![/]", title=self.state.current_file))
            return
        
        # Clamp issue index
        self.state.current_issue_idx = max(0, min(self.state.current_issue_idx, len(result.issues) - 1))
        issue = result.issues[self.state.current_issue_idx]
        
        # Issue header
        severity_style = {
            Severity.CRITICAL: "red bold",
            Severity.HIGH: "orange1 bold",
            Severity.MEDIUM: "yellow",
            Severity.LOW: "dim",
        }.get(issue.severity, "white")
        
        header = Text()
        header.append(f"[{issue.severity.value.upper()}]", style=severity_style)
        header.append(f" Issue {self.state.current_issue_idx + 1}/{len(result.issues)}", style="dim")
        
        if issue.line:
            header.append(f" │ Line {issue.line}", style="cyan")
            if issue.end_line and issue.end_line != issue.line:
                header.append(f"-{issue.end_line}", style="cyan")
        
        self.console.print(Panel(header, title=Path(self.state.current_file).name, border_style="blue"))
        
        # Issue content
        self.console.print(f"\n[bold]Category:[/] {issue.category.value}")
        self.console.print(f"\n[bold]Message:[/]\n{issue.message}")
        
        if issue.suggestion:
            self.console.print(f"\n[bold green]Suggestion:[/]\n{issue.suggestion}")
        
        if issue.code_suggestion:
            self.console.print("\n[bold green]Code Fix:[/]")
            # Try to detect language from file extension
            lang = "python"  # default
            if self.state.current_file:
                ext = Path(self.state.current_file).suffix.lower()
                lang_map = {".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go", ".rs": "rust"}
                lang = lang_map.get(ext, "text")
            
            syntax = Syntax(issue.code_suggestion, lang, theme="monokai", line_numbers=True)
            self.console.print(Panel(syntax, border_style="green"))
    
    def _render_review_progress(self) -> None:
        """Render review progress (placeholder - actual progress is shown inline)."""
        self.console.print("[bold blue]Reviewing files...[/]")
        self.console.print("[dim]Please wait while the AI analyzes your code.[/]")
    
    def _render_help(self) -> None:
        """Render the help screen."""
        help_text = """
# CodeRev TUI Help

## Navigation
- `j` / `↓` - Move cursor down
- `k` / `↑` - Move cursor up
- `J` / `K` - Page down / up
- `g` / `G` - Go to top / bottom
- `Enter` - Open directory / View file results
- `Esc` / `b` - Go back

## Selection
- `Space` - Toggle file selection
- `a` - Select all files
- `A` - Deselect all

## Review
- `r` - Start review of selected files
- `n` / `p` - Next / Previous issue
- `f` - Cycle focus areas
- `e` - Export results

## Options
- `.` - Toggle hidden files
- `/` - Toggle recursive mode

## General
- `?` / `h` - Show this help
- `q` - Quit
"""
        self.console.print(Markdown(help_text))
    
    def _get_current_items(self) -> list[Path]:
        """Get items in the current directory."""
        try:
            items = list(self.state.cwd.iterdir())
            
            # Filter hidden files
            if not self.state.show_hidden:
                items = [p for p in items if not p.name.startswith(".")]
            
            # Sort: directories first, then files
            dirs = sorted([p for p in items if p.is_dir()], key=lambda x: x.name.lower())
            files = sorted([p for p in items if p.is_file()], key=lambda x: x.name.lower())
            
            # Add parent directory if not at root
            result = []
            if self.state.cwd.parent != self.state.cwd:
                result.append(self.state.cwd.parent)
            result.extend(dirs)
            result.extend(files)
            
            return result
        except PermissionError:
            return []
    
    def _get_file_icon(self, path: Path) -> str:
        """Get an icon for a file based on its extension."""
        ext = path.suffix.lower()
        icons = {
            ".py": "🐍",
            ".js": "📜",
            ".ts": "📘",
            ".tsx": "⚛️",
            ".jsx": "⚛️",
            ".go": "🐹",
            ".rs": "🦀",
            ".rb": "💎",
            ".java": "☕",
            ".c": "📝",
            ".cpp": "📝",
            ".h": "📝",
            ".cs": "🎯",
            ".php": "🐘",
            ".swift": "🦅",
            ".kt": "🎯",
            ".md": "📄",
            ".json": "📋",
            ".yaml": "📋",
            ".yml": "📋",
            ".toml": "📋",
            ".txt": "📄",
            ".sh": "🐚",
            ".sql": "🗃️",
        }
        return icons.get(ext, "📄")
    
    def _handle_escape_sequence(self, seq: str) -> None:
        """Handle ANSI escape sequences (arrow keys, etc.)."""
        sequences = {
            "\x1b[A": self._move_up,    # Up arrow
            "\x1b[B": self._move_down,  # Down arrow
            "\x1b[C": self._select,     # Right arrow
            "\x1b[D": self._back,       # Left arrow
        }
        if seq in sequences:
            sequences[seq]()
    
    # ========================================================================
    # Actions
    # ========================================================================
    
    def _quit(self) -> None:
        """Quit the application."""
        self._running = False
    
    def _back(self) -> None:
        """Go back to the previous view."""
        if self.state.current_view == "help":
            self.state.current_view = "files"
        elif self.state.current_view == "issue":
            self.state.current_view = "results"
        elif self.state.current_view == "results":
            self.state.current_view = "files"
        elif self.state.current_view == "files":
            # Go to parent directory
            if self.state.cwd.parent != self.state.cwd:
                self.state.cwd = self.state.cwd.parent
                self.state.cursor_position = 0
                self.state.scroll_offset = 0
    
    def _move_down(self) -> None:
        """Move cursor down."""
        items = self._get_current_items() if self.state.current_view == "files" else list(self.state.review_results.keys())
        if self.state.cursor_position < len(items) - 1:
            self.state.cursor_position += 1
    
    def _move_up(self) -> None:
        """Move cursor up."""
        if self.state.cursor_position > 0:
            self.state.cursor_position -= 1
    
    def _page_down(self) -> None:
        """Page down."""
        height = self.console.size.height - 10
        items = self._get_current_items() if self.state.current_view == "files" else list(self.state.review_results.keys())
        self.state.cursor_position = min(self.state.cursor_position + height, len(items) - 1)
    
    def _page_up(self) -> None:
        """Page up."""
        height = self.console.size.height - 10
        self.state.cursor_position = max(self.state.cursor_position - height, 0)
    
    def _go_to_top(self) -> None:
        """Go to the first item."""
        self.state.cursor_position = 0
        self.state.scroll_offset = 0
    
    def _go_to_bottom(self) -> None:
        """Go to the last item."""
        items = self._get_current_items() if self.state.current_view == "files" else list(self.state.review_results.keys())
        self.state.cursor_position = len(items) - 1
    
    def _select(self) -> None:
        """Select/enter the current item."""
        if self.state.current_view == "files":
            items = self._get_current_items()
            if not items:
                return
            
            item = items[self.state.cursor_position]
            
            if item.is_dir():
                self.state.cwd = item.resolve()
                self.state.cursor_position = 0
                self.state.scroll_offset = 0
            else:
                self._toggle_select()
        
        elif self.state.current_view == "results":
            # Enter issue detail view
            files = list(self.state.review_results.keys())
            if files:
                self.state.current_file = files[self.state.cursor_position]
                self.state.current_issue_idx = 0
                self.state.current_view = "issue"
    
    def _toggle_select(self) -> None:
        """Toggle selection on the current file."""
        if self.state.current_view != "files":
            return
        
        items = self._get_current_items()
        if not items:
            return
        
        item = items[self.state.cursor_position]
        
        if item.is_file():
            if item in self.state.selected_files:
                self.state.selected_files.remove(item)
            else:
                self.state.selected_files.append(item)
    
    def _select_all(self) -> None:
        """Select all files in the current directory."""
        items = self._get_current_items()
        for item in items:
            if item.is_file() and item not in self.state.selected_files:
                self.state.selected_files.append(item)
    
    def _deselect_all(self) -> None:
        """Deselect all files."""
        self.state.selected_files.clear()
    
    def _start_review(self) -> None:
        """Start reviewing selected files."""
        if not self.state.selected_files:
            # If nothing selected, select current file
            items = self._get_current_items()
            if items and items[self.state.cursor_position].is_file():
                self.state.selected_files.append(items[self.state.cursor_position])
        
        if not self.state.selected_files:
            return
        
        self.state.current_view = "review"
        self._render()
        
        # Run the review
        try:
            if not self._reviewer:
                self._reviewer = CodeReviewer(config=self.config)
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
            ) as progress:
                task = progress.add_task("Reviewing files...", total=len(self.state.selected_files))
                
                for file_path in self.state.selected_files:
                    progress.update(task, description=f"Reviewing {file_path.name}...")
                    
                    try:
                        result = self._reviewer.review_file(file_path, focus=self.state.focus)
                        self.state.review_results[str(file_path)] = result
                    except Exception as e:
                        self.state.review_results[str(file_path)] = ReviewResult(
                            summary=f"Error: {e}",
                            issues=[],
                            score=-1,
                        )
                    
                    progress.advance(task)
            
            self.state.current_view = "results"
            self.state.cursor_position = 0
        
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/]")
            self.state.current_view = "files"
    
    def _next_issue(self) -> None:
        """Move to the next issue."""
        if self.state.current_view == "issue" and self.state.current_file:
            result = self.state.review_results.get(self.state.current_file)
            if result and self.state.current_issue_idx < len(result.issues) - 1:
                self.state.current_issue_idx += 1
    
    def _prev_issue(self) -> None:
        """Move to the previous issue."""
        if self.state.current_view == "issue" and self.state.current_issue_idx > 0:
            self.state.current_issue_idx -= 1
    
    def _toggle_hidden(self) -> None:
        """Toggle showing hidden files."""
        self.state.show_hidden = not self.state.show_hidden
        self.state.cursor_position = 0
    
    def _toggle_recursive(self) -> None:
        """Toggle recursive mode."""
        self.state.recursive = not self.state.recursive
    
    def _show_help(self) -> None:
        """Show the help screen."""
        self.state.current_view = "help"
    
    def _cycle_focus(self) -> None:
        """Cycle through focus area presets."""
        presets = [
            ["bugs", "security", "performance"],
            ["security"],
            ["performance"],
            ["style"],
            ["architecture"],
            ["bugs"],
        ]
        
        try:
            current_idx = presets.index(self.state.focus)
            self.state.focus = presets[(current_idx + 1) % len(presets)]
        except ValueError:
            self.state.focus = presets[0]
    
    def _export_results(self) -> None:
        """Export results to a JSON file."""
        if not self.state.review_results:
            return
        
        import json
        
        output_path = self.state.cwd / "coderev-results.json"
        
        results_dict = {}
        for path, result in self.state.review_results.items():
            results_dict[path] = {
                "summary": result.summary,
                "score": result.score,
                "issues": [
                    {
                        "message": i.message,
                        "severity": i.severity.value,
                        "category": i.category.value,
                        "line": i.line,
                        "suggestion": i.suggestion,
                    }
                    for i in result.issues
                ],
            }
        
        output_path.write_text(json.dumps(results_dict, indent=2))


def run_tui(
    config: Config | None = None,
    start_path: Path | str | None = None,
    simple_mode: bool = False,
) -> None:
    """Run the interactive TUI.
    
    Args:
        config: Optional CodeRev config.
        start_path: Starting directory path.
        simple_mode: Use simplified input mode (for non-TTY terminals).
    """
    app = TUIApp(config=config, start_path=start_path)
    
    if simple_mode:
        app.run_simple()
    else:
        # Try raw mode, fall back to simple mode
        try:
            app.run()
        except Exception:
            app.run_simple()
