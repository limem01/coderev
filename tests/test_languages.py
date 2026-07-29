"""Tests for the shared language-detection module (``coderev.languages``)."""

from pathlib import Path

import pytest

from coderev.languages import (
    EXTENSION_MAP,
    LANGUAGE_ALIASES,
    detect_language,
    detect_language_from_filename,
    normalize_language,
)


class TestDetectLanguage:
    """``detect_language`` returns a language name or ``None``."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("test.py", "python"),
            ("app.js", "javascript"),
            ("mod.mjs", "javascript"),
            ("mod.cjs", "javascript"),
            ("component.tsx", "typescript"),
            ("component.jsx", "javascript"),
            ("server.go", "go"),
            ("lib.rs", "rust"),
            ("Model.java", "java"),
            ("main.kt", "kotlin"),
            ("a.cpp", "cpp"),
            ("a.cc", "cpp"),
            ("a.cxx", "cpp"),
            ("a.hpp", "cpp"),
            ("a.c", "c"),
            ("a.h", "c"),
            ("a.cs", "csharp"),
            ("a.php", "php"),
            ("a.swift", "swift"),
            ("a.scala", "scala"),
            ("q.sql", "sql"),
            ("run.sh", "bash"),
            ("run.bash", "bash"),
            ("config.yml", "yaml"),
            ("config.yaml", "yaml"),
            ("data.json", "json"),
            ("README.md", "markdown"),
            ("App.vue", "vue"),
            ("Widget.svelte", "svelte"),
        ],
    )
    def test_known_extensions(self, path, expected):
        assert detect_language(path) == expected

    def test_accepts_path_object(self):
        assert detect_language(Path("src/pkg/mod.py")) == "python"

    def test_case_insensitive_extension(self):
        assert detect_language("SCRIPT.PY") == "python"
        assert detect_language("Component.TSX") == "typescript"

    def test_unknown_returns_none(self):
        assert detect_language("mystery.xyz") is None
        assert detect_language("Makefile") is None
        assert detect_language(".gitignore") is None

    def test_multi_dot_uses_final_extension(self):
        assert detect_language("archive.test.py") == "python"
        assert detect_language("bundle.min.js") == "javascript"


class TestDetectLanguageFromFilename:
    """``detect_language_from_filename`` returns a name or ``""``."""

    def test_known_extension(self):
        assert detect_language_from_filename("main.py") == "python"

    def test_unknown_returns_empty_string(self):
        assert detect_language_from_filename("mystery.xyz") == ""
        assert detect_language_from_filename("Dockerfile") == ""

    def test_agrees_with_detect_language(self):
        # For every known extension the two entry points must agree.
        for ext, lang in EXTENSION_MAP.items():
            name = f"file{ext}"
            assert detect_language_from_filename(name) == lang
            assert detect_language(name) == lang


class TestSharedByAllModules:
    """The per-module wrappers all delegate to the shared implementation."""

    def test_pr_clients_reexport_same_object(self):
        from coderev import bitbucket, github, gitlab
        from coderev import languages

        assert (
            github.detect_language_from_filename
            is languages.detect_language_from_filename
        )
        assert (
            gitlab.detect_language_from_filename
            is languages.detect_language_from_filename
        )
        assert (
            bitbucket.detect_language_from_filename
            is languages.detect_language_from_filename
        )

    def test_reviewer_detect_language_matches(self):
        from coderev.reviewer import CodeReviewer

        reviewer = CodeReviewer(api_key="test-key")
        assert reviewer._detect_language(Path("a.vue")) == "vue"
        assert reviewer._detect_language(Path("a.xyz")) is None

    def test_cost_estimator_detect_language_matches(self):
        from coderev.cost import CostEstimator

        estimator = CostEstimator(model="claude-3-sonnet")
        assert estimator._detect_language(Path("a.scala")) == "scala"
        assert estimator._detect_language(Path("a.xyz")) is None


class TestNormalizeLanguage:
    """``normalize_language`` folds human aliases to canonical names."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("py", "python"),
            ("python3", "python"),
            ("js", "javascript"),
            ("node", "javascript"),
            ("nodejs", "javascript"),
            ("ecmascript", "javascript"),
            ("ts", "typescript"),
            ("golang", "go"),
            ("rs", "rust"),
            ("rb", "ruby"),
            ("kt", "kotlin"),
            ("c++", "cpp"),
            ("cplusplus", "cpp"),
            ("cs", "csharp"),
            ("c#", "csharp"),
            ("sh", "bash"),
            ("shell", "bash"),
            ("zsh", "bash"),
            ("yml", "yaml"),
            ("md", "markdown"),
        ],
    )
    def test_aliases_fold_to_canonical(self, name, expected):
        assert normalize_language(name) == expected

    def test_case_insensitive_and_stripped(self):
        assert normalize_language("  C++  ") == "cpp"
        assert normalize_language("GoLang") == "go"
        assert normalize_language("Python") == "python"

    def test_canonical_names_map_to_themselves(self):
        # Every canonical name (a value in EXTENSION_MAP) is idempotent.
        for canonical in set(EXTENSION_MAP.values()):
            assert normalize_language(canonical) == canonical

    def test_unknown_returned_lowercased_unchanged(self):
        assert normalize_language("Haskell") == "haskell"
        assert normalize_language("cobol") == "cobol"

    def test_every_alias_targets_a_canonical_name(self):
        # Guard against an alias pointing at a name no extension produces.
        canonical = set(EXTENSION_MAP.values())
        for alias, target in LANGUAGE_ALIASES.items():
            assert target in canonical, f"{alias} -> {target} is not canonical"
