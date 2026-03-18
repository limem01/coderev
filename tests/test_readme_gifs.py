from __future__ import annotations

from pathlib import Path


def test_readme_references_gif_demos() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    gif_path = "docs/gifs/coderev-cli-demo.gif"
    assert gif_path in readme

    gif_file = repo_root / gif_path
    assert gif_file.exists()

    data = gif_file.read_bytes()
    assert data[:4] == b"GIF8"
    # Sanity check: ensure we didn't commit an empty/placeholder file.
    assert len(data) > 5_000
