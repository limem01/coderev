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
    * a ``/**/`` in the middle matches zero or more directories.
    * ``**`` that is *not* bounded by ``/`` (or the pattern boundary) is treated
      as regular asterisks and does not cross ``/`` -- gitignore: "other
      consecutive asterisks are considered regular asterisks". So ``a**b``
      matches ``axxb`` but not ``ax/yb``.
    * ``*`` and ``?`` never cross ``/``.
    * ``[...]`` character classes (including ranges like ``[a-z]`` and negations
      like ``[!0-9]``) match a single character, mirroring gitignore.
    """
    i = 0
    n = len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "[":
            # Parse a character class, e.g. [abc], [a-z], [!0-9].
            j = i + 1
            if j < n and pattern[j] in ("!", "^"):
                j += 1
            # A ']' immediately after the (optional) negation is a literal.
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                # Unterminated class: treat '[' as a literal character.
                out.append(re.escape("["))
                i += 1
                continue
            inner = pattern[i + 1 : j]
            # Translate a leading '!' (glob negation) to regex '^'.
            if inner.startswith("!"):
                inner = "^" + inner[1:]
            # Escape backslashes so the class can't introduce regex escapes.
            inner = inner.replace("\\", "\\\\")
            out.append("[" + inner + "]")
            i = j + 1
            continue
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # ``**`` is only special when bounded by ``/`` or the pattern
                # boundary; otherwise gitignore treats it as regular asterisks.
                prev_boundary = i == 0 or pattern[i - 1] == "/"
                j = i + 2
                next_slash = j < n and pattern[j] == "/"
                next_end = j == n
                if prev_boundary and next_slash:
                    # leading '**/' or middle '/**/' -> zero or more dir segments
                    out.append("(?:.*/)?")
                    i = j + 1
                    continue
                if prev_boundary and next_end:
                    # trailing '/**' (or a bare '**' pattern) -> anything,
                    # including separators
                    out.append(".*")
                    i = j
                    continue
                # '**' not bounded by '/' -> regular asterisks, stay in-segment
                out.append("[^/]*")
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
        # Lazily-built list of (matcher_callable, negated) tuples. Building it
        # parses, normalizes and (where relevant) compiles regexes for every
        # pattern exactly once, instead of repeating that work for every path
        # checked. Invalidated whenever the pattern set changes.
        self._compiled: list[tuple] | None = None
    
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
        """Parse a .coderevignore file.

        Lines are kept verbatim apart from the trailing newline so that
        gitignore escape semantics handled later (``\\#``/``\\!`` literals and
        backslash-escaped trailing spaces) survive intact. Blank lines are
        skipped here; comment and escape interpretation happens in
        :meth:`_preprocess_line`.
        """
        patterns = []

        with open(path) as f:
            for line in f:
                line = line.rstrip("\n").rstrip("\r")
                # Skip clearly empty lines; keep trailing spaces (which may be
                # backslash-escaped) and any leading backslash on real patterns.
                if line.strip() == "":
                    continue
                patterns.append(line)

        return patterns

    @staticmethod
    def _strip_trailing_ws(line: str) -> str:
        """Strip trailing whitespace unless it is backslash-escaped.

        Mirrors gitignore: ``foo  `` -> ``foo`` but ``foo\\ `` keeps a single
        trailing space (the escaping backslash is consumed).
        """
        i = len(line)
        while i > 0 and line[i - 1] in " \t":
            i -= 1
        if i == len(line):
            return line
        prefix, trailing = line[:i], line[i:]
        # Count backslashes immediately preceding the whitespace run.
        nb = 0
        while nb < len(prefix) and prefix[len(prefix) - 1 - nb] == "\\":
            nb += 1
        if nb % 2 == 1:
            # The first whitespace char is escaped: drop the backslash, keep it.
            return prefix[:-1] + trailing[0]
        return prefix

    @staticmethod
    def _preprocess_line(raw: str) -> tuple[str, bool] | None:
        """Interpret a raw ignore line per gitignore escape rules.

        Returns ``(pattern, negated)`` or ``None`` for blank/comment lines.

        * Unescaped leading ``#`` marks a comment.
        * ``\\#`` / ``\\!`` are literal leading ``#`` / ``!`` (the backslash is
          consumed, and ``\\!`` is *not* a negation).
        * A leading ``!`` negates the pattern.
        * Trailing whitespace is stripped unless backslash-escaped.
        """
        line = CodeRevIgnore._strip_trailing_ws(raw)
        if not line or line.startswith("#"):
            return None

        negated = False
        if line.startswith("\\#") or line.startswith("\\!"):
            line = line[1:]
        elif line.startswith("!"):
            negated = True
            line = line[1:]

        if not line:
            return None
        return line, negated
    
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

    def _normalize_pattern(self, pattern: str) -> tuple[str, bool]:
        """Normalize a pattern so matching is consistent across OSes.

        Returns a ``(pattern, anchored)`` tuple. Following gitignore semantics, a
        leading ``/`` (or ``./``) anchors the pattern to the repository root, so
        ``/build/`` matches a top-level ``build/`` but not a nested
        ``src/build/``. Patterns without a leading separator continue to match at
        any depth.
        """
        p = pattern.replace("\\", "/").strip()
        # Allow users to use leading ./ or / (repo-relative) in patterns.
        if os.name == "nt":
            p = p.lower()
        anchored = False
        if p.startswith("./"):
            p = p[2:]
            anchored = True
        if p.startswith("/"):
            p = p.lstrip("/")
            anchored = True
        # gitignore semantics: a separator anywhere except a lone trailing one
        # anchors the pattern to the repo root (so ``src/*.py`` is relative to
        # root and its ``*`` does not cross directory separators). Patterns with
        # no internal separator (e.g. ``build/``, ``*.py``) still match at any
        # depth.
        if not anchored:
            core = p[:-1] if p.endswith("/") else p
            if "/" in core:
                anchored = True
        return p, anchored

    def _matches(
        self,
        pattern: str,
        path_str: str,
        path_str_padded: str,
        anchored: bool = False,
    ) -> bool:
        """Check whether a *normalized* pattern matches a *normalized* path string."""
        # Handle globstar patterns (containing **) with proper gitignore
        # semantics: ** crosses directory separators, * does not. Globstar
        # patterns are already anchored at the start of the path via regex.
        if "**" in pattern:
            return self._matches_globstar(pattern, path_str)

        # Anchored patterns (leading '/' or './') must match from the repo root.
        # Reuse the globstar regex builder: it anchors with ^...$ and keeps '*'
        # within a single path segment, giving true gitignore anchoring.
        if anchored:
            return self._matches_globstar(pattern, path_str)

        # Handle directory patterns (ending with /). An unanchored directory
        # pattern has no internal separator (an internal '/' would have anchored
        # it), so its name must match a single path *segment*. Matching each
        # segment individually keeps the match "at any depth" while stopping a
        # wildcard from crossing '/': ``foo*bar/`` matches ``a/fooXbar/y`` but
        # not ``foo/x/bar/z``, mirroring gitignore's FNM_PATHNAME semantics.
        if pattern.endswith("/"):
            dir_pattern = pattern.rstrip("/")
            return any(
                fnmatch.fnmatch(seg, dir_pattern)
                for seg in path_str.split("/")
                if seg
            )

        # Regular glob matching. An unanchored pattern with no separator matches
        # "at any level" (gitignore semantics), but its ``*``/``?`` must not
        # cross directory separators. Matching each path *segment* individually
        # gives both properties: it matches a basename like ``a.py`` against
        # ``*.py`` at any depth, and a directory component like ``foo`` against
        # ``foo`` -- while never letting a wildcard span a ``/``.
        return any(fnmatch.fnmatch(seg, pattern) for seg in path_str.split("/") if seg)

    @staticmethod
    def _compile_globstar(pattern: str) -> re.Pattern:
        """Compile a globstar/anchored pattern into an anchored regex.

        Shared by both the lazy per-path matcher and :meth:`_matches_globstar`
        so the two paths can never drift apart.
        """
        if pattern.endswith("/"):
            # Directory pattern: match the directory itself and anything under it.
            body = pattern.rstrip("/")
            regex = "^" + _globstar_to_regex(body) + "(?:/.*)?$"
        else:
            regex = "^" + _globstar_to_regex(pattern) + "$"
        return re.compile(regex)

    def _matches_globstar(self, pattern: str, path_str: str) -> bool:
        """Match a pattern containing ``**`` against a normalized path string."""
        return self._compile_globstar(pattern).match(path_str) is not None

    def _build_matcher(self, pattern: str, anchored: bool):
        """Pre-build a matcher callable for a *normalized* pattern.

        The returned callable has signature ``(path_str, path_str_padded) ->
        bool`` and mirrors the dispatch in :meth:`_matches`, but any regex
        compilation happens here (once) rather than on every path check.
        """
        # Globstar and anchored patterns are matched via an anchored regex.
        if "**" in pattern or anchored:
            regex = self._compile_globstar(pattern)
            return lambda ps, _pp: regex.match(ps) is not None

        # Directory patterns (ending with '/') match a path segment anywhere.
        # Match each segment individually so the pattern applies at any depth
        # while its wildcards never cross '/' (see :meth:`_matches`).
        if pattern.endswith("/"):
            dir_pattern = pattern.rstrip("/")

            def _dir_match(ps: str, _pp: str) -> bool:
                return any(
                    fnmatch.fnmatch(seg, dir_pattern)
                    for seg in ps.split("/")
                    if seg
                )

            return _dir_match

        # Regular glob: match any single path segment (see :meth:`_matches`).
        # Segment-wise matching keeps ``*``/``?`` from crossing ``/`` while still
        # matching at any depth, mirroring gitignore's no-separator patterns.
        def _glob_match(ps: str, _pp: str) -> bool:
            return any(fnmatch.fnmatch(seg, pattern) for seg in ps.split("/") if seg)

        return _glob_match

    def _compiled_patterns(self) -> list[tuple]:
        """Return the cached list of ``(matcher, negated)`` tuples, building it
        on first use. Defaults come first so user patterns (incl. negations)
        can override them, matching :meth:`should_ignore`'s ordering."""
        if self._compiled is not None:
            return self._compiled

        all_patterns: list[str] = []
        if self._include_defaults:
            all_patterns.extend(DEFAULT_IGNORE_PATTERNS)
        all_patterns.extend(self.patterns)

        compiled: list[tuple] = []
        for raw_pattern in all_patterns:
            parsed = self._preprocess_line(raw_pattern)
            if parsed is None:
                continue
            pattern, negated = parsed
            pattern, anchored = self._normalize_pattern(pattern)
            if not pattern:
                continue
            compiled.append((self._build_matcher(pattern, anchored), negated))

        self._compiled = compiled
        return compiled

    def should_ignore(self, path: Path | str) -> bool:
        """Check if a path should be ignored.

        Supports negation patterns prefixed with '!'. Like gitignore semantics,
        patterns are evaluated top-to-bottom and the last matching rule wins.
        """
        path_str = self._normalize_path(path)
        # Make directory-segment checks robust by ensuring separators at ends.
        path_str_padded = f"/{path_str.strip('/')}/"

        # Patterns are compiled once and cached; the last matching rule wins so
        # negations can re-include paths excluded by an earlier rule.
        ignored = False
        for matcher, negated in self._compiled_patterns():
            if matcher(path_str, path_str_padded):
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
        self._compiled = None  # invalidate cache

    def disable_defaults(self) -> None:
        """Disable default ignore patterns."""
        self._include_defaults = False
        self._compiled = None  # invalidate cache


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
