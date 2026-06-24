"""Handle .coderevignore files for excluding paths from review."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Iterator


def _globstar_to_regex(pattern: str) -> str:
    """Translate a glob pattern containing ``**`` into a regex string.

    Unlike :mod:`fnmatch`, this distinguishes ``**`` (matches across directory
    separators, including *zero* segments) from ``*`` (matches within a single
    path segment). This mirrors gitignore semantics:

    * ``**/`` matches zero or more leading directories, so ``docs/**/*.md``
      matches both ``docs/x.md`` and ``docs/a/b.md``.
    * a trailing ``/**`` matches everything underneath a directory.
    * ``*`` and ``?`` never cross ``/``.
    """
    i = 0
    n = len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                j = i + 2
                if j < n and pattern[j] == "/":
                    # '**/' -> zero or more directory segments
                    out.append("(?:.*/)?")
                    i = j + 1
                    continue
                # trailing or bare '**' -> anything (including separators)
                out.append(".*")
                i = j
                continue
            # single '*' -> anything within a segment
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "/":
            out.append("/")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    return "".join(out)


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
    def load(cls, root: Path | None = None, use_gitignore: bool = False) -> CodeRevIgnore:
        """Load .coderevignore from root directory or search upward.

        Args:
            root: Directory to look in first; falls back to cwd then home.
            use_gitignore: When True, also fold in patterns from a sibling
                ``.gitignore`` so existing repo exclusions are reused. The
                ``.coderevignore`` patterns are applied last, so they (including
                negations) can override anything inherited from ``.gitignore``.
        """
        patterns: list[str] = []

        search_paths = []
        if root:
            search_paths.append(root / ".coderevignore")
        search_paths.extend([
            Path.cwd() / ".coderevignore",
            Path.home() / ".coderevignore",
        ])

        coderev_path: Path | None = None
        for path in search_paths:
            if path.exists():
                coderev_path = path
                break

        if use_gitignore:
            # Prefer a .gitignore next to the chosen .coderevignore, else one in
            # the requested root / cwd.
            gitignore_dirs = []
            if coderev_path:
                gitignore_dirs.append(coderev_path.parent)
            if root:
                gitignore_dirs.append(root)
            gitignore_dirs.append(Path.cwd())
            seen: set[Path] = set()
            for d in gitignore_dirs:
                gi = d / ".gitignore"
                if gi in seen:
                    continue
                seen.add(gi)
                if gi.exists():
                    patterns.extend(cls._parse_file(gi))
                    break

        if coderev_path:
            patterns.extend(cls._parse_file(coderev_path))

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

        We also normalize common user inputs like leading './' (CLI usage) and
        leading '/' (copy/pasted absolute-ish patterns) so matching stays
        predictable.
        """
        s = str(path).replace("\\", "/")
        # Match Windows' case-insensitive filesystem semantics.
        if os.name == "nt":
            s = s.lower()
        # Normalize common prefixes
        if s.startswith("./"):
            s = s[2:]
        # Treat leading slash as "root-relative" in the repo; we match against
        # relative paths so drop it.
        s = s.lstrip("/")
        return s

    def _normalize_pattern(self, pattern: str) -> str:
        """Normalize a pattern so matching is consistent across OSes."""
        p = pattern.replace("\\", "/").strip()
        # Allow users to use leading ./ or / (repo-relative) in patterns.
        if os.name == "nt":
            p = p.lower()
        if p.startswith("./"):
            p = p[2:]
        p = p.lstrip("/")
        return p

    def _matches(self, pattern: str, path_str: str, path_str_padded: str) -> bool:
        """Check whether a *normalized* pattern matches a *normalized* path string."""
        # Handle globstar patterns (containing **) with proper gitignore
        # semantics: ** crosses directory separators, * does not.
        if "**" in pattern:
            return self._matches_globstar(pattern, path_str)

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
            return False

        # Regular glob matching
        if fnmatch.fnmatch(path_str, pattern):
            return True
        if fnmatch.fnmatch(Path(path_str).name, pattern):
            return True
        return False

    def _matches_globstar(self, pattern: str, path_str: str) -> bool:
        """Match a pattern containing ``**`` against a normalized path string."""
        if pattern.endswith("/"):
            # Directory pattern: match the directory itself and anything under it.
            body = pattern.rstrip("/")
            regex = "^" + _globstar_to_regex(body) + "(?:/.*)?$"
        else:
            regex = "^" + _globstar_to_regex(pattern) + "$"
        return re.match(regex, path_str) is not None

    def should_ignore(self, path: Path | str) -> bool:
        """Check if a path should be ignored.

        Supports negation patterns prefixed with '!'. Like gitignore semantics,
        patterns are evaluated top-to-bottom and the last matching rule wins.
        """
        path_str = self._normalize_path(path)
        # Make directory-segment checks robust by ensuring separators at ends.
        path_str_padded = f"/{path_str.strip('/')}/"

        # Put defaults first so user-provided patterns (including negations)
        # can override them.
        all_patterns: list[str] = []
        if self._include_defaults:
            all_patterns.extend(DEFAULT_IGNORE_PATTERNS)
        all_patterns.extend(self.patterns)

        ignored = False

        for raw_pattern in all_patterns:
            raw_pattern = raw_pattern.strip()
            if not raw_pattern or raw_pattern.startswith("#"):
                continue

            negated = raw_pattern.startswith("!")
            pattern = raw_pattern[1:] if negated else raw_pattern
            pattern = self._normalize_pattern(pattern)
            if not pattern:
                continue

            if self._matches(pattern, path_str, path_str_padded):
                ignored = not negated

        return ignored
    
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


def should_ignore(
    path: Path | str,
    additional_patterns: list[str] | None = None,
    use_gitignore: bool = False,
) -> bool:
    """Convenience function to check if a path should be ignored.

    Args:
        path: The path to check.
        additional_patterns: Optional list of additional patterns to check against.
        use_gitignore: When True, also load patterns from a nearby ``.gitignore``.

    Returns:
        True if the path should be ignored.
    """
    ignorer = CodeRevIgnore.load(use_gitignore=use_gitignore)
    if additional_patterns:
        for pattern in additional_patterns:
            ignorer.add_pattern(pattern)
    return ignorer.should_ignore(path)
