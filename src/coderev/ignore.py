"""Handle .coderevignore files for excluding paths from review."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterator


DEFAULT_IGNORE_PATTERNS = [
    # Dependencies
    "node_modules/",
    "vendor/",
    "venv/",
    ".venv/",
    "__pycache__/",
    "*.pyc",
    
    # Build outputs
    "dist/",
    "build/",
    "*.egg-info/",
    ".next/",
    "out/",
    
    # IDE/Editor
    ".idea/",
    ".vscode/",
    "*.swp",
    "*.swo",
    
    # Version control
    ".git/",
    ".svn/",
    
    # Generated files
    "*.min.js",
    "*.min.css",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    
    # Test fixtures/snapshots
    "__snapshots__/",
    "*.snap",
    
    # Misc
    ".DS_Store",
    "Thumbs.db",
    "*.log",
]


class CodeRevIgnore:
    """Handle .coderevignore file parsing and matching."""
    
    def __init__(self, patterns: list[str] | None = None):
        self.patterns = patterns or []
        self._include_defaults = True
    
    @classmethod
    def load(cls, root: Path | None = None) -> CodeRevIgnore:
        """Load .coderevignore from root directory or search upward."""
        patterns: list[str] = []
        
        search_paths = []
        if root:
            search_paths.append(root / ".coderevignore")
        search_paths.extend([
            Path.cwd() / ".coderevignore",
            Path.home() / ".coderevignore",
        ])
        
        for path in search_paths:
            if path.exists():
                patterns.extend(cls._parse_file(path))
                break
        
        return cls(patterns)
    
    @staticmethod
    def _parse_file(path: Path) -> list[str]:
        """Parse a .coderevignore file."""
        patterns = []
        
        with open(path) as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith("#"):
                    patterns.append(line)
        
        return patterns
    
    def _normalize_path(self, path: Path | str) -> str:
        """Normalize paths so ignore patterns behave consistently across OSes.

        On Windows, file paths often contain backslashes, while ignore patterns
        typically use forward slashes. We normalize to a POSIX-style string.
        """
        return str(path).replace("\\", "/")

    def should_ignore(self, path: Path | str) -> bool:
        """Check if a path should be ignored."""
        path_str = self._normalize_path(path)
        # Make directory-segment checks robust by ensuring separators at ends.
        path_str_padded = f"/{path_str.strip('/')}/"

        all_patterns = self.patterns.copy()
        if self._include_defaults:
            all_patterns.extend(DEFAULT_IGNORE_PATTERNS)

        for pattern in all_patterns:
            # Normalize pattern too (users may copy Windows paths into ignore file)
            pattern = pattern.replace("\\", "/")

            # Handle directory patterns (ending with /)
            if pattern.endswith("/"):
                dir_pattern = pattern.rstrip("/")
                # Match path segments (e.g. /node_modules/ anywhere in the path)
                if f"/{dir_pattern}/" in path_str_padded:
                    return True
                # Fallback glob matching
                if fnmatch.fnmatch(path_str, f"*/{dir_pattern}/*"):
                    return True
                if fnmatch.fnmatch(path_str, f"{dir_pattern}/*"):
                    return True
            else:
                # Regular glob matching
                if fnmatch.fnmatch(path_str, pattern):
                    return True
                if fnmatch.fnmatch(Path(path_str).name, pattern):
                    return True

        return False
    
    def filter_paths(self, paths: list[Path]) -> Iterator[Path]:
        """Filter a list of paths, yielding only non-ignored ones."""
        for path in paths:
            if not self.should_ignore(path):
                yield path
    
    def add_pattern(self, pattern: str) -> None:
        """Add a custom ignore pattern."""
        self.patterns.append(pattern)
    
    def disable_defaults(self) -> None:
        """Disable default ignore patterns."""
        self._include_defaults = False


def should_ignore(path: Path | str, additional_patterns: list[str] | None = None) -> bool:
    """Convenience function to check if a path should be ignored.
    
    Args:
        path: The path to check.
        additional_patterns: Optional list of additional patterns to check against.
    
    Returns:
        True if the path should be ignored.
    """
    ignorer = CodeRevIgnore.load()
    if additional_patterns:
        for pattern in additional_patterns:
            ignorer.add_pattern(pattern)
    return ignorer.should_ignore(path)
