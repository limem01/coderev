"""Handle .coderevignore files for excluding paths from review."""

from __future__ import annotations

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
    * a backslash escapes the following glob metacharacter, so ``\\*`` matches a
      literal ``*`` rather than acting as a wildcard.
    """
    i = 0
    n = len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "\\":
            # Escape: the next character is a literal, never a metacharacter.
            # A trailing lone backslash is itself a literal.
            if i + 1 < n:
                out.append(re.escape(pattern[i + 1]))
                i += 2
            else:
                out.append(re.escape("\\"))
                i += 1
            continue
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


# Characters a backslash may escape inside a pattern. A backslash before any
# *other* character is treated as a Windows path separator (see
# :meth:`CodeRevIgnore._normalize_pattern`), which is why this set is explicit
# rather than "escape anything".
ESCAPABLE_CHARS = set("*?[]!#\\ ")


def _has_globstar(pattern: str) -> bool:
    """True if ``pattern`` contains an *unescaped* ``**``.

    ``a\\**`` is a literal ``*`` followed by a wildcard, not a globstar, so a
    naive ``"**" in pattern`` check would route it down the wrong branch.
    """
    i = 0
    n = len(pattern)
    while i < n:
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern.startswith("**", i):
            return True
        i += 1
    return False


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

    @staticmethod
    def _fold_separators(pattern: str) -> str:
        """Fold Windows separators to ``/`` while preserving escape sequences.

        A backslash followed by a glob metacharacter is an escape and is kept
        verbatim (``\\*`` stays ``\\*``); any other backslash is a Windows path
        separator and becomes ``/``.
        """
        out: list[str] = []
        i = 0
        n = len(pattern)
        while i < n:
            c = pattern[i]
            if c == "\\" and i + 1 < n and pattern[i + 1] in ESCAPABLE_CHARS:
                out.append(pattern[i : i + 2])
                i += 2
                continue
            out.append("/" if c == "\\" else c)
            i += 1
        return "".join(out)

    def _normalize_pattern(self, pattern: str) -> tuple[str, bool]:
        """Normalize a pattern so matching is consistent across OSes.

        Returns a ``(pattern, anchored)`` tuple. Following gitignore semantics, a
        leading ``/`` (or ``./``) anchors the pattern to the repository root, so
        ``/build/`` matches a top-level ``build/`` but not a nested
        ``src/build/``. Patterns without a leading separator continue to match at
        any depth.

        A backslash before a glob metacharacter (see :data:`ESCAPABLE_CHARS`) is
        kept as an escape, so ``report\\*.csv`` matches a file literally named
        ``report*.csv``. A backslash before anything else is a Windows path
        separator and is folded to ``/``, keeping ``src\\generated\\`` working.
        """
        p = self._fold_separators(pattern).lstrip()
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
        # Delegate to the same matcher the cached path uses, so the two can
        # never drift apart.
        return self._build_matcher(pattern, anchored)(path_str, path_str_padded)

    @staticmethod
    def _compile_segment(pattern: str) -> re.Pattern:
        """Compile a separator-free pattern into a regex matching one segment.

        Used for unanchored patterns, which match a single path segment at any
        depth. We build the regex with :func:`_globstar_to_regex` rather than
        using :mod:`fnmatch` so that backslash escapes (``\\*``, ``\\?``,
        ``\\[``) are honored here exactly as they are on the anchored/globstar
        path -- ``fnmatch`` has no escape syntax.
        """
        return re.compile("^" + _globstar_to_regex(pattern) + "$")

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
            # No trailing slash: gitignore matches both files and directories,
            # and when the match is a directory everything under it is ignored
            # too. So allow an optional ``/...`` suffix -- ``/build`` matches
            # ``build`` and ``build/foo.py`` alike, exactly like ``git`` does.
            regex = "^" + _globstar_to_regex(pattern) + "(?:/.*)?$"
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
        if _has_globstar(pattern) or anchored:
            regex = self._compile_globstar(pattern)
            return lambda ps, _pp: regex.match(ps) is not None

        # Unanchored patterns (directory or not) have no internal separator, so
        # they match a single path *segment* at any depth. Matching each segment
        # individually keeps the "any depth" behavior while stopping a wildcard
        # from crossing '/': ``foo*bar/`` matches ``a/fooXbar/y`` but not
        # ``foo/x/bar/z``, mirroring gitignore's FNM_PATHNAME semantics.
        regex = self._compile_segment(pattern.rstrip("/"))

        def _segment_match(ps: str, _pp: str) -> bool:
            return any(regex.match(seg) for seg in ps.split("/") if seg)

        return _segment_match

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
            # A trailing '/' means the pattern matches directories only
            # (gitignore: "the pattern will only match directories").
            dir_only = pattern.endswith("/")
            compiled.append((self._build_matcher(pattern, anchored), negated, dir_only))

        self._compiled = compiled
        return compiled

    def should_ignore(self, path: Path | str, is_dir: bool | None = None) -> bool:
        """Check if a path should be ignored.

        Supports negation patterns prefixed with '!'. Like gitignore semantics,
        patterns are evaluated top-to-bottom and the last matching rule wins.

        A trailing-slash pattern matches directories only (gitignore: "if there
        is a separator at the end of the pattern then the pattern will only
        match directories"). ``is_dir`` tells us whether the *leaf* of ``path``
        is a directory; when ``None`` it is inferred from disk if the path
        exists, and otherwise assumed unknown (dir-only rules still apply, for
        backwards compatibility). Ancestor prefixes of ``path`` are always
        directories, so dir-only rules always apply to them.

        Follows gitignore's parent-directory rule: "It is not possible to
        re-include a file if a parent directory of that file is excluded." We
        therefore evaluate every ancestor directory prefix from the top down;
        once a directory prefix is excluded, everything beneath it stays
        ignored regardless of later ``!`` negations that would otherwise match
        the file. This is what makes ``build/`` + ``!build/keep.txt`` keep
        ``build/keep.txt`` ignored (the directory itself is excluded), while
        ``build/*`` + ``!build/keep.txt`` still re-includes it (the ``build``
        directory is never excluded, only its contents).
        """
        path_str = self._normalize_path(path)
        if not path_str:
            return False

        # Determine whether the leaf is a directory so dir-only ('foo/')
        # patterns don't match a regular file of the same name. If not told,
        # infer from disk when the path exists; otherwise leave it unknown
        # (None) so dir-only rules still apply as before.
        if is_dir is None:
            try:
                p = path if isinstance(path, Path) else Path(path)
                if p.exists():
                    is_dir = p.is_dir()
            except (OSError, ValueError):
                is_dir = None

        segments = [s for s in path_str.split("/") if s]
        rules = self._compiled_patterns()

        ignored = False
        prefix_parts: list[str] = []
        for seg in segments:
            prefix_parts.append(seg)
            if ignored:
                # A parent directory is already excluded; gitignore forbids
                # re-including anything beneath it, so short-circuit and keep
                # the whole subtree ignored.
                return True
            prefix = "/".join(prefix_parts)
            # Every non-final prefix is an ancestor directory; only the final
            # segment's directory-ness is in question.
            is_last = len(prefix_parts) == len(segments)
            leaf_is_dir = is_dir if is_last else True
            # The second matcher argument is unused by the compiled matchers;
            # pass a padded form for backward compatibility.
            prefix_padded = f"/{prefix}/"
            for matcher, negated, dir_only in rules:
                # A dir-only rule cannot match a leaf we know to be a file.
                if dir_only and leaf_is_dir is False:
                    continue
                if matcher(prefix, prefix_padded):
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
