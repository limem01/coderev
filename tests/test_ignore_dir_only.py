"""Regression tests for gitignore's directory-only (trailing-slash) semantics.

A pattern ending in ``/`` matches directories only, so a *regular file* of the
same name must not be ignored. ``should_ignore`` learns the leaf's type from an
explicit ``is_dir`` argument, or infers it from disk when the path exists.
"""

from pathlib import Path

from coderev.ignore import CodeRevIgnore


def test_dir_only_pattern_does_not_match_file_when_is_dir_false():
    ig = CodeRevIgnore(["build/"])
    assert ig.should_ignore("build", is_dir=False) is False


def test_dir_only_pattern_matches_directory_when_is_dir_true():
    ig = CodeRevIgnore(["build/"])
    assert ig.should_ignore("build", is_dir=True) is True


def test_dir_only_pattern_still_ignores_contents():
    ig = CodeRevIgnore(["build/"])
    # The leaf here is a file, but its ancestor 'build' is a directory, so the
    # whole subtree stays ignored regardless of the leaf's type.
    assert ig.should_ignore("build/out.o", is_dir=False) is True


def test_unknown_leaf_type_keeps_backwards_compatible_match():
    # No is_dir hint and the path does not exist on disk -> unchanged behavior.
    ig = CodeRevIgnore(["build/"])
    assert ig.should_ignore("build") is True


def test_non_dir_pattern_matches_file_regardless_of_type():
    ig = CodeRevIgnore(["*.log"])
    assert ig.should_ignore("app.log", is_dir=False) is True
    assert ig.should_ignore("app.log", is_dir=True) is True


def test_anchored_dir_only_pattern_respects_is_dir():
    ig = CodeRevIgnore(["/dist/"])
    assert ig.should_ignore("dist", is_dir=False) is False
    assert ig.should_ignore("dist", is_dir=True) is True
    # A same-named file nested deeper is not matched by the anchored pattern.
    assert ig.should_ignore("src/dist", is_dir=False) is False


def test_globstar_dir_only_pattern_respects_is_dir():
    ig = CodeRevIgnore(["**/cache/"])
    assert ig.should_ignore("a/b/cache", is_dir=False) is False
    assert ig.should_ignore("a/b/cache", is_dir=True) is True
    assert ig.should_ignore("a/b/cache/x", is_dir=False) is True


def test_is_dir_inferred_from_disk(tmp_path: Path):
    (tmp_path / "build").mkdir()
    (tmp_path / "buildfile").write_text("x")

    ig = CodeRevIgnore(["build/", "buildfile/"])
    # Real directory -> ignored; real file with a dir-only pattern -> not.
    assert ig.should_ignore(tmp_path / "build") is True
    assert ig.should_ignore(tmp_path / "buildfile") is False


def test_explicit_is_dir_overrides_disk_inference(tmp_path: Path):
    (tmp_path / "build").write_text("actually a file")
    ig = CodeRevIgnore(["build/"])
    # Caller asserts it's a file; dir-only pattern must not match.
    assert ig.should_ignore(tmp_path / "build", is_dir=False) is False
