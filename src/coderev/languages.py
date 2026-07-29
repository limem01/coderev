"""Shared file-extension → programming-language detection.

Single source of truth for mapping a file's extension to a language name.
Previously each of ``reviewer``, ``async_reviewer`` and ``cost`` carried its own
copy of an extension map (returning ``None`` for unknown files), while the
``github``, ``gitlab`` and ``bitbucket`` PR clients carried yet another copy
(returning ``""``). The copies had drifted apart -- e.g. ``github`` never
detected ``.yaml``/``.json``/``.md`` and none of the review-side maps knew
``.vue``/``.svelte`` -- so the same file could be labelled differently
depending on which code path reviewed it. This module unifies them.

Two entry points preserve the two historical return contracts:

- :func:`detect_language` returns ``str | None`` (for the reviewer/cost paths).
- :func:`detect_language_from_filename` returns ``str`` (``""`` when unknown,
  for the PR-client paths, whose callers build a fenced code block from it).
"""

from __future__ import annotations

from pathlib import Path
from typing import Union


# Canonical file-extension → language-name map. Union of the historical
# per-module maps plus a few common, unambiguous additions. Extensions are
# lowercase and include the leading dot.
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".cs": "csharp",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".vue": "vue",
    ".svelte": "svelte",
}


# Human-written language aliases → the canonical names used as values in
# ``EXTENSION_MAP`` (and therefore emitted by :func:`detect_language`). Users
# write these freely in custom-rule YAML (``languages: [C++, golang, js]``), so
# a rule keyed on an alias must still match a file that ``detect_language``
# labels with the canonical name. Keys are lowercase; a name already canonical
# maps to itself implicitly (an unknown name is returned unchanged), so this map
# only needs to list the *aliases*.
LANGUAGE_ALIASES: dict[str, str] = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "ecmascript": "javascript",
    "ts": "typescript",
    "golang": "go",
    "rs": "rust",
    "rb": "ruby",
    "kt": "kotlin",
    "c++": "cpp",
    "cplusplus": "cpp",
    "cs": "csharp",
    "c#": "csharp",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "yml": "yaml",
    "md": "markdown",
}


def normalize_language(name: str) -> str:
    """Fold a human-written language name to its canonical form.

    Lowercases and strips ``name``, then maps common aliases (``c++`` → ``cpp``,
    ``golang`` → ``go``, ``js`` → ``javascript``, ...) to the canonical names
    :func:`detect_language` emits. A name that is already canonical, or simply
    unrecognized, is returned lowercased/stripped and otherwise unchanged, so
    exact matches keep working and no valid input is dropped.

    Args:
        name: A language name, possibly an alias or differently cased.

    Returns:
        The canonical language name.
    """
    key = name.strip().lower()
    return LANGUAGE_ALIASES.get(key, key)


def detect_language(path: Union[str, Path]) -> str | None:
    """Detect the language for a path's file extension.

    Args:
        path: A file path (``str`` or :class:`~pathlib.Path`). Only the
            extension is inspected; the file need not exist.

    Returns:
        The language name, or ``None`` if the extension is unknown.
    """
    return EXTENSION_MAP.get(Path(path).suffix.lower())


def detect_language_from_filename(filename: str) -> str:
    """Detect the language for a filename's extension, defaulting to ``""``.

    Same mapping as :func:`detect_language`, but returns an empty string for
    unknown extensions so callers can splice it directly into a Markdown code
    fence (```` ```{language} ````).

    Args:
        filename: The file name or path.

    Returns:
        The language name, or ``""`` if the extension is unknown.
    """
    return detect_language(filename) or ""
