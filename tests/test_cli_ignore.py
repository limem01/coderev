"""Tests that the CLI's file collection honors .coderevignore.

The `.coderevignore` engine (coderev.ignore) was fully implemented and heavily
tested on its own, but `collect_files` never consulted it -- so `review` and
`estimate` would expand a directory into files the user had explicitly ignored,
sending them to the API and inflating cost estimates. These tests lock in that
`collect_files` filters ignored files by default, that `use_ignore=False` opts
out, and that an explicitly named file is never filtered.
"""

from pathlib import Path

import pytest

from coderev.cli import collect_files


def _names(files):
    return sorted(Path(f).name for f in files)


class TestCollectFilesRespectsIgnore:
    def test_ignored_file_is_dropped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "keep.py").write_text("pass")
        (tmp_path / "secret.py").write_text("pass")
        (tmp_path / ".coderevignore").write_text("secret.py\n")

        files = collect_files((".",), recursive=True)

        assert "secret.py" not in _names(files)
        assert "keep.py" in _names(files)

    def test_ignored_directory_contents_dropped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("pass")
        build = tmp_path / "build"
        build.mkdir()
        (build / "out.py").write_text("pass")
        (tmp_path / ".coderevignore").write_text("build/\n")

        files = collect_files((".",), recursive=True)

        assert "out.py" not in _names(files)
        assert "app.py" in _names(files)

    def test_root_anchored_pattern_matches_top_level_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Use a directory name not in DEFAULT_IGNORE_PATTERNS so the anchoring
        # behavior is what's under test, not a default rule.
        top = tmp_path / "gen"
        top.mkdir()
        (top / "a.py").write_text("pass")
        nested = tmp_path / "src" / "gen"
        nested.mkdir(parents=True)
        (nested / "b.py").write_text("pass")
        # Anchored: only the top-level gen/ is ignored, not src/gen/.
        (tmp_path / ".coderevignore").write_text("/gen/\n")

        files = collect_files((".",), recursive=True)
        rels = sorted(
            str(Path(f).resolve().relative_to(tmp_path)).replace("\\", "/")
            for f in files
        )

        assert "gen/a.py" not in rels
        assert "src/gen/b.py" in rels

    def test_negation_reincludes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "debug.log").write_text("x")
        (logs / "important.log").write_text("x")
        # Ignore the contents of logs/ but re-include important.log.
        (tmp_path / ".coderevignore").write_text("logs/*\n!logs/important.log\n")

        files = collect_files((".",), recursive=True)

        assert "debug.log" not in _names(files)
        assert "important.log" in _names(files)

    def test_use_ignore_false_disables_filtering(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "keep.py").write_text("pass")
        (tmp_path / "secret.py").write_text("pass")
        (tmp_path / ".coderevignore").write_text("secret.py\n")

        files = collect_files((".",), recursive=True, use_ignore=False)

        assert "secret.py" in _names(files)

    def test_explicit_file_argument_is_never_filtered(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        secret = tmp_path / "secret.py"
        secret.write_text("pass")
        (tmp_path / ".coderevignore").write_text("secret.py\n")

        # Naming the file directly overrides the ignore rule, mirroring how an
        # explicit path beats a broad exclude.
        files = collect_files((str(secret),), recursive=True)

        assert "secret.py" in _names(files)

    def test_exclude_and_ignore_compose(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.py").write_text("pass")
        (tmp_path / "c.py").write_text("pass")
        (tmp_path / ".coderevignore").write_text("a.py\n")

        files = collect_files((".",), recursive=True, exclude=("b.py",))

        got = _names(files)
        assert "a.py" not in got  # dropped by .coderevignore
        assert "b.py" not in got  # dropped by --exclude
        assert "c.py" in got
