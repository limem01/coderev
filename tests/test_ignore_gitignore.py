"""Tests for optional .gitignore integration in CodeRevIgnore."""

from pathlib import Path

from coderev.ignore import CodeRevIgnore, should_ignore


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestGitignoreIntegration:
    def test_gitignore_not_loaded_by_default(self, tmp_path):
        _write(tmp_path / ".gitignore", ["secrets/"])
        ignore = CodeRevIgnore.load(root=tmp_path)
        assert ignore.should_ignore("secrets/key.txt") is False

    def test_gitignore_loaded_when_enabled(self, tmp_path):
        _write(tmp_path / ".gitignore", ["secrets/", "*.tmp"])
        ignore = CodeRevIgnore.load(root=tmp_path, use_gitignore=True)
        assert ignore.should_ignore("secrets/key.txt") is True
        assert ignore.should_ignore("scratch.tmp") is True

    def test_gitignore_comments_and_blanks_skipped(self, tmp_path):
        _write(tmp_path / ".gitignore", ["# a comment", "", "build/"])
        ignore = CodeRevIgnore.load(root=tmp_path, use_gitignore=True)
        assert ignore.should_ignore("build/out.o") is True

    def test_coderevignore_overrides_gitignore(self, tmp_path):
        # .gitignore ignores all logs; .coderevignore un-ignores an important one.
        _write(tmp_path / ".gitignore", ["*.log"])
        _write(tmp_path / ".coderevignore", ["!important.log"])
        ignore = CodeRevIgnore.load(root=tmp_path, use_gitignore=True)
        assert ignore.should_ignore("debug.log") is True
        assert ignore.should_ignore("important.log") is False

    def test_missing_gitignore_is_harmless(self, tmp_path):
        _write(tmp_path / ".coderevignore", ["dist/"])
        ignore = CodeRevIgnore.load(root=tmp_path, use_gitignore=True)
        assert ignore.should_ignore("dist/app.js") is True
        assert ignore.should_ignore("src/app.js") is False

    def test_convenience_function_passes_flag(self, tmp_path, monkeypatch):
        _write(tmp_path / ".gitignore", ["coverage/"])
        # load() falls back to cwd for both files when root is not given.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert should_ignore("coverage/index.html", use_gitignore=True) is True
        assert should_ignore("coverage/index.html") is False
