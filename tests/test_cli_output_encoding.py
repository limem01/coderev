"""CLI output files are written as UTF-8, whatever the locale encoding is.

``coderev batch -o`` saved its reports with ``Path.write_text(output)`` and no
encoding, so Python used the locale encoding. On Windows that is usually
cp1252, which cannot encode the markdown report's severity emoji (U+1F534 ...)
or the HTML report's check mark (U+2713): the write raised "'charmap' codec
can't encode character" and the command exited 1 with no report, even for a
single clean file. ``coderev init`` wrote ``.coderev.toml`` the same way.

The tests pin the locale encoding to cp1252 for writes that do not pass an
encoding, so they fail the same way on a UTF-8 Linux CI runner as on Windows,
and they record every such write so a new one is caught even when its content
happens to be ASCII.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from coderev.cli import main
from coderev.reviewer import CodeReviewer, ReviewResult


@pytest.fixture
def cp1252_locale(monkeypatch) -> list[Path]:
    """Make ``Path.write_text`` without an encoding behave as on cp1252 Windows.

    Returns the list of paths written without an explicit encoding.
    """
    real_write_text = Path.write_text
    defaulted: list[Path] = []

    def write_text(self, data, encoding=None, *args, **kwargs):
        if encoding is None:
            defaulted.append(self)
            encoding = "cp1252"
        return real_write_text(self, data, encoding, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)
    return defaulted


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_config():
    with patch("coderev.cli.Config") as config_cls:
        config = MagicMock()
        config.validate.return_value = []
        config_cls.load.return_value = config
        yield config


def _clean_reviewer() -> CodeReviewer:
    reviewer = CodeReviewer.__new__(CodeReviewer)
    reviewer.review_file = MagicMock(
        return_value=ReviewResult(summary="Looks good", issues=[], score=90)
    )
    return reviewer


def test_fixture_reproduces_the_windows_crash(tmp_path, cp1252_locale):
    with pytest.raises(UnicodeEncodeError):
        (tmp_path / "report.md").write_text("\U0001f534 Critical")
    assert cp1252_locale == [tmp_path / "report.md"]


@pytest.mark.parametrize(
    ("output_format", "filename", "marker"),
    [
        ("markdown", "report.md", "✅"),  # emoji in the clean-report summary
        ("html", "report.html", "✓"),  # check mark in the clean-report summary
        ("json", "report.json", None),
    ],
)
def test_batch_report_file_is_utf8(
    runner, tmp_path, mock_config, cp1252_locale, output_format, filename, marker
):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("a.py").write_text("a = 1\n", encoding="utf-8")
        with patch("coderev.cli.CodeReviewer", return_value=_clean_reviewer()):
            result = runner.invoke(
                main,
                ["batch", "a.py", "--no-parallel", "--format", output_format, "-o", filename],
            )
        raw = Path(filename).read_bytes()

    assert result.exit_code == 0, result.output
    assert "Error:" not in result.output
    assert f"Report saved to {filename}" in result.stderr
    assert cp1252_locale == []
    text = raw.decode("utf-8")  # strict: the file must be valid UTF-8
    if marker is not None:
        assert marker in text
    else:
        assert json.loads(text)["summary"]["files_reviewed"] == 1


def test_batch_markdown_report_matches_stdout_output(runner, tmp_path, mock_config, cp1252_locale):
    """The saved file holds exactly what ``--format markdown`` prints."""
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("a.py").write_text("a = 1\n", encoding="utf-8")
        with patch("coderev.cli.CodeReviewer", return_value=_clean_reviewer()):
            printed = runner.invoke(
                main, ["batch", "a.py", "--no-parallel", "--format", "markdown"]
            )
            saved = runner.invoke(
                main, ["batch", "a.py", "--no-parallel", "--format", "markdown", "-o", "r.md"]
            )
        text = Path("r.md").read_text(encoding="utf-8")

    assert printed.exit_code == 0 and saved.exit_code == 0, saved.output
    assert text.strip() == printed.stdout.strip()
    assert "\U0001f534" in text or "✅" in text


def test_init_writes_config_as_utf8(runner, tmp_path, cp1252_locale):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["init"])
        raw = Path(".coderev.toml").read_bytes()

    assert result.exit_code == 0, result.output
    assert cp1252_locale == []
    assert "[coderev]" in raw.decode("utf-8")
